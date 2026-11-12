"""Rapports sur n'importe quelle période : jour, semaine, mois, année ou dates choisies.

Recette constatée par service (hébergement, restaurant · bar, boutique), argent encaissé, occupation, ventes,
stock, caisses et, pour le gérant, dépenses. Chaque chiffre est comparé à la période d'avant de même longueur.
Rien n'est compté deux fois : un plat ou une boisson « sur la chambre » est un extra de la note, pas une vente.
"""
from collections import OrderedDict
from datetime import date, datetime, timedelta

from django.db.models import F, Sum
from django.utils import timezone

from caisse.models import Encaissement, SessionCaisse, SortieCaisse, VenteComptoir, totaux_par_moyen
from core.utils import aujourd_hui, mois_suivant
from hotel.models import Chambre, Extra, Nuitee, Sejour
from stock.models import MouvementStock

SERVICES = [("HEBERGEMENT", "Hébergement"), ("RESTAURANT_BAR", "Restaurant · Bar"), ("BOUTIQUE", "Boutique")]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
        "décembre"]
JOURS_COURTS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]

PERIODES = [("jour", "Aujourd'hui"), ("hier", "Hier"), ("semaine", "Cette semaine"), ("semaine_derniere", "Semaine dernière"),
            ("mois", "Ce mois"), ("mois_dernier", "Mois dernier"), ("annee", "Cette année")]


# --- Périodes ------------------------------------------------------------------------------------------------
def periode(cle, du=None, au=None):
    """(début, fin) inclus pour un raccourci, ou les dates choisies."""
    j = aujourd_hui()
    lundi = j - timedelta(days=j.weekday())
    if cle == "hier":
        return j - timedelta(days=1), j - timedelta(days=1)
    if cle == "semaine":
        return lundi, lundi + timedelta(days=6)
    if cle == "semaine_derniere":
        return lundi - timedelta(days=7), lundi - timedelta(days=1)
    if cle == "mois":
        return j.replace(day=1), mois_suivant(j.replace(day=1)) - timedelta(days=1)
    if cle == "mois_dernier":
        debut = (j.replace(day=1) - timedelta(days=1)).replace(day=1)
        return debut, j.replace(day=1) - timedelta(days=1)
    if cle == "annee":
        return date(j.year, 1, 1), date(j.year, 12, 31)
    if cle == "dates" and du and au:
        return (du, au) if du <= au else (au, du)
    return j, j


def periode_precedente(debut, fin):
    """La période d'avant, de même nature : le mois d'avant pour un mois entier, l'année d'avant pour une année."""
    if debut.day == 1 and fin == mois_suivant(debut) - timedelta(days=1):
        avant = (debut - timedelta(days=1)).replace(day=1)
        return avant, debut - timedelta(days=1)
    if (debut.month, debut.day, fin.month, fin.day) == (1, 1, 12, 31) and debut.year == fin.year:
        return date(debut.year - 1, 1, 1), date(debut.year - 1, 12, 31)
    duree = (fin - debut).days + 1
    return debut - timedelta(days=duree), debut - timedelta(days=1)


def libelle_periode(debut, fin):
    if debut == fin:
        return f"{JOURS_COURTS[debut.weekday()].rstrip('.').capitalize()} {debut.day} {MOIS[debut.month - 1]} {debut.year}"
    if debut.day == 1 and fin == mois_suivant(debut) - timedelta(days=1):
        return f"{MOIS[debut.month - 1].capitalize()} {debut.year}"
    if (debut.month, debut.day, fin.month, fin.day) == (1, 1, 12, 31) and debut.year == fin.year:
        return f"Année {debut.year}"
    return f"Du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"


def _bornes(debut, fin):
    return (timezone.make_aware(datetime.combine(debut, datetime.min.time())),
            timezone.make_aware(datetime.combine(fin + timedelta(days=1), datetime.min.time())))


def _service_article(categorie):
    return "BOUTIQUE" if categorie == "BOUTIQUE" else "RESTAURANT_BAR"


def _service_extra(source):
    return {"BOUTIQUE": "BOUTIQUE", "BAR": "RESTAURANT_BAR", "RESTAURANT": "RESTAURANT_BAR"}.get(source, "HEBERGEMENT")


# --- Les chiffres ------------------------------------------------------------------------------------------------
def chiffres(debut, fin, finances=False):
    """Tout ce que le rapport affiche pour une période (dates incluses)."""
    t0, t1 = _bornes(debut, fin)
    nb_jours = (fin - debut).days + 1
    par_mois = nb_jours > 62
    if par_mois:
        seaux, m = [], debut.replace(day=1)
        while m <= fin:
            seaux.append(m)
            m = mois_suivant(m)
        cle = lambda d: d.replace(day=1)  # noqa: E731
    else:
        seaux = [debut + timedelta(days=i) for i in range(nb_jours)]
        cle = lambda d: d  # noqa: E731
    recettes = OrderedDict((s, {k: 0 for k, _ in SERVICES}) for s in seaux)

    nuitees = Nuitee.objects.filter(date_nuit__gte=debut, date_nuit__lte=fin)
    for jour, montant in nuitees.values_list("date_nuit", "montant"):
        recettes[cle(jour)]["HEBERGEMENT"] += montant
    for quand, source, montant in (Extra.objects.filter(statut=Extra.Statut.ACTIF, date_conso__gte=t0, date_conso__lt=t1)
                                   .values_list("date_conso", "source", "montant")):
        recettes[cle(timezone.localtime(quand).date())][_service_extra(source)] += montant
    ventes = VenteComptoir.objects.filter(annulee=False, journee__gte=debut, journee__lte=fin)
    payantes = ventes.exclude(reglement=VenteComptoir.Reglement.OFFERT).exclude(
        reglement=VenteComptoir.Reglement.CREDIT, sejour__isnull=False)  # sur la chambre : déjà un extra
    for jour, categorie, montant in payantes.values_list("journee", "article__categorie", "montant"):
        recettes[cle(jour)][_service_article(categorie)] += montant

    par_service = {k: sum(r[k] for r in recettes.values()) for k, _ in SERVICES}
    total = sum(par_service.values())
    nb_nuitees = nuitees.count()
    recette_chambres = par_service["HEBERGEMENT"]
    capacite = Chambre.objects.filter(active=True).count() * nb_jours
    encaissements = Encaissement.objects.filter(date__gte=t0, date__lt=t1)
    encaisse = encaissements.aggregate(s=Sum("montant_signe"))["s"] or 0

    meilleurs = (ventes.exclude(reglement=VenteComptoir.Reglement.OFFERT).values("article__nom", "article__code",
                                                                                 "article__categorie")
                 .annotate(quantite=Sum("quantite"), montant=Sum("montant")).order_by("-montant")[:10])
    mouvements = MouvementStock.objects.filter(journee__gte=debut, journee__lte=fin)

    def stock(type_, valeur):
        qs = mouvements.filter(type=type_)
        return {"quantite": abs(qs.aggregate(s=Sum("quantite"))["s"] or 0), "nombre": qs.count(),
                "valeur": abs(qs.aggregate(s=Sum(valeur))["s"] or 0)}

    sessions = SessionCaisse.objects.filter(remise_le__gte=t0, remise_le__lt=t1, est_rectificative=False)
    caissiers = {}
    for ligne in (encaissements.values("utilisateur__username", "utilisateur__first_name", "utilisateur__last_name")
                  .annotate(s=Sum("montant_signe"))):
        identifiant = ligne["utilisateur__username"]
        nom = f"{ligne['utilisateur__first_name']} {ligne['utilisateur__last_name']}".strip() or identifiant
        caissiers.setdefault(identifiant, {"nom": nom, "encaisse": 0, "sessions": 0, "ecart": 0,
                                           "ecarts": 0})["encaisse"] += ligne["s"] or 0
    for s in sessions.select_related("receptionniste", "remise"):
        ligne = caissiers.setdefault(s.receptionniste.username, {"nom": str(s.receptionniste), "encaisse": 0,
                                                                 "sessions": 0, "ecart": 0, "ecarts": 0})
        ligne["sessions"] += 1
        ecart = getattr(getattr(s, "remise", None), "ecart", 0) or 0
        ligne["ecart"] += ecart
        ligne["ecarts"] += 1 if abs(ecart) > s.seuil_ecart else 0

    donnees = {
        "debut": debut, "fin": fin, "nb_jours": nb_jours, "par_mois": par_mois,
        "recettes": recettes, "par_service": par_service, "total": total, "encaisse": encaisse,
        "nb_nuitees": nb_nuitees, "capacite": capacite,
        "occupation": round(100 * nb_nuitees / capacite, 1) if capacite else 0,
        "prix_moyen": round(recette_chambres / nb_nuitees) if nb_nuitees else 0,
        "revpar": round(recette_chambres / capacite) if capacite else 0,
        "moyens": [m for m in totaux_par_moyen(encaissements) if m["montant"] or m["cle"] not in ("CARTE", "CHEQUE")],
        "meilleurs": list(meilleurs),
        "offres": ventes.filter(reglement=VenteComptoir.Reglement.OFFERT).aggregate(s=Sum("montant"))["s"] or 0,
        "stock": {
            "livraisons": stock(MouvementStock.Type.ENTREE, F("quantite") * F("cout_unitaire")),
            "ventes": stock(MouvementStock.Type.VENTE, F("quantite") * F("article__prix_vente")),
            "casse": stock(MouvementStock.Type.AVARIE, F("quantite") * F("article__prix_achat")),
            "manquants": _manquants(mouvements),
        },
        "caissiers": sorted(caissiers.values(), key=lambda c: -c["encaisse"]),
        "arrivees": Sejour.objects.filter(check_in_le__gte=t0, check_in_le__lt=t1).count(),
        "departs": Sejour.objects.filter(check_out_le__gte=t0, check_out_le__lt=t1).count(),
        "remises": sessions.count(),
    }
    if finances:
        from finances.models import Depense

        depenses = Depense.objects.filter(date__gte=debut, date__lte=fin)
        tiroir = SortieCaisse.objects.filter(type=SortieCaisse.Type.DEPENSE, date__gte=t0, date__lt=t1).exclude(
            statut=SortieCaisse.Statut.REFUSEE).aggregate(s=Sum("montant"))["s"] or 0
        par_categorie = [{"libelle": Depense.Categorie(c["categorie"]).label, "montant": c["total"]}
                         for c in depenses.values("categorie").annotate(total=Sum("montant")).order_by("-total")]
        if tiroir:
            par_categorie.append({"libelle": "Petites dépenses payées à la caisse", "montant": tiroir})
            par_categorie.sort(key=lambda c: -c["montant"])
        donnees["depenses"] = {"total": sum(c["montant"] for c in par_categorie), "par_categorie": par_categorie}
    return donnees


def _manquants(mouvements):
    """Manquants constatés aux inventaires (pas le premier comptage d'un article)."""
    qs = mouvements.filter(type=MouvementStock.Type.INVENTAIRE, quantite__lt=0)
    return {"quantite": -(qs.aggregate(s=Sum("quantite"))["s"] or 0), "nombre": qs.count(),
            "valeur": -(qs.aggregate(s=Sum(F("quantite") * F("cout_unitaire")))["s"] or 0)}


# --- Mise en forme pour l'écran ------------------------------------------------------------------------------------
def evolution(actuel, precedent):
    """Variation en % par rapport à la période d'avant (None si rien avant)."""
    if not precedent:
        return None
    return round(100 * (actuel - precedent) / abs(precedent))


def graduations(maximum, nb=4):
    """Des repères ronds pour l'axe : 0, 50 k, 100 k…"""
    if maximum <= 0:
        return 1, [0]
    brut = maximum / nb
    puissance = 10 ** (len(str(int(brut))) - 1)
    pas = next(p * puissance for p in (1, 2, 2.5, 5, 10) if p * puissance >= brut)
    haut = pas * -(-maximum // pas)
    return haut, [round(pas * i) for i in range(int(haut // pas) + 1)]


def compact(n):
    """150000 → « 150 k » ; 2 500 000 → « 2,5 M »."""
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " M"
    if abs(n) >= 1000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " k"
    return str(int(n))


def colonnes(donnees):
    """Les colonnes empilées du graphique : une par jour (ou par mois), une part par service."""
    maximum = max([sum(v.values()) for v in donnees["recettes"].values()] + [0])
    haut, reperes = graduations(maximum)
    sortie = []
    n = len(donnees["recettes"])
    etiquette_tous = 1 if n <= 14 else (2 if n <= 31 else 3)
    for i, (seau, valeurs) in enumerate(donnees["recettes"].items()):
        total = sum(valeurs.values())
        if donnees["par_mois"]:
            titre, court = f"{MOIS[seau.month - 1].capitalize()} {seau.year}", MOIS_COURTS[seau.month - 1]
        else:
            titre = f"{JOURS_COURTS[seau.weekday()].capitalize()} {seau.day} {MOIS[seau.month - 1]}"
            court = f"{seau.day}" if n > 7 else f"{JOURS_COURTS[seau.weekday()]} {seau.day}"
        parts = [{"cle": k, "libelle": l, "montant": valeurs[k], "part": round(100 * valeurs[k] / total, 2) if total else 0,
                  "rang": rang} for rang, (k, l) in enumerate(SERVICES)]
        sortie.append({"titre": titre, "court": court, "total": total, "hauteur": round(100 * total / haut, 2),
                       "parts": [p for p in reversed(parts) if p["montant"]], "toutes": parts,
                       "etiquette": i % etiquette_tous == 0, "aujourdhui": seau == aujourd_hui() and not donnees["par_mois"]})
    return {"colonnes": sortie, "reperes": [{"valeur": r, "texte": compact(r), "position": round(100 * r / haut, 2)}
                                            for r in reperes]}


def barres(lignes, cle="montant"):
    """Barres horizontales classées : largeur proportionnelle au plus grand."""
    maximum = max([l[cle] for l in lignes] + [0])
    total = sum(l[cle] for l in lignes)
    return [{**l, "largeur": round(100 * l[cle] / maximum, 2) if maximum > 0 else 0,
             "part": round(100 * l[cle] / total) if total else 0} for l in lignes]


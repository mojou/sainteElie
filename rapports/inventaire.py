"""Rapport d'inventaire et de rentabilité, sur n'importe quelle période.

Pour chaque article : stock au début et à la fin, livraisons, ventes, offerts, casse, sorties internes, écarts
d'inventaire ; son coût d'achat (coût moyen), son prix de vente, sa marge et ses taux. Puis, pour tout l'hôtel : le
chiffre d'affaires par service, le coût de ce qui a été vendu, la marge brute, les pertes, les charges (dépenses,
petites dépenses de caisse, salaires) et le résultat ; enfin tout ce qui s'est passé dans l'application.

Règles de calcul (écrites ici pour que le gérant puisse les vérifier) :
- Chiffre d'affaires d'un article = ses ventes payées ou à crédit (chambre ou client) ; l'offert n'en fait pas partie.
- Coût des marchandises vendues = quantité vendue × coût moyen d'achat de l'article (son coût actuel).
- Marge = chiffre d'affaires − coût. Taux de marque = marge ÷ prix de vente. Coefficient = prix de vente ÷ coût.
- Un article sans prix d'achat noté n'a pas de marge calculée : il est signalé, jamais compté à 100 %.
- Les plats n'ont pas de stock ; leur coût de revient se note, si on le connaît, dans le prix d'achat de l'article.
- Le résultat de gestion = recettes − dépenses enregistrées − petites dépenses de caisse − salaires bruts (au prorata
  des jours de la période). Comme au bilan du mois, les achats de marchandises comptent quand ils sont notés en dépenses.
"""
import calendar
from collections import Counter, OrderedDict, defaultdict
from datetime import timedelta

from django.db.models import Count, Sum

from caisse.models import Encaissement, SessionCaisse, SortieCaisse, VenteComptoir
from hotel.models import Extra, Sejour
from stock.models import Article, MouvementStock

from . import services

T = MouvementStock.Type


def _taux(part, total):
    return round(100 * part / total, 1) if total else None


def _stocks(debut, fin):
    """Stock au début et à la fin de la période, pour chaque article.

    Stock à la fin d'un jour = stock d'aujourd'hui − tout ce qui a bougé après ce jour. Le calcul ne dépend ni de
    l'heure des mouvements (une horloge d'ordinateur peut être fausse) ni de l'ordre de saisie.
    """
    actuel = dict(Article.objects.filter(suivi_stock=True).values_list("pk", "quantite"))
    apres_fin = dict(MouvementStock.objects.filter(journee__gt=fin).values("article").annotate(s=Sum("quantite"))
                     .values_list("article", "s"))
    depuis_debut = dict(MouvementStock.objects.filter(journee__gte=debut).values("article").annotate(s=Sum("quantite"))
                        .values_list("article", "s"))
    return ({pk: q - depuis_debut.get(pk, 0) for pk, q in actuel.items()},
            {pk: q - apres_fin.get(pk, 0) for pk, q in actuel.items()})


def articles(debut, fin):
    """Une ligne par article qui a bougé ou qui a du stock : quantités, prix, coût, marge et taux."""
    from django.db.models import Min

    from core.utils import aujourd_hui

    stock_debut, stock_fin = _stocks(debut, fin)
    # Jours réellement écoulés et suivis : une période pas finie, ou un article arrivé en cours de route, ne compte
    # que ses vrais jours de vente (sinon « 150 jours de stock » pour une bière qui part à 2 par jour).
    dernier_jour = min(fin, aujourd_hui())
    premiers = dict(MouvementStock.objects.values("article").annotate(d=Min("journee")).values_list("article", "d"))
    mouvements = defaultdict(Counter)
    entrees_valeur = Counter()
    for article, type_, quantite, cout in (MouvementStock.objects.filter(journee__gte=debut, journee__lte=fin)
                                           .values_list("article_id", "type", "quantite", "cout_unitaire")):
        if type_ == T.INVENTAIRE:
            mouvements[article]["ecart"] += quantite
            continue
        mouvements[article][type_] += abs(quantite)
        if type_ == T.ENTREE:
            entrees_valeur[article] += quantite * cout
    # Le premier comptage d'un article (stock de départ à zéro) n'est pas un écart.
    for m in MouvementStock.objects.filter(journee__gte=debut, journee__lte=fin, type=T.INVENTAIRE, quantite__gt=0).only(
            "article_id", "quantite", "quantite_apres"):
        if m.quantite == m.quantite_apres:
            mouvements[m.article_id]["ecart"] -= m.quantite
            mouvements[m.article_id]["premier_comptage"] += m.quantite
    ventes = defaultdict(Counter)
    for article, reglement, quantite, montant in (VenteComptoir.objects.filter(
            annulee=False, journee__gte=debut, journee__lte=fin)
            .values_list("article_id", "reglement").annotate(q=Sum("quantite"), m=Sum("montant"))
            .values_list("article_id", "reglement", "q", "m")):
        cle = "offert" if reglement == VenteComptoir.Reglement.OFFERT else "vendu"
        ventes[article][cle + "_qte"] += quantite
        ventes[article][cle + "_montant"] += montant
    ids = set(mouvements) | set(ventes) | {a for a, q in stock_fin.items() if q}
    lignes = []
    for a in Article.objects.filter(pk__in=ids).order_by("categorie", "ordre", "nom"):
        mv, v = mouvements[a.pk], ventes[a.pk]
        cout = a.prix_achat or 0
        ca, qte = v["vendu_montant"], v["vendu_qte"]
        avec_cout = bool(cout)
        cmv = qte * cout if avec_cout else None
        marge = ca - cmv if avec_cout else None
        fin_q = stock_fin.get(a.pk, 0) if a.suivi_stock else None
        jours_suivis = (dernier_jour - max(debut, premiers.get(a.pk, debut))).days + 1
        vitesse = qte / max(jours_suivis, 1) if qte else 0
        lignes.append({
            "article": a, "categorie": a.get_categorie_display(), "suivi": a.suivi_stock, "avec_cout": avec_cout,
            "debut": stock_debut.get(a.pk, 0) if a.suivi_stock else None, "fin": fin_q,
            "entrees": mv[T.ENTREE], "entrees_valeur": entrees_valeur[a.pk], "premier_comptage": mv["premier_comptage"],
            "vendu": qte, "ca": ca, "offert": v["offert_qte"], "offert_vente": v["offert_montant"],
            "offert_cout": v["offert_qte"] * cout, "pertes": mv[T.AVARIE], "pertes_valeur": mv[T.AVARIE] * cout,
            "sorties": mv[T.SORTIE], "sorties_valeur": mv[T.SORTIE] * cout, "retours": mv[T.RETOUR],
            # sorti du stock par la vente (vendu + offert), net des ventes annulées : c'est ce que compte l'inventaire
            "sorti_vente": mv[T.VENTE] - mv[T.RETOUR],
            "ecart": mv["ecart"], "ecart_valeur": mv["ecart"] * cout,
            "cout": cout, "prix": a.prix_vente, "marge_unitaire": a.prix_vente - cout if avec_cout else None,
            "taux_marque": _taux(a.prix_vente - cout, a.prix_vente) if avec_cout else None,
            "coefficient": round(a.prix_vente / cout, 2) if avec_cout else None,
            "cmv": cmv, "marge": marge,
            "valeur_fin": (fin_q or 0) * cout if a.suivi_stock else 0,
            "valeur_fin_vente": (fin_q or 0) * a.prix_vente if a.suivi_stock else 0,
            "valeur_debut": (stock_debut.get(a.pk, 0) or 0) * cout if a.suivi_stock else 0,
            "jours_de_stock": int(fin_q / vitesse) if a.suivi_stock and vitesse and fin_q else None,
        })
    ca_total = sum(l["ca"] for l in lignes)
    for l in lignes:
        l["part_ca"] = _taux(l["ca"], ca_total)
    return lignes


def _somme(lignes, champ):
    return sum(l[champ] or 0 for l in lignes)


def par_categorie(lignes):
    groupes = OrderedDict()
    for l in lignes:
        groupes.setdefault(l["categorie"], []).append(l)
    total_ca = _somme(lignes, "ca")
    sortie = []
    for nom, liste in groupes.items():
        avec_cout = [l for l in liste if l["avec_cout"]]
        ca_avec_cout = _somme(avec_cout, "ca")
        marge = _somme(avec_cout, "marge")
        sortie.append({
            "nom": nom, "lignes": liste, "ca": _somme(liste, "ca"), "vendu": _somme(liste, "vendu"),
            "cmv": _somme(avec_cout, "cmv"), "marge": marge, "taux_marque": _taux(marge, ca_avec_cout),
            "part_ca": _taux(_somme(liste, "ca"), total_ca), "sans_cout": sum(1 for l in liste if not l["avec_cout"] and l["vendu"]),
            "valeur_debut": _somme(liste, "valeur_debut"), "valeur_fin": _somme(liste, "valeur_fin"),
            "valeur_fin_vente": _somme(liste, "valeur_fin_vente"), "entrees_valeur": _somme(liste, "entrees_valeur"),
            "pertes_valeur": _somme(liste, "pertes_valeur"), "ecart_valeur": _somme(liste, "ecart_valeur"),
            "offert_cout": _somme(liste, "offert_cout"), "offert_vente": _somme(liste, "offert_vente"),
        })
    return sortie


def salaires(debut, fin):
    """Salaires bruts (base + primes + heures sup) des fiches validées, au prorata des jours de la période."""
    from paie.models import FichePaie

    total, mois_vus = 0, set()
    for f in FichePaie.objects.exclude(statut=FichePaie.Statut.BROUILLON).filter(
            mois__lte=fin, mois__gte=debut.replace(day=1)):
        jours_mois = calendar.monthrange(f.mois.year, f.mois.month)[1]
        fin_mois = f.mois + timedelta(days=jours_mois - 1)
        communs = (min(fin, fin_mois) - max(debut, f.mois)).days + 1
        if communs > 0:
            total += round((f.salaire_base + f.primes + f.heures_sup) * communs / jours_mois)
            mois_vus.add(f.mois)
    return total, sorted(mois_vus)


def activites(debut, fin):
    """Tout ce qui s'est passé dans l'application pendant la période, en nombres."""
    from core.models import JournalAction
    from personnel.models import Affectation, DemandeConge, Pointage
    from postes.models import Intervention
    from vitrine.models import DemandeReservation

    t0, t1 = services._bornes(debut, fin)
    ventes = VenteComptoir.objects.filter(journee__gte=debut, journee__lte=fin)
    annulees = ventes.filter(annulee=True)
    encaissements = Encaissement.objects.filter(date__gte=t0, date__lt=t1)
    annulations = encaissements.filter(nature=Encaissement.Nature.ANNULATION)
    sessions = SessionCaisse.objects.filter(est_rectificative=False)
    mouvements = MouvementStock.objects.filter(journee__gte=debut, journee__lte=fin)
    demandes = DemandeReservation.objects.filter(cree_le__gte=t0, cree_le__lt=t1)
    return [
        ("Hébergement", [
            ("Réservations enregistrées", Sejour.objects.filter(cree_le__gte=t0, cree_le__lt=t1).count()),
            ("Arrivées", Sejour.objects.filter(check_in_le__gte=t0, check_in_le__lt=t1).count()),
            ("Départs", Sejour.objects.filter(check_out_le__gte=t0, check_out_le__lt=t1).count()),
            ("Réservations annulées ou clients pas venus", Sejour.objects.filter(
                statut__in=[Sejour.Statut.ANNULE, Sejour.Statut.NO_SHOW], date_arrivee__gte=debut,
                date_arrivee__lte=fin).count()),
            ("Réservations en ligne reçues", demandes.count()),
            ("… confirmées", demandes.filter(statut=DemandeReservation.Statut.CONFIRMEE).count()),
            ("Extras portés sur les notes", Extra.objects.filter(date_conso__gte=t0, date_conso__lt=t1,
                                                                statut=Extra.Statut.ACTIF).count()),
        ]),
        ("Ventes et caisses", [
            ("Reçus de vente", encaissements.filter(nature=Encaissement.Nature.VENTE).count()),
            ("Articles vendus", ventes.filter(annulee=False).exclude(reglement="OFFERT").aggregate(s=Sum("quantite"))["s"] or 0),
            ("Articles offerts", ventes.filter(annulee=False, reglement="OFFERT").aggregate(s=Sum("quantite"))["s"] or 0),
            ("Ventes annulées", f"{annulees.count()} ({services.compact(annulees.aggregate(s=Sum('montant'))['s'] or 0)} FCFA)"),
            ("Paiements reçus", encaissements.exclude(nature=Encaissement.Nature.ANNULATION).count()),
            ("Paiements annulés", f"{annulations.count()} ({services.compact(-(annulations.aggregate(s=Sum('montant_signe'))['s'] or 0))} FCFA)"),
            ("Caisses ouvertes", sessions.filter(ouverte_le__gte=t0, ouverte_le__lt=t1).count()),
            ("Caisses fermées", sessions.filter(remise_le__gte=t0, remise_le__lt=t1).count()),
            ("Sorties d'argent de la caisse", SortieCaisse.objects.filter(date__gte=t0, date__lt=t1).count()),
        ]),
        ("Stock", [
            ("Livraisons reçues", mouvements.filter(type=T.ENTREE).count()),
            ("Comptages d'inventaire", mouvements.filter(type=T.INVENTAIRE).count()),
            ("Casse ou périmé", mouvements.filter(type=T.AVARIE).count()),
            ("Sorties pour l'hôtel", mouvements.filter(type=T.SORTIE).count()),
        ]),
        ("Personnel et entretien", [
            ("Créneaux au planning", Affectation.objects.filter(date__gte=debut, date__lte=fin).count()),
            ("Pointages", Pointage.objects.filter(date__gte=debut, date__lte=fin).count()),
            ("Demandes de congé", DemandeConge.objects.filter(cree_le__gte=t0, cree_le__lt=t1).count()),
            ("Pannes signalées", Intervention.objects.filter(signale_le__gte=t0, signale_le__lt=t1).count()),
            ("Pannes réparées", Intervention.objects.filter(traite_le__gte=t0, traite_le__lt=t1,
                                                           statut=Intervention.Statut.FAITE).count()),
        ]),
        ("Journal de l'application", [
            (action, n) for action, n in JournalAction.objects.filter(date__gte=t0, date__lt=t1).values_list("action")
            .annotate(n=Count("id")).order_by("-n")[:8]]),
    ]


def rapport(debut, fin, finances=False):
    """Tout le rapport : synthèse, services, articles, stock, pertes, charges, résultat, activités."""
    c = services.chiffres(debut, fin, finances=finances)
    lignes = articles(debut, fin)
    categories = par_categorie(lignes)
    avec_cout = [l for l in lignes if l["avec_cout"]]
    ca_marchandises = _somme(lignes, "ca")
    ca_avec_cout = _somme(avec_cout, "ca")
    cmv = _somme(avec_cout, "cmv")
    marge = _somme(avec_cout, "marge")
    pertes = _somme(lignes, "pertes_valeur")
    ecarts = _somme(lignes, "ecart_valeur")
    offerts_cout = _somme(lignes, "offert_cout")
    marge_nette_marchandises = marge - pertes + min(ecarts, 0) - offerts_cout
    t0, t1 = services._bornes(debut, fin)
    # Extras saisis à la main (sans passer par la caisse) : recette sans article.
    extras_manuels = (Extra.objects.filter(statut=Extra.Statut.ACTIF, date_conso__gte=t0, date_conso__lt=t1)
                      .exclude(pk__in=VenteComptoir.objects.filter(extra__isnull=False).values("extra"))
                      .aggregate(s=Sum("montant"))["s"] or 0)
    d = {
        "c": c, "lignes": lignes, "categories": categories, "ca_marchandises": ca_marchandises,
        "ca_avec_cout": ca_avec_cout, "cmv": cmv, "marge": marge, "taux_marque": _taux(marge, ca_avec_cout),
        "coefficient": round(ca_avec_cout / cmv, 2) if cmv else None, "pertes": pertes, "ecarts": ecarts,
        "offerts_cout": offerts_cout, "offerts_vente": _somme(lignes, "offert_vente"),
        "marge_nette_marchandises": marge_nette_marchandises,
        "taux_pertes": _taux(pertes - min(ecarts, 0), cmv),
        "sans_cout": [l for l in lignes if not l["avec_cout"] and l["vendu"]],
        "valeur_debut": _somme(lignes, "valeur_debut"), "valeur_fin": _somme(lignes, "valeur_fin"),
        "valeur_fin_vente": _somme(lignes, "valeur_fin_vente"), "livraisons": _somme(lignes, "entrees_valeur"),
        "extras_manuels": extras_manuels,
        "services": [{"libelle": l, "montant": c["par_service"][k], "part": _taux(c["par_service"][k], c["total"]), "rang": i}
                     for i, (k, l) in enumerate(services.SERVICES)],
        "activites": activites(debut, fin),
        "nb_jours": (fin - debut).days + 1,
    }
    if finances:
        sal, mois = salaires(debut, fin)
        dep = c["depenses"]
        charges = dep["total"] + sal
        resultat = c["total"] - charges
        d.update({
            "salaires": sal, "mois_salaires": mois, "charges": charges, "resultat": resultat,
            "taux_resultat": _taux(resultat, c["total"]), "part_charges": _taux(charges, c["total"]),
            "part_salaires": _taux(sal, c["total"]),
            "depenses": [{**x, "part": _taux(x["montant"], c["total"])} for x in dep["par_categorie"]],
            "prelevements": SortieCaisse.objects.filter(type=SortieCaisse.Type.PRELEVEMENT, date__gte=t0, date__lt=t1)
            .exclude(statut=SortieCaisse.Statut.REFUSEE).aggregate(s=Sum("montant"))["s"] or 0,
            "achats_notes": sum(x["montant"] for x in dep["par_categorie"]
                                if x["libelle"] in ("Alimentation et boissons", "Fournitures et achats")),
        })
    return d


def avertissements(d, debut, fin, finances):
    """Ce qui rend un chiffre incomplet : dit en tête du rapport, plutôt qu'un résultat faussement beau."""
    from datetime import date

    from paie.models import FichePaie

    notes = []
    if d["sans_cout"]:
        noms = ", ".join(str(l["article"]) for l in d["sans_cout"][:6]) + (" …" if len(d["sans_cout"]) > 6 else "")
        notes.append(f"{len(d['sans_cout'])} article(s) vendu(s) sans prix d'achat noté : leur marge n'est pas "
                     f"calculée ({noms}). Notez le prix d'achat à la prochaine livraison, ou dans la fiche de l'article.")
    if not MouvementStock.objects.filter(type=T.INVENTAIRE, journee__gte=debut, journee__lte=fin).exists():
        notes.append("Aucun inventaire compté sur la période : le stock de fin est celui que l'application calcule, "
                     "pas celui compté. Faites un inventaire pour vérifier.")
    if finances:
        mois, m = [], debut.replace(day=1)
        while m <= fin:
            mois.append(m)
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        sans_paie = [m for m in mois if not FichePaie.objects.filter(mois=m).exclude(
            statut=FichePaie.Statut.BROUILLON).exists()]
        if sans_paie:
            notes.append("Salaires non comptés pour " + ", ".join(f"{services.MOIS[m.month - 1]} {m.year}" for m in sans_paie)
                         + " : aucune fiche de paie validée. Le résultat est donc trop élevé.")
        if not d["c"]["depenses"]["total"]:
            notes.append("Aucune dépense notée sur la période : le résultat ne tient compte d'aucune charge.")
    return notes

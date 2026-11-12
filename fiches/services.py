"""
Calcul des fiches journalières, avec les mêmes colonnes que les fiches papier de l'hôtel.

Une « journée » est celle de l'ouverture des sessions de caisse : le réceptionniste de nuit qui ouvre
à 23 h reste sur la fiche du jour, même pour une vente faite après minuit.

R1, R2, R3 (fiche boutique) : les réceptionnistes du jour, dans l'ordre de leur prise de service.
"""
from datetime import datetime, timedelta

from django.db.models import Sum
from django.utils import timezone

from caisse.models import Encaissement, SessionCaisse, Tiroir, VenteComptoir
from core.utils import premier_du_mois
from hotel.models import Chambre, Extra, Sejour
from stock.models import Article, MouvementStock

NB_COLONNES_RECEPTIONNISTES = 3  # R1, R2, R3 comme sur la fiche papier ; R4… s'ajoutent si besoin


def poste_de(categorie):
    """La boutique se vend à la réception ; le bar et le restaurant, au bar."""
    return Tiroir.Poste.RECEPTION if categorie == Article.Categorie.BOUTIQUE else Tiroir.Poste.BAR


def debut_journee(jour):
    return timezone.make_aware(datetime.combine(jour, datetime.min.time()))


def _sessions_du_jour(jour, poste=None):
    sessions = (SessionCaisse.objects.filter(est_rectificative=False, ouverte_le__gte=debut_journee(jour),
                                             ouverte_le__lt=debut_journee(jour + timedelta(days=1)))
                .select_related("receptionniste").order_by("ouverte_le"))
    return sessions.filter(tiroir__poste=poste) if poste else sessions


def receptionnistes_ordonnes(jour, poste=None):
    """Personnes du poste dans l'ordre de leur prise de service : la première est R1, la deuxième R2…"""
    ordre = []
    for s in _sessions_du_jour(jour, poste):
        if s.receptionniste not in ordre:
            ordre.append(s.receptionniste)
    return ordre


def colonnes_receptionnistes(jour, poste=None):
    """[{"code": "R1", "nom": "Aïcha Moussa"}, …], au moins trois colonnes comme sur la fiche."""
    personnes = receptionnistes_ordonnes(jour, poste)
    nb = max(NB_COLONNES_RECEPTIONNISTES, len(personnes))
    return [{"code": f"R{i + 1}", "personne": personnes[i] if i < len(personnes) else None,
             "nom": str(personnes[i]) if i < len(personnes) else "-"} for i in range(nb)]


def receptionnistes_du_jour(jour, poste=None):
    noms = []
    for s in _sessions_du_jour(jour, poste):
        nom = f"{s.receptionniste} ({s.get_shift_display()})"
        if nom not in noms:
            noms.append(nom)
    return noms


# --- Main courante bar / boutique -----------------------------------------------------------
def main_courante(jour, categorie, sessions=None):
    """Ventes du jour regroupées par article ; `sessions` limite à certains réceptionnistes."""
    ventes = (VenteComptoir.objects.filter(journee=jour, annulee=False, article__categorie=categorie)
              .select_related("article", "sejour__chambre", "sejour__client", "client", "encaissement")
              .order_by("date"))
    if sessions is not None:
        ventes = ventes.filter(session__in=sessions)
    lignes = {}
    for v in ventes:
        ligne = lignes.setdefault(v.article_id, {"article": v.article, "quantite": 0, "cash": 0, "credit": 0,
                                                 "offre": 0, "total": 0, "obs": []})
        ligne["quantite"] += v.quantite
        ligne["total"] += v.montant
        cle = {"COMPTANT": "cash", "CREDIT": "credit", "OFFERT": "offre"}[v.reglement]
        ligne[cle] += v.montant
        if v.reglement == "CREDIT":
            ligne["obs"].append(f"crédit {v.beneficiaire}")
        elif v.reglement == "OFFERT":
            ligne["obs"].append(f"offert : {v.observation}")
        else:
            if v.encaissement_id and v.encaissement.mode in Encaissement.MODES_MOBILE:
                ligne["obs"].append(f"{v.encaissement.moyen_libelle} {v.montant:,}".replace(",", " "))
            if v.observation:
                ligne["obs"].append(v.observation)
    lignes = sorted(lignes.values(), key=lambda x: (x["article"].ordre, x["article"].nom))
    totaux = {k: sum(x[k] for x in lignes) for k in ("quantite", "cash", "credit", "offre", "total")}
    return {"lignes": lignes, "totaux": totaux}


# --- Fiches de stock --------------------------------------------------------------------------
def fiche_stock(jour, categorie):
    articles = list(Article.objects.filter(categorie=categorie).order_by("ordre", "nom"))
    avant = dict(MouvementStock.objects.filter(article__categorie=categorie, journee__lt=jour)
                 .values_list("article").annotate(s=Sum("quantite")))
    du_jour = {}
    for article_id, type_, total in (MouvementStock.objects.filter(article__categorie=categorie, journee=jour)
                                     .values_list("article", "type").annotate(s=Sum("quantite"))):
        du_jour.setdefault(article_id, {})[type_] = total
    colonnes = colonnes_receptionnistes(jour, poste_de(categorie))
    rang = {c["personne"].pk: i for i, c in enumerate(colonnes) if c["personne"]}
    moyens = {libelle: 0 for mode, libelle in Encaissement.Mode.choices if mode in Encaissement.MODES_COMPTOIR}

    def vide():
        return {"releves": [0] * len(colonnes), "quantite": 0, "montant": 0, "credit": 0, "offre": 0, "comptant": 0}

    ventes = {}
    mobile_money = 0
    for v in (VenteComptoir.objects.filter(journee=jour, annulee=False, article__categorie=categorie)
              .select_related("session", "encaissement")):
        d = ventes.setdefault(v.article_id, vide())
        d["releves"][rang.get(v.session.receptionniste_id, 0)] += v.quantite
        d["quantite"] += v.quantite
        d["montant"] += v.montant
        d[{"COMPTANT": "comptant", "CREDIT": "credit", "OFFERT": "offre"}[v.reglement]] += v.montant
        if v.encaissement_id:
            moyens[v.encaissement.moyen_libelle] = moyens.get(v.encaissement.moyen_libelle, 0) + v.montant
            if v.encaissement.mode in Encaissement.MODES_MOBILE:
                mobile_money += v.montant
    cumul = dict(VenteComptoir.objects.filter(journee__gte=premier_du_mois(jour), journee__lte=jour, annulee=False,
                                              article__categorie=categorie)
                 .values_list("article").annotate(s=Sum("montant")))
    lignes = []
    for a in articles:
        mvts = du_jour.get(a.pk, {})
        v = ventes.get(a.pk) or vide()
        if not a.actif and not mvts and not avant.get(a.pk):
            continue
        si = avant.get(a.pk, 0)
        appro = mvts.get(MouvementStock.Type.ENTREE, 0)
        avaries = -mvts.get(MouvementStock.Type.AVARIE, 0)
        sorties = -mvts.get(MouvementStock.Type.SORTIE, 0)
        ajustement = mvts.get(MouvementStock.Type.INVENTAIRE, 0)
        st = si + appro - avaries - sorties
        sf = si + sum(mvts.values())
        lignes.append({"article": a, "si": si, "appro": appro, "avaries": avaries, "sorties": sorties, "st": st,
                       "ajustement": ajustement, "sf": sf, "pv": a.prix_vente, "cumul": cumul.get(a.pk, 0), **v})
    totaux = {k: sum(x[k] for x in lignes) for k in ("montant", "credit", "offre", "comptant", "quantite", "cumul")}
    totaux["releves"] = [sum(x["releves"][i] for x in lignes) for i in range(len(colonnes))]
    totaux["mobile_money"] = mobile_money
    totaux["especes"] = totaux["comptant"] - mobile_money
    totaux["moyens"] = [{"libelle": libelle, "montant": montant} for libelle, montant in moyens.items()]
    return {"lignes": lignes, "totaux": totaux, "colonnes": colonnes,
            "a_ajustements": any(x["ajustement"] for x in lignes), "a_sorties": any(x["sorties"] for x in lignes)}


# --- Fiche recette chambres (hébergement) --------------------------------------------------------
def _paye_jusqua(sejour, fin):
    """Ce que le séjour a payé dans les sessions ouvertes avant `fin`, plus les virements de valeur antérieure."""
    encaisse = sejour.encaissements.filter(session__ouverte_le__lt=fin).aggregate(s=Sum("montant_signe"))["s"] or 0
    vire = sejour.virements.filter(date_valeur__lt=timezone.localtime(fin).date()).aggregate(s=Sum("montant"))["s"] or 0
    return encaisse + vire


def _extras(sejour, avant):
    return sejour.extras.filter(statut=Extra.Statut.ACTIF, date_conso__lt=avant).aggregate(s=Sum("montant"))["s"] or 0


def _du_jusqua(sejour, jour_exclu, avant_extras):
    """Nuits passées avant `jour_exclu` + extras consommés avant `avant_extras`."""
    nuits = max(0, (min(jour_exclu, sejour.date_depart) - sejour.date_arrivee).days)
    return nuits * sejour.tarif_nuit + _extras(sejour, avant_extras)


def fiche_hebergement(jour):
    debut, fin = debut_journee(jour), debut_journee(jour + timedelta(days=1))
    occupants = {s.chambre_id: s for s in Sejour.objects.filter(
        statut__in=[Sejour.Statut.EN_COURS, Sejour.Statut.TERMINE], date_arrivee__lte=jour, date_depart__gt=jour)
        .select_related("client")}
    lignes = []
    for chambre in Chambre.objects.filter(active=True).order_by("numero"):
        s = occupants.get(chambre.pk)
        ligne = {"chambre": chambre, "sejour": s, "recette": 0, "impaye": 0, "extras": 0, "offre": 0,
                 "compensation": 0, "avance": 0, "observation": ""}
        if s:
            paye = _paye_jusqua(s, fin)
            du_avant = _du_jusqua(s, jour, debut)
            extras_jour = _extras(s, fin) - _extras(s, debut)
            ligne["extras"] = extras_jour
            if s.gratuite == Sejour.Gratuite.OFFERT:
                ligne["offre"] = s.tarif_grille
            elif s.gratuite == Sejour.Gratuite.COMPENSATION:
                ligne["compensation"] = s.tarif_grille
            else:
                ligne["recette"] = min(max(paye - du_avant, 0), s.tarif_nuit)
                ligne["impaye"] = s.tarif_nuit - ligne["recette"]
            ligne["avance"] = max(0, paye - (du_avant + s.tarif_nuit + extras_jour))
            notes = []
            if s.date_arrivee == jour:
                notes.append("arrivée")
            if s.date_depart == jour + timedelta(days=1):
                notes.append("départ demain")
            if s.gratuite:
                notes.append(s.motif_tarif)
            ligne["observation"] = ", ".join(n for n in notes if n)
        lignes.append(ligne)

    # Règlements de dettes : paiements du jour qui couvrent ce qui restait dû à la veille.
    reglements = []
    sejours_payes = Sejour.objects.filter(encaissements__session__ouverte_le__gte=debut,
                                          encaissements__session__ouverte_le__lt=fin).distinct().select_related("client")
    for s in sejours_payes:
        paye_veille = _paye_jusqua(s, debut)
        paye_jour = _paye_jusqua(s, fin) - paye_veille
        dette_veille = max(0, _du_jusqua(s, jour, debut) - paye_veille)
        montant = min(max(paye_jour, 0), dette_veille)
        if montant:
            reglements.append({"nom": f"{s.client} (ch. {s.chambre.numero})", "montant": montant})
    for e in Encaissement.objects.filter(nature=Encaissement.Nature.REGLEMENT_CREDIT, session__ouverte_le__gte=debut,
                                         session__ouverte_le__lt=fin).select_related("client"):
        if not e.est_annule:
            reglements.append({"nom": f"{e.client} (comptoir)", "montant": e.montant})

    # Restes de dettes : séjours partis avec un solde dû, crédits de comptoir non réglés.
    dettes = []
    for s in Sejour.objects.filter(statut=Sejour.Statut.TERMINE, date_depart__lte=jour,
                                   date_depart__gte=jour - timedelta(days=365)).select_related("client", "chambre"):
        reste = _du_jusqua(s, s.date_depart, fin) - _paye_jusqua(s, fin)
        if reste > 0:
            dettes.append({"nom": f"{s.client} (ch. {s.chambre.numero})", "montant": reste})
    credits = (VenteComptoir.objects.filter(client__isnull=False, annulee=False, journee__lte=jour)
               .values("client", "client__nom").annotate(s=Sum("montant")))
    for c in credits:
        regle = Encaissement.objects.filter(client_id=c["client"], session__ouverte_le__lt=fin).aggregate(
            s=Sum("montant_signe"))["s"] or 0
        if c["s"] - regle > 0:
            dettes.append({"nom": f"{c['client__nom']} (comptoir)", "montant": c["s"] - regle})

    colonnes = ("recette", "impaye", "extras", "offre", "compensation", "avance")
    totaux = {k: sum(x[k] for x in lignes) for k in colonnes}
    # Extras du jour (cuisine, réception, bar) : ils sont encaissés à la réception, avec la chambre.
    extras_du_jour = list(Extra.objects.filter(statut=Extra.Statut.ACTIF, date_conso__gte=debut, date_conso__lt=fin)
                          .select_related("sejour__chambre", "sejour__client", "saisi_par").order_by("date_conso"))
    totaux["reglements"] = sum(r["montant"] for r in reglements)
    totaux["dettes"] = sum(d["montant"] for d in dettes)
    return {"lignes": lignes, "reglements": reglements, "dettes": sorted(dettes, key=lambda d: -d["montant"]),
            "totaux": totaux, "occupees": len(occupants), "extras_du_jour": extras_du_jour}


def chambres_a_faire(jour):
    """La fiche du ménage : chaque chambre à faire aujourd'hui, et ce qu'il faut y faire.

    Le personnel des chambres n'a pas de compte : il emporte la fiche, coche les chambres faites et la rapporte ;
    la réception touche alors « Faite » sur l'écran.
    """
    from hotel.models import Chambre, Sejour

    en_cours = {s.chambre_id: s for s in Sejour.objects.filter(statut=Sejour.Statut.EN_COURS)}
    attendues = set(Sejour.objects.filter(statut=Sejour.Statut.RESERVE, date_arrivee__lte=jour)
                    .values_list("chambre_id", flat=True))
    lignes = []
    for chambre in Chambre.objects.filter(active=True).order_by("numero"):
        sejour = en_cours.get(chambre.pk)
        if chambre.statut == Chambre.Statut.A_NETTOYER:
            quoi, ordre = "Client parti : ménage complet, changer tout le linge", 0
        elif chambre.statut == Chambre.Statut.OCCUPEE and sejour and sejour.date_depart <= jour:
            quoi, ordre = "Départ prévu aujourd'hui : ménage complet après le départ", 1
        elif chambre.statut == Chambre.Statut.OCCUPEE:
            quoi, ordre = "Recouche (le client reste) : lit, serviettes, poubelle", 2
        elif chambre.statut == Chambre.Statut.LIBRE and chambre.pk in attendues:
            quoi, ordre = "Arrivée attendue : vérifier que tout est prêt", 3
        else:
            continue
        lignes.append({"chambre": chambre, "quoi": quoi, "ordre": ordre})
    lignes.sort(key=lambda x: (x["ordre"], x["chambre"].numero))
    return lignes


def equipe_chambres():
    """Prénoms du personnel des chambres et de la blanchisserie (fiches employé, sans compte)."""
    from personnel.models import Departement, Employe

    return [e.prenom or e.nom for e in Employe.objects.filter(actif=True, departement=Departement.MENAGE)]

"""
Calcul des fiches journalières, avec les mêmes colonnes que les fiches papier de l'hôtel.

Une « journée » est celle de l'ouverture des sessions de caisse : le réceptionniste de nuit qui ouvre
à 23 h reste sur la fiche du jour, même pour une vente faite après minuit.

R1, R2, R3 (fiche boutique) : les réceptionnistes du jour, dans l'ordre de leur prise de service.
"""
from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q, Sum
from django.utils import timezone

from caisse.models import Encaissement, SessionCaisse, Tiroir, VenteComptoir
from core.utils import format_fcfa, premier_du_mois
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


def entete_caisse(sessions):
    """Le bandeau du haut des fiches papier : qui, espèces d'ouverture et de fermeture, heures de service.

    Plusieurs personnes dans la journée : l'ouverture est celle de la première, la fermeture celle de la dernière
    (espèces comptées à sa remise de caisse ; vide tant que la caisse est ouverte).
    """
    sessions = list(sessions)
    entete = {"noms": [], "ouverture": None, "fermeture": None, "heure": ""}
    if not sessions:
        return entete
    premiere, derniere = sessions[0], sessions[-1]
    for s in sessions:
        nom = f"{s.receptionniste} ({s.get_shift_display().lower()})"
        if nom not in entete["noms"]:
            entete["noms"].append(nom)
    entete["ouverture"] = premiere.especes_ouverture_comptees
    try:
        remise = derniere.remise
    except ObjectDoesNotExist:
        remise = None
    if remise is not None and remise.finalisee:
        entete["fermeture"] = remise.especes_comptees
    debut = timezone.localtime(premiere.ouverte_le).strftime("%H:%M")
    entete["heure"] = (f"{debut} à {timezone.localtime(derniere.remise_le):%H:%M}" if derniere.remise_le
                       else f"depuis {debut}")
    return entete


def _montant(valeur):
    return format_fcfa(valeur, unite=False)


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
    # L'argent reçu ce jour pour les chambres (nuits, avances, extras, dettes) : colonne Mobile et MONTANT.
    argent = Encaissement.objects.filter(session__ouverte_le__gte=debut, session__ouverte_le__lt=fin).filter(
        Q(sejour__isnull=False) | Q(client__isnull=False))
    mobile = argent.filter(mode__in=Encaissement.MODES_MOBILE)
    # Colonne Mobile d'une chambre : ce qu'ont payé par mobile le client de la nuit et celui parti ce jour.
    # Une vieille dette réglée par mobile compte seulement dans le TOTAL OM.
    mobile_par_sejour = dict(mobile.filter(sejour__isnull=False).values_list("sejour")
                             .annotate(s=Sum("montant_signe")))
    partis = {s.chambre_id: s for s in Sejour.objects.filter(check_out_le__gte=debut, check_out_le__lt=fin)
              .select_related("client").order_by("check_out_le")}
    lignes = []
    for chambre in Chambre.objects.filter(active=True).order_by("numero"):
        s = occupants.get(chambre.pk)
        ligne = {"chambre": chambre, "sejour": s, "recette": 0, "impaye": 0, "extras": 0, "offre": 0,
                 "compensation": 0, "avance": 0, "observation": "", "mobile": 0,
                 "heure_arrivee": "", "heure_depart": ""}
        parti = partis.get(chambre.pk)
        if parti:
            ligne["heure_depart"] = timezone.localtime(parti.check_out_le).strftime("%H:%M")
        ligne["mobile"] = sum(mobile_par_sejour.get(x.pk, 0) for x in {s, parti} if x)
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
            if s.check_in_le:
                arrivee = timezone.localtime(s.check_in_le)
                ligne["heure_arrivee"] = arrivee.strftime("%H:%M" if arrivee.date() == jour else "%d/%m")
            elif s.date_arrivee < jour:
                ligne["heure_arrivee"] = s.date_arrivee.strftime("%d/%m")
        notes = []
        if parti and parti != s:
            notes.append(f"parti : {parti.client}")
        if s:
            if ligne["extras"]:
                notes.append(f"extras {_montant(ligne['extras'])}")
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
    totaux["mobile"] = mobile.aggregate(s=Sum("montant_signe"))["s"] or 0
    totaux["montant"] = argent.aggregate(s=Sum("montant_signe"))["s"] or 0
    dettes = sorted(dettes, key=lambda d: -d["montant"])

    # Bandeau : la caisse de la réception ce jour-là. Total vente : tout ce qui y est entré (chambres et boutique).
    sessions = list(_sessions_du_jour(jour, Tiroir.Poste.RECEPTION))
    entete = entete_caisse(sessions)
    entete["total_vente"] = (Encaissement.objects.filter(session__in=sessions)
                             .aggregate(s=Sum("montant_signe"))["s"] or 0)

    # Comme sur papier : les colonnes « Reg dette » et « Reste dette » sont des listes écrites ligne après ligne.
    nb = max(len(lignes), len(reglements), len(dettes))
    grille = [{"ligne": lignes[i] if i < len(lignes) else None,
               "reglement": reglements[i] if i < len(reglements) else None,
               "dette": dettes[i] if i < len(dettes) else None} for i in range(nb)]
    return {"lignes": lignes, "reglements": reglements, "dettes": dettes, "grille": grille, "entete": entete,
            "totaux": totaux, "occupees": len(occupants), "extras_du_jour": extras_du_jour}


# --- Fiche bar / restaurant (même présentation que la fiche recette chambres) ------------------------------
GROUPES_BAR = ((Article.Categorie.BAR, "BOISSONS (BAR)"), (Article.Categorie.RESTAURANT, "PLATS (CUISINE)"))


def fiche_bar_restaurant(jour, sessions=None):
    """Ventes du jour au bar et à la cuisine, article par article : Qté V, Cash, Crédit, Offre, Total, Mobile.

    `sessions` : une personne seulement (sa ou ses caisses du jour) ; sinon toute la journée de la caisse Cuisine / Bar.
    Cash = payé tout de suite (espèces ou mobile) ; Mobile = la part payée par Orange Money ou MTN MoMo ;
    MONTANT = l'argent reçu (Cash) ; Total vente = Cash + Crédit (les offres ne rapportent rien).
    """
    ventes = (VenteComptoir.objects.filter(journee=jour, annulee=False,
                                           article__categorie__in=[c for c, _ in GROUPES_BAR])
              .select_related("article", "encaissement", "sejour__chambre", "client").order_by("date"))
    if sessions is not None:
        ventes = ventes.filter(session__in=sessions)
    par_categorie = {c: {} for c, _ in GROUPES_BAR}
    for v in ventes:
        ligne = par_categorie[v.article.categorie].setdefault(v.article_id, {
            "article": v.article, "prix": v.prix_unitaire, "quantite": 0, "cash": 0, "mobile": 0, "credit": 0,
            "offre": 0, "total": 0, "noms": [], "obs": []})
        ligne["quantite"] += v.quantite
        ligne["total"] += v.montant
        if v.reglement == VenteComptoir.Reglement.COMPTANT:
            ligne["cash"] += v.montant
            if v.encaissement_id and v.encaissement.mode in Encaissement.MODES_MOBILE:
                ligne["mobile"] += v.montant
        elif v.reglement == VenteComptoir.Reglement.CREDIT:
            ligne["credit"] += v.montant
            nom = f"ch. {v.sejour.chambre.numero}" if v.sejour_id else str(v.client or "")
            if nom and nom not in ligne["noms"]:
                ligne["noms"].append(nom)
        else:
            ligne["offre"] += v.montant
            texte = f"offert : {v.observation}" if v.observation else "offert"
            if texte not in ligne["obs"]:
                ligne["obs"].append(texte)
    groupes = []
    for categorie, titre in GROUPES_BAR:
        lignes = sorted(par_categorie[categorie].values(), key=lambda x: (x["article"].ordre, x["article"].nom))
        if lignes:
            groupes.append({"titre": titre, "lignes": lignes})
    toutes = [x for g in groupes for x in g["lignes"]]
    totaux = {k: sum(x[k] for x in toutes) for k in ("quantite", "cash", "mobile", "credit", "offre", "total")}
    totaux["montant"] = totaux["cash"]
    totaux["especes"] = totaux["cash"] - totaux["mobile"]
    if sessions is None:
        sessions = _sessions_du_jour(jour, Tiroir.Poste.BAR)
    entete = entete_caisse(sorted(sessions, key=lambda s: s.ouverte_le))
    entete["total_vente"] = totaux["cash"] + totaux["credit"]
    return {"groupes": groupes, "totaux": totaux, "entete": entete, "vide": not toutes}


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

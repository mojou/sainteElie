"""
Règles de la caisse par réceptionniste.

Les vues vérifient les codes PIN ; les services reçoivent des personnes déjà authentifiées
et appliquent les règles de gestion. Toute violation lève une ValidationError au message clair.
"""
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.models import Alerte, Compteur
from core.utils import alerter, format_fcfa, journaliser, maintenant
from hotel.models import Sejour
from hotel.services import constater_nuitees

from .models import (Encaissement, ParametreCaisse, RapportQuotidien, RemiseCaisse, SessionCaisse, Shift, SortieCaisse,
                     Tiroir, VenteComptoir, detail_lignes)


# --- Ouverture -----------------------------------------------------------------
def shift_suggere(quand=None):
    heure = timezone.localtime(quand or maintenant()).hour
    if 6 <= heure < 14:
        return Shift.MATIN
    if 14 <= heure < 22:
        return Shift.APRES_MIDI
    return Shift.NUIT


def session_ouverte_de(user):
    return SessionCaisse.objects.filter(receptionniste=user, statut=SessionCaisse.Statut.OUVERTE,
                                        est_rectificative=False).first()


def especes_ouverture_prevues(tiroir):
    """Ce que la session précédente a laissé dans le tiroir ; le fond si c'est la première."""
    derniere = (tiroir.sessions.filter(est_rectificative=False, remise__finalisee=True)
                .select_related("remise").order_by("-remise_le").first())
    if derniere:
        return derniere.remise.especes_transmises
    return tiroir.fond_en_vigueur()


def ouvrir_session(user, tiroir, shift, especes_comptees):
    if not user.tient_caisse:
        raise ValidationError("Seuls la réception, la cuisine / bar et la direction tiennent une caisse.")
    if not Tiroir.accessibles_a(user).filter(pk=tiroir.pk).exists():
        raise ValidationError(f"La caisse « {tiroir} » ({tiroir.get_poste_display()}) n'est pas celle de votre poste.")
    if session_ouverte_de(user):
        raise ValidationError("Vous avez déjà une session de caisse ouverte.")
    bloquante = tiroir.sessions.filter(statut=SessionCaisse.Statut.OUVERTE, est_rectificative=False).first()
    if bloquante:
        raise ValidationError(
            f"La session de {bloquante.receptionniste} sur le tiroir « {tiroir} » n'est pas encore remise. "
            "Sa remise (ou une clôture d'office par le chef) doit être faite avant toute ouverture.")
    if especes_comptees < 0:
        raise ValidationError("Le montant compté ne peut pas être négatif.")
    params = ParametreCaisse.en_vigueur()
    prevues = especes_ouverture_prevues(tiroir)
    with transaction.atomic():
        session = SessionCaisse.objects.create(
            receptionniste=user, tiroir=tiroir, shift=shift, especes_ouverture_prevues=prevues,
            especes_ouverture_comptees=especes_comptees, seuil_ecart=params.seuil_ecart)
    if especes_comptees < prevues:
        alerter(Alerte.Type.FOND_INCOMPLET,
                f"{user} a trouvé {format_fcfa(especes_comptees)} à l'ouverture au lieu de {format_fcfa(prevues)} "
                f"(tiroir {tiroir}). Le manque relève de la session précédente.",
                public=Alerte.Public.RECEPTION, lien=reverse("caisse:session", args=[session.pk]))
    journaliser(user, "Ouverture de caisse", session, f"prévu {prevues}, compté {especes_comptees}")
    return session


def _exiger_session_active(session, user):
    if session.statut != SessionCaisse.Statut.OUVERTE or session.est_rectificative:
        raise ValidationError("Cette session de caisse n'est plus ouverte.")
    if session.receptionniste_id != user.pk:
        raise ValidationError("Seul le titulaire de la session peut y enregistrer des opérations.")


# --- Encaissements ---------------------------------------------------------------
def encaisser(session, user, sejour, nature, mode, montant, reference="", valideur=None):
    _exiger_session_active(session, user)
    if nature not in (Encaissement.Nature.ACOMPTE, Encaissement.Nature.REGLEMENT, Encaissement.Nature.REMBOURSEMENT):
        raise ValidationError("Nature d'encaissement invalide.")
    if montant is None or montant <= 0:
        raise ValidationError("Le montant doit être positif.")
    if sejour.statut in (Sejour.Statut.ANNULE, Sejour.Statut.NO_SHOW) and nature != Encaissement.Nature.REMBOURSEMENT:
        raise ValidationError("Séjour annulé : seul un remboursement est possible.")
    if mode not in Encaissement.Mode.values:
        raise ValidationError("Choisissez comment le client paie.")
    reference = (reference or "").strip() if mode in (Encaissement.Mode.CARTE, Encaissement.Mode.CHEQUE) else ""
    if mode in (Encaissement.Mode.CARTE, Encaissement.Mode.CHEQUE) and not reference:
        raise ValidationError("Pour une carte ou un chèque, la référence est obligatoire (n° de transaction ou de chèque).")
    if nature == Encaissement.Nature.REMBOURSEMENT:
        if montant > sejour.total_paye:
            raise ValidationError(f"Impossible de rembourser plus que ce que le client a payé "
                                  f"({format_fcfa(sejour.total_paye)}).")
        params = ParametreCaisse.en_vigueur()
        if mode == Encaissement.Mode.ESPECES:
            if montant > session.especes_attendues:
                raise ValidationError("Il n'y a pas assez d'espèces dans le tiroir pour ce remboursement.")
            if montant > params.plafond_remboursement:
                if valideur is None:
                    raise ValidationError(
                        f"Au-delà de {format_fcfa(params.plafond_remboursement)}, un remboursement en espèces doit "
                        "être validé par le chef de réception ou le gérant (code PIN).")
                if not valideur.peut_valider_caisse or valideur.pk == user.pk:
                    raise ValidationError("Le remboursement doit être validé par une autre personne habilitée.")
    signe = -montant if nature == Encaissement.Nature.REMBOURSEMENT else montant
    encaissement = Encaissement.objects.create(
        session=session, sejour=sejour, nature=nature, mode=mode, montant=montant, montant_signe=signe,
        reference=reference, numero_recu=Compteur.suivant("recu"),
        valide_par=valideur if nature == Encaissement.Nature.REMBOURSEMENT else None, utilisateur=user)
    journaliser(user, "Encaissement", encaissement, f"{sejour}")
    return encaissement


def annuler_encaissement(encaissement, user, motif, depuis_vente=False):
    """Jamais de suppression : une écriture inverse, dans la session ouverte ou dans une session rectificative."""
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError("Une annulation sans motif est refusée.")
    if encaissement.nature == Encaissement.Nature.ANNULATION:
        raise ValidationError("On n'annule pas une annulation.")
    if encaissement.nature == Encaissement.Nature.VENTE and not depuis_vente:
        raise ValidationError("Annulez cette vente depuis la main courante : le stock sera rétabli en même temps.")
    if encaissement.est_annule:
        raise ValidationError("Cet encaissement est déjà annulé.")
    session = encaissement.session
    est_titulaire = session.receptionniste_id == user.pk
    with transaction.atomic():
        if session.statut == SessionCaisse.Statut.OUVERTE and not session.est_rectificative:
            if not (est_titulaire or user.peut_valider_caisse):
                raise ValidationError("Vous ne pouvez pas annuler une opération de la session d'un collègue.")
            cible = session
        else:
            if not user.peut_valider_caisse or est_titulaire:
                raise ValidationError("Cette session est déjà remise : seul le chef de réception ou le gérant "
                                      "peut corriger, par une session rectificative.")
            quand = maintenant()
            cible = SessionCaisse.objects.create(
                receptionniste=user, tiroir=session.tiroir, shift=session.shift, statut=SessionCaisse.Statut.VALIDEE,
                est_rectificative=True, rectifie_session=session, motif_rectification=motif, remise_le=quand,
                validee_par=user, validee_le=quand, seuil_ecart=session.seuil_ecart)
        inverse = Encaissement.objects.create(
            session=cible, sejour=encaissement.sejour, client=encaissement.client,
            nature=Encaissement.Nature.ANNULATION, mode=encaissement.mode, montant=encaissement.montant,
            montant_signe=-encaissement.montant_signe,
            reference=encaissement.reference, numero_recu=Compteur.suivant("recu"), annule=encaissement,
            motif=motif, utilisateur=user)
    alerter(Alerte.Type.ANNULATION,
            f"{user} a annulé le reçu n°{encaissement.numero_recu} ({format_fcfa(encaissement.montant)}) : {motif}",
            public=Alerte.Public.RECEPTION, lien=reverse("caisse:session", args=[cible.pk]))
    journaliser(user, "Annulation d'encaissement", encaissement, motif)
    return inverse


# --- Ventes bar et boutique (main courante) ---------------------------------------------
def journee_de(session):
    """Une session appartient à la journée de son ouverture (la nuit ouverte à 23 h reste sur la fiche du jour)."""
    return timezone.localtime(session.ouverte_le).date()


def _verifier_paiement_comptant(mode):
    if mode not in Encaissement.MODES_COMPTOIR:
        raise ValidationError("Au comptoir, on paie en espèces, Orange Money ou MTN MoMo.")


def _verifier_article(session, article, quantite):
    if article.categorie not in session.tiroir.categories_vendues:
        if article.categorie == "RESTAURANT":
            raise ValidationError("Les plats se vendent à la caisse Cuisine / Bar. Un client de l'hôtel qui ne paie "
                                  "pas tout de suite : portez le plat sur sa chambre avec « Ajouter un extra ».")
        raise ValidationError(f"{article.get_categorie_display()} : cet article ne se vend pas à la caisse "
                              f"« {session.tiroir} » ({session.tiroir.get_poste_display()}).")
    if not article.vendable_au_comptoir:
        raise ValidationError(f"{article} n'est pas en vente, ou son prix de vente n'est pas renseigné.")
    if not quantite or quantite <= 0:
        raise ValidationError("La quantité doit être positive.")


def vendre_commande(session, user, lignes, reglement, mode=Encaissement.Mode.ESPECES, sejour=None, client=None,
                    observation=""):
    """Une commande (une table, un client) : plusieurs articles, un seul paiement.

    Payée tout de suite : un seul encaissement, donc un seul reçu pour toute la commande ; chaque article garde sa
    ligne de main courante et sa sortie de stock. À crédit sur une chambre : un extra par article sur la note.
    Tout ou rien : si un article manque en stock, rien n'est enregistré.
    """
    from hotel.models import Extra
    from stock.models import MouvementStock
    from stock.services import enregistrer_mouvement

    from .models import VenteComptoir

    _exiger_session_active(session, user)
    regroupees = {}
    for article, quantite in lignes:
        _verifier_article(session, article, quantite)
        precedent = regroupees.get(article.pk)
        regroupees[article.pk] = (article, quantite + (precedent[1] if precedent else 0))
    if not regroupees:
        raise ValidationError("La commande est vide : touchez au moins un article.")
    observation = (observation or "").strip()
    R = VenteComptoir.Reglement
    if reglement == R.CREDIT:
        if sejour is None and client is None:
            raise ValidationError("Un crédit se porte sur une chambre occupée ou au nom d'un client.")
        if sejour is not None:
            if sejour.statut != Sejour.Statut.EN_COURS:
                raise ValidationError("Le crédit sur chambre n'est possible que pour un séjour en cours.")
            client = None
    else:
        sejour = client = None
    if reglement == R.OFFERT and not observation:
        raise ValidationError("Une offre doit être motivée : à qui, et pourquoi.")
    if reglement == R.COMPTANT:
        _verifier_paiement_comptant(mode)
    journee = journee_de(session)
    total = sum(article.prix_vente * quantite for article, quantite in regroupees.values())
    ventes = []
    with transaction.atomic():
        encaissement = None
        if reglement == R.COMPTANT:
            encaissement = Encaissement.objects.create(
                session=session, nature=Encaissement.Nature.VENTE, mode=mode, montant=total,
                montant_signe=total, numero_recu=Compteur.suivant("recu"), utilisateur=user)
        for article, quantite in regroupees.values():
            montant = quantite * article.prix_vente
            mouvement = extra = None
            if article.suivi_stock:
                mouvement = enregistrer_mouvement(article, user, MouvementStock.Type.VENTE, quantite,
                                                  motif=f"Main courante : {R(reglement).label}", journee=journee)
            if reglement == R.CREDIT and sejour is not None:
                source = {"BOUTIQUE": Extra.Source.BOUTIQUE, "RESTAURANT": Extra.Source.RESTAURANT}.get(
                    article.categorie, Extra.Source.BAR)
                extra = Extra.objects.create(sejour=sejour, source=source, description=f"{quantite} × {article}",
                                             montant=montant, saisi_par=user, date_conso=maintenant())
            ventes.append(VenteComptoir.objects.create(
                session=session, journee=journee, article=article, quantite=quantite,
                prix_unitaire=article.prix_vente, montant=montant, reglement=reglement, encaissement=encaissement,
                sejour=sejour, extra=extra, client=client, mouvement=mouvement, observation=observation,
                utilisateur=user))
    if reglement == R.OFFERT:
        journaliser(user, "Offre au comptoir", ", ".join(str(v) for v in ventes), observation)
    return ventes


def vendre(session, user, article, quantite, reglement, mode=Encaissement.Mode.ESPECES, sejour=None, client=None,
           observation=""):
    """Un seul article : une commande d'une ligne."""
    return vendre_commande(session, user, [(article, quantite)], reglement, mode=mode, sejour=sejour, client=client,
                           observation=observation)[0]


def annuler_vente(vente, user, motif):
    from hotel.models import Extra
    from hotel.services import annuler_extra
    from stock.models import MouvementStock
    from stock.services import enregistrer_mouvement

    motif = (motif or "").strip()
    if not motif:
        raise ValidationError("Une annulation sans motif est refusée.")
    if vente.annulee:
        raise ValidationError("Cette vente est déjà annulée.")
    session = vente.session
    ouverte = session.statut == SessionCaisse.Statut.OUVERTE
    if not ((ouverte and (session.receptionniste_id == user.pk or user.peut_valider_caisse))
            or (not ouverte and user.peut_valider_caisse and session.receptionniste_id != user.pk)):
        raise ValidationError("Cette session est déjà remise : seul le chef de réception ou le gérant peut annuler.")
    # Un reçu couvre toute la commande : on annule le reçu entier, donc chaque article de la commande.
    ventes = list(commande_de(vente))
    with transaction.atomic():
        for v in ventes:
            if v.mouvement_id:
                enregistrer_mouvement(v.article, user, MouvementStock.Type.RETOUR, v.quantite,
                                      motif=f"Annulation : {motif}", journee=v.journee)
            if v.extra_id and v.extra.statut == Extra.Statut.ACTIF:
                annuler_extra(v.extra, user, motif)
            v.annulee = True
            v.motif_annulation = motif
            v.annulee_par = user
            v.save(update_fields=["annulee", "motif_annulation", "annulee_par"])
        if vente.encaissement_id:
            annuler_encaissement(vente.encaissement, user, motif, depuis_vente=True)
    for v in ventes:
        journaliser(user, "Vente comptoir annulée", v, motif)


def commande_de(vente):
    """Les ventes encore valables du même reçu (la commande entière), ou la vente seule si elle n'a pas de reçu."""
    if not vente.encaissement_id:
        return [vente]
    return vente.encaissement.ventes.filter(annulee=False).select_related("article", "extra")


def dette_client(client):
    """Crédits de comptoir non annulés moins les règlements (et leurs annulations)."""
    from django.db.models import Sum

    credits = client.credits_comptoir.filter(annulee=False).aggregate(s=Sum("montant"))["s"] or 0
    regle = Encaissement.objects.filter(client=client).aggregate(s=Sum("montant_signe"))["s"] or 0
    return credits - regle


def resume_comptoir(ventes):
    """Ventes, crédits, offres, cash d'un ensemble de ventes comptoir.

    La recette du comptoir = cash + crédits aux clients non logés ; un crédit sur chambre est déjà
    compté dans les extras de la note, une offre n'est pas une recette.
    """
    from django.db.models import Sum

    def total(qs):
        return qs.aggregate(s=Sum("montant"))["s"] or 0

    comptant = total(ventes.filter(reglement="COMPTANT"))
    credits = total(ventes.filter(reglement="CREDIT"))
    credits_clients = total(ventes.filter(reglement="CREDIT", sejour__isnull=True))
    offres = total(ventes.filter(reglement="OFFERT"))
    return {"ventes": comptant + credits + offres, "comptant": comptant, "credits": credits, "offres": offres,
            "recette": comptant + credits_clients}


def clients_debiteurs():
    from hotel.models import Client

    resultats = []
    for client in Client.objects.filter(credits_comptoir__annulee=False).distinct():
        reste = dette_client(client)
        if reste > 0:
            resultats.append((client, reste))
    return sorted(resultats, key=lambda x: -x[1])


def regler_credit(session, user, client, montant, mode):
    _exiger_session_active(session, user)
    reste = dette_client(client)
    if not montant or montant <= 0:
        raise ValidationError("Le montant doit être positif.")
    if montant > reste:
        raise ValidationError(f"{client} ne doit que {format_fcfa(reste)}.")
    _verifier_paiement_comptant(mode)
    encaissement = Encaissement.objects.create(
        session=session, client=client, nature=Encaissement.Nature.REGLEMENT_CREDIT, mode=mode,
        montant=montant, montant_signe=montant, numero_recu=Compteur.suivant("recu"),
        utilisateur=user)
    journaliser(user, "Règlement de dette client", client, format_fcfa(montant))
    return encaissement


# --- Sorties de caisse --------------------------------------------------------------
def creer_sortie(session, user, type_, montant, motif, justificatif=None, valideur=None):
    _exiger_session_active(session, user)
    motif = (motif or "").strip()
    if not montant or montant <= 0:
        raise ValidationError("Le montant doit être positif.")
    if not motif:
        raise ValidationError("Le motif est obligatoire.")
    params = ParametreCaisse.en_vigueur()
    if type_ == SortieCaisse.Type.PRELEVEMENT:
        if valideur is None or not valideur.est_gerant:
            raise ValidationError("Un prélèvement doit être confirmé par le gérant avec son code PIN.")
        statut = SortieCaisse.Statut.VALIDEE
    else:
        valideur = None
        statut = SortieCaisse.Statut.VALIDEE if montant <= params.plafond_depense else SortieCaisse.Statut.A_VALIDER
    if montant > session.especes_attendues:
        raise ValidationError(f"Il n'y a que {format_fcfa(session.especes_attendues)} dans le tiroir.")
    sortie = SortieCaisse.objects.create(session=session, type=type_, montant=montant, motif=motif,
                                         saisi_par=user, valide_par=valideur, statut=statut)
    if justificatif:
        sortie.justificatif.save(justificatif.name, justificatif, save=True)
    if statut == SortieCaisse.Statut.A_VALIDER:
        alerter(Alerte.Type.SORTIE_A_VALIDER,
                f"Dépense de {format_fcfa(montant)} par {user} à valider : {motif}",
                public=Alerte.Public.RECEPTION, lien=reverse("caisse:session", args=[session.pk]))
    journaliser(user, "Sortie de caisse", sortie)
    return sortie


def traiter_sortie(sortie, user, accepter):
    if sortie.statut != SortieCaisse.Statut.A_VALIDER:
        raise ValidationError("Cette sortie n'est pas en attente de validation.")
    if not user.peut_valider_caisse or user.pk == sortie.saisi_par_id:
        raise ValidationError("Cette sortie doit être validée par le chef de réception ou le gérant.")
    with transaction.atomic():
        sortie.statut = SortieCaisse.Statut.VALIDEE if accepter else SortieCaisse.Statut.REFUSEE
        sortie.valide_par = user
        sortie.save(update_fields=["statut", "valide_par"])
        session = sortie.session
        if not accepter and session.statut == SessionCaisse.Statut.REMISE:
            session.statut = SessionCaisse.Statut.ECART
            session.motif_contestation = f"Dépense refusée : {sortie.motif} ({format_fcfa(sortie.montant)})"
            session.save(update_fields=["statut", "motif_contestation"])
    journaliser(user, "Sortie validée" if accepter else "Sortie refusée", sortie)


# --- Remise de caisse ------------------------------------------------------------------
def _peut_compter(session, user, cloture_office):
    if cloture_office:
        if not user.peut_valider_caisse or user.pk == session.receptionniste_id:
            raise ValidationError("La clôture d'office est réservée au chef de réception ou au gérant.")
    elif session.receptionniste_id != user.pk:
        raise ValidationError("Seul le titulaire de la session fait sa remise.")


def enregistrer_comptage(session, user, especes, billetage=None, cheques_nombre=0, cheques_total=0, mobile=None,
                         cloture_office=False):
    """Comptage à l'aveugle. Le premier comptage reste enregistré ; un seul recomptage est permis.

    `mobile` : {"ORANGE_MONEY": [montants], "MTN_MOMO": [montants]}, ce que la personne a reçu sur le téléphone.
    """
    if session.statut != SessionCaisse.Statut.OUVERTE:
        raise ValidationError("Cette session n'est plus ouverte.")
    _peut_compter(session, user, cloture_office)
    if especes is None or especes < 0:
        raise ValidationError("Saisissez le montant des espèces comptées.")
    mobile = {cle: [int(v) for v in (mobile or {}).get(cle, [])] for cle, _, _ in RemiseCaisse.MOBILES}
    if any(v < 0 for montants in mobile.values() for v in montants):
        raise ValidationError("Un montant Orange Money ou MTN MoMo ne peut pas être négatif.")
    declares = {f"{champ}_declare": sum(mobile[cle]) for cle, _, champ in RemiseCaisse.MOBILES}
    with transaction.atomic():
        remise = RemiseCaisse.objects.filter(session=session).first()
        if remise and remise.finalisee:
            raise ValidationError("La remise est déjà faite.")
        if remise:
            if remise.recompte_fait:
                raise ValidationError("Le recomptage a déjà été fait : finalisez la remise.")
            remise.especes_comptees = especes
            remise.recompte_fait = True
            remise.billetage = billetage or {}
            remise.cheques_nombre = cheques_nombre
            remise.cheques_total = cheques_total
            remise.detail_mobile = mobile
            for champ, total in declares.items():
                setattr(remise, champ, total)
            remise.save()
        else:
            remise = RemiseCaisse.objects.create(
                session=session, premier_comptage=especes, especes_comptees=especes, billetage=billetage or {},
                cheques_nombre=cheques_nombre, cheques_total=cheques_total, detail_mobile=mobile, compte_par=user,
                **declares)
    session.remise = remise  # garde en mémoire la version à jour (évite une remise périmée en cache)
    return remise


def comparaison(session):
    """Les chiffres de l'écran de remise, affichés seulement après le comptage."""
    remise = session.remise
    seuil = session.seuil_ecart
    attendues = session.especes_attendues
    nb_cheques, total_cheques = session.cheques_attendus()
    ecart = remise.especes_comptees - attendues
    ecart_cheques = remise.cheques_total - total_cheques
    mobiles = []
    for cle, libelle, champ in RemiseCaisse.MOBILES:
        attendu = session._somme_encaissements(mode=cle)
        declare = getattr(remise, f"{champ}_declare")
        mobiles.append({"cle": cle, "libelle": libelle, "champ": champ, "attendu": attendu, "declare": declare,
                        "ecart": declare - attendu, "hors_seuil": abs(declare - attendu) > seuil,
                        "lignes": detail_lignes((remise.detail_mobile or {}).get(cle, []))})
    fond = session.tiroir.fond_en_vigueur()
    versement = max(0, remise.especes_comptees - fond)
    hors_seuil = abs(ecart) > seuil or abs(ecart_cheques) > seuil or any(m["hors_seuil"] for m in mobiles)
    return {
        "attendues": attendues, "comptees": remise.especes_comptees, "premier_comptage": remise.premier_comptage,
        "ecart": ecart, "ecart_hors_seuil": abs(ecart) > seuil, "cheques_attendus": total_cheques,
        "nb_cheques_attendus": nb_cheques, "cheques_comptes": remise.cheques_total, "ecart_cheques": ecart_cheques,
        "seuil": seuil, "hors_seuil": hors_seuil, "fond": fond, "versement": versement,
        "transmises": remise.especes_comptees - versement, "mobiles": mobiles,
    }


def finaliser_remise(session, user, motif="", entrant=None, cloture_office=False):
    if session.statut != SessionCaisse.Statut.OUVERTE:
        raise ValidationError("Cette session n'est plus ouverte.")
    _peut_compter(session, user, cloture_office)
    remise = RemiseCaisse.objects.filter(session=session).first()
    if remise is None:
        raise ValidationError("Comptez d'abord le tiroir.")
    session.remise = remise  # une seule instance pour le calcul, l'enregistrement et le reçu PDF
    chiffres = comparaison(session)
    motif = (motif or "").strip()
    if chiffres["hors_seuil"] and not motif:
        raise ValidationError(f"Écart au-delà du seuil de {format_fcfa(chiffres['seuil'])} : le motif est obligatoire.")
    if cloture_office and not motif:
        raise ValidationError("Une clôture d'office doit être motivée.")
    if entrant is not None:
        if entrant.pk in (session.receptionniste_id, user.pk):
            raise ValidationError("Le réceptionniste entrant doit être une autre personne.")
        if not entrant.tient_caisse:
            raise ValidationError("La personne qui prend la relève doit tenir une caisse (réception, cuisine / bar, "
                                  "direction).")
    quand = maintenant()
    with transaction.atomic():
        remise.especes_attendues = chiffres["attendues"]
        remise.ecart = chiffres["ecart"]
        remise.cheques_attendus_total = chiffres["cheques_attendus"]
        remise.ecart_cheques = chiffres["ecart_cheques"]
        for m in chiffres["mobiles"]:
            setattr(remise, f"{m['champ']}_attendu", m["attendu"])
            setattr(remise, f"ecart_{m['champ']}", m["ecart"])
        remise.motif = motif
        remise.versement = chiffres["versement"]
        remise.especes_transmises = chiffres["transmises"]
        remise.entrant = entrant
        remise.signe_sortant_le = quand
        remise.signe_entrant_le = quand if entrant else None
        remise.finalisee = True
        remise.save()
        session.statut = (SessionCaisse.Statut.ECART if chiffres["hors_seuil"] or cloture_office
                          else SessionCaisse.Statut.REMISE)
        session.cloture_office = cloture_office
        session.remise_le = quand
        session.save(update_fields=["statut", "cloture_office", "remise_le"])
    from .pdf import recu_remise_pdf  # import local : évite un cycle au chargement

    remise.recu_pdf.save(f"remise-{session.pk}.pdf", ContentFile(recu_remise_pdf(session)), save=True)
    if session.statut == SessionCaisse.Statut.ECART:
        ecarts = [f"{format_fcfa(chiffres['ecart'])} en espèces"] + [
            f"{format_fcfa(m['ecart'])} en {m['libelle']}" for m in chiffres["mobiles"] if m["ecart"]]
        alerter(Alerte.Type.ECART,
                f"Écart à arbitrer sur la session de {session.receptionniste} ({', '.join(ecarts)}) : {motif}",
                public=Alerte.Public.RECEPTION, lien=reverse("caisse:session", args=[session.pk]))
    verifier_ecarts_recurrents(session)
    journaliser(user, "Clôture d'office" if cloture_office else "Remise de caisse", session,
                f"attendu {chiffres['attendues']}, compté {chiffres['comptees']}, écart {chiffres['ecart']}")
    return remise


# --- Validation ---------------------------------------------------------------------------
def _exiger_validateur(session, user):
    if not user.peut_valider_caisse:
        raise ValidationError("La validation est réservée au chef de réception ou au gérant.")
    remise = getattr(session, "remise", None)
    interdits = {session.receptionniste_id, remise.compte_par_id if remise else None}
    if user.pk in interdits:
        raise ValidationError("Personne ne valide sa propre remise.")


def valider_session(session, user, imputation="", decision=""):
    _exiger_validateur(session, user)
    if session.statut == SessionCaisse.Statut.REMISE:
        pass
    elif session.statut == SessionCaisse.Statut.ECART:
        if not imputation or not (decision or "").strip():
            raise ValidationError("Pour un écart, enregistrez la décision d'arbitrage et son explication.")
        session.imputation = imputation
        session.decision_arbitrage = decision.strip()
    else:
        raise ValidationError("Cette session n'est pas en attente de validation.")
    if session.sorties.filter(statut=SortieCaisse.Statut.A_VALIDER).exists():
        raise ValidationError("Une dépense de cette session attend encore sa validation.")
    session.statut = SessionCaisse.Statut.VALIDEE
    session.validee_par = user
    session.validee_le = maintenant()
    session.save()
    journaliser(user, "Validation de caisse", session, session.get_imputation_display() if imputation else "")


def contester_session(session, user, motif):
    _exiger_validateur(session, user)
    if session.statut != SessionCaisse.Statut.REMISE:
        raise ValidationError("Seule une remise en attente de validation peut être contestée.")
    if not (motif or "").strip():
        raise ValidationError("Le motif de contestation est obligatoire.")
    session.statut = SessionCaisse.Statut.ECART
    session.motif_contestation = motif.strip()
    session.save(update_fields=["statut", "motif_contestation"])
    journaliser(user, "Remise contestée", session, motif)


# --- Alertes ------------------------------------------------------------------------------
def verifier_ecarts_recurrents(session):
    params = ParametreCaisse.en_vigueur()
    depuis = maintenant() - timedelta(days=params.alerte_fenetre_jours)
    remises = (RemiseCaisse.objects.filter(finalisee=True, session__remise_le__gte=depuis,
                                           session__est_rectificative=False).select_related("session"))

    def nb_hors_seuil(qs):
        return sum(1 for r in qs if r.ecart is not None and abs(r.ecart) > r.session.seuil_ecart)

    lien = reverse("caisse:sessions")
    n = nb_hors_seuil(remises.filter(session__receptionniste=session.receptionniste))
    if n >= params.alerte_nb_ecarts:
        alerter(Alerte.Type.ECART_RECURRENT,
                f"{session.receptionniste} : {n} écarts hors seuil en {params.alerte_fenetre_jours} jours.",
                lien=lien, cle=f"recurrent-personne-{session.receptionniste_id}")
    n = nb_hors_seuil(remises.filter(session__shift=session.shift))
    if n >= params.alerte_nb_ecarts:
        alerter(Alerte.Type.ECART_RECURRENT,
                f"Shift {session.get_shift_display()} : {n} écarts hors seuil en {params.alerte_fenetre_jours} jours.",
                lien=lien, cle=f"recurrent-shift-{session.shift}")


def alerter_validations_en_retard():
    params = ParametreCaisse.en_vigueur()
    limite = maintenant() - timedelta(hours=params.delai_validation_heures)
    for session in SessionCaisse.objects.filter(statut__in=[SessionCaisse.Statut.REMISE, SessionCaisse.Statut.ECART],
                                                remise_le__lt=limite):
        alerter(Alerte.Type.VALIDATION_EN_RETARD,
                f"La remise de {session.receptionniste} du {timezone.localtime(session.remise_le):%d/%m %H:%M} "
                f"attend sa validation depuis plus de {params.delai_validation_heures} h.",
                lien=reverse("caisse:session", args=[session.pk]), cle=f"retard-{session.pk}")


# --- Visibilité ---------------------------------------------------------------------------
def sessions_visibles(user):
    qs = SessionCaisse.objects.select_related("receptionniste", "tiroir", "remise")
    if user.peut_valider_caisse:
        return qs
    return qs.filter(Q(receptionniste=user) | Q(remise__entrant=user))


# --- Rapport quotidien ------------------------------------------------------------------------
def coupure_du(jour):
    params = ParametreCaisse.en_vigueur(jour)
    return timezone.make_aware(datetime.combine(jour, params.heure_coupure))


def generer_rapports_dus(quand=None, user=None):
    """Crée les rapports dont l'heure de coupure est passée (rattrape les jours manqués)."""
    quand = quand or maintenant()
    dernier = RapportQuotidien.objects.order_by("-coupure").first()
    if dernier:
        debut = dernier.coupure
        jour = timezone.localtime(dernier.coupure).date() + timedelta(days=1)
    else:
        premiere = SessionCaisse.objects.order_by("ouverte_le").first()
        if premiere is None:
            return []
        jour = timezone.localtime(premiere.ouverte_le).date()
        debut = coupure_du(jour - timedelta(days=1))
    rapports = []
    while True:
        coupure = coupure_du(jour)
        if coupure > quand:
            break
        rapports.append(creer_rapport(debut, coupure, user))
        debut = coupure
        jour += timedelta(days=1)
    return rapports


def creer_rapport(debut, coupure, user=None):
    constater_nuitees(coupure)
    with transaction.atomic():
        rapport = RapportQuotidien.objects.create(debut=debut, coupure=coupure, genere_par=user)
        SessionCaisse.objects.filter(rapport__isnull=True, remise_le__isnull=False, remise_le__lte=coupure).update(
            rapport=rapport)
    from .pdf import rapport_pdf

    rapport.pdf.save(f"rapport-{timezone.localtime(coupure):%Y-%m-%d}.pdf", ContentFile(rapport_pdf(rapport)), save=True)
    return rapport


def donnees_rapport(rapport):
    from hotel.models import Extra, Nettoyage, Nuitee

    from .models import totaux_par_moyen

    sessions = list(rapport.sessions.select_related("receptionniste", "remise", "tiroir").order_by("remise_le"))
    par_session = {s.pk: {m["cle"]: m for m in totaux_par_moyen(s.encaissements.all())} for s in sessions}
    base = {m["cle"]: m for m in totaux_par_moyen(Encaissement.objects.none())}
    # Colonnes : espèces, Orange Money et MTN MoMo toujours ; carte et chèque seulement s'ils ont servi.
    moyens = []
    for detail in [base] + list(par_session.values()):
        for cle, m in detail.items():
            deja = cle in [x["cle"] for x in moyens]
            utile = cle not in ("CARTE", "CHEQUE") or any(d.get(cle, {}).get("montant") for d in par_session.values())
            if not deja and utile:
                moyens.append({"cle": cle, "libelle": m["libelle"]})
    lignes = []
    totaux = {"moyens": [0] * len(moyens), "total": 0, "sorties": 0, "ecart": 0, "ecart_mobile": 0}
    for s in sessions:
        remise = getattr(s, "remise", None)
        montants = [par_session[s.pk].get(m["cle"], {}).get("montant", 0) for m in moyens]
        ligne = {
            "session": s, "moyens": montants, "total": s.total_encaisse, "sorties": s.total_sorties_especes,
            "attendues": remise.especes_attendues if remise else None, "ecart": remise.ecart if remise else 0,
            "ecart_mobile": ((remise.ecart_orange_money or 0) + (remise.ecart_mtn_momo or 0)) if remise else 0,
        }
        lignes.append(ligne)
        totaux["moyens"] = [a + b for a, b in zip(totaux["moyens"], montants)]
        for cle in ("total", "sorties", "ecart", "ecart_mobile"):
            totaux[cle] += ligne[cle] or 0
    nuitees = (Nuitee.objects.filter(constatee_le__gt=rapport.debut, constatee_le__lte=rapport.coupure)
               .select_related("sejour__chambre", "sejour__client").order_by("sejour__chambre__numero", "date_nuit"))
    extras = (Extra.objects.filter(statut=Extra.Statut.ACTIF, date_conso__gt=rapport.debut,
                                   date_conso__lte=rapport.coupure).select_related("sejour__chambre"))
    total_nuitees = sum(n.montant for n in nuitees)
    total_extras = sum(e.montant for e in extras)
    impayes = [s for s in Sejour.objects.filter(statut=Sejour.Statut.TERMINE,
                                                check_out_le__gte=rapport.coupure - timedelta(days=180))
               .select_related("client", "chambre") if s.reste_a_payer > 0]
    sorties = SortieCaisse.objects.filter(session__in=sessions).select_related("session__receptionniste")
    menage = Nettoyage.objects.filter(sans_sejour=True, fait_le__gt=rapport.debut, fait_le__lte=rapport.coupure)
    comptoir = resume_comptoir(VenteComptoir.objects.filter(session__in=sessions, annulee=False))
    return {
        "rapport": rapport, "lignes": lignes, "totaux": totaux, "moyens": moyens, "nuitees": nuitees,
        "extras": extras,
        "total_nuitees": total_nuitees, "total_extras": total_extras, "comptoir": comptoir,
        "total_recettes": total_nuitees + total_extras + comptoir["recette"],
        "ecarts": [s for s in sessions if s.statut == SessionCaisse.Statut.ECART or (
            getattr(s, "remise", None) and s.remise.motif)],
        "impayes": impayes, "sorties": sorties, "menage_sans_sejour": menage,
    }

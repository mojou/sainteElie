"""
Saisie après coup d'un jour passé : les fiches papier d'avant l'application, ou un oubli.

Réservé au gérant et aux adjoints. Tout est daté du jour passé (caisses, séjours, nuitées, paiements, ventes), si
bien que les fiches de ce jour (recette chambres, bar / restaurant) se remplissent comme si on avait tout saisi à
l'heure. Chaque saisie est notée dans le journal (qui, quand, pour quel jour).

- Une caisse passée est déjà fermée (statut « validée ») et marquée `saisie_passee` : elle n'entre ni dans le
  rapport quotidien d'aujourd'hui, ni dans le calcul des espèces prévues à la prochaine ouverture.
- Les ventes passées ne touchent pas au stock (le stock d'aujourd'hui est compté à part).
- Pas de suppression d'argent : une erreur s'annule par une écriture inverse dans la même caisse passée.
"""
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Compteur
from core.utils import aujourd_hui, format_fcfa, journaliser, maintenant
from hotel.models import Chambre, Extra, Nuitee, Sejour

from .models import Encaissement, ParametreCaisse, RemiseCaisse, SessionCaisse, Tiroir, VenteComptoir
from .services import comparaison, journee_de

JOURS_MAX = 730  # deux ans en arrière au plus
MOTIF = "Saisie après coup d'un jour passé"


def verifier_droit(user):
    if not user.est_direction:
        raise ValidationError("Seuls le gérant et les adjoints peuvent saisir un jour passé.")


def verifier_jour(jour):
    if jour >= aujourd_hui():
        raise ValidationError("Choisissez un jour passé (avant aujourd'hui). Aujourd'hui se saisit normalement.")
    if jour < aujourd_hui() - timedelta(days=JOURS_MAX):
        raise ValidationError("On ne remonte pas plus de deux ans en arrière.")


def a(jour, heure):
    """Le jour et l'heure, à l'heure du Cameroun."""
    return timezone.make_aware(datetime.combine(jour, heure))


def _moment(session, heure):
    """L'heure d'une opération dans une caisse passée (après minuit pour une caisse de nuit)."""
    quand = a(journee_de(session), heure)
    if quand < session.ouverte_le:
        quand += timedelta(days=1)
    return quand


def caisses_du_jour(jour, poste=None):
    debut = a(jour, time(0, 0))
    qs = (SessionCaisse.objects.filter(saisie_passee=True, ouverte_le__gte=debut, ouverte_le__lt=debut + timedelta(days=1))
          .select_related("tiroir", "receptionniste", "remise").order_by("ouverte_le"))
    return qs.filter(tiroir__poste=poste) if poste else qs


def _caisse_passee(session):
    if not session.saisie_passee:
        raise ValidationError("Cette caisse n'est pas une caisse de jour passé.")
    return session


# --- 1. Caisses : qui la tenait, ouverture et fermeture --------------------------------------------------------
def ajouter_caisse(user, jour, tiroir, titulaire, shift, heure_ouverture, ouverture, heure_fermeture, fermeture):
    verifier_droit(user)
    verifier_jour(jour)
    if not titulaire.tient_caisse:
        raise ValidationError(f"{titulaire} ne tient pas de caisse (réception, cuisine / bar ou direction).")
    if titulaire.est_bar and tiroir.poste != Tiroir.Poste.BAR:
        raise ValidationError(f"{titulaire} tient la caisse Cuisine / Bar, pas « {tiroir} ».")
    if ouverture < 0 or fermeture < 0:
        raise ValidationError("Les montants ne peuvent pas être négatifs.")
    ouverte_le = a(jour, heure_ouverture)
    remise_le = a(jour, heure_fermeture)
    if remise_le <= ouverte_le:  # caisse de nuit : fermée le lendemain matin
        remise_le += timedelta(days=1)
    with transaction.atomic():
        session = SessionCaisse.objects.create(
            receptionniste=titulaire, tiroir=tiroir, shift=shift, especes_ouverture_prevues=ouverture,
            especes_ouverture_comptees=ouverture, seuil_ecart=ParametreCaisse.en_vigueur().seuil_ecart,
            statut=SessionCaisse.Statut.VALIDEE, validee_par=user, validee_le=maintenant(), saisie_passee=True)
        SessionCaisse.objects.filter(pk=session.pk).update(ouverte_le=ouverte_le, remise_le=remise_le)
        session.ouverte_le, session.remise_le = ouverte_le, remise_le
        RemiseCaisse.objects.create(session=session, premier_comptage=fermeture, especes_comptees=fermeture,
                                    compte_par=user, finalisee=True, motif=MOTIF, signe_sortant_le=remise_le)
        recalculer(session)
    journaliser(user, MOTIF, session, f"caisse du {jour:%d/%m/%Y} : ouverture {ouverture}, fermeture {fermeture}")
    return session


def recalculer(session):
    """Chiffres de la remise d'une caisse passée, après chaque paiement ou vente saisi.

    La fiche papier ne donne que les espèces : Orange Money, MoMo et chèques sont pris comme déclarés justes.
    """
    remise = RemiseCaisse.objects.get(session=session)
    for cle, _, champ in RemiseCaisse.MOBILES:
        setattr(remise, f"{champ}_declare", session._somme_encaissements(mode=cle))
    remise.cheques_nombre, remise.cheques_total = session.cheques_attendus()
    session.remise = remise
    c = comparaison(session)
    remise.especes_attendues, remise.ecart = c["attendues"], c["ecart"]
    remise.cheques_attendus_total, remise.ecart_cheques = c["cheques_attendus"], c["ecart_cheques"]
    for m in c["mobiles"]:
        setattr(remise, f"{m['champ']}_attendu", m["attendu"])
        setattr(remise, f"ecart_{m['champ']}", m["ecart"])
    remise.versement, remise.especes_transmises = c["versement"], c["transmises"]
    remise.save()


def supprimer_caisse(user, session):
    """Une caisse passée saisie par erreur, tant qu'elle n'a ni paiement ni vente."""
    verifier_droit(user)
    _caisse_passee(session)
    if session.encaissements.exists() or session.ventes.exists():
        raise ValidationError("Cette caisse a des paiements ou des ventes : annulez-les d'abord.")
    with transaction.atomic():
        RemiseCaisse.objects.filter(session=session).delete()
        session.delete()
    journaliser(user, f"{MOTIF} : caisse supprimée", None, str(session))


# --- 2. Chambres et paiements ------------------------------------------------------------------------------------
def sejour_passe(user, *, nom, telephone, chambre, arrivee, nuits, heure_arrivee, heure_depart=None, tarif=None,
                 motif_tarif=""):
    """Un client d'un jour passé : il est parti (séjour terminé) ou il est encore là (séjour en cours)."""
    from hotel.services import client_au_numero

    verifier_droit(user)
    verifier_jour(arrivee)
    if not nuits or nuits < 1:
        raise ValidationError("Au moins une nuit.")
    if not chambre.tarif_nuit:
        raise ValidationError(f"Le tarif de la chambre {chambre.numero} n'est pas renseigné.")
    depart = arrivee + timedelta(days=nuits)
    parti = depart <= aujourd_hui()
    if parti and heure_depart is None:
        raise ValidationError(f"Le client est parti le {depart:%d/%m/%Y} : indiquez son heure de départ.")
    tarif = chambre.tarif_nuit if tarif in (None, "") else tarif
    if tarif != chambre.tarif_nuit and not (motif_tarif or "").strip():
        raise ValidationError(f"Prix différent de la grille ({format_fcfa(chambre.tarif_nuit)}) : écrivez pourquoi.")
    autre = (Sejour.objects.filter(chambre=chambre, date_arrivee__lt=depart, date_depart__gt=arrivee)
             .exclude(statut__in=[Sejour.Statut.ANNULE, Sejour.Statut.NO_SHOW]).select_related("client").first())
    if autre:
        raise ValidationError(f"La chambre {chambre.numero} est déjà prise par {autre.client} du "
                              f"{autre.date_arrivee:%d/%m} au {autre.date_depart:%d/%m/%Y}.")
    if not parti and chambre.statut == Chambre.Statut.HORS_SERVICE:
        raise ValidationError(f"La chambre {chambre.numero} est hors service.")
    with transaction.atomic():
        client = client_au_numero(nom, telephone)
        sejour = Sejour.objects.create(
            client=client, chambre=chambre, date_arrivee=arrivee, date_depart=depart, tarif_grille=chambre.tarif_nuit,
            tarif_nuit=tarif, motif_tarif=(motif_tarif or "").strip(), cree_par=user, saisi_apres_coup=True,
            statut=Sejour.Statut.TERMINE if parti else Sejour.Statut.EN_COURS,
            check_in_le=a(arrivee, heure_arrivee), heure_arrivee=heure_arrivee,
            check_out_le=a(depart, heure_depart) if parti else None, heure_depart=heure_depart if parti else None,
            notes=f"{MOTIF} par {user}.")
        # Les nuits passées sont constatées, chacune le lendemain matin, comme l'aurait fait l'application.
        jour = arrivee
        while jour < min(depart, aujourd_hui()):
            constatee = min(a(jour + timedelta(days=1), time(8, 0)), sejour.check_out_le or maintenant())
            Nuitee.objects.create(sejour=sejour, date_nuit=jour, montant=tarif, constatee_le=constatee)
            jour += timedelta(days=1)
        if not parti:
            chambre.statut = Chambre.Statut.OCCUPEE
            chambre.save(update_fields=["statut"])
    journaliser(user, MOTIF, sejour, f"arrivée le {arrivee:%d/%m/%Y}, {nuits} nuit(s)")
    return sejour


def sejours_du_jour(jour):
    """Les clients présents ce jour-là (arrivés avant ou ce jour, partis ce jour ou après)."""
    return (Sejour.objects.filter(date_arrivee__lte=jour, date_depart__gte=jour,
                                  statut__in=[Sejour.Statut.EN_COURS, Sejour.Statut.TERMINE])
            .select_related("client", "chambre").order_by("chambre__numero"))


def paiement_passe(user, session, sejour, nature, mode, montant, heure, reference=""):
    verifier_droit(user)
    _caisse_passee(session)
    if session.tiroir.poste != Tiroir.Poste.RECEPTION:
        raise ValidationError("Les chambres se paient à une caisse de la réception.")
    if nature not in (Encaissement.Nature.ACOMPTE, Encaissement.Nature.REGLEMENT):
        raise ValidationError("Choisissez acompte ou règlement.")
    if not montant or montant <= 0:
        raise ValidationError("Le montant doit être positif.")
    if mode not in Encaissement.Mode.values:
        raise ValidationError("Choisissez comment le client a payé.")
    reference = (reference or "").strip() if mode in (Encaissement.Mode.CARTE, Encaissement.Mode.CHEQUE) else ""
    if mode in (Encaissement.Mode.CARTE, Encaissement.Mode.CHEQUE) and not reference:
        raise ValidationError("Pour une carte ou un chèque, la référence est obligatoire.")
    if sejour.statut in (Sejour.Statut.ANNULE, Sejour.Statut.NO_SHOW):
        raise ValidationError("Ce séjour est annulé.")
    with transaction.atomic():
        e = Encaissement.objects.create(
            session=session, sejour=sejour, nature=nature, mode=mode, montant=montant, montant_signe=montant,
            reference=reference, numero_recu=Compteur.suivant("recu"), utilisateur=session.receptionniste,
            motif=MOTIF)
        Encaissement.objects.filter(pk=e.pk).update(date=_moment(session, heure))
        recalculer(session)
    journaliser(user, MOTIF, e, f"{format_fcfa(montant)} pour {sejour}, le {journee_de(session):%d/%m/%Y}")
    return e


def annuler_paiement(user, encaissement):
    """Erreur de saisie : une écriture inverse dans la même caisse passée (le numéro de reçu reste)."""
    verifier_droit(user)
    session = _caisse_passee(encaissement.session)
    if encaissement.nature == Encaissement.Nature.ANNULATION or encaissement.est_annule:
        raise ValidationError("Ce paiement est déjà annulé.")
    with transaction.atomic():
        inverse = Encaissement.objects.create(
            session=session, sejour=encaissement.sejour, client=encaissement.client,
            nature=Encaissement.Nature.ANNULATION, mode=encaissement.mode, montant=encaissement.montant,
            montant_signe=-encaissement.montant_signe, reference=encaissement.reference,
            numero_recu=Compteur.suivant("recu"), annule=encaissement, motif="Erreur de saisie (jour passé)",
            utilisateur=user)
        Encaissement.objects.filter(pk=inverse.pk).update(date=encaissement.date)
        for v in encaissement.ventes.filter(annulee=False):
            _annuler_ligne(v, user)
        recalculer(session)
    journaliser(user, f"{MOTIF} : paiement annulé", encaissement, "erreur de saisie")
    return inverse


def supprimer_sejour(user, sejour):
    """Un séjour saisi après coup par erreur, tant qu'il n'a ni paiement ni consommation."""
    verifier_droit(user)
    if not sejour.saisi_apres_coup:
        raise ValidationError("Seul un séjour saisi après coup peut être supprimé ici.")
    if sejour.encaissements.exists() or sejour.extras.exists() or sejour.virements.exists():
        raise ValidationError("Ce séjour a des paiements ou des consommations : annulez-les d'abord.")
    with transaction.atomic():
        if sejour.statut == Sejour.Statut.EN_COURS and sejour.chambre.statut == Chambre.Statut.OCCUPEE:
            Chambre.objects.filter(pk=sejour.chambre_id).update(statut=Chambre.Statut.LIBRE)
        sejour.nuitees.all().delete()
        texte = str(sejour)
        sejour.delete()
    journaliser(user, f"{MOTIF} : séjour supprimé", None, texte)


# --- 3. Ventes bar / restaurant --------------------------------------------------------------------------------
PAIEMENTS_VENTE = [("ESPECES", "Espèces"), ("ORANGE_MONEY", "Orange Money"), ("MTN_MOMO", "MTN MoMo"),
                   ("CHAMBRE", "Sur la chambre (payé à la réception)"), ("OFFERT", "Offert")]


def vente_passee(user, session, article, quantite, paiement, heure, sejour=None, motif=""):
    verifier_droit(user)
    _caisse_passee(session)
    if article.categorie not in session.tiroir.categories_vendues:
        raise ValidationError(f"« {article} » ne se vend pas à la caisse « {session.tiroir} ».")
    if not quantite or quantite < 1:
        raise ValidationError("La quantité doit être d'au moins 1.")
    if paiement not in dict(PAIEMENTS_VENTE):
        raise ValidationError("Choisissez comment le client a payé.")
    jour = journee_de(session)
    quand = _moment(session, heure)
    montant = article.prix_vente * quantite
    R = VenteComptoir.Reglement
    if paiement == "CHAMBRE":
        if sejour is None:
            raise ValidationError("Choisissez la chambre du client.")
        if not (sejour.date_arrivee <= jour <= sejour.date_depart) or sejour.statut not in (
                Sejour.Statut.EN_COURS, Sejour.Statut.TERMINE):
            raise ValidationError(f"{sejour.client} n'était pas à l'hôtel le {jour:%d/%m/%Y}.")
    if paiement == "OFFERT" and not (motif or "").strip():
        raise ValidationError("Une offre doit être motivée : à qui, et pourquoi.")
    with transaction.atomic():
        encaissement = extra = None
        if paiement in ("ESPECES", "ORANGE_MONEY", "MTN_MOMO"):
            reglement = R.COMPTANT
            encaissement = Encaissement.objects.create(
                session=session, nature=Encaissement.Nature.VENTE, mode=paiement, montant=montant,
                montant_signe=montant, numero_recu=Compteur.suivant("recu"), utilisateur=session.receptionniste,
                motif=MOTIF)
            Encaissement.objects.filter(pk=encaissement.pk).update(date=quand)
        elif paiement == "CHAMBRE":
            reglement = R.CREDIT
            source = Extra.Source.RESTAURANT if article.categorie == "RESTAURANT" else Extra.Source.BAR
            extra = Extra.objects.create(sejour=sejour, source=source, description=f"{quantite} × {article}",
                                         montant=montant, saisi_par=user, date_conso=quand)
        else:
            reglement = R.OFFERT
        vente = VenteComptoir.objects.create(
            session=session, journee=jour, article=article, quantite=quantite, prix_unitaire=article.prix_vente,
            montant=montant, reglement=reglement, encaissement=encaissement, sejour=sejour if extra else None,
            extra=extra, observation=(motif or "").strip() or MOTIF, utilisateur=session.receptionniste)
        VenteComptoir.objects.filter(pk=vente.pk).update(date=quand)
        recalculer(session)
    journaliser(user, MOTIF, vente, f"{quantite} × {article}, le {jour:%d/%m/%Y}")
    return vente


def _annuler_ligne(vente, user):
    from hotel.services import annuler_extra

    if vente.extra_id and vente.extra.statut == Extra.Statut.ACTIF:
        annuler_extra(vente.extra, user, "Erreur de saisie (jour passé)")
    vente.annulee, vente.motif_annulation, vente.annulee_par = True, "Erreur de saisie (jour passé)", user
    vente.save(update_fields=["annulee", "motif_annulation", "annulee_par"])


def annuler_vente(user, vente):
    verifier_droit(user)
    session = _caisse_passee(vente.session)
    if vente.annulee:
        raise ValidationError("Cette vente est déjà annulée.")
    with transaction.atomic():
        if vente.encaissement_id:
            annuler_paiement(user, vente.encaissement)   # annule aussi la ligne de vente
        else:
            _annuler_ligne(vente, user)
            recalculer(session)
    journaliser(user, f"{MOTIF} : vente annulée", vente, "erreur de saisie")


def ventes_du_jour(jour):
    return (VenteComptoir.objects.filter(session__saisie_passee=True, journee=jour)
            .select_related("article", "encaissement", "sejour__chambre", "session__receptionniste")
            .order_by("date"))

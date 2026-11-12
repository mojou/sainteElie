from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from core.models import Alerte
from core.utils import alerter, journaliser, maintenant
from hotel.models import Chambre

from .models import EvenementSecurite, Intervention


def signaler_panne(user, probleme, chambre=None, lieu="", urgence=Intervention.Urgence.NORMALE, hors_service=False):
    probleme = (probleme or "").strip()
    if not probleme:
        raise ValidationError("Dites quel est le problème.")
    if chambre is None and not (lieu or "").strip():
        raise ValidationError("Choisissez la chambre, ou écrivez l'endroit.")
    hors_service = bool(hors_service and chambre)
    with transaction.atomic():
        panne = Intervention.objects.create(chambre=chambre, lieu=(lieu or "").strip(), probleme=probleme,
                                            urgence=urgence, hors_service=hors_service, signale_par=user)
        if hors_service and chambre.statut != Chambre.Statut.OCCUPEE:
            chambre.statut = Chambre.Statut.HORS_SERVICE
            chambre.save(update_fields=["statut"])
    if urgence == Intervention.Urgence.URGENTE or hors_service:
        alerter(Alerte.Type.AUTRE, f"Panne signalée par {user} : {panne}", public=Alerte.Public.ENCADREMENT,
                lien=reverse("postes:maintenance"))
    journaliser(user, "Panne signalée", panne)
    return panne


def avancer_panne(panne, user, statut, commentaire=""):
    if panne.statut == Intervention.Statut.FAITE:
        raise ValidationError("Cette panne est déjà réparée.")
    with transaction.atomic():
        panne.statut = statut
        if statut == Intervention.Statut.FAITE:
            panne.traite_par = user
            panne.traite_le = maintenant()
            panne.commentaire = (commentaire or "").strip()
        panne.save()
        chambre = panne.chambre
        autres = chambre and chambre.interventions.filter(hors_service=True).exclude(
            statut=Intervention.Statut.FAITE).exists()
        if statut == Intervention.Statut.FAITE and chambre and chambre.statut == Chambre.Statut.HORS_SERVICE \
                and not autres:
            # Après des travaux, la chambre passe par le ménage avant d'être relouée.
            chambre.statut = Chambre.Statut.A_NETTOYER
            chambre.save(update_fields=["statut"])
    journaliser(user, f"Panne : {Intervention.Statut(statut).label}", panne, commentaire)


def noter_evenement(user, type_, description):
    description = (description or "").strip()
    if not description:
        raise ValidationError("Écrivez ce qui s'est passé.")
    evenement = EvenementSecurite.objects.create(type=type_, description=description, saisi_par=user)
    if type_ == EvenementSecurite.Type.INCIDENT:
        alerter(Alerte.Type.AUTRE, f"Incident noté par la sécurité : {description}", public=Alerte.Public.ENCADREMENT,
                lien=reverse("postes:securite"))
    return evenement

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.utils import aujourd_hui, journaliser, maintenant

from .models import Affectation, Departement, DemandeConge, DemandeEchange, Employe, Pointage, Statut


def employes_geres(user):
    """Employés dont l'utilisateur gère le planning, les pointages et les demandes."""
    if user.est_direction:
        return Employe.objects.all()
    if user.est_gouvernante:
        return Employe.objects.filter(departement__in=[Departement.RECEPTION, Departement.BAR, Departement.MENAGE])
    if user.est_chef_reception:
        return Employe.objects.filter(departement=Departement.RECEPTION)
    if user.est_chef_equipe and user.profil_employe:
        return Employe.objects.filter(departement=user.profil_employe.departement)
    return Employe.objects.none()


def peut_gerer(user, employe):
    return employes_geres(user).filter(pk=employe.pk).exists()


def pointer_arrivee(employe, user, quand=None):
    quand = quand or maintenant()
    jour = timezone.localtime(quand).date()
    if Pointage.objects.filter(employe=employe, depart__isnull=True).exists():
        raise ValidationError("Une arrivée est déjà pointée sans départ.")
    affectation = (Affectation.objects.filter(employe=employe, date=jour).select_related("creneau")
                   .order_by("creneau__heure_debut").first())
    retard = 0
    if affectation:
        debut = affectation.creneau.debut_le(jour)
        retard = max(0, int((quand - debut).total_seconds() // 60))
    pointage = Pointage.objects.create(employe=employe, date=jour, arrivee=quand, affectation=affectation,
                                       retard_minutes=retard, saisi_par=user)
    journaliser(user, "Pointage arrivée", employe)
    return pointage


def pointer_depart(employe, user, quand=None):
    pointage = Pointage.objects.filter(employe=employe, depart__isnull=True).order_by("-arrivee").first()
    if pointage is None:
        raise ValidationError("Aucune arrivée pointée.")
    pointage.depart = quand or maintenant()
    pointage.save(update_fields=["depart"])
    journaliser(user, "Pointage départ", employe)
    return pointage


def traiter_conge(demande, user, accepter, commentaire=""):
    if demande.statut != Statut.EN_ATTENTE:
        raise ValidationError("Cette demande est déjà traitée.")
    if not peut_gerer(user, demande.employe) or (user.profil_employe and user.profil_employe.pk == demande.employe_id):
        raise ValidationError("Cette demande doit être traitée par le responsable de l'employé.")
    demande.statut = Statut.ACCEPTEE if accepter else Statut.REFUSEE
    demande.traite_par = user
    demande.commentaire = commentaire
    demande.save()
    journaliser(user, "Congé accepté" if accepter else "Congé refusé", demande.employe)


def demander_echange(user, affectation, affectation_collegue, motif=""):
    if affectation.employe.user_id != user.pk:
        raise ValidationError("Vous ne pouvez proposer que l'échange de votre propre shift.")
    if affectation_collegue.employe_id == affectation.employe_id:
        raise ValidationError("Choisissez le shift d'un collègue.")
    if affectation.date < aujourd_hui():
        raise ValidationError("Ce shift est déjà passé.")
    return DemandeEchange.objects.create(affectation=affectation, affectation_collegue=affectation_collegue,
                                         motif=motif, demandeur=user)


def traiter_echange(demande, user, accepter):
    if demande.statut != Statut.EN_ATTENTE:
        raise ValidationError("Cette demande est déjà traitée.")
    a, b = demande.affectation, demande.affectation_collegue
    if not (peut_gerer(user, a.employe) and peut_gerer(user, b.employe)) or user.pk == demande.demandeur_id:
        raise ValidationError("Cet échange doit être validé par le chef de réception, le chef d'équipe ou le gérant.")
    with transaction.atomic():
        if accepter:
            employe_a, employe_b = a.employe_id, b.employe_id
            Affectation.objects.filter(pk=a.pk).update(employe_id=employe_b)
            Affectation.objects.filter(pk=b.pk).update(employe_id=employe_a)
        demande.statut = Statut.ACCEPTEE if accepter else Statut.REFUSEE
        demande.traite_par = user
        demande.save()
    journaliser(user, "Échange de shift accepté" if accepter else "Échange de shift refusé", f"{a} / {b}")


def conges_en_cours(jour=None):
    jour = jour or aujourd_hui()
    return DemandeConge.objects.filter(statut=Statut.ACCEPTEE, date_debut__lte=jour, date_fin__gte=jour)


# --- Planning ---------------------------------------------------------------------------------------------------
def verifier_affectation(employe, jour, creneau, sauf=None):
    """Refuse un créneau impossible : pendant un congé accordé, réservé à un autre département, ou qui chevauche
    un autre créneau de la même personne (un créneau de nuit déborde sur le lendemain)."""
    from datetime import timedelta

    conge = DemandeConge.objects.filter(employe=employe, statut=Statut.ACCEPTEE, date_debut__lte=jour,
                                        date_fin__gte=jour).first()
    if conge:
        raise ValidationError(f"{employe} est en {conge.get_type_display().lower()} ce jour-là "
                              f"(du {conge.date_debut:%d/%m} au {conge.date_fin:%d/%m}).")
    if creneau.departement and employe.departement and creneau.departement != employe.departement:
        raise ValidationError(f"Le créneau « {creneau.nom} » est réservé à : {creneau.get_departement_display()}.")
    debut, fin = creneau.debut_le(jour), creneau.fin_le(jour)
    autres = (Affectation.objects.filter(employe=employe, date__gte=jour - timedelta(days=1),
                                         date__lte=jour + timedelta(days=1)).select_related("creneau"))
    if sauf is not None:
        autres = autres.exclude(pk=sauf.pk)
    for autre in autres:
        if autre.creneau.debut_le(autre.date) < fin and debut < autre.creneau.fin_le(autre.date):
            raise ValidationError(f"{employe} travaille déjà à ce moment-là : {autre.creneau.nom} le "
                                  f"{autre.date:%d/%m} ({autre.creneau.heure_debut:%H:%M}–{autre.creneau.heure_fin:%H:%M}).")


def planifier(user, employe, jour, creneau, note="", affectation=None, journal=True):
    """Ajoute un créneau au planning, ou modifie / déplace celui qui existe."""
    if not peut_gerer(user, employe):
        raise ValidationError("Vous ne gérez pas le planning de cette personne.")
    verifier_affectation(employe, jour, creneau, sauf=affectation)
    nouveau = affectation is None
    if nouveau:
        affectation = Affectation(employe=employe)
    affectation.employe, affectation.date, affectation.creneau, affectation.note = employe, jour, creneau, note[:120]
    affectation.save()
    if journal:
        journaliser(user, "Shift planifié" if nouveau else "Shift modifié", affectation)
    return affectation


def copier_semaine(user, employes, lundi):
    """Recopie la semaine précédente sur la semaine du `lundi` ; ce qui serait impossible (congé, déjà pris) est sauté."""
    from datetime import timedelta

    copies = sautes = 0
    for a in (Affectation.objects.filter(employe__in=employes, date__gte=lundi - timedelta(days=7), date__lt=lundi)
              .select_related("creneau", "employe")):
        try:
            planifier(user, a.employe, a.date + timedelta(days=7), a.creneau, a.note, journal=False)
            copies += 1
        except ValidationError:
            sautes += 1
    if copies:
        journaliser(user, "Planning : semaine précédente recopiée", f"semaine du {lundi:%d/%m/%Y}", f"{copies} shifts")
    return copies, sautes

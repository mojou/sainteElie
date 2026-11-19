"""Règles de gestion des séjours (disponibilité, check-in/out, nuitées, extras, ménage)."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import Alerte
from core.utils import alerter, aujourd_hui, journaliser, maintenant

from .models import Chambre, Extra, Nettoyage, Nuitee, Sejour


def client_au_numero(nom, telephone, email=""):
    """La fiche du client à ce numéro, écrit de n'importe quelle façon (« +237 677 12 34 56 » = « 677123456 ») ;
    une nouvelle fiche s'il n'est jamais venu."""
    from core.utils import normaliser_telephone

    from .models import Client

    numero = normaliser_telephone(telephone)
    if numero:
        for c in Client.objects.exclude(telephone="").only("pk", "telephone", "nom"):
            if normaliser_telephone(c.telephone) == numero:
                return c
    return Client.objects.create(nom=(nom or "").strip()[:120], telephone=numero or (telephone or "").strip(),
                                 email=email or "")


def conflits(chambre, arrivee, depart, exclure=None):
    """Séjours actifs qui chevauchent [arrivee, depart[ sur la chambre.

    Une réservation porte sur des nuits : un départ le 12 et une arrivée le 12 ne se gênent pas.
    """
    qs = Sejour.objects.filter(chambre=chambre, statut__in=Sejour.ACTIFS,
                               date_arrivee__lt=depart, date_depart__gt=arrivee)
    if exclure is not None and exclure.pk:
        qs = qs.exclude(pk=exclure.pk)
    return qs


def verifier_disponibilite(chambre, arrivee, depart, exclure=None):
    if depart <= arrivee:
        raise ValidationError("La date de départ doit être après la date d'arrivée.")
    if not chambre.active or chambre.statut == Chambre.Statut.HORS_SERVICE:
        raise ValidationError(f"La {chambre} est hors service.")
    autre = conflits(chambre, arrivee, depart, exclure).first()
    if autre:
        raise ValidationError(
            f"La chambre {chambre.numero} est déjà réservée du {autre.date_arrivee:%d/%m/%Y} "
            f"au {autre.date_depart:%d/%m/%Y} ({autre.client})."
        )


def nuitees_passees(sejour):
    """Les nuits déjà écoulées d'un séjour saisi après coup, chacune constatée le lendemain matin."""
    from datetime import datetime, time

    jour = sejour.date_arrivee
    while jour < min(sejour.date_depart, aujourd_hui()):
        constatee = min(timezone.make_aware(datetime.combine(jour + timedelta(days=1), time(8, 0))),
                        sejour.check_out_le or maintenant())
        Nuitee.objects.get_or_create(sejour=sejour, date_nuit=jour,
                                     defaults={"montant": sejour.tarif_nuit, "constatee_le": constatee})
        jour += timedelta(days=1)


def liberer_sejour_passe(sejour, user, heure_arrivee, heure_depart):
    """Un séjour aux dates déjà passées (fiche papier) : enregistré directement « libéré ».

    Pas d'arrivée ni de départ à faire, pas de ménage : la chambre reste libre. Les nuits sont constatées.
    """
    from datetime import datetime

    if sejour.date_depart > aujourd_hui():
        raise ValidationError("Ce séjour n'est pas fini : le client part après aujourd'hui.")
    if not user.est_direction:
        raise ValidationError("Un séjour déjà passé s'enregistre par le gérant, le PDG ou un adjoint.")
    with transaction.atomic():
        sejour.statut = Sejour.Statut.TERMINE
        sejour.saisi_apres_coup = True
        sejour.check_in_le = timezone.make_aware(datetime.combine(sejour.date_arrivee, heure_arrivee))
        sejour.check_out_le = timezone.make_aware(datetime.combine(sejour.date_depart, heure_depart))
        sejour.heure_arrivee, sejour.heure_depart = heure_arrivee, heure_depart
        sejour.save(update_fields=["statut", "saisi_apres_coup", "check_in_le", "check_out_le", "heure_arrivee",
                                   "heure_depart"])
        nuitees_passees(sejour)
    journaliser(user, "Séjour passé saisi (libéré)", sejour,
                f"du {sejour.date_arrivee:%d/%m/%Y} {heure_arrivee:%H:%M} au {sejour.date_depart:%d/%m/%Y} "
                f"{heure_depart:%H:%M}")
    return sejour


def lire_heure(texte, quoi):
    """« 14:30 » (champ heure du navigateur) → 14 h 30 ; vide ou faux : on redemande l'heure."""
    from datetime import datetime

    texte = (texte or "").strip()
    for format_ in ("%H:%M", "%H:%M:%S", "%Hh%M", "%H h %M"):
        try:
            return datetime.strptime(texte, format_).time().replace(second=0)
        except ValueError:
            continue
    raise ValidationError(f"Indiquez l'heure {quoi} du client (par exemple 14:30).")


def _heure_actuelle():
    return timezone.localtime(maintenant()).time().replace(second=0, microsecond=0)


def check_in(sejour, user, heure=None):
    """`heure` : l'heure réelle d'arrivée du client, tapée par la réception (sinon l'heure actuelle)."""
    if sejour.statut != Sejour.Statut.RESERVE:
        raise ValidationError("Seul un séjour réservé peut faire son check-in.")
    if sejour.date_arrivee > aujourd_hui():
        raise ValidationError(f"L'arrivée est prévue le {sejour.date_arrivee:%d/%m/%Y}.")
    chambre = sejour.chambre
    if chambre.statut == Chambre.Statut.HORS_SERVICE:
        raise ValidationError(f"La {chambre} est hors service.")
    occupant = Sejour.objects.filter(chambre=chambre, statut=Sejour.Statut.EN_COURS).exclude(pk=sejour.pk).first()
    if occupant:
        raise ValidationError(f"La {chambre} est encore occupée par {occupant.client}.")
    if chambre.statut == Chambre.Statut.A_NETTOYER:
        raise ValidationError(f"La {chambre} n'est pas encore faite : le ménage doit la marquer propre.")
    with transaction.atomic():
        sejour.statut = Sejour.Statut.EN_COURS
        sejour.check_in_le = maintenant()
        sejour.heure_arrivee = heure or _heure_actuelle()
        sejour.save(update_fields=["statut", "check_in_le", "heure_arrivee"])
        chambre.statut = Chambre.Statut.OCCUPEE
        chambre.save(update_fields=["statut"])
    journaliser(user, "Check-in", sejour)


def _constater(sejour, jusqua_exclu, quand):
    crees = 0
    jour = sejour.date_arrivee
    while jour < jusqua_exclu:
        _, cree = Nuitee.objects.get_or_create(
            sejour=sejour, date_nuit=jour, defaults={"montant": sejour.tarif_nuit, "constatee_le": quand})
        crees += int(cree)
        jour += timedelta(days=1)
    return crees


def constater_nuitees(quand=None):
    """Constate la recette des nuits écoulées pour les séjours en cours.

    La nuit du J au J+1 est constatée dès le J+1 ; le reste au check-out.
    """
    quand = quand or maintenant()
    jour = timezone.localtime(quand).date()
    total = 0
    for sejour in Sejour.objects.filter(statut=Sejour.Statut.EN_COURS, date_arrivee__lt=jour):
        total += _constater(sejour, min(jour, sejour.date_depart), quand)
    return total


def check_out(sejour, user, heure=None):
    """`heure` : l'heure réelle de départ du client, tapée par la réception (sinon l'heure actuelle)."""
    if sejour.statut != Sejour.Statut.EN_COURS:
        raise ValidationError("Seul un séjour en cours peut faire son check-out.")
    aujourd = aujourd_hui()
    with transaction.atomic():
        if aujourd != sejour.date_depart:
            # Départ anticipé ou tardif : on facture les nuits réellement passées, au moins une.
            sejour.date_depart = max(aujourd, sejour.date_arrivee + timedelta(days=1))
        _constater(sejour, sejour.date_depart, maintenant())
        sejour.statut = Sejour.Statut.TERMINE
        sejour.check_out_le = maintenant()
        sejour.heure_depart = heure or _heure_actuelle()
        sejour.save(update_fields=["statut", "check_out_le", "date_depart", "heure_depart"])
        chambre = sejour.chambre
        chambre.statut = Chambre.Statut.A_NETTOYER
        chambre.save(update_fields=["statut"])
    journaliser(user, "Check-out", sejour, f"reste à payer : {sejour.reste_a_payer}")


def annuler(sejour, user, motif, no_show=False):
    if sejour.statut != Sejour.Statut.RESERVE:
        raise ValidationError("Seule une réservation pas encore arrivée peut être annulée ou passée en no-show.")
    if not motif:
        raise ValidationError("Le motif est obligatoire.")
    sejour.statut = Sejour.Statut.NO_SHOW if no_show else Sejour.Statut.ANNULE
    sejour.motif_annulation = motif
    sejour.save(update_fields=["statut", "motif_annulation"])
    journaliser(user, "No-show" if no_show else "Annulation de réservation", sejour, motif)


def ajouter_extra(sejour, user, source, description, montant, numero_bon=""):
    if sejour.statut != Sejour.Statut.EN_COURS:
        raise ValidationError("Un extra ne peut être porté que sur un séjour en cours.")
    if montant <= 0:
        raise ValidationError("Le montant doit être positif.")
    extra = Extra.objects.create(sejour=sejour, source=source, description=description, montant=montant,
                                 numero_bon=numero_bon, saisi_par=user, date_conso=maintenant())
    journaliser(user, "Extra saisi", extra, f"{montant} FCFA sur {sejour}")
    return extra


def annuler_extra(extra, user, motif):
    if extra.statut != Extra.Statut.ACTIF:
        raise ValidationError("Cet extra est déjà annulé.")
    if not motif:
        raise ValidationError("Le motif d'annulation est obligatoire.")
    if extra.sejour.statut == Sejour.Statut.TERMINE and not user.peut_valider_caisse:
        raise ValidationError("Le séjour est terminé : seul le chef de réception ou le gérant peut annuler cet extra.")
    extra.statut = Extra.Statut.ANNULE
    extra.motif_annulation = motif
    extra.annule_par = user
    extra.annule_le = maintenant()
    extra.save()
    journaliser(user, "Extra annulé", extra, motif)
    alerter(Alerte.Type.ANNULATION, f"Extra annulé par {user} sur la ch. {extra.sejour.chambre.numero} : "
            f"{extra.montant} FCFA ({motif})", public=Alerte.Public.RECEPTION,
            lien=reverse("hotel:sejour", args=[extra.sejour_id]))


def marquer_nettoyee(chambre, user):
    """Le ménage marque la chambre faite. Une chambre faite sans séjour récent déclenche une alerte."""
    quand = maintenant()
    recent = Sejour.objects.filter(chambre=chambre).filter(
        statut=Sejour.Statut.EN_COURS).exists() or Sejour.objects.filter(
        chambre=chambre, statut=Sejour.Statut.TERMINE, check_out_le__gte=quand - timedelta(hours=36)).exists()
    nettoyage = Nettoyage.objects.create(chambre=chambre, fait_le=quand, fait_par=user, sans_sejour=not recent)
    if chambre.statut == Chambre.Statut.A_NETTOYER:
        chambre.statut = Chambre.Statut.LIBRE
        chambre.save(update_fields=["statut"])
    if not recent:
        alerter(Alerte.Type.MENAGE_SANS_SEJOUR,
                f"{chambre} faite le {timezone.localtime(quand):%d/%m à %H:%M} sans séjour enregistré récemment.",
                lien=reverse("hotel:menage"))
    journaliser(user, "Chambre faite", chambre)
    return nettoyage

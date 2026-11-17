"""Réservation depuis la page d'accueil : le client voit les chambres libres à ses dates et envoie sa demande.

La réception la confirme d'un geste (elle appelle le client si besoin) : le séjour « Réservé » est alors créé.
Pourquoi une demande et pas une réservation immédiate : sans paiement en ligne, n'importe qui pourrait bloquer toutes
les chambres avec un faux numéro. La demande ne bloque pas la chambre ; la disponibilité est revérifiée à la
confirmation, et la réception peut proposer une autre chambre.
"""
from collections import OrderedDict
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.templatetags.static import static
from django.urls import reverse

from core.models import Alerte
from core.utils import alerter, aujourd_hui, format_fcfa, journaliser, maintenant, normaliser_telephone
from hotel.models import Chambre, Sejour
from hotel.services import verifier_disponibilite

from .models import DemandeReservation

NUITS_MAX = 30          # au-delà, on appelle la réception
JOURS_AVANCE_MAX = 365  # on réserve au plus un an à l'avance
PERSONNES_MAX = 6
DEMANDES_PAR_HEURE_MAX = 40  # toutes adresses confondues : au-delà, c'est un robot, pas des clients
LIBELLES = {"SIMPLE": "Chambre simple", "DOUBLE": "Chambre double", "SUITE": "Suite", "AUTRE": "Chambre"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
        "décembre"]


def date_longue(jour):
    return f"{JOURS[jour.weekday()]} {jour.day} {MOIS[jour.month - 1]} {jour.year}"


def verifier_dates(arrivee, depart, personnes):
    j = aujourd_hui()
    if arrivee < j:
        raise ValidationError("La date d'arrivée est déjà passée : choisissez aujourd'hui ou plus tard.")
    if depart <= arrivee:
        raise ValidationError("La date de départ doit venir après la date d'arrivée.")
    if (depart - arrivee).days > NUITS_MAX:
        raise ValidationError(f"En ligne, on réserve {NUITS_MAX} nuits au plus. Pour un long séjour, appelez la "
                              "réception : elle vous fera un prix.")
    if arrivee > j + timedelta(days=JOURS_AVANCE_MAX):
        raise ValidationError("On réserve au plus un an à l'avance.")
    if not 1 <= personnes <= PERSONNES_MAX:
        raise ValidationError(f"De 1 à {PERSONNES_MAX} personnes par réservation en ligne.")


def chambres_libres(arrivee, depart, personnes=1):
    """Les chambres libres toutes les nuits du séjour, assez grandes, triées par prix."""
    prises = Sejour.objects.filter(statut__in=Sejour.ACTIFS, date_arrivee__lt=depart,
                                   date_depart__gt=arrivee).values("chambre")
    return (Chambre.objects.filter(active=True, tarif_nuit__gt=0, capacite__gte=personnes)
            .exclude(statut=Chambre.Statut.HORS_SERVICE).exclude(pk__in=prises).order_by("tarif_nuit", "numero"))


def types_libres(arrivee, depart, personnes=1):
    """Ce que le client choisit : un type de chambre (catégorie et prix), avec le nombre encore libre."""
    nuits = (depart - arrivee).days
    groupes = OrderedDict()
    for c in chambres_libres(arrivee, depart, personnes):
        cle = f"{c.categorie}-{c.tarif_nuit}"
        g = groupes.setdefault(cle, {"cle": cle, "categorie": c.categorie, "libelle": LIBELLES.get(c.categorie, "Chambre"),
                                     "tarif": c.tarif_nuit, "nuits": nuits, "total": c.tarif_nuit * nuits,
                                     "chambres": [], "capacite": c.capacite, "photo": "", "description": ""})
        g["chambres"].append(c)
        g["capacite"] = max(g["capacite"], c.capacite)
        if not g["photo"] and c.photo:
            g["photo"] = c.photo_url
        if not g["description"] and c.description:
            g["description"] = c.description
    for g in groupes.values():
        g["libres"] = len(g["chambres"])
        g["photo"] = g["photo"] or static("img/vitrine/chambres.svg")
    return list(groupes.values())


def trouver_type(arrivee, depart, personnes, cle):
    return next((t for t in types_libres(arrivee, depart, personnes) if t["cle"] == cle), None)


def trop_de_demandes():
    """Plus de demandes en une heure qu'un hôtel de cette taille n'en reçoit jamais : on suspend le formulaire."""
    depuis = maintenant() - timedelta(hours=1)
    return DemandeReservation.objects.filter(cree_le__gte=depuis).count() >= DEMANDES_PAR_HEURE_MAX


def _cle_alerte(demande):
    return f"demande-reservation-{demande.pk}"


def creer_demande(arrivee, depart, personnes, cle_type, nom, telephone, email="", message="", compte=None):
    verifier_dates(arrivee, depart, personnes)
    choix = trouver_type(arrivee, depart, personnes, cle_type)
    if choix is None:
        raise ValidationError("Ce type de chambre n'est plus libre à ces dates : choisissez-en un autre.")
    demande = DemandeReservation.objects.create(
        date_arrivee=arrivee, date_depart=depart, nb_personnes=personnes, categorie=choix["categorie"],
        tarif_nuit=choix["tarif"], chambre_proposee=choix["chambres"][0], nom=nom.strip()[:120],
        telephone=normaliser_telephone(telephone), email=(email or "").strip(), message=(message or "").strip()[:500],
        compte=compte)
    alerter(Alerte.Type.AUTRE,
            f"Réservation en ligne n°{demande.pk} à confirmer : {demande.nom} ({demande.telephone}), "
            f"{choix['libelle'].lower()} à {format_fcfa(choix['tarif'])}, du {arrivee:%d/%m} au {depart:%d/%m} "
            f"({demande.nb_nuits} nuit{'s' if demande.nb_nuits > 1 else ''}).",
            public=Alerte.Public.RECEPTION, lien=reverse("vitrine:demandes"), cle=_cle_alerte(demande))
    journaliser(None, "Demande de réservation en ligne", demande, f"{demande.nom} {demande.telephone}")
    return demande


def _fiche_client(demande):
    """La fiche du client : celle de son compte en ligne relié, sinon celle à son numéro, sinon une nouvelle."""
    if demande.compte_id and demande.compte.client_id:
        return demande.compte.client
    from hotel.services import client_au_numero

    return client_au_numero(demande.nom, demande.telephone, demande.email)


def _clore(demande, user, statut, motif=""):
    from core.models import Alerte as A

    demande.statut = statut
    demande.motif = motif
    demande.traitee_par = user
    demande.traitee_le = maintenant()
    A.objects.filter(cle=_cle_alerte(demande), lue_le__isnull=True).update(lue_le=maintenant())


def _prendre(demande, statut):
    """Passe la demande de « À confirmer » à son nouveau statut en une seule écriture : si une collègue l'a traitée
    entre-temps (double appui, deux postes), rien n'est fait deux fois."""
    pris = DemandeReservation.objects.filter(pk=demande.pk, statut=DemandeReservation.Statut.NOUVELLE).update(
        statut=statut)
    if not pris:
        raise ValidationError("Cette demande a déjà été traitée.")


def confirmer(demande, user, chambre):
    """La réception confirme : la disponibilité est revérifiée et le séjour « Réservé » est créé."""
    if demande.statut != DemandeReservation.Statut.NOUVELLE:
        raise ValidationError("Cette demande a déjà été traitée.")
    with transaction.atomic():
        _prendre(demande, DemandeReservation.Statut.CONFIRMEE)
        verifier_disponibilite(chambre, demande.date_arrivee, demande.date_depart)
        if chambre.capacite < demande.nb_personnes:
            raise ValidationError(f"La chambre {chambre.numero} est prévue pour {chambre.capacite} personne(s) ; "
                                  f"la demande est pour {demande.nb_personnes}.")
        client = _fiche_client(demande)
        notes = f"Réservation en ligne n°{demande.pk}." + (f" Message du client : {demande.message}" if demande.message else "")
        sejour = Sejour.objects.create(
            client=client, chambre=chambre, date_arrivee=demande.date_arrivee, date_depart=demande.date_depart,
            nb_personnes=demande.nb_personnes, tarif_grille=chambre.tarif_nuit, tarif_nuit=chambre.tarif_nuit,
            statut=Sejour.Statut.RESERVE, notes=notes, cree_par=user)
        demande.sejour = sejour
        _clore(demande, user, DemandeReservation.Statut.CONFIRMEE)
        demande.save()
    journaliser(user, "Réservation en ligne confirmée", sejour, f"demande n°{demande.pk}")
    return sejour


def refuser(demande, user, motif):
    if demande.statut != DemandeReservation.Statut.NOUVELLE:
        raise ValidationError("Cette demande a déjà été traitée.")
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError("Dites pourquoi (complet, client injoignable…) : le client le verra.")
    with transaction.atomic():
        _prendre(demande, DemandeReservation.Statut.REFUSEE)
        _clore(demande, user, DemandeReservation.Statut.REFUSEE, motif[:200])
        demande.save()
    journaliser(user, "Réservation en ligne refusée", demande, motif)


def annuler_par_le_client(demande, compte):
    if demande.compte_id != compte.pk:
        raise ValidationError("Cette demande n'est pas la vôtre.")
    if demande.statut != DemandeReservation.Statut.NOUVELLE:
        raise ValidationError("Cette demande est déjà traitée : appelez la réception pour la changer.")
    with transaction.atomic():
        _prendre(demande, DemandeReservation.Statut.ANNULEE)
        _clore(demande, None, DemandeReservation.Statut.ANNULEE, "Annulée par le client")
        demande.save()

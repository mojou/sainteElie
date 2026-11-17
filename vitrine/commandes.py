"""Commander des plats depuis le site : le client choisit ses plats, le jour et l'heure, et où il mange.

La réception ou la cuisine appelle le client et confirme. À l'heure dite, la cuisine sert et encaisse à sa caisse
« Cuisine / Bar », comme une vente au comptoir (un seul reçu), ou porte les plats sur la note de la chambre.
Rien n'est payé en ligne : une commande n'engage personne tant qu'elle n'est pas confirmée.
"""
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import Alerte
from core.utils import alerter, aujourd_hui, format_fcfa, journaliser, maintenant, normaliser_telephone
from stock.models import Article

from .models import CommandePlats, LignePlat

# Heures de la cuisine (à ajuster si besoin) : on commande pour 7 h au plus tôt, 22 h au plus tard.
HEURE_OUVERTURE = 7
HEURE_FERMETURE = 22
DELAI_MINUTES = 45      # le temps de préparer : pas de commande pour dans moins de 45 minutes
JOURS_AVANCE_MAX = 30
QUANTITE_MAX = 20       # d'un même plat
PLATS_MAX = 40          # en tout dans une commande
COMMANDES_PAR_HEURE_MAX = 40  # toutes adresses confondues : au-delà, c'est un robot


def plats_a_commander():
    """La carte : les plats en vente, rubrique par rubrique, dans l'ordre de la carte."""
    return Article.objects.filter(categorie=Article.Categorie.RESTAURANT, actif=True, prix_vente__gt=0).order_by(
        "ordre", "nom")


def creneaux():
    """Les heures proposées, de demi-heure en demi-heure."""
    resultat, minutes = [], HEURE_OUVERTURE * 60
    while minutes <= HEURE_FERMETURE * 60:
        resultat.append(time(minutes // 60, minutes % 60))
        minutes += 30
    return resultat


def moment(jour, heure):
    return timezone.make_aware(datetime.combine(jour, heure))


def verifier_moment(pour_le):
    jour = timezone.localtime(pour_le).date()
    if pour_le < maintenant() + timedelta(minutes=DELAI_MINUTES):
        raise ValidationError(f"Choisissez une heure dans {DELAI_MINUTES} minutes au moins : le temps de préparer.")
    if jour > aujourd_hui() + timedelta(days=JOURS_AVANCE_MAX):
        raise ValidationError(f"On commande au plus {JOURS_AVANCE_MAX} jours à l'avance.")
    heure = timezone.localtime(pour_le).time()
    if not time(HEURE_OUVERTURE) <= heure <= time(HEURE_FERMETURE):
        raise ValidationError(f"La cuisine sert de {HEURE_OUVERTURE} h à {HEURE_FERMETURE} h.")


def verifier_lignes(quantites):
    """{id article: quantité} → [(article, quantité)] ; seulement des plats de la carte, en quantités raisonnables."""
    quantites = {pk: q for pk, q in quantites.items() if q}
    if not quantites:
        raise ValidationError("Choisissez au moins un plat (touchez « + »).")
    if any(q < 0 or q > QUANTITE_MAX for q in quantites.values()):
        raise ValidationError(f"{QUANTITE_MAX} portions au plus d'un même plat : pour un groupe, appelez la réception.")
    if sum(quantites.values()) > PLATS_MAX:
        raise ValidationError(f"{PLATS_MAX} plats au plus par commande : pour un groupe, appelez la réception.")
    plats = {a.pk: a for a in plats_a_commander().filter(pk__in=quantites)}
    if set(quantites) - set(plats):
        raise ValidationError("Un plat choisi n'est plus à la carte : rechargez la page.")
    return [(plats[pk], q) for pk, q in quantites.items()]


def trop_de_commandes():
    depuis = maintenant() - timedelta(hours=1)
    return CommandePlats.objects.filter(cree_le__gte=depuis).count() >= COMMANDES_PAR_HEURE_MAX


def creer_commande(quantites, pour_le, service, nom, telephone, chambre="", email="", message="", compte=None):
    """quantites : {id du plat: nombre de portions}."""
    verifier_moment(pour_le)
    lignes = verifier_lignes(quantites)
    if service not in CommandePlats.Service.values:
        raise ValidationError("Dites où vous mangez : au restaurant, à emporter ou dans votre chambre.")
    chambre = (chambre or "").strip()[:10] if service == CommandePlats.Service.EN_CHAMBRE else ""
    with transaction.atomic():
        commande = CommandePlats.objects.create(
            pour_le=pour_le, service=service, chambre=chambre, nom=nom.strip()[:120],
            telephone=normaliser_telephone(telephone), email=(email or "").strip(),
            message=(message or "").strip()[:300], compte=compte)
        LignePlat.objects.bulk_create([LignePlat(commande=commande, article=a, quantite=q, prix_unitaire=a.prix_vente)
                                       for a, q in lignes])
    quand = timezone.localtime(pour_le)
    alerter(Alerte.Type.AUTRE,
            f"Plats commandés en ligne n°{commande.pk} à confirmer : {commande.nom} ({commande.telephone}), "
            f"{commande.nb_plats} plat(s), {format_fcfa(commande.total)}, pour le {quand:%d/%m à %H:%M} "
            f"({commande.get_service_display().lower()}).",
            public=Alerte.Public.RECEPTION, lien=reverse("vitrine:commandes_plats"), cle=_cle(commande))
    journaliser(None, "Plats commandés en ligne", commande, f"{commande.nom} {commande.telephone}")
    return commande


def _cle(commande):
    return f"commande-plats-{commande.pk}"


def _passer(commande, depuis, vers):
    """Change le statut en une seule écriture : si une collègue l'a déjà fait (double appui, deux postes), rien
    n'est fait deux fois."""
    if not CommandePlats.objects.filter(pk=commande.pk, statut=depuis).update(statut=vers):
        raise ValidationError("Cette commande a déjà été traitée : rechargez la page.")
    commande.statut = vers


def _clore_alerte(commande):
    Alerte.objects.filter(cle=_cle(commande), lue_le__isnull=True).update(lue_le=maintenant())


def confirmer(commande, user):
    with transaction.atomic():
        _passer(commande, CommandePlats.Statut.NOUVELLE, CommandePlats.Statut.CONFIRMEE)
        commande.traitee_par, commande.traitee_le = user, maintenant()
        commande.save(update_fields=["traitee_par", "traitee_le"])
    _clore_alerte(commande)
    journaliser(user, "Commande de plats confirmée", commande)


def refuser(commande, user, motif):
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError("Dites pourquoi (plat épuisé, client injoignable…) : le client le verra.")
    with transaction.atomic():
        _passer(commande, CommandePlats.Statut.NOUVELLE, CommandePlats.Statut.REFUSEE)
        commande.motif, commande.traitee_par, commande.traitee_le = motif[:200], user, maintenant()
        commande.save(update_fields=["motif", "traitee_par", "traitee_le"])
    _clore_alerte(commande)
    journaliser(user, "Commande de plats refusée", commande, motif)


def annuler(commande, user, motif):
    """Commande confirmée que le client ne vient pas chercher (ou qu'il annule par téléphone)."""
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError("Dites pourquoi la commande est annulée.")
    with transaction.atomic():
        _passer(commande, CommandePlats.Statut.CONFIRMEE, CommandePlats.Statut.ANNULEE)
        commande.motif = motif[:200]
        commande.save(update_fields=["motif"])
    journaliser(user, "Commande de plats annulée", commande, motif)


def annuler_par_le_client(commande, compte):
    if commande.compte_id != compte.pk:
        raise ValidationError("Cette commande n'est pas la vôtre.")
    if commande.statut != CommandePlats.Statut.NOUVELLE:
        raise ValidationError("Cette commande est déjà confirmée : appelez la réception pour l'annuler.")
    with transaction.atomic():
        _passer(commande, CommandePlats.Statut.NOUVELLE, CommandePlats.Statut.ANNULEE)
        commande.motif = "Annulée par le client"
        commande.save(update_fields=["motif"])
    _clore_alerte(commande)


PAIEMENTS = [("ESPECES", "Espèces"), ("ORANGE_MONEY", "Orange Money"), ("MTN_MOMO", "MTN MoMo"),
             ("CHAMBRE", "Sur sa chambre")]


def servir(commande, user, session, paiement, sejour=None):
    """Les plats sont servis : la vente s'enregistre à la caisse Cuisine / Bar (un seul reçu), ou sur la chambre."""
    from caisse import services as caisse
    from caisse.models import VenteComptoir

    if session is None:
        raise ValidationError("Ouvrez d'abord votre caisse « Cuisine / Bar » pour encaisser ces plats.")
    if paiement not in dict(PAIEMENTS):
        raise ValidationError("Touchez comment le client paie.")
    lignes = [(ligne.article, ligne.quantite) for ligne in commande.lignes.select_related("article")]
    observation = f"Commande en ligne n°{commande.pk}"
    with transaction.atomic():
        _passer(commande, CommandePlats.Statut.CONFIRMEE, CommandePlats.Statut.SERVIE)
        if paiement == "CHAMBRE":
            if sejour is None:
                raise ValidationError("Choisissez la chambre du client.")
            ventes = caisse.vendre_commande(session, user, lignes, VenteComptoir.Reglement.CREDIT, sejour=sejour,
                                            observation=observation)
        else:
            ventes = caisse.vendre_commande(session, user, lignes, VenteComptoir.Reglement.COMPTANT, mode=paiement,
                                            observation=observation)
        commande.servie_par, commande.servie_le = user, maintenant()
        commande.encaissement = ventes[0].encaissement
        commande.sejour = sejour if paiement == "CHAMBRE" else None
        commande.save(update_fields=["servie_par", "servie_le", "encaissement", "sejour"])
    journaliser(user, "Commande de plats servie", commande,
                f"reçu n°{commande.encaissement.numero_recu}" if commande.encaissement else f"sur la {sejour}")
    return commande

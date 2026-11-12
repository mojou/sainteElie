from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse

from accounts.models import Role, User
from core.models import Alerte
from core.utils import alerter, journaliser, maintenant, normaliser_telephone
from hotel.models import Client

from .models import CompteClient, PhotoSite

TAILLE_MAX_PHOTO = 1600  # pixels sur le plus grand côté : nette à l'écran, légère sur une connexion lente


def _cle_alerte(compte):
    return f"compte-client-{compte.pk}"


def _alerte_traitee(compte):
    Alerte.objects.filter(cle=_cle_alerte(compte), lue_le__isnull=True).update(lue_le=maintenant())


def fiches_au_meme_numero(compte):
    """Fiches clients de l'hôtel au même numéro de téléphone (comparé chiffre à chiffre)."""
    numero = compte.telephone
    if len(numero) < 6:
        return []
    # Comparé chiffre à chiffre : « +237 699 11 22 33 » et « 699112233 » sont le même numéro.
    return [c for c in Client.objects.exclude(telephone="") if normaliser_telephone(c.telephone) == numero]


def inscrire(nom, telephone, email, mot_de_passe):
    """Crée le compte en ligne d'un client ; son numéro de téléphone est son identifiant."""
    numero = normaliser_telephone(telephone)
    nom = nom.strip()
    with transaction.atomic():
        user = User.objects.create_user(username=numero, password=mot_de_passe, email=email, role=Role.CLIENT,
                                        first_name=nom[:150])
        compte = CompteClient.objects.create(user=user, nom=nom, telephone=numero, email=email)
    alerter(Alerte.Type.AUTRE, f"Nouveau compte client en ligne : {compte}. La réception doit le relier à sa fiche.",
            public=Alerte.Public.RECEPTION, lien=reverse("vitrine:comptes"), cle=_cle_alerte(compte))
    return compte


def relier(compte, user, client=None):
    """La réception confirme que c'est bien ce client : le compte voit désormais ses séjours."""
    if compte.statut != CompteClient.Statut.EN_ATTENTE:
        raise ValidationError("Ce compte a déjà été traité.")
    with transaction.atomic():
        if client is None:
            client = Client.objects.create(nom=compte.nom, telephone=compte.telephone, email=compte.email)
        compte.client = client
        compte.statut = CompteClient.Statut.RELIE
        compte.traite_par = user
        compte.traite_le = maintenant()
        compte.save(update_fields=["client", "statut", "traite_par", "traite_le"])
        _alerte_traitee(compte)
    journaliser(user, "Compte client en ligne relié", client, str(compte))
    return compte


def refuser(compte, user):
    if compte.statut != CompteClient.Statut.EN_ATTENTE:
        raise ValidationError("Ce compte a déjà été traité.")
    with transaction.atomic():
        compte.statut = CompteClient.Statut.REFUSE
        compte.traite_par = user
        compte.traite_le = maintenant()
        compte.save(update_fields=["statut", "traite_par", "traite_le"])
        compte.user.is_active = False
        compte.user.save(update_fields=["is_active"])
        _alerte_traitee(compte)
    journaliser(user, "Compte client en ligne refusé", compte.user, str(compte))


def ajouter_photo(user, rubrique, image, legende=""):
    """Enregistre une photo du site, tournée dans le bon sens et réduite à 1600 pixels (JPEG)."""
    from PIL import Image, ImageOps

    try:
        with Image.open(image) as source:
            photo = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValidationError("Ce fichier n'est pas une photo lisible (JPEG, PNG ou WebP).") from exc
    photo.thumbnail((TAILLE_MAX_PHOTO, TAILLE_MAX_PHOTO))
    tampon = BytesIO()
    photo.save(tampon, "JPEG", quality=82, optimize=True)
    dernier = PhotoSite.objects.filter(rubrique=rubrique).order_by("-ordre").first()
    objet = PhotoSite(rubrique=rubrique, legende=(legende or "").strip(), ajoutee_par=user,
                      ordre=(dernier.ordre + 1) if dernier else 0)
    objet.image.save(f"{rubrique.lower()}.jpg", ContentFile(tampon.getvalue()), save=False)
    objet.save()
    journaliser(user, "Photo ajoutée au site", objet)
    return objet


def retirer_photo(user, photo):
    journaliser(user, "Photo retirée du site", photo)
    photo.image.delete(save=False)
    photo.delete()

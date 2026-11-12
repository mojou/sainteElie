"""Photos et justificatifs envoyés par le personnel : contrôlés, allégés, sans contenu caché."""
import os
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

TAILLE_MAX_ENVOI = 10 * 1024 * 1024  # 10 Mo
EXTENSIONS_JUSTIFICATIF = (".jpg", ".jpeg", ".png", ".webp", ".pdf")


def photo_allegee(fichier, nom="photo", taille=1600):
    """Photo tournée dans le bon sens, réduite à `taille` pixels et réenregistrée en JPEG.

    Le réenregistrement ne garde que l'image : rien d'autre ne passe (script, page web déguisée…).
    """
    from PIL import Image, ImageOps

    if fichier.size and fichier.size > TAILLE_MAX_ENVOI:
        raise ValidationError("Photo trop lourde (10 Mo au plus).")
    try:
        fichier.seek(0)
        with Image.open(fichier) as source:
            photo = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValidationError("Ce fichier n'est pas une photo lisible (JPEG, PNG ou WebP).") from exc
    photo.thumbnail((taille, taille))
    tampon = BytesIO()
    photo.save(tampon, "JPEG", quality=82, optimize=True)
    return ContentFile(tampon.getvalue(), name=f"{nom}.jpg")


def valider_justificatif(fichier):
    """Justificatif de dépense : une photo ou un PDF, rien d'autre (10 Mo au plus)."""
    if not fichier:
        return fichier
    extension = os.path.splitext(fichier.name)[1].lower()
    if extension not in EXTENSIONS_JUSTIFICATIF:
        raise ValidationError("Justificatif : une photo (JPEG, PNG, WebP) ou un PDF seulement.")
    if fichier.size > TAILLE_MAX_ENVOI:
        raise ValidationError("Justificatif trop lourd (10 Mo au plus).")
    fichier.seek(0)
    debut = fichier.read(5)
    fichier.seek(0)
    if extension == ".pdf":
        if debut != b"%PDF-":
            raise ValidationError("Ce fichier n'est pas un vrai PDF.")
        return fichier
    from PIL import Image

    try:
        with Image.open(fichier) as image:
            image.verify()
    except Exception as exc:  # Pillow lève des erreurs variées selon le format
        raise ValidationError("Ce fichier n'est pas une photo lisible.") from exc
    fichier.seek(0)
    return fichier

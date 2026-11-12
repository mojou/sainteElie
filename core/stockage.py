import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.http import FileResponse, Http404
from django.utils.deconstruct import deconstructible


@deconstructible
class StockagePrive(FileSystemStorage):
    """Fichiers archivés hors des dossiers servis par le serveur web.

    L'emplacement est relu dans les réglages à chaque accès (utile pour les tests).
    """

    @property
    def base_location(self):
        return str(settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None


_STOCKAGE = StockagePrive()


def stockage_prive():
    return _STOCKAGE


TYPES_AFFICHABLES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                     ".webp": "image/webp"}


def reponse_fichier(champ, nom=None, en_ligne=True):
    """Renvoie le contenu d'un FileField après contrôle des droits par la vue appelante.

    Seuls une photo ou un PDF s'affichent dans le navigateur ; tout autre fichier est proposé au téléchargement, avec un
    type neutre : un fichier piégé (page web, script) ne s'exécute jamais dans l'application.
    """
    if not champ:
        raise Http404("Document introuvable.")
    try:
        fichier = champ.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Document introuvable.") from exc
    type_ = TYPES_AFFICHABLES.get(os.path.splitext(champ.name)[1].lower())
    reponse = FileResponse(fichier, as_attachment=not (en_ligne and type_), filename=nom or os.path.basename(champ.name),
                           content_type=type_ or "application/octet-stream")
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse

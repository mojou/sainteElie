from functools import lru_cache
from pathlib import Path

from django.conf import settings

from . import modules
from .models import Alerte, Etablissement


@lru_cache(maxsize=1)
def version_statique():
    """Change à chaque mise à jour des styles ou des scripts : ajoutée à leur adresse (?v=…), elle oblige les
    navigateurs à recharger les nouveaux fichiers au lieu de garder l'ancienne version en cache."""
    fichiers = [f for d in settings.STATICFILES_DIRS for f in Path(d).rglob("*") if f.suffix in (".css", ".js")]
    return str(int(max((f.stat().st_mtime for f in fichiers), default=0)))


def site(request):
    etablissement = Etablissement.get()
    contexte = {"etablissement_nom": etablissement.nom, "etablissement": etablissement,
                "montant_a_confirmer": settings.MONTANT_A_CONFIRMER,
                "verrouillage_minutes": settings.VERROUILLAGE_MINUTES}
    if settings.DEBUG:
        version_statique.cache_clear()  # en développement, un style modifié se voit sans redémarrer le serveur
    contexte["version_statique"] = version_statique()
    contexte["modules_ouverts"] = modules.ouverts(request)
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        contexte["nb_alertes"] = Alerte.visibles_par(user).filter(lue_le__isnull=True).count()
        if user.voit_reception or user.est_bar:
            from vitrine.models import CommandePlats

            contexte["nb_commandes_plats"] = CommandePlats.objects.filter(
                statut=CommandePlats.Statut.NOUVELLE).count()
        if user.voit_reception:
            from vitrine.models import CompteClient

            from vitrine.models import DemandeReservation

            contexte["nb_demandes_reservation"] = DemandeReservation.objects.filter(
                statut=DemandeReservation.Statut.NOUVELLE).count()
            contexte["nb_comptes_a_relier"] = CompteClient.objects.filter(
                statut=CompteClient.Statut.EN_ATTENTE).count()
    return contexte

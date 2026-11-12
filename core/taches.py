"""Tâches périodiques : lancées au chargement du tableau de bord et par la commande `taches_quotidiennes`."""
from django.core.cache import cache


def executer_taches_periodiques(force=False):
    """Constate les nuitées, génère les rapports dus, alerte sur les validations en retard.

    Limité à une exécution toutes les 5 minutes, sauf si `force`.
    """
    if not force and not cache.add("taches-periodiques", True, timeout=300):
        return
    from caisse.services import alerter_validations_en_retard, generer_rapports_dus
    from hotel.services import constater_nuitees

    constater_nuitees()
    generer_rapports_dus()
    alerter_validations_en_retard()

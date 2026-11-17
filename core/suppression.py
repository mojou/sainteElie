"""Supprimer un élément saisi (plat, chambre, client, article) sans jamais casser l'historique.

Un élément qui a déjà servi (vendu, réservé, encaissé…) est protégé par la base : on ne le supprime pas, on explique
pourquoi et quoi faire à la place (le retirer de la vente, le désactiver). Un élément jamais utilisé — une erreur de
saisie, un doublon — se supprime d'un geste, après confirmation.
"""
from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError, RestrictedError

from .utils import journaliser


def bloc(url, nom, explication="On ne peut supprimer que ce qui n'a encore jamais servi."):
    """Ce qu'il faut à form_page.html pour afficher le bouton « Supprimer » (avec sa question de confirmation)."""
    return {"url": url, "texte": f"Supprimer {nom}", "question": f"Supprimer {nom} ? C'est définitif.",
            "explication": explication}


def supprimer(request, objet, nom, a_la_place):
    """Supprime l'objet, ou explique pourquoi c'est impossible. Renvoie True si c'est supprimé."""
    libelle = str(objet)
    try:
        with transaction.atomic():
            objet.delete()
    except (ProtectedError, RestrictedError):
        messages.error(request, f"{nom.capitalize()} a déjà servi (séjours, ventes, reçus…) : on ne peut plus le "
                                f"supprimer, l'historique en a besoin. {a_la_place}")
        return False
    journaliser(request.user, f"Suppression : {nom}", libelle)
    messages.success(request, f"C'est supprimé : {libelle}.")
    return True

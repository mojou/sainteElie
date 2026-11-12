"""
Contrôle d'accès par rôle.

Chaque test reçoit l'utilisateur connecté et renvoie True s'il a accès. Les vues
utilisent `acces_requis(test)` (fonctions) ou `AccesMixin` (classes).
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


def gerant(u):
    return u.est_gerant


def direction(u):
    """Gérant et adjoints de direction."""
    return u.est_direction


def reception(u):
    """Réception au sens large : réceptionnistes, chef de réception, direction."""
    return u.voit_reception


def caisse(u):
    """Tient une caisse : réception (chambres, boutique), cuisine / bar, direction."""
    return u.tient_caisse


def suivi_caisse(u):
    """Voir les sessions de caisse : celles qu'on tient, ou toutes quand on les valide (direction, gouvernante)."""
    return u.tient_caisse or u.peut_valider_caisse


def validateur_caisse(u):
    return u.peut_valider_caisse


def extras(u):
    """Porter une consommation sur la note d'une chambre : cuisine / bar et réception."""
    return u.est_bar or reception(u)


def encadrement(u):
    return u.est_encadrement


def stock(u):
    return u.voit_stock


def menage(u):
    """Marquer une chambre comme faite : la réception (qui relaie le ménage), l'encadrement, un compte ménage s'il existe.

    Pas la cuisine / bar.
    """
    return u.departement == "MENAGE" or u.est_reception or u.est_encadrement


def tout_le_monde(u):
    return True


def acces_requis(test):
    def decorateur(vue):
        @login_required
        @wraps(vue)
        def enveloppe(request, *args, **kwargs):
            if not test(request.user):
                raise PermissionDenied("Vous n'avez pas accès à cette page.")
            return vue(request, *args, **kwargs)

        return enveloppe

    return decorateur


class AccesMixin(LoginRequiredMixin):
    acces = staticmethod(tout_le_monde)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.acces(request.user):
            raise PermissionDenied("Vous n'avez pas accès à cette page.")
        return super().dispatch(request, *args, **kwargs)

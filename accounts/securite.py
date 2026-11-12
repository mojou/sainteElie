"""Protection contre les essais au hasard (mot de passe, code PIN) et secrets provisoires.

Un code PIN de 4 chiffres se devine en quelques milliers d'essais : après 5 erreurs de suite, le compte (ou le PIN)
est bloqué 15 minutes et la direction est prévenue. Les compteurs sont en base : ils valent pour tous les postes.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import F
from django.utils import timezone

ESSAIS_MAX = 5
DUREE_BLOCAGE = timedelta(minutes=15)
PIN_TROP_SIMPLES = {"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999", "1234", "4321",
                    "0123", "12345", "123456", "000000", "111111"}


def bloque_jusqua(moment):
    """L'heure de fin du blocage s'il est encore en cours, sinon None."""
    return moment if moment and moment > timezone.now() else None


def _echec(user, champ_echecs, champ_blocage, quoi):
    from core.models import Alerte
    from core.utils import alerter

    comptes = get_user_model().objects.filter(pk=user.pk)
    comptes.update(**{champ_echecs: F(champ_echecs) + 1})
    echecs = comptes.values_list(champ_echecs, flat=True).get()
    setattr(user, champ_echecs, echecs)
    if echecs >= ESSAIS_MAX:
        fin = timezone.now() + DUREE_BLOCAGE
        comptes.update(**{champ_echecs: 0, champ_blocage: fin})
        setattr(user, champ_blocage, fin)
        alerter(Alerte.Type.AUTRE, f"{quoi} de {user} bloqué 15 minutes après {ESSAIS_MAX} essais faux.",
                public=Alerte.Public.GERANT, cle=f"blocage-{champ_echecs}-{user.pk}-{fin:%Y%m%d%H%M}")


def _reussite(user, champ_echecs):
    if getattr(user, champ_echecs):
        get_user_model().objects.filter(pk=user.pk).update(**{champ_echecs: 0})
        setattr(user, champ_echecs, 0)


def echec_connexion(user):
    _echec(user, "echecs_connexion", "connexion_bloquee_jusqua", "Le compte")


def reussite_connexion(user):
    _reussite(user, "echecs_connexion")


def echec_pin(user):
    _echec(user, "echecs_pin", "pin_bloque_jusqua", "Le code PIN")


def reussite_pin(user):
    _reussite(user, "echecs_pin")


def pin_trop_simple(pin):
    return pin in PIN_TROP_SIMPLES or len(set(pin)) == 1

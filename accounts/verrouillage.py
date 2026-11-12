"""Écran verrouillé après quelques minutes sans activité, et relève par code PIN sur un écran partagé.

L'ordinateur de la réception et la tablette du bar servent à plusieurs personnes dans la journée. Sans verrouillage,
une connexion reste ouverte 12 heures : quelqu'un pourrait encaisser ou vendre au nom d'une collègue partie. Après
VERROUILLAGE_MINUTES sans toucher l'écran ni le clavier, l'écran se verrouille (dans le navigateur, et côté serveur
pour toute page demandée ensuite). La personne reprend avec son code PIN ; à la relève, une collègue de la même
équipe touche son prénom et tape son propre code PIN : c'est alors elle qui travaille sur l'écran.
"""
import time

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from .models import Role, User

CLE_ACTIVITE = "derniere_activite"
CLE_VERROU = "ecran_verrouille"
# Pages permises écran verrouillé : l'écran de verrouillage lui-même, le signal d'activité, la déconnexion.
LIBRES = ("/comptes/verrouille/", "/comptes/presence/", "/comptes/deconnexion/", "/comptes/connexion/", "/static/")


def concerne(user):
    """Le personnel connecté. Les clients, sur leur propre téléphone, ne sont pas verrouillés."""
    return settings.VERROUILLAGE_MINUTES > 0 and user.is_authenticated and not user.est_client


def deverrouiller(request):
    request.session.pop(CLE_VERROU, None)
    request.session[CLE_ACTIVITE] = int(time.time())


def collegues_pour_releve(user):
    """Qui peut prendre la place sur cet écran avec son code PIN.

    Seulement le personnel de terrain qui tient une caisse (réception, cuisine / bar), de la même équipe que la
    personne verrouillée, avec son propre code PIN (pas un code provisoire). La direction et les chefs passent par
    leur mot de passe : un code à 4 chiffres ne doit pas ouvrir un compte qui voit tout.
    """
    if user.est_bar:
        roles = [Role.BAR_RESTAURANT]
    elif user.est_reception and user.est_terrain:
        roles = [Role.RECEPTIONNISTE]
    else:
        roles = [Role.RECEPTIONNISTE, Role.BAR_RESTAURANT]
    return (User.objects.filter(is_active=True, is_superuser=False, doit_changer_secret=False, role__in=roles)
            .exclude(pin_hash="").exclude(pk=user.pk).order_by("first_name", "username"))


class VerrouillageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and concerne(user):
            session = request.session
            maintenant = int(time.time())
            derniere = session.get(CLE_ACTIVITE)
            if derniere and maintenant - derniere > settings.VERROUILLAGE_MINUTES * 60:
                session[CLE_VERROU] = True
            if session.get(CLE_VERROU):
                if not request.path.startswith(LIBRES):
                    url = reverse("accounts:verrouille")
                    if request.method == "GET":
                        url += "?" + urlencode({"suite": request.get_full_path()})
                    return redirect(url)
            elif not request.path.startswith("/static/") and (not derniere or maintenant - derniere >= 30):
                # Au plus une écriture toutes les 30 secondes : la session n'est pas réenregistrée à chaque page.
                session[CLE_ACTIVITE] = maintenant
        return self.get_response(request)

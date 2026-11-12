"""Un formulaire envoyé deux fois n'est enregistré qu'une fois ; une page expirée ne montre pas d'erreur technique.

Sur un écran tactile, un double appui sur « Encaisser » ou « Installer le client » envoie le formulaire deux fois :
sans protection, l'argent serait compté deux fois. Chaque formulaire porte un numéro d'envoi unique (ajouté par
app.js) : le second envoi du même numéro n'est pas exécuté, on revient simplement à la page.
"""
from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

DUREE = 6 * 3600  # un numéro d'envoi est retenu 6 heures


def page_precedente(request):
    """La page d'où vient le formulaire (même site seulement), sinon l'accueil."""
    precedente = request.META.get("HTTP_REFERER", "")
    if precedente and url_has_allowed_host_and_scheme(precedente, allowed_hosts={request.get_host()},
                                                      require_https=request.is_secure()):
        from urllib.parse import urlsplit

        morceaux = urlsplit(precedente)
        return morceaux.path + (f"?{morceaux.query}" if morceaux.query else "")
    return reverse("core:accueil")


class EnvoiUniqueMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        numero = request.POST.get("_envoi", "") if request.method == "POST" else ""
        if not numero or len(numero) > 64:
            return self.get_response(request)
        cle = f"envoi-unique:{numero}"
        if not cache.add(cle, 1, DUREE):
            # Déjà reçu : on ne refait rien. Le premier envoi a fait (ou fait encore) le travail.
            if request.path.startswith("/comptes/"):
                # Connexion, écran verrouillé : le premier appui a connecté ou rouvert l'écran, on va à l'accueil.
                return redirect("core:accueil")
            if getattr(request, "user", None) and request.user.is_authenticated:
                messages.info(request, "Vous aviez touché deux fois le bouton : c'est enregistré une seule fois.")
            return redirect(page_precedente(request))
        reponse = self.get_response(request)
        if reponse.status_code != 302:
            cache.delete(cle)  # rien d'enregistré (une erreur à corriger) : le même formulaire peut repartir
        return reponse


def echec_csrf(request, reason=""):
    """Page expirée (bouton touché deux fois pendant une connexion, autre personne connectée sur ce navigateur…).

    Rien n'a été enregistré. Au lieu d'une page d'erreur technique, on revient à la page avec une phrase simple.
    """
    if request.path == reverse("accounts:connexion"):
        if request.user.is_authenticated:
            return redirect("core:accueil")  # le premier appui a déjà connecté la personne
        messages.warning(request, "La page de connexion avait expiré : tapez de nouveau votre identifiant et votre "
                                  "mot de passe.")
        return redirect("accounts:connexion")
    messages.warning(request, "La page avait expiré : rien n'a été enregistré. Vérifiez qui est connecté en haut "
                              "à droite, puis recommencez.")
    return redirect(page_precedente(request))

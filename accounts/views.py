from django import forms
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.permissions import acces_requis, gerant
from core.utils import journaliser

from . import securite, verrouillage
from .forms import ConnexionForm, PinForm, PremiereConnexionForm, UtilisateurForm, verifier_pin
from .models import Role, User


class ConnexionView(auth_views.LoginView):
    template_name = "accounts/connexion.html"
    authentication_form = ConnexionForm
    redirect_authenticated_user = True


@login_required
def mon_compte(request):
    form = PinForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.set_pin(form.cleaned_data["pin"])
        request.user.save(update_fields=["pin_hash"])
        journaliser(request.user, "Code PIN modifié", request.user)
        messages.success(request, "Votre code PIN est enregistré.")
        return redirect("accounts:mon_compte")
    return render(request, "accounts/mon_compte.html", {"form": form})


@acces_requis(gerant)
def utilisateurs(request):
    return render(request, "accounts/utilisateurs.html", {"utilisateurs": User.objects.exclude(role=Role.CLIENT)})


@acces_requis(gerant)
def utilisateur_form(request, pk=None):
    instance = get_object_or_404(User, pk=pk) if pk else None
    form = UtilisateurForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        journaliser(request.user, "Utilisateur modifié" if pk else "Utilisateur créé", user, f"rôle : {user.get_role_display()}")
        messages.success(request, f"Compte de {user} enregistré.")
        return redirect("accounts:utilisateurs")
    return render(request, "form_page.html", {
        "form": form, "titre": f"Modifier {instance}" if instance else "Nouvel utilisateur",
        "retour": "accounts:utilisateurs",
    })


@login_required
def premiere_connexion(request):
    """Compte créé avec un mot de passe provisoire : on choisit le sien et son code PIN avant tout le reste."""
    if not request.user.doit_changer_secret:
        return redirect("core:accueil")
    form = PremiereConnexionForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        user.set_password(form.cleaned_data["mot_de_passe"])
        user.set_pin(form.cleaned_data["pin"])
        user.doit_changer_secret = False
        user.save()
        update_session_auth_hash(request, user)
        journaliser(user, "Mot de passe et code PIN choisis (première connexion)", user)
        messages.success(request, "C'est fait : votre mot de passe et votre code PIN sont à vous seul.")
        return redirect("core:accueil")
    return render(request, "form_page.html", {
        "form": form, "titre": "Première connexion : vos codes",
        "intro": "Votre compte a été créé avec un mot de passe provisoire, connu d'autres personnes. Choisissez votre "
                 "mot de passe et votre code PIN : personne d'autre ne doit les connaître."})


# --- Écran verrouillé et relève par code PIN (voir verrouillage.py) -----------------------------------------
def _suite(request):
    suite = request.POST.get("suite") or request.GET.get("suite") or ""
    if (suite and not suite.startswith("/comptes/") and
            url_has_allowed_host_and_scheme(suite, allowed_hosts={request.get_host()},
                                            require_https=request.is_secure())):
        return suite
    return reverse("core:accueil")


def _verifier_secret(user, secret):
    """Code PIN ; mot de passe pour qui n'a pas encore de code PIN (sinon il resterait bloqué devant l'écran)."""
    if user.a_un_pin:
        verifier_pin(user, secret)
        return
    fin = securite.bloque_jusqua(user.connexion_bloquee_jusqua)
    if fin:
        raise forms.ValidationError(f"Trop d'essais : bloqué jusqu'à {timezone.localtime(fin):%H:%M}.")
    if not user.check_password(secret or ""):
        securite.echec_connexion(user)
        raise forms.ValidationError("Mot de passe incorrect.")
    securite.reussite_connexion(user)


@login_required
def verrouille(request):
    """L'écran verrouillé : reprendre avec son code PIN, ou laisser la place à une collègue (son code PIN à elle)."""
    user = request.user
    if user.est_client:
        return redirect("vitrine:espace")
    request.session[verrouillage.CLE_VERROU] = True
    collegues = verrouillage.collegues_pour_releve(user)
    id_qui = request.POST.get("qui") or request.GET.get("qui") or ""
    if id_qui and not id_qui.isdigit():
        raise Http404
    qui = get_object_or_404(collegues, pk=id_qui) if id_qui else None
    erreur = ""
    if request.method == "POST":
        cible = qui or user
        try:
            _verifier_secret(cible, request.POST.get("secret", ""))
        except forms.ValidationError as exc:
            erreur = exc.messages[0]
        else:
            if cible == user:
                verrouillage.deverrouiller(request)
                return redirect(_suite(request))
            # Relève : la collègue prend l'écran. login() vide la session de la personne précédente.
            login(request, cible, backend="django.contrib.auth.backends.ModelBackend")
            verrouillage.deverrouiller(request)
            journaliser(cible, "Prise de l'écran par code PIN", cible, f"à la place de {user}")
            messages.success(request, f"Bonjour {cible.first_name or cible.username} : c'est maintenant vous qui "
                                      "travaillez sur cet écran.")
            return redirect("core:accueil")
    return render(request, "accounts/verrouille.html", {
        "collegues": collegues, "qui": qui, "erreur": erreur, "suite": _suite(request),
        "cible": qui or user, "par_pin": (qui or user).a_un_pin,
    })


@require_POST
@login_required
def verrouiller(request):
    """Bouton « Changer de personne » : l'écran se verrouille tout de suite."""
    request.session[verrouillage.CLE_VERROU] = True
    return redirect(reverse("accounts:verrouille") + "?suite=" + _suite(request))


@require_POST
def presence(request):
    """Signal d'activité envoyé par la page quand on tape ou touche l'écran sans changer de page (long formulaire).

    Le middleware a déjà noté l'activité ; on dit seulement à la page si l'écran est verrouillé entre-temps.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"verrouille": True})
    if request.session.get(verrouillage.CLE_VERROU):
        return JsonResponse({"verrouille": True})
    return HttpResponse(status=204)

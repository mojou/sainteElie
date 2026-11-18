from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.ConnexionView.as_view(), name="connexion"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="deconnexion"),
    path("mon-compte/", views.mon_compte, name="mon_compte"),
    path("premiere-connexion/", views.premiere_connexion, name="premiere_connexion"),
    path("verrouille/", views.verrouille, name="verrouille"),
    path("verrouiller/", views.verrouiller, name="verrouiller"),
    path("presence/", views.presence, name="presence"),
    path("mot-de-passe/", auth_views.PasswordChangeView.as_view(
        template_name="form_page.html", success_url=reverse_lazy("accounts:mon_compte"),
        extra_context={"titre": "Changer mon mot de passe", "retour": "accounts:mon_compte"}), name="mot_de_passe"),
    path("utilisateurs/", views.utilisateurs, name="utilisateurs"),
    path("utilisateurs/nouveau/", views.utilisateur_form, name="utilisateur_nouveau"),
    path("utilisateurs/<int:pk>/", views.utilisateur_form, name="utilisateur_modifier"),
    path("utilisateurs/<int:pk>/supprimer/", views.utilisateur_supprimer, name="utilisateur_supprimer"),
]

from django.urls import path

from . import views

app_name = "projets"

urlpatterns = [
    path("liste/", views.liste, name="liste"),
    path("projet/nouveau/", views.projet_form, name="projet_nouveau"),
    path("projet/<int:pk>/", views.projet_detail, name="projet"),
    path("projet/<int:pk>/modifier/", views.projet_form, name="projet_modifier"),
    path("mes-taches/", views.mes_taches, name="mes_taches"),
    path("taches/<int:pk>/", views.tache_detail, name="tache"),
    path("taches/<int:pk>/statut/", views.tache_statut, name="tache_statut"),
    path("taches/<int:pk>/priorite/", views.tache_priorite, name="tache_priorite"),
]

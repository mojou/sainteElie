from django.urls import path

from . import views

app_name = "personnel"

urlpatterns = [
    path("mon-espace/", views.mon_espace, name="mon_espace"),
    path("planning/", views.planning, name="planning"),
    path("pointages/", views.pointages, name="pointages"),
    path("employes/", views.employes, name="employes"),
    path("employes/nouveau/", views.employe_form, name="employe_nouveau"),
    path("employes/<int:pk>/", views.employe_form, name="employe_modifier"),
    path("creneaux/", views.creneaux, name="creneaux"),
    path("creneaux/nouveau/", views.creneau_form, name="creneau_nouveau"),
    path("creneaux/<int:pk>/", views.creneau_form, name="creneau_modifier"),
    path("conges/", views.conges, name="conges"),
    path("conges/nouveau/", views.conge_nouveau, name="conge_nouveau"),
    path("conges/<int:pk>/traiter/", views.conge_traiter, name="conge_traiter"),
    path("echanges/nouveau/", views.echange_nouveau, name="echange_nouveau"),
    path("echanges/<int:pk>/traiter/", views.echange_traiter, name="echange_traiter"),
]

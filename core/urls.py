from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("alertes/", views.alertes, name="alertes"),
    path("alertes/<int:pk>/lue/", views.alerte_lue, name="alerte_lue"),
    path("journal/", views.journal, name="journal"),
    path("parametres/", views.parametres, name="parametres"),
    path("parametres/etablissement/", views.etablissement, name="etablissement"),
    path("parametres/modules/", views.modules_vue, name="modules"),
    path("autres-pages/", views.pages, name="pages"),
]

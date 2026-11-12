from django.urls import path

from . import views

app_name = "postes"

urlpatterns = [
    path("", views.poste, name="poste"),
    path("tous/", views.tous, name="tous"),
    path("reception/", views.reception_vue, name="reception"),
    path("reception/recu-imprime/", views.oublier_recu, name="oublier_recu"),
    path("reception/chambre/<int:pk>/", views.chambre_vue, name="chambre"),
    path("reception/arrivee/", views.arrivee, name="arrivee"),
    path("maintenance/", views.maintenance, name="maintenance"),
    path("securite/", views.securite, name="securite"),
]

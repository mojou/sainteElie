from django.urls import path

from . import views

app_name = "rapports"

urlpatterns = [
    path("", views.rapport, name="rapport"),
    path("inventaire-et-rentabilite/", views.inventaire, name="inventaire"),
]

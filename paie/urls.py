from django.urls import path

from . import views

app_name = "paie"

urlpatterns = [
    path("fiches/", views.fiches, name="fiches"),
    path("fiches/<int:pk>/", views.fiche_modifier, name="fiche_modifier"),
    path("fiches/<int:pk>/valider/", views.fiche_valider, name="fiche_valider"),
    path("fiches/<int:pk>/payer/", views.fiche_payer, name="fiche_payer"),
    path("fiches/<int:pk>/bulletin.pdf", views.fiche_pdf, name="fiche_pdf"),
    path("mes-bulletins/", views.mes_bulletins, name="mes_bulletins"),
    path("acomptes/", views.acomptes, name="acomptes"),
]

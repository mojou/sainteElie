from django.urls import path

from . import views

app_name = "caisse"

urlpatterns = [
    path("ma-caisse/", views.ma_caisse, name="ma_caisse"),
    path("ma-caisse/consigne/", views.consigne_ajouter, name="consigne_ajouter"),
    path("ma-caisse/sortie/", views.sortie_nouvelle, name="sortie_nouvelle"),
    path("ventes/", views.ventes, name="ventes"),
    path("ventes/<int:pk>/annuler/", views.vente_annuler, name="vente_annuler"),
    path("avarie/", views.avarie, name="avarie"),
    path("credits/", views.credits, name="credits"),
    path("credits/<int:pk>/regler/", views.credit_regler, name="credit_regler"),
    path("remise/", views.remise_comptage, name="remise_comptage"),
    path("remise/comparaison/", views.remise_comparaison, name="remise_comparaison"),
    path("sessions/", views.sessions, name="sessions"),
    path("sessions/<int:pk>/", views.session_detail, name="session"),
    path("sessions/<int:pk>/recu.pdf", views.recu_remise, name="recu_remise"),
    path("sessions/<int:pk>/cloture-office/", views.remise_comptage, {"cloture_office": True}, name="cloture_office"),
    path("sessions/<int:pk>/cloture-office/comparaison/", views.remise_comparaison, {"cloture_office": True},
         name="cloture_office_comparaison"),
    path("sorties/<int:pk>/justificatif/", views.justificatif, name="justificatif"),
    path("encaissements/<int:pk>/annuler/", views.annuler_encaissement, name="annuler_encaissement"),
    path("encaissements/<int:pk>/recu/", views.recu_client, name="recu_client"),
    path("encaissements/<int:pk>/recu.pdf", views.recu_client_pdf, name="recu_client_pdf"),
    path("encaissements/recherche/", views.recherche_encaissements, name="recherche"),
    path("rapports/", views.rapports, name="rapports"),
    path("rapports/<int:pk>/", views.rapport_detail, name="rapport"),
    path("rapports/<int:pk>/rapport.pdf", views.rapport_pdf, name="rapport_pdf"),
    path("virements/", views.virements, name="virements"),
    path("parametres/", views.parametres, name="parametres"),
    path("parametres/nouveaux/", views.parametres_nouveaux, name="parametres_nouveaux"),
    path("parametres/fond/", views.fond_nouveau, name="fond_nouveau"),
    path("parametres/tiroirs/nouveau/", views.tiroir_form, name="tiroir_nouveau"),
    path("parametres/tiroirs/<int:pk>/", views.tiroir_form, name="tiroir_modifier"),
    path("parametres/tiroirs/<int:pk>/supprimer/", views.tiroir_supprimer, name="tiroir_supprimer"),
]

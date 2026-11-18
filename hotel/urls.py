from django.urls import path

from . import views

app_name = "hotel"

urlpatterns = [
    path("sejours/", views.sejours, name="sejours"),
    path("sejours/nouveau/", views.sejour_form, name="sejour_nouveau"),
    path("sejours/<int:pk>/", views.sejour_detail, name="sejour"),
    path("sejours/<int:pk>/modifier/", views.sejour_form, name="sejour_modifier"),
    path("sejours/<int:pk>/annuler/", views.sejour_annuler, name="sejour_annuler"),
    path("sejours/<int:pk>/no-show/", views.sejour_annuler, {"no_show": True}, name="sejour_no_show"),
    path("sejours/<int:pk>/encaisser/", views.encaisser, name="encaisser"),
    path("sejours/<int:pk>/supprimer/", views.sejour_supprimer, name="sejour_supprimer"),
    path("sejours/<int:pk>/facture/", views.sejour_facture, name="facture"),
    path("sejours/<int:pk>/facture.pdf", views.sejour_facture_pdf, name="facture_pdf"),
    path("sejours/<int:pk>/<str:action>/", views.sejour_action, name="sejour_action"),
    path("chambres/", views.chambres, name="chambres"),
    path("chambres/nouvelle/", views.chambre_form, name="chambre_nouvelle"),
    path("chambres/photos/", views.photos_chambres, name="photos_chambres"),
    path("chambres/<int:pk>/", views.chambre_form, name="chambre_modifier"),
    path("chambres/<int:pk>/supprimer/", views.chambre_supprimer, name="chambre_supprimer"),
    path("clients/", views.clients, name="clients"),
    path("clients/nouveau/", views.client_form, name="client_nouveau"),
    path("clients/<int:pk>/", views.client_detail, name="client"),
    path("clients/<int:pk>/modifier/", views.client_form, name="client_modifier"),
    path("clients/<int:pk>/supprimer/", views.client_supprimer, name="client_supprimer"),
    path("extras/", views.extras_vue, name="extras"),
    path("extras/<int:pk>/annuler/", views.extra_annuler, name="extra_annuler"),
    path("menage/", views.menage_vue, name="menage"),
]

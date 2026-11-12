from django.urls import path

from . import views

app_name = "vitrine"

urlpatterns = [
    path("espace-client/", views.espace, name="espace"),
    path("espace-client/inscription/", views.inscription, name="inscription"),
    path("espace-client/mot-de-passe/", views.MotDePasseClient.as_view(), name="mot_de_passe"),
    path("hotel/comptes-en-ligne/", views.comptes, name="comptes"),
    path("hotel/reservations-en-ligne/", views.demandes, name="demandes"),
    path("reserver/", views.reserver, name="reserver"),
    path("reserver/coordonnees/", views.reserver_coordonnees, name="reserver_coordonnees"),
    path("reserver/demande/<int:pk>/", views.reservation_envoyee, name="reservation_envoyee"),
    path("espace-client/demandes/<int:pk>/annuler/", views.demande_annuler, name="demande_annuler"),
    path("site/", views.page_vitrine, name="site"),
    path("site/photos/<int:pk>/", views.photo, name="photo"),
    path("site/images/article/<int:pk>/", views.image_article, name="image_article"),
    path("site/images/article/<int:pk>/dessin.svg", views.dessin_article, name="dessin_article"),
    path("site/images/chambre/<int:pk>/", views.image_chambre, name="image_chambre"),
    path("parametres/photos-du-site/", views.photos, name="photos"),
    path("parametres/photos-du-site/<int:pk>/retirer/", views.photo_retirer, name="photo_retirer"),
]

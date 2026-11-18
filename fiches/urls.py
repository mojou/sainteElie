from django.urls import path

from . import views

app_name = "fiches"

urlpatterns = [
    path("", views.index, name="index"),
    path("main-courante/<str:categorie>/", views.main_courante, name="main_courante"),
    path("stock/<str:categorie>/", views.fiche_stock, name="stock"),
    path("recette-chambres/", views.hebergement, name="hebergement"),
    path("bar-restaurant/", views.bar_restaurant, name="bar_restaurant"),
    path("chambres-a-faire/", views.chambres_a_faire, name="chambres_a_faire"),
    path("main-courante-gardien/", views.main_courante_gardien, name="main_courante_gardien"),
]

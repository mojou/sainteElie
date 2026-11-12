from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("", views.articles, name="articles"),
    path("articles/nouveau/", views.article_form, name="article_nouveau"),
    path("articles/<int:pk>/", views.article_detail, name="article"),
    path("articles/<int:pk>/modifier/", views.article_form, name="article_modifier"),
    path("mouvements/", views.mouvements, name="mouvements"),
    path("saisie-groupee/", views.saisie_groupee, name="saisie_groupee"),
    path("ecarts-inventaire/", views.ecarts, name="ecarts"),
    path("photos-des-articles/", views.photos, name="photos"),
]

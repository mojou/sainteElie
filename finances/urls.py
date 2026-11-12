from django.urls import path

from . import views

app_name = "finances"

urlpatterns = [
    path("bilan/", views.bilan, name="bilan"),
    path("depenses/", views.depenses, name="depenses"),
    path("depenses/<int:pk>/justificatif/", views.justificatif, name="justificatif"),
]

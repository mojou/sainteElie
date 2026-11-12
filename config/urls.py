import os

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
    path("comptes/", include("accounts.urls")),
    path("hotel/", include("hotel.urls")),
    path("caisse/", include("caisse.urls")),
    path("personnel/", include("personnel.urls")),
    path("paie/", include("paie.urls")),
    path("stock/", include("stock.urls")),
    path("finances/", include("finances.urls")),
    path("projets/", include("projets.urls")),
    path("fiches/", include("fiches.urls")),
    path("poste/", include("postes.urls")),
    path("rapports/", include("rapports.urls")),
    path("", include("vitrine.urls")),
]

# L'administration technique de Django (accès direct aux tables) n'est exposée que si
# DJANGO_ADMIN_URL est défini, par exemple pour une intervention exceptionnelle.
if os.environ.get("DJANGO_ADMIN_URL"):
    urlpatterns.append(path(os.environ["DJANGO_ADMIN_URL"].strip("/") + "/", admin.site.urls))

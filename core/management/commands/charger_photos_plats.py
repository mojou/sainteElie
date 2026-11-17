"""
Met les photos d'illustration des plats (stock/photos_plats/) sur les plats de la carte.

    python manage.py charger_photos_plats              # seulement les plats sans photo
    python manage.py charger_photos_plats --remplacer  # aussi ceux qui ont déjà une photo d'illustration

Ce sont des photos libres de droits (Wikimedia Commons), pas les assiettes de l'hôtel : le site les signale
(« Photos d'illustration », page « Crédits photos » avec l'auteur, la licence et la source de chacune).
Une vraie photo prise par l'hôtel (Photos des plats) n'est jamais remplacée.
"""
import json
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from stock.models import Article

DOSSIER = Path(__file__).resolve().parents[3] / "stock" / "photos_plats"


class Command(BaseCommand):
    help = "Met les photos d'illustration libres de droits sur les plats de la carte (crédits conservés)."

    def add_arguments(self, parser):
        parser.add_argument("--remplacer", action="store_true",
                            help="Remplace aussi une photo d'illustration déjà posée (jamais une vraie photo).")

    def handle(self, *args, **options):
        credits = json.loads((DOSSIER / "credits.json").read_text(encoding="utf-8"))
        posees, gardees, absents = 0, [], []
        for c in credits:
            plat = Article.objects.filter(categorie=Article.Categorie.RESTAURANT, nom=c["plat"]).first()
            if plat is None:
                absents.append(c["plat"])
                continue
            if plat.photo and not (plat.photo_credit and options["remplacer"]):
                gardees.append(plat.nom)  # vraie photo de l'hôtel, ou illustration déjà en place
                continue
            with open(DOSSIER / c["fichier"], "rb") as f:
                plat.photo.save(c["fichier"], File(f), save=False)
            plat.photo_credit = f"« {c['titre']} », {c['auteur']}, {c['licence']}, via Wikimedia Commons"[:300]
            plat.photo_source = c["source"]
            plat.photo_licence_url = c["licence_url"]
            plat.save(update_fields=["photo", "photo_credit", "photo_source", "photo_licence_url"])
            posees += 1
        self.stdout.write(self.style.SUCCESS(f"{posees} photo(s) d'illustration posée(s) sur les plats."))
        if gardees:
            self.stdout.write(f"{len(gardees)} plat(s) avaient déjà une photo : gardée.")
        if absents:
            self.stdout.write(self.style.WARNING("Plats introuvables sur la carte (nom changé ?) : " + ", ".join(absents)))

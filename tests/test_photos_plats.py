"""Photos d'illustration des plats : posées depuis stock/photos_plats/, citées sur le site, remplacées par les vraies."""
import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.urls import reverse

from core import modules
from stock.models import Article

from .base import BaseTest
from .test_securite import photo_png


class PhotosPlatsTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.ndole = Article.objects.create(nom="Ndolé", categorie="RESTAURANT", prix_vente=2500, rubrique="Plats",
                                            description="Feuilles de ndolé et pâte d'arachide.")
        self.riz = Article.objects.create(nom="Riz", categorie="RESTAURANT", prix_vente=500, rubrique="Garnitures")
        self.dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dossier, True)
        for nom in ("ndole.jpg", "riz.jpg"):
            (self.dossier / nom).write_bytes(photo_png().read())
        (self.dossier / "credits.json").write_text(json.dumps([
            {"plat": "Ndolé", "fichier": "ndole.jpg", "titre": "Ndolé camerounais.JPG", "auteur": "PRA",
             "licence": "CC BY 3.0", "licence_url": "https://creativecommons.org/licenses/by/3.0",
             "source": "https://commons.wikimedia.org/wiki/File:Ndol%C3%A9_camerounais.JPG"},
            {"plat": "Riz", "fichier": "riz.jpg", "titre": "Steamed rice.jpg", "auteur": "A. F.", "licence": "CC0",
             "licence_url": "", "source": "https://commons.wikimedia.org/wiki/File:Steamed_rice.jpg"},
            {"plat": "Plat disparu", "fichier": "riz.jpg", "titre": "x", "auteur": "x", "licence": "CC0",
             "licence_url": "", "source": ""},
        ]), encoding="utf-8")

    def charger(self, *options):
        sortie = StringIO()
        with mock.patch("core.management.commands.charger_photos_plats.DOSSIER", self.dossier):
            call_command("charger_photos_plats", *options, stdout=sortie)
        return sortie.getvalue()

    def test_les_photos_d_illustration_sont_posees_et_citees(self):
        sortie = self.charger()
        self.assertIn("2 photo(s) d'illustration posée(s)", sortie)
        self.assertIn("Plat disparu", sortie)
        self.ndole.refresh_from_db()
        self.assertTrue(self.ndole.photo_d_illustration)
        self.assertIn("PRA", self.ndole.photo_credit)
        self.assertIn("CC BY 3.0", self.ndole.photo_credit)
        credits = self.client.get(reverse("vitrine:credits_photos"))
        self.assertContains(credits, "Ndolé")
        self.assertContains(credits, '<a class="lien-discret" href="https://creativecommons.org/licenses/by/3.0"')
        self.assertContains(credits, ">CC BY 3.0</a>")
        self.assertNotContains(credits, "Voir la licence")
        self.assertNotContains(credits, ">Source</a>")
        accueil = self.client.get("/")
        self.assertContains(accueil, "Photos d'illustration")
        self.assertContains(accueil, reverse("vitrine:credits_photos"))
        self.assertContains(accueil, "Feuilles de ndolé et pâte d")
        self.assertContains(self.client.get(reverse("vitrine:commander")), "Photos d'illustration")

    def test_une_vraie_photo_n_est_jamais_remplacee_et_efface_le_credit(self):
        self.charger()
        # Le gérant prend la vraie photo du ndolé : le crédit disparaît, et elle n'est plus remplacée
        self.client.force_login(self.gerant)
        self.client.post(reverse("stock:photos"), {"article": self.ndole.pk, "photo": photo_png()})
        self.ndole.refresh_from_db()
        self.assertTrue(self.ndole.photo)
        self.assertFalse(self.ndole.photo_d_illustration)
        self.assertNotContains(self.client.get(reverse("vitrine:credits_photos")), "Ndolé (photo d'illustration)")
        sortie = self.charger("--remplacer")
        self.ndole.refresh_from_db()
        self.assertEqual(self.ndole.photo_credit, "", "la vraie photo reste")
        self.assertIn("1 photo(s) d'illustration posée(s)", sortie, "seule l'illustration du riz est reposée")

    def test_photos_des_plats_ouverte_meme_module_stock_ferme(self):
        modules.ouvrir([])
        self.client.force_login(self.gerant)
        self.assertEqual(self.client.get(reverse("stock:articles")).status_code, 403)
        page = self.client.get(reverse("stock:photos"), {"categorie": "RESTAURANT"})
        self.assertEqual(page.status_code, 200)
        self.assertContains(self.client.get(reverse("core:pages")), "Photos des plats")
        self.charger()
        self.assertContains(self.client.get(reverse("stock:photos"), {"categorie": "RESTAURANT"}),
                            "Photo d'illustration")

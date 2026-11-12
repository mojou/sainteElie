"""Failles corrigées lors de l'audit : chacune a son test."""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Role, User
from caisse import services as caisse
from caisse.models import SortieCaisse
from core.models import Alerte

from .base import BaseTest


def photo_png(couleur=(200, 160, 70)):
    from PIL import Image

    tampon = BytesIO()
    Image.new("RGB", (1200, 900), couleur).save(tampon, "PNG")
    return SimpleUploadedFile("photo.png", tampon.getvalue(), content_type="image/png")


class EssaisAuHasardTests(BaseTest):
    def test_cinq_mots_de_passe_faux_bloquent_le_compte_15_minutes(self):
        for _ in range(5):
            self.client.post(reverse("accounts:connexion"), {"username": "aicha", "password": "faux"})
        reponse = self.client.post(reverse("accounts:connexion"), {"username": "aicha", "password": "Demo1234!x"})
        self.assertContains(reponse, "Trop d")
        self.assertFalse(reponse.wsgi_request.user.is_authenticated, "même le bon mot de passe attend la fin du blocage")
        self.assertTrue(Alerte.objects.filter(message__contains="bloqué").exists(), "le gérant est prévenu")

    def test_cinq_codes_pin_faux_bloquent_la_signature(self):
        from django import forms

        from accounts.forms import verifier_pin

        for _ in range(5):
            with self.assertRaises(forms.ValidationError):
                verifier_pin(self.chef, "0000")
        with self.assertRaisesMessage(forms.ValidationError, "bloqué"):
            verifier_pin(self.chef, "1234")  # le bon code, mais trop tard
        self.chef.refresh_from_db()
        self.assertIsNotNone(self.chef.pin_bloque_jusqua)

    def test_un_bon_code_remet_le_compteur_a_zero(self):
        from django import forms

        from accounts.forms import verifier_pin

        for _ in range(4):
            with self.assertRaises(forms.ValidationError):
                verifier_pin(self.chef, "0000")
        verifier_pin(self.chef, "1234")
        self.chef.refresh_from_db()
        self.assertEqual(self.chef.echecs_pin, 0)


class AccesEtFichiersTests(BaseTest):
    def test_la_cuisine_ne_voit_pas_les_recus_de_la_reception(self):
        session = self.ouvrir()
        recu = self.encaisser_especes(session, self.sejour(), 10000)
        barman = self.utilisateur("jean", Role.BAR_RESTAURANT)
        self.client.force_login(barman)
        self.assertEqual(self.client.get(reverse("caisse:recu_client", args=[recu.pk])).status_code, 403)
        self.client.force_login(self.serge)
        self.assertEqual(self.client.get(reverse("caisse:recu_client", args=[recu.pk])).status_code, 200,
                         "la réception réimprime les reçus des clients")

    def test_un_justificatif_piege_est_refuse(self):
        self.client.force_login(self.aicha)
        self.ouvrir()
        piege = SimpleUploadedFile("facture.html", b"<script>alert(1)</script>", content_type="text/html")
        faux_pdf = SimpleUploadedFile("facture.pdf", b"<html><script>alert(1)</script>", content_type="application/pdf")
        for fichier in (piege, faux_pdf):
            with self.subTest(fichier=fichier.name):
                reponse = self.client.post(reverse("caisse:sortie_nouvelle"), {
                    "type": "DEPENSE", "montant": 2000, "motif": "Glaçons", "justificatif": fichier})
                self.assertEqual(reponse.status_code, 200)
        self.assertFalse(SortieCaisse.objects.exists())
        self.client.post(reverse("caisse:sortie_nouvelle"),
                         {"type": "DEPENSE", "montant": 2000, "motif": "Glaçons", "justificatif": photo_png()})
        sortie = SortieCaisse.objects.get()
        reponse = self.client.get(reverse("caisse:justificatif", args=[sortie.pk]))
        self.assertEqual((reponse.status_code, reponse["Content-Type"]), (200, "image/png"))
        reponse.close()

    def test_un_fichier_d_un_autre_type_n_est_jamais_affiche(self):
        from django.core.files.base import ContentFile

        from core.stockage import reponse_fichier

        session = self.ouvrir()
        sortie = caisse.creer_sortie(session, self.aicha, "DEPENSE", 1000, "Ancien fichier")
        sortie.justificatif.save("ancien.html", ContentFile(b"<script>alert(1)</script>"), save=True)
        reponse = reponse_fichier(sortie.justificatif)
        self.assertEqual(reponse["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", reponse["Content-Disposition"])
        reponse.close()

    def test_inscriptions_limitees_par_appareil(self):
        from django.core.cache import cache

        cache.clear()
        for n in range(6):
            reponse = self.client.post(reverse("vitrine:inscription"), {
                "nom": f"Client {n}", "telephone": f"69900000{n}", "mot_de_passe": "Sejour2026!", "confirmation": "Sejour2026!"})
            self.client.post(reverse("accounts:deconnexion"))
        self.assertContains(reponse, "Trop de comptes")
        self.assertEqual(User.objects.filter(role=Role.CLIENT).count(), 5)
        cache.clear()

    def test_le_gerant_ne_cree_pas_de_client_et_impose_un_nouveau_mot_de_passe(self):
        self.client.force_login(self.gerant)
        page = self.client.get(reverse("accounts:utilisateur_nouveau"))
        self.assertNotContains(page, 'value="CLIENT"')
        self.client.post(reverse("accounts:utilisateur_nouveau"), {
            "username": "nadia", "first_name": "Nadia", "last_name": "F", "role": "RECEPTIONNISTE", "is_active": "on",
            "mot_de_passe": "Provisoire-2026"})
        self.assertTrue(User.objects.get(username="nadia").doit_changer_secret)


class PhotosTests(BaseTest):
    def test_photo_d_article_visible_au_stock_et_a_la_vente(self):
        from caisse.models import Tiroir
        from stock.models import Article

        biere = Article.objects.create(nom="33 EXPORT", code="65CL", categorie="BAR", prix_vente=1000)
        self.client.force_login(self.gerant)
        self.client.post(reverse("stock:article_modifier", args=[biere.pk]), {
            "nom": "33 EXPORT", "code": "65CL", "categorie": "BAR", "ordre": 0, "unite": "unité", "seuil_alerte": 0,
            "prix_achat": 0, "prix_vente": 1000, "suivi_stock": "on", "actif": "on", "photo": photo_png()})
        biere.refresh_from_db()
        self.assertTrue(biere.photo.name.endswith(".jpg"), "réenregistrée en JPEG allégé")
        self.assertContains(self.client.get(reverse("stock:articles")), biere.photo_url)

        tiroir_bar = Tiroir.objects.create(nom="Cuisine / Bar", poste=Tiroir.Poste.BAR)
        barman = self.utilisateur("jean", Role.BAR_RESTAURANT)
        caisse.ouvrir_session(barman, tiroir_bar, "MATIN", 0)
        self.client.force_login(barman)
        self.assertContains(self.client.get(reverse("caisse:ventes")), f'<img src="{biere.photo_url}"')
        reponse = self.client.get(biere.photo_url)
        self.assertEqual((reponse.status_code, reponse["Content-Type"]), (200, "image/jpeg"))
        reponse.close()

    def test_photo_de_chambre_et_de_plat_sur_la_page_d_accueil(self):
        from stock.models import Article

        self.client.force_login(self.gerant)
        self.client.post(reverse("hotel:chambre_modifier", args=[self.chambre.pk]), {
            "numero": "101", "categorie": "SIMPLE", "tarif_nuit": 15000, "capacite": 2, "statut": "LIBRE",
            "description": "", "active": "on", "photo": photo_png()})
        self.chambre.refresh_from_db()
        plat = Article.objects.create(nom="Poulet DG", categorie="RESTAURANT", prix_vente=6500)
        plat.photo.save("plat.jpg", photo_png(), save=True)
        self.client.post(reverse("accounts:deconnexion"))
        page = self.client.get("/")
        self.assertContains(page, self.chambre.photo_url)
        self.assertContains(page, "Notre carte")
        self.assertContains(page, plat.photo_url)

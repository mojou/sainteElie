"""Photos des chambres : plusieurs par chambre, prises au téléphone, visibles sur la réservation en ligne."""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Role
from core.utils import aujourd_hui, format_fcfa
from hotel.models import Chambre, PhotoChambre

from .base import BaseTest
from .test_securite import photo_png

URL = reverse("hotel:photos_chambres")


class PhotosChambresTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.gerant)

    def envoyer(self, *fichiers, chambre=None):
        return self.client.post(URL, {"chambre": (chambre or self.chambre).pk, "photos": list(fichiers)}, follow=True)

    def test_plusieurs_photos_d_un_coup_puis_visibles_partout(self):
        page = self.envoyer(photo_png(), photo_png((40, 90, 160)))
        self.assertContains(page, "2 photos ajoutées à la chambre 101")
        photos = list(self.chambre.photos.all())
        self.assertEqual(len(photos), 2)
        self.assertTrue(all(p.image.name.endswith(".jpg") for p in photos), "réenregistrées en JPEG allégé")
        # Vignette dans la liste des chambres
        self.assertContains(self.client.get(reverse("hotel:chambres")), photos[0].url)
        # Publiques : la page d'accueil et la réservation en ligne les montrent, sans connexion
        self.client.post(reverse("accounts:deconnexion"))
        image = self.client.get(photos[1].url)
        self.assertEqual((image.status_code, image["Content-Type"]), (200, "image/jpeg"))
        image.close()
        self.assertContains(self.client.get("/"), photos[0].url)
        j = aujourd_hui() + timedelta(days=1)
        resa = self.client.get(reverse("vitrine:reserver"), {"arrivee": j.isoformat(),
                                                             "depart": (j + timedelta(days=1)).isoformat(),
                                                             "personnes": 1})
        self.assertContains(resa, "2 photos · faites glisser")
        for p in photos:
            self.assertContains(resa, p.url)

    def test_un_faux_fichier_photo_est_refuse(self):
        piege = SimpleUploadedFile("photo.jpg", b"<script>alert(1)</script>", content_type="image/jpeg")
        page = self.envoyer(piege, photo_png())
        self.assertContains(page, "Pas des photos lisibles")
        self.assertContains(page, "1 photo ajoutée")
        self.assertEqual(self.chambre.photos.count(), 1, "seule la vraie photo est gardée")

    def test_limites(self):
        page = self.envoyer(*[photo_png() for _ in range(11)])
        self.assertContains(page, "10 photos au plus à la fois")
        self.assertEqual(self.chambre.photos.count(), 0)
        for _ in range(PhotoChambre.MAX_PAR_CHAMBRE):
            PhotoChambre.objects.create(chambre=self.chambre, image="chambres/x.jpg")
        page = self.envoyer(photo_png())
        self.assertContains(page, "retirez-en avant d")
        self.assertNotContains(page, "Ajouter des photos\n", msg_prefix="plus de bouton d'ajout quand c'est plein")
        page = self.client.post(URL, {"chambre": self.chambre.pk}, follow=True)
        self.assertContains(page, "Choisissez au moins une photo")

    def test_mettre_en_premier_et_retirer(self):
        self.envoyer(photo_png(), photo_png((10, 10, 10)))
        premiere, seconde = self.chambre.photos.all()
        self.client.post(URL, {"action": "premiere", "photo": seconde.pk})
        self.assertEqual(self.chambre.photo_principale, seconde)
        fichier = Path(settings.PRIVATE_MEDIA_ROOT) / premiere.image.name
        self.assertTrue(fichier.exists())
        self.client.post(URL, {"action": "retirer", "photo": premiere.pk})
        self.assertEqual(list(self.chambre.photos.all()), [seconde])
        self.assertFalse(fichier.exists(), "le fichier est supprimé aussi")

    def test_qui_peut_ajouter_des_photos(self):
        for user, code in [(self.aicha, 403), (self.utilisateur("adelaide", Role.GOUVERNANTE), 200),
                           (self.utilisateur("julio", Role.ADJOINT), 200)]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(URL).status_code, code, user.username)
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.post(URL, {"chambre": self.chambre.pk, "photos": [photo_png()]}).status_code, 403)
        self.assertEqual(PhotoChambre.objects.count(), 0)

    def test_photo_d_une_chambre_retiree_du_service_n_est_plus_publique(self):
        self.envoyer(photo_png())
        photo = self.chambre.photos.get()
        Chambre.objects.filter(pk=self.chambre.pk).update(active=False)
        self.client.post(reverse("accounts:deconnexion"))
        self.assertEqual(self.client.get(photo.url).status_code, 404)

    def test_sans_photo_le_site_montre_un_dessin_et_la_page_le_signale(self):
        page = self.client.get(URL)
        self.assertContains(page, "Encore sans photo sur le site")
        self.assertContains(page, "Sans photo (1)")


class VoirLaChambreTests(BaseTest):
    """Le client voit la chambre avant de s'engager : sur le site, et à la réception avant de payer."""

    def setUp(self):
        super().setUp()
        self.j = aujourd_hui() + timedelta(days=2)
        self.recherche = {"arrivee": self.j.isoformat(), "depart": (self.j + timedelta(days=2)).isoformat(),
                          "personnes": 1}
        self.photos = [PhotoChambre.objects.create(chambre=self.chambre, image=f"chambres/p{i}.jpg", ordre=i)
                       for i in range(3)]

    def test_sur_le_site_voir_la_chambre_puis_reserver(self):
        liste = self.client.get(reverse("vitrine:reserver"), self.recherche)
        self.assertContains(liste, "Voir la chambre")
        self.assertContains(liste, reverse("vitrine:reserver_chambre"))
        page = self.client.get(reverse("vitrine:reserver_chambre"), {**self.recherche, "type": "SIMPLE-25000"})
        for p in self.photos:
            self.assertContains(page, p.url)
        self.assertContains(page, "data-galerie")
        self.assertContains(page, format_fcfa(50000))  # 2 nuits à 25 000
        self.assertContains(page, "Réserver cette chambre")
        self.assertContains(page, f"{reverse('vitrine:reserver_coordonnees')}?arrivee={self.j.isoformat()}")
        self.assertContains(page, "type=SIMPLE-25000")

    def test_type_inconnu_ou_plus_libre_renvoie_a_la_liste(self):
        reponse = self.client.get(reverse("vitrine:reserver_chambre"), {**self.recherche, "type": "SUITE-99999"})
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("vitrine:reserver"), reponse["Location"])

    def test_sans_photo_le_dessin_et_un_mot(self):
        PhotoChambre.objects.all().delete()
        page = self.client.get(reverse("vitrine:reserver_chambre"), {**self.recherche, "type": "SIMPLE-25000"})
        self.assertContains(page, "arrivent bientôt")

    def test_a_la_reception_on_montre_la_chambre_avant_de_payer(self):
        self.client.force_login(self.aicha)
        fiche = self.client.get(reverse("postes:chambre", args=[self.chambre.pk]))
        self.assertContains(fiche, "Montrez la chambre au client avant qu")
        self.assertContains(fiche, self.photos[0].url)
        arrivee = self.client.get(reverse("postes:arrivee"), {"chambre": self.chambre.pk})
        self.assertContains(arrivee, 'id="photos-chambres"')
        self.assertContains(arrivee, self.photos[2].url)
        self.assertContains(arrivee, 'id="montrer-chambre"')

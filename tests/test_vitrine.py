"""Page d'accueil publique, comptes clients en ligne et leur espace."""
import re

from django.urls import reverse

from accounts.models import Role, User
from core.models import Alerte
from vitrine.models import CompteClient

from .base import BaseTest


class PageAccueilTests(BaseTest):
    def test_un_visiteur_voit_la_presentation_et_les_deux_boutons(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        for texte in ("Créer un compte", "Se connecter", "Nos chambres et suites", "Orange Money", "MTN MoMo"):
            self.assertContains(page, texte)
        self.assertNotContains(page, "Tableau de bord", msg_prefix="aucun écran de gestion pour un visiteur")
        self.assertEqual(self.client.get(reverse("caisse:ma_caisse")).status_code, 302, "la gestion reste fermée")

    def test_le_personnel_arrive_toujours_sur_sa_gestion(self):
        self.client.force_login(self.gerant)
        self.assertContains(self.client.get("/"), "Tableau de bord")
        self.client.post(reverse("accounts:deconnexion"))
        self.assertContains(self.client.get("/"), "Créer un compte", msg_prefix="après déconnexion : la page publique")


class EspaceClientTests(BaseTest):
    def inscrire(self, telephone="+237 699 00 00 00", **autres):
        donnees = {"nom": "M. Kamga", "telephone": telephone, "email": "", "mot_de_passe": "Sejour2026!",
                   "confirmation": "Sejour2026!", **autres}
        return self.client.post(reverse("vitrine:inscription"), donnees, follow=True)

    def test_inscription_puis_attente_puis_suivi_du_sejour(self):
        reponse = self.inscrire()
        self.assertRedirects(reponse, reverse("vitrine:espace"))
        self.assertContains(reponse, "presque prêt")
        compte = CompteClient.objects.get()
        self.assertEqual((compte.telephone, compte.user.username, compte.user.role), ("699000000", "699000000", "CLIENT"))
        self.assertTrue(Alerte.objects.filter(message__contains="Nouveau compte client").exists())

        # Tant que la réception n'a pas confirmé, aucun séjour n'est montré.
        s = self.sejour()
        self.encaisser_especes(self.ouvrir(), s, 30000)
        self.assertNotContains(self.client.get(reverse("vitrine:espace")), "Chambre 101")

        # La réception reconnaît M. Kamga (même numéro) et relie le compte à sa fiche.
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("vitrine:comptes"))
        self.assertContains(page, "Même numéro")
        self.client.post(reverse("vitrine:comptes"), {"compte": compte.pk, "client": self.client_hotel.pk,
                                                      "action": "relier"})
        compte.refresh_from_db()
        self.assertEqual((compte.statut, compte.client), ("RELIE", self.client_hotel))

        self.client.force_login(compte.user)
        page = self.client.get(reverse("vitrine:espace"))
        self.assertContains(page, "Chambre 101")
        self.assertContains(page, "Reste à payer")
        self.assertContains(page, "Mes paiements")

    def test_connexion_avec_le_numero_ecrit_comme_on_veut(self):
        self.inscrire()
        self.client.post(reverse("accounts:deconnexion"))
        reponse = self.client.post(reverse("accounts:connexion"), {"username": "699 00 00 00", "password": "Sejour2026!"},
                                   follow=True)
        self.assertRedirects(reponse, reverse("vitrine:espace"))

    def test_un_client_ne_voit_jamais_la_gestion(self):
        self.inscrire()
        for url in ["/hotel/menage/", "/caisse/ma-caisse/", "/poste/", "/comptes/mon-compte/", "/hotel/comptes-en-ligne/"]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse("vitrine:espace"))
        self.assertRedirects(self.client.get("/"), reverse("vitrine:espace"))

    def test_numero_deja_utilise_et_mots_de_passe_differents(self):
        self.inscrire()
        self.client.post(reverse("accounts:deconnexion"))
        self.assertContains(self.inscrire("699000000"), "existe déjà")
        self.assertContains(self.inscrire("677111111", confirmation="Autre2026!"), "pas identiques")

    def test_refus_et_clients_absents_des_listes_du_personnel(self):
        self.inscrire()
        compte = CompteClient.objects.get()
        self.client.force_login(self.gerant)
        self.assertNotContains(self.client.get(reverse("accounts:utilisateurs")), "699000000")
        from projets.views import TacheForm

        self.assertFalse(TacheForm().fields["assigne_a"].queryset.filter(role=Role.CLIENT).exists())
        self.client.post(reverse("vitrine:comptes"), {"compte": compte.pk, "action": "refuser"})
        self.assertFalse(User.objects.get(pk=compte.user_id).is_active)

    def test_le_personnel_n_a_pas_d_espace_client(self):
        self.client.force_login(self.aicha)
        self.assertRedirects(self.client.get(reverse("vitrine:espace")), reverse("core:accueil"),
                             fetch_redirect_response=False)


class PhotosSiteTests(BaseTest):
    @staticmethod
    def image_png(largeur=2400, hauteur=1600):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        tampon = BytesIO()
        Image.new("RGB", (largeur, hauteur), (18, 48, 90)).save(tampon, "PNG")
        return SimpleUploadedFile("facade.png", tampon.getvalue(), content_type="image/png")

    def test_sans_photo_la_page_montre_les_illustrations(self):
        page = self.client.get("/")
        for rubrique in ("hotel", "chambres", "reception", "plats", "parking"):
            with self.subTest(rubrique=rubrique):
                self.assertContains(page, f"img/vitrine/{rubrique}.svg")
        self.assertContains(page, "Le parking")

    def test_le_gerant_ajoute_une_photo_qui_remplace_l_illustration(self):
        from PIL import Image

        from vitrine.models import PhotoSite

        self.client.force_login(self.gerant)
        self.assertContains(self.client.get(reverse("vitrine:site")), "Découvrez", msg_prefix="aperçu pour le personnel")
        reponse = self.client.post(reverse("vitrine:photos"), {"rubrique": "HOTEL", "legende": "La façade",
                                                               "images": self.image_png()})
        self.assertRedirects(reponse, reverse("vitrine:photos"))
        photo = PhotoSite.objects.get()
        photo.image.open("rb")
        with Image.open(photo.image) as img:
            self.assertEqual((max(img.size), img.format), (1600, "JPEG"), "photo allégée pour les connexions lentes")
        photo.image.close()

        self.client.post(reverse("accounts:deconnexion"))
        page = self.client.get("/")
        for texte in (photo.url, "La façade", "avec-photo", "img/vitrine/parking.svg"):
            self.assertContains(page, texte)
        self.assertNotContains(page, "img/vitrine/hotel.svg", msg_prefix="la vraie photo remplace l'illustration")
        reponse = self.client.get(photo.url)
        self.assertEqual((reponse.status_code, reponse["Content-Type"]), (200, "image/jpeg"))
        reponse.close()

        self.client.force_login(self.gerant)
        self.client.post(reverse("vitrine:photo_retirer", args=[photo.pk]))
        self.assertFalse(PhotoSite.objects.exists())

    def test_un_fichier_qui_n_est_pas_une_photo_et_acces_reserve_au_gerant(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from vitrine.models import PhotoSite

        self.client.force_login(self.gerant)
        reponse = self.client.post(reverse("vitrine:photos"), {
            "rubrique": "PLATS", "images": SimpleUploadedFile("plat.jpg", b"pas une image", content_type="image/jpeg")})
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(PhotoSite.objects.exists())
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.get(reverse("vitrine:photos")).status_code, 403)


class PageAnimeeTests(BaseTest):
    def test_l_administration_ajoute_plusieurs_photos_qui_defilent_dans_le_bandeau(self):
        from vitrine.models import PhotoSite

        adjoint = self.utilisateur("julio", Role.ADJOINT)
        self.client.force_login(adjoint)
        self.assertContains(self.client.get(reverse("core:accueil")), "Photos du site", msg_prefix="lien dans le menu")
        envoi = [PhotosSiteTests.image_png(), PhotosSiteTests.image_png(1600, 1200)]
        reponse = self.client.post(reverse("vitrine:photos"), {"rubrique": "CHAMBRES", "images": envoi}, follow=True)
        self.assertContains(reponse, "2 photo(s) ajoutée(s)")
        self.assertEqual(PhotoSite.objects.count(), 2)

        self.client.post(reverse("accounts:deconnexion"))
        page = self.client.get("/").content.decode()
        self.assertIn("data-diaporama", page)
        self.assertEqual(len(re.findall(r'class="v-diapo[ "]', page)), 2, "les deux photos défilent dans le bandeau")
        self.assertIn("v-apparait", page)
        self.assertIn("data-defile", page)

    def test_les_prix_les_plus_bas_defilent(self):
        from stock.models import Article

        Article.objects.create(nom="Riz", categorie="RESTAURANT", rubrique="Garnitures", prix_vente=500)
        Article.objects.create(nom="Poulet DG", categorie="RESTAURANT", rubrique="Plats chauds", prix_vente=3500)
        Article.objects.create(nom="Poulet rôti", categorie="RESTAURANT", rubrique="Plats chauds", prix_vente=3000)
        Article.objects.create(nom="33 EXPORT", code="65CL", categorie="BAR", prix_vente=1000)
        page = self.client.get("/").content.decode()
        self.assertIn('class="v-defile"', page)
        self.assertRegex(page, r"animation-duration: (2\d|[3-9]\d)s", "il défile à une vitesse lisible")
        texte = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page.split('class="v-defile"')[1].split("</ul>")[0]))
        for attendu in ("Chambres dès 25", "Plats chauds dès 3", "Garnitures 500", "Boissons du bar dès 1"):
            self.assertIn(attendu, texte.replace("\u202f", " ").replace("\xa0", " "))

    def test_sans_photo_pas_de_diaporama_mais_la_page_reste_complete(self):
        page = self.client.get("/").content.decode()
        self.assertNotIn("data-diaporama", page)
        self.assertIn("Créer un compte", page)

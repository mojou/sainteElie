"""Caisse tactile : une commande de plusieurs articles, une seule question « Comment le client paie ? », un seul reçu."""
from django.urls import reverse

from caisse import services as caisse
from caisse.models import Encaissement, VenteComptoir
from core.utils import format_fcfa
from hotel.models import Client, Extra

from .test_comptoir import BaseComptoir


class CommandeTests(BaseComptoir):
    def commander(self, donnees, user=None):
        self.client.force_login(user or self.jean)
        return self.client.post(reverse("caisse:ventes"), donnees)

    def test_une_table_un_seul_recu(self):
        self.client.force_login(self.jean)
        reponse = self.client.post(reverse("caisse:ventes"), {f"q_{self.biere.pk}": 4, f"q_{self.plat.pk}": 2,
                                                              "paiement": "ORANGE_MONEY"}, follow=True)
        self.assertRedirects(reponse, reverse("caisse:ventes"))
        self.assertContains(reponse, "6 articles, 17")
        enc = Encaissement.objects.get(nature="VENTE")
        self.assertContains(reponse, f"Reçu n°{enc.numero_recu}")
        self.assertContains(reponse, "C'est enregistré")
        self.assertContains(reponse, reverse("caisse:recu_client", args=[enc.pk]), msg_prefix="imprimer le reçu")
        self.assertNotContains(self.client.get(reverse("caisse:ventes")), "C'est enregistré",
                               msg_prefix="l'écran de fin ne revient pas au rechargement")
        self.assertEqual((enc.montant, enc.mode), (4 * 1000 + 2 * 6500, "ORANGE_MONEY"))
        self.assertEqual(enc.ventes.count(), 2, "chaque article garde sa ligne de main courante")
        self.refresh(self.biere)
        self.assertEqual(self.biere.quantite, 24 - 4)
        self.assertIn("4 × 33 EXPORT", enc.libelle)
        recu = self.client.get(reverse("caisse:recu_client", args=[enc.pk]))
        for texte in ("33 EXPORT", "Poulet DG", format_fcfa(13000), "Dix-sept mille francs CFA"):
            self.assertContains(recu, texte)

    def test_sur_la_chambre_un_extra_par_article(self):
        s = self.sejour()
        self.commander({f"q_{self.biere.pk}": 2, f"q_{self.plat.pk}": 1, "paiement": "CHAMBRE", "sejour": s.pk})
        self.assertEqual(sorted(Extra.objects.values_list("description", "montant")),
                         [("1 × Poulet DG", 6500), ("2 × 33 EXPORT 65CL", 2000)])
        self.assertFalse(Encaissement.objects.filter(nature="VENTE").exists(), "rien n'entre dans la caisse")

    def test_chambre_obligatoire(self):
        reponse = self.commander({f"q_{self.biere.pk}": 1, "paiement": "CHAMBRE"})
        self.assertContains(reponse, "Touchez la chambre du client")
        self.assertContains(reponse, f'{{"{self.biere.pk}": 1}}', msg_prefix="la commande revient à l'écran")
        self.assertFalse(VenteComptoir.objects.exists())

    def test_credit_a_un_nouveau_client(self):
        self.commander({f"q_{self.whisky.pk}": 1, "paiement": "CREDIT", "nouveau_client": "M. Etoa",
                        "telephone": "677000000"})
        client = Client.objects.get(nom="M. Etoa")
        self.assertEqual(caisse.dette_client(client), 4000)
        reponse = self.commander({f"q_{self.whisky.pk}": 1, "paiement": "CREDIT", "nouveau_client": "Sans tel"})
        self.assertContains(reponse, "Le téléphone est obligatoire")

    def test_offert_seulement_avec_un_motif(self):
        self.assertContains(self.commander({f"q_{self.biere.pk}": 1, "paiement": "OFFERT"}), "à qui c&#x27;est offert")
        self.commander({f"q_{self.biere.pk}": 1, "paiement": "OFFERT", "observation": "Anniversaire du gérant"})
        self.assertEqual(VenteComptoir.objects.get().reglement, "OFFERT")

    def test_commande_vide_ou_article_d_une_autre_caisse(self):
        self.assertContains(self.commander({"paiement": "ESPECES"}), "La commande est vide")
        self.assertContains(self.commander({f"q_{self.savon.pk}": 1, "paiement": "ESPECES"}),
                            "plus en vente à cette caisse")
        self.assertContains(self.commander({f"q_{self.biere.pk}": "abc", "paiement": "ESPECES"}), "illisible")
        self.assertFalse(VenteComptoir.objects.exists())

    def test_tout_ou_rien_si_le_stock_manque(self):
        reponse = self.commander({f"q_{self.biere.pk}": 2, f"q_{self.whisky.pk}": 50, "paiement": "ESPECES"})
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(VenteComptoir.objects.exists())
        self.refresh(self.biere)
        self.assertEqual(self.biere.quantite, 24, "la bière n'est pas sortie du stock non plus")

    def test_annuler_une_ligne_annule_toute_la_commande(self):
        ventes = caisse.vendre_commande(self.bar, self.jean, [(self.biere, 3), (self.whisky, 1)], "COMPTANT")
        self.client.force_login(self.jean)
        page = self.client.get(reverse("caisse:vente_annuler", args=[ventes[0].pk]))
        self.assertContains(page, "Annuler toute la commande")
        self.client.post(reverse("caisse:vente_annuler", args=[ventes[0].pk]), {"motif": "Mauvais client"})
        self.assertEqual(VenteComptoir.objects.filter(annulee=True).count(), 2)
        self.refresh(self.biere, self.whisky)
        self.assertEqual((self.biere.quantite, self.whisky.quantite), (24, 10), "tout est remis en stock")
        self.assertEqual(Encaissement.objects.filter(nature="ANNULATION").count(), 1)
        self.bar.refresh_from_db()
        self.assertEqual(self.bar.especes_attendues, 10000)

    def test_les_tuiles_et_les_plus_vendus(self):
        from stock.models import Article
        from stock.services import enregistrer_mouvement

        for i in range(12):
            a = Article.objects.create(nom=f"Boisson {i}", categorie="BAR", prix_vente=500 + i)
            enregistrer_mouvement(a, self.gerant, "INVENTAIRE", 5)
        caisse.vendre(self.bar, self.jean, self.whisky, 2, "COMPTANT")
        self.client.force_login(self.jean)
        page = self.client.get(reverse("caisse:ventes")).content.decode()
        self.assertIn("Les plus vendus", page)
        self.assertIn(f'data-id="{self.whisky.pk}"', page)
        self.assertIn(">Plats</button>", page, "les plats ont leur famille")
        self.assertIn("Sur sa chambre", page)
        self.assertIn("Restaurant · Bar", page, "le point de vente du bar porte son nom")
        self.assertNotIn(">Chambres</a>", page, "le bar n'a pas le lien vers les chambres")

    def test_la_reception_voit_la_boutique(self):
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("caisse:ventes")).content.decode()
        self.assertIn("<strong>Boutique</strong>", page)
        self.assertIn("Brosse à dent", page)
        self.assertNotIn("33 EXPORT", page, "pas de boissons du bar à la boutique")
        self.assertIn(">Chambres</a>", page, "retour au plan des chambres")
        self.assertIn(reverse("caisse:ventes"), self.client.get(reverse("postes:reception")).content.decode())


class ImagesDesArticlesTests(BaseComptoir):
    """Chaque article a une image : sa photo, sinon un dessin fait par l'application."""

    def test_chaque_article_a_un_dessin_valide(self):
        import xml.etree.ElementTree as ET
        from io import StringIO

        from django.core.management import call_command

        from stock.illustrations import illustration_svg
        from stock.models import Article

        call_command("charger_saint_elie", stdout=StringIO())
        Article.objects.create(nom="Savon <script>", categorie="MAGASIN", prix_vente=0)
        for article in Article.objects.all():
            with self.subTest(article=article.nom):
                ET.fromstring(illustration_svg(article))
        self.assertNotIn("<script", illustration_svg(Article.objects.get(nom="Savon <script>")))

    def test_le_dessin_est_servi_et_la_photo_le_remplace(self):
        from .test_securite import photo_png

        reponse = self.client.get(self.biere.image_url)
        self.assertEqual((reponse.status_code, reponse["Content-Type"]), (200, "image/svg+xml"))
        self.assertIn(b"<svg", reponse.content)
        self.client.force_login(self.jean)
        self.assertContains(self.client.get(reverse("caisse:ventes")), self.biere.image_url)

        self.client.force_login(self.gerant)
        page = self.client.get(reverse("stock:photos"))
        self.assertContains(page, 'capture="environment"')
        self.client.post(reverse("stock:photos"), {"article": self.biere.pk, "photo": photo_png()})
        self.biere.refresh_from_db()
        self.assertTrue(self.biere.photo)
        self.assertEqual(self.biere.image_url, self.biere.photo_url)
        self.client.post(reverse("stock:photos"), {"article": self.biere.pk, "action": "retirer"})
        self.biere.refresh_from_db()
        self.assertFalse(self.biere.photo)
        self.assertIn("dessin.svg", self.biere.image_url)

    def test_le_bar_ne_photographie_pas(self):
        self.client.force_login(self.jean)
        self.assertEqual(self.client.get(reverse("stock:photos")).status_code, 403)

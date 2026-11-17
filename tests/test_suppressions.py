"""Modifier et supprimer ce qui a été saisi (plats, chambres, clients, articles), sans jamais casser l'historique."""
from datetime import timedelta

from django.urls import reverse

from core import modules
from core.utils import aujourd_hui
from hotel.models import Chambre, Client
from stock.models import Article
from vitrine import commandes

from .test_comptoir import BaseComptoir


class CarteDesPlatsTests(BaseComptoir):
    def test_ajouter_modifier_retirer_et_supprimer_un_plat(self):
        modules.ouvrir([])  # la carte reste ouverte même quand le module Stock est fermé
        self.client.force_login(self.gerant)
        self.assertContains(self.client.get(reverse("stock:carte")), "Poulet DG")
        # Ajouter
        self.client.post(reverse("stock:plat_nouveau"), {
            "nom": "Eru", "rubrique": "Plats chauds", "description": "Feuilles d'eru, waterleaf, viande et peau.",
            "prix_vente": 3000, "ordre": 5, "actif": "on"})
        eru = Article.objects.get(nom="Eru")
        self.assertEqual((eru.categorie, eru.suivi_stock, eru.prix_vente), ("RESTAURANT", False, 3000))
        self.assertContains(self.client.get(reverse("vitrine:site")), "Feuilles d")  # sur le site tout de suite
        # Modifier le prix et la composition
        self.client.post(reverse("stock:plat_modifier", args=[eru.pk]), {
            "nom": "Eru", "rubrique": "Plats chauds", "description": "Eru et waterleaf.", "prix_vente": 3500,
            "ordre": 5, "actif": "on"})
        eru.refresh_from_db()
        self.assertEqual((eru.prix_vente, eru.description), (3500, "Eru et waterleaf."))
        # Un prix vide est refusé
        page = self.client.post(reverse("stock:plat_modifier", args=[eru.pk]), {
            "nom": "Eru", "rubrique": "Plats chauds", "prix_vente": 0, "ordre": 5, "actif": "on"})
        self.assertContains(page, "Donnez le prix du plat")
        # Retirer de la vente : il disparaît de la commande en ligne
        self.client.post(reverse("stock:plat_modifier", args=[eru.pk]), {
            "nom": "Eru", "rubrique": "Plats chauds", "prix_vente": 3500, "ordre": 5})
        self.assertNotContains(self.client.get(reverse("vitrine:commander")), 'aria-label="Nombre de Eru"')
        # Supprimer : jamais vendu, donc c'est possible
        reponse = self.client.post(reverse("stock:plat_supprimer", args=[eru.pk]), follow=True)
        self.assertContains(reponse, "supprimé")
        self.assertFalse(Article.objects.filter(nom="Eru").exists())

    def test_un_plat_deja_vendu_ou_commande_ne_se_supprime_pas(self):
        commandes.creer_commande({self.plat.pk: 1}, commandes.moment(aujourd_hui() + timedelta(days=1),
                                                                     commandes.time(12)),
                                 "SUR_PLACE", "Client", "677000000")
        self.client.force_login(self.gerant)
        reponse = self.client.post(reverse("stock:plat_supprimer", args=[self.plat.pk]), follow=True)
        self.assertContains(reponse, "déjà servi")
        self.assertContains(reponse, "décochez « En vente »")
        self.assertTrue(Article.objects.filter(pk=self.plat.pk).exists())

    def test_seuls_les_responsables_modifient_la_carte(self):
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.get(reverse("stock:carte")).status_code, 403)
        self.assertEqual(self.client.post(reverse("stock:plat_supprimer", args=[self.plat.pk])).status_code, 403)
        self.assertTrue(Article.objects.filter(pk=self.plat.pk).exists())
        self.client.force_login(self.jean)
        self.assertEqual(self.client.get(reverse("stock:plat_modifier", args=[self.plat.pk])).status_code, 403)

    def test_un_article_deja_compte_au_stock_ne_se_supprime_pas(self):
        self.client.force_login(self.gerant)
        self.client.post(reverse("stock:article_supprimer", args=[self.biere.pk]))
        self.assertTrue(Article.objects.filter(pk=self.biere.pk).exists(), "inventaire de la veille : protégé")
        neuf = Article.objects.create(nom="Erreur de saisie", categorie="BAR", prix_vente=100)
        self.client.post(reverse("stock:article_supprimer", args=[neuf.pk]))
        self.assertFalse(Article.objects.filter(pk=neuf.pk).exists())


class ChambresClientsTests(BaseComptoir):
    def test_chambre_jamais_reservee_se_supprime_les_autres_non(self):
        self.client.force_login(self.gerant)
        neuve = Chambre.objects.create(numero="999", tarif_nuit=10000)
        self.assertContains(self.client.get(reverse("hotel:chambre_modifier", args=[neuve.pk])), "Supprimer cette chambre")
        self.client.post(reverse("hotel:chambre_supprimer", args=[neuve.pk]))
        self.assertFalse(Chambre.objects.filter(pk=neuve.pk).exists())
        self.sejour()
        reponse = self.client.post(reverse("hotel:chambre_supprimer", args=[self.chambre.pk]), follow=True)
        self.assertContains(reponse, "décochez « Active »")
        self.assertTrue(Chambre.objects.filter(pk=self.chambre.pk).exists())
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.post(reverse("hotel:chambre_supprimer", args=[self.chambre.pk])).status_code, 403)

    def test_client_doublon_se_supprime_client_qui_a_sejourne_non(self):
        doublon = Client.objects.create(nom="M. Kamga (doublon)", telephone="699000001")
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("hotel:client_modifier", args=[doublon.pk]))
        self.assertNotContains(page, "Supprimer ce client", msg_prefix="la réception corrige, la direction supprime")
        self.assertEqual(self.client.post(reverse("hotel:client_supprimer", args=[doublon.pk])).status_code, 403)
        self.client.force_login(self.gerant)
        self.assertContains(self.client.get(reverse("hotel:client_modifier", args=[doublon.pk])), "Supprimer ce client")
        self.client.post(reverse("hotel:client_supprimer", args=[doublon.pk]))
        self.assertFalse(Client.objects.filter(pk=doublon.pk).exists())
        self.sejour()
        reponse = self.client.post(reverse("hotel:client_supprimer", args=[self.client_hotel.pk]), follow=True)
        self.assertContains(reponse, "déjà servi")
        self.assertTrue(Client.objects.filter(pk=self.client_hotel.pk).exists())

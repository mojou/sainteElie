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


class FormulaireAvecPhotoTests(BaseComptoir):
    """Ouvrir la fiche d'un plat qui a déjà une photo (rangée hors du site, sans adresse publique) ne plante pas."""

    def test_modifier_un_plat_qui_a_une_photo(self):
        from .test_securite import photo_png

        self.plat.photo.save("plat.jpg", photo_png(), save=True)
        self.client.force_login(self.gerant)
        page = self.client.get(reverse("stock:plat_modifier", args=[self.plat.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "déjà enregistrée")
        self.assertContains(page, "Le retirer")
        self.assertEqual(self.client.get(reverse("stock:article_modifier", args=[self.biere.pk])).status_code, 200)
        self.biere.photo.save("biere.jpg", photo_png(), save=True)
        self.assertEqual(self.client.get(reverse("stock:article_modifier", args=[self.biere.pk])).status_code, 200)
        # Retirer la photo depuis la fiche
        self.client.post(reverse("stock:plat_modifier", args=[self.plat.pk]), {
            "nom": self.plat.nom, "rubrique": "Plats", "prix_vente": 6500, "ordre": 1, "actif": "on",
            "photo-clear": "on"})
        self.plat.refresh_from_db()
        self.assertFalse(self.plat.photo)


class ListesModifierSupprimerTests(BaseComptoir):
    """Chaque liste propose « Modifier » et « Supprimer » ; ce qui a servi reste, avec une explication."""

    def test_les_listes_montrent_modifier_et_supprimer(self):
        self.client.force_login(self.gerant)
        for url in (reverse("hotel:chambres"), reverse("hotel:clients"), reverse("accounts:utilisateurs"),
                    reverse("caisse:parametres"), reverse("stock:carte")):
            page = self.client.get(url)
            self.assertContains(page, "Modifier", msg_prefix=url)
            self.assertContains(page, ">Supprimer</button>", msg_prefix=url)
        self.sejour(statut="RESERVE", arrivee=aujourd_hui() + timedelta(days=3))
        page = self.client.get(reverse("hotel:sejours"), {"vue": "reserves"})
        self.assertContains(page, ">Modifier</a>")
        self.assertContains(page, ">Supprimer</button>")

    def test_photos_de_la_chambre_sur_sa_page(self):
        from hotel.models import PhotoChambre

        PhotoChambre.objects.create(chambre=self.chambre, image="chambres/x.jpg")
        self.client.force_login(self.gerant)
        page = self.client.get(reverse("hotel:chambre_modifier", args=[self.chambre.pk]))
        self.assertContains(page, "Photos de la chambre")
        self.assertContains(page, "Ajouter, changer ou retirer des photos")
        self.assertContains(page, self.chambre.photos.get().url)

    def test_supprimer_un_compte(self):
        from accounts.models import Role, User

        erreur = self.utilisateur("erreur", Role.RECEPTIONNISTE)
        self.client.force_login(self.gerant)
        self.client.post(reverse("accounts:utilisateur_supprimer", args=[erreur.pk]))
        self.assertFalse(User.objects.filter(pk=erreur.pk).exists())
        # Aïcha a tenu une caisse : son compte reste, on le désactive
        reponse = self.client.post(reverse("accounts:utilisateur_supprimer", args=[self.aicha.pk]), follow=True)
        self.assertContains(reponse, "Compte actif")
        self.assertTrue(User.objects.filter(pk=self.aicha.pk).exists())
        # Pas soi-même
        self.client.post(reverse("accounts:utilisateur_supprimer", args=[self.gerant.pk]))
        self.assertTrue(User.objects.filter(pk=self.gerant.pk).exists())

    def test_supprimer_un_sejour(self):
        from hotel.models import Sejour

        erreur = self.sejour(statut="RESERVE", arrivee=aujourd_hui() + timedelta(days=5))
        en_cours = self.sejour(chambre=Chambre.objects.create(numero="102", tarif_nuit=25000))
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.post(reverse("hotel:sejour_supprimer", args=[erreur.pk])).status_code, 403)
        self.client.force_login(self.gerant)
        self.client.post(reverse("hotel:sejour_supprimer", args=[erreur.pk]))
        self.assertFalse(Sejour.objects.filter(pk=erreur.pk).exists())
        reponse = self.client.post(reverse("hotel:sejour_supprimer", args=[en_cours.pk]), follow=True)
        self.assertContains(reponse, "reste dans l")
        self.assertTrue(Sejour.objects.filter(pk=en_cours.pk).exists())
        # Une réservation déjà payée (acompte) ne s'efface pas
        paye = self.sejour(statut="RESERVE", arrivee=aujourd_hui() + timedelta(days=9),
                           chambre=Chambre.objects.create(numero="103", tarif_nuit=25000))
        self.encaisser_especes(self.session, paye, 5000)
        self.client.post(reverse("hotel:sejour_supprimer", args=[paye.pk]))
        self.assertTrue(Sejour.objects.filter(pk=paye.pk).exists())

    def test_supprimer_une_caisse(self):
        from caisse.models import Tiroir

        neuve = Tiroir.objects.create(nom="Caisse en trop")
        self.client.force_login(self.gerant)
        self.client.post(reverse("caisse:tiroir_supprimer", args=[neuve.pk]))
        self.assertFalse(Tiroir.objects.filter(pk=neuve.pk).exists())
        self.client.post(reverse("caisse:tiroir_supprimer", args=[self.tiroir.pk]))
        self.assertTrue(Tiroir.objects.filter(pk=self.tiroir.pk).exists(), "elle a des sessions : gardée")

"""Mise en service : les données d'essai s'effacent, la configuration réelle de l'hôtel reste."""
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command

from accounts.models import Role, User
from caisse import services as caisse
from caisse.models import Encaissement, SessionCaisse, Tiroir, VenteComptoir
from core.models import Compteur, JournalAction
from hotel.models import Chambre, Client, Sejour
from personnel.models import Employe
from stock.models import Article, MouvementStock
from stock.services import enregistrer_mouvement

from .test_comptoir import BaseComptoir


class EffacerDonneesTestTests(BaseComptoir):
    def setUp(self):
        super().setUp()
        sejour = self.sejour()
        Chambre.objects.filter(pk=self.chambre.pk).update(statut=Chambre.Statut.OCCUPEE)
        caisse.vendre(self.bar, self.jean, self.biere, 2, "COMPTANT")
        erreur = caisse.vendre(self.bar, self.jean, self.whisky, 1, "COMPTANT")
        caisse.annuler_vente(erreur, self.jean, "erreur de saisie")  # le reçu d'annulation protège l'original
        self.encaisser_especes(self.session, sejour, 10000)
        User.objects.create_user("690000000", password="Demo1234!", role=Role.CLIENT)
        # Ce compte a déjà ses propres codes : on n'y touche pas.
        self.gerant.set_password("MonVraiCode2026")
        self.gerant.set_pin("4821")
        self.gerant.save()
        self.jean.set_password("Demo1234!")
        self.jean.save()
        Employe.objects.create(nom="Carine", departement="MENAGE", poste="Chambres", salaire_base=75000)  # démo
        Employe.objects.create(nom="Gardien", departement="SECURITE", poste="Gardien", salaire_base=82000)  # vrai
        Article.objects.create(nom="Draps 2 places", categorie=Article.Categorie.MAGASIN)
        self.vieux_recu = Path(settings.PRIVATE_MEDIA_ROOT) / "remises" / "remise-99.pdf"
        self.vieux_recu.parent.mkdir(parents=True, exist_ok=True)
        self.vieux_recu.write_bytes(b"%PDF essai")

    def lancer(self, *options):
        sortie = StringIO()
        call_command("effacer_donnees_test", *options, stdout=sortie)
        return sortie.getvalue()

    def test_sans_oui_rien_n_est_efface(self):
        sortie = self.lancer()
        self.assertIn("Aperçu seulement", sortie)
        self.assertIn("ventes (bar, restaurant, boutique)", sortie)
        self.assertTrue(VenteComptoir.objects.exists())
        self.assertTrue(self.vieux_recu.exists())

    def test_efface_l_activite_et_garde_la_configuration(self):
        self.lancer("--oui")
        for modele in (VenteComptoir, Encaissement, SessionCaisse, Sejour, Client, MouvementStock, JournalAction,
                       Compteur):
            self.assertFalse(modele.objects.exists(), modele.__name__)
        self.assertFalse(User.objects.filter(role=Role.CLIENT).exists(), "comptes clients du site effacés")
        self.assertFalse(self.vieux_recu.exists(), "reçu PDF d'une remise effacée : supprimé")
        # Gardé : chambres (libres), catalogue (stock à 0), caisses, personnel.
        self.chambre.refresh_from_db()
        self.assertEqual((self.chambre.statut, self.chambre.tarif_nuit), (Chambre.Statut.LIBRE, 25000))
        self.biere.refresh_from_db()
        self.assertEqual((self.biere.quantite, self.biere.prix_vente), (0, 1000))
        self.assertFalse(Article.objects.filter(nom="Draps 2 places").exists(), "article inventé par la démo")
        self.assertEqual(Tiroir.objects.count(), 2)
        self.assertEqual(sorted(Employe.objects.filter(user__isnull=True).values_list("nom", "salaire_base")),
                         [("Carine", 0), ("Gardien", 82000)], "salaire de démo remis à 0, vrai salaire gardé")

    def test_mots_de_passe_de_demonstration_remplaces(self):
        sortie = self.lancer("--oui")
        self.jean.refresh_from_db()
        self.assertFalse(self.jean.check_password("Demo1234!"))
        self.assertTrue(self.jean.doit_changer_secret, "il choisit ses codes à la première connexion")
        self.assertFalse(self.jean.a_un_pin)
        code = next(ligne.split()[-1] for ligne in sortie.splitlines() if ligne.strip().startswith("jean "))
        self.assertTrue(self.jean.check_password(code), "le code provisoire affiché est le bon")
        self.gerant.refresh_from_db()
        self.assertTrue(self.gerant.check_password("MonVraiCode2026"), "codes déjà personnels : gardés")
        self.assertFalse(self.gerant.doit_changer_secret)
        self.assertNotIn("gerant ", sortie)

    def test_l_application_marche_apres_le_menage(self):
        self.lancer("--oui")
        self.client.force_login(self.gerant)
        for url in ("/", "/rapports/", "/rapports/inventaire-et-rentabilite/", "/stock/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        session = caisse.ouvrir_session(self.mireille, Tiroir.objects.get(nom="Bar"), "MATIN", 10000)
        with self.assertRaisesMessage(ValidationError, "Stock insuffisant"):  # inventaire de départ d'abord
            caisse.vendre(session, self.mireille, self.biere, 1, "COMPTANT")
        enregistrer_mouvement(self.biere, self.gerant, "INVENTAIRE", 24)
        caisse.vendre(session, self.mireille, self.biere, 1, "COMPTANT")
        self.assertEqual(list(Encaissement.objects.values_list("numero_recu", flat=True)), [1],
                         "les reçus repartent du numéro 1")

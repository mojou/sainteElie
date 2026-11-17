"""Commander des plats sur le site : choix, confirmation par l'hôtel, service et encaissement à la caisse Cuisine / Bar."""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client as Navigateur
from django.test import override_settings
from django.urls import reverse

from accounts.models import Role
from caisse.models import Encaissement, VenteComptoir
from core import modules
from core.models import Alerte
from core.utils import aujourd_hui
from hotel.models import Sejour
from stock.models import Article
from vitrine import commandes
from vitrine.models import CommandePlats

from .test_comptoir import BaseComptoir

URL = reverse("vitrine:commander")
SUIVI = reverse("vitrine:commandes_plats")


class CommandePlatsTests(BaseComptoir):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.ndole = Article.objects.create(nom="Ndolé", categorie="RESTAURANT", prix_vente=3000, rubrique="Plats")
        self.demain = aujourd_hui() + timedelta(days=1)

    def donnees(self, **autres):
        d = {f"q_{self.plat.pk}": "2", f"q_{self.ndole.pk}": "1", "jour": self.demain.isoformat(), "heure": "12:30",
             "service": "SUR_PLACE", "nom": "Mme Ewodo", "telephone": "+237 677 12 34 56", "message": "Sans piment"}
        d.update(autres)
        return d

    def commander(self, navigateur=None, **autres):
        return (navigateur or self.client).post(URL, self.donnees(**autres))

    # --- Le client -------------------------------------------------------------------------------------------------
    def test_le_client_commande_et_suit_sa_commande(self):
        page = self.client.get(URL)
        self.assertContains(page, "Poulet DG")
        self.assertContains(page, "Ndolé")
        reponse = self.commander()
        commande = CommandePlats.objects.get()
        self.assertRedirects(reponse, reverse("vitrine:commande_envoyee", args=[commande.pk]))
        self.assertEqual([(ligne.article, ligne.quantite, ligne.prix_unitaire) for ligne in commande.lignes.all()],
                         [(self.plat, 2, 6500), (self.ndole, 1, 3000)])
        self.assertEqual((commande.total, commande.telephone, commande.statut), (16000, "677123456", "NOUVELLE"))
        self.assertTrue(Alerte.objects.filter(cle=f"commande-plats-{commande.pk}").exists())
        envoyee = self.client.get(reponse["Location"])
        self.assertContains(envoyee, f"Commande n°{commande.pk} envoyée")
        self.assertContains(envoyee, "2 × Poulet DG")
        self.assertEqual(Navigateur().get(reponse["Location"]).status_code, 404, "privée : seul l'auteur la voit")

    def test_erreurs_de_saisie(self):
        cas = [
            ({f"q_{self.plat.pk}": "", f"q_{self.ndole.pk}": ""}, "Choisissez au moins un plat"),
            ({f"q_{self.plat.pk}": "21"}, "20 portions au plus"),
            ({f"q_{self.plat.pk}": "abc"}, "Une quantité est illisible"),
            ({"q_999999": "1"}, "plus à la carte"),
            ({"service": "EN_CHAMBRE", "chambre": ""}, "Donnez votre numéro de chambre"),
            ({"service": "EN_CHAMBRE", "chambre": "999"}, "n&#x27;existe pas"),
            ({"jour": (aujourd_hui() + timedelta(days=40)).isoformat()}, "30 jours"),
            ({"heure": "23:30"}, "Sélectionnez un choix valide"),
        ]
        for autres, message in cas:
            page = self.commander(**autres)
            self.assertEqual(page.status_code, 200, autres)
            self.assertContains(page, message, msg_prefix=str(autres))
        self.assertFalse(CommandePlats.objects.exists())

    def test_trop_tot_pour_la_cuisine(self):
        with mock.patch("vitrine.commandes.maintenant", return_value=commandes.moment(self.demain, commandes.time(12))):
            page = self.commander(heure="12:30")
        self.assertContains(page, "45 minutes au moins")
        self.assertFalse(CommandePlats.objects.exists())

    def test_un_plat_retire_de_la_carte_ne_se_commande_plus(self):
        Article.objects.filter(pk=self.ndole.pk).update(actif=False)
        self.assertContains(self.commander(), "plus à la carte")
        self.assertNotContains(self.client.get(URL), "Ndolé")

    def test_protections(self):
        self.assertRedirects(self.commander(site_web="spam"), reverse("vitrine:site"), fetch_redirect_response=False)
        self.assertFalse(CommandePlats.objects.exists(), "piège à robots")
        navigateur = Navigateur(enforce_csrf_checks=True)
        navigateur.post(URL, self.donnees())
        self.assertFalse(CommandePlats.objects.exists(), "jeton anti-falsification exigé")
        with override_settings(ENTETE_IP_CLIENT="HTTP_X_REAL_IP"):
            for _ in range(5):
                self.client.post(URL, self.donnees(), HTTP_X_REAL_IP="41.1.1.1")
            self.assertContains(self.client.post(URL, self.donnees(), HTTP_X_REAL_IP="41.1.1.1"), "Trop de commandes")
            self.assertEqual(self.client.post(URL, self.donnees(), HTTP_X_REAL_IP="41.2.2.2").status_code, 302)
        with mock.patch.object(commandes, "COMMANDES_PAR_HEURE_MAX", 6):
            self.assertContains(self.commander(REMOTE_ADDR="9.9.9.9"), "Beaucoup de commandes")

    def test_le_client_avec_compte_annule_sa_commande_tant_qu_elle_n_est_pas_confirmee(self):
        from vitrine import services as vitrine

        compte = vitrine.inscrire("Mme Ewodo", "677123456", "", "MotDePasse-2026")
        autre = vitrine.inscrire("Autre", "690000002", "", "MotDePasse-2026")
        self.client.force_login(compte.user)
        self.assertContains(self.client.get(URL), 'value="Mme Ewodo"')
        self.commander()
        commande = CommandePlats.objects.get()
        self.assertEqual(commande.compte, compte)
        self.assertContains(self.client.get(reverse("vitrine:espace")), f"Commande n°{commande.pk}")
        self.client.force_login(autre.user)
        self.client.post(reverse("vitrine:commande_annuler", args=[commande.pk]))
        commande.refresh_from_db()
        self.assertEqual(commande.statut, "NOUVELLE", "pas la sienne")
        self.client.force_login(compte.user)
        self.client.post(reverse("vitrine:commande_annuler", args=[commande.pk]))
        commande.refresh_from_db()
        self.assertEqual(commande.statut, "ANNULEE")

    # --- L'hôtel ---------------------------------------------------------------------------------------------------
    def test_confirmer_puis_servir_et_encaisser(self):
        self.commander()
        commande = CommandePlats.objects.get()
        recep = Navigateur()
        recep.force_login(self.aicha)
        self.assertContains(recep.get(reverse("postes:reception")), "1 commande de plats en ligne à confirmer")
        recep.post(SUIVI, {"commande": commande.pk, "action": "confirmer"})
        reponse = recep.post(SUIVI, {"commande": commande.pk, "action": "confirmer"}, follow=True)
        self.assertContains(reponse, "déjà été traitée")
        commande.refresh_from_db()
        self.assertEqual(commande.statut, "CONFIRMEE")
        # La réception n'encaisse pas les plats : c'est la caisse Cuisine / Bar (pas de bouton, et refusé si forcé)
        self.assertNotContains(recep.get(SUIVI), "Servie et encaissée")
        page = recep.post(SUIVI, {"commande": commande.pk, "action": "servir", "paiement": "ESPECES"}, follow=True)
        self.assertContains(page, "Les plats se vendent à la caisse Cuisine / Bar")
        commande.refresh_from_db()
        self.assertEqual(commande.statut, "CONFIRMEE", "rien n'a changé")
        # La cuisine sert et encaisse : un seul reçu pour toute la commande
        self.client.force_login(self.jean)
        self.assertContains(self.client.get(SUIVI), "Servie et encaissée")
        page = self.client.post(SUIVI, {"commande": commande.pk, "action": "servir", "paiement": "ORANGE_MONEY"},
                                follow=True)
        commande.refresh_from_db()
        self.assertEqual(commande.statut, "SERVIE")
        self.assertContains(page, f"reçu n°{commande.encaissement.numero_recu}")
        self.assertEqual((commande.encaissement.montant, commande.encaissement.mode), (16000, "ORANGE_MONEY"))
        ventes = VenteComptoir.objects.filter(encaissement=commande.encaissement)
        self.assertEqual(sorted((v.article.nom, v.quantite) for v in ventes), [("Ndolé", 1), ("Poulet DG", 2)])
        self.assertTrue(all(v.observation == f"Commande en ligne n°{commande.pk}" for v in ventes))
        self.client.post(SUIVI, {"commande": commande.pk, "action": "servir", "paiement": "ESPECES"})
        self.assertEqual(Encaissement.objects.filter(nature="VENTE").count(), 1, "servie une seule fois")

    def test_servir_sur_la_note_de_la_chambre(self):
        sejour = self.sejour()
        self.commander(service="EN_CHAMBRE", chambre="101")
        commande = CommandePlats.objects.get()
        commandes.confirmer(commande, self.aicha)
        self.client.force_login(self.jean)
        self.assertContains(self.client.get(SUIVI), f'<option value="{sejour.pk}" selected>')
        self.client.post(SUIVI, {"commande": commande.pk, "action": "servir", "paiement": "CHAMBRE",
                                 "sejour": sejour.pk})
        commande.refresh_from_db()
        sejour.refresh_from_db()
        self.assertEqual((commande.statut, commande.sejour, commande.encaissement), ("SERVIE", sejour, None))
        self.assertEqual(sejour.total_extras, 16000, "les plats sont sur la note de la chambre")

    def test_refuser_et_annuler_demandent_un_motif(self):
        self.commander()
        commande = CommandePlats.objects.get()
        self.client.force_login(self.aicha)
        self.assertContains(self.client.post(SUIVI, {"commande": commande.pk, "action": "refuser"}, follow=True),
                            "Dites pourquoi")
        self.client.post(SUIVI, {"commande": commande.pk, "action": "refuser", "motif": "Ndolé épuisé"})
        commande.refresh_from_db()
        self.assertEqual((commande.statut, commande.motif), ("REFUSEE", "Ndolé épuisé"))
        self.commander()
        autre = CommandePlats.objects.exclude(pk=commande.pk).get()
        commandes.confirmer(autre, self.aicha)
        self.client.post(SUIVI, {"commande": autre.pk, "action": "annuler", "motif": "Client pas venu"})
        autre.refresh_from_db()
        self.assertEqual(autre.statut, "ANNULEE")

    def test_qui_voit_les_plats_commandes(self):
        self.assertEqual(self.client.get(SUIVI).status_code, 302, "anonyme : connexion")
        for user, code in [(self.aicha, 200), (self.jean, 200), (self.gerant, 200),
                           (self.utilisateur("adelaide", Role.GOUVERNANTE), 200)]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(SUIVI).status_code, code, user.username)

    def test_ouvert_meme_quand_les_autres_modules_sont_fermes(self):
        modules.ouvrir([])
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.client.force_login(self.jean)
        self.assertRedirects(self.client.get(reverse("postes:poste")), SUIVI)
        self.assertEqual(self.client.get(SUIVI).status_code, 200)
        self.assertEqual(self.client.get(reverse("caisse:ventes")).status_code, 403)

    def test_effacer_les_donnees_d_essai_efface_les_commandes(self):
        from io import StringIO

        from django.core.management import call_command

        self.commander()
        call_command("effacer_donnees_test", "--oui", stdout=StringIO())
        self.assertFalse(CommandePlats.objects.exists())
        self.assertFalse(Sejour.objects.exists())

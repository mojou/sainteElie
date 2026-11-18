"""Réservation depuis la page d'accueil : chambres libres, demande, confirmation par la réception."""
from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse

from accounts.models import Role, User
from core.models import Alerte
from core.utils import aujourd_hui
from hotel.models import Chambre, Client, Sejour
from vitrine import reservations
from vitrine.models import CompteClient, DemandeReservation

from .base import BaseTest


class ReservationEnLigneTests(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.j = aujourd_hui() + timedelta(days=2)
        self.d = self.j + timedelta(days=3)
        self.double = Chambre.objects.create(numero="201", categorie="DOUBLE", tarif_nuit=20000)
        self.suite = Chambre.objects.create(numero="301", categorie="SUITE", tarif_nuit=40000, capacite=4)
        self.params = {"arrivee": self.j.isoformat(), "depart": self.d.isoformat(), "personnes": 2}

    def test_la_page_d_accueil_propose_de_reserver(self):
        page = self.client.get(reverse("vitrine:site"))
        self.assertContains(page, "Réservez votre chambre")
        self.assertContains(page, 'action="/reserver/"')
        self.assertNotContains(page, 'href="#reserver"', msg_prefix="chaque bouton « Réserver » mène quelque part")
        self.assertContains(page, 'class="btn or grand" href="/reserver/"')

    def test_reserver_sans_dates_montre_les_chambres_libres_ce_soir(self):
        reponse = self.client.get(reverse("vitrine:reserver"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(f"arrivee={aujourd_hui().isoformat()}", reponse["Location"])
        page = self.client.get(reponse["Location"])
        self.assertContains(page, "Choisissez votre chambre")
        self.assertContains(page, "Voir la chambre")

    def test_seules_les_chambres_libres_et_assez_grandes(self):
        self.sejour(arrivee=self.j + timedelta(days=1), depart=self.d + timedelta(days=2), chambre=self.double,
                    statut=Sejour.Statut.RESERVE)
        types = reservations.types_libres(self.j, self.d, 2)
        self.assertEqual([(t["libelle"], t["tarif"], t["total"]) for t in types],
                         [("Chambre simple", 25000, 75000), ("Suite", 40000, 120000)])
        self.assertEqual([t["libelle"] for t in reservations.types_libres(self.j, self.d, 3)], ["Suite"])
        page = self.client.get(reverse("vitrine:reserver"), self.params)
        self.assertContains(page, "Choisissez votre chambre")
        self.assertContains(page, "120")
        self.assertNotContains(page, "Chambre double")

    def test_dates_impossibles(self):
        hier = aujourd_hui() - timedelta(days=1)
        page = self.client.get(reverse("vitrine:reserver"), {"arrivee": hier.isoformat(), "depart": self.d.isoformat(),
                                                             "personnes": 1})
        self.assertContains(page, "déjà passée")
        page = self.client.get(reverse("vitrine:reserver"), {"arrivee": self.j.isoformat(),
                                                             "depart": (self.j + timedelta(days=45)).isoformat(),
                                                             "personnes": 1})
        self.assertContains(page, "30 nuits au plus")

    def demander(self, **extra):
        url = f"{reverse('vitrine:reserver_coordonnees')}?arrivee={self.j}&depart={self.d}&personnes=2&type=SUITE-40000"
        donnees = {"nom": "Mme Ngo Bella", "telephone": "677 12 34 56", "message": "Arrivée vers 20 h", **extra}
        return self.client.post(url, donnees)

    def test_demande_puis_confirmation_par_la_reception(self):
        reponse = self.demander()
        demande = DemandeReservation.objects.get()
        self.assertRedirects(reponse, reverse("vitrine:reservation_envoyee", args=[demande.pk]))
        page = self.client.get(reverse("vitrine:reservation_envoyee", args=[demande.pk]))
        self.assertContains(page, f"Demande n°{demande.pk} envoyée")
        self.assertContains(page, "677123456")
        self.assertEqual((demande.telephone, demande.chambre_proposee, demande.total_prevu),
                         ("677123456", self.suite, 120000))
        self.assertTrue(Alerte.objects.filter(cle=f"demande-reservation-{demande.pk}", lue_le__isnull=True).exists())
        self.assertFalse(Sejour.objects.exists(), "la demande ne bloque rien tant que la réception n'a pas confirmé")

        autre = self.client_class()
        self.assertEqual(autre.get(reverse("vitrine:reservation_envoyee", args=[demande.pk])).status_code, 404,
                         "un inconnu ne voit pas la demande d'un autre")

        self.client.force_login(self.aicha)
        page = self.client.get(reverse("vitrine:demandes"))
        self.assertContains(page, "Mme Ngo Bella")
        self.assertContains(page, "Arrivée vers 20 h")
        self.client.post(reverse("vitrine:demandes"), {"demande": demande.pk, "action": "confirmer", "chambre": self.suite.pk})
        demande.refresh_from_db()
        sejour = demande.sejour
        self.assertEqual((demande.statut, sejour.statut, sejour.chambre, sejour.tarif_nuit, sejour.nb_personnes),
                         ("CONFIRMEE", "RESERVE", self.suite, 40000, 2))
        self.assertEqual(sejour.client.telephone, "677123456")
        self.assertIn("Arrivée vers 20 h", sejour.notes)
        self.assertFalse(Alerte.objects.filter(cle=f"demande-reservation-{demande.pk}", lue_le__isnull=True).exists())
        self.assertNotIn(self.suite, list(reservations.chambres_libres(self.j, self.d)))

    def test_meme_client_retrouve_sa_fiche(self):
        Client.objects.create(nom="Mme Ngo", telephone="+237 677 12 34 56")
        self.demander()
        self.client.force_login(self.aicha)
        self.client.post(reverse("vitrine:demandes"), {"demande": DemandeReservation.objects.get().pk,
                                                       "action": "confirmer", "chambre": self.suite.pk})
        self.assertEqual(Client.objects.filter(nom__startswith="Mme Ngo").count(), 1)

    def test_chambre_prise_entre_temps(self):
        self.demander()
        demande = DemandeReservation.objects.get()
        self.sejour(arrivee=self.j, depart=self.d, chambre=self.suite, statut=Sejour.Statut.RESERVE)
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("vitrine:demandes"))
        self.assertContains(page, "Autres chambres libres")
        reponse = self.client.post(reverse("vitrine:demandes"), {"demande": demande.pk, "action": "confirmer",
                                                                 "chambre": self.suite.pk}, follow=True)
        self.assertContains(reponse, "déjà réservée")
        demande.refresh_from_db()
        self.assertEqual(demande.statut, "NOUVELLE")

    def test_refus_motive(self):
        self.demander()
        demande = DemandeReservation.objects.get()
        self.client.force_login(self.aicha)
        self.assertContains(self.client.post(reverse("vitrine:demandes"), {"demande": demande.pk, "action": "refuser"},
                                             follow=True), "Dites pourquoi")
        self.client.post(reverse("vitrine:demandes"), {"demande": demande.pk, "action": "refuser", "motif": "Complet"})
        demande.refresh_from_db()
        self.assertEqual((demande.statut, demande.motif), ("REFUSEE", "Complet"))

    def test_robots_et_abus(self):
        self.demander(site_web="http://spam.example")
        self.assertFalse(DemandeReservation.objects.exists(), "le champ piège rempli : rien n'est créé")
        for i in range(5):
            self.demander(nom=f"Client {i}")
        self.assertContains(self.demander(nom="Sixième"), "Trop de demandes")
        self.assertEqual(DemandeReservation.objects.count(), 5)

    def test_le_client_connecte_suit_et_annule_sa_demande(self):
        user = User.objects.create_user("677123456", password="Demo1234!x", role=Role.CLIENT, first_name="Mme Ngo")
        compte = CompteClient.objects.create(user=user, nom="Mme Ngo Bella", telephone="677123456")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("vitrine:reserver"), self.params).status_code, 200,
                         "un client connecté peut réserver")
        page = self.client.get(f"{reverse('vitrine:reserver_coordonnees')}?arrivee={self.j}&depart={self.d}"
                               "&personnes=2&type=SUITE-40000")
        self.assertContains(page, 'value="Mme Ngo Bella"')
        self.demander()
        demande = DemandeReservation.objects.get()
        self.assertEqual(demande.compte, compte)
        espace = self.client.get(reverse("vitrine:espace"))
        self.assertContains(espace, f"Demande n°{demande.pk}")
        self.client.post(reverse("vitrine:demande_annuler", args=[demande.pk]))
        demande.refresh_from_db()
        self.assertEqual(demande.statut, "ANNULEE")

    def test_la_reception_voit_le_nombre_a_confirmer(self):
        self.demander()
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("postes:reception"))
        self.assertContains(page, "1 réservation en ligne à confirmer")
        self.client.force_login(self.utilisateur("aurelle", Role.BAR_RESTAURANT))
        self.assertEqual(self.client.get(reverse("vitrine:demandes")).status_code, 403)

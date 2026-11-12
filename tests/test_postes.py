"""Une page de saisie par département : c'est l'écran qui reste ouvert sur le poste."""
from datetime import timedelta

from django.urls import reverse

from accounts.models import Role
from caisse.models import Encaissement
from core.models import Alerte
from core.utils import aujourd_hui
from hotel.models import Chambre, Sejour
from personnel.models import Departement, Employe
from postes.models import EvenementSecurite, Intervention

from .base import BaseTest


class PostesDepartementsTests(BaseTest):
    def employe(self, nom, role, departement):
        user = self.utilisateur(nom, role)
        Employe.objects.create(user=user, nom=nom, poste=nom, departement=departement)
        return user

    def arrive_sur(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("core:accueil"), follow=True).redirect_chain[-1][0]

    def test_chacun_arrive_sur_la_saisie_de_son_departement(self):
        self.assertEqual(self.arrive_sur(self.aicha), reverse("postes:reception"))
        self.assertEqual(self.arrive_sur(self.employe("odile", Role.EMPLOYE, Departement.MENAGE)), reverse("hotel:menage"))
        self.assertEqual(self.arrive_sur(self.employe("thomas", Role.EMPLOYE, Departement.MAINTENANCE)),
                         reverse("postes:maintenance"))
        self.assertEqual(self.arrive_sur(self.employe("ibrahim", Role.EMPLOYE, Departement.SECURITE)),
                         reverse("postes:securite"))
        # La cuisine / bar sans caisse ouverte passe d'abord par l'ouverture de caisse, qui le ramène ensuite à sa saisie.
        self.assertEqual(self.arrive_sur(self.utilisateur("jean", Role.BAR_RESTAURANT)),
                         reverse("caisse:ma_caisse") + "?suite=" + reverse("caisse:ventes"))
        self.client.force_login(self.gerant)
        self.assertEqual(self.client.get(reverse("core:accueil")).status_code, 200, "le gérant garde son tableau de bord")
        self.assertEqual(self.client.get(reverse("postes:tous")).status_code, 200)

    def test_menage_et_gardien_sans_compte_la_reception_relaie(self):
        self.client.force_login(self.aicha)
        Chambre.objects.filter(pk=self.chambre.pk).update(statut=Chambre.Statut.A_NETTOYER)
        page = self.client.get(reverse("postes:reception"))
        self.assertContains(page, "Chambres à nettoyer (1)")
        self.assertContains(page, "Main courante du gardien")
        self.client.post(reverse("postes:reception"), {"action": "menage", "chambre": self.chambre.pk})
        self.chambre.refresh_from_db()
        self.assertEqual(self.chambre.statut, Chambre.Statut.LIBRE, "le ménage l'a dit à la réception")
        self.client.post(reverse("postes:securite"), {"type": "RONDE", "description": "Ronde de 22 h : RAS"})
        self.assertEqual(EvenementSecurite.objects.get().saisi_par, self.aicha)

    def test_un_compte_menage_eventuel_n_a_pas_de_caisse(self):
        femme_de_chambre = self.employe("odile", Role.EMPLOYE, Departement.MENAGE)
        self.client.force_login(femme_de_chambre)
        self.assertFalse(femme_de_chambre.tient_caisse)
        self.assertEqual(self.client.get(reverse("caisse:ma_caisse")).status_code, 403)

    def test_ouvrir_sa_caisse_ramene_a_la_page_de_saisie(self):
        self.client.force_login(self.aicha)
        reponse = self.client.post(reverse("caisse:ma_caisse"), {
            "tiroir": self.tiroir.pk, "shift": "MATIN", "especes_comptees": 20000, "suite": reverse("postes:reception")})
        self.assertRedirects(reponse, reverse("postes:reception"))


class SaisieReceptionTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.aicha)
        self.url = reverse("postes:reception")

    def test_client_sans_reservation_installe_et_encaisse_en_une_fois(self):
        donnees = {"nom": "M. Biya Paul", "telephone": "677001122", "chambre": self.chambre.pk,
                   "nuits": 2, "montant": 50000, "moyen": "ESPECES"}
        reponse = self.client.post(reverse("postes:arrivee"), donnees, follow=True)
        self.assertContains(reponse, "abord votre caisse")
        self.assertFalse(Sejour.objects.exists(), "rien n'est créé si le paiement ne peut pas être encaissé")

        self.ouvrir()
        reponse = self.client.post(reverse("postes:arrivee"), donnees, follow=True)
        self.assertContains(reponse, "est installé en chambre 101")
        sejour = Sejour.objects.get()
        self.chambre.refresh_from_db()
        self.assertEqual((sejour.statut, sejour.nb_nuits, self.chambre.statut), ("EN_COURS", 2, "OCCUPEE"))
        self.assertEqual(sejour.total_paye, 50000)
        self.assertContains(reponse, "Dernier reçu")

    def test_arrivee_sans_paiement_possible_meme_caisse_fermee(self):
        reponse = self.client.post(reverse("postes:arrivee"), {"nom": "Mme Ngo", "telephone": "699",
                                              "chambre": self.chambre.pk, "nuits": 1, "moyen": "ESPECES"}, follow=True)
        self.assertContains(reponse, "encore été payé")
        self.assertEqual(Sejour.objects.get().reste_a_payer, 25000)

    def test_encaisser_et_faire_partir_depuis_la_liste_des_chambres(self):
        self.ouvrir()
        s = self.sejour(arrivee=aujourd_hui() - timedelta(days=1), depart=aujourd_hui() + timedelta(days=1))
        page = self.client.get(reverse("postes:chambre", args=[self.chambre.pk]))
        self.assertContains(page, f'name="s{s.pk}-montant" value="50000"', msg_prefix="le reste à payer est proposé")
        self.assertNotContains(page, f"s{s.pk}-reference", msg_prefix="Orange Money ou MoMo : rien d'autre à saisir")
        self.client.post(self.url, {"action": "encaisser", "sejour": s.pk, f"s{s.pk}-montant": 20000,
                                    f"s{s.pk}-moyen": "ORANGE_MONEY"})
        self.assertEqual(Encaissement.objects.get().moyen_libelle, "Orange Money")
        reponse = self.client.post(self.url, {"action": "depart", "sejour": s.pk}, follow=True)
        self.assertContains(reponse, "doit encore")
        s.refresh_from_db()
        self.assertEqual(s.statut, "TERMINE")

    def test_reservation_attendue_installee_d_un_geste(self):
        s = self.sejour(statut=Sejour.Statut.RESERVE)
        self.assertContains(self.client.get(self.url), "Il est arrivé")
        self.client.post(self.url, {"action": "checkin", "sejour": s.pk})
        s.refresh_from_db()
        self.assertEqual(s.statut, "EN_COURS")


class MaintenanceSecuriteTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.technicien = self.utilisateur("thomas", Role.EMPLOYE)
        Employe.objects.create(user=self.technicien, nom="Nkou", poste="Technicien", departement=Departement.MAINTENANCE)
        self.agent = self.utilisateur("ibrahim", Role.EMPLOYE)
        Employe.objects.create(user=self.agent, nom="Bello", poste="Agent", departement=Departement.SECURITE)

    def test_panne_signalee_par_tous_reparee_par_la_maintenance(self):
        self.client.force_login(self.aicha)
        self.client.post(reverse("postes:maintenance"), {
            "action": "signaler", "chambre": self.chambre.pk, "probleme": "Fuite d'eau", "urgence": "URGENTE",
            "hors_service": "on"})
        panne = Intervention.objects.get()
        self.chambre.refresh_from_db()
        self.assertEqual(self.chambre.statut, Chambre.Statut.HORS_SERVICE)
        self.assertTrue(Alerte.objects.filter(message__contains="Fuite d'eau").exists())
        self.client.post(reverse("postes:maintenance"), {"action": "repare", "panne": panne.pk})
        panne.refresh_from_db()
        self.assertEqual(panne.statut, "A_FAIRE", "la réception signale, elle ne répare pas")

        self.client.force_login(self.technicien)
        self.client.post(reverse("postes:maintenance"), {"action": "repare", "panne": panne.pk,
                                                         "commentaire": "Joint changé"})
        panne.refresh_from_db()
        self.chambre.refresh_from_db()
        self.assertEqual((panne.statut, panne.traite_par), ("FAITE", self.technicien))
        self.assertEqual(self.chambre.statut, Chambre.Statut.A_NETTOYER, "après les travaux, le ménage repasse")

    def test_seule_la_reception_signale_les_problemes_de_chambre(self):
        barman = self.utilisateur("jean", Role.BAR_RESTAURANT)
        femme_de_chambre = self.utilisateur("odile", Role.EMPLOYE)
        Employe.objects.create(user=femme_de_chambre, nom="Ngo", poste="Ménage", departement=Departement.MENAGE)
        for personne in (barman, femme_de_chambre, self.agent):
            self.client.force_login(personne)
            with self.subTest(personne=personne.username):
                self.assertEqual(self.client.get(reverse("postes:maintenance")).status_code, 403)
                self.client.post(reverse("postes:maintenance"), {"action": "signaler", "chambre": self.chambre.pk,
                                                                 "probleme": "x", "urgence": "NORMALE"})
                self.assertNotContains(self.client.get(reverse("accounts:mon_compte")), "Signaler une panne")
        self.assertFalse(Intervention.objects.exists())

        self.client.force_login(self.technicien)
        page = self.client.get(reverse("postes:maintenance"))
        self.assertEqual(page.status_code, 200, "la maintenance voit les pannes à réparer")
        self.assertNotContains(page, "Signaler un problème de chambre")

        chef = self.utilisateur("chef.menage", Role.CHEF_EQUIPE)
        self.client.force_login(chef)
        page = self.client.get(reverse("postes:maintenance"))
        self.assertEqual(page.status_code, 200, "le chef d'équipe suit les réparations")
        self.assertNotContains(page, "Signaler un problème de chambre")

        self.client.force_login(self.aicha)
        self.assertContains(self.client.get(reverse("postes:reception")), "Signaler une panne")
        self.assertContains(self.client.get(reverse("postes:maintenance")), "Signaler un problème de chambre")

    def test_main_courante_securite(self):
        self.client.force_login(self.agent)
        self.client.post(reverse("postes:securite"), {"type": "INCIDENT", "description": "Bagarre au parking"})
        self.assertEqual(EvenementSecurite.objects.get().saisi_par, self.agent)
        self.assertTrue(Alerte.objects.filter(message__contains="Bagarre").exists())
        self.assertContains(self.client.get(reverse("postes:securite")), "Bagarre au parking")
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.get(reverse("postes:securite")).status_code, 200, "la réception relaie le gardien")
        self.client.force_login(self.utilisateur("jean", Role.BAR_RESTAURANT))
        self.assertEqual(self.client.get(reverse("postes:securite")).status_code, 403)


class PlanDesChambresTests(BaseTest):
    """L'accueil de la réception est le plan des chambres ; on touche une chambre, seules ses actions s'affichent."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.aicha)
        self.libre = Chambre.objects.create(numero="102", tarif_nuit=20000)
        self.sale = Chambre.objects.create(numero="201", tarif_nuit=20000, statut=Chambre.Statut.A_NETTOYER)

    def test_le_plan_montre_chaque_chambre_et_son_etat(self):
        self.sejour()
        Chambre.objects.filter(pk=self.chambre.pk).update(statut=Chambre.Statut.OCCUPEE)
        page = self.client.get(reverse("postes:reception"))
        self.assertContains(page, 'class="chambre-tuile OCCUPEE"')
        self.assertContains(page, 'class="chambre-tuile LIBRE"')
        self.assertContains(page, "M. Kamga")
        self.assertContains(page, "Chambres 101 à 102")
        self.assertContains(page, "1 libre")
        self.assertContains(page, reverse("postes:chambre", args=[self.libre.pk]))

    def test_chaque_chambre_n_offre_que_ses_actions(self):
        s = self.sejour()
        Chambre.objects.filter(pk=self.chambre.pk).update(statut=Chambre.Statut.OCCUPEE)
        occupee = self.client.get(reverse("postes:chambre", args=[self.chambre.pk]))
        for texte in ("Reste à payer", "Le client part", "Ajouter un repas", "Ouvrir ma caisse"):
            self.assertContains(occupee, texte)
        self.assertNotContains(occupee, "Un client arrive")
        libre = self.client.get(reverse("postes:chambre", args=[self.libre.pk]))
        self.assertContains(libre, f'{reverse("postes:arrivee")}?chambre={self.libre.pk}')
        self.assertNotContains(libre, "Le client part")
        sale = self.client.get(reverse("postes:chambre", args=[self.sale.pk]))
        self.assertContains(sale, "Chambre faite")
        self.ouvrir()
        self.assertContains(self.client.get(reverse("postes:chambre", args=[self.chambre.pk])),
                            f'data-montant-max="{s.reste_a_payer}"')

    def test_reservation_du_jour_sur_la_chambre(self):
        self.sejour(chambre=self.libre, statut=Sejour.Statut.RESERVE)
        page = self.client.get(reverse("postes:chambre", args=[self.libre.pk]))
        self.assertContains(page, "M. Kamga est arrivé")
        self.assertNotContains(page, f'{reverse("postes:arrivee")}?chambre=',
                               msg_prefix="pas d'autre client sur une chambre réservée")

    def test_arrivee_pas_a_pas(self):
        page = self.client.get(reverse("postes:arrivee"), {"chambre": self.libre.pk})
        for texte in ("1. Qui est le client ?", "2. Combien de nuits ?", "3. Combien le client paie maintenant ?",
                      "4. Vérifiez", "Installer le client", '"%s": 20000' % self.libre.pk):
            self.assertContains(page, texte)
        self.assertRedirects(self.client.get(reverse("postes:arrivee"), {"chambre": self.sale.pk}),
                             reverse("postes:reception"), msg_prefix="une chambre pas libre ramène au plan")
        erreur = self.client.post(reverse("postes:arrivee"), {"chambre": self.libre.pk, "nom": "", "telephone": "",
                                                              "nuits": 1, "moyen": "ESPECES"})
        self.assertContains(erreur, "Ce champ est obligatoire")
        self.assertFalse(Sejour.objects.exists())

    def test_signaler_une_panne_depuis_la_chambre(self):
        page = self.client.get(reverse("postes:maintenance"), {"chambre": self.libre.pk})
        self.assertContains(page, f'<option value="{self.libre.pk}" selected>')

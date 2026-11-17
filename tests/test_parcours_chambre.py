"""Le parcours complet d'une chambre, de la demande en ligne à la caisse validée ; les modules grisés ; les protections."""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client as Navigateur
from django.test import override_settings
from django.urls import reverse

from accounts.models import Role
from caisse import services as caisse
from caisse.models import Encaissement, SessionCaisse
from core import modules
from core.utils import aujourd_hui
from hotel.models import Chambre, Client, Nuitee, Sejour
from vitrine import reservations
from vitrine.models import DemandeReservation

from .base import BaseTest


class ParcoursChambreTests(BaseTest):
    """Un client réserve sur le site pour ce soir, la réception confirme, il arrive, paie, part ; la chambre est faite,
    la caisse est fermée et validée. Chaque étape passe par les écrans (comme au doigt), pas par les fonctions."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.jour = aujourd_hui()
        self.depart = self.jour + timedelta(days=2)

    def demander(self, navigateur=None, telephone="+237 677 12 34 56", **entetes):
        navigateur = navigateur or self.client
        recherche = {"arrivee": self.jour.isoformat(), "depart": self.depart.isoformat(), "personnes": 1}
        page = navigateur.get(reverse("vitrine:reserver"), recherche)
        self.assertContains(page, "Choisissez votre chambre")
        cle = page.context["types"][0]["cle"]
        url = f"{reverse('vitrine:reserver_coordonnees')}?arrivee={recherche['arrivee']}&depart={recherche['depart']}" \
              f"&personnes=1&type={cle}"
        return navigateur.post(url, {"nom": "Mme Ewodo", "telephone": telephone, "message": "Arrivée vers 20 h"},
                               **entetes)

    def test_de_la_demande_en_ligne_a_la_caisse_validee(self):
        # 1. Le client envoie sa demande depuis le site
        reponse = self.demander()
        demande = DemandeReservation.objects.get()
        self.assertRedirects(reponse, reverse("vitrine:reservation_envoyee", args=[demande.pk]))
        self.assertContains(self.client.get(reponse["Location"]), f"Demande n°{demande.pk} envoyée")
        self.assertEqual((demande.telephone, demande.tarif_nuit, demande.nb_nuits), ("677123456", 25000, 2))

        # 2. La réception la voit (pastille) et la confirme d'un geste
        recep = Navigateur()
        recep.force_login(self.aicha)
        plan = recep.get(reverse("postes:reception"))
        self.assertContains(plan, "1 réservation en ligne à confirmer")
        self.assertContains(recep.get(reverse("vitrine:demandes")), "Mme Ewodo")
        confirmer = {"demande": demande.pk, "action": "confirmer", "chambre": self.chambre.pk}
        recep.post(reverse("vitrine:demandes"), confirmer)
        sejour = Sejour.objects.get()
        self.assertEqual((sejour.statut, sejour.tarif_nuit, sejour.client.telephone),
                         (Sejour.Statut.RESERVE, 25000, "677123456"))
        # Une collègue confirme la même demande au même moment : rien en double
        reponse = recep.post(reverse("vitrine:demandes"), confirmer, follow=True)
        self.assertContains(reponse, "déjà été traitée")
        self.assertEqual(Sejour.objects.count(), 1)

        # 3. Il arrive : la chambre l'attend sur le plan
        self.assertContains(recep.get(reverse("postes:chambre", args=[self.chambre.pk])), "Mme Ewodo est arrivé")
        recep.post(reverse("postes:reception"), {"action": "checkin", "sejour": sejour.pk})
        sejour.refresh_from_db()
        self.chambre.refresh_from_db()
        self.assertEqual((sejour.statut, self.chambre.statut), (Sejour.Statut.EN_COURS, Chambre.Statut.OCCUPEE))

        # 4. Il paie le séjour (50 000 F) à la caisse de la réception
        session = self.ouvrir()
        recep.post(reverse("postes:reception"), {"action": "encaisser", "sejour": sejour.pk,
                                                 f"s{sejour.pk}-montant": 50000, f"s{sejour.pk}-moyen": "ORANGE_MONEY"})
        encaissement = Encaissement.objects.get()
        self.assertEqual((encaissement.montant, encaissement.mode, encaissement.numero_recu), (50000, "ORANGE_MONEY", 1))
        self.assertEqual(recep.get(reverse("caisse:recu_client", args=[encaissement.pk])).status_code, 200)
        self.assertEqual(sejour.reste_a_payer, 0)

        # 5. Il part : nuits constatées, chambre à faire ; le ménage la rend libre
        with mock.patch("hotel.services.aujourd_hui", return_value=self.depart):
            recep.post(reverse("postes:reception"), {"action": "depart", "sejour": sejour.pk})
        sejour.refresh_from_db()
        self.chambre.refresh_from_db()
        self.assertEqual((sejour.statut, self.chambre.statut), (Sejour.Statut.TERMINE, Chambre.Statut.A_NETTOYER))
        self.assertEqual(Nuitee.objects.filter(sejour=sejour).count(), 2)
        self.assertEqual((sejour.total_facture, sejour.reste_a_payer), (50000, 0))
        recep.post(reverse("postes:reception"), {"action": "menage", "chambre": self.chambre.pk})
        self.chambre.refresh_from_db()
        self.assertEqual(self.chambre.statut, Chambre.Statut.LIBRE)

        # 6. Elle ferme sa caisse (l'Orange Money déclaré) ; le gérant valide
        self.remettre(session, 20000, mobile={"ORANGE_MONEY": [50000]})
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionCaisse.Statut.REMISE)
        caisse.valider_session(session, self.gerant)
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionCaisse.Statut.VALIDEE)

        # 7. La recette de la chambre figure sur la fiche du jour
        self.client.force_login(self.gerant)
        fiche = self.client.get(reverse("fiches:hebergement"), {"date": self.jour.isoformat()})
        self.assertEqual(fiche.status_code, 200)

    def test_le_client_avec_compte_suit_sa_demande(self):
        from vitrine import services as vitrine

        compte = vitrine.inscrire("Mme Ewodo", "677123456", "", "MotDePasse-2026")
        vitrine.relier(compte, self.aicha, None)
        self.client.force_login(compte.user)
        self.demander()
        demande = DemandeReservation.objects.get()
        self.assertEqual(demande.compte, compte)
        self.assertContains(self.client.get(reverse("vitrine:espace")), "La réception vous appelle pour confirmer")
        sejour = reservations.confirmer(demande, self.aicha, self.chambre)
        self.assertContains(self.client.get(reverse("vitrine:espace")), "Confirmée : chambre 101")
        Sejour.objects.filter(pk=sejour.pk).update(statut=Sejour.Statut.ANNULE)
        espace = self.client.get(reverse("vitrine:espace"))
        self.assertContains(espace, "Réservation annulée")
        self.assertNotContains(espace, "Confirmée : chambre 101")

    def test_arrivee_sans_reservation_retrouve_le_client_et_respecte_les_reservations(self):
        ancien = Client.objects.create(nom="M. Owona", telephone="699 11 22 33")
        self.client.force_login(self.aicha)
        self.client.post(reverse("postes:arrivee"), {"nom": "Owona", "telephone": "+237699112233",
                                                     "chambre": self.chambre.pk, "nuits": 1, "moyen": "ESPECES"})
        self.assertEqual(Sejour.objects.get().client, ancien, "même numéro écrit autrement : même client")
        # Une chambre libre ce soir mais réservée demain ne peut pas être prise pour 3 nuits
        autre = Chambre.objects.create(numero="102", tarif_nuit=25000)
        Sejour.objects.create(client=ancien, chambre=autre, date_arrivee=self.jour + timedelta(days=1),
                              date_depart=self.jour + timedelta(days=3), tarif_grille=25000, tarif_nuit=25000,
                              cree_par=self.aicha)
        page = self.client.post(reverse("postes:arrivee"), {"nom": "X", "telephone": "655000000",
                                                            "chambre": autre.pk, "nuits": 3, "moyen": "ESPECES"})
        self.assertContains(page, "déjà réservée")
        self.assertEqual(Sejour.objects.filter(chambre=autre).count(), 1)


class ModulesGrisesTests(BaseTest):
    """Au lancement, seule la réservation et la vente des chambres sont ouvertes ; le reste est grisé et bloqué."""

    def setUp(self):
        super().setUp()
        modules.ouvrir([])

    def test_un_module_ferme_disparait_du_menu_et_reste_bloque(self):
        self.client.force_login(self.gerant)
        accueil = self.client.get("/")
        self.assertContains(accueil, "Ouvrir des modules")
        menu = accueil.content.decode().split('<nav class="menu"')[1].split("</nav>")[0]
        for absent in ("/stock/", "/rapports/", "/personnel/", "/paie/", "/finances/", "/projets/", "/caisse/ventes/"):
            self.assertNotIn(absent, menu, absent)
        self.assertLessEqual(menu.count("<a "), 10, "menu court")
        autres = self.client.get(reverse("core:pages"))
        self.assertContains(autres, "Photos des chambres")
        self.assertNotContains(autres, 'href="/stock/"', msg_prefix="le stock est fermé")
        self.assertContains(autres, "Photos des plats", msg_prefix="sauf les photos des plats, commandés en ligne")
        self.assertContains(autres, "Pas encore ouverts")
        for url in ("/stock/", "/rapports/", "/personnel/planning/", "/paie/fiches/", "/finances/bilan/",
                    "/projets/liste/", "/caisse/ventes/", "/hotel/extras/", "/poste/maintenance/"):
            page = self.client.get(url)
            self.assertEqual(page.status_code, 403, url)
            self.assertContains(page, "pas encore ouvert", status_code=403)
        for url in ("/hotel/sejours/", "/hotel/reservations-en-ligne/", "/poste/reception/", "/caisse/ma-caisse/",
                    "/hotel/chambres/", "/hotel/clients/", "/fiches/recette-chambres/", "/parametres/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_la_reception_voit_la_boutique_grisee(self):
        self.client.force_login(self.aicha)
        plan = self.client.get(reverse("postes:reception"))
        self.assertNotContains(plan, 'href="/caisse/ventes/"')
        self.assertContains(plan, "Un client arrive")
        self.assertEqual(self.client.get("/caisse/ventes/").status_code, 403)

    def test_le_gerant_ouvre_un_module_les_autres_non(self):
        adjoint = self.utilisateur("julio", Role.ADJOINT)
        self.client.force_login(adjoint)
        self.assertEqual(self.client.get(reverse("core:modules")).status_code, 403)
        self.client.force_login(self.gerant)
        page = self.client.post(reverse("core:modules"), {"ouverts": ["stock", "inconnu"]}, follow=True)
        self.assertContains(page, "Stock et inventaire ouvert")
        self.assertEqual(modules.ouverts(), {"stock"}, "une clé inconnue est ignorée")
        self.assertEqual(self.client.get("/stock/").status_code, 200)
        self.assertEqual(self.client.get("/rapports/").status_code, 403)


class ProtectionsReservationTests(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.j = aujourd_hui() + timedelta(days=3)
        self.url = (f"{reverse('vitrine:reserver_coordonnees')}?arrivee={self.j.isoformat()}"
                    f"&depart={(self.j + timedelta(days=1)).isoformat()}&personnes=1&type=SIMPLE-25000")
        self.donnees = {"nom": "Client", "telephone": "677000000"}

    def test_robot_ignore(self):
        reponse = self.client.post(self.url, {**self.donnees, "site_web": "http://spam.example"})
        self.assertRedirects(reponse, reverse("vitrine:site"), fetch_redirect_response=False)
        self.assertFalse(DemandeReservation.objects.exists())

    @override_settings(ENTETE_IP_CLIENT="HTTP_X_REAL_IP")
    def test_limite_par_visiteur_derriere_l_hebergeur(self):
        """Derrière l'hébergeur, REMOTE_ADDR est le même pour tous : la limite se fait sur la vraie adresse."""
        for _ in range(5):
            self.client.post(self.url, self.donnees, HTTP_X_REAL_IP="41.202.1.1")
        bloque = self.client.post(self.url, self.donnees, HTTP_X_REAL_IP="41.202.1.1")
        self.assertContains(bloque, "Trop de demandes")
        autre = self.client.post(self.url, self.donnees, HTTP_X_REAL_IP="102.244.9.9")
        self.assertEqual(autre.status_code, 302, "un autre visiteur n'est pas bloqué")
        self.assertEqual(DemandeReservation.objects.count(), 6)

    def test_afflux_de_demandes_suspendu(self):
        with mock.patch.object(reservations, "DEMANDES_PAR_HEURE_MAX", 2):
            for ip in ("1.1.1.1", "2.2.2.2"):
                self.client.post(self.url, self.donnees, REMOTE_ADDR=ip)
            page = self.client.post(self.url, self.donnees, REMOTE_ADDR="3.3.3.3")
        self.assertContains(page, "Beaucoup de demandes")
        self.assertEqual(DemandeReservation.objects.count(), 2)

    def test_la_demande_d_un_autre_reste_privee(self):
        self.client.post(self.url, self.donnees)
        demande = DemandeReservation.objects.get()
        self.assertEqual(self.client.get(reverse("vitrine:reservation_envoyee", args=[demande.pk])).status_code, 200)
        curieux = Navigateur()
        self.assertEqual(curieux.get(reverse("vitrine:reservation_envoyee", args=[demande.pk])).status_code, 404)

    def test_le_formulaire_exige_le_jeton_anti_falsification(self):
        navigateur = Navigateur(enforce_csrf_checks=True)
        reponse = navigateur.post(self.url, self.donnees, follow=True)
        self.assertContains(reponse, "rien n&#x27;a été enregistré")  # page expirée : phrase simple, pas d'erreur
        self.assertFalse(DemandeReservation.objects.exists())

    def test_seule_la_reception_traite_les_demandes(self):
        self.assertEqual(self.client.get(reverse("vitrine:demandes")).status_code, 302, "anonyme : connexion")
        from vitrine import services as vitrine

        compte = vitrine.inscrire("Curieux", "690000001", "", "MotDePasse-2026")
        self.client.force_login(compte.user)
        self.assertNotEqual(self.client.get(reverse("vitrine:demandes")).status_code, 200)

    def test_chambre_trop_petite_refusee(self):
        suite = Chambre.objects.create(numero="301", categorie="SUITE", tarif_nuit=40000, capacite=4)
        demande = reservations.creer_demande(self.j, self.j + timedelta(days=1), 3, f"SUITE-{suite.tarif_nuit}",
                                             "Famille", "677000000")
        with self.assertRaisesMessage(Exception, "prévue pour"):
            reservations.confirmer(demande, self.aicha, self.chambre)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeReservation.Statut.NOUVELLE, "rien n'a changé")
        reservations.confirmer(demande, self.aicha, suite)

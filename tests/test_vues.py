"""Parcours dans le navigateur (client de test) : pages par rôle et remise de caisse complète."""
from django.urls import reverse

from accounts.models import Role
from caisse.models import SessionCaisse
from personnel.models import Departement, Employe

from .base import BaseTest

PAGES_COMMUNES = ["accounts:mon_compte", "personnel:conges", "projets:mes_taches"]
PAGES_RECEPTION = ["hotel:sejours", "hotel:sejour_nouveau", "hotel:chambres", "hotel:clients", "hotel:extras",
                   "hotel:menage", "caisse:ma_caisse", "caisse:sessions"]
PAGES_GERANT = ["caisse:rapports", "caisse:virements", "caisse:parametres", "core:parametres", "core:journal",
                "core:alertes", "accounts:utilisateurs", "personnel:planning", "personnel:pointages",
                "personnel:employes", "personnel:creneaux", "paie:fiches", "paie:acomptes", "stock:articles",
                "stock:mouvements", "finances:bilan", "finances:depenses", "projets:liste", "projets:projet_nouveau",
                "caisse:recherche"]


class PagesParRoleTests(BaseTest):
    def test_le_gerant_ouvre_toutes_les_pages(self):
        self.client.force_login(self.gerant)
        for nom in ["core:accueil", "postes:tous", "postes:reception"] + PAGES_COMMUNES + PAGES_RECEPTION + PAGES_GERANT:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)

    def test_le_receptionniste_n_a_pas_acces_a_la_paie_ni_aux_finances(self):
        self.client.force_login(self.aicha)
        for nom in PAGES_COMMUNES + PAGES_RECEPTION:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)
        for nom in ["paie:fiches", "finances:bilan", "stock:articles", "caisse:rapports", "accounts:utilisateurs",
                    "core:journal"]:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 403)

    def test_le_bar_restaurant_a_sa_caisse_mais_pas_les_chambres(self):
        barman = self.utilisateur("barman", Role.BAR_RESTAURANT)
        self.client.force_login(barman)
        for nom in ["hotel:extras", "caisse:ma_caisse", "caisse:sessions"]:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)
        for nom in ["hotel:sejours", "hotel:menage", "hotel:chambres"]:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 403)

    def test_le_personnel_de_terrain_a_un_menu_court(self):
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("core:accueil"), follow=True)
        self.assertContains(page, "Saisie réception")
        menu = page.content.decode().split('<nav class="menu"')[1].split("</nav>")[0]
        self.assertLessEqual(menu.count("<a "), 9, "menu court : le travail du jour seulement")
        autres = self.client.get(reverse("core:pages"))
        self.assertContains(autres, "Extras sur chambre")
        self.assertNotContains(autres, "Journal d'activité")
        self.client.force_login(self.gerant)
        self.assertContains(self.client.get(reverse("core:pages")), "Saisies des départements")

    def test_un_employe_voit_son_espace(self):
        employe = self.utilisateur("odile", Role.EMPLOYE)
        Employe.objects.create(user=employe, nom="Ngo", poste="Ménage", departement=Departement.MENAGE)
        self.client.force_login(employe)
        for nom in ["personnel:mon_espace", "paie:mes_bulletins", "hotel:menage"]:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)
        self.assertEqual(self.client.get(reverse("personnel:planning")).status_code, 403)
        self.assertEqual(self.client.get(reverse("postes:maintenance")).status_code, 403,
                         "les problèmes de chambre passent par la réception")

    def test_anonyme_renvoye_vers_la_connexion(self):
        reponse = self.client.get(reverse("hotel:sejours"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("accounts:connexion"), reponse["Location"])


class ParcoursRemiseTests(BaseTest):
    def test_ouverture_encaissement_remise_validation(self):
        sejour = self.sejour()
        c = self.client
        c.force_login(self.aicha)
        reponse = c.post(reverse("caisse:ma_caisse"), {"tiroir": self.tiroir.pk, "shift": "MATIN",
                                                       "especes_comptees": 20000})
        self.assertRedirects(reponse, reverse("caisse:ma_caisse"))
        session = SessionCaisse.objects.get()
        # L'attendu n'est pas affiché pendant le shift.
        self.assertNotContains(c.get(reverse("caisse:ma_caisse")), "Espèces attendues")

        reponse = c.post(reverse("hotel:encaisser", args=[sejour.pk]),
                         {"nature": "REGLEMENT", "moyen": "ESPECES", "montant": 125000})
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(c.get(reponse["Location"]).status_code, 200)

        page = c.get(reverse("caisse:remise_comptage"))
        self.assertNotContains(page, "145")
        self.assertContains(page, 'name="orange_money"')
        self.assertContains(page, 'name="mtn_momo"')
        self.assertNotContains(page, "data-ajouter-ligne", msg_prefix="plus de bouton « + » : on tape 10000+5000")
        self.assertContains(c.post(reverse("caisse:remise_comptage"), {
            "especes": 143500, "cheques_nombre": 0, "cheques_total": 0, "orange_money": "5000+abc"}),
            "pas un montant")
        reponse = c.post(reverse("caisse:remise_comptage"), {
            "b10000": 14, "b1000": 3, "b500": 1, "especes": 143500, "cheques_nombre": 0, "cheques_total": 0})
        self.assertRedirects(reponse, reverse("caisse:remise_comparaison"))
        page = c.get(reverse("caisse:remise_comparaison"))
        self.assertContains(page, "data-motif-obligatoire")

        reponse = c.post(reverse("caisse:remise_comparaison"), {"motif": "", "pin": "1234"})
        self.assertContains(reponse, "le motif est obligatoire")
        reponse = c.post(reverse("caisse:remise_comparaison"), {"motif": "Erreur de rendu", "pin": "0000"})
        self.assertContains(reponse, "Code PIN incorrect")
        reponse = c.post(reverse("caisse:remise_comparaison"), {
            "motif": "Erreur de rendu", "pin": "1234", "entrant": self.serge.pk, "entrant_pin": "1234", "consigne": "Chambre 204 : fuite"})
        self.assertRedirects(reponse, reverse("caisse:session", args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionCaisse.Statut.ECART)
        self.assertEqual(c.get(reverse("caisse:recu_remise", args=[session.pk])).status_code, 200)

        # Un autre réceptionniste qui n'est pas l'entrant ne voit pas cette session.
        nadia = self.utilisateur("nadia", Role.RECEPTIONNISTE)
        c.force_login(nadia)
        self.assertEqual(c.get(reverse("caisse:session", args=[session.pk])).status_code, 404)

        # L'entrant voit les consignes à l'ouverture.
        c.force_login(self.serge)
        self.assertContains(c.get(reverse("caisse:ma_caisse")), "Chambre 204 : fuite")

        c.force_login(self.chef)
        reponse = c.post(reverse("caisse:session", args=[session.pk]), {
            "action": "valider", "imputation": "ERREUR_CORRIGEE", "decision": "Billet retrouvé"})
        self.assertRedirects(reponse, reverse("caisse:session", args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionCaisse.Statut.VALIDEE)

    def test_reservation_par_formulaire_refuse_le_chevauchement_et_la_remise_non_validee(self):
        from datetime import timedelta

        from core.utils import aujourd_hui
        self.client.force_login(self.aicha)
        j = aujourd_hui() + timedelta(days=5)
        donnees = {"nouveau_client_nom": "Mme Abena", "nouveau_client_telephone": "677000000",
                   "chambre": self.chambre.pk, "date_arrivee": j, "date_depart": j + timedelta(days=2),
                   "nb_personnes": 1}
        self.assertEqual(self.client.post(reverse("hotel:sejour_nouveau"), donnees).status_code, 302)
        donnees.update({"date_arrivee": j + timedelta(days=1), "date_depart": j + timedelta(days=3)})
        self.assertContains(self.client.post(reverse("hotel:sejour_nouveau"), donnees), "est déjà réservée")
        donnees.update({"date_arrivee": j + timedelta(days=2), "date_depart": j + timedelta(days=4),
                        "tarif_nuit": 15000, "motif_tarif": "Client fidèle"})
        reponse = self.client.post(reverse("hotel:sejour_nouveau"), donnees)
        self.assertContains(reponse, "le chef de réception ou le gérant doit valider")
        donnees.update({"valideur": self.chef.pk, "valideur_pin": "1234"})
        self.assertEqual(self.client.post(reverse("hotel:sejour_nouveau"), donnees).status_code, 302)


class DirectionEtEquipeTests(BaseTest):
    def test_les_adjoints_valident_les_caisses_et_suivent_l_activite_sauf_la_paie(self):
        from caisse import services as caisse

        adjoint = self.utilisateur("adjoint", Role.ADJOINT)
        self.assertTrue(adjoint.peut_valider_caisse and adjoint.est_encadrement and adjoint.voit_reception)
        session = self.ouvrir()
        self.encaisser_especes(session, self.sejour(), 10000)
        self.remettre(session, 30000)
        caisse.valider_session(session, adjoint)
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionCaisse.Statut.VALIDEE)
        self.client.force_login(adjoint)
        for nom in ["core:accueil", "core:alertes", "caisse:rapports", "caisse:sessions", "hotel:sejours",
                    "stock:articles", "personnel:planning", "fiches:index", "postes:tous"]:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)
        for nom in ["paie:fiches", "finances:bilan", "core:parametres", "accounts:utilisateurs"]:
            with self.subTest(reserve_au_gerant=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 403)

    def test_creer_equipe_cree_les_12_comptes(self):
        from collections import Counter
        from io import StringIO

        from django.core.management import call_command

        from accounts.models import User

        call_command("creer_equipe", stdout=StringIO())
        call_command("creer_equipe", stdout=StringIO())
        equipe = User.objects.filter(username__in=["ducart", "julio", "germain", "adelaide", "carine", "nina", "junior",
                                                   "aurelle", "merveille", "liliane"])
        self.assertEqual(Counter(equipe.values_list("role", flat=True)),
                         {"ADMIN": 1, "ADJOINT": 2, "GOUVERNANTE": 1, "RECEPTIONNISTE": 3, "BAR_RESTAURANT": 3})
        self.assertEqual((str(User.objects.get(username="ducart")), User.objects.get(username="ducart").role),
                         ("M. Ducart", "ADMIN"))
        sans_compte = Employe.objects.filter(user__isnull=True)
        self.assertEqual(Counter(sans_compte.values_list("departement", flat=True)), {"MENAGE": 3, "SECURITE": 1},
                         "chambres / blanchisserie et gardien : seulement dans les salaires")
        self.assertEqual(str(User.objects.get(username="nina")), "Nina", "son prénom sur les fiches (R1, R2, R3)")
        chambres = Employe.objects.filter(user__isnull=True, departement=Departement.MENAGE)
        self.assertEqual(sorted(str(e) for e in chambres), ["Benedite", "Blondelle", "Carine"])
        self.assertEqual(Employe.objects.filter(nom="Carine").count(), 2, "deux Carine : réception et chambres")
        # Mot de passe provisoire : à la première connexion, on choisit ses propres codes avant tout le reste.
        reception1 = User.objects.get(username="carine")
        self.client.force_login(reception1)
        self.assertRedirects(self.client.get(reverse("caisse:ma_caisse")), reverse("accounts:premiere_connexion"))
        page = self.client.post(reverse("accounts:premiere_connexion"), {
            "mot_de_passe": "Demo1234!", "confirmation": "Demo1234!", "pin": "1234", "pin_confirmation": "1234"})
        self.assertContains(page, "différent du mot de passe provisoire")
        self.assertContains(page, "trop facile")
        self.client.post(reverse("accounts:premiere_connexion"), {
            "mot_de_passe": "Recep-Elie-2026", "confirmation": "Recep-Elie-2026", "pin": "4826", "pin_confirmation": "4826"})
        reception1.refresh_from_db()
        self.assertFalse(reception1.doit_changer_secret)
        self.assertTrue(reception1.check_pin("4826") and reception1.check_password("Recep-Elie-2026"))
        self.assertEqual(self.client.get(reverse("core:accueil"), follow=True).redirect_chain[-1][0],
                         reverse("postes:reception"))


class GouvernanteTests(BaseTest):
    def test_la_gouvernante_encadre_ses_trois_equipes_et_valide_les_caisses(self):
        from caisse import services as caisse

        adelaide = self.utilisateur("adelaide", Role.GOUVERNANTE)
        self.assertFalse(adelaide.tient_caisse, "elle n'a pas de caisse à elle")
        session = self.ouvrir()
        self.encaisser_especes(session, self.sejour(), 10000)
        self.remettre(session, 30000)
        self.client.force_login(adelaide)
        menu = self.client.get(reverse("core:accueil"))
        self.assertContains(menu, "Caisses à valider")
        self.assertNotContains(menu, "Ma caisse")
        self.assertEqual(self.client.get(reverse("caisse:session", args=[session.pk])).status_code, 200)
        caisse.valider_session(session, adelaide)
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionCaisse.Statut.VALIDEE)

        from personnel.services import employes_geres

        for departement in (Departement.RECEPTION, Departement.BAR, Departement.MENAGE, Departement.SECURITE):
            Employe.objects.create(nom=f"Employé {departement}", poste="x", departement=departement)
        self.assertEqual(set(employes_geres(adelaide).values_list("departement", flat=True)),
                         {"RECEPTION", "BAR", "MENAGE"}, "ses trois équipes, pas le gardien")
        for nom in ["stock:articles", "stock:ecarts", "hotel:sejours", "hotel:chambres", "hotel:menage",
                    "personnel:planning", "caisse:rapports", "fiches:index"]:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)
        for nom in ["paie:fiches", "finances:bilan", "core:parametres", "accounts:utilisateurs"]:
            with self.subTest(reserve_au_gerant=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 403)

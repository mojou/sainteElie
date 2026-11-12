"""Planning façon tableau de bord, et projets en colonnes (à faire, en cours, bloquée, faite)."""
from datetime import time, timedelta

from django.urls import reverse

from accounts.models import Role
from core.utils import aujourd_hui
from personnel.models import Affectation, Creneau, Departement, DemandeConge, Employe, Statut

from .base import BaseTest


class PlanningTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.matin = Creneau.objects.create(nom="Matin", heure_debut=time(7), heure_fin=time(15))
        self.soir = Creneau.objects.create(nom="Après-midi", heure_debut=time(15), heure_fin=time(23))
        self.nuit = Creneau.objects.create(nom="Nuit", heure_debut=time(23), heure_fin=time(7))
        self.nina = Employe.objects.create(nom="N", prenom="Nina", poste="Réceptionniste",
                                           departement=Departement.RECEPTION)
        self.junior = Employe.objects.create(nom="J", prenom="Junior", poste="Réceptionniste",
                                             departement=Departement.RECEPTION)
        self.jour = aujourd_hui()
        self.client.force_login(self.gerant)
        self.url = reverse("personnel:planning")

    def poster(self, **donnees):
        return self.client.post(self.url, donnees, follow=True)

    def test_heures_des_creneaux(self):
        self.assertEqual((self.matin.heures, self.nuit.heures), (8, 8))

    def test_ajouter_changer_deplacer_retirer(self):
        self.poster(action="ajouter", employe=self.nina.pk, date=self.jour.isoformat(), creneau=self.matin.pk, note="")
        a = Affectation.objects.get()
        page = self.client.get(self.url)
        self.assertContains(page, 'class="gantt-shift creneau-c0"')
        self.assertContains(page, "8 h")
        self.poster(action="modifier", pk=a.pk, employe=self.nina.pk, date=self.jour.isoformat(), creneau=self.soir.pk,
                    note="remplace Junior")
        a.refresh_from_db()
        self.assertEqual((a.creneau, a.note), (self.soir, "remplace Junior"))
        demain = self.jour + timedelta(days=1)
        self.poster(action="deplacer", pk=a.pk, employe=self.junior.pk, date=demain.isoformat())
        a.refresh_from_db()
        self.assertEqual((a.employe, a.date, a.creneau), (self.junior, demain, self.soir), "glisser garde le créneau")
        self.poster(action="supprimer", pk=a.pk)
        self.assertFalse(Affectation.objects.exists())

    def test_chevauchement_refuse_meme_la_nuit(self):
        tot = Creneau.objects.create(nom="Tôt", heure_debut=time(6), heure_fin=time(14))
        self.poster(action="ajouter", employe=self.nina.pk, date=self.jour.isoformat(), creneau=self.nuit.pk)
        reponse = self.poster(action="ajouter", employe=self.nina.pk, date=(self.jour + timedelta(days=1)).isoformat(),
                              creneau=tot.pk)
        self.assertContains(reponse, "travaille déjà à ce moment-là", msg_prefix="la nuit finit à 7 h, pas à minuit")
        self.poster(action="ajouter", employe=self.nina.pk, date=(self.jour + timedelta(days=1)).isoformat(),
                    creneau=self.soir.pk)
        self.assertEqual(Affectation.objects.count(), 2, "le lendemain après-midi ne chevauche pas la nuit")

    def test_pas_de_creneau_pendant_un_conge(self):
        DemandeConge.objects.create(employe=self.nina, date_debut=self.jour, date_fin=self.jour + timedelta(days=2),
                                    statut=Statut.ACCEPTEE)
        reponse = self.poster(action="ajouter", employe=self.nina.pk, date=self.jour.isoformat(), creneau=self.matin.pk)
        self.assertContains(reponse, "est en congé ce jour-là")
        self.assertContains(self.client.get(self.url), 'class="gantt-conge"')

    def test_copier_la_semaine_precedente(self):
        lundi = self.jour - timedelta(days=self.jour.weekday())
        for i in range(3):
            Affectation.objects.create(employe=self.nina, date=lundi - timedelta(days=7 - i), creneau=self.matin)
        Affectation.objects.create(employe=self.nina, date=lundi + timedelta(days=1), creneau=self.matin)
        reponse = self.client.post(f"{self.url}?vue=semaine&date={lundi.isoformat()}", {"action": "copier"}, follow=True)
        self.assertContains(reponse, "2 créneau(x) recopié(s)")
        self.assertContains(reponse, "1 sauté(s)")
        self.assertEqual(Affectation.objects.filter(date__gte=lundi).count(), 3)

    def test_vue_mois_et_filtre_departement(self):
        Employe.objects.create(nom="A", prenom="Aurelle", poste="Bar", departement=Departement.BAR)
        page = self.client.get(self.url, {"vue": "mois", "date": self.jour.isoformat(), "dep": "RECEPTION"})
        self.assertContains(page, 'class="gantt mois"')
        self.assertContains(page, "Nina")
        self.assertNotContains(page, "Aurelle")

    def test_on_ne_planifie_que_son_equipe(self):
        chef = self.utilisateur("cheffe", Role.CHEF_RECEPTION)
        bar = Employe.objects.create(nom="M", prenom="Merveille", poste="Bar", departement=Departement.BAR)
        self.client.force_login(chef)
        self.client.post(self.url, {"action": "ajouter", "employe": bar.pk, "date": self.jour.isoformat(),
                                    "creneau": self.matin.pk})
        self.assertFalse(Affectation.objects.filter(employe=bar).exists())


class ProjetsTests(BaseTest):
    def setUp(self):
        super().setUp()
        from projets.models import Projet

        self.projet = Projet.objects.create(nom="Peinture du hall", responsable=self.gerant, statut="EN_COURS")
        self.client.force_login(self.gerant)

    def test_colonnes_ajout_rapide_et_cartes(self):
        from projets.models import Tache

        url = reverse("projets:projet", args=[self.projet.pk])
        self.client.post(url, {"titre": "Acheter la peinture", "statut": "EN_COURS"})
        tache = Tache.objects.get()
        self.assertEqual(tache.statut, "EN_COURS")
        page = self.client.get(url)
        for texte in ("À faire", "En cours", "Bloquée", "Faite", "Acheter la peinture", "data-kanban"):
            self.assertContains(page, texte)
        liste = self.client.get(reverse("projets:liste"))
        self.assertContains(liste, "0</strong>/1 tâches faites")
        self.assertContains(liste, "1 en cours")

    def test_glisser_change_l_etape_et_le_note(self):
        from projets.models import Tache

        tache = Tache.objects.create(projet=self.projet, titre="Poncer les murs")
        reponse = self.client.post(reverse("projets:tache_statut", args=[tache.pk]), {"statut": "BLOQUEE"},
                                   HTTP_X_REQUESTED_WITH="fetch")
        self.assertJSONEqual(reponse.content, {"ok": True, "statut": "BLOQUEE", "change": True})
        tache.refresh_from_db()
        self.assertEqual(tache.statut, "BLOQUEE")
        self.assertTrue(tache.commentaires.filter(systeme=True, texte="Étape : À faire → Bloquée").exists())
        etoile = self.client.post(reverse("projets:tache_priorite", args=[tache.pk]), HTTP_X_REQUESTED_WITH="fetch")
        self.assertJSONEqual(etoile.content, {"ok": True, "haute": True})

    def test_fiche_discussion_et_droits(self):
        from projets.models import Tache

        aicha = self.aicha
        tache = Tache.objects.create(projet=self.projet, titre="Choisir la couleur", assigne_a=aicha)
        url = reverse("projets:tache", args=[tache.pk])
        self.client.post(url, {"action": "commenter", "texte": "Le blanc cassé est en stock."})
        self.client.force_login(aicha)
        page = self.client.get(url)
        self.assertContains(page, "Le blanc cassé est en stock.")
        self.assertNotContains(page, "Modifier la tâche", msg_prefix="la personne chargée ne modifie pas la fiche")
        self.client.post(url, {"action": "etape", "statut": "FAITE"})
        tache.refresh_from_db()
        self.assertEqual(tache.statut, "FAITE")
        self.assertContains(self.client.get(reverse("projets:mes_taches")), "Choisir la couleur")
        autre = Tache.objects.create(projet=self.projet, titre="Pas à moi")
        self.assertEqual(self.client.get(reverse("projets:tache", args=[autre.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("projets:tache_statut", args=[autre.pk]), {"statut": "FAITE"}).status_code, 403)



class AuditFormulairesTests(PlanningTests):
    """Défauts trouvés par l'audit de tous les formulaires et liens (11/11/2026)."""

    def test_planning_sans_numero_ne_plante_pas(self):
        for donnees in ({"action": "supprimer", "pk": ""}, {"action": "deplacer", "pk": "", "employe": "", "date": ""},
                        {"action": "modifier", "pk": "abc"}, {"action": "ajouter", "employe": "", "date": "",
                                                              "creneau": ""}):
            with self.subTest(donnees=donnees):
                reponse = self.client.post(self.url, donnees, follow=True)
                self.assertEqual(reponse.status_code, 200)
                self.assertContains(reponse, "Choisissez")

    def test_liens_reserves_au_gerant_et_a_la_caisse(self):
        gouvernante = self.utilisateur("adelaide", Role.GOUVERNANTE)
        self.client.force_login(gouvernante)
        self.assertNotContains(self.client.get(self.url), reverse("personnel:creneaux"))
        plan = self.client.get(reverse("postes:reception"))
        self.assertNotContains(plan, f'href="{reverse("caisse:ventes")}"')
        self.assertNotContains(self.client.get(reverse("postes:arrivee")), reverse("caisse:ma_caisse"))
        self.client.force_login(self.gerant)
        self.assertContains(self.client.get(self.url), reverse("personnel:creneaux"))

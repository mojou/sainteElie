"""Saisir un jour passé (fiches papier, oubli) : caisses, chambres et paiements, ventes du bar ; direction seulement."""
from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.models import Role
from caisse import passe
from caisse import services as caisse
from caisse.models import Encaissement, SessionCaisse
from core.utils import aujourd_hui, maintenant
from fiches import services as fiches
from hotel.models import Chambre, Sejour

from .test_comptoir import BaseComptoir


class JourPasseTests(BaseComptoir):
    def setUp(self):
        super().setUp()
        self.adjoint = self.utilisateur("julio", Role.ADJOINT)
        self.j = aujourd_hui() - timedelta(days=3)
        self.url = reverse("caisse:jour_passe")

    def poster(self, action, **donnees):
        prefixe = {"caisse", "sejour", "paiement", "vente"}
        champs = {(f"{action}-{k}" if action in prefixe else k): v for k, v in donnees.items()}
        return self.client.post(self.url, {"date": self.j.isoformat(), "action": action, **champs}, follow=True)

    def caisse_reception(self):
        return passe.ajouter_caisse(self.gerant, self.j, self.tiroir, self.aicha, "MATIN", time(8, 0), 20000,
                                    time(16, 0), 70000)

    def test_seule_la_direction(self):
        for user in (self.aicha, self.chef, self.jean):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403, user)
        for user in (self.gerant, self.adjoint):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 200, user)
        with self.assertRaisesMessage(ValidationError, "gérant et les adjoints"):
            passe.ajouter_caisse(self.chef, self.j, self.tiroir, self.aicha, "MATIN", time(8), 0, time(16), 0)
        with self.assertRaisesMessage(ValidationError, "jour passé"):
            passe.ajouter_caisse(self.gerant, aujourd_hui(), self.tiroir, self.aicha, "MATIN", time(8), 0, time(16), 0)

    def test_une_journee_passee_complete_depuis_l_ecran(self):
        self.client.force_login(self.gerant)
        page = self.poster("caisse", tiroir=self.tiroir.pk, titulaire=self.aicha.pk, shift="MATIN",
                           heure_ouverture="08:00", ouverture=20000, heure_fermeture="16:00", fermeture=70000)
        self.assertContains(page, "enregistrée")
        session = SessionCaisse.objects.get(saisie_passee=True)
        self.assertEqual((session.statut, session.ouverte_le.date(), session.remise.finalisee),
                         (SessionCaisse.Statut.VALIDEE, self.j, True))

        page = self.poster("sejour", nom="M. Owona", telephone="699112233", chambre=self.chambre.pk,
                           date_arrivee=self.j.isoformat(), heure_arrivee="14:30", nuits=2, heure_depart="11:00")
        self.assertContains(page, "enregistré en chambre 101")
        s = Sejour.objects.get(client__nom="M. Owona")
        self.assertEqual((s.statut, s.nuitees.count(), s.total_facture), (Sejour.Statut.TERMINE, 2, 50000))
        self.assertEqual(s.check_out_le.date(), self.j + timedelta(days=2))

        page = self.poster("paiement", sejour=s.pk, nature="ACOMPTE", montant=50000, moyen="ESPECES",
                           session=session.pk, heure="14:45")
        self.assertContains(page, "Paiement de")
        e = Encaissement.objects.get(sejour=s)
        self.assertEqual((e.date.date(), e.utilisateur), (self.j, self.aicha), "daté du jour passé, reçu par Aïcha")
        session.refresh_from_db()
        self.assertEqual((session.remise.especes_attendues, session.remise.ecart), (70000, 0))

        # La fiche recette chambres de ce jour se remplit
        d = fiches.fiche_hebergement(self.j)
        ligne = next(x for x in d["lignes"] if x["chambre"] == self.chambre)
        self.assertEqual((ligne["recette"], ligne["avance"], ligne["heure_arrivee"]), (25000, 25000, "14:30"))
        self.assertEqual((d["entete"]["ouverture"], d["entete"]["fermeture"], d["entete"]["heure"]),
                         (20000, 70000, "08:00 à 16:00"))
        self.assertEqual(d["totaux"]["montant"], 50000)
        depart = fiches.fiche_hebergement(self.j + timedelta(days=2))
        self.assertEqual(next(x for x in depart["lignes"] if x["chambre"] == self.chambre)["heure_depart"], "11:00")

        # Le bar de ce jour
        self.poster("caisse", tiroir=self.tiroir_bar.pk, titulaire=self.jean.pk, shift="APRES_MIDI",
                    heure_ouverture="15:00", ouverture=10000, heure_fermeture="02:00", fermeture=12000)
        bar = SessionCaisse.objects.get(saisie_passee=True, tiroir=self.tiroir_bar)
        self.assertEqual(bar.remise_le.date(), self.j + timedelta(days=1), "caisse de nuit fermée le lendemain")
        self.poster("vente", session=bar.pk, article=self.biere.pk, quantite=2, paiement="ORANGE_MONEY", heure="20:00")
        self.poster("vente", session=bar.pk, article=self.plat.pk, quantite=1, paiement="CHAMBRE", sejour=s.pk,
                    heure="20:30")
        b = fiches.fiche_bar_restaurant(self.j)
        self.assertEqual((b["totaux"]["cash"], b["totaux"]["mobile"], b["totaux"]["credit"]), (2000, 2000, 6500))
        s.refresh_from_db()
        self.assertEqual(s.reste_a_payer, 6500, "le plat sur la chambre s'ajoute à la note")
        self.biere.refresh_from_db()
        self.assertEqual(self.biere.quantite, 24, "le stock d'aujourd'hui n'est pas touché")

    def test_ni_rapport_du_jour_ni_especes_prevues(self):
        session = self.caisse_reception()
        self.client.force_login(self.gerant)
        recu = self.client.get(reverse("caisse:recu_remise", args=[session.pk]))
        self.assertEqual((recu.status_code, recu["Content-Type"]), (200, "application/pdf"),
                         "le reçu de remise d'une caisse passée s'ouvre")
        self.assertEqual(caisse.especes_ouverture_prevues(self.tiroir), 20000, "le fond, pas la caisse passée")
        rapport = caisse.creer_rapport(maintenant() - timedelta(days=1), maintenant())
        self.assertFalse(rapport.sessions.filter(saisie_passee=True).exists())

    def test_client_encore_la_et_chambre_deja_prise(self):
        arrivee = aujourd_hui() - timedelta(days=2)
        s = passe.sejour_passe(self.gerant, nom="Mme Ewodo", telephone="677000999", chambre=self.chambre,
                               arrivee=arrivee, nuits=4, heure_arrivee=time(19, 0))
        self.chambre.refresh_from_db()
        self.assertEqual((s.statut, s.nuitees.count(), self.chambre.statut),
                         (Sejour.Statut.EN_COURS, 2, Chambre.Statut.OCCUPEE))
        with self.assertRaisesMessage(ValidationError, "déjà prise par Mme Ewodo"):
            passe.sejour_passe(self.gerant, nom="X", telephone="600", chambre=self.chambre,
                               arrivee=arrivee - timedelta(days=1), nuits=2, heure_arrivee=time(12), heure_depart=time(10))
        with self.assertRaisesMessage(ValidationError, "heure de départ"):
            passe.sejour_passe(self.gerant, nom="Y", telephone="601",
                               chambre=Chambre.objects.create(numero="202", tarif_nuit=15000),
                               arrivee=self.j, nuits=1, heure_arrivee=time(12))

    def test_corriger_une_erreur(self):
        session = self.caisse_reception()
        s = passe.sejour_passe(self.gerant, nom="M. Erreur", telephone="611", chambre=self.chambre, arrivee=self.j,
                               nuits=1, heure_arrivee=time(15), heure_depart=time(10))
        e = passe.paiement_passe(self.gerant, session, s, "ACOMPTE", "ESPECES", 25000, time(15, 5))
        with self.assertRaisesMessage(ValidationError, "paiements ou des ventes"):
            passe.supprimer_caisse(self.gerant, session)
        self.client.force_login(self.gerant)
        self.poster("annuler_paiement", pk=e.pk)
        self.assertTrue(e.est_annule)
        self.assertEqual(fiches.fiche_hebergement(self.j)["totaux"]["montant"], 0)
        with self.assertRaisesMessage(ValidationError, "paiements"):
            passe.supprimer_sejour(self.gerant, s)   # le reçu annulé reste : on garde la trace
        autre = passe.sejour_passe(self.gerant, nom="M. Doublon", telephone="612",
                                   chambre=Chambre.objects.create(numero="203", tarif_nuit=15000), arrivee=self.j,
                                   nuits=1, heure_arrivee=time(15), heure_depart=time(10))
        self.poster("supprimer_sejour", pk=autre.pk)
        self.assertFalse(Sejour.objects.filter(pk=autre.pk).exists())

    def test_liens_vers_la_saisie(self):
        self.client.force_login(self.gerant)
        fiche = self.client.get(reverse("fiches:hebergement"), {"date": self.j.isoformat()})
        self.assertContains(fiche, f"{self.url}?date={self.j.isoformat()}")
        self.assertContains(self.client.get(reverse("core:pages")), self.url)
        self.client.force_login(self.aicha)
        self.assertNotContains(self.client.get(reverse("fiches:hebergement"), {"date": self.j.isoformat()}), self.url)


class SejourPasseDepuisLaReservationTests(BaseComptoir):
    """« Nouvelle réservation » avec des dates passées : enregistré directement « Libéré », chambre libre."""

    def donnees(self, **extra):
        j = aujourd_hui()
        return {"nouveau_client_nom": "M. Papier", "nouveau_client_telephone": "690112233",
                "chambre": self.chambre.pk, "date_arrivee": (j - timedelta(days=4)).isoformat(),
                "date_depart": (j - timedelta(days=2)).isoformat(), "nb_personnes": 1, **extra}

    def test_la_direction_enregistre_un_sejour_passe_libere(self):
        self.client.force_login(self.gerant)
        page = self.client.get(reverse("hotel:sejour_nouveau"))
        self.assertContains(page, "Heure d&#x27;arrivée du client")
        reponse = self.client.post(reverse("hotel:sejour_nouveau"),
                                   self.donnees(heure_arrivee="15:10", heure_depart="10:45"), follow=True)
        s = Sejour.objects.get(client__nom="M. Papier")
        self.assertEqual((s.statut, s.get_statut_display(), s.saisi_apres_coup), (Sejour.Statut.TERMINE, "Libéré", True))
        self.assertEqual(s.nuitees.count(), 2)
        self.assertEqual((s.heure_arrivee.strftime("%H:%M"), s.heure_depart.strftime("%H:%M")), ("15:10", "10:45"))
        self.assertEqual(s.check_out_le.date(), s.date_depart)
        self.chambre.refresh_from_db()
        self.assertEqual(self.chambre.statut, Chambre.Statut.LIBRE, "pas de ménage à faire : la chambre reste libre")
        self.assertContains(reponse, "libérée")
        self.assertContains(reponse, '<span class="badge TERMINE">Libéré</span>', html=False)
        ligne = next(x for x in fiches.fiche_hebergement(s.date_arrivee)["lignes"] if x["chambre"] == self.chambre)
        self.assertEqual((ligne["sejour"], ligne["heure_arrivee"]), (s, "15:10"))

    def test_heures_obligatoires_et_chambre_deja_prise(self):
        self.client.force_login(self.gerant)
        page = self.client.post(reverse("hotel:sejour_nouveau"), self.donnees())
        self.assertContains(page, "indiquez l&#x27;heure d&#x27;arrivée du client")
        self.assertFalse(Sejour.objects.exists())
        self.client.post(reverse("hotel:sejour_nouveau"), self.donnees(heure_arrivee="15:00", heure_depart="10:00"))
        page = self.client.post(reverse("hotel:sejour_nouveau"),
                                self.donnees(nouveau_client_nom="M. Doublon", heure_arrivee="16:00", heure_depart="9:00"))
        self.assertContains(page, "était déjà prise par M. Papier")

    def test_la_reception_ne_saisit_pas_le_passe(self):
        self.client.force_login(self.aicha)
        page = self.client.post(reverse("hotel:sejour_nouveau"), self.donnees(heure_arrivee="15:00", heure_depart="10:00"))
        self.assertContains(page, "seuls le gérant, le PDG et les adjoints")
        self.assertFalse(Sejour.objects.exists())

    def test_une_reservation_a_venir_reste_reservee(self):
        self.client.force_login(self.gerant)
        j = aujourd_hui()
        self.client.post(reverse("hotel:sejour_nouveau"), self.donnees(
            date_arrivee=(j + timedelta(days=1)).isoformat(), date_depart=(j + timedelta(days=3)).isoformat()))
        self.assertEqual(Sejour.objects.get().statut, Sejour.Statut.RESERVE)

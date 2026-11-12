from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import Alerte
from core.utils import aujourd_hui
from hotel import services
from hotel.models import Chambre, Extra, Nuitee, Sejour

from .base import BaseTest


class DisponibiliteTests(BaseTest):
    def test_chevauchement_refuse_avec_message_clair(self):
        j = aujourd_hui() + timedelta(days=10)
        self.sejour(arrivee=j, depart=j + timedelta(days=2), statut=Sejour.Statut.RESERVE)
        with self.assertRaisesMessage(ValidationError, "La chambre 101 est déjà réservée du"):
            services.verifier_disponibilite(self.chambre, j + timedelta(days=1), j + timedelta(days=3))

    def test_depart_et_arrivee_le_meme_jour_acceptes(self):
        j = aujourd_hui() + timedelta(days=10)
        self.sejour(arrivee=j, depart=j + timedelta(days=2), statut=Sejour.Statut.RESERVE)
        services.verifier_disponibilite(self.chambre, j + timedelta(days=2), j + timedelta(days=4))
        services.verifier_disponibilite(self.chambre, j - timedelta(days=2), j)

    def test_sejour_annule_ne_bloque_plus(self):
        j = aujourd_hui() + timedelta(days=10)
        s = self.sejour(arrivee=j, depart=j + timedelta(days=2), statut=Sejour.Statut.RESERVE)
        services.annuler(s, self.aicha, "Client a prévenu")
        services.verifier_disponibilite(self.chambre, j, j + timedelta(days=2))

    def test_annulation_sans_motif_refusee(self):
        s = self.sejour(statut=Sejour.Statut.RESERVE)
        with self.assertRaises(ValidationError):
            services.annuler(s, self.aicha, "")


class SejourTests(BaseTest):
    def test_check_in_puis_check_out_facture_les_nuits_passees(self):
        s = self.sejour(arrivee=aujourd_hui() - timedelta(days=2), depart=aujourd_hui() + timedelta(days=2),
                        statut=Sejour.Statut.RESERVE)
        services.check_in(s, self.aicha)
        self.chambre.refresh_from_db()
        self.assertEqual(self.chambre.statut, Chambre.Statut.OCCUPEE)
        services.check_out(s, self.aicha)
        s.refresh_from_db()
        self.chambre.refresh_from_db()
        self.assertEqual(s.statut, Sejour.Statut.TERMINE)
        self.assertEqual(s.date_depart, aujourd_hui(), "départ anticipé : la date de départ suit la réalité")
        self.assertEqual(s.nuitees.count(), 2)
        self.assertEqual(s.total_facture, 50000)
        self.assertEqual(self.chambre.statut, Chambre.Statut.A_NETTOYER)

    def test_check_in_refuse_si_chambre_pas_faite(self):
        self.chambre.statut = Chambre.Statut.A_NETTOYER
        self.chambre.save()
        s = self.sejour(statut=Sejour.Statut.RESERVE)
        with self.assertRaisesMessage(ValidationError, "pas encore faite"):
            services.check_in(s, self.aicha)

    def test_nuitee_constatee_le_lendemain(self):
        s = self.sejour(arrivee=aujourd_hui() - timedelta(days=1))
        self.assertEqual(services.constater_nuitees(), 1)
        self.assertEqual(services.constater_nuitees(), 0, "jamais deux fois la même nuit")
        self.assertTrue(Nuitee.objects.filter(sejour=s, date_nuit=aujourd_hui() - timedelta(days=1)).exists())

    def test_exemple_du_cahier_des_charges_recette_et_encaissement(self):
        """25 000 x 3 nuits, acompte 50 000, solde 25 000 au départ : 75 000 de recette, 75 000 encaissés."""
        s = self.sejour(arrivee=aujourd_hui() - timedelta(days=3), depart=aujourd_hui())
        session = self.ouvrir()
        from caisse import services as caisse
        caisse.encaisser(session, self.aicha, s, "ACOMPTE", "ESPECES", 50000)
        services.check_out(s, self.aicha)
        s.refresh_from_db()
        self.assertEqual(s.total_nuitees, 75000)
        self.assertEqual(s.reste_a_payer, 25000)
        self.encaisser_especes(session, s, 25000)
        self.assertEqual(s.reste_a_payer, 0)


class ExtraEtMenageTests(BaseTest):
    def test_extra_sur_la_note_et_annulation_motivee(self):
        s = self.sejour()
        extra = services.ajouter_extra(s, self.aicha, Extra.Source.BAR, "2 bières", 2000)
        self.assertEqual(s.total_extras, 2000)
        with self.assertRaises(ValidationError):
            services.annuler_extra(extra, self.aicha, "")
        services.annuler_extra(extra, self.aicha, "Erreur de chambre")
        self.assertEqual(s.total_extras, 0)
        self.assertTrue(Alerte.objects.filter(type=Alerte.Type.ANNULATION).exists())

    def test_extra_refuse_sur_sejour_pas_en_cours(self):
        s = self.sejour(statut=Sejour.Statut.RESERVE)
        with self.assertRaises(ValidationError):
            services.ajouter_extra(s, self.aicha, Extra.Source.BAR, "Bière", 1000)

    def test_chambre_faite_sans_sejour_declenche_une_alerte(self):
        services.marquer_nettoyee(self.chambre, self.aicha)
        self.assertTrue(Alerte.objects.filter(type=Alerte.Type.MENAGE_SANS_SEJOUR).exists())

    def test_chambre_faite_apres_un_depart_ne_declenche_rien(self):
        s = self.sejour(arrivee=aujourd_hui() - timedelta(days=1))
        Sejour.objects.filter(pk=s.pk).update(statut=Sejour.Statut.TERMINE, check_out_le=timezone.now())
        services.marquer_nettoyee(self.chambre, self.aicha)
        self.assertFalse(Alerte.objects.filter(type=Alerte.Type.MENAGE_SANS_SEJOUR).exists())

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from caisse import services as caisse
from caisse.models import Encaissement, RapportQuotidien, SessionCaisse, SortieCaisse
from core.models import Alerte
from hotel.models import Nuitee

from .base import BaseTest


class OuvertureTests(BaseTest):
    def test_premiere_ouverture_attend_le_fond(self):
        session = self.ouvrir()
        self.assertEqual(session.especes_ouverture_prevues, 20000)
        self.assertEqual(session.seuil_ecart, 1000)

    def test_tiroir_bloque_tant_que_la_session_precedente_n_est_pas_remise(self):
        self.ouvrir(self.aicha)
        with self.assertRaisesMessage(ValidationError, "n'est pas encore remise"):
            self.ouvrir(self.serge)

    def test_une_seule_session_ouverte_par_personne(self):
        self.ouvrir(self.aicha)
        with self.assertRaises(ValidationError):
            self.ouvrir(self.aicha)

    def test_fond_incomplet_signale_et_n_impute_pas_l_entrant(self):
        session = self.ouvrir(especes=18000)
        self.assertTrue(Alerte.objects.filter(type=Alerte.Type.FOND_INCOMPLET).exists())
        self.assertEqual(session.especes_attendues, 18000, "l'attendu part de ce qui a été réellement trouvé")


class EncaissementTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.session = self.ouvrir()
        self.s = self.sejour()

    def test_orange_money_et_mtn_momo_sans_rien_d_autre_a_saisir(self):
        om = caisse.encaisser(self.session, self.aicha, self.s, "REGLEMENT", "ORANGE_MONEY", 5000)
        momo = caisse.encaisser(self.session, self.aicha, self.s, "REGLEMENT", "MTN_MOMO", 3000, reference="ignorée")
        self.assertEqual((om.moyen_libelle, momo.moyen_libelle, momo.reference), ("Orange Money", "MTN MoMo", ""))
        self.assertEqual(self.session.especes_attendues, 20000, "Orange Money et MoMo ne vont pas dans le tiroir")
        with self.assertRaisesMessage(ValidationError, "référence est obligatoire"):
            caisse.encaisser(self.session, self.aicha, self.s, "REGLEMENT", "CHEQUE", 5000)

    def test_numeros_de_recu_continus(self):
        a = self.encaisser_especes(self.session, self.s, 1000)
        b = self.encaisser_especes(self.session, self.s, 1000)
        self.assertEqual(b.numero_recu, a.numero_recu + 1)

    def test_seul_le_titulaire_encaisse_dans_sa_session(self):
        with self.assertRaises(ValidationError):
            self.encaisser_especes(self.session, self.s, 1000, user=self.serge)

    def test_remboursement_especes_au_dela_du_plafond_exige_un_valideur(self):
        self.encaisser_especes(self.session, self.s, 30000)
        with self.assertRaisesMessage(ValidationError, "doit être validé"):
            caisse.encaisser(self.session, self.aicha, self.s, "REMBOURSEMENT", "ESPECES", 15000)
        with self.assertRaises(ValidationError):
            caisse.encaisser(self.session, self.aicha, self.s, "REMBOURSEMENT", "ESPECES", 15000, valideur=self.aicha)
        rembourse = caisse.encaisser(self.session, self.aicha, self.s, "REMBOURSEMENT", "ESPECES", 15000,
                                     valideur=self.chef)
        self.assertEqual(rembourse.montant_signe, -15000)
        self.assertEqual(self.session.especes_attendues, 20000 + 30000 - 15000)

    def test_annulation_dans_sa_session_ouverte(self):
        enc = self.encaisser_especes(self.session, self.s, 10000)
        with self.assertRaises(ValidationError):
            caisse.annuler_encaissement(enc, self.aicha, "")
        inverse = caisse.annuler_encaissement(enc, self.aicha, "Erreur de montant")
        self.assertEqual(inverse.session, self.session)
        self.assertEqual(self.session.especes_attendues, 20000)
        self.assertTrue(enc.est_annule)
        with self.assertRaises(ValidationError):
            caisse.annuler_encaissement(enc, self.aicha, "deux fois")
        self.assertTrue(Alerte.objects.filter(type=Alerte.Type.ANNULATION).exists())

    def test_annulation_apres_remise_passe_par_une_session_rectificative(self):
        enc = self.encaisser_especes(self.session, self.s, 10000)
        self.remettre(self.session, 30000)
        with self.assertRaisesMessage(ValidationError, "session rectificative"):
            caisse.annuler_encaissement(enc, self.aicha, "Erreur")
        inverse = caisse.annuler_encaissement(enc, self.chef, "Doublon constaté")
        self.assertTrue(inverse.session.est_rectificative)
        self.assertEqual(inverse.session.rectifie_session, self.session)
        self.assertEqual(Encaissement.objects.count(), 2, "rien n'est supprimé")


class SortieTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.session = self.ouvrir()

    def test_depense_et_prelevement_deduits_des_especes_attendues(self):
        caisse.creer_sortie(self.session, self.aicha, "DEPENSE", 3000, "Gaz")
        with self.assertRaisesMessage(ValidationError, "confirmé par le gérant"):
            caisse.creer_sortie(self.session, self.aicha, "PRELEVEMENT", 5000, "Fournisseur", valideur=self.chef)
        caisse.creer_sortie(self.session, self.aicha, "PRELEVEMENT", 5000, "Fournisseur", valideur=self.gerant)
        self.assertEqual(self.session.especes_attendues, 12000)

    def test_depense_au_dela_du_plafond_attend_validation_et_refus_cree_un_ecart(self):
        self.encaisser_especes(self.session, self.sejour(), 30000)
        sortie = caisse.creer_sortie(self.session, self.aicha, "DEPENSE", 15000, "Réparation")
        self.assertEqual(sortie.statut, SortieCaisse.Statut.A_VALIDER)
        self.assertEqual(self.session.especes_attendues, 35000)
        self.remettre(self.session, 35000)
        self.assertEqual(self.session.statut, SessionCaisse.Statut.REMISE)
        caisse.traiter_sortie(sortie, self.chef, accepter=False)
        self.session.refresh_from_db()
        self.assertEqual(self.session.statut, SessionCaisse.Statut.ECART)

    def test_sortie_impossible_au_dela_du_contenu_du_tiroir(self):
        with self.assertRaises(ValidationError):
            caisse.creer_sortie(self.session, self.aicha, "DEPENSE", 25000, "Trop")


class RemiseTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.session = self.ouvrir()
        self.encaisser_especes(self.session, self.sejour(), 125000)

    def test_comptage_a_l_aveugle_premier_comptage_conserve_un_seul_recomptage(self):
        caisse.enregistrer_comptage(self.session, self.aicha, 140000)
        caisse.enregistrer_comptage(self.session, self.aicha, 143500)
        remise = self.session.remise
        remise.refresh_from_db()
        self.assertEqual(remise.premier_comptage, 140000)
        self.assertEqual(remise.especes_comptees, 143500)
        with self.assertRaisesMessage(ValidationError, "recomptage a déjà été fait"):
            caisse.enregistrer_comptage(self.session, self.aicha, 145000)

    def test_ecart_hors_seuil_exige_un_motif_puis_passe_en_ecart(self):
        caisse.enregistrer_comptage(self.session, self.aicha, 143500)
        with self.assertRaisesMessage(ValidationError, "le motif est obligatoire"):
            caisse.finaliser_remise(self.session, self.aicha, "")
        remise = caisse.finaliser_remise(self.session, self.aicha, "Erreur de rendu de monnaie")
        self.assertEqual(remise.especes_attendues, 145000)
        self.assertEqual(remise.ecart, -1500)
        self.assertEqual(remise.versement, 123500)
        self.assertEqual(remise.especes_transmises, 20000)
        self.assertTrue(remise.recu_pdf.name.endswith(".pdf"))
        self.session.refresh_from_db()
        self.assertEqual(self.session.statut, SessionCaisse.Statut.ECART)

    def test_ecart_dans_le_seuil_sans_motif_et_shift_suivant_ouvre_sans_attendre_la_validation(self):
        self.remettre(self.session, 144000)
        self.session.refresh_from_db()
        self.assertEqual(self.session.statut, SessionCaisse.Statut.REMISE)
        suivante = self.ouvrir(self.serge)
        self.assertEqual(suivante.especes_ouverture_prevues, 20000)

    def test_validation_jamais_par_soi_meme_et_arbitrage_motive(self):
        self.remettre(self.session, 140000, motif="Billet manquant")
        with self.assertRaisesMessage(ValidationError, "réservée au chef de réception ou au gérant"):
            caisse.valider_session(self.session, self.aicha)
        with self.assertRaises(ValidationError):
            caisse.valider_session(self.session, self.serge)
        session_du_chef = self.ouvrir(self.chef)
        self.remettre(session_du_chef, 20000)
        with self.assertRaisesMessage(ValidationError, "Personne ne valide sa propre remise"):
            caisse.valider_session(session_du_chef, self.chef)
        caisse.valider_session(session_du_chef, self.gerant)
        with self.assertRaisesMessage(ValidationError, "décision d'arbitrage"):
            caisse.valider_session(self.session, self.chef)
        caisse.valider_session(self.session, self.chef, "PERTE_HOTEL", "Billet perdu, première fois")
        self.session.refresh_from_db()
        self.assertEqual(self.session.statut, SessionCaisse.Statut.VALIDEE)
        self.assertEqual(self.session.validee_par, self.chef)

    def test_contestation_d_une_remise(self):
        self.remettre(self.session, 145000)
        caisse.contester_session(self.session, self.chef, "Enveloppe de versement incomplète")
        self.assertEqual(self.session.statut, SessionCaisse.Statut.ECART)

    def test_cloture_d_office_par_le_chef(self):
        caisse.enregistrer_comptage(self.session, self.chef, 145000,
                                    cloture_office=True)
        with self.assertRaises(ValidationError):
            caisse.finaliser_remise(self.session, self.chef, "", cloture_office=True)
        caisse.finaliser_remise(self.session, self.chef, "Partie sans remise", cloture_office=True, entrant=self.serge)
        self.session.refresh_from_db()
        self.assertEqual(self.session.statut, SessionCaisse.Statut.ECART)
        self.assertTrue(self.session.cloture_office)
        with self.assertRaisesMessage(ValidationError, "Personne ne valide"):
            caisse.valider_session(self.session, self.chef, "AUTRE", "x")
        caisse.valider_session(self.session, self.gerant, "AUTRE", "Vu avec l'intéressée")

    def test_orange_money_et_momo_declares_a_la_cloture_ligne_par_ligne(self):
        caisse.encaisser(self.session, self.aicha, self.sejour(), "REGLEMENT", "ORANGE_MONEY", 55000)
        caisse.encaisser(self.session, self.aicha, self.sejour(), "REGLEMENT", "MTN_MOMO", 8000)
        # Deux téléphones Orange Money : deux lignes, additionnées.
        self.remettre(self.session, 145000, mobile={"ORANGE_MONEY": [50000, 5000], "MTN_MOMO": [8000]})
        self.session.refresh_from_db()
        remise = self.session.remise
        self.assertEqual((remise.ecart, self.session.statut), (0, SessionCaisse.Statut.REMISE))
        self.assertEqual([(m["libelle"], m["attendu"], m["declare"], m["ecart"]) for m in remise.lignes_mobile()],
                         [("Orange Money", 55000, 55000, 0), ("MTN MoMo", 8000, 8000, 0)])
        self.assertEqual(remise.detail_mobile["ORANGE_MONEY"], [50000, 5000])

    def test_plusieurs_montants_se_tapent_avec_un_plus(self):
        from caisse.forms import ComptageForm

        form = ComptageForm({"especes": 0, "cheques_nombre": 0, "cheques_total": 0,
                             "orange_money": "10 000 + 5000+", "mtn_momo": ""})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["mobile"], {"ORANGE_MONEY": [10000, 5000], "MTN_MOMO": []})

    def test_orange_money_manquant_exige_un_motif(self):
        caisse.encaisser(self.session, self.aicha, self.sejour(), "REGLEMENT", "ORANGE_MONEY", 55000)
        caisse.enregistrer_comptage(self.session, self.aicha, 145000, mobile={"ORANGE_MONEY": [45000]})
        with self.assertRaisesMessage(ValidationError, "le motif est obligatoire"):
            caisse.finaliser_remise(self.session, self.aicha, "")
        caisse.finaliser_remise(self.session, self.aicha, "Transfert de 10 000 pas encore arrivé")
        self.session.refresh_from_db()
        self.assertEqual((self.session.statut, self.session.remise.ecart_orange_money), (SessionCaisse.Statut.ECART, -10000))
        self.assertTrue(Alerte.objects.filter(message__contains="Orange Money").exists())

    def test_ecarts_recurrents_declenchent_une_alerte(self):
        self.remettre(self.session, 140000, motif="1")
        for _ in range(2):
            session = self.ouvrir(self.aicha)
            self.remettre(session, 15000, motif="encore")
        self.assertTrue(Alerte.objects.filter(type=Alerte.Type.ECART_RECURRENT, cle=f"recurrent-personne-{self.aicha.pk}")
                        .exists())


class VisibiliteTests(BaseTest):
    def test_receptionniste_ne_voit_que_ses_sessions_et_celles_qu_il_recoit(self):
        session = self.ouvrir(self.aicha)
        self.remettre(session, 20000, entrant=self.serge)
        autre = self.ouvrir(self.serge)
        self.assertEqual(set(caisse.sessions_visibles(self.aicha)), {session})
        self.assertEqual(set(caisse.sessions_visibles(self.serge)), {session, autre})
        self.assertEqual(caisse.sessions_visibles(self.chef).count(), 2)


class RapportTests(BaseTest):
    def test_rapport_reprend_chaque_session_une_seule_fois_avec_recettes_et_encaissements(self):
        s = self.sejour(arrivee=timezone.localdate() - timedelta(days=1))
        session = self.ouvrir()
        caisse.encaisser(session, self.aicha, s, "ACOMPTE", "ESPECES", 50000)
        self.remettre(session, 70000)
        rapports = caisse.generer_rapports_dus(timezone.now() + timedelta(days=2))
        self.assertGreaterEqual(len(rapports), 1)
        self.assertEqual(caisse.generer_rapports_dus(timezone.now() + timedelta(days=2)), [], "pas de doublon")
        session.refresh_from_db()
        rapport = session.rapport
        self.assertIsNotNone(rapport)
        self.assertTrue(rapport.debut < session.remise_le <= rapport.coupure)
        donnees = caisse.donnees_rapport(rapport)
        par_moyen = dict(zip([m["cle"] for m in donnees["moyens"]], donnees["totaux"]["moyens"]))
        self.assertEqual(par_moyen["ESPECES"], 50000)
        self.assertEqual((par_moyen["ORANGE_MONEY"], par_moyen["MTN_MOMO"]), (0, 0), "toujours une colonne chacun")
        self.assertEqual(sum(r.sessions.count() for r in RapportQuotidien.objects.all()), 1)
        nuitee = Nuitee.objects.get(sejour=s, date_nuit=timezone.localdate() - timedelta(days=1))
        rapport_nuitee = RapportQuotidien.objects.get(debut__lt=nuitee.constatee_le, coupure__gte=nuitee.constatee_le)
        self.assertEqual(caisse.donnees_rapport(rapport_nuitee)["total_nuitees"], 25000)
        self.assertTrue(rapport.pdf.name.endswith(".pdf"))

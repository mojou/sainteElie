"""Le reçu remis au client à chaque paiement et la facture du séjour (page à imprimer, PDF, espace client)."""
from datetime import timedelta

from django.urls import reverse

from accounts.models import Role, User
from caisse import services as caisse
from caisse.models import Encaissement
from core.models import Etablissement
from core.utils import aujourd_hui, format_fcfa
from hotel import services as hotel
from hotel.facturation import facture
from hotel.models import Client, Extra, Sejour
from vitrine.models import CompteClient

from .base import BaseTest


class FactureTests(BaseTest):
    def setUp(self):
        super().setUp()
        etab = Etablissement.get()
        etab.nom, etab.adresse, etab.telephone, etab.niu = ("Complexe St Élie Palace", "Bonamoussadi, Douala",
                                                           "699 00 00 00", "M0123456789")
        etab.save()

    def test_facture_provisoire_d_un_sejour_en_cours(self):
        s = self.sejour(arrivee=aujourd_hui() - timedelta(days=1), depart=aujourd_hui() + timedelta(days=2),
                        tarif=20000)
        hotel.ajouter_extra(s, self.aicha, Extra.Source.BAR, "2 × 33 Export", 2000, numero_bon="B12")
        session = self.ouvrir()
        self.encaisser_especes(session, s, 30000)
        f = facture(s)
        self.assertFalse(f.definitive)
        self.assertEqual(f.total, s.total_facture)
        self.assertEqual([(ligne.quantite, ligne.prix, ligne.montant) for ligne in f.lignes],
                         [(3, 20000, 60000), (1, 2000, 2000)])
        self.assertEqual(f.reste, 62000 - 30000)

        self.client.force_login(self.aicha)
        page = self.client.get(reverse("hotel:facture", args=[s.pk]))
        for texte in ("Facture provisoire", f"N° {f.numero}", "Complexe St Élie Palace", "Bonamoussadi, Douala",
                      "NIU / RCCM : M0123456789", "Chambre 101", "remise de 20 %", "2 × 33 Export", "bon n°B12",
                      "Reçu n°", "Arrêtée la présente facture à la somme de",
                      "Soixante-deux mille francs CFA", "Imprimer la facture", "Télécharger en PDF"):
            self.assertContains(page, texte)
        self.assertNotContains(page, "doc-tampon\">Payée")

        pdf = self.client.get(reverse("hotel:facture_pdf", args=[s.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn(f'attachment; filename="facture-{f.numero}.pdf"', pdf["Content-Disposition"])
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        sejour_page = self.client.get(reverse("hotel:sejour", args=[s.pk]))
        self.assertContains(sejour_page, reverse("hotel:facture", args=[s.pk]))

    def test_facture_definitive_apres_le_depart_et_payee(self):
        s = self.sejour(arrivee=aujourd_hui() - timedelta(days=2), depart=aujourd_hui())
        hotel.check_out(s, self.aicha)
        s.refresh_from_db()
        session = self.ouvrir()
        self.encaisser_especes(session, s, s.total_facture)
        f = facture(s)
        self.assertTrue(f.definitive)
        self.assertEqual(f.titre, "Facture")
        self.assertEqual([(ligne.quantite, ligne.montant) for ligne in f.lignes], [(2, 50000)])
        self.assertTrue(f.soldee)
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("hotel:facture", args=[s.pk]))
        self.assertContains(page, '<span class="doc-tampon">Payée</span>', html=False)
        self.assertNotContains(page, "Facture provisoire")

    def test_trop_paye_a_rendre(self):
        s = self.sejour(arrivee=aujourd_hui(), depart=aujourd_hui() + timedelta(days=1))
        self.encaisser_especes(self.ouvrir(), s, 30000)
        f = facture(s)
        self.assertEqual(f.a_rendre, 5000)
        self.client.force_login(self.aicha)
        self.assertContains(self.client.get(reverse("hotel:facture", args=[s.pk])), "À rendre au client")

    def test_seule_la_reception_voit_les_factures(self):
        s = self.sejour()
        cuisinier = self.utilisateur("cuisine", Role.BAR_RESTAURANT)
        self.client.force_login(cuisinier)
        self.assertEqual(self.client.get(reverse("hotel:facture", args=[s.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("hotel:facture_pdf", args=[s.pk])).status_code, 403)


class RecuTests(BaseTest):
    def test_recu_de_paiement_d_un_sejour(self):
        s = self.sejour(arrivee=aujourd_hui(), depart=aujourd_hui() + timedelta(days=2))
        session = self.ouvrir()
        enc = caisse.encaisser(session, self.aicha, s, Encaissement.Nature.ACOMPTE, Encaissement.Mode.ORANGE_MONEY,
                               20000)
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("caisse:recu_client", args=[enc.pk]))
        for texte in ("Reçu de paiement", f"N° {enc.numero_recu}", "M. Kamga", "699000000",
                      "Acompte - séjour en chambre 101", "Vingt mille francs CFA", "Orange Money",
                      "Reste à payer", format_fcfa(30000), "Le caissier", "Gardez ce reçu", "Facture du séjour",
                      "Télécharger en PDF"):
            self.assertContains(page, texte)
        pdf = self.client.get(reverse("caisse:recu_client_pdf", args=[enc.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn(f"recu-{enc.numero_recu}.pdf", pdf["Content-Disposition"])
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_recu_annule_le_dit(self):
        s = self.sejour()
        session = self.ouvrir()
        enc = self.encaisser_especes(session, s, 10000)
        annulation = caisse.annuler_encaissement(enc, self.chef, "erreur de montant")
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("caisse:recu_client", args=[enc.pk]))
        self.assertContains(page, "Il ne prouve plus aucun paiement")
        self.assertNotContains(page, "Tout est réglé")
        page = self.client.get(reverse("caisse:recu_client", args=[annulation.pk]))
        self.assertContains(page, "Annulation de reçu")
        self.assertContains(page, f"Annulation du reçu n°{enc.numero_recu}")
        self.assertEqual(self.client.get(reverse("caisse:recu_client_pdf", args=[annulation.pk])).status_code, 200)

    def test_le_recu_d_un_collegue_reste_prive(self):
        session = self.ouvrir(user=self.serge)
        enc = self.encaisser_especes(session, self.sejour(), 10000)
        cuisinier = self.utilisateur("bar", Role.BAR_RESTAURANT)
        self.client.force_login(cuisinier)
        self.assertEqual(self.client.get(reverse("caisse:recu_client_pdf", args=[enc.pk])).status_code, 403)


class FactureEspaceClientTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.user_client = User.objects.create_user("699000000", password="Demo1234!x", role=Role.CLIENT)
        self.compte = CompteClient.objects.create(user=self.user_client, nom="M. Kamga", telephone="699000000",
                                                  client=self.client_hotel, statut=CompteClient.Statut.RELIE)

    def test_le_client_telecharge_sa_facture_et_jamais_celle_d_un_autre(self):
        s = self.sejour()
        autre = Sejour.objects.create(client=Client.objects.create(nom="Autre", telephone="677000000"),
                                      chambre=self.chambre, date_arrivee=aujourd_hui() + timedelta(days=10),
                                      date_depart=aujourd_hui() + timedelta(days=11), tarif_grille=25000,
                                      tarif_nuit=25000, statut=Sejour.Statut.RESERVE, cree_par=self.gerant)
        self.client.force_login(self.user_client)
        espace = self.client.get(reverse("vitrine:espace"))
        self.assertContains(espace, reverse("vitrine:ma_facture", args=[s.pk]))
        pdf = self.client.get(reverse("vitrine:ma_facture", args=[s.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertEqual(self.client.get(reverse("vitrine:ma_facture", args=[autre.pk])).status_code, 404)
        self.compte.statut = CompteClient.Statut.EN_ATTENTE
        self.compte.save()
        self.assertRedirects(self.client.get(reverse("vitrine:ma_facture", args=[s.pk])), reverse("vitrine:espace"),
                             msg_prefix="compte pas encore vérifié par la réception : rien")
        self.client.logout()
        reponse = self.client.get(reverse("vitrine:ma_facture", args=[s.pk]))
        self.assertEqual(reponse.status_code, 302)

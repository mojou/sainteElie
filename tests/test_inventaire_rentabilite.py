"""Rapport d'inventaire et de rentabilité : un cas complet aux chiffres connus d'avance."""
import calendar

from django.urls import reverse

from accounts.models import Role
from caisse import services as caisse
from core.utils import aujourd_hui
from rapports import inventaire
from stock.services import enregistrer_mouvement

from .test_comptoir import BaseComptoir


class InventaireRentabiliteTests(BaseComptoir):
    """La bière : 24 en stock hier ; aujourd'hui livraison de 12 à 600 F, 10 vendues à 1 000 F, 1 offerte, 2 cassées,
    inventaire du soir : 22 comptées au lieu de 23. Un plat vendu sans coût connu. Une dépense, un salaire."""

    def setUp(self):
        super().setUp()
        from finances.models import Depense
        from paie.models import FichePaie
        from personnel.models import Departement, Employe

        self.jour = aujourd_hui()
        enregistrer_mouvement(self.biere, self.gerant, "ENTREE", 12, cout_unitaire=600)
        caisse.vendre_commande(self.bar, self.jean, [(self.biere, 10), (self.plat, 1)], "COMPTANT")
        caisse.vendre(self.bar, self.jean, self.biere, 1, "OFFERT", observation="Client fidèle")
        enregistrer_mouvement(self.biere, self.gerant, "AVARIE", 2, "bouteilles cassées")
        enregistrer_mouvement(self.biere, self.gerant, "INVENTAIRE", 22)
        Depense.objects.create(categorie="ENERGIE", libelle="Électricité", montant=5000, saisi_par=self.gerant)
        employe = Employe.objects.create(nom="N", prenom="Nina", poste="Réceptionniste", departement=Departement.RECEPTION)
        FichePaie.objects.create(employe=employe, mois=self.jour.replace(day=1), salaire_base=90000, primes=10000,
                                 statut=FichePaie.Statut.VALIDEE)

    def test_chiffres_de_la_biere(self):
        d = inventaire.rapport(self.jour, self.jour, finances=True)
        b = next(l for l in d["lignes"] if l["article"] == self.biere)
        # Inventaire : 24 + 12 − 11 (vendu ou offert) − 2 (casse) − 1 (écart) = 22
        self.assertEqual((b["debut"], b["entrees"], b["sorti_vente"], b["pertes"], b["ecart"], b["fin"]),
                         (24, 12, 11, 2, -1, 22))
        # Rentabilité : 10 vendues à 1 000 F, coût moyen 600 F
        self.assertEqual((b["vendu"], b["ca"], b["cout"], b["cmv"], b["marge"]), (10, 10000, 600, 6000, 4000))
        self.assertEqual((b["taux_marque"], b["coefficient"], b["marge_unitaire"]), (40.0, 1.67, 400))
        self.assertEqual((b["offert"], b["offert_cout"], b["pertes_valeur"], b["ecart_valeur"], b["valeur_fin"]),
                         (1, 600, 1200, -600, 13200))
        self.assertEqual((d["cmv"], d["marge"], d["taux_marque"], d["pertes"], d["ecarts"]), (6000, 4000, 40.0, 1200, -600))
        self.assertEqual(d["marge_nette_marchandises"], 4000 - 1200 - 600 - 600)
        self.assertEqual(d["ca_marchandises"], 10000 + 6500)
        self.assertEqual([l["article"] for l in d["sans_cout"]], [self.plat], "le plat n'a pas de coût : signalé")

    def test_charges_et_resultat(self):
        d = inventaire.rapport(self.jour, self.jour, finances=True)
        jours_mois = calendar.monthrange(self.jour.year, self.jour.month)[1]
        salaire_du_jour = round(100000 / jours_mois)
        self.assertEqual(d["salaires"], salaire_du_jour, "salaire brut au prorata d'un jour")
        self.assertEqual(d["charges"], 5000 + salaire_du_jour)
        self.assertEqual(d["resultat"], d["c"]["total"] - d["charges"])
        mois = inventaire.rapport(self.jour.replace(day=1), self.jour.replace(day=jours_mois), finances=True)
        self.assertEqual(mois["salaires"], 100000, "le mois entier : le salaire entier")

    def test_avertissements(self):
        d = inventaire.rapport(self.jour, self.jour, finances=True)
        notes = inventaire.avertissements(d, self.jour, self.jour, True)
        self.assertTrue(any("sans prix d'achat" in n and "Poulet DG" in n for n in notes))
        self.assertFalse(any("Aucun inventaire" in n for n in notes), "un inventaire a été compté")
        self.assertFalse(any("Salaires non comptés" in n for n in notes))

    def test_pages_pdf_excel_et_droits(self):
        url = reverse("rapports:inventaire")
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.get(url).status_code, 403)
        adjoint = self.utilisateur("julio", Role.ADJOINT)
        self.client.force_login(adjoint)
        page = self.client.get(url, {"periode": "jour"})
        self.assertContains(page, "Rentabilité par article")
        self.assertContains(page, "40 %")
        self.assertNotContains(page, "Charges et résultat", msg_prefix="charges et résultat : le gérant seulement")
        self.client.force_login(self.gerant)
        page = self.client.get(url, {"periode": "jour"})
        self.assertContains(page, "Charges et résultat")
        self.assertContains(page, "Résultat de gestion")
        pdf = self.client.get(url, {"periode": "jour", "format": "pdf"})
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        csv = self.client.get(url, {"periode": "jour", "format": "csv"}).content.decode("utf-8-sig")
        self.assertIn("Taux de marque %", csv)
        self.assertIn("33 EXPORT 65CL", csv)
        for periode in ("mois", "annee", "semaine_derniere"):
            self.assertEqual(self.client.get(url, {"periode": periode}).status_code, 200)

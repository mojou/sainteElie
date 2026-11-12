from django.core.exceptions import ValidationError

from core.models import Alerte
from core.utils import aujourd_hui, premier_du_mois
from paie import services as paie
from paie.models import Acompte, FichePaie
from personnel import services as personnel
from personnel.models import Affectation, Creneau, DemandeConge, Departement, Employe, Statut
from stock.models import Article
from stock.services import enregistrer_mouvement

from .base import BaseTest


class PaieTests(BaseTest):
    def test_fiche_deduit_les_acomptes_et_se_verrouille(self):
        employe = Employe.objects.create(nom="Fouda", prenom="Nadia", poste="Réceptionniste",
                                         departement=Departement.RECEPTION, salaire_base=110000)
        mois = premier_du_mois()
        Acompte.objects.create(employe=employe, date=aujourd_hui(), montant=20000, saisi_par=self.gerant)
        self.assertEqual(paie.generer_fiches(mois, self.gerant), 1)
        fiche = FichePaie.objects.get(employe=employe)
        fiche.primes = 5000
        fiche.cotisations = 4620
        fiche.save()
        paie.valider_fiche(fiche, self.gerant)
        fiche.refresh_from_db()
        self.assertEqual(fiche.net_a_payer, 110000 + 5000 - 4620 - 20000)
        self.assertTrue(fiche.pdf.name.endswith(".pdf"))
        with self.assertRaises(ValidationError):
            paie.valider_fiche(fiche, self.gerant)
        paie.marquer_payee(fiche, self.gerant, aujourd_hui(), "Mobile money")
        self.assertEqual(fiche.statut, FichePaie.Statut.PAYEE)


class StockTests(BaseTest):
    def test_sortie_limitee_au_stock_inventaire_et_alerte(self):
        article = Article.objects.create(nom="Bière", categorie="BAR", seuil_alerte=10)
        enregistrer_mouvement(article, self.gerant, "ENTREE", 24, "Livraison", 550)
        with self.assertRaisesMessage(ValidationError, "Stock insuffisant"):
            enregistrer_mouvement(article, self.gerant, "SORTIE", 30, "Personnel")
        with self.assertRaisesMessage(ValidationError, "doit être motivée"):
            enregistrer_mouvement(article, self.gerant, "SORTIE", 10)
        enregistrer_mouvement(article, self.gerant, "SORTIE", 10, "Repas du personnel")
        enregistrer_mouvement(article, self.gerant, "INVENTAIRE", 9)
        article.refresh_from_db()
        self.assertEqual(article.quantite, 9)
        self.assertEqual(article.mouvements.first().quantite, -5)
        self.assertTrue(Alerte.objects.filter(type=Alerte.Type.STOCK).exists())
        self.assertTrue(Alerte.objects.filter(message__contains="Écart d'inventaire : 5 Bière").exists(),
                        "un manquant au comptage est signalé et chiffré")

    def test_cout_moyen_pondere_et_ecarts_d_inventaire_chiffres(self):
        from stock.services import ecarts_inventaire

        article = Article.objects.create(nom="Castel", code="65CL", categorie="BAR", prix_vente=1000)
        enregistrer_mouvement(article, self.gerant, "INVENTAIRE", 0)
        enregistrer_mouvement(article, self.gerant, "ENTREE", 10, "Livraison 1", 500)
        enregistrer_mouvement(article, self.gerant, "ENTREE", 10, "Livraison 2", 700)
        article.refresh_from_db()
        self.assertEqual((article.prix_achat, article.marge), (600, 400), "coût moyen pondéré : (10×500 + 10×700) / 20")
        enregistrer_mouvement(article, self.gerant, "INVENTAIRE", 17, "Comptage du soir")
        d = ecarts_inventaire(aujourd_hui(), aujourd_hui())
        self.assertEqual((d["manque_cout"], d["manque_ventes"]), (1800, 3000), "3 bouteilles manquantes")
        self.client.force_login(self.gerant)
        self.assertContains(self.client.get("/stock/ecarts-inventaire/"), "Comptage du soir")


class PersonnelTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.e_aicha = Employe.objects.create(user=self.aicha, nom="Moussa", prenom="Aïcha", poste="Réceptionniste",
                                              departement=Departement.RECEPTION)
        self.e_serge = Employe.objects.create(user=self.serge, nom="Mbarga", prenom="Serge", poste="Réceptionniste",
                                              departement=Departement.RECEPTION)
        from datetime import time
        self.matin = Creneau.objects.create(nom="Matin", heure_debut=time(7), heure_fin=time(15))
        self.soir = Creneau.objects.create(nom="Après-midi", heure_debut=time(15), heure_fin=time(23))

    def test_pointage_arrivee_depart(self):
        Affectation.objects.create(employe=self.e_aicha, date=aujourd_hui(), creneau=self.matin)
        p = personnel.pointer_arrivee(self.e_aicha, self.aicha)
        with self.assertRaises(ValidationError):
            personnel.pointer_arrivee(self.e_aicha, self.aicha)
        personnel.pointer_depart(self.e_aicha, self.aicha)
        p.refresh_from_db()
        self.assertIsNotNone(p.depart)

    def test_conge_valide_par_le_chef_pas_par_un_collegue(self):
        demande = DemandeConge.objects.create(employe=self.e_aicha, date_debut=aujourd_hui(), date_fin=aujourd_hui())
        with self.assertRaises(ValidationError):
            personnel.traiter_conge(demande, self.serge, True)
        personnel.traiter_conge(demande, self.chef, True)
        self.assertEqual(demande.statut, Statut.ACCEPTEE)

    def test_echange_de_shift_valide_par_le_chef(self):
        a = Affectation.objects.create(employe=self.e_aicha, date=aujourd_hui(), creneau=self.matin)
        b = Affectation.objects.create(employe=self.e_serge, date=aujourd_hui(), creneau=self.soir)
        demande = personnel.demander_echange(self.aicha, a, b, "Rendez-vous médical")
        personnel.traiter_echange(demande, self.chef, True)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.employe, self.e_serge)
        self.assertEqual(b.employe, self.e_aicha)

"""Rapports sur toute période, et stock qui parle (état en mots, mouvements racontés)."""
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from caisse import services as caisse
from core.utils import aujourd_hui
from hotel.models import Extra, Nuitee
from rapports import services as rapports
from stock import recit
from stock.models import Article, MouvementStock
from stock.services import enregistrer_mouvement

from .test_comptoir import BaseComptoir


class RapportsTests(BaseComptoir):
    def test_chiffres_sans_double_comptage(self):
        jour = aujourd_hui()
        s = self.sejour(arrivee=jour, depart=jour + timedelta(days=2))
        Nuitee.objects.create(sejour=s, date_nuit=jour, montant=25000, constatee_le=timezone.now())
        caisse.vendre(self.session, self.aicha, self.savon, 2, "COMPTANT")                 # boutique : 1 000
        caisse.vendre(self.bar, self.jean, self.biere, 3, "COMPTANT")                      # bar : 3 000
        caisse.vendre(self.bar, self.jean, self.plat, 1, "CREDIT", sejour=s)               # extra cuisine : 6 500
        caisse.vendre(self.bar, self.jean, self.biere, 1, "OFFERT", observation="Client fidèle")  # pas une recette
        d = rapports.chiffres(jour, jour)
        self.assertEqual(d["par_service"], {"HEBERGEMENT": 25000, "RESTAURANT_BAR": 3000 + 6500, "BOUTIQUE": 1000})
        self.assertEqual(d["total"], 35500)
        self.assertEqual(d["offres"], 1000)
        self.assertEqual(d["nb_nuitees"], 1)
        self.assertEqual(d["prix_moyen"], 25000)
        self.assertEqual(d["encaisse"], 4000)
        self.assertEqual(Extra.objects.count(), 1)
        self.assertEqual(d["meilleurs"][0]["article__nom"], "Poulet DG")

    def test_periodes_et_comparaison(self):
        self.assertEqual(rapports.periode_precedente(date(2026, 3, 1), date(2026, 3, 31)),
                         (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(rapports.periode_precedente(date(2026, 1, 1), date(2026, 12, 31)),
                         (date(2025, 1, 1), date(2025, 12, 31)))
        self.assertEqual(rapports.periode_precedente(date(2026, 11, 9), date(2026, 11, 15)),
                         (date(2026, 11, 2), date(2026, 11, 8)))
        self.assertEqual(rapports.libelle_periode(date(2026, 11, 1), date(2026, 11, 30)), "Novembre 2026")
        self.assertEqual(rapports.evolution(120, 100), 20)
        self.assertIsNone(rapports.evolution(5, 0))
        self.assertEqual(rapports.graduations(115500)[1], [0, 50000, 100000, 150000])
        self.assertEqual(rapports.compact(2_500_000), "2,5 M")
        annee = rapports.chiffres(date(2026, 1, 1), date(2026, 12, 31))
        self.assertTrue(annee["par_mois"])
        self.assertEqual(len(annee["recettes"]), 12)

    def test_pages_et_droits(self):
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.get(reverse("rapports:rapport")).status_code, 403)
        gouvernante = self.utilisateur("adelaide", Role.GOUVERNANTE)
        self.client.force_login(gouvernante)
        page = self.client.get(reverse("rapports:rapport"), {"periode": "semaine"})
        self.assertContains(page, "Recette jour par jour")
        self.assertNotContains(page, "Dépenses", msg_prefix="les dépenses restent au gérant")
        self.client.force_login(self.gerant)
        for periode, _ in rapports.PERIODES:
            with self.subTest(periode=periode):
                self.assertEqual(self.client.get(reverse("rapports:rapport"), {"periode": periode}).status_code, 200)
        page = self.client.get(reverse("rapports:rapport"), {"du": "2026-10-01", "au": "2026-11-30"})
        self.assertContains(page, "Du 01/10/2026 au 30/11/2026")
        self.assertContains(page, "Dépenses")
        self.assertNotContains(page, "height: 0,0%", msg_prefix="pas de virgule décimale dans le CSS")
        csv = self.client.get(reverse("rapports:rapport"), {"periode": "mois", "format": "csv"})
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Hébergement", csv.content.decode("utf-8-sig"))


class StockQuiParleTests(BaseComptoir):
    def test_chaque_mouvement_raconte(self):
        vente = caisse.vendre(self.bar, self.jean, self.biere, 4, "COMPTANT")
        m = recit.raconter_tous([vente.mouvement])[0]
        self.assertEqual(m.recit["titre"], "Vendu : 4 unités")
        self.assertIn(f"reçu n°{vente.encaissement.numero_recu}", m.recit["detail"])
        self.assertIn("stock 24 → 20", m.recit["detail"])
        casse = enregistrer_mouvement(self.biere, self.gerant, "AVARIE", 1, "bouteille cassée")
        self.assertEqual(recit.raconter(casse)["titre"], "Perdu (casse ou périmé) : 1 unité")
        livraison = enregistrer_mouvement(self.biere, self.gerant, "ENTREE", 12, cout_unitaire=650)
        self.assertIn("7 800 FCFA en tout", recit.raconter(livraison)["detail"])
        compte = enregistrer_mouvement(self.biere, self.gerant, "INVENTAIRE", 29)
        texte = recit.raconter(compte)
        self.assertEqual(texte["titre"], "Inventaire : 2 unités manquent")
        self.assertIn("l'application attendait 31", texte["detail"])

    def test_etat_en_mots(self):
        biere = self.biere
        biere.refresh_from_db()
        biere.seuil_alerte = 5
        self.assertEqual(recit.etat(biere, 2)["titre"], "Bon")
        self.assertEqual(recit.etat(biere, 10)["titre"], "Bientôt épuisé", "24 en stock à 10 par jour : 2 jours")
        self.assertEqual(recit.etat(biere, 0)["titre"], "Ne se vend pas")
        biere.quantite = 4
        self.assertEqual(recit.etat(biere, 1)["titre"], "À commander")
        biere.quantite = 0
        self.assertEqual(recit.etat(biere, 1)["titre"], "Rupture")
        self.assertEqual(recit.etat(self.plat)["titre"], "Sans stock")

    def test_pages_du_stock(self):
        Article.objects.filter(pk=self.whisky.pk).update(seuil_alerte=20)
        caisse.vendre(self.bar, self.jean, self.biere, 4, "COMPTANT")
        self.client.force_login(self.gerant)
        page = self.client.get(reverse("stock:articles"), {"etat": "commander"})
        self.assertContains(page, "BLACK LABEL CONSO")
        self.assertNotContains(page, "33 EXPORT</strong>")
        fiche = self.client.get(reverse("stock:article", args=[self.biere.pk]))
        self.assertContains(fiche, "Vendu : 4 unités")
        self.assertContains(fiche, "Le stock jour après jour")
        mouvements = self.client.get(reverse("stock:mouvements"), {"type": "VENTE"})
        self.assertContains(mouvements, "Vendu : 4 unités")
        self.assertNotContains(mouvements, "Premier comptage")
        csv = self.client.get(reverse("stock:mouvements"), {"format": "csv"})
        self.assertIn("Vendu : 4 unités", csv.content.decode("utf-8-sig"))
        self.assertEqual(MouvementStock.objects.filter(type="VENTE").count(), 1)


class VitesseReelleTests(BaseComptoir):
    def test_vitesse_sur_les_jours_reellement_suivis(self):
        caisse.vendre(self.bar, self.jean, self.biere, 4, "COMPTANT")
        vitesse, _, premiers = recit.vitesses([self.biere])
        self.assertEqual(vitesse[self.biere.pk], 2.0, "4 vendues en 2 jours de suivi (hier, aujourd'hui) : 2 par jour")
        self.biere.refresh_from_db()
        etat = recit.etat(self.biere, vitesse[self.biere.pk], None, premiers[self.biere.pk])
        self.assertIn("environ 10 jours de vente", etat["phrase"])
        self.whisky.refresh_from_db()
        nouveau = recit.etat(self.whisky, 0, None, premiers.get(self.whisky.pk) or aujourd_hui())
        self.assertEqual(nouveau["titre"], "Nouveau")

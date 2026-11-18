"""Fiches au format papier de l'hôtel : recette chambres (réception) et bar / restaurant, sur le même modèle."""
import re
from datetime import timedelta

from django.urls import reverse

from caisse import services as caisse
from caisse.models import Encaissement
from core import modules
from core.utils import aujourd_hui, format_fcfa
from fiches import services as fiches
from hotel import services as hotel
from hotel.models import Chambre, Client, Sejour

from .test_comptoir import BaseComptoir


def nb_pages(pdf):
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


class FicheRecetteChambresTests(BaseComptoir):
    def test_colonnes_bandeau_et_montant_comme_sur_papier(self):
        j = aujourd_hui()
        s = self.sejour(arrivee=j, depart=j + timedelta(days=2))
        caisse.encaisser(self.session, self.aicha, s, Encaissement.Nature.ACOMPTE, Encaissement.Mode.ORANGE_MONEY,
                         30000)
        # Une dette d'un ancien client, réglée ce jour
        ancien = Client.objects.create(nom="M. Fotso", telephone="677000111")
        parti = Sejour.objects.create(client=ancien, chambre=Chambre.objects.create(numero="102", tarif_nuit=20000),
                                      date_arrivee=j - timedelta(days=3), date_depart=j - timedelta(days=1),
                                      tarif_grille=20000, tarif_nuit=20000, statut=Sejour.Statut.TERMINE,
                                      cree_par=self.gerant)
        self.encaisser_especes(self.session, parti, 15000)

        d = fiches.fiche_hebergement(j)
        ligne = next(x for x in d["lignes"] if x["chambre"] == self.chambre)
        self.assertEqual((ligne["recette"], ligne["avance"], ligne["mobile"]), (25000, 5000, 30000))
        self.assertEqual(d["totaux"]["mobile"], 30000)
        self.assertEqual(d["totaux"]["montant"], 45000, "tout l'argent reçu ce jour pour les chambres")
        self.assertEqual(d["entete"]["noms"], ["Aicha (matin)"])
        self.assertEqual((d["entete"]["ouverture"], d["entete"]["fermeture"]), (20000, None))
        self.assertEqual(d["entete"]["total_vente"], 45000)
        self.assertEqual(d["grille"][0]["reglement"]["nom"], "M. Fotso (ch. 102)", "Reg dette : liste ligne après ligne")
        self.assertEqual(d["grille"][0]["dette"]["montant"], 40000 - 15000)

        self.client.force_login(self.aicha)
        page = self.client.get(reverse("fiches:hebergement"))
        for texte in ("Receptioniste", "Montant ouverture", "Montant fermeture", "Total vente", "N° CH", "Recette jr",
                      "Imp jr", "Offre jr", "Comp.", "avance", "Reg dette", "Reste dette", "Obs.", "Mobile",
                      "Heure arrivé", "Heure depart", "TOTAL OM", "MONTANT", "M. Fotso (ch. 102)",
                      format_fcfa(45000)):
            self.assertContains(page, texte)
        pdf = self.client.get(reverse("fiches:hebergement"), {"format": "pdf"})
        self.assertEqual(pdf["Content-Type"], "application/pdf")

    def test_toutes_les_chambres_tiennent_sur_une_feuille_et_fiche_vierge(self):
        for i in range(2, 39):
            Chambre.objects.create(numero=str(100 + i), tarif_nuit=15000)
        self.client.force_login(self.aicha)
        pdf = self.client.get(reverse("fiches:hebergement"), {"format": "pdf"}).content
        self.assertEqual(nb_pages(pdf), 1, "38 chambres : une seule feuille A4, comme la fiche papier")
        vierge = self.client.get(reverse("fiches:hebergement"), {"vierge": "1"})
        self.assertEqual(vierge["Content-Type"], "application/pdf")
        self.assertEqual(nb_pages(vierge.content), 1)

    def test_heures_d_arrivee_et_de_depart(self):
        j = aujourd_hui()
        s = self.sejour(arrivee=j - timedelta(days=1), depart=j, statut=Sejour.Statut.EN_COURS)
        hotel.check_out(s, self.aicha)
        Chambre.objects.filter(pk=self.chambre.pk).update(statut=Chambre.Statut.LIBRE)  # le ménage est passé
        self.chambre.refresh_from_db()
        nouveau =self.sejour(arrivee=j, depart=j + timedelta(days=1), statut=Sejour.Statut.RESERVE)
        hotel.check_in(nouveau, self.aicha)
        ligne = next(x for x in fiches.fiche_hebergement(j)["lignes"] if x["chambre"] == self.chambre)
        self.assertRegex(ligne["heure_arrivee"], r"^\d\d:\d\d$")
        self.assertRegex(ligne["heure_depart"], r"^\d\d:\d\d$")


class FicheBarRestaurantTests(BaseComptoir):
    def vendre_la_journee(self):
        s = self.sejour()
        caisse.vendre(self.bar, self.jean, self.biere, 3, "COMPTANT")
        caisse.vendre(self.bar, self.jean, self.biere, 2, "COMPTANT", mode=Encaissement.Mode.ORANGE_MONEY)
        caisse.vendre(self.bar, self.jean, self.plat, 1, "CREDIT", sejour=s)
        caisse.vendre(self.bar, self.jean, self.whisky, 1, "OFFERT", observation="Anniversaire")
        return s

    def test_les_ventes_article_par_article(self):
        self.vendre_la_journee()
        d = fiches.fiche_bar_restaurant(aujourd_hui())
        self.assertEqual([g["titre"] for g in d["groupes"]], ["BOISSONS (BAR)", "PLATS (CUISINE)"])
        biere = d["groupes"][0]["lignes"][0]
        self.assertEqual((biere["quantite"], biere["cash"], biere["mobile"]), (5, 5000, 2000))
        plat = d["groupes"][1]["lignes"][0]
        self.assertEqual((plat["credit"], plat["noms"]), (6500, ["ch. 101"]))
        t = d["totaux"]
        self.assertEqual((t["cash"], t["mobile"], t["credit"], t["offre"], t["total"]), (5000, 2000, 6500, 4000, 15500))
        self.assertEqual((t["montant"], t["especes"], d["entete"]["total_vente"]), (5000, 3000, 11500))
        self.assertEqual(d["entete"]["noms"], ["Jean (matin)"])

        self.client.force_login(self.jean)
        page = self.client.get(reverse("fiches:bar_restaurant"))
        for texte in ("Caissier(e)", "Montant ouverture", "Montant fermeture", "Total vente", "Désignation", "Qté V",
                      "Cash", "Crédit", "Offre", "Mobile", "TOTAL OM", "MONTANT", "33 EXPORT", "Poulet DG",
                      "ch. 101", "offert : Anniversaire"):
            self.assertContains(page, texte)
        pdf = self.client.get(reverse("fiches:bar_restaurant"), {"format": "pdf"})
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        vierge = self.client.get(reverse("fiches:bar_restaurant"), {"vierge": "1"})
        self.assertEqual(nb_pages(vierge.content), 1)

    def test_chacun_sa_fiche_et_la_direction_voit_tout(self):
        self.vendre_la_journee()
        self.client.force_login(self.mireille)
        page = self.client.get(reverse("fiches:bar_restaurant"))
        self.assertContains(page, "Aucune vente ce jour", msg_prefix="Mireille ne voit pas les ventes de Jean")
        self.client.force_login(self.gerant)
        self.assertContains(self.client.get(reverse("fiches:bar_restaurant")), "33 EXPORT")
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.get(reverse("fiches:bar_restaurant")).status_code, 403,
                         "la réception n'a pas la fiche du bar")

    def test_ouverte_meme_quand_le_module_ventes_est_ferme(self):
        """Les plats commandés en ligne passent par la caisse Cuisine / Bar : la fiche reste là."""
        modules.ouvrir([])
        self.client.force_login(self.jean)
        accueil = self.client.get(reverse("vitrine:commandes_plats"))
        self.assertContains(accueil, reverse("fiches:bar_restaurant"))
        self.assertEqual(self.client.get(reverse("fiches:bar_restaurant")).status_code, 200)

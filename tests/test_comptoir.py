"""Ventes bar / restaurant / boutique, crédits clients et fiches journalières (formats des fiches papier)."""
from datetime import datetime, timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from caisse import services as caisse
from caisse.models import Encaissement, FondCaisse, SessionCaisse, Tiroir, VenteComptoir
from core.utils import aujourd_hui, format_fcfa
from fiches import services as fiches
from hotel.models import Chambre, Client, Extra, Sejour
from stock.models import Article
from stock.services import enregistrer_mouvement

from .base import BaseTest


class BaseComptoir(BaseTest):
    """Réception (Aïcha, Serge) : chambres et boutique. Bar / restaurant (Jean, Mireille) : boissons et plats."""

    def setUp(self):
        super().setUp()
        self.jean = self.utilisateur("jean", Role.BAR_RESTAURANT)
        self.mireille = self.utilisateur("mireille", Role.BAR_RESTAURANT)
        self.tiroir_bar = Tiroir.objects.create(nom="Bar", poste=Tiroir.Poste.BAR)
        FondCaisse.objects.create(tiroir=self.tiroir_bar, montant=10000, date_effet=aujourd_hui() - timedelta(days=10))
        self.biere = Article.objects.create(nom="33 EXPORT", code="65CL", categorie="BAR", prix_vente=1000, ordre=10)
        self.whisky = Article.objects.create(nom="BLACK LABEL CONSO", code="75CL", categorie="BAR", prix_vente=4000,
                                             ordre=20)
        self.plat = Article.objects.create(nom="Poulet DG", categorie="RESTAURANT", prix_vente=6500, suivi_stock=False)
        self.savon = Article.objects.create(nom="Brosse à dent", categorie="BOUTIQUE", prix_vente=500)
        hier = aujourd_hui() - timedelta(days=1)
        for article, quantite in [(self.biere, 24), (self.whisky, 10), (self.savon, 10)]:
            enregistrer_mouvement(article, self.gerant, "INVENTAIRE", quantite, journee=hier)
        self.session = self.ouvrir()  # Aïcha, caisse Réception
        self.bar = caisse.ouvrir_session(self.jean, self.tiroir_bar, "MATIN", 10000)

    def refresh(self, *objets):
        for o in objets:
            o.refresh_from_db()


class PostesTests(BaseComptoir):
    def test_chacun_vend_ce_qui_releve_de_son_poste(self):
        with self.assertRaisesMessage(ValidationError, "ne se vend pas à la caisse"):
            caisse.vendre(self.session, self.aicha, self.biere, 1, "COMPTANT")
        with self.assertRaisesMessage(ValidationError, "ne se vend pas à la caisse"):
            caisse.vendre(self.bar, self.jean, self.savon, 1, "COMPTANT")
        caisse.vendre(self.session, self.aicha, self.savon, 1, "COMPTANT")
        caisse.vendre(self.bar, self.jean, self.biere, 1, "COMPTANT")

    def test_le_barman_n_ouvre_que_la_caisse_du_bar(self):
        caisse.vendre(self.bar, self.jean, self.biere, 1, "COMPTANT")
        self.remettre(self.bar, 11000)
        with self.assertRaisesMessage(ValidationError, "n'est pas celle de votre poste"):
            caisse.ouvrir_session(self.mireille, self.tiroir, "APRES_MIDI", 20000)
        self.assertEqual(list(Tiroir.accessibles_a(self.mireille)), [self.tiroir_bar])
        self.assertEqual(list(Tiroir.accessibles_a(self.aicha)), [self.tiroir])
        caisse.ouvrir_session(self.mireille, self.tiroir_bar, "APRES_MIDI", 10000)


class CuisineBarTests(BaseComptoir):
    """Cuisine / bar : une équipe, une caisse. Payé tout de suite à la caisse ; à crédit, extra sur la chambre."""

    def test_boissons_et_plats_sur_la_meme_caisse(self):
        self.client.force_login(self.jean)
        page = self.client.get(reverse("caisse:ventes"))
        for texte in ("Restaurant · Bar", "Poulet DG", "33 EXPORT"):
            self.assertContains(page, texte)
        reponse = self.client.post(reverse("caisse:ventes"), {f"q_{self.plat.pk}": 2, "paiement": "ESPECES"})
        self.assertRedirects(reponse, reverse("caisse:ventes"))
        vente = VenteComptoir.objects.get(article=self.plat)
        self.assertEqual((vente.montant, vente.encaissement.montant, vente.mouvement_id), (13000, 13000, None))
        self.assertEqual(self.bar.especes_attendues, 10000 + 13000)
        self.assertEqual(fiches.main_courante(aujourd_hui(), "RESTAURANT")["totaux"]["cash"], 13000)
        url = reverse("fiches:main_courante", args=["cuisine"])
        self.assertContains(self.client.get(url), "Poulet DG")
        self.assertEqual(self.client.get(url + "?format=pdf")["Content-Type"], "application/pdf")
        self.assertEqual(self.client.get(reverse("fiches:stock", args=["cuisine"])).status_code, 404)

    def test_plat_a_credit_va_sur_la_chambre_et_se_paie_a_la_reception(self):
        s = self.sejour()
        self.client.force_login(self.jean)
        self.client.post(reverse("caisse:ventes"), {f"q_{self.plat.pk}": 2, "paiement": "CHAMBRE", "sejour": s.pk})
        extra = Extra.objects.get()
        self.assertEqual((extra.description, extra.montant, extra.source), ("2 × Poulet DG", 13000, "RESTAURANT"))
        self.assertEqual(self.bar.especes_attendues, 10000, "rien n'entre dans la caisse cuisine / bar")
        ligne = next(x for x in fiches.fiche_hebergement(aujourd_hui())["lignes"] if x["chambre"] == self.chambre)
        self.assertEqual(ligne["extras"], 13000, "l'extra figure sur la fiche du réceptionniste")
        self.assertEqual(s.reste_a_payer, s.montant_chambre_prevu + 13000, "il se paie à la réception avec la chambre")

    def test_la_reception_ne_vend_pas_de_plats(self):
        with self.assertRaisesMessage(ValidationError, "caisse Cuisine / Bar"):
            caisse.vendre(self.session, self.aicha, self.plat, 1, "COMPTANT")
        self.client.force_login(self.aicha)
        self.assertNotContains(self.client.get(reverse("caisse:ventes")), "Poulet DG")

    def test_un_plat_cree_dans_le_stock_n_a_pas_de_stock(self):
        plat = Article.objects.create(nom="Riz sauté", categorie="RESTAURANT", prix_vente=2500)
        self.assertFalse(plat.suivi_stock)

    def test_orange_money_et_mtn_momo_sont_de_simples_moyens_de_paiement(self):
        from caisse.forms import choix_moyens

        self.assertEqual(choix_moyens(), [("ESPECES", "Espèces"), ("ORANGE_MONEY", "Orange Money"),
                                          ("MTN_MOMO", "MTN MoMo")])
        self.assertEqual(choix_moyens(carte_cheque=True)[3:], [("CARTE", "Carte bancaire"), ("CHEQUE", "Chèque")])


class ExtrasReceptionTests(BaseComptoir):
    def test_la_reception_porte_un_plat_sur_la_chambre(self):
        s = self.sejour()
        self.client.force_login(self.aicha)
        self.assertContains(self.client.get(reverse("hotel:extras")), f"?sejour={s.pk}")
        reponse = self.client.post(reverse("hotel:extras"), {"sejour": s.pk, "plat": self.plat.pk, "quantite": 2})
        self.assertRedirects(reponse, reverse("hotel:extras"))
        extra = Extra.objects.get()
        self.assertEqual((extra.description, extra.montant, extra.source), ("2 × Poulet DG", 13000, "RESTAURANT"))
        self.client.post(reverse("hotel:extras"), {"sejour": s.pk, "quantite": 1, "description": "Jus d'orange",
                                                   "montant": 1500})
        self.assertEqual(s.total_extras, 14500)
        self.assertContains(self.client.post(reverse("hotel:extras"), {"sejour": s.pk, "quantite": 1}),
                            "Choisissez un plat")

        d = fiches.fiche_hebergement(aujourd_hui())
        ligne = next(x for x in d["lignes"] if x["chambre"] == self.chambre)
        self.assertEqual(ligne["extras"], 14500, "l'extra figure sur la fiche du réceptionniste")
        self.assertEqual((len(d["extras_du_jour"]), d["totaux"]["extras"]), (2, 14500))
        self.assertEqual(s.reste_a_payer, s.montant_chambre_prevu + 14500, "il se paie à la réception avec la chambre")

        page = self.client.get(reverse("fiches:hebergement"))
        self.assertContains(page, f"extras {format_fcfa(14500, unite=False)}", msg_prefix="les extras dans « Obs. »")
        self.assertContains(page, "2 × Poulet DG")


class VenteTests(BaseComptoir):
    def test_vente_cash_sort_du_stock_et_entre_dans_la_caisse(self):
        vente = caisse.vendre(self.bar, self.jean, self.biere, 3, "COMPTANT")
        self.refresh(self.biere)
        self.assertEqual(self.biere.quantite, 21)
        self.assertEqual(vente.montant, 3000)
        self.assertEqual(vente.encaissement.nature, Encaissement.Nature.VENTE)
        self.assertEqual(self.bar.especes_attendues, 13000)
        self.assertEqual(vente.journee, aujourd_hui())

    def test_orange_money_et_mtn_momo_separes(self):
        with self.assertRaisesMessage(ValidationError, "espèces, Orange Money ou MTN MoMo"):
            caisse.vendre(self.bar, self.jean, self.biere, 1, "COMPTANT", mode="CHEQUE")
        caisse.vendre(self.bar, self.jean, self.biere, 1, "COMPTANT", mode="ORANGE_MONEY")
        caisse.vendre(self.bar, self.jean, self.whisky, 1, "COMPTANT", mode="MTN_MOMO")
        caisse.vendre(self.bar, self.jean, self.biere, 2, "COMPTANT")
        self.assertEqual(self.bar.especes_attendues, 12000)
        moyens = {m["libelle"]: m["montant"] for m in self.bar.totaux_par_moyen()}
        self.assertEqual((moyens["Espèces"], moyens["Orange Money"], moyens["MTN MoMo"]), (2000, 1000, 4000))
        t = fiches.fiche_stock(aujourd_hui(), "BAR")["totaux"]
        self.assertEqual((t["comptant"], t["especes"], t["mobile_money"]), (7000, 2000, 5000))
        self.assertEqual({m["libelle"]: m["montant"] for m in t["moyens"]},
                         {"Espèces": 2000, "Orange Money": 1000, "MTN MoMo": 4000})

    def test_credit_sur_chambre_va_sur_la_note(self):
        s = self.sejour()
        with self.assertRaisesMessage(ValidationError, "chambre occupée ou au nom d'un client"):
            caisse.vendre(self.bar, self.jean, self.whisky, 2, "CREDIT")
        caisse.vendre(self.bar, self.jean, self.whisky, 2, "CREDIT", sejour=s)
        self.assertEqual(s.total_extras, 8000)
        self.assertEqual(Extra.objects.get().source, Extra.Source.BAR)
        self.assertEqual(self.bar.especes_attendues, 10000, "un crédit n'entre pas dans le tiroir")

    def test_credit_client_dette_puis_reglement(self):
        client = Client.objects.create(nom="M. Essomba", telephone="699")
        caisse.vendre(self.bar, self.jean, self.biere, 5, "CREDIT", client=client)
        self.assertEqual(caisse.dette_client(client), 5000)
        self.assertEqual(caisse.clients_debiteurs(), [(client, 5000)])
        with self.assertRaisesMessage(ValidationError, "ne doit que"):
            caisse.regler_credit(self.session, self.aicha, client, 6000, "ESPECES")
        caisse.regler_credit(self.session, self.aicha, client, 3000, "ESPECES")
        self.assertEqual(caisse.dette_client(client), 2000)
        self.assertEqual(self.session.especes_attendues, 23000)

    def test_offre_motivee_sort_du_stock_sans_entrer_en_caisse(self):
        with self.assertRaisesMessage(ValidationError, "doit être motivée"):
            caisse.vendre(self.bar, self.jean, self.biere, 1, "OFFERT")
        caisse.vendre(self.bar, self.jean, self.biere, 1, "OFFERT", observation="Client fidèle, ch. 101")
        self.refresh(self.biere)
        self.assertEqual(self.biere.quantite, 23)
        self.assertEqual(self.bar.total_encaisse, 0)

    def test_stock_insuffisant_et_article_sans_prix_refuses(self):
        with self.assertRaisesMessage(ValidationError, "Stock insuffisant"):
            caisse.vendre(self.bar, self.jean, self.whisky, 11, "COMPTANT")
        sans_prix = Article.objects.create(nom="Nouveau", categorie="BAR", prix_vente=0)
        with self.assertRaisesMessage(ValidationError, "prix de vente n'est pas renseigné"):
            caisse.vendre(self.bar, self.jean, sans_prix, 1, "COMPTANT")

    def test_annulation_retablit_stock_caisse_et_note(self):
        s = self.sejour()
        cash = caisse.vendre(self.bar, self.jean, self.biere, 2, "COMPTANT")
        credit = caisse.vendre(self.bar, self.jean, self.whisky, 1, "CREDIT", sejour=s)
        with self.assertRaisesMessage(ValidationError, "depuis la main courante"):
            caisse.annuler_encaissement(cash.encaissement, self.jean, "x")
        caisse.annuler_vente(cash, self.jean, "Erreur d'article")
        caisse.annuler_vente(credit, self.jean, "Client a refusé")
        self.refresh(self.biere, self.whisky)
        self.assertEqual((self.biere.quantite, self.whisky.quantite), (24, 10))
        self.assertEqual(self.bar.especes_attendues, 10000)
        self.assertEqual(s.total_extras, 0)
        with self.assertRaises(ValidationError):
            caisse.annuler_vente(cash, self.jean, "deux fois")


class FichesTests(BaseComptoir):
    def test_fiche_stock_bar_colonnes_du_papier(self):
        jour = aujourd_hui()
        enregistrer_mouvement(self.biere, self.gerant, "ENTREE", 12, "Livraison", journee=jour)
        enregistrer_mouvement(self.biere, self.jean, "AVARIE", 1, "Bouteille cassée", journee=jour)
        caisse.vendre(self.bar, self.jean, self.biere, 4, "COMPTANT")
        caisse.vendre(self.bar, self.jean, self.biere, 2, "CREDIT", client=Client.objects.create(nom="X", telephone="1"))
        caisse.vendre(self.bar, self.jean, self.biere, 1, "OFFERT", observation="Geste")
        self.remettre(self.bar, 14000)
        soir = caisse.ouvrir_session(self.mireille, self.tiroir_bar, "APRES_MIDI", 10000)
        caisse.vendre(soir, self.mireille, self.biere, 3, "COMPTANT")

        d = fiches.fiche_stock(jour, "BAR")
        ligne = next(x for x in d["lignes"] if x["article"] == self.biere)
        self.assertEqual((ligne["si"], ligne["appro"], ligne["avaries"], ligne["st"]), (24, 12, 1, 35))
        self.assertEqual((ligne["releves"][0], ligne["releves"][1], ligne["quantite"]), (7, 3, 10))
        self.assertEqual([c["nom"] for c in d["colonnes"][:2]], [str(self.jean), str(self.mireille)],
                         "sur la fiche bar, seules les personnes du bar comptent")
        self.assertEqual(ligne["sf"], 25)
        self.assertEqual(ligne["montant"], 10000)
        t = d["totaux"]
        self.assertEqual((t["montant"], t["credit"], t["offre"], t["comptant"]), (10000, 2000, 1000, 7000))

    def test_r1_r2_r3_sont_les_receptionnistes_dans_l_ordre_de_prise_de_service(self):
        caisse.vendre(self.session, self.aicha, self.savon, 2, "COMPTANT")
        self.remettre(self.session, 21000)
        nuit = caisse.ouvrir_session(self.serge, self.tiroir, "NUIT", 20000)
        caisse.vendre(nuit, self.serge, self.savon, 1, "COMPTANT")
        self.remettre(nuit, 20500)
        retour = self.ouvrir(self.aicha)
        caisse.vendre(retour, self.aicha, self.savon, 3, "COMPTANT")

        d = fiches.fiche_stock(aujourd_hui(), "BOUTIQUE")
        self.assertEqual([(c["code"], c["nom"]) for c in d["colonnes"]],
                         [("R1", str(self.aicha)), ("R2", str(self.serge)), ("R3", "-")],
                         "le barman, qui a aussi ouvert sa caisse ce jour, n'apparaît pas sur la fiche boutique")
        ligne = next(x for x in d["lignes"] if x["article"] == self.savon)
        self.assertEqual(ligne["releves"], [5, 1, 0], "Aïcha garde sa colonne R1 quand elle rouvre sa caisse")
        self.assertEqual(d["totaux"]["releves"], [5, 1, 0])

    def test_main_courante_par_personne(self):
        caisse.vendre(self.bar, self.jean, self.biere, 2, "COMPTANT")
        caisse.vendre(self.bar, self.jean, self.biere, 1, "OFFERT", observation="Patron")
        d = fiches.main_courante(aujourd_hui(), "BAR", [self.bar])
        ligne = d["lignes"][0]
        self.assertEqual((ligne["quantite"], ligne["cash"], ligne["offre"], ligne["total"]), (3, 2000, 1000, 3000))
        self.assertEqual(fiches.main_courante(aujourd_hui(), "BAR", [])["lignes"], [])

    def test_fiche_recette_chambres(self):
        j = aujourd_hui()
        hier = j - timedelta(days=1)
        ch2 = Chambre.objects.create(numero="102/103", tarif_nuit=30000)
        ch3 = Chambre.objects.create(numero="104", tarif_nuit=20000)
        ch4 = Chambre.objects.create(numero="105", tarif_nuit=20000)
        a = self.sejour(arrivee=hier, depart=j + timedelta(days=2))
        b = self.sejour(arrivee=hier, depart=j + timedelta(days=2), chambre=ch2)
        offert = self.sejour(arrivee=j, depart=j + timedelta(days=1), chambre=ch3, tarif=0)
        Sejour.objects.filter(pk=offert.pk).update(gratuite="OFFERT", tarif_grille=20000, tarif_nuit=0)
        parti = self.sejour(arrivee=j - timedelta(days=3), depart=j, chambre=ch4, statut=Sejour.Statut.TERMINE)

        # Session d'hier : A paie deux nuits d'avance, B ne paie rien.
        session_hier = SessionCaisse.objects.create(receptionniste=self.serge, tiroir=self.tiroir, shift="MATIN",
                                                    statut=SessionCaisse.Statut.VALIDEE)
        SessionCaisse.objects.filter(pk=session_hier.pk).update(
            ouverte_le=timezone.make_aware(datetime.combine(hier, datetime.min.time())) + timedelta(hours=10))
        Encaissement.objects.create(session=session_hier, sejour=a, nature="ACOMPTE", mode="ESPECES", montant=50000,
                                    montant_signe=50000, numero_recu=900, utilisateur=self.serge)
        # Aujourd'hui : B paie 40 000 = 30 000 de dette de la veille + 10 000 sur la nuit du jour.
        self.encaisser_especes(self.session, b, 40000)

        veille = fiches.fiche_hebergement(hier)
        lv = {x["chambre"].numero: x for x in veille["lignes"]}
        self.assertEqual((lv["101"]["recette"], lv["101"]["avance"]), (25000, 25000))
        self.assertEqual(lv["102/103"]["impaye"], 30000)

        jour = fiches.fiche_hebergement(j)
        lj = {x["chambre"].numero: x for x in jour["lignes"]}
        self.assertEqual((lj["101"]["recette"], lj["101"]["avance"]), (25000, 0))
        self.assertEqual((lj["102/103"]["recette"], lj["102/103"]["impaye"]), (10000, 20000))
        self.assertEqual((lj["104"]["offre"], lj["104"]["recette"]), (20000, 0))
        self.assertEqual(jour["reglements"], [{"nom": f"{b.client} (ch. 102/103)", "montant": 30000, "mobile": 0}])
        self.assertIn({"nom": f"{parti.client} (ch. 105)", "montant": 60000}, jour["dettes"])


class SejourOffertTests(BaseTest):
    def test_sejour_offert_exige_motif_et_validation_et_chambre_sans_tarif_refusee(self):
        self.client.force_login(self.aicha)
        j = aujourd_hui() + timedelta(days=3)
        donnees = {"nouveau_client_nom": "Invité", "nouveau_client_telephone": "6", "chambre": self.chambre.pk,
                   "date_arrivee": j, "date_depart": j + timedelta(days=1), "nb_personnes": 1, "gratuite": "OFFERT"}
        reponse = self.client.post(reverse("hotel:sejour_nouveau"), donnees)
        self.assertContains(reponse, "doit être motivé")
        self.assertContains(reponse, "Séjour gratuit")
        donnees.update({"motif_tarif": "Partenaire", "valideur": self.chef.pk, "valideur_pin": "1234"})
        self.assertEqual(self.client.post(reverse("hotel:sejour_nouveau"), donnees).status_code, 302)
        sejour = Sejour.objects.get()
        self.assertEqual((sejour.tarif_nuit, sejour.gratuite), (0, "OFFERT"))

        sans_tarif = Chambre.objects.create(numero="201", tarif_nuit=0)
        donnees.update({"chambre": sans_tarif.pk, "gratuite": ""})
        self.assertContains(self.client.post(reverse("hotel:sejour_nouveau"), donnees), "pas encore renseigné")


class ChargementEtPagesTests(BaseComptoir):
    def test_chargement_des_fiches_idempotent_sans_ecraser_les_prix(self):
        call_command("charger_saint_elie", stdout=StringIO())
        from core.models import Etablissement

        etab = Etablissement.get()
        self.assertEqual((etab.nom, etab.monogramme), ("Complexe St Élie Palace", "S"), "le nom de l'en-tête du menu")
        self.assertEqual(Chambre.objects.filter(numero__in=["101", "102/103", "312"]).count(), 3)
        for numero in ("102/103", "106/107", "109/110"):
            suite = Chambre.objects.get(numero=numero)
            self.assertEqual((suite.categorie, suite.tarif_nuit), ("SUITE", 40000), f"{numero} : suite à 40 000 F")
        tarifs = dict(Chambre.objects.values_list("numero", "tarif_nuit"))
        self.assertEqual([tarifs[n] for n in ("104", "115", "203", "206", "302", "307", "311")],
                         [12000, 10000, 15000, 20000, 55000, 25000, 35000])
        self.assertFalse(Chambre.objects.filter(tarif_nuit=0).exists(), "toutes les chambres ont un prix")
        self.assertEqual(tarifs["101"], 25000, "un prix déjà saisi n'est pas écrasé sans --tarifs")
        call_command("charger_saint_elie", "--tarifs", stdout=StringIO())
        self.assertEqual(Chambre.objects.get(numero="101").tarif_nuit, 15000, "la grille de la direction s'applique")
        self.assertEqual(Article.objects.filter(nom="COOKS").count(), 3)
        plats = Article.objects.filter(categorie="RESTAURANT")
        self.assertEqual(plats.count(), 36, "la carte du menu : 20 plats chauds, 5 garnitures, 1 dessert, 6 + 4")
        self.assertEqual([plats.get(nom=n).prix_vente for n in ("Poulet rôti", "Bouillon de poisson bar", "Riz", "Thé")],
                         [3000, 4000, 500, 500])
        self.assertEqual(plats.get(nom="Poulet DG").prix_vente, 6500, "un prix déjà saisi dans l'application est gardé")
        self.assertFalse(plats.filter(suivi_stock=True).exists(), "un plat n'a pas de stock")
        self.assertEqual(plats.get(nom="Petit-déjeuner complet").rubrique, "Petit-déjeuner")
        page = self.client.get("/")
        for texte in ("Notre carte", "Plats chauds", "Garnitures", "Poulet aux arachides", "Ananas, papaye, pastèque"):
            self.assertContains(page, texte)
        Article.objects.filter(nom="CHIVAS", code="75CL").update(prix_vente=36000)
        call_command("charger_saint_elie", stdout=StringIO())
        self.assertEqual(Article.objects.get(nom="CHIVAS", code="75CL").prix_vente, 36000)
        self.assertEqual(Chambre.objects.filter(numero="101").count(), 1)

    def test_pages_du_barman(self):
        self.client.force_login(self.jean)
        page = self.client.get(reverse("caisse:ventes"))
        self.assertContains(page, "Orange Money")
        self.assertContains(page, "MTN MoMo")
        self.assertNotContains(page, "Brosse à dent", msg_prefix="la boutique ne se vend pas au bar")
        reponse = self.client.post(reverse("caisse:ventes"), {f"q_{self.biere.pk}": 2, "paiement": "ORANGE_MONEY"})
        self.assertRedirects(reponse, reverse("caisse:ventes"))
        self.assertEqual(Encaissement.objects.get(nature="VENTE").mode, "ORANGE_MONEY")
        for url in [reverse("caisse:ma_caisse"), reverse("hotel:extras"), reverse("caisse:credits"),
                    reverse("fiches:index"), reverse("fiches:stock", args=["bar"])]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        for url in [reverse("hotel:sejours"), reverse("hotel:menage"), reverse("fiches:stock", args=["boutique"]),
                    reverse("fiches:hebergement"), reverse("stock:articles")]:
            with self.subTest(interdit=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_pages_du_receptionniste_et_fiches_pdf(self):
        self.client.force_login(self.aicha)
        reponse = self.client.post(reverse("caisse:ventes"), {f"q_{self.savon.pk}": 2, "paiement": "ESPECES"})
        self.assertRedirects(reponse, reverse("caisse:ventes"))
        self.assertNotContains(self.client.get(reverse("caisse:ventes")), "33 EXPORT")
        pages = [reverse("caisse:credits"), reverse("caisse:avarie"), reverse("fiches:index"),
                 reverse("fiches:stock", args=["boutique"]), reverse("fiches:main_courante", args=["boutique"]),
                 reverse("fiches:hebergement"), reverse("caisse:ma_caisse")]
        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        for url in pages[3:6]:
            with self.subTest(pdf=url):
                self.assertEqual(self.client.get(url + "?format=pdf")["Content-Type"], "application/pdf")
        self.assertEqual(self.client.get(reverse("fiches:stock", args=["bar"])).status_code, 403)
        enc = Encaissement.objects.filter(nature="VENTE").first()
        self.assertEqual(self.client.get(reverse("caisse:recu_client", args=[enc.pk])).status_code, 200)
        s = self.sejour()
        reponse = self.client.post(reverse("hotel:encaisser", args=[s.pk]), {
            "nature": "REGLEMENT", "montant": 10000, "moyen": "ORANGE_MONEY"})
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Encaissement.objects.get(sejour=s).moyen_libelle, "Orange Money")

        self.client.force_login(self.gerant)
        self.assertEqual(self.client.get(reverse("stock:saisie_groupee")).status_code, 200)
        reponse = self.client.post(reverse("stock:saisie_groupee"), {
            "categorie": "BAR", "type": "ENTREE", "journee": aujourd_hui().isoformat(), f"q_{self.biere.pk}": "12"})
        self.assertEqual(reponse.status_code, 302)
        self.biere.refresh_from_db()
        self.assertEqual(self.biere.quantite, 36)

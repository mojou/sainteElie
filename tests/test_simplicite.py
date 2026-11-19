"""Phase 1 « opérateurs peu à l'aise » : montants en lettres, mots expliqués, écran verrouillé, fiches papier."""
import re
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from accounts.models import Role, User
from accounts.verrouillage import CLE_ACTIVITE, CLE_VERROU
from core.aides import GLOSSAIRE
from core.models import JournalAction
from core.utils import aujourd_hui, en_lettres, montant_en_lettres
from hotel.models import Chambre, Sejour
from personnel.models import Departement, Employe

from .base import BaseTest


class MontantsEnLettresTests(BaseTest):
    def test_regles_du_francais(self):
        attendus = {
            0: "zéro", 21: "vingt et un", 71: "soixante et onze", 80: "quatre-vingts", 81: "quatre-vingt-un",
            91: "quatre-vingt-onze", 200: "deux cents", 201: "deux cent un", 1000: "mille",
            3500: "trois mille cinq cents", 80000: "quatre-vingt mille", 200000: "deux cent mille",
            250000: "deux cent cinquante mille", 1000000: "un million", 200000000: "deux cents millions",
            1250500: "un million deux cent cinquante mille cinq cents",
        }
        for nombre, texte in attendus.items():
            self.assertEqual(en_lettres(nombre), texte, nombre)

    def test_phrase_du_recu(self):
        self.assertEqual(montant_en_lettres(25000), "Vingt-cinq mille francs CFA")
        self.assertEqual(montant_en_lettres(1), "Un franc CFA")

    def test_le_recu_porte_le_montant_en_lettres(self):
        session = self.ouvrir()
        enc = self.encaisser_especes(session, self.sejour(), 25000)
        self.client.force_login(self.aicha)
        self.assertContains(self.client.get(reverse("caisse:recu_client", args=[enc.pk])),
                            "Vingt-cinq mille francs CFA")

    def test_les_champs_d_argent_sont_marques(self):
        """Montant écrit en lettres dessous ; l'argent reçu est relu au-delà du seuil (app.js)."""
        from caisse.forms import ComptageForm, SortieForm
        from postes.forms import ArriveeForm

        arrivee = ArriveeForm()
        self.assertIn("data-confirmer-montant", arrivee.fields["montant"].widget.attrs)
        self.assertNotIn("data-montant", arrivee.fields["nuits"].widget.attrs, "un nombre de nuits n'est pas de l'argent")
        self.assertIn("data-confirmer-montant", ComptageForm().fields["especes"].widget.attrs)
        self.assertIn("data-montant", SortieForm().fields["montant"].widget.attrs)

    def test_la_reception_fait_relire_un_montant_plus_grand_que_le_du(self):
        self.sejour()
        self.ouvrir()
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("postes:chambre", args=[self.chambre.pk])).content.decode()
        self.assertIn('data-montant-max="', page)
        self.assertIn(f'data-montant-eleve="{settings.MONTANT_A_CONFIRMER}"', page)


class AidesTests(BaseTest):
    def test_chaque_aide_des_ecrans_existe_dans_le_glossaire(self):
        cles = set()
        for gabarit in Path(settings.BASE_DIR, "templates").rglob("*.html"):
            cles |= set(re.findall(r'{%\s*aide\s+"([a-z_]+)"', gabarit.read_text(encoding="utf-8")))
        self.assertTrue(cles, "des écrans utilisent les « ? »")
        self.assertFalse(cles - set(GLOSSAIRE), "mot sans explication")

    def test_le_point_d_interrogation_explique_le_mot(self):
        self.ouvrir()
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("caisse:ma_caisse")).content.decode()
        self.assertIn('class="aide-bouton"', page)
        self.assertIn("la personne qui prend la suite", page)

    def test_mots_simples_sur_les_ecrans_de_caisse(self):
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("caisse:ma_caisse")).content.decode()
        self.assertIn("Ouvrir ma caisse", page)
        self.assertNotIn("session de caisse", page)
        self.assertNotIn("shift précédent", page)
        self.assertNotIn(">Shift", page)


@override_settings(VERROUILLAGE_MINUTES=10)
class VerrouillageTests(BaseTest):
    def endormir(self, minutes=11):
        """Simule une absence : la dernière activité date d'il y a `minutes`."""
        session = self.client.session
        session[CLE_ACTIVITE] = int(time.time()) - minutes * 60
        session.save()

    def test_apres_10_minutes_sans_activite_l_ecran_se_verrouille(self):
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.get(reverse("postes:reception")).status_code, 200)
        self.endormir()
        reponse = self.client.get(reverse("postes:reception"))
        self.assertRedirects(reponse, reverse("accounts:verrouille") + "?suite=%2Fposte%2Freception%2F",
                             fetch_redirect_response=False)
        self.assertTrue(self.client.session[CLE_VERROU])

    def test_moins_de_10_minutes_ne_verrouille_pas(self):
        self.client.force_login(self.aicha)
        self.client.get(reverse("postes:reception"))
        self.endormir(minutes=8)
        self.assertEqual(self.client.get(reverse("postes:reception")).status_code, 200)

    def test_reprendre_avec_son_code_pin(self):
        self.client.force_login(self.aicha)
        self.client.get(reverse("postes:reception"))
        self.endormir()
        self.client.get(reverse("postes:reception"))
        faux = self.client.post(reverse("accounts:verrouille"), {"secret": "9999", "suite": "/poste/reception/"})
        self.assertContains(faux, "incorrect")
        self.assertTrue(self.client.session[CLE_VERROU], "toujours verrouillé")
        bon = self.client.post(reverse("accounts:verrouille"), {"secret": "1234", "suite": "/poste/reception/"})
        self.assertRedirects(bon, "/poste/reception/", fetch_redirect_response=False)
        self.assertNotIn(CLE_VERROU, self.client.session)
        self.assertEqual(self.client.get(reverse("postes:reception")).status_code, 200)

    def test_la_suite_ne_peut_pas_mener_sur_un_autre_site(self):
        self.client.force_login(self.aicha)
        self.client.post(reverse("accounts:verrouiller"))
        reponse = self.client.post(reverse("accounts:verrouille"), {"secret": "1234", "suite": "https://ailleurs.example/"})
        self.assertRedirects(reponse, reverse("core:accueil"), fetch_redirect_response=False)

    def test_une_collegue_prend_l_ecran_avec_son_propre_code(self):
        self.client.force_login(self.aicha)
        self.client.post(reverse("accounts:verrouiller"))
        page = self.client.get(reverse("accounts:verrouille"))
        self.assertContains(page, "Serge")
        self.assertNotContains(page, "Chef", msg_prefix="les chefs passent par leur mot de passe")
        self.assertContains(self.client.post(reverse("accounts:verrouille"), {"qui": self.serge.pk, "secret": "4321"}),
                            "incorrect")
        reponse = self.client.post(reverse("accounts:verrouille"), {"qui": self.serge.pk, "secret": "1234"})
        self.assertRedirects(reponse, reverse("core:accueil"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.serge.pk)
        self.assertNotIn(CLE_VERROU, self.client.session)
        self.assertTrue(JournalAction.objects.filter(utilisateur=self.serge, action__contains="Prise de l'écran",
                                                     details__contains="Aicha").exists())

    def test_on_ne_prend_pas_l_ecran_d_un_chef_ou_d_un_code_provisoire(self):
        nouveau = self.utilisateur("nina", Role.RECEPTIONNISTE)
        nouveau.doit_changer_secret = True
        nouveau.save()
        self.client.force_login(self.aicha)
        self.client.post(reverse("accounts:verrouiller"))
        self.assertEqual(self.client.get(reverse("accounts:verrouille"), {"qui": self.gerant.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse("accounts:verrouille"),
                                          {"qui": self.chef.pk, "secret": "1234"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("accounts:verrouille"), {"qui": nouveau.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse("accounts:verrouille"), {"qui": "abc"}).status_code, 404)

    def test_le_bar_ne_voit_que_le_bar(self):
        aurelle = self.utilisateur("aurelle", Role.BAR_RESTAURANT)
        merveille = self.utilisateur("merveille", Role.BAR_RESTAURANT)
        self.client.force_login(aurelle)
        self.client.post(reverse("accounts:verrouiller"))
        page = self.client.get(reverse("accounts:verrouille"))
        self.assertContains(page, merveille.first_name)
        self.assertNotContains(page, "Serge")

    def test_cinq_codes_faux_bloquent_comme_ailleurs(self):
        self.client.force_login(self.aicha)
        self.client.post(reverse("accounts:verrouiller"))
        for _ in range(5):
            self.client.post(reverse("accounts:verrouille"), {"qui": self.serge.pk, "secret": "0000"})
        reponse = self.client.post(reverse("accounts:verrouille"), {"qui": self.serge.pk, "secret": "1234"})
        self.assertContains(reponse, "bloqué")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.aicha.pk)

    def test_sans_code_pin_on_reprend_avec_le_mot_de_passe(self):
        sans_pin = User.objects.create_user("paul", password="Demo1234!x", role=Role.RECEPTIONNISTE)
        self.client.force_login(sans_pin)
        self.client.post(reverse("accounts:verrouiller"))
        self.assertContains(self.client.get(reverse("accounts:verrouille")), "mot de passe")
        reponse = self.client.post(reverse("accounts:verrouille"), {"secret": "Demo1234!x"})
        self.assertEqual(reponse.status_code, 302)
        self.assertNotIn(CLE_VERROU, self.client.session)

    def test_signal_d_activite(self):
        self.client.force_login(self.aicha)
        self.assertEqual(self.client.post(reverse("accounts:presence")).status_code, 204)
        self.client.post(reverse("accounts:verrouiller"))
        self.assertJSONEqual(self.client.post(reverse("accounts:presence")).content, {"verrouille": True})

    def test_un_client_n_est_jamais_verrouille(self):
        from vitrine.models import CompteClient

        client = User.objects.create_user("699112233", password="Demo1234!x", role=Role.CLIENT)
        CompteClient.objects.create(user=client, nom="Client en ligne", telephone="699112233")
        self.client.force_login(client)
        self.client.get("/")
        self.endormir(minutes=60)
        reponse = self.client.get(reverse("vitrine:espace"))
        self.assertNotIn("verrouille", reponse.get("Location", ""))
        self.assertNotIn(CLE_VERROU, self.client.session)

    @override_settings(VERROUILLAGE_MINUTES=0)
    def test_verrouillage_desactivable(self):
        self.client.force_login(self.aicha)
        self.client.get(reverse("postes:reception"))
        self.endormir(minutes=600)
        self.assertEqual(self.client.get(reverse("postes:reception")).status_code, 200)


class FichesPapierTests(BaseTest):
    def test_chambres_a_faire(self):
        from fiches.services import chambres_a_faire

        jour = aujourd_hui()
        partie = Chambre.objects.create(numero="102", tarif_nuit=20000, statut=Chambre.Statut.A_NETTOYER)
        self.sejour(arrivee=jour, depart=jour + timedelta(days=2))
        self.chambre.statut = Chambre.Statut.OCCUPEE
        self.chambre.save()
        attendue = Chambre.objects.create(numero="103", tarif_nuit=20000)
        Sejour.objects.create(client=self.client_hotel, chambre=attendue, date_arrivee=jour,
                              date_depart=jour + timedelta(days=1), tarif_grille=20000,
                              tarif_nuit=20000, statut=Sejour.Statut.RESERVE, cree_par=self.gerant)
        Chambre.objects.create(numero="104", tarif_nuit=20000)  # libre, rien à faire
        lignes = chambres_a_faire(jour)
        self.assertEqual([x["chambre"].numero for x in lignes], ["102", "101", "103"])
        self.assertIn("ménage complet", lignes[0]["quoi"])
        self.assertIn("Recouche", lignes[1]["quoi"])
        self.assertIn("Arrivée", lignes[2]["quoi"])
        self.assertEqual(partie.statut, Chambre.Statut.A_NETTOYER)

    def test_pdf_imprimables(self):
        Employe.objects.create(nom="X", prenom="Blondelle", poste="Femme de chambre", departement=Departement.MENAGE)
        self.client.force_login(self.aicha)
        for url in (reverse("fiches:chambres_a_faire"), reverse("fiches:main_courante_gardien")):
            reponse = self.client.get(url)
            self.assertEqual(reponse.status_code, 200, url)
            self.assertEqual(reponse["Content-Type"], "application/pdf")
            self.assertTrue(reponse.content.startswith(b"%PDF"))

    def test_le_bar_n_imprime_pas_les_fiches_de_la_reception(self):
        self.client.force_login(self.utilisateur("aurelle", Role.BAR_RESTAURANT))
        self.assertEqual(self.client.get(reverse("fiches:chambres_a_faire")).status_code, 403)
        self.assertEqual(self.client.get(reverse("fiches:main_courante_gardien")).status_code, 403)


class EnvoiUniqueTests(BaseTest):
    """Un double appui sur un bouton n'enregistre qu'une fois ; une page expirée n'affiche pas d'erreur technique."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()

    def test_double_appui_sur_encaisser_compte_une_seule_fois(self):
        from caisse.models import Encaissement

        s = self.sejour()
        self.ouvrir()
        self.client.force_login(self.aicha)
        page = reverse("postes:chambre", args=[self.chambre.pk])
        donnees = {"action": "encaisser", "sejour": s.pk, f"s{s.pk}-montant": 20000, f"s{s.pk}-moyen": "ESPECES",
                   "_envoi": "abc123"}
        self.client.post(reverse("postes:reception"), donnees, HTTP_REFERER="http://testserver" + page)
        second = self.client.post(reverse("postes:reception"), donnees, HTTP_REFERER="http://testserver" + page)
        self.assertRedirects(second, page, fetch_redirect_response=False)
        self.assertEqual(Encaissement.objects.count(), 1)
        self.assertContains(self.client.get(page), "deux fois le bouton")
        donnees["_envoi"] = "autre"
        self.client.post(reverse("postes:reception"), donnees)
        self.assertEqual(Encaissement.objects.count(), 2, "un nouvel envoi, lui, compte")

    def test_un_envoi_refuse_peut_repartir(self):
        self.client.force_login(self.aicha)
        donnees = {"nom": "", "telephone": "", "heure": "14:30", "chambre": self.chambre.pk, "nuits": 1, "moyen": "ESPECES",
                   "_envoi": "x1"}
        self.assertEqual(self.client.post(reverse("postes:arrivee"), donnees).status_code, 200)
        donnees.update(nom="M. Ngo", telephone="699000111")
        self.client.post(reverse("postes:arrivee"), donnees)
        self.assertTrue(Sejour.objects.filter(client__nom="M. Ngo").exists())

    def test_double_appui_sur_se_connecter(self):
        from django.test import Client

        navigateur = Client(enforce_csrf_checks=True)
        jeton = navigateur.get(reverse("accounts:connexion")).context["csrf_token"]
        donnees = {"username": "aicha", "password": "Demo1234!x", "csrfmiddlewaretoken": str(jeton)}
        self.assertEqual(navigateur.post(reverse("accounts:connexion"), donnees).status_code, 302)
        second = navigateur.post(reverse("accounts:connexion"), donnees)  # même page : ancien jeton
        self.assertRedirects(second, reverse("core:accueil"), fetch_redirect_response=False)
        donnees["_envoi"] = "z9"
        navigateur.logout()
        jeton = navigateur.get(reverse("accounts:connexion")).context["csrf_token"]
        donnees["csrfmiddlewaretoken"] = str(jeton)
        navigateur.post(reverse("accounts:connexion"), donnees)
        self.assertRedirects(navigateur.post(reverse("accounts:connexion"), donnees), reverse("core:accueil"),
                             fetch_redirect_response=False)

    def test_page_expiree_sans_erreur_technique(self):
        from django.test import Client

        navigateur = Client(enforce_csrf_checks=True)
        navigateur.force_login(self.aicha)
        page = reverse("postes:reception")
        reponse = navigateur.post(page, {"action": "menage", "chambre": self.chambre.pk,
                                         "csrfmiddlewaretoken": "x" * 64}, HTTP_REFERER="http://testserver" + page)
        self.assertRedirects(reponse, page, fetch_redirect_response=False)
        self.assertContains(navigateur.get(page), "La page avait expiré")
        anonyme = Client(enforce_csrf_checks=True)
        anonyme.get(reverse("accounts:connexion"))
        reponse = anonyme.post(reverse("accounts:connexion"), {"username": "aicha", "password": "x",
                                                               "csrfmiddlewaretoken": "y" * 64})
        self.assertRedirects(reponse, reverse("accounts:connexion"), fetch_redirect_response=False)

    def test_numero_d_envoi_et_personne_connectee_sur_la_page(self):
        self.client.force_login(self.aicha)
        page = self.client.get(reverse("postes:reception")).content.decode()
        self.assertIn(f'data-utilisateur="{self.aicha.pk}"', page)

    def test_double_appui_sur_reprendre_ne_reverrouille_pas(self):
        self.client.force_login(self.aicha)
        self.client.post(reverse("accounts:verrouiller"))
        donnees = {"secret": "1234", "suite": "/poste/reception/", "_envoi": "r1"}
        verrou = "http://testserver" + reverse("accounts:verrouille")
        self.client.post(reverse("accounts:verrouille"), donnees, HTTP_REFERER=verrou)
        second = self.client.post(reverse("accounts:verrouille"), donnees, HTTP_REFERER=verrou)
        self.assertRedirects(second, reverse("core:accueil"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("postes:reception")).status_code, 200, "l'écran reste ouvert")

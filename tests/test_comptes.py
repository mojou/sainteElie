"""Comptes numérotés (reception1…, bar1…, admin, pdg) et rôle PDG (tous les droits, comme le gérant)."""
import re
from io import StringIO

from django.core.management import call_command
from django.urls import reverse

from accounts.models import Role, User
from personnel.models import Employe

from .base import BaseTest


def creer(*args):
    sortie = StringIO()
    call_command("creer_comptes", *args, stdout=sortie)
    return sortie.getvalue()


class CreerComptesTests(BaseTest):
    def test_comptes_numerotes_avec_mot_de_passe_provisoire(self):
        sortie = creer()
        attendus = {"pdg": Role.PDG, "admin": Role.ADMIN, "reception1": Role.RECEPTIONNISTE,
                    "reception2": Role.RECEPTIONNISTE, "reception3": Role.RECEPTIONNISTE,
                    "bar1": Role.BAR_RESTAURANT, "bar2": Role.BAR_RESTAURANT, "bar3": Role.BAR_RESTAURANT}
        for identifiant, role in attendus.items():
            user = User.objects.get(username=identifiant)
            self.assertEqual(user.role, role, identifiant)
            self.assertTrue(user.doit_changer_secret, "chacun choisit ses codes à la première connexion")
            self.assertTrue(Employe.objects.filter(user=user).exists(), "une fiche employé pour le planning et la paie")
        codes = dict(re.findall(r"^\s+(\S+)\s+(Palace\d{6})", sortie, re.M))
        self.assertEqual(set(codes), set(attendus) | {"client"}, "chaque mot de passe provisoire est affiché une fois")
        self.assertEqual(len(set(codes.values())), len(codes), "tous différents")

        # Première connexion : le mot de passe provisoire marche, puis on choisit le sien
        self.assertTrue(self.client.login(username="reception2", password=codes["reception2"]))
        self.assertRedirects(self.client.get(reverse("core:accueil")), reverse("accounts:premiere_connexion"),
                             fetch_redirect_response=False)

        # Le compte client : relié à sa fiche, il arrive directement dans son espace (pas d'écran du personnel)
        from vitrine.models import CompteClient

        client = User.objects.get(username="client")
        compte = CompteClient.objects.get(user=client)
        self.assertEqual((client.role, client.doit_changer_secret, compte.statut, compte.client.nom),
                         (Role.CLIENT, False, CompteClient.Statut.RELIE, "Client test"))
        self.assertFalse(Employe.objects.filter(user=client).exists(), "un client n'est pas du personnel")
        self.client.logout()
        self.assertTrue(self.client.login(username="client", password=codes["client"]))
        espace = self.client.get(reverse("core:accueil"), follow=True)
        self.assertEqual(espace.redirect_chain[-1][0], reverse("vitrine:espace"))
        self.assertContains(espace, "Bonjour Client test")
        self.assertNotContains(espace, "presque prêt", msg_prefix="le compte est déjà relié")
        self.assertEqual(self.client.get(reverse("vitrine:mot_de_passe")).status_code, 200,
                         "il change son mot de passe dans son espace")
        self.assertEqual(self.client.get(reverse("vitrine:commander")).status_code, 200)

    def test_sans_risque_a_relancer(self):
        creer()
        avant = set(User.objects.values_list("username", "password"))
        sortie = creer("--reception", "4", "--bar", "4")
        self.assertIn("Déjà là, pas touchés", sortie)
        self.assertIn("client", sortie.split("Déjà là")[1], "le compte client n'est pas recréé")
        apres = set(User.objects.values_list("username", "password"))
        self.assertTrue(avant <= apres, "les comptes existants ne changent pas")
        self.assertEqual({u for u, _ in apres - avant}, {"reception4", "bar4"})


class RolePdgTests(BaseTest):
    def test_le_pdg_a_tous_les_droits_du_gerant(self):
        pdg = self.utilisateur("patron", Role.PDG)
        for droit in ("est_gerant", "est_direction", "peut_valider_caisse", "tient_caisse", "voit_reception",
                      "voit_stock", "est_encadrement"):
            self.assertTrue(getattr(pdg, droit), droit)
        self.client.force_login(pdg)
        for url in (reverse("accounts:utilisateurs"), reverse("core:modules"), reverse("caisse:jour_passe"),
                    reverse("paie:fiches"), reverse("caisse:virements"), reverse("fiches:hebergement"),
                    reverse("fiches:bar_restaurant")):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_le_gerant_peut_creer_un_compte_pdg(self):
        self.client.force_login(self.gerant)
        page = self.client.get(reverse("accounts:utilisateur_nouveau"))
        self.assertContains(page, 'value="PDG"')
        self.client.post(reverse("accounts:utilisateur_nouveau"), {
            "username": "proprietaire", "first_name": "M.", "last_name": "Fotsing", "role": "PDG", "is_active": "on",
            "mot_de_passe": "Provisoire-2026!"})
        self.assertEqual(User.objects.get(username="proprietaire").role, Role.PDG)

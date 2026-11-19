"""
Crée les comptes de connexion numérotés, à renommer ensuite :

    python manage.py creer_comptes                          # reception1-3, bar1-3, admin, pdg, client
    python manage.py creer_comptes --reception 4 --bar 4    # un compte de plus de chaque côté

    reception1, reception2…  Réceptionniste (chambres et boutique)
    bar1, bar2…              Cuisine / Bar
    admin                    Gérant (admin) : tous les droits
    pdg                      PDG (propriétaire) : tous les droits, comme le gérant
    client                   Client du site (espace client) : réserver, commander des plats, voir ses séjours,
                             ses paiements et télécharger ses factures. Déjà relié à une fiche client « Client test ».

Chaque compte reçoit un mot de passe provisoire, affiché une seule fois : notez-le et remettez-le à la personne. À sa
première connexion, elle choisit son mot de passe et son code PIN (le compte client change le sien dans « Mon espace
→ Changer mon mot de passe »). Les vrais noms se mettent ensuite dans
Administration → Utilisateurs (« Modifier »). Sans risque à relancer : un compte qui existe déjà n'est pas touché.
"""
import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Role, User
from hotel.models import Client
from personnel.models import Departement, Employe
from vitrine.models import CompteClient

CLIENT = ("client", "Client test", "000000000")  # identifiant, nom, téléphone (fictif)


def comptes_a_creer(reception=3, bar=3):
    """(identifiant, nom affiché, rôle, département, poste), dans l'ordre d'affichage."""
    return ([("pdg", "PDG", Role.PDG, Departement.ADMINISTRATION, "PDG"),
             ("admin", "Admin", Role.ADMIN, Departement.ADMINISTRATION, "Gérant")]
            + [(f"reception{i}", f"Réception {i}", Role.RECEPTIONNISTE, Departement.RECEPTION, "Réceptionniste")
               for i in range(1, reception + 1)]
            + [(f"bar{i}", f"Bar {i}", Role.BAR_RESTAURANT, Departement.BAR, "Cuisine / bar")
               for i in range(1, bar + 1)])


def mot_de_passe_provisoire():
    return f"Palace{secrets.randbelow(900000) + 100000}"


class Command(BaseCommand):
    help = ("Crée les comptes numérotés : reception1…, bar1…, admin, pdg et client, avec un mot de passe provisoire "
            "chacun.")

    def add_arguments(self, parser):
        parser.add_argument("--reception", type=int, default=3, help="Nombre de comptes réception / boutique.")
        parser.add_argument("--bar", type=int, default=3, help="Nombre de comptes cuisine / bar.")

    @transaction.atomic
    def handle(self, *args, **options):
        if not (0 <= options["reception"] <= 20 and 0 <= options["bar"] <= 20):
            raise CommandError("Entre 0 et 20 comptes de chaque côté.")
        crees, existants = [], []
        for identifiant, nom, role, departement, poste in comptes_a_creer(options["reception"], options["bar"]):
            if User.objects.filter(username=identifiant).exists():
                existants.append(identifiant)
                continue
            code = mot_de_passe_provisoire()
            user = User(username=identifiant, first_name=nom, role=role, doit_changer_secret=True)
            user.set_password(code)
            user.save()
            Employe.objects.get_or_create(user=user, defaults={"nom": nom, "poste": poste, "departement": departement})
            crees.append((identifiant, nom, user.get_role_display(), code))
        compte_client = self.creer_client()
        if compte_client:
            crees.append(compte_client)
        else:
            existants.append(CLIENT[0])
        if crees:
            self.stdout.write(self.style.SUCCESS(f"{len(crees)} compte(s) créé(s). Notez ces mots de passe provisoires "
                                                 "(ils ne s'afficheront plus) :"))
            for identifiant, nom, role, code in crees:
                self.stdout.write(f"  {identifiant:<12} {code:<14} {role}")
            self.stdout.write(self.style.WARNING(
                "À sa première connexion, chacun choisit son mot de passe et son code PIN. Mettez les vrais noms dans "
                "Administration → Utilisateurs (« Modifier »). Le compte client se connecte sur le site et change son "
                "mot de passe dans « Mon espace → Changer mon mot de passe »."))
        if existants:
            self.stdout.write(f"Déjà là, pas touchés : {', '.join(existants)}.")

    @staticmethod
    def creer_client():
        """Le compte client du site, relié à sa fiche : il voit tout de suite son espace (séjours, commandes).

        Pas d'écran « première connexion » pour un client (réservé au personnel) : il change son mot de passe dans
        son espace.
        """
        identifiant, nom, telephone = CLIENT
        if User.objects.filter(username=identifiant).exists():
            return None
        code = mot_de_passe_provisoire()
        user = User(username=identifiant, first_name=nom, role=Role.CLIENT)
        user.set_password(code)
        user.save()
        fiche = Client.objects.create(nom=nom, telephone=telephone, notes="Compte client de test (creer_comptes).")
        CompteClient.objects.create(user=user, nom=nom, telephone=telephone, client=fiche,
                                    statut=CompteClient.Statut.RELIE)
        return identifiant, nom, user.get_role_display(), code

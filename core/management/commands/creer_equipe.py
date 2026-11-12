"""
Crée les comptes du personnel du Saint-Élie Palace, avec des noms provisoires :

    python manage.py creer_equipe
    python manage.py creer_equipe --mot-de-passe "Provisoire2026!" --pin 4821

    Réception / boutique : carine, nina, junior
    Cuisine / bar        : aurelle, merveille, liliane
    Administration       : ducart (M. Ducart, gérant), julio et germain (M. Julio, M. Germain, adjoints de direction)
    Gouvernante          : adelaide (Mme Adélaïde) : réception / boutique, cuisine / bar, chambres / blanchisserie

Les gestionnaires de chambre / blanchisserie (Carine, Benedite, Blondelle) et le gardien
n'ont pas de compte : ils figurent seulement dans les salaires
(fiche employé), et la réception relaie leurs informations (chambres faites, main courante du gardien).

Ensuite : renommer chacun (Administration → Utilisateurs, Personnel → Employés) et faire changer à chacun
son mot de passe et son code PIN (Mon compte). Sans risque à relancer : un compte existant n'est pas modifié.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role, User
from personnel.models import Departement, Employe

MOT_DE_PASSE = "Demo1234!"
PIN = "1234"

# identifiant, prénom, nom, rôle, département, poste
EQUIPE = (
    [("ducart", "M.", "Ducart", Role.ADMIN, Departement.ADMINISTRATION, "Gérant"),
     ("julio", "M.", "Julio", Role.ADJOINT, Departement.ADMINISTRATION, "Adjoint de direction"),
     ("germain", "M.", "Germain", Role.ADJOINT, Departement.ADMINISTRATION, "Adjoint de direction"),
     ("adelaide", "Mme", "Adélaïde", Role.GOUVERNANTE, Departement.ADMINISTRATION, "Gouvernante")]
    + [(prenom.lower(), prenom, "", Role.RECEPTIONNISTE, Departement.RECEPTION, "Réceptionniste")
       for prenom in ("Carine", "Nina", "Junior")]
    + [(prenom.lower(), prenom, "", Role.BAR_RESTAURANT, Departement.BAR, "Cuisine / bar")
       for prenom in ("Aurelle", "Merveille", "Liliane")]
)

# Sans compte : ils apparaissent seulement dans les salaires. prénom, nom, département, poste
SANS_COMPTE = (
    [("", prenom, Departement.MENAGE, "Gestionnaire de chambre / blanchisserie")
     for prenom in ("Carine", "Benedite", "Blondelle")]
    + [("Gardien", "1", Departement.SECURITE, "Gardien")]
)


class Command(BaseCommand):
    help = ("Crée les comptes du personnel (noms provisoires) : réception, cuisine / bar, administration ; "
            "et les fiches employé du ménage et du gardien (salaires seulement).")

    def add_arguments(self, parser):
        parser.add_argument("--mot-de-passe", default=MOT_DE_PASSE, help="Mot de passe provisoire de chaque compte.")
        parser.add_argument("--pin", default=PIN, help="Code PIN provisoire (4 à 6 chiffres).")

    @transaction.atomic
    def handle(self, *args, **options):
        crees = []
        for identifiant, prenom, nom, role, departement, poste in EQUIPE:
            user, cree = User.objects.get_or_create(username=identifiant, defaults={
                "first_name": prenom, "last_name": nom, "role": role})
            if cree:
                user.set_password(options["mot_de_passe"])
                user.set_pin(options["pin"])
                user.doit_changer_secret = True  # chacun choisit ses codes à la première connexion
                user.save()
                crees.append(identifiant)
            Employe.objects.get_or_create(user=user, defaults={  # un prénom seul va dans « nom » (obligatoire)
                "nom": nom or prenom, "prenom": prenom if nom else "", "poste": poste, "departement": departement})
        fiches = 0
        for prenom, nom, departement, poste in SANS_COMPTE:
            _, cree = Employe.objects.get_or_create(prenom=prenom, nom=nom, user=None, defaults={
                "poste": poste, "departement": departement})
            fiches += cree
        if fiches:
            self.stdout.write(f"{fiches} fiche(s) employé sans compte (chambres / blanchisserie, gardien) : "
                              "elles servent aux salaires.")
        if crees:
            self.stdout.write(self.style.SUCCESS(
                f"{len(crees)} compte(s) créé(s) : {', '.join(crees)} (mot de passe {options['mot_de_passe']}, "
                f"PIN {options['pin']})."))
            self.stdout.write(self.style.WARNING(
                "À sa première connexion, chacun devra choisir son mot de passe et son code PIN. "
                "Les noms de famille se complètent dans Administration → Utilisateurs et Personnel → Employés."))
        else:
            self.stdout.write("Les comptes existent déjà : rien n'a été modifié.")

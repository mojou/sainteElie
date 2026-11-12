from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Gérant (admin)"
    ADJOINT = "ADJOINT", "Adjoint de direction"
    GOUVERNANTE = "GOUVERNANTE", "Gouvernante"
    CHEF_RECEPTION = "CHEF_RECEPTION", "Chef de réception"
    RECEPTIONNISTE = "RECEPTIONNISTE", "Réceptionniste (chambres et boutique)"
    BAR_RESTAURANT = "BAR_RESTAURANT", "Cuisine / Bar"
    CHEF_EQUIPE = "CHEF_EQUIPE", "Chef d'équipe"
    EMPLOYE = "EMPLOYE", "Employé"
    CLIENT = "CLIENT", "Client (espace en ligne)"


class User(AbstractUser):
    """Utilisateur de l'application. Le rôle décide de ce qu'il voit.

    Le chef de réception a aussi tous les droits d'un réceptionniste (il peut tenir un shift).
    Le code PIN sert de signature électronique (remise de caisse, validations sur le poste d'un autre).
    """

    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.EMPLOYE)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    pin_hash = models.CharField(max_length=128, blank=True, editable=False)
    # Protection contre les essais au hasard : 5 erreurs de suite bloquent 15 minutes.
    echecs_connexion = models.PositiveSmallIntegerField(default=0, editable=False)
    connexion_bloquee_jusqua = models.DateTimeField(null=True, blank=True, editable=False)
    echecs_pin = models.PositiveSmallIntegerField(default=0, editable=False)
    pin_bloque_jusqua = models.DateTimeField(null=True, blank=True, editable=False)
    doit_changer_secret = models.BooleanField(
        "doit choisir son mot de passe et son code PIN", default=False,
        help_text="Compte créé avec un mot de passe provisoire : la personne choisit les siens à la première connexion.")

    class Meta:
        verbose_name = "utilisateur"
        ordering = ["first_name", "last_name", "username"]

    def __str__(self):
        return self.get_full_name() or self.username

    # --- Code PIN (signature) ----------------------------------------------
    def set_pin(self, pin):
        self.pin_hash = make_password(pin)

    def check_pin(self, pin):
        return bool(self.pin_hash) and bool(pin) and check_password(pin, self.pin_hash)

    @property
    def a_un_pin(self):
        return bool(self.pin_hash)

    # --- Rôles ----------------------------------------------------------------
    @property
    def est_gerant(self):
        return self.is_superuser or self.role == Role.ADMIN

    @property
    def est_client(self):
        """Client de l'hôtel avec un compte en ligne : il ne voit que son espace, jamais la gestion."""
        return self.role == Role.CLIENT and not self.is_superuser

    @property
    def est_adjoint(self):
        return self.role == Role.ADJOINT

    @property
    def est_direction(self):
        """Gérant et adjoints : ils suivent toute l'activité. La paie, les finances et les paramètres restent au gérant."""
        return self.est_gerant or self.est_adjoint

    @property
    def est_gouvernante(self):
        """Encadre la réception / boutique, la cuisine / bar et les chambres / blanchisserie.

        Planning et congés de ces équipes, stock, chambres et séjours, validation des caisses. Pas de caisse à elle,
        ni la paie, les finances ou les paramètres.
        """
        return self.role == Role.GOUVERNANTE

    @property
    def est_chef_reception(self):
        return self.role == Role.CHEF_RECEPTION

    @property
    def est_reception(self):
        return self.role in (Role.RECEPTIONNISTE, Role.CHEF_RECEPTION)

    @property
    def peut_valider_caisse(self):
        return self.est_direction or self.est_chef_reception or self.est_gouvernante

    @property
    def est_chef_equipe(self):
        return self.role == Role.CHEF_EQUIPE

    @property
    def est_bar(self):
        """Cuisine / bar : vend boissons et plats sur sa caisse ; un plat ou une boisson à crédit va sur la chambre."""
        return self.role == Role.BAR_RESTAURANT and not self.is_superuser

    @property
    def est_terrain(self):
        """Personnel qui n'encadre pas : il voit un menu court et des gros boutons."""
        return not (self.est_direction or self.est_chef_reception or self.est_chef_equipe or self.est_gouvernante)

    @property
    def est_encadrement(self):
        """Direction et chefs : menu complet, tableau de bord, planning, alertes."""
        return not self.est_terrain

    @property
    def voit_reception(self):
        return self.est_reception or self.est_direction or self.est_gouvernante

    @property
    def voit_stock(self):
        return self.est_direction or self.est_chef_equipe or self.est_gouvernante

    @property
    def departement(self):
        """Département de la fiche employé (maintenance, sécurité…), vide s'il n'y en a pas."""
        employe = self.profil_employe
        return employe.departement if employe else ""

    @property
    def tient_caisse(self):
        """Réception, cuisine / bar et direction. Le ménage, le nettoyage et le gardiennage n'ont pas de caisse."""
        return self.est_reception or self.est_bar or self.est_direction

    @property
    def poste_sans_saisie(self):
        """Employé sans caisse ni écran de saisie : il ne voit que son planning et ses congés."""
        return (self.est_terrain and not (self.est_reception or self.est_bar or self.est_client)
                and self.departement not in ("MENAGE", "MAINTENANCE", "SECURITE"))

    @property
    def profil_employe(self):
        return getattr(self, "employe", None)

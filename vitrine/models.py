from django.conf import settings
from django.db import models
from django.urls import reverse

from core.stockage import stockage_prive


class CompteClient(models.Model):
    """Compte en ligne d'un client : il y suit ses séjours, ce qu'il a payé et ce qu'il reste à régler.

    À l'inscription, le compte est « en attente » : la réception le relie à la fiche du client après avoir vérifié
    que c'est bien lui. Sans cette étape, quiconque connaît un numéro de téléphone verrait les séjours d'un autre.
    """

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente de la réception"
        RELIE = "RELIE", "Relié à la fiche client"
        REFUSE = "REFUSE", "Refusé"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="compte_client")
    client = models.ForeignKey("hotel.Client", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="comptes_en_ligne")
    nom = models.CharField("nom complet", max_length=120)
    telephone = models.CharField("téléphone", max_length=20)
    email = models.EmailField("e-mail", blank=True)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    cree_le = models.DateTimeField("inscrit le", auto_now_add=True)
    traite_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    traite_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-cree_le"]
        verbose_name = "compte client en ligne"
        verbose_name_plural = "comptes clients en ligne"

    def __str__(self):
        return f"{self.nom} ({self.telephone})"


class PhotoSite(models.Model):
    """Photo de la page d'accueil publique, ajoutée par le gérant (Paramètres → Photos du site).

    Une rubrique sans photo affiche une illustration dessinée : jamais la photo d'un autre hôtel.
    """

    class Rubrique(models.TextChoices):
        HOTEL = "HOTEL", "L'hôtel"
        CHAMBRES = "CHAMBRES", "Les chambres"
        RECEPTION = "RECEPTION", "La réception"
        PLATS = "PLATS", "Nos plats"
        PARKING = "PARKING", "Le parking"

    rubrique = models.CharField(max_length=12, choices=Rubrique.choices)
    image = models.ImageField(storage=stockage_prive, upload_to="site/")
    legende = models.CharField("légende", max_length=120, blank=True,
                               help_text="Facultatif. Ex. : « Suite 102/103 », « Poulet DG », « Parking gardé ».")
    ordre = models.PositiveSmallIntegerField(default=0)
    ajoutee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    ajoutee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordre", "ajoutee_le"]
        verbose_name = "photo du site"
        verbose_name_plural = "photos du site"

    def __str__(self):
        return f"{self.get_rubrique_display()} : {self.legende or self.image.name}"

    @property
    def url(self):
        return reverse("vitrine:photo", args=[self.pk])


class DemandeReservation(models.Model):
    """Réservation demandée sur la page d'accueil, confirmée ensuite par la réception (voir reservations.py)."""

    class Statut(models.TextChoices):
        NOUVELLE = "NOUVELLE", "À confirmer"
        CONFIRMEE = "CONFIRMEE", "Confirmée"
        REFUSEE = "REFUSEE", "Refusée"
        ANNULEE = "ANNULEE", "Annulée par le client"

    date_arrivee = models.DateField("arrivée")
    date_depart = models.DateField("départ")
    nb_personnes = models.PositiveSmallIntegerField("personnes", default=1)
    categorie = models.CharField("type de chambre", max_length=10)
    tarif_nuit = models.PositiveIntegerField("prix affiché par nuit")
    chambre_proposee = models.ForeignKey("hotel.Chambre", null=True, blank=True, on_delete=models.SET_NULL,
                                         related_name="+", help_text="Une chambre libre de ce type au moment de la demande.")
    nom = models.CharField(max_length=120)
    telephone = models.CharField("téléphone", max_length=30)
    email = models.EmailField("e-mail", blank=True)
    message = models.CharField(max_length=500, blank=True)
    compte = models.ForeignKey(CompteClient, null=True, blank=True, on_delete=models.SET_NULL, related_name="demandes")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.NOUVELLE)
    sejour = models.ForeignKey("hotel.Sejour", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    motif = models.CharField(max_length=200, blank=True)
    traitee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    traitee_le = models.DateTimeField(null=True, blank=True)
    cree_le = models.DateTimeField("reçue le", auto_now_add=True)

    class Meta:
        ordering = ["-cree_le"]
        verbose_name = "demande de réservation en ligne"
        verbose_name_plural = "demandes de réservation en ligne"

    def __str__(self):
        return f"Demande n°{self.pk} : {self.nom} du {self.date_arrivee:%d/%m} au {self.date_depart:%d/%m}"

    @property
    def nb_nuits(self):
        return (self.date_depart - self.date_arrivee).days

    @property
    def total_prevu(self):
        return self.nb_nuits * self.tarif_nuit

    @property
    def libelle_type(self):
        from .reservations import LIBELLES

        return LIBELLES.get(self.categorie, "Chambre")

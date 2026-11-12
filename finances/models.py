from django.conf import settings
from django.db import models

from core.stockage import stockage_prive
from core.utils import aujourd_hui


class Depense(models.Model):
    """Dépense générale de l'établissement (hors tiroir de la réception)."""

    class Categorie(models.TextChoices):
        FOURNITURES = "FOURNITURES", "Fournitures et achats"
        ENERGIE = "ENERGIE", "Électricité, eau, gaz"
        ENTRETIEN = "ENTRETIEN", "Entretien et réparations"
        ALIMENTATION = "ALIMENTATION", "Alimentation et boissons"
        TELECOM = "TELECOM", "Téléphone et internet"
        TRANSPORT = "TRANSPORT", "Transport"
        IMPOTS = "IMPOTS", "Impôts et taxes"
        LOYER = "LOYER", "Loyer"
        AUTRE = "AUTRE", "Autre"

    class Mode(models.TextChoices):
        ESPECES = "ESPECES", "Espèces"
        ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"
        MTN_MOMO = "MTN_MOMO", "MTN MoMo"
        VIREMENT = "VIREMENT", "Virement"
        CHEQUE = "CHEQUE", "Chèque"

    date = models.DateField(default=aujourd_hui)
    categorie = models.CharField("catégorie", max_length=15, choices=Categorie.choices)
    libelle = models.CharField("libellé", max_length=200)
    montant = models.PositiveIntegerField("montant (FCFA)")
    mode_paiement = models.CharField(max_length=15, choices=Mode.choices, default=Mode.ESPECES)
    fournisseur = models.CharField(max_length=120, blank=True)
    justificatif = models.FileField(storage=stockage_prive, upload_to="justificatifs/depenses/", blank=True)
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "dépense"

    def __str__(self):
        return f"{self.libelle} ({self.montant} FCFA)"

from django.conf import settings
from django.db import models


class Intervention(models.Model):
    """Une panne signalée par n'importe qui, traitée par la maintenance."""

    class Urgence(models.TextChoices):
        NORMALE = "NORMALE", "Normale"
        URGENTE = "URGENTE", "Urgente"

    class Statut(models.TextChoices):
        A_FAIRE = "A_FAIRE", "À faire"
        EN_COURS = "EN_COURS", "En cours"
        FAITE = "FAITE", "Réparé"

    chambre = models.ForeignKey("hotel.Chambre", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="interventions")
    lieu = models.CharField("ou autre endroit", max_length=120, blank=True,
                            help_text="Si ce n'est pas une chambre : couloir, cuisine, groupe électrogène…")
    probleme = models.CharField("quel est le problème ?", max_length=200)
    urgence = models.CharField(max_length=8, choices=Urgence.choices, default=Urgence.NORMALE)
    hors_service = models.BooleanField("la chambre ne peut plus être louée en attendant", default=False)
    statut = models.CharField(max_length=8, choices=Statut.choices, default=Statut.A_FAIRE)
    signale_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    signale_le = models.DateTimeField(auto_now_add=True)
    traite_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    traite_le = models.DateTimeField(null=True, blank=True)
    commentaire = models.CharField("ce qui a été fait", max_length=200, blank=True)

    class Meta:
        ordering = ["-signale_le"]
        verbose_name = "panne"

    def __str__(self):
        return f"{self.endroit} : {self.probleme}"

    @property
    def endroit(self):
        return f"Chambre {self.chambre.numero}" if self.chambre_id else (self.lieu or "-")


class EvenementSecurite(models.Model):
    """Une ligne de la main courante de la sécurité."""

    class Type(models.TextChoices):
        RONDE = "RONDE", "Ronde"
        VISITEUR = "VISITEUR", "Visiteur"
        LIVRAISON = "LIVRAISON", "Livraison"
        INCIDENT = "INCIDENT", "Incident"
        AUTRE = "AUTRE", "Autre"

    type = models.CharField(max_length=10, choices=Type.choices, default=Type.RONDE)
    description = models.CharField("ce qui s'est passé", max_length=300)
    date = models.DateTimeField(auto_now_add=True, db_index=True)
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-date"]
        verbose_name = "événement de sécurité"

    def __str__(self):
        return f"{self.get_type_display()} : {self.description}"

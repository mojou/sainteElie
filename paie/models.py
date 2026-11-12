from django.conf import settings
from django.db import models
from django.db.models import Sum

from core.stockage import stockage_prive
from core.utils import mois_suivant


class Acompte(models.Model):
    """Avance sur salaire, déduite de la fiche de paie du mois."""

    employe = models.ForeignKey("personnel.Employe", on_delete=models.PROTECT, related_name="acomptes")
    date = models.DateField()
    montant = models.PositiveIntegerField()
    motif = models.CharField(max_length=200, blank=True)
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Acompte {self.employe} {self.montant} FCFA"


class FichePaie(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        VALIDEE = "VALIDEE", "Validée"
        PAYEE = "PAYEE", "Payée"

    employe = models.ForeignKey("personnel.Employe", on_delete=models.PROTECT, related_name="fiches_paie")
    mois = models.DateField(help_text="Premier jour du mois")
    salaire_base = models.PositiveIntegerField("salaire de base")
    primes = models.PositiveIntegerField(default=0)
    heures_sup = models.PositiveIntegerField("heures supplémentaires (montant)", default=0)
    cotisations = models.PositiveIntegerField("cotisations salariales", default=0,
                                              help_text="CNPS et impôts retenus : à calculer avec le comptable.")
    retenues = models.PositiveIntegerField("autres retenues", default=0)
    motif_retenues = models.CharField(max_length=200, blank=True)
    acomptes = models.PositiveIntegerField("acomptes déduits", default=0, editable=False)
    net_a_payer = models.IntegerField("net à payer", default=0, editable=False)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.BROUILLON)
    mode_paiement = models.CharField(max_length=40, blank=True)
    validee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    validee_le = models.DateTimeField(null=True, blank=True)
    payee_le = models.DateField(null=True, blank=True)
    pdf = models.FileField(storage=stockage_prive, upload_to="paie/", blank=True)

    class Meta:
        ordering = ["-mois", "employe__nom"]
        verbose_name = "fiche de paie"
        verbose_name_plural = "fiches de paie"
        constraints = [models.UniqueConstraint(fields=["employe", "mois"], name="une_fiche_par_mois")]

    def __str__(self):
        return f"Fiche de paie {self.employe} {self.mois:%m/%Y}"

    @property
    def brut(self):
        return self.salaire_base + self.primes + self.heures_sup

    def acomptes_du_mois(self):
        return Acompte.objects.filter(employe=self.employe, date__gte=self.mois, date__lt=mois_suivant(self.mois))

    def calculer(self):
        self.acomptes = self.acomptes_du_mois().aggregate(s=Sum("montant"))["s"] or 0
        self.net_a_payer = self.brut - self.cotisations - self.retenues - self.acomptes
        return self.net_a_payer

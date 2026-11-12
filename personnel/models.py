from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Departement(models.TextChoices):
    RECEPTION = "RECEPTION", "Réception"
    MENAGE = "MENAGE", "Chambres et blanchisserie"
    BAR = "BAR", "Cuisine / Bar"
    MAINTENANCE = "MAINTENANCE", "Maintenance"
    SECURITE = "SECURITE", "Gardiennage"
    ADMINISTRATION = "ADMINISTRATION", "Administration"
    AUTRE = "AUTRE", "Autre"


class Employe(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="employe", verbose_name="compte utilisateur")
    nom = models.CharField(max_length=80)
    prenom = models.CharField("prénom", max_length=80, blank=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    poste = models.CharField(max_length=80)
    departement = models.CharField("département", max_length=15, choices=Departement.choices)
    date_embauche = models.DateField("date d'embauche", null=True, blank=True)
    salaire_base = models.PositiveIntegerField("salaire de base mensuel (FCFA)", default=0)
    numero_cnps = models.CharField("n° CNPS", max_length=40, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom", "prenom"]
        verbose_name = "employé"

    def __str__(self):
        return f"{self.prenom} {self.nom}".strip()


class Creneau(models.Model):
    nom = models.CharField(max_length=40)
    heure_debut = models.TimeField("début")
    heure_fin = models.TimeField("fin")
    departement = models.CharField("département", max_length=15, choices=Departement.choices, blank=True,
                                   help_text="Vide = valable pour tous les départements.")
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["heure_debut"]
        verbose_name = "créneau"

    def __str__(self):
        return f"{self.nom} ({self.heure_debut:%H:%M}-{self.heure_fin:%H:%M})"

    @property
    def heures(self):
        """Durée du créneau en heures (un créneau de nuit passe minuit : 23 h → 7 h = 8 h)."""
        debut = self.heure_debut.hour * 60 + self.heure_debut.minute
        fin = self.heure_fin.hour * 60 + self.heure_fin.minute
        return round(((fin - debut) % (24 * 60) or 24 * 60) / 60, 2)

    def debut_le(self, jour):
        return timezone.make_aware(datetime.combine(jour, self.heure_debut))

    def fin_le(self, jour):
        fin = datetime.combine(jour, self.heure_fin)
        if self.heure_fin <= self.heure_debut:
            fin += timedelta(days=1)
        return timezone.make_aware(fin)


class Affectation(models.Model):
    """Planning : un employé sur un créneau un jour donné."""

    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="affectations")
    date = models.DateField()
    creneau = models.ForeignKey(Creneau, on_delete=models.PROTECT, related_name="affectations")
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["date", "creneau__heure_debut"]
        constraints = [models.UniqueConstraint(fields=["employe", "date", "creneau"], name="affectation_unique")]

    def __str__(self):
        return f"{self.employe} - {self.creneau.nom} le {self.date:%d/%m}"


class Pointage(models.Model):
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="pointages")
    date = models.DateField()
    arrivee = models.DateTimeField("arrivée")
    depart = models.DateTimeField("départ", null=True, blank=True)
    affectation = models.ForeignKey(Affectation, null=True, blank=True, on_delete=models.SET_NULL)
    retard_minutes = models.PositiveIntegerField(default=0)
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-arrivee"]

    def __str__(self):
        return f"{self.employe} le {self.date:%d/%m}"

    @property
    def duree_heures(self):
        if not self.depart:
            return None
        return round((self.depart - self.arrivee).total_seconds() / 3600, 2)


class Statut(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    ACCEPTEE = "ACCEPTEE", "Acceptée"
    REFUSEE = "REFUSEE", "Refusée"


class DemandeConge(models.Model):
    class Type(models.TextChoices):
        CONGE = "CONGE", "Congé"
        PERMISSION = "PERMISSION", "Permission"
        MALADIE = "MALADIE", "Maladie"

    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="conges")
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.CONGE)
    date_debut = models.DateField("du")
    date_fin = models.DateField("au")
    motif = models.CharField(max_length=200, blank=True)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    traite_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    commentaire = models.CharField(max_length=200, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le"]
        verbose_name = "demande de congé"

    @property
    def nb_jours(self):
        return (self.date_fin - self.date_debut).days + 1


class DemandeEchange(models.Model):
    """Échange de shift entre deux collègues, validé par le chef."""

    affectation = models.ForeignKey(Affectation, on_delete=models.CASCADE, related_name="+",
                                    verbose_name="mon shift")
    affectation_collegue = models.ForeignKey(Affectation, on_delete=models.CASCADE, related_name="+",
                                             verbose_name="shift du collègue")
    motif = models.CharField(max_length=200, blank=True)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    demandeur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    traite_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le"]
        verbose_name = "demande d'échange de shift"

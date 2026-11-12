from django.conf import settings
from django.db import models


class Projet(models.Model):
    class Statut(models.TextChoices):
        A_FAIRE = "A_FAIRE", "À démarrer"
        EN_COURS = "EN_COURS", "En cours"
        SUSPENDU = "SUSPENDU", "Suspendu"
        TERMINE = "TERMINE", "Terminé"

    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="projets")
    date_debut = models.DateField("début", null=True, blank=True)
    echeance = models.DateField("échéance", null=True, blank=True)
    budget = models.PositiveIntegerField("budget (FCFA)", default=0)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.A_FAIRE)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["statut", "echeance"]

    def __str__(self):
        return self.nom

    @property
    def avancement(self):
        total = self.taches.count()
        return round(100 * self.taches.filter(statut=Tache.Statut.FAITE).count() / total) if total else 0

    @property
    def couleur(self):
        """Une couleur par projet, pour le reconnaître d'un coup d'œil (bande de la carte)."""
        return (self.pk or 0) % 6

    @property
    def en_retard(self):
        from core.utils import aujourd_hui

        return bool(self.echeance and self.echeance < aujourd_hui() and self.statut != self.Statut.TERMINE)


class Tache(models.Model):
    class Statut(models.TextChoices):
        A_FAIRE = "A_FAIRE", "À faire"
        EN_COURS = "EN_COURS", "En cours"
        BLOQUEE = "BLOQUEE", "Bloquée"
        FAITE = "FAITE", "Faite"

    class Priorite(models.TextChoices):
        BASSE = "BASSE", "Basse"
        NORMALE = "NORMALE", "Normale"
        HAUTE = "HAUTE", "Haute"

    projet = models.ForeignKey(Projet, on_delete=models.CASCADE, related_name="taches")
    titre = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assigne_a = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="taches", verbose_name="assignée à")
    echeance = models.DateField("échéance", null=True, blank=True)
    priorite = models.CharField("priorité", max_length=8, choices=Priorite.choices, default=Priorite.NORMALE)
    statut = models.CharField(max_length=8, choices=Statut.choices, default=Statut.A_FAIRE)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["statut", "echeance", "-priorite"]
        verbose_name = "tâche"

    def __str__(self):
        return self.titre

    @property
    def etat_echeance(self):
        """« retard » (dépassée), « bientot » (dans 2 jours au plus) ou vide."""
        from core.utils import aujourd_hui

        if not self.echeance or self.statut == self.Statut.FAITE:
            return ""
        reste = (self.echeance - aujourd_hui()).days
        return "retard" if reste < 0 else ("bientot" if reste <= 2 else "")


class CommentaireTache(models.Model):
    """La discussion d'une tâche : messages de l'équipe, et changements d'étape notés tout seuls."""

    tache = models.ForeignKey(Tache, on_delete=models.CASCADE, related_name="commentaires")
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    texte = models.TextField()
    systeme = models.BooleanField(default=False, help_text="Noté par l'application (changement d'étape…).")
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]
        verbose_name = "commentaire de tâche"

    def __str__(self):
        return f"{self.auteur} : {self.texte[:40]}"

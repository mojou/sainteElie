from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.urls import reverse

from core.stockage import stockage_prive


class Chambre(models.Model):
    class Categorie(models.TextChoices):
        SIMPLE = "SIMPLE", "Simple"
        DOUBLE = "DOUBLE", "Double"
        SUITE = "SUITE", "Suite"
        AUTRE = "AUTRE", "Autre"

    class Statut(models.TextChoices):
        LIBRE = "LIBRE", "Libre"
        OCCUPEE = "OCCUPEE", "Occupée"
        A_NETTOYER = "A_NETTOYER", "À nettoyer"
        HORS_SERVICE = "HORS_SERVICE", "Hors service"

    numero = models.CharField("numéro", max_length=10, unique=True)
    categorie = models.CharField("catégorie", max_length=10, choices=Categorie.choices, default=Categorie.SIMPLE)
    tarif_nuit = models.PositiveIntegerField("tarif par nuit (FCFA)")
    capacite = models.PositiveSmallIntegerField("capacité", default=2)
    statut = models.CharField(max_length=15, choices=Statut.choices, default=Statut.LIBRE)
    description = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    photo = models.ImageField(storage=stockage_prive, upload_to="chambres/", blank=True,
                              help_text="Facultatif : montrée sur la page d'accueil, dans la carte de sa catégorie.")

    class Meta:
        ordering = ["numero"]

    def __str__(self):
        return f"Chambre {self.numero}"

    @property
    def photo_url(self):
        return reverse("vitrine:image_chambre", args=[self.pk]) if self.photo else ""


class Client(models.Model):
    nom = models.CharField("nom complet", max_length=120)
    telephone = models.CharField("téléphone", max_length=30)
    piece_identite = models.CharField("pièce d'identité", max_length=60, blank=True)
    entreprise = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Sejour(models.Model):
    """Réservation puis séjour : une seule fiche qui change de statut."""

    class Statut(models.TextChoices):
        RESERVE = "RESERVE", "Réservé"
        EN_COURS = "EN_COURS", "En cours"
        TERMINE = "TERMINE", "Terminé"
        ANNULE = "ANNULE", "Annulé"
        NO_SHOW = "NO_SHOW", "No-show"

    class Gratuite(models.TextChoices):
        PAYANT = "", "Payant"
        OFFERT = "OFFERT", "Offert (geste commercial)"
        COMPENSATION = "COMPENSATION", "Compensation"

    ACTIFS = (Statut.RESERVE, Statut.EN_COURS)

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="sejours")
    chambre = models.ForeignKey(Chambre, on_delete=models.PROTECT, related_name="sejours")
    date_arrivee = models.DateField("arrivée")
    date_depart = models.DateField("départ")
    nb_personnes = models.PositiveSmallIntegerField("personnes", default=1)
    tarif_grille = models.PositiveIntegerField("tarif de la grille")
    tarif_nuit = models.PositiveIntegerField("tarif appliqué par nuit")
    motif_tarif = models.CharField("motif du tarif", max_length=200, blank=True)
    gratuite = models.CharField("type de séjour", max_length=15, choices=Gratuite.choices, blank=True, default="",
                                help_text="Offert ou compensation : nuit à 0 FCFA, valeur reportée dans la colonne "
                                          "Offre ou Compensation de la fiche recette.")
    tarif_valide_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.RESERVE)
    virement_annonce = models.BooleanField("virement annoncé", default=False)
    notes = models.TextField(blank=True)
    motif_annulation = models.CharField(max_length=200, blank=True)
    check_in_le = models.DateTimeField(null=True, blank=True)
    check_out_le = models.DateTimeField(null=True, blank=True)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_arrivee", "-id"]
        verbose_name = "séjour"

    def __str__(self):
        return f"{self.client} - ch. {self.chambre.numero} ({self.date_arrivee:%d/%m} au {self.date_depart:%d/%m})"

    @property
    def nb_nuits(self):
        return max((self.date_depart - self.date_arrivee).days, 0)

    @property
    def montant_chambre_prevu(self):
        return self.nb_nuits * self.tarif_nuit

    @property
    def total_nuitees(self):
        return self.nuitees.aggregate(s=Sum("montant"))["s"] or 0

    @property
    def total_extras(self):
        return self.extras.filter(statut=Extra.Statut.ACTIF).aggregate(s=Sum("montant"))["s"] or 0

    @property
    def total_facture(self):
        """Ce que le client doit au total : nuitées constatées une fois parti, nuits prévues sinon."""
        chambre = self.total_nuitees if self.statut == self.Statut.TERMINE else self.montant_chambre_prevu
        if self.statut in (self.Statut.ANNULE, self.Statut.NO_SHOW):
            chambre = self.total_nuitees
        return chambre + self.total_extras

    @property
    def total_encaisse(self):
        return self.encaissements.aggregate(s=Sum("montant_signe"))["s"] or 0

    @property
    def total_virements(self):
        return self.virements.aggregate(s=Sum("montant"))["s"] or 0

    @property
    def total_paye(self):
        return self.total_encaisse + self.total_virements

    @property
    def reste_a_payer(self):
        return self.total_facture - self.total_paye

    @property
    def remise_pct(self):
        if not self.tarif_grille or self.tarif_nuit >= self.tarif_grille:
            return 0
        return round(100 * (self.tarif_grille - self.tarif_nuit) / self.tarif_grille)


class Nuitee(models.Model):
    """La recette chambre : une ligne par nuit passée, constatée au plus tard au check-out."""

    sejour = models.ForeignKey(Sejour, on_delete=models.PROTECT, related_name="nuitees")
    date_nuit = models.DateField("nuit du")
    montant = models.PositiveIntegerField()
    constatee_le = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["date_nuit"]
        constraints = [models.UniqueConstraint(fields=["sejour", "date_nuit"], name="nuitee_unique")]
        verbose_name = "nuitée"

    def __str__(self):
        return f"Nuit du {self.date_nuit:%d/%m/%Y} - {self.sejour.chambre}"


class Extra(models.Model):
    """Consommation portée sur la note du séjour (recette), payée avec la note."""

    class Source(models.TextChoices):
        RESTAURANT = "RESTAURANT", "Cuisine"
        BAR = "BAR", "Bar"
        BOUTIQUE = "BOUTIQUE", "Boutique"
        AUTRE = "AUTRE", "Autre"

    class Statut(models.TextChoices):
        ACTIF = "ACTIF", "Sur la note"
        ANNULE = "ANNULE", "Annulé"

    sejour = models.ForeignKey(Sejour, on_delete=models.PROTECT, related_name="extras")
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.RESTAURANT)
    description = models.CharField(max_length=200)
    montant = models.PositiveIntegerField()
    numero_bon = models.CharField("n° de bon", max_length=30, blank=True)
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    date_conso = models.DateTimeField("consommé le", db_index=True)
    statut = models.CharField(max_length=8, choices=Statut.choices, default=Statut.ACTIF)
    motif_annulation = models.CharField(max_length=200, blank=True)
    annule_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    annule_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_conso"]

    def __str__(self):
        return f"{self.get_source_display()} : {self.description}"


class Nettoyage(models.Model):
    """Chambre faite par le ménage. Sert aussi de contrôle des ventes jamais saisies."""

    chambre = models.ForeignKey(Chambre, on_delete=models.PROTECT, related_name="nettoyages")
    fait_le = models.DateTimeField(db_index=True)
    fait_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    sans_sejour = models.BooleanField(default=False)

    class Meta:
        ordering = ["-fait_le"]

    def __str__(self):
        return f"{self.chambre} faite le {self.fait_le:%d/%m %H:%M}"

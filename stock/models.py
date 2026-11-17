from django.conf import settings
from django.db import models
from django.urls import reverse

from core.stockage import stockage_prive
from core.utils import aujourd_hui


class Article(models.Model):
    class Categorie(models.TextChoices):
        BAR = "BAR", "Bar"
        BOUTIQUE = "BOUTIQUE", "Boutique"
        RESTAURANT = "RESTAURANT", "Cuisine (carte des plats)"
        MAGASIN = "MAGASIN", "Magasin (linge, produits d'accueil)"
        ENTRETIEN = "ENTRETIEN", "Entretien"
        AUTRE = "AUTRE", "Autre"

    VENDUS_AU_COMPTOIR = (Categorie.BAR, Categorie.BOUTIQUE)

    nom = models.CharField(max_length=120)
    code = models.CharField("code (contenance)", max_length=20, blank=True,
                            help_text="Comme sur la fiche : 65CL, 75CL, 1L… « CONSO » = vente au verre.")
    categorie = models.CharField("catégorie", max_length=12, choices=Categorie.choices)
    rubrique = models.CharField("rubrique de la carte", max_length=40, blank=True,
                                help_text="Pour les plats : Plats chauds, Garnitures, Desserts, Petit-déjeuner…")
    description = models.CharField("composition", max_length=160, blank=True,
                                   help_text="Facultatif, montré sur la carte du site : « omelette garnie, pain, cake… ».")
    ordre = models.PositiveIntegerField("ordre sur la fiche", default=0)
    unite = models.CharField("unité", max_length=20, default="unité")
    quantite = models.IntegerField("quantité en stock", default=0, editable=False)
    seuil_alerte = models.PositiveIntegerField("seuil d'alerte", default=0)
    prix_achat = models.PositiveIntegerField("prix d'achat unitaire (FCFA)", default=0)
    prix_vente = models.PositiveIntegerField("prix de vente unitaire (FCFA)", default=0)
    suivi_stock = models.BooleanField("suivi du stock", default=True,
                                      help_text="Sans effet pour un plat de la cuisine : il se vend sans sortie de stock.")
    actif = models.BooleanField(default=True)
    photo = models.ImageField(storage=stockage_prive, upload_to="articles/", blank=True,
                              help_text="Facultatif : aide à reconnaître l'article à la vente (et les plats sur le site).")
    # Photo d'illustration libre de droits (pas la vraie photo du plat) : à citer sur le site (« Crédits photos »).
    # Vide dès que le gérant prend la vraie photo.
    photo_credit = models.CharField("crédit de la photo", max_length=300, blank=True)
    photo_source = models.URLField("source de la photo", blank=True)
    photo_licence_url = models.URLField("licence de la photo", blank=True)

    class Meta:
        ordering = ["categorie", "ordre", "nom"]
        constraints = [models.UniqueConstraint(fields=["nom", "code"], name="article_nom_code_unique")]

    def __str__(self):
        return f"{self.nom} {self.code}".strip()

    @property
    def photo_url(self):
        return reverse("vitrine:image_article", args=[self.pk]) if self.photo else ""

    @property
    def photo_d_illustration(self):
        return bool(self.photo and self.photo_credit)

    def oublier_credit(self):
        """La vraie photo remplace l'illustration : plus rien à citer."""
        self.photo_credit = self.photo_source = self.photo_licence_url = ""

    @property
    def image_url(self):
        """La vraie photo si le gérant l'a prise, sinon le dessin de l'article (stock/illustrations.py)."""
        if self.photo:
            return self.photo_url
        from .illustrations import VERSION

        return f"{reverse('vitrine:dessin_article', args=[self.pk])}?v={VERSION}"

    @property
    def marge(self):
        """Ce que rapporte une unité vendue, au coût moyen d'achat."""
        return self.prix_vente - self.prix_achat if self.prix_achat else None

    @property
    def est_bas(self):
        return self.quantite <= self.seuil_alerte

    @property
    def valeur(self):
        return self.quantite * self.prix_achat

    @property
    def vendable_au_comptoir(self):
        """Boissons au bar, boutique à la réception, plats de la carte à la caisse de la cuisine."""
        return (self.actif and self.prix_vente > 0
                and self.categorie in (*self.VENDUS_AU_COMPTOIR, self.Categorie.RESTAURANT))

    def save(self, *args, **kwargs):
        if self.categorie == self.Categorie.RESTAURANT:
            self.suivi_stock = False
        super().save(*args, **kwargs)


class MouvementStock(models.Model):
    class Type(models.TextChoices):
        ENTREE = "ENTREE", "Approvisionnement"
        VENTE = "VENTE", "Vente (main courante)"
        RETOUR = "RETOUR", "Annulation de vente"
        AVARIE = "AVARIE", "Avarie (casse, périmé)"
        SORTIE = "SORTIE", "Sortie (consommation interne)"
        INVENTAIRE = "INVENTAIRE", "Inventaire (ajustement)"

    SORTANTS = (Type.VENTE, Type.AVARIE, Type.SORTIE)

    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="mouvements")
    type = models.CharField(max_length=10, choices=Type.choices)
    quantite = models.IntegerField(help_text="Variation du stock (négative pour une sortie).")
    quantite_apres = models.IntegerField()
    cout_unitaire = models.PositiveIntegerField(default=0)
    motif = models.CharField(max_length=200, blank=True)
    journee = models.DateField("journée", default=aujourd_hui, db_index=True,
                               help_text="Journée de la fiche de stock à laquelle le mouvement appartient.")
    date = models.DateTimeField(auto_now_add=True)
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "mouvement de stock"

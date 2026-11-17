from django.conf import settings
from django.db import models, transaction


class Etablissement(models.Model):
    """Coordonnées de l'établissement, reprises en tête des documents PDF (une seule ligne)."""

    nom = models.CharField(max_length=120, default="Saint-Élie")
    slogan = models.CharField(max_length=120, blank=True, help_text="Une phrase sous le nom, sur la page d'accueil.")
    presentation = models.TextField("présentation", blank=True,
                                    help_text="Quelques lignes pour présenter l'hôtel sur la page d'accueil publique.")
    adresse = models.CharField(max_length=200, blank=True)
    telephone = models.CharField("téléphone", max_length=60, blank=True)
    email = models.EmailField(blank=True)
    niu = models.CharField("NIU / RCCM", max_length=80, blank=True)
    # Vide : seule la réservation et la vente des chambres sont ouvertes, le reste est grisé (voir core/modules.py).
    modules_ouverts = models.JSONField("modules ouverts", default=list, blank=True)

    class Meta:
        verbose_name = "établissement"

    def __str__(self):
        return self.nom

    @property
    def monogramme(self):
        """La lettre du logo : « S » pour « Complexe St Élie Palace » (on saute les mots génériques)."""
        mots = [m for m in self.nom.split() if m.lower() not in ("complexe", "hôtel", "hotel", "résidence", "le", "la")]
        return (mots[0][0] if mots else self.nom[:1] or "H").upper()

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"nom": settings.ETABLISSEMENT_NOM})
        return obj


class Compteur(models.Model):
    """Numérotation continue (reçus clients…) : un numéro manquant se voit."""

    nom = models.CharField(max_length=40, unique=True)
    valeur = models.PositiveBigIntegerField(default=0)

    @classmethod
    def suivant(cls, nom):
        with transaction.atomic():
            cls.objects.get_or_create(nom=nom)
            compteur = cls.objects.select_for_update().get(nom=nom)
            compteur.valeur += 1
            compteur.save(update_fields=["valeur"])
            return compteur.valeur


class Alerte(models.Model):
    class Type(models.TextChoices):
        ECART = "ECART", "Écart de caisse"
        ECART_RECURRENT = "ECART_RECURRENT", "Écarts récurrents"
        ANNULATION = "ANNULATION", "Annulation"
        VALIDATION_EN_RETARD = "VALIDATION_EN_RETARD", "Validation en retard"
        FOND_INCOMPLET = "FOND_INCOMPLET", "Fond de caisse incomplet"
        SORTIE_A_VALIDER = "SORTIE_A_VALIDER", "Sortie de caisse à valider"
        MENAGE_SANS_SEJOUR = "MENAGE_SANS_SEJOUR", "Chambre faite sans séjour"
        STOCK = "STOCK", "Stock bas"
        PERSONNEL = "PERSONNEL", "Personnel"
        AUTRE = "AUTRE", "Autre"

    class Public(models.TextChoices):
        GERANT = "GERANT", "Gérant"
        RECEPTION = "RECEPTION", "Gérant et chef de réception"
        ENCADREMENT = "ENCADREMENT", "Gérant et chefs"
        STOCK = "STOCK", "Gérant et chefs d'équipe"

    type = models.CharField(max_length=30, choices=Type.choices)
    public = models.CharField(max_length=20, choices=Public.choices, default=Public.GERANT)
    message = models.CharField(max_length=300)
    lien = models.CharField(max_length=200, blank=True)
    cle = models.CharField(max_length=120, blank=True, db_index=True,
                           help_text="Évite les doublons d'une même alerte non lue.")
    creee_le = models.DateTimeField(auto_now_add=True)
    lue_le = models.DateTimeField(null=True, blank=True)
    lue_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")

    class Meta:
        ordering = ["-creee_le"]

    def __str__(self):
        return self.message

    @classmethod
    def visibles_par(cls, user):
        if user.est_direction:
            return cls.objects.all()
        publics = []
        if user.est_chef_reception:
            publics += [cls.Public.RECEPTION, cls.Public.ENCADREMENT]
        if user.est_gouvernante:
            publics += [cls.Public.RECEPTION, cls.Public.ENCADREMENT, cls.Public.STOCK]
        if user.est_chef_equipe:
            publics += [cls.Public.ENCADREMENT, cls.Public.STOCK]
        return cls.objects.filter(public__in=publics)


class JournalAction(models.Model):
    """Journal d'audit : qui a fait quoi, quand. Jamais modifié."""

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    action = models.CharField(max_length=80)
    objet = models.CharField(max_length=160, blank=True)
    details = models.TextField(blank=True)
    date = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "action journalisée"

    def __str__(self):
        return f"{self.date:%d/%m/%Y %H:%M} {self.action} {self.objet}"

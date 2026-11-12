"""
Caisse par réceptionniste.

Montants en entiers FCFA. Rien n'est supprimé : les erreurs s'annulent par une écriture liée,
avec motif. Une session validée est verrouillée ; une correction passe par une session rectificative.
"""
from datetime import time

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from core.stockage import stockage_prive
from core.utils import aujourd_hui


class ParametreCaisse(models.Model):
    """Paramètres datés : chaque session copie ceux en vigueur à son ouverture."""

    date_effet = models.DateField("date d'effet", default=aujourd_hui)
    seuil_ecart = models.PositiveIntegerField("seuil de tolérance (FCFA)", default=1000)
    heure_coupure = models.TimeField("heure de coupure du rapport quotidien", default=time(16, 0))
    plafond_depense = models.PositiveIntegerField("dépense sans validation jusqu'à (FCFA)", default=10000)
    plafond_remboursement = models.PositiveIntegerField("remboursement espèces sans validation jusqu'à (FCFA)",
                                                        default=10000)
    remise_tarif_max_pct = models.PositiveSmallIntegerField("remise sur tarif sans validation jusqu'à (%)", default=20)
    delai_validation_heures = models.PositiveSmallIntegerField("délai de validation d'une remise (heures)", default=24)
    alerte_nb_ecarts = models.PositiveSmallIntegerField("alerte après N écarts hors seuil", default=3)
    alerte_fenetre_jours = models.PositiveSmallIntegerField("sur une période de (jours)", default=30)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_effet", "-id"]
        verbose_name = "paramètres de caisse"

    def __str__(self):
        return f"Paramètres au {self.date_effet:%d/%m/%Y}"

    @classmethod
    def en_vigueur(cls, jour=None):
        jour = jour or aujourd_hui()
        return cls.objects.filter(date_effet__lte=jour).first() or cls(date_effet=jour)


class Tiroir(models.Model):
    """Une caisse physique. Son poste décide de qui l'ouvre et de ce qu'on y vend."""

    class Poste(models.TextChoices):
        RECEPTION = "RECEPTION", "Réception (chambres et boutique)"
        BAR = "BAR", "Cuisine / Bar"

    # Cuisine / bar : boissons et plats sur la même caisse. Payés tout de suite, ou à crédit sur la chambre (extra).
    CATEGORIES = {Poste.RECEPTION: ("BOUTIQUE",), Poste.BAR: ("BAR", "RESTAURANT")}

    nom = models.CharField(max_length=60, unique=True)
    poste = models.CharField(max_length=10, choices=Poste.choices, default=Poste.RECEPTION)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["poste", "nom"]

    def __str__(self):
        return self.nom

    @property
    def categories_vendues(self):
        return self.CATEGORIES.get(self.poste, ())

    @classmethod
    def accessibles_a(cls, user):
        tiroirs = cls.objects.filter(actif=True)
        if user.est_bar:
            return tiroirs.filter(poste=cls.Poste.BAR)
        if user.est_reception and not user.est_chef_reception:
            return tiroirs.filter(poste=cls.Poste.RECEPTION)
        return tiroirs

    def fond_en_vigueur(self, jour=None):
        jour = jour or aujourd_hui()
        fond = self.fonds.filter(date_effet__lte=jour).first()
        return fond.montant if fond else 0


class FondCaisse(models.Model):
    """Historique du fond de caisse d'un tiroir (modifiable par l'admin seul, avec date d'effet)."""

    tiroir = models.ForeignKey(Tiroir, on_delete=models.PROTECT, related_name="fonds")
    montant = models.PositiveIntegerField("fond de caisse (FCFA)")
    date_effet = models.DateField("date d'effet", default=aujourd_hui)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_effet", "-id"]


def totaux_par_moyen(encaissements):
    """Totaux d'un ensemble d'encaissements par moyen : Espèces, Orange Money, MTN MoMo, Carte, Chèque.

    Renvoie une liste ordonnée de dicts {"cle", "libelle", "montant"} ; chaque moyen apparaît, même à zéro.
    """
    lignes = {mode: [libelle, 0] for mode, libelle in Encaissement.Mode.choices}
    for mode, total in encaissements.order_by().values_list("mode").annotate(s=Sum("montant_signe")):
        lignes.setdefault(mode, [mode.replace("_", " ").capitalize(), 0])[1] += total or 0
    return [{"cle": cle, "libelle": libelle, "montant": montant} for cle, (libelle, montant) in lignes.items()]


def detail_lignes(montants):
    """[1000, 2000] → « 1 000 + 2 000 » ; vide s'il n'y a qu'une ligne (le total suffit)."""
    from core.utils import format_fcfa

    return " + ".join(format_fcfa(m, unite=False) for m in montants) if len(montants) > 1 else ""


class Shift(models.TextChoices):
    MATIN = "MATIN", "Matin"
    APRES_MIDI = "APRES_MIDI", "Après-midi"
    NUIT = "NUIT", "Nuit"
    AUTRE = "AUTRE", "Autre"


class RapportQuotidien(models.Model):
    debut = models.DateTimeField()
    coupure = models.DateTimeField(unique=True)
    genere_le = models.DateTimeField(auto_now_add=True)
    genere_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    pdf = models.FileField(storage=stockage_prive, upload_to="rapports/", blank=True)

    class Meta:
        ordering = ["-coupure"]
        verbose_name = "rapport quotidien"

    def __str__(self):
        return f"Rapport du {timezone.localtime(self.coupure):%d/%m/%Y}"


class SessionCaisse(models.Model):
    class Statut(models.TextChoices):
        OUVERTE = "OUVERTE", "Ouverte"
        REMISE = "REMISE", "Remise effectuée"
        ECART = "ECART", "Écart à arbitrer"
        VALIDEE = "VALIDEE", "Validée"

    class Imputation(models.TextChoices):
        ERREUR_CORRIGEE = "ERREUR_CORRIGEE", "Erreur de saisie corrigée"
        PERTE_HOTEL = "PERTE_HOTEL", "Perte pour l'hôtel"
        CHARGE_RECEPTIONNISTE = "CHARGE_RECEPTIONNISTE", "À la charge du réceptionniste"
        AUTRE = "AUTRE", "Autre décision"

    receptionniste = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sessions_caisse",
                                       verbose_name="titulaire (réceptionniste, barman…)")
    tiroir = models.ForeignKey(Tiroir, on_delete=models.PROTECT, related_name="sessions")
    shift = models.CharField(max_length=12, choices=Shift.choices)
    ouverte_le = models.DateTimeField(auto_now_add=True)
    remise_le = models.DateTimeField(null=True, blank=True, db_index=True)
    especes_ouverture_prevues = models.IntegerField("espèces d'ouverture prévues", default=0)
    especes_ouverture_comptees = models.IntegerField("espèces d'ouverture comptées", default=0)
    seuil_ecart = models.PositiveIntegerField(default=1000)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.OUVERTE, db_index=True)
    cloture_office = models.BooleanField("clôture d'office", default=False)
    motif_contestation = models.CharField(max_length=300, blank=True)
    validee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    validee_le = models.DateTimeField(null=True, blank=True)
    imputation = models.CharField(max_length=25, choices=Imputation.choices, blank=True)
    decision_arbitrage = models.TextField("décision d'arbitrage", blank=True)
    rapport = models.ForeignKey(RapportQuotidien, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="sessions")
    est_rectificative = models.BooleanField(default=False)
    rectifie_session = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="rectifications")
    motif_rectification = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-ouverte_le"]
        verbose_name = "session de caisse"
        constraints = [
            models.UniqueConstraint(fields=["tiroir"], condition=Q(statut="OUVERTE", est_rectificative=False),
                                    name="une_session_ouverte_par_tiroir"),
            models.UniqueConstraint(fields=["receptionniste"], condition=Q(statut="OUVERTE", est_rectificative=False),
                                    name="une_session_ouverte_par_personne"),
        ]

    def __str__(self):
        prefixe = "Rectification" if self.est_rectificative else "Session"
        return f"{prefixe} n°{self.pk} - {self.receptionniste} ({self.get_shift_display()}, {timezone.localtime(self.ouverte_le):%d/%m})"

    # --- Calculs en direct -----------------------------------------------------
    @property
    def ecart_ouverture(self):
        return self.especes_ouverture_comptees - self.especes_ouverture_prevues

    def _somme_encaissements(self, **filtres):
        return self.encaissements.filter(**filtres).aggregate(s=Sum("montant_signe"))["s"] or 0

    def totaux_par_mode(self):
        return {mode: self._somme_encaissements(mode=mode) for mode, _ in Encaissement.Mode.choices}

    def totaux_par_moyen(self):
        """Espèces, Orange Money, MTN MoMo, carte, chèque : comme le réceptionniste les compte."""
        return totaux_par_moyen(self.encaissements.all())

    @property
    def total_encaisse(self):
        return self._somme_encaissements()

    @property
    def total_depenses(self):
        return self.sorties.exclude(statut=SortieCaisse.Statut.REFUSEE).filter(
            type=SortieCaisse.Type.DEPENSE).aggregate(s=Sum("montant"))["s"] or 0

    @property
    def total_sorties_especes(self):
        """Ce qui a quitté le tiroir (dépenses et prélèvements), y compris en attente de validation.

        Une dépense refusée n'est plus déduite : l'argent manquant devient un écart à arbitrer.
        """
        return self.sorties.exclude(statut=SortieCaisse.Statut.REFUSEE).aggregate(
            s=Sum("montant"))["s"] or 0

    @property
    def especes_attendues(self):
        return (self.especes_ouverture_comptees + self._somme_encaissements(mode=Encaissement.Mode.ESPECES)
                - self.total_sorties_especes)

    def cheques_attendus(self):
        qs = self.encaissements.filter(mode=Encaissement.Mode.CHEQUE)
        nombre = qs.filter(nature__in=Encaissement.ENTREES).count() - qs.filter(nature=Encaissement.Nature.ANNULATION).count()
        return max(nombre, 0), self._somme_encaissements(mode=Encaissement.Mode.CHEQUE)

    @property
    def est_verrouillee(self):
        return self.statut == self.Statut.VALIDEE


class Encaissement(models.Model):
    class Nature(models.TextChoices):
        ACOMPTE = "ACOMPTE", "Acompte"
        REGLEMENT = "REGLEMENT", "Règlement (chambre et extras)"
        REMBOURSEMENT = "REMBOURSEMENT", "Remboursement"
        VENTE = "VENTE", "Vente bar / boutique"
        REGLEMENT_CREDIT = "REGLEMENT_CREDIT", "Règlement d'une dette client"
        ANNULATION = "ANNULATION", "Annulation"

    class Mode(models.TextChoices):
        """Orange Money et MTN MoMo sont des moyens de paiement comme les espèces : rien d'autre à saisir."""

        ESPECES = "ESPECES", "Espèces"
        ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"
        MTN_MOMO = "MTN_MOMO", "MTN MoMo"
        CARTE = "CARTE", "Carte"
        CHEQUE = "CHEQUE", "Chèque"

    MODES_MOBILE = (Mode.ORANGE_MONEY, Mode.MTN_MOMO)
    MODES_COMPTOIR = (Mode.ESPECES, Mode.ORANGE_MONEY, Mode.MTN_MOMO)
    ENTREES = (Nature.ACOMPTE, Nature.REGLEMENT, Nature.VENTE, Nature.REGLEMENT_CREDIT)

    session = models.ForeignKey(SessionCaisse, on_delete=models.PROTECT, related_name="encaissements")
    sejour = models.ForeignKey("hotel.Sejour", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="encaissements", help_text="Vide pour une vente comptoir ou une dette client.")
    client = models.ForeignKey("hotel.Client", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="reglements", help_text="Client qui règle une dette de comptoir.")
    nature = models.CharField(max_length=20, choices=Nature.choices)
    mode = models.CharField(max_length=15, choices=Mode.choices)
    montant = models.PositiveIntegerField()
    montant_signe = models.IntegerField(editable=False)
    reference = models.CharField("référence (carte, chèque)", max_length=80, blank=True)
    numero_recu = models.PositiveBigIntegerField("n° de reçu", unique=True)
    annule = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="annulations",
                               help_text="Pour une annulation : l'encaissement annulé.")
    motif = models.CharField(max_length=300, blank=True)
    valide_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    date = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Reçu n°{self.numero_recu} - {self.get_nature_display()} {self.montant} FCFA"

    @property
    def est_annule(self):
        return self.annulations.exists()

    @property
    def moyen_libelle(self):
        """Espèces, Orange Money, MTN MoMo, carte ou chèque."""
        return self.get_mode_display()

    @property
    def libelle(self):
        """Ce que l'encaissement concerne : un séjour, une vente comptoir ou une dette client."""
        if self.sejour_id:
            return f"Ch. {self.sejour.chambre.numero} · {self.sejour.client}"
        ventes = list(self.ventes.select_related("article")[:4])
        if ventes:
            articles = ", ".join(f"{v.quantite} × {v.article}" for v in ventes[:3]) + (" …" if len(ventes) > 3 else "")
            return f"{ventes[0].get_categorie_display()} : {articles}"
        if self.client_id:
            return f"Dette de {self.client}"
        return self.get_nature_display()


class VenteComptoir(models.Model):
    """Une ligne de la main courante (boutique, bar ou cuisine), saisie dans une session de caisse."""

    class Reglement(models.TextChoices):
        COMPTANT = "COMPTANT", "Payé maintenant"
        CREDIT = "CREDIT", "À crédit (sur une chambre ou un client)"
        OFFERT = "OFFERT", "Offert"

    session = models.ForeignKey(SessionCaisse, on_delete=models.PROTECT, related_name="ventes")
    journee = models.DateField("journée", db_index=True)
    article = models.ForeignKey("stock.Article", on_delete=models.PROTECT, related_name="ventes")
    quantite = models.PositiveIntegerField("quantité")
    prix_unitaire = models.PositiveIntegerField()
    montant = models.PositiveIntegerField()
    reglement = models.CharField("règlement", max_length=10, choices=Reglement.choices)
    encaissement = models.ForeignKey(Encaissement, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="ventes")
    sejour = models.ForeignKey("hotel.Sejour", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="ventes_comptoir", help_text="Crédit porté sur la note d'une chambre.")
    extra = models.ForeignKey("hotel.Extra", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    client = models.ForeignKey("hotel.Client", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="credits_comptoir", help_text="Crédit à un client qui n'est pas logé.")
    mouvement = models.ForeignKey("stock.MouvementStock", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+", help_text="Vide pour un plat du restaurant (pas de suivi de stock).")
    observation = models.CharField("observation / motif", max_length=200, blank=True)
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    date = models.DateTimeField(auto_now_add=True)
    annulee = models.BooleanField(default=False)
    motif_annulation = models.CharField(max_length=200, blank=True)
    annulee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "vente comptoir"

    def __str__(self):
        return f"{self.quantite} × {self.article} ({self.get_reglement_display()})"

    def get_categorie_display(self):
        return self.article.get_categorie_display()

    @property
    def beneficiaire(self):
        if self.sejour_id:
            return f"Ch. {self.sejour.chambre.numero} · {self.sejour.client}"
        return str(self.client) if self.client_id else ""


class SortieCaisse(models.Model):
    class Type(models.TextChoices):
        DEPENSE = "DEPENSE", "Dépense"
        PRELEVEMENT = "PRELEVEMENT", "Prélèvement du gérant"

    class Statut(models.TextChoices):
        VALIDEE = "VALIDEE", "Validée"
        A_VALIDER = "A_VALIDER", "À valider"
        REFUSEE = "REFUSEE", "Refusée"

    session = models.ForeignKey(SessionCaisse, on_delete=models.PROTECT, related_name="sorties")
    type = models.CharField(max_length=12, choices=Type.choices)
    montant = models.PositiveIntegerField()
    motif = models.CharField(max_length=300)
    justificatif = models.FileField(storage=stockage_prive, upload_to="justificatifs/caisse/", blank=True)
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    valide_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.VALIDEE)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "sortie de caisse"

    def __str__(self):
        return f"{self.get_type_display()} {self.montant} FCFA - {self.motif}"


class RemiseCaisse(models.Model):
    session = models.OneToOneField(SessionCaisse, on_delete=models.PROTECT, related_name="remise")
    premier_comptage = models.IntegerField("premier comptage des espèces")
    especes_comptees = models.IntegerField("espèces comptées")
    recompte_fait = models.BooleanField(default=False)
    billetage = models.JSONField(default=dict, blank=True)
    cheques_nombre = models.PositiveSmallIntegerField(default=0)
    cheques_total = models.PositiveIntegerField(default=0)
    # Orange Money et MTN MoMo : ce que la personne a reçu sur le téléphone, déclaré ligne à ligne (bouton « + »).
    orange_money_declare = models.IntegerField("Orange Money déclaré", default=0)
    mtn_momo_declare = models.IntegerField("MTN MoMo déclaré", default=0)
    detail_mobile = models.JSONField("montants saisis ligne à ligne", default=dict, blank=True)
    orange_money_attendu = models.IntegerField(null=True, blank=True)
    mtn_momo_attendu = models.IntegerField(null=True, blank=True)
    ecart_orange_money = models.IntegerField(null=True, blank=True)
    ecart_mtn_momo = models.IntegerField(null=True, blank=True)
    especes_attendues = models.IntegerField(null=True, blank=True)
    ecart = models.IntegerField(null=True, blank=True)
    cheques_attendus_total = models.IntegerField(null=True, blank=True)
    ecart_cheques = models.IntegerField(null=True, blank=True)
    motif = models.TextField(blank=True)
    versement = models.IntegerField(default=0)
    especes_transmises = models.IntegerField(default=0)
    compte_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    entrant = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="remises_recues")
    signe_sortant_le = models.DateTimeField(null=True, blank=True)
    signe_entrant_le = models.DateTimeField(null=True, blank=True)
    finalisee = models.BooleanField(default=False)
    recu_pdf = models.FileField(storage=stockage_prive, upload_to="remises/", blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "remise de caisse"

    # (mode d'encaissement, libellé, préfixe des champs ci-dessus)
    MOBILES = (("ORANGE_MONEY", "Orange Money", "orange_money"), ("MTN_MOMO", "MTN MoMo", "mtn_momo"))

    def __str__(self):
        return f"Remise de la {self.session}"

    def lignes_mobile(self):
        """Orange Money puis MTN MoMo : déclaré, attendu et écart (les deux derniers après la remise)."""
        return [{"cle": cle, "libelle": libelle, "declare": getattr(self, f"{champ}_declare"),
                 "attendu": getattr(self, f"{champ}_attendu"), "ecart": getattr(self, f"ecart_{champ}"),
                 "lignes": detail_lignes((self.detail_mobile or {}).get(cle, []))}
                for cle, libelle, champ in self.MOBILES]


class Virement(models.Model):
    """Arrive sur le compte bancaire, pas au tiroir : hors session, saisi par l'admin ou le comptable."""

    sejour = models.ForeignKey("hotel.Sejour", on_delete=models.PROTECT, related_name="virements")
    montant = models.PositiveIntegerField()
    reference_bancaire = models.CharField("référence bancaire", max_length=80)
    date_valeur = models.DateField("date de valeur")
    saisi_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_valeur"]


class Consigne(models.Model):
    """Consigne de passation laissée en fin de shift."""

    session = models.ForeignKey(SessionCaisse, on_delete=models.PROTECT, related_name="consignes")
    texte = models.TextField()
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return self.texte[:60]


class ConsigneLecture(models.Model):
    consigne = models.ForeignKey(Consigne, on_delete=models.CASCADE, related_name="lectures")
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    lu_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["consigne", "utilisateur"], name="lecture_unique")]

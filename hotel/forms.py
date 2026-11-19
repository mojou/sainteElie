from django import forms
from django.core.exceptions import ValidationError

from caisse.forms import MoyenPaiementForm
from caisse.models import Encaissement, ParametreCaisse
from core.forms import (Formulaire, FormulaireModele, champ_pin, champ_signataire, controler_signature,
                        validateurs_caisse)

from core.utils import aujourd_hui

from . import services
from .models import Chambre, Client, Sejour


class ChambreForm(FormulaireModele):
    class Meta:
        model = Chambre
        fields = ["numero", "categorie", "tarif_nuit", "capacite", "statut", "description", "active"]
        help_texts = {"description": "Ce que le client lit sur la réservation en ligne (lit, climatisation, vue…). "
                                     "Les photos s'ajoutent dans Chambres → Photos des chambres."}


class ClientForm(FormulaireModele):
    class Meta:
        model = Client
        fields = ["nom", "telephone", "piece_identite", "entreprise", "email", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class SejourForm(FormulaireModele):
    """Réservation : le tarif vient de la fiche chambre ; un autre tarif exige un motif (et un visa au-delà du plafond).

    Dates déjà passées (départ aujourd'hui ou avant) : le séjour est enregistré directement « Libéré ».
    """

    def _clean_passe(self, d, chambre, arrivee, depart):
        """Séjour déjà fini : la direction donne les heures du client ; il sera enregistré « Libéré »."""
        if "heure_arrivee" not in self.fields:
            self.add_error(None, f"Ce séjour est déjà passé (départ le {depart:%d/%m/%Y}) : seuls le gérant, le PDG "
                                 "et les adjoints peuvent l'enregistrer.")
            return
        for champ, quoi in (("heure_arrivee", "d'arrivée"), ("heure_depart", "de départ")):
            if not d.get(champ):
                self.add_error(champ, f"Séjour déjà passé : indiquez l'heure {quoi} du client.")
        if chambre and arrivee:
            autre = (Sejour.objects.filter(chambre=chambre, statut=Sejour.Statut.TERMINE, date_arrivee__lt=depart,
                                           date_depart__gt=arrivee).select_related("client").first())
            if autre:
                self.add_error(None, f"La chambre {chambre.numero} était déjà prise par {autre.client} du "
                                     f"{autre.date_arrivee:%d/%m} au {autre.date_depart:%d/%m/%Y}.")
        d["_passe"] = True

    """Réservation : le tarif vient de la fiche chambre ; un autre tarif exige un motif (et un visa au-delà du plafond)."""

    nouveau_client_nom = forms.CharField(label="… ou nouveau client : nom", required=False, max_length=120)
    nouveau_client_telephone = forms.CharField(label="Téléphone du nouveau client", required=False, max_length=30)
    tarif_nuit = forms.IntegerField(label="Tarif par nuit (FCFA)", required=False, min_value=0,
                                    help_text="Laisser vide pour appliquer le tarif de la chambre.")
    valideur = champ_signataire("Remise validée par", validateurs_caisse(), required=False)
    valideur_pin = champ_pin("Code PIN du valideur", required=False)
    # Séjour aux dates déjà passées (fiche papier) : enregistré directement « Libéré » (direction seulement).
    heure_arrivee = forms.TimeField(label="Heure d'arrivée du client", required=False)
    heure_depart = forms.TimeField(label="Heure de départ du client", required=False)

    class Meta:
        model = Sejour
        fields = ["client", "chambre", "date_arrivee", "date_depart", "nb_personnes", "gratuite", "tarif_nuit",
                  "motif_tarif", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["client"].required = False
        self.fields["client"].label = "Client existant"
        self.fields["chambre"].queryset = Chambre.objects.filter(active=True).exclude(
            statut=Chambre.Statut.HORS_SERVICE)
        self.fields["chambre"].label_from_instance = (
            lambda c: f"{c.numero} - {c.get_categorie_display()} - {c.tarif_nuit:,} FCFA".replace(",", " "))
        if self.instance.pk and self.instance.statut == Sejour.Statut.EN_COURS:
            self.fields["date_arrivee"].disabled = True
        if self.instance.pk:
            for nom in ("nouveau_client_nom", "nouveau_client_telephone", "heure_arrivee", "heure_depart"):
                self.fields.pop(nom)
        elif not (user and user.est_direction):
            for nom in ("heure_arrivee", "heure_depart"):
                self.fields.pop(nom)

    def clean(self):
        d = super().clean()
        if not d.get("client") and not self.instance.pk:
            if not (d.get("nouveau_client_nom") and d.get("nouveau_client_telephone")):
                raise ValidationError("Choisissez un client existant, ou saisissez le nom et le téléphone du nouveau client.")
        chambre, arrivee, depart = d.get("chambre"), d.get("date_arrivee"), d.get("date_depart")
        if chambre and arrivee and depart:
            try:
                services.verifier_disponibilite(chambre, arrivee, depart, exclure=self.instance)
            except ValidationError as exc:
                self.add_error(None, exc)
        d["_passe"] = False
        if not self.instance.pk and depart and depart <= aujourd_hui():
            self._clean_passe(d, chambre, arrivee, depart)
        if chambre:
            tarif = d.get("tarif_nuit")
            grille = chambre.tarif_nuit
            gratuit = bool(d.get("gratuite"))
            if not grille:
                self.add_error("chambre", f"Le tarif de la chambre {chambre.numero} n'est pas encore renseigné : "
                                          "le gérant doit le saisir (menu Chambres).")
                return d
            if gratuit:
                tarif = 0
            elif tarif in (None, ""):
                tarif = self.instance.tarif_nuit if self.instance.pk and self.instance.chambre_id == chambre.pk else grille
            d["tarif_nuit"] = tarif
            if tarif != grille and not (d.get("motif_tarif") or "").strip():
                self.add_error("motif_tarif", "Un séjour offert, compensé ou à un autre tarif que la grille doit être motivé.")
            remise = round(100 * (grille - tarif) / grille) if grille and tarif < grille else 0
            plafond = ParametreCaisse.en_vigueur().remise_tarif_max_pct
            if remise > plafond:
                if not d.get("valideur"):
                    quoi = "Séjour gratuit" if gratuit else f"Remise de {remise} %"
                    self.add_error("valideur", f"{quoi} : au-delà de {plafond} % de remise, "
                                               "le chef de réception ou le gérant doit valider avec son code PIN.")
                else:
                    valideur = controler_signature(self, "valideur", "valideur_pin")
                    if valideur is not None and valideur.pk == self.user.pk:
                        self.add_error("valideur", "La remise doit être validée par une autre personne.")
                        valideur = None
                    d["_valideur"] = valideur
        return d


class EncaissementForm(MoyenPaiementForm, Formulaire):
    """Encaissement d'un séjour : Espèces, Orange Money, MTN MoMo, carte ou chèque."""

    carte_cheque = True
    ordre_champs = ["nature", "montant", "moyen", "reference"]
    nature = forms.ChoiceField(choices=[c for c in Encaissement.Nature.choices if c[0] in (
        "ACOMPTE", "REGLEMENT", "REMBOURSEMENT")])
    montant = forms.IntegerField(label="Montant (FCFA)", min_value=1)
    reference = forms.CharField(label="Référence (n° de transaction ou de chèque)", required=False, max_length=80)
    valideur = champ_signataire("Remboursement validé par", validateurs_caisse(), required=False)
    valideur_pin = champ_pin("Code PIN du valideur", required=False)

    def clean(self):
        d = super().clean()
        d["_valideur"] = None
        if d.get("valideur"):
            d["_valideur"] = controler_signature(self, "valideur", "valideur_pin")
        return d


def _carte_des_plats(champ):
    from stock.models import Article

    champ.queryset = Article.objects.filter(
        categorie=Article.Categorie.RESTAURANT, actif=True, prix_vente__gt=0).order_by("ordre", "nom")
    champ.label_from_instance = lambda a: f"{a.nom} — {a.prix_vente:,} FCFA".replace(",", " ")


class ExtraForm(Formulaire):
    """Un extra en deux gestes : un plat de la carte (prix calculé), ou autre chose avec son prix."""

    plat = forms.ModelChoiceField(label="Plat de la carte", queryset=None, required=False,
                                  empty_label="— Choisir un plat —")
    quantite = forms.IntegerField(label="Combien ?", min_value=1, initial=1)
    description = forms.CharField(label="… ou autre chose (écrivez-le)", required=False, max_length=200)
    montant = forms.IntegerField(label="Prix (FCFA), seulement pour « autre chose »", min_value=1, required=False)
    numero_bon = forms.CharField(label="N° du bon (si vous en avez un)", required=False, max_length=30)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _carte_des_plats(self.fields["plat"])

    def clean(self):
        d = super().clean()
        plat, quantite = d.get("plat"), d.get("quantite") or 1
        if plat:
            d["description"] = f"{quantite} × {plat.nom}"
            d["montant"] = quantite * plat.prix_vente
        elif not (d.get("description") or "").strip():
            raise ValidationError("Choisissez un plat, ou écrivez ce que le client a pris.")
        elif not d.get("montant"):
            self.add_error("montant", "Indiquez le prix.")
        elif quantite > 1:
            d["description"] = f"{quantite} × {d['description'].strip()}"
            d["montant"] = quantite * d["montant"]
        return d

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User
from core.forms import Formulaire
from core.utils import normaliser_telephone


class InscriptionForm(Formulaire):
    nom = forms.CharField(label="Nom complet", max_length=120,
                          widget=forms.TextInput(attrs={"autocomplete": "name", "autofocus": True}))
    telephone = forms.CharField(label="Téléphone", max_length=30,
                                widget=forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel",
                                                              "placeholder": "Ex. : 699 11 22 33"}),
                                help_text="Le numéro que vous donnez à la réception. Il sera votre identifiant.")
    email = forms.EmailField(label="E-mail (facultatif)", required=False,
                             widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    mot_de_passe = forms.CharField(label="Mot de passe", help_text="8 caractères au moins, pas seulement des chiffres.",
                                   widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    confirmation = forms.CharField(label="Confirmer le mot de passe",
                                   widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_telephone(self):
        numero = normaliser_telephone(self.cleaned_data["telephone"])
        if not 8 <= len(numero) <= 12:
            raise ValidationError("Ce numéro de téléphone ne semble pas complet.")
        if User.objects.filter(username=numero).exists():
            raise ValidationError("Un compte existe déjà avec ce numéro : connectez-vous.")
        return numero

    def clean(self):
        d = super().clean()
        mot_de_passe = d.get("mot_de_passe")
        if mot_de_passe and mot_de_passe != d.get("confirmation"):
            self.add_error("confirmation", "Les deux mots de passe ne sont pas identiques.")
        elif mot_de_passe:
            try:
                validate_password(mot_de_passe, User(username=d.get("telephone", ""), first_name=d.get("nom", "")))
            except ValidationError as exc:
                self.add_error("mot_de_passe", exc)
        return d


class EnvoiMultiple(forms.ClearableFileInput):
    allow_multiple_selected = True


class ChampPhotos(forms.ImageField):
    """Une ou plusieurs photos d'un coup (20 au plus)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("widget", EnvoiMultiple(attrs={"accept": "image/jpeg,image/png,image/webp", "multiple": True}))
        super().__init__(**kwargs)

    def clean(self, data, initial=None):
        photos = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        if not photos:
            return [super().clean(None, initial)]  # lève « champ obligatoire »
        if len(photos) > 20:
            raise ValidationError("20 photos au plus à la fois.")
        return [super(ChampPhotos, self).clean(photo, initial) for photo in photos]


class PhotoForm(Formulaire):
    rubrique = forms.ChoiceField(label="Rubrique", choices=[])
    images = ChampPhotos(label="Photos", help_text="Une ou plusieurs (20 au plus) : JPEG, PNG ou WebP, 10 Mo chacune. "
                                                   "Elles sont tournées et allégées automatiquement.")
    legende = forms.CharField(label="Légende (facultatif, pour toutes)", max_length=120, required=False)

    def __init__(self, *args, **kwargs):
        from .models import PhotoSite

        super().__init__(*args, **kwargs)
        self.fields["rubrique"].choices = PhotoSite.Rubrique.choices

    def clean_images(self):
        images = self.cleaned_data["images"]
        for image in images:
            if image.size > 10 * 1024 * 1024:
                raise ValidationError(f"« {image.name} » est trop lourde (10 Mo au plus).")
        return images


class RechercheChambreForm(Formulaire):
    """Les dates et le nombre de personnes : la première question de la réservation en ligne."""

    arrivee = forms.DateField(label="Arrivée")
    depart = forms.DateField(label="Départ")
    personnes = forms.IntegerField(label="Personnes", min_value=1, max_value=6, initial=1)


class DemandeReservationForm(Formulaire):
    nom = forms.CharField(label="Votre nom", max_length=120, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    telephone = forms.CharField(label="Votre téléphone", max_length=30,
                                widget=forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel",
                                                              "placeholder": "Ex. : 699 11 22 33"}),
                                help_text="La réception vous appelle à ce numéro pour confirmer.")
    email = forms.EmailField(label="E-mail (facultatif)", required=False,
                             widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    message = forms.CharField(label="Un mot pour la réception (facultatif)", required=False, max_length=500,
                              widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Heure d'arrivée, lit bébé, facture au nom d'une entreprise…"}))
    # Piège à robots : un champ texte invisible pour un humain (caché par le style) ; un robot le remplit.
    site_web = forms.CharField(label="Site web (ne pas remplir)", required=False, max_length=200,
                               widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off",
                                                             "class": "piege"}))

    def clean_telephone(self):
        numero = normaliser_telephone(self.cleaned_data["telephone"])
        if not 8 <= len(numero) <= 12:
            raise ValidationError("Ce numéro de téléphone ne semble pas complet.")
        return numero


class CommandePlatsForm(Formulaire):
    """Commander des plats : les quantités (champs q_<id>), le jour et l'heure, où l'on mange, les coordonnées."""

    jour = forms.DateField(label="Pour quel jour ?", widget=forms.DateInput(attrs={"type": "date"}))
    heure = forms.ChoiceField(label="À quelle heure ?", choices=[])
    service = forms.ChoiceField(label="Où mangez-vous ?", widget=forms.RadioSelect, choices=[])
    chambre = forms.CharField(label="Votre numéro de chambre", max_length=10, required=False,
                              widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "Ex. : 104"}))
    nom = forms.CharField(label="Votre nom", max_length=120, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    telephone = forms.CharField(label="Votre téléphone", max_length=30,
                                widget=forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel",
                                                              "placeholder": "Ex. : 699 11 22 33"}),
                                help_text="La réception vous appelle à ce numéro pour confirmer.")
    email = forms.EmailField(label="E-mail (facultatif)", required=False,
                             widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    message = forms.CharField(label="Un mot pour la cuisine (facultatif)", required=False, max_length=300,
                              widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Sans piment, bien cuit…"}))
    site_web = forms.CharField(label="Site web (ne pas remplir)", required=False, max_length=200,
                               widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def __init__(self, *args, **kwargs):
        from . import commandes
        from .models import CommandePlats

        super().__init__(*args, **kwargs)
        self.fields["heure"].choices = [(h.strftime("%H:%M"), h.strftime("%H h %M").replace(" 00", "")) for h in
                                        commandes.creneaux()]
        self.fields["service"].choices = CommandePlats.Service.choices

    def quantites(self):
        """{id du plat: portions} tel que tapé ; lève une erreur si une quantité n'est pas un nombre."""
        resultat = {}
        for cle, valeur in (self.data or {}).items():
            if not cle.startswith("q_"):
                continue
            valeur = str(valeur).strip() or "0"
            if not (cle[2:].isdigit() and valeur.isdigit() and len(valeur) <= 3):
                raise ValidationError("Une quantité est illisible : recommencez votre choix.")
            if int(valeur):
                resultat[int(cle[2:])] = int(valeur)
        return resultat

    def clean_telephone(self):
        numero = normaliser_telephone(self.cleaned_data["telephone"])
        if not 8 <= len(numero) <= 12:
            raise ValidationError("Ce numéro de téléphone ne semble pas complet.")
        return numero

    def clean(self):
        from datetime import datetime

        from hotel.models import Chambre

        from . import commandes
        from .models import CommandePlats

        d = super().clean()
        try:
            d["lignes"] = commandes.verifier_lignes(self.quantites())
        except ValidationError as exc:
            self.add_error(None, exc)
        if d.get("jour") and d.get("heure"):
            d["pour_le"] = commandes.moment(d["jour"], datetime.strptime(d["heure"], "%H:%M").time())
            try:
                commandes.verifier_moment(d["pour_le"])
            except ValidationError as exc:
                self.add_error("heure", exc)
        if d.get("service") == CommandePlats.Service.EN_CHAMBRE:
            numero = (d.get("chambre") or "").strip()
            if not numero:
                self.add_error("chambre", "Donnez votre numéro de chambre.")
            elif not Chambre.objects.filter(active=True, numero__iexact=numero).exists():
                self.add_error("chambre", "Ce numéro de chambre n'existe pas chez nous.")
        return d

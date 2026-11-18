from django import forms
from django.db.models import Q

from accounts.forms import verifier_pin
from accounts.models import Role, User


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None, format="%Y-%m-%d"):
        super().__init__(attrs, format=format)


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, attrs=None, format="%H:%M"):
        super().__init__(attrs, format=format)


# Champs d'argent : le montant s'écrit en lettres dessous (app.js). Ceux d'argent reçu ou compté demandent
# « C'est bien ça ? » au-delà du seuil (MONTANT_A_CONFIRMER) ou du montant dû : un zéro en trop ne passe plus.
NOMS_MONTANT = {"montant", "prix", "prix_vente", "prix_achat", "tarif_nuit", "tarif", "especes", "especes_comptees",
                "cheques_total", "salaire_base", "cout_unitaire", "primes", "cotisations", "retenues"}
NOMS_ARGENT_RECU = {"montant", "especes", "especes_comptees", "cheques_total"}


def est_champ_montant(nom, champ):
    return isinstance(champ, forms.IntegerField) and (nom in NOMS_MONTANT or "fcfa" in str(champ.label or "").lower())


class FichierProtege(forms.ClearableFileInput):
    """Champ photo ou justificatif d'une fiche déjà enregistrée.

    Les fichiers sont rangés hors du site (stockage privé) : ils n'ont pas d'adresse publique, donc pas de lien
    « fichier actuel » (le widget de Django en voudrait un, et la page planterait). On dit seulement qu'il y en a un.
    """

    template_name = "widgets/fichier_protege.html"
    initial_text = "Photo ou fichier actuel"
    input_text = "Pour le remplacer, choisissez-en un autre"
    clear_checkbox_label = "Le retirer"

    def is_initial(self, value):
        return bool(value and getattr(value, "name", ""))


class StyleMixin:
    """Champs date et heure natifs du navigateur, nombres sans flèches inutiles, montants écrits en lettres."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nom, champ in self.fields.items():
            if type(champ.widget) is forms.ClearableFileInput:  # champ photo ou fichier simple (pas l'envoi multiple)
                champ.widget = FichierProtege(attrs=champ.widget.attrs)
            if est_champ_montant(nom, champ):
                champ.widget.attrs.setdefault("data-montant", "")
                if nom in NOMS_ARGENT_RECU:
                    champ.widget.attrs.setdefault("data-confirmer-montant", "")
            if isinstance(champ, forms.DateField) and not isinstance(champ, forms.DateTimeField):
                champ.widget = DateInput()
            elif isinstance(champ, forms.TimeField):
                champ.widget = TimeInput()
            elif isinstance(champ, forms.IntegerField):
                champ.widget.attrs.setdefault("inputmode", "numeric")
            elif isinstance(champ, forms.ModelChoiceField) and getattr(champ.queryset, "model", None) is User:
                # Les clients en ligne ne sont pas du personnel : jamais proposés comme responsable, signataire…
                champ.queryset = champ.queryset.exclude(role=Role.CLIENT)


class SelectAvecImages(forms.Select):
    """Liste déroulante dont chaque choix peut porter une petite photo, montrée dans la recherche (voir app.js)."""

    def __init__(self, *args, images=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.images = images or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        image = self.images.get(getattr(value, "value", value))
        if image:
            option["attrs"]["data-image"] = image
        return option


class Formulaire(StyleMixin, forms.Form):
    pass


class FormulaireModele(StyleMixin, forms.ModelForm):
    pass


class MotifForm(Formulaire):
    motif = forms.CharField(label="Motif", max_length=300, widget=forms.Textarea(attrs={"rows": 3}))


def champ_signataire(label, qs=None, required=True):
    qs = qs if qs is not None else User.objects.filter(is_active=True)
    return forms.ModelChoiceField(label=label, queryset=qs, required=required)


def champ_pin(label="Code PIN", required=True):
    return forms.CharField(label=label, required=required, max_length=6,
                           widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}))


def validateurs_caisse():
    return User.objects.filter(Q(role__in=[Role.ADMIN, Role.ADJOINT, Role.GOUVERNANTE, Role.CHEF_RECEPTION])
                               | Q(is_superuser=True),
                               is_active=True)


def gerants():
    return User.objects.filter(Q(role=Role.ADMIN) | Q(is_superuser=True), is_active=True)


def controler_signature(form, champ_user, champ_code):
    """Vérifie le PIN d'un signataire choisi dans le formulaire ; ajoute l'erreur au bon champ."""
    signataire = form.cleaned_data.get(champ_user)
    try:
        verifier_pin(signataire, form.cleaned_data.get(champ_code))
    except forms.ValidationError as exc:
        form.add_error(champ_code, exc)
        return None
    return signataire

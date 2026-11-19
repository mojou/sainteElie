from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError

from caisse.forms import MoyenPaiementForm
from core.forms import Formulaire
from core.utils import aujourd_hui
from hotel.models import Chambre
from hotel.services import verifier_disponibilite

from .models import EvenementSecurite, Intervention


def _libelle_chambre(c):
    return f"{c.numero} — {c.tarif_nuit:,} FCFA la nuit".replace(",", " ")


class ArriveeForm(MoyenPaiementForm, Formulaire):
    """Un client arrive sans réservation : on l'installe et on encaisse en une fois."""

    ordre_champs = ["nom", "telephone", "heure", "chambre", "nuits", "montant", "moyen"]
    nom = forms.CharField(label="Nom du client", max_length=120)
    telephone = forms.CharField(label="Téléphone", max_length=30)
    heure = forms.TimeField(label="Heure d'arrivée", input_formats=["%H:%M", "%H:%M:%S"],
                            error_messages={"required": "Indiquez l'heure d'arrivée du client (par exemple 14:30).",
                                            "invalid": "Indiquez l'heure d'arrivée du client (par exemple 14:30)."})
    chambre = forms.ModelChoiceField(label="Chambre (libres)", queryset=Chambre.objects.none())
    nuits = forms.IntegerField(label="Nombre de nuits", min_value=1, max_value=90, initial=1)
    montant = forms.IntegerField(label="Payé maintenant (FCFA)", min_value=0, required=False,
                                 help_text="Laisser vide si le client paiera plus tard.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["chambre"].queryset = Chambre.objects.filter(active=True, statut=Chambre.Statut.LIBRE,
                                                                 tarif_nuit__gt=0)
        self.fields["chambre"].label_from_instance = _libelle_chambre

    def clean(self):
        d = super().clean()
        chambre, nuits = d.get("chambre"), d.get("nuits")
        if chambre and nuits:
            try:
                verifier_disponibilite(chambre, aujourd_hui(), aujourd_hui() + timedelta(days=nuits))
            except ValidationError as exc:
                self.add_error("chambre", exc)
        return d


class EncaissementRapideForm(MoyenPaiementForm, Formulaire):
    ordre_champs = ["montant", "moyen"]
    montant = forms.IntegerField(min_value=1)


class PanneForm(Formulaire):
    chambre = forms.ModelChoiceField(label="Chambre", queryset=Chambre.objects.filter(active=True), required=False,
                                     empty_label="— Pas une chambre —")
    lieu = forms.CharField(label="… ou autre endroit", max_length=120, required=False)
    probleme = forms.CharField(label="Quel est le problème ?", max_length=200)
    urgence = forms.ChoiceField(label="Urgence", choices=Intervention.Urgence.choices)
    hors_service = forms.BooleanField(label="La chambre ne peut plus être louée en attendant la réparation",
                                      required=False)


class EvenementForm(Formulaire):
    type = forms.ChoiceField(label="Quoi ?", choices=EvenementSecurite.Type.choices)
    description = forms.CharField(label="Ce qui s'est passé", max_length=300)

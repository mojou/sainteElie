from django import forms

from core.forms import Formulaire, FormulaireModele

from .models import Affectation, Creneau, DemandeConge, Employe


class EmployeForm(FormulaireModele):
    class Meta:
        model = Employe
        fields = ["nom", "prenom", "telephone", "poste", "departement", "date_embauche", "salaire_base", "numero_cnps",
                  "user", "actif"]


class CreneauForm(FormulaireModele):
    class Meta:
        model = Creneau
        fields = ["nom", "heure_debut", "heure_fin", "departement", "actif"]


class AffectationForm(FormulaireModele):
    class Meta:
        model = Affectation
        fields = ["employe", "date", "creneau", "note"]

    def __init__(self, *args, employes=None, **kwargs):
        super().__init__(*args, **kwargs)
        if employes is not None:
            self.fields["employe"].queryset = employes.filter(actif=True)
        self.fields["creneau"].queryset = Creneau.objects.filter(actif=True)


class PointageManuelForm(Formulaire):
    employe = forms.ModelChoiceField(queryset=Employe.objects.none())
    arrivee = forms.DateTimeField(label="Arrivée", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    depart = forms.DateTimeField(label="Départ", required=False,
                                 widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    note = forms.CharField(label="Motif de la saisie manuelle", max_length=200)

    def __init__(self, *args, employes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employe"].queryset = employes.filter(actif=True)

    def clean(self):
        d = super().clean()
        if d.get("arrivee") and d.get("depart") and d["depart"] <= d["arrivee"]:
            self.add_error("depart", "Le départ doit être après l'arrivée.")
        return d


class DemandeCongeForm(FormulaireModele):
    class Meta:
        model = DemandeConge
        fields = ["type", "date_debut", "date_fin", "motif"]

    def clean(self):
        d = super().clean()
        if d.get("date_debut") and d.get("date_fin") and d["date_fin"] < d["date_debut"]:
            self.add_error("date_fin", "La fin doit être après le début.")
        return d


class DemandeEchangeForm(Formulaire):
    affectation = forms.ModelChoiceField(label="Mon shift", queryset=Affectation.objects.none())
    affectation_collegue = forms.ModelChoiceField(label="Shift du collègue", queryset=Affectation.objects.none())
    motif = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, mes_shifts=None, shifts_collegues=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["affectation"].queryset = mes_shifts
        self.fields["affectation_collegue"].queryset = shifts_collegues

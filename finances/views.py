from datetime import date

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from core.forms import FormulaireModele
from core.permissions import acces_requis, gerant
from core.stockage import reponse_fichier
from core.utils import journaliser, mois_suivant, premier_du_mois
from paie.services import libelle_mois

from .models import Depense
from .services import bilan_mois


class DepenseForm(FormulaireModele):
    class Meta:
        model = Depense
        fields = ["date", "categorie", "libelle", "montant", "mode_paiement", "fournisseur", "justificatif"]

    def clean_justificatif(self):
        from core.images import valider_justificatif

        fichier = self.cleaned_data.get("justificatif")
        return valider_justificatif(fichier) if fichier and hasattr(fichier, "content_type") else fichier


def _mois(request):
    try:
        return premier_du_mois(date.fromisoformat(request.GET.get("mois", "") + "-01"))
    except ValueError:
        return premier_du_mois()


def _voisins(mois):
    precedent = date(mois.year - (mois.month == 1), 12 if mois.month == 1 else mois.month - 1, 1)
    return f"{precedent:%Y-%m}", f"{mois_suivant(mois):%Y-%m}"


@acces_requis(gerant)
def depenses(request):
    mois = _mois(request)
    form = DepenseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        depense = form.save(commit=False)
        depense.saisi_par = request.user
        depense.save()
        journaliser(request.user, "Dépense enregistrée", depense)
        messages.success(request, "Dépense enregistrée.")
        return redirect(f"{request.path}?mois={depense.date:%Y-%m}")
    qs = Depense.objects.filter(date__gte=mois, date__lt=mois_suivant(mois)).select_related("saisi_par")
    precedent, suivant = _voisins(mois)
    return render(request, "finances/depenses.html", {
        "form": form, "depenses": qs, "total": qs.aggregate(s=Sum("montant"))["s"] or 0, "libelle": libelle_mois(mois),
        "precedent": precedent, "suivant": suivant})


@acces_requis(gerant)
def justificatif(request, pk):
    return reponse_fichier(get_object_or_404(Depense, pk=pk).justificatif)


@acces_requis(gerant)
def bilan(request):
    mois = _mois(request)
    precedent, suivant = _voisins(mois)
    return render(request, "finances/bilan.html", {**bilan_mois(mois), "libelle": libelle_mois(mois),
                                                   "precedent": precedent, "suivant": suivant})

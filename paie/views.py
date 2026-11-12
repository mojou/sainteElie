from datetime import date

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.forms import Formulaire, FormulaireModele
from core.permissions import acces_requis, gerant
from core.stockage import reponse_fichier
from core.utils import aujourd_hui, journaliser, premier_du_mois

from . import services
from .models import Acompte, FichePaie


class FicheForm(FormulaireModele):
    class Meta:
        model = FichePaie
        fields = ["salaire_base", "primes", "heures_sup", "cotisations", "retenues", "motif_retenues"]


class AcompteForm(FormulaireModele):
    class Meta:
        model = Acompte
        fields = ["employe", "date", "montant", "motif"]


class PaiementForm(Formulaire):
    date = forms.DateField(initial=aujourd_hui)
    mode = forms.ChoiceField(choices=[("Espèces", "Espèces"), ("Mobile money", "Mobile money"),
                                      ("Virement", "Virement"), ("Chèque", "Chèque")])


def _mois(request):
    try:
        return premier_du_mois(date.fromisoformat(request.GET.get("mois", "") + "-01"))
    except ValueError:
        return premier_du_mois()


@acces_requis(gerant)
def fiches(request):
    mois = _mois(request)
    if request.method == "POST":
        n = services.generer_fiches(mois, request.user)
        messages.success(request, f"{n} fiche(s) créée(s) en brouillon.")
        return redirect(f"{request.path}?mois={mois:%Y-%m}")
    qs = FichePaie.objects.filter(mois=mois).select_related("employe")
    for fiche in qs:
        if fiche.statut == FichePaie.Statut.BROUILLON:
            fiche.calculer()
    precedent = date(mois.year - (mois.month == 1), 12 if mois.month == 1 else mois.month - 1, 1)
    suivant = date(mois.year + (mois.month == 12), 1 if mois.month == 12 else mois.month + 1, 1)
    return render(request, "paie/fiches.html", {
        "fiches": qs, "mois": mois, "libelle": services.libelle_mois(mois), "precedent": f"{precedent:%Y-%m}",
        "suivant": f"{suivant:%Y-%m}", "total_net": sum(f.net_a_payer for f in qs),
    })


@acces_requis(gerant)
def fiche_modifier(request, pk):
    fiche = get_object_or_404(FichePaie, pk=pk)
    if fiche.statut != FichePaie.Statut.BROUILLON:
        messages.error(request, "Une fiche validée ne se modifie plus.")
        return redirect(f"/paie/fiches/?mois={fiche.mois:%Y-%m}")
    form = FicheForm(request.POST or None, instance=fiche)
    if request.method == "POST" and form.is_valid():
        fiche = form.save(commit=False)
        fiche.calculer()
        fiche.save()
        messages.success(request, f"Fiche enregistrée : net {fiche.net_a_payer:,} FCFA.".replace(",", " "))
        return redirect(f"/paie/fiches/?mois={fiche.mois:%Y-%m}")
    return render(request, "form_page.html", {
        "form": form, "titre": str(fiche), "retour_url": f"/paie/fiches/?mois={fiche.mois:%Y-%m}",
        "intro": "Les acomptes du mois sont déduits automatiquement. Cotisations CNPS et impôts : "
                 "montants à fixer avec le comptable."})


@require_POST
@acces_requis(gerant)
def fiche_valider(request, pk):
    fiche = get_object_or_404(FichePaie, pk=pk)
    try:
        services.valider_fiche(fiche, request.user)
        messages.success(request, f"Fiche de {fiche.employe} validée ; le bulletin PDF est prêt.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect(f"/paie/fiches/?mois={fiche.mois:%Y-%m}")


@acces_requis(gerant)
def fiche_payer(request, pk):
    fiche = get_object_or_404(FichePaie, pk=pk)
    form = PaiementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.marquer_payee(fiche, request.user, form.cleaned_data["date"], form.cleaned_data["mode"])
            messages.success(request, "Salaire marqué payé.")
            return redirect(f"/paie/fiches/?mois={fiche.mois:%Y-%m}")
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
    return render(request, "form_page.html", {"form": form, "titre": f"Payer : {fiche}", "bouton": "Marquer payé",
                                              "retour_url": f"/paie/fiches/?mois={fiche.mois:%Y-%m}"})


@login_required
def fiche_pdf(request, pk):
    fiche = get_object_or_404(FichePaie, pk=pk)
    proprietaire = request.user.profil_employe and request.user.profil_employe.pk == fiche.employe_id
    if not (request.user.est_gerant or (proprietaire and fiche.statut != FichePaie.Statut.BROUILLON)):
        raise PermissionDenied
    return reponse_fichier(fiche.pdf)


@login_required
def mes_bulletins(request):
    employe = request.user.profil_employe
    if employe is None:
        raise PermissionDenied
    return render(request, "paie/mes_bulletins.html", {
        "fiches": FichePaie.objects.filter(employe=employe).exclude(statut=FichePaie.Statut.BROUILLON),
        "acomptes": Acompte.objects.filter(employe=employe)[:24]})


@acces_requis(gerant)
def acomptes(request):
    form = AcompteForm(request.POST or None, initial={"date": aujourd_hui()})
    if request.method == "POST" and form.is_valid():
        acompte = form.save(commit=False)
        acompte.saisi_par = request.user
        deja_valide = FichePaie.objects.filter(employe=acompte.employe, mois=premier_du_mois(acompte.date)).exclude(
            statut=FichePaie.Statut.BROUILLON).exists()
        if deja_valide:
            form.add_error("date", "La fiche de paie de ce mois est déjà validée : datez l'acompte du mois suivant.")
        else:
            acompte.save()
            journaliser(request.user, "Acompte sur salaire", acompte.employe, f"{acompte.montant}")
            messages.success(request, "Acompte enregistré ; il sera déduit de la fiche du mois.")
            return redirect("paie:acomptes")
    qs = Acompte.objects.select_related("employe", "saisi_par")
    return render(request, "paie/acomptes.html", {"form": form, "acomptes": qs[:100],
                                                  "total_mois": qs.filter(date__gte=premier_du_mois()).aggregate(
                                                      s=Sum("montant"))["s"] or 0})

"""Projets internes en cartes, tâches en colonnes (à faire, en cours, bloquée, faite) qu'on fait glisser."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.forms import FormulaireModele
from core.permissions import acces_requis, encadrement
from core.utils import journaliser

from .models import CommentaireTache, Projet, Tache

COLONNES = [{"statut": v, "libelle": l} for v, l in Tache.Statut.choices]


class ProjetForm(FormulaireModele):
    class Meta:
        model = Projet
        fields = ["nom", "description", "responsable", "date_debut", "echeance", "budget", "statut"]


class TacheForm(FormulaireModele):
    class Meta:
        model = Tache
        fields = ["titre", "description", "assigne_a", "echeance", "priorite", "statut"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].widget.attrs["rows"] = 4
        self.fields["assigne_a"].empty_label = "— Personne —"


def _peut_voir(user, tache):
    return encadrement(user) or tache.assigne_a_id == user.pk


def _changer_statut(tache, user, statut):
    if statut not in Tache.Statut.values or statut == tache.statut:
        return False
    avant = tache.get_statut_display()
    tache.statut = statut
    tache.save(update_fields=["statut"])
    CommentaireTache.objects.create(tache=tache, auteur=user, systeme=True,
                                    texte=f"Étape : {avant} → {tache.get_statut_display()}")
    return True


def _colonnes(taches):
    taches = sorted(taches, key=lambda t: (t.priorite != Tache.Priorite.HAUTE, t.echeance is None, t.echeance or 0))
    return [{**c, "taches": [t for t in taches if t.statut == c["statut"]]} for c in COLONNES]


@acces_requis(encadrement)
def liste(request):
    filtre = request.GET.get("voir", "actifs")
    projets = Projet.objects.select_related("responsable").annotate(
        nb=Count("taches"), faites=Count("taches", filter=Q(taches__statut=Tache.Statut.FAITE)),
        bloquees=Count("taches", filter=Q(taches__statut=Tache.Statut.BLOQUEE)),
        en_cours=Count("taches", filter=Q(taches__statut=Tache.Statut.EN_COURS)))
    if filtre == "actifs":
        projets = projets.exclude(statut=Projet.Statut.TERMINE)
    elif filtre == "termines":
        projets = projets.filter(statut=Projet.Statut.TERMINE)
    return render(request, "projets/liste.html", {"projets": projets, "filtre": filtre})


@acces_requis(encadrement)
def projet_form(request, pk=None):
    projet = get_object_or_404(Projet, pk=pk) if pk else None
    form = ProjetForm(request.POST or None, instance=projet, initial={"responsable": request.user} if not projet else None)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        journaliser(request.user, "Projet modifié" if projet else "Projet créé", obj)
        messages.success(request, "Projet enregistré.")
        return redirect("projets:projet", pk=obj.pk)
    return render(request, "form_page.html", {"form": form, "titre": f"Modifier {projet}" if projet else "Nouveau projet",
                                              "retour": "projets:liste"})


@acces_requis(encadrement)
def projet_detail(request, pk):
    projet = get_object_or_404(Projet, pk=pk)
    if request.method == "POST":
        titre = request.POST.get("titre", "").strip()
        statut = request.POST.get("statut") if request.POST.get("statut") in Tache.Statut.values else Tache.Statut.A_FAIRE
        if titre:
            tache = Tache.objects.create(projet=projet, titre=titre[:200], statut=statut)
            CommentaireTache.objects.create(tache=tache, auteur=request.user, systeme=True, texte="Tâche créée")
            messages.success(request, f"Tâche « {tache} » ajoutée. Touchez-la pour l'assigner et lui donner une échéance.")
        return redirect("projets:projet", pk=projet.pk)
    taches = list(projet.taches.select_related("assigne_a").annotate(nb_commentaires=Count(
        "commentaires", filter=Q(commentaires__systeme=False))))
    return render(request, "projets/projet.html", {
        "projet": projet, "colonnes": _colonnes(taches), "nb": len(taches),
        "faites": sum(1 for t in taches if t.statut == Tache.Statut.FAITE)})


@login_required
def tache_detail(request, pk):
    tache = get_object_or_404(Tache.objects.select_related("projet", "assigne_a"), pk=pk)
    if not _peut_voir(request.user, tache):
        raise PermissionDenied
    peut_modifier = encadrement(request.user)
    form = TacheForm(request.POST if request.POST.get("action") == "modifier" else None, instance=tache) \
        if peut_modifier else None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "commenter" and request.POST.get("texte", "").strip():
            CommentaireTache.objects.create(tache=tache, auteur=request.user, texte=request.POST["texte"].strip()[:2000])
            return redirect(f"{reverse('projets:tache', args=[tache.pk])}#discussion")
        if action == "etape":
            _changer_statut(tache, request.user, request.POST.get("statut"))
            return redirect("projets:tache", pk=tache.pk)
        if action == "modifier" and form is not None:
            ancien = Tache.objects.get(pk=tache.pk)
            if form.is_valid():
                nouvelle = form.save(commit=False)
                statut = nouvelle.statut
                nouvelle.statut = ancien.statut
                nouvelle.save()
                _changer_statut(nouvelle, request.user, statut)
                if ancien.assigne_a_id != nouvelle.assigne_a_id and nouvelle.assigne_a_id:
                    CommentaireTache.objects.create(tache=nouvelle, auteur=request.user, systeme=True,
                                                    texte=f"Confiée à {nouvelle.assigne_a}")
                messages.success(request, "Tâche enregistrée.")
                return redirect("projets:tache", pk=tache.pk)
    return render(request, "projets/tache.html", {
        "tache": tache, "form": form, "colonnes": COLONNES,
        "commentaires": tache.commentaires.select_related("auteur")})


@login_required
def mes_taches(request):
    taches = list(Tache.objects.filter(assigne_a=request.user).select_related("projet", "assigne_a").annotate(
        nb_commentaires=Count("commentaires", filter=Q(commentaires__systeme=False))))
    return render(request, "projets/mes_taches.html", {"colonnes": _colonnes(taches), "nb": len(taches)})


@require_POST
@login_required
def tache_statut(request, pk):
    """Changer d'étape : par le menu de la tâche, ou en la faisant glisser dans une autre colonne."""
    tache = get_object_or_404(Tache, pk=pk)
    if not _peut_voir(request.user, tache):
        raise PermissionDenied
    change = _changer_statut(tache, request.user, request.POST.get("statut"))
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True, "statut": tache.statut, "change": change})
    if change:
        messages.success(request, f"« {tache} » : {tache.get_statut_display().lower()}.")
    retour = request.POST.get("retour", "")
    if not url_has_allowed_host_and_scheme(retour, allowed_hosts={request.get_host()}):
        retour = reverse("projets:mes_taches")
    return redirect(retour)


@require_POST
@acces_requis(encadrement)
def tache_priorite(request, pk):
    """L'étoile : tâche prioritaire ou non."""
    tache = get_object_or_404(Tache, pk=pk)
    tache.priorite = Tache.Priorite.NORMALE if tache.priorite == Tache.Priorite.HAUTE else Tache.Priorite.HAUTE
    tache.save(update_fields=["priorite"])
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True, "haute": tache.priorite == Tache.Priorite.HAUTE})
    return redirect("projets:projet", pk=tache.projet_id)

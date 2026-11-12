from collections import defaultdict
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import acces_requis, encadrement, gerant
from core.utils import aujourd_hui, journaliser, mois_suivant

from . import services
from .forms import CreneauForm, DemandeCongeForm, DemandeEchangeForm, EmployeForm, PointageManuelForm
from .models import Affectation, Creneau, Departement, DemandeConge, DemandeEchange, Employe, Pointage, Statut


def _mon_employe(request):
    employe = request.user.profil_employe
    if employe is None:
        messages.error(request, "Votre compte n'est relié à aucune fiche employé : demandez au gérant de le faire.")
    return employe


@login_required
def mon_espace(request):
    employe = _mon_employe(request)
    if employe is None:
        return redirect("core:accueil")
    if request.method == "POST":
        try:
            if request.POST.get("action") == "arrivee":
                p = services.pointer_arrivee(employe, request.user)
                messages.success(request, f"Arrivée pointée à {timezone.localtime(p.arrivee):%H:%M}"
                                 + (f" ({p.retard_minutes} min de retard)." if p.retard_minutes else "."))
            else:
                p = services.pointer_depart(employe, request.user)
                messages.success(request, f"Départ pointé à {timezone.localtime(p.depart):%H:%M}.")
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
        return redirect("personnel:mon_espace")
    jour = aujourd_hui()
    return render(request, "personnel/mon_espace.html", {
        "employe": employe,
        "planning": Affectation.objects.filter(employe=employe, date__gte=jour, date__lte=jour + timedelta(days=13))
        .select_related("creneau"),
        "pointage_ouvert": Pointage.objects.filter(employe=employe, depart__isnull=True).first(),
        "pointages": Pointage.objects.filter(employe=employe)[:15],
    })


def _lundi(jour):
    return jour - timedelta(days=jour.weekday())


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
        "décembre"]


def _periode_planning(request):
    vue = "mois" if request.GET.get("vue") == "mois" else "semaine"
    try:
        repere = date.fromisoformat(request.GET.get("date") or request.GET.get("semaine") or "")
    except ValueError:
        repere = aujourd_hui()
    if vue == "mois":
        debut = repere.replace(day=1)
        fin = mois_suivant(debut) - timedelta(days=1)
        return vue, debut, fin, (debut - timedelta(days=1)).replace(day=1), mois_suivant(debut), \
            f"{MOIS[debut.month - 1].capitalize()} {debut.year}"
    debut = _lundi(repere)
    fin = debut + timedelta(days=6)
    titre = (f"Semaine du {debut.day} {MOIS[debut.month - 1] if debut.month != fin.month else ''} au "
             f"{fin.day} {MOIS[fin.month - 1]} {fin.year}").replace("  ", " ")
    return vue, debut, fin, debut - timedelta(days=7), debut + timedelta(days=7), titre


@acces_requis(encadrement)
def planning(request):
    """Le planning, comme un tableau de bord : une ligne par personne, une colonne par jour, chaque créneau en couleur.

    On touche une case pour ajouter un créneau, un créneau pour le changer ou le retirer ; à la souris, on le glisse
    vers un autre jour ou une autre personne. Les congés accordés apparaissent ; un créneau impossible est refusé.
    """
    vue, debut, fin, precedent, suivant, titre = _periode_planning(request)
    geres = services.employes_geres(request.user).filter(actif=True)
    departement = request.GET.get("dep", "")
    employes = geres.filter(departement=departement) if departement in Departement.values else geres
    retour = f"{request.path}?vue={vue}&date={debut.isoformat()}&dep={departement}"
    if request.method == "POST":
        action = request.POST.get("action")

        def numero(champ, defaut=None, message="Choisissez le créneau à changer."):
            valeur = request.POST.get(champ, "")
            if valeur.isdigit():
                return int(valeur)
            if defaut is not None:
                return defaut
            raise ValidationError(message)

        try:
            if action in ("ajouter", "modifier", "deplacer"):
                affectation = (get_object_or_404(Affectation, pk=numero("pk"), employe__in=geres)
                               if action != "ajouter" else None)
                employe = get_object_or_404(geres, pk=numero("employe", affectation and affectation.employe_id,
                                                             "Choisissez la personne."))
                try:
                    jour = date.fromisoformat(request.POST.get("date", ""))
                except ValueError:
                    raise ValidationError("Choisissez le jour.")
                creneau = get_object_or_404(Creneau, actif=True, pk=numero(
                    "creneau", affectation and affectation.creneau_id, "Choisissez le créneau horaire."))
                note = request.POST.get("note", affectation.note if affectation else "").strip()
                a = services.planifier(request.user, employe, jour, creneau, note, affectation=affectation)
                messages.success(request, f"{a.employe} : {a.creneau.nom} le {a.date:%d/%m}.")
            elif action == "supprimer":
                affectation = get_object_or_404(Affectation, pk=numero("pk"), employe__in=geres)
                journaliser(request.user, "Shift retiré du planning", affectation)
                affectation.delete()
                messages.success(request, "Créneau retiré du planning.")
            elif action == "copier":
                copies, sautes = services.copier_semaine(request.user, employes, _lundi(debut))
                messages.success(request, f"{copies} créneau(x) recopié(s) depuis la semaine précédente."
                                 + (f" {sautes} sauté(s) : congé ou déjà planifié." if sautes else ""))
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
        return redirect(retour)

    jours = [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]
    creneaux = list(Creneau.objects.filter(actif=True))
    couleur = {c.pk: i % 6 for i, c in enumerate(creneaux)}
    for c in creneaux:
        c.couleur = couleur[c.pk]
    par_case = defaultdict(list)
    for a in (Affectation.objects.filter(employe__in=employes, date__gte=debut, date__lte=fin)
              .select_related("creneau").order_by("creneau__heure_debut")):
        a.couleur = couleur.get(a.creneau_id, 0)
        par_case[(a.employe_id, a.date)].append(a)
    conges = list(DemandeConge.objects.filter(statut=Statut.ACCEPTEE, employe__in=employes, date_debut__lte=fin,
                                              date_fin__gte=debut))
    aujourdhui = aujourd_hui()
    groupes = []
    for dep, libelle in Departement.choices:
        lignes = []
        for employe in [e for e in employes if e.departement == dep]:
            cases = []
            for jour in jours:
                conge = next((c for c in conges if c.employe_id == employe.pk and c.date_debut <= jour <= c.date_fin),
                             None)
                cases.append({"jour": jour, "shifts": par_case.get((employe.pk, jour), []), "conge": conge,
                              "weekend": jour.weekday() >= 5, "aujourdhui": jour == aujourdhui})
            heures = sum(a.creneau.heures for c in cases for a in c["shifts"])
            lignes.append({"employe": employe, "cases": cases, "heures": heures})
        if lignes:
            groupes.append({"nom": libelle, "lignes": lignes, "heures": sum(l["heures"] for l in lignes)})
    couverture = [{"jour": jour, "aujourdhui": jour == aujourdhui, "weekend": jour.weekday() >= 5,
                   "creneaux": [{"creneau": c, "n": sum(1 for (e, j), liste in par_case.items() if j == jour
                                                         for a in liste if a.creneau_id == c.pk)} for c in creneaux]}
                  for jour in jours]
    return render(request, "personnel/planning.html", {
        "vue": vue, "titre": titre, "debut": debut, "jours": jours, "groupes": groupes, "creneaux": creneaux,
        "couverture": couverture, "precedent": precedent.isoformat(), "suivant": suivant.isoformat(),
        "aujourdhui": aujourdhui.isoformat(), "departement": departement, "employes": employes,
        "departements": [(v, l) for v, l in Departement.choices if geres.filter(departement=v).exists()],
        "total_heures": sum(g["heures"] for g in groupes),
    })


@acces_requis(encadrement)
def pointages(request):
    employes = services.employes_geres(request.user)
    try:
        jour = date.fromisoformat(request.GET.get("jour", ""))
    except ValueError:
        jour = aujourd_hui()
    form = PointageManuelForm(request.POST or None, employes=employes)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        Pointage.objects.create(employe=d["employe"], date=timezone.localtime(d["arrivee"]).date(), arrivee=d["arrivee"],
                                depart=d.get("depart"), saisi_par=request.user, note=d["note"])
        journaliser(request.user, "Pointage saisi à la main", d["employe"], d["note"])
        messages.success(request, "Pointage enregistré.")
        return redirect(f"{request.path}?jour={jour.isoformat()}")
    prevus = Affectation.objects.filter(employe__in=employes, date=jour).select_related("employe", "creneau")
    faits = Pointage.objects.filter(employe__in=employes, date=jour).select_related("employe", "saisi_par")
    pointes = {p.employe_id for p in faits}
    return render(request, "personnel/pointages.html", {
        "jour": jour, "prevus": prevus, "faits": faits, "absents": [a for a in prevus if a.employe_id not in pointes],
        "form": form, "veille": (jour - timedelta(days=1)).isoformat(), "lendemain": (jour + timedelta(days=1)).isoformat(),
    })


@acces_requis(encadrement)
def employes(request):
    return render(request, "personnel/employes.html", {"employes": services.employes_geres(request.user)
                                                       .select_related("user")})


@acces_requis(gerant)
def employe_form(request, pk=None):
    employe = get_object_or_404(Employe, pk=pk) if pk else None
    form = EmployeForm(request.POST or None, instance=employe)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        journaliser(request.user, "Fiche employé modifiée" if employe else "Employé créé", obj)
        messages.success(request, f"Fiche de {obj} enregistrée.")
        return redirect("personnel:employes")
    return render(request, "form_page.html", {"form": form, "titre": f"Modifier {employe}" if employe else "Nouvel employé",
                                              "retour": "personnel:employes"})


@acces_requis(gerant)
def creneaux(request):
    return render(request, "personnel/creneaux.html", {"creneaux": Creneau.objects.all()})


@acces_requis(gerant)
def creneau_form(request, pk=None):
    creneau = get_object_or_404(Creneau, pk=pk) if pk else None
    form = CreneauForm(request.POST or None, instance=creneau)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Créneau enregistré.")
        return redirect("personnel:creneaux")
    return render(request, "form_page.html", {"form": form, "titre": "Créneau horaire", "retour": "personnel:creneaux",
                                              "intro": "Un créneau qui finit avant son début passe minuit (ex. nuit 23:00 - 07:00)."})


@login_required
def conges(request):
    employe = request.user.profil_employe
    geres = services.employes_geres(request.user)
    a_traiter = DemandeConge.objects.filter(statut=Statut.EN_ATTENTE, employe__in=geres)
    echanges_a_traiter = DemandeEchange.objects.filter(statut=Statut.EN_ATTENTE,
                                                       affectation__employe__in=geres).select_related(
        "affectation__employe", "affectation__creneau", "affectation_collegue__employe", "affectation_collegue__creneau")
    if employe:
        a_traiter = a_traiter.exclude(employe=employe)
    return render(request, "personnel/conges.html", {
        "mes_demandes": DemandeConge.objects.filter(employe=employe) if employe else [],
        "mes_echanges": DemandeEchange.objects.filter(demandeur=request.user).select_related(
            "affectation__creneau", "affectation_collegue__employe", "affectation_collegue__creneau"),
        "a_traiter": a_traiter.select_related("employe"), "echanges_a_traiter": echanges_a_traiter,
        "employe": employe,
    })


@login_required
def conge_nouveau(request):
    employe = _mon_employe(request)
    if employe is None:
        return redirect("personnel:conges")
    form = DemandeCongeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        demande = form.save(commit=False)
        demande.employe = employe
        demande.save()
        messages.success(request, "Demande envoyée à votre responsable.")
        return redirect("personnel:conges")
    return render(request, "form_page.html", {"form": form, "titre": "Demander un congé", "retour": "personnel:conges"})


@require_POST
@login_required
def conge_traiter(request, pk):
    demande = get_object_or_404(DemandeConge, pk=pk)
    try:
        services.traiter_conge(demande, request.user, request.POST.get("decision") == "accepter",
                               request.POST.get("commentaire", ""))
        messages.success(request, "Demande traitée.")
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect("personnel:conges")


@login_required
def echange_nouveau(request):
    employe = _mon_employe(request)
    if employe is None:
        return redirect("personnel:conges")
    jour = aujourd_hui()
    mes_shifts = Affectation.objects.filter(employe=employe, date__gte=jour).select_related("creneau")
    collegues = Affectation.objects.filter(employe__departement=employe.departement, date__gte=jour).exclude(
        employe=employe).select_related("creneau", "employe")
    form = DemandeEchangeForm(request.POST or None, mes_shifts=mes_shifts, shifts_collegues=collegues)
    if request.method == "POST" and form.is_valid():
        try:
            services.demander_echange(request.user, form.cleaned_data["affectation"],
                                      form.cleaned_data["affectation_collegue"], form.cleaned_data["motif"])
            messages.success(request, "Demande d'échange envoyée au chef.")
            return redirect("personnel:conges")
        except ValidationError as exc:
            for msg in exc.messages:
                form.add_error(None, msg)
    return render(request, "form_page.html", {"form": form, "titre": "Échanger un shift", "retour": "personnel:conges"})


@require_POST
@login_required
def echange_traiter(request, pk):
    demande = get_object_or_404(DemandeEchange, pk=pk)
    try:
        services.traiter_echange(demande, request.user, request.POST.get("decision") == "accepter")
        messages.success(request, "Demande d'échange traitée.")
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect("personnel:conges")

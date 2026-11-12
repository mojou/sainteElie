"""
Saisie du jour, une page par département : c'est l'écran qui reste ouvert sur le poste toute la journée.
"""
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from caisse import services as caisse
from caisse.models import Encaissement
from core.permissions import acces_requis, encadrement, reception
from core.utils import aujourd_hui, journaliser
from hotel import services as hotel
from hotel.models import Chambre, Client, Sejour
from personnel.models import Departement

from . import services
from .forms import ArriveeForm, EncaissementRapideForm, EvenementForm, PanneForm
from .models import EvenementSecurite, Intervention


def _erreurs(request, exc):
    for msg in exc.messages:
        messages.error(request, msg)


def maintenance_ou_chef(u):
    return u.departement == Departement.MAINTENANCE or encadrement(u)


def signale_les_pannes(u):
    """Les problèmes des chambres sont signalés par la réception (et le gérant), personne d'autre."""
    return reception(u)


def voit_les_pannes(u):
    """La maintenance et les chefs voient la liste pour réparer ; seule la réception signale."""
    return signale_les_pannes(u) or maintenance_ou_chef(u)


def securite_ou_chef(u):
    """Main courante du gardien : le gardien n'a pas de compte, la réception note ce qu'il lui signale."""
    return u.departement == Departement.SECURITE or reception(u) or encadrement(u)


@login_required
def poste(request):
    """Envoie chacun sur la saisie de son département."""
    u = request.user
    if u.est_reception:
        return redirect("postes:reception")
    if u.est_bar:
        return redirect("caisse:ventes")
    if u.departement == Departement.MAINTENANCE:
        return redirect("postes:maintenance")
    if u.departement == Departement.SECURITE:
        return redirect("postes:securite")
    if u.departement == Departement.MENAGE:
        return redirect("hotel:menage")
    if u.est_terrain:
        # Jardinage et autres services sans caisse ni saisie : planning, pointage et congés.
        return redirect("personnel:mon_espace" if u.profil_employe else "accounts:mon_compte")
    return redirect("postes:tous")


@acces_requis(encadrement)
def tous(request):
    return render(request, "postes/tous.html", {})


# --- Réception : chambres -------------------------------------------------------------------
@acces_requis(reception)
def reception_vue(request):
    """Le plan des chambres : l'écran d'accueil de la réception. On touche une chambre pour agir."""
    session = caisse.session_ouverte_de(request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "menage":
                # Le ménage n'a pas de compte : il dit à la réception que la chambre est faite.
                chambre = get_object_or_404(Chambre, pk=request.POST.get("chambre"))
                hotel.marquer_nettoyee(chambre, request.user)
                messages.success(request, f"Chambre {chambre.numero} faite : elle est de nouveau libre.")
                return redirect("postes:reception")
            elif action in ("encaisser", "checkin", "depart"):
                sejour = get_object_or_404(Sejour, pk=request.POST.get("sejour"))
                if action == "encaisser":
                    _encaisser(request, session, sejour)
                elif action == "checkin":
                    hotel.check_in(sejour, request.user)
                    messages.success(request, f"{sejour.client} est installé en chambre {sejour.chambre.numero}.")
                else:
                    hotel.check_out(sejour, request.user)
                    sejour.refresh_from_db()
                    if sejour.reste_a_payer > 0:
                        messages.warning(request, f"Départ noté. {sejour.client} doit encore "
                                                  f"{sejour.reste_a_payer:,} FCFA.".replace(",", " "))
                    else:
                        messages.success(request, f"Départ noté : chambre {sejour.chambre.numero} à nettoyer.")
                return redirect("postes:reception")
        except ValidationError as exc:
            _erreurs(request, exc)
    jour = aujourd_hui()
    chambres = list(Chambre.objects.filter(active=True).order_by("numero"))
    en_cours = {s.chambre_id: s for s in Sejour.objects.filter(statut=Sejour.Statut.EN_COURS).select_related("client")}
    attendus = list(Sejour.objects.filter(statut=Sejour.Statut.RESERVE, date_arrivee__lte=jour)
                    .select_related("chambre", "client").order_by("chambre__numero"))
    attendu_par_chambre = {s.chambre_id: s for s in attendus}
    groupes, nombres = {}, {statut: 0 for statut, _ in Chambre.Statut.choices}
    for c in chambres:
        c.sejour = en_cours.get(c.pk)
        c.attendu = attendu_par_chambre.get(c.pk)
        nombres[c.statut] += 1
        groupes.setdefault(c.numero[:1], []).append(c)
    return render(request, "postes/reception.html", {
        "session": session, "jour": jour, "attendus": attendus, "nombres": nombres,
        "groupes": [{"titre": f"Chambres {liste[0].numero} à {liste[-1].numero}" if len(liste) > 1
                     else f"Chambre {liste[0].numero}", "chambres": liste} for liste in groupes.values()],
        "dernier_recu": Encaissement.objects.filter(pk=request.session.get("dernier_recu")).first(),
        "a_nettoyer": [c for c in chambres if c.statut == Chambre.Statut.A_NETTOYER],
    })


@acces_requis(reception)
def chambre_vue(request, pk):
    """Une chambre : seulement ce qu'on peut y faire maintenant (encaisser, départ, ménage, arrivée…)."""
    chambre = get_object_or_404(Chambre, pk=pk, active=True)
    jour = aujourd_hui()
    sejour = Sejour.objects.filter(chambre=chambre, statut=Sejour.Statut.EN_COURS).select_related("client").first()
    attendu = (Sejour.objects.filter(chambre=chambre, statut=Sejour.Statut.RESERVE, date_arrivee__lte=jour)
               .select_related("client").first())
    form = None
    if sejour:
        form = EncaissementRapideForm(prefix=f"s{sejour.pk}",
                                      initial={"montant": max(sejour.reste_a_payer, 0) or None, "moyen": "ESPECES"})
    return render(request, "postes/chambre.html", {
        "chambre": chambre, "sejour": sejour, "attendu": attendu, "form": form, "jour": jour,
        "session": caisse.session_ouverte_de(request.user),
        "pannes": Intervention.objects.filter(chambre=chambre).exclude(statut=Intervention.Statut.FAITE),
    })


@acces_requis(reception)
def arrivee(request):
    """Un client arrive sans réservation, une question par écran : qui, combien de nuits, combien il paie, vérifier."""
    session = caisse.session_ouverte_de(request.user)
    id_chambre = request.POST.get("chambre") or request.GET.get("chambre") or ""
    form = ArriveeForm(request.POST or None, initial={"nuits": 1, "moyen": "ESPECES", "chambre": id_chambre or None})
    libres = form.fields["chambre"].queryset
    chambre_fixe = libres.filter(pk=id_chambre).first() if id_chambre.isdigit() else None
    if id_chambre and chambre_fixe is None and request.method == "GET":
        messages.error(request, "Cette chambre n'est pas libre : choisissez-en une autre sur le plan.")
        return redirect("postes:reception")
    if request.method == "POST" and form.is_valid():
        try:
            _enregistrer_arrivee(request, session, form.cleaned_data)
            return redirect("postes:reception")
        except ValidationError as exc:
            for msg in exc.messages:
                form.add_error(None, msg)
    return render(request, "postes/arrivee.html", {
        "form": form, "session": session, "chambre_fixe": chambre_fixe, "jour": aujourd_hui(),
        "tarifs": {str(c.pk): c.tarif_nuit for c in libres}, "nuits_rapides": [1, 2, 3, 4, 5, 7],
    })


def _enregistrer_arrivee(request, session, d):
    if d.get("montant") and session is None:
        raise ValidationError("Ouvrez d'abord votre caisse (bouton en haut) pour encaisser ce paiement.")
    jour = aujourd_hui()
    with transaction.atomic():
        client = Client.objects.filter(telephone=d["telephone"].strip()).first() or Client.objects.create(
            nom=d["nom"].strip(), telephone=d["telephone"].strip())
        chambre = d["chambre"]
        sejour = Sejour.objects.create(client=client, chambre=chambre, date_arrivee=jour,
                                       date_depart=jour + timedelta(days=d["nuits"]), tarif_grille=chambre.tarif_nuit,
                                       tarif_nuit=chambre.tarif_nuit, cree_par=request.user)
        hotel.check_in(sejour, request.user)
        if d.get("montant"):
            enc = caisse.encaisser(session, request.user, sejour, "ACOMPTE", d["mode"], d["montant"])
            request.session["dernier_recu"] = enc.pk
    journaliser(request.user, "Arrivée sans réservation", sejour)
    messages.success(request, f"{client} est installé en chambre {chambre.numero} pour {d['nuits']} nuit(s)."
                     + (f" Reçu n°{enc.numero_recu}." if d.get("montant") else " Rien n'a encore été payé."))


def _encaisser(request, session, sejour):
    if session is None:
        raise ValidationError("Ouvrez d'abord votre caisse (bouton en haut) pour encaisser.")
    form = EncaissementRapideForm(request.POST, prefix=f"s{sejour.pk}")
    if not form.is_valid():
        raise ValidationError("Indiquez le montant reçu.")
    d = form.cleaned_data
    enc = caisse.encaisser(session, request.user, sejour, "REGLEMENT", d["mode"], d["montant"])
    request.session["dernier_recu"] = enc.pk
    messages.success(request, f"Reçu n°{enc.numero_recu} : {enc.montant:,} FCFA de {sejour.client} "
                              f"(chambre {sejour.chambre.numero}).".replace(",", " "))


# --- Maintenance ------------------------------------------------------------------------------
@acces_requis(voit_les_pannes)
def maintenance(request):
    peut_signaler = signale_les_pannes(request.user)
    chambre = request.GET.get("chambre", "")
    form = (PanneForm(request.POST if request.POST.get("action") == "signaler" else None,
                      initial={"chambre": chambre if chambre.isdigit() else None}) if peut_signaler else None)
    peut_traiter = maintenance_ou_chef(request.user)
    if request.method == "POST":
        try:
            if request.POST.get("action") == "signaler" and form is not None:
                if form.is_valid():
                    d = form.cleaned_data
                    services.signaler_panne(request.user, d["probleme"], d.get("chambre"), d.get("lieu", ""),
                                            d["urgence"], d.get("hors_service"))
                    messages.success(request, "Panne signalée à la maintenance. Merci !")
                    return redirect("postes:maintenance")
            elif peut_traiter:
                panne = get_object_or_404(Intervention, pk=request.POST.get("panne"))
                statut = Intervention.Statut.FAITE if request.POST.get("action") == "repare" \
                    else Intervention.Statut.EN_COURS
                services.avancer_panne(panne, request.user, statut, request.POST.get("commentaire", ""))
                messages.success(request, "C'est noté.")
                return redirect("postes:maintenance")
        except ValidationError as exc:
            _erreurs(request, exc)
    return render(request, "postes/maintenance.html", {
        "form": form, "peut_traiter": peut_traiter,
        "a_faire": Intervention.objects.exclude(statut=Intervention.Statut.FAITE).select_related(
            "chambre", "signale_par"),
        "reparees": Intervention.objects.filter(statut=Intervention.Statut.FAITE).select_related(
            "chambre", "traite_par")[:15],
    })


# --- Sécurité ---------------------------------------------------------------------------------
@acces_requis(securite_ou_chef)
def securite(request):
    form = EvenementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.noter_evenement(request.user, form.cleaned_data["type"], form.cleaned_data["description"])
            messages.success(request, "C'est noté dans la main courante.")
            return redirect("postes:securite")
        except ValidationError as exc:
            _erreurs(request, exc)
    debut = timezone.make_aware(datetime.combine(aujourd_hui(), datetime.min.time()))
    return render(request, "postes/securite.html", {
        "form": form, "du_jour": EvenementSecurite.objects.filter(date__gte=debut).select_related("saisi_par"),
        "veille": EvenementSecurite.objects.filter(date__gte=debut - timedelta(days=1), date__lt=debut).select_related(
            "saisi_par"),
    })


@require_POST
@login_required
def oublier_recu(request):
    request.session.pop("dernier_recu", None)
    return redirect("postes:reception")

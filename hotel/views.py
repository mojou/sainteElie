from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from caisse import services as caisse_services
from caisse.models import Encaissement
from core.forms import MotifForm
from core.permissions import acces_requis, extras, gerant, menage, reception
from core.utils import aujourd_hui, format_fcfa, journaliser

from . import services
from .forms import ChambreForm, ClientForm, EncaissementForm, ExtraForm, SejourForm
from .models import Chambre, Client, Extra, Nettoyage, Sejour


def _erreurs(request, exc):
    for msg in exc.messages:
        messages.error(request, msg)


# --- Séjours ------------------------------------------------------------------------
@acces_requis(reception)
def sejours(request):
    vue = request.GET.get("vue", "jour")
    q = request.GET.get("q", "").strip()
    jour = aujourd_hui()
    qs = Sejour.objects.select_related("client", "chambre")
    blocs = []
    if q:
        qs = qs.filter(Q(client__nom__icontains=q) | Q(client__telephone__icontains=q) | Q(chambre__numero=q))
        blocs.append(("Résultats", qs[:100]))
    elif vue == "jour":
        blocs = [
            ("Arrivées du jour", qs.filter(statut=Sejour.Statut.RESERVE, date_arrivee__lte=jour)),
            ("Départs du jour", qs.filter(statut=Sejour.Statut.EN_COURS, date_depart=jour)),
            ("Départs en retard", qs.filter(statut=Sejour.Statut.EN_COURS, date_depart__lt=jour)),
            ("Séjours en cours", qs.filter(statut=Sejour.Statut.EN_COURS, date_depart__gt=jour)),
        ]
    elif vue == "reserves":
        blocs.append(("Réservations à venir", qs.filter(statut=Sejour.Statut.RESERVE).order_by("date_arrivee")))
    elif vue == "impayes":
        impayes = [s for s in qs.filter(statut=Sejour.Statut.TERMINE).order_by("-check_out_le")[:500]
                   if s.reste_a_payer > 0]
        blocs.append(("Séjours terminés non soldés", impayes))
    else:
        blocs.append(("Tous les séjours (200 derniers)", qs[:200]))
    return render(request, "hotel/sejours.html", {"blocs": blocs, "vue": vue, "q": q})


@acces_requis(reception)
def sejour_form(request, pk=None):
    sejour = get_object_or_404(Sejour, pk=pk) if pk else None
    if sejour and sejour.statut not in Sejour.ACTIFS:
        messages.error(request, "Un séjour terminé ou annulé ne se modifie plus.")
        return redirect("hotel:sejour", pk=sejour.pk)
    ancienne_chambre = sejour.chambre if sejour else None
    form = SejourForm(request.POST or None, instance=sejour, user=request.user,
                      initial={"date_arrivee": aujourd_hui(), "date_depart": aujourd_hui() + timedelta(days=1)}
                      if not sejour else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            if not obj.client_id:
                obj.client = Client.objects.create(nom=form.cleaned_data["nouveau_client_nom"],
                                                   telephone=form.cleaned_data["nouveau_client_telephone"])
            obj.tarif_grille = obj.chambre.tarif_nuit
            obj.tarif_valide_par = form.cleaned_data.get("_valideur")
            if not obj.pk:
                obj.cree_par = request.user
            obj.save()
            if sejour and obj.statut == Sejour.Statut.EN_COURS and ancienne_chambre.pk != obj.chambre_id:
                ancienne_chambre.statut = Chambre.Statut.A_NETTOYER
                ancienne_chambre.save(update_fields=["statut"])
                obj.chambre.statut = Chambre.Statut.OCCUPEE
                obj.chambre.save(update_fields=["statut"])
        journaliser(request.user, "Séjour modifié" if sejour else "Réservation créée", obj,
                    f"tarif {obj.tarif_nuit} (grille {obj.tarif_grille})")
        messages.success(request, "Séjour enregistré.")
        return redirect("hotel:sejour", pk=obj.pk)
    return render(request, "hotel/sejour_form.html", {"form": form, "sejour": sejour})


@acces_requis(reception)
def sejour_detail(request, pk):
    sejour = get_object_or_404(Sejour.objects.select_related("client", "chambre"), pk=pk)
    return render(request, "hotel/sejour_detail.html", {
        "sejour": sejour,
        "nuitees": sejour.nuitees.all(),
        "extras": sejour.extras.select_related("saisi_par"),
        "encaissements": sejour.encaissements.select_related("utilisateur", "annule").order_by("date"),
        "virements": sejour.virements.all(),
        "session": caisse_services.session_ouverte_de(request.user),
    })


@require_POST
@acces_requis(reception)
def sejour_action(request, pk, action):
    sejour = get_object_or_404(Sejour, pk=pk)
    try:
        if action == "check-in":
            services.check_in(sejour, request.user)
            messages.success(request, f"Check-in fait : {sejour.chambre} occupée.")
        elif action == "check-out":
            services.check_out(sejour, request.user)
            sejour.refresh_from_db()
            if sejour.reste_a_payer > 0:
                messages.warning(request, f"Check-out fait. Reste à payer : {sejour.reste_a_payer:,} FCFA "
                                          "(apparaît dans les impayés).".replace(",", " "))
            else:
                messages.success(request, "Check-out fait, séjour soldé.")
        else:
            raise PermissionDenied
    except ValidationError as exc:
        _erreurs(request, exc)
    return redirect("hotel:sejour", pk=sejour.pk)


@acces_requis(reception)
def sejour_annuler(request, pk, no_show=False):
    sejour = get_object_or_404(Sejour, pk=pk)
    form = MotifForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.annuler(sejour, request.user, form.cleaned_data["motif"], no_show=no_show)
            messages.success(request, "Réservation passée en no-show." if no_show else "Réservation annulée.")
            return redirect("hotel:sejour", pk=sejour.pk)
        except ValidationError as exc:
            _erreurs(request, exc)
    return render(request, "form_page.html", {
        "form": form, "titre": "No-show" if no_show else "Annuler la réservation", "sous_titre": str(sejour),
        "bouton": "Confirmer", "retour_url": reverse("hotel:sejour", args=[sejour.pk]),
        "intro": "La chambre est libérée. Le sort de l'acompte suit la politique de l'hôtel : "
                 "un remboursement éventuel se fait ensuite depuis la fiche du séjour."})


@acces_requis(reception)
def encaisser(request, pk):
    sejour = get_object_or_404(Sejour, pk=pk)
    session = caisse_services.session_ouverte_de(request.user)
    if session is None:
        messages.error(request, "Ouvrez d'abord votre session de caisse.")
        return redirect("caisse:ma_caisse")
    initial = {"montant": max(sejour.reste_a_payer, 0) or None,
               "nature": Encaissement.Nature.ACOMPTE if sejour.statut == Sejour.Statut.RESERVE
               else Encaissement.Nature.REGLEMENT}
    form = EncaissementForm(request.POST or None, initial={**initial, "moyen": "ESPECES"})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            enc = caisse_services.encaisser(session, request.user, sejour, d["nature"], d["mode"], d["montant"],
                                            reference=d.get("reference", ""), valideur=d.get("_valideur"))
            messages.success(request, f"Encaissement enregistré : reçu n°{enc.numero_recu}.")
            return redirect("caisse:recu_client", pk=enc.pk)
        except ValidationError as exc:
            for msg in exc.messages:
                form.add_error(None, msg)
    return render(request, "hotel/encaisser.html", {"form": form, "sejour": sejour, "session": session})


# --- Chambres et clients -----------------------------------------------------------------
@acces_requis(reception)
def chambres(request):
    liste = Chambre.objects.prefetch_related("photos")
    occupants = {s.chambre_id: s for s in Sejour.objects.filter(statut=Sejour.Statut.EN_COURS).select_related("client")}
    for c in liste:
        c.occupant = occupants.get(c.pk)
    return render(request, "hotel/chambres.html", {"chambres": liste})


@acces_requis(gerant)
def chambre_form(request, pk=None):
    chambre = get_object_or_404(Chambre, pk=pk) if pk else None
    form = ChambreForm(request.POST or None, request.FILES or None, instance=chambre)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        journaliser(request.user, "Chambre modifiée" if chambre else "Chambre créée", obj, f"tarif {obj.tarif_nuit}")
        messages.success(request, f"{obj} enregistrée.")
        return redirect("hotel:chambres")
    return render(request, "form_page.html", {"form": form, "titre": f"Modifier la {chambre}" if chambre else
                                              "Nouvelle chambre", "retour": "hotel:chambres"})


def photographe(u):
    """Qui ajoute les photos des chambres : la direction et la gouvernante (elle suit les chambres)."""
    return u.est_direction or u.est_gouvernante


PHOTOS_PAR_ENVOI = 10


@acces_requis(photographe)
def photos_chambres(request):
    """Ajouter des photos à une chambre (plusieurs d'un coup, prises au téléphone), en retirer, choisir la première.

    Sur le site, les clients voient les photos par type de chambre (même catégorie et même prix) : photographier une
    chambre de chaque type suffit.
    """
    from core.images import photo_allegee

    from .models import PhotoChambre

    if request.method == "POST":
        action = request.POST.get("action")
        if action in ("retirer", "premiere"):
            photo = get_object_or_404(PhotoChambre, pk=request.POST.get("photo"))
            chambre = photo.chambre
            if action == "retirer":
                photo.image.delete(save=False)
                photo.delete()
                journaliser(request.user, "Photo de chambre retirée", chambre)
                messages.success(request, f"Photo retirée de la chambre {chambre.numero}.")
            else:
                premiere = chambre.photos.order_by("ordre", "pk").first()
                photo.ordre = (premiere.ordre - 1) if premiere and premiere.pk != photo.pk else photo.ordre
                photo.save(update_fields=["ordre"])
                messages.success(request, f"Cette photo est maintenant la première de la chambre {chambre.numero}.")
        else:
            chambre = get_object_or_404(Chambre, pk=request.POST.get("chambre"))
            fichiers = request.FILES.getlist("photos")
            place = PhotoChambre.MAX_PAR_CHAMBRE - chambre.photos.count()
            if not fichiers:
                messages.error(request, "Choisissez au moins une photo.")
            elif len(fichiers) > PHOTOS_PAR_ENVOI:
                messages.error(request, f"{PHOTOS_PAR_ENVOI} photos au plus à la fois : recommencez avec moins de photos.")
            elif len(fichiers) > place:
                messages.error(request, f"La chambre {chambre.numero} a déjà {chambre.photos.count()} photos "
                                        f"({PhotoChambre.MAX_PAR_CHAMBRE} au plus) : retirez-en avant d'en ajouter.")
            else:
                dernier = max(chambre.photos.values_list("ordre", flat=True), default=0)
                ajoutees, refusees = 0, []
                for fichier in fichiers:
                    try:
                        image = photo_allegee(fichier, nom=f"chambre-{chambre.numero.replace('/', '-')}", taille=1600)
                    except ValidationError:
                        refusees.append(fichier.name)
                        continue
                    ajoutees += 1
                    PhotoChambre.objects.create(chambre=chambre, image=image, ordre=dernier + ajoutees,
                                                ajoutee_par=request.user)
                if ajoutees:
                    journaliser(request.user, "Photos de chambre ajoutées", chambre, f"{ajoutees} photo(s)")
                    messages.success(request, f"{ajoutees} photo{'s' if ajoutees > 1 else ''} ajoutée"
                                              f"{'s' if ajoutees > 1 else ''} à la chambre {chambre.numero}.")
                if refusees:
                    messages.error(request, "Pas des photos lisibles (JPEG, PNG ou WebP, 10 Mo au plus) : "
                                            + ", ".join(refusees[:5]))
        return redirect(f"{reverse('hotel:photos_chambres')}?vue={request.POST.get('vue', '')}#chambre-{chambre.pk}")
    vue = request.GET.get("vue", "")
    chambres = list(Chambre.objects.filter(active=True).prefetch_related("photos").order_by("numero"))
    sans_photo = [c for c in chambres if not c.photos.all()]
    types_sans_photo = sorted({(c.get_categorie_display(), c.tarif_nuit) for c in chambres}
                              - {(c.get_categorie_display(), c.tarif_nuit) for c in chambres if c.photos.all()},
                              key=lambda t: t[1])
    groupes = {}
    for c in (sans_photo if vue == "sans" else chambres):
        groupes.setdefault(c.numero[:1], []).append(c)
    return render(request, "hotel/photos_chambres.html", {
        "groupes": [{"titre": f"Chambres {liste[0].numero} à {liste[-1].numero}" if len(liste) > 1
                     else f"Chambre {liste[0].numero}", "chambres": liste} for liste in groupes.values()],
        "vue": vue, "nb_sans_photo": len(sans_photo), "types_sans_photo": types_sans_photo,
        "max_par_chambre": PhotoChambre.MAX_PAR_CHAMBRE, "par_envoi": PHOTOS_PAR_ENVOI})


@acces_requis(reception)
def clients(request):
    q = request.GET.get("q", "").strip()
    qs = Client.objects.all()
    if q:
        qs = qs.filter(Q(nom__icontains=q) | Q(telephone__icontains=q) | Q(entreprise__icontains=q))
    return render(request, "hotel/clients.html", {"clients": qs[:200], "q": q})


@acces_requis(reception)
def client_form(request, pk=None):
    client = get_object_or_404(Client, pk=pk) if pk else None
    form = ClientForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Client {obj} enregistré.")
        return redirect("hotel:clients")
    return render(request, "form_page.html", {"form": form, "titre": f"Modifier {client}" if client else "Nouveau client",
                                              "retour": "hotel:clients"})


@acces_requis(reception)
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    return render(request, "hotel/client_detail.html", {"client": client,
                                                        "sejours": client.sejours.select_related("chambre")})


# --- Extras (restaurant, bar) --------------------------------------------------------------
@acces_requis(extras)
def extras_vue(request):
    """Extras sur chambre, en deux temps : toucher la chambre, puis dire ce que le client a pris.

    L'extra va sur la note de la chambre ; il est payé à la réception avec la chambre. La cuisine / bar fait de même
    depuis son écran de vente (« À crédit » sur la chambre).
    """
    u = request.user
    presents = Sejour.objects.filter(statut=Sejour.Statut.EN_COURS).select_related("chambre", "client").order_by(
        "chambre__numero")
    sejour = None
    choix = request.POST.get("sejour") or request.GET.get("sejour")
    if choix:
        sejour = get_object_or_404(presents, pk=choix)
    form = ExtraForm(request.POST or None) if sejour else None
    if request.method == "POST" and form is not None and form.is_valid():
        d = form.cleaned_data
        source = Extra.Source.RESTAURANT if d.get("plat") else Extra.Source.AUTRE
        try:
            extra = services.ajouter_extra(sejour, u, source, d["description"], d["montant"],
                                           d.get("numero_bon", ""))
            messages.success(request, f"C'est noté : {extra.description}, {format_fcfa(extra.montant)} sur la "
                                      f"chambre {sejour.chambre.numero}. Le client paiera à la réception.")
            return redirect("hotel:extras")
        except ValidationError as exc:
            for msg in exc.messages:
                form.add_error(None, msg)
    debut = timezone.make_aware(datetime.combine(aujourd_hui(), datetime.min.time()))
    du_jour = Extra.objects.filter(date_conso__gte=debut).select_related(
        "sejour__chambre", "sejour__client", "saisi_par")
    actifs = [e for e in du_jour if e.statut == Extra.Statut.ACTIF]
    return render(request, "hotel/extras.html", {
        "presents": presents, "sejour": sejour, "form": form, "du_jour": du_jour,
        "total_jour": sum(e.montant for e in actifs)})


@acces_requis(extras)
def extra_annuler(request, pk):
    extra = get_object_or_404(Extra, pk=pk)
    if request.user.est_bar and extra.saisi_par_id != request.user.pk:
        raise PermissionDenied("Vous ne pouvez annuler que vos propres extras.")
    form = MotifForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.annuler_extra(extra, request.user, form.cleaned_data["motif"])
            messages.success(request, "Extra annulé. Le chef de réception est prévenu.")
            return redirect("hotel:extras")
        except ValidationError as exc:
            _erreurs(request, exc)
    return render(request, "form_page.html", {"form": form, "titre": "Annuler un extra", "sous_titre": str(extra),
                                              "bouton": "Annuler l'extra", "retour": "hotel:extras"})


# --- Ménage ----------------------------------------------------------------------------------
@acces_requis(menage)
def menage_vue(request):
    if request.method == "POST":
        chambre = get_object_or_404(Chambre, pk=request.POST.get("chambre"))
        services.marquer_nettoyee(chambre, request.user)
        messages.success(request, f"{chambre} marquée comme faite.")
        return redirect("hotel:menage")
    return render(request, "hotel/menage.html", {
        "a_faire": Chambre.objects.filter(active=True, statut=Chambre.Statut.A_NETTOYER),
        "occupees": Chambre.objects.filter(active=True, statut=Chambre.Statut.OCCUPEE),
        "historique": Nettoyage.objects.select_related("chambre", "fait_par")[:30],
    })

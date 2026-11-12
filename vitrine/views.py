from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Min
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from caisse.models import Encaissement
from core.models import Etablissement
from core.permissions import acces_requis, direction, reception
from core.stockage import reponse_fichier
from hotel.models import Chambre, Client, Sejour

from . import services
from .forms import InscriptionForm, PhotoForm
from .models import CompteClient, PhotoSite

# Le texte de chaque rubrique ; sans photo, elle montre une illustration, jamais la photo d'un autre hôtel.
TEXTES_RUBRIQUES = {
    "HOTEL": "Un cadre calme pour vos séjours et vos rendez-vous.",
    "CHAMBRES": "Chambres et suites, prêtes à vous accueillir.",
    "RECEPTION": "Une équipe à l'écoute à votre arrivée et pendant tout le séjour.",
    "PLATS": "Les plats de notre cuisine, servis sur place.",
    "PARKING": "Garez votre véhicule sur place.",
}


def tuiles_galerie():
    """Toutes les photos du site, rubrique par rubrique ; une illustration pour chaque rubrique encore sans photo."""
    photos = list(PhotoSite.objects.all())
    tuiles = []
    for rubrique, titre in PhotoSite.Rubrique.choices:
        dans_rubrique = [p for p in photos if p.rubrique == rubrique]
        for p in dans_rubrique:
            tuiles.append({"url": p.url, "titre": titre, "texte": p.legende or TEXTES_RUBRIQUES[rubrique],
                           "photo": True, "rubrique": rubrique})
        if not dans_rubrique:
            tuiles.append({"url": static(f"img/vitrine/{rubrique.lower()}.svg"), "titre": titre,
                           "texte": TEXTES_RUBRIQUES[rubrique], "photo": False, "rubrique": rubrique})
    return tuiles


def page_vitrine(request):
    """Page publique : présentation de l'hôtel, « Se connecter » et « Créer un compte »."""
    chambres = Chambre.objects.filter(active=True)
    noms = {"SIMPLE": ("Chambres", "chambre", "chambres"), "DOUBLE": ("Chambres doubles", "chambre double", "chambres doubles"),
            "SUITE": ("Suites", "suite", "suites"), "AUTRE": ("Autres chambres", "autre chambre", "autres chambres")}
    offres = []
    for categorie, _ in Chambre.Categorie.choices:
        qs = chambres.filter(categorie=categorie)
        nombre = qs.count()
        if nombre:
            titre, un, plusieurs = noms[categorie]
            avec_photo = qs.exclude(photo="").first()
            offres.append({"libelle": titre, "compte": f"{nombre} {un if nombre == 1 else plusieurs}",
                           "prix": qs.filter(tarif_nuit__gt=0).aggregate(p=Min("tarif_nuit"))["p"],
                           "photo": avec_photo.photo_url if avec_photo else ""})
    from datetime import timedelta

    from core.utils import aujourd_hui

    from .forms import RechercheChambreForm

    jour = aujourd_hui()
    return render(request, "vitrine/accueil.html", {
        "recherche": RechercheChambreForm(initial={"arrivee": jour, "depart": jour + timedelta(days=1), "personnes": 1}),
        "etab": Etablissement.get(), "nb_chambres": chambres.count(), "offres": offres, "tuiles": tuiles_galerie(),
        "diaporama": _diaporama(), "prix_bas": (prix_bas := _prix_les_plus_bas(offres)),
        "duree_defile": max(20, 5 * len(prix_bas)),  # environ 5 secondes par prix : lisible sans attendre
        **_carte()})


def _prix_les_plus_bas(offres):
    """Ce qui défile sous le bandeau : le prix d'entrée de chaque chambre, de chaque rubrique de la carte et du bar.

    « dès » seulement quand la rubrique a plusieurs prix (les garnitures sont toutes à 500 F).
    """
    from django.db.models import Max

    from stock.models import Article

    lignes = [{"libelle": o["libelle"], "prix": o["prix"], "des": True} for o in offres if o["prix"]]
    plats = (Article.objects.filter(categorie=Article.Categorie.RESTAURANT, actif=True, prix_vente__gt=0)
             .values("rubrique").annotate(bas=Min("prix_vente"), haut=Max("prix_vente"), ordre=Min("ordre"))
             .order_by("ordre"))
    lignes += [{"libelle": p["rubrique"] or "La carte", "prix": p["bas"], "des": p["haut"] > p["bas"]} for p in plats]
    bar = Article.objects.filter(categorie=Article.Categorie.BAR, actif=True, prix_vente__gt=0).aggregate(
        bas=Min("prix_vente"))["bas"]
    if bar:
        lignes.append({"libelle": "Boissons du bar", "prix": bar, "des": True})
    return lignes


def _diaporama():
    """Les photos qui défilent dans le grand bandeau : celles de l'hôtel d'abord, puis les autres (8 au plus)."""
    photos = list(PhotoSite.objects.all())
    photos.sort(key=lambda p: (p.rubrique != PhotoSite.Rubrique.HOTEL, p.ordre, p.ajoutee_le))
    return [p.url for p in photos[:8]]


def _carte():
    """La carte de la cuisine, rubrique par rubrique, et les plats qui ont une photo."""
    from stock.models import Article

    plats = list(Article.objects.filter(categorie=Article.Categorie.RESTAURANT, actif=True, prix_vente__gt=0)
                 .order_by("ordre", "nom"))
    rubriques = {}
    for p in plats:
        rubriques.setdefault(p.rubrique or "La carte", []).append(p)
    return {"carte": [{"titre": titre, "plats": liste} for titre, liste in rubriques.items()],
            "plats": [p for p in plats if p.photo][:8]}


def _image_publique(champ):
    reponse = reponse_fichier(champ)
    reponse["Cache-Control"] = "public, max-age=86400"
    return reponse


def image_article(request, pk):
    from stock.models import Article

    return _image_publique(get_object_or_404(Article, pk=pk).photo)


def dessin_article(request, pk):
    """Le dessin d'un article qui n'a pas encore de photo : une image SVG faite par l'application, sans texte libre."""
    from django.http import HttpResponse

    from stock.illustrations import illustration_svg
    from stock.models import Article

    reponse = HttpResponse(illustration_svg(get_object_or_404(Article, pk=pk)), content_type="image/svg+xml")
    reponse["Cache-Control"] = "public, max-age=86400"
    reponse["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return reponse


def image_chambre(request, pk):
    return _image_publique(get_object_or_404(Chambre, pk=pk).photo)


def photo(request, pk):
    """Les photos du site sont publiques : elles s'affichent sur la page d'accueil."""
    reponse = reponse_fichier(get_object_or_404(PhotoSite, pk=pk).image)
    reponse["Cache-Control"] = "public, max-age=86400"
    return reponse


@acces_requis(direction)
def photos(request):
    form = PhotoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        ajoutees, refusees = 0, []
        for image in d["images"]:
            try:
                services.ajouter_photo(request.user, d["rubrique"], image, d.get("legende", ""))
                ajoutees += 1
            except ValidationError as exc:
                refusees.append(f"{image.name} : {exc.messages[0]}")
        if ajoutees:
            messages.success(request, f"{ajoutees} photo(s) ajoutée(s) : elles apparaissent sur la page d'accueil.")
        for msg in refusees:
            messages.error(request, msg)
        return redirect("vitrine:photos")
    toutes = list(PhotoSite.objects.all())
    rubriques = [{"cle": cle, "titre": titre, "photos": [p for p in toutes if p.rubrique == cle]}
                 for cle, titre in PhotoSite.Rubrique.choices]
    return render(request, "vitrine/photos.html", {"form": form, "rubriques": rubriques})


@require_POST
@acces_requis(direction)
def photo_retirer(request, pk):
    services.retirer_photo(request.user, get_object_or_404(PhotoSite, pk=pk))
    messages.success(request, "Photo retirée de la page d'accueil.")
    return redirect("vitrine:photos")


def inscription(request):
    if request.user.is_authenticated:
        return redirect("core:accueil")
    form = InscriptionForm(request.POST or None)
    cle = f"inscriptions:{request.META.get('REMOTE_ADDR', '')}"
    if request.method == "POST" and cache.get(cle, 0) >= 5:
        form.is_valid()
        form.add_error(None, "Trop de comptes créés depuis cet appareil : réessayez dans une heure.")
    elif request.method == "POST" and form.is_valid():
        cache.set(cle, cache.get(cle, 0) + 1, 3600)
        d = form.cleaned_data
        compte = services.inscrire(d["nom"], d["telephone"], d.get("email", ""), d["mot_de_passe"])
        login(request, compte.user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Votre compte est créé. Votre identifiant est votre numéro de téléphone.")
        return redirect("vitrine:espace")
    return render(request, "vitrine/inscription.html", {"form": form, "etab": Etablissement.get()})


@login_required
def espace(request):
    """Espace du client : ses séjours en cours et à venir, ce qu'il a payé, ce qu'il reste à régler."""
    if not request.user.est_client:
        return redirect("core:accueil")
    compte = request.user.compte_client
    ctx = {"compte": compte, "etab": Etablissement.get(),
           "demandes": compte.demandes.select_related("sejour__chambre")[:10]}
    if compte.client_id:
        sejours = list(compte.client.sejours.exclude(statut=Sejour.Statut.ANNULE).select_related("chambre")
                       .prefetch_related("extras").order_by("-date_arrivee"))
        passes = [s for s in sejours if s.statut in (Sejour.Statut.TERMINE, Sejour.Statut.NO_SHOW)]
        ctx.update({
            "en_cours": [s for s in sejours if s.statut == Sejour.Statut.EN_COURS],
            "a_venir": sorted((s for s in sejours if s.statut == Sejour.Statut.RESERVE), key=lambda s: s.date_arrivee),
            "passes": passes[:10],
            "reste_passes": sum(max(s.reste_a_payer, 0) for s in passes),
            "paiements": Encaissement.objects.filter(sejour__client=compte.client).select_related("sejour__chambre")
            .order_by("-date")[:30],
        })
    return render(request, "vitrine/espace.html", ctx)


class MotDePasseClient(auth_views.PasswordChangeView):
    template_name = "vitrine/formulaire.html"
    success_url = reverse_lazy("vitrine:espace")
    extra_context = {"titre": "Changer mon mot de passe"}

    def form_valid(self, form):
        messages.success(self.request, "Mot de passe changé.")
        return super().form_valid(form)


# --- Côté réception : relier les comptes en ligne aux fiches clients -------------------------------------
@acces_requis(reception)
def comptes(request):
    if request.method == "POST":
        compte = get_object_or_404(CompteClient, pk=request.POST.get("compte"))
        try:
            if request.POST.get("action") == "refuser":
                services.refuser(compte, request.user)
                messages.success(request, f"Compte de {compte.nom} refusé : il ne peut plus se connecter.")
            else:
                client = get_object_or_404(Client, pk=request.POST["client"]) if request.POST.get("client") else None
                services.relier(compte, request.user, client)
                messages.success(request, f"{compte.nom} voit maintenant ses séjours et ses paiements en ligne.")
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
        return redirect("vitrine:comptes")
    en_attente = list(CompteClient.objects.filter(statut=CompteClient.Statut.EN_ATTENTE).order_by("cree_le"))
    for compte in en_attente:
        compte.suggestions = services.fiches_au_meme_numero(compte)
    return render(request, "vitrine/comptes.html", {
        "en_attente": en_attente, "clients": Client.objects.order_by("nom"),
        "traites": CompteClient.objects.exclude(statut=CompteClient.Statut.EN_ATTENTE).select_related(
            "client", "traite_par")[:30],
    })


# --- Réserver depuis la page d'accueil -------------------------------------------------------------------------------
def _recherche(request):
    """Les dates demandées (dans l'adresse), vérifiées ; None et un message si elles ne vont pas."""
    from datetime import timedelta

    from core.utils import aujourd_hui

    from . import reservations
    from .forms import RechercheChambreForm

    jour = aujourd_hui()
    form = RechercheChambreForm(request.GET if request.GET.get("arrivee") else None,
                                initial={"arrivee": jour, "depart": jour + timedelta(days=1), "personnes": 1})
    if not form.is_bound or not form.is_valid():
        return form, None
    d = form.cleaned_data
    try:
        reservations.verifier_dates(d["arrivee"], d["depart"], d["personnes"])
    except ValidationError as exc:
        form.add_error(None, exc)
        return form, None
    return form, d


def reserver(request):
    """Étape 1 et 2 : les dates, puis les chambres libres à ces dates, avec le prix du séjour."""
    from . import reservations

    form, d = _recherche(request)
    types = reservations.types_libres(d["arrivee"], d["depart"], d["personnes"]) if d else None
    return render(request, "vitrine/reserver.html", {
        "form": form, "d": d, "types": types, "etab": Etablissement.get(),
        "arrivee_texte": reservations.date_longue(d["arrivee"]) if d else "",
        "depart_texte": reservations.date_longue(d["depart"]) if d else "",
        "nuits": (d["depart"] - d["arrivee"]).days if d else 0})


def reserver_coordonnees(request):
    """Étape 3 : le nom et le téléphone ; la demande part à la réception."""
    from django.urls import reverse

    from . import reservations
    from .forms import DemandeReservationForm

    recherche, d = _recherche(request)
    choix = reservations.trouver_type(d["arrivee"], d["depart"], d["personnes"], request.GET.get("type", "")) if d else None
    if choix is None:
        messages.warning(request, "Ce type de chambre n'est plus libre à ces dates : choisissez-en un autre.")
        return redirect(f"{reverse('vitrine:reserver')}?{request.GET.urlencode()}")
    compte = request.user.compte_client if request.user.is_authenticated and request.user.est_client else None
    form = DemandeReservationForm(request.POST or None, initial={"nom": compte.nom, "telephone": compte.telephone,
                                                                 "email": compte.email} if compte else None)
    cle = f"reservations-en-ligne:{request.META.get('REMOTE_ADDR', '')}"
    if request.method == "POST" and cache.get(cle, 0) >= 5:
        form.is_valid()
        form.add_error(None, "Trop de demandes envoyées depuis cet appareil : appelez la réception, ou réessayez dans une heure.")
    elif request.method == "POST" and form.is_valid():
        f = form.cleaned_data
        if f.get("site_web"):  # un robot a rempli le champ caché : on fait comme si de rien n'était
            return redirect("vitrine:site")
        cache.set(cle, cache.get(cle, 0) + 1, 3600)
        try:
            demande = reservations.creer_demande(d["arrivee"], d["depart"], d["personnes"], choix["cle"], f["nom"],
                                                 f["telephone"], f.get("email", ""), f.get("message", ""), compte)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            request.session["demandes_reservation"] = request.session.get("demandes_reservation", [])[-9:] + [demande.pk]
            return redirect("vitrine:reservation_envoyee", pk=demande.pk)
    return render(request, "vitrine/reserver_coordonnees.html", {
        "form": form, "d": d, "choix": choix, "etab": Etablissement.get(), "compte": compte,
        "arrivee_texte": reservations.date_longue(d["arrivee"]), "depart_texte": reservations.date_longue(d["depart"])})


def reservation_envoyee(request, pk):
    """Étape 4 : le numéro de la demande et ce qui va se passer. Visible seulement par qui l'a envoyée."""
    from django.http import Http404

    from . import reservations
    from .models import DemandeReservation

    demande = get_object_or_404(DemandeReservation, pk=pk)
    sienne = (request.user.is_authenticated and request.user.est_client and demande.compte_id
              and demande.compte.user_id == request.user.pk)
    if pk not in request.session.get("demandes_reservation", []) and not sienne:
        raise Http404
    return render(request, "vitrine/reservation_envoyee.html", {
        "demande": demande, "etab": Etablissement.get(),
        "arrivee_texte": reservations.date_longue(demande.date_arrivee),
        "depart_texte": reservations.date_longue(demande.date_depart)})


@require_POST
@login_required
def demande_annuler(request, pk):
    from . import reservations
    from .models import DemandeReservation

    if not request.user.est_client:
        return redirect("core:accueil")
    demande = get_object_or_404(DemandeReservation, pk=pk)
    try:
        reservations.annuler_par_le_client(demande, request.user.compte_client)
        messages.success(request, "Votre demande est annulée.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect("vitrine:espace")


@acces_requis(reception)
def demandes(request):
    """Côté réception : les réservations demandées en ligne, à confirmer d'un geste."""
    from . import reservations
    from .models import DemandeReservation

    if request.method == "POST":
        demande = get_object_or_404(DemandeReservation, pk=request.POST.get("demande"))
        try:
            if request.POST.get("action") == "refuser":
                reservations.refuser(demande, request.user, request.POST.get("motif", ""))
                messages.success(request, f"Demande n°{demande.pk} refusée.")
            else:
                chambre = get_object_or_404(Chambre, pk=request.POST.get("chambre"))
                sejour = reservations.confirmer(demande, request.user, chambre)
                messages.success(request, f"Réservation confirmée : {sejour.client}, chambre {chambre.numero}, du "
                                          f"{sejour.date_arrivee:%d/%m} au {sejour.date_depart:%d/%m}. "
                                          "Pensez à prévenir le client.")
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
        return redirect("vitrine:demandes")
    nouvelles = list(DemandeReservation.objects.filter(statut=DemandeReservation.Statut.NOUVELLE)
                     .select_related("chambre_proposee", "compte").order_by("date_arrivee"))
    for demande in nouvelles:
        libres = list(reservations.chambres_libres(demande.date_arrivee, demande.date_depart, 1))
        demande.memes = [c for c in libres if c.categorie == demande.categorie and c.tarif_nuit == demande.tarif_nuit]
        demande.autres = [c for c in libres if c not in demande.memes]
        demande.proposee_libre = demande.chambre_proposee in libres
    return render(request, "vitrine/demandes.html", {
        "nouvelles": nouvelles,
        "traitees": DemandeReservation.objects.exclude(statut=DemandeReservation.Statut.NOUVELLE)
        .select_related("sejour__chambre", "traitee_par")[:30]})

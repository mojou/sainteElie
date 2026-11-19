from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.forms import MotifForm
from core.permissions import acces_requis, direction, gerant, stock, suivi_caisse, validateur_caisse
from core.permissions import caisse as tient_caisse
from core.stockage import reponse_fichier
from core.utils import aujourd_hui, format_fcfa, journaliser, maintenant
from hotel.models import Client
from stock.models import Article, MouvementStock
from stock.services import enregistrer_mouvement

from . import services
from .forms import (AvarieForm, ComptageForm, FinalisationForm, FondForm, OuvertureForm,
                    ParametreCaisseForm, ReglementCreditForm, SortieForm, TiroirForm, ValidationForm, CommandeForm,
                    VirementForm)
from .models import (Consigne, ConsigneLecture, Encaissement, FondCaisse, ParametreCaisse,
                     RapportQuotidien, RemiseCaisse, SessionCaisse, SortieCaisse, Tiroir, VenteComptoir, Virement)


def acces_avarie(u):
    return tient_caisse(u) or stock(u)


def _erreurs_form(form, exc):
    for msg in exc.messages:
        form.add_error(None, msg)


def _consignes_non_lues(user, tiroir):
    derniere = (tiroir.sessions.filter(est_rectificative=False, remise__finalisee=True).exclude(receptionniste=user)
                .order_by("-remise_le").first())
    if not derniere:
        return Consigne.objects.none()
    return derniere.consignes.exclude(lectures__utilisateur=user)


# --- Ma caisse -------------------------------------------------------------------------
@acces_requis(tient_caisse)
def ma_caisse(request):
    session = services.session_ouverte_de(request.user)
    if session is None:
        return _ouverture(request)
    sorties = session.sorties.select_related("valide_par")
    return render(request, "caisse/ma_caisse.html", {
        "session": session,
        "moyens": session.totaux_par_moyen(),
        "encaissements": session.encaissements.select_related("sejour__client", "sejour__chambre"),
        "sorties": sorties,
        "consignes": session.consignes.all(),
    })


def _ouverture(request):
    tiroirs = Tiroir.accessibles_a(request.user)
    if not tiroirs.exists():
        messages.error(request, "Aucune caisse n'est configurée pour votre poste : demandez au gérant de la créer "
                                "(Paramètres → Caisse).")
        return render(request, "caisse/ouverture.html", {"form": None})
    tiroir_id = request.POST.get("tiroir") or request.GET.get("tiroir") or tiroirs.first().pk
    tiroir = get_object_or_404(tiroirs, pk=tiroir_id)
    consignes = list(_consignes_non_lues(request.user, tiroir))
    form = OuvertureForm(request.POST or None, initial={"tiroir": tiroir, "shift": services.shift_suggere()})
    form.fields["tiroir"].queryset = tiroirs
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if consignes and not d["consignes_lues"]:
            form.add_error("consignes_lues", "Lisez les messages de la personne d'avant, puis cochez la case.")
        else:
            try:
                session = services.ouvrir_session(request.user, d["tiroir"], d["shift"], d["especes_comptees"])
                for c in consignes:
                    ConsigneLecture.objects.get_or_create(consigne=c, utilisateur=request.user)
                messages.success(request, f"Votre caisse est ouverte ({session.get_shift_display()}). Bon service !")
                if session.ecart_ouverture < 0:
                    messages.warning(request, "Il manque de l'argent dans la caisse : le chef est prévenu, c'est la "
                                              "personne d'avant qui en répond.")
                suite = request.POST.get("suite", "")
                if url_has_allowed_host_and_scheme(suite, allowed_hosts={request.get_host()}):
                    return redirect(suite)
                return redirect("caisse:ma_caisse")
            except ValidationError as exc:
                _erreurs_form(form, exc)
    return render(request, "caisse/ouverture.html", {
        "suite": request.POST.get("suite") or request.GET.get("suite", ""),
        "form": form, "tiroir": tiroir, "prevues": services.especes_ouverture_prevues(tiroir),
        "consignes": consignes,
        "bloquante": tiroir.sessions.filter(statut=SessionCaisse.Statut.OUVERTE, est_rectificative=False).first(),
    })


@require_POST
@acces_requis(tient_caisse)
def consigne_ajouter(request):
    session = services.session_ouverte_de(request.user)
    texte = request.POST.get("texte", "").strip()
    if session and texte:
        Consigne.objects.create(session=session, texte=texte, auteur=request.user)
        messages.success(request, "Message enregistré pour la personne suivante.")
    return redirect("caisse:ma_caisse")


@acces_requis(tient_caisse)
def sortie_nouvelle(request):
    session = services.session_ouverte_de(request.user)
    if session is None:
        return redirect("caisse:ma_caisse")
    form = SortieForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            sortie = services.creer_sortie(session, request.user, d["type"], d["montant"], d["motif"],
                                           justificatif=d.get("justificatif"), valideur=d.get("_valideur"))
            if sortie.statut == SortieCaisse.Statut.A_VALIDER:
                messages.warning(request, "Dépense enregistrée, en attente de validation par le chef de réception.")
            else:
                messages.success(request, "Sortie de caisse enregistrée.")
            return redirect("caisse:ma_caisse")
        except ValidationError as exc:
            _erreurs_form(form, exc)
    return render(request, "form_page.html", {
        "form": form, "titre": "Sortir de l'argent de la caisse", "retour": "caisse:ma_caisse",
        "intro": "Tout argent qui quitte la caisse passe par ici : un petit achat (photographiez le reçu), ou le "
                 "gérant qui prend de l'argent (avec son code PIN). Sinon, il manquera quand vous fermerez la caisse."})


# --- Remise : comptage à l'aveugle puis comparaison ------------------------------------------
def _session_a_compter(request, pk, cloture_office):
    if cloture_office:
        if not request.user.peut_valider_caisse:
            raise PermissionDenied
        session = get_object_or_404(SessionCaisse, pk=pk, statut=SessionCaisse.Statut.OUVERTE)
        if session.receptionniste_id == request.user.pk:
            raise PermissionDenied
        return session
    session = services.session_ouverte_de(request.user)
    if session is None:
        raise PermissionDenied("Aucune session ouverte.")
    return session


@acces_requis(suivi_caisse)
def remise_comptage(request, pk=None, cloture_office=False):
    session = _session_a_compter(request, pk, cloture_office)
    remise = getattr(session, "remise", None)
    if remise and remise.recompte_fait:
        return redirect(_url_comparaison(session, cloture_office))
    if remise and request.method == "GET" and request.GET.get("recompter") != "1":
        return redirect(_url_comparaison(session, cloture_office))
    form = ComptageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.enregistrer_comptage(session, request.user, d["especes"], form.billetage(), d["cheques_nombre"],
                                          d["cheques_total"], d["mobile"], cloture_office=cloture_office)
            return redirect(_url_comparaison(session, cloture_office))
        except ValidationError as exc:
            _erreurs_form(form, exc)
    return render(request, "caisse/remise_comptage.html", {"form": form, "session": session, "remise": remise,
                                                           "cloture_office": cloture_office})


def _url_comparaison(session, cloture_office):
    if cloture_office:
        return reverse("caisse:cloture_office_comparaison", args=[session.pk])
    return reverse("caisse:remise_comparaison")


@acces_requis(suivi_caisse)
def remise_comparaison(request, pk=None, cloture_office=False):
    session = _session_a_compter(request, pk, cloture_office)
    if not hasattr(session, "remise"):
        return redirect(reverse("caisse:cloture_office", args=[session.pk]) if cloture_office
                        else reverse("caisse:remise_comptage"))
    form = FinalisationForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.finaliser_remise(session, request.user, d["motif"], entrant=d.get("_entrant"),
                                      cloture_office=cloture_office)
            if d.get("consigne", "").strip():
                Consigne.objects.create(session=session, texte=d["consigne"].strip(), auteur=request.user)
            messages.success(request, "Caisse fermée. Le reçu est prêt ; la personne suivante peut ouvrir sa caisse.")
            return redirect("caisse:session", pk=session.pk)
        except ValidationError as exc:
            _erreurs_form(form, exc)
    chiffres = services.comparaison(session)
    return render(request, "caisse/remise_comparaison.html", {
        "session": session, "c": chiffres, "form": form, "cloture_office": cloture_office,
        "motif_requis": chiffres["hors_seuil"] or cloture_office,
    })


# --- Sessions -------------------------------------------------------------------------------------
@acces_requis(suivi_caisse)
def sessions(request):
    statut = request.GET.get("statut", "")
    qs = services.sessions_visibles(request.user)
    if statut:
        qs = qs.filter(statut=statut)
    a_valider = qs.filter(statut__in=[SessionCaisse.Statut.REMISE, SessionCaisse.Statut.ECART]).exclude(
        receptionniste=request.user) if request.user.peut_valider_caisse else None
    return render(request, "caisse/sessions.html", {"sessions": qs[:200], "statut": statut,
                                                    "statuts": SessionCaisse.Statut.choices, "a_valider": a_valider})


def _session_visible(request, pk):
    session = get_object_or_404(services.sessions_visibles(request.user), pk=pk)
    return session


@acces_requis(suivi_caisse)
def session_detail(request, pk):
    session = _session_visible(request, pk)
    remise = getattr(session, "remise", None)
    peut_valider = (request.user.peut_valider_caisse and request.user.pk != session.receptionniste_id
                    and (remise is None or request.user.pk != remise.compte_par_id))
    form = ValidationForm(request.POST or None)
    if request.method == "POST" and peut_valider:
        action = request.POST.get("action")
        try:
            if action == "valider" and form.is_valid():
                services.valider_session(session, request.user, form.cleaned_data["imputation"],
                                         form.cleaned_data["decision"])
                messages.success(request, "Session validée et verrouillée.")
                return redirect("caisse:session", pk=session.pk)
            if action == "contester":
                services.contester_session(session, request.user, request.POST.get("motif_contestation", ""))
                messages.warning(request, "Remise contestée : elle passe en écart à arbitrer.")
                return redirect("caisse:session", pk=session.pk)
            if action in ("accepter_sortie", "refuser_sortie"):
                sortie = get_object_or_404(SortieCaisse, pk=request.POST.get("sortie"), session=session)
                services.traiter_sortie(sortie, request.user, action == "accepter_sortie")
                messages.success(request, "Sortie traitée.")
                return redirect("caisse:session", pk=session.pk)
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
    afficher_attendu = session.statut != SessionCaisse.Statut.OUVERTE or request.user.peut_valider_caisse
    return render(request, "caisse/session_detail.html", {
        "session": session, "remise": remise, "moyens": session.totaux_par_moyen(),
        "encaissements": session.encaissements.select_related(
            "sejour__client", "sejour__chambre", "annule"),
        "sorties": session.sorties.select_related("saisi_par", "valide_par"),
        "consignes": session.consignes.all(), "form": form, "peut_valider": peut_valider,
        "afficher_attendu": afficher_attendu,
        "rectifications": session.rectifications.all(),
    })


@acces_requis(suivi_caisse)
def recu_remise(request, pk):
    session = _session_visible(request, pk)
    remise = get_object_or_404(RemiseCaisse, session=session, finalisee=True)
    if session.saisie_passee or not remise.recu_pdf:
        # Caisse d'un jour passé saisie après coup : le reçu se refait à chaque fois, à jour des saisies.
        from core.pdf import reponse_pdf

        from .pdf import recu_remise_pdf
        return reponse_pdf(recu_remise_pdf(session), f"remise-{session.pk}.pdf", telecharger=False)
    return reponse_fichier(remise.recu_pdf, f"remise-{session.pk}.pdf")


@acces_requis(suivi_caisse)
def justificatif(request, pk):
    sortie = get_object_or_404(SortieCaisse, pk=pk)
    _session_visible(request, sortie.session_id)
    return reponse_fichier(sortie.justificatif)


@acces_requis(suivi_caisse)
def annuler_encaissement(request, pk):
    encaissement = get_object_or_404(Encaissement.objects.select_related("session", "sejour", "client"), pk=pk)
    vente = encaissement.ventes.first()
    if vente is not None:
        return redirect("caisse:vente_annuler", pk=vente.pk)
    retour = (reverse("hotel:sejour", args=[encaissement.sejour_id]) if encaissement.sejour_id
              else reverse("caisse:ma_caisse"))
    form = MotifForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.annuler_encaissement(encaissement, request.user, form.cleaned_data["motif"])
            messages.success(request, "Encaissement annulé par une écriture inverse. Le chef de réception est prévenu.")
            return redirect(retour)
        except ValidationError as exc:
            _erreurs_form(form, exc)
    return render(request, "form_page.html", {
        "form": form, "titre": f"Annuler le reçu n°{encaissement.numero_recu}",
        "sous_titre": f"{encaissement.get_nature_display()} de {encaissement.montant:,} FCFA - {encaissement.libelle}"
        .replace(",", " "),
        "intro": "Rien n'est supprimé : une écriture inverse est créée, avec votre motif, et le chef de réception "
                 "est prévenu. Après la remise, seul le chef ou le gérant peut corriger.",
        "bouton": "Annuler l'encaissement", "retour_url": retour})


def _recu_visible(request, pk):
    encaissement = get_object_or_404(Encaissement.objects.select_related(
        "sejour__client", "sejour__chambre", "utilisateur", "client", "annule"), pk=pk)
    if not (request.user.voit_reception
            or services.sessions_visibles(request.user).filter(pk=encaissement.session_id).exists()):
        raise PermissionDenied("Ce reçu appartient à la caisse d'un collègue.")
    return encaissement


@acces_requis(suivi_caisse)
def recu_client(request, pk):
    """Le reçu à remettre au client : à imprimer, ou à télécharger en PDF pour l'envoyer par WhatsApp."""
    from .recus import recu

    encaissement = _recu_visible(request, pk)
    return render(request, "caisse/recu_client.html", {"r": recu(encaissement), "e": encaissement,
                                                       "sejour": encaissement.sejour,
                                                       "maintenant": timezone.localtime()})


@acces_requis(suivi_caisse)
def recu_client_pdf(request, pk):
    from core.pdf import reponse_pdf

    from .pdf import recu_client_pdf as fabriquer
    from .recus import recu

    encaissement = _recu_visible(request, pk)
    return reponse_pdf(fabriquer(recu(encaissement)), f"recu-{encaissement.numero_recu}.pdf")


# --- Rapports quotidiens --------------------------------------------------------------------------
@acces_requis(validateur_caisse)
def rapports(request):
    nouveaux = services.generer_rapports_dus(user=request.user)
    if nouveaux:
        messages.info(request, f"{len(nouveaux)} rapport(s) généré(s) à l'heure de coupure.")
    return render(request, "caisse/rapports.html", {"rapports": RapportQuotidien.objects.all()[:120],
                                                    "params": ParametreCaisse.en_vigueur()})


@acces_requis(validateur_caisse)
def rapport_detail(request, pk):
    rapport = get_object_or_404(RapportQuotidien, pk=pk)
    return render(request, "caisse/rapport_detail.html", services.donnees_rapport(rapport))


@acces_requis(validateur_caisse)
def rapport_pdf(request, pk):
    rapport = get_object_or_404(RapportQuotidien, pk=pk)
    return reponse_fichier(rapport.pdf)


# --- Virements -----------------------------------------------------------------------------------------
@acces_requis(gerant)
def virements(request):
    form = VirementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        virement = form.save(commit=False)
        virement.saisi_par = request.user
        virement.save()
        journaliser(request.user, "Virement reçu", virement.sejour, f"{virement.montant} - {virement.reference_bancaire}")
        messages.success(request, "Virement enregistré : il solde le séjour concerné.")
        return redirect("caisse:virements")
    return render(request, "caisse/virements.html", {"form": form, "virements": Virement.objects.select_related(
        "sejour__client", "saisi_par")[:100]})


# --- Paramètres de caisse (admin) --------------------------------------------------------------------
@acces_requis(gerant)
def parametres(request):
    return render(request, "caisse/parametres.html", {
        "params": ParametreCaisse.objects.all()[:10], "en_vigueur": ParametreCaisse.en_vigueur(),
        "tiroirs": Tiroir.objects.all(), "fonds": FondCaisse.objects.select_related("tiroir", "cree_par")[:20],
    })


def _formulaire_admin(request, form_class, titre, instance=None, avant_save=None, intro=""):
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if avant_save:
            avant_save(obj)
        obj.save()
        journaliser(request.user, titre, obj)
        messages.success(request, "Enregistré.")
        return redirect("caisse:parametres")
    return render(request, "form_page.html", {"form": form, "titre": titre, "retour": "caisse:parametres",
                                              "intro": intro})


@acces_requis(gerant)
def parametres_nouveaux(request):
    def fixer(obj):
        obj.cree_par = request.user

    actuel = ParametreCaisse.en_vigueur()
    actuel.pk = None
    return _formulaire_admin(request, ParametreCaisseForm, "Nouveaux paramètres de caisse", instance=actuel,
                             avant_save=fixer, intro="Les paramètres s'appliquent à partir de leur date d'effet ; "
                                                     "les sessions déjà ouvertes gardent les leurs.")


@acces_requis(gerant)
def fond_nouveau(request):
    def fixer(obj):
        obj.cree_par = request.user

    return _formulaire_admin(request, FondForm, "Nouveau fond de caisse", avant_save=fixer,
                             intro="Le fond est le montant laissé dans le tiroir pour rendre la monnaie. "
                                   "Il s'applique à partir de sa date d'effet.")


@require_POST
@acces_requis(gerant)
def tiroir_supprimer(request, pk):
    from core import suppression

    tiroir = get_object_or_404(Tiroir, pk=pk)
    suppression.supprimer(request, tiroir, "cette caisse",
                          "Pour ne plus l'utiliser, ouvrez « Modifier » et décochez « Actif ».")
    return redirect("caisse:parametres")


@acces_requis(gerant)
def tiroir_form(request, pk=None):
    return _formulaire_admin(request, TiroirForm, "Tiroir de caisse",
                             instance=get_object_or_404(Tiroir, pk=pk) if pk else None)


# --- Ventes bar et boutique (main courante) -------------------------------------------------------
@acces_requis(tient_caisse)
def ventes(request):
    session = services.session_ouverte_de(request.user)
    if session is None:
        messages.info(request, "Commencez par ouvrir votre caisse : comptez le fond, puis validez.")
        return redirect(f"{reverse('caisse:ma_caisse')}?suite={request.path}")
    articles = Article.objects.filter(actif=True, categorie__in=session.tiroir.categories_vendues,
                                      prix_vente__gt=0).order_by("categorie", "ordre", "nom")
    form = CommandeForm(request.POST or None, articles=articles)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        client = d.get("client")
        try:
            with transaction.atomic():
                if d["paiement"] == "CREDIT" and not client and d.get("nouveau_client"):
                    client = Client.objects.create(nom=d["nouveau_client"].strip(), telephone=d["telephone"].strip())
                vendues = services.vendre_commande(session, request.user, d["lignes"], d["reglement"], mode=d["mode"],
                                                   sejour=d.get("sejour"), client=client,
                                                   observation=d.get("observation", ""))
        except ValidationError as exc:
            _erreurs_form(form, exc)
        else:
            # Écran de fin, comme une caisse enregistreuse : « C'est enregistré », imprimer le reçu, nouvelle commande.
            request.session["vente_terminee"] = {"message": _message_commande(vendues),
                                                 "recu": vendues[0].encaissement_id}
            return redirect("caisse:ventes")
    erreurs_paiement = any(form.errors.get(champ) for champ in
                           ("paiement", "sejour", "client", "nouveau_client", "telephone", "observation"))
    ventes = session.ventes.select_related("article", "sejour__chambre", "sejour__client", "client", "encaissement")
    return render(request, "caisse/ventes.html", {
        "form": form, "session": session, "familles": _familles(articles, session),
        "nom_pdv": nom_point_de_vente(session.tiroir), "est_boutique": session.tiroir.poste == Tiroir.Poste.RECEPTION,
        "panier": {str(k): v for k, v in form.quantites().items()} if form.is_bound else {},
        "billets_rapides": [500, 1000, 2000, 5000, 10000],
        "terminee": request.session.pop("vente_terminee", None) if request.method == "GET" else None,
        "ouvrir_paiement": erreurs_paiement, "ventes": ventes, "nb_ventes": ventes.filter(annulee=False).count(),
    })


def nom_point_de_vente(tiroir):
    """La réception vend la boutique ; la cuisine et le bar vendent boissons et plats."""
    return "Restaurant · Bar" if tiroir.poste == Tiroir.Poste.BAR else "Boutique"


def _familles(articles, session):
    """Les tuiles par famille : d'abord les plus vendus des 30 derniers jours, puis chaque rubrique."""
    articles = list(articles)
    par_id = {a.pk: a for a in articles}
    meilleurs = (VenteComptoir.objects.filter(session__tiroir=session.tiroir, annulee=False,
                                              date__gte=maintenant() - timedelta(days=30), article__in=par_id)
                 .values("article").annotate(n=Sum("quantite")).order_by("-n")[:12])
    familles = []
    if len(articles) > 12 and meilleurs:
        familles.append({"nom": "Les plus vendus", "articles": [par_id[m["article"]] for m in meilleurs],
                         "doublons": True})
    groupes = {}
    for a in articles:
        famille = a.rubrique or ("Plats" if a.categorie == Article.Categorie.RESTAURANT else a.get_categorie_display())
        groupes.setdefault(famille, []).append(a)
    familles += [{"nom": nom, "articles": liste} for nom, liste in groupes.items()]
    return familles


def _message_commande(vendues):
    total = format_fcfa(sum(v.montant for v in vendues))
    nombre = sum(v.quantite for v in vendues)
    articles = f"{nombre} article{'s' if nombre > 1 else ''}"
    v = vendues[0]
    if v.encaissement_id:
        mode = "espèces" if v.encaissement.mode == Encaissement.Mode.ESPECES else v.encaissement.get_mode_display()
        return f"{articles.capitalize()}, {total} payés en {mode}. Reçu n°{v.encaissement.numero_recu}."
    if v.sejour_id:
        return f"C'est noté sur la chambre {v.sejour.chambre.numero} ({v.sejour.client}) : {articles}, {total}."
    if v.client_id:
        return f"C'est noté à crédit pour {v.client} : {articles}, {total}."
    return f"C'est noté comme offert : {articles}, {total}."


@acces_requis(tient_caisse)
def vente_annuler(request, pk):
    vente = get_object_or_404(VenteComptoir.objects.select_related("article", "session__tiroir"), pk=pk)
    retour = "caisse:ventes"
    form = MotifForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.annuler_vente(vente, request.user, form.cleaned_data["motif"])
            messages.success(request, "Vente annulée : stock rétabli, encaissement contre-passé, chef de réception prévenu.")
            return redirect(retour if vente.session.statut == SessionCaisse.Statut.OUVERTE else "caisse:sessions")
        except ValidationError as exc:
            _erreurs_form(form, exc)
    commande = list(services.commande_de(vente))
    if len(commande) > 1:
        detail = ", ".join(f"{v.quantite} × {v.article}" for v in commande)
        return render(request, "form_page.html", {
            "form": form, "titre": f"Annuler la commande du reçu n°{vente.encaissement.numero_recu}",
            "sous_titre": f"{detail} - {format_fcfa(sum(v.montant for v in commande))}",
            "bouton": "Annuler toute la commande", "retour": retour,
            "intro": "Ce reçu couvre toute la commande : tous ses articles sont annulés ensemble et remis en stock. "
                     "Ensuite, ressaisissez la bonne commande. Rien n'est supprimé : l'annulation reste visible."})
    return render(request, "form_page.html", {
        "form": form, "titre": "Annuler une vente", "sous_titre": f"{vente} - {vente.montant:,} FCFA".replace(",", " "),
        "bouton": "Annuler la vente", "retour": retour,
        "intro": "Le stock est rétabli et l'encaissement contre-passé. Rien n'est supprimé : l'annulation reste visible."})


@acces_requis(acces_avarie)
def avarie(request):
    session = services.session_ouverte_de(request.user)
    form = AvarieForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            enregistrer_mouvement(d["article"], request.user, MouvementStock.Type.AVARIE, d["quantite"], d["motif"],
                                  journee=services.journee_de(session) if session else None)
            messages.success(request, "C'est noté : le produit sort du stock, le gérant est prévenu.")
            return redirect("caisse:ventes" if session else "stock:articles")
        except ValidationError as exc:
            _erreurs_form(form, exc)
    return render(request, "form_page.html", {
        "form": form, "titre": "Casse ou produit périmé", "retour": "caisse:ventes" if session else "stock:articles",
        "intro": "Une bouteille cassée, un produit qu'on ne peut plus vendre : il sort du stock sans être vendu "
                 "(colonne « Avaries » de la fiche de stock). Le gérant est prévenu."})


@acces_requis(tient_caisse)
def credits(request):
    return render(request, "caisse/credits.html", {"debiteurs": services.clients_debiteurs(),
                                                   "session": services.session_ouverte_de(request.user)})


@acces_requis(tient_caisse)
def credit_regler(request, pk):
    client = get_object_or_404(Client, pk=pk)
    session = services.session_ouverte_de(request.user)
    if session is None:
        messages.error(request, "Ouvrez d'abord votre session de caisse.")
        return redirect("caisse:ma_caisse")
    reste = services.dette_client(client)
    form = ReglementCreditForm(request.POST or None, initial={"montant": reste, "moyen": "ESPECES"})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            enc = services.regler_credit(session, request.user, client, d["montant"], d["mode"])
            messages.success(request, f"Règlement enregistré : reçu n°{enc.numero_recu}.")
            return redirect("caisse:recu_client", pk=enc.pk)
        except ValidationError as exc:
            _erreurs_form(form, exc)
    historique = client.credits_comptoir.filter(annulee=False).select_related("article")[:50]
    return render(request, "caisse/credit_regler.html", {"form": form, "client": client, "reste": reste,
                                                         "historique": historique,
                                                         "reglements": client.reglements.all()[:20]})


@acces_requis(validateur_caisse)
def recherche_encaissements(request):
    q = request.GET.get("q", "").strip()
    resultats = Encaissement.objects.none()
    if q:
        filtre = Q(reference__icontains=q) | Q(sejour__client__nom__icontains=q) | Q(client__nom__icontains=q)
        if q.isdigit():
            filtre |= Q(numero_recu=int(q))
        resultats = Encaissement.objects.filter(filtre).select_related("sejour__client", "utilisateur")[:100]
    return render(request, "caisse/recherche.html", {"q": q, "resultats": resultats})


# --- Saisie après coup d'un jour passé (gérant et adjoints) --------------------------------------------------------
def _jour_demande(request):
    from datetime import date

    hier = aujourd_hui() - timedelta(days=1)
    try:
        jour = date.fromisoformat(request.GET.get("date") or request.POST.get("date") or "")
    except ValueError:
        return hier
    return min(jour, hier)


@acces_requis(direction)
def jour_passe(request):
    """Saisir un jour passé (fiches papier, oubli) : les caisses, les chambres et les paiements, les ventes du bar."""
    from . import passe
    from .forms import CaissePasseeForm, PaiementPasseForm, SejourPasseForm, VentePasseeForm

    jour = _jour_demande(request)
    caisses = list(passe.caisses_du_jour(jour))
    reception = SessionCaisse.objects.filter(pk__in=[s.pk for s in caisses if s.tiroir.poste == Tiroir.Poste.RECEPTION])
    bar = SessionCaisse.objects.filter(pk__in=[s.pk for s in caisses if s.tiroir.poste == Tiroir.Poste.BAR])
    sejours = passe.sejours_du_jour(jour)

    def seule(qs):
        return qs.first() if qs.count() == 1 else None

    data = request.POST if request.method == "POST" else None
    action = request.POST.get("action") if data else None
    forms = {
        "caisse": CaissePasseeForm(data if action == "caisse" else None, prefix="caisse",
                                   initial={"tiroir": Tiroir.objects.filter(poste=Tiroir.Poste.RECEPTION).first(),
                                            "shift": "MATIN"}),
        "sejour": SejourPasseForm(data if action == "sejour" else None, prefix="sejour",
                                  initial={"date_arrivee": jour, "nuits": 1}),
        "paiement": PaiementPasseForm(data if action == "paiement" else None, prefix="paiement", sejours=sejours,
                                      sessions=reception, initial={"session": seule(reception), "moyen": "ESPECES",
                                                                   "nature": "ACOMPTE"}),
        "vente": VentePasseeForm(data if action == "vente" else None, prefix="vente", sejours=sejours,
                                 sessions=bar, initial={"session": seule(bar), "paiement": "ESPECES", "quantite": 1}),
    }
    if data:
        form = forms.get(action)
        try:
            if form is not None and form.is_valid():
                d = form.cleaned_data
                if action == "caisse":
                    passe.ajouter_caisse(request.user, jour, d["tiroir"], d["titulaire"], d["shift"],
                                         d["heure_ouverture"], d["ouverture"], d["heure_fermeture"], d["fermeture"])
                    messages.success(request, f"Caisse de {d['titulaire']} du {jour:%d/%m/%Y} enregistrée.")
                elif action == "sejour":
                    s = passe.sejour_passe(request.user, nom=d["nom"], telephone=d["telephone"], chambre=d["chambre"],
                                           arrivee=d["date_arrivee"], nuits=d["nuits"],
                                           heure_arrivee=d["heure_arrivee"], heure_depart=d["heure_depart"],
                                           tarif=d["tarif_nuit"], motif_tarif=d["motif_tarif"])
                    messages.success(request, f"{s.client} enregistré en chambre {s.chambre.numero} "
                                              f"({s.get_statut_display().lower()}).")
                elif action == "paiement":
                    e = passe.paiement_passe(request.user, d["session"], d["sejour"], d["nature"], d["mode"],
                                             d["montant"], d["heure"], d.get("reference", ""))
                    messages.success(request, f"Paiement de {format_fcfa(e.montant)} enregistré : reçu n°{e.numero_recu}.")
                elif action == "vente":
                    v = passe.vente_passee(request.user, d["session"], d["article"], d["quantite"], d["paiement"],
                                           d["heure"], sejour=d.get("sejour"), motif=d.get("motif", ""))
                    messages.success(request, f"Vente enregistrée : {v}.")
                return redirect(f"{reverse('caisse:jour_passe')}?date={jour.isoformat()}#{action}")
            if form is None and action in ("supprimer_caisse", "annuler_paiement", "annuler_vente", "supprimer_sejour"):
                cible = request.POST.get("pk")
                if action == "supprimer_caisse":
                    passe.supprimer_caisse(request.user, get_object_or_404(SessionCaisse, pk=cible, saisie_passee=True))
                    messages.success(request, "Caisse supprimée.")
                elif action == "annuler_paiement":
                    passe.annuler_paiement(request.user, get_object_or_404(Encaissement, pk=cible,
                                                                           session__saisie_passee=True))
                    messages.success(request, "Paiement annulé.")
                elif action == "annuler_vente":
                    passe.annuler_vente(request.user, get_object_or_404(VenteComptoir, pk=cible,
                                                                        session__saisie_passee=True))
                    messages.success(request, "Vente annulée.")
                else:
                    from hotel.models import Sejour

                    passe.supprimer_sejour(request.user, get_object_or_404(Sejour, pk=cible, saisi_apres_coup=True))
                    messages.success(request, "Séjour supprimé.")
                return redirect(f"{reverse('caisse:jour_passe')}?date={jour.isoformat()}")
        except ValidationError as exc:
            if form is not None:
                form.add_error(None, exc)
            else:
                messages.error(request, " ".join(exc.messages))
    paiements = (Encaissement.objects.filter(session__in=reception, sejour__isnull=False)
                 .select_related("sejour__chambre", "sejour__client", "annule", "session__receptionniste")
                 .order_by("date", "pk"))
    return render(request, "caisse/jour_passe.html", {
        "jour": jour, "veille": jour - timedelta(days=1), "lendemain": jour + timedelta(days=1),
        "hier": aujourd_hui() - timedelta(days=1), "caisses": caisses,
        "sejours": sejours, "paiements": paiements, "ventes": passe.ventes_du_jour(jour), "forms": forms,
        "ouvert": action if data else "", "a_reception": reception.exists(), "a_bar": bar.exists()})

from datetime import datetime, timedelta

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from caisse.models import Encaissement, SessionCaisse, SortieCaisse
from caisse.services import session_ouverte_de
from hotel.models import Chambre, Extra, Nuitee, Sejour
from personnel.models import Affectation, DemandeConge, Pointage, Statut
from personnel.services import employes_geres
from projets.models import Tache
from stock.models import Article
from vitrine.views import page_vitrine

from .forms import FormulaireModele
from .models import Alerte, Etablissement, JournalAction
from .permissions import acces_requis, encadrement, gerant
from .taches import executer_taches_periodiques
from .utils import aujourd_hui, journaliser


def accueil(request):
    """Visiteur : la page de présentation. Client : son espace. Personnel : sa saisie ou le tableau de bord."""
    user = request.user
    if not user.is_authenticated:
        return page_vitrine(request)
    if user.est_client:
        return redirect("vitrine:espace")
    if user.est_terrain:
        # Le personnel arrive directement sur la saisie de son département : c'est l'écran de son poste.
        return redirect("postes:poste")
    if user.peut_valider_caisse:
        executer_taches_periodiques()
    jour = aujourd_hui()
    debut_jour = timezone.make_aware(datetime.combine(jour, datetime.min.time()))
    ctx = {"jour": jour}

    if user.voit_reception:
        chambres = Chambre.objects.filter(active=True)
        ctx.update({
            "nb_chambres": chambres.count(),
            "nb_occupees": chambres.filter(statut=Chambre.Statut.OCCUPEE).count(),
            "nb_a_nettoyer": chambres.filter(statut=Chambre.Statut.A_NETTOYER).count(),
            "arrivees": Sejour.objects.filter(statut=Sejour.Statut.RESERVE, date_arrivee__lte=jour).select_related(
                "client", "chambre"),
            "departs": Sejour.objects.filter(statut=Sejour.Statut.EN_COURS, date_depart__lte=jour).select_related(
                "client", "chambre"),
        })
    if user.tient_caisse:
        ctx["ma_session"] = session_ouverte_de(user)
    if user.peut_valider_caisse:
        a_valider = SessionCaisse.objects.filter(statut__in=[SessionCaisse.Statut.REMISE, SessionCaisse.Statut.ECART])
        ctx.update({
            "sessions_ouvertes": SessionCaisse.objects.filter(statut=SessionCaisse.Statut.OUVERTE,
                                                              est_rectificative=False).select_related("receptionniste"),
            "nb_a_valider": a_valider.count(),
            "nb_ecarts": a_valider.filter(statut=SessionCaisse.Statut.ECART).count(),
            "nb_sorties_a_valider": SortieCaisse.objects.filter(statut=SortieCaisse.Statut.A_VALIDER).count(),
        })
    if user.est_direction:
        ctx.update({
            "encaisse_jour": Encaissement.objects.filter(date__gte=debut_jour).aggregate(s=Sum("montant_signe"))["s"] or 0,
            "recette_jour": (Nuitee.objects.filter(date_nuit=jour - timedelta(days=1)).aggregate(s=Sum("montant"))["s"]
                             or 0) + (Extra.objects.filter(statut=Extra.Statut.ACTIF, date_conso__gte=debut_jour)
                                      .aggregate(s=Sum("montant"))["s"] or 0),
            "stock_bas": [a for a in Article.objects.filter(actif=True, suivi_stock=True) if a.est_bas],
            "alertes": Alerte.visibles_par(user).filter(lue_le__isnull=True)[:8],
        })
    if user.est_encadrement:
        geres = employes_geres(user)
        ctx.update({
            "equipe_du_jour": Affectation.objects.filter(date=jour, employe__in=geres).select_related(
                "employe", "creneau"),
            "pointes": set(Pointage.objects.filter(date=jour, employe__in=geres).values_list("employe_id", flat=True)),
            "conges_en_attente": DemandeConge.objects.filter(statut=Statut.EN_ATTENTE, employe__in=geres).count(),
        })
    employe = user.profil_employe
    if employe:
        ctx.update({
            "mon_planning": Affectation.objects.filter(employe=employe, date__gte=jour,
                                                       date__lte=jour + timedelta(days=6)).select_related("creneau"),
            "pointage_ouvert": Pointage.objects.filter(employe=employe, depart__isnull=True).first(),
        })
    ctx["mes_taches"] = Tache.objects.filter(assigne_a=user).exclude(statut=Tache.Statut.FAITE).select_related(
        "projet")[:6]
    return render(request, "core/accueil.html", ctx)


@acces_requis(encadrement)
def alertes(request):
    qs = Alerte.visibles_par(request.user)
    if request.method == "POST":
        ids = request.POST.getlist("alerte")
        qs.filter(pk__in=ids, lue_le__isnull=True).update(lue_le=timezone.now(), lue_par=request.user)
        messages.success(request, "Alertes marquées comme lues.")
        return redirect("core:alertes")
    return render(request, "core/alertes.html", {"non_lues": qs.filter(lue_le__isnull=True),
                                                 "lues": qs.filter(lue_le__isnull=False)[:50]})


@acces_requis(gerant)
def journal(request):
    qs = JournalAction.objects.select_related("utilisateur")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(action__icontains=q) | qs.filter(objet__icontains=q) | qs.filter(utilisateur__username__icontains=q)
    return render(request, "core/journal.html", {"actions": qs[:300], "q": q})


class EtablissementForm(FormulaireModele):
    class Meta:
        model = Etablissement
        fields = ["nom", "slogan", "presentation", "adresse", "telephone", "email", "niu"]


@acces_requis(gerant)
def parametres(request):
    return render(request, "core/parametres.html", {"etablissement": Etablissement.get()})


@acces_requis(gerant)
def etablissement(request):
    form = EtablissementForm(request.POST or None, instance=Etablissement.get())
    if request.method == "POST" and form.is_valid():
        form.save()
        journaliser(request.user, "Établissement modifié", form.instance)
        messages.success(request, "Coordonnées enregistrées.")
        return redirect("core:parametres")
    intro = ("Ces coordonnées figurent en tête des reçus et rapports PDF, et sur la page d'accueil publique "
             "(avec le slogan et la présentation).")
    return render(request, "form_page.html", {"form": form, "titre": "Établissement", "retour": "core:parametres",
                                              "intro": intro})


@require_POST
@acces_requis(encadrement)
def alerte_lue(request, pk):
    alerte = get_object_or_404(Alerte.visibles_par(request.user), pk=pk)
    alerte.lue_le = timezone.now()
    alerte.lue_par = request.user
    alerte.save(update_fields=["lue_le", "lue_par"])
    return redirect(alerte.lien or "core:alertes")

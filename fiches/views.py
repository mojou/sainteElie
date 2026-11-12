from datetime import date, timedelta

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from caisse.models import SessionCaisse, Tiroir
from caisse.services import journee_de, sessions_visibles
from core.permissions import acces_requis, caisse, encadrement, menage, reception, stock
from core.utils import aujourd_hui
from stock.models import Article

from . import pdf, services

CATEGORIES = {"bar": Article.Categorie.BAR, "cuisine": Article.Categorie.RESTAURANT,
              "boutique": Article.Categorie.BOUTIQUE}


def acces_fiches(u):
    return caisse(u) or stock(u)


def voit_poste(u, poste):
    """Le bar voit les fiches du bar ; la réception, celles de la boutique ; l'encadrement voit tout."""
    if u.est_gerant or u.est_chef_reception or stock(u):
        return True
    return u.est_bar if poste == Tiroir.Poste.BAR else u.est_reception


def _categorie(request, categorie):
    if categorie not in CATEGORIES:
        raise Http404
    poste = services.poste_de(CATEGORIES[categorie])
    if not voit_poste(request.user, poste):
        raise PermissionDenied("Cette fiche appartient à un autre poste.")
    return CATEGORIES[categorie], poste


def _jour(request):
    try:
        return date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        return aujourd_hui()


def _pdf(contenu, nom):
    reponse = HttpResponse(contenu, content_type="application/pdf")
    reponse["Content-Disposition"] = f'inline; filename="{nom}"'
    return reponse


def _contexte(jour, poste=None, **extra):
    return {"jour": jour, "veille": (jour - timedelta(days=1)).isoformat(),
            "lendemain": (jour + timedelta(days=1)).isoformat(),
            "receptionnistes": services.receptionnistes_du_jour(jour, poste), **extra}


@acces_requis(acces_fiches)
def index(request):
    jour = _jour(request)
    sessions = (sessions_visibles(request.user).filter(est_rectificative=False, ventes__journee=jour)
                .select_related("tiroir").distinct())
    u = request.user
    return render(request, "fiches/index.html", _contexte(
        jour, sessions=sessions, voit_bar=voit_poste(u, Tiroir.Poste.BAR),
        voit_reception=voit_poste(u, Tiroir.Poste.RECEPTION), voit_chambres=reception(u)))


@acces_requis(acces_fiches)
def main_courante(request, categorie):
    cat, poste = _categorie(request, categorie)
    jour = _jour(request)
    session = None
    sessions = None
    if request.GET.get("session"):
        session = get_object_or_404(sessions_visibles(request.user), pk=request.GET["session"])
        jour = journee_de(session)
        sessions = [session]
    elif not (request.user.peut_valider_caisse or stock(request.user)):
        # Chacun voit sa propre main courante, pas celle de ses collègues.
        sessions = list(SessionCaisse.objects.filter(receptionniste=request.user, ventes__journee=jour).distinct())
    donnees = services.main_courante(jour, cat, sessions)
    titre = f"MAIN COURANTE {categorie.upper()}"
    qui = "Cuisine / Bar" if poste == Tiroir.Poste.BAR else "Réceptionniste(s)"
    if sessions is None:
        noms = services.receptionnistes_du_jour(jour, poste)
    else:
        noms = [f"{s.receptionniste} ({s.get_shift_display()})" for s in sessions] or [str(request.user)]
    if request.GET.get("format") == "pdf":
        return _pdf(pdf.main_courante_pdf(titre, jour, noms, donnees, qui=qui), f"main-courante-{categorie}-{jour}.pdf")
    return render(request, "fiches/main_courante.html", _contexte(jour, poste, d=donnees, titre=titre,
                                                                  categorie=categorie, session=session, noms=noms,
                                                                  qui=qui))


@acces_requis(acces_fiches)
def fiche_stock(request, categorie):
    if categorie == "cuisine":
        raise Http404("Les plats n'ont pas de fiche de stock.")
    cat, poste = _categorie(request, categorie)
    jour = _jour(request)
    donnees = services.fiche_stock(jour, cat)
    noms = services.receptionnistes_du_jour(jour, poste)
    if request.GET.get("format") == "pdf":
        if categorie == "bar":
            contenu = pdf.stock_bar_pdf(jour, noms, donnees)
        else:
            contenu = pdf.stock_boutique_pdf(jour, noms, donnees, services.main_courante(jour, cat))
        return _pdf(contenu, f"stock-{categorie}-{jour}.pdf")
    return render(request, f"fiches/stock_{categorie}.html", _contexte(jour, poste, d=donnees, categorie=categorie))


@acces_requis(reception)
def hebergement(request):
    jour = _jour(request)
    donnees = services.fiche_hebergement(jour)
    if request.GET.get("format") == "pdf":
        return _pdf(pdf.hebergement_pdf(jour, services.receptionnistes_du_jour(jour, Tiroir.Poste.RECEPTION), donnees),
                    f"recette-chambres-{jour}.pdf")
    return render(request, "fiches/hebergement.html", _contexte(jour, Tiroir.Poste.RECEPTION, d=donnees))


@acces_requis(menage)
def chambres_a_faire(request):
    """Fiche du ménage du jour, à imprimer : le personnel des chambres n'a pas de compte."""
    jour = _jour(request)
    return _pdf(pdf.chambres_a_faire_pdf(jour, services.chambres_a_faire(jour), services.equipe_chambres()),
                f"chambres-a-faire-{jour}.pdf")


def note_le_gardiennage(u):
    return u.departement == "SECURITE" or reception(u) or encadrement(u)


@acces_requis(note_le_gardiennage)
def main_courante_gardien(request):
    """Feuille vierge pour la nuit du gardien, qui n'a pas de compte : la réception recopie le matin."""
    jour = _jour(request)
    return _pdf(pdf.main_courante_gardien_pdf(jour), f"main-courante-gardien-{jour}.pdf")

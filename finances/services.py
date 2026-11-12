"""Bilan mensuel : recettes constatées, encaissements, dépenses et résultat simplifié."""
import calendar
from datetime import datetime

from django.db.models import Sum
from django.utils import timezone

from caisse.models import Encaissement, SortieCaisse, VenteComptoir, Virement, totaux_par_moyen
from caisse.services import resume_comptoir
from core.utils import mois_suivant
from hotel.models import Chambre, Extra, Nuitee
from paie.models import FichePaie

from .models import Depense


def _bornes(mois):
    debut = timezone.make_aware(datetime.combine(mois, datetime.min.time()))
    fin = timezone.make_aware(datetime.combine(mois_suivant(mois), datetime.min.time()))
    return debut, fin


def bilan_mois(mois):
    debut, fin = _bornes(mois)
    nuitees = Nuitee.objects.filter(date_nuit__gte=mois, date_nuit__lt=mois_suivant(mois))
    recettes_chambres = nuitees.aggregate(s=Sum("montant"))["s"] or 0
    recettes_extras = Extra.objects.filter(statut=Extra.Statut.ACTIF, date_conso__gte=debut,
                                           date_conso__lt=fin).aggregate(s=Sum("montant"))["s"] or 0
    comptoir = resume_comptoir(VenteComptoir.objects.filter(journee__gte=mois, journee__lt=mois_suivant(mois),
                                                            annulee=False))
    encaissements = Encaissement.objects.filter(date__gte=debut, date__lt=fin)
    par_mode = {m["libelle"]: m["montant"] for m in totaux_par_moyen(encaissements)}
    virements = Virement.objects.filter(date_valeur__gte=mois, date_valeur__lt=mois_suivant(mois)).aggregate(
        s=Sum("montant"))["s"] or 0
    depenses = Depense.objects.filter(date__gte=mois, date__lt=mois_suivant(mois))
    par_categorie = [(Depense.Categorie(c["categorie"]).label, c["total"])
                     for c in depenses.values("categorie").annotate(total=Sum("montant")).order_by("-total")]
    total_depenses = depenses.aggregate(s=Sum("montant"))["s"] or 0
    depenses_tiroir = SortieCaisse.objects.filter(
        type=SortieCaisse.Type.DEPENSE, date__gte=debut, date__lt=fin).exclude(
        statut=SortieCaisse.Statut.REFUSEE).aggregate(s=Sum("montant"))["s"] or 0
    salaires = FichePaie.objects.filter(mois=mois).exclude(statut=FichePaie.Statut.BROUILLON).aggregate(
        s=Sum("net_a_payer"))["s"] or 0
    nb_chambres = Chambre.objects.filter(active=True).count()
    jours = calendar.monthrange(mois.year, mois.month)[1]
    capacite = nb_chambres * jours
    recettes = recettes_chambres + recettes_extras + comptoir["recette"]
    charges = total_depenses + depenses_tiroir + salaires
    return {
        "mois": mois, "recettes_chambres": recettes_chambres, "recettes_extras": recettes_extras,
        "recettes": recettes, "nb_nuitees": nuitees.count(), "comptoir": comptoir,
        "taux_occupation": round(100 * nuitees.count() / capacite) if capacite else 0,
        "prix_moyen": round(recettes_chambres / nuitees.count()) if nuitees.count() else 0,
        "encaissements_par_mode": par_mode, "virements": virements,
        "total_encaisse": sum(par_mode.values()) + virements,
        "depenses_par_categorie": par_categorie, "total_depenses": total_depenses,
        "depenses_tiroir": depenses_tiroir, "salaires": salaires, "charges": charges,
        "resultat": recettes - charges,
    }

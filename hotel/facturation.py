"""
La facture d'un séjour : ce qui est facturé (nuits, extras), ce qui est déjà payé, ce qui reste.

Une seule source pour la page à imprimer, le PDF et l'espace client. Le total des lignes est toujours égal à
`Sejour.total_facture` : nuits prévues tant que le client est là, nuits constatées une fois parti.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

from core.models import Etablissement
from core.utils import aujourd_hui, format_fcfa

from .models import Extra, Sejour


@dataclass
class Ligne:
    designation: str
    detail: str = ""
    quantite: int = 1
    prix: int = 0
    montant: int = 0


@dataclass
class Paiement:
    date: date
    libelle: str
    montant: int


@dataclass
class Facture:
    sejour: Sejour
    etablissement: Etablissement
    numero: str
    date: date
    definitive: bool
    lignes: list = field(default_factory=list)
    paiements: list = field(default_factory=list)

    @property
    def titre(self):
        return "Facture" if self.definitive else "Facture provisoire"

    @property
    def total(self):
        return sum(ligne.montant for ligne in self.lignes)

    @property
    def total_paye(self):
        return sum(p.montant for p in self.paiements)

    @property
    def reste(self):
        return self.total - self.total_paye

    @property
    def soldee(self):
        """Tout est réglé : la facture porte le tampon « Payée »."""
        return self.total > 0 and self.reste == 0

    @property
    def a_rendre(self):
        return max(-self.reste, 0)


def numero_facture(sejour):
    """2026-0012 : l'année d'arrivée et le numéro du séjour (unique, ne change jamais)."""
    return f"{sejour.date_arrivee:%Y}-{sejour.pk:04d}"


def _jours(debut, fin):
    return f"du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"


def _chambre(sejour):
    chambre = sejour.chambre
    return f"Chambre {chambre.numero} ({chambre.get_categorie_display().lower()})"


def _detail_tarif(sejour):
    if sejour.gratuite:
        return sejour.get_gratuite_display()
    if sejour.tarif_nuit < sejour.tarif_grille:
        return f"prix normal {format_fcfa(sejour.tarif_grille)} la nuit, remise de {sejour.remise_pct} %"
    return ""


def _lignes_chambre(sejour):
    constatees = sejour.statut in (Sejour.Statut.TERMINE, Sejour.Statut.ANNULE, Sejour.Statut.NO_SHOW)
    if not constatees:
        if not sejour.nb_nuits:
            return []
        detail = ", ".join(x for x in [_jours(sejour.date_arrivee, sejour.date_depart), _detail_tarif(sejour)] if x)
        return [Ligne(_chambre(sejour), detail, sejour.nb_nuits, sejour.tarif_nuit, sejour.montant_chambre_prevu)]

    # Nuits réellement passées : une ligne par prix (le prix peut avoir changé en cours de séjour).
    groupes = {}
    for nuitee in sejour.nuitees.order_by("date_nuit"):
        groupes.setdefault(nuitee.montant, []).append(nuitee.date_nuit)
    if sejour.statut == Sejour.Statut.NO_SHOW:
        designation = f"{_chambre(sejour)} - client non venu"
    elif sejour.statut == Sejour.Statut.ANNULE:
        designation = f"{_chambre(sejour)} - réservation annulée"
    else:
        designation = _chambre(sejour)
    lignes = []
    for prix, nuits in groupes.items():
        dates = (_jours(nuits[0], nuits[-1] + timedelta(days=1)) if len(nuits) > 1
                 else f"nuit du {nuits[0]:%d/%m/%Y}")
        detail = ", ".join(x for x in [dates, _detail_tarif(sejour) if prix == sejour.tarif_nuit else ""] if x)
        lignes.append(Ligne(designation, detail, len(nuits), prix, prix * len(nuits)))
    return lignes


def _lignes_extras(sejour):
    lignes = []
    for extra in sejour.extras.filter(statut=Extra.Statut.ACTIF).order_by("date_conso", "pk"):
        moment = timezone.localtime(extra.date_conso)
        detail = f"{extra.get_source_display()}, le {moment:%d/%m à %H:%M}"
        if extra.numero_bon:
            detail += f", bon n°{extra.numero_bon}"
        lignes.append(Ligne(extra.description, detail, 1, extra.montant, extra.montant))
    return lignes


def _paiements(sejour):
    paiements = []
    for e in sejour.encaissements.select_related("annule").order_by("date", "pk"):
        libelle = f"Reçu n°{e.numero_recu} - {e.get_nature_display()} - {e.get_mode_display()}"
        if e.reference:
            libelle += f" (réf. {e.reference})"
        if e.annule_id:
            libelle += f" - annule le reçu n°{e.annule.numero_recu}"
        paiements.append(Paiement(timezone.localtime(e.date).date(), libelle, e.montant_signe))
    for v in sejour.virements.order_by("date_valeur", "pk"):
        paiements.append(Paiement(v.date_valeur, f"Virement bancaire (réf. {v.reference_bancaire})", v.montant))
    return sorted(paiements, key=lambda p: p.date)


def facture(sejour):
    definitive = sejour.statut in (Sejour.Statut.TERMINE, Sejour.Statut.ANNULE, Sejour.Statut.NO_SHOW)
    if sejour.statut == Sejour.Statut.TERMINE and sejour.check_out_le:
        jour = timezone.localtime(sejour.check_out_le).date()
    else:
        jour = aujourd_hui()
    return Facture(sejour=sejour, etablissement=Etablissement.get(), numero=numero_facture(sejour), date=jour,
                   definitive=definitive, lignes=_lignes_chambre(sejour) + _lignes_extras(sejour),
                   paiements=_paiements(sejour))

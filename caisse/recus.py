"""
Le reçu remis au client pour chaque encaissement : même contenu sur la page à imprimer et dans le PDF.
"""
from dataclasses import dataclass, field

from django.utils import timezone

from core.models import Etablissement

from .models import Encaissement


@dataclass
class LigneRecu:
    designation: str
    quantite: int
    prix: int
    montant: int


@dataclass
class Recu:
    e: Encaissement
    etablissement: Etablissement
    titre: str
    libelle_montant: str
    libelle_mode: str
    objet: str
    client: str = ""
    telephone: str = ""
    lignes: list = field(default_factory=list)
    annule_par: Encaissement | None = None
    situation: list = field(default_factory=list)   # [(libellé, montant)] : le séjour ou la dette, à ce jour
    reste: int | None = None

    @property
    def date(self):
        return timezone.localtime(self.e.date)

    @property
    def solde(self):
        """Plus rien à payer (séjour ou ardoise)."""
        return self.reste is not None and self.reste <= 0

    @property
    def a_rendre(self):
        """Le client a trop payé : l'hôtel lui doit cette somme."""
        return max(-self.reste, 0) if self.reste is not None else 0


def _titre(e):
    if e.nature == Encaissement.Nature.REMBOURSEMENT:
        return "Reçu de remboursement", "Montant remboursé", "Rendu en"
    if e.nature == Encaissement.Nature.ANNULATION:
        return "Annulation de reçu", "Montant annulé", "Moyen de paiement :"
    return "Reçu de paiement", "Montant reçu", "Payé en"


def _objet(e, lignes):
    if e.nature == Encaissement.Nature.ANNULATION and e.annule_id:
        return f"Annulation du reçu n°{e.annule.numero_recu}" + (f" ({e.motif})" if e.motif else "")
    if e.sejour_id:
        s = e.sejour
        nuits = f"{s.nb_nuits} nuit{'s' if s.nb_nuits > 1 else ''}"
        quoi = {Encaissement.Nature.ACOMPTE: "Acompte", Encaissement.Nature.REGLEMENT: "Règlement",
                Encaissement.Nature.REMBOURSEMENT: "Remboursement"}.get(e.nature, e.get_nature_display())
        return (f"{quoi} - séjour en chambre {s.chambre.numero}, du {s.date_arrivee:%d/%m/%Y} "
                f"au {s.date_depart:%d/%m/%Y} ({nuits})")
    if lignes:
        return "Consommations"
    if e.client_id:
        return "Règlement d'une somme due (ardoise)"
    return e.get_nature_display()


def recu(e):
    from vitrine.models import CommandePlats

    from . import services

    titre, libelle_montant, libelle_mode = _titre(e)
    lignes = [LigneRecu(str(v.article), v.quantite, v.prix_unitaire, v.montant)
              for v in e.ventes.select_related("article").order_by("pk")]
    r = Recu(e=e, etablissement=Etablissement.get(), titre=titre, libelle_montant=libelle_montant,
             libelle_mode=libelle_mode, objet=_objet(e, lignes), lignes=lignes,
             annule_par=e.annulations.order_by("date").first())
    if e.sejour_id:
        s = e.sejour
        r.client, r.telephone = s.client.nom, s.client.telephone
        r.reste = s.reste_a_payer
        r.situation = [("Total du séjour" + ("" if s.statut == s.Statut.TERMINE else " (prévu)"), s.total_facture),
                       ("Total déjà payé", s.total_paye)]
    elif e.client_id:
        r.client, r.telephone = e.client.nom, e.client.telephone
        r.reste = services.dette_client(e.client)
    else:
        commande = CommandePlats.objects.filter(encaissement=e).first()
        if commande:
            r.client, r.telephone = commande.nom, commande.telephone
    return r

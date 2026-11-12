from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from core.pdf import DocumentPDF, montant_pdf
from core.utils import journaliser, maintenant
from personnel.models import Employe

from .models import FichePaie

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


def libelle_mois(premier):
    return f"{MOIS[premier.month - 1]} {premier.year}"


def generer_fiches(mois, user):
    """Crée en brouillon la fiche du mois de chaque employé actif qui n'en a pas encore."""
    creees = 0
    for employe in Employe.objects.filter(actif=True):
        fiche, cree = FichePaie.objects.get_or_create(employe=employe, mois=mois,
                                                      defaults={"salaire_base": employe.salaire_base})
        if cree:
            fiche.calculer()
            fiche.save()
            creees += 1
    journaliser(user, "Fiches de paie générées", libelle_mois(mois), f"{creees} fiche(s)")
    return creees


def fiche_pdf(fiche):
    e = fiche.employe
    doc = DocumentPDF(f"Bulletin de paie - {libelle_mois(fiche.mois)}", f"{e} - {e.poste}")
    doc.cles_valeurs([
        ("Employé", str(e)), ("Poste", e.poste), ("Département", e.get_departement_display()),
        ("Date d'embauche", e.date_embauche.strftime("%d/%m/%Y") if e.date_embauche else "-"),
        ("N° CNPS", e.numero_cnps or "-"),
    ])
    doc.section("Éléments de paie")
    lignes = [["Salaire de base", montant_pdf(fiche.salaire_base)], ["Primes", montant_pdf(fiche.primes)],
              ["Heures supplémentaires", montant_pdf(fiche.heures_sup)], ["Salaire brut", montant_pdf(fiche.brut)],
              ["Cotisations salariales", "- " + montant_pdf(fiche.cotisations)],
              ["Autres retenues" + (f" ({fiche.motif_retenues})" if fiche.motif_retenues else ""),
               "- " + montant_pdf(fiche.retenues)]]
    for acompte in fiche.acomptes_du_mois():
        lignes.append([f"Acompte du {acompte.date:%d/%m/%Y}" + (f" ({acompte.motif})" if acompte.motif else ""),
                       "- " + montant_pdf(acompte.montant)])
    doc.tableau(["Libellé", "Montant"], lignes, total=["Net à payer", montant_pdf(fiche.net_a_payer)])
    doc.espace(6)
    doc.signatures(["L'employeur", "L'employé (lu et approuvé)"], titre="Signatures")
    return doc.rendre()


def valider_fiche(fiche, user):
    if fiche.statut != FichePaie.Statut.BROUILLON:
        raise ValidationError("Cette fiche est déjà validée.")
    with transaction.atomic():
        fiche.calculer()
        fiche.statut = FichePaie.Statut.VALIDEE
        fiche.validee_par = user
        fiche.validee_le = maintenant()
        fiche.save()
    fiche.pdf.save(f"paie-{fiche.employe_id}-{fiche.mois:%Y-%m}.pdf", ContentFile(fiche_pdf(fiche)), save=True)
    journaliser(user, "Fiche de paie validée", fiche, f"net {fiche.net_a_payer}")


def marquer_payee(fiche, user, date, mode):
    if fiche.statut != FichePaie.Statut.VALIDEE:
        raise ValidationError("Seule une fiche validée peut être marquée payée.")
    fiche.statut = FichePaie.Statut.PAYEE
    fiche.payee_le = date
    fiche.mode_paiement = mode
    fiche.save(update_fields=["statut", "payee_le", "mode_paiement"])
    journaliser(user, "Salaire payé", fiche, mode)

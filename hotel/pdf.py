from core.pdf import DocumentPDF, montant_pdf
from core.utils import montant_en_lettres


def facture_pdf(f):
    """La facture d'un séjour en PDF (à envoyer par WhatsApp ou par e-mail, ou à imprimer)."""
    sejour = f.sejour
    client = sejour.client
    doc = DocumentPDF(f"{f.titre} n° {f.numero}", f"Date : {f.date:%d/%m/%Y}")
    facture_a = [("Facturé à", client.nom)]
    if client.entreprise:
        facture_a.append(("Entreprise", client.entreprise))
    facture_a.append(("Téléphone", client.telephone))
    facture_a += [
        ("Séjour", f"Chambre {sejour.chambre.numero}, du {sejour.date_arrivee:%d/%m/%Y} au "
                   f"{sejour.date_depart:%d/%m/%Y} ({sejour.nb_nuits} nuit{'s' if sejour.nb_nuits > 1 else ''}, "
                   f"{sejour.nb_personnes} personne{'s' if sejour.nb_personnes > 1 else ''})"),
    ]
    doc.cles_valeurs(facture_a, largeur_cle=35)
    doc.section("Détail")
    doc.tableau(["Désignation", "Qté", "Prix unitaire", "Montant"],
                [[ligne.designation + (f" - {ligne.detail}" if ligne.detail else ""), str(ligne.quantite),
                  montant_pdf(ligne.prix), montant_pdf(ligne.montant)] for ligne in f.lignes],
                total=["Total", "", "", montant_pdf(f.total)], alignement_droite=(1, 2, 3), largeurs=(9, 1.2, 2.6, 2.6))
    if f.paiements:
        doc.section("Paiements reçus")
        doc.tableau(["Date", "Détail", "Montant"],
                    [[f"{p.date:%d/%m/%Y}", p.libelle, montant_pdf(p.montant)] for p in f.paiements],
                    total=["", "Total payé", montant_pdf(f.total_paye)], alignement_droite=(2,), largeurs=(2, 9, 2.6))
    lignes = [("Total de la facture", montant_pdf(f.total)), ("Déjà payé", montant_pdf(f.total_paye))]
    if f.a_rendre:
        lignes.append(("À rendre au client", montant_pdf(f.a_rendre)))
    elif f.soldee:
        lignes.append(("Reste à payer", "Rien - payée"))
    else:
        lignes.append(("Reste à payer", montant_pdf(f.reste)))
    doc.totaux(lignes)
    doc.espace(3)
    doc.paragraphe(f"Arrêtée la présente facture à la somme de : {montant_en_lettres(f.total) or 'zéro franc CFA'}.")
    if not f.definitive:
        doc.paragraphe("Facture provisoire : le montant définitif est calculé au départ du client, "
                       "d'après les nuits passées et les consommations.", petit=True)
    doc.signatures(["Pour la direction", "Le client"])
    doc.espace(3)
    doc.paragraphe(f"Merci de votre confiance et à bientôt au {f.etablissement.nom}.", petit=True)
    return doc.rendre()

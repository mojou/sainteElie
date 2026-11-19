"""Fiches PDF imprimables, colonne pour colonne comme les fiches papier de l'hôtel."""
from datetime import timedelta
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.models import Etablissement
from core.pdf import DocumentPDF, _echapper, texte_pdf
from core.utils import format_fcfa


def n(valeur, vide_si_zero=True):
    if vide_si_zero and not valeur:
        return ""
    return texte_pdf(format_fcfa(valeur, unite=False))


def q(valeur):
    """Quantité : zéro affiché (un stock nul est une information)."""
    return str(valeur)


def _entete(jour, receptionnistes, extra="", qui="Réceptionniste(s)"):
    noms = ", ".join(receptionnistes) or "-"
    return f"Date : {jour:%d/%m/%Y}  -  {qui} : {noms}{extra}"


def main_courante_pdf(titre, jour, receptionnistes, donnees, qui="Réceptionniste(s)"):
    doc = DocumentPDF(titre, _entete(jour, receptionnistes, qui=qui))
    _tableau_main_courante(doc, donnees)
    doc.espace(6)
    doc.signatures([qui.replace("(s)", ""), "Chef de réception / gérant"])
    return doc.rendre()


def _tableau_main_courante(doc, donnees):
    t = donnees["totaux"]
    doc.tableau(
        ["Désignation", "Qté V", "Cash", "Crédit", "Total", "Offre", "Obs"],
        [[str(x["article"]), q(x["quantite"]), n(x["cash"]), n(x["credit"]), n(x["total"]), n(x["offre"]),
          "; ".join(x["obs"])] for x in donnees["lignes"]],
        total=["TOTAL", q(t["quantite"]), n(t["cash"], False), n(t["credit"], False), n(t["total"], False),
               n(t["offre"], False), ""],
        alignement_droite={1, 2, 3, 4, 5}, largeurs=[29, 9, 11, 11, 11, 11, 24])


def _resume_ventes(doc, t):
    doc.espace(3)
    doc.cles_valeurs([
        ("VENTES", n(t["montant"], False)), ("CRÉDITS", n(t["credit"], False)),
        ("OFFRES", n(t["offre"], False)),
    ] + [(m["libelle"].upper(), n(m["montant"], False)) for m in t["moyens"]], largeur_cle=55)


def stock_bar_pdf(jour, receptionnistes, donnees):
    nom = Etablissement.get().nom.upper()
    doc = DocumentPDF(f"STOCK BAR {nom}", _entete(jour, receptionnistes, qui="Caisse bar"), paysage=True)
    t = donnees["totaux"]
    entetes = ["PRODUITS", "CODE", "S.I", "APPRO.", "AVARIES", "S.T", "Qtés vendues", "P.V", "MONTANT", "S.F"]
    largeurs = [26, 8, 7, 7, 7, 7, 9, 9, 11, 7]
    if donnees["a_ajustements"]:
        entetes.append("Ajust. inv.")
        largeurs.append(7)
    lignes = []
    for x in donnees["lignes"]:
        ligne = [x["article"].nom, x["article"].code, q(x["si"]), n(x["appro"]), n(x["avaries"]), q(x["st"]),
                 n(x["quantite"]), n(x["pv"], False), n(x["montant"]), q(x["sf"])]
        if donnees["a_ajustements"]:
            ligne.append(f"{x['ajustement']:+d}" if x["ajustement"] else "")
        lignes.append(ligne)
    total = ["TOTAL", "", "", "", "", "", q(t["quantite"]), "", n(t["montant"], False), ""]
    if donnees["a_ajustements"]:
        total.append("")
    doc.tableau(entetes, lignes, total=total, alignement_droite=set(range(2, len(entetes))), largeurs=largeurs,
                compact=True)
    _resume_ventes(doc, t)
    doc.espace(4)
    doc.signatures(["Bar / restaurant", "Gérant"])
    return doc.rendre()


def legende_receptionnistes(colonnes):
    return ", ".join(f"{c['code']} : {c['nom']}" for c in colonnes)


def stock_boutique_pdf(jour, receptionnistes, donnees, main_courante):
    colonnes = donnees["colonnes"]
    doc = DocumentPDF("STOCK BOUTIQUE", f"Date : {jour:%d/%m/%Y}  -  {legende_receptionnistes(colonnes)}",
                      paysage=True)
    t = donnees["totaux"]
    nb = len(colonnes)
    doc.tableau(
        ["Désignation", "Prix", "S.I", "Approv"] + [c["code"] for c in colonnes] + ["S.F", "Montant", "Cumulé", "Crédit"],
        [[x["article"].nom, n(x["pv"], False), q(x["si"]), n(x["appro"])] + [n(r) for r in x["releves"]]
         + [q(x["sf"]), n(x["montant"]), n(x["cumul"]), n(x["credit"])] for x in donnees["lignes"]],
        total=["TOTAL", "", "", ""] + [q(r) for r in t["releves"]]
        + ["", n(t["montant"], False), n(t["cumul"], False), n(t["credit"], False)],
        alignement_droite=set(range(1, 8 + nb)), largeurs=[24, 9, 6, 7] + [6] * nb + [6, 10, 10, 9], compact=True)
    _resume_ventes(doc, t)
    doc.section("MAIN COURANTE BOUTIQUE")
    _tableau_main_courante(doc, main_courante)
    return doc.rendre()


# --- Fiches au format papier de l'hôtel (recette chambres, bar / restaurant) ------------------------------------
PECHE = colors.HexColor("#FCE4D6")
JAUNE = colors.HexColor("#FFD966")
JAUNE_PALE = colors.HexColor("#FFF2CC")
GRIS = colors.HexColor("#E7EAEE")


def _couper(texte, largeur_mm, taille, gras=False):
    """Le texte tient dans sa case (sinon il déborderait sur la voisine) : coupé avec « … »."""
    texte = texte_pdf(texte)
    police = "Helvetica-Bold" if gras else "Helvetica"
    place = largeur_mm * mm - 4
    if stringWidth(texte, police, taille) <= place:
        return texte
    while texte and stringWidth(texte + "…", police, taille) > place:
        texte = texte[:-1]
    return texte.rstrip() + "…"


def _fiche_papier_pdf(titre, jour, bandeau, entetes, largeurs, lignes, total, total_om, montant, droite,
                      groupes=(), hauteur_ligne=4.0, taille=6.6):
    """Une fiche comme le modèle papier : bandeau (Date, qui, ouverture, fermeture, total vente, heure) en haut,
    une ligne par chambre ou par article, TOTAL en jaune, TOTAL OM, puis MONTANT.

    bandeau : [(libellé, valeur, première colonne, dernière colonne)] ; total : une case par colonne ;
    total_om : (colonne du libellé, valeur) ; groupes : index des lignes de titre (BOISSONS, PLATS).
    """
    nb = len(entetes)
    page = landscape(A4)
    tampon = BytesIO()
    etab = Etablissement.get()
    genere = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    doc = SimpleDocTemplate(tampon, pagesize=page, leftMargin=8 * mm, rightMargin=8 * mm, topMargin=7 * mm,
                            bottomMargin=9 * mm, title=texte_pdf(titre), author=texte_pdf(etab.nom))
    echelle = (page[0] - 16 * mm) / (sum(largeurs) * mm)
    largeurs = [w * echelle for w in largeurs]   # en mm, ajustées à la page

    donnees = [[""] * nb, [""] * nb]
    style = [("GRID", (0, 0), (-1, -1), 0.5, colors.black),
             ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), taille),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 0.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
             ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
             ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (0, 0), (-1, 1), "CENTER"),
             ("BACKGROUND", (0, 1), (-1, 1), PECHE), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
             ("ALIGN", (0, 2), (-1, 2), "CENTER")]
    for libelle, valeur, debut, fin in bandeau:
        largeur = sum(largeurs[debut:fin + 1])
        donnees[0][debut] = _couper(libelle, largeur, taille, gras=True)
        donnees[1][debut] = _couper(valeur, largeur, taille, gras=True)
        if fin > debut:
            style += [("SPAN", (debut, 0), (fin, 0)), ("SPAN", (debut, 1), (fin, 1))]
    donnees.append([texte_pdf(e) for e in entetes])
    for i, ligne in enumerate(lignes):
        r = len(donnees)
        if i in groupes:
            donnees.append([texte_pdf(ligne[0])] + [""] * (nb - 1))
            style += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), GRIS),
                      ("FONTNAME", (0, r), (-1, r), "Helvetica-Bold")]
        else:
            donnees.append([_couper(c, largeurs[j], taille) for j, c in enumerate(ligne)])
    r = len(donnees)
    for j in droite:
        style.append(("ALIGN", (j, 3), (j, r), "RIGHT"))
    col_om, valeur_om = total_om
    donnees.append([_couper(c, largeurs[j], taille, gras=True) for j, c in enumerate(total)])
    donnees[r][col_om] = "TOTAL OM"
    donnees[r][col_om + 1] = texte_pdf(valeur_om)
    style += [("FONTNAME", (0, r), (-1, r), "Helvetica-Bold"), ("BACKGROUND", (1, r), (col_om, r), JAUNE),
              ("BACKGROUND", (col_om + 1, r), (-1, r), JAUNE_PALE), ("SPAN", (col_om + 1, r), (-1, r)),
              ("ALIGN", (col_om + 1, r), (-1, r), "CENTER"), ("ALIGN", (col_om, r), (col_om, r), "CENTER")]
    donnees.append(["MONTANT", texte_pdf(montant)] + [""] * (nb - 2))
    style += [("SPAN", (1, r + 1), (-1, r + 1)), ("FONTNAME", (0, r + 1), (-1, r + 1), "Helvetica-Bold"),
              ("FONTSIZE", (1, r + 1), (-1, r + 1), taille + 1.5), ("ALIGN", (1, r + 1), (-1, r + 1), "CENTER")]
    style.append(("ALIGN", (0, 3), (0, r - 1), "CENTER"))
    hauteurs = [4.6 * mm, 5 * mm, 7 * mm] + [hauteur_ligne * mm] * (len(donnees) - 5) + [4.8 * mm, 5.2 * mm]
    table = Table(donnees, colWidths=[w * mm for w in largeurs], rowHeights=hauteurs, repeatRows=3)
    table.setStyle(TableStyle(style))

    def pied(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(8 * mm, 4.5 * mm, texte_pdf(f"{etab.nom} - {titre} du {jour:%d/%m/%Y} - imprimée le {genere}"))
        canvas.drawRightString(page[0] - 8 * mm, 4.5 * mm, f"Page {document.page}")
        canvas.restoreState()

    style_titre = ParagraphStyle("titre_fiche", fontName="Helvetica-Bold", fontSize=9.5, leading=12)
    doc.build([Paragraph(f"{_echapper(etab.nom.upper())} - {_echapper(titre.upper())}", style_titre),
               Spacer(1, 1.5 * mm), table], onFirstPage=pied, onLaterPages=pied)
    return tampon.getvalue()


def _v(valeur, vide_si_zero=True):
    return "" if valeur is None else n(valeur, vide_si_zero)


def recette_chambres_pdf(jour, donnees=None, chambres=None):
    """La fiche recette chambres, colonne pour colonne comme le modèle papier. Sans données : fiche vierge."""
    entetes = ["N° CH", "Nom client", "Recette jr", "Imp jr", "Offre jr", "Comp.", "avance", "Nom client",
               "Reg dette", "Nom client", "Reste dette", "Obs.", "Mobile", "Heure arrivé", "Heure depart"]
    largeurs = [12, 30, 15, 13, 11, 12, 13, 27, 14, 27, 14, 30, 13, 13, 13]
    if donnees is None:
        lignes = [[c.numero] + [""] * 14 for c in chambres]
        e, t = {}, {}
        bandeau_valeurs = [f"{jour:%d/%m/%Y}", "", "", "", "", ""]
        total = ["TOTAL"] + [""] * 14
        total_om, montant = "", ""
    else:
        e, t = donnees["entete"], donnees["totaux"]
        lignes = []
        for rang in donnees["grille"]:
            x, reg, det = rang["ligne"], rang["reglement"], rang["dette"]
            ligne = [""] * 15
            if x:
                ligne[0:7] = [x["chambre"].numero, str(x["sejour"].client) if x["sejour"] else "", n(x["recette"]),
                              n(x["impaye"]), n(x["offre"]), n(x["compensation"]), n(x["avance"])]
                ligne[11:15] = [x["observation"], n(x["mobile"]), x["heure_arrivee"], x["heure_depart"]]
            if reg:
                if reg["mobile"]:   # déjà dans le TOTAL OM : seulement rappelé, pas compté dans Reg dette
                    case = f"{n(reg['montant'])} +OM" if reg["montant"] else f"OM {n(reg['mobile'])}"
                else:
                    case = n(reg["montant"])
                ligne[7:9] = [reg["nom"], case]
            if det:
                ligne[9:11] = [det["nom"], n(det["montant"], False)]
            lignes.append(ligne)
        bandeau_valeurs = [f"{jour:%d/%m/%Y}", ", ".join(e["noms"]), _v(e["ouverture"], False),
                           _v(e["fermeture"], False), _v(e["total_vente"], False), e["heure"]]
        total = ["TOTAL", "", n(t["recette"], False), n(t["impaye"], False), n(t["offre"], False),
                 n(t["compensation"], False), n(t["avance"], False), "", n(t["reglements"], False), "",
                 n(t["dettes"], False), "", "", "", ""]
        total_om, montant = n(t["mobile"], False), n(t["montant"], False)
    libelles = ["Date:", "Receptioniste", "Montant ouverture", "Montant fermeture", "Total vente", "Heure"]
    colonnes = [(0, 0), (1, 2), (3, 5), (6, 8), (9, 12), (13, 14)]
    bandeau = [(lib, val, a, b) for lib, val, (a, b) in zip(libelles, bandeau_valeurs, colonnes)]
    return _fiche_papier_pdf("Fiche recette chambres", jour, bandeau, entetes, largeurs, lignes, total,
                             (11, total_om), montant, droite={2, 3, 4, 5, 6, 8, 10, 12})


def bar_restaurant_pdf(jour, donnees=None, lignes_vierges=32):
    """La fiche bar / restaurant, sur le même modèle que la fiche recette chambres. Sans données : fiche vierge."""
    entetes = ["N°", "Désignation", "P.U", "Qté V", "Cash", "Crédit", "Nom client (crédit)", "Offre", "Total",
               "Obs.", "Mobile"]
    largeurs = [15, 50, 15, 12, 18, 18, 34, 15, 18, 36, 18]
    groupes = set()
    if donnees is None:
        lignes = [[str(i + 1)] + [""] * 10 for i in range(lignes_vierges)]
        bandeau_valeurs = [f"{jour:%d/%m/%Y}", "", "", "", "", ""]
        total = ["TOTAL"] + [""] * 10
        total_om, montant = "", ""
    else:
        e, t = donnees["entete"], donnees["totaux"]
        lignes = []
        for g in donnees["groupes"]:
            groupes.add(len(lignes))
            lignes.append([g["titre"]])
            for numero, x in enumerate(g["lignes"], start=1):
                lignes.append([str(numero), x["article"].nom, n(x["prix"], False), q(x["quantite"]), n(x["cash"]),
                               n(x["credit"]), ", ".join(x["noms"]), n(x["offre"]), n(x["total"]),
                               "; ".join(x["obs"]), n(x["mobile"])])
        if not lignes:
            lignes = [["", "Aucune vente ce jour."] + [""] * 9]
        bandeau_valeurs = [f"{jour:%d/%m/%Y}", ", ".join(e["noms"]), _v(e["ouverture"], False),
                           _v(e["fermeture"], False), _v(e["total_vente"], False), e["heure"]]
        total = ["TOTAL", "", "", q(t["quantite"]), n(t["cash"], False), n(t["credit"], False), "",
                 n(t["offre"], False), n(t["total"], False), "", ""]
        total_om, montant = n(t["mobile"], False), n(t["montant"], False)
    libelles = ["Date:", "Caissier(e)", "Montant ouverture", "Montant fermeture", "Total vente", "Heure"]
    colonnes = [(0, 0), (1, 1), (2, 4), (5, 6), (7, 8), (9, 10)]
    bandeau = [(lib, val, a, b) for lib, val, (a, b) in zip(libelles, bandeau_valeurs, colonnes)]
    return _fiche_papier_pdf("Fiche bar / restaurant", jour, bandeau, entetes, largeurs, lignes, total,
                             (9, total_om), montant, droite={2, 3, 4, 5, 7, 8, 10}, groupes=groupes,
                             hauteur_ligne=4.6 if donnees is None else 4.2)


def chambres_a_faire_pdf(jour, lignes, equipe):
    doc = DocumentPDF("CHAMBRES À FAIRE", f"Date : {jour:%d/%m/%Y}  -  Équipe : {', '.join(equipe) or '..................'}")
    doc.paragraphe("Cochez « Faite » pour chaque chambre terminée, écrivez votre prénom et l'heure, puis rapportez "
                   "cette fiche à la réception : elle touche « Faite » sur l'écran. Une panne, un objet oublié, du "
                   "linge abîmé ? Écrivez-le dans « Remarques ».")
    doc.espace(3)
    doc.tableau(["CH", "À FAIRE", "FAITE", "PAR QUI", "HEURE", "REMARQUES"],
                [[x["chambre"].numero, x["quoi"], "", "", "", ""] for x in lignes]
                + [["", "", "", "", "", ""] for _ in range(4)],
                largeurs=[7, 38, 8, 14, 9, 24], hauteur_lignes=9)
    doc.espace(5)
    doc.signatures(["Chambres et blanchisserie", "Réception (a saisi « Faite »)", "Gouvernante"])
    return doc.rendre()


def main_courante_gardien_pdf(jour, lignes_vides=22):
    lendemain = jour + timedelta(days=1)
    doc = DocumentPDF("MAIN COURANTE DU GARDIEN",
                      f"Nuit du {jour:%d/%m/%Y} au {lendemain:%d/%m/%Y}  -  Gardien : ................................"
                      "  -  Prise de service : ....h....  -  Fin : ....h....")
    doc.paragraphe("Notez tout, heure par heure : rondes, visiteurs (nom, chambre), livraisons, incidents. Cochez la "
                   "bonne case. Le matin, remettez la fiche à la réception : elle recopie tout dans l'application.")
    doc.espace(3)
    doc.tableau(["HEURE", "RONDE", "VISITEUR", "LIVRAISON", "INCIDENT", "CE QUI S'EST PASSÉ"],
                [["", "", "", "", "", ""] for _ in range(lignes_vides)],
                largeurs=[9, 8, 9, 10, 9, 55], hauteur_lignes=8)
    doc.espace(4)
    doc.paragraphe("Fiche remise à la réception à ....h....")
    doc.espace(2)
    doc.signatures(["Gardien", "Réception (a tout recopié)"])
    return doc.rendre()

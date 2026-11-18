"""
Petit générateur de documents PDF (reçus de remise, rapports quotidiens, fiches de paie).

Police Helvetica (encodage WinAnsi) : les caractères hors de cet encodage
(espace fine, signe moins typographique) sont remplacés avant le rendu.
"""
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import Etablissement
from .utils import format_fcfa

_REMPLACEMENTS = {" ": " ", " ": " ", "−": "-", "→": "->", " ": " "}


def texte_pdf(valeur):
    texte = "" if valeur is None else str(valeur)
    for avant, apres in _REMPLACEMENTS.items():
        texte = texte.replace(avant, apres)
    return texte


def montant_pdf(valeur):
    return texte_pdf(format_fcfa(valeur))


def _echapper(texte):
    return texte_pdf(texte).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class DocumentPDF:
    def __init__(self, titre, sous_titre="", paysage=False):
        self.titre = titre
        self.sous_titre = sous_titre
        self.paysage = paysage
        self.elements = []
        styles = getSampleStyleSheet()
        self.style_normal = ParagraphStyle("normal", parent=styles["Normal"], fontSize=9.5, leading=12)
        self.style_petit = ParagraphStyle("petit", parent=self.style_normal, fontSize=8, leading=10,
                                          textColor=colors.HexColor("#555555"))
        self.style_titre = ParagraphStyle("titre", parent=styles["Title"], fontSize=16, leading=20, spaceAfter=2,
                                          alignment=0)
        self.style_section = ParagraphStyle("section", parent=styles["Heading3"], fontSize=11, leading=14,
                                            spaceBefore=8, spaceAfter=4, keepWithNext=1)
        self.style_cellule = ParagraphStyle("cellule", parent=self.style_normal, fontSize=8.5, leading=10.5)

    # --- Contenu -----------------------------------------------------------
    def section(self, texte):
        self.elements.append(Paragraph(_echapper(texte), self.style_section))

    def paragraphe(self, texte, petit=False):
        self.elements.append(Paragraph(_echapper(texte), self.style_petit if petit else self.style_normal))

    def espace(self, hauteur=4):
        self.elements.append(Spacer(1, hauteur * mm))

    def cles_valeurs(self, lignes, largeur_cle=60):
        donnees = [[Paragraph(f"<b>{_echapper(c)}</b>", self.style_cellule), Paragraph(_echapper(v), self.style_cellule)]
                   for c, v in lignes]
        if not donnees:
            return
        table = Table(donnees, colWidths=[largeur_cle * mm, None], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F2F2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        self.elements.append(table)

    def tableau(self, entetes, lignes, total=None, alignement_droite=(), largeurs=None, compact=False,
                hauteur_lignes=None):
        """`largeurs` : poids relatifs des colonnes ; `alignement_droite` : index des colonnes de nombres ;
        `hauteur_lignes` (mm) : lignes assez hautes pour écrire à la main (fiches à remplir au stylo)."""
        base = ParagraphStyle("c", parent=self.style_cellule, fontSize=7.5 if compact else 8.5,
                              leading=9 if compact else 10.5)
        droite = ParagraphStyle("d", parent=base, alignment=2)

        def cellule(texte, i, gras=False):
            contenu = f"<b>{_echapper(texte)}</b>" if gras else _echapper(texte)
            return Paragraph(contenu, droite if i in alignement_droite else base)

        donnees = [[cellule(e, i, True) for i, e in enumerate(entetes)]]
        for ligne in lignes:
            donnees.append([cellule(c, i) for i, c in enumerate(ligne)])
        if total:
            donnees.append([cellule(c, i, True) for i, c in enumerate(total)])
        if len(donnees) == 1:
            donnees.append([Paragraph("Aucune ligne", base)] + [""] * (len(entetes) - 1))
        col_widths = None
        if largeurs:
            unite = self.largeur_utile / sum(largeurs)
            col_widths = [w * unite for w in largeurs]
        hauteurs = None
        if hauteur_lignes:
            hauteurs = [None] + [hauteur_lignes * mm] * (len(donnees) - 1)
        table = Table(donnees, repeatRows=1, hAlign="LEFT", colWidths=col_widths, rowHeights=hauteurs)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        if total:
            style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F2F2F2")))
        if compact:
            style += [("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
        table.setStyle(TableStyle(style))
        self.elements.append(table)

    @property
    def largeur_utile(self):
        # Largeur de page moins les marges (2 x 15 mm) et le retrait intérieur du cadre (2 x 6 pt).
        return (landscape(A4) if self.paysage else A4)[0] - 30 * mm - 12

    def signatures(self, libelles, titre=None):
        cellules = [[Paragraph(f"<b>{_echapper(lib)}</b><br/><br/><br/>Signature :", self.style_cellule)
                     for lib in libelles]]
        table = Table(cellules, colWidths=[self.largeur_utile / len(libelles)] * len(libelles), hAlign="LEFT")
        table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
                                   ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6)]))
        bloc = [Paragraph(_echapper(titre), self.style_section)] if titre else []
        self.elements.append(KeepTogether(bloc + [table]))

    def totaux(self, lignes, fort=-1):
        """Encadré des totaux à droite (total, déjà payé, reste) ; la ligne `fort` en gros caractères."""
        if not lignes:
            return
        style = ParagraphStyle("t", parent=self.style_cellule, fontSize=9.5, leading=12)
        style_fort = ParagraphStyle("tf", parent=style, fontSize=12, leading=15)
        droite = ParagraphStyle("td", parent=style, alignment=2)
        droite_fort = ParagraphStyle("tdf", parent=style_fort, alignment=2)
        index_fort = fort % len(lignes)
        donnees = []
        for i, (libelle, valeur) in enumerate(lignes):
            gras = i == index_fort
            donnees.append([Paragraph(f"<b>{_echapper(libelle)}</b>" if gras else _echapper(libelle),
                                      style_fort if gras else style),
                            Paragraph(f"<b>{_echapper(valeur)}</b>", droite_fort if gras else droite)])
        table = Table(donnees, colWidths=[55 * mm, 40 * mm], hAlign="RIGHT")
        table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#12305A")),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#CCCCCC")),
            ("BACKGROUND", (0, index_fort), (-1, index_fort), colors.HexColor("#F8F0DC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        self.elements.append(Spacer(1, 3 * mm))
        self.elements.append(table)

    # --- Rendu ---------------------------------------------------------------
    def rendre(self):
        tampon = BytesIO()
        taille = landscape(A4) if self.paysage else A4
        etab = Etablissement.get()
        genere = timezone.localtime().strftime("%d/%m/%Y %H:%M")

        def pied(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(colors.HexColor("#666666"))
            canvas.drawString(15 * mm, 10 * mm, texte_pdf(f"{etab.nom} - document généré le {genere}"))
            canvas.drawRightString(taille[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
            canvas.restoreState()

        doc = SimpleDocTemplate(tampon, pagesize=taille, leftMargin=15 * mm, rightMargin=15 * mm,
                                topMargin=14 * mm, bottomMargin=16 * mm, title=texte_pdf(self.titre),
                                author=texte_pdf(etab.nom))
        entete = [Paragraph(f"<b>{_echapper(etab.nom)}</b>", self.style_normal)]
        coordonnees = " - ".join(x for x in [etab.adresse, etab.telephone, etab.niu] if x)
        if coordonnees:
            entete.append(Paragraph(_echapper(coordonnees), self.style_petit))
        entete += [Spacer(1, 3 * mm), Paragraph(_echapper(self.titre), self.style_titre)]
        if self.sous_titre:
            entete.append(Paragraph(_echapper(self.sous_titre), self.style_normal))
        entete.append(Spacer(1, 4 * mm))
        doc.build(entete + self.elements, onFirstPage=pied, onLaterPages=pied)
        return tampon.getvalue()


def reponse_pdf(contenu, nom, telecharger=True):
    """Réponse HTTP d'un PDF : téléchargé (pour l'envoyer par WhatsApp ou par e-mail) ou ouvert dans le navigateur."""
    from django.http import HttpResponse

    reponse = HttpResponse(contenu, content_type="application/pdf")
    reponse["Content-Disposition"] = f'{"attachment" if telecharger else "inline"}; filename="{nom}"'
    return reponse

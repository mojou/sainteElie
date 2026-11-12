"""Fiches PDF imprimables, colonne pour colonne comme les fiches papier de l'hôtel."""
from datetime import timedelta

from django.utils import timezone

from core.models import Etablissement
from core.pdf import DocumentPDF, texte_pdf
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


def hebergement_pdf(jour, receptionnistes, donnees):
    doc = DocumentPDF("RECETTE CHAMBRES (main courante hébergement)", _entete(jour, receptionnistes), paysage=True)
    t = donnees["totaux"]
    doc.tableau(
        ["CH", "NOM CLIENT", "RECETTE JR", "IMP JR", "EXTRAS JR", "OFFRE JR", "COMPENSATION", "AVANCE",
         "OBSERVATION"],
        [[x["chambre"].numero, str(x["sejour"].client) if x["sejour"] else "", n(x["recette"]), n(x["impaye"]),
          n(x["extras"]), n(x["offre"]), n(x["compensation"]), n(x["avance"]), x["observation"]]
         for x in donnees["lignes"]],
        total=["TOTAL", "", n(t["recette"], False), n(t["impaye"], False), n(t["extras"], False),
               n(t["offre"], False), n(t["compensation"], False), n(t["avance"], False), ""],
        alignement_droite={2, 3, 4, 5, 6, 7}, largeurs=[7, 22, 9, 9, 9, 9, 11, 9, 19], compact=True)
    doc.section("Extras du jour (cuisine, réception, bar) : à encaisser à la réception")
    doc.tableau(["HEURE", "CH", "CLIENT", "CE QUI A ÉTÉ PRIS", "SAISI PAR", "MONTANT"],
                [[timezone.localtime(e.date_conso).strftime("%H:%M"), e.sejour.chambre.numero, str(e.sejour.client),
                  e.description, f"{e.saisi_par} ({e.saisi_par.get_role_display()})", n(e.montant, False)]
                 for e in donnees["extras_du_jour"]],
                total=["TOTAL", "", "", "", "", n(t["extras"], False)], alignement_droite={5},
                largeurs=[7, 7, 20, 30, 24, 12], compact=True)
    doc.section("Règlements de dettes du jour")
    doc.tableau(["NOM CLIENT", "RÉG. DETTE"], [[r["nom"], n(r["montant"], False)] for r in donnees["reglements"]],
                total=["TOTAL", n(t["reglements"], False)], alignement_droite={1}, largeurs=[70, 30], compact=True)
    doc.section("Restes de dettes")
    doc.tableau(["NOM CLIENT", "RESTE DETTE"], [[d["nom"], n(d["montant"], False)] for d in donnees["dettes"]],
                total=["TOTAL", n(t["dettes"], False)], alignement_droite={1}, largeurs=[70, 30], compact=True)
    doc.espace(4)
    doc.signatures(["Réceptionniste", "Chef de réception / gérant"])
    return doc.rendre()


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

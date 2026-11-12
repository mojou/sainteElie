"""Le rapport d'inventaire et de rentabilité, à imprimer (A4 paysage)."""
from core.pdf import DocumentPDF, texte_pdf
from core.utils import format_fcfa


def n(valeur):
    return "" if valeur is None else texte_pdf(format_fcfa(valeur, unite=False))


def pc(valeur):
    return "" if valeur is None else f"{str(valeur).replace('.', ',')} %"


def variation(actuel, avant):
    from .services import evolution

    v = evolution(actuel, avant)
    return "" if v is None else f"{'+' if v > 0 else ''}{v} %"


def rapport_inventaire_pdf(d, a, libelle, libelle_avant, notes, finances):
    doc = DocumentPDF("RAPPORT D'INVENTAIRE ET DE RENTABILITÉ", f"{libelle} - comparé à : {libelle_avant}", paysage=True)
    if notes:
        doc.section("À savoir avant de lire")
        for note in notes:
            doc.paragraphe("- " + note, petit=True)
    doc.section("Synthèse")
    lignes = [("Chiffre d'affaires", f"{n(d['c']['total'])} FCFA ({variation(d['c']['total'], a['c']['total'])} par rapport à avant)"),
              ("Ventes de marchandises (bar, cuisine, boutique)", f"{n(d['ca_marchandises'])} FCFA"),
              ("Coût des marchandises vendues", f"{n(d['cmv'])} FCFA (articles dont le prix d'achat est noté)"),
              ("Marge brute sur marchandises", f"{n(d['marge'])} FCFA - taux de marque {pc(d['taux_marque'])}"
                                               + (f" - coefficient {str(d['coefficient']).replace('.', ',')}" if d['coefficient'] else "")),
              ("Pertes : casse et périmés (au coût)", f"{n(d['pertes'])} FCFA"),
              ("Écarts d'inventaire (au coût)", f"{n(d['ecarts'])} FCFA"),
              ("Offerts", f"{n(d['offerts_vente'])} FCFA au prix de vente, {n(d['offerts_cout'])} FCFA au coût"),
              ("Valeur du stock au début / à la fin (au coût)", f"{n(d['valeur_debut'])} / {n(d['valeur_fin'])} FCFA"),
              ("Valeur du stock à la fin (au prix de vente)", f"{n(d['valeur_fin_vente'])} FCFA"),
              ("Livraisons reçues (au coût)", f"{n(d['livraisons'])} FCFA"),
              ("Taux d'occupation des chambres", pc(d['c']['occupation'])),
              ("Argent encaissé", f"{n(d['c']['encaisse'])} FCFA")]
    if finances:
        lignes += [("Charges (dépenses + salaires)", f"{n(d['charges'])} FCFA, soit {pc(d['part_charges'])} du chiffre d'affaires"),
                   ("Résultat de gestion", f"{n(d['resultat'])} FCFA - marge nette {pc(d['taux_resultat'])}")]
    doc.cles_valeurs(lignes, largeur_cle=90)

    doc.section("Recettes par service")
    doc.tableau(["Service", "Recette", "Part"], [[s["libelle"], n(s["montant"]), pc(s["part"])] for s in d["services"]],
                total=["Total", n(d["c"]["total"]), "100 %"], alignement_droite={1, 2}, largeurs=[50, 25, 15])

    doc.section("Ventes et marges par catégorie")
    doc.tableau(["Catégorie", "Vendus", "Chiffre d'affaires", "Part du CA", "Coût des ventes", "Marge", "Taux de marque",
                 "Sans prix d'achat"],
                [[c["nom"], str(c["vendu"]), n(c["ca"]), pc(c["part_ca"]), n(c["cmv"]), n(c["marge"]), pc(c["taux_marque"]),
                  str(c["sans_cout"] or "")] for c in d["categories"] if c["ca"] or c["valeur_fin"]],
                total=["Total", "", n(d["ca_marchandises"]), "100 %", n(d["cmv"]), n(d["marge"]), pc(d["taux_marque"]), ""],
                alignement_droite={1, 2, 3, 4, 5, 6, 7}, largeurs=[26, 9, 14, 10, 13, 12, 11, 10], compact=True)

    vendus = [l for l in d["lignes"] if l["vendu"] or l["offert"]]
    doc.section("Rentabilité par article (articles vendus)")
    doc.tableau(["Article", "Vendu", "Prix", "Coût", "Marge unit.", "Taux de marque", "Coef.", "Chiffre d'affaires",
                 "Marge totale", "Part du CA"],
                [[str(l["article"]), str(l["vendu"]), n(l["prix"]), n(l["cout"] or None), n(l["marge_unitaire"]),
                  pc(l["taux_marque"]), str(l["coefficient"] or "").replace(".", ","), n(l["ca"]), n(l["marge"]),
                  pc(l["part_ca"])] for l in sorted(vendus, key=lambda x: -x["ca"])],
                alignement_droite=set(range(1, 10)), largeurs=[26, 7, 9, 9, 9, 9, 6, 11, 10, 8], compact=True)

    suivis = [l for l in d["lignes"] if l["suivi"]]
    doc.section("Inventaire : le stock article par article")
    doc.paragraphe("Début + 1er comptage + livré − vendu ou offert − casse − sorties ± écart d'inventaire = fin. "
                   "Une vente annulée revient en stock : elle n'est pas comptée.", petit=True)
    doc.tableau(["Article", "Début", "1er comptage", "Livré", "Vendu ou offert", "Casse", "Sorties", "Écart", "Fin",
                 "Valeur fin (coût)", "Jours de stock"],
                [[str(l["article"]), str(l["debut"]), str(l["premier_comptage"] or ""), str(l["entrees"] or ""),
                  str(l["sorti_vente"] or ""), str(l["pertes"] or ""), str(l["sorties"] or ""),
                  f"{l['ecart']:+d}" if l["ecart"] else "", str(l["fin"]), n(l["valeur_fin"] or None),
                  str(l["jours_de_stock"] or "")] for l in suivis],
                total=["Total", "", "", "", "", "", "", "", "", n(d["valeur_fin"]), ""],
                alignement_droite=set(range(1, 11)), largeurs=[28, 6, 8, 6, 8, 6, 6, 6, 6, 10, 8], compact=True)

    if finances:
        doc.section("Charges et résultat")
        lignes = [["Recettes", n(d["c"]["total"]), "100 %", n(a["c"]["total"])]]
        lignes += [["- " + x["libelle"], n(x["montant"]), pc(x["part"]), ""] for x in d["depenses"]]
        lignes += [["- Salaires bruts (au prorata des jours)", n(d["salaires"]), pc(d["part_salaires"]), n(a["salaires"])]]
        doc.tableau(["", "Montant", "Part des recettes", "Période d'avant"], lignes,
                    total=["= Résultat de gestion", n(d["resultat"]), pc(d["taux_resultat"]), n(a["resultat"])],
                    alignement_droite={1, 2, 3}, largeurs=[50, 18, 16, 18])
        doc.paragraphe(f"Prélèvements du gérant dans les caisses (sortie d'argent, pas une charge) : {n(d['prelevements'])} FCFA. "
                       f"Livraisons de marchandises reçues sur la période : {n(d['livraisons'])} FCFA au coût ; "
                       f"achats notés en dépenses : {n(d['achats_notes'])} FCFA.", petit=True)

    doc.section("Tout ce qui s'est passé dans l'application")
    for titre, lignes in d["activites"]:
        doc.cles_valeurs([(f"{titre} - {libelle_ligne}", str(valeur)) for libelle_ligne, valeur in lignes], largeur_cle=110)
        doc.espace(1)
    doc.espace(4)
    doc.signatures(["Établi par", "Gérant"])
    return doc.rendre()

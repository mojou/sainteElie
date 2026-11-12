import csv
from datetime import date

from django.http import HttpResponse
from django.shortcuts import render

from core.permissions import acces_requis

from . import services


def suit_l_activite(u):
    """La direction (gérant, adjoints) et la gouvernante suivent l'activité ; les dépenses restent au gérant."""
    return u.est_direction or u.est_gouvernante


def _date(texte):
    try:
        return date.fromisoformat(texte or "")
    except ValueError:
        return None


INDICATEURS = [
    ("total", "Recette de la période", "FCFA", True), ("encaisse", "Argent encaissé", "FCFA", True),
    ("occupation", "Taux d'occupation", "%", True), ("prix_moyen", "Prix moyen d'une nuit", "FCFA", True),
    ("revpar", "Recette par chambre disponible", "FCFA", True), ("nb_nuitees", "Nuits vendues", "", True),
]


def _periode(request):
    cle = request.GET.get("periode", "mois")
    du, au = _date(request.GET.get("du")), _date(request.GET.get("au"))
    if du and au:
        cle = "dates"
    debut, fin = services.periode(cle, du, au)
    if (fin - debut).days > 731:
        fin = debut.replace(year=debut.year + 2)
    return cle, debut, fin


@acces_requis(suit_l_activite)
def rapport(request):
    """Le rapport d'activité, sur la période choisie : jour, semaine, mois, année, ou du … au …."""
    cle, debut, fin = _periode(request)
    avant_debut, avant_fin = services.periode_precedente(debut, fin)
    finances = request.user.est_gerant
    d = services.chiffres(debut, fin, finances=finances)
    a = services.chiffres(avant_debut, avant_fin, finances=finances)
    if request.GET.get("format") == "csv":
        return _csv(d)
    tuiles = []
    for champ, libelle, unite, hausse_bonne in INDICATEURS:
        variation = services.evolution(d[champ], a[champ])
        tuiles.append({"libelle": libelle, "valeur": d[champ], "unite": unite, "avant": a[champ],
                       "variation": variation,
                       "sens": "" if not variation else ("bon" if (variation > 0) == hausse_bonne else "mauvais")})
    graphe = services.colonnes(d)
    return render(request, "rapports/rapport.html", {
        "d": d, "a": a, "tuiles": tuiles, "graphe": graphe, "periodes": services.PERIODES, "cle": cle,
        "libelle": services.libelle_periode(debut, fin),
        "libelle_avant": services.libelle_periode(avant_debut, avant_fin),
        "services": [{"cle": k, "libelle": l, "rang": i, "montant": d["par_service"][k],
                      "avant": a["par_service"][k], "variation": services.evolution(d["par_service"][k], a["par_service"][k])}
                     for i, (k, l) in enumerate(services.SERVICES)],
        "moyens": services.barres(d["moyens"]),
        "meilleurs": services.barres(d["meilleurs"]),
        "depenses": services.barres(d["depenses"]["par_categorie"]) if finances else None,
        "finances": finances,
    })


def _csv(d):
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = f'attachment; filename="rapport-{d["debut"]}-{d["fin"]}.csv"'
    reponse.write("\ufeff")  # pour qu'Excel lise les accents
    ecrivain = csv.writer(reponse, delimiter=";")
    ecrivain.writerow(["Période"] + [l for _, l in services.SERVICES] + ["Total"])
    for seau, valeurs in d["recettes"].items():
        ecrivain.writerow([seau.strftime("%m/%Y" if d["par_mois"] else "%d/%m/%Y")]
                          + [valeurs[k] for k, _ in services.SERVICES] + [sum(valeurs.values())])
    ecrivain.writerow(["Total"] + [d["par_service"][k] for k, _ in services.SERVICES] + [d["total"]])
    return reponse


def suit_le_stock(u):
    """Inventaire et marges : la direction, la gouvernante, les chefs d'équipe. Charges et résultat : le gérant."""
    return u.est_direction or u.est_gouvernante or u.voit_stock


@acces_requis(suit_le_stock)
def inventaire(request):
    """Rapport d'inventaire et de rentabilité : stock, ventes, marges, pertes, charges, résultat, activités."""
    from . import inventaire as calcul

    cle, debut, fin = _periode(request)
    finances = request.user.est_gerant
    d = calcul.rapport(debut, fin, finances=finances)
    avant_debut, avant_fin = services.periode_precedente(debut, fin)
    a = calcul.rapport(avant_debut, avant_fin, finances=finances)
    notes = calcul.avertissements(d, debut, fin, finances)
    libelle = services.libelle_periode(debut, fin)
    if request.GET.get("format") == "csv":
        return _csv_inventaire(d, debut, fin)
    if request.GET.get("format") == "pdf":
        from .pdf import rapport_inventaire_pdf

        reponse = HttpResponse(rapport_inventaire_pdf(d, a, libelle, services.libelle_periode(avant_debut, avant_fin),
                                                      notes, finances), content_type="application/pdf")
        reponse["Content-Disposition"] = f'inline; filename="inventaire-rentabilite-{debut}-{fin}.pdf"'
        return reponse
    comparer = [("Chiffre d'affaires", d["c"]["total"], a["c"]["total"]),
                ("Ventes de marchandises", d["ca_marchandises"], a["ca_marchandises"]),
                ("Marge brute sur marchandises", d["marge"], a["marge"]),
                ("Pertes (casse) au coût", d["pertes"], a["pertes"])]
    if finances:
        comparer += [("Charges", d["charges"], a["charges"]), ("Résultat", d["resultat"], a["resultat"])]
    return render(request, "rapports/inventaire.html", {
        "d": d, "a": a, "notes": notes, "finances": finances, "periodes": services.PERIODES, "cle": cle,
        "libelle": libelle, "libelle_avant": services.libelle_periode(avant_debut, avant_fin),
        "comparaison": [{"libelle": l, "valeur": v, "avant": av, "variation": services.evolution(v, av)}
                        for l, v, av in comparer],
    })


def _csv_inventaire(d, debut, fin):
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = f'attachment; filename="inventaire-rentabilite-{debut}-{fin}.csv"'
    reponse.write("\ufeff")
    e = csv.writer(reponse, delimiter=";")
    e.writerow(["Catégorie", "Article", "Stock début", "1er comptage", "Livré", "Sorti par la vente (net)", "Vendu", "Offert", "Casse", "Sorties", "Écart inventaire",
                "Stock fin", "Coût d'achat", "Prix de vente", "Marge unitaire", "Taux de marque %", "Coefficient",
                "Chiffre d'affaires", "Coût des ventes", "Marge", "Part du CA %", "Valeur stock fin (coût)",
                "Valeur stock fin (vente)", "Jours de stock"])
    for l in d["lignes"]:
        e.writerow([l["categorie"], str(l["article"]), l["debut"], l["premier_comptage"], l["entrees"], l["sorti_vente"], l["vendu"], l["offert"], l["pertes"],
                    l["sorties"], l["ecart"], l["fin"], l["cout"] or "", l["prix"], l["marge_unitaire"],
                    str(l["taux_marque"]).replace(".", ",") if l["taux_marque"] is not None else "",
                    str(l["coefficient"]).replace(".", ",") if l["coefficient"] is not None else "", l["ca"], l["cmv"],
                    l["marge"], str(l["part_ca"]).replace(".", ",") if l["part_ca"] is not None else "",
                    l["valeur_fin"], l["valeur_fin_vente"], l["jours_de_stock"]])
    return reponse

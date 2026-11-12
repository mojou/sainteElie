"""Le stock qui parle : l'état de chaque article en mots, et chaque mouvement raconté en une phrase.

Au lieu de « VENTE −4 », on lit « Vendu : 4 bouteilles, payé en espèces (reçu n°45), par Merveille — il en
reste 36 ». Au lieu d'une colonne de chiffres, « À commander : il en reste 6, environ 2 jours de vente ».
"""
from datetime import timedelta

from django.db.models import Max, Min, Sum

from core.utils import aujourd_hui, format_fcfa

from .models import Article, MouvementStock

JOURS_OBSERVES = 30   # la vitesse de vente se mesure sur les 30 derniers jours
JOURS_BIENTOT = 3     # en dessous de 3 jours de vente devant soi : à commander bientôt


def quantite_texte(n, unite):
    """« 1 unité », « 4 unités », « 2 casiers » (pluriel simple)."""
    n = abs(int(n))
    unite = unite or "unité"
    if n > 1 and not unite.endswith(("s", "x")):
        unite += "s"
    return f"{n} {unite}"


def vitesses(articles):
    """Pour chaque article : unités vendues par jour en moyenne, date de la dernière vente, date du premier mouvement.

    La moyenne porte sur les 30 derniers jours, ou sur les jours réellement suivis si l'article est plus récent :
    4 bouteilles vendues le premier jour, c'est 4 par jour, pas 4 / 30.
    """
    jour = aujourd_hui()
    depuis = jour - timedelta(days=JOURS_OBSERVES)
    premiers = {v["article"]: v["d"] for v in MouvementStock.objects.filter(article__in=articles)
                .values("article").annotate(d=Min("journee"))}
    ventes = (MouvementStock.objects.filter(article__in=articles, journee__gt=depuis,
                                            type__in=[MouvementStock.Type.VENTE, MouvementStock.Type.RETOUR])
              .values("article").annotate(net=Sum("quantite")))
    derniere = (MouvementStock.objects.filter(article__in=articles, type=MouvementStock.Type.VENTE)
                .values("article").annotate(d=Max("journee")))
    vitesse = {}
    for v in ventes:
        if v["net"] < 0:
            suivis = min(JOURS_OBSERVES, (jour - premiers.get(v["article"], depuis)).days + 1)
            vitesse[v["article"]] = round(-v["net"] / max(suivis, 1), 2)
    return vitesse, {v["article"]: v["d"] for v in derniere}, premiers


def etat(article, vitesse=0, derniere_vente=None, premier_mouvement=None):
    """Ce qu'il faut savoir d'un article, en mots : un code (pour la couleur), un titre court, une phrase."""
    if not article.suivi_stock:
        return {"code": "neutre", "titre": "Sans stock", "phrase": "Plat de la carte : il se vend sans sortir du stock.",
                "jours": None}
    q, unite = article.quantite, article.unite
    jours = int(q / vitesse) if vitesse else None
    rythme = (f" On en vend environ {f'{vitesse:.1f}'.rstrip('0').rstrip('.').replace('.', ',')} par jour."
              if vitesse else "")
    if q <= 0:
        return {"code": "danger", "titre": "Rupture", "jours": 0,
                "phrase": f"Plus rien en stock : il faut en commander.{rythme}"}
    if q <= article.seuil_alerte:
        return {"code": "alerte", "titre": "À commander", "jours": jours,
                "phrase": f"Il en reste {quantite_texte(q, unite)}, sous le seuil de {article.seuil_alerte}."
                          + (f" Environ {jours} jour{'s' if jours > 1 else ''} de vente." if jours is not None else "")}
    if jours is not None and jours <= JOURS_BIENTOT:
        return {"code": "alerte", "titre": "Bientôt épuisé", "jours": jours,
                "phrase": f"Il en reste {quantite_texte(q, unite)} : environ {jours} jour{'s' if jours > 1 else ''} "
                          f"de vente.{rythme}"}
    if not vitesse and article.categorie in Article.VENDUS_AU_COMPTOIR:
        if premier_mouvement and (aujourd_hui() - premier_mouvement).days < JOURS_OBSERVES:
            return {"code": "neutre", "titre": "Nouveau", "jours": None,
                    "phrase": f"En stock depuis le {premier_mouvement:%d/%m} : trop tôt pour dire s'il se vend bien."}
        depuis = (f"dernière le {derniere_vente:%d/%m}" if derniere_vente else "jamais vendu ici")
        argent = f" : {format_fcfa(article.valeur)} immobilisés en stock" if article.valeur else ""
        return {"code": "dort", "titre": "Ne se vend pas", "jours": None,
                "phrase": f"Aucune vente en {JOURS_OBSERVES} jours ({depuis}){argent}."}
    return {"code": "ok", "titre": "Bon", "jours": jours,
            "phrase": f"Il en reste {quantite_texte(q, unite)}"
                      + (f", environ {jours} jours de vente.{rythme}" if jours is not None else ".")}


def raconter(m, vente=None):
    """Un mouvement de stock en une phrase : ce qui s'est passé, combien, pourquoi, et le stock avant → après."""
    T = MouvementStock.Type
    unite = m.article.unite
    combien = quantite_texte(m.quantite, unite)
    avant = m.quantite_apres - m.quantite
    stock = f"stock {avant} → {m.quantite_apres}"
    par = f"par {m.saisi_par}" if m.saisi_par_id else ""
    if m.type == T.ENTREE:
        cout = f"à {format_fcfa(m.cout_unitaire)} l'unité, {format_fcfa(m.cout_unitaire * m.quantite)} en tout" \
            if m.cout_unitaire else "prix d'achat non noté"
        return {"sens": "entree", "icone": "+", "titre": f"Livraison reçue : {combien}",
                "detail": " · ".join(x for x in [cout, m.motif if m.motif and m.motif != "Livraison" else "", par, stock] if x)}
    if m.type == T.VENTE:
        comment = ""
        if vente is not None:
            if vente.encaissement_id:
                comment = f"payé en {vente.encaissement.get_mode_display().lower() if vente.encaissement.mode == 'ESPECES' else vente.encaissement.get_mode_display()} (reçu n°{vente.encaissement.numero_recu})"
            elif vente.sejour_id:
                comment = f"sur la chambre {vente.sejour.chambre.numero} ({vente.sejour.client})"
            elif vente.client_id:
                comment = f"à crédit pour {vente.client}"
            elif vente.reglement == "OFFERT":
                comment = f"offert : {vente.observation}" if vente.observation else "offert"
            if vente.annulee:
                comment += " — vente annulée ensuite"
        return {"sens": "sortie", "icone": "−", "titre": f"Vendu : {combien}",
                "detail": " · ".join(x for x in [comment, par, stock] if x)}
    if m.type == T.RETOUR:
        return {"sens": "entree", "icone": "↺", "titre": f"Vente annulée : {combien} revien{'nent' if abs(m.quantite) > 1 else 't'} en stock",
                "detail": " · ".join(x for x in [m.motif.replace("Annulation : ", "motif : "), par, stock] if x)}
    if m.type == T.AVARIE:
        perte = format_fcfa(abs(m.quantite) * m.article.prix_achat)
        return {"sens": "perte", "icone": "!", "titre": f"Perdu (casse ou périmé) : {combien}",
                "detail": " · ".join(x for x in [m.motif, f"{perte} au coût", par, stock] if x)}
    if m.type == T.SORTIE:
        return {"sens": "sortie", "icone": "−", "titre": f"Sortie pour l'hôtel : {combien}",
                "detail": " · ".join(x for x in [m.motif, par, stock] if x)}
    # Inventaire : on a compté ; la différence avec ce que l'application attendait est l'écart.
    if m.quantite == 0:
        titre, sens, ecart = f"Inventaire : compté {m.quantite_apres}, c'est juste", "juste", ""
    elif avant == 0 and m.quantite > 0:
        titre, sens, ecart = f"Premier comptage : {quantite_texte(m.quantite_apres, unite)} en stock", "entree", ""
    elif m.quantite < 0:
        titre, sens = f"Inventaire : {quantite_texte(m.quantite, unite)} manqu{'ent' if abs(m.quantite) > 1 else 'e'}", "perte"
        ecart = f"{format_fcfa(abs(m.quantite) * m.cout_unitaire)} au coût, {format_fcfa(abs(m.quantite) * m.article.prix_vente)} de ventes"
    else:
        titre, sens = f"Inventaire : {quantite_texte(m.quantite, unite)} en trop", "entree"
        ecart = "vente ou livraison peut-être mal notée"
    return {"sens": sens, "icone": "=", "titre": titre,
            "detail": " · ".join(x for x in [f"compté {m.quantite_apres}, l'application attendait {avant}" if m.quantite else "",
                                             ecart, par] if x)}


def raconter_tous(mouvements):
    """Les phrases d'une liste de mouvements, avec la vente de chacun (reçu, chambre, client) en une seule requête."""
    from caisse.models import VenteComptoir

    mouvements = list(mouvements)
    ventes = {v.mouvement_id: v for v in VenteComptoir.objects.filter(
        mouvement__in=[m for m in mouvements if m.type == MouvementStock.Type.VENTE]).select_related(
        "encaissement", "sejour__chambre", "sejour__client", "client")}
    for m in mouvements:
        m.recit = raconter(m, ventes.get(m.pk))
    return mouvements

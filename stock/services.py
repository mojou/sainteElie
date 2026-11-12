from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from core.models import Alerte
from core.utils import alerter, aujourd_hui, format_fcfa, journaliser

from .models import Article, MouvementStock


def enregistrer_mouvement(article, user, type_, quantite, motif="", cout_unitaire=0, journee=None):
    """Enregistre un mouvement et met à jour le stock.

    Entrée, vente, retour, avarie, sortie : quantité positive saisie. Inventaire : quantité réellement comptée.
    """
    if quantite is None or quantite < 0 or (type_ != MouvementStock.Type.INVENTAIRE and quantite == 0):
        raise ValidationError("Quantité invalide.")
    if type_ == MouvementStock.Type.AVARIE and not (motif or "").strip():
        raise ValidationError("Une avarie doit être motivée (bouteille cassée, produit périmé…).")
    if type_ == MouvementStock.Type.SORTIE and not (motif or "").strip():
        raise ValidationError("Une sortie doit être motivée : pour qui, pour quoi (consommation du personnel…).")
    with transaction.atomic():
        article = Article.objects.select_for_update().get(pk=article.pk)
        avant = article.quantite
        if type_ in (MouvementStock.Type.ENTREE, MouvementStock.Type.RETOUR):
            delta = quantite
        elif type_ in MouvementStock.SORTANTS:
            if quantite > article.quantite:
                raise ValidationError(f"Stock insuffisant pour {article} : il reste {article.quantite}. "
                                      "Faites d'abord enregistrer l'approvisionnement.")
            delta = -quantite
        else:
            motif = motif or "Inventaire"
            delta = quantite - article.quantite
            cout_unitaire = article.prix_achat  # coût au moment du comptage : il chiffre l'écart
        article.quantite += delta
        champs = ["quantite"]
        if type_ == MouvementStock.Type.ENTREE and cout_unitaire:
            # Coût moyen pondéré : le stock restant garde son coût, la livraison apporte le sien.
            if article.prix_achat and avant > 0:
                article.prix_achat = round((avant * article.prix_achat + quantite * cout_unitaire) / (avant + quantite))
            else:
                article.prix_achat = cout_unitaire
            champs.append("prix_achat")
        article.save(update_fields=champs)
        mouvement = MouvementStock.objects.create(
            article=article, type=type_, quantite=delta, quantite_apres=article.quantite, cout_unitaire=cout_unitaire,
            motif=motif, saisi_par=user, journee=journee or aujourd_hui())
    lien = reverse("stock:article", args=[article.pk])
    if type_ == MouvementStock.Type.INVENTAIRE and delta < 0:
        manque = -delta
        alerter(Alerte.Type.STOCK,
                f"Écart d'inventaire : {manque} {article} manquant(s) au comptage de {user}, soit "
                f"{format_fcfa(manque * article.prix_vente)} de ventes (coût {format_fcfa(manque * article.prix_achat)}).",
                public=Alerte.Public.GERANT, lien=reverse("stock:ecarts"))
    if type_ == MouvementStock.Type.AVARIE:
        alerter(Alerte.Type.STOCK, f"Avarie déclarée par {user} : {quantite} {article} ({motif}).",
                public=Alerte.Public.STOCK, lien=lien)
    if article.est_bas:
        alerter(Alerte.Type.STOCK, f"Stock bas : {article} ({article.quantite} {article.unite}, seuil {article.seuil_alerte}).",
                public=Alerte.Public.STOCK, lien=lien, cle=f"stock-{article.pk}")
    if type_ not in (MouvementStock.Type.VENTE, MouvementStock.Type.RETOUR):
        journaliser(user, f"Stock : {MouvementStock.Type(type_).label}", article, f"{delta:+d}")
    return mouvement


def ecarts_inventaire(debut, fin):
    """Écarts constatés aux inventaires entre deux journées, chiffrés au coût et au prix de vente.

    Le premier comptage d'un article (stock de départ à zéro) n'est pas un écart.
    """
    lignes = []
    for m in (MouvementStock.objects.filter(type=MouvementStock.Type.INVENTAIRE, journee__gte=debut, journee__lte=fin)
              .exclude(quantite=0).select_related("article", "saisi_par").order_by("-journee", "-date")):
        if m.quantite > 0 and m.quantite_apres == m.quantite:
            continue
        lignes.append({"mouvement": m, "article": m.article, "ecart": m.quantite,
                       "cout": m.quantite * m.cout_unitaire, "ventes": m.quantite * m.article.prix_vente})
    manquants = [x for x in lignes if x["ecart"] < 0]
    return {"lignes": lignes,
            "manque_cout": -sum(x["cout"] for x in manquants), "manque_ventes": -sum(x["ventes"] for x in manquants),
            "surplus": sum(x["ecart"] for x in lignes if x["ecart"] > 0)}

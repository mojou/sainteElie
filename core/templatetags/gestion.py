from django import template

from core.utils import format_fcfa

register = template.Library()


@register.filter
def fcfa(valeur):
    return format_fcfa(valeur)


@register.filter
def nombre(valeur):
    return format_fcfa(valeur, unite=False)


@register.filter
def nv(valeur):
    """Nombre, ou case vide quand il vaut zéro (comme sur les fiches papier)."""
    return format_fcfa(valeur, unite=False) if valeur else ""


@register.filter
def hors_seuil(ecart, seuil):
    try:
        return abs(int(ecart)) > int(seuil)
    except (TypeError, ValueError):
        return False


@register.filter
def get(dictionnaire, cle):
    try:
        return dictionnaire.get(cle)
    except AttributeError:
        return None


@register.simple_tag(takes_context=True)
def actif(context, *prefixes):
    """Renvoie 'active' si l'URL courante commence par l'un des préfixes."""
    chemin = context["request"].path
    return "active" if any(chemin.startswith(p) for p in prefixes) else ""


@register.simple_tag(takes_context=True)
def href(context, nom_url, *args, suite="", ancre="", **parametres):
    """`href="…"` vers une page, ou un lien grisé (sans adresse) si la page est dans un module pas encore ouvert.

        <a class="btn" {% href 'stock:articles' %}>Stock</a>
        <a class="btn" {% href 'postes:maintenance' chambre=chambre.pk %}>Signaler une panne</a>   → ?chambre=12
    """
    from urllib.parse import urlencode

    from django.urls import reverse
    from django.utils.html import format_html

    from core import modules

    if not modules.est_ouvert(nom_url, context.get("request")):
        return format_html('aria-disabled="true" title="{}"', modules.TITRE_FERME)
    url = reverse(nom_url, args=args) + suite
    if parametres:
        url += ("&" if "?" in url else "?") + urlencode(parametres)
    if ancre:
        url += f"#{ancre}"
    return format_html('href="{}"', url)


@register.simple_tag(takes_context=True)
def chemin_ouvert(context, chemin):
    """Une adresse enregistrée telle quelle (lien d'une alerte…) mène-t-elle à une page ouverte ?"""
    from django.urls import Resolver404, resolve

    from core import modules

    try:
        match = resolve((chemin or "").split("?")[0].split("#")[0])
    except Resolver404:
        return False
    return modules.est_ouvert(f"{match.namespace}:{match.url_name}", context.get("request"))


@register.simple_tag(takes_context=True)
def ouvert(context, cle):
    """Le module est-il ouvert ? {% ouvert 'stock' as stock_ouvert %}"""
    from core import modules

    return cle in modules.ouverts(context.get("request"))


@register.filter
def en_lettres(valeur):
    """250000 → « Deux cent cinquante mille francs CFA »."""
    from core.utils import montant_en_lettres

    return montant_en_lettres(valeur)


@register.simple_tag
def aide(cle, texte=""):
    """Petit « ? » qui explique un mot du métier en une phrase (liste dans core/aides.py)."""
    from django.utils.html import format_html

    from core.aides import GLOSSAIRE

    phrase = texte or GLOSSAIRE.get(cle, "")
    if not phrase:
        return ""
    return format_html(
        '<span class="aide-mot"><button type="button" class="aide-bouton" aria-expanded="false" '
        'aria-label="Que veut dire ce mot ?" title="{}">?</button><span class="aide-bulle" role="note" hidden>{}</span>'
        '</span>', phrase, phrase)

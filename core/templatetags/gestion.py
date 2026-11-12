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

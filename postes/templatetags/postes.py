from django import template

from caisse.services import session_ouverte_de
from core.utils import aujourd_hui

register = template.Library()


@register.inclusion_tag("postes/_entete.html", takes_context=True)
def entete_poste(context, nom, avec_caisse=False):
    """En-tête commun des pages de saisie : département, date, personne, état de la caisse."""
    request = context["request"]
    return {
        "nom": nom, "jour": aujourd_hui(), "user": request.user, "request": request, "avec_caisse": avec_caisse,
        "session": session_ouverte_de(request.user) if avec_caisse else None,
    }

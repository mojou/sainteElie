from datetime import date

from django.utils import timezone

from .models import Alerte, JournalAction


def normaliser_telephone(texte):
    """« +237 699 11 22 33 » → « 699112233 » : les chiffres seuls, sans l'indicatif du Cameroun."""
    chiffres = "".join(c for c in (texte or "") if c.isdigit())
    if len(chiffres) == 12 and chiffres.startswith("237"):
        chiffres = chiffres[3:]
    return chiffres


def maintenant():
    return timezone.now()


def aujourd_hui():
    return timezone.localdate()


def premier_du_mois(jour=None):
    jour = jour or aujourd_hui()
    return date(jour.year, jour.month, 1)


def mois_suivant(premier):
    return date(premier.year + (premier.month // 12), premier.month % 12 + 1, 1)


def journaliser(utilisateur, action, objet=None, details=""):
    JournalAction.objects.create(
        utilisateur=utilisateur if getattr(utilisateur, "pk", None) else None,
        action=action[:80],
        objet=str(objet)[:160] if objet is not None else "",
        details=details,
    )


def alerter(type_, message, public=Alerte.Public.GERANT, lien="", cle=""):
    """Crée une alerte, sauf si une alerte non lue avec la même clé existe déjà."""
    if cle and Alerte.objects.filter(cle=cle, lue_le__isnull=True).exists():
        return None
    return Alerte.objects.create(type=type_, message=message[:300], public=public, lien=lien, cle=cle)


def format_fcfa(valeur, unite=True):
    """145000 -> '145 000 FCFA' ; -1500 -> '−1 500 FCFA' (espace insécable fine)."""
    if valeur is None or valeur == "":
        return ""
    try:
        n = int(valeur)
    except (TypeError, ValueError):
        return str(valeur)
    texte = f"{abs(n):,}".replace(",", " ")
    if n < 0:
        texte = "−" + texte
    return f"{texte} FCFA" if unite else texte


# --- Montants en toutes lettres ------------------------------------------------------------------
# « 250000 » → « deux cent cinquante mille » : écrit sous chaque montant saisi (voir app.js, même règle)
# et sur les reçus, pour qu'un zéro en trop saute aux yeux. Orthographe traditionnelle : traits d'union
# sous cent ; « vingt » et « cent » prennent un s quand ils finissent le nombre (quatre-vingts, deux cents),
# pas devant « mille » (deux cent mille) ; « mille » est invariable.
_UNITES = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
           "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
_DIZAINES = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _moins_de_cent(n, final):
    if n < 20:
        return _UNITES[n]
    dizaine, unite = divmod(n, 10)
    if dizaine == 7:
        return "soixante et onze" if unite == 1 else f"soixante-{_UNITES[10 + unite]}"
    if dizaine == 8:
        return ("quatre-vingts" if final else "quatre-vingt") if unite == 0 else f"quatre-vingt-{_UNITES[unite]}"
    if dizaine == 9:
        return f"quatre-vingt-{_UNITES[10 + unite]}"
    base = _DIZAINES[dizaine]
    if unite == 0:
        return base
    return f"{base} et un" if unite == 1 else f"{base}-{_UNITES[unite]}"


def _moins_de_mille(n, final=True):
    centaine, reste = divmod(n, 100)
    morceaux = []
    if centaine == 1:
        morceaux.append("cent")
    elif centaine > 1:
        morceaux.append(f"{_UNITES[centaine]} cent" + ("s" if reste == 0 and final else ""))
    if reste:
        morceaux.append(_moins_de_cent(reste, final))
    return " ".join(morceaux)


def en_lettres(valeur):
    """145000 → « cent quarante-cinq mille » ; -500 → « moins cinq cents »."""
    try:
        n = int(valeur)
    except (TypeError, ValueError):
        return ""
    if n == 0:
        return "zéro"
    signe = "moins " if n < 0 else ""
    n = abs(n)
    milliards, n = divmod(n, 1_000_000_000)
    millions, n = divmod(n, 1_000_000)
    milliers, unites = divmod(n, 1000)
    morceaux = []
    if milliards:
        morceaux.append(f"{en_lettres(milliards)} milliard" + ("s" if milliards > 1 else ""))
    if millions:
        morceaux.append(f"{_moins_de_mille(millions)} million" + ("s" if millions > 1 else ""))
    if milliers:
        morceaux.append("mille" if milliers == 1 else f"{_moins_de_mille(milliers, final=False)} mille")
    if unites:
        morceaux.append(_moins_de_mille(unites))
    return signe + " ".join(morceaux)


def montant_en_lettres(valeur):
    """« Deux cent cinquante mille francs CFA » : la phrase des reçus."""
    texte = en_lettres(valeur)
    if not texte:
        return ""
    francs = "franc" if abs(int(valeur)) <= 1 else "francs"
    return f"{texte[0].upper()}{texte[1:]} {francs} CFA"

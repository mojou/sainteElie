"""Une image dessinée pour chaque article tant qu'il n'a pas sa vraie photo.

Le dessin dépend de ce qu'est l'article (bière, soda en verre ou en plastique, canette, eau, whisky, vin, verre au détail,
plat, bouillon, tasse, brosse à dents, sac…), reconnu à son nom, et de sa couleur (parfum, sorte). Jamais de logo ni de
photo d'une marque : une forme simple, pour que le personnel reconnaisse l'article d'un coup d'œil sur la caisse.
Une vraie photo (Stock → Photos des articles) remplace le dessin partout.
"""
import hashlib
import unicodedata
from xml.sax.saxutils import escape

VERSION = "1"  # à changer quand les dessins changent : les navigateurs rechargent alors les images

ETIQUETTES = ["#d94f30", "#2a6f97", "#e9c46a", "#3a7d44", "#8d5a97", "#f4a261", "#264653", "#bc4749", "#2b9348"]


def _normaliser(texte):
    sans_accent = unicodedata.normalize("NFD", texte or "").encode("ascii", "ignore").decode()
    return f" {sans_accent.upper()} "


def _contient(nom, *mots):
    return any(mot in nom for mot in mots)


def _choix(texte, palette):
    return palette[int(hashlib.md5(texte.encode()).hexdigest(), 16) % len(palette)]


def _eclaircir(couleur, part=0.82):
    r, g, b = (int(couleur[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(c + (255 - c) * part) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _cadre(fond, contenu):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 90" width="120" height="90">'
            f'<rect width="120" height="90" fill="{fond}"/>'
            '<ellipse cx="60" cy="84.5" rx="32" ry="4" fill="#000" opacity=".09"/>' + contenu + "</svg>")


def _reflet(x, y, h):
    return f'<rect x="{x}" y="{y}" width="2.6" height="{h}" rx="1.3" fill="#fff" opacity=".32"/>'


def _texte(x, y, texte, couleur="#1b2433", taille=6):
    return (f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{taille}" font-weight="700" '
            f'text-anchor="middle" fill="{couleur}">{escape(texte)}</text>')


# --- Boissons ---------------------------------------------------------------------------------------------------
def biere(verre, etiquette, code):
    return (f'<rect x="54.5" y="6" width="11" height="5" rx="1.5" fill="#c9ced4"/>'
            f'<path d="M56 11H64V28C64 33 71 35 71 42V80Q71 84 67 84H53Q49 84 49 80V42C49 35 56 33 56 28Z" fill="{verre}"/>'
            f'<rect x="56" y="19" width="8" height="5" fill="{etiquette}"/>'
            f'<rect x="49" y="51" width="22" height="18" fill="{etiquette}"/>'
            f'<rect x="49" y="64" width="22" height="2.5" fill="#fff" opacity=".55"/>'
            + _texte(60, 61, code, "#fff") + _reflet(52.5, 43, 34))


def soda_verre(liquide, etiquette, code):
    return (f'<rect x="53.5" y="13" width="13" height="5" rx="1.5" fill="{etiquette}"/>'
            f'<path d="M55 18H65V30C65 36 72 37 72 45V80Q72 84 68 84H52Q48 84 48 80V45C48 37 55 36 55 30Z" fill="{liquide}" '
            'stroke="#000" stroke-opacity=".18"/>'
            '<rect x="55.5" y="18.5" width="9" height="8" fill="#fff" opacity=".55"/>'
            f'<rect x="48" y="54" width="24" height="14" fill="#fff" opacity=".9"/>'
            f'<rect x="48" y="58" width="24" height="5" fill="{etiquette}"/>' + _texte(60, 66.6, code, "#1b2433", 4.6)
            + _reflet(51.5, 46, 30))


def soda_plastique(liquide, etiquette, code, bouchon=None):
    return (f'<rect x="54" y="6" width="12" height="6" rx="1.5" fill="{bouchon or etiquette}"/>'
            f'<path d="M56 12H64V16C64 22 75 24 75 32V78Q75 84 69 84H51Q45 84 45 78V32C45 24 56 22 56 16Z" fill="{liquide}" '
            'fill-opacity=".92" stroke="#000" stroke-opacity=".15"/>'
            '<path d="M46 37H74M46 75H74" stroke="#fff" stroke-opacity=".55" stroke-width="1.5"/>'
            f'<rect x="45" y="46" width="30" height="20" fill="#fff"/>'
            f'<rect x="45" y="51" width="30" height="7" fill="{etiquette}"/>' + _texte(60, 64, code, "#1b2433", 5)
            + _reflet(48.5, 26, 16))


def canette(couleur, code):
    return (f'<rect x="47" y="24" width="26" height="58" rx="4" fill="{couleur}"/>'
            '<rect x="48" y="19" width="24" height="7" rx="2.5" fill="#c9ced4"/>'
            '<rect x="48" y="79" width="24" height="5" rx="2.5" fill="#b0b7bf"/>'
            '<rect x="47" y="43" width="26" height="15" fill="#fff" opacity=".85"/>' + _texte(60, 53, code, couleur, 6)
            + _reflet(50, 28, 48))


def spiritueux(liquide, bouchon, etiquette, code):
    return (f'<rect x="54" y="8" width="12" height="9" rx="1.5" fill="{bouchon}"/>'
            f'<rect x="56" y="17" width="8" height="12" fill="{liquide}"/>'
            f'<path d="M56 29H64Q76 31 76 38V80Q76 84 72 84H48Q44 84 44 80V38Q44 31 56 29Z" fill="{liquide}" '
            'stroke="#000" stroke-opacity=".15"/>'
            '<rect x="47" y="47" width="26" height="22" rx="1" fill="#f6eedb"/>'
            f'<rect x="49" y="49" width="22" height="18" fill="none" stroke="{etiquette}" stroke-width="1.2"/>'
            + _texte(60, 61, code, etiquette, 5.5) + _reflet(47.5, 36, 42))


def liqueur(liquide, bouchon, code):
    return (f'<rect x="54.5" y="10" width="11" height="15" rx="2" fill="{bouchon}"/>'
            f'<path d="M56 25H64V32C74 34 78 42 78 56V78Q78 84 72 84H48Q42 84 42 78V56C42 42 46 34 56 32Z" fill="{liquide}" '
            'stroke="#000" stroke-opacity=".15"/>'
            '<ellipse cx="60" cy="60" rx="13" ry="9" fill="#fbf4e6"/>' + _texte(60, 62, code, "#6b4423", 5)
            + _reflet(46.5, 46, 28))


def vin(verre, capsule, code):
    return (f'<rect x="55.5" y="4" width="9" height="14" rx="1.5" fill="{capsule}"/>'
            f'<path d="M56 18H64V34C64 38 70 39 70 44V80Q70 84 66 84H54Q50 84 50 80V44C50 39 56 38 56 34Z" fill="{verre}"/>'
            '<rect x="50" y="56" width="20" height="17" fill="#f6efe0"/>'
            f'<rect x="52" y="58" width="16" height="2" fill="{capsule}"/>' + _texte(60, 69, code, "#6b1f2e", 4.6)
            + _reflet(52.6, 45, 30))


def mousseux(code):
    return ('<path d="M56 6H64V22C64 32 71 34 71 46V80Q71 84 67 84H53Q49 84 49 80V46C49 34 56 32 56 22Z" fill="#24452f"/>'
            '<path d="M55 3H65V24C65 28 58 28 55 24Z" fill="#d4a94c"/>'
            '<ellipse cx="60" cy="62" rx="10" ry="8" fill="#f6efe0"/>' + _texte(60, 64, code, "#24452f", 4.6)
            + _reflet(52, 46, 30))


def verre(liquide, glacons=False):
    glace = ('<rect x="50" y="44" width="9" height="9" rx="1.5" fill="#eaf7fc" opacity=".9" transform="rotate(12 54 48)"/>'
             '<rect x="60" y="46" width="9" height="9" rx="1.5" fill="#eaf7fc" opacity=".9" transform="rotate(-10 64 50)"/>'
             if glacons else "")
    return ('<path d="M42 30H78L74 80Q73.5 84 69 84H51Q46.5 84 46 80Z" fill="#fff" fill-opacity=".55" stroke="#9fb0ba"/>'
            f'<path d="M44.2 52H75.8L74 80Q73.5 84 69 84H51Q46.5 84 46 80Z" fill="{liquide}" fill-opacity=".92"/>'
            + glace + '<rect x="46" y="34" width="2.6" height="44" rx="1.3" fill="#fff" opacity=".5"/>')


def eau(code):
    return soda_plastique("#d6ecf8", "#2a7fd4", code, bouchon="#1e64b4")


# --- Plats et boissons chaudes -----------------------------------------------------------------------------------
def assiette(contenu):
    return ('<ellipse cx="60" cy="60" rx="47" ry="20" fill="#fff" stroke="#ddd5c5"/>'
            '<ellipse cx="60" cy="59" rx="35" ry="13.5" fill="#f3ede2"/>' + contenu)


def poulet(accompagnement=""):
    return assiette(accompagnement + '<ellipse cx="55" cy="55" rx="16" ry="10" fill="#b5651d"/>'
                    '<ellipse cx="51" cy="52" rx="8" ry="4" fill="#d8893d" opacity=".7"/>'
                    '<rect x="68" y="51" width="13" height="4.5" rx="2.2" fill="#f4ead8"/>'
                    '<circle cx="82" cy="50.5" r="3" fill="#f4ead8"/><circle cx="82" cy="56" r="3" fill="#f4ead8"/>')


def poisson(couleur="#a8b4bc"):
    return assiette(f'<ellipse cx="57" cy="56" rx="21" ry="8.5" fill="{couleur}"/>'
                    f'<path d="M76 56L89 47V65Z" fill="{couleur}"/>'
                    '<circle cx="43" cy="54" r="1.7" fill="#222"/>'
                    '<path d="M52 50L49 62M60 49L57 63M68 50L65 62" stroke="#000" stroke-opacity=".22" stroke-width="1.5"/>')


def viande(couleur="#7a3b1e"):
    return assiette('<ellipse cx="60" cy="57" rx="26" ry="9" fill="#a4522a" opacity=".45"/>'
                    f'<rect x="43" y="50" width="13" height="9" rx="3" fill="{couleur}"/>'
                    f'<rect x="56" y="46" width="13" height="10" rx="3" fill="{couleur}"/>'
                    f'<rect x="65" y="54" width="13" height="9" rx="3" fill="{couleur}"/>'
                    '<rect x="52" y="57" width="10" height="7" rx="2.5" fill="#5e2c14"/>')


def brochettes():
    morceaux = "".join(f'<rect x="{x}" y="{y}" width="8" height="7" rx="2" fill="{c}"/>'
                       for x, y, c in [(40, 55, "#7a3b1e"), (50, 52, "#e9d8a6"), (60, 49, "#7a3b1e"),
                                       (70, 46, "#c0392b"), (44, 63, "#7a3b1e"), (54, 60, "#e9d8a6"), (64, 57, "#7a3b1e")])
    return assiette('<path d="M32 62L88 45M34 70L90 53" stroke="#c9a46a" stroke-width="2"/>' + morceaux)


def boulettes():
    return assiette('<ellipse cx="60" cy="57" rx="25" ry="8.5" fill="#c0392b" opacity=".35"/>' + "".join(
        f'<circle cx="{x}" cy="{y}" r="6.5" fill="#7a3b1e"/><circle cx="{x - 2}" cy="{y - 2}" r="2" fill="#a0522d"/>'
        for x, y in [(48, 56), (60, 52), (72, 56), (60, 61)]))


def tripes():
    return assiette('<path d="M42 55c6-6 10 6 16 0s10 6 16 0M44 61c6-6 10 6 16 0s10 6 16 0" stroke="#e6d3b3" '
                    'stroke-width="5" fill="none" stroke-linecap="round"/>'
                    '<path d="M42 55c6-6 10 6 16 0s10 6 16 0" stroke="#c9a77a" stroke-width="1" fill="none"/>')


def feuilles():
    points = "".join(f'<circle cx="{x}" cy="{y}" r="2" fill="{c}"/>' for x, y, c in
                     [(48, 53, "#1f4d1f"), (58, 50, "#5a9a3a"), (66, 56, "#1f4d1f"), (54, 59, "#5a9a3a"),
                      (72, 52, "#5a9a3a"), (44, 58, "#5a9a3a")])
    return assiette('<ellipse cx="60" cy="55" rx="25" ry="9.5" fill="#2f6b2f"/>' + points
                    + '<rect x="62" y="50" width="9" height="6" rx="2" fill="#7a3b1e"/>')


def spaghetti(garni=False):
    pates = "".join(f'<path d="M{x} {y}c4-5 8 5 12 0s8 5 12 0" stroke="#e9c46a" stroke-width="2.4" fill="none" '
                    'stroke-linecap="round"/>' for x, y in [(42, 52), (46, 56), (40, 60), (50, 49), (52, 63)])
    extra = ('<rect x="56" y="53" width="8" height="5" rx="1.5" fill="#9aa7b0"/>'
             '<circle cx="68" cy="58" r="3.5" fill="#c0392b"/>') if garni else ""
    return assiette(pates + extra)


def riz():
    grains = "".join(f'<ellipse cx="{x}" cy="{y}" rx="1.6" ry=".8" fill="#e2dccb"/>'
                     for x, y in [(52, 52), (58, 49), (64, 53), (70, 51), (56, 57), (66, 58), (48, 56)])
    return assiette('<ellipse cx="60" cy="54" rx="22" ry="9" fill="#fbfaf5" stroke="#e8e2d0"/>' + grains)


def manioc():
    return assiette('<rect x="38" y="50" width="44" height="8" rx="4" fill="#f1ead2" stroke="#d8cfae" transform="rotate(-8 60 54)"/>'
                    '<rect x="40" y="58" width="44" height="8" rx="4" fill="#f1ead2" stroke="#d8cfae" transform="rotate(-8 62 62)"/>'
                    '<path d="M36 58c8-10 16-2 22-8" stroke="#4f8f3a" stroke-width="3" fill="none"/>')


def frites(plantain=False):
    if plantain:
        morceaux = "".join(f'<ellipse cx="{x}" cy="{y}" rx="6" ry="3.5" fill="#f08c1e" stroke="#c96a0c" '
                           f'transform="rotate(-20 {x} {y})"/>'
                           for x, y in [(46, 55), (56, 51), (66, 55), (74, 51), (52, 60), (64, 61)])
    else:
        morceaux = "".join(f'<rect x="{x}" y="{y}" width="4" height="16" rx="1.5" fill="#f2c94c" stroke="#d8a92c" '
                           f'transform="rotate({r} {x} {y})"/>'
                           for x, y, r in [(46, 46, -30), (54, 44, -10), (60, 45, 15), (66, 46, 35), (50, 50, 20), (70, 49, -25)])
    return assiette(morceaux)


def omelette():
    return assiette('<path d="M38 60C38 44 82 44 82 60Z" fill="#f2c94c" stroke="#e0a91e"/>'
                    '<circle cx="52" cy="53" r="2" fill="#e0a91e"/><circle cx="66" cy="51" r="2.4" fill="#6fa83a"/>'
                    '<circle cx="60" cy="56" r="1.8" fill="#c0392b"/>')


def crudites():
    return assiette('<ellipse cx="54" cy="55" rx="15" ry="7" fill="#6fa83a"/><ellipse cx="66" cy="53" rx="12" ry="6" fill="#8bc34a"/>'
                    '<circle cx="50" cy="52" r="4.5" fill="#e63946"/><circle cx="70" cy="57" r="4.5" fill="#e63946"/>'
                    '<rect x="58" y="57" width="10" height="2.5" rx="1" fill="#f08c1e"/>')


def bol(soupe, morceaux="#7a3b1e"):
    vapeur = ('<path d="M50 34c-4-5 4-7 0-12M60 32c-4-5 4-7 0-12M70 34c-4-5 4-7 0-12" stroke="#b8b0a0" '
              'stroke-width="2" fill="none" stroke-linecap="round" opacity=".8"/>')
    return (vapeur + '<path d="M30 46H90C90 65 78 80 60 80C42 80 30 65 30 46Z" fill="#fff" stroke="#ddd5c5"/>'
            f'<ellipse cx="60" cy="46" rx="30" ry="6.5" fill="{soupe}"/>'
            f'<rect x="48" y="43" width="8" height="5" rx="2" fill="{morceaux}"/>'
            f'<rect x="62" y="44" width="9" height="5" rx="2" fill="{morceaux}"/>'
            '<path d="M38 62c6 4 38 4 44 0" stroke="#c9a46a" stroke-width="2" fill="none"/>')


def fruits():
    return ('<path d="M28 48H92C92 66 78 80 60 80C42 80 28 66 28 48Z" fill="#fff" stroke="#ddd5c5"/>'
            + "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>' for x, y, r, c in
                      [(44, 44, 7, "#e63946"), (56, 41, 7, "#f4a261"), (68, 43, 7, "#e9c46a"), (78, 46, 6, "#6fa83a"),
                       (50, 48, 6, "#8d5a97"), (63, 48, 6, "#f08c1e")])
            + '<ellipse cx="60" cy="48" rx="32" ry="4" fill="#fff" opacity=".35"/>')


def tasse(boisson, x=0, echelle=1.0, vapeur=True):
    fumee = ('<path d="M52 36c-4-5 4-7 0-12M62 34c-4-5 4-7 0-12" stroke="#b8b0a0" stroke-width="2" fill="none" '
             'stroke-linecap="round" opacity=".8"/>') if vapeur else ""
    dessin = (fumee + '<ellipse cx="60" cy="80" rx="30" ry="5" fill="#fff" stroke="#ddd5c5"/>'
              '<path d="M78 50C89 50 89 66 78 66" stroke="#fff" stroke-width="5" fill="none"/>'
              '<path d="M78 50C89 50 89 66 78 66" stroke="#ddd5c5" stroke-width="1" fill="none"/>'
              '<path d="M40 44H78V62C78 74 70 80 59 80C48 80 40 74 40 62Z" fill="#fff" stroke="#ddd5c5"/>'
              f'<ellipse cx="59" cy="45" rx="18.5" ry="3.5" fill="{boisson}"/>')
    if echelle == 1.0 and not x:
        return dessin
    return f'<g transform="translate({x} {90 - 90 * echelle}) scale({echelle})">{dessin}</g>'


def petit_dejeuner():
    return (tasse("#6f4e37", x=-8, echelle=.72, vapeur=False)
            + '<rect x="62" y="56" width="46" height="13" rx="6.5" fill="#d9a35b" transform="rotate(-18 85 62)"/>'
            '<path d="M72 64l5-6M82 61l5-6M92 58l5-6" stroke="#b07a35" stroke-width="2" stroke-linecap="round"/>'
            '<ellipse cx="80" cy="77" rx="10" ry="6" fill="#fff" stroke="#e8e2d0"/><circle cx="80" cy="77" r="3.5" fill="#f2b705"/>')


# --- Boutique et magasin ----------------------------------------------------------------------------------------
def brosse_a_dent():
    return ('<g transform="rotate(-20 60 50)"><rect x="26" y="48" width="58" height="7" rx="3.5" fill="#3a86c8"/>'
            '<rect x="72" y="39" width="16" height="9" rx="2" fill="#e8f4fb" stroke="#9fc4e0"/>'
            '<path d="M75 39v9M79 39v9M83 39v9" stroke="#9fc4e0"/></g>')


def dentifrice():
    return ('<g transform="rotate(-15 60 50)"><rect x="32" y="41" width="50" height="18" rx="3" fill="#fff" stroke="#c7d3de"/>'
            '<rect x="80" y="38" width="6" height="24" rx="1" fill="#2d6fb7"/><rect x="23" y="45" width="10" height="10" rx="2" fill="#2d6fb7"/>'
            '<rect x="40" y="45" width="32" height="10" rx="2" fill="#2d6fb7" opacity=".85"/></g>')


def serviettes():
    return ('<rect x="36" y="24" width="48" height="58" rx="7" fill="#f3b6cf"/>'
            '<path d="M60 36C70 48 72 56 72 62A12 12 0 0 1 48 62C48 56 50 48 60 36Z" fill="#fff"/>'
            '<rect x="36" y="72" width="48" height="5" fill="#e48aae"/>')


def cirage():
    return ('<rect x="34" y="48" width="52" height="16" fill="#1d1d1d"/><ellipse cx="60" cy="64" rx="26" ry="8" fill="#1d1d1d"/>'
            '<ellipse cx="60" cy="48" rx="26" ry="8" fill="#3a3a3a"/><ellipse cx="60" cy="48" rx="14" ry="4.5" fill="#c9a227"/>')


def pot_creme():
    return ('<rect x="40" y="46" width="40" height="34" rx="6" fill="#fff" stroke="#c7d3de"/>'
            '<rect x="38" y="37" width="44" height="12" rx="3" fill="#2f8f6b"/>'
            '<rect x="40" y="58" width="40" height="10" fill="#2f8f6b" opacity=".25"/>')


def lotion():
    return ('<rect x="52" y="18" width="16" height="13" rx="3" fill="#4f8f3a"/>'
            '<rect x="47" y="30" width="26" height="52" rx="9" fill="#e8f3e1" stroke="#a9c99a"/>'
            '<path d="M60 48C68 52 68 62 60 68C52 62 52 52 60 48Z" fill="#4f8f3a"/>')


def lessive():
    return ('<rect x="38" y="20" width="44" height="62" rx="3" fill="#f2f6fb" stroke="#b9c9dc"/>'
            '<rect x="38" y="20" width="44" height="30" rx="3" fill="#1f64b8"/>'
            '<circle cx="50" cy="62" r="5" fill="none" stroke="#7fb0e6" stroke-width="2"/>'
            '<circle cx="64" cy="68" r="7" fill="none" stroke="#7fb0e6" stroke-width="2"/>'
            '<circle cx="70" cy="56" r="3.5" fill="none" stroke="#7fb0e6" stroke-width="2"/>')


def brosse_cirage():
    return ('<rect x="34" y="44" width="52" height="15" rx="6" fill="#b07a45"/>'
            '<rect x="36" y="59" width="48" height="13" fill="#2b2b2b"/>'
            '<path d="M42 59v13M50 59v13M58 59v13M66 59v13M74 59v13" stroke="#555"/>')


def boucles():
    return ('<circle cx="46" cy="44" r="12" fill="none" stroke="#d4a94c" stroke-width="3"/>'
            '<circle cx="74" cy="44" r="12" fill="none" stroke="#d4a94c" stroke-width="3"/>'
            '<path d="M46 56V64M74 56V64" stroke="#d4a94c" stroke-width="2"/>'
            '<circle cx="46" cy="68" r="5" fill="#2a9d8f"/><circle cx="74" cy="68" r="5" fill="#2a9d8f"/>')


def collier():
    return ('<path d="M30 20C34 70 86 70 90 20" stroke="#d4a94c" stroke-width="3" fill="none"/>'
            '<circle cx="60" cy="60" r="2.5" fill="none" stroke="#d4a94c" stroke-width="2"/>'
            '<path d="M60 63L67 72L60 81L53 72Z" fill="#c0392b" stroke="#d4a94c" stroke-width="1.5"/>')


def sac_a_dos():
    return ('<path d="M52 28C52 18 68 18 68 28" stroke="#1f3f5f" stroke-width="4" fill="none"/>'
            '<rect x="40" y="27" width="40" height="55" rx="12" fill="#2f5d8a"/>'
            '<rect x="46" y="56" width="28" height="20" rx="5" fill="#244a6e"/>'
            '<path d="M48 62H72" stroke="#d4a94c" stroke-width="1.5"/>')


def sac_a_main():
    return ('<path d="M46 46C46 26 74 26 74 46" stroke="#7b2d3a" stroke-width="4" fill="none"/>'
            '<path d="M34 44H86L80 80Q79.5 82 77 82H43Q40.5 82 40 80Z" fill="#9b3b4a"/>'
            '<rect x="55" y="50" width="10" height="7" rx="1.5" fill="#d4a94c"/>')


def ballerine():
    return ('<path d="M26 66C26 56 40 52 52 54C62 56 70 58 82 58C93 58 95 67 88 71C80 75 40 75 31 73C28 72 26 69 26 66Z" '
            'fill="#d0476f"/><ellipse cx="52" cy="58" rx="16" ry="4" fill="#7a1f3d"/>'
            '<path d="M66 58l-5-4v8zM66 58l5-4v8z" fill="#f3b6cf"/>')


def botte():
    return ('<path d="M40 18H66V54C76 56 90 60 90 70V76H40Z" fill="#6b4423"/>'
            '<rect x="38" y="76" width="54" height="6" rx="2" fill="#2b1d12"/>'
            '<path d="M46 26H60M46 34H60M46 42H60" stroke="#e9d8a6" stroke-width="2"/>')


def rasoir():
    return ('<g transform="rotate(-30 60 52)"><rect x="24" y="48" width="54" height="7" rx="3.5" fill="#f0a51e"/>'
            '<rect x="76" y="40" width="11" height="23" rx="2" fill="#f6f6f6" stroke="#b0b7bf"/>'
            '<path d="M83 42v19" stroke="#8d99a6"/></g>')


def casque():
    return ('<path d="M34 58C34 26 86 26 86 58" stroke="#333" stroke-width="6" fill="none"/>'
            '<rect x="26" y="52" width="15" height="24" rx="6" fill="#333"/><rect x="79" y="52" width="15" height="24" rx="6" fill="#333"/>'
            '<rect x="37" y="55" width="6" height="18" rx="3" fill="#2a6f97"/><rect x="77" y="55" width="6" height="18" rx="3" fill="#2a6f97"/>')


def bocal(contenu, couvercle):
    if contenu == "bonbons":
        interieur = "".join(f'<circle cx="{x}" cy="{y}" r="4.2" fill="{c}"/>' for x, y, c in
                            [(46, 44, "#e63946"), (56, 48, "#f4a261"), (68, 44, "#2a9d8f"), (74, 54, "#8d5a97"),
                             (48, 58, "#e9c46a"), (60, 62, "#e63946"), (70, 68, "#2a6f97"), (50, 72, "#f4a261"),
                             (62, 76, "#2a9d8f"), (73, 76, "#e9c46a")])
        fond = "#fdf4e3"
    else:
        fond = contenu
        interieur = "".join(f'<ellipse cx="{x}" cy="{y}" rx="3.2" ry="2.2" fill="#000" opacity=".14"/>'
                            for x, y in [(48, 44), (60, 48), (70, 44), (54, 58), (66, 60), (48, 70), (62, 72), (72, 68)])
    return (f'<rect x="42" y="15" width="36" height="9" rx="2" fill="{couvercle}"/>'
            f'<rect x="40" y="36" width="40" height="45" rx="6" fill="{fond}"/>' + interieur
            + '<rect x="38" y="23" width="44" height="60" rx="8" fill="#fff" fill-opacity=".25" stroke="#9fb0ba"/>'
            + _reflet(42, 30, 46))


def cacahuetes():
    une = ('<g transform="translate({x} {y}) rotate({r})"><ellipse cx="0" cy="-6" rx="7" ry="8" fill="#d4a066"/>'
           '<ellipse cx="0" cy="7" rx="7.5" ry="8.5" fill="#d4a066"/><path d="M-4 -8h8M-5 6h10" stroke="#b07a45" '
           'stroke-width="1.2"/></g>')
    return "".join(une.format(x=x, y=y, r=r) for x, y, r in [(46, 52, -25), (62, 56, 15), (76, 50, -5)])


def noix_de_coco():
    return ('<circle cx="46" cy="54" r="22" fill="#6b4423"/><circle cx="40" cy="48" r="2.5" fill="#3b2412"/>'
            '<circle cx="50" cy="46" r="2.5" fill="#3b2412"/><circle cx="45" cy="56" r="2.5" fill="#3b2412"/>'
            '<path d="M60 60A18 18 0 0 0 96 60Z" fill="#6b4423"/><path d="M63 60A15 15 0 0 0 93 60Z" fill="#fbfaf5"/>')


def draps():
    return ('<rect x="32" y="62" width="56" height="13" rx="3" fill="#e8eef6" stroke="#b9c9dc"/>'
            '<rect x="35" y="49" width="50" height="13" rx="3" fill="#cfe0f2" stroke="#b9c9dc"/>'
            '<rect x="38" y="36" width="44" height="13" rx="3" fill="#b7d0ea" stroke="#9db8d6"/>')


def savon():
    return ('<rect x="36" y="46" width="48" height="28" rx="11" fill="#f6d7e6" stroke="#e3a9c4"/>'
            '<circle cx="44" cy="38" r="5" fill="none" stroke="#9fc4e0" stroke-width="1.5"/>'
            '<circle cx="56" cy="32" r="3.5" fill="none" stroke="#9fc4e0" stroke-width="1.5"/>'
            '<circle cx="76" cy="38" r="4" fill="none" stroke="#9fc4e0" stroke-width="1.5"/>')


def sac_courses(couleur):
    return ('<path d="M50 36C50 24 70 24 70 36" stroke="#5f6a7a" stroke-width="3" fill="none"/>'
            f'<path d="M38 36H82L86 82H34Z" fill="{couleur}"/>')


def carton():
    return ('<path d="M34 38L60 28L86 38V74L60 84L34 74Z" fill="#c9a46a"/><path d="M34 38L60 48L86 38" stroke="#a9844a" '
            'fill="none" stroke-width="1.5"/><path d="M60 48V84" stroke="#a9844a" stroke-width="1.5"/>')


# --- Reconnaître l'article à son nom ----------------------------------------------------------------------------
SAVEURS = [(("COCA", "COLA"), "#3b1d10"), (("DJINO",), "#e85d2a"), (("GRENADINE",), "#c4142f"),
           (("PAMPLEMOUSSE",), "#f07a7a"), (("ANANAS",), "#f2c230"), (("ORANGE", "ORANGINA"), "#f39a1e"),
           (("SPRITE",), "#cfe9b9"), (("TONIC",), "#e8f1f3"), (("VIMTO",), "#7b1e3c"), (("XXL",), "#6a3d9a"),
           (("SODA",), "#e8f1f3")]
SODAS = ("COCA", "DJINO", " TOP ", "ORANGINA", "SPRITE", "TONIC", "XXL", "VIMTO", " SODA ")
BIERES = ("33 EXPORT", "BEAUFORT", "CASTEL", "DOPPEL", "ISENBECK", "MUTZIG", "GUINNESS", "HARP", "ORIGIN", "KADJI",
          "HEINEKEN", "BOOSTER", "CHILL", " ICE ", "MALTA", "BIERE")
WHISKIES = ("WHITE HORSE", "BLACK & WHITE", "BLACK LABEL", "CHIVAS", "GRANTS", "J & B", "JACK DANIEL", "WHISK",
            "RED LABEL", "BALLENTINE", "LORDSON")
LIQUEURS = ("AMARULA", "BAILEYS")
MOUSSEUX = ("COOKS", "POL REMY", "CHAMPAIGN", "CHAMPAGNE", "MUSCATO", "PAUL BERNARD", "PROSPERITY")


def _saveur(nom):
    for mots, couleur in SAVEURS:
        if _contient(nom, *mots):
            return couleur
    return "#e8f1f3"


def _alcool(nom):
    """Couleur et bouchon d'un alcool fort, d'après sa sorte."""
    if _contient(nom, "GIN", "VODKA", "NIGHTS"):
        return "#e9f2f5", "#3a5a6a"
    if _contient(nom, "CAMPARI"):
        return "#c4142f", "#1b2433"
    if _contient(nom, "MARTINI ROUGE", "VERMOUT"):
        return "#7b1e2c", "#1b2433"
    if _contient(nom, "BIANCO"):
        return "#efe2a0", "#1b2433"
    if _contient(nom, "ROSE"):
        return "#f2a7b5", "#1b2433"
    if _contient(nom, "PASTIS"):
        return "#d9d27a", "#1e64b4"
    if _contient(nom, "JACK DANIEL"):
        return "#5a2e0e", "#1b1b1b"
    if _contient(nom, *LIQUEURS):
        return "#d8c3a0", "#5a3b22"
    return "#b8621b", "#2b1d12"


def dessin_boisson(nom, code):
    contenance = code.lower() if code else ""
    etiquette = _choix(nom, ETIQUETTES)
    if _contient(nom, " CONSO "):
        liquide, _ = _alcool(nom)
        return verre(liquide, glacons=_contient(nom, *WHISKIES) or liquide == "#b8621b"), _eclaircir(liquide, .8)
    if _contient(nom, "CANETTE"):
        return canette(etiquette, contenance), _eclaircir(etiquette)
    if _contient(nom, "SUPERMONT", "TANGUI", " EAU "):
        return eau(contenance), "#e6f2fb"
    if _contient(nom, *SODAS):
        liquide = _saveur(nom)
        if _contient(nom, "PLASTIQUE") or contenance in ("1l", "1,5l", "2l"):
            return soda_plastique(liquide, etiquette, contenance), _eclaircir(liquide, .85)
        return soda_verre(liquide, etiquette, contenance), _eclaircir(liquide, .85)
    if _contient(nom, *BIERES):
        verre_bouteille = "#2a1a12" if _contient(nom, "GUINNESS", "MALTA") else (
            "#2f6b3a" if _contient(nom, "HEINEKEN", "HARP") else "#7a3f12")
        return biere(verre_bouteille, etiquette, contenance), "#f6ecd9"
    if _contient(nom, *MOUSSEUX):
        return mousseux(contenance), "#eef3ea"
    if _contient(nom, *LIQUEURS):
        liquide, bouchon = _alcool(nom)
        return liqueur(liquide, bouchon, contenance), "#f3ebdd"
    if _contient(nom, *WHISKIES, "GIN", "VODKA", "CAMPARI", "MARTINI", "PASTIS", "VERMOUT"):
        liquide, bouchon = _alcool(nom)
        return spiritueux(liquide, bouchon, etiquette, contenance), _eclaircir(liquide, .86)
    if _contient(nom, "BORDEAUX", "CHATEAU", "ESCHENEAU", "ISABELLE", "MOULIN", "CHENET", "PITAR", "FLORIDA", " VIN "):
        return vin("#3a1220", "#7b1e2c", contenance), "#f3e3e6"
    return vin("#5a2e0e", "#d4a94c", contenance), "#f3ebdd"


def dessin_plat(nom):
    if _contient(nom, "BOUILLON"):
        return bol("#c96a2c" if _contient(nom, "POISSON") else "#8a4a24",
                   "#9aa7b0" if _contient(nom, "POISSON") else "#7a3b1e"), "#f7efe3"
    if _contient(nom, "SALADE DE FRUITS"):
        return fruits(), "#fdf1e4"
    if _contient(nom, "SALADE"):
        return crudites(), "#eef6e6"
    if _contient(nom, "PETIT-DEJEUNER", "PETIT DEJEUNER"):
        return petit_dejeuner(), "#f7efe3"
    if _contient(nom, "CHOCOLAT"):
        return tasse("#5a3420"), "#f3ebe3"
    if _contient(nom, "CAFE"):
        return tasse("#3b2412"), "#f3ebe3"
    if _contient(nom, "LAIT"):
        return tasse("#fbf7ee"), "#eef2f6"
    if _contient(nom, " THE "):
        return tasse("#b5651d"), "#f6efe3"
    if _contient(nom, "OMELETTE"):
        return omelette(), "#fbf3dc"
    if _contient(nom, "POULET"):
        sauce = ('<ellipse cx="60" cy="58" rx="27" ry="9" fill="#c0702a" opacity=".55"/>'
                 if _contient(nom, "ARACHIDE") else "")
        plantains = ('<ellipse cx="80" cy="62" rx="5" ry="3" fill="#f08c1e"/><ellipse cx="40" cy="62" rx="5" ry="3" fill="#f08c1e"/>'
                     if _contient(nom, " DG ") else "")
        return poulet(sauce + plantains), "#f7efe3"
    if _contient(nom, "NDOLE", "FOLONG"):
        return feuilles(), "#edf4e6"
    if _contient(nom, "SPAGHETTI"):
        return spaghetti(garni=_contient(nom, "GARNI")), "#fbf3dc"
    if _contient(nom, " RIZ "):
        return riz(), "#f4f1e8"
    if _contient(nom, "MANIOC"):
        return manioc(), "#eef4e6"
    if _contient(nom, "PLANTAIN"):
        return frites(plantain=True), "#fdf1e4"
    if _contient(nom, "POMMES", "FRITES"):
        return frites(), "#fbf3dc"
    if _contient(nom, " BAR ", "MAQUEREAU", "CARPE", "POISSON"):
        grille = _contient(nom, "BRAIS", "GRILL")
        return poisson("#c8873a" if grille else "#a8b4bc"), "#eef2f6"
    if _contient(nom, "BROCHETTE"):
        return brochettes(), "#f7efe3"
    if _contient(nom, "BOULETTE"):
        return boulettes(), "#f7efe3"
    if _contient(nom, "TRIPES"):
        return tripes(), "#f7efe3"
    if _contient(nom, "ROGNON"):
        return viande("#6b1f2e"), "#f7efe3"
    return viande(), "#f7efe3"


def dessin_boutique(nom):
    regles = [(("BROSSE A CIRAGE",), brosse_cirage, "#efe6da"), (("BROSSE A DENT",), brosse_a_dent, "#e6f1fa"),
              (("COLGATE", "DENTIFRICE"), dentifrice, "#e6f1fa"), (("SERVIETTE",), serviettes, "#fbe9f1"),
              (("CIRAGE",), cirage, "#efe6da"), (("SANTEX", "CREME", "POMMADE"), pot_creme, "#e7f3ee"),
              (("HERBODERM", "LOTION"), lotion, "#eef6e6"), (("OMO", "LESSIVE", "DETERGENT"), lessive, "#e6eef8"),
              (("BOUCLE",), boucles, "#f6f0e1"), (("COLLIER", "CHAINE"), collier, "#f6f0e1"),
              (("SAC A DOS",), sac_a_dos, "#e6eef6"), (("SAC A MAIN", " SAC "), sac_a_main, "#f6e6ea"),
              (("BALLERINE",), ballerine, "#fbe9f1"), (("CHAUSSURE", "BOTTE"), botte, "#f3ebe3"),
              (("RASOIR",), rasoir, "#fdf1e4"), (("CASQUE", "ECOUTEUR"), casque, "#e9eef3"),
              (("CACAHUETE",), cacahuetes, "#f6ecd9"), (("COCONUT", "COCO"), noix_de_coco, "#eef4e6"),
              (("DRAP",), draps, "#e9eff6"), (("SAVON",), savon, "#fbe9f1")]
    for mots, dessin, fond in regles:
        if _contient(nom, *mots):
            return dessin(), fond
    if _contient(nom, "CARAMEL", "BONBON"):
        return bocal("bonbons", "#e63946"), "#fdf1e4"
    if _contient(nom, "MAIS"):
        return bocal("#f2c94c", "#2a9d8f"), "#fbf3dc"
    if _contient(nom, "ARACHIDE"):
        return bocal("#c98b4b", "#bc4749"), "#f6ecd9"
    if _contient(nom, "CROQUETTE"):
        return bocal("#d9a25b", "#2a6f97"), "#f6ecd9"
    return sac_courses(_choix(nom, ETIQUETTES)), "#e9eff6"


def illustration_svg(article):
    """Le dessin SVG d'un article (texte du fichier)."""
    nom = _normaliser(article.nom)
    if article.categorie == "BAR":
        contenu, fond = dessin_boisson(nom, article.code)
    elif article.categorie == "RESTAURANT":
        contenu, fond = dessin_plat(nom)
    elif article.categorie == "BOUTIQUE":
        contenu, fond = dessin_boutique(nom)
    else:
        contenu, fond = dessin_boutique(nom)
        if contenu.startswith('<path d="M50 36C50 24'):  # rien de reconnu au magasin : un carton
            contenu, fond = carton(), "#f3ebdd"
    return _cadre(fond, contenu)

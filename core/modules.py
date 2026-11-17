"""
Modules ouverts et modules grisés.

L'hôtel démarre avec la réservation et la vente des chambres seulement : réservations en ligne, séjours, plan des
chambres, arrivées et départs, paiements à la caisse de la réception, ménage des chambres, comptes et réglages.
Le reste est visible mais grisé ; le gérant l'ouvre quand l'équipe est prête, un module à la fois
(Paramètres → Modules). Un module fermé est aussi bloqué côté serveur : une adresse tapée à la main ne l'ouvre pas.
"""
from dataclasses import dataclass

from django.shortcuts import render

TITRE_FERME = "Pas encore ouvert : le gérant l'ouvre dans Paramètres → Modules"


@dataclass(frozen=True)
class Module:
    cle: str
    nom: str
    contenu: str
    adresses: tuple  # « espace:nom » ou « espace:* »

    def contient(self, nom_url):
        espace = nom_url.split(":", 1)[0]
        return nom_url in self.adresses or f"{espace}:*" in self.adresses


MODULES = (
    Module("ventes", "Boutique, restaurant · bar",
           "Point de vente (boutique à la réception, restaurant et bar), extras sur chambre, crédits des clients, "
           "mains courantes du bar et de la boutique.",
           ("caisse:ventes", "caisse:vente_annuler", "caisse:avarie", "caisse:credits", "caisse:credit_regler",
            "hotel:extras", "hotel:extra_annuler", "fiches:main_courante")),
    Module("stock", "Stock et inventaire",
           "Articles, livraisons, inventaire, écarts, photos des articles, fiches de stock, rapport d'inventaire et "
           "de rentabilité.",
           ("stock:*", "rapports:inventaire", "fiches:stock")),
    Module("rapports", "Rapports d'activité", "Rapports sur le jour, la semaine, le mois ou l'année.",
           ("rapports:rapport",)),
    Module("personnel", "Personnel", "Planning, pointages, congés et échanges, fiches employé, horaires.",
           ("personnel:*",)),
    Module("paie", "Paie", "Fiches de paie, bulletins, acomptes.", ("paie:*",)),
    Module("finances", "Dépenses et bilan",
           "Dépenses, bilan du mois, petites dépenses payées avec l'argent de la caisse.",
           ("finances:*", "caisse:sortie_nouvelle", "caisse:justificatif")),
    Module("pannes", "Pannes et gardien", "Pannes signalées, main courante du gardien.",
           ("postes:maintenance", "postes:securite", "fiches:main_courante_gardien")),
    Module("projets", "Projets et tâches", "Projets internes, tâches de chacun.", ("projets:*",)),
)
PAR_CLE = {m.cle: m for m in MODULES}

TOUJOURS_OUVERT = ("Réservations et vente des chambres : réservations en ligne, séjours et clients, plan des chambres, "
                   "arrivées et départs, paiements et reçus, caisse de la réception (ouvrir, fermer, valider), ménage "
                   "des chambres, fiche recette chambres, comptes clients en ligne, utilisateurs et paramètres.")


def module_de(nom_url):
    """Le module (fermable) auquel appartient une adresse, ou None si elle fait partie du socle toujours ouvert."""
    if not nom_url or ":" not in nom_url:
        return None
    return next((m for m in MODULES if m.contient(nom_url)), None)


def ouverts(request=None):
    """Les clés des modules ouverts (lues une fois par requête)."""
    if request is not None and hasattr(request, "_modules_ouverts"):
        return request._modules_ouverts
    from .models import Etablissement

    valeur = set(Etablissement.get().modules_ouverts or []) & set(PAR_CLE)
    if request is not None:
        request._modules_ouverts = valeur
    return valeur


def est_ouvert(nom_url, request=None):
    module = module_de(nom_url)
    return module is None or module.cle in ouverts(request)


def ouvrir(cles):
    """Enregistre la liste des modules ouverts (les clés inconnues sont ignorées)."""
    from .models import Etablissement

    etab = Etablissement.get()
    etab.modules_ouverts = [m.cle for m in MODULES if m.cle in set(cles)]
    etab.save(update_fields=["modules_ouverts"])
    return etab.modules_ouverts


def ouvrir_tout():
    return ouvrir(PAR_CLE)


class ModulesMiddleware:
    """Une adresse d'un module fermé affiche « pas encore ouvert » au lieu de la page (même tapée à la main)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match is None or not match.namespace:
            return None
        module = module_de(f"{match.namespace}:{match.url_name}")
        if module is None or module.cle in ouverts(request):
            return None
        return render(request, "module_ferme.html", {"module": module}, status=403)

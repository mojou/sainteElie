"""
« Autres pages » : tout ce qui n'est pas dans le menu court, rangé par sujet, en gros boutons.

Le menu de gauche ne garde que le travail de tous les jours ; le reste est ici, à un geste. Chaque lien n'apparaît
qu'à qui a le droit d'ouvrir la page, et seulement si son module est ouvert (Paramètres → Modules).
"""
from django.urls import reverse

from . import modules, permissions


SUITES = {"stock:photos": "?categorie=RESTAURANT"}


def _photographe(u):
    return u.est_direction or u.est_gouvernante


def groupes(user, request=None):
    u = user
    rapports = u.est_direction or u.est_gouvernante
    liste = [
        ("Réservations et chambres", [
            ("vitrine:demandes", "Réservations en ligne", u.voit_reception),
            ("vitrine:commandes_plats", "Plats commandés en ligne", u.voit_reception or u.est_bar),
            ("postes:reception", "Plan des chambres", u.voit_reception),
            ("postes:arrivee", "Un client arrive (sans réservation)", u.voit_reception),
            ("hotel:sejour_nouveau", "Nouvelle réservation", u.voit_reception),
            ("hotel:sejours", "Séjours : arrivées, départs, impayés", u.voit_reception),
            ("hotel:clients", "Clients", u.voit_reception),
            ("vitrine:comptes", "Comptes clients en ligne", u.voit_reception),
            ("hotel:chambres", "Chambres et tarifs", u.voit_reception),
            ("hotel:photos_chambres", "Photos des chambres", _photographe(u)),
            ("stock:carte", "La carte : ajouter, modifier, supprimer un plat", u.voit_stock),
            ("stock:photos", "Photos des plats", u.voit_stock),
            ("hotel:menage", "Ménage des chambres", permissions.menage(u)),
        ]),
        ("Caisse", [
            ("caisse:ma_caisse", "Ma caisse", u.tient_caisse),
            ("caisse:sessions", "Sessions de caisse", permissions.suivi_caisse(u)),
            ("caisse:recherche", "Retrouver un reçu", u.peut_valider_caisse),
            ("caisse:rapports", "Rapports quotidiens de caisse", u.peut_valider_caisse),
            ("caisse:virements", "Virements reçus", u.est_gerant),
        ]),
        ("Fiches à imprimer", [
            ("fiches:index", "Fiches du jour", u.tient_caisse or u.voit_stock),
            ("fiches:hebergement", "Fiche recette chambres", u.voit_reception),
            ("fiches:bar_restaurant", "Fiche bar / restaurant",
             (u.tient_caisse or u.voit_stock) and (u.est_bar or u.est_gerant or u.est_chef_reception or u.voit_stock)),
            ("fiches:chambres_a_faire", "Fiche des chambres à faire", permissions.menage(u)),
        ]),
        ("Boutique, restaurant · bar", [
            ("caisse:ventes", "Point de vente", u.tient_caisse),
            ("hotel:extras", "Extras sur chambre", permissions.extras(u)),
            ("caisse:credits", "Crédits clients", u.tient_caisse),
        ]),
        ("Stock", [
            ("stock:articles", "Articles et mouvements", u.voit_stock),
            ("stock:ecarts", "Écarts d'inventaire", u.voit_stock),
            ("stock:photos", "Photos des articles", u.voit_stock),
            ("rapports:inventaire", "Inventaire et rentabilité", u.voit_stock),
        ]),
        ("Rapports", [("rapports:rapport", "Rapports (jour, semaine, mois, année)", rapports)]),
        ("Personnel", [
            ("personnel:mon_espace", "Mon planning et pointage", bool(u.profil_employe)),
            ("personnel:conges", "Congés et échanges", u.est_encadrement),
            ("personnel:planning", "Planning", u.est_encadrement),
            ("personnel:pointages", "Pointages", u.est_encadrement),
            ("personnel:employes", "Employés", u.est_encadrement),
        ]),
        ("Paie", [
            ("paie:fiches", "Paie", u.est_gerant),
            ("paie:acomptes", "Acomptes", u.est_gerant),
            ("paie:mes_bulletins", "Mes bulletins de paie", bool(u.profil_employe) and not u.est_gerant),
        ]),
        ("Dépenses", [
            ("finances:bilan", "Bilan du mois", u.est_gerant),
            ("finances:depenses", "Dépenses", u.est_gerant),
        ]),
        ("Pannes et gardien", [
            ("postes:maintenance", "Signaler une panne", u.voit_reception),
            ("postes:securite", "Main courante du gardien", u.voit_reception),
        ]),
        ("Projets", [
            ("projets:liste", "Projets internes", u.est_encadrement),
            ("projets:mes_taches", "Mes tâches", True),
        ]),
        ("Site public", [
            ("vitrine:photos", "Photos du site", u.est_direction),
            ("vitrine:site", "Voir le site", True),
        ]),
        ("Administration", [
            ("core:alertes", "Alertes", u.est_encadrement),
            ("postes:tous", "Saisies des départements", u.est_encadrement),
            ("accounts:utilisateurs", "Utilisateurs", u.est_gerant),
            ("core:parametres", "Paramètres", u.est_gerant),
            ("core:modules", "Modules (ouvrir ou fermer)", u.est_gerant),
            ("core:journal", "Journal d'activité", u.est_gerant),
        ]),
        ("Mon compte", [
            ("accounts:mon_compte", "Mon compte et code PIN", True),
            ("accounts:mot_de_passe", "Changer mon mot de passe", True),
        ]),
    ]
    resultat = []
    for titre, liens in liste:
        visibles = [{"url": reverse(nom) + SUITES.get(nom, ""), "texte": texte, "externe": nom == "vitrine:site"}
                    for nom, texte, permis in liens if permis and modules.est_ouvert(nom, request)]
        if visibles:
            resultat.append({"titre": titre, "liens": visibles})
    return resultat

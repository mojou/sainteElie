"""
Efface les données d'essai avant la mise en service, en gardant tout ce qui est réel.

    python manage.py effacer_donnees_test         # montre ce qui sera effacé, sans rien toucher
    python manage.py effacer_donnees_test --oui   # efface vraiment

Gardé : l'établissement, les chambres et leurs prix, le catalogue (bar, boutique, carte du restaurant), les caisses
et leurs réglages, les créneaux du planning, les comptes du personnel et leurs fiches employé, les photos de
chambres et d'articles.

Effacé : clients, séjours, ventes et reçus, caisses tenues, mouvements de stock, dépenses, paie, planning,
pointages, congés, projets, pannes, réservations en ligne, comptes clients, alertes, journal, sessions ouvertes.

Remis à zéro : le stock de chaque article (à recompter le premier jour : Stock → Faire l'inventaire), l'état des
chambres (toutes libres), les salaires fictifs de la démonstration, la numérotation des reçus et des séjours.
Un compte du personnel qui a encore le mot de passe de démonstration reçoit un mot de passe provisoire : la
personne choisit le sien et son code PIN à sa première connexion.

Faites une copie de db.sqlite3 avant : rien de ce qui est effacé ne peut être récupéré ensuite.
"""
import secrets
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction
from django.db.models import FileField

from accounts.models import Role, User
from hotel.models import Chambre
from personnel.models import Employe
from stock.models import Article

from .creer_equipe import MOT_DE_PASSE, PIN
from .seed_demo import SALAIRES_DEMO

# Du plus dépendant au moins dépendant.
# Libellé vide : compté avec la ligne d'à côté (inutile de l'afficher à part).
A_VIDER = [
    ("caisse.ConsigneLecture", ""), ("caisse.Consigne", "consignes de caisse"), ("caisse.Virement", "virements"),
    ("caisse.RemiseCaisse", "remises de caisse"), ("caisse.SortieCaisse", "sorties de caisse"),
    ("caisse.VenteComptoir", "ventes (bar, restaurant, boutique)"), ("caisse.Encaissement", "reçus et encaissements"),
    ("caisse.RapportQuotidien", "rapports de caisse du jour"), ("caisse.SessionCaisse", "caisses tenues"),
    ("hotel.Extra", "extras sur les chambres"), ("hotel.Nuitee", "nuitées"), ("hotel.Nettoyage", "chambres faites"),
    ("vitrine.DemandeReservation", "demandes de réservation en ligne"), ("vitrine.LignePlat", ""),
    ("vitrine.CommandePlats", "commandes de plats en ligne"), ("vitrine.CompteClient", ""),
    ("hotel.Sejour", "séjours"), ("hotel.Client", "clients"),
    ("stock.MouvementStock", "mouvements de stock"), ("finances.Depense", "dépenses"),
    ("paie.Acompte", "acomptes"), ("paie.FichePaie", "fiches de paie"),
    ("personnel.Pointage", "pointages"), ("personnel.DemandeConge", "demandes de congé"),
    ("personnel.DemandeEchange", "échanges de créneau"), ("personnel.Affectation", "créneaux du planning"),
    ("projets.CommentaireTache", ""), ("projets.Tache", "tâches"), ("projets.Projet", "projets"),
    ("postes.Intervention", "pannes signalées"), ("postes.EvenementSecurite", "mains courantes du gardien"),
    ("core.Alerte", "alertes"), ("core.JournalAction", "lignes du journal"), ("core.Compteur", ""),
    ("admin.LogEntry", ""), ("sessions.Session", "sessions de connexion (tout le monde est déconnecté)"),
]
GARDE = [("core.Etablissement", "établissement (nom, adresse)"), ("hotel.Chambre", "chambres et leurs prix"),
         ("caisse.Tiroir", "caisses (réception, cuisine / bar)"), ("personnel.Creneau", "horaires du planning"),
         ("personnel.Employe", "fiches employé"), ("vitrine.PhotoSite", "photos du site")]
# Articles inventés par la démonstration (seed_demo), absents des fiches papier de l'hôtel.
ARTICLES_DEMO = ["Savon d'accueil", "Draps 2 places"]


class Command(BaseCommand):
    help = "Efface les données d'essai (ventes, séjours, clients, stock…) et garde la configuration réelle de l'hôtel."

    def add_arguments(self, parser):
        parser.add_argument("--oui", action="store_true", help="Efface vraiment (sans cette option : simple aperçu).")

    def handle(self, *args, **options):
        clients = User.objects.filter(role=Role.CLIENT).count()
        demo = Article.objects.filter(nom__in=ARTICLES_DEMO, categorie=Article.Categorie.MAGASIN)

        self.stdout.write(self.style.MIGRATE_HEADING("Sera effacé :"))
        for label, libelle in A_VIDER:
            n = apps.get_model(label).objects.count()
            if n and libelle:
                self.stdout.write(f"  {n:>5}  {libelle}")
        if clients:
            self.stdout.write(f"  {clients:>5}  comptes clients du site")
        if demo:
            self.stdout.write(f"  {len(demo):>5}  articles inventés pour la démonstration ({', '.join(ARTICLES_DEMO)})")
        self.stdout.write(self.style.MIGRATE_HEADING("Sera gardé :"))
        for label, libelle in GARDE:
            self.stdout.write(f"  {apps.get_model(label).objects.count():>5}  {libelle}")
        self.stdout.write(f"  {Article.objects.count() - len(demo):>5}  articles du catalogue (stock remis à 0)")
        self.stdout.write(f"  {User.objects.exclude(role=Role.CLIENT).count():>5}  comptes du personnel")

        if not options["oui"]:
            self.stdout.write(self.style.WARNING(
                "\nAperçu seulement : rien n'a été effacé. Faites une copie de db.sqlite3, puis relancez avec --oui."))
            return

        with transaction.atomic():
            self._vider()
            User.objects.filter(role=Role.CLIENT).delete()
            Article.objects.filter(nom__in=ARTICLES_DEMO, categorie=Article.Categorie.MAGASIN).delete()
            Article.objects.update(quantite=0)
            Chambre.objects.update(statut=Chambre.Statut.LIBRE)
            salaires = self._salaires_de_demo()
            codes = self._codes_provisoires()
        try:
            cache.clear()  # envois déjà vus, compteurs de demandes en ligne
        except DatabaseError:
            pass  # table du cache pas encore créée (createcachetable)
        fichiers = self._fichiers_orphelins()
        self._renumeroter()

        self.stdout.write(self.style.SUCCESS("\nDonnées d'essai effacées."))
        self.stdout.write("Stock de chaque article remis à 0 : faites l'inventaire de départ (Stock → Faire l'inventaire).")
        self.stdout.write("Toutes les chambres sont libres. Les reçus et les séjours repartent du numéro 1.")
        if salaires:
            self.stdout.write(f"{salaires} salaire(s) fictif(s) de la démonstration remis à 0 : "
                              "saisissez les vrais dans Personnel → Employés.")
        if fichiers:
            self.stdout.write(f"{fichiers} fichier(s) qui n'appartenaient plus à rien supprimé(s) (reçus PDF, rapports…).")
        if codes:
            self.stdout.write(self.style.WARNING(
                "\nMots de passe provisoires (à remettre à chacun ; à la première connexion, chacun choisit "
                "son mot de passe et son code PIN) :"))
            for user, code in codes:
                self.stdout.write(f"  {user.username:<12} {str(user):<16} {code}")

    def _vider(self):
        """Tout d'un bloc : un reçu annulé « protège » son reçu d'origine, une suppression ligne à ligne bloquerait.
        Les liens sont vérifiés par la base à la fin de la transaction : si une donnée gardée pointait encore vers une
        donnée effacée, rien ne serait effacé."""
        with connection.cursor() as curseur:
            for label, _ in A_VIDER:
                curseur.execute(f"DELETE FROM {connection.ops.quote_name(apps.get_model(label)._meta.db_table)}")

    def _salaires_de_demo(self):
        """Les salaires posés par la démonstration sont fictifs : remis à 0 (un salaire déjà corrigé est gardé)."""
        remis = 0
        for employe in Employe.objects.select_related("user"):
            cle = employe.user.username if employe.user_id else employe.departement
            if employe.salaire_base and employe.salaire_base == SALAIRES_DEMO.get(cle):
                Employe.objects.filter(pk=employe.pk).update(salaire_base=0, date_embauche=None)
                remis += 1
        return remis

    def _codes_provisoires(self):
        """Le mot de passe de démonstration est connu de tous : chaque compte qui l'a encore en reçoit un nouveau."""
        codes = []
        for user in User.objects.exclude(role=Role.CLIENT).order_by("pk"):
            if not (user.check_password(MOT_DE_PASSE) or user.check_pin(PIN)):
                continue
            code = f"Palace{secrets.randbelow(900000) + 100000}"
            user.set_password(code)
            user.pin_hash = ""  # choisi par la personne à sa première connexion
            user.doit_changer_secret = True
            user.last_login = None
            user.echecs_connexion = user.echecs_pin = 0
            user.connexion_bloquee_jusqua = user.pin_bloque_jusqua = None
            user.save()
            codes.append((user, code))
        return codes

    def _fichiers_orphelins(self):
        """Supprime les documents archivés (reçus, rapports, justificatifs…) dont la fiche vient d'être effacée."""
        racine = Path(settings.PRIVATE_MEDIA_ROOT)
        if not racine.exists():
            return 0
        utilises = set()
        for modele in apps.get_models():
            for champ in modele._meta.get_fields():
                if isinstance(champ, FileField):
                    utilises.update(n for n in modele.objects.exclude(**{champ.name: ""})
                                    .values_list(champ.name, flat=True) if n)
        supprimes = 0
        for fichier in racine.rglob("*"):
            if fichier.is_file() and fichier.relative_to(racine).as_posix() not in utilises:
                fichier.unlink()
                supprimes += 1
        return supprimes

    def _renumeroter(self):
        """SQLite : les numéros (séjours, demandes…) repartent après le plus grand qui reste, puis la base est compactée."""
        if connection.vendor != "sqlite":
            return
        with connection.cursor() as curseur:
            curseur.execute("SELECT name FROM sqlite_master WHERE name = 'sqlite_sequence'")
            if curseur.fetchone():
                for modele in apps.get_models():
                    table, pk = modele._meta.db_table, modele._meta.pk.column
                    curseur.execute(f'UPDATE sqlite_sequence SET seq = (SELECT COALESCE(MAX("{pk}"), 0) FROM "{table}") '
                                    "WHERE name = %s", [table])
            if not connection.in_atomic_block:  # VACUUM est impossible dans une transaction (tests)
                curseur.execute("VACUUM")

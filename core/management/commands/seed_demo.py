"""
Données de démonstration : chambres, les 12 comptes du personnel, caisses configurées, quelques séjours.

    python manage.py seed_demo            # crée ce qui manque
    python manage.py seed_demo --sejours  # ajoute aussi des séjours et extras d'exemple

Mot de passe de tous les comptes de démonstration : Demo1234!  ·  code PIN : 1234
À ne pas lancer sur une base de production.
"""
from datetime import time, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from caisse.models import FondCaisse, ParametreCaisse, Tiroir
from core.models import Etablissement
from core.utils import aujourd_hui
from hotel import services as hotel_services
from hotel.models import Chambre, Client, Sejour
from personnel.models import Affectation, Creneau, Employe
from projets.models import Projet, Tache
from stock.models import Article
from stock.services import enregistrer_mouvement

from .creer_equipe import EQUIPE, MOT_DE_PASSE, PIN

# Salaires FICTIFS de démonstration (les vrais se saisissent dans Personnel → Employés).
SALAIRES_DEMO = {"ducart": 350000, "julio": 180000, "germain": 180000, "adelaide": 160000,
                 "carine": 110000, "nina": 110000, "junior": 110000,
                 "aurelle": 90000, "merveille": 90000, "liliane": 90000,
                 "MENAGE": 75000, "SECURITE": 70000}


class Command(BaseCommand):
    help = "Crée des données de démonstration (comptes, chambres, caisse, séjours)."

    def add_arguments(self, parser):
        parser.add_argument("--sejours", action="store_true", help="Ajoute des séjours, extras et stock d'exemple.")

    @transaction.atomic
    def handle(self, *args, **options):
        etab = Etablissement.get()
        if not etab.adresse:
            etab.adresse = "Yaoundé, Cameroun"
            etab.save()

        if not ParametreCaisse.objects.exists():
            ParametreCaisse.objects.create(date_effet=aujourd_hui() - timedelta(days=30), seuil_ecart=1000,
                                           heure_coupure=time(16, 0))
        # Deux caisses : la réception (chambres, boutique) et la cuisine / bar (boissons et plats).
        for nom, poste, fond in [("Réception", Tiroir.Poste.RECEPTION, 20000), ("Cuisine / Bar", Tiroir.Poste.BAR, 10000)]:
            tiroir, cree = Tiroir.objects.get_or_create(nom=nom, defaults={"poste": poste})
            if cree or not tiroir.fonds.exists():
                FondCaisse.objects.create(tiroir=tiroir, montant=fond, date_effet=aujourd_hui() - timedelta(days=30))

        creneaux = {}
        for nom, debut, fin in [("Matin", time(7), time(15)), ("Après-midi", time(15), time(23)), ("Nuit", time(23), time(7))]:
            creneaux[nom], _ = Creneau.objects.get_or_create(nom=nom, defaults={"heure_debut": debut, "heure_fin": fin})

        # Chambres, prix de la direction et catalogue réels (fiches papier).
        call_command("charger_saint_elie", stdout=self.stdout)

        # Les 12 comptes du personnel (noms provisoires), avec des salaires fictifs pour la démonstration.
        call_command("creer_equipe", stdout=self.stdout)
        utilisateurs = {u.username: u for u in User.objects.filter(username__in=[e[0] for e in EQUIPE])}
        # Démonstration seulement : on garde Demo1234! / 1234 pour pouvoir essayer tous les comptes.
        User.objects.filter(pk__in=[u.pk for u in utilisateurs.values()]).update(doit_changer_secret=False)
        for identifiant, user in utilisateurs.items():
            salaire = SALAIRES_DEMO[identifiant]
            Employe.objects.filter(user=user, salaire_base=0).update(
                salaire_base=salaire, date_embauche=aujourd_hui() - timedelta(days=400))

        for departement in ("MENAGE", "SECURITE"):
            Employe.objects.filter(user__isnull=True, departement=departement, salaire_base=0).update(
                salaire_base=SALAIRES_DEMO[departement], date_embauche=aujourd_hui() - timedelta(days=400))

        jour = aujourd_hui()
        # R1, R2, R3 : les trois réceptionnistes se relaient matin, après-midi, nuit.
        planning = [("carine", "Matin"), ("nina", "Après-midi"), ("junior", "Nuit"),
                    ("aurelle", "Matin"), ("merveille", "Après-midi"), ("liliane", "Matin")]
        for decalage in range(7):
            for identifiant, creneau in planning:
                Affectation.objects.get_or_create(employe=utilisateurs[identifiant].employe,
                                                  date=jour + timedelta(days=decalage), creneau=creneaux[creneau])

        if options["sejours"]:
            self._exemples(utilisateurs, jour)

        self.stdout.write(self.style.SUCCESS(
            f"Données de démonstration prêtes. Comptes : {', '.join(u for u, *_ in EQUIPE)} "
            f"(mot de passe {MOT_DE_PASSE}, PIN {PIN})."))

    def _exemples(self, utilisateurs, jour):
        if Sejour.objects.exists():
            self.stdout.write("Des séjours existent déjà : exemples non ajoutés.")
            return
        gerant = utilisateurs["ducart"]
        clients = [Client.objects.create(nom=nom, telephone=tel, entreprise=ent) for nom, tel, ent in [
            ("M. Kamga Joseph", "699112233", ""), ("Mme Abena Claire", "677445566", "MTN Cameroon"),
            ("M. Tchoupo Eric", "655778899", ""), ("Mme Ngono Marie", "690334455", "")]]
        ch = {c.numero: c for c in Chambre.objects.all()}
        sejours = [
            Sejour(client=clients[0], chambre=ch["101"], date_arrivee=jour - timedelta(days=2),
                   date_depart=jour + timedelta(days=1)),
            Sejour(client=clients[1], chambre=ch["106/107"], date_arrivee=jour - timedelta(days=1),
                   date_depart=jour + timedelta(days=3)),
            Sejour(client=clients[2], chambre=ch["104"], date_arrivee=jour, date_depart=jour + timedelta(days=2)),
            Sejour(client=clients[3], chambre=ch["309"], date_arrivee=jour + timedelta(days=3),
                   date_depart=jour + timedelta(days=5)),
        ]
        for s in sejours:
            s.tarif_grille = s.tarif_nuit = s.chambre.tarif_nuit
            s.cree_par = gerant
            s.save()
        for s in sejours[:2]:
            Sejour.objects.filter(pk=s.pk).update(statut=Sejour.Statut.EN_COURS)
            Chambre.objects.filter(pk=s.chambre_id).update(statut=Chambre.Statut.OCCUPEE)
        hotel_services.constater_nuitees()

        # Inventaire de démonstration (la veille) : il donne le S.I des fiches du jour.
        veille = jour - timedelta(days=1)
        for article in Article.objects.filter(categorie__in=Article.VENDUS_AU_COMPTOIR):
            quantite = 24 if article.prix_vente <= 1000 else (10 if article.categorie == "BOUTIQUE" else 6)
            Article.objects.filter(pk=article.pk).update(seuil_alerte=6 if quantite == 24 else 2)
            enregistrer_mouvement(article, gerant, "INVENTAIRE", quantite, "Inventaire de démonstration", journee=veille)
        for nom, quantite in [("Savon d'accueil", 15), ("Draps 2 places", 40)]:
            article = Article.objects.create(nom=nom, categorie=Article.Categorie.MAGASIN, seuil_alerte=10)
            enregistrer_mouvement(article, gerant, "ENTREE", quantite, "Stock initial", journee=veille)

        self._shift_de_demonstration(utilisateurs, ch)

        from postes import services as postes
        postes.signaler_panne(utilisateurs["carine"], "Fuite sous le lavabo", chambre=ch["204"],
                              urgence="URGENTE", hors_service=True)
        postes.signaler_panne(utilisateurs["nina"], "Climatisation en panne", chambre=ch["111"])

        projet = Projet.objects.create(nom="Rénovation des salles de bain du 1er étage", responsable=gerant,
                                       date_debut=jour, echeance=jour + timedelta(days=45), budget=1500000,
                                       statut=Projet.Statut.EN_COURS)
        Tache.objects.create(projet=projet, titre="Devis plombier (3 devis)", assigne_a=utilisateurs["adelaide"],
                             echeance=jour + timedelta(days=7), priorite=Tache.Priorite.HAUTE)
        Tache.objects.create(projet=projet, titre="Planifier les chambres hors service", assigne_a=utilisateurs["julio"],
                             echeance=jour + timedelta(days=14))
        # Espace client : M. Kamga suit son séjour en ligne ; un autre client attend que la réception le relie.
        from vitrine import services as vitrine

        compte = vitrine.inscrire(clients[0].nom, clients[0].telephone, "", MOT_DE_PASSE)
        vitrine.relier(compte, utilisateurs["carine"], clients[0])
        vitrine.inscrire("M. Fotso Alain", "691 23 45 67", "", MOT_DE_PASSE)
        self.stdout.write("Séjours, extras, stock, ventes, projet et comptes clients en ligne d'exemple ajoutés "
                          f"(client : {clients[0].telephone} / {MOT_DE_PASSE}).")

    def _shift_de_demonstration(self, u, ch):
        """Réception : boutique et chambres. Cuisine / bar : boissons et plats. Espèces, Orange Money, MTN MoMo."""
        from caisse import services as caisse

        reception = Tiroir.objects.get(nom="Réception")
        bar = Tiroir.objects.get(nom="Cuisine / Bar")

        def art(nom, code=""):
            return Article.objects.get(nom=nom, code=code)

        OM, MOMO = "ORANGE_MONEY", "MTN_MOMO"
        s101 = Sejour.objects.get(chambre=ch["101"], statut=Sejour.Statut.EN_COURS)
        s106 = Sejour.objects.get(chambre=ch["106/107"], statut=Sejour.Statut.EN_COURS)

        # Réception : Carine le matin (chambre et boutique), relève par Nina.
        aicha, serge = u["carine"], u["nina"]
        matin = caisse.ouvrir_session(aicha, reception, "MATIN", 20000)
        caisse.encaisser(matin, aicha, s101, "REGLEMENT", "ESPECES", 20000)
        caisse.encaisser(matin, aicha, s101, "REGLEMENT", OM, 10000)
        caisse.vendre(matin, aicha, art("Brosse à dent"), 1, "COMPTANT")
        voisin = Client.objects.create(nom="M. Owona (habitué)", telephone="694556677")
        caisse.vendre(matin, aicha, art("Colgate 30g"), 2, "CREDIT", client=voisin)
        # Attendu espèces : 20 000 + 20 000 + 500 = 40 500.
        # … et elle déclare l'Orange Money reçu sur le téléphone.
        caisse.enregistrer_comptage(matin, aicha, 40500, mobile={"ORANGE_MONEY": [10000]})
        caisse.finaliser_remise(matin, aicha, "", entrant=serge)
        apres_midi = caisse.ouvrir_session(serge, reception, "APRES_MIDI", 20000)
        caisse.vendre(apres_midi, serge, art("Cacahuète"), 1, "COMPTANT", mode=MOMO)

        # Cuisine / bar : boissons et plats sur la même caisse, qui reste ouverte pour essayer.
        jean = u["aurelle"]
        bar_matin = caisse.ouvrir_session(jean, bar, "MATIN", 10000)
        caisse.vendre(bar_matin, jean, art("Poulet DG"), 1, "CREDIT", sejour=s101)
        caisse.vendre(bar_matin, jean, art("Petit-déjeuner complet"), 2, "CREDIT", sejour=s106)
        caisse.vendre(bar_matin, jean, art("Ndolé viande de bœuf ou poisson fumé"), 2, "COMPTANT")
        caisse.vendre(bar_matin, jean, art("Carpe braisée / grillée / à la poêle"), 1, "COMPTANT", mode=OM)
        caisse.vendre(bar_matin, jean, art("33 EXPORT", "65CL"), 4, "COMPTANT")
        caisse.vendre(bar_matin, jean, art("CASTEL", "65CL"), 2, "COMPTANT", mode=OM)
        caisse.vendre(bar_matin, jean, art("BLACK LABEL CONSO", "75CL"), 2, "CREDIT", sejour=s106)
        caisse.vendre(bar_matin, jean, art("GUINNESS G", "65CL"), 1, "OFFERT", observation="Geste commercial, client ch. 101")
        caisse.vendre(bar_matin, jean, art("MUTZIG", "65CL"), 3, "COMPTANT", mode=MOMO)
        caisse.creer_sortie(bar_matin, jean, "DEPENSE", 2000, "Achat de glaçons")

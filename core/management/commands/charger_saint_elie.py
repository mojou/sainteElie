"""
Charge les données de référence relevées sur les fiches papier : chambres et catalogue bar / boutique.

    python manage.py charger_saint_elie
    python manage.py charger_saint_elie --desactiver-autres-chambres
    python manage.py charger_saint_elie --tarifs     # réapplique la grille de prix de la direction

Sans risque à relancer : rien n'est supprimé, et un prix déjà corrigé dans l'application n'est pas écrasé.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Etablissement
from hotel.models import Chambre
from stock import catalogue_saint_elie as ref
from stock.models import Article


class Command(BaseCommand):
    help = "Charge les chambres et le catalogue bar / boutique du Saint-Élie Palace (relevés des fiches papier)."

    def add_arguments(self, parser):
        parser.add_argument("--desactiver-autres-chambres", action="store_true",
                            help="Désactive les chambres qui ne figurent pas sur la fiche (elles ne sont pas supprimées).")
        parser.add_argument("--tarifs", action="store_true",
                            help="Applique la grille de prix de la direction même aux chambres qui ont déjà un prix "
                                 "(les séjours déjà enregistrés gardent leur prix).")

    @transaction.atomic
    def handle(self, *args, **options):
        etab = Etablissement.get()
        if etab.nom in ref.ANCIENS_NOMS:
            etab.nom = ref.ETABLISSEMENT
            etab.save(update_fields=["nom"])

        chambres_creees = tarifs_poses = 0
        for numero in ref.CHAMBRES:
            suite = numero in ref.SUITES
            categorie = Chambre.Categorie.SUITE if suite else Chambre.Categorie.SIMPLE
            tarif = ref.TARIFS.get(numero, 0)
            chambre, cree = Chambre.objects.get_or_create(numero=numero, defaults={
                "tarif_nuit": tarif, "categorie": categorie, "description": ref.SUITES.get(numero, "")})
            if not cree:
                changements = {}
                if tarif and chambre.tarif_nuit != tarif and (options["tarifs"] or not chambre.tarif_nuit):
                    changements["tarif_nuit"] = tarif
                if suite and chambre.categorie != Chambre.Categorie.SUITE:
                    changements.update(categorie=categorie, description=ref.SUITES[numero])
                if changements:
                    Chambre.objects.filter(pk=chambre.pk).update(**changements)
                    tarifs_poses += "tarif_nuit" in changements
            chambres_creees += cree
        if options["desactiver_autres_chambres"]:
            Chambre.objects.exclude(numero__in=ref.CHAMBRES).update(active=False)

        articles = [(Article.Categorie.BAR, nom, code, prix) for nom, code, prix in ref.BAR]
        articles += [(Article.Categorie.BOUTIQUE, nom, "", prix) for nom, prix in ref.BOUTIQUE]
        crees = 0
        for ordre, (categorie, nom, code, prix) in enumerate(articles, start=1):
            article, cree = Article.objects.get_or_create(nom=nom, code=code, defaults={
                "categorie": categorie, "prix_vente": prix, "ordre": ordre * 10,
                "unite": "verre" if "CONSO" in nom.upper() else "unité"})
            if not cree:
                changements = {"ordre": ordre * 10}
                if not article.prix_vente:
                    changements["prix_vente"] = prix
                Article.objects.filter(pk=article.pk).update(**changements)
            crees += cree

        plats_crees = 0
        for ordre, (rubrique, nom, prix, description) in enumerate(ref.CARTE, start=1):
            plat, cree = Article.objects.get_or_create(nom=nom, code="", defaults={
                "categorie": Article.Categorie.RESTAURANT, "rubrique": rubrique, "description": description,
                "prix_vente": prix, "ordre": ordre * 10, "unite": "plat", "suivi_stock": False})
            if not cree:
                changements = {"ordre": ordre * 10, "rubrique": plat.rubrique or rubrique,
                               "description": plat.description or description}
                if not plat.prix_vente:
                    changements["prix_vente"] = prix
                Article.objects.filter(pk=plat.pk).update(**changements)
            plats_crees += cree

        sans_tarif = Chambre.objects.filter(active=True, tarif_nuit=0).count()
        self.stdout.write(self.style.SUCCESS(
            f"{etab.nom} : {chambres_creees} chambre(s), {crees} article(s) et {plats_crees} plat(s) créés "
            f"({len(ref.CHAMBRES)} chambres, {len(ref.BAR)} articles de bar, {len(ref.BOUTIQUE)} de boutique sur les fiches)."))
        if tarifs_poses:
            self.stdout.write(f"{tarifs_poses} prix de chambre mis à jour selon la grille de la direction.")
        if sans_tarif:
            self.stdout.write(self.style.WARNING(
                f"{sans_tarif} chambre(s) sans tarif : renseignez-les dans Chambres avant de prendre des réservations."))
        self.stdout.write("Faites ensuite l'inventaire de départ : Stock → Inventaire / livraison groupée.")

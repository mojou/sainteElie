import shutil
import tempfile
from datetime import time, timedelta

from django.test import TestCase, override_settings

from accounts.models import Role, User
from caisse import services as caisse
from caisse.models import Encaissement, FondCaisse, ParametreCaisse, Tiroir
from core.utils import aujourd_hui
from hotel.models import Chambre, Client, Sejour

_DOSSIER = tempfile.mkdtemp(prefix="gestion-tests-")


@override_settings(PRIVATE_MEDIA_ROOT=_DOSSIER)
class BaseTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_DOSSIER, ignore_errors=True)

    def setUp(self):
        self.gerant = self.utilisateur("gerant", Role.ADMIN)
        self.chef = self.utilisateur("chef", Role.CHEF_RECEPTION)
        self.aicha = self.utilisateur("aicha", Role.RECEPTIONNISTE)
        self.serge = self.utilisateur("serge", Role.RECEPTIONNISTE)
        ParametreCaisse.objects.create(date_effet=aujourd_hui() - timedelta(days=10), seuil_ecart=1000,
                                       heure_coupure=time(16, 0), plafond_depense=10000, plafond_remboursement=10000)
        self.tiroir = Tiroir.objects.create(nom="Réception")
        FondCaisse.objects.create(tiroir=self.tiroir, montant=20000, date_effet=aujourd_hui() - timedelta(days=10))
        self.chambre = Chambre.objects.create(numero="101", tarif_nuit=25000)
        self.client_hotel = Client.objects.create(nom="M. Kamga", telephone="699000000")

    @staticmethod
    def utilisateur(nom, role):
        user = User.objects.create_user(nom, password="Demo1234!x", role=role, first_name=nom.capitalize())
        user.set_pin("1234")
        user.save()
        return user

    def sejour(self, arrivee=None, depart=None, chambre=None, statut=Sejour.Statut.EN_COURS, tarif=None):
        arrivee = arrivee or aujourd_hui()
        chambre = chambre or self.chambre
        tarif = tarif or chambre.tarif_nuit
        return Sejour.objects.create(client=self.client_hotel, chambre=chambre, date_arrivee=arrivee,
                                     date_depart=depart or arrivee + timedelta(days=3), tarif_grille=chambre.tarif_nuit,
                                     tarif_nuit=tarif, statut=statut, cree_par=self.gerant)

    def ouvrir(self, user=None, especes=20000):
        return caisse.ouvrir_session(user or self.aicha, self.tiroir, "MATIN", especes)

    def encaisser_especes(self, session, sejour, montant, user=None):
        return caisse.encaisser(session, user or session.receptionniste, sejour, Encaissement.Nature.REGLEMENT,
                                Encaissement.Mode.ESPECES, montant)

    def remettre(self, session, especes, motif="", entrant=None, mobile=None):
        caisse.enregistrer_comptage(session, session.receptionniste, especes, mobile=mobile)
        return caisse.finaliser_remise(session, session.receptionniste, motif, entrant=entrant)

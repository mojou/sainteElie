from django.core.management.base import BaseCommand

from core.taches import executer_taches_periodiques


class Command(BaseCommand):
    help = "Constate les nuitées, produit les rapports quotidiens dus et signale les validations en retard (à planifier toutes les heures)."

    def handle(self, *args, **options):
        executer_taches_periodiques(force=True)
        self.stdout.write(self.style.SUCCESS("Tâches périodiques exécutées."))

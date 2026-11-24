from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
import signal
import threading

from imports_app.jobs import run_job
from imports_app.models import MatchingJob


class Command(BaseCommand):
    help = "Exécuter un import enregistré ; --resume reprend après un arrêt de la machine."

    def add_arguments(self, parser):
        parser.add_argument("job_id", nargs="?")
        parser.add_argument("--resume", action="store_true")

    def handle(self, *args, **options):
        settings.DEBUG = False  # Ne pas conserver les requêtes et leurs JSON en mémoire.
        stop = threading.Event()
        previous = signal.signal(signal.SIGTERM, lambda *args: stop.set())
        try:
            job_id = run_job(options["job_id"], resume=options["resume"], stop=stop)
            if job_id is None:
                self.stdout.write("Aucun import éligible.")
                return
            job = MatchingJob.objects.get(pk=job_id)
            if job.state in {"FAILED", "RETRYABLE", "INTERRUPTED"}:
                raise CommandError(job.error)
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        finally:
            signal.signal(signal.SIGTERM, previous)

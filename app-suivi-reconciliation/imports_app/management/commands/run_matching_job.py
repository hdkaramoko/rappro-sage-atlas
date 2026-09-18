from django.core.management.base import BaseCommand, CommandError

from imports_app.jobs import run_job
from imports_app.models import MatchingJob


class Command(BaseCommand):
    help = "Exécuter un import enregistré ; --resume reprend après un arrêt de la machine."

    def add_arguments(self, parser):
        parser.add_argument("job_id")
        parser.add_argument("--resume", action="store_true")

    def handle(self, *args, **options):
        try:
            run_job(options["job_id"], resume=options["resume"])
            job = MatchingJob.objects.get(pk=options["job_id"])
            if job.state == "FAILED":
                raise CommandError(job.error)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

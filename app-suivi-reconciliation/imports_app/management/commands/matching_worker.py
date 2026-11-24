"""Boucle supervisée Kubernetes ; aucune dépendance Celery/Redis."""

import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection, DatabaseError

from imports_app.jobs import run_job
from imports_app.models import MatchingJob


class Command(BaseCommand):
    help = "Consommer les imports PostgreSQL jusqu'à SIGTERM."

    def add_arguments(self, parser):
        parser.add_argument("--poll-seconds", type=float, default=5)

    def handle(self, *args, **options):
        settings.DEBUG = False
        if connection.vendor != "postgresql":
            raise CommandError("Le worker supervisé exige PostgreSQL ; SQLite conserve le runner local.")
        stop = threading.Event()
        previous = signal.signal(signal.SIGTERM, lambda *args: stop.set())
        try:
            while not stop.is_set():
                try:
                    job_id = run_job(resume=True, stop=stop)
                    if job_id:
                        job = MatchingJob.objects.get(pk=job_id)
                        self.stdout.write(f"Import {job.pk} : {job.state} ; {job.committed_batches} lots ; {job.error}")
                except (OSError, DatabaseError) as exc:
                    self.stderr.write(f"Worker indisponible : {exc}")
                finally:
                    close_old_connections()
                stop.wait(max(1, options["poll_seconds"]))
        finally:
            signal.signal(signal.SIGTERM, previous)

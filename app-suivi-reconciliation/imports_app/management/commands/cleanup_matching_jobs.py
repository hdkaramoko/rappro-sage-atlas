"""Rétention explicite ; dry-run par défaut et aucun PVC supprimé."""

import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction

from imports_app.jobs import job_directory, worker_lock
from imports_app.models import MatchingJob
from reconciliation.models import Campaign


class Command(BaseCommand):
    help = "Lister les artefacts terminaux expirés ; --apply confirme leur suppression."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if settings.MATCHING_RETENTION_DAYS < 1:
            raise CommandError("La rétention doit être d'au moins un jour.")
        cutoff = timezone.now() - timedelta(days=settings.MATCHING_RETENTION_DAYS)
        root = Path(settings.MATCHING_JOB_ROOT).resolve()
        with worker_lock():
            for job in MatchingJob.objects.filter(active=False, finished_at__lt=cutoff,
                                                  state__in=["SUCCESS", "DUPLICATE", "FAILED", "ABANDONED"]):
                directory = job_directory(job).resolve()
                if directory.parent != root or directory.name != str(job.pk):
                    raise CommandError("Répertoire hors de la racine autorisée ; nettoyage refusé.")
                self.stdout.write(f"{job.pk} : {directory}")
                if options["apply"]:
                    with transaction.atomic():
                        for campaign in Campaign.all_objects.filter(job=job, published=False):
                            campaign.inventory.all().delete()
                            campaign.sage_inventory.all().delete()
                            campaign.delete()
                        job.identities.all().delete()
                    if directory.exists():
                        shutil.rmtree(directory)

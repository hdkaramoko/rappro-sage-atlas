from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from reconciliation.review_import import import_bundle


class Command(BaseCommand):
    help = "Importer les propositions JSONL du moteur pour validation métier"

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, **options):
        settings.DEBUG = False  # Import volumineux : aucune accumulation des requêtes SQL.
        try:
            from imports_app.jobs import worker_lock
            from imports_app.progress import ImportProgress
            from imports_app.sqlite_staging import is_file_sqlite, staged_import

            with worker_lock():
                if is_file_sqlite():
                    directory = Path(settings.MATCHING_JOB_ROOT) / f"cli-{uuid4()}"
                    directory.mkdir(parents=True)
                    count = staged_import(
                        options["path"], directory=directory, progress=ImportProgress(directory)
                    )
                else:
                    count = import_bundle(options["path"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"{count} groupes importés pour validation"))

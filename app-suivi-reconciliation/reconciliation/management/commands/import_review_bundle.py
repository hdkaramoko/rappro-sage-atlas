from django.core.management.base import BaseCommand, CommandError

from reconciliation.review_import import import_bundle


class Command(BaseCommand):
    help = "Importer les propositions JSONL du moteur pour validation métier"

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, **options):
        try:
            count = import_bundle(options["path"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"{count} groupes importés pour validation"))

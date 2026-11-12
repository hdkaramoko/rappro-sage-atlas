"""Exploitation explicite de la maintenance SQLite, sans préparation comptable."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from reconciliation.sqlite_statistics import maintain_statistics


class Command(BaseCommand):
    """Vérifie les statistiques et propose --force pour un diagnostic volontaire."""

    help = "Maintenir les statistiques SQLite si absentes ; --force pour une actualisation explicite."

    def add_arguments(self, parser):
        """Déclare le forçage et l'alias Django ; pas de chemin arbitraire ni de commande destructive."""
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--database", default="default", choices=tuple(connections))

    def handle(self, *args, **options):
        """Affiche le résultat non sensible ; échoue proprement si report/erreur, sans recalcul métier."""
        result = maintain_statistics(using=options["database"], force=options["force"], automatic=False)
        self.stdout.write(f"Statistiques : {result['status']} ({result['reason']}), {result['seconds']:.3f} s")
        if result["status"] in ("failed", "deferred"):
            raise CommandError("Maintenance indisponible ; aucune préparation déclenchée.")

"""Activation explicite de WAL sans interrompre un import déjà démarré."""

import sqlite3
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from imports_app.jobs import worker_lock
from imports_app.sqlite_staging import enable_wal, is_file_sqlite, open_database, revision


class Command(BaseCommand):
    """Prépare SQLite une fois les migrations appliquées et l'ancien worker arrêté."""

    help = "Activer WAL pour les imports SQLite (refus si un worker est encore actif)"

    def add_arguments(self, parser):
        """Autorise une mise à niveau sauvegardée, sous le même verrou que les imports."""
        parser.add_argument("--migrate", action="store_true")

    def handle(self, *args, **options):
        """Vérifie le verrou applicatif et la migration avant de changer le journal SQLite."""
        if not is_file_sqlite():
            raise CommandError("Cette commande nécessite une base SQLite sur disque")
        try:
            with worker_lock():
                db = open_database(connection.settings_dict["NAME"])
                try:
                    if options["migrate"]:
                        folder = Path(settings.BASE_DIR) / "var" / "backups"
                        folder.mkdir(parents=True, exist_ok=True)
                        backup = folder / f"before-staged-import-{uuid4()}.sqlite3"
                        target = sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                        self.stdout.write(f"Sauvegarde : {backup}")
                        call_command("migrate", stdout=self.stdout)
                    revision(db)
                    enable_wal(db)
                finally:
                    db.close()
        except Exception as exc:
            raise CommandError(
                f"Préparation impossible (import actif ou migration manquante) : {exc}"
            ) from exc
        self.stdout.write(
            self.style.SUCCESS("SQLite WAL activé ; délai d’attente configuré à 30 secondes.")
        )

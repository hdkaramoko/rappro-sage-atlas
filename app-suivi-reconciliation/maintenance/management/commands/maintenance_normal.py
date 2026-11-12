"""Retour de secours audité au mode normal depuis le serveur."""

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from maintenance.models import MaintenanceState
from maintenance.services import current_state, transition


class Command(BaseCommand):
    """Réserve la récupération à l'exploitation disposant d'un accès au processus Django."""

    help = "Remet la maintenance à NORMAL avec un motif obligatoire et un audit."

    def add_arguments(self, parser):
        """Ajoute le motif obligatoire, limité au contenu non sensible de l'incident."""
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        """Applique le retour NORMAL ; échoue lisiblement sans contourner une base indisponible."""
        reason = options["reason"].strip()
        if not reason or len(reason) > 500:
            raise CommandError("Fournissez un motif non vide de 500 caractères maximum.")
        try:
            configuration = current_state()
            transition(state=MaintenanceState.State.NORMAL, message="", planned_at=None,
                       version=configuration.version, recovery_reason=reason)
        except (DatabaseError, ValidationError) as exc:
            raise CommandError("Retour à Normal impossible ; vérifiez la base et réessayez.") from exc
        self.stdout.write(self.style.SUCCESS("Maintenance remise à NORMAL ; récupération auditée."))

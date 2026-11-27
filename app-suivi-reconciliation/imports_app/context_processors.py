"""Annonce du gel temporaire des écritures, visible aussi aux utilisateurs métier."""

from django.db import connection
from .models import MatchingJob
from .resumable import PUBLICATION_PHASE


def import_status(request):
    if connection.vendor != "postgresql" or not request.user.is_authenticated:
        return {"import_publication_in_progress": False}
    return {"import_publication_in_progress": MatchingJob.objects.filter(
        active=True, state="IMPORTING", phase=PUBLICATION_PHASE).exists()}

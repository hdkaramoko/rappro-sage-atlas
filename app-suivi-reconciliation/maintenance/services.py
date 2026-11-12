"""Lecture fraîche et transitions atomiques du mode maintenance."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import MaintenanceEvent, MaintenanceState


def can_manage(user):
    """Retourne l'autorisation de pilotage du compte actif, distincte de l'accès métier global."""
    return bool(user.is_authenticated and user.is_active and user.is_staff
                and user.has_perm("maintenance.change_maintenancestate"))


def current_state():
    """Lit le singleton sans écriture ni cache ; une ligne absente vaut NORMAL.

    Les erreurs de base sont propagées au middleware, qui sert un 503 explicite.
    """
    return MaintenanceState.objects.filter(pk=1).first() or MaintenanceState(pk=1)


def transition(*, state, message, planned_at, version, actor=None, recovery_reason=None):
    """Enregistre état et audit atomiquement, avec contrôle de version et d'autorisation.

    Les appels HTTP fournissent un acteur autorisé. L'exploitation locale fournit
    exclusivement un motif de récupération pour revenir à NORMAL. Une collision
    de version lève ValidationError sans écraser le changement concurrent.
    """
    if recovery_reason is None:
        if actor is None or not can_manage(actor):
            raise PermissionDenied
    elif actor is not None or state != MaintenanceState.State.NORMAL or not recovery_reason.strip():
        raise ValidationError("La récupération exige un motif et le retour à Normal.")
    if state not in MaintenanceState.State.values or len(message) > 2000:
        raise ValidationError("État ou message invalide.")
    with transaction.atomic():
        previous, _ = MaintenanceState.objects.get_or_create(pk=1)
        if version != previous.version:
            raise ValidationError("L’état a changé entre-temps. Rechargez la page avant de réessayer.")
        changed = MaintenanceState.objects.filter(pk=1, version=version).update(
            state=state, message=message, planned_at=planned_at, updated_at=timezone.now(),
            actor=actor, version=version + 1)
        if changed != 1:
            raise ValidationError("L’état a changé entre-temps. Rechargez la page.")
        MaintenanceEvent.objects.create(previous_state=previous.state, next_state=state, actor=actor,
            actor_label=actor.get_username() if actor else "Exploitation serveur",
            message=message, planned_at=planned_at, reason=recovery_reason or "")

"""Index techniques de consultation, sans recalcul des règles ou des décisions."""

from contextlib import contextmanager
from contextvars import ContextVar
from django.db import transaction
from django.db.models import Exists, OuterRef

indexing_suspended = ContextVar("control_indexing_suspended", default=False)


@contextmanager
def suspend_indexing():
    """Suspend les synchronisations unitaires pendant un import, puis restaure le contexte.

    Le décorateur encadre la transaction d'import existante ; la reconstruction
    explicite en fin d'import indexe la photographie finale une seule fois.
    """
    token = indexing_suspended.set(True)
    try:
        yield
    finally:
        indexing_suspended.reset(token)


def context_values(decision):
    """Retourne les clés et l'alerte existantes d'un snapshot, sans interprétation métier nouvelle."""
    keys = decision.get("multiple_context", {}).get("controls", {})
    keys = {key for key in keys if isinstance(key, str) and len(key) == 64}
    return keys, not (decision.get("state") == "VALIDATED" and decision.get("current") is True)


def refresh_pending(campaign_id, project_code, keys):
    """Actualise les seuls indicateurs de contrôles touchés via une relation indexée.

    Pas de lecture JSON ni de recalcul financier. Les clés sans contrôle restent
    dans l'index de contexte pour la navigation mais ne créent aucun contrôle fictif.
    """
    from .models import CampaignGlobalControl, ReviewControlContext
    if not keys:
        return
    pending = ReviewControlContext.objects.filter(campaign_id=campaign_id, project_code=project_code,
        key=OuterRef("key"), pending=True)
    CampaignGlobalControl.objects.filter(campaign_id=campaign_id, project_code=project_code,
        key__in=keys).update(has_pending=Exists(pending))


def sync_review(review):
    """Synchronise les anciens/nouveaux contextes de la revue exacte après son écriture.

    L'appelant garantit la transaction et les droits métier. Aucune décision n'est
    changée : l'état/péremption vient du snapshot existant. Les importations bulk
    utilisent rebuild_campaign au lieu d'un travail par ligne.
    """
    from .models import ReviewControlContext
    previous = set(review.control_contexts.values_list("key", flat=True))
    keys, pending = context_values(review.decision)
    project = review.project.code
    review.control_contexts.exclude(key__in=keys).delete()
    review.control_contexts.update(pending=pending, project_code=project, campaign_id=review.campaign_id)
    ReviewControlContext.objects.bulk_create([ReviewControlContext(review=review, campaign_id=review.campaign_id,
        project_code=project, key=key, pending=pending) for key in keys - previous], batch_size=500)
    refresh_pending(review.campaign_id, project, previous | keys)


@transaction.atomic
def rebuild_campaign(campaign, *, progress=None):
    """Extrait les contextes une fois en fin d'import et matérialise les alertes.

    Parcourt les snapshots par lots ; aucun moteur ni choix utilisateur n'est rejoué.
    Les données restent dans la transaction d'import/publication. Ne s'exécute
    jamais lors de l'affichage d'une page. Retourne le nombre de relations créées.
    """
    from .models import CampaignGlobalControl, ReviewControlContext
    campaign.review_control_contexts.all().delete()
    batch, count = [], 0
    rows = campaign.reviews.values_list("pk", "project__code", "decision").iterator(chunk_size=500)
    for review_id, project, decision in rows:
        keys, pending = context_values(decision)
        for key in keys:
            batch.append(ReviewControlContext(review_id=review_id, campaign=campaign,
                project_code=project, key=key, pending=pending))
            count += 1
            if len(batch) >= 500:
                ReviewControlContext.objects.bulk_create(batch, batch_size=500)
                batch.clear()
    if batch:
        ReviewControlContext.objects.bulk_create(batch, batch_size=500)
    pending = ReviewControlContext.objects.filter(campaign=campaign, project_code=OuterRef("project_code"),
        key=OuterRef("key"), pending=True)
    controls = CampaignGlobalControl.objects.filter(campaign=campaign)
    controls.filter(has_pending=True).update(has_pending=False)
    pending_keys = ReviewControlContext.objects.filter(campaign=campaign, pending=True).values("key")
    controls.filter(key__in=pending_keys).update(has_pending=Exists(pending))
    if progress:
        progress("Index de consultation préparés", count)
    return count

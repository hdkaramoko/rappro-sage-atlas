"""Import et présentation du contexte BAP, sans correction ou règle métier."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError

from reconciliation_contract.bap_history import bap_key, validate_record
from .models import CampaignBapHistory


def insert_batch(campaign, rows, targets):
    """Valide et insère un lot de contextes appartenant aux couples BAP/projet JDD.

    Les champs ne modifient aucune source Atlas. Une incohérence ou un doublon
    SQL lève ValidationError et annule la transaction d'import englobante.
    """
    try:
        records = []
        for row in rows:
            validate_record(row)
            if (row["project_code"], row["bap_sage_number"]) not in targets:
                raise ValueError("Historique BAP hors du périmètre Atlas")
            records.append(CampaignBapHistory(campaign=campaign, **row))
        CampaignBapHistory.objects.bulk_create(records, batch_size=500)
    except (ValueError, IntegrityError) as exc:
        raise ValidationError("Historique BAP invalide ou répété") from exc


def attach_history(lines):
    """Joint le contexte aux seules lignes de la page en une requête bornée.

    Exige des lignes déjà autorisées ; campagne/projet/BAP forment la clé.
    Retourne None et ajoute bap_history sans toucher aux décisions. Une ancienne
    campagne sans capacité n'entraîne aucune requête supplémentaire.
    """
    keys = {(line.campaign_id, line.transaction.project.code, bap_key(line.transaction.sage_bap_number))
            for line in lines if line.campaign_id and line.campaign.metadata.get("bap_history_policy")}
    histories = {}
    if keys:
        from django.db.models import Q
        condition = Q(pk__in=[])
        for campaign, project, bap in keys:
            if bap:
                condition |= Q(campaign_id=campaign, project_code=project, bap_sage_number=bap)
        histories = {(row.campaign_id, row.project_code, row.bap_sage_number): row for row in CampaignBapHistory.objects.filter(condition)}
    for line in lines:
        line.bap_history = histories.get((line.campaign_id, line.transaction.project.code, bap_key(line.transaction.sage_bap_number)))


def snapshot_history(snapshot):
    """Retourne l'historique de la photographie consultée, jamais celui d'une autre campagne.

    snapshot doit déjà être autorisé par la vue ; une absence retourne None.
    Lecture d'une seule clé indexée, sans changement de sources ni de décision.
    """
    if not snapshot.campaign.metadata.get("bap_history_policy"):
        return None
    return CampaignBapHistory.objects.filter(campaign=snapshot.campaign, project_code=snapshot.source["project_code"],
        bap_sage_number=bap_key(snapshot.source.get("sage_bap_number", ""))).first()

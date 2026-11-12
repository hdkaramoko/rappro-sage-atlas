"""Lecture des bases exactes du matching, distinctes du cadrage et des sources affichées."""

from django.core.exceptions import ValidationError
from reconciliation_contract import money
from reconciliation_contract.matching_policy import RESIDUAL_RULES, precise_source, rule_tolerance


def source_project_amount(line):
    """Retourne le montant projet Decimal servant à la seule règle résiduelle courante.

    Pour une politique v3 déclarée, lit la preuve exacte photographiée de cette
    ligne/campagne. Les autres règles et anciens fichiers gardent leur montant
    historique. Cache local à l'objet ; aucun écrit. ValidationError si la
    politique ou la preuve exacte est absente/invalide, sans repli arrondi.
    """
    declared = line.campaign.metadata.get("matching_tolerances") if line.campaign_id else None
    if line.group.rule not in RESIDUAL_RULES or not declared:
        return line.transaction.total_project_charges
    try:
        rule_tolerance(line.group.rule, declared)
        if not hasattr(line, "_exact_matching_amount"):
            record = line.campaign_reviews.filter(campaign_id=line.campaign_id).values(
                "source", "group__data__matching_source_amounts").first()
            if record is None:
                raise ValueError("Photographie de matching absente")
            source = precise_source(record["source"], record["group__data__matching_source_amounts"])
            line._exact_matching_amount = money(source["total_project_charges"])
        return line._exact_matching_amount
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

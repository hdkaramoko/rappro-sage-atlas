"""Lecture du diagnostic moteur, sans participation au service de décision."""

from django.core.exceptions import ValidationError
from reconciliation_contract.piece_coherence import atlas_entry, validate_check


def validate_proposal_check(payload):
    data = payload.get("piece_coherence")
    if data is None:
        return None
    try:
        validate_check(data)
        if len(payload["atlas"]) != 1 or any(atlas_entry(raw) not in data["atlas"] for raw in payload["atlas"]):
            raise ValueError("Ligne Atlas absente ou contradictoire avec le diagnostic")
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise ValidationError(f"Contrôle de cohérence SAGE invalide : {exc}") from exc
    return data

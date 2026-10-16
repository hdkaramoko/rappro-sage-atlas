"""Décision conservatrice sur le résultat final, sans modifier le matching."""
from reconciliation import config
from reconciliation.matching.models import RULES
from math import isfinite


def validate_config():
    options = config.AUTO_VALIDATION
    if not isinstance(options, dict) or type(options.get("enabled")) is not bool or not isinstance(options.get("statuses"), (list, tuple)):
        raise ValueError("AUTO_VALIDATION : enabled booléen et statuses liste requis")
    if any(not isinstance(status, str) for status in options["statuses"]):
        raise ValueError("AUTO_VALIDATION : chaque statut doit être une chaîne")
    unknown = set(options["statuses"]) - set(RULES) - {"MATCHED"}
    if unknown:
        raise ValueError(f"Statuts AUTO_VALIDATION inconnus : {sorted(unknown)}")
    return options


def proposal_metadata(record, options):
    if not options["enabled"] or not ({record["match_status"], record["match_rule"]} & set(options["statuses"])):
        return None
    # Les agrégations et règles expérimentales restent manuelles.
    if record["match_status"] != "MATCHED" or record["match_rule"] not in ("MATCH_EXACT", "MATCH_CONFIRMED_ATLAS") or record["requires_review"] or record["atlas_row_count"] != 1:
        return None
    if record["match_rule"] == "MATCH_EXACT" and (record["candidate_count"] != 1 or record["sage_row_count"] != 1 or record["cardinality_match"] != True):
        return None
    difference = record.get("amount_difference")
    if difference is None or not isfinite(difference) or abs(difference) > 0.01:
        return None
    return {"source": "AUTO", "rule": record["match_rule"], "state": "VALIDATED"}

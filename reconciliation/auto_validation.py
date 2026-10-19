"""Décision conservatrice sur le résultat final, sans modifier le matching."""
from reconciliation import config
from reconciliation.matching.models import RULES
from math import isfinite
from reconciliation_contract.auto_validation import AUTO_VALIDATION_RULES


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
    if record["match_status"] != "MATCHED" or record["match_rule"] not in AUTO_VALIDATION_RULES or record["atlas_row_count"] != 1:
        return None
    if record["match_rule"] == "MATCH_CONFIRMED_ATLAS":
        if record["requires_review"] or record.get("reason") != "ATLAS_EVIDENCE_PRESENT":
            return None
    # requires_review signale aussi une règle expérimentale, même avec des
    # preuves complètes. L'autorisation explicite remplace cette seule réserve,
    # jamais une anomalie : le motif final doit confirmer la preuve complète.
    elif (record["candidate_count"] != 1 or record.get("reason") != "UNIQUE_CANDIDATE"
          or not record.get("sage_document_number") or not record.get("sage_accounting_date")):
        return None
    if record["match_rule"] == "MATCH_EXACT" and (record["requires_review"] or record["sage_row_count"] != 1 or record["cardinality_match"] != True):
        return None
    difference = record.get("amount_difference")
    if difference is None or not isfinite(difference) or abs(difference) > 0.01:
        return None
    return {"source": "AUTO", "rule": record["match_rule"], "state": "VALIDATED"}

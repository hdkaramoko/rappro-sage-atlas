"""Décision conservatrice sur le résultat final, sans modifier le matching."""
from reconciliation import config
from reconciliation.matching.models import RULES
from decimal import Decimal
from reconciliation_contract.auto_validation import AUTO_VALIDATION_RULES
from reconciliation_contract import money
from reconciliation_contract.matching_policy import MATCHING_TOLERANCES, rule_tolerance


def validate_config():
    """Retourne la configuration AUTO active ou lève ValueError si invalide.

    Lit config.AUTO_VALIDATION sans mutation ; vérifie types et codes connus.
    Aucun accès fichier/base ni effet de bord.
    """
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
    """Retourne l'autorisation AUTO d'un résultat moteur, ou None si non admissible.

    `record` décrit la proposition finale, `options` l'activation et les règles
    autorisées. Confirmé utilise la charge Sage Atlas finie (`sage_amount`) :
    l'écart aux charges projet n'est pas un veto. Les autres catégories gardent
    leur écart projet/Sage de 0,01 EUR et leurs règles d'unicité historiques.
    La preuve externe et les signes sont revérifiés par Django avant décision.
    Exact autorise aussi les cardinalités égales multilignes ; l'exporteur v3
    doit ensuite prouver une bijection individuelle avant de publier l'autorisation.
    Pour Fuzzy, Sans libellé, BAP et Individuel, l'exporteur exige une écriture v3 complète et l'unicité
    bilatérale sur les sources entières avant publication.
    Aucun montant source ni résultat moteur n'est modifié ; aucun effet de bord.
    L'écart est recalculé en Decimal depuis les deux montants, sans soustraire
    leurs représentations flottantes ; seuls BAP/Individuel admettent 0,05 EUR.
    Les autres règles restent à 0,01 EUR, sans effet sur le cadrage.
    """
    if not options["enabled"] or not ({record["match_status"], record["match_rule"]} & set(options["statuses"])):
        return None
    grouped_exact = record["match_rule"] == "MATCH_EXACT" and record["atlas_row_count"] > 1
    if record["match_status"] != "MATCHED" or record["match_rule"] not in AUTO_VALIDATION_RULES or (record["atlas_row_count"] != 1 and not grouped_exact):
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
    if record["match_rule"] == "MATCH_EXACT" and (record["requires_review"] or record["sage_row_count"] != record["atlas_row_count"] or record["cardinality_match"] != True):
        return None
    atlas_amount, sage_amount = money(record.get("atlas_amount")), money(record.get("sage_amount"))
    if record["match_rule"] == "MATCH_CONFIRMED_ATLAS":
        difference = Decimal(0) if sage_amount is not None else None
    elif "atlas_amount" in record or "sage_amount" in record:
        difference = atlas_amount - sage_amount if atlas_amount is not None and sage_amount is not None else None
    else:
        difference = money(record.get("amount_difference"))
    if difference is None or abs(difference) > rule_tolerance(record["match_rule"], MATCHING_TOLERANCES):
        return None
    return {"source": "AUTO", "rule": record["match_rule"], "state": "VALIDATED"}

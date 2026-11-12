"""Ordre public et seuils du matching, sans modifier les contrôles comptables."""

from decimal import Decimal

from . import money

RULE_ORDER = ("MATCH_CONFIRMED_ATLAS", "MATCH_EXACT", "MATCH_AMOUNT", "MATCH_FUZZY_HIGH",
              "MATCH_FUZZY_REVIEW", "MATCH_WITHOUT_LABEL", "MATCH_BAP", "MATCH_INDIVIDUAL",
              "AMBIGUOUS", "UNMATCHED")
RESIDUAL_RULES = frozenset({"MATCH_BAP", "MATCH_INDIVIDUAL"})
MATCHING_TOLERANCES = {rule: "0.05" for rule in ("MATCH_BAP", "MATCH_INDIVIDUAL")}


def rule_tolerance(rule, declared=None):
    """Retourne le seuil Decimal d'une règle et d'une politique déclarée.

    Sans politique (ancien JSONL), retourne 0,01 EUR. Seuls BAP/Individuel
    peuvent déclarer 0,05 ; les autres règles restent à 0,01. Aucun effet externe.
    ValueError si la politique n'est pas un dictionnaire strictement reconnu.
    """
    if declared is None:
        return Decimal("0.01")
    if not isinstance(declared, dict) or any(k not in RESIDUAL_RULES or v != "0.05" for k, v in declared.items()):
        raise ValueError("Tolérances de matching non reconnues")
    return Decimal(declared.get(rule, "0.01"))


def source_amounts(payload):
    """Vérifie et retourne les montants Atlas exacts ajoutés à une proposition.

    Le dictionnaire par identifiant doit reproduire exactement les charges projet
    des sources JSONL, avant arrondi des modèles d'affichage. Retourne None pour
    un ancien fichier. ValueError si absent/incohérent/non fini ; aucun écrit.
    """
    values = payload.get("matching_source_amounts")
    if values is None:
        return None
    expected = {str(row["Id"]): money(row.get("Total charges projet (€)")) for row in payload["atlas"]}
    if not isinstance(values, dict) or set(values) != set(expected):
        raise ValueError("Preuves monétaires Atlas incomplètes")
    for identifier, amount in values.items():
        if amount is not None and (not isinstance(amount, str) or money(amount) is None):
            raise ValueError("Preuve monétaire Atlas invalide")
        if money(amount) != expected[identifier]:
            raise ValueError("Preuve monétaire contradictoire avec la source Atlas")
    return values


def precise_source(source, amounts):
    """Retourne une copie canonique portant le montant projet exact attesté.

    `amounts` est la preuve par identifiant vérifiée à l'import/export. Une clé
    absente lève ValueError ; None reste une absence, jamais zéro. Aucun écrit.
    """
    identifier = str(source.get("source_id"))
    if not isinstance(amounts, dict) or identifier not in amounts:
        raise ValueError("Montant Atlas exact absent des preuves de matching")
    return {**source, "total_project_charges": amounts[identifier]}

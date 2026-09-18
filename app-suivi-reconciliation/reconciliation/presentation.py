"""Présentation des champs réellement importés, sans nouvelle règle de matching."""

from decimal import Decimal

from .review import is_current

RULE_LABELS = {
    "MATCH_EXACT": "Correspondance exacte",
    "MATCH_AMOUNT": "Concordance des montants",
    "MATCH_CONFIRMED_ATLAS": "Confirmé dans Atlas",
    "MATCH_WITHOUT_LABEL": "Sans contrôle du libellé",
    "MATCH_FUZZY_HIGH": "Libellé proche",
    "MATCH_FUZZY_REVIEW": "Libellé à vérifier",
    "AMBIGUOUS": "Plusieurs candidats",
    "UNMATCHED": "Sans correspondance",
}


def decorate(line):
    line.stale = bool(line.version and not is_current(line))
    line.decision_label = (
        "À réexaminer"
        if line.stale
        else {"VALIDATED": "Validé", "REJECTED": "Refusé"}.get(line.state, "—")
    )
    line.decision_tone = (
        "warning"
        if line.stale
        else {"VALIDATED": "success", "REJECTED": "danger"}.get(line.state, "neutral")
    )
    return line


def money(value):
    if value is None or value == "" or str(value) == "None":
        return "—"
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return "—"
        return f"{number:,.2f}".replace(",", "\u202f").replace(".", ",") + " €"
    except (ValueError, ArithmeticError):
        return "—"


def history_rows(events):
    labels = {"status": "Statut BAP", "amount": "Montant SAGE", "document": "Pièce", "date": "Date"}

    def display(name, entry):
        if entry.get("mode", "KEEP") == "KEEP":
            return "Conserver Atlas"
        if entry.get("mode") == "CLEAR":
            return "Effacer"
        return money(entry.get("value")) if name == "amount" else entry.get("value", "—")

    for event in events:
        snapshot = event.snapshot
        before = snapshot.get("before", {}).get("values", {})
        after = snapshot.get("values", {})
        event.changes = [
            {
                "label": label,
                "before": display(name, before.get(name, {})),
                "after": display(name, after.get(name, {})),
            }
            for name, label in labels.items()
            if display(name, before.get(name, {})) != display(name, after.get(name, {}))
        ]
        event.decision = {
            "VALIDATED": "Validé",
            "REJECTED": "Refusé",
            "DRAFT": "Modifications enregistrées",
        }.get(snapshot.get("state"), "—")
        yield event

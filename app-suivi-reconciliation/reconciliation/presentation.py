"""Présentation des champs réellement importés, sans nouvelle règle de matching."""

from decimal import Decimal

from .review import is_current
from reconciliation_contract.matching_policy import RULE_ORDER

RULE_LABELS = {
    "MATCH_EXACT": "Correspondance exacte",
    "MATCH_AMOUNT": "Concordance des montants",
    "MATCH_CONFIRMED_ATLAS": "Confirmé dans Atlas",
    "MATCH_WITHOUT_LABEL": "Sans contrôle du libellé",
    "MATCH_BAP": "N° BAP uniquement",
    "MATCH_INDIVIDUAL": "Correspondance individuelle",
    "MATCH_FUZZY_HIGH": "Libellé proche",
    "MATCH_FUZZY_REVIEW": "Libellé à vérifier",
    "AMBIGUOUS": "Plusieurs candidats",
    "UNMATCHED": "Sans correspondance",
}


def rule_choices(available):
    """Retourne les règles présentes dans l'ordre réel du moteur, puis les états transverses.

    `available` contient les codes de la campagne visible. Les anciens codes
    inconnus restent consultables ; Sans correspondance reste proposé comme
    auparavant. Toutes est géré en premier par multifilter. Aucune mutation.
    """
    available = set(available)
    present = available - {"UNMATCHED", "AMBIGUOUS", ""}
    ordered = [code for code in RULE_ORDER if code in present]
    ordered.extend(sorted(present - set(RULE_ORDER)))
    if "AMBIGUOUS" in available:
        ordered.append("AMBIGUOUS")
    return [(code, RULE_LABELS.get(code, code)) for code in ordered] + [("__NO_MATCH__", "Sans correspondance")]


def inventory_baps(rows, campaign):
    """Retourne les BAP Atlas disponibles pour une page d'inventaires déjà autorisés.

    Lit le nouveau champ source, sinon la photographie Atlas des anciennes
    revues de la même campagne. Ne déduit jamais un BAP depuis Sage ; au plus
    une requête bornée à la page, sans écriture ni recours à une campagne courante.
    """
    from .models import CampaignReview
    missing = [row.business_key for row in rows if "display_bap" not in row.data]
    prior = dict(CampaignReview.objects.filter(campaign=campaign, line__transaction__business_key__in=missing)
        .values_list("line__transaction__business_key", "source__sage_bap_number")) if missing else {}
    return {row.pk: row.data.get("display_bap", prior.get(row.business_key, "")) for row in rows}


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

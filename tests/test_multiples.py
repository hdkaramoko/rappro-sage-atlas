"""Calculs de multiples sur montants individuels et preuves stables fictives."""

import pandas as pd

from reconciliation.matching import match_reconciliations as match
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage
from reconciliation.multiples import build_controls
from reconciliation_contract import compare, entry_from_sage, label


def match_reconciliations(atlas, sage):
    """Prépare les colonnes canoniques comme la CLI avant les règles métier."""
    return match(transform_atlas(atlas), transform_sage(sage))


def sage_row(**changes):
    """Fournit une véritable écriture analytique avec identité à zéros initiaux."""
    return {
        "Projet": "P",
        "Numéro pièce": "D",
        "Date comptable": "2026-01-01",
        "Journal": "ACH",
        "N° de ligne comptable": "001",
        "N° de ligne Analytique": "01",
        "Charges (Dépenses)": "100",
        "Devise": "EUR",
        "Code Tiers - Tiers doc Orig": "001",
        "Libellé pièce": "Café mission",
        "Référence": "B",
        **changes,
    }


def atlas_row(identifier="A", **changes):
    """Construit une charge individuelle déjà comptabilisée, distincte d'un total moteur."""
    return {
        "Id": identifier,
        "Code projet": "P",
        "Année": 2026,
        "Statut BAP": "Comptabilisé",
        "Total charges projet (€)": 70,
        "Total charges SAGE (€)": 70,
        "N° pièce SAGE": "D",
        "Date comptable": "2026-01-01",
        "Libellé ATLAS": "Café mission",
        "Code tiers SAGE": "001",
        "N° BAP (SAGE)": "B",
        "Devise": "EUR",
        **changes,
    }


def test_signed_amounts_and_incomplete_sums():
    """Un avoir homogène se compare en absolu ; un mélange de signes reste inconnu."""
    assert compare(["70", "50"], ["60", "40"])["status"] == "EXCESS"
    assert compare(["0"], ["0"])["status"] == "BALANCED"
    assert compare(["-120"], ["-100"])["status"] == "EXCESS"
    assert compare(["120", "-20"], ["100"])["status"] == "UNKNOWN"
    assert compare(["70", None], ["100"])["atlas_total"] is None
    assert compare(["100.01"], ["100"])["status"] == "BALANCED"


def test_entries_are_not_group_totals_and_are_stable():
    """L'identité ne dépend ni de l'ordre des clés ni du montant, qui reste une preuve."""
    row = sage_row()
    assert (
        entry_from_sage(row)["ref"]
        == entry_from_sage(dict(reversed(list(row.items()))))["ref"]
    )
    assert (
        entry_from_sage(row)["ref"]
        != entry_from_sage(sage_row(**{"N° de ligne Analytique": "02"}))["ref"]
    )
    assert entry_from_sage(row)["line"] == "001"
    assert label(" CAFÉ\u00a0  Mission ") == label("cafe\u0301 mission")
    assert label(None) == ""


def test_standard_multi_entries_ods_and_no_partial_matching_filter():
    """Le contrôle lit SAGE complet même sans aucune proposition Envoyé SAGE."""
    atlas = pd.DataFrame(
        [atlas_row(), atlas_row("B"), atlas_row("C", **{"N° pièce SAGE": "ODS-ATLAS"})]
    )
    sage = pd.DataFrame(
        [
            sage_row(**{"Charges (Dépenses)": 60}),
            sage_row(**{"N° de ligne comptable": "002", "Charges (Dépenses)": 40}),
            sage_row(
                **{
                    "Numéro pièce": "ODG-SAGE",
                    "Libellé pièce": "CAFE\u00a0MISSION",
                    "Charges (Dépenses)": 50,
                }
            ),
        ]
    )
    result = match_reconciliations(atlas, sage)
    controls = list(
        build_controls(atlas, sage, result, amount_field="total_sage_charges")
    )
    standard = next(
        c for c in controls if c["identity"]["strategy"] == "STANDARD_BY_DOCUMENT"
    )
    ods = next(c for c in controls if c["identity"]["strategy"] == "ODS_ODG_BY_GROUP")
    assert standard["status"] == "EXCESS"
    assert standard["sage_count"] == 2
    assert standard["atlas_total"] == "140.00"
    assert ods["status"] == "EXCESS"
    assert ods["sage_total"] == "50"
    reverse = list(
        build_controls(
            atlas.iloc[::-1],
            sage.iloc[::-1],
            match_reconciliations(atlas.iloc[::-1], sage.iloc[::-1]),
            amount_field="total_sage_charges",
        )
    )
    assert {c["signature"] for c in controls} == {c["signature"] for c in reverse}


def test_unknown_amount_policy_and_original_currency():
    """Charges SAGE est toujours en euros, indépendamment de la devise de l'opération."""
    atlas, sage = pd.DataFrame([atlas_row()]), pd.DataFrame([sage_row()])
    result = match_reconciliations(atlas, sage)
    assert (
        list(build_controls(atlas, sage, result, amount_field=None))[0]["status"]
        == "UNKNOWN"
    )
    sage["Devise"] = "USD"
    assert list(build_controls(atlas, sage, result))[0]["status"] == "SHORTFALL"

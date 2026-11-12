"""Cas synthétiques fondés sur les formats et distributions de data/inputs.

Pas de nom de tiers, libellé ou identifiant métier réel dans les tests.
Constats : deux feuilles Atlas utiles + une vide, doublon interfeuilles,
historique largement comptabilisé, dates Sage sentinelles, TVA descriptive,
colonne finale CSV vide, devises Atlas descriptives et une référence absente.
"""

import pandas as pd

from matching_helpers import atlas_row, sage_row, frames
from reconciliation.loaders.atlas import load_atlas
from reconciliation.loaders.sage import load_sage
from reconciliation.matching import match_reconciliations
from reconciliation.matching.trace import iter_attempts
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage


def test_sage_sentinel_dates_descriptive_vat_and_trailing_separator(tmp_path):
    """Préserve dates invalides signalées, colonne CSV vide et charges décimales exactes."""
    source = tmp_path / "ZLISTPJT.csv"
    source.write_text(
        "Projet;Numéro pièce;Date comptable;Date modification;Date début de prestation;"
        "Taux de TVA;Charges (Dépenses);Libellé pièce;Code Tiers - Tiers doc Orig;Référence;\n"
        "P;00001;16/09/2026;  /  /    ;  /  /    ;SC6 TVA France 20.0%;"
        "1 000,00;FACTURE CONSULTANT DUPONT JANVIER;T;B;\n",
        encoding="utf-8-sig",
    )
    sage = load_sage(source)
    assert sage["Date modification"].isna().all()
    assert sage["Taux de TVA"].isna().all()  # Mapping numérique actuel, ne pas inventer un taux.
    assert sage.attrs["typing_issues"] == {"Date modification": 1, "Date début de prestation": 1, "Taux de TVA": 1}
    assert sage["Charges (Dépenses)"].iloc[0] == 1000
    assert sage["Numéro pièce"].iloc[0] == "00001"
    assert sage["Unnamed: 10"].isna().all()
    assert sage["_charges_decimal"].iloc[0] == "1000.00"
    atlas, _ = frames()
    result = match_reconciliations(atlas, transform_sage(sage))
    assert result.iloc[0].match_rule == "MATCH_EXACT"


def test_two_useful_sheets_one_empty_and_duplicate_before_status_filter(tmp_path):
    source = tmp_path / "JDD.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([atlas_row(Id="001", **{"Année": 2020, "Statut BAP": "Comptabilisé"})]).to_excel(writer, sheet_name="Sheet1", index=False)
        pd.DataFrame([atlas_row(Id="001"), atlas_row(Id="002", **{"Année": 2026})]).to_excel(writer, sheet_name="Sheet2", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="Sheet3", index=False)
    raw = load_atlas(source)
    assert raw.attrs["load_summary"]["duplicates_removed"] == 1
    _, sage = frames()
    result = match_reconciliations(transform_atlas(raw), sage)
    # Filtrer avant de dédupliquer changerait la première occurrence de 001.
    assert result.iloc[0].atlas_source_ids == ("002",)
    assert result.attrs["population_summary"]["atlas_rows_excluded"] == 1


def test_large_accounted_history_does_not_generate_attempts(tmp_path):
    accounted = atlas_row(**{"Statut BAP": "Comptabilisé", "Année": 2020})
    a, s = frames([dict(accounted, Id=str(i)) for i in range(10000)] + [atlas_row(Id="LAST")])
    result = match_reconciliations(a, s, trace_path=tmp_path / "trace.jsonl")
    assert result.attrs["population_summary"]["atlas_rows_selected"] == 1
    assert result.iloc[0].atlas_source_positions == (10000,)
    assert result.attrs["trace_row_count"] < 10
    assert result.attrs["matching_attempts"] == []
    assert all(row["atlas_source_ids"] == ["LAST"] for row in iter_attempts(result))


def test_missing_bap_is_not_replaced_by_atlas_bap():
    a, s = frames([atlas_row(**{"N° BAP (SAGE)": None, "N° BAP (Atlas)": "B"})])
    result = match_reconciliations(a, s, collect_trace=True)
    assert result.iloc[0].reason == "INCOMPLETE_STRUCTURED_KEY"
    assert result.iloc[0].match_status == "UNMATCHED"


def test_descriptive_currency_and_old_atlas_year_do_not_change_existing_rules():
    a, s = frames([atlas_row(**{"Année": 2025, "Devise": "USD - Dollar Usa"})],
                  [sage_row(Devise="USD", **{"Date comptable": pd.Timestamp("2026-01-31")})])
    result = match_reconciliations(a, s)
    # Les montants comparés sont projet EUR / charges, pas les montants en devises.
    # Année Atlas n'est pas la date comptable Sage : pas de filtre annuel implicite.
    assert result.iloc[0].match_rule == "MATCH_EXACT"


def test_large_sage_group_keeps_all_incompatible_documents():
    a, s = frames([atlas_row(**{"Total charges projet (€)": 577.})],
                  [sage_row(**{"Charges (Dépenses)": 1., "Numéro pièce": f"D{i:04d}"}) for i in range(577)])
    result = match_reconciliations(a, s)
    row = result.iloc[0]
    assert row.match_status == "AMBIGUOUS"
    assert row.sage_row_count == 577 and len(row.sage_document_numbers) == 577
    assert row.sage_document_number is None

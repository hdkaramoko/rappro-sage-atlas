"""Contrats communs aux transformations Atlas et Sage."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage
from reconciliation.transformations.common import TransformationError, normalize_text


@pytest.mark.parametrize("transform, source, columns", [
    (transform_atlas, "ATLAS", [
        "Code projet", "N° pièce SAGE", "Libellé ATLAS", "Nom du tiers",
    ]),
    (transform_sage, "SAGE", [
        "Projet", "Numéro pièce", "Libellé pièce", "Nom du Tiers",
    ]),
])
def test_canonical_values_and_preservation(transform, source, columns):
    raw = pd.DataFrame({
        columns[0]: ["\u00a0afg-001 ", "  "],
        columns[1]: [" 000a/02 ", None],
        columns[2]: [" Libellé éÀ / test ", ""],
        columns[3]: [" Société X\u202f", pd.NA],
        "Devise": [" eur ", ""],
        "Référence": [" ref/001-2 ", None],
        "Date comptable": pd.to_datetime(["2026-01-31", None]),
        "N° BAP (Atlas)": ["001", "002"],
        "N° BAP (SAGE)": ["003", "004"],
        "Extra": [12, 13],
    }, index=[7, 7])
    raw.attrs["load_summary"] = {"rows_final": 2}
    before = raw.copy(deep=True)
    result = transform(raw)
    assert_frame_equal(raw, before)
    assert_frame_equal(result[raw.columns], raw)
    assert result.index.tolist() == [7, 7]
    assert len(result) == 2
    assert result.project_code.iloc[0] == "AFG-001"
    assert result.accounting_document.iloc[0] == "000A/02"
    assert result.label.iloc[0] == "Libellé éÀ / test"
    assert result.third_party.iloc[0] == "Société X"
    assert result.currency.iloc[0] == "EUR"
    assert result.source.tolist() == [source, source]
    assert pd.isna(result.project_code.iloc[1])
    assert result.accounting_date.iloc[0] == pd.Timestamp("2026-01-31")
    assert str(result.accounting_date.dtype) == "datetime64[ns]"
    assert str(result.amount.dtype) == "Float64"
    assert result.amount.isna().all()
    if source == "SAGE":
        assert result.reference.iloc[0] == "REF/001-2"
    else:
        assert result.reference.isna().all()
    assert result.attrs["load_summary"] == raw.attrs["load_summary"]
    assert result.attrs["transformation_summary"]["missing_project_codes"] == 1
    result.loc[:, columns[0]] = "modifié"
    assert_frame_equal(raw, before)


@pytest.mark.parametrize("transform", [transform_atlas, transform_sage])
@pytest.mark.parametrize("rows", [0, 2])
def test_missing_optional_columns_and_empty(transform, rows):
    raw = pd.DataFrame(index=range(rows))
    result = transform(raw)
    assert len(result) == rows
    assert list(result.columns) == [
        "project_code", "reference", "accounting_document", "amount",
        "currency", "accounting_date", "label", "third_party", "source",
    ]
    assert result.drop(columns="source").isna().all().all()
    assert str(result.project_code.dtype) == "string"
    assert str(result.accounting_date.dtype) == "datetime64[ns]"


def test_text_does_not_remove_separators_or_internal_spaces():
    result = normalize_text(pd.Series([" 00a / b-2.é  ", "\u00a0", None]), uppercase=True)
    assert result.iloc[0] == "00A / B-2.É"
    assert result.iloc[1:].isna().all()


@pytest.mark.parametrize("transform", [transform_atlas, transform_sage])
def test_canonical_collision_is_not_overwritten(transform):
    with pytest.raises(TransformationError, match="déjà présents"):
        transform(pd.DataFrame({"project_code": ["source à conserver"]}))


def test_loader_to_transformation(tmp_path):
    from reconciliation.loaders.atlas import load_atlas
    from reconciliation.loaders.sage import load_sage

    atlas_path = tmp_path / "atlas.xlsx"
    sage_path = tmp_path / "sage.csv"
    pd.DataFrame({
        "Id": ["001"], "Code projet": [" a-01 "],
        "Date comptable": ["invalide"],
    }).to_excel(atlas_path, index=False)
    sage_path.write_text(
        "Projet;Numéro pièce;Date comptable;Référence\na-01;0002;31/01/2026; ref-1 \n",
        encoding="utf-8",
    )
    atlas = transform_atlas(load_atlas(atlas_path))
    sage = transform_sage(load_sage(sage_path))
    assert atlas.project_code.iloc[0] == sage.project_code.iloc[0] == "A-01"
    assert pd.isna(atlas.accounting_date.iloc[0])
    assert atlas.attrs["typing_issues"] == {"Date comptable": 1}
    assert sage.reference.iloc[0] == "REF-1"

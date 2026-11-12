"""Clés techniques ODS/ODG versionnées, sources et sécurité des contextes."""

import copy
import pytest

from reconciliation_contract import control_identity
from reconciliation_contract.ods_party import ABSENT, POLICY, party_context, party_scope


@pytest.mark.parametrize("left,right,equal", [("", "NA", True), (None, " na ", True),
    ("T", "T", True), ("T", "U", False), ("T", "NA", False), ("", "T", False)])
@pytest.mark.parametrize("prefix", ["ODS", "ODG"])
def test_absent_parties_only_are_equivalent(left, right, equal, prefix):
    """Assimile uniquement deux absences, sans altérer les sources ni assimiler un tiers connu."""
    a = {"project_code": "P", "fiscal_year": 2026, "sage_document_number": prefix+"1",
         "bap_status": "Comptabilisé", "sage_label": "TVA", "sage_third_party_code": left}
    s = {"project_code": "P", "fiscal_year": 2026, "document": prefix+"2", "label": "TVA", "third_party": right}
    before = copy.deepcopy((a, s))
    with party_scope(True):
        assert (control_identity(a) == control_identity(s, sage=True)) is equal
    assert (a, s) == before


def test_legacy_other_types_and_generator_context_are_preserved():
    """L'absence de politique garde les clés historiques ; un yield partiel ne fuit pas dans le contexte appelant."""
    row = {"project_code": "P", "fiscal_year": 2026, "sage_document_number": "ODS1", "sage_third_party_code": "NA"}
    old = control_identity(row)

    @party_context()
    def values(campaign):
        """Retourne deux clés sous la politique synthétique pour vérifier la restauration entre yields."""
        yield control_identity(row)
        yield control_identity(row)

    stream = values({"ods_party_policy": POLICY})
    assert next(stream)["parts"][2] == ABSENT
    assert control_identity(row) == old
    stream.close()
    assert control_identity(row) == old
    keyword_stream = values(campaign={"ods_party_policy": POLICY})
    assert next(keyword_stream)["parts"][2] == ABSENT
    keyword_stream.close()
    with party_scope(True):
        for prefix in ("ODA", "FAF"):
            known = {**row, "sage_document_number": prefix+"1"}
            assert control_identity(known) == {"strategy": "STANDARD_BY_DOCUMENT", "parts": ["P", 2026, prefix+"1"]}

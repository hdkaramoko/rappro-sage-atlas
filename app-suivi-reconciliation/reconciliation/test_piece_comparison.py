from copy import deepcopy

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from .templatetags.review_ui import piece_comparison


class PieceComparisonTests(SimpleTestCase):
    def test_repeated_combinations_and_missing_entries(self):
        row = {"third_party": "T", "bap": "B", "amount": "10.00"}
        data = {"atlas": [row, row], "sage": [{**row, "amount": "10"}]}
        original = deepcopy(data)
        result = piece_comparison(data)
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]["atlas_count"], result[0]["sage_count"], result[0]["difference"]), (2, 1, 1))
        self.assertEqual(result[0]["label"], "Multiplicité différente")
        self.assertEqual(data, original)

    def test_third_party_reference_sign_and_precision_remain_distinct(self):
        row = {"third_party": "T", "bap": "B", "amount": "10.001"}
        result = piece_comparison({"atlas": [row], "sage": [
            {**row, "amount": "-10.001"}, {**row, "bap": "OTHER"},
            {**row, "third_party": "OTHER"}, {**row, "amount": "10.002"}]})
        self.assertEqual(len(result), 5)
        self.assertTrue(all(r["tone"] == "warning" for r in result))
        self.assertIn("10,001", {r["amount"] for r in result})
        self.assertIn("-10,001", {r["amount"] for r in result})

    def test_absent_data_is_never_presented_as_concordant(self):
        row = {"third_party": "", "bap": "B", "amount": None}
        result = piece_comparison({"atlas": [row], "sage": [row]})
        self.assertEqual(result[0]["label"], "Champ manquant")
        self.assertEqual(piece_comparison({}), [])

    def test_component_collapsed_escaped_and_compatible_with_older_campaign(self):
        row = {"third_party": "<script>bad()</script>", "bap": "B", "amount": "0"}
        html = render_to_string("components/piece_coherence.html", {"piece_check": {
            "status": "PIECE_MISMATCH", "atlas": [row], "sage": []}})
        self.assertIn('<details class="piece-comparison">', html)
        self.assertNotIn("<details open", html)
        self.assertNotIn("<script>", html)
        self.assertIn('<th scope="col">Source</th>', html)
        self.assertNotIn('<th scope="col">Comparaison</th>', html)
        self.assertNotIn('class="numeric">Écart</th>', html)
        self.assertIn('>Atlas</span>', html)
        html = render_to_string("components/piece_coherence.html", {"piece_check": {"status": "NOT_CHECKED"}})
        self.assertIn("Aucune donnée de comparaison disponible", html)

    def test_source_identifies_both_sides_without_splitting_combinations(self):
        common = {"third_party": "T", "bap": "COMMON", "amount": "10"}
        data = {"atlas": [common, common, {**common, "bap": "ATLAS_ONLY"}],
                "sage": [common, {**common, "bap": "SAGE_ONLY"}]}
        rows = {row["bap"]: row for row in piece_comparison(data)}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows["COMMON"]["source"], "Atlas et SAGE")
        self.assertEqual((rows["COMMON"]["atlas_count"], rows["COMMON"]["sage_count"]), (2, 1))
        self.assertEqual(rows["ATLAS_ONLY"]["source"], "Atlas")
        self.assertEqual(rows["SAGE_ONLY"]["source"], "SAGE")

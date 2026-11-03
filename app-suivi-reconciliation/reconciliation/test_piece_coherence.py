from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse
from reconciliation_contract.piece_coherence import atlas_entry, sage_entry, check_piece

from . import test_campaigns as fixtures
from .models import Campaign, LineReview, ReviewEvent
from .piece_coherence import _same_atlas_entry, validate_proposal_check


class ProposalDiagnosticValidationTests(SimpleTestCase):
    """Vérifie l'équivalence décimale sans relâcher l'intégrité des autres preuves."""

    def test_equivalent_decimal_formats_preserve_signed_diagnostic(self):
        """Accepte formats entiers, décimaux et scientifiques sans réécrire la signature."""
        import copy
        for source, diagnostic_amount in (("374", "374.0"), ("8820", "8820.00"),
                                          ("-374", "-374.000"), ("0.001", "1E-3"),
                                          ("0", "-0.00"), (None, None)):
            with self.subTest(source=source, diagnostic=diagnostic_amount):
                row = fixtures.atlas(**{"N° pièce SAGE": "D", "Total charges SAGE (€)": source})
                entry = {**atlas_entry(row), "amount": diagnostic_amount}
                diagnostic = check_piece("P", "D", [entry], [])
                payload = {"atlas": [row], "piece_coherence": diagnostic}
                original = copy.deepcopy(payload)
                self.assertIs(validate_proposal_check(payload), diagnostic)
                self.assertEqual(payload, original)

    def test_business_differences_are_rejected(self):
        """Un centime, une absence, un signe ou tout autre champ différent restent refusés."""
        row = fixtures.atlas(**{"N° pièce SAGE": "D", "Total charges SAGE (€)": "374"})
        entry = atlas_entry(row)
        diagnostic = check_piece("P", "D", [{**entry, "amount": "374.0"}], [])
        changes = {"Id": "OTHER", "Code projet": "OTHER", "Année": 2025,
                   "N° pièce SAGE": "OTHER", "Date comptable": "2025-01-01",
                   "Code tiers SAGE": "OTHER", "N° BAP (SAGE)": "OTHER"}
        for field, value in list(changes.items()) + [("Total charges SAGE (€)", v) for v in ("374.01", "-374", None)]:
            with self.subTest(field=field, value=value):
                with self.assertRaisesMessage(ValidationError, "Ligne Atlas absente ou contradictoire"):
                    validate_proposal_check({"atlas": [{**row, field: value}], "piece_coherence": diagnostic})
        self.assertFalse(_same_atlas_entry({"amount": None}, {"amount": "0"}))
        self.assertFalse(_same_atlas_entry({"amount": None}, {"amount": "NaN"}))
        self.assertFalse(_same_atlas_entry({"amount": "NaN"}, {"amount": "NaN"}))

    def test_tampered_diagnostic_and_multiple_sources_are_rejected(self):
        """La signature reste obligatoire et une proposition doit avoir une seule source."""
        import copy
        row = fixtures.atlas(**{"N° pièce SAGE": "D", "Total charges SAGE (€)": "374"})
        diagnostic = check_piece("P", "D", [{**atlas_entry(row), "amount": "374.0"}], [])
        altered = copy.deepcopy(diagnostic)
        altered["atlas"][0]["amount"] = "374.00"
        with self.assertRaises(ValidationError):
            validate_proposal_check({"atlas": [row], "piece_coherence": altered})
        with self.assertRaises(ValidationError):
            validate_proposal_check({"atlas": [row, row], "piece_coherence": diagnostic})


class PieceDiagnosticTests(fixtures.CampaignTests):
    def test_equivalent_decimal_format_imports_without_changing_diagnostic(self):
        """Importe le JSONL existant malgré 100/100.0 et conserve le diagnostic signé."""
        import copy
        row, payload = self.diagnostic_payload()
        data = payload["piece_coherence"]
        data = check_piece(data["project"], data["document"],
                           [{**entry, "amount": "100.0"} for entry in data["atlas"]], data["sage"])
        payload["piece_coherence"] = data
        original = copy.deepcopy(data)
        campaign = self.load(inventory=[row], proposals=[payload])
        self.assertEqual(campaign.reviews.get().group.data["piece_coherence"], original)

    def diagnostic_payload(self):
        row = fixtures.atlas(**{"N° pièce SAGE": "D", "Date comptable": "2026-01-01",
                                "Total charges SAGE (€)": "100", "Code tiers SAGE": "T",
                                "N° BAP (SAGE)": "B"})
        raw = {"Projet": "P", "Numéro pièce": "D", "Date comptable": "2026-01-01",
               "Charges (Dépenses)": "100", "Code Tiers - Tiers doc Orig": "T",
               "Référence": "B", "Journal": "ACH", "N° de ligne comptable": "1",
               "N° de ligne Analytique": "1"}
        diagnostic = check_piece("P", "D", [atlas_entry(row)], [sage_entry(raw)])
        payload = fixtures.proposal([row], rule="MATCH_CONFIRMED_ATLAS", evidence=[], piece_coherence=diagnostic)
        return row, payload

    def test_diagnostic_is_displayed_and_never_validates(self):
        row, payload = self.diagnostic_payload()
        campaign = self.load(inventory=[row], proposals=[payload])
        line = LineReview.objects.get()
        self.assertEqual((line.state, line.version), ("DRAFT", 0))
        self.assertEqual(ReviewEvent.objects.count(), 0)
        for name, pk in (("review-detail", line.pk), ("campaign-review", campaign.reviews.get().pk)):
            response = self.client.get(reverse("reconciliation:" + name, args=[pk]))
            self.assertContains(response, "Contrôle de cohérence SAGE")
            self.assertContains(response, "Pièce cohérente avec SAGE")
            self.assertNotContains(response, "PIECE_RECONCILED")
            source_heading = "Données sources" if name == "review-detail" else "Source de cette campagne"
            html = response.content.decode()
            self.assertLess(html.index(source_heading), html.index("Contrôle de cohérence SAGE"))
        response = self.client.get(reverse("reconciliation:reviews"))
        self.assertNotContains(response, "Contrôle de cohérence SAGE")

    def test_idempotence_human_priority_and_frozen_diagnostic(self):
        from .review_import import import_bundle
        row, payload = self.diagnostic_payload()
        path = self.bundle(inventory=[row], proposals=[payload])
        import_bundle(path)
        count = Campaign.objects.count()
        import_bundle(path)
        self.assertEqual(Campaign.objects.count(), count)
        self.validate(state="REJECTED")
        first = Campaign.objects.get(is_current=True)
        self.load(inventory=[row], proposals=[payload])
        self.assertEqual(LineReview.objects.get().state, "REJECTED")
        self.assertEqual(ReviewEvent.objects.count(), 1)
        self.load()
        self.assertEqual(first.reviews.get().group.data["piece_coherence"], payload["piece_coherence"])
        self.assertEqual(first.reviews.get().decision["state"], "REJECTED")

    def test_invalid_diagnostic_rolls_back_campaign(self):
        row, payload = self.diagnostic_payload()
        payload["piece_coherence"]["atlas_total"] = "999"
        with self.assertRaises(ValidationError):
            self.load(inventory=[row], proposals=[payload])
        self.assertEqual(Campaign.objects.count(), 0)
        self.assertEqual(LineReview.objects.count(), 0)

    def test_reconciled_shared_piece_does_not_enable_auto_validation(self):
        row, payload = self.diagnostic_payload()
        other = {**row, "Id": "B", "Total charges SAGE (€)": "60",
                 "Total charges projet (€)": "60"}
        row.update({"Total charges SAGE (€)": "40", "Total charges projet (€)": "40"})
        sage = payload["piece_coherence"]["sage"][0]
        diagnostic = check_piece("P", "D", [atlas_entry(row), atlas_entry(other)],
            [{**sage, "amount": "40"}, {**sage, "ref": "second-entry", "amount": "60"}])
        self.assertEqual(diagnostic["status"], "PIECE_RECONCILED")
        proposals = [fixtures.proposal([source], key=source["Id"], rule="MATCH_CONFIRMED_ATLAS",
            sage_total=source["Total charges SAGE (€)"], evidence=[], piece_coherence=diagnostic,
            auto_validation={"source": "AUTO", "rule": "MATCH_CONFIRMED_ATLAS", "state": "VALIDATED"})
            for source in (row, other)]
        campaign = self.load(inventory=[row, other], proposals=proposals)
        self.assertEqual(LineReview.objects.filter(state="VALIDATED").count(), 0)
        self.assertEqual(ReviewEvent.objects.count(), 0)
        for frozen in campaign.reviews.all():
            self.assertIn("Preuve partagée", " ".join(frozen.reasons))

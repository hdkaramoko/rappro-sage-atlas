from django.core.exceptions import ValidationError
from django.urls import reverse
from reconciliation_contract.piece_coherence import atlas_entry, sage_entry, check_piece

from . import test_campaigns as fixtures
from .models import Campaign, LineReview, ReviewEvent


class PieceDiagnosticTests(fixtures.CampaignTests):
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

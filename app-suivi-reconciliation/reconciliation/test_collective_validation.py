import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from reconciliation_contract import control_identity, entry_from_sage, snapshot
from reconciliation_contract.piece_coherence import atlas_entry, sage_entry, check_piece

from . import test_campaigns as fixtures
from .models import Campaign, ControlContribution, LineReview, ReviewEvent
from .review import is_current
from .review_import import import_bundle


class CollectiveTests(TestCase):
    setUp = fixtures.CampaignTests.setUp
    bundle = fixtures.CampaignTests.bundle
    validate = fixtures.CampaignTests.validate

    def records(self, *, amounts=("40", "60"), mode="ACTIVE"):
        sources, proofs = [], []
        for number, amount in enumerate(amounts, 1):
            sources.append(fixtures.atlas(str(number), **{
                "Total charges projet (€)": amount, "Total charges SAGE (€)": amount,
                "Code tiers SAGE": "T", "N° BAP (SAGE)": "B", "Devise": "EUR",
                "N° pièce SAGE": "D", "Date comptable": "2026-01-01"}))
            proofs.append({"Projet": "P", "Numéro pièce": "D", "Date comptable": "2026-01-01",
                "Journal": "ACH", "N° de ligne comptable": str(number),
                "N° de ligne Analytique": "1", "Code Tiers - Tiers doc Orig": "T",
                "Référence": "B", "Charges (Dépenses)": amount, "Devise": "EUR"})
        diagnostic = check_piece("P", "D", [atlas_entry(r) for r in sources], [sage_entry(r) for r in proofs])
        entries = [entry_from_sage(r) for r in proofs]
        control = snapshot(control_identity(entries[0], sage=True), [], entries, amount_field="total_sage_charges")
        proposals = [fixtures.proposal([r], key=r["Id"], rule="MATCH_CONFIRMED_ATLAS", schema_version=3,
            sage_total=r["Total charges SAGE (€)"], evidence=[], piece_coherence=diagnostic,
            auto_validation={"source": "AUTO", "rule": "MATCH_CONFIRMED_ATLAS", "state": "VALIDATED"}) for r in sources]
        path = self.bundle(inventory=sources, proposals=proposals)
        records = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
        records[0].update(schema_version=3, controls_available=True, piece_coherence_mode=mode,
                          amount_field="total_sage_charges", sage_amount_currency="EUR", tolerance="0.01")
        records.insert(-1, {"type": "control", "data": control})
        records[-1].update(control_count=1, control_statuses={control["status"]: 1})
        return records

    def load_records(self, records):
        from pathlib import Path
        path = Path(self.folder.name) / "collective.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def assert_validated(self, count=2):
        lines = list(LineReview.objects.select_related("transaction__project", "group"))
        self.assertEqual(len(lines), count)
        refs = set()
        for line in lines:
            self.assertEqual((line.state, line.validation_source), ("VALIDATED", "AUTO"))
            self.assertTrue(is_current(line))
            refs.add(line.automatic_assignment["entry"]["ref"])
        self.assertEqual(len(refs), count)

    def test_shared_piece_atomic_validation_and_reimport(self):
        records = self.records()
        campaign = self.load_records(records)
        self.assert_validated()
        self.assertEqual(ReviewEvent.objects.count(), 2)
        self.assertEqual(ControlContribution.objects.filter(control__campaign=campaign).count(), 2)
        self.load_records(records)
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertEqual(ReviewEvent.objects.count(), 2)

    def test_assignment_visible_in_detail_history_and_export(self):
        from django.urls import reverse
        from io import BytesIO
        from openpyxl import load_workbook
        campaign = self.load_records(self.records())
        frozen = campaign.reviews.first()
        for name, pk in (("review-detail", frozen.line_id), ("campaign-review", frozen.pk)):
            response = self.client.get(reverse("reconciliation:" + name, args=[pk]))
            self.assertContains(response, "Écriture SAGE affectée à cette ligne")
            self.assertContains(response, "Contrôle collectif actif")
        response = self.client.get(reverse("reconciliation:campaign-export", args=[campaign.pk]))
        workbook = load_workbook(BytesIO(response.content))
        exported = list(workbook.active.values)
        column = exported[0].index("Affectation automatique SAGE")
        self.assertEqual(len(exported), 3)
        self.assertTrue(all(json.loads(row[column])["entry"]["ref"] for row in exported[1:]))
        workbook.close()

    def test_successive_campaign_carries_without_duplicate_events(self):
        self.load_records(self.records())
        second = self.load_records(self.records())
        self.assert_validated()
        self.assertEqual(ReviewEvent.objects.count(), 2)
        self.assertEqual(set(second.reviews.values_list("comparison", flat=True)), {"CARRIED"})

    def test_repeated_combinations_are_assigned_distinct_entries(self):
        self.load_records(self.records(amounts=("50", "50")))
        self.assert_validated()

    def test_single_piece(self):
        self.load_records(self.records(amounts=("100",)))
        self.assert_validated(1)

    def test_default_diagnostic_does_not_unblock_shared_piece(self):
        self.load_records(self.records(mode="DIAGNOSTIC"))
        self.assertEqual(LineReview.objects.filter(state="VALIDATED").count(), 0)

    def test_human_rejection_preserved_and_other_auto_invalidated(self):
        first = self.load_records(self.records())
        line = LineReview.objects.select_related("group", "transaction__project").get(transaction__source_id="1")
        self.validate(line, amount="40", state="REJECTED")
        self.load_records(self.records())
        human = LineReview.objects.get(pk=line.pk)
        self.assertEqual((human.state, human.validation_source, human.automatic_assignment), ("REJECTED", "MANUAL", {}))
        other = LineReview.objects.select_related("group", "transaction__project").get(transaction__source_id="2")
        self.assertFalse(is_current(other))
        self.assertTrue(first.reviews.get(source__source_id="2").decision["current"])

    def test_savepoint_rolls_back_first_decision_if_second_fails(self):
        from .collective_validation import decide
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise ValidationError("Échec simulé du second membre")
            return decide(*args, **kwargs)
        with patch("reconciliation.collective_validation.decide", side_effect=fail_second):
            campaign = self.load_records(self.records())
        self.assertEqual(len(calls), 2)
        self.assertEqual(ReviewEvent.objects.count(), 0)
        self.assertEqual(ControlContribution.objects.count(), 0)
        self.assertEqual(LineReview.objects.filter(version=0, state="DRAFT", automatic_assignment={}).count(), 2)
        self.assertTrue(all("Échec simulé" in " ".join(r.reasons) for r in campaign.reviews.all()))

    def test_one_member_without_authorization_blocks_everyone(self):
        records = self.records()
        proposals = [r for r in records if r.get("type") == "proposal"]
        proposals[-1].pop("auto_validation")
        self.load_records(records)
        self.assertEqual(LineReview.objects.filter(state="VALIDATED").count(), 0)
        self.assertEqual(ControlContribution.objects.count(), 0)

    def test_unknown_activation_mode_rejects_import(self):
        with self.assertRaisesMessage(ValidationError, "Mode de cohérence SAGE inconnu"):
            self.load_records(self.records(mode="UNKNOWN"))
        self.assertEqual(Campaign.objects.count(), 0)

    def test_disabled_mode_invalidates_collective_auto(self):
        self.load_records(self.records())
        self.load_records(self.records(mode="DIAGNOSTIC"))
        self.assertTrue(all(not is_current(r) for r in LineReview.objects.select_related("transaction__project", "group")))
        self.assertEqual(ControlContribution.objects.filter(control__campaign__is_current=True).count(), 0)

    def test_changed_piece_revalidated_and_old_snapshot_preserved(self):
        first = self.load_records(self.records())
        self.load_records(self.records(amounts=("45", "55")))
        self.assert_validated()
        self.assertEqual(first.reviews.get(source__source_id="1").decision["effective"]["amount"], "40.00")
        self.assertEqual(ReviewEvent.objects.count(), 4)

    def test_current_human_validation_is_not_converted_to_auto(self):
        self.load_records(self.records(mode="DIAGNOSTIC"))
        line = LineReview.objects.select_related("group", "transaction__project").get(transaction__source_id="1")
        self.validate(line, amount="40")
        self.load_records(self.records())
        line.refresh_from_db()
        self.assertEqual((line.state, line.validation_source), ("VALIDATED", "MANUAL"))
        self.assertEqual(LineReview.objects.filter(validation_source="AUTO").count(), 0)

    def test_incomplete_piece_membership_blocks_all(self):
        records = self.records()
        records = [r for r in records if not (
            r.get("type") == "proposal" and r["atlas"][0]["Id"] == "2"
            or r.get("type") == "inventory" and r["atlas"]["Id"] == "2")]
        records[-1].update(complete=1, inventory_count=1)
        campaign = self.load_records(records)
        self.assertEqual(LineReview.objects.get().state, "DRAFT")
        self.assertIn("Composition de pièce incomplète", " ".join(campaign.reviews.get().reasons))

    def test_diagnostic_cannot_substitute_for_different_control_evidence(self):
        from reconciliation_contract.piece_coherence import check_piece
        records = self.records()
        proposals = [r for r in records if r.get("type") == "proposal"]
        old = proposals[0]["piece_coherence"]
        proofs = [{**r} for r in old["sage"]]
        proofs[0]["amount"], proofs[1]["amount"] = proofs[1]["amount"], proofs[0]["amount"]
        diagnostic = check_piece("P", "D", old["atlas"], proofs)
        self.assertEqual(diagnostic["status"], "PIECE_RECONCILED")
        for payload in proposals:
            payload["piece_coherence"] = diagnostic
        self.load_records(records)
        self.assertEqual(LineReview.objects.filter(state="VALIDATED").count(), 0)
        self.assertEqual(ControlContribution.objects.count(), 0)

    def test_unknown_control_invalidates_all_carried_auto(self):
        first = self.load_records(self.records())
        records = self.records()
        control = next(r for r in records if r.get("type") == "control")
        data = control["data"]
        control["data"] = snapshot(data["identity"], data["atlas"], data["entries"],
            amount_field=data["amount_field"], reasons=["Périmètre devenu incertain"])
        records[-1]["control_statuses"] = {"UNKNOWN": 1}
        self.load_records(records)
        self.assertTrue(all(not is_current(r) for r in LineReview.objects.select_related("transaction__project", "group")))
        self.assertEqual(ControlContribution.objects.filter(control__campaign__is_current=True).count(), 0)
        self.assertTrue(all(r.decision["current"] for r in first.reviews.all()))

    def test_incoherent_piece_never_validates_even_with_request(self):
        from reconciliation_contract.piece_coherence import check_piece
        records = self.records()
        proposals = [r for r in records if r.get("type") == "proposal"]
        old = proposals[0]["piece_coherence"]
        for missing, expected in ((False, "PIECE_MISMATCH"), (True, "PIECE_AMBIGUOUS")):
            proofs = [{**r, "bap": "" if missing else "OTHER"} for r in old["sage"]]
            diagnostic = check_piece("P", "D", old["atlas"], proofs)
            self.assertEqual(diagnostic["status"], expected)
            for payload in proposals:
                payload["piece_coherence"] = diagnostic
            records[0]["name"] = f"Incohérence {missing}"
            self.load_records(records)
            self.assertEqual(LineReview.objects.filter(state="VALIDATED").count(), 0)

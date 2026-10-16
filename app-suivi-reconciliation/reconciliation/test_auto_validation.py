from .test_campaigns import CampaignTests, atlas, proposal
from .models import LineReview, ReviewEvent
from .review import is_current


class AutomaticTests(CampaignTests):
    def automatic(self, **changes):
        row = atlas()
        rule = changes.pop("rule", "MATCH_EXACT")
        return self.load(inventory=[row], proposals=[proposal([row], rule=rule,
            auto_validation={"source": "AUTO", "rule": rule, "state": "VALIDATED"}, **changes)])

    def test_configured_experimental_rules(self):
        for rule in ("MATCH_AMOUNT", "MATCH_FUZZY_HIGH", "MATCH_FUZZY_REVIEW", "MATCH_WITHOUT_LABEL"):
            with self.subTest(rule=rule):
                campaign = self.automatic(rule=rule)
                line = LineReview.objects.get()
                self.assertTrue(is_current(line))
                self.assertEqual(line.state, "VALIDATED")
                self.assertEqual(line.auto_validation_rule, rule)
                self.assertEqual(campaign.reviews.get().decision["validation_source"], "AUTO")

    def test_amount_accepts_multiple_rows_on_same_document(self):
        evidence = [{"rows": [{"Numéro pièce": "D", "Date comptable": "2026-01-01"},
                              {"Numéro pièce": "D", "Date comptable": "2026-01-01"}]}]
        self.automatic(rule="MATCH_AMOUNT", evidence=evidence)
        self.assertEqual(LineReview.objects.get().state, "VALIDATED")

    def test_experimental_conflicting_evidence_stays_manual(self):
        campaign = self.automatic(rule="MATCH_FUZZY_HIGH", evidence=[{"rows": [
            {"Numéro pièce": "D", "Date comptable": "2026-01-01"},
            {"Numéro pièce": "OTHER", "Date comptable": "2026-01-01"}]}])
        self.assertEqual(LineReview.objects.get().version, 0)
        self.assertIn("pièce/date non unique", " ".join(campaign.reviews.get().reasons))

    def test_unsafe_status_never_validates(self):
        for status in ("AMBIGUOUS", "UNMATCHED"):
            self.automatic(rule="MATCH_FUZZY_HIGH", match_status=status)
            self.assertEqual(LineReview.objects.get().version, 0)

    def v3_automatic(self, rule, *, unknown=False):
        import json
        from .review_import import import_bundle
        from .models import Campaign
        from reconciliation_contract import control_identity, entry_from_sage, snapshot
        row = atlas(**{"Code tiers SAGE": "T", "Devise": "EUR"})
        proofs = []
        for number, amount in enumerate(("40", "60") if rule == "MATCH_AMOUNT" else ("100",), 1):
            raw = {"Projet": "P", "Numéro pièce": "D", "Date comptable": "2026-01-01",
                   "Journal": "ACH", "N° de ligne comptable": str(number),
                   "N° de ligne Analytique": "1", "Charges (Dépenses)": amount,
                   "Libellé pièce": "Mission", "Code Tiers - Tiers doc Orig": "T", "Devise": "EUR"}
            raw["entry_ref"] = entry_from_sage(raw)["ref"]
            proofs.append(raw)
        entries = [entry_from_sage(raw) for raw in proofs]
        field = None if unknown else "total_sage_charges"
        control = snapshot(control_identity(entries[0], sage=True), [], entries, amount_field=field)
        payload = proposal([row], rule=rule, schema_version=3, evidence=[{"rows": proofs}],
            auto_validation={"source": "AUTO", "rule": rule, "state": "VALIDATED"})
        path = self.bundle(inventory=[row], proposals=[payload])
        records = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
        records[0].update(schema_version=3, controls_available=True, amount_field=field,
                          sage_amount_currency="EUR", tolerance="0.01")
        records.insert(-1, {"type": "control", "data": control})
        records[-1].update(control_count=1, control_statuses={control["status"]: 1})
        path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def test_v3_fuzzy_and_amount_project_and_carry(self):
        from .models import ControlContribution
        for rule in ("MATCH_FUZZY_HIGH", "MATCH_AMOUNT"):
            self.v3_automatic(rule)
            line = LineReview.objects.get()
            self.assertTrue(is_current(line))
            self.assertEqual(line.auto_validation_rule, rule)
            self.assertTrue(ControlContribution.objects.filter(line=line, control__campaign=line.campaign).exists())
            events = ReviewEvent.objects.count()
            self.v3_automatic(rule)
            self.assertEqual(ReviewEvent.objects.count(), events)

    def test_v3_unknown_control_blocks_experimental_auto(self):
        campaign = self.v3_automatic("MATCH_FUZZY_HIGH", unknown=True)
        self.assertEqual(LineReview.objects.get().version, 0)
        self.assertIn("Calcul non fiable", " ".join(campaign.reviews.get().reasons))

    def test_v3_changed_control_invalidates_old_fuzzy_decision(self):
        first = self.v3_automatic("MATCH_FUZZY_HIGH")
        self.v3_automatic("MATCH_FUZZY_HIGH", unknown=True)
        self.assertFalse(is_current(LineReview.objects.get()))
        self.assertTrue(first.reviews.get().decision["current"])

    def test_human_rejection_overrides_configured_fuzzy(self):
        self.automatic(rule="MATCH_FUZZY_HIGH")
        self.validate(state="REJECTED")
        self.automatic(rule="MATCH_FUZZY_HIGH")
        line = LineReview.objects.get()
        self.assertEqual((line.state, line.validation_source), ("REJECTED", "MANUAL"))

    def test_automatic_lifecycle(self):
        first = self.automatic()
        line = LineReview.objects.get()
        self.assertEqual(line.state, "VALIDATED")
        self.assertEqual(line.validation_source, "AUTO")
        self.assertTrue(is_current(line))
        self.assertEqual(ReviewEvent.objects.count(), 1)
        self.automatic()
        self.assertEqual(ReviewEvent.objects.count(), 1)
        self.load()
        line.refresh_from_db()
        self.assertFalse(is_current(line))
        self.assertEqual(first.reviews.get().decision["validation_source"], "AUTO")

    def test_human_priority(self):
        self.automatic()
        self.validate(state="REJECTED")
        self.automatic()
        line = LineReview.objects.get()
        self.assertEqual(line.state, "REJECTED")
        self.assertEqual(line.validation_source, "MANUAL")

    def test_identical_file_is_idempotent(self):
        from .review_import import import_bundle
        from .models import Campaign
        row = atlas()
        path = self.bundle(inventory=[row], proposals=[proposal([row], rule="MATCH_EXACT",
            auto_validation={"source": "AUTO", "rule": "MATCH_EXACT", "state": "VALIDATED"})])
        import_bundle(path)
        campaigns, events = Campaign.objects.count(), ReviewEvent.objects.count()
        import_bundle(path)
        self.assertEqual(Campaign.objects.count(), campaigns)
        self.assertEqual(ReviewEvent.objects.count(), events)

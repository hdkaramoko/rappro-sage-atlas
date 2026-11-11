from .test_campaigns import CampaignTests, atlas, proposal
from .models import LineReview, ReviewEvent
from .review import is_current


class AutomaticTests(CampaignTests):
    """Recette des autorisations AUTO, de leurs refus et des reprises entre campagnes."""
    def automatic(self, **changes):
        row = atlas()
        rule = changes.pop("rule", "MATCH_EXACT")
        return self.load(inventory=[row], proposals=[proposal([row], rule=rule,
            auto_validation={"source": "AUTO", "rule": rule, "state": "VALIDATED"}, **changes)])

    def test_configured_experimental_rules(self):
        """Les règles historiques gardent leur activation explicite hors fuzzy sans preuve v3."""
        for rule in ("MATCH_AMOUNT",):
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
        """Une preuve fuzzy ancienne et contradictoire reste sans validation ni mutation."""
        campaign = self.automatic(rule="MATCH_FUZZY_HIGH", evidence=[{"rows": [
            {"Numéro pièce": "D", "Date comptable": "2026-01-01"},
            {"Numéro pièce": "OTHER", "Date comptable": "2026-01-01"}]}])
        self.assertEqual(LineReview.objects.get().version, 0)
        self.assertIn("preuve individuelle", " ".join(campaign.reviews.get().reasons))

    def test_unsafe_status_never_validates(self):
        for status in ("AMBIGUOUS", "UNMATCHED"):
            self.automatic(rule="MATCH_FUZZY_HIGH", match_status=status)
            self.assertEqual(LineReview.objects.get().version, 0)

    def v3_automatic(self, rule, *, unknown=False, variant=None):
        """Importe une paire v3 et son inventaire complet signé dans la base jetable.

        `rule` sélectionne la catégorie, `unknown` une preuve collective non fiable,
        `variant` ajoute un concurrent, un autre BAP ou une seconde paire unique.
        Retourne la nouvelle campagne ; aucune source réelle n'est utilisée.
        """
        import json
        from .review_import import import_bundle
        from .models import Campaign
        from reconciliation_contract import control_identity, entry_from_sage, snapshot
        row = atlas(**{"Code tiers SAGE": "T", "Devise": "EUR - Euro", "N° BAP (SAGE)": "B"})
        proofs = []
        for number, amount in enumerate(("40", "60") if rule == "MATCH_AMOUNT" else ("100",), 1):
            raw = {"Projet": "P", "Numéro pièce": "D", "Date comptable": "2026-01-01",
                   "Journal": "ACH", "N° de ligne comptable": str(number),
                   "N° de ligne Analytique": "1", "Charges (Dépenses)": amount,
                   "Libellé pièce": "Mission", "Code Tiers - Tiers doc Orig": "T", "Devise": "EUR", "Référence": "B"}
            raw["entry_ref"] = entry_from_sage(raw)["ref"]
            proofs.append(raw)
        inventories = [row]
        payloads = [proposal([row], rule=rule, schema_version=3, evidence=[{"rows": proofs}],
            auto_validation={"source": "AUTO", "rule": rule, "state": "VALIDATED"})]
        if variant in ("sage", "distinct", "atlas", "shared", "bap"):
            if variant in ("sage", "distinct", "bap"):
                raw = {**proofs[0], "N° de ligne comptable": "2",
                       "Charges (Dépenses)": "200" if variant == "distinct" else "100", "Libellé pièce": "Autre"}
                raw["entry_ref"] = entry_from_sage(raw)["ref"]
                if variant == "bap":
                    raw["Référence"] = "OTHER"
                proofs = [*proofs, raw]
            if variant in ("atlas", "distinct", "shared"):
                other = atlas("B", **{"Code tiers SAGE": "T", "Devise": "EUR", "N° BAP (SAGE)": "B",
                    "Libellé ATLAS": "Autre", "Total charges projet (€)": "200" if variant == "distinct" else "100"})
                inventories.append(other)
                if variant == "atlas":
                    payloads.append(proposal([other], key="other", rule="UNMATCHED", match_status="UNMATCHED",
                                             schema_version=3, evidence=[], sage_total=None))
                if variant in ("distinct", "shared"):
                    payloads.append(proposal([other], key="other", rule=rule, schema_version=3,
                        sage_total="200" if variant == "distinct" else "100",
                        evidence=[{"rows": [proofs[-1]]}],
                        auto_validation={"source": "AUTO", "rule": rule, "state": "VALIDATED"}))
        entries = [entry_from_sage(raw) for raw in proofs]
        field = None if unknown else "total_sage_charges"
        control = snapshot(control_identity(entries[0], sage=True), [], entries, amount_field=field)
        path = self.bundle(inventory=inventories, proposals=payloads)
        records = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
        records[0].update(schema_version=3, controls_available=True, amount_field=field,
                          sage_amount_currency="EUR", tolerance="0.01")
        from reconciliation_contract.sage_inventory import CAPABILITY, exclusion_policy, inventory_record
        from .test_sage_inventory import sign_records
        policy = exclusion_policy()
        records[0].update(capabilities=[CAPABILITY], sage_exclusions=policy)
        for entry, raw in zip(entries, proofs, strict=True):
            position = next(i for i, record in enumerate(records) if record.get("type") == "proposal")
            records.insert(position, {"type": "sage_inventory", "data": inventory_record(entry, policy, attributes={"Référence": raw["Référence"]})})
        records.insert(-1, {"type": "control", "data": control})
        records[-1].update(control_count=1, control_statuses={control["status"]: 1})
        sign_records(records)
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def test_fuzzy_competitors_hidden_from_proposal_block_import_auto(self):
        """Un concurrent Atlas/Sage hors proposition ou une preuve réutilisée refuse AUTO.

        Importe de vrais inventaires signés ; les décisions antérieures restent
        photographiées. Chaque variante ne modifie que la campagne synthétique.
        """
        for variant in ("sage", "atlas", "shared"):
            with self.subTest(variant=variant):
                campaign = self.v3_automatic("MATCH_FUZZY_REVIEW", variant=variant)
                self.assertFalse(campaign.reviews.filter(decision__state="VALIDATED").exists())
                self.assertTrue(campaign.reviews.exclude(reasons=[]).exists())

    def test_fuzzy_distinct_entries_on_same_piece_are_auto(self):
        """Deux écritures traçables de montants distincts partagent une pièce sans réutilisation."""
        from .models import ControlContribution
        campaign = self.v3_automatic("MATCH_FUZZY_REVIEW", variant="distinct")
        self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED").count(), 2)
        contributions = list(ControlContribution.objects.filter(control__campaign=campaign))
        self.assertEqual(len(contributions), 2)
        self.assertNotEqual(contributions[0].entries, contributions[1].entries)

    def test_fuzzy_other_bap_no_longer_blocks_unique_pair(self):
        """Deux Sage de même montant mais BAP distincts n'empêchent pas la bonne paire AUTO."""
        campaign = self.v3_automatic("MATCH_FUZZY_REVIEW", variant="bap")
        self.assertEqual(campaign.reviews.get().decision["state"], "VALIDATED")

    def test_without_label_competitors_are_not_auto(self):
        """Sans libellé refuse les concurrents Atlas/Sage et références partagées à l'import."""
        for variant in ("sage", "atlas", "shared"):
            with self.subTest(variant=variant):
                campaign = self.v3_automatic("MATCH_WITHOUT_LABEL", variant=variant)
                self.assertFalse(campaign.reviews.filter(decision__current=True, decision__state="VALIDATED").exists())

    def test_legacy_fuzzy_without_full_inventory_stays_manual(self):
        """Un ancien contrat sans identité traçable ne reçoit aucune nouvelle AUTO fuzzy."""
        campaign = self.automatic(rule="MATCH_FUZZY_REVIEW")
        self.assertEqual(LineReview.objects.get().version, 0)
        self.assertIn("inventaires complets", " ".join(campaign.reviews.get().reasons))

    def test_fuzzy_active_manual_reservation_blocks_auto(self):
        """Une réservation manuelle active empêche AUTO de recréer une contribution Sage.

        Simule une nouvelle tentative sur une proposition revenue en brouillon,
        sans libérer la réservation inventaire. Seule la base jetable est modifiée.
        """
        from .auto_validation import apply_automatic_validations
        from .models import ControlContribution, ManualAllocation, ManualReconciliation
        campaign = self.v3_automatic("MATCH_FUZZY_HIGH")
        line = LineReview.objects.get()
        ControlContribution.objects.filter(line=line).delete()
        line.state, line.source_signature = "DRAFT", ""
        line.save(update_fields=["state", "source_signature"])
        link = ManualReconciliation.objects.create(inventory=campaign.inventory.get(), amount="100", actor=self.user)
        allocation = ManualAllocation.objects.create(link=link, entry=campaign.sage_inventory.get(), amount="100")
        apply_automatic_validations(campaign)
        line.refresh_from_db()
        self.assertEqual(line.state, "DRAFT")
        self.assertFalse(ControlContribution.objects.filter(line=line).exists())
        self.assertTrue(ManualAllocation.objects.get(pk=allocation.pk).active)
        self.assertIn("déjà affectée", " ".join(campaign.reviews.get().reasons))

    def test_v3_fuzzy_and_amount_project_and_carry(self):
        """Les deux fuzzy et Montant réservent Sage puis se reportent sans événement doublé."""
        from .models import ControlContribution
        for rule in ("MATCH_FUZZY_HIGH", "MATCH_FUZZY_REVIEW", "MATCH_WITHOUT_LABEL", "MATCH_AMOUNT", "MATCH_BAP", "MATCH_INDIVIDUAL"):
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

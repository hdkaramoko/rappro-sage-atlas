"""Recette réelle moteur → JSONL → nouvelle campagne, sur sources synthétiques A/B."""

import copy
import json
import subprocess
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from . import test_campaigns as fixtures
from .models import Campaign, ControlContribution, LineReview, ReviewEvent
from .review import decide, signature, is_current
from .review_import import import_bundle
from .test_sage_inventory import sign_records


class ValidationV2Tests(TestCase):
    """Exerce les autorisations et les réservations réelles sans base de production."""
    setUp = fixtures.CampaignTests.setUp

    @classmethod
    def setUpClass(cls):
        """Exécute une fois le vrai moteur sur trois lignes fictives du protocole A/B."""
        super().setUpClass()
        cls.sources = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.validation_v2_fixture", cls.sources.name],
                                cwd=root, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.records = [json.loads(row) for row in (Path(cls.sources.name) / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        """Supprime les seuls fichiers synthétiques temporaires de la recette."""
        cls.sources.cleanup()
        super().tearDownClass()

    def load(self, records=None):
        """Importe une nouvelle photographie signée dans la base jetable de TestCase."""
        records = copy.deepcopy(self.records if records is None else records)
        records[0]["name"] = f"Recette validation v2 {Campaign.objects.count()}"
        sign_records(records)
        path = Path(self.folder.name) / "validation-v2.jsonl"
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def confirmed(self):
        """Charge la ligne Confirmé de recette avec les relations de signature nécessaires."""
        return LineReview.objects.select_related("transaction__project", "campaign", "group").get(transaction__source_id="1903381")

    def validate_confirmed(self):
        """Soumet la décision humaine sans commentaire pour le seul écart de BAP."""
        line = self.confirmed()
        values = {name: {"mode": "KEEP"} for name in ("status", "amount", "document", "date")}
        values["status"] = {"mode": "SET", "value": "Comptabilisé"}
        return decide(line.pk, self.user, state="VALIDATED", values=values, comment="",
            expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line))

    def test_engine_jsonl_and_exact_group_individual_reservations(self):
        """652,40 + 36,48 sont AUTO ensemble, avec deux références et total 688,88."""
        campaign = self.load()
        exact = LineReview.objects.filter(group__rule="MATCH_EXACT").select_related("group", "transaction__project")
        self.assertEqual(exact.count(), 2)
        self.assertTrue(all(line.state == "VALIDATED" and is_current(line) for line in exact),
                        list(campaign.reviews.values_list("reasons", flat=True)))
        contributions = list(ControlContribution.objects.filter(control__campaign=campaign, line__group__rule="MATCH_EXACT"))
        self.assertEqual(sum(row.amount for row in contributions), Decimal("688.88"))
        self.assertEqual(len({ref for row in contributions for ref in row.entries}), 2)
        self.assertEqual(self.confirmed().state, "DRAFT")

    def test_manual_confirmed_bap_difference_is_audited_without_comment(self):
        """1903381 retrouve l'écriture importée ; le BAP diverge mais n'interdit pas la décision humaine."""
        campaign = self.load()
        line = self.validate_confirmed()
        self.assertEqual(line.validation_source, "MANUAL")
        event = line.events.first()
        self.assertTrue(event.snapshot["confirmed_evidence"]["bap_difference"])
        self.assertEqual(event.snapshot["confirmed_evidence"]["sage_bap"], "BAPPJT26100271601042026")
        self.assertTrue(event.snapshot["warnings"])
        self.assertEqual(ControlContribution.objects.get(control__campaign=campaign, line=line).amount, Decimal("8820"))
        self.assertTrue(ControlContribution.objects.get(control__campaign=campaign, line=line).entries)

    def test_confirmed_missing_or_ambiguous_evidence_stays_blocked(self):
        """Un contrôle équilibré ne remplace jamais l'identification d'une écriture unique."""
        campaign = self.load()
        control = campaign.controls.get(data__identity__parts__2="FAF0126101276")
        original = copy.deepcopy(control.data)
        for entries in ([], original["entries"] * 2):
            control.data = {**original, "entries": entries}
            control.save(update_fields=["data"])
            with self.assertRaises(ValidationError):
                self.validate_confirmed()
        self.assertEqual(self.confirmed().state, "DRAFT")

    def test_second_member_error_rolls_back_entire_exact_group(self):
        """Une erreur au second decide ne laisse ni AUTO ni réservation du premier membre."""
        from . import exact_collective
        original = exact_collective.decide
        calls = []
        def fail_second(*args, **kwargs):
            """Simule un refus métier tardif dans le savepoint collectif de recette."""
            calls.append(args[0])
            if len(calls) == 2:
                raise ValidationError("Refus tardif simulé")
            return original(*args, **kwargs)
        with patch("reconciliation.exact_collective.decide", side_effect=fail_second):
            campaign = self.load()
        self.assertEqual(LineReview.objects.filter(group__rule="MATCH_EXACT", state="VALIDATED").count(), 0)
        self.assertFalse(ControlContribution.objects.filter(control__campaign=campaign, line__group__rule="MATCH_EXACT").exists())
        self.assertFalse(ReviewEvent.objects.filter(campaign=campaign, snapshot__state="VALIDATED").exists())

    def test_human_priority_and_old_campaign_immutability(self):
        """Une décision humaine bloque tout nouveau groupe AUTO sans changer la campagne antérieure."""
        first = self.load()
        line = LineReview.objects.select_related("group", "transaction__project").get(transaction__source_id="1559564")
        decide(line.pk, self.user, state="REJECTED", values=line.values, comment="Dépense contestée",
            expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line))
        before = list(first.reviews.values_list("pk", "decision"))
        second = self.load()
        self.assertEqual(LineReview.objects.filter(group__rule="MATCH_EXACT", state="VALIDATED").count(), 1)
        self.assertFalse(second.reviews.filter(line__group__rule="MATCH_EXACT", decision__current=True, decision__state="VALIDATED").exists())
        self.assertEqual(list(first.reviews.values_list("pk", "decision")), before)

    def test_policy_does_not_change_old_campaign_manual_path(self):
        """Sans marqueur de politique dans l'ancien JSONL, aucune nouvelle résolution manuelle n'est activée."""
        records = copy.deepcopy(self.records)
        records[0].pop("validation_policy", None)
        self.load(records)
        with self.assertRaises(ValidationError):
            self.validate_confirmed()

    def test_group_order_does_not_change_attribution(self):
        """Permuter les lignes Atlas et les preuves conserve les mêmes affectations individuelles."""
        records = copy.deepcopy(self.records)
        for row in records:
            if row.get("type") == "proposal" and row["rule"] == "MATCH_EXACT":
                row["atlas"].reverse()
                row["evidence"][0]["rows"].reverse()
        self.load(records)
        amounts = {row.line.transaction.source_id: row.amount for row in ControlContribution.objects.select_related("line__transaction")}
        self.assertEqual(amounts, {"1559564": Decimal("652.40"), "1559565": Decimal("36.48")})

    def test_identical_new_campaign_carries_without_duplicate_events(self):
        """Un nouvel import identique conserve les décisions AUTO et leurs événements d'origine."""
        first = self.load()
        count = ReviewEvent.objects.count()
        second = self.load()
        self.assertEqual(ReviewEvent.objects.count(), count)
        self.assertEqual(second.reviews.filter(comparison="CARRIED").count(), 2)
        self.assertTrue(all(row.decision["current"] for row in first.reviews.filter(line__group__rule="MATCH_EXACT")))

    def test_management_import_command_accepts_generated_bundle(self):
        """La commande réelle importe le nouveau JSONL, puis reste idempotente sur les mêmes octets."""
        from django.core.management import call_command
        from django.test import override_settings
        from io import StringIO
        records = copy.deepcopy(self.records)
        sign_records(records)
        path = Path(self.folder.name) / "commande.jsonl"
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in records), encoding="utf-8")
        with override_settings(MATCHING_JOB_ROOT=Path(self.folder.name) / "jobs"):
            call_command("import_review_bundle", str(path), stdout=StringIO())
            count = ReviewEvent.objects.count()
            call_command("import_review_bundle", str(path), stdout=StringIO())
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertEqual(ReviewEvent.objects.count(), count)
        self.assertEqual(LineReview.objects.filter(group__rule="MATCH_EXACT", state="VALIDATED").count(), 2)

    def test_manual_confirmed_cent_tolerance_is_kept_by_global_control(self):
        """La tolérance déjà vérifiée sur la preuve individuelle survit au contrôle global ciblé."""
        self.load()
        line = self.confirmed()
        values = {name: {"mode": "KEEP"} for name in ("status", "amount", "document", "date")}
        values.update(status={"mode": "SET", "value": "Comptabilisé"}, amount={"mode": "SET", "value": "8820.01"})
        result = decide(line.pk, self.user, state="VALIDATED", values=values, comment="",
            expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line))
        self.assertEqual(result.state, "VALIDATED")

    def test_xof_original_currency_auto_validates_eur_charges(self):
        """1691538/1691539 sont AUTO en XOF d'origine, sans convertir les charges EUR."""
        from reconciliation_contract import snapshot
        from reconciliation_contract.sage_inventory import inventory_record
        records = copy.deepcopy(self.records)
        amounts = {"1559564": ("1691538", "3926.2706"), "1559565": ("1691539", "35.5282")}
        proposal = next(row for row in records if row.get("rule") == "MATCH_EXACT")
        entries = {}
        for raw, amount in zip(proposal["evidence"][0]["rows"], ("3926.27", "35.53")):
            raw.update({"Devise": "XOF", "Charges (Dépenses)": amount})
            entries[raw["entry_ref"]] = amount
        proposal["sage_total"] = "3961.80"
        for row in [*proposal["atlas"], *[r["atlas"] for r in records if r.get("type") == "inventory"]]:
            if row["Id"] in amounts:
                identifier, amount = amounts[row["Id"]]
                row.update({"Id": identifier, "Devise": "XOF - Franc CFA", "Total charges projet (€)": amount})
        for row in records:
            if row.get("type") == "sage_inventory" and row["data"]["entry"]["ref"] in entries:
                data = row["data"]
                entry = {**data["entry"], "currency": "XOF", "amount": entries[data["entry"]["ref"]]}
                row["data"] = inventory_record(entry, records[0]["sage_exclusions"], attributes=data["attributes"])
            if row.get("type") == "control" and any(e["ref"] in entries for e in row["data"]["entries"]):
                data = row["data"]
                proofs = [{**e, "currency": "XOF", "amount": entries[e["ref"]]} for e in data["entries"]]
                row["data"] = snapshot(data["identity"], data["atlas"], proofs,
                                       amount_field=data["amount_field"], tolerance=data["tolerance"])
        campaign = self.load(records)
        lines = LineReview.objects.filter(transaction__source_id__in=["1691538", "1691539"])
        self.assertEqual(lines.filter(state="VALIDATED", validation_source="AUTO").count(), 2)
        contributions = ControlContribution.objects.filter(control__campaign=campaign, line__in=lines)
        self.assertEqual(sum(row.amount for row in contributions), Decimal("3961.80"))
        self.assertEqual(len({ref for row in contributions for ref in row.entries}), 2)

    def test_large_group_does_not_query_inventory_for_every_member(self):
        """Trente membres utilisent les services existants sans trente lectures d'inventaire Sage."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from reconciliation_contract import entry_from_sage, control_identity, snapshot
        from reconciliation_contract.sage_inventory import inventory_record
        header = copy.deepcopy(self.records[0])
        for quality in header["load_quality"].values():
            quality.update(rows_read=30, rows_final=30)
        proposal = copy.deepcopy(next(r for r in self.records if r.get("rule") == "MATCH_EXACT"))
        source = proposal["atlas"][0]
        proof = proposal["evidence"][0]["rows"][0]
        inventory = next(r["atlas"] for r in self.records if r.get("type") == "inventory" and r["atlas"]["Id"] == "1559564")
        sources, inventories, proofs, entries = [], [], [], []
        for index in range(30):
            amount, identifier = str(index + 1), str(9000 + index)
            sources.append({**source, "Id": identifier, "Total charges projet (€)": amount})
            inventories.append({"type": "inventory", "atlas": {**inventory, "Id": identifier, "Total charges projet (€)": amount}})
            raw = {**proof, "Charges (Dépenses)": amount, "N° de ligne comptable": str(index + 10)}
            raw["entry_ref"] = entry_from_sage(raw)["ref"]
            proofs.append(raw)
            entries.append(entry_from_sage(raw))
        proposal.update(atlas=sources, evidence=[{"rows": proofs}], sage_total=465)
        control = snapshot(control_identity(entries[0], sage=True), [], entries, amount_field="total_sage_charges")
        records = [header, *inventories, *[{"type": "sage_inventory", "data": inventory_record(e, header["sage_exclusions"])} for e in entries],
                   proposal, {"type": "control", "data": control},
                   {"complete": 1, "inventory_count": 30, "sage_inventory_count": 30, "control_count": 1,
                    "control_statuses": {control["status"]: 1}}]
        with CaptureQueriesContext(connection) as queries:
            campaign = self.load(records)
        self.assertEqual(campaign.reviews.filter(decision__current=True, decision__state="VALIDATED").count(), 30)
        self.assertLess(sum('FROM "reconciliation_campaignsageentry"' in query["sql"] for query in queries), 15)

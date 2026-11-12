"""Scénarios de campagnes successives, pas des copies de l'implémentation."""

import copy
import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .models import Campaign, LineReview, ReviewEvent
from .review import decide, is_current, signature
from .review_import import import_bundle


def atlas(identifier="A", **changes):
    return {
        "Code projet": "P",
        "Année": 2026,
        "Id": identifier,
        "Statut BAP": "Envoyé SAGE",
        "Total charges projet (€)": "100",
        "Total charges SAGE (€)": None,
        "N° pièce SAGE": "",
        "Date comptable": None,
        "Libellé ATLAS": "Mission",
        **changes,
    }


def proposal(rows, key="group", **changes):
    return {
        "type": "proposal",
        "schema_version": 2,
        "project": "P",
        "key": key,
        "rule": "MATCH_AMOUNT",
        "match_status": "MATCHED",
        "sage_total": "100",
        "evidence": [
            {"id": "SAGE:1", "rows": [{"Numéro pièce": "D", "Date comptable": "2026-01-01"}]}
        ],
        "atlas": rows,
        **changes,
    }


class CampaignTests(TestCase):
    def test_batched_snapshots_and_project_cache(self):
        from unittest.mock import patch

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        rows = [atlas(str(n)) for n in range(5)]
        proposals = [proposal([row], key=f"group-{n}") for n, row in enumerate(rows)]
        with (
            patch("reconciliation.campaigns.BATCH_SIZE", 2),
            CaptureQueriesContext(connection) as queries,
        ):
            campaign = self.load(inventory=rows, proposals=proposals)
        self.assertEqual(campaign.reviews.count(), 5)
        project_reads = [q for q in queries if 'FROM "projects_project"' in q["sql"]]
        self.assertEqual(len(project_reads), 1)
        inserts = [q for q in queries if 'INSERT INTO "reconciliation_campaignreview"' in q["sql"]]
        self.assertEqual(len(inserts), 3)

    def test_late_failure_rolls_back_already_flushed_snapshots(self):
        from unittest.mock import patch

        from .models import CampaignReview, ReviewGroup

        rows = [atlas(str(n)) for n in range(5)]
        proposals = [proposal([row], key=f"group-{n}") for n, row in enumerate(rows)]
        # Le dernier groupe contredit l'inventaire après deux lots déjà écrits.
        proposals[-1]["atlas"] = [atlas("missing")]
        with patch("reconciliation.campaigns.BATCH_SIZE", 2), self.assertRaises(ValidationError):
            self.load(inventory=rows, proposals=proposals)
        self.assertFalse(Campaign.objects.exists())
        self.assertFalse(CampaignReview.objects.exists())
        self.assertFalse(ReviewGroup.objects.exists())

    def test_import_hash_never_loads_whole_file(self):
        from unittest.mock import patch

        with patch.object(Path, "read_bytes", side_effect=AssertionError("Full file read")):
            campaign = self.load()
        self.assertEqual(campaign.reviews.count(), 1)

    def test_atlas_context_changes_require_reexamination(self):
        """Chaque champ invalide la reprise ; null/zéro et six décimales restent distincts."""
        from reconciliation_contract.atlas_context import ATLAS_CONTEXT

        for column, field in ATLAS_CONTEXT.items():
            with self.subTest(column=column):
                row = atlas(**{column: "1.123456"})
                first = self.load(inventory=[row], proposals=[proposal([row])])
                self.validate()
                same = self.load(inventory=[row], proposals=[proposal([row])])
                self.assertEqual(same.reviews.get().comparison, "CARRIED")
                changed = atlas(**{column: "1.123457"})
                current = self.load(inventory=[changed], proposals=[proposal([changed])])
                self.assertEqual(current.reviews.get().comparison, "CHANGED")
                self.assertIn(field, current.inventory.get().differences)
                self.assertEqual(first.reviews.get().source[field], "1.123456")
                self.assertFalse(is_current(LineReview.objects.get()))
                self.assertIn(column, " ".join(current.reviews.get().reasons))
                self.validate()
                zero = atlas(**{column: "0"})
                self.load(inventory=[zero], proposals=[proposal([zero])])
                self.validate()
                absent = self.load()
                self.assertEqual(absent.reviews.get().comparison, "CHANGED")
                self.assertIsNone(getattr(LineReview.objects.get().transaction, field))

    def test_context_mismatch_or_invalid_number_rolls_back(self):
        """Les valeurs incohérentes, infinies ou trop précises ne sont jamais arrondies."""
        for value in ("NaN", "Infinity", "texte", "0.1234567"):
            row = atlas(**{"Nombre d'unités": value})
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.load(inventory=[row], proposals=[proposal([row])])
        with self.assertRaises(ValidationError):
            self.load(inventory=[atlas()], proposals=[proposal([atlas(**{"Nombre d'unités": 1})])])
        self.assertFalse(Campaign.objects.exists())

    def test_annual_campaigns_compare_only_the_same_year(self):
        first = self.load(year=2026)
        self.validate()
        older = atlas(**{"Année": 2025})
        other = proposal(
            [older],
            key="year-2025",
            evidence=[
                {"id": "S25", "rows": [{"Numéro pièce": "D25", "Date comptable": "2025-12-31"}]}
            ],
        )
        second = self.load(year=2025, inventory=[older], proposals=[other])
        self.assertIsNone(second.previous_id)
        self.assertEqual(second.inventory.count(), 1)
        current = self.load(year=2026)
        self.assertEqual(current.previous_id, first.pk)
        self.assertEqual(current.reviews.get().comparison, "CARRIED")
        self.assertEqual(current.inventory.get().change, "UNCHANGED")
        self.assertFalse(Campaign.objects.get(pk=second.pk).is_current)

    def test_annual_scope_rejects_other_years_empty_inventory_and_wrong_sage_dates(self):
        for kwargs in (
            {"year": 2025},
            {"year": 2026, "inventory": [], "proposals": []},
            {
                "year": 2026,
                "proposals": [
                    proposal([atlas()], evidence=[{"rows": [{"Date comptable": "2025-12-31"}]}])
                ],
            },
            {"year": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.load(**kwargs)
        self.assertEqual(Campaign.objects.count(), 0)

    def test_all_years_and_annual_decisions_do_not_get_mixed(self):
        original = self.load()
        self.validate()
        annual = self.load(year=2026)
        self.assertIsNone(annual.previous_id)
        self.validate(state="REJECTED")
        current = self.load()
        self.assertEqual(current.previous_id, original.pk)
        self.assertEqual(current.reviews.get().decision["state"], "VALIDATED")
        self.assertEqual(current.reviews.get().comparison, "CARRIED")
        self.assertEqual(annual.reviews.get().decision["state"], "REJECTED")

    def setUp(self):
        self.user = User.objects.create_user("reviewer")
        self.project = Project.objects.create(code="P", label="Projet")
        ProjectPortfolio.objects.create(user=self.user, project=self.project)
        self.client.force_login(self.user)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def bundle(
        self, inventory=None, proposals=None, *, scope="atlas-complet", complete=True, year=None
    ):
        inventory = [atlas()] if inventory is None else inventory
        proposals = [proposal([atlas()])] if proposals is None else proposals
        records = [
            {
                "type": "campaign",
                "schema_version": 2,
                "name": f"Campagne {Campaign.objects.count() + 1}",
                "scope": scope,
                "year": year,
                "sources": {"Atlas": "JDD.xlsx"},
            }
        ]
        records += [{"type": "inventory", "atlas": row} for row in inventory]
        records += proposals
        if complete:
            records.append({"complete": len(proposals), "inventory_count": len(inventory)})
        path = Path(self.folder.name) / "campaign.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
        return path

    def load(self, **kwargs):
        import_bundle(self.bundle(**kwargs))
        return Campaign.objects.get(is_current=True)

    def validate(self, line=None, amount="100", state="VALIDATED", **extra):
        line = line or LineReview.objects.get()
        values = {
            key: {"mode": "SET", "value": value}
            for key, value in {
                "amount": amount,
                "status": "Comptabilisé",
                "document": "D",
                "date": "2026-01-01",
            }.items()
        }
        return decide(
            line.pk,
            self.user,
            state=state,
            values=values,
            comment="Répartition contrôlée",
            expected_version=line.version,
            expected_group_version=line.group.version,
            expected_source=signature(line),
            acknowledge=True,
            **extra,
        )

    def export_rows(self, campaign):
        response = self.client.get(reverse("reconciliation:campaign-export", args=[campaign.pk]))
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        rows = list(workbook.active.values)
        workbook.close()
        return rows

    def test_report_preserves_date_author_comment_and_original_campaign(self):
        first = self.load()
        decision = self.validate()
        saved = copy.deepcopy(first.reviews.get().decision)
        for _ in range(2):
            current = self.load()
            line = LineReview.objects.get()
            self.assertTrue(is_current(line))
            self.assertEqual(line.validated_at, decision.validated_at)
            self.assertEqual(line.validation_origin_id, first.pk)
            snapshot = current.reviews.get()
            self.assertEqual(snapshot.comparison, "CARRIED")
            self.assertEqual(snapshot.decision["actor"], "reviewer")
            self.assertEqual(len(self.export_rows(current)), 2)
        self.assertEqual(first.reviews.get().decision, saved)
        self.assertEqual(ReviewEvent.objects.count(), 1)
        self.assertContains(
            self.client.get(reverse("reconciliation:review-detail", args=[line.pk])), "Reprise de"
        )

    def test_amount_change_invalidates_and_history_is_not_overwritten(self):
        first = self.load()
        self.validate()
        changed = atlas(**{"Total charges projet (€)": "120"})
        second = self.load(inventory=[changed], proposals=[proposal([changed])])
        self.assertFalse(is_current(LineReview.objects.get()))
        difference = second.inventory.get().differences["total_project_charges"]
        self.assertEqual(difference, {"before": "100.00", "after": "120.00"})
        self.assertEqual(len(self.export_rows(second)), 1)
        self.assertEqual(len(self.export_rows(first)), 2)
        self.assertEqual(first.reviews.get().source["total_project_charges"], "100.00")
        self.assertEqual(second.reviews.get().source["total_project_charges"], "120.00")
        self.validate(amount="120")
        self.assertEqual(LineReview.objects.get().validation_origin_id, second.pk)
        self.assertEqual(first.reviews.get().decision["effective"]["amount"], "100")

    def test_sage_amount_and_status_changes_are_visible_outside_matching(self):
        self.load()
        self.validate()
        changed = atlas(
            **{
                "Statut BAP": "Comptabilisé",
                "Total charges SAGE (€)": "100",
                "N° pièce SAGE": "D",
                "Date comptable": "2026-01-01",
            }
        )
        current = self.load(inventory=[changed], proposals=[])
        self.assertEqual(current.inventory.get().change, "CHANGED")
        self.assertIn("total_sage_charges", current.inventory.get().differences)
        self.assertEqual(current.reviews.count(), 0)
        self.assertEqual(len(self.export_rows(current)), 1)
        self.assertEqual(
            self.client.get(
                reverse("reconciliation:review-detail", args=[LineReview.objects.get().pk])
            ).status_code,
            404,
        )
        with self.assertRaises(ValidationError):
            self.validate()

    def test_absence_new_line_and_reappearance(self):
        first = self.load()
        self.validate()
        current = self.load(inventory=[atlas("B")], proposals=[proposal([atlas("B")], key="other")])
        self.assertEqual(current.inventory.get(source_id="A").change, "ABSENT")
        self.assertFalse(current.inventory.get(source_id="A").present)
        self.assertEqual(current.inventory.get(source_id="B").change, "NEW")
        self.assertEqual(first.reviews.count(), 1)
        returned = self.load()
        self.assertEqual(returned.inventory.get(source_id="A").change, "RETURNED")
        self.assertFalse(is_current(LineReview.objects.get(transaction__source_id="A")))

    def test_group_member_change_invalidates_unchanged_neighbour(self):
        a, b = atlas(), atlas("B", **{"Total charges projet (€)": "0"})
        self.load(inventory=[a, b], proposals=[proposal([a, b])])
        self.validate(LineReview.objects.get(transaction__source_id="A"))
        b["Total charges projet (€)"] = "10"
        current = self.load(inventory=[a, b], proposals=[proposal([a, b])])
        line = LineReview.objects.get(transaction__source_id="A")
        self.assertFalse(is_current(line))
        self.assertEqual(current.reviews.get(line=line).comparison, "CHANGED")

    def test_reordered_evidence_and_candidate_ids_do_not_invalidate(self):
        self.load()
        self.validate()
        data = proposal([atlas()])
        data["evidence"][0]["id"] = "SAGE:19999"
        current = self.load(proposals=[data])
        self.assertEqual(current.reviews.get().comparison, "CARRIED")

    def test_failed_import_rolls_back_entire_campaign_and_sources(self):
        first = self.load()
        self.validate()
        changed = atlas(**{"Total charges projet (€)": "200"})
        with self.assertRaises(ValidationError):
            self.load(inventory=[changed], proposals=[proposal([changed])], complete=False)
        self.assertEqual(Campaign.objects.get(is_current=True), first)
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertEqual(str(LineReview.objects.get().transaction.total_project_charges), "100.00")

    def test_reject_duplicate_inventory_wrong_scope_missing_or_contradictory_proposals(self):
        self.load()
        for kwargs in (
            {"inventory": [atlas(), atlas()]},
            {"scope": "autre"},
            {"proposals": []},
            {"inventory": []},
            {"proposals": [proposal([atlas(**{"Total charges projet (€)": "9"})])]},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.load(**kwargs)
        self.assertEqual(Campaign.objects.count(), 1)

    def test_inventory_batches_and_historical_permissions(self):
        inventory = [atlas(str(i), **{"Statut BAP": "Comptabilisé"}) for i in range(510)]
        current = self.load(inventory=inventory, proposals=[])
        self.assertEqual(current.inventory.count(), 510)
        self.assertContains(
            self.client.get(
                reverse("reconciliation:campaign", args=[current.pk]), {"tab": "inventory"}
            ),
            "510",
        )
        other = User.objects.create_user("other")
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("reconciliation:campaign", args=[current.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.get(
                reverse("reconciliation:campaign-export", args=[current.pk])
            ).status_code,
            404,
        )

    def test_pages_archive_and_frozen_decisions(self):
        first = self.load()
        self.validate()
        self.load()
        snapshot = first.reviews.get()
        self.assertEqual(
            self.client.post(
                reverse("reconciliation:campaign-review", args=[snapshot.pk]), {}
            ).status_code,
            405,
        )
        for name, args in (
            ("campaigns", []),
            ("campaign", [first.pk]),
            ("campaign-review", [snapshot.pk]),
        ):
            self.assertEqual(
                self.client.get(reverse("reconciliation:" + name, args=args)).status_code, 200
            )
        self.validate(state="REJECTED")
        self.assertEqual(first.reviews.get().decision["state"], "VALIDATED")
        self.assertEqual(
            Campaign.objects.get(is_current=True).reviews.get().decision["state"], "REJECTED"
        )

    def test_existing_legacy_validation_is_archived_and_carried(self):
        # Une proposition v1 contient les mêmes sources ; l'inventaire reste inconnu.
        path = Path(self.folder.name) / "old.jsonl"
        data = proposal([atlas()])
        data["schema_version"] = 1
        data.pop("type")
        path.write_text(json.dumps(data) + '\n{"complete": 1}\n', encoding="utf-8")
        import_bundle(path)
        self.validate()
        current = self.load()
        self.assertFalse(current.previous.inventory_complete)
        self.assertEqual(current.reviews.get().comparison, "CARRIED")
        self.assertEqual(current.previous.reviews.get().decision["state"], "VALIDATED")

    def test_form_opened_before_identical_import_is_rejected(self):
        self.load()
        line = LineReview.objects.select_related("group", "transaction__project").get()
        self.load()
        with self.assertRaises(ValidationError):
            self.validate(line)

    def test_absence_remains_visible_until_return_and_never_exports(self):
        self.load()
        self.validate()
        self.load(inventory=[], proposals=[])
        third = self.load(inventory=[], proposals=[])
        self.assertEqual(third.inventory.get(source_id="A").change, "ABSENT")
        self.assertEqual(len(self.export_rows(third)), 1)

    def test_added_member_changes_context_without_losing_past_allocation(self):
        first = self.load()
        self.validate()
        current = self.load(
            inventory=[atlas(), atlas("B")],
            proposals=[proposal([atlas(), atlas("B")], key="new-group", sage_total="200")],
        )
        line = LineReview.objects.get(transaction__source_id="A")
        self.assertFalse(is_current(line))
        self.assertEqual(current.reviews.get(line=line).comparison, "CHANGED")
        self.assertEqual(first.reviews.get().decision["effective"]["amount"], "100")

    def test_headerless_v2_and_legacy_after_campaign_are_rejected(self):
        path = Path(self.folder.name) / "headerless.jsonl"
        data = proposal([atlas()])
        path.write_text(json.dumps(data) + '\n{"complete": 1}\n', encoding="utf-8")
        with self.assertRaises(ValidationError):
            import_bundle(path)
        self.load()
        data["schema_version"] = 1
        path.write_text(json.dumps(data) + '\n{"complete": 1}\n', encoding="utf-8")
        with self.assertRaises(ValidationError):
            import_bundle(path)

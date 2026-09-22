"""Décisions par ligne, dérogations, concurrence et conservation."""

import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .models import LineReview, ReconciliationTransaction, ReviewGroup
from .review import decide, effective, is_current, signature
from .review_import import import_bundle


class ReviewTests(TestCase):
    def test_status_is_a_choice_and_arbitrary_values_are_rejected(self):
        response = self.client.get(reverse("reconciliation:review-detail", args=[self.line.pk]))
        form = response.context["form"]
        self.assertEqual(
            list(form.fields["status"].choices),
            [
                ("", "Choisir un statut"),
                ("Envoyé SAGE", "Envoyé SAGE"),
                ("Comptabilisé", "Comptabilisé"),
            ],
        )
        self.values["status"]["value"] = "AUTRE"
        with self.assertRaises(ValidationError):
            self.save(state="DRAFT")
        with self.assertRaises(ValidationError):
            self.save()

    def setUp(self):
        self.user = User.objects.create_user("reviewer", password="test")
        self.other = User.objects.create_user("other", password="test")
        self.project = Project.objects.create(code="P", label="Projet")
        ProjectPortfolio.objects.create(user=self.user, project=self.project)
        self.group = ReviewGroup.objects.create(
            project=self.project,
            key="g",
            rule="MATCH_AMOUNT",
            match_status="MATCHED",
            sage_total=Decimal("100"),
            evidence=[
                {"id": "S1", "rows": [{"Numéro pièce": "D", "Date comptable": "2026-01-01"}]}
            ],
        )
        self.item = ReconciliationTransaction.objects.create(
            project=self.project,
            business_key="P::2026::A",
            source_id="A",
            fiscal_year=2026,
            reference="A",
            label="Test",
            atlas_label="Test",
            bap_status="Envoyé SAGE",
            total_project_charges=Decimal("100"),
        )
        self.line = LineReview.objects.create(transaction=self.item, group=self.group)
        self.values = {
            k: {"mode": "SET", "value": v}
            for k, v in {
                "status": "Comptabilisé",
                "amount": "100",
                "document": "D",
                "date": "2026-01-01",
            }.items()
        }
        self.client.force_login(self.user)

    def save(self, **kwargs):
        self.line.refresh_from_db()
        options = dict(
            state="VALIDATED",
            values=self.values,
            comment="",
            expected_version=self.line.version,
            expected_group_version=self.line.group.version,
            expected_source=signature(self.line),
        )
        options.update(kwargs)
        return decide(self.line.pk, self.user, **options)

    def test_validation_history_and_export(self):
        line = self.save()
        self.assertEqual(line.events.count(), 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.bap_status, "Envoyé SAGE")
        response = self.client.get(reverse("reconciliation:conservation-export"))
        workbook = load_workbook(BytesIO(response.content))
        rows = list(workbook.active.values)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][3:6], ("Comptabilisé", 100, "D"))
        workbook.close()

    def test_draft_after_validation_is_no_longer_exported(self):
        self.save()
        self.save(state="DRAFT")
        response = self.client.get(reverse("reconciliation:conservation-export"))
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(len(list(workbook.active.values)), 1)
        workbook.close()

    def test_deviation_requires_explicit_comment_and_acknowledgment(self):
        self.values["amount"]["value"] = "90"
        with self.assertRaises(ValidationError):
            self.save()
        line = self.save(comment="Répartition métier", acknowledge=True)
        self.assertTrue(line.events.first().snapshot["derogation"])

    def test_refusal_requires_comment(self):
        with self.assertRaises(ValidationError):
            self.save(state="REJECTED")
        self.assertEqual(self.save(state="REJECTED", comment="Mauvaise pièce").state, "REJECTED")

    def test_clear_and_zero_are_distinct(self):
        self.values["amount"] = {"mode": "CLEAR", "value": None}
        self.assertIsNone(effective(self.save(state="DRAFT"))["amount"])
        self.values["amount"] = {"mode": "SET", "value": "0"}
        self.assertEqual(effective(self.save(state="DRAFT"))["amount"], Decimal("0"))

    def test_changed_sources_invalidate_export_and_stale_form(self):
        before = signature(self.line)
        line = self.save()
        self.item.total_project_charges = 200
        self.item.save()
        line.refresh_from_db()
        self.assertFalse(is_current(line))
        with self.assertRaises(ValidationError):
            self.save(expected_source=before)
        response = self.client.get(reverse("reconciliation:conservation-export"))
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(len(list(workbook.active.values)), 1)
        workbook.close()

    def test_group_version_blocks_concurrent_edits(self):
        self.save(state="DRAFT")
        with self.assertRaises(ValidationError):
            self.save(expected_group_version=0)

    def test_portfolio_and_pages(self):
        self.assertContains(
            self.client.get(reverse("reconciliation:review-detail", args=[self.line.pk])),
            "Correspondance SAGE",
        )
        self.assertNotContains(self.client.get(reverse("reconciliation:reviews")), "Brouillon")
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(
                reverse("reconciliation:review-detail", args=[self.line.pk])
            ).status_code,
            404,
        )
        with self.assertRaises(PermissionDenied):
            decide(
                self.line.pk,
                self.other,
                state="DRAFT",
                values=self.values,
                comment="",
                expected_version=0,
                expected_group_version=0,
                expected_source=signature(self.line),
            )

    def test_import_idempotency_and_transaction_rollback(self):
        payload = {
            "schema_version": 1,
            "key": "g",
            "project": "P",
            "rule": "MATCH_AMOUNT",
            "match_status": "MATCHED",
            "sage_total": "100",
            "evidence": self.group.evidence,
            "atlas": [
                {
                    "Id": "A",
                    "Code projet": "P",
                    "Année": 2026,
                    "Statut BAP": "Envoyé SAGE",
                    "Total charges projet (€)": "100",
                    "Libellé ATLAS": "Test",
                }
            ],
        }
        with TemporaryDirectory() as folder:
            path = Path(folder) / "bundle.jsonl"
            path.write_text(json.dumps(payload) + '\n{"complete": 1}\n', encoding="utf-8")
            import_bundle(path)
            self.save()
            import_bundle(path)
            self.line.refresh_from_db()
            self.assertEqual(self.line.state, "VALIDATED")
            self.assertTrue(is_current(self.line))
            payload["atlas"][0]["Total charges projet (€)"] = "200"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaises(ValidationError):
                import_bundle(path)
            self.item.refresh_from_db()
            self.assertEqual(self.item.total_project_charges, Decimal("100"))

    def test_multiline_allocation_and_individual_decisions(self):
        second_item = ReconciliationTransaction.objects.create(
            project=self.project,
            business_key="P::2026::B",
            source_id="B",
            fiscal_year=2026,
            reference="B",
            label="Autre ligne",
            total_project_charges=Decimal("40"),
        )
        other = LineReview.objects.create(transaction=second_item, group=self.group)
        values = {k: dict(v) for k, v in self.values.items()}
        values["amount"]["value"] = "40"
        decide(
            other.pk,
            self.user,
            state="DRAFT",
            values=values,
            comment="Répartition",
            expected_version=0,
            expected_group_version=0,
            expected_source=signature(other),
        )
        self.values["amount"]["value"] = "60"
        validated = self.save()
        self.assertEqual(validated.state, "VALIDATED")
        other.refresh_from_db()
        self.assertEqual(other.state, "DRAFT")
        self.assertEqual(validated.events.first().snapshot["warnings"], [])

    def test_http_validation_and_explicit_clear_stays_draft(self):
        data = {
            "action": "VALIDATED",
            "version": 0,
            "group_version": 0,
            "source": signature(self.line),
            "comment": "Contrôlé",
        }
        for name, entry in self.values.items():
            data[name + "_mode"] = entry["mode"]
            data[name] = entry["value"]
        response = self.client.post(
            reverse("reconciliation:review-detail", args=[self.line.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.line.refresh_from_db()
        self.assertEqual(self.line.state, "VALIDATED")

    def test_dashboard_tracks_decisions_and_changed_sources(self):
        url = reverse("dashboard:index")
        self.assertEqual(self.client.get(url).context["counts"]["draft"], 1)
        self.save()
        self.assertEqual(self.client.get(url).context["counts"]["validated"], 1)
        self.item.atlas_label = "Source modifiée"
        self.item.save()
        response = self.client.get(url)
        self.assertEqual(response.context["counts"]["stale"], 1)
        self.assertEqual(response.context["counts"]["validated"], 0)
        self.assertEqual(self.client.get(url, {"project": "INACCESSIBLE"}).status_code, 404)

    def test_only_review_workflow_is_accessible(self):
        response = self.client.get(reverse("reconciliation:reviews"))
        self.assertNotContains(response, "Ancien parcours")
        self.assertNotContains(response, 'href="/imports/"')
        self.assertRedirects(self.client.get("/rapprochements/"), reverse("reconciliation:reviews"))
        for url in ("/rapprochements/export/", "/rapprochements/1/"):
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {}).status_code, 404)

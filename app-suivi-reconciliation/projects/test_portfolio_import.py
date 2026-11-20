"""Contrôle d'accès, atomicité et validation des projets dans l'inventaire."""

from io import BytesIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from accounts.models import User
from reconciliation.models import Campaign, CampaignInventory

from .models import PortfolioImport, Project, ProjectPortfolio
from .portfolio_import import import_portfolios, project_from_inventory


class PortfolioImportTests(TestCase):
    def test_duplicate_pairs_are_counted(self):
        report = import_portfolios(self.workbook([("marie", "P1"), (" marie ", " p1 ")]), self.admin)
        self.assertEqual((report.created_count, report.duplicate_count, report.analyzed_count), (1, 1, 2))
        self.assertEqual(report.anomalies[0]["line"], 3)

    def test_same_project_for_different_users_is_allowed(self):
        """L'unicité porte sur le couple, pas sur ses deux éléments séparément."""
        report = import_portfolios(self.workbook([("marie", "P1"), ("admin", "P1")]), self.admin)
        self.assertEqual(report.created_count, 2)

    def test_multicode_cells_and_old_headers_are_rejected(self):
        """Les listes de codes et la maquette plurielle ne sont plus acceptées."""
        for separator in (";", ",", "\n", "\r"):
            report = import_portfolios(self.workbook([("marie", f"P1{separator}P2")]), self.admin)
            self.assertEqual(report.status, "rejected")
            self.assertIn("un seul code projet", report.anomalies[0]["reason"])
        with self.assertRaisesRegex(ValidationError, "En-têtes attendus"):
            import_portfolios(
                self.workbook([("marie", "P1")], headers=("username", "codes projets")),
                self.admin,
            )

    def setUp(self):
        self.admin = User.objects.create_user("admin", is_staff=True)
        self.reader = User.objects.create_user("marie")
        self.campaign = Campaign.objects.create(
            name="2026", scope="atlas-complet", fiscal_year=2026, is_current=True
        )
        for code in ("P1", "P2"):
            CampaignInventory.objects.create(
                campaign=self.campaign,
                business_key=code + "::2026::A",
                project_code=code,
                source_id="A",
                fiscal_year=2026,
            )
        self.client.force_login(self.admin)

    def workbook(self, rows, headers=("username", "code projet")):
        book = Workbook()
        sheet = book.active
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        content = BytesIO()
        book.save(content)
        book.close()
        return SimpleUploadedFile("portefeuilles.xlsx", content.getvalue())

    def test_additive_single_project_idempotent_and_audited(self):
        report = import_portfolios(self.workbook([("marie", "p1"), ("marie", "P2")]), self.admin)
        self.assertEqual(report.created_count, 2)
        self.assertEqual(report.existing_count, 0)
        self.assertEqual(ProjectPortfolio.objects.filter(user=self.reader).count(), 2)
        report = import_portfolios(self.workbook([("marie", "P1")]), self.admin)
        self.assertEqual(report.existing_count, 1)
        self.assertEqual(ProjectPortfolio.objects.count(), 2)
        self.assertEqual(PortfolioImport.objects.count(), 2)

    def test_unknown_lines_allow_valid_assignments(self):
        report = import_portfolios(self.workbook([("marie", "P1"), ("inconnu", "P2"), ("marie", "ABSENT")]), self.admin)
        self.assertEqual((report.created_count, report.rejected_count, report.status), (1, 2, "partial"))
        self.assertEqual(ProjectPortfolio.objects.count(), 1)

    def test_admin_only_template_download_and_error_page(self):
        self.assertEqual(self.client.get(reverse("projects:portfolio-import")).status_code, 200)
        response = self.client.get(reverse("projects:portfolio-template"))
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(list(book.active.values), [("username", "code projet")])
        book.close()
        response = self.client.post(
            reverse("projects:portfolio-import"), {"workbook": self.workbook([("marie", "P1")])}
        )
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.reader)
        for name in ("portfolio-import", "portfolio-template"):
            self.assertEqual(self.client.get(reverse("projects:" + name)).status_code, 403)
        with self.assertRaises(PermissionDenied):
            import_portfolios(self.workbook([("marie", "P2")]), self.reader)

    def test_admin_addition_checks_inventory_not_just_project_table(self):
        """L'ajout réservé à l'administrateur exige toujours un projet attesté par l'inventaire."""
        Project.objects.create(code="OLD", label="Ancien")
        response = self.client.post(reverse("projects:portfolio"), {"project_code": "OLD"})
        self.assertContains(response, "introuvable")
        self.client.post(reverse("projects:portfolio"), {"project_code": "p1"})
        self.assertEqual(ProjectPortfolio.objects.get().project.code, "P1")

    def test_latest_inventory_and_different_years(self):
        newer = Campaign.objects.create(
            name="2026 suivant", scope="atlas-complet", fiscal_year=2026
        )
        CampaignInventory.objects.create(
            campaign=newer,
            business_key="P1::2026::A",
            project_code="P1",
            source_id="A",
            fiscal_year=2026,
            present=False,
        )
        with self.assertRaises(ValidationError):
            project_from_inventory("P1")
        previous_year = Campaign.objects.create(
            name="2025", scope="atlas-complet", fiscal_year=2025
        )
        CampaignInventory.objects.create(
            campaign=previous_year,
            business_key="P1::2025::A",
            project_code="P1",
            source_id="A",
            fiscal_year=2025,
        )
        self.assertEqual(project_from_inventory("P1").code, "P1")

    def test_annual_inventory_supersedes_same_year_in_older_full_inventory(self):
        self.campaign.fiscal_year = None
        self.campaign.save()
        yearly = Campaign.objects.create(
            name="Nouvel inventaire 2026", scope="atlas-complet", fiscal_year=2026
        )
        CampaignInventory.objects.create(
            campaign=yearly,
            business_key="P1::2026::A",
            project_code="P1",
            source_id="A",
            fiscal_year=2026,
            present=False,
        )
        with self.assertRaises(ValidationError):
            project_from_inventory("P1")

    def test_invalid_workbooks_inactive_accounts_and_projects(self):
        User.objects.create_user("inactive", is_active=False)
        Project.objects.create(code="P2", label="Désactivé", is_active=False)
        for rows in (
            [("marie", "=1+1")],
            [("marie", None)],
            [("inactive", "P1")],
            [("marie", "P2")],
        ):
            with self.subTest(rows=rows):
                report = import_portfolios(self.workbook(rows), self.admin)
                self.assertEqual(report.status, "rejected")
                self.assertEqual(report.created_count, 0)
        with self.assertRaises(ValidationError):
            import_portfolios(
                self.workbook([("marie", "P1")], headers=("incorrect", "code projet")), self.admin
            )
        with self.assertRaises(ValidationError):
            import_portfolios(SimpleUploadedFile("bad.xlsx", b"not excel"), self.admin)


    def test_blank_lines_and_export_persisted(self):
        report = import_portfolios(self.workbook([("marie", "P1"), (None, None), ("=BAD", "P1"), ("unknown", "P1")]), self.admin)
        self.assertEqual(report.analyzed_count, 3)
        response = self.client.get(reverse("projects:portfolio-import"), {"report": report.pk})
        self.assertContains(response, "Import terminé avec avertissements")
        response = self.client.get(reverse("projects:portfolio-rejections", args=[report.pk]))
        book = load_workbook(BytesIO(response.content))
        rows = list(book.active.values)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][1], "=BAD")
        self.assertEqual(book.active["B2"].data_type, "s")
        book.close()
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("projects:portfolio-rejections", args=[report.pk])).status_code, 403)

    def test_technical_error_rolls_back_projects_and_assignments(self):
        from unittest.mock import patch
        from django.db import DatabaseError
        with patch.object(PortfolioImport.objects, "create", side_effect=DatabaseError("failure")):
            with self.assertRaises(DatabaseError):
                import_portfolios(self.workbook([("marie", "P1")]), self.admin)
        self.assertFalse(Project.objects.exists())
        self.assertFalse(ProjectPortfolio.objects.exists())
        self.assertFalse(PortfolioImport.objects.exists())

    def test_empty_file_is_global_error(self):
        with self.assertRaises(ValidationError):
            import_portfolios(self.workbook([]), self.admin)


    def test_bulk_insert_failure_rolls_back(self):
        from unittest.mock import patch
        from django.db import DatabaseError
        with patch.object(ProjectPortfolio.objects, "bulk_create", side_effect=DatabaseError("failure")):
            response = self.client.post(reverse("projects:portfolio-import"), {
                "workbook": self.workbook([("marie", "P1")])})
        self.assertContains(response, "Erreur technique")
        self.assertFalse(Project.objects.exists())
        self.assertFalse(PortfolioImport.objects.exists())

    def test_rejected_counters_and_persisted_reasons(self):
        User.objects.create_user("inactive", is_active=False)
        report = import_portfolios(self.workbook([
            ("unknown", "P1"), ("inactive", "P1"), ("marie", "ABSENT"), ("marie", "")]), self.admin)
        report.refresh_from_db()
        self.assertEqual((report.status, report.analyzed_count, report.rejected_count), ("rejected", 4, 4))
        self.assertEqual(report.created_count + report.existing_count, 0)
        self.assertEqual(len(report.anomalies), 4)

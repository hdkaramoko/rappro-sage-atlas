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

    def workbook(self, rows, headers=("username", "codes projets")):
        book = Workbook()
        sheet = book.active
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        content = BytesIO()
        book.save(content)
        book.close()
        return SimpleUploadedFile("portefeuilles.xlsx", content.getvalue())

    def test_additive_multicode_idempotent_and_audited(self):
        report = import_portfolios(
            self.workbook([("marie", "p1; P2\nP1"), ("marie", "P2")]), self.admin
        )
        self.assertEqual(report.created_count, 2)
        self.assertEqual(report.existing_count, 0)
        self.assertEqual(ProjectPortfolio.objects.filter(user=self.reader).count(), 2)
        report = import_portfolios(self.workbook([("marie", "P1")]), self.admin)
        self.assertEqual(report.existing_count, 1)
        self.assertEqual(ProjectPortfolio.objects.count(), 2)
        self.assertEqual(PortfolioImport.objects.count(), 2)

    def test_unknown_user_or_project_rolls_back_every_assignment(self):
        for bad in (("inconnu", "P2"), ("marie", "ABSENT")):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                import_portfolios(self.workbook([("marie", "P1"), bad]), self.admin)
            self.assertEqual(ProjectPortfolio.objects.count(), 0)
            self.assertEqual(Project.objects.count(), 0)
        self.assertEqual(PortfolioImport.objects.count(), 0)

    def test_admin_only_template_download_and_error_page(self):
        self.assertEqual(self.client.get(reverse("projects:portfolio-import")).status_code, 200)
        response = self.client.get(reverse("projects:portfolio-template"))
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(list(book.active.values), [("username", "codes projets")])
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

    def test_self_service_also_checks_inventory_not_just_project_table(self):
        Project.objects.create(code="OLD", label="Ancien")
        self.client.force_login(self.reader)
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
            [],
            [("marie", "=1+1")],
            [("marie", None)],
            [("inactive", "P1")],
            [("marie", "P2")],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                import_portfolios(self.workbook(rows), self.admin)
        with self.assertRaises(ValidationError):
            import_portfolios(
                self.workbook([("marie", "P1")], headers=("incorrect", "codes projets")), self.admin
            )
        with self.assertRaises(ValidationError):
            import_portfolios(SimpleUploadedFile("bad.xlsx", b"not excel"), self.admin)

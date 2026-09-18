from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .models import ReconciliationTransaction
from .services import CorrectionConflictError, apply_correction, cancel_correction


class ReconciliationRulesTests(TestCase):
    """Vérifie les règles centrales et l'isolation géographique."""

    def setUp(self) -> None:
        """Prépare deux utilisateurs possédant des portefeuilles disjoints."""
        self.rwanda = User.objects.create_user("rwanda", password="test", geography="Rwanda")
        self.senegal = User.objects.create_user("senegal", password="test", geography="Sénégal")
        self.project_rw = Project.objects.create(code="RW-01", label="Rwanda")
        self.project_sn = Project.objects.create(code="SN-01", label="Sénégal")
        ProjectPortfolio.objects.create(user=self.rwanda, project=self.project_rw)
        ProjectPortfolio.objects.create(user=self.senegal, project=self.project_sn)
        self.item = ReconciliationTransaction.objects.create(
            project=self.project_rw,
            business_key="RW-01::A",
            reference="A",
            label="Test",
            transaction_date=date.today(),
            atlas_amount=Decimal("100"),
            sage_amount=Decimal("90"),
            atlas_status_source="ENVOYE",
            sage_status="COMPTABILISE",
            source_id="A",
            source_project_label="Rwanda",
            fiscal_year=2026,
            atlas_label="Test",
            bap_status="ENVOYE",
            accounting_date=date.today(),
            total_project_charges=Decimal("100"),
            total_sage_charges=Decimal("90"),
            suggestion_bap_status="COMPTABILISE",
            suggestion_sage_document_number="PI-1",
            suggestion_accounting_date=date.today(),
            suggestion_total_sage_charges=Decimal("90"),
        )

    def test_correction_effective_and_history(self) -> None:
        """Une correction devient effective sans altérer la valeur Atlas."""
        apply_correction(self.item, "COMPTABILISE", "Vérifié", self.rwanda)
        self.item.refresh_from_db()
        self.assertEqual(self.item.atlas_status_source, "ENVOYE")
        self.assertEqual(self.item.effective_status, "COMPTABILISE")
        self.assertEqual(self.item.correction_history.count(), 1)
        history = self.item.correction_history.get()
        self.assertEqual(history.event_type, "CREATION")
        self.assertEqual(history.new_snapshot["bap_status"], "COMPTABILISE")

    def test_visibility_is_limited_to_portfolio(self) -> None:
        """Un compte ne voit aucune transaction d'un portefeuille tiers."""
        self.assertEqual(ReconciliationTransaction.objects.visible_for(self.rwanda).count(), 1)
        self.assertEqual(ReconciliationTransaction.objects.visible_for(self.senegal).count(), 0)
        self.client.login(username="senegal", password="test")
        self.assertEqual(self.client.get(f"/rapprochements/{self.item.pk}/").status_code, 404)

    def test_anonymous_user_is_redirected_to_configured_login(self) -> None:
        """Un visiteur anonyme est redirigé vers la page de connexion existante."""
        self.client.logout()
        response = self.client.get("/")
        self.assertRedirects(response, "/connexion/?next=/")

    def test_login_page_uses_the_shared_modern_layout(self) -> None:
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'class="login-page"')
        self.assertContains(response, "Vos données comptables")
        self.assertContains(response, "Se connecter")

    def test_complete_correction_modification_and_cancellation(self) -> None:
        """Les quatre valeurs évoluent ensemble et toutes les versions restent auditées."""
        corrected = apply_correction(
            self.item,
            "VALIDE",
            "Première validation",
            self.rwanda,
            "PI-2",
            date(2026, 2, 1),
            Decimal("100.00"),
            expected_version=0,
        )
        modified = apply_correction(
            corrected,
            "COMPTABILISE",
            "Ajustement",
            self.rwanda,
            "PI-3",
            date(2026, 2, 2),
            Decimal("101.00"),
            expected_version=1,
        )
        self.assertEqual(modified.correction_history.count(), 2)
        self.assertEqual(modified.correction_history.first().event_type, "MODIFICATION")
        cancel_correction(modified, self.rwanda, expected_version=2)
        modified.refresh_from_db()
        self.assertFalse(modified.correction_active)
        self.assertEqual(modified.correction_history.first().event_type, "ANNULATION")
        self.assertEqual(modified.effective_bap_status, "COMPTABILISE")

    def test_stale_correction_is_rejected(self) -> None:
        """Une version obsolète ne peut pas écraser silencieusement une correction."""
        apply_correction(self.item, "VALIDE", "", self.rwanda, expected_version=0)
        with self.assertRaises(CorrectionConflictError):
            apply_correction(self.item, "ANCIEN", "", self.rwanda, expected_version=0)

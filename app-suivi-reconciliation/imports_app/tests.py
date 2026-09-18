from datetime import date
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook, load_workbook

from accounts.models import User
from reconciliation.models import ReconciliationTransaction
from reconciliation.services import apply_correction

from .services import EXPECTED_COLUMNS, LEGACY_COLUMNS, ImportValidationError, import_xlsx


class ImportServiceTests(TestCase):
    """Vérifie l'idempotence et la persistance des corrections."""

    def setUp(self) -> None:
        """Crée le compte technique utilisé par les imports."""
        self.user = User.objects.create_user("admin", is_staff=True)

    def _file(self, amount=100, suggestion=100, headers=EXPECTED_COLUMNS, name="test.xlsx"):
        """Construit en mémoire un fichier Excel adapté au scénario."""
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        if headers == EXPECTED_COLUMNS:
            sheet.append(
                (
                    "REF-1",
                    "RW-01",
                    "Projet Rwanda",
                    2026,
                    "Activité",
                    "LB-1",
                    "Fonctionnement",
                    "Dépense",
                    "Service",
                    "T-1",
                    "Tiers",
                    "BAP-1",
                    "ENVOYE",
                    "Kigali",
                    "Virement",
                    date(2026, 1, 1),
                    "PI-1",
                    amount,
                    100,
                    "COMPTABILISE",
                    "PI-1",
                    date(2026, 1, 2),
                    str(suggestion).replace(".", ","),
                )
            )
        elif headers == LEGACY_COLUMNS:
            sheet.append(
                (
                    "RW-01",
                    "REF-1",
                    "Dépense",
                    date(2026, 1, 1),
                    amount,
                    100,
                    "ENVOYE",
                    "COMPTABILISE",
                )
            )
        stream = BytesIO()
        workbook.save(stream)
        return SimpleUploadedFile(name, stream.getvalue())

    def test_create_update_and_duplicate_file(self) -> None:
        """Un premier fichier crée, un nouveau met à jour et un doublon est ignoré."""
        original = self._file()
        content = original.read()
        original.seek(0)
        first = import_xlsx(original, self.user)
        self.assertEqual(first.batch.created_rows, 1)
        duplicate = import_xlsx(SimpleUploadedFile("test.xlsx", content), self.user)
        self.assertTrue(duplicate.duplicate)
        second = import_xlsx(self._file(amount=120, name="update.xlsx"), self.user)
        self.assertEqual(second.batch.updated_rows, 1)
        self.assertEqual(ReconciliationTransaction.objects.count(), 1)

    def test_reimport_keeps_business_correction(self) -> None:
        """Une nouvelle valeur source ne supprime jamais une correction existante."""
        import_xlsx(self._file(), self.user)
        item = ReconciliationTransaction.objects.get()
        apply_correction(item, "COMPTABILISE", "Validé", self.user)
        import_xlsx(self._file(amount=120, name="update.xlsx"), self.user)
        item.refresh_from_db()
        self.assertTrue(item.correction_active)
        self.assertEqual(item.correction_bap_status, "COMPTABILISE")

    def test_reimport_updates_suggestion_without_touching_history(self) -> None:
        """Une suggestion modifiée est actualisée tandis que l'audit reste intact."""
        import_xlsx(self._file(), self.user)
        item = ReconciliationTransaction.objects.get()
        apply_correction(item, "VALIDE", "Contrôle", self.user)
        import_xlsx(self._file(suggestion="125.50", name="suggestion.xlsx"), self.user)
        item.refresh_from_db()
        self.assertEqual(item.suggestion_total_sage_charges, Decimal("125.50"))
        self.assertTrue(item.correction_active)
        self.assertEqual(item.correction_history.count(), 1)

    def test_legacy_file_remains_supported(self) -> None:
        """L'ancien format explicite reste importable pendant la transition."""
        result = import_xlsx(self._file(headers=LEGACY_COLUMNS), self.user)
        item = ReconciliationTransaction.objects.get()
        self.assertEqual(result.batch.created_rows, 1)
        self.assertEqual(item.source_id, "REF-1")
        self.assertEqual(item.total_project_charges, 100)

    def test_duplicate_header_and_source_id_are_rejected(self) -> None:
        """Les ambiguïtés d'en-tête et doublons métier bloquent l'import atomique."""
        headers = list(EXPECTED_COLUMNS)
        headers[-1] = headers[0]
        with self.assertRaises(ImportValidationError):
            import_xlsx(self._file(headers=tuple(headers)), self.user)

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(EXPECTED_COLUMNS)
        valid = list(
            load_workbook(BytesIO(self._file().read())).active.iter_rows(values_only=True)
        )[1]
        sheet.append(valid)
        sheet.append(valid)
        stream = BytesIO()
        workbook.save(stream)
        duplicate = SimpleUploadedFile("duplicate.xlsx", stream.getvalue())
        with self.assertRaises(ImportValidationError):
            import_xlsx(duplicate, self.user)
        self.assertFalse(ReconciliationTransaction.objects.exists())

    def test_invalid_date_and_amount_are_explicit(self) -> None:
        """Une date ou un montant invalide indique la ligne et la colonne."""
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(EXPECTED_COLUMNS)
        values = list(
            load_workbook(BytesIO(self._file().read())).active.iter_rows(values_only=True)
        )[1]
        values = list(values)
        values[15] = "31/12/2026"
        sheet.append(values)
        stream = BytesIO()
        workbook.save(stream)
        with self.assertRaisesRegex(ImportValidationError, "Ligne 2.*Date comptable"):
            import_xlsx(SimpleUploadedFile("invalid.xlsx", stream.getvalue()), self.user)

    def test_missing_columns_are_rejected(self) -> None:
        """Un fichier incomplet produit une erreur explicite."""
        with self.assertRaises(ImportValidationError):
            import_xlsx(self._file(headers=("code_projet",)), self.user)

"""Intégration lot 1 : vrai export CLI, import atomique et contrôle consolidé."""

import copy
import hashlib
import json
import subprocess
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from reconciliation_contract import digest
from reconciliation_contract.sage_inventory import exclusion_policy, inventory_record, ods_scope

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .global_control import campaign_controls
from .models import Campaign, CampaignSageEntry, LineReview
from .multiple_review import candidates_for
from .review import decide, signature
from .review_import import import_bundle


def sign_records(records: list[dict]) -> list[dict]:
    """Signe une variante de fixture volontairement cohérente avant son import.

    Les tests de corruption omettent cet appel ; cette fonction ne corrige
    jamais les signatures métier des écritures ou contrôles eux-mêmes.
    """
    stream = "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records[:-1])
    records[-1]["stream_sha256"] = hashlib.sha256(stream.encode()).hexdigest()
    records[-1]["sage_inventory_count"] = sum(r.get("type") == "sage_inventory" for r in records)
    return records


class SageInventoryTests(TestCase):
    """Exerce les photographies Sage sur la base de test, sans donnée de production."""

    @classmethod
    def setUpClass(cls):
        """Génère une fois une extraction et un JSONL fictifs via le moteur CLI."""
        super().setUpClass()
        cls.folder = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.lot1_fixture", cls.folder.name],
                                cwd=root, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.records = [json.loads(line) for line in (Path(cls.folder.name) / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        """Libère uniquement les fichiers synthétiques temporaires de cette classe."""
        cls.folder.cleanup()
        super().tearDownClass()

    def load(self, records=None, *, resign=True):
        """Importe une nouvelle variante nommée, signée sauf corruption demandée."""
        records = copy.deepcopy(self.records if records is None else records)
        records[0]["name"] = f"Lot1 {Campaign.objects.count()}"
        if resign:
            sign_records(records)
        path = Path(self.folder.name) / "import.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def test_inventory_initial_ods_and_confirmed_mix(self):
        """La confirmation de 4000 équilibre FAC123 sans effacer l'écart source de 4000."""
        # La proposition seule n'est jamais comptée : désactiver son autorisation
        # pour vérifier séparément l'étape de confirmation métier.
        records = copy.deepcopy(self.records)
        next(r for r in records if r.get("type") == "proposal").pop("auto_validation", None)
        campaign = self.load(records)
        self.assertEqual(campaign.sage_inventory.count(), 4)
        self.assertEqual(campaign.sage_inventory.get(document="FAC999").amount, Decimal("50"))
        initial = next(d for d in campaign_controls(campaign) if d["identity"]["parts"][-1] == "FAC123")
        self.assertEqual(initial["gap"], "-4000.00")
        ods = campaign.global_controls.get(data__identity__strategy="ODS_ODG_BY_GROUP")
        self.assertEqual(ods.data["state"], "EQUILIBRE")
        self.assertTrue(ods.data["auto_validated"])
        user = User.objects.create_user("lot1-reviewer")
        ProjectPortfolio.objects.create(user=user, project=Project.objects.get(code="P"))
        line = LineReview.objects.select_related("transaction__project", "campaign", "group").get(transaction__source_id="S")
        refs = list(candidates_for(line))
        values = {k: {"mode": "SET", "value": v} for k, v in {
            "status": "Comptabilisé", "document": "FAC123", "date": "2026-01-01", "amount": "4000"}.items()}
        decide(line.pk, user, state="VALIDATED", values=values, comment="Affectation vérifiée",
               expected_version=line.version, expected_group_version=line.group.version,
               expected_source=signature(line), manual_refs=refs, manual_confirm=True, multiple_confirm=True)
        after = next(d for d in campaign_controls(campaign) if d["identity"]["parts"][-1] == "FAC123")
        self.assertEqual(after["state"], "EQUILIBRE")
        self.assertEqual(after["accounted_state"], "ECART")
        self.assertEqual(after["confirmed_sent_total"], "4000.00")
        self.assertEqual(after["gap"], "0.00")
        self.assertEqual(campaign.global_controls.get(key=after["key"]).data, initial)
        # Le calcul initial est une preuve immuable, le service reflète la décision.
        line.refresh_from_db()
        line.state = "REJECTED"
        line.save(update_fields=["state"])
        frozen = campaign.reviews.get(line=line)
        frozen.decision["state"] = "REJECTED"
        frozen.save(update_fields=["decision"])
        self.assertEqual(next(d for d in campaign_controls(campaign) if d["key"] == initial["key"])["state"], "ECART")

    def test_corruption_order_truncation_and_duplicate_rollback(self):
        """Signatures, ordre et identités sont contrôlés avant de publier une campagne."""
        current = self.load()
        original_count = Campaign.objects.count()
        variants = []
        altered = copy.deepcopy(self.records)
        next(r for r in altered if r.get("type") == "sage_inventory")["data"]["entry"]["amount"] = "999"
        variants.append((altered, False))
        counter = copy.deepcopy(self.records)
        counter[-1]["inventory_count"] += 1
        variants.append((counter, True))
        duplicate = copy.deepcopy(self.records)
        i = next(i for i, r in enumerate(duplicate) if r.get("type") == "sage_inventory")
        duplicate.insert(i, copy.deepcopy(duplicate[i]))
        duplicate[0]["load_quality"]["sage"]["rows_final"] += 1
        variants.append((duplicate, True))
        reordered = copy.deepcopy(self.records)
        row = reordered.pop(i)
        reordered.insert(-1, row)
        variants.append((reordered, True))
        invalid_policy = copy.deepcopy(self.records)
        invalid_policy[0]["sage_exclusions"]["prefixes"] = ["AB"]
        variants.append((invalid_policy, True))
        for records, resign in variants:
            with self.subTest(case=str(records[-1])):
                with self.assertRaises(ValidationError):
                    self.load(records, resign=resign)
                self.assertEqual(Campaign.objects.get(is_current=True).pk, current.pk)
                self.assertEqual(Campaign.objects.count(), original_count)
        path = Path(self.folder.name) / "truncated.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in self.records[:-1]), encoding="utf-8")
        with self.assertRaises(ValidationError):
            import_bundle(path)
        self.assertEqual(Campaign.objects.get(is_current=True).pk, current.pk)

    def test_policy_history_and_old_campaign_unavailable(self):
        """Un changement de politique ne réécrit pas la photographie antérieure."""
        first = self.load()
        records = copy.deepcopy(self.records)
        policy = exclusion_policy(["FAC"])
        records[0]["sage_exclusions"] = policy
        for r in records:
            if r.get("type") == "sage_inventory":
                r["data"] = inventory_record(r["data"]["entry"], policy)
        # La politique des contrôles v3 doit elle aussi interdire les validations.
        from reconciliation_contract import snapshot
        for r in records:
            if r.get("type") == "control" and any(e["document"].startswith("FAC") for e in r["data"]["entries"]):
                d = r["data"]
                r["data"] = snapshot(d["identity"], d["atlas"], d["entries"], amount_field=d["amount_field"], reasons=["Type de pièce exclu des contrôles selon la politique de campagne"])
        from collections import Counter
        records[-1]["control_statuses"] = dict(Counter(r["data"]["status"] for r in records if r.get("type") == "control"))
        second = self.load(records)
        self.assertEqual(second.sage_inventory.filter(eligible=False).count(), 3)
        self.assertEqual(second.global_controls.filter(state="EXCLU").count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.metadata["sage_exclusions"]["prefixes"], [])
        self.assertEqual(first.sage_inventory.filter(eligible=False).count(), 0)
        legacy = Campaign.objects.create(name="Historique", scope="ancien", metadata={"schema_version": 3})
        with self.assertRaisesMessage(ValidationError, "indisponible"):
            list(campaign_controls(legacy))

    def test_label_absent_with_other_label_is_not_unique(self):
        """Un autre groupe du même tiers empêche l'auto-validation sans libellé."""
        campaign = self.load()
        ods = campaign.sage_inventory.get(document="ODG-SAGE")
        entry = {**ods.data["entry"], "document": "ODS-OTHER", "label": "Autre", "original_label": "Autre"}
        entry["ref"] = digest([entry[k] for k in ("project_code", "fiscal_year", "document", "journal", "line", "analytic_line")])
        record = inventory_record(entry, campaign.metadata["sage_exclusions"])
        CampaignSageEntry.objects.create(campaign=campaign, record_id=record["record_id"], entry_ref=entry["ref"],
                                        project_code="P", fiscal_year=2026, document=entry["document"],
                                        control_key=record["control_key"], ods_scope=ods_scope(entry, sage=True),
                                        amount=Decimal("100"), data=record)
        data = next(d for d in campaign_controls(campaign) if d["key"] == ods.control_key)
        self.assertEqual(data["state"], "INDETERMINE")
        self.assertFalse(data["auto_validated"])

    def test_batched_calculation_queries_and_sql_indexes(self):
        """Les groupes partagent les lectures SQL ; aucun N+1 par écriture Sage."""
        campaign = self.load()
        with CaptureQueriesContext(connection) as queries:
            controls = list(campaign_controls(campaign))
        self.assertGreaterEqual(len(controls), 3)
        self.assertLessEqual(len(queries), 12)
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, CampaignSageEntry._meta.db_table)
        for name in ("sage_campaign_piece_idx", "sage_campaign_group_idx", "sage_campaign_ref_idx", "sage_campaign_ods_idx"):
            self.assertIn(name, constraints)

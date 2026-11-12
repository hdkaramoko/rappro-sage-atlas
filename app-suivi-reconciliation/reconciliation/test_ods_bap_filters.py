"""Recette ciblée du nouvel export, de son import et des filtres, sans campagne réelle réécrite."""

from decimal import Decimal
from collections import Counter
import json
from pathlib import Path
import subprocess
from time import perf_counter
from tempfile import TemporaryDirectory

from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from reconciliation_contract import digest
from reconciliation_contract.ods_party import POLICY

from accounts.models import User
from projects.models import Project, ProjectPortfolio
from .models import Campaign, CampaignGlobalControl, LineReview
from .review_import import import_bundle


class OdsBapFilterTests(TestCase):
    """Exerce un vrai JSONL moteur sur base jetable, puis les lectures et droits de la vue."""

    @classmethod
    def setUpClass(cls):
        """Génère une fois la petite campagne synthétique, sans lecture ou modification de source utilisateur."""
        super().setUpClass()
        cls.folder = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.ods_bap_filters_fixture", cls.folder.name],
                       cwd=root, check=True, capture_output=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        """Libère uniquement les fichiers fictifs temporaires de la recette."""
        cls.folder.cleanup()
        super().tearDownClass()

    def setUp(self):
        """Importe la fixture et donne au lecteur uniquement le projet P."""
        import_bundle(Path(self.folder.name) / "ods-bap.jsonl")
        self.campaign = Campaign.objects.get(is_current=True)
        self.user = User.objects.create_user("ods-reader")
        ProjectPortfolio.objects.create(user=self.user, project=Project.objects.get(code="P"))
        self.client.force_login(self.user)

    def workspace(self, **params):
        """Consulte toutes les origines et tous les états, avec filtres supplémentaires sans mutation."""
        return self.client.get(reverse("reconciliation:reviews"), {"view": "controls", "control_state": "", **params})

    def test_export_import_merges_absent_ods_parties_and_preserves_sources(self):
        """Les trois ODG -890 constituent un groupe bilatéral, avec NA/vide originaux conservés."""
        self.assertEqual(self.campaign.metadata["ods_party_policy"], POLICY)
        control = self.campaign.global_controls.get(data__identity__strategy="ODS_ODG_BY_GROUP")
        data = control.current_data or control.data
        self.assertEqual((data["atlas_count"], data["sage_count"], data["state"]), (3, 3, "EQUILIBRE"))
        self.assertEqual(Decimal(data["accounted_total"]), Decimal(-890))
        self.assertEqual(Decimal(data["sage_total"]), Decimal(-890))
        self.assertEqual(set(self.campaign.inventory.filter(source_id__startswith="OD").values_list("data__sage_third_party_code", flat=True)), {""})
        self.assertEqual(set(self.campaign.sage_inventory.filter(document__startswith="ODG").values_list("data__entry__third_party", flat=True)), {"NA"})
        self.assertContains(self.workspace(), "Non renseigné (vide/NA)")
        self.assertNotContains(self.workspace(), "TIERS_ABSENT_ODS")

    def test_bap_distinct_accounted_entries_do_not_block_auto(self):
        """Quatre comptabilisées distinctes ne bloquent plus la seule preuve BAP et sa réservation unique."""
        line = LineReview.objects.get(transaction__source_id="BAP-TARGET")
        self.assertEqual((line.group.rule, line.state, line.validation_source), ("MATCH_BAP", "VALIDATED", "AUTO"))
        self.assertEqual(self.campaign.reviews.get(line=line).reasons, [])

    def test_piece_type_all_multiselection_and_origin(self):
        """Toutes est le défaut exclusif ; les types se combinent aux origines avant pagination."""
        response = self.workspace()
        menus = {m["name"]: m for m in response.context["filter_menus"]}
        self.assertEqual(menus["piece_type"]["selected"], [])
        self.assertEqual(menus["origin"]["selected"], [])
        self.assertEqual({v["value"] for v in menus["piece_type"]["choices"]}, {"ODS/ODG", "CIF", "FAF"})
        self.assertEqual(self.workspace(piece_type="ODS/ODG").context["page"].paginator.count, 1)
        self.assertEqual(self.workspace(piece_type=["CIF", "FAF"], origin="both").context["page"].paginator.count, 5)
        self.assertEqual(self.workspace(piece_type=["", "CIF"]).context["page"].paginator.count, 6)
        self.assertEqual(self.workspace(piece_type="ODS/ODG", origin="sage").context["page"].paginator.count, 0)
        self.assertEqual(self.workspace(piece_type="ODS/ODG", q="NO-SUCH").context["page"].paginator.count, 0)

    def test_filters_pagination_and_permissions(self):
        """Le type reste sélectionné en page 2 ; aucune option ni ligne hors portefeuille ne fuit."""
        for i in range(60):
            identity = {"strategy": "STANDARD_BY_DOCUMENT", "parts": ["P", 2026, f"AAA{i}"]}
            data = {"identity": identity, "state": "ECART", "atlas_count": 0, "sage_count": 1}
            CampaignGlobalControl.objects.create(campaign=self.campaign, key=digest(identity), project_code="P", state="ECART", data=data)
        other = Project.objects.create(code="SECRET", label="Interdit")
        identity = {"strategy": "STANDARD_BY_DOCUMENT", "parts": [other.code, 2026, "ZZZ1"]}
        CampaignGlobalControl.objects.create(campaign=self.campaign, key=digest(identity), project_code=other.code,
            state="ECART", data={"identity": identity})
        response = self.workspace(piece_type="AAA", origin="sage", page=2)
        self.assertEqual(response.context["page"].paginator.count, 60)
        self.assertEqual(len(response.context["page"]), 10)
        self.assertContains(response, "piece_type=AAA")
        self.assertContains(response, "origin=sage")
        self.assertNotContains(response, "ZZZ")
        self.assertNotContains(response, "SECRET")

    def test_legacy_jsonl_keeps_its_original_keys(self):
        """Un ancien JSONL signé sans politique conserve les clés vide/NA distinctes, sans réécrire sa campagne précédente."""
        from reconciliation_contract import control_identity, snapshot
        from reconciliation_contract.sage_inventory import inventory_record
        from .test_sage_inventory import sign_records
        records = [json.loads(line) for line in (Path(self.folder.name) / "ods-bap.jsonl").read_text(encoding="utf-8").splitlines()]
        records[0].pop("ods_party_policy")
        records[0]["name"] = "Legacy fictif"
        for record in records:
            if record.get("type") == "sage_inventory":
                data = record["data"]
                record["data"] = inventory_record(data["entry"], records[0]["sage_exclusions"],
                    source_fingerprint=data["source_fingerprint"], attributes=data["attributes"])
            if record.get("type") == "control" and record["data"]["identity"]["strategy"] == "ODS_ODG_BY_GROUP":
                data = record["data"]
                record["data"] = snapshot(control_identity(data["atlas"][0]), data["atlas"], [],
                    amount_field=data["amount_field"], tolerance=data["tolerance"])
        records[-1]["control_statuses"] = dict(Counter(r["data"]["status"] for r in records if r.get("type") == "control"))
        sign_records(records)
        path = Path(self.folder.name) / "legacy.jsonl"
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in records), encoding="utf-8")
        previous = list(self.campaign.inventory.values_list("pk", "control_key", "data"))
        import_bundle(path)
        current = Campaign.objects.get(is_current=True)
        self.assertEqual(current.global_controls.filter(data__identity__strategy="ODS_ODG_BY_GROUP").count(), 2)
        self.assertEqual(previous, list(self.campaign.inventory.values_list("pk", "control_key", "data")))

    def test_filter_cost_on_thousand_materialized_controls(self):
        """Mille contrôles gardent une page de cinquante lignes et un nombre borné de requêtes sans N+1."""
        from .accounting_models import AccountingGroup
        rows = []
        for index in range(1000):
            identity = {"strategy": "STANDARD_BY_DOCUMENT", "parts": ["P", 2026, f"FAC{index}"]}
            rows.append(CampaignGlobalControl(campaign=self.campaign, key=digest(identity), project_code="P",
                state="ECART", data={"identity": identity, "state": "ECART", "atlas_count": 0, "sage_count": 1}))
        CampaignGlobalControl.objects.bulk_create(rows, batch_size=500)
        AccountingGroup.objects.bulk_create([AccountingGroup(campaign=self.campaign, control=row, project_code="P",
            piece_type="FAC", atlas=0, sage=1, gap=-1, state="NON_CADRE", data={}) for row in rows], batch_size=500)
        start = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = self.workspace(piece_type="FAC", origin="sage", page=2)
        self.assertEqual(response.context["page"].paginator.count, 1000)
        self.assertEqual(len(response.context["page"]), 50)
        self.assertLess(len(queries), 16)
        print(f"BENCH filtre types : 1000 contrôles, {perf_counter()-start:.3f}s, {len(queries)} requêtes")

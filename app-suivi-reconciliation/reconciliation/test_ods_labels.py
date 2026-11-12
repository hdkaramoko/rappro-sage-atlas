"""Import et compatibilité de la clé ODS fondée sur Libellé SAGE Atlas."""

import copy
import json
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from reconciliation_contract import control_identity, snapshot

from . import test_campaigns as fixtures
from .campaigns import normalize_inventory
from .models import Campaign, LineReview
from .review_import import import_bundle
from .test_sage_inventory import sign_records


class OdsLabelTests(TestCase):
    """Exerce le vrai moteur et l'import sans toucher aux campagnes de production."""
    setUp = fixtures.CampaignTests.setUp

    @classmethod
    def setUpClass(cls):
        """Génère une fois les trois cas C/M/S sur fichiers temporaires synthétiques."""
        super().setUpClass()
        cls.sources = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.ods_labels_fixture", cls.sources.name],
                                cwd=root, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.records = [json.loads(row) for row in (Path(cls.sources.name) / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        """Libère les seules sources générées pour cette recette."""
        cls.sources.cleanup()
        super().tearDownClass()

    def load(self, records=None):
        """Signe et importe une variante dans la base jetable, en ajustant ses compteurs."""
        records = copy.deepcopy(self.records if records is None else records)
        records[0]["name"] = f"Recette ODS {Campaign.objects.count()}"
        records[-1].update(inventory_count=sum(r.get("type") == "inventory" for r in records),
            complete=sum(r.get("type") == "proposal" for r in records), control_count=sum(r.get("type") == "control" for r in records),
            sage_inventory_count=sum(r.get("type") == "sage_inventory" for r in records),
            control_statuses=dict(Counter(r["data"]["status"] for r in records if r.get("type") == "control")))
        records[0]["load_quality"]["sage"]["rows_final"] = records[-1]["sage_inventory_count"]
        sign_records(records)
        path = Path(self.folder.name) / "ods-labels.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def test_accounted_uses_sage_label_and_sent_keeps_atlas_matching(self):
        """Les deux parcours importés utilisent leur libellé propre et conservent les sources."""
        campaign = self.load()
        source = campaign.inventory.get(source_id="C")
        sage = campaign.sage_inventory.get(document="ODG-SAGE")
        self.assertEqual(source.control_key, sage.control_key)
        self.assertEqual(source.data["atlas_label"], "Texte Atlas différent")
        self.assertEqual(source.data["sage_label"], "Réaffect salaires 08/26")
        self.assertEqual(campaign.global_controls.get(key=source.control_key).current_state, "EQUILIBRE")
        line = LineReview.objects.select_related("group", "transaction").get(transaction__source_id="S")
        self.assertEqual(line.group.rule, "MATCH_EXACT")
        self.assertEqual(line.transaction.atlas_label, "Mission Recherche")
        self.assertEqual(line.state, "VALIDATED")

    def test_empty_sage_label_is_visible_and_never_uses_atlas_fallback(self):
        """Un champ vide explicite reste indéterminé, malgré un libellé Atlas identique à Sage."""
        campaign = self.load()
        source = campaign.inventory.get(source_id="M")
        control = campaign.global_controls.get(key=source.control_key)
        self.assertEqual(control.data["identity"]["parts"][-1], "")
        self.assertEqual(control.current_state, "INDETERMINE")
        self.assertIn("Libellé SAGE Atlas absent pour le contrôle ODS/ODG", control.data["reasons"])
        response = self.client.get(reverse("reconciliation:inventory-detail", args=[source.pk]))
        self.assertContains(response, "Libellé SAGE du fichier Atlas")
        self.assertContains(response, "Non renseigné")

    def test_new_policy_missing_column_or_unknown_policy_rolls_back(self):
        """Une politique inconnue ou un champ non transmis n'est pas interprété silencieusement."""
        for missing in (True, False):
            records = copy.deepcopy(self.records)
            if missing:
                next(row for row in records if row.get("type") == "inventory")["atlas"].pop("Libellé SAGE")
            else:
                records[0]["ods_label_policy"] = "unknown"
            with self.assertRaises(ValidationError):
                self.load(records)
        self.assertFalse(Campaign.objects.exists())

    def test_old_field_absence_keeps_historical_identity(self):
        """Une ancienne ligne canonique n'acquiert pas un champ vide qui changerait sa clé."""
        raw = copy.deepcopy(next(row["atlas"] for row in self.records if row.get("type") == "inventory" and row["atlas"]["Id"] == "C"))
        raw.pop("Libellé SAGE")
        source = normalize_inventory(raw, extended=True)
        self.assertNotIn("sage_label", source)
        self.assertEqual(control_identity(source)["parts"][-1], "texte atlas different")

    def test_manual_ods_projection_uses_new_label_without_modifying_source(self):
        """Un lien manuel ODS projette la preuve ciblée sans écraser les deux libellés source."""
        from .business import confirm_inventory_link
        campaign = self.load()
        source = campaign.inventory.get(source_id="C")
        original = copy.deepcopy(source.data)
        target = campaign.sage_inventory.get(document="ODG-SAGE")
        confirm_inventory_link(source.pk, self.user, entry_ids=[target.pk], comment="Preuve vérifiée", expected_version=0)
        source.refresh_from_db()
        self.assertEqual(source.data, original)
        result = campaign.global_controls.get(key=target.control_key).current_data
        self.assertEqual(result["state"], "EQUILIBRE")

    def test_legacy_bundle_import_and_new_campaign_preserve_old_sources(self):
        """Un ancien v3 s'importe encore ; un nouveau flux ne réécrit pas ses preuves."""
        records = copy.deepcopy(self.records)
        records[0].pop("ods_label_policy")
        for row in records:
            if row.get("type") in ("inventory", "proposal"):
                sources = [row["atlas"]] if row["type"] == "inventory" else row["atlas"]
                for raw in sources:
                    if raw["Id"] in ("C", "M"):
                        raw["Libellé ATLAS"] = raw["Libellé SAGE"]
                    raw.pop("Libellé SAGE")
            elif row.get("type") == "control":
                data = row["data"]
                for source in data["atlas"]:
                    source["atlas_label"] = source.pop("sage_label")
                reasons = [reason for reason in data["reasons"]
                           if reason != "Libellé SAGE Atlas absent pour le contrôle ODS/ODG"]
                row["data"] = snapshot(data["identity"], data["atlas"], data["entries"],
                    amount_field=records[0]["amount_field"], tolerance=records[0]["tolerance"], reasons=reasons)
        old = self.load(records)
        source = old.inventory.get(source_id="C")
        original = copy.deepcopy(source.data)
        self.assertNotIn("sage_label", original)
        self.load()
        source.refresh_from_db()
        self.assertEqual(source.data, original)

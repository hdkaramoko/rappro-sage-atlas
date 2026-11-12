"""Recette du volet A : seuil ciblé importé et provenance des tableaux BAP."""

import copy
import json
import subprocess
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.core.exceptions import ValidationError

from accounts.models import User
from . import test_campaigns as fixtures
from .models import Campaign, CampaignInventory, CampaignSageEntry, LineReview
from .review_import import import_bundle
from .test_sage_inventory import sign_records
from .presentation import rule_choices
from reconciliation_contract.matching_policy import RULE_ORDER


class VoletATests(TestCase):
    """Teste seulement des campagnes fictives, sans réimport ni migration de la base utilisateur."""

    @classmethod
    def setUpClass(cls):
        """Produit un JSONL de recette au moyen du vrai moteur, hors namespace Django."""
        super().setUpClass()
        cls.sources = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        completed = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.volet_a_fixture", cls.sources.name],
            cwd=root, capture_output=True, text=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        cls.records = [json.loads(line) for line in (Path(cls.sources.name) / "volet-a.jsonl").read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        """Libère les seuls fichiers synthétiques créés par cette classe."""
        cls.sources.cleanup()
        super().tearDownClass()

    def setUp(self):
        """Crée les droits de portefeuille et importe une variante dans la base de test."""
        fixtures.CampaignTests.setUp(self)
        self.campaign = self.load()

    def load(self, records=None):
        """Signe puis importe la variante fournie ; les corruptions métier ne sont pas réparées.

        Retourne la nouvelle campagne ; toute ValidationError conserve les données
        publiées précédentes. Aucun accès aux JSONL ou bases réels.
        """
        records = copy.deepcopy(self.records if records is None else records)
        records[0]["name"] = f"Volet A {Campaign.objects.count()}"
        sign_records(records)
        path = Path(self.folder.name) / "volet-a.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def test_new_auto_is_consumed_with_exact_precision_and_old_controls(self):
        """L'import accepte 0,0116 et le BAP à 0,04 sans modifier les seuils des contrôles."""
        lines = {line.transaction.source_id: line for line in LineReview.objects.select_related("transaction", "group")}
        self.assertEqual({key for key, line in lines.items() if line.validation_source == "AUTO"}, {"A1", "A2", "I", "L"})
        self.assertEqual(lines["I"].transaction.total_project_charges, Decimal("362.26"))
        frozen = self.campaign.reviews.get(line=lines["I"])
        self.assertEqual(frozen.group.data["matching_source_amounts"]["I"], "362.2616")
        self.assertEqual(self.campaign.metadata["tolerance"], "0.01")
        self.assertEqual(self.campaign.global_controls.get(data__identity__parts__2="FAC-BAP-I").current_state, "ECART")
        self.assertNotEqual(lines["D1"].validation_source, "AUTO")
        self.assertEqual(lines["L"].validation_source, "AUTO")
        self.assertNotEqual(lines["O"].validation_source, "AUTO")

    def test_control_tables_have_independent_bounded_pagination(self):
        """Les deux pages restent indépendantes, bornées et ancrées, sans écritures de consultation."""
        from reconciliation_contract import entry_from_sage
        from reconciliation_contract.sage_inventory import inventory_record
        from imports_app.services import build_business_key
        control = self.campaign.global_controls.get(data__identity__parts__2="COMPTA")
        inventory = self.campaign.inventory.get(source_id="C")
        entry = self.campaign.sage_inventory.get(document="COMPTA")
        atlas_rows, sage_rows = [], []
        for index in range(26):
            atlas_copy = copy.copy(inventory)
            atlas_copy.pk = None
            atlas_copy.source_id = f"C-{index}"
            atlas_copy.business_key = build_business_key("P", atlas_copy.source_id, 2026)
            atlas_copy.data = {**inventory.data, "source_id": atlas_copy.source_id, "total_sage_charges": "0.00", "total_project_charges": "0.00"}
            atlas_rows.append(atlas_copy)
            raw = {"Projet": "P", "Numéro pièce": "COMPTA", "Date comptable": "2026-01-01", "Journal": "ACH",
                   "N° de ligne comptable": str(index + 10), "N° de ligne Analytique": "1", "Charges (Dépenses)": "0",
                   "Code Tiers - Tiers doc Orig": "T", "Libellé pièce": "SAGE_EXTRACTION", "Devise": "EUR"}
            record = inventory_record(entry_from_sage(raw), self.campaign.metadata["sage_exclusions"], attributes={"Référence": "BAP-SAGE-C"})
            sage_copy = copy.copy(entry)
            sage_copy.pk = None
            sage_copy.record_id, sage_copy.entry_ref, sage_copy.data = record["record_id"], record["entry"]["ref"], record
            sage_rows.append(sage_copy)
        CampaignInventory.objects.bulk_create(atlas_rows)
        CampaignSageEntry.objects.bulk_create(sage_rows)
        url = reverse("reconciliation:global-control-detail", args=[control.pk])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url, {"page": 2, "sage_page": 2, "return": "/rapprochements/validation/?origin=both"})
        self.assertEqual(response.context["page"].paginator.count, 27)
        self.assertEqual(response.context["sage_page"].paginator.count, 27)
        self.assertEqual(len(response.context["page"]), 2)
        self.assertEqual(len(response.context["sage_page"]), 2)
        self.assertContains(response, "sage_page=1")
        self.assertContains(response, "#sage-lines")
        self.assertContains(response, "#atlas-lines")
        self.assertLess(len(queries), 20)

    def test_legacy_tolerance_and_forged_source_are_refused_safely(self):
        """Sans politique reste 0,01 ; une base source contradictoire annule l'import entier."""
        legacy = copy.deepcopy(self.records)
        legacy[0].pop("matching_tolerances")
        for record in legacy:
            if record.get("type") == "proposal":
                record.pop("matching_source_amounts", None)
        campaign = self.load(legacy)
        self.assertFalse(campaign.reviews.filter(source__source_id__in=["A1", "A2"],
            decision__validation_source="AUTO", decision__current=True).exists())
        broken = copy.deepcopy(self.records)
        proposal = next(r for r in broken if r.get("type") == "proposal" and r["atlas"][0]["Id"] == "I")
        proposal["matching_source_amounts"]["I"] = "362.25"
        count = Campaign.objects.count()
        with self.assertRaisesMessage(ValidationError, "contradictoire"):
            self.load(broken)
        self.assertEqual(Campaign.objects.count(), count)

    def test_rule_labels_order_and_sage_bap_never_fall_back_to_atlas(self):
        """Toutes précède la cascade ; le justificatif Sage ne reprend jamais le BAP Atlas."""
        codes = list(reversed(RULE_ORDER))
        choices = rule_choices(codes)
        self.assertEqual([code for code, _ in choices], list(RULE_ORDER[:-1]) + ["__NO_MATCH__"])
        response = self.client.get(reverse("reconciliation:reviews"), {"state": ""})
        self.assertContains(response, "N° BAP uniquement")
        self.assertNotContains(response, "Correspondance par BAP")
        line = LineReview.objects.select_related("group").get(transaction__source_id="I")
        proofs = copy.deepcopy(line.group.evidence)
        proofs[0]["rows"][0]["Référence"] = "SAGE_REFERENCE_PROUVEE"
        line.group.evidence = proofs
        line.group.save(update_fields=["evidence"])
        response = self.client.get(reverse("reconciliation:review-detail", args=[line.pk]))
        section = response.content.decode().split('<h2>Correspondance SAGE</h2>', 1)[1].split('</section>', 1)[0]
        self.assertIn("N° BAP Sage", section)
        self.assertIn("SAGE_REFERENCE_PROUVEE", section)
        self.assertNotIn(">BAP-I<", section)
        proofs[0]["rows"][0].pop("Référence")
        line.group.evidence = proofs
        line.group.save(update_fields=["evidence"])
        response = self.client.get(reverse("reconciliation:review-detail", args=[line.pk]))
        section = response.content.decode().split('<h2>Correspondance SAGE</h2>', 1)[1].split('</section>', 1)[0]
        self.assertNotIn(">BAP-I<", section)

    def test_control_detail_source_labels_keys_and_read_only(self):
        """Le détail affiche les BAP de chaque source et le libellé Sage du fichier Atlas."""
        control = self.campaign.global_controls.get(data__identity__parts__2="COMPTA")
        before = (control.data, control.current_data, control.current_state, control.current_version)
        url = reverse("reconciliation:global-control-detail", args=[control.pk])
        response = self.client.get(url)
        self.assertContains(response, "BAP-ATLAS-C")
        self.assertContains(response, "BAP-SAGE-C")
        self.assertContains(response, "SAGE_DANS_ATLAS")
        self.assertContains(response, "SAGE_EXTRACTION")
        self.assertNotContains(response, "LIBELLE_ATLAS_NON_UTILISE")
        self.assertNotContains(response, "FAC-BAP-I")
        control.refresh_from_db()
        self.assertEqual((control.data, control.current_data, control.current_state, control.current_version), before)
        outsider = User.objects.create_user("outsider")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_optional_display_bap_does_not_break_existing_correction_carry(self):
        """Le passage d'un ancien inventaire sans BAP au nouveau ne perd pas une correction."""
        from .business import correct_inventory
        legacy = copy.deepcopy(self.records)
        for record in legacy:
            if record.get("type") == "inventory":
                record["atlas"].pop("N° BAP (SAGE)", None)
        prior = self.load(legacy)
        inventory = prior.inventory.get(source_id="C")
        correct_inventory(inventory.pk, self.user, reason="AMOUNT", amount="2.00", expected_version=0)
        campaign = self.load()
        current = campaign.inventory.get(source_id="C")
        self.assertTrue(current.adjustment.active)
        self.assertEqual(current.adjustment.amount, Decimal("2.00"))
        self.assertFalse(current.business_events.filter(kind="CARRY_PENDING").exists())

    def test_search_shows_only_sage_reference_and_control_empty_state(self):
        """La recherche expose Référence Sage ; les contrôles sans Sage ont un état vide lisible."""
        inventory = self.campaign.inventory.get(source_id="C")
        response = self.client.get(reverse("reconciliation:inventory-detail", args=[inventory.pk]))
        self.assertContains(response, "N° BAP Sage")
        self.assertContains(response, "BAP-SAGE-C")
        control = self.campaign.global_controls.get(data__identity__parts__2="COMPTA")
        self.campaign.sage_inventory.filter(control_key=control.key).delete()
        response = self.client.get(reverse("reconciliation:global-control-detail", args=[control.pk]))
        self.assertContains(response, "Aucune écriture Sage concernée")

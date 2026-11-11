"""Recette Lot 2 sur sources fictives, sans base ni fichiers de production."""

import copy
import json
import subprocess
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from reconciliation_contract import control_identity, digest, snapshot
from reconciliation_contract.atlas_context import ATLAS_CONTEXT
from reconciliation_contract.sage_inventory import inventory_record

from accounts.models import User

from . import test_campaigns as fixtures
from .business import (affected_keys, cancel_inventory_link, confirm_inventory_link, correct_inventory,
                       recalculate, retained_amount, search_sage)
from .campaigns import normalize_inventory
from .global_control import campaign_controls
from .models import Campaign, CampaignAction, CampaignSageEntry, LineReview, ManualAllocation
from .review import decide, signature
from .review_import import import_bundle
from .test_sage_inventory import sign_records


class BusinessTests(TestCase):
    """Corrections, affectations entières et contrôles ciblés dans la transaction métier."""

    @classmethod
    def setUpClass(cls):
        """Génère une seule fois le vrai JSONL fictif 6000 Comptabilisé + 4000 Envoyé."""
        super().setUpClass()
        cls.source_folder = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.lot1_fixture", cls.source_folder.name],
                                cwd=root, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.records = [json.loads(line) for line in (Path(cls.source_folder.name) / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
        for row in cls.records:
            if row.get("type") == "proposal":
                row.pop("auto_validation", None)

    @classmethod
    def tearDownClass(cls):
        """Libère uniquement les extractions et JSONL synthétiques temporaires."""
        cls.source_folder.cleanup()
        super().tearDownClass()

    def setUp(self):
        """Crée utilisateur/portefeuille de recette et importe la campagne fictive."""
        fixtures.CampaignTests.setUp(self)
        self.campaign = self.load()

    def load(self, records=None):
        """Importe une nouvelle variante signée dans la base de test jetable.

        Recalcule les preuves Comptabilisé et compteurs des variantes, sans
        toucher aux décisions des campagnes antérieures.
        Les variantes intentionnellement cohérentes réémettent leurs bases exactes
        après modification des lignes ; les tests de corruption restent séparés.
        """
        records = copy.deepcopy(self.records if records is None else records)
        records[0]["name"] = f"Campagne Lot 2 {Campaign.objects.count()}"
        accounted = [normalize_inventory(r["atlas"], extended=True) for r in records if r.get("type") == "inventory" and r["atlas"]["Statut BAP"] == "Comptabilisé"]
        accounted = [{k: v for k, v in row.items() if k not in ATLAS_CONTEXT.values()} for row in accounted]
        from collections import Counter
        from reconciliation_contract import money
        for record in records:
            if record.get("type") == "proposal" and "matching_source_amounts" in record:
                record["matching_source_amounts"] = {str(row["Id"]): str(money(row.get("Total charges projet (€)")))
                    if money(row.get("Total charges projet (€)")) is not None else None for row in record["atlas"]}
        for row in records:
            if row.get("type") == "control":
                data = row["data"]
                row["data"] = snapshot(data["identity"], [a for a in accounted if control_identity(a) == data["identity"]],
                                       data["entries"], amount_field=data["amount_field"], tolerance=data["tolerance"])
        records[-1]["inventory_count"] = sum(r.get("type") == "inventory" for r in records)
        records[-1]["control_statuses"] = dict(Counter(r["data"]["status"] for r in records if r.get("type") == "control"))
        sign_records(records)
        path = Path(self.folder.name) / "lot2.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def inventory(self, source="S"):
        """Charge la source exacte de la campagne courante et ses bases métier."""
        return self.campaign.inventory.select_related("campaign", "adjustment", "inventory_match").get(source_id=source)

    def entry(self, amount="4000"):
        """Retourne l'écriture Sage du montant demandé sur FAC123 dans la campagne."""
        return self.campaign.sage_inventory.get(document="FAC123", amount=Decimal(amount))

    def result(self, document="FAC123"):
        """Retourne le calcul courant matérialisé sans déclencher de recalcul en lecture."""
        row = self.campaign.global_controls.get(data__identity__parts__2=document)
        return row.current_data or row.data

    def confirm(self, *, source="S", entries=None, replace=False, request_id=None):
        """Confirme via le service transactionnel les écritures fictives explicitement choisies."""
        row = self.inventory(source)
        return confirm_inventory_link(row.pk, self.user, entry_ids=entries or [self.entry().pk],
                    comment="Justificatifs vérifiés", expected_version=row.business_version,
                    replace_existing=replace, request_id=request_id)

    def test_reference_confirm_cancel_keeps_initial_control_and_sources(self):
        """6000 + 4000 passent de -4000 à zéro puis -4000 sans réécrire l'import."""
        original = copy.deepcopy(self.campaign.global_controls.get(data__identity__parts__2="FAC123").data)
        source = copy.deepcopy(self.inventory().data)
        self.assertEqual(self.result()["gap"], "-4000.00")
        self.confirm()
        data = self.result()
        self.assertEqual((data["state"], Decimal(data["gap"])), ("EQUILIBRE", Decimal(0)))
        self.assertEqual(Decimal(data["confirmed_sent_total"]), Decimal("4000"))
        self.assertEqual(Decimal(data["accounted_gap"]), Decimal("-4000"))
        self.assertEqual(self.inventory().data, source)
        row = self.inventory()
        cancel_inventory_link(row.pk, self.user, expected_version=row.business_version)
        self.assertEqual(Decimal(self.result()["gap"]), Decimal("-4000"))
        self.assertEqual(ManualAllocation.objects.filter(active=True).count(), 0)
        self.assertEqual(self.campaign.global_controls.get(data__identity__parts__2="FAC123").data, original)
        self.assertEqual(CampaignAction.objects.filter(inventory=row).count(), 2)

    def test_correct_amount_15000_to_10000_then_cancel(self):
        """La correction Comptabilisé préserve 15000 source et rétablit l'écart après annulation."""
        records = copy.deepcopy(self.records)
        next(r["atlas"] for r in records if r.get("type") == "inventory" and r["atlas"]["Id"] == "C")["Total charges SAGE (€)"] = "15000"
        self.campaign = self.load(records)
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="10000.00", expected_version=0)
        self.assertEqual(self.inventory("C").data["total_sage_charges"], "15000.00")
        self.assertEqual(retained_amount(self.inventory("C")), Decimal("10000"))
        self.assertEqual(self.result()["state"], "EQUILIBRE")
        self.assertFalse(self.result()["auto_validated"])
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, cancel=True, expected_version=row.business_version)
        self.assertEqual(retained_amount(self.inventory("C")), Decimal("15000"))
        self.assertEqual(Decimal(self.result()["gap"]), Decimal("5000"))

    def test_duplicate_excludes_only_one_source_without_deleting_it(self):
        """Deux Comptabilisé de 10000 deviennent équilibrés après exclusion explicite d'un doublon."""
        records = copy.deepcopy(self.records)
        source = next(r["atlas"] for r in records if r.get("type") == "inventory" and r["atlas"]["Id"] == "C")
        source["Total charges SAGE (€)"] = "10000"
        records.insert(1, {"type": "inventory", "atlas": {**source, "Id": "D"}})
        self.campaign = self.load(records)
        row = self.inventory("D")
        correct_inventory(row.pk, self.user, reason="DUPLICATE", expected_version=0)
        self.assertEqual(retained_amount(self.inventory("D")), Decimal(0))
        self.assertEqual(self.inventory("D").data["total_sage_charges"], "10000.00")
        self.assertEqual(self.result()["state"], "EQUILIBRE")
        self.assertTrue(self.campaign.inventory.filter(source_id="D", present=True).exists())

    def test_no_engine_candidate_needed_for_manual_confirmation(self):
        """Une ligne UNMATCHED trouve Sage dans l'inventaire sans fabriquer une preuve moteur."""
        records = copy.deepcopy(self.records)
        proposal = next(r for r in records if r.get("type") == "proposal")
        proposal.update(rule="UNMATCHED", match_status="UNMATCHED", evidence=[], sage_total=None)
        self.campaign = self.load(records)
        self.confirm()
        line = LineReview.objects.get(transaction__source_id="S")
        self.assertEqual((line.group.rule, line.group.evidence), ("UNMATCHED", []))
        self.assertEqual((line.state, line.validation_source), ("VALIDATED", "MANUAL"))
        self.assertEqual(self.result()["state"], "EQUILIBRE")

    def test_original_atlas_currency_does_not_block_search(self):
        """Une origine USD n'empêche pas la recherche de charges EUR ; le statut reste vérifié."""
        row = self.inventory()
        row.data = {**row.data, "currency": "USD - Dollar Usa"}
        row.save(update_fields=["data"])
        self.assertTrue(search_sage(row, self.user).filter(pk=self.entry().pk).exists())
        row.data["bap_status"] = "Autre statut"
        with self.assertRaisesMessage(ValidationError, "Le statut Atlas"):
            search_sage(row, self.user)

    def test_correction_is_not_a_confirmation_and_requires_new_link_basis(self):
        """Une correction de la ligne liée impose une nouvelle confirmation explicite."""
        self.confirm()
        row = self.inventory()
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="3500", expected_version=row.business_version)
        self.assertEqual(self.result()["state"], "INDETERMINE")
        row = self.inventory()
        correct_inventory(row.pk, self.user, cancel=True, expected_version=row.business_version)
        self.assertEqual(self.result()["state"], "INDETERMINE")
        self.confirm(replace=True)
        self.assertEqual(self.result()["state"], "EQUILIBRE")

    def test_wrong_sign_precision_reason_and_partial_selection_are_rejected(self):
        """Les erreurs de montant/motif et les affectations partielles n'écrivent aucun événement."""
        row = self.inventory()
        for reason, amount in (("", "4000"), ("AMOUNT", None), ("AMOUNT", "NaN"),
                               ("AMOUNT", "4000.001"), ("AMOUNT", "-4000")):
            with self.subTest(reason=reason, amount=amount), self.assertRaises(ValidationError):
                correct_inventory(row.pk, self.user, reason=reason, amount=amount, expected_version=0)
        with self.assertRaisesMessage(ValidationError, "partielle"):
            self.confirm(entries=[self.entry("6000").pk])
        self.assertEqual(CampaignAction.objects.count(), 0)
        self.assertEqual(ManualAllocation.objects.count(), 0)

    def test_permissions_closed_campaign_and_optimistic_version(self):
        """Aucun accès hors portefeuille, action historique ou écriture sur version périmée."""
        row = self.inventory()
        outsider = User.objects.create_user("outside")
        with self.assertRaises(PermissionDenied):
            search_sage(row, outsider)
        with self.assertRaises(PermissionDenied):
            correct_inventory(row.pk, outsider, reason="DUPLICATE", expected_version=0)
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="4000", expected_version=0)
        with self.assertRaisesMessage(ValidationError, "changé"):
            correct_inventory(row.pk, self.user, cancel=True, expected_version=0)
        self.campaign.is_current = False
        self.campaign.save(update_fields=["is_current"])
        with self.assertRaisesMessage(ValidationError, "close"):
            self.confirm()

    def test_retries_are_idempotent_and_request_ids_cannot_change_payload(self):
        """Deux soumissions identiques ne créent qu'une confirmation et un événement."""
        row, request_id = self.inventory(), uuid4()
        options = {"entry_ids": [self.entry().pk], "comment": "Vérifié", "expected_version": 0, "request_id": request_id}
        confirm_inventory_link(row.pk, self.user, **options)
        confirm_inventory_link(row.pk, self.user, **options)
        self.assertEqual(CampaignAction.objects.filter(inventory=row).count(), 1)
        self.assertEqual(ManualAllocation.objects.filter(active=True).count(), 1)
        with self.assertRaises(ValidationError):
            confirm_inventory_link(row.pk, self.user, **{**options, "comment": "Autre action"})
        row = self.inventory()
        correction_id = uuid4()
        correction = {"reason": "AMOUNT", "amount": "4000", "expected_version": row.business_version, "request_id": correction_id}
        correct_inventory(row.pk, self.user, **correction)
        correct_inventory(row.pk, self.user, **correction)
        self.assertEqual(CampaignAction.objects.filter(inventory=row).count(), 2)
        row = self.inventory()
        cancel_id = uuid4()
        cancel_inventory_link(row.pk, self.user, expected_version=row.business_version, request_id=cancel_id)
        cancel_inventory_link(row.pk, self.user, expected_version=row.business_version, request_id=cancel_id)
        self.assertEqual(CampaignAction.objects.filter(inventory=row).count(), 3)

    def test_excluded_other_scope_and_reserved_entries_cannot_be_selected(self):
        """La sélection revalide le périmètre et l'éligibilité côté serveur."""
        entry = self.entry()
        CampaignSageEntry.objects.filter(pk=entry.pk).update(eligible=False)
        self.assertNotIn(entry.pk, search_sage(self.inventory(), self.user).values_list("pk", flat=True))
        with self.assertRaisesMessage(ValidationError, "exclue"):
            self.confirm()
        CampaignSageEntry.objects.filter(pk=entry.pk).update(eligible=True, project_code="OTHER")
        with self.assertRaisesMessage(ValidationError, "périmètre"):
            self.confirm(entries=[entry.pk])

    def test_legacy_decision_confirm_refuse_recalculates_old_target(self):
        """Les boutons existants déclenchent aussi le recalcul ciblé après validation/refus."""
        line = LineReview.objects.select_related("transaction__project", "group", "campaign").get(transaction__source_id="S")
        values = {k: {"mode": "SET", "value": v} for k, v in {
            "status": "Comptabilisé", "amount": "4000", "document": "FAC123", "date": "2026-01-01"}.items()}
        decide(line.pk, self.user, state="VALIDATED", values=values, comment="Pièce vérifiée",
               expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line), multiple_confirm=True)
        self.assertEqual(self.result()["state"], "EQUILIBRE")
        line.refresh_from_db()
        line.group.refresh_from_db()
        decide(line.pk, self.user, state="REJECTED", values=values, comment="Refus vérifié",
               expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line))
        self.assertEqual(Decimal(self.result()["gap"]), Decimal("-4000"))

    def test_recalculation_is_targeted_and_idempotent(self):
        """Une action n'appelle jamais le calcul complet et ne modifie pas FAC999."""
        untouched = self.campaign.global_controls.get(data__identity__parts__2="FAC999")
        with patch("reconciliation.global_control.campaign_controls", wraps=campaign_controls) as calculate:
            self.confirm()
        self.assertTrue(calculate.called)
        for call in calculate.call_args_list:
            self.assertIsNotNone(call.kwargs.get("keys"))
            self.assertNotIn(untouched.key, call.kwargs["keys"])
        control = self.campaign.global_controls.get(data__identity__parts__2="FAC123")
        version = control.current_version
        from django.db import transaction
        with transaction.atomic():
            recalculate(self.campaign, affected_keys(self.inventory()))
        control.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(control.current_version, version)
        self.assertEqual(untouched.current_version, 0)

    def test_new_campaign_carries_identical_manual_link(self):
        """Les sources identiques reprennent le lien sans modifier la campagne d'origine."""
        self.confirm()
        first = self.campaign
        old_source = self.inventory().data
        self.campaign = self.load()
        self.assertTrue(self.inventory().inventory_match.active)
        frozen = self.campaign.reviews.get(source__source_id="S")
        self.assertTrue(frozen.decision["current"])
        self.assertTrue(self.inventory().business_events.filter(kind="CARRY").exists())
        self.assertTrue(first.reviews.get(source__source_id="S").decision["current"])
        self.assertEqual(old_source, self.inventory().data)

    def test_ui_preview_has_no_side_effects_and_formats_amounts(self):
        """GET et récapitulatif sont en lecture seule ; les données hors portefeuille restent masquées."""
        row = self.inventory()
        url = reverse("reconciliation:inventory-detail", args=[row.pk])
        response = self.client.get(url)
        self.assertContains(response, "Montant retenu pour le rapprochement")
        self.assertContains(response, "Rechercher une correspondance")
        response = self.client.post(url, {"action": "preview", "version": 0, "request_id": str(uuid4()), "entries": [self.entry().pk]})
        self.assertContains(response, "Récapitulatif avant confirmation")
        self.assertEqual(CampaignAction.objects.count(), 0)
        outsider = User.objects.create_user("no-right")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_manual_ods_keeps_composite_identity_and_lot1_auto_rule(self):
        """Un lien ODS explicite ne devient pas une nouvelle auto-validation par numéro de pièce."""
        row = self.inventory("O")
        ods = self.campaign.sage_inventory.get(document="ODG-SAGE")
        original = self.campaign.global_controls.get(key=ods.control_key).data
        self.assertTrue(original["auto_validated"])
        confirm_inventory_link(row.pk, self.user, entry_ids=[ods.pk], comment="Groupe ODS vérifié", expected_version=0)
        current = self.campaign.global_controls.get(key=ods.control_key).current_data
        self.assertEqual(current["state"], "EQUILIBRE")
        self.assertEqual(current["identity"]["strategy"], "ODS_ODG_BY_GROUP")
        self.assertFalse(current["auto_validated"])

    def add_sage_variant(self, records, *, document="FAC456", project="P", year=2026):
        """Ajoute une écriture fictive complète sans créer de candidat moteur.

        La nouvelle référence est recalculée selon l'identité Lot 1 ; les
        compteurs d'extraction sont actualisés avant signature par load.
        """
        source = next(r["data"]["entry"] for r in records if r.get("type") == "sage_inventory" and r["data"]["entry"]["amount"] == "4000")
        entry = {**source, "document": document, "project_code": project, "fiscal_year": year, "date": f"{year}-01-01"}
        entry["ref"] = digest([entry[k] for k in ("project_code", "fiscal_year", "document", "journal", "line", "analytic_line")])
        record = inventory_record(entry, records[0]["sage_exclusions"])
        position = next(i for i, r in enumerate(records) if r.get("type") == "proposal")
        records.insert(position, {"type": "sage_inventory", "data": record})
        records[0]["load_quality"]["sage"]["rows_final"] += 1

    def test_transfer_recalculates_both_old_and_new_piece(self):
        """Transférer une affectation rétablit l'écart de l'ancienne pièce et équilibre la nouvelle."""
        records = copy.deepcopy(self.records)
        self.add_sage_variant(records)
        self.campaign = self.load(records)
        self.confirm()
        target = self.campaign.sage_inventory.get(document="FAC456")
        self.confirm(entries=[target.pk], replace=True)
        self.assertEqual(Decimal(self.result("FAC123")["gap"]), Decimal("-4000"))
        self.assertEqual(self.result("FAC456")["state"], "EQUILIBRE")
        self.assertEqual(ManualAllocation.objects.filter(active=True).count(), 1)
        row = self.inventory()
        cancel_inventory_link(row.pk, self.user, expected_version=row.business_version)
        self.assertEqual(Decimal(self.result("FAC456")["gap"]), Decimal("-4000"))

    def test_one_atlas_to_several_whole_entries_counts_each_once(self):
        """Une ligne de 10000 peut choisir 6000 + 4000 sans répéter un total de pièce."""
        records = copy.deepcopy(self.records)
        # Ne pas confondre l'existant Comptabilisé avec une nouvelle contribution.
        for r in records:
            if r.get("type") == "inventory" and r["atlas"]["Id"] == "C":
                r["atlas"]["Total charges SAGE (€)"] = "0"
            if r.get("type") == "inventory" and r["atlas"]["Id"] == "S":
                r["atlas"]["Total charges projet (€)"] = "10000"
            if r.get("type") == "proposal":
                r["atlas"][0]["Total charges projet (€)"] = "10000"
        self.campaign = self.load(records)
        self.confirm(entries=[self.entry("6000").pk, self.entry("4000").pk])
        self.assertEqual(Decimal(self.result()["confirmed_sent_total"]), Decimal("10000"))
        self.assertEqual(self.result()["state"], "EQUILIBRE")
        self.assertEqual(ManualAllocation.objects.filter(active=True).count(), 2)

    def test_same_entry_cannot_be_confirmed_by_another_line(self):
        """Une seconde ligne ne peut consommer la référence réservée, même sur une pièce partagée."""
        records = copy.deepcopy(self.records)
        original = next(r for r in records if r.get("type") == "proposal")
        raw = {**original["atlas"][0], "Id": "S2"}
        records.insert(1, {"type": "inventory", "atlas": raw})
        position = next(i for i, r in enumerate(records) if r.get("type") == "control")
        records.insert(position, {**original, "key": digest(["S2"]), "atlas": [raw]})
        records[-1]["complete"] += 1
        self.campaign = self.load(records)
        self.confirm()
        with self.assertRaisesMessage(ValidationError, "déjà affectée"):
            self.confirm(source="S2")
        self.assertEqual(ManualAllocation.objects.filter(active=True).count(), 1)

    def test_other_campaign_project_and_exercise_are_not_searchable(self):
        """Les filtres de portée s'appliquent aussi aux identifiants POST fabriqués."""
        entry = self.entry()
        for field, value in (("fiscal_year", 2025), ("project_code", "OTHER")):
            with self.subTest(field=field):
                CampaignSageEntry.objects.filter(pk=entry.pk).update(**{field: value})
                self.assertNotIn(entry.pk, search_sage(self.inventory(), self.user).values_list("pk", flat=True))
                with self.assertRaises(ValidationError):
                    self.confirm(entries=[entry.pk])
                CampaignSageEntry.objects.filter(pk=entry.pk).update(**{field: getattr(entry, field)})
        old = self.campaign
        self.campaign = self.load()
        self.assertNotIn(entry.pk, search_sage(self.inventory(), self.user).values_list("pk", flat=True))
        with self.assertRaises(ValidationError):
            self.confirm(entries=[entry.pk])
        self.assertFalse(Campaign.objects.get(pk=old.pk).is_current)

    def test_form_post_correction_and_confirmation_are_audited(self):
        """Exerce les vrais formulaires : format français, motif, UUID et lien manuel."""
        row = self.inventory()
        url = reverse("reconciliation:inventory-detail", args=[row.pk])
        response = self.client.post(url, {"action": "correct", "version": 0, "request_id": str(uuid4()),
                                         "reason": "AMOUNT", "amount": "4000,00", "comment": "Montant vérifié"})
        self.assertEqual(response.status_code, 302)
        row = self.inventory()
        response = self.client.post(url, {"action": "confirm", "version": row.business_version,
                                         "request_id": str(uuid4()), "entries": [self.entry().pk], "comment": "Facture vérifiée"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.result()["state"], "EQUILIBRE")
        self.assertEqual(CampaignAction.objects.filter(inventory=row).count(), 2)

    def test_multiple_ods_candidates_can_be_resolved_by_explicit_whole_selection(self):
        """Un groupe déjà équilibré accepte un lien explicite sans altérer son diagnostic initial."""
        records = copy.deepcopy(self.records)
        source = next(r["data"]["entry"] for r in records if r.get("type") == "sage_inventory" and r["data"]["entry"]["document"] == "ODG-SAGE")
        entry = {**source, "document": "ODS-SECOND"}
        entry["ref"] = digest([entry[k] for k in ("project_code", "fiscal_year", "document", "journal", "line", "analytic_line")])
        record = inventory_record(entry, records[0]["sage_exclusions"])
        records.insert(next(i for i, r in enumerate(records) if r.get("type") == "proposal"), {"type": "sage_inventory", "data": record})
        records[0]["load_quality"]["sage"]["rows_final"] += 1
        for r in records:
            if r.get("type") == "inventory" and r["atlas"]["Id"] == "O":
                r["atlas"]["Total charges SAGE (€)"] = "200"
            if r.get("type") == "control" and r["data"]["key"] == record["control_key"]:
                r["data"]["entries"].append(entry)
        self.campaign = self.load(records)
        control = self.campaign.global_controls.get(key=record["control_key"])
        self.assertEqual(control.data["state"], "EQUILIBRE")
        row = self.inventory("O")
        ids = list(self.campaign.sage_inventory.filter(control_key=record["control_key"]).values_list("pk", flat=True))
        confirm_inventory_link(row.pk, self.user, entry_ids=ids, comment="Les deux écritures justifient cette charge", expected_version=0)
        control.refresh_from_db()
        self.assertEqual(control.current_data["state"], "EQUILIBRE")
        self.assertFalse(control.current_data["auto_validated"])
        self.assertEqual(control.data["state"], "EQUILIBRE")

    def test_old_campaign_without_sage_inventory_displays_unavailable(self):
        """Un historique sans capacité Sage ne présente pas de faux zéro ni recherche hors preuve."""
        row = self.inventory()
        self.campaign.metadata = {"schema_version": 2}
        self.campaign.save(update_fields=["metadata"])
        response = self.client.get(reverse("reconciliation:inventory-detail", args=[row.pk]))
        self.assertContains(response, "Contrôle global indisponible pour cette campagne")
        with self.assertRaisesMessage(ValidationError, "indisponible"):
            confirm_inventory_link(row.pk, self.user, entry_ids=[self.entry().pk], comment="Tentative", expected_version=0)

    def test_correction_invalidates_export_freshness_without_overwriting_decision(self):
        """Une correction explicite conserve l'auteur/type de décision mais empêche un export périmé."""
        self.confirm()
        line = LineReview.objects.select_related("transaction__project", "group").get(transaction__source_id="S")
        old_state, old_source = line.state, line.validation_source
        row = self.inventory()
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="3500", expected_version=row.business_version)
        line.refresh_from_db()
        from .review import is_current
        self.assertEqual((line.state, line.validation_source), (old_state, old_source))
        self.assertFalse(is_current(line))
        event = row.business_events.order_by("-pk").first()
        self.assertTrue(event.before["controls"])
        self.assertTrue(event.after["controls"])

    def test_large_unrelated_inventory_does_not_expand_confirmation_queries(self):
        """2000 pièces supplémentaires ne déclenchent ni calcul complet ni N+1 lors d'un clic."""
        source = self.entry().data["entry"]
        rows = []
        for i in range(2000):
            entry = {**source, "document": f"FAC-BENCH-{i}"}
            entry["ref"] = digest([entry[k] for k in ("project_code", "fiscal_year", "document", "journal", "line", "analytic_line")])
            data = inventory_record(entry, self.campaign.metadata["sage_exclusions"])
            rows.append(CampaignSageEntry(campaign=self.campaign, record_id=data["record_id"], entry_ref=entry["ref"],
                        project_code="P", fiscal_year=2026, document=entry["document"], control_key=data["control_key"],
                        amount=Decimal(entry["amount"]), data=data))
        CampaignSageEntry.objects.bulk_create(rows, batch_size=500)
        with CaptureQueriesContext(connection) as queries, patch("reconciliation.global_control.campaign_controls", wraps=campaign_controls) as calculate:
            self.confirm()
        self.assertLess(len(queries), 90)
        self.assertTrue(all(call.kwargs.get("keys") is not None and len(call.kwargs["keys"]) <= 2 for call in calculate.call_args_list))
        self.assertEqual(self.result()["state"], "EQUILIBRE")

    def test_corrected_auto_is_not_automatically_reactivated_in_next_campaign(self):
        """La correction persiste mais ne réactive jamais à elle seule une décision AUTO."""
        records = copy.deepcopy(self.records)
        next(r for r in records if r.get("type") == "proposal")["auto_validation"] = {
            "source": "AUTO", "rule": "MATCH_EXACT", "state": "VALIDATED"}
        self.campaign = self.load(records)
        line = LineReview.objects.get(transaction__source_id="S")
        self.assertEqual(line.validation_source, "AUTO")
        row = self.inventory()
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="3500", expected_version=0)
        self.campaign = self.load(records)
        self.assertEqual(self.inventory().adjustment.amount, Decimal("3500"))
        self.assertFalse(self.campaign.reviews.get(source__source_id="S").decision["current"])
        self.assertEqual(Decimal(self.result()["confirmed_sent_total"]), Decimal(0))

    def test_manual_export_contains_actual_inventory_allocations(self):
        """L'export de campagne conserve l'origine manuelle et les cibles hors moteur."""
        from io import BytesIO
        from openpyxl import load_workbook
        self.confirm()
        response = self.client.get(reverse("reconciliation:campaign-export", args=[self.campaign.pk]))
        book = load_workbook(BytesIO(response.content))
        rows = list(book.active.values)
        self.assertTrue(any(value == "INVENTORY_MANUAL" for value in rows[1]))
        self.assertTrue(any(isinstance(value, str) and '"document": "FAC123"' in value for value in rows[1]))
        book.close()

    def test_amount_correction_persists_on_identical_sources_over_three_campaigns(self):
        """Une correction seule persiste sans fabriquer une confirmation Sage."""
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="5000", expected_version=0)
        first = self.campaign
        for _ in range(2):
            self.campaign = self.load()
            self.assertEqual(retained_amount(self.inventory("C")), Decimal("5000"))
            self.assertTrue(self.inventory("C").business_events.filter(kind="CARRY").exists())
        self.assertEqual(first.inventory.get(source_id="C").adjustment.amount, Decimal("5000"))
        self.assertIsNone(getattr(self.inventory("C"), "inventory_match", None))

    def test_changed_atlas_proposes_correction_and_keeps_it_visible_next_time(self):
        """Un montant source changé suspend la reprise et préremplit une proposition lisible."""
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="5000", expected_version=0)
        records = copy.deepcopy(self.records)
        next(r for r in records if r.get("type") == "inventory" and r["atlas"]["Id"] == "C")["atlas"]["Total charges SAGE (€)"] = "6100"
        for _ in range(2):
            self.campaign = self.load(records)
            row = self.inventory("C")
            self.assertIsNone(getattr(row, "adjustment", None))
            self.assertEqual(retained_amount(row), Decimal("6100"))
            response = self.client.get(reverse("reconciliation:inventory-detail", args=[row.pk]))
            self.assertContains(response, "Action précédente à confirmer")
            self.assertEqual(response.context["correction"].initial["amount"], "5000.00")

    def test_cancelled_actions_are_not_revived(self):
        """Une annulation explicite empêche toute résurrection dans une nouvelle extraction."""
        self.confirm()
        row = self.inventory()
        cancel_inventory_link(row.pk, self.user, expected_version=row.business_version)
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="5000", expected_version=0)
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, cancel=True, expected_version=row.business_version)
        self.campaign = self.load()
        self.assertIsNone(getattr(self.inventory(), "inventory_match", None))
        self.assertIsNone(getattr(self.inventory("C"), "adjustment", None))
        self.assertFalse(self.campaign.inventory.filter(business_events__kind="CARRY").exists())

    def test_duplicate_without_witness_requires_confirmation(self):
        """Une exclusion de doublon sans autre ligne identique n'est jamais reconduite seule."""
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, reason="DUPLICATE", expected_version=0)
        self.campaign = self.load()
        self.assertIsNone(getattr(self.inventory("C"), "adjustment", None))
        self.assertTrue(self.inventory("C").business_events.filter(kind="CARRY_PENDING").exists())

    def test_carry_without_author_rights_becomes_pending(self):
        """Le retrait du portefeuille interdit la reprise et laisse une proposition sans affectation."""
        self.confirm()
        from projects.models import ProjectPortfolio
        ProjectPortfolio.objects.filter(user=self.user).delete()
        self.campaign = self.load()
        self.assertIsNone(getattr(self.inventory(), "inventory_match", None))
        self.assertTrue(self.inventory().business_events.filter(kind="CARRY_PENDING").exists())

    def test_replaying_carry_does_not_duplicate_allocations_or_audit(self):
        """Un second appel sur la même campagne ne réapplique aucune action déjà reprise."""
        from .business_carry import carry_business_actions
        self.confirm()
        self.campaign = self.load()
        count = CampaignAction.objects.count()
        allocations = ManualAllocation.objects.count()
        carry_business_actions(self.campaign)
        self.assertEqual(CampaignAction.objects.count(), count)
        self.assertEqual(ManualAllocation.objects.count(), allocations)

    def test_changed_sage_or_ambiguous_content_never_reuses_the_link(self):
        """Une modification Sage ou deux copies métier empêchent la reprise complète."""
        from .business_carry import carry_business_actions
        self.confirm()
        with patch("reconciliation.business_carry.carry_business_actions"):
            self.campaign = self.load()
        entry = self.entry()
        entry.data["entry"]["label"] = "Libellé changé"
        entry.save(update_fields=["data"])
        carry_business_actions(self.campaign)
        self.assertIsNone(getattr(self.inventory(), "inventory_match", None))
        self.assertTrue(self.inventory().business_events.filter(kind="CARRY_PENDING").exists())
        count = CampaignAction.objects.count()
        carry_business_actions(self.campaign)
        self.assertEqual(CampaignAction.objects.count(), count)

    def test_ambiguous_sage_content_requires_confirmation(self):
        """Deux écritures au même contenu ne fournissent pas une identité unique."""
        from .business_carry import carry_business_actions
        self.confirm()
        with patch("reconciliation.business_carry.carry_business_actions"):
            self.campaign = self.load()
        entry = self.entry()
        entry.pk = None
        entry.record_id = digest([entry.record_id, "collision fictive"])
        entry.entry_ref = digest([entry.entry_ref, "autre référence"])
        entry.save(force_insert=True)
        carry_business_actions(self.campaign)
        self.assertIsNone(getattr(self.inventory(), "inventory_match", None))
        self.assertTrue(self.inventory().business_events.filter(kind="CARRY_PENDING").exists())

    def test_whole_selection_and_corrections_are_carried_together(self):
        """Deux écritures entières sont reprises après la correction du Comptabilisé voisin."""
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="0", expected_version=0)
        row = self.inventory()
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="10000", expected_version=0)
        self.confirm(entries=list(self.campaign.sage_inventory.filter(document="FAC123").values_list("pk", flat=True)))
        self.campaign = self.load()
        row = self.inventory()
        self.assertEqual(row.adjustment.amount, Decimal("10000"))
        self.assertEqual(row.inventory_match.allocations.filter(active=True).count(), 2)
        self.assertEqual(self.result()["state"], "EQUILIBRE")

    def test_insufficient_capacity_rolls_back_correction_and_link_carry(self):
        """Un Comptabilisé voisin augmenté refuse le lien sans laisser de correction partielle."""
        row = self.inventory()
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="4000", expected_version=0)
        self.confirm()
        records = copy.deepcopy(self.records)
        next(r for r in records if r.get("type") == "inventory" and r["atlas"]["Id"] == "C")["atlas"]["Total charges SAGE (€)"] = "7000"
        self.campaign = self.load(records)
        row = self.inventory()
        self.assertIsNone(getattr(row, "adjustment", None))
        self.assertIsNone(getattr(row, "inventory_match", None))
        self.assertEqual(row.business_version, 0)
        self.assertTrue(row.business_events.filter(kind="CARRY_PENDING").exists())

    def test_duplicate_witness_must_still_exist(self):
        """L'exclusion persiste avec son témoin identique puis s'arrête lorsque celui-ci disparaît."""
        records = copy.deepcopy(self.records)
        clone = copy.deepcopy(next(r for r in records if r.get("type") == "inventory" and r["atlas"]["Id"] == "C"))
        clone["atlas"]["Id"] = "C2"
        records.insert(2, clone)
        self.campaign = self.load(records)
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, reason="DUPLICATE", expected_version=0)
        self.campaign = self.load(records)
        self.assertEqual(retained_amount(self.inventory("C")), Decimal(0))
        self.campaign = self.load()
        self.assertIsNone(getattr(self.inventory("C"), "adjustment", None))
        self.assertTrue(self.inventory("C").business_events.filter(kind="CARRY_PENDING").exists())

    def test_legacy_validation_cannot_bypass_inventory_capacity_with_a_comment(self):
        """Un bouton historique ne contourne pas la capacité fiable du Lot 2 par dérogation."""
        line = LineReview.objects.select_related("transaction__project", "group", "campaign").get(transaction__source_id="S")
        values = {k: {"mode": "SET", "value": v} for k, v in {
            "status": "Comptabilisé", "amount": "5000", "document": "FAC123", "date": "2026-01-01"}.items()}
        with self.assertRaisesMessage(ValidationError, "Affectation impossible"):
            decide(line.pk, self.user, state="VALIDATED", values=values, comment="Tentative de dépassement",
                   expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line),
                   acknowledge=True, multiple_confirm=True)
        line.refresh_from_db()
        self.assertEqual((line.state, line.version), ("DRAFT", 0))
        self.assertEqual(CampaignAction.objects.count(), 0)

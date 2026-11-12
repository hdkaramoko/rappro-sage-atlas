"""Recette intégrée moteur → JSONL → décisions, sur sources entièrement fictives."""

import json
import subprocess
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio
from .models import Campaign, ControlContribution, LineReview
from .multiple_review import candidates_for, selection_values
from .review import decide, signature, effective
from .review_import import import_bundle


class BapDecisionTests(TestCase):
    """Vérifie les preuves, réservations, historiques et préremplissages côté serveur."""

    @classmethod
    def setUpClass(cls):
        """Génère les deux campagnes du témoin hors ORM, dans un dossier jetable."""
        super().setUpClass()
        cls.folder = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        completed = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.matching_bap_fixture", cls.folder.name],
            cwd=root, capture_output=True, text=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        cls.comparison = json.loads((Path(cls.folder.name) / "comparison.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        """Libère les seuls fichiers de recette, sans toucher aux extractions réelles."""
        cls.folder.cleanup()
        super().tearDownClass()

    def setUp(self):
        """Crée les droits de recette puis importe le nouveau JSONL dans la base jetable."""
        self.user = User.objects.create_user("reviewer")
        project = Project.objects.create(code="17GEF0C086", label="Projet fictif")
        ProjectPortfolio.objects.create(user=self.user, project=project)
        self.client.force_login(self.user)
        self.load("after")

    def load(self, name):
        """Importe le JSONL fictif nommé et retourne sa campagne courante, sans réévaluation."""
        import_bundle(Path(self.folder.name) / f"{name}.jsonl")
        return Campaign.objects.get(is_current=True)

    def line(self, identifier="R1"):
        """Charge une revue courante et ses relations nécessaires à la signature."""
        return LineReview.objects.select_related("transaction__project", "group", "campaign").get(transaction__source_id=identifier)

    def choose(self, identifier, reference, **changes):
        """Valide une sélection avec champs à Conserver, rechargés et calculés par le service.

        `changes` surcharge les arguments pour tester falsification/concurrence.
        Une ValidationError annule toutes les écritures dans la base de recette.
        """
        line = self.line(identifier)
        values = {name: {"mode": "KEEP"} for name in ("status", "amount", "document", "date")}
        values["status"] = {"mode": "SET", "value": "Comptabilisé"}
        return decide(line.pk, self.user, state="VALIDATED", values=values, comment="Affectation vérifiée",
            expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line),
            manual_refs=[reference], manual_confirm=True, multiple_confirm=True, acknowledge=True, **changes)

    def test_import_real_new_rules_and_unique_allocations(self):
        """Les quatre AUTO restent uniques ; les 400 Sage non rapprochés entrent désormais dans le cadrage."""
        campaign = Campaign.objects.get(is_current=True)
        self.assertEqual(campaign.reviews.filter(decision__validation_source="AUTO").count(), 4)
        self.assertEqual(self.line("1681313").group.rule, "MATCH_BAP")
        self.assertEqual(self.line("1681314").group.rule, "MATCH_BAP")
        self.assertEqual(self.line("I").group.rule, "MATCH_INDIVIDUAL")
        self.assertEqual(self.line("W").auto_validation_rule, "MATCH_WITHOUT_LABEL")
        self.assertEqual(self.line().state, "DRAFT")
        contributions = list(ControlContribution.objects.filter(control__campaign=campaign))
        refs = [ref for c in contributions for ref in c.entries]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertEqual(sum((c.amount for c in contributions), Decimal(0)), Decimal("2004.91"))
        for contribution in contributions:
            self.assertEqual(contribution.amount, effective(contribution.line)["amount"])
        from .accounting_models import AccountingProject
        accounting = AccountingProject.objects.get(campaign=campaign)
        self.assertEqual(accounting.atlas, Decimal("2004.91"))
        self.assertEqual(accounting.sage, Decimal("2454.91"))
        self.assertEqual(accounting.gap, Decimal("-450.00"))
        shared_piece = [c for c in contributions if c.line.transaction.source_id in ("1681313", "1681314")]
        self.assertEqual(shared_piece[0].control_id, shared_piece[1].control_id)
        self.assertNotEqual(shared_piece[0].entries, shared_piece[1].entries)

    def test_selection_prefills_before_required_field_validation_and_no_reuse(self):
        """Une sélection remplit montant/pièce/date ; une autre ligne ne peut pas la reprendre."""
        refs = list(candidates_for(self.line()))
        self.choose("R1", refs[0])
        resolved = effective(self.line())
        self.assertEqual(resolved["amount"], Decimal("200"))
        self.assertEqual(resolved["document"], "FAC4")
        self.assertEqual(resolved["date"], "2026-04-20")
        with self.assertRaisesMessage(ValidationError, "déjà affectée"):
            self.choose("R2", refs[0])
        self.choose("R2", refs[1])
        self.assertEqual(self.line("R2").state, "VALIDATED")
        self.assertNotEqual(self.line().manual_assignment[0]["ref"], self.line("R2").manual_assignment[0]["ref"])

    def test_post_tampered_amount_and_foreign_ref_leave_no_mutation(self):
        """Le POST ne peut ni imposer un montant différent ni sélectionner une référence inventée."""
        line = self.line()
        url = reverse("reconciliation:review-detail", args=[line.pk])
        payload = dict(action="VALIDATED", version=line.version, group_version=line.group.version,
            source=signature(line), status_mode="SET", status="Comptabilisé", amount_mode="SET", amount="999,00",
            document_mode="KEEP", date_mode="KEEP", manual_refs=[next(iter(candidates_for(line)))], comment="Vérifié")
        response = self.client.post(url, payload)
        self.assertContains(response, "somme Sage")
        self.assertEqual(self.line().version, 0)
        payload.update(manual_refs=["invented"], amount="200")
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.line().version, 0)

    def test_decimal_multiselection_zero_negative_and_ambiguous_dates(self):
        """La somme serveur garde neuf décimales, les signes et zéro ; les dates ambiguës sont refusées."""
        line = self.line()
        entry = next(iter(candidates_for(line).values()))
        values = {name: {"mode": "KEEP"} for name in ("amount", "document", "date", "status")}
        sources = [{**entry, "amount": "600"}, {**entry, "amount": "400.123456789"}]
        total = selection_values(line, values, sources)
        self.assertEqual(total["amount"]["value"], "1000.123456789")
        for amounts, expected in ((("-600", "-400"), "-1000"), (("0", "0"), "0")):
            selected = [{**entry, "amount": amount} for amount in amounts]
            self.assertEqual(Decimal(selection_values(line, values, selected)["amount"]["value"]), Decimal(expected))
        sources[1]["date"] = "2026-04-21"
        with self.assertRaisesMessage(ValidationError, "Plusieurs dates"):
            selection_values(line, values, sources)
        with self.assertRaisesMessage(ValidationError, "Aucune écriture"):
            selection_values(line, values, [], ["amount"])

    def test_bap_global_balance_is_rechecked_at_import(self):
        """Une autorisation BAP falsifiée sur le résiduel déséquilibré ne réserve rien."""
        from .test_sage_inventory import sign_records
        from .review import is_current
        records = [json.loads(row) for row in (Path(self.folder.name) / "after.jsonl").read_text(encoding="utf-8").splitlines()]
        records[0]["name"] = "BAP incohérent synthétique"
        proposal = next(r for r in records if r.get("type") == "proposal" and r["atlas"][0]["Id"] == "I")
        proposal["rule"] = proposal["auto_validation"]["rule"] = "MATCH_BAP"
        sign_records(records)
        path = Path(self.folder.name) / "invalid-bap.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        import_bundle(path)
        line = self.line("I")
        self.assertFalse(is_current(line))
        self.assertFalse(ControlContribution.objects.filter(control__campaign=line.campaign, line=line).exists())
        self.assertIn("BAP non équilibré", " ".join(line.campaign_reviews.get(campaign=line.campaign).reasons))

    def test_selected_entries_cannot_exceed_piece_capacity(self):
        """Même confirmé/commenté, un dépassement de capacité ne réserve pas une écriture entière."""
        line = self.line()
        ref = next(iter(candidates_for(line)))
        control = line.campaign.controls.get(data__identity__parts__2="FAC4")
        control.data["atlas"] = [{"total_sage_charges": "400", "source_id": "ALREADY_ACCOUNTED"}]
        control.save(update_fields=["data"])
        with self.assertRaisesMessage(ValidationError, "capacité Sage"):
            self.choose("R1", ref)
        self.assertEqual(self.line().version, 0)

    def test_comparison_keeps_source_totals_and_historical_decisions(self):
        """Les décisions changent avec les preuves, jamais les totaux source ni l'histoire de campagne."""
        after = Campaign.objects.get(is_current=True)
        source_total = sum((Decimal(c.data["sage_total"]) for c in after.global_controls.all()), Decimal(0))
        old_decisions = list(after.reviews.values_list("decision", flat=True))
        before = self.load("before")
        self.assertEqual(source_total, sum((Decimal(c.data["sage_total"]) for c in before.global_controls.all()), Decimal(0)))
        self.assertEqual(list(after.reviews.values_list("decision", flat=True)), old_decisions)
        self.assertEqual(self.comparison["after"]["auto_lines"] - self.comparison["before"]["auto_lines"], 4)

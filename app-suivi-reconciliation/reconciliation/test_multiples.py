"""Tests intégrés : sortie réelle du moteur sur données fictives, jamais sur la base métier."""

import copy
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from openpyxl import load_workbook
from reconciliation_contract import control_identity, entry_from_sage, snapshot

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .models import Campaign, ControlContribution, LineReview, MultipleControl
from .multiple_review import candidates_for, review_control
from .review import decide, signature
from .review_import import import_bundle


class MultipleTests(TestCase):
    """Vérifie les décisions, reports et exports avec deux groupes sur une même pièce."""

    @classmethod
    def setUpClass(cls):
        """Génère une seule fois le JSONL via la CLI installée du moteur."""
        super().setUpClass()
        cls.folder = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                str(root / ".venv/Scripts/python.exe"),
                "-m",
                "examples.multiples_fixture",
                cls.folder.name,
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.records = [
            json.loads(line)
            for line in (Path(cls.folder.name) / "campaign.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]

    @classmethod
    def tearDownClass(cls):
        """Supprime uniquement les fichiers fictifs temporaires du test."""
        cls.folder.cleanup()
        super().tearDownClass()

    def setUp(self):
        """Crée un utilisateur et son portefeuille dans la base de test Django."""
        self.user = User.objects.create_user("reviewer")
        project = Project.objects.create(code="P", label="Projet test")
        ProjectPortfolio.objects.create(user=self.user, project=project)
        self.client.force_login(self.user)
        self.load()

    def load(self, records=None):
        """Importe atomiquement une variante du fichier fictif."""
        path = Path(self.folder.name) / "input.jsonl"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in (records or self.records)),
            encoding="utf-8",
        )
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def recount(self, records):
        """Actualise les compteurs d'une variante valide de la photographie."""
        from collections import Counter

        records[-1].update(
            complete=sum(r.get("type") == "proposal" for r in records),
            inventory_count=sum(r.get("type") == "inventory" for r in records),
            control_count=sum(r.get("type") == "control" for r in records),
            control_statuses=dict(
                Counter(r["data"]["status"] for r in records if r.get("type") == "control")
            ),
        )
        return records

    def validate(self, source="A", **kwargs):
        """Soumet une décision avec la fraîcheur réellement courante."""
        line = LineReview.objects.select_related("transaction__project", "group", "campaign").get(
            transaction__source_id=source
        )
        values = {
            k: {"mode": "SET", "value": v}
            for k, v in {
                "status": "Comptabilisé",
                "amount": "60",
                "document": "D",
                "date": "2026-01-01",
            }.items()
        }
        options = {
            "state": "VALIDATED",
            "values": values,
            "comment": "Vérification métier",
            "acknowledge": True,
            **kwargs,
        }
        return decide(
            line.pk,
            self.user,
            expected_version=line.version,
            expected_group_version=line.group.version,
            expected_source=signature(line),
            **options,
        )

    def test_source_plus_two_groups_refusal_and_reapplication(self):
        """La seconde validation ne peut ignorer la première ; un refus libère sa contribution."""
        self.validate("A")
        with self.assertRaisesMessage(ValidationError, "projeté 160"):
            self.validate("B")
        self.validate("B", multiple_confirm=True)
        self.assertEqual(ControlContribution.objects.count(), 2)
        self.validate("A", state="REJECTED")
        self.assertEqual(ControlContribution.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.validate("A")
        self.validate("A", multiple_confirm=True)

    def test_manual_selection_is_separate_and_fresh(self):
        """L'affectation ne réécrit jamais le statut moteur et exige confirmation/commentaire."""
        line = LineReview.objects.select_related("campaign", "group").get(
            transaction__source_id="A"
        )
        refs = list(candidates_for(line))
        with self.assertRaises(ValidationError):
            self.validate(manual_refs=["invented"], manual_confirm=True)
        with self.assertRaises(ValidationError):
            self.validate(manual_refs=refs)
        result = self.validate(manual_refs=refs, manual_confirm=True, multiple_confirm=True)
        self.assertEqual(len(result.manual_assignment), 1)
        self.assertEqual(result.group.match_status, "MATCHED")
        self.assertTrue(result.multiple_diagnostic["derogation"])

    def test_validate_button_accepts_manual_assignment_and_risk_without_checkboxes(self):
        """Le POST Valider suffit ; preuves, justification et dérogation restent historisées."""
        self.validate("A")
        line = LineReview.objects.select_related("campaign", "group", "transaction").get(
            transaction__source_id="B"
        )
        url = reverse("reconciliation:review-detail", args=[line.pk])
        response = self.client.get(url)
        self.assertNotContains(response, 'name="manual_confirm"')
        self.assertNotContains(response, 'name="multiple_confirm"')
        data = {
            "action": "VALIDATED",
            "version": line.version,
            "group_version": line.group.version,
            "source": signature(line),
            "manual_refs": list(candidates_for(line)),
            "comment": "",
        }
        for field, value in {
            "status": "Comptabilisé",
            "amount": "60",
            "document": "D",
            "date": "2026-01-01",
        }.items():
            data[field + "_mode"] = "SET"
            data[field] = value
        self.assertEqual(self.client.post(url, data).status_code, 200)
        line.refresh_from_db()
        self.assertEqual(line.state, "DRAFT")
        data["comment"] = "Pièce partagée vérifiée par le métier"
        self.assertEqual(self.client.post(url, data).status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.state, "VALIDATED")
        event = line.events.get().snapshot
        self.assertEqual(event["matching_decision"], "MANUAL_MATCH")
        self.assertTrue(event["multiple_diagnostic"]["derogation"])
        self.assertEqual(event["comment"], data["comment"])

    def test_identical_campaign_carries_and_collective_excess_invalidates_all(self):
        """Un report sûr est conservé ; un risque collectif invalide toutes les reprises."""
        self.validate()
        campaign = self.load()
        self.assertEqual(campaign.reviews.get(source__source_id="A").comparison, "CARRIED")
        self.validate("B", multiple_confirm=True)
        campaign = self.load()
        self.assertEqual(campaign.reviews.filter(comparison="CARRIED").count(), 0)
        self.assertEqual(ControlContribution.objects.filter(control__campaign=campaign).count(), 0)

    def test_materialization_and_new_source_invalidates_remaining_claim(self):
        """Une validation devenue Comptabilisé n'est plus ajoutée comme contribution projetée."""
        self.validate()
        records = copy.deepcopy(self.records)
        for r in records:
            if r.get("type") == "inventory" and r["atlas"]["Id"] == "A":
                r["atlas"].update(
                    {
                        "Statut BAP": "Comptabilisé",
                        "Total charges SAGE (€)": "60.00",
                        "N° pièce SAGE": "D",
                        "Date comptable": "2026-01-01",
                    }
                )
        records = [
            r for r in records if not (r.get("type") == "proposal" and r["atlas"][0]["Id"] == "A")
        ]
        control = next(
            r["data"] for r in records if r.get("type") == "control" and r["data"]["entries"]
        )
        new = dict(
            control["atlas"][0],
            source_id="A",
            total_sage_charges="60.00",
            total_project_charges="60.00",
        )
        new["bap_status"] = "Comptabilisé"
        control.update(
            snapshot(
                control["identity"],
                control["atlas"] + [new],
                control["entries"],
                amount_field="total_sage_charges",
            )
        )
        records[-1]["complete"] = 1
        campaign = self.load(records)
        self.assertFalse(ControlContribution.objects.filter(control__campaign=campaign).exists())
        with self.assertRaisesMessage(ValidationError, "projeté 160"):
            self.validate("B")

    def test_truncated_bad_counter_and_missing_control_roll_back(self):
        """Un import défectueux conserve la campagne et les réservations courantes."""
        current = Campaign.objects.get(is_current=True)
        for records in (self.records[:-1], [r for r in self.records if r.get("type") != "control"]):
            with self.assertRaises(ValidationError):
                self.load(records)
            self.assertEqual(Campaign.objects.get(is_current=True).pk, current.pk)
        altered = copy.deepcopy(self.records)
        next(r["data"] for r in altered if r.get("type") == "control")["atlas_total"] = "999"
        with self.assertRaises(ValidationError):
            self.load(altered)

    def test_rights_control_history_and_audit_do_not_use_current_projection(self):
        """Les exports anciens conservent commentaire/décision et respectent le portefeuille."""
        first = Campaign.objects.get(is_current=True)
        self.validate(comment="=commentaire littéral")
        control = MultipleControl.objects.filter(
            campaign=first, data__entries__0__document="D"
        ).first()
        review_control(
            control.pk, self.user, state="DISMISSED", comment="Analyse terminée", version=0
        )
        current = self.load()
        self.validate(state="REJECTED", comment="Nouvelle décision")
        response = self.client.get(reverse("reconciliation:campaign-audit", args=[first.pk]))
        self.assertEqual(response.status_code, 200)
        book = load_workbook(BytesIO(response.content))
        self.assertIn("Multiples", book.sheetnames)
        comments = [row[10] for row in book["Décisions"].iter_rows(min_row=2)]
        self.assertTrue(
            any(c.value == "=commentaire littéral" and c.data_type == "s" for c in comments)
        )
        with self.assertRaises(ValidationError):
            review_control(control.pk, self.user, state="CONFIRMED", comment="Ancienne", version=1)
        stranger = User.objects.create_user("stranger")
        with self.assertRaises(PermissionDenied):
            review_control(
                current.controls.first().pk,
                stranger,
                state="CONFIRMED",
                comment="Interdit",
                version=0,
            )
        self.client.force_login(stranger)
        self.assertEqual(
            self.client.get(
                reverse("reconciliation:multiple-detail", args=[control.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("reconciliation:campaign-audit", args=[first.pk])).status_code,
            404,
        )

    def test_select_two_individual_entries_and_changed_proof(self):
        """Deux écritures restent sélectionnables séparément ; leur somme est contrôlée."""
        records = copy.deepcopy(self.records)
        proposal = next(
            r for r in records if r.get("type") == "proposal" and r["atlas"][0]["Id"] == "A"
        )
        raw = proposal["evidence"][0]["rows"][0]
        raw["Charges (Dépenses)"] = 30
        second = dict(raw, **{"N° de ligne Analytique": "02"})
        second["entry_ref"] = entry_from_sage(second)["ref"]
        proposal["evidence"][0]["rows"].append(second)
        control = next(
            r["data"] for r in records if r.get("type") == "control" and r["data"]["entries"]
        )
        entries = [e for e in control["entries"] if e["ref"] != raw["entry_ref"]]
        entries += [entry_from_sage(raw), entry_from_sage(second)]
        control.update(
            snapshot(
                control["identity"], control["atlas"], entries, amount_field="total_sage_charges"
            )
        )
        self.load(self.recount(records))
        line = LineReview.objects.select_related("campaign", "group").get(
            transaction__source_id="A"
        )
        refs = list(candidates_for(line))
        self.assertEqual(len(refs), 2)
        with self.assertRaisesMessage(ValidationError, "somme"):
            self.validate(manual_refs=refs[:1], manual_confirm=True)
        self.validate(manual_refs=refs, manual_confirm=True, multiple_confirm=True)
        campaign = self.load()  # L'écriture analytique 02 a disparu.
        self.assertFalse(campaign.reviews.get(source__source_id="A").decision["current"])

    def test_ods_review_carries_only_identical_group(self):
        """Une revue ODS ne dépend pas d'une égalité intersource de numéro de pièce."""
        from .campaigns import normalize_inventory

        records = copy.deepcopy(self.records)
        raw = dict(
            next(
                r["atlas"]
                for r in records
                if r.get("type") == "inventory" and r["atlas"]["Id"] == "C"
            )
        )
        raw.update({"Id": "ODS-A", "N° pièce SAGE": "ODS-ATLAS", "Libellé ATLAS": "Café Mission"})
        records.insert(1, {"type": "inventory", "atlas": raw})
        source = normalize_inventory(raw, extended=True)
        entry = entry_from_sage(
            {
                "Projet": "P",
                "Numéro pièce": "ODG-SAGE",
                "Date comptable": "2026-01-01",
                "N° de ligne comptable": "001",
                "N° de ligne Analytique": "01",
                "Journal": "ACH",
                "Devise": "EUR",
                "Libellé pièce": "CAFE\u00a0MISSION",
                "Code Tiers - Tiers doc Orig": "001",
                "Charges (Dépenses)": "20",
            }
        )
        data = snapshot(
            control_identity(source), [source], [entry], amount_field="total_sage_charges"
        )
        records.insert(-1, {"type": "control", "data": data})
        campaign = self.load(self.recount(records))
        control = campaign.controls.get(strategy="ODS_ODG_BY_GROUP")
        self.assertEqual(control.status, "EXCESS")
        review_control(
            control.pk,
            self.user,
            state="CONFIRMED",
            comment="Deux opérations à analyser",
            version=0,
        )
        self.assertEqual(
            self.client.get(
                reverse("reconciliation:multiple-detail", args=[control.pk])
            ).status_code,
            200,
        )
        next_campaign = self.load(records)
        self.assertEqual(next_campaign.controls.get(strategy="ODS_ODG_BY_GROUP").state, "CONFIRMED")
        entry["amount"] = "25"
        records[-2]["data"] = snapshot(
            control_identity(source), [source], [entry], amount_field="total_sage_charges"
        )
        newer = self.load(self.recount(records))
        self.assertEqual(newer.controls.get(strategy="ODS_ODG_BY_GROUP").state, "TO_REVIEW")

    def test_unknown_policy_blocks_without_bypassing_and_historical_v2_remains_readable(self):
        """Une confirmation utilisateur ne remplace jamais un calcul impossible."""
        records = copy.deepcopy(self.records)
        records[0]["amount_field"] = None
        for r in records:
            if r.get("type") == "control":
                d = r["data"]
                r["data"] = snapshot(d["identity"], d["atlas"], d["entries"], amount_field=None)
        self.load(self.recount(records))
        with self.assertRaisesMessage(ValidationError, "non fiable"):
            self.validate(multiple_confirm=True)
        self.load()
        self.validate()
        old = [r for r in copy.deepcopy(self.records) if r.get("type") != "control"]
        old[0]["schema_version"] = 2
        old[0]["controls_available"] = False
        for r in old:
            if r.get("type") == "proposal":
                r["schema_version"] = 2
        current = self.load(old)
        self.assertFalse(current.reviews.get(source__source_id="A").decision["current"])
        self.assertContains(
            self.client.get(reverse("reconciliation:multiples", args=[current.pk])),
            "ne contient pas",
        )

    def test_forged_candidate_and_interleaved_inventory_are_rejected(self):
        """Les preuves candidates doivent correspondre au contrôle et respecter l'ordre JSONL."""
        records = copy.deepcopy(self.records)
        proposal = next(r for r in records if r.get("type") == "proposal")
        proposal["evidence"][0]["rows"][0]["Charges (Dépenses)"] = 999
        with self.assertRaisesMessage(ValidationError, "contradictoire"):
            self.load(records)
        records = copy.deepcopy(self.records)
        inventory = records.pop(1)
        records.insert(-1, inventory)
        with self.assertRaises(ValidationError):
            self.load(records)


@skipUnless(connection.vendor == "postgresql", "Verrouillage de lignes : PostgreSQL requis")
class PostgreSQLMultipleConcurrencyTests(TransactionTestCase):
    """Exerce deux connexions réelles ; volontairement ignoré avec SQLite."""

    def test_two_groups_cannot_validate_against_the_same_old_balance(self):
        """Le verrou Campaign sérialise des groupes distincts partageant une pièce."""
        with TemporaryDirectory() as folder:
            root = Path(__file__).resolve().parents[2]
            subprocess.run(
                [
                    str(root / ".venv/Scripts/python.exe"),
                    "-m",
                    "examples.multiples_fixture",
                    folder,
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            import_bundle(Path(folder) / "campaign.jsonl")
            user = User.objects.create_user("concurrent")
            ProjectPortfolio.objects.create(user=user, project=Project.objects.get(code="P"))
            barrier = Barrier(2)

            def attempt(identifier):
                """Soumet sur une connexion indépendante une vue prise avant les deux écritures."""
                try:
                    line = LineReview.objects.select_related(
                        "transaction__project", "group", "campaign"
                    ).get(transaction__source_id=identifier)
                    expected = signature(line)
                    barrier.wait(timeout=10)
                    try:
                        decide(
                            line.pk,
                            User.objects.get(pk=user.pk),
                            state="VALIDATED",
                            values={
                                k: {"mode": "SET", "value": v}
                                for k, v in {
                                    "status": "Comptabilisé",
                                    "amount": "60",
                                    "document": "D",
                                    "date": "2026-01-01",
                                }.items()
                            },
                            comment="Concurrent",
                            expected_version=line.version,
                            expected_group_version=line.group.version,
                            expected_source=expected,
                            acknowledge=True,
                        )
                        return "OK"
                    except ValidationError:
                        return "REVIEW"
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(attempt, ["A", "B"]))
            self.assertCountEqual(results, ["OK", "REVIEW"])
            self.assertEqual(ControlContribution.objects.count(), 1)

"""Recettes A/B : preuves exactes distinctes et référence Sage des Confirmé."""

import copy
import json
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from reconciliation_contract import control_identity, entry_from_sage, snapshot
from reconciliation_contract.atlas_context import ATLAS_CONTEXT

from . import test_campaigns as fixtures
from .campaigns import normalize_inventory
from .models import Campaign, ControlContribution, LineReview, ReviewEvent
from .presentation import money as display_money
from .review import decide, is_current, signature
from .review_import import import_bundle
from . import test_collective_validation as collective_fixtures


class CorrectifAutomaticTests(TestCase):
    """Utilise de vrais imports JSONL sur base jetable et conserve les sources."""

    setUp = fixtures.CampaignTests.setUp
    bundle = fixtures.CampaignTests.bundle

    def exact_records(self, amounts=("140", "4500", "67.58"), *, sage_amounts=None,
                      assignments=None, incomplete=False, accounted=None):
        """Construit une pièce v3 à preuves distinctes ou volontairement concurrentes.

        `amounts` sont les charges projet Atlas ; `sage_amounts` les charges
        individuelles Sage EUR. `assignments` associe chaque ligne à un indice
        de preuve ; `incomplete` retire la ligne analytique, `accounted` ajoute
        une source déjà comptabilisée. Retourne des enregistrements JSON signés.
        """
        sage_amounts = amounts if sage_amounts is None else sage_amounts
        assignments = tuple(range(len(amounts))) if assignments is None else assignments
        proofs = []
        for i, amount in enumerate(sage_amounts):
            raw = {"Projet": "P", "Numéro pièce": "GNF0126051766", "Journal": "ACH",
                   "N° de ligne comptable": f"00{i + 1}", "N° de ligne Analytique": "" if incomplete else "01",
                   "Date comptable": "2026-05-14", "Charges (Dépenses)": amount,
                   "Libellé pièce": f"Mission {i}", "Code Tiers - Tiers doc Orig": "T", "Référence": f"B{i}", "Devise": "EUR"}
            raw["entry_ref"] = entry_from_sage(raw)["ref"]
            proofs.append(raw)
        sources, proposals = [], []
        for i, amount in enumerate(amounts):
            proof = proofs[assignments[i]]
            row = fixtures.atlas(str(i + 1), **{"Total charges projet (€)": amount,
                                 "Libellé ATLAS": proof["Libellé pièce"], "Code tiers SAGE": "T",
                                 "N° BAP (SAGE)": proof["Référence"], "Devise": "EUR"})
            sources.append(row)
            proposals.append(fixtures.proposal([row], key=f"g{i}", schema_version=3, rule="MATCH_EXACT",
                             sage_total=proof["Charges (Dépenses)"], evidence=[{"rows": [proof]}],
                             auto_validation={"source": "AUTO", "rule": "MATCH_EXACT", "state": "VALIDATED"}))
        accounted_rows = []
        if accounted is not None:
            row = fixtures.atlas("C", **{"Statut BAP": "Comptabilisé", "Total charges projet (€)": accounted,
                                 "Total charges SAGE (€)": accounted, "N° pièce SAGE": "GNF0126051766",
                                 "Date comptable": "2026-05-14", "Code tiers SAGE": "T", "Libellé ATLAS": "Existant", "Devise": "EUR"})
            sources.append(row)
            accounted_rows.append({k: v for k, v in normalize_inventory(row, extended=True).items() if k not in ATLAS_CONTEXT.values()})
        entries = [entry_from_sage(raw) for raw in proofs]
        control = snapshot(control_identity(entries[0], sage=True), accounted_rows, entries, amount_field="total_sage_charges")
        records = [json.loads(line) for line in self.bundle(inventory=sources, proposals=proposals).read_text(encoding="utf-8").splitlines()]
        records[0].update(schema_version=3, controls_available=True, piece_coherence_mode="ACTIVE",
                          amount_field="total_sage_charges", sage_amount_currency="EUR", tolerance="0.01")
        records.insert(-1, {"type": "control", "data": control})
        records[-1].update(control_count=1, control_statuses={control["status"]: 1})
        return records

    def load_records(self, records):
        """Importe une nouvelle campagne synthétique sans modifier les campagnes closes."""
        records = copy.deepcopy(records)
        records[0]["name"] = f"Recette correctif {Campaign.objects.count()}"
        path = Path(self.folder.name) / "correctif.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def test_b1_distinct_entries_on_shared_piece_and_carry(self):
        """140, 4500 et 67,58 EUR sont AUTO, réservés une fois et reportables sans événement ajouté."""
        first = self.load_records(self.exact_records())
        lines = list(LineReview.objects.select_related("group", "transaction__project"))
        self.assertTrue(all(l.state == "VALIDATED" and l.validation_source == "AUTO" and is_current(l) for l in lines))
        contributions = list(ControlContribution.objects.filter(control__campaign=first))
        self.assertEqual(sum((c.amount for c in contributions), Decimal(0)), Decimal("4707.58"))
        self.assertEqual(len({ref for c in contributions for ref in c.entries}), 3)
        second = self.load_records(self.exact_records())
        self.assertEqual(ReviewEvent.objects.count(), 3)
        self.assertEqual(second.reviews.filter(comparison="CARRIED").count(), 3)
        self.assertTrue(all(r.decision["current"] for r in first.reviews.all()))

    def test_b2_reused_entry_blocks_every_claimant_in_both_orders(self):
        """Deux demandes de 1000 sur la même écriture restent manuelles quel que soit l'ordre."""
        records = self.exact_records(("1000", "1000"), sage_amounts=("1000",), assignments=(0, 0))
        for reverse in (False, True):
            ordered = self.permuted(records, reverse)
            campaign = self.load_records(ordered)
            self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED").count(), 0)
            self.assertEqual(ControlContribution.objects.filter(control__campaign=campaign).count(), 0)
            self.assertTrue(all("réutilisée" in " ".join(r.reasons) for r in campaign.reviews.all()))

    def permuted(self, records, reverse):
        """Retourne une copie dont l'ordre des seules propositions peut être inversé."""
        records = copy.deepcopy(records)
        positions = [i for i, row in enumerate(records) if row.get("type") == "proposal"]
        if reverse:
            values = [records[i] for i in positions][::-1]
            for i, value in zip(positions, values):
                records[i] = value
        return records

    def test_b3_twin_amounts_have_distinct_identified_proofs(self):
        """Deux écritures de 1000 EUR à références/lignes distinctes permettent deux AUTO."""
        campaign = self.load_records(self.exact_records(("1000", "1000")))
        self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED").count(), 2)
        self.assertEqual(len({c.entries[0] for c in ControlContribution.objects.filter(control__campaign=campaign)}), 2)

    def test_b4_missing_analytic_identity_stays_manual(self):
        """Le triplet pièce/date/projet ne remplace pas une identité analytique absente."""
        campaign = self.load_records(self.exact_records(("1000", "1000"), incomplete=True))
        self.assertEqual(LineReview.objects.filter(state="VALIDATED").count(), 0)
        self.assertTrue(all("Identité" in " ".join(r.reasons) for r in campaign.reviews.all()))

    def test_b5_distinct_entries_have_same_result_after_permutation(self):
        """Les décisions et réservations restent identiques après permutation des propositions."""
        records = self.exact_records()
        first = self.load_records(records)
        expected = {r.source["source_id"]: r.decision["effective"] for r in first.reviews.all()}
        second = self.load_records(self.permuted(records, True))
        self.assertEqual({r.source["source_id"]: r.decision["effective"] for r in second.reviews.all()}, expected)
        self.assertEqual(second.reviews.filter(decision__state="VALIDATED").count(), 3)

    def test_b1_reversed_initial_import_validates_all_three(self):
        """Un import initial inversé valide les trois écritures sans dépendre d'un report."""
        campaign = self.load_records(self.permuted(self.exact_records(), True))
        self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED", decision__current=True).count(), 3)

    def test_new_reuse_invalidates_carried_auto_without_rewriting_history(self):
        """Un conflit nouveau invalide toutes les AUTO courantes et préserve l'ancienne campagne."""
        first = self.load_records(self.exact_records(("1000", "1000")))
        second = self.load_records(self.exact_records(("1000", "1000"), sage_amounts=("1000",), assignments=(0, 0)))
        self.assertFalse(second.reviews.filter(decision__current=True).exists())
        self.assertEqual(ControlContribution.objects.filter(control__campaign=second).count(), 0)
        self.assertTrue(all(r.decision["current"] for r in first.reviews.all()))

    def test_identical_amount_with_ambiguous_multiple_proofs_stays_manual(self):
        """Deux preuves concurrentes dans un Exact ne sont pas départagées par leur montant."""
        records = self.exact_records(("1000", "1000"))
        proposals = [r for r in records if r.get("type") == "proposal"]
        proposals[0]["evidence"][0]["rows"].append(copy.deepcopy(proposals[1]["evidence"][0]["rows"][0]))
        campaign = self.load_records(records)
        self.assertFalse(campaign.reviews.filter(decision__current=True).exists())

    def test_human_decision_remains_manual_in_successive_campaign(self):
        """La nouvelle politique n'écrase pas une décision humaine enregistrée."""
        self.load_records(self.exact_records(("100",)))
        line = LineReview.objects.select_related("group", "transaction__project").get()
        decide(line.pk, self.user, state="REJECTED", values=line.values, comment="Refus métier",
               expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line))
        self.load_records(self.exact_records(("100",)))
        line.refresh_from_db()
        self.assertEqual((line.state, line.validation_source), ("REJECTED", "MANUAL"))

    def test_aggregate_excess_blocks_all_distinct_candidates(self):
        """Deux preuves distinctes ne permettent pas de dépasser la pièce avec l'existant Atlas."""
        records = self.exact_records(("100", "100"), accounted="50")
        for reverse in (False, True):
            campaign = self.load_records(self.permuted(records, reverse))
            self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED").count(), 0)
            self.assertTrue(all("Dépassement collectif" in " ".join(r.reasons) for r in campaign.reviews.all()))

    def test_zero_negative_and_missing_amounts(self):
        """Zéro et avoirs homogènes suivent les contrôles signés ; une source absente bloque."""
        for amounts in (("0", "100"), ("-140", "-4500", "-67.58")):
            campaign = self.load_records(self.exact_records(amounts))
            self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED").count(), len(amounts))
        records = self.exact_records(("100",))
        for r in records:
            if r.get("type") == "inventory":
                r["atlas"]["Total charges projet (€)"] = None
            elif r.get("type") == "proposal":
                r["atlas"][0]["Total charges projet (€)"] = None
        campaign = self.load_records(records)
        self.assertFalse(campaign.reviews.filter(decision__state="VALIDATED", decision__current=True).exists())

    def test_exact_cent_tolerance_does_not_change_reference_policy(self):
        """Exact garde sa référence projet et la tolérance inclusive d'un centime."""
        for project_amount, expected in (("100.01", True), ("100.02", False)):
            campaign = self.load_records(self.exact_records((project_amount,), sage_amounts=("100",)))
            self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED", decision__current=True).exists(), expected)

    def test_manual_piece_sharing_still_requires_risk_confirmation(self):
        """La nouvelle exemption AUTO ne supprime pas les avertissements du parcours manuel."""
        self.load_records(self.exact_records(("100", "100")))
        line = LineReview.objects.select_related("group", "transaction__project").get(transaction__source_id="2")
        with self.assertRaisesMessage(ValidationError, "Justifiez ce risque"):
            decide(line.pk, self.user, state="VALIDATED", values=line.values, comment="Revue manuelle",
                   expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line))


class ConfirmedReferenceTests(TestCase):
    """Recette A et rendu des sources, sans dépendre du Lot 2."""

    setUp = fixtures.CampaignTests.setUp
    bundle = fixtures.CampaignTests.bundle
    records = collective_fixtures.CollectiveTests.records
    load_records = CorrectifAutomaticTests.load_records

    def test_reference_86819_ignores_project_gap_and_preserves_sources(self):
        """L'écart projet de cinq euros n'empêche plus les deux AUTO d'une pièce équilibrée."""
        records = self.records(amounts=("109.56", "758.63"))
        for r in records:
            rows = [r["atlas"]] if r.get("type") == "inventory" else r.get("atlas", []) if r.get("type") == "proposal" else []
            for row in rows:
                if row["Id"] == "2":
                    row["Total charges projet (€)"] = "753.63"
        campaign = self.load_records(records)
        self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED").count(), 2)
        line = LineReview.objects.get(transaction__source_id="2")
        self.assertEqual(line.transaction.total_project_charges, Decimal("753.63"))
        self.assertEqual(line.transaction.total_sage_charges, Decimal("758.63"))
        self.assertEqual(sum((c.amount for c in ControlContribution.objects.filter(control__campaign=campaign)), Decimal(0)), Decimal("868.19"))
        response = self.client.get(reverse("reconciliation:review-detail", args=[line.pk]))
        source_block = response.content.decode().split("Données sources", 1)[1].split("</section>", 1)[0]
        self.assertIn("Total charges SAGE (€)", source_block)
        self.assertIn(display_money(Decimal("753.63")), source_block)
        self.assertIn(display_money(Decimal("758.63")), source_block)

    def test_missing_sage_source_displays_dash_not_zero(self):
        """Une source absente affiche le tiret monétaire et ne peut être AUTO."""
        records = self.records(amounts=("100",))
        for r in records:
            if r.get("type") == "inventory":
                r["atlas"]["Total charges SAGE (€)"] = None
            elif r.get("type") == "proposal":
                r["atlas"][0]["Total charges SAGE (€)"] = None
                r.pop("piece_coherence")
        self.load_records(records)
        line = LineReview.objects.get()
        response = self.client.get(reverse("reconciliation:review-detail", args=[line.pk]))
        self.assertContains(response, '<dt>Total charges SAGE (€)</dt><dd class="amount-emphasis">—</dd>', html=True)
        self.assertEqual(line.state, "DRAFT")

    def test_confirmed_zero_and_negative_reference_preserve_project_sources(self):
        """Les références Sage nulles et négatives restent admissibles sans veto projet."""
        for amounts in (("0", "100"), ("-40", "-60")):
            records = self.records(amounts=amounts)
            for r in records:
                rows = [r["atlas"]] if r.get("type") == "inventory" else r.get("atlas", []) if r.get("type") == "proposal" else []
                for row in rows:
                    row["Total charges projet (€)"] = str(Decimal(row["Total charges SAGE (€)"]) + Decimal("10"))
            campaign = self.load_records(records)
            self.assertEqual(campaign.reviews.filter(decision__state="VALIDATED", decision__current=True).count(), 2)

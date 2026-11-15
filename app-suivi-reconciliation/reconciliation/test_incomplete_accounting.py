"""Parcours manuel des Comptabilisé incomplets, avec preuves et sources conservées."""

import copy
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from reconciliation_contract import digest, entry_from_sage
from reconciliation_contract.sage_inventory import CAPABILITY, exclusion_policy, inventory_record

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .accounting import prepare_campaign
from .accounting_models import AccountingProject
from .business import (
    cancel_inventory_link,
    confirm_inventory_link,
    correct_inventory,
    retained_amount,
    search_sage,
    selection_summary,
)
from .campaigns import insert_inventory
from .global_control import initialize_controls
from .incomplete_accounting import missing_mask
from .models import Campaign, CampaignAction, CampaignGlobalControl, ManualAllocation
from .sage_import import insert_sage_batch


class IncompleteFixture:
    """Construit une campagne synthétique reproduisant exactement les montants du cas 1665867."""

    def setUp(self):
        """Crée les inventaires de test et leurs projections par les vrais services."""
        self.user = User.objects.create_user("incomplete-reviewer")
        project = Project.objects.create(code="19DDU0C041", label="Projet de recette")
        ProjectPortfolio.objects.create(user=self.user, project=project)
        self.campaign = Campaign.objects.create(
            name="Recette incomplets",
            is_current=True,
            scope="test",
            fiscal_year=2026,
            metadata={
                "schema_version": 3,
                "capabilities": [CAPABILITY],
                "sage_exclusions": exclusion_policy(),
                "amount_field": "total_sage_charges",
                "tolerance": "0.01",
            },
        )
        self.source = {
            "project_code": project.code,
            "fiscal_year": 2026,
            "source_id": "1665867",
            "bap_status": "Comptabilisé",
            "total_project_charges": "4213.50",
            "total_sage_charges": None,
            "sage_document_number": "",
            "accounting_date": None,
            "sage_third_party_code": "CABINET_KPC",
            "atlas_label": "Mapping vétos PEFFAG Guinée",
            "sage_label": "",
            "currency": "GNF",
            "display_bap": "BAPETR260400447",
        }
        insert_inventory(self.campaign, [self.source])
        self.entry = self.add_entry("GNF0126041594", "4213.38")
        initialize_controls(self.campaign)
        prepare_campaign(self.campaign)
        self.client.force_login(self.user)

    def add_entry(self, document, amount, **changes):
        """Insère une écriture canonique signée ; retourne l'objet Sage persistant."""
        raw = {
            "Projet": self.source["project_code"],
            "Numéro pièce": document,
            "Date comptable": "2026-04-07",
            "Journal": "ACHGN",
            "N° de ligne comptable": "2",
            "N° de ligne Analytique": "1",
            "Code Tiers - Tiers doc Orig": "CABINET_KPC",
            "Libellé pièce": self.source["atlas_label"],
            "Devise": "GNF",
            "Charges (Dépenses)": amount,
            **changes,
        }
        data = inventory_record(
            entry_from_sage(raw),
            self.campaign.metadata["sage_exclusions"],
            attributes={"Référence": self.source["display_bap"]},
        )
        insert_sage_batch(self.campaign, [data])
        return self.campaign.sage_inventory.get(record_id=data["record_id"])

    def inventory(self):
        """Relit la source et ses décisions courantes pour éviter les caches ORM anciens."""
        return self.campaign.inventory.select_related(
            "campaign", "adjustment", "inventory_match"
        ).get(source_id="1665867")

    def correction(self):
        """Corrige explicitement 0,12 € avec une justification distincte, sans confirmer."""
        return correct_inventory(
            self.inventory().pk,
            self.user,
            reason="AMOUNT",
            amount="4213.38",
            comment="Écart de conversion vérifié sur justificatif",
            expected_version=self.inventory().business_version,
        )

    def confirmation(self, **changes):
        """Confirme la sélection de recette via le service transactionnel existant."""
        options = {
            "entry_ids": [self.entry.pk],
            "comment": "Pièce, tiers, BAP et facture vérifiés",
            "expected_version": self.inventory().business_version,
            **changes,
        }
        return confirm_inventory_link(self.inventory().pk, self.user, **options)


class IncompleteAccountingTests(IncompleteFixture, TestCase):
    """Couvre détection, consultation, corrections et affectations dans une base jetable."""

    def test_detection_zero_invalid_date_and_missing_fields(self):
        """Zéro est valide ; chaque défaut reste distinct et Envoyé SAGE n'est pas reclassé."""
        self.assertEqual(missing_mask(self.source, 2026), 7)
        full = {
            **self.source,
            "total_sage_charges": "0",
            "sage_document_number": " GNF0001 ",
            "accounting_date": "2026-04-07",
        }
        self.assertEqual(missing_mask(full, 2026), 0)
        self.assertEqual(missing_mask({**full, "accounting_date": "2025-04-07"}, 2026), 4)
        self.assertEqual(missing_mask({**full, "total_sage_charges": "NaN"}, 2026), 1)
        self.assertEqual(missing_mask({**full, "sage_document_number": "  "}, 2026), 2)
        self.assertEqual(missing_mask({**self.source, "bap_status": "Envoyé SAGE"}, 2026), 0)
        self.assertEqual(self.inventory().sage_missing_mask, 7)

    def test_candidate_and_exact_gap_without_validation(self):
        """Trouve le candidat malgré 0,12 € d'écart, sans créer de décision."""
        before = CampaignAction.objects.count()
        row = self.inventory()
        self.assertIsNone(retained_amount(row))
        candidates = list(search_sage(row, self.user))
        self.assertEqual(candidates[0].pk, self.entry.pk)
        preview = selection_summary(row, self.user, [self.entry.pk])
        self.assertEqual(preview["gap"], Decimal("0.12"))
        self.assertIsNone(preview["retained"])
        self.assertEqual(preview["reference"], Decimal("4213.50"))
        response = self.client.get(reverse("reconciliation:inventory-detail", args=[row.pk]))
        self.assertContains(response, "GNF0126041594")
        self.assertContains(response, "+0,12")
        self.assertContains(response, "BAP, Tiers, Libellé")
        self.assertFalse(ManualAllocation.objects.exists())
        self.assertEqual(CampaignAction.objects.count(), before)

    def test_correction_confirmation_cancel_and_idempotence(self):
        """Un écart exige correction puis confirmation ; l'annulation rétablit l'insuffisance."""
        with self.assertRaises(ValidationError):
            self.confirmation()
        with self.assertRaisesMessage(ValidationError, "Justifiez"):
            correct_inventory(
                self.inventory().pk,
                self.user,
                reason="AMOUNT",
                amount="4213.38",
                expected_version=0,
            )
        original = copy.deepcopy(self.inventory().data)
        self.correction()
        self.assertFalse(ManualAllocation.objects.exists())
        self.assertEqual(AccountingProject.objects.get(campaign=self.campaign).state, "INSUFFISANT")
        request_id = uuid4()
        version = self.inventory().business_version
        self.confirmation(request_id=request_id, expected_version=version)
        self.confirmation(request_id=request_id, expected_version=version)
        summary = AccountingProject.objects.get(campaign=self.campaign)
        self.assertEqual(
            (summary.atlas, summary.sage, summary.gap, summary.state),
            (Decimal("4213.38"), Decimal("4213.38"), Decimal(0), "CADRE"),
        )
        self.assertIsNone(summary.data["totals"]["initial"])
        self.assertEqual(ManualAllocation.objects.filter(active=True).count(), 1)
        self.assertEqual(CampaignAction.objects.filter(kind="LINK").count(), 1)
        self.assertEqual(self.inventory().data, original)
        cancel_inventory_link(
            self.inventory().pk,
            self.user,
            expected_version=self.inventory().business_version,
            comment="Association retirée après revue",
        )
        self.assertFalse(ManualAllocation.objects.filter(active=True).exists())
        self.assertEqual(AccountingProject.objects.get(campaign=self.campaign).state, "INSUFFISANT")

    def test_remaining_missing_line_still_blocks_the_project(self):
        """Résoudre une ligne ne supprime pas une autre cause source réellement bloquante."""
        insert_inventory(self.campaign, [{**self.source, "source_id": "OTHER"}])
        self.correction()
        self.confirmation()
        self.assertEqual(AccountingProject.objects.get(campaign=self.campaign).state, "INSUFFISANT")

    def test_equal_reference_is_manual_and_source_remains_missing(self):
        """L'égalité autorise une confirmation humaine, sans correction ni complétion source."""
        target = self.add_entry("GNF-EQUAL", "4213.50")
        self.assertFalse(ManualAllocation.objects.exists())
        self.confirmation(entry_ids=[target.pk])
        self.assertIsNone(self.inventory().data["total_sage_charges"])
        self.assertEqual(retained_amount(self.inventory()), Decimal("4213.50"))
        self.assertEqual(self.inventory().inventory_match.actor_id, self.user.pk)

    def test_search_pagination_and_correction_invalidate_a_confirmation(self):
        """La recherche reste paginée ; modifier une correction exige de reconfirmer."""
        for number in range(26):
            self.add_entry(f"GNF-PAGE-{number:02}", "1")
        url = reverse("reconciliation:inventory-detail", args=[self.inventory().pk])
        response = self.client.get(url, {"page": 2})
        self.assertEqual(response.context["page"].paginator.count, 27)
        self.assertEqual(len(response.context["page"]), 2)
        self.correction()
        self.confirmation()
        self.assertEqual(ManualAllocation.objects.filter(active=True).count(), 1)
        correct_inventory(
            self.inventory().pk,
            self.user,
            reason="AMOUNT",
            amount="4213.39",
            comment="Nouvelle justification",
            expected_version=self.inventory().business_version,
        )
        self.assertEqual(AccountingProject.objects.get(campaign=self.campaign).state, "INSUFFISANT")

    def test_duplicate_correction_does_not_allow_a_sign_flip(self):
        """Une exclusion provisoire ne remplace pas le signe de référence de la source."""
        correct_inventory(
            self.inventory().pk,
            self.user,
            reason="DUPLICATE",
            comment="Doublon à vérifier",
            expected_version=0,
        )
        with self.assertRaisesMessage(ValidationError, "signe"):
            correct_inventory(
                self.inventory().pk,
                self.user,
                reason="AMOUNT",
                amount="-4213.38",
                comment="Signe interdit",
                expected_version=1,
            )

    def test_candidates_remain_in_campaign_project_and_year(self):
        """Même BAP/montant ne permet pas de choisir une autre campagne ou un autre projet."""
        other = Campaign.objects.create(
            name="Autre", scope="test", fiscal_year=2026, metadata=self.campaign.metadata
        )
        insert_sage_batch(other, [self.entry.data])
        foreign_campaign = other.sage_inventory.get()
        foreign_project = self.add_entry("GNF-OTHER", "4213.38", **{"Projet": "OTHER"})
        for entry in (foreign_campaign, foreign_project):
            with self.assertRaises(ValidationError):
                selection_summary(self.inventory(), self.user, [entry.pk])
        self.campaign.sage_inventory.filter(pk=self.entry.pk).update(fiscal_year=2025)
        self.assertFalse(search_sage(self.inventory(), self.user).exists())

    def test_list_and_detail_have_bounded_queries(self):
        """Mesure liste/détail et interdit les écritures métier, hors session HTTP normale."""
        from time import perf_counter

        start = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                reverse("reconciliation:reviews"), {"view": "controls", "sage_missing": "yes"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(queries), 25)
        for query in queries:
            sql = query["sql"]
            self.assertFalse(
                sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
                and ('"reconciliation_' in sql or '"projects_' in sql),
                sql,
            )
        control = response.context["page"][0]
        with CaptureQueriesContext(connection) as detail_queries:
            detail = self.client.get(
                reverse("reconciliation:global-control-detail", args=[control.pk])
            )
        self.assertEqual(detail.status_code, 200)
        self.assertLess(len(detail_queries), 25)
        print(
            f"BENCH incomplets : liste {len(queries)} requêtes, détail {len(detail_queries)}, "
            f"{perf_counter() - start:.3f}s"
        )

    def test_priority_filters_detail_and_no_get_writes(self):
        """Le contrôle incomplet précède les écarts ordinaires ; le filtre n'explore pas le JSON."""
        project = Project.objects.create(code="000-FIRST", label="Anomalie ordinaire")
        ProjectPortfolio.objects.create(user=self.user, project=project)
        data = {
            "state": "ECART",
            "identity": {
                "strategy": "STANDARD_BY_DOCUMENT",
                "parts": [project.code, 2026, "GNF-ORDINARY"],
            },
            "accounted_total": "0",
            "confirmed_sent_total": "0",
            "sage_total": "1",
            "gap": "-1",
        }
        CampaignGlobalControl.objects.create(
            campaign=self.campaign,
            project_code=project.code,
            key=digest(["ordinary"]),
            state="ECART",
            data=data,
        )
        url = reverse("reconciliation:reviews")
        response = self.client.get(url, {"view": "controls"})
        first = response.context["page"][0]
        self.assertEqual(first.sage_incomplete_count, 1)
        self.assertContains(response, "Informations Sage manquantes dans Atlas")
        for choice, count in (("yes", 1), ("no", 2)):
            filtered = self.client.get(url, {"view": "controls", "sage_missing": choice})
            self.assertEqual(filtered.context["page"].paginator.count, count)
        detail = self.client.get(reverse("reconciliation:global-control-detail", args=[first.pk]))
        self.assertContains(detail, "Rechercher une correspondance Sage")
        self.assertContains(detail, "Date comptable absente")
        self.assertFalse(CampaignAction.objects.exists())

    def test_scope_reservations_versions_and_sign_remain_enforced(self):
        """Les URL, versions, écritures exclues et corrections de signe restent protégées."""
        other = User.objects.create_user("outside-incomplete")
        with self.assertRaises(PermissionDenied):
            search_sage(self.inventory(), other)
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(
                reverse("reconciliation:inventory-detail", args=[self.inventory().pk])
            ).status_code,
            404,
        )
        with self.assertRaises(ValidationError):
            correct_inventory(
                self.inventory().pk,
                self.user,
                reason="AMOUNT",
                amount="-4213.38",
                comment="Signe erroné",
                expected_version=0,
            )
        self.correction()
        with self.assertRaises(ValidationError):
            self.confirmation(expected_version=0)
        self.confirmation()
        second = {**self.source, "source_id": "SECOND", "total_sage_charges": "4213.38"}
        insert_inventory(self.campaign, [second])
        row = self.campaign.inventory.get(source_id="SECOND")
        with self.assertRaisesMessage(ValidationError, "déjà affectée"):
            confirm_inventory_link(
                row.pk,
                self.user,
                entry_ids=[self.entry.pk],
                comment="Autre tentative",
                expected_version=0,
            )

    def test_multi_selection_ranking_and_pagination(self):
        """Somme les références entières et classe les indices sans masquer les candidats."""
        decoy = self.add_entry(
            "GNF-DECOY",
            "4213.50",
            **{"Code Tiers - Tiers doc Orig": "AUTRE", "Libellé pièce": "Autre"},
        )
        self.assertEqual(search_sage(self.inventory(), self.user).first().pk, self.entry.pk)
        first = self.add_entry("GNF-SPLIT", "2000")
        second = self.add_entry("GNF-SPLIT", "2213.38", **{"N° de ligne comptable": "3"})
        summary = selection_summary(self.inventory(), self.user, [first.pk, second.pk])
        self.assertEqual(summary["sage_total"], Decimal("4213.38"))
        self.assertEqual(summary["gap"], Decimal("0.12"))
        with self.assertRaises(ValidationError):
            selection_summary(self.inventory(), self.user, [first.pk, first.pk])
        self.campaign.sage_inventory.filter(pk=decoy.pk).update(eligible=False)
        self.assertNotIn(
            decoy.pk, search_sage(self.inventory(), self.user).values_list("pk", flat=True)
        )

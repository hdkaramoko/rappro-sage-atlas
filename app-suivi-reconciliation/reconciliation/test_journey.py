"""Recette du parcours métier sur campagnes synthétiques, sans sources réelles."""

import copy
import json
import subprocess
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio
from . import test_campaigns as fixtures
from .business import correct_inventory
from .global_views import global_controls_for
from .models import Campaign, CampaignAction, CampaignGlobalControl, LineReview, ManualAllocation, ReviewGroup
from .review import signature
from .revision import reopen_review
from . import test_business as business_fixtures


class JourneyTests(TestCase):
    """Actions contextuelles, filtres SQL, révision et façade des contrôles courants."""

    load = business_fixtures.BusinessTests.load
    inventory = business_fixtures.BusinessTests.inventory
    entry = business_fixtures.BusinessTests.entry
    result = business_fixtures.BusinessTests.result
    confirm = business_fixtures.BusinessTests.confirm

    @classmethod
    def setUpClass(cls):
        """Génère une campagne Lot 1 réelle à partir de sources strictement synthétiques."""
        super().setUpClass()
        cls.source_folder = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.lot1_fixture", cls.source_folder.name],
                       cwd=root, check=True, capture_output=True, timeout=60)
        cls.records = [json.loads(row) for row in (Path(cls.source_folder.name) / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
        for record in cls.records:
            if record.get("type") == "proposal":
                record.pop("auto_validation", None)

    @classmethod
    def tearDownClass(cls):
        """Libère les seuls fichiers de recette temporaires générés par cette classe."""
        cls.source_folder.cleanup()
        super().tearDownClass()

    def setUp(self):
        """Initialise utilisateur, portefeuille et campagne publiée de recette."""
        fixtures.CampaignTests.setUp(self)
        self.campaign = self.load()
        self.list_url = reverse("reconciliation:reviews")

    def line(self):
        """Retourne la projection courante S avec les relations nécessaires à la signature."""
        return LineReview.objects.select_related("group", "transaction__project", "campaign", "inventory_link").get(transaction__source_id="S")

    def detail_url(self):
        """Construit l'adresse de la fiche de décision de la ligne S synthétique."""
        return reverse("reconciliation:review-detail", args=[self.line().pk])

    def test_usable_proposal_prioritizes_decision_without_lot2_buttons(self):
        """Une proposition exploitable garde Valider/Refuser sans les actions manuelles en tête."""
        response = self.client.get(self.detail_url())
        self.assertContains(response, 'value="VALIDATED"')
        self.assertContains(response, 'value="REJECTED"')
        self.assertNotContains(response, "Actions métier")
        self.assertNotContains(response, ">Rechercher une correspondance</a>")

    def test_unmatched_and_amount_anomaly_offer_contextual_actions(self):
        """Sans preuve, la recherche est proposée et une anomalie de montant permet Corriger."""
        line = self.line()
        line.group.match_status = "UNMATCHED"
        line.group.evidence = []
        line.group.sage_total = Decimal("3900")
        line.group.save()
        response = self.client.get(self.detail_url())
        self.assertContains(response, ">Rechercher une correspondance</a>")
        self.assertContains(response, "Corriger le montant Atlas")
        response = self.client.get(self.list_url, {"rule": "__NO_MATCH__"})
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertNotContains(response, 'name="match_status"')
        self.assertContains(response, "Sans correspondance")

    def test_confirmed_manual_revision_releases_and_audits(self):
        """La révision motivée libère Sage, conserve l'ancienne décision et recalcule la pièce."""
        self.confirm()
        response = self.client.get(self.detail_url())
        self.assertContains(response, "Réviser le rapprochement")
        self.assertNotContains(response, 'value="VALIDATED"')
        line = self.line()
        response = self.client.post(self.detail_url(), {"action": "REVISE", "version": line.version,
            "group_version": line.group.version, "source": signature(line), "comment": "Mauvaise dépense"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.line().state, "DRAFT")
        self.assertFalse(ManualAllocation.objects.filter(entry__campaign=self.campaign, active=True).exists())
        self.assertEqual(Decimal(self.result()["confirmed_sent_total"]), 0)
        self.assertEqual(self.line().events.first().snapshot["before"]["state"], "VALIDATED")
        self.assertTrue(self.inventory().business_events.filter(kind="DECISION").exists())

    def test_revision_requires_reason_permissions_and_versions(self):
        """Sans motif, sans accès ou avec version périmée, aucune écriture n'est libérée."""
        self.confirm()
        line = self.line()
        response = self.client.post(self.detail_url(), {"action": "REVISE", "version": line.version,
            "group_version": line.group.version, "source": signature(line), "comment": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.line().state, "VALIDATED")
        with self.assertRaises(ValidationError):
            reopen_review(line.pk, self.user, version=line.version - 1, group_version=line.group.version,
                          source=signature(line), comment="Motif")
        outsider = User.objects.create_user("outside")
        with self.assertRaises(PermissionDenied):
            reopen_review(line.pk, outsider, version=line.version, group_version=line.group.version,
                          source=signature(line), comment="Motif")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_auto_revision_is_explicit_and_preserves_its_origin(self):
        """Une AUTO ne peut être éditée par un POST ordinaire ; sa contestation reste auditée."""
        records = copy.deepcopy(self.records)
        next(r for r in records if r.get("type") == "proposal")["auto_validation"] = {
            "source": "AUTO", "rule": "MATCH_EXACT", "state": "VALIDATED"}
        self.campaign = self.load(records)
        line = self.line()
        self.assertEqual(line.validation_source, "AUTO")
        response = self.client.get(self.detail_url())
        self.assertContains(response, "Réviser le rapprochement")
        self.assertNotContains(response, "data-review-form")
        response = self.client.post(self.detail_url(), {"action": "DRAFT"})
        self.assertContains(response, "Utilisez Réviser le rapprochement")
        self.assertEqual(self.line().validation_source, "AUTO")
        self.assertEqual(self.line().state, "VALIDATED")
        reopen_review(line.pk, self.user, version=line.version, group_version=line.group.version,
                      source=signature(line), comment="Écriture contestée")
        self.assertEqual(self.line().state, "DRAFT")
        self.assertEqual(self.line().events.first().snapshot["before"]["validation_source"], "AUTO")

    def test_revising_carried_link_never_mutates_historical_campaign(self):
        """La révision ne touche que les réservations courantes d'un lien repris."""
        self.confirm()
        old = self.inventory()
        self.campaign = self.load()
        line = self.line()
        reopen_review(line.pk, self.user, version=line.version, group_version=line.group.version,
                      source=signature(line), comment="Révision après reprise")
        old.refresh_from_db()
        self.assertTrue(old.inventory_match.active)
        self.assertTrue(old.inventory_match.allocations.filter(active=True).exists())
        self.assertFalse(self.inventory().inventory_match.active)

    def test_global_view_uses_current_totals_and_anomalies_by_default(self):
        """La façade lit le résultat recalculé et inclut les Envoyé confirmés une seule fois."""
        response = self.client.get(self.list_url, {"view": "controls"})
        self.assertContains(response, "Contrôle des montants")
        self.assertContains(response, "FAC123")
        self.confirm()
        response = self.client.get(self.list_url, {"view": "controls", "control_state": "RECONCILED"})
        row = next(c for c in response.context["page"] if c.result["identity"]["parts"][2] == "FAC123")
        self.assertEqual(Decimal(row.result["confirmed_sent_total"]), Decimal("4000"))
        self.assertEqual(Decimal(row.result["gap"]), 0)
        detail = self.client.get(reverse("reconciliation:global-control-detail", args=[row.pk]))
        self.assertContains(detail, "État initial")
        self.assertContains(detail, "Envoyé SAGE")
        self.assertEqual(row.data["state"], "ECART")

    def test_equal_totals_with_unconfirmed_context_are_not_resolved(self):
        """L'état courant équilibré conserve l'alerte distincte de proposition non confirmée."""
        row = self.inventory("C")
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="10000", expected_version=0)
        control = self.campaign.global_controls.get(key=self.entry().control_key)
        self.assertEqual(control.current_data["state"], "EQUILIBRE")
        current = global_controls_for(self.user).get(pk=control.pk)
        self.assertTrue(current.pending)
        response = self.client.get(self.list_url, {"view": "controls", "control_state": "EQUILIBRE"})
        self.assertContains(response, "FAC123")
        self.assertContains(response, "proposition non confirmée")
        response = self.client.get(self.list_url, {"view": "controls", "control_state": "RECONCILED"})
        self.assertNotContains(response, "FAC123")

    def test_global_scope_and_ods_identity_are_preserved(self):
        """Les ODS utilisent leur identité composite et un contrôle hors portefeuille répond 404."""
        response = self.client.get(self.list_url, {"view": "controls", "control_state": ""})
        self.assertContains(response, "ODS/ODG")
        self.assertContains(response, "tiers 002")
        control = self.campaign.global_controls.first()
        outsider = User.objects.create_user("hidden")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse("reconciliation:global-control-detail", args=[control.pk])).status_code, 404)
        self.assertEqual(self.client.get(self.list_url, {"view": "controls", "control_state": ""}).context["page"].paginator.count, 0)

    def test_multifilters_union_intersection_all_and_return(self):
        """Les choix multiples s'unissent par dimension et se croisent entre dimensions en SQL."""
        line = self.line()
        transaction = line.transaction
        transaction.pk = None
        transaction.business_key, transaction.source_id = "SECOND", "SECOND"
        transaction.save(force_insert=True)
        group = ReviewGroup.objects.create(project=transaction.project, key="no-match", rule="MATCH_FUZZY_REVIEW", match_status="UNMATCHED")
        other = LineReview.objects.create(transaction=transaction, group=group, campaign=self.campaign,
                                         state="REJECTED", validation_source="MANUAL")
        params = {"project": ["P"], "rule": [line.group.rule, "__NO_MATCH__"], "state": ["DRAFT", "REJECTED"],
                  "validation_source": ["AUTO", "MANUAL"]}
        response = self.client.get(self.list_url, params)
        self.assertEqual(response.context["page"].paginator.count, 2)
        params["state"] = ["REJECTED"]
        self.assertEqual(self.client.get(self.list_url, params).context["page"].paginator.count, 1)
        params["state"] = ["", "VALIDATED"]
        self.assertEqual(self.client.get(self.list_url, params).context["page"].paginator.count, 2)
        self.assertEqual(self.client.get(self.list_url).context["page"].paginator.count, 1)
        back = self.list_url + "?" + urlencode(params, doseq=True)
        response = self.client.get(self.detail_url(), {"return": back})
        self.assertEqual(response.context["return_url"], back)
        self.assertNotContains(response, "select multiple")

    def test_cancel_link_form_demands_reason_and_preserves_return(self):
        """L'annulation depuis l'inventaire exige un motif et conserve le retour filtré."""
        self.confirm()
        row = self.inventory()
        back = self.list_url + "?state=VALIDATED&project=P"
        url = reverse("reconciliation:inventory-detail", args=[row.pk]) + "?" + urlencode({"return": back})
        response = self.client.post(url, {"action": "cancel_link", "version": row.business_version,
                                         "request_id": str(uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.inventory().inventory_match.active)
        self.assertEqual(response.context["return_url"], back)
        response = self.client.post(url, {"action": "cancel_link", "version": row.business_version,
            "request_id": str(uuid4()), "comment": "Mauvaise écriture"})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertFalse(self.inventory().inventory_match.active)

    def test_filters_and_global_list_are_read_only_and_paginated(self):
        """Les listes ne recalculent rien et paginent en SQL sans charger toutes les preuves."""
        count = CampaignAction.objects.count()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.list_url, {"view": "controls", "control_state": ""})
        self.assertEqual(CampaignAction.objects.count(), count)
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(queries), 15)
        self.assertTrue(any("LIMIT" in q["sql"] for q in queries))

    def origin_rows(self, **params):
        """Retourne la page Origine demandée, sans mutation ni calcul des groupes.

        `params` surcharge les filtres GET ; Tous états est le défaut de recette.
        Les requêtes passent par la vue et ses contrôles de portefeuille réels.
        """
        return self.client.get(self.list_url, {"view": "controls", "control_state": "", **params})

    def test_origin_uses_presence_zero_and_confirmed_sent(self):
        """Zéro et Envoyé confirmé comptent comme présents, jamais une simple proposition."""
        row = self.campaign.global_controls.get(data__identity__parts__2="FAC999")
        self.assertEqual({r.pk for r in self.origin_rows(origin="sage").context["page"]}, {row.pk})
        row.current_data = {**row.data, "sage_total": "0", "gap": "0"}
        row.save(update_fields=["current_data"])
        self.assertIn(row.pk, {r.pk for r in self.origin_rows(origin="sage").context["page"]})
        # Une confirmation acceptée porte une présence Atlas même sans Comptabilisé.
        row.current_data.update(atlas_count=0, confirmed_allocations=[{"line_key": "test", "amount": "0"}])
        row.save(update_fields=["current_data"])
        self.assertNotIn(row.pk, {r.pk for r in self.origin_rows(origin="sage").context["page"]})
        self.assertIn(row.pk, {r.pk for r in self.origin_rows(origin="both").context["page"]})
        row.current_data.update(confirmed_allocations=[], atlas_count=1, sage_count=0, accounted_total="0")
        row.save(update_fields=["current_data"])
        self.assertIn(row.pk, {r.pk for r in self.origin_rows(origin="atlas").context["page"]})

    def test_origin_multiselection_scope_exclusion_and_unknown(self):
        """Origines en OU, autres filtres en ET ; exclus/incomplets ne sont pas classés."""
        rows = self.origin_rows(origin=["sage", "both"]).context["page"]
        self.assertEqual(rows.paginator.count, 3)
        self.assertEqual(self.origin_rows(origin=["", "sage"]).context["page"].paginator.count, 3)
        self.assertEqual(self.origin_rows(origin="both", q="002").context["page"].paginator.count, 1)
        self.assertEqual(self.origin_rows(origin="sage", control_state="EQUILIBRE").context["page"].paginator.count, 0)
        self.assertEqual(self.origin_rows(origin="sage", project="P", q="FAC999").context["page"].paginator.count, 1)
        row = self.campaign.global_controls.get(data__identity__parts__2="FAC999")
        row.current_data = {**row.data, "state": "EXCLU"}
        row.save(update_fields=["current_data"])
        self.assertEqual(self.origin_rows(origin="sage").context["page"].paginator.count, 0)
        self.assertEqual(self.origin_rows(origin="").context["page"].paginator.count, 3)
        row.current_data = {"state": "INDETERMINE"}
        row.save(update_fields=["current_data"])
        self.assertEqual(self.origin_rows(origin="sage").context["page"].paginator.count, 0)
        self.assertEqual(self.origin_rows().context["page"].paginator.count, 3)
        row.current_data.update(atlas_count=None, sage_count=None)
        row.save(update_fields=["current_data"])
        self.assertEqual(self.origin_rows(origin="both").context["page"].paginator.count, 2)
        self.campaign.metadata["capabilities"] = []
        self.campaign.save(update_fields=["metadata"])
        self.assertEqual(self.origin_rows(origin="both").context["page"].paginator.count, 0)

    def test_origin_pagination_is_sql_and_keeps_choices(self):
        """Deux cents groupes sont filtrés avant LIMIT avec un nombre constant de requêtes."""
        example = self.campaign.global_controls.get(data__identity__parts__2="FAC999")
        CampaignGlobalControl.objects.bulk_create([
            CampaignGlobalControl(campaign=self.campaign, key=f"origin-{i}", project_code="P",
                state="ECART", current_state="ECART", has_pending=False, data=example.data) for i in range(200)])
        with CaptureQueriesContext(connection) as queries:
            response = self.origin_rows(origin=["atlas", "sage"], project="P", page=2)
        self.assertEqual(response.context["page"].paginator.count, 201)
        self.assertEqual(len(response.context["page"]), 50)
        self.assertContains(response, "origin=atlas&amp;origin=sage")
        self.assertContains(response, "Réinitialiser")
        self.assertLess(len(queries), 15)
        self.assertTrue(any('LIMIT 50' in q["sql"] and 'atlas_count' in q["sql"] for q in queries))

    def test_redundant_confirmation_fields_absent_and_choices_preserved(self):
        """Les formulaires perdent leurs cases redondantes, pas la sélection multiple Sage."""
        from .business_forms import CancelLinkForm
        from .revision import RevisionForm
        self.assertNotIn("confirm_revision", RevisionForm().fields)
        self.assertNotIn("confirm_cancel", CancelLinkForm().fields)
        response = self.client.get(reverse("reconciliation:inventory-detail", args=[self.inventory().pk]))
        self.assertContains(response, 'class="sage-choice"')
        self.assertContains(response, 'type="checkbox" name="entries"')
        self.confirm()
        response = self.client.get(self.detail_url())
        self.assertNotContains(response, 'name="confirm_revision"')
        self.assertContains(response, "Confirmer l'annulation de la validation")

    def test_stale_validation_is_back_in_to_examine(self):
        """Une validation invalidée par correction revient dans la file À examiner."""
        self.confirm()
        row = self.inventory()
        correct_inventory(row.pk, self.user, reason="AMOUNT", amount="3500", expected_version=row.business_version)
        self.assertEqual(self.line().state, "VALIDATED")
        self.assertEqual(self.client.get(self.list_url).context["page"].paginator.count, 1)
        self.assertEqual(self.client.get(self.list_url, {"state": "VALIDATED"}).context["page"].paginator.count, 0)

    def test_multi_selection_pagination_preserves_every_value(self):
        """La deuxième page conserve projets, règles et origines sans requêtes par preuve."""
        line = self.line()
        other = Project.objects.create(code="Q", label="Autre projet")
        ProjectPortfolio.objects.create(project=other, user=self.user)
        second_group = ReviewGroup.objects.create(project=other, key="other-group", rule="MATCH_AMOUNT", match_status="MATCHED")
        for index in range(28):
            item = self.line().transaction
            item.pk = None
            item.business_key, item.source_id = f"PAGE-{index}", f"PAGE-{index}"
            item.project = other if index % 2 else line.transaction.project
            item.save(force_insert=True)
            LineReview.objects.create(transaction=item, group=second_group if index % 2 else line.group, campaign=self.campaign)
        params = {"project": ["P", "Q"], "rule": [line.group.rule, "MATCH_AMOUNT"],
                  "validation_source": ["AUTO", "MANUAL"], "state": ["DRAFT", "REJECTED"], "page_size": "25", "page": "2"}
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.list_url, params)
        self.assertEqual(response.context["page"].paginator.count, 29)
        self.assertEqual(len(response.context["page"]), 4)
        self.assertContains(response, "project=P&amp;project=Q")
        self.assertContains(response, "validation_source=AUTO&amp;validation_source=MANUAL")
        self.assertLessEqual(len(queries), 12)

    def test_closed_campaign_cannot_be_revised_and_return_url_is_local(self):
        """Campagne close : lecture seule ; les URL de retour externes sont neutralisées."""
        self.confirm()
        line = self.line()
        self.campaign.is_current = False
        self.campaign.save(update_fields=["is_current"])
        response = self.client.get(self.detail_url(), {"return": "https://evil.example/"})
        self.assertNotContains(response, "Réviser le rapprochement")
        self.assertEqual(response.context["return_url"], self.list_url)
        with self.assertRaises(ValidationError):
            reopen_review(line.pk, self.user, version=line.version, group_version=line.group.version,
                          source=signature(line), comment="Campagne close")

    def test_zero_gap_ambiguous_control_is_not_reconciled(self):
        """Un état INDETERMINE à écart nul demeure une anomalie, sans nouveau calcul métier."""
        row = self.campaign.global_controls.get(data__identity__parts__2="FAC999")
        row.current_data = {**row.data, "state": "INDETERMINE", "gap": "0", "reasons": ["Correspondance ambiguë"]}
        row.save(update_fields=["current_data"])
        response = self.client.get(self.list_url, {"view": "controls", "control_state": "RECONCILED"})
        self.assertNotContains(response, "FAC999")
        response = self.client.get(self.list_url, {"view": "controls"})
        self.assertContains(response, "FAC999")

    def test_replacement_preview_shows_old_and_new_and_keeps_history(self):
        """Un remplacement exige confirmation explicite et conserve les cibles avant/après."""
        records = copy.deepcopy(self.records)
        business_fixtures.BusinessTests.add_sage_variant(self, records)
        self.campaign = self.load(records)
        self.confirm()
        row = self.inventory()
        target = self.campaign.sage_inventory.get(document="FAC456")
        url = reverse("reconciliation:inventory-detail", args=[row.pk])
        response = self.client.post(url, {"action": "preview", "version": row.business_version,
            "request_id": str(uuid4()), "entries": [target.pk]})
        self.assertContains(response, "Écriture précédente : FAC123")
        self.assertContains(response, "FAC456")
        self.assertContains(response, "Remplacer explicitement")
        response = self.client.post(url, {"action": "confirm", "version": row.business_version,
            "request_id": str(uuid4()), "entries": [target.pk], "comment": "Autre dépense vérifiée", "replace_existing": "on"})
        self.assertEqual(response.status_code, 302)
        event = self.inventory().business_events.filter(kind="LINK").first()
        self.assertEqual(event.before["link"]["allocations"][0]["document"], "FAC123")
        self.assertEqual(event.after["link"]["allocations"][0]["document"], "FAC456")
        self.assertEqual(self.inventory().inventory_match.allocations.filter(active=True).count(), 1)

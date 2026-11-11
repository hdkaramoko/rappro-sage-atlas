"""Recette du cadrage autonome sur inventaires fictifs et résultats courants."""

import copy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from reconciliation_contract import digest
from accounts.models import User
from projects.models import Project

from . import test_business as fixtures
from .accounting import accounting_state, prepare_campaign, refresh_project
from .accounting_models import AccountingGroup, AccountingProject
from .business import cancel_inventory_link, correct_inventory
from .models import CampaignGlobalControl, CampaignSageEntry, LineReview
from .review import decide, signature
from .test_control_index import synthetic_records


class AccountingTests(TestCase):
    """Les chiffres se déduisent des groupes existants, jamais de propositions supposées confirmées."""

    load = fixtures.BusinessTests.load
    inventory = fixtures.BusinessTests.inventory
    entry = fixtures.BusinessTests.entry
    confirm = fixtures.BusinessTests.confirm
    setUp = fixtures.BusinessTests.setUp

    @classmethod
    def setUpClass(cls):
        """Génère les seules sources de recette dans un dossier temporaire, puis importe en base jetable."""
        super().setUpClass()
        cls.folder_sources = TemporaryDirectory()
        cls.records = synthetic_records(Path(cls.folder_sources.name))

    @classmethod
    def tearDownClass(cls):
        """Libère les fichiers synthétiques sans toucher aux extractions utilisateur."""
        cls.folder_sources.cleanup()
        super().tearDownClass()

    def summary(self):
        """Retourne le résultat projet courant sans déclencher de calcul sur lecture."""
        return AccountingProject.objects.get(campaign=self.campaign, project_code="P")

    def test_confirmed_counts_once_and_sage_without_proposal_is_included(self):
        """6000 comptabilisés et 4000 confirmés couvrent une pièce de 10000, sans doubler Sage."""
        initial = self.summary()
        self.assertEqual(initial.atlas, Decimal("6100"))
        self.assertEqual(initial.sage, Decimal("10100"))
        self.assertEqual(Decimal(initial.data["totals"]["pending_initial"]), Decimal("4000"))
        self.assertEqual(Decimal(initial.data["totals"]["unattached_sage"]), Decimal("50"))
        self.confirm()
        result = self.summary()
        self.assertEqual((result.atlas, result.sage, result.state), (Decimal("10100"), Decimal("10100"), "CADRE"))
        fac = AccountingGroup.objects.get(control__campaign=self.campaign, control__key=self.entry().control_key)
        self.assertEqual(fac.sage, Decimal("10000"))
        self.assertEqual(fac.atlas, Decimal("10000"))
        self.assertEqual(Decimal(result.data["totals"]["confirmed"]), Decimal("4000"))
        # L'écriture de 6000 est incluse par sa clé Comptabilisé, sans proposition individuelle.
        self.assertTrue(self.campaign.sage_inventory.filter(document="FAC123", amount=6000).exists())

    def test_nonconfirmed_has_no_invented_type_and_exact_cent_rule(self):
        """Le poste NA expose le non confirmé ; l'état projet dépend de l'écart arrondi à zéro."""
        result = self.summary()
        post = next(row for row in result.data["types"] if row["type"] == "NA")
        self.assertEqual(Decimal(post["initial"]), Decimal("4000"))
        self.assertEqual(Decimal(post["atlas"]), 0)
        self.assertEqual(accounting_state(Decimal("10000"), Decimal("9500")), ("NON_CADRE", Decimal("500.00")))
        self.assertEqual(accounting_state(Decimal("10000"), Decimal("10000"))[0], "CADRE")
        self.assertEqual(accounting_state(Decimal("100"), Decimal("100.01"))[0], "NON_CADRE")
        self.assertEqual(accounting_state(None, Decimal(0))[0], "INSUFFISANT")

    def test_correction_duplicate_and_cancel_refresh_without_changing_sources(self):
        """Les ajustements changent les chiffres retenus ; annulation et doublon conservent l'initial."""
        source = self.inventory("C")
        before = copy.deepcopy(source.data)
        correct_inventory(source.pk, self.user, reason="AMOUNT", amount="10000", expected_version=0)
        self.assertEqual(self.summary().state, "CADRE")
        source.refresh_from_db()
        self.assertEqual(source.data, before)
        self.assertEqual(Decimal(self.summary().data["totals"]["adjustments"]), Decimal("4000"))
        correct_inventory(source.pk, self.user, cancel=True, expected_version=source.business_version)
        self.assertEqual(self.summary().state, "NON_CADRE")
        source.refresh_from_db()
        correct_inventory(source.pk, self.user, reason="DUPLICATE", expected_version=source.business_version)
        self.assertEqual(self.summary().atlas, Decimal("100"))
        self.assertEqual(self.summary().sage, Decimal("100"))
        self.assertEqual(Decimal(self.summary().data["totals"]["accounted_initial"]), Decimal("6100"))

    def test_source_15000_corrected_to_10000_and_missing_amount_is_not_zero(self):
        """15000 corrigés à 10000 cadrent ; une valeur source manquante reste absente, jamais zéro."""
        records = copy.deepcopy(self.records)
        for record in records:
            if record.get("type") == "inventory" and record["atlas"]["Id"] == "C":
                record["atlas"]["Total charges SAGE (€)"] = "15000"
        self.campaign = self.load(records)
        source = self.inventory("C")
        correct_inventory(source.pk, self.user, reason="AMOUNT", amount="10000", expected_version=0)
        self.assertEqual(self.summary().state, "CADRE")
        self.assertEqual(Decimal(self.summary().data["totals"]["accounted_initial"]), Decimal("15100"))
        source.data["total_sage_charges"] = None
        source.save(update_fields=["data"])
        result = refresh_project(self.campaign, "P")
        self.assertEqual(result.state, "INSUFFISANT")
        self.assertIsNone(result.data["totals"]["initial"])

    def test_explicit_historical_preparation_preserves_decisions_and_old_results(self):
        """La préparation historique lit sa photographie sans la remplacer par les décisions courantes."""
        self.confirm()
        previous = self.campaign
        before = list(previous.reviews.values_list("pk", "decision"))
        controls = list(previous.global_controls.values_list("pk", "data", "current_data"))
        self.campaign = self.load()
        prepare_campaign(previous)
        self.assertEqual(list(previous.reviews.values_list("pk", "decision")), before)
        self.assertEqual(list(previous.global_controls.values_list("pk", "data", "current_data")), controls)

    def test_link_cancellation_removes_only_confirmed_amount(self):
        """L'annulation d'un lien retire les 4000 confirmés et rétablit le poste en attente."""
        self.confirm()
        source = self.inventory()
        cancel_inventory_link(source.pk, self.user, expected_version=source.business_version)
        self.assertEqual(self.summary().gap, Decimal("-4000"))
        self.assertEqual(Decimal(self.summary().data["totals"]["confirmed"]), 0)

    def test_existing_validation_and_rejection_buttons_update_the_summary(self):
        """Les décisions du parcours existant alimentent le cadrage sans créer une validation supplémentaire."""
        line = LineReview.objects.select_related("transaction__project", "group", "campaign").get(transaction__source_id="S")
        values = {key: {"mode": "SET", "value": value} for key, value in {
            "status": "Comptabilisé", "amount": "4000", "document": "FAC123", "date": "2026-01-01"}.items()}
        for state, expected in (("VALIDATED", "CADRE"), ("REJECTED", "NON_CADRE")):
            decide(line.pk, self.user, state=state, values=values, comment="Recette cadrage",
                expected_version=line.version, expected_group_version=line.group.version,
                expected_source=signature(line), multiple_confirm=True)
            self.assertEqual(self.summary().state, expected)
            line.refresh_from_db()
            line.group.refresh_from_db()

    def test_exclusion_keeps_atlas_visible_outside_scope(self):
        """Un type exclu retire son comparateur et expose l'Atlas correspondant sans le dissimuler."""
        self.campaign.sage_inventory.filter(document="FAC123").update(eligible=False)
        result = refresh_project(self.campaign, "P")
        self.assertEqual(result.atlas, Decimal("100"))
        self.assertEqual(result.sage, Decimal("100"))
        self.assertEqual(Decimal(result.data["totals"]["outside_atlas"]), Decimal("6000"))
        self.assertEqual(Decimal(result.data["totals"]["excluded_sage"]), Decimal("10000"))

    def test_compensating_local_gaps_keep_project_balanced_and_totals_reconcile(self):
        """Deux écarts locaux se compensent au projet ; les postes par type reconstituent ses totaux."""
        self.confirm()
        controls = list(self.campaign.global_controls.order_by("pk"))
        attached = [c for c in controls if (c.current_data or c.data).get("atlas_count")]
        for control, delta in zip(attached, (Decimal("20"), Decimal("-20"))):
            data = copy.deepcopy(control.current_data or control.data)
            data["accounted_total"] = str(Decimal(data["accounted_total"]) + delta)
            control.current_data = data
            control.save(update_fields=["current_data"])
        result = refresh_project(self.campaign, "P")
        self.assertEqual(result.state, "CADRE")
        self.assertTrue(AccountingGroup.objects.filter(campaign=self.campaign, state="NON_CADRE", data__attached=True).exists())
        self.assertEqual(sum(Decimal(t["atlas"]) for t in result.data["types"]), result.atlas)
        self.assertEqual(sum(Decimal(t["sage"]) for t in result.data["types"]), result.sage)

    def test_incomplete_ods_and_reference_collision_are_not_false_balances(self):
        """Une clé ODS incomplète ou une référence Sage dupliquée rend le périmètre insuffisant."""
        control = self.campaign.global_controls.get(data__identity__strategy="ODS_ODG_BY_GROUP")
        data = copy.deepcopy(control.data)
        data["identity"]["parts"][-1] = ""
        control.current_data = data
        control.save(update_fields=["current_data"])
        result = refresh_project(self.campaign, "P")
        self.assertEqual(result.state, "INSUFFISANT")
        self.assertIsNone(result.atlas)
        entry = self.entry()
        entry.pk = None
        entry.record_id = "f" * 64
        entry.save(force_insert=True)
        self.assertTrue(any("répétée" in issue for issue in refresh_project(self.campaign, "P").data["issues"]))

    def test_views_filters_permissions_links_and_readonly_consultation(self):
        """Les pages autonomes préservent filtres et retours ; aucun accès direct hors portefeuille."""
        url = reverse("reconciliation:accounting-list")
        before = list(self.campaign.reviews.values_list("pk", "decision"))
        response = self.client.get(url, {"project": ["P"], "state": ["", "CADRE"], "q": "P"})
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertContains(response, "Cadrage comptable")
        self.assertContains(response, "Voir le détail")
        detail = reverse("reconciliation:accounting-detail", args=[self.summary().pk])
        response = self.client.get(detail, {"return": url + "?q=P", "type": "FAC"})
        self.assertContains(response, "Retour aux projets")
        self.assertContains(response, "Voir le contrôle")
        self.assertContains(response, "Non attribué / Non confirmé")
        self.assertEqual(list(self.campaign.reviews.values_list("pk", "decision")), before)
        self.client.force_login(User.objects.create_user("outsider-accounting"))
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.get(url).context["page"].paginator.count, 0)

    def test_list_cost_and_pagination_on_large_materialized_campaign(self):
        """Mesure 120 projets/12000 groupes, sans inventaire chargé, plus une lecture de maintenance explicite."""
        for index in range(120):
            code = f"BENCH{index:03d}"
            Project.objects.create(code=code, label="Recette")
        from projects.models import ProjectPortfolio
        ProjectPortfolio.objects.bulk_create([ProjectPortfolio(user=self.user, project=p) for p in Project.objects.filter(code__startswith="BENCH")])
        AccountingProject.objects.bulk_create([AccountingProject(campaign=self.campaign, project_code=f"BENCH{i:03d}",
            atlas=10000, sage=9500, gap=500, state="NON_CADRE", data={"prepared": True}) for i in range(120)])
        control = self.campaign.global_controls.first()
        # Les groupes volumineux ne sont jamais chargés par la liste des projets.
        controls = [CampaignGlobalControl(campaign=self.campaign, key=digest([i]), project_code=f"BENCH{i % 120:03d}",
                    state="ECART", current_state="ECART", data=control.data) for i in range(12000)]
        CampaignGlobalControl.objects.bulk_create(controls, batch_size=500)
        AccountingGroup.objects.bulk_create([AccountingGroup(control=c, campaign=self.campaign, project_code=c.project_code,
            piece_type="FAC", atlas=100, sage=95, gap=5, state="NON_CADRE") for c in controls], batch_size=500)
        start = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("reconciliation:accounting-list"), {"q": "BENCH", "page": 2})
        duration = perf_counter() - start
        self.assertEqual(response.context["page"].paginator.count, 120)
        self.assertEqual(len(response.context["page"]), 40)
        maintenance_queries = [query for query in queries if 'FROM "maintenance_maintenancestate"' in query["sql"]]
        self.assertEqual(len(maintenance_queries), 1)
        self.assertLess(len(queries) - len(maintenance_queries), 15)
        for query in queries:
            if 'FROM "reconciliation_campaigninventory"' in query["sql"] or 'FROM "reconciliation_campaignsageentry"' in query["sql"]:
                self.assertIn("LIMIT 1", query["sql"])
        print(f"BENCH cadrage: 120 projets / 12000 groupes, GET {duration:.3f}s, {len(queries)} requêtes")

    def test_preparation_streams_a_thousand_groups_without_per_line_queries(self):
        """Mesure la préparation de 1000 groupes Sage supplémentaires, avec écritures distinctes."""
        controls, entries = [], []
        template = self.campaign.global_controls.first().data
        for index in range(1000):
            identity = {"strategy": "STANDARD_BY_DOCUMENT", "parts": ["P", 2026, f"BEN{index}"]}
            key = digest(identity)
            data = {**template, "identity": identity, "atlas_count": 0, "accounted_total": "0",
                    "confirmed_sent_total": "0", "confirmed_allocations": [], "reasons": []}
            controls.append(CampaignGlobalControl(campaign=self.campaign, key=key, project_code="P", state="ECART", data=data))
            entries.append(CampaignSageEntry(campaign=self.campaign, record_id=digest([index, "record"]),
                entry_ref=digest([index, "ref"]), project_code="P", document=f"BEN{index}",
                control_key=key, amount=1, fiscal_year=2026, eligible=True, data={}))
        CampaignGlobalControl.objects.bulk_create(controls, batch_size=500)
        CampaignSageEntry.objects.bulk_create(entries, batch_size=500)
        start = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            result = refresh_project(self.campaign, "P")
        self.assertEqual(Decimal(result.data["totals"]["unattached_sage"]), Decimal("1050"))
        self.assertLess(len(queries), 100)
        print(f"BENCH préparation: 1000 groupes + écritures, {perf_counter() - start:.3f}s, {len(queries)} requêtes")

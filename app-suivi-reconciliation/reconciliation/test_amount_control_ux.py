"""Recette UX des états courants et des formulaires métier existants."""

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from reconciliation_contract import digest

from . import test_business as fixtures
from .business import correct_inventory
from .models import CampaignGlobalControl
from .test_control_index import synthetic_records


class AmountControlUXTests(TestCase):
    """Exerce les vues avec sources fictives et base jetable, sans modifier le métier."""

    load = fixtures.BusinessTests.load
    inventory = fixtures.BusinessTests.inventory
    entry = fixtures.BusinessTests.entry
    confirm = fixtures.BusinessTests.confirm
    setUp = fixtures.BusinessTests.setUp

    @classmethod
    def setUpClass(cls):
        """Prépare le JSONL synthétique via le moteur réel, dans un dossier temporaire."""
        super().setUpClass()
        cls.sources = TemporaryDirectory()
        cls.records = synthetic_records(Path(cls.sources.name))

    @classmethod
    def tearDownClass(cls):
        """Libère uniquement les fichiers de recette créés par cette classe."""
        cls.sources.cleanup()
        super().tearDownClass()

    def workspace(self, **parameters):
        """Teste les filtres d'état sur Toutes origines explicite, sans mutation des sources.

        Le défaut Présentes dans les deux est couvert par test_journey ; ce
        helper conserve le périmètre complet des régressions d'état/pagination.
        """
        return self.client.get(reverse("reconciliation:reviews"), {"view": "controls", "origin": "", **parameters})

    def create_control(self, index, state):
        """Crée un contrôle fictif dont l'état courant diffère de l'initial pour tester le filtre."""
        identity = {"strategy": "STANDARD_BY_DOCUMENT", "parts": ["P", 2026, f"UX-{index:03d}"]}
        data = {"identity": identity, "state": "ECART", "gap": "50", "reasons": []}
        return CampaignGlobalControl.objects.create(campaign=self.campaign, key=digest(identity), project_code="P",
            state="ECART", data=data, current_data={**data, "state": state}, has_pending=False)

    def panel(self, response, mode):
        """Extrait l'en-tête HTML du panneau nommé pour contrôler sa visibilité serveur."""
        return re.search(r'<section[^>]+id="' + mode + r'"[^>]*>', response.content.decode()).group()

    def test_current_states_all_and_multiple_filters(self):
        """Les états actuels s'unissent, Toutes prime, et projet/recherche se croisent en SQL."""
        balanced = self.create_control(1, "EQUILIBRE")
        review = self.create_control(2, "INDETERMINE")
        excluded = self.create_control(3, "EXCLU")
        response = self.workspace(control_state=["EQUILIBRE", "INDETERMINE"], project=["P"], q="UX-")
        self.assertEqual({row.pk for row in response.context["page"]}, {balanced.pk, review.pk})
        self.assertContains(response, "Plusieurs choix possibles")
        self.assertContains(response, 'value="EXCLU"')
        response = self.workspace(control_state=["", "ECART"], project=["P"], q="UX-")
        self.assertEqual({row.pk for row in response.context["page"]}, {balanced.pk, review.pk, excluded.pk})
        state_menu = response.context["filter_menus"][1]
        self.assertEqual(state_menu["selected"], [])
        self.assertEqual(self.workspace(control_state="EQUILIBRE", project="OTHER", q="UX-").context["page"].paginator.count, 1)
        self.assertEqual(self.workspace(control_state="EQUILIBRE", q="NO-SUCH-DOCUMENT").context["page"].paginator.count, 0)

    def test_pagination_preserves_selections_and_reset(self):
        """La deuxième page conserve les GET répétés et le lien de remise à zéro reste simple."""
        for index in range(60):
            self.create_control(index, "EQUILIBRE" if index % 2 else "INDETERMINE")
        response = self.workspace(control_state=["EQUILIBRE", "INDETERMINE"], project="P", q="UX-")
        self.assertEqual(response.context["page"].paginator.count, 60)
        self.assertContains(response, "control_state=EQUILIBRE&amp;control_state=INDETERMINE")
        self.assertContains(response, "q=UX-")
        self.assertContains(response, reverse("reconciliation:reviews") + '?view=controls">Réinitialiser')
        second = self.workspace(control_state=["EQUILIBRE", "INDETERMINE"], project="P", q="UX-", page=2)
        self.assertEqual(len(second.context["page"]), 10)
        self.assertFalse({row.pk for row in response.context["page"]}.intersection(row.pk for row in second.context["page"]))

    def test_modes_and_invalid_post_keep_only_own_form_visible(self):
        """Le mode stable est Recherche ; une correction invalide reste visible et sans mutation."""
        inventory = self.inventory()
        url = reverse("reconciliation:inventory-detail", args=[inventory.pk])
        response = self.client.get(url)
        self.assertIn("hidden", self.panel(response, "correct"))
        self.assertNotIn("hidden", self.panel(response, "search"))
        response = self.client.get(url, {"mode": "correct"})
        self.assertNotIn("hidden", self.panel(response, "correct"))
        self.assertIn("hidden", self.panel(response, "search"))
        response = self.client.post(url, {"action": "correct", "version": 0, "request_id": str(uuid4()),
            "reason": "AMOUNT", "amount": "", "comment": "Saisie conservée"})
        self.assertContains(response, "Renseignez le montant corrigé.")
        self.assertContains(response, "Saisie conservée")
        self.assertNotIn("hidden", self.panel(response, "correct"))
        self.assertIn("hidden", self.panel(response, "search"))
        self.assertFalse(inventory.business_events.exists())

    def test_correct_preview_confirm_and_cancel_refresh_current_state(self):
        """Les POST existants restent indépendants et les vues suivent correction, confirmation et annulation."""
        inventory = self.inventory("C")
        url = reverse("reconciliation:inventory-detail", args=[inventory.pk])
        response = self.client.post(url, {"action": "correct", "version": 0, "request_id": str(uuid4()),
            "reason": "AMOUNT", "amount": "10000,00", "comment": "Contrôle", "entries": ["invalid-ignored"]})
        self.assertEqual(response.status_code, 302)
        control = self.campaign.global_controls.get(key=self.entry().control_key)
        self.assertEqual(control.current_state, "EQUILIBRE")
        self.assertIn(control.pk, [row.pk for row in self.workspace(control_state="EQUILIBRE").context["page"]])
        inventory.refresh_from_db()
        response = self.client.post(url, {"action": "cancel_correction", "version": inventory.business_version,
            "request_id": str(uuid4())})
        self.assertEqual(response.status_code, 302)
        control.refresh_from_db()
        self.assertEqual(control.current_state, "ECART")
        source = self.inventory()
        source_url = reverse("reconciliation:inventory-detail", args=[source.pk])
        response = self.client.post(source_url, {"action": "preview", "version": 0, "request_id": str(uuid4()),
            "entries": [self.entry().pk], "amount": "invalid-ignored", "reason": "invalid-ignored"})
        self.assertContains(response, "Récapitulatif avant confirmation")
        self.assertNotIn("hidden", self.panel(response, "search"))
        self.confirm()
        control.refresh_from_db()
        self.assertEqual(control.current_state, "EQUILIBRE")
        detail = self.client.get(reverse("reconciliation:global-control-detail", args=[control.pk]))
        self.assertEqual(detail.context["control"].result["state"], "EQUILIBRE")
        self.assertEqual(detail.context["control"].data["state"], "ECART")

    def test_zero_gap_does_not_hide_remaining_reason(self):
        """L'interface affiche À revoir et son motif malgré un écart nul, sans forcer le métier."""
        control = self.create_control(99, "INDETERMINE")
        control.current_data.update(gap="0", reasons=["Preuve incomplète"])
        control.save(update_fields=["current_data"])
        response = self.client.get(reverse("reconciliation:global-control-detail", args=[control.pk]))
        self.assertContains(response, "À revoir")
        self.assertContains(response, "Preuve incomplète")
        self.assertIn(control.pk, [row.pk for row in self.workspace(control_state="INDETERMINE").context["page"]])
        self.assertNotIn(control.pk, [row.pk for row in self.workspace(control_state="EQUILIBRE").context["page"]])

    def test_source_identity_long_labels_history_and_source_links(self):
        """Les textes longs échappés restent dans les cartes et les identifiants conservent leur lien."""
        inventory = self.inventory("C")
        inventory.data.update(atlas_label="A" * 500, sage_label="<script>" + "S" * 500, sage_third_party_code="TIER-UX")
        inventory.save(update_fields=["data"])
        response = self.client.get(reverse("reconciliation:inventory-detail", args=[inventory.pk]))
        self.assertContains(response, "Code projet")
        self.assertContains(response, "TIER-UX")
        self.assertContains(response, "source-identity")
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "Aucune action métier")
        self.assertContains(response, 'class="card business-history"')
        correct_inventory(inventory.pk, self.user, reason="AMOUNT", amount="6000", expected_version=0)
        response = self.client.get(reverse("reconciliation:inventory-detail", args=[inventory.pk]))
        self.assertContains(response, self.user.username)
        self.assertNotContains(response, "Aucune action métier")
        control = self.campaign.global_controls.get(key=self.entry().control_key)
        response = self.client.get(reverse("reconciliation:global-control-detail", args=[control.pk]))
        self.assertContains(response, 'class="consultation-panel"')
        self.assertContains(response, "atlas-lines-table")
        self.assertContains(response, reverse("reconciliation:inventory-detail", args=[inventory.pk]) + "?return=")

    def test_state_filter_does_not_load_json_for_count_or_page(self):
        """La multisélection conserve le comptage SQL léger et le chargement d'une seule page."""
        with CaptureQueriesContext(connection) as queries:
            self.workspace(control_state=["ECART", "INDETERMINE"])
        controls = [q["sql"] for q in queries if 'FROM "reconciliation_campaignglobalcontrol"' in q["sql"]]
        for sql in controls:
            if "COUNT(" in sql or "LIMIT" in sql:
                self.assertNotIn("JSON_", sql)
                self.assertNotIn("COALESCE", sql)
            self.assertNotIn("CASE WHEN", sql)
        self.assertEqual(sum("COALESCE" in sql for sql in controls), 1)

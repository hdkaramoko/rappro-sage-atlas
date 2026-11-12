"""Sélection implicite et navigation des tableaux, sans recalcul des chiffres."""

import html
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from django.test import TestCase
from django.urls import reverse
from reconciliation_contract import digest
from accounts.models import User
from projects.models import Project, ProjectPortfolio

from . import test_business as fixtures
from .accounting_models import AccountingGroup, AccountingProject
from .models import Campaign, CampaignGlobalControl, CampaignInventory
from .test_control_index import synthetic_records


class AccountingUXTests(TestCase):
    """Exerce les GET publics sur des campagnes préparées ou partielles et des groupes fictifs."""

    load = fixtures.BusinessTests.load
    inventory = fixtures.BusinessTests.inventory
    entry = fixtures.BusinessTests.entry
    confirm = fixtures.BusinessTests.confirm
    setUp = fixtures.BusinessTests.setUp

    @classmethod
    def setUpClass(cls):
        """Prépare les sources synthétiques une fois ; toutes les écritures restent dans la base de test."""
        super().setUpClass()
        cls.sources = TemporaryDirectory()
        cls.records = synthetic_records(Path(cls.sources.name))

    @classmethod
    def tearDownClass(cls):
        """Libère les seuls fichiers de recette temporaires."""
        cls.sources.cleanup()
        super().tearDownClass()

    def summary(self):
        """Retourne la synthèse P initiale, sans reconstruire les agrégats."""
        return self.campaign.accounting_projects.get(project_code="P")

    def detail(self, **query):
        """Consulte le détail du projet de test avec les GET fournis ; aucun effet métier."""
        return self.client.get(reverse("reconciliation:accounting-detail", args=[self.summary().pk]), query)

    def campaign_with_summary(self, name, *, published=True, project="P"):
        """Crée une photographie minimale prête ; ne change pas la campagne courante existante."""
        campaign = Campaign.all_objects.create(name=name, scope="ux", published=published, fiscal_year=2026)
        AccountingProject.objects.create(campaign=campaign, project_code=project, atlas=0, sage=0, gap=0,
            state="CADRE", data={"prepared": True, "types": []})
        return campaign

    def test_latest_ready_published_accessible_campaign_and_legacy_parameter(self):
        """Une campagne cachée ou inaccessible ne supplante pas la dernière prête ; les vieux paramètres sont ignorés."""
        latest = self.campaign_with_summary("Photographie prête")
        self.campaign_with_summary("Préparation privée", published=False)
        self.campaign_with_summary("Campagne interdite", project="OUTSIDE")
        response = self.client.get(reverse("reconciliation:accounting-list"), {"campaign": self.campaign.pk})
        self.assertEqual(response.context["campaign"].pk, latest.pk)
        self.assertNotContains(response, 'name="campaign"')
        self.assertContains(response, "Photographie prête")
        self.assertContains(response, latest.created_at.strftime("%Y"))
        self.assertContains(response, "paramètre de campagne est ignoré")
        self.assertNotContains(response, "Campagne interdite")
        self.assertEqual(self.detail().status_code, 200)

    def test_partial_preparation_is_not_selected(self):
        """Une synthèse manquante pour un projet autorisé empêche la sélection d'une campagne partielle."""
        latest = self.campaign_with_summary("Préparation partielle")
        project = Project.objects.create(code="P2", label="Autre projet autorisé")
        ProjectPortfolio.objects.create(user=self.user, project=project)
        CampaignInventory.objects.create(campaign=latest, project_code="P2", business_key="PARTIAL", source_id="PARTIAL",
            fiscal_year=2026, data={})
        response = self.client.get(reverse("reconciliation:accounting-list"))
        self.assertEqual(response.context["campaign"].pk, self.campaign.pk)

    def test_no_published_unprepared_and_inaccessible_messages(self):
        """Les trois absences sont explicites sans noms de campagnes interdites ni erreur serveur."""
        url = reverse("reconciliation:accounting-list")
        Campaign.all_objects.update(published=False)
        self.assertContains(self.client.get(url), "Aucune campagne publiée")
        Campaign.all_objects.filter(pk=self.campaign.pk).update(published=True)
        self.campaign.accounting_projects.all().delete()
        self.assertIn("n'est pas encore préparé", self.client.get(url).context["availability"])
        self.client.force_login(User.objects.create_user("outside-ux"))
        self.assertContains(self.client.get(url), "Aucune campagne accessible")
        self.assertEqual(self.client.get(url, {"campaign": "invalide"}).status_code, 200)

    def test_independent_filters_use_stored_gaps_and_keep_unknown_in_all(self):
        """Les Sage seuls sont des écarts filtrables ; insuffisants et types exclus restent dans Toutes."""
        all_rows = self.detail()
        self.assertEqual(len(all_rows.context["type_rows"]), len(self.summary().data["types"]))
        response = self.detail(type_state="gap", group_state="balanced")
        self.assertEqual([r["type"] for r in response.context["type_rows"]], ["FAC"])
        self.assertTrue(all(row.state == "CADRE" and row.data["attached"] for row in response.context["page"]))
        response = self.detail(type_state="balanced", group_state="gap")
        self.assertEqual([r["type"] for r in response.context["type_rows"]], ["ODG"])
        self.assertEqual(response.context["page"].paginator.count, 2)
        group = self.campaign.accounting_groups.get(piece_type="ODG")
        group.state = "INSUFFISANT"
        group.save(update_fields=["state"])
        response = self.detail(type_state="balanced", group_state="balanced")
        self.assertEqual(response.context["type_rows"], [])
        self.assertEqual(response.context["page"].paginator.count, 0)
        self.assertContains(response, "Aucun type pour ce filtre")
        self.assertEqual(self.detail().context["page"].paginator.count, all_rows.context["page"].paginator.count)

    def test_group_pagination_anchors_parameters_filter_reset_and_return(self):
        """Les pages et liens descendants gardent les deux filtres ; seul le formulaire groupes remet page à 1."""
        base = self.campaign.global_controls.first()
        for index in range(60):
            identity = {"strategy": "STANDARD_BY_DOCUMENT", "parts": ["P", 2026, f"UX{index}"]}
            control = CampaignGlobalControl.objects.create(campaign=self.campaign, key=digest(identity), project_code="P",
                state="ECART", data={**base.data, "identity": identity})
            AccountingGroup.objects.create(campaign=self.campaign, control=control, project_code="P", piece_type="FAC",
                atlas=2, sage=1, gap=1, state="NON_CADRE", data={"attached": True, "excluded": False, "identity": identity})
        response = self.detail(type_state="balanced", group_state="gap", page=2)
        text = response.content.decode()
        self.assertEqual(response.context["page"].number, 2)
        self.assertIn('page=1#accounting-groups', text)
        self.assertIn('page=3#accounting-groups', text)
        self.assertIn('type_state=balanced&amp;group_state=gap', text)
        group_form = re.search(r'<form[^>]+action="[^"]*#accounting-groups".*?</form>', text, re.S).group()
        self.assertIn('name="page" value="1"', group_form)
        self.assertIn('name="type_state" value="balanced"', group_form)
        type_form = re.search(r'<form[^>]+action="[^"]*#accounting-types".*?</form>', text, re.S).group()
        self.assertIn('name="page" value="2"', type_form)
        url = html.unescape(re.search(r'href="([^"]+)">Voir le contrôle', text).group(1))
        control_response = self.client.get(url)
        self.assertTrue(control_response.context["return_url"].endswith("#accounting-groups"))
        self.assertIn("page=2", control_response.context["return_url"])

    def test_summary_and_get_filters_preserve_all_financial_results(self):
        """La consultation après confirmation et correction conserve strictement tous les montants et états."""
        self.confirm()
        from .business import correct_inventory
        source = self.inventory("O")
        correct_inventory(source.pk, self.user, reason="AMOUNT", amount="50", comment="Recette correction", expected_version=0)
        before_project = list(self.campaign.accounting_projects.values())
        before_groups = list(self.campaign.accounting_groups.values())
        for parameters in ({}, {"type_state": "gap"}, {"group_state": "balanced"}, {"page": 99}):
            response = self.detail(**parameters)
            self.assertContains(response, "accounting-main-amount")
            self.assertContains(response, "Envoyé SAGE initial")
            self.assertContains(response, "Périmètre et données disponibles")
        self.assertEqual(list(self.campaign.accounting_projects.values()), before_project)
        self.assertEqual(list(self.campaign.accounting_groups.values()), before_groups)

    def test_negative_stored_amounts_are_presented_without_conversion(self):
        """Un snapshot synthétique négatif reste négatif et filtrable, sans recalcul de son contenu."""
        group = self.campaign.accounting_groups.get(piece_type="ODG")
        group.atlas, group.sage, group.gap = -100, -100, 0
        group.save(update_fields=["atlas", "sage", "gap"])
        summary = self.summary()
        for row in summary.data["types"]:
            if row["type"] == "ODG":
                row.update(atlas="-100", sage="-100", gap="0.00")
        summary.save(update_fields=["data"])
        before = list(self.campaign.accounting_groups.values())
        response = self.detail(type_state="balanced", group_state="balanced")
        self.assertContains(response, "-100,00")
        self.assertEqual([row["type"] for row in response.context["type_rows"]], ["ODG"])
        self.assertEqual(list(self.campaign.accounting_groups.values()), before)

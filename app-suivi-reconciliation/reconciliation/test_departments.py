"""Import réel du contexte organisationnel et recette des trois filtres serveur."""

import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio
from .accounting_models import AccountingProject
from .models import Campaign, CampaignDepartment, CampaignGlobalControl
from .review_import import import_bundle


class DepartmentTests(TestCase):
    """Photographies successives et filtres ; toutes les écritures restent en base jetable."""

    @classmethod
    def setUpClass(cls):
        """Produit une campagne synthétique enrichie une seule fois, sans base utilisateur."""
        super().setUpClass()
        cls.folder = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        program = "from examples.ods_bap_filters_fixture import generate; import sys; generate(sys.argv[1], project_departments={'P': {'source':'Sante','consolidated':'SANTE','in_reference':True}})"
        subprocess.run([str(root / ".venv/Scripts/python.exe"), "-c", program, cls.folder.name],
                       cwd=root, check=True, capture_output=True, timeout=60)
        cls.records = [json.loads(s) for s in (Path(cls.folder.name) / "ods-bap.jsonl").read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        """Libère les seuls fichiers de recette créés dans le dossier temporaire."""
        cls.folder.cleanup()
        super().tearDownClass()

    def load(self, consolidated="SANTE", *, legacy=False, bad=False, pole=None, pole_source=None):
        """Importe une variante re-signée du même JSONL et retourne sa campagne.

        legacy enlève uniquement le contexte ; bad crée un périmètre contradictoire
        pour vérifier le rollback. Les sources financières restent identiques.
        pole ajoute une photographie de configuration explicite, indépendante
        de celle du moteur installé ; None conserve le vieux contrat Département.
        """
        records = json.loads(json.dumps(self.records))
        records[0]["name"] = f"Départements {consolidated} {legacy} {bad} {pole}"
        if legacy:
            records[0].pop("department_policy")
            records[0].pop("project_departments")
            records[0].pop("department_summary")
        else:
            records[0]["project_departments"]["P"] = {"source": consolidated, "consolidated": consolidated, "in_reference": True}
            if bad:
                records[0]["project_departments"]["OUTSIDE"] = records[0]["project_departments"]["P"].copy()
            if pole is not None:
                from reconciliation_contract.departments import POLE_POLICY
                records[0]["pole_policy"] = POLE_POLICY
                records[0]["pole_configuration"] = {"followed": [pole] if pole != "Hors DP" else [], "fallback": "Hors DP"}
                records[0]["project_departments"]["P"].update(pole=pole, pole_source=pole if pole_source is None else pole_source)
        lines = [json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records[:-1]]
        records[-1]["stream_sha256"] = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
        path = Path(self.folder.name) / f"{consolidated}-{legacy}-{bad}.jsonl"
        path.write_text("".join(lines) + json.dumps(records[-1], ensure_ascii=False) + "\n", encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def setUp(self):
        """Importe P puis prépare un lecteur limité et deux projets Sage supplémentaires."""
        self.campaign = self.load()
        self.user = User.objects.create_user("department-reader")
        ProjectPortfolio.objects.create(user=self.user, project=Project.objects.get(code="P"))
        self.client.force_login(self.user)
        for code, department in [("UNASSIGNED", ""), ("SECRET", "HIDDEN_DEPARTMENT")]:
            project = Project.objects.create(code=code, label=code)
            if code != "SECRET":
                ProjectPortfolio.objects.create(user=self.user, project=project)
            CampaignDepartment.objects.create(campaign=self.campaign, project_code=code, source=department, consolidated=department)
            CampaignGlobalControl.objects.create(campaign=self.campaign, project_code=code, key=code, state="ECART",
                data={"identity": {"strategy": "STANDARD_BY_DOCUMENT", "parts": [code, 2026, "FAF-TEST"]},
                      "atlas_count": 0, "sage_count": 1, "state": "ECART"})
            AccountingProject.objects.create(campaign=self.campaign, project_code=code, state="CADRE", atlas=0, sage=0,
                gap=0, data={"prepared": True})

    def response(self, view, **query):
        """Consulte une des trois vues avec filtres explicites et droits du lecteur."""
        if view == "accounting":
            return self.client.get(reverse("reconciliation:accounting-list"), query)
        return self.client.get(reverse("reconciliation:reviews"),
            {"state": "", **({"view": "controls", "control_state": ""} if view == "controls" else {}), **query})

    def test_transcoded_label_defaults_and_permissions_in_three_views(self):
        """Département affiche la cible transcodifiée, Toutes par défaut, sans fuite des options."""
        for view in ("reviews", "controls", "accounting"):
            response = self.response(view)
            self.assertEqual(response.status_code, 200)
            menu = next(m for m in response.context["filter_menus"] if m["name"] == "department")
            self.assertEqual((menu["label"], menu["selected"]), ("Département", []))
            self.assertIn("SANTE", [c["value"] for c in menu["choices"]])
            self.assertNotContains(response, "HIDDEN_DEPARTMENT")
            self.assertNotContains(response, "SECRET")
            self.assertEqual(self.response(view, department="SANTE").context["page"].paginator.count,
                             1 if view != "controls" else 6)
            self.assertEqual(self.response(view, department=["", "SANTE"]).context["page"].paginator.count,
                             response.context["page"].paginator.count)
        self.assertEqual(self.response("controls", department="__NO_DEPARTMENT__").context["page"].paginator.count, 1)
        self.assertEqual(self.response("accounting", department="__NO_DEPARTMENT__").context["page"].paginator.count, 1)
        self.assertEqual(self.response("controls", department=["SANTE", "__NO_DEPARTMENT__"]).context["page"].paginator.count, 7)
        self.assertEqual(self.response("controls", department="SANTE", piece_type="ODS/ODG", origin="both").context["page"].paginator.count, 1)
        self.assertEqual(self.response("controls", department="SANTE", q="UNASSIGNED").context["page"].paginator.count, 0)

    def test_history_import_idempotence_and_legacy(self):
        """Changer le département en N+1 ne change ni N, ni ses sources, ni les décisions."""
        first = self.campaign
        old_sources = list(first.inventory.order_by("pk").values_list("data", flat=True))
        start = perf_counter()
        current = self.load("P2S")
        self.assertEqual(first.departments.get(project_code="P").consolidated, "SANTE")
        self.assertEqual(current.departments.get(project_code="P").consolidated, "P2S")
        self.assertEqual(old_sources, list(current.inventory.order_by("pk").values_list("data", flat=True)))
        count = Campaign.objects.count()
        self.assertEqual(self.load("P2S").pk, current.pk)
        self.assertEqual(Campaign.objects.count(), count)
        legacy = self.load(legacy=True)
        self.assertEqual(legacy.departments.count(), 0)
        self.assertEqual(self.response("reviews", department="__NO_DEPARTMENT__").context["page"].paginator.count, 1)
        print(f"BENCH import enrichi synthétique + reprise/idempotence/historique : {perf_counter() - start:.3f}s")

    def test_inconsistent_scope_rolls_back(self):
        """Un rattachement hors inventaire annule l'import et préserve la campagne active."""
        count = Campaign.objects.count()
        with self.assertRaisesMessage(ValidationError, "périmètre des départements"):
            self.load(bad=True)
        self.assertEqual(Campaign.objects.count(), count)
        self.assertTrue(Campaign.objects.get(pk=self.campaign.pk).is_current)

    def test_department_filter_cost_and_pagination(self):
        """Mille projets restent filtrés en SQL par département/pôle, sans requête par ligne."""
        projects = [Project(code=f"DP{i:04}", label="Test") for i in range(1000)]
        Project.objects.bulk_create(projects)
        ProjectPortfolio.objects.bulk_create([ProjectPortfolio(user=self.user, project=p) for p in projects])
        CampaignDepartment.objects.bulk_create([CampaignDepartment(campaign=self.campaign, project_code=p.code,
            source="Test", consolidated="SANTE" if i % 2 == 0 else "P2S") for i, p in enumerate(projects)])
        AccountingProject.objects.bulk_create([AccountingProject(campaign=self.campaign, project_code=p.code,
            atlas=0, sage=0, gap=0, state="CADRE", data={"prepared": True}) for p in projects])
        start = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = self.response("accounting", department="SANTE", page=2)
        self.assertEqual(response.context["page"].paginator.count, 501)
        self.assertContains(response, "department=SANTE")
        self.assertLess(len(queries), 25)
        print(f"BENCH département : 1000 projets, {perf_counter() - start:.3f}s, {len(queries)} requêtes")
        self.campaign.metadata["pole_policy"] = "project-poles-v1"
        self.campaign.save(update_fields=["metadata"])
        self.campaign.departments.filter(consolidated="SANTE").update(pole="Agriculture")
        start = perf_counter()
        with CaptureQueriesContext(connection) as pole_queries:
            response = self.response("accounting", department="SANTE", pole="Agriculture", page=2)
        self.assertEqual(response.context["page"].paginator.count, 501)
        self.assertLess(len(pole_queries), 25)
        print(f"BENCH département+pôle : 1000 projets, {perf_counter() - start:.3f}s, {len(pole_queries)} requêtes")

    def test_pole_filters_history_and_legacy(self):
        """Les trois vues filtrent la photographie ; changer le suivi ne réécrit ni N ni les décisions."""
        previous = self.campaign
        old_decisions = list(previous.reviews.order_by("pk").values_list("source", "decision"))
        financial_fields = ("atlas", "sage", "gap", "state", "data__totals")
        financial = list(previous.accounting_projects.filter(project_code="P").values_list(*financial_fields))
        states = list(previous.reviews.order_by("pk").values_list("source__source_id", "decision__state", "decision__validation_source"))
        current = self.load(pole="Agriculture", pole_source=" Agriculture ")
        self.assertEqual(current.departments.get().pole_source, " Agriculture ")
        self.assertEqual(list(current.accounting_projects.filter(project_code="P").values_list(*financial_fields)), financial)
        self.assertEqual(list(current.reviews.order_by("pk").values_list("source__source_id", "decision__state", "decision__validation_source")), states)
        for view in ("reviews", "controls", "accounting"):
            response = self.response(view, pole="Agriculture", department="SANTE")
            menu = next(m for m in response.context["filter_menus"] if m["name"] == "pole")
            self.assertEqual(menu["label"], "Pôle")
            self.assertEqual(menu["selected"], ["Agriculture"])
            self.assertEqual(response.context["page"].paginator.count, 6 if view == "controls" else 1)
            self.assertEqual(self.response(view, pole="Agriculture", department="SANTE", q="NO-SUCH").context["page"].paginator.count, 0)
            self.assertEqual(self.response(view, pole=["", "Agriculture"]).context["page"].paginator.count,
                             self.response(view).context["page"].paginator.count)
        next_campaign = self.load(pole="Hors DP", pole_source="Agriculture")
        self.assertEqual(current.departments.get().pole, "Agriculture")
        self.assertEqual(next_campaign.departments.get().pole, "Hors DP")
        self.assertEqual(list(previous.reviews.order_by("pk").values_list("source", "decision")), old_decisions)
        legacy = self.load(legacy=True)
        self.assertEqual(legacy.departments.count(), 0)
        self.assertEqual(self.response("reviews", pole="Hors DP").context["page"].paginator.count, 1)

    def test_pole_permissions_multiselection_and_pagination(self):
        """Options et compteurs restent limités au portefeuille, avant pagination et en combinaison."""
        self.campaign.metadata["pole_policy"] = "project-poles-v1"
        self.campaign.save(update_fields=["metadata"])
        self.campaign.departments.filter(project_code="P").update(pole="Agriculture")
        self.campaign.departments.filter(project_code="SECRET").update(pole="POLE_SECRET")
        for view in ("reviews", "controls", "accounting"):
            response = self.response(view)
            self.assertNotContains(response, "POLE_SECRET")
            menu = next(m for m in response.context["filter_menus"] if m["name"] == "pole")
            self.assertEqual(menu["selected"], [])
        self.assertEqual(self.response("controls", pole="Hors DP").context["page"].paginator.count, 1)
        self.assertEqual(self.response("controls", pole=["Hors DP", "Agriculture"]).context["page"].paginator.count, 7)
        self.assertEqual(self.response("controls", pole="Hors DP", department="SANTE").context["page"].paginator.count, 0)
        self.assertEqual(self.response("controls", pole="Agriculture", piece_type="ODS/ODG").context["page"].paginator.count, 1)
        for i in range(60):
            CampaignGlobalControl.objects.create(campaign=self.campaign, project_code="P", key=f"POLE-{i}", state="ECART",
                data={"identity": {"strategy": "STANDARD_BY_DOCUMENT", "parts": ["P", 2026, f"TEST{i}"]}})
        response = self.response("controls", pole="Agriculture", department="SANTE", page=2)
        self.assertEqual(response.context["page"].paginator.count, 66)
        self.assertEqual(len(response.context["page"]), 16)
        self.assertContains(response, "pole=Agriculture")
        self.assertContains(response, "department=SANTE")

"""Recette de l'import, des droits et de l'historique BAP par campagne."""

import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio
from .models import Campaign, CampaignBapHistory, LineReview
from .review_import import import_bundle
from .templatetags.review_ui import bap_datetime_fr


class BapHistoryTests(TestCase):
    """Utilise un vrai export fictif, une base jetable et les vues publiques autorisées."""

    @classmethod
    def setUpClass(cls):
        """Génère une fois l'export enrichi sans lire ni écrire une base utilisateur."""
        super().setUpClass()
        cls.folder = TemporaryDirectory()
        root = Path(__file__).resolve().parents[2]
        code = "from examples.ods_bap_filters_fixture import generate; import sys; generate(sys.argv[1], bap_history=[{'project_code':'P','bap_sage_number':'BAP-TARGET','bap_created_at':'2026-01-02T15:30:00','bap_created_by':'Auteur <test>','bap_modified_at':'2026-01-03T17:00:00','bap_modified_by':'Modificateur test'}])"
        subprocess.run([str(root / ".venv/Scripts/python.exe"), "-c", code, cls.folder.name],
                       cwd=root, check=True, capture_output=True, timeout=60)
        cls.records = [json.loads(s) for s in (Path(cls.folder.name) / "ods-bap.jsonl").read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        """Supprime uniquement les fichiers fictifs du dossier de recette."""
        cls.folder.cleanup()
        super().tearDownClass()

    def load(self, *, legacy=False, changed=False, bad=False):
        """Re-signe une variante de contexte sans modifier les données métier.

        legacy supprime la capacité, changed change une date, bad forge un projet
        hors inventaire. L'import nominal doit rester atomique et idempotent.
        """
        rows = json.loads(json.dumps(self.records))
        rows[0]["name"] = f"BAP {legacy} {changed} {bad}"
        if legacy:
            rows = [r for r in rows if r.get("type") != "bap_history"]
            rows[0].pop("bap_history_policy")
            rows[0].pop("bap_history_summary")
            rows[-1].pop("bap_history_count")
        else:
            for row in rows:
                if row.get("type") == "bap_history":
                    if changed:
                        row["data"]["bap_created_at"] = "2026-04-02T10:00:00"
                    if bad:
                        row["data"]["project_code"] = "OUTSIDE"
        lines = [json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in rows[:-1]]
        rows[-1]["stream_sha256"] = hashlib.sha256("".join(lines).encode()).hexdigest()
        path = Path(self.folder.name) / "input.jsonl"
        path.write_text("".join(lines) + json.dumps(rows[-1]) + "\n", encoding="utf-8")
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def setUp(self):
        """Importe P et autorise uniquement son lecteur, sans élargir le portefeuille."""
        self.campaign = self.load()
        self.user = User.objects.create_user("bap-reader")
        ProjectPortfolio.objects.create(user=self.user, project=Project.objects.get(code="P"))
        self.client.force_login(self.user)

    def test_dates_in_list_authors_only_in_detail_and_permissions(self):
        """Liste compacte, auteurs échappés dans la fiche, aucun accès hors portefeuille."""
        row = LineReview.objects.get(transaction__source_id="BAP-TARGET")
        response = self.client.get(reverse("reconciliation:reviews"), {"state": ""})
        self.assertContains(response, "Date de création du BAP")
        self.assertContains(response, "02/01/2026 à 15:30")
        self.assertNotContains(response, "Auteur &lt;test&gt;")
        response = self.client.get(reverse("reconciliation:review-detail", args=[row.pk]))
        self.assertContains(response, "Historique du BAP")
        self.assertContains(response, "Auteur &lt;test&gt;")
        self.assertContains(response, "03/01/2026 à 17:00")
        self.assertNotContains(response, 'name="bap_created_at"')
        self.client.force_login(User.objects.create_user("bap-outsider"))
        self.assertEqual(self.client.get(reverse("reconciliation:review-detail", args=[row.pk])).status_code, 404)
        response = self.client.get(reverse("reconciliation:reviews"), {"state": ""})
        self.assertNotContains(response, "Auteur &lt;test&gt;")

    def test_history_and_business_results_stay_in_their_campaign(self):
        """Changer un horodatage ne change ni décisions, ni montants, ni contexte de N."""
        first = self.campaign
        decisions = list(first.reviews.values_list("source__source_id", "decision__state", "decision__validation_source"))
        sources = list(first.inventory.order_by("business_key").values_list("data", flat=True))
        amounts = list(first.accounting_projects.values_list("project_code", "atlas", "sage", "gap", "state"))
        second = self.load(changed=True)
        self.assertEqual(first.bap_history.get().bap_created_at, "2026-01-02T15:30:00")
        self.assertEqual(second.bap_history.get().bap_created_at, "2026-04-02T10:00:00")
        self.assertEqual(list(second.reviews.values_list("source__source_id", "decision__state", "decision__validation_source")), decisions)
        self.assertEqual(list(second.inventory.order_by("business_key").values_list("data", flat=True)), sources)
        self.assertFalse(second.inventory.exclude(change="UNCHANGED").exists())
        self.assertEqual(list(second.accounting_projects.values_list("project_code", "atlas", "sage", "gap", "state")), amounts)
        snapshot = first.reviews.get()
        response = self.client.get(reverse("reconciliation:campaign-review", args=[snapshot.pk]))
        self.assertContains(response, "02/01/2026 à 15:30")
        self.assertNotContains(response, "02/04/2026 à 10:00")
        count = Campaign.objects.count()
        self.assertEqual(self.load(changed=True).pk, second.pk)
        self.assertEqual(Campaign.objects.count(), count)

    def test_legacy_missing_history_and_atomic_rollback(self):
        """Un contexte hors JDD annule l'import ; une ancienne campagne n'invente aucune date."""
        with self.assertRaises(ValidationError):
            self.load(bad=True)
        self.assertEqual(Campaign.objects.count(), 1)
        old = self.load(legacy=True)
        self.assertFalse(old.bap_history.exists())
        row = LineReview.objects.get(transaction__source_id="BAP-TARGET")
        response = self.client.get(reverse("reconciliation:review-detail", args=[row.pk]))
        self.assertContains(response, "Non renseigné")
        self.assertNotContains(response, "02/01/2026 à 15:30")

    def test_page_history_has_no_n_plus_one(self):
        """Cinquante lignes partageant un BAP nécessitent une seule lecture d'historique."""
        line = LineReview.objects.select_related("transaction", "group").get(transaction__source_id="BAP-TARGET")
        for i in range(49):
            source = type(line.transaction).objects.get(pk=line.transaction_id)
            source.pk, source.source_id, source.business_key = None, f"HISTORY-{i}", f"HISTORY-{i}"
            source.save(force_insert=True)
            LineReview.objects.create(transaction=source, group=line.group, campaign=self.campaign)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("reconciliation:reviews"), {"state": "", "page_size": "50"})
        self.assertEqual(response.context["page"].paginator.count, 50)
        history_queries = [q for q in queries if 'FROM "reconciliation_campaignbaphistory"' in q["sql"]]
        self.assertEqual(len(history_queries), 1)
        self.assertEqual(CampaignBapHistory.objects.filter(campaign=self.campaign).count(), 1)

    def test_french_date_formatting_preserves_naive_time(self):
        """Affiche l'heure significative sans décalage implicite ni date fabriquée."""
        self.assertEqual(bap_datetime_fr("2026-01-02T00:00:00"), "02/01/2026")
        self.assertEqual(bap_datetime_fr("2026-01-02T15:30:00"), "02/01/2026 à 15:30")
        self.assertEqual(bap_datetime_fr("2026-01-02T15:30:05.12"), "02/01/2026 à 15:30:05.12")
        self.assertEqual(bap_datetime_fr(None), "—")

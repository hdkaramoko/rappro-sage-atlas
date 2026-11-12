"""Concurrence PostgreSQL réelle des nouvelles réservations d'inventaire."""

import copy
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase
from reconciliation_contract import digest

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .business import confirm_inventory_link
from .models import Campaign, ManualAllocation
from .review_import import import_bundle
from .test_sage_inventory import sign_records


@skipUnless(connection.vendor == "postgresql", "Réservations concurrentes : PostgreSQL requis")
class BusinessConcurrencyTests(TransactionTestCase):
    """Deux connexions demandent la même écriture ; le verrou campagne les sérialise."""

    def test_only_one_conflicting_confirmation_can_commit(self):
        """Une seule des deux confirmations incompatibles aboutit, sans double consommation.

        Crée une campagne fictive et deux utilisateurs indépendants de connexion.
        Les fichiers et la base sont ceux de la recette, jamais de production.
        """
        with TemporaryDirectory() as folder:
            root = Path(__file__).resolve().parents[2]
            subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.lot1_fixture", folder],
                           cwd=root, check=True, capture_output=True, timeout=60)
            path = Path(folder) / "campaign.jsonl"
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            original = next(r for r in records if r.get("type") == "proposal")
            original.pop("auto_validation", None)
            row = {**original["atlas"][0], "Id": "S2"}
            records.insert(1, {"type": "inventory", "atlas": row})
            proposal = copy.deepcopy(original)
            proposal.update(key=digest(["S2"]), atlas=[row])
            records.insert(next(i for i, r in enumerate(records) if r.get("type") == "control"), proposal)
            records[-1]["complete"] += 1
            records[-1]["inventory_count"] += 1
            sign_records(records)
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
            import_bundle(path)
            campaign = Campaign.objects.get(is_current=True)
            user = User.objects.create_user("lot2-concurrent")
            ProjectPortfolio.objects.create(user=user, project=Project.objects.get(code="P"))
            entry_id = campaign.sage_inventory.get(document="FAC123", amount="4000").pk
            inventory_ids = list(campaign.inventory.filter(source_id__in=["S", "S2"]).values_list("pk", flat=True))
            barrier = Barrier(2)

            def attempt(pk):
                """Confirme sur connexion isolée après barrière ; retourne OK ou CONFLICT."""
                try:
                    actor = User.objects.get(pk=user.pk)
                    barrier.wait(timeout=20)
                    try:
                        confirm_inventory_link(pk, actor, entry_ids=[entry_id], comment="Contrôle concurrent",
                                               expected_version=0)
                        return "OK"
                    except ValidationError:
                        return "CONFLICT"
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(attempt, inventory_ids))
            self.assertCountEqual(results, ["OK", "CONFLICT"])
            self.assertEqual(ManualAllocation.objects.filter(active=True, entry_id=entry_id).count(), 1)

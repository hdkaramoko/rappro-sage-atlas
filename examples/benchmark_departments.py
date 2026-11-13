"""Mesure avant/après sur données fictives, bases et sorties entièrement temporaires."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import pandas as pd

from reconciliation.exporters.review import export_review_bundle
from reconciliation.matching import match_reconciliations
from reconciliation.multiples import build_controls
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage


def benchmark(projects=200, entries=10, *, include_poles=False):
    """Compare exports/imports/GET avec contexte identique, hors politique département.

    projects et entries fixent la population synthétique. Le matching est exécuté
    une seule fois ; les corps JSONL doivent rester identiques. Deux processus
    migrent des bases SQLite neuves avant chronométrage de l'import et des trois
    vues. Retourne les mesures ; propage les erreurs. Ne lit aucune base métier.
    include_poles compare une campagne Département existante à son extension
    Pôle, avec une liste fictive limitée à la recette et le même périmètre filtré.
    """
    left, right = [], []
    table = {}
    for p in range(projects):
        code = f"PROJ{p:04}"
        table[code] = {"source": "Département test", "consolidated": "SANTE" if p % 2 == 0 else "P2S", "in_reference": True}
        if include_poles:
            table[code].update(pole="Agriculture" if p % 2 == 0 else "Hors DP", pole_source="Agriculture" if p % 2 == 0 else "Autre")
        for i in range(entries):
            label = "COMP" if i == 0 else "SENT" if i == 1 else f"AUTRE{i}"
            right.append({"Projet": code, "Numéro pièce": f"FAC{p:04}{i:03}", "Date comptable": "2026-01-01",
                          "Journal": "ACH", "N° de ligne comptable": "1", "N° de ligne Analytique": "1",
                          "Charges (Dépenses)": "100", "Code Tiers - Tiers doc Orig": "T", "Libellé pièce": label})
            if i < 2:
                left.append({"Code projet": code, "Id": f"{p}-{i}", "Année": 2026,
                    "Statut BAP": "Comptabilisé" if i == 0 else "Envoyé SAGE", "Code tiers SAGE": "T",
                    "Libellé ATLAS": label, "Libellé SAGE": label, "Total charges projet (€)": "100",
                    "Total charges SAGE (€)": "100" if i == 0 else None,
                    "N° pièce SAGE": f"FAC{p:04}{i:03}" if i == 0 else "",
                    "Date comptable": "2026-01-01" if i == 0 else None})
    atlas, sage = transform_atlas(pd.DataFrame(left)), transform_sage(pd.DataFrame(right))
    result = match_reconciliations(atlas, sage)
    root = Path(__file__).resolve().parents[1]
    measures, hashes = {}, []
    program = '''
import json, os, sys, time
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
from django.conf import settings
settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': sys.argv[2]}}
settings.ALLOWED_HOSTS = ['testserver']
import django
django.setup()
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from accounts.models import User
from reconciliation.review_import import import_bundle
from reconciliation.models import Campaign
call_command('migrate', verbosity=0, interactive=False)
start = time.perf_counter()
import_bundle(sys.argv[1])
results = {'import_seconds': time.perf_counter() - start}
campaign = Campaign.objects.get(is_current=True)
user = User.objects.create_superuser('bench', password='test')
client = Client()
client.force_login(user)
for name, query in [('reviews', {'state': ''}), ('controls', {'view':'controls', 'control_state':''}), ('accounting', {})]:
    url = reverse('reconciliation:accounting-list' if name == 'accounting' else 'reconciliation:reviews')
    client.get(url, query)
    if sys.argv[4] == 'poles':
        query['department'] = 'SANTE'
    if sys.argv[3] == 'enriched':
        query['department'] = 'SANTE'
        if sys.argv[4] == 'poles':
            query['pole'] = 'Agriculture'
    start = time.perf_counter()
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, query)
    assert response.status_code == 200
    results[name] = {'seconds': time.perf_counter() - start, 'queries':len(queries)}
results['counts'] = {'atlas': campaign.inventory.count(), 'sage': campaign.sage_inventory.count(),
                    'controls': campaign.global_controls.count(), 'auto':campaign.reviews.filter(line__validation_source='AUTO',line__state='VALIDATED').count()}
results['financial_snapshot'] = list(campaign.accounting_projects.order_by('project_code').values('project_code','atlas','sage','gap','state','data__totals'))
print(json.dumps(results, default=str))
'''
    with TemporaryDirectory() as folder:
        baseline = {code: {k: v for k, v in row.items() if k not in ("pole", "pole_source")} for code, row in table.items()} if include_poles else None
        for name, departments in [("baseline", baseline), ("enriched", table)]:
            start = perf_counter()
            path = export_review_bundle(atlas, sage, result, Path(folder) / f"{name}.jsonl", year=2026,
                controls=build_controls(atlas, sage, result), include_sage_inventory=True, project_departments=departments,
                pole_configuration={"followed": ["Agriculture"], "fallback": "Hors DP"} if include_poles and name == "enriched" else None)
            export_seconds = perf_counter() - start
            lines = path.read_bytes().splitlines()
            hashes.append(hashlib.sha256(b"\n".join(lines[1:-1])).hexdigest())
            imported = subprocess.run([sys.executable, "-c", program, str(path), str(Path(folder) / f"{name}.sqlite3"), name, "poles" if include_poles else "departments"],
                cwd=root / "app-suivi-reconciliation", capture_output=True, text=True, check=True, timeout=180)
            measures[name] = {"export_seconds": export_seconds, "jsonl_bytes": path.stat().st_size,
                              **json.loads(imported.stdout.splitlines()[-1])}
    assert hashes[0] == hashes[1], "Le contexte départemental a changé des enregistrements métier"
    assert measures["baseline"]["counts"] == measures["enriched"]["counts"]
    assert measures["baseline"]["financial_snapshot"] == measures["enriched"]["financial_snapshot"]
    for measure in measures.values():
        measure.pop("financial_snapshot")
    return {"projects": projects, "entries_per_project": entries, "identical_business_records": True, **measures}


if __name__ == "__main__":
    print(json.dumps(benchmark(include_poles="--poles" in sys.argv), ensure_ascii=False, indent=2))

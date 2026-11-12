"""Mesure reproductible du lot 1 sur données synthétiques et base SQLite temporaire."""

import json
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from reconciliation.exporters.review import export_review_bundle
from reconciliation.matching import match_reconciliations
from reconciliation.multiples import build_controls
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage


def benchmark(count: int = 10000) -> dict:
    """Mesure export/import de `count` pièces sans écrire dans une base existante.

    Retourne secondes, taille JSONL, pic mémoire Python d'import et compteurs.
    Chaque pièce possède une écriture ; une seule est présente dans Atlas.
    Les fichiers et la base sont isolés dans TemporaryDirectory puis supprimés.
    Lève CalledProcessError si migration ou import du processus isolé échoue.
    """
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory() as folder:
        atlas = transform_atlas(pd.DataFrame([{
            "Id": "A", "Code projet": "P", "Année": 2026, "Statut BAP": "Comptabilisé",
            "Total charges projet (€)": "100", "Total charges SAGE (€)": "100",
            "N° pièce SAGE": "FAC000000", "Date comptable": "2026-01-01", "Devise": "EUR"}]))
        sage = transform_sage(pd.DataFrame([{
            "Projet": "P", "Numéro pièce": f"FAC{i:06}", "Date comptable": "2026-01-01",
            "Journal": "ACH", "N° de ligne comptable": "001", "N° de ligne Analytique": "01",
            "Charges (Dépenses)": "100", "Devise": "EUR"} for i in range(count)]))
        start = time.perf_counter()
        result = match_reconciliations(atlas, sage)
        path = export_review_bundle(atlas, sage, result, Path(folder) / "campaign.jsonl",
                                    controls=build_controls(atlas, sage, result), include_sage_inventory=True)
        export_seconds = time.perf_counter() - start
        code = '''
import json, os, sys, time, tracemalloc
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
from django.conf import settings
settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": sys.argv[2]}}
import django
django.setup()
from django.core.management import call_command
call_command("migrate", verbosity=0, interactive=False)
from reconciliation.review_import import import_bundle
from reconciliation.models import Campaign
tracemalloc.start()
start = time.perf_counter()
import_bundle(sys.argv[1])
seconds = time.perf_counter() - start
_, peak = tracemalloc.get_traced_memory()
campaign = Campaign.objects.get(is_current=True)
print(json.dumps({"import_seconds": round(seconds, 3), "peak_python_mib": round(peak / 1024**2, 3),
                  "sage_count": campaign.sage_inventory.count(), "global_count": campaign.global_controls.count()}))
'''
        imported = subprocess.run([sys.executable, "-c", code, str(path), str(Path(folder) / "benchmark.sqlite3")],
                                  cwd=root / "app-suivi-reconciliation", capture_output=True, text=True, check=True)
        return {"population": count, "export_seconds": round(export_seconds, 3),
                "jsonl_mib": round(path.stat().st_size / 1024**2, 3), **json.loads(imported.stdout)}


if __name__ == "__main__":
    print(json.dumps(benchmark(int(sys.argv[1]) if len(sys.argv) > 1 else 10000), indent=2))

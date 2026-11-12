"""Compare le cadrage HEAD et modifié sur une copie SQLite privée, jamais sur la source."""

import argparse
from collections import Counter
from contextlib import ExitStack, closing
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


def source_digest(db, campaign_id):
    """Signe les inventaires et décisions en flux, sans exporter leurs contenus ni les modifier."""
    result = hashlib.sha256()
    for table, fields in (("campaigninventory", "id,data,business_version"),
                          ("campaignsageentry", "id,data,amount,eligible"),
                          ("campaignreview", "id,source,decision"),
                          ("linereview", "id,state,version")):
        for row in db.execute(f"SELECT {fields} FROM reconciliation_{table} WHERE campaign_id=? ORDER BY id", (campaign_id,)):
            result.update(repr(row).encode())
    return result.hexdigest()


def summaries(campaign):
    """Retourne les synthèses par code privé pour comparer états, sommes et motifs avant anonymisation."""
    return {row.project_code: {"state": row.state, "atlas": str(row.atlas) if row.atlas is not None else None,
        "sage": str(row.sage) if row.sage is not None else None, "totals": row.data["totals"],
        "issues": row.data["issues"], "diagnostics": row.data.get("diagnostics", [])}
        for row in campaign.accounting_projects.all().iterator(chunk_size=100)}


def audit(source, output):
    """Copie la source en lecture seule, analyse SQLite puis mesure deux préparations complètes.

    Le rapport contient des alias de projets et des montants agrégés. Les données
    sources et décisions doivent garder la même empreinte. La copie temporaire
    est supprimée après fermeture ; aucune migration ou activation n'est faite.
    """
    source = source.resolve()
    baseline = subprocess.run(["git", "show", "HEAD:app-suivi-reconciliation/reconciliation/accounting.py"],
        cwd=ROOT, check=True, capture_output=True).stdout.decode("utf-8")
    with TemporaryDirectory(prefix="sage-atlas-accounting-") as folder, ExitStack() as resources:
        target = Path(folder) / "audit.sqlite3"
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original, closing(sqlite3.connect(target)) as copied:
            original.backup(copied, pages=2048)
        sys.path.insert(0, str(ROOT / "app-suivi-reconciliation"))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        from django.conf import settings
        settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(target), "OPTIONS": {"timeout": 30}}}
        settings.DEBUG = False
        import django
        django.setup()
        from django.db import connection, connections
        resources.callback(connections.close_all)
        from reconciliation.models import Campaign
        from reconciliation.sqlite_statistics import maintain_statistics
        from reconciliation import accounting
        campaign = Campaign.objects.filter(is_current=True).get()
        maintenance_statistics = maintain_statistics(force=True)
        if maintenance_statistics["status"] not in ("executed", "skipped"):
            raise RuntimeError("Statistiques de la copie indisponibles")
        connection.ensure_connection()
        digest_before = source_digest(connection.connection, campaign.pk)
        namespace = {"__name__": "reconciliation._accounting_before", "__package__": "reconciliation"}
        exec(compile(baseline, "accounting_before.py", "exec"), namespace)
        timings, query_counts, results, project_times = {}, {}, {}, {}
        volumes = {"atlas": campaign.inventory.count(), "sage": campaign.sage_inventory.count()}
        for name, prepare in (("before", namespace["prepare_campaign"]), ("after", accounting.prepare_campaign)):
            query_count = 0

            def count_query(execute, sql, params, many, context):
                """Compte les appels SQL de la mesure courante sans conserver SQL ni paramètres."""
                nonlocal query_count
                query_count += 1
                return execute(sql, params, many, context)

            def progress(phase, count):
                """Affiche une progression sans code projet, montant ni donnée source."""
                if count % 100 == 0:
                    print(f"{name}: {count} projets", flush=True)

            started = perf_counter()
            owner = prepare.__globals__
            original_refresh = owner["refresh_project"]
            durations = []

            def measured_refresh(campaign, project):
                """Chronomètre un appel projet réel sans modifier son résultat ni ses garanties transactionnelles."""
                begin = perf_counter()
                try:
                    return original_refresh(campaign, project)
                finally:
                    durations.append(perf_counter() - begin)

            owner["refresh_project"] = measured_refresh
            try:
                with connection.execute_wrapper(count_query):
                    count = prepare(campaign, progress=progress)
            finally:
                owner["refresh_project"] = original_refresh
            timings[name] = round(perf_counter() - started, 3)
            durations.sort()
            project_times[name] = {"median": round(statistics.median(durations), 6),
                "p95": round(durations[min(len(durations)-1, int(len(durations)*0.95))], 6),
                "max": round(max(durations), 6)} if durations else {}
            query_counts[name] = query_count
            results[name] = summaries(campaign)
            print(f"{name}: terminé ({count} projets, {timings[name]} s)", flush=True)
        after = results["after"]
        before = results["before"]
        changed = []
        reasons = Counter()
        for number, code in enumerate(sorted(after), 1):
            old, new = before[code], after[code]
            if (old["state"], old["sage"], old["atlas"]) != (new["state"], new["sage"], new["atlas"]):
                motifs = []
                old_sage, new_sage = old["totals"].get("sage"), new["totals"].get("sage")
                if ((Decimal(old_sage) if old_sage is not None else None)
                        != (Decimal(new_sage) if new_sage is not None else None)):
                    motifs.append("Périmètre Sage exhaustif ou dédoublonnage technique")
                if old["issues"] != new["issues"]:
                    motifs.append("Distinction diagnostic individuel / blocage global")
                reasons.update(motifs)
                changed.append({"project": f"P{number:05d}", "before": old, "after": new, "motifs": motifs})
        # Vérifie aussi la réconciliation exacte des groupes et types.
        # SUM natif SQLite convertit en flottants : sommer ici en Decimal,
        # comme le service nominal, sans changer la tolérance de comparaison.
        grouped = {}
        oda_counts = Counter()
        for code, data in campaign.accounting_groups.values_list("project_code", "data").iterator(chunk_size=500):
            atlas, sage = data["totals"]["atlas"], data["totals"]["sage"]
            aggregate = grouped.setdefault(code, {"atlas_sum": Decimal(0), "sage_sum": Decimal(0)})
            aggregate["atlas_sum"] += Decimal(atlas) if atlas is not None else Decimal(0)
            aggregate["sage_sum"] += Decimal(sage) if sage is not None else Decimal(0)
            if "oda" in data:
                oda_counts["reliable" if data["oda"]["reliable"] else "review"] += 1
        mismatches = []
        type_mismatches = []
        for code, row in after.items():
            aggregate = grouped.get(code, {})
            for field in ("atlas", "sage"):
                expected = row["totals"].get(field) if row[field] is not None else None
                if expected is not None and (aggregate.get(field + "_sum") or Decimal(0)) != Decimal(expected):
                    mismatches.append({"project": f"P{sorted(after).index(code)+1:05d}", "field": field})
        for number, (code, data) in enumerate(campaign.accounting_projects.order_by("project_code").values_list("project_code", "data").iterator(chunk_size=100), 1):
            for field in ("atlas", "sage"):
                if after[code][field] is not None and all(row.get(field) is not None for row in data["types"]):
                    total = sum((Decimal(row[field]) for row in data["types"]), Decimal(0))
                    if total != Decimal(data["totals"][field]):
                        type_mismatches.append({"project": f"P{number:05d}", "field": field})
        source_unchanged = digest_before == source_digest(connection.connection, campaign.pk)
        report = {"projects": len(after), "volumes": volumes, "seconds": timings, "queries": query_counts,
            "refresh_project_seconds": project_times, "oda_diagnostics": dict(oda_counts),
            "statistics": maintenance_statistics, "states_before": dict(Counter(row["state"] for row in before.values())),
            "states_after": dict(Counter(row["state"] for row in after.values())),
            "sage_total_before": str(sum((Decimal(row["totals"].get("sage") or 0) for row in before.values()), Decimal(0))),
            "sage_total_after": str(sum((Decimal(row["totals"].get("sage") or 0) for row in after.values()), Decimal(0))),
            "sources_and_decisions_unchanged": source_unchanged, "group_total_mismatches": mismatches,
            "type_total_mismatches": type_mismatches,
            "insufficient_before": [{"project": f"P{number:05d}", "before_issues": before[code]["issues"],
                "after_state": after[code]["state"], "after_issues": after[code]["issues"]}
                for number, code in enumerate(sorted(after), 1) if before[code]["state"] == "INSUFFISANT"],
            "changed_projects": changed, "motifs": dict(reasons)}
        connections.close_all()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key not in ("changed_projects", "insufficient_before")}, ensure_ascii=True), flush=True)
        if not source_unchanged or mismatches or type_mismatches:
            raise RuntimeError("Audit d'intégrité non conforme : consulter le rapport")


def main():
    """Lit les chemins explicites puis lance l'audit privé ; aucune base de travail n'est ciblée en écriture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.source, args.output)


if __name__ == "__main__":
    main()

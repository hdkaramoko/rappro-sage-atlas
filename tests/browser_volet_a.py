"""Recette graphique des vrais tableaux du volet A sur données fictives, sans requête SQL."""

import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


def run(output):
    """Rend les composants Django puis vérifie leur géométrie dans Chrome headless.

    `output` reçoit HTML et captures desktop/mobile synthétiques. Aucun serveur,
    migration ou import ; un garde interdit toute requête SQL. Retourne les
    mesures des deux tailles ; RuntimeError si débordement, colonne manquante
    ou navigateur absent, TimeoutExpired si le navigateur ne termine pas.
    """
    root = Path(__file__).resolve().parents[1]
    app = root / "app-suivi-reconciliation"
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(app))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.db import connection
    from django.core.paginator import Paginator
    from django.http import QueryDict
    from django.template.loader import render_to_string

    browser = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not browser.exists():
        raise RuntimeError("Chrome absent : recette graphique non exécutée")
    destination = Path(output).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    request = SimpleNamespace(GET=QueryDict("sage_page=1"), get_full_path=lambda: "/controle/1/?sage_page=1")
    atlas = [SimpleNamespace(pk=i, source_id=str(i), atlas_bap="BAP-ATLAS-" + "0123456789" * 10,
        data=dict(bap_status="Comptabilisé", sage_label="Libellé Sage dans Atlas " * 12, total_sage_charges="362.25")) for i in range(1, 3)]
    sage = [dict(date="2026-01-01", document="CIF0126040938", third_party="M81412", bap="BAP-SAGE-" + "ABCDEFGHIJ" * 10,
        label="Libellé Sage extraction " * 12, amount="-362.25") for _ in range(2)]
    context = dict(page=Paginator(atlas, 25).page(1), sage_page=Paginator(sage, 25).page(1), request=request)

    def no_sql(execute, sql, params, many, execution_context):
        """Refuse toute tentative SQL pendant le rendu, sans afficher ses paramètres."""
        raise RuntimeError("Une recette de présentation ne doit pas interroger une base")

    with connection.execute_wrapper(no_sql):
        tables = '<section class="card"><h2>Lignes Atlas concernées</h2>' + render_to_string("components/atlas_control_lines.html", context) + '</section>'
        tables += '<section class="card"><h2>Écritures Sage concernées</h2>' + render_to_string("components/sage_control_lines.html", context) + '</section>'
    checks = """
let checks = 0;
function expect(condition, reason) { checks++; if (!condition) throw Error(reason); }
try {
  expect(document.querySelectorAll('.atlas-lines-table th').length === 5, 'Colonnes Atlas');
  expect(document.querySelectorAll('.sage-control-table th').length === 6, 'Colonnes Sage');
  expect(document.body.textContent.includes('BAP-SAGE-'), 'Référence Sage');
  expect(document.body.textContent.includes('BAP-ATLAS-'), 'Référence Atlas');
  expect(document.documentElement.scrollWidth <= innerWidth + 1, 'Débordement de la page');
  document.querySelectorAll('.table-scroll').forEach(container => {
    expect(container.getBoundingClientRect().right <= innerWidth + 1, 'Conteneur hors écran');
    expect(['auto','scroll'].includes(getComputedStyle(container).overflowX), 'Défilement horizontal manquant');
    if (innerWidth < 720) expect(container.scrollWidth > container.clientWidth, 'Colonnes mobiles perdues');
  });
  document.getElementById('test-result').textContent=JSON.stringify({ok:true,checks,width:innerWidth});
} catch(error) { document.getElementById('test-result').textContent=JSON.stringify({ok:false,checks,error:String(error),width:innerWidth}); }
"""
    document = '<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    for css in ("app.css", "workspace.css"):
        document += '<link rel="stylesheet" href="' + (app / "static/css" / css).as_uri() + '">'
    document += '<body><main class="main-content"><h1>Contrôle des montants · Recette fictive</h1><div class="control-detail-stack">' + tables
    document += '</div></main><output hidden id="test-result"></output><script>' + checks + '</script></body></html>'
    page = destination / "tables.html"
    page.write_text(document, encoding="utf-8")
    results = []
    for name, width in (("desktop", 1440), ("mobile", 390)):
        target = page
        if name == "mobile":
            # Le cadre impose 390 px réels malgré la largeur minimale du navigateur headless Windows.
            target = destination / "mobile.html"
            target.write_text('<!doctype html><meta charset="utf-8"><body style="margin:0;width:390px">'
                '<iframe style="display:block;width:390px;height:1100px;border:0" srcdoc="' + html.escape(document, quote=True) +
                '" onload="document.getElementById(\'test-result\').textContent=this.contentDocument.getElementById(\'test-result\').textContent"></iframe>'
                '<output hidden id="test-result"></output></body>', encoding="utf-8")
        with TemporaryDirectory(prefix="volet-a-browser-") as profile:
            completed = subprocess.run([str(browser), '--headless', '--disable-gpu', '--disable-background-networking',
                '--no-first-run', '--hide-scrollbars', f'--user-data-dir={profile}', f'--window-size={width},1100',
                '--screenshot=' + str(destination / f"{name}.png"), '--dump-dom', target.as_uri()],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        match = re.search(r'<output hidden="" id="test-result">(.*?)</output>', completed.stdout, re.S)
        if not match:
            raise RuntimeError("Résultat navigateur absent : " + completed.stderr[-800:])
        result = json.loads(html.unescape(match.group(1)))
        if not result.get("ok"):
            raise RuntimeError(str(result))
        results.append({"screen": name, **result})
    return results


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1]), ensure_ascii=True))

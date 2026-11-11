"""Recette DOM du vrai JavaScript dans Chrome/Edge headless, sans serveur métier."""

import html
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def run():
    """Exécute coches/décoches, conflits et saisies manuelles sur un DOM isolé.

    Utilise Chrome/Edge déjà installé, un profil temporaire et le JavaScript du
    dépôt. Aucune dépendance téléchargée, base ni source réelle. Retourne le
    nombre d'assertions ; RuntimeError en cas d'échec et TimeoutExpired si bloqué.
    """
    root = Path(__file__).resolve().parents[1]
    browsers = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]
    browser = next((p for p in browsers if p.exists()), None)
    if browser is None:
        raise RuntimeError("Chrome/Edge absent : recette navigateur non exécutée")
    entries = [dict(ref=str(i), amount=amount, document=document, date=date)
        for i, (amount, document, date) in enumerate([
            ("600", "D", "2026-01-01"), ("400", "D", "2026-01-01"),
            ("-100.123456789", "D", "2026-01-01"), ("0", "D", "2026-01-01"),
            ("25", "E", "2026-01-02")])]
    controls = ''.join(f'<select name="{name}_mode"><option>KEEP</option><option>SET</option><option>CLEAR</option></select><input name="{name}" id="id_{name}">'
                       for name in ("amount", "document", "date"))
    controls += ''.join(f'<input type="checkbox" name="manual_refs" value="{i}">' for i in range(len(entries)))
    harness = r"""
let assertions = 0;
// Compare les valeurs DOM de recette et compte les assertions, sans données métier.
function equal(actual, expected) { assertions++; if (actual !== expected) throw Error(`${actual} != ${expected}`); }
// Simule une coche/décoche et son événement, sans requête réseau.
function check(index, selected) {
  const input = document.querySelectorAll('[name="manual_refs"]')[index];
  input.checked = selected; input.dispatchEvent(new Event('change', {bubbles:true}));
}
try {
  const clean = document.body.innerHTML;
  const f = document.querySelector('form');
  check(0,true); equal(f.elements.amount.value,'600,00'); equal(f.elements.document.value,'D'); equal(f.elements.date.value,'2026-01-01');
  check(1,true); equal(f.elements.amount.value,'1000,00');
  check(1,false); equal(f.elements.amount.value,'600,00');
  check(0,false); equal(f.elements.amount.value,''); equal(f.elements.amount_mode.value,'KEEP'); equal(f.querySelectorAll('[name="selection_auto"]').length,0);
  check(2,true); check(3,true); equal(f.elements.amount.value,'-100,12');
  check(2,false); equal(f.elements.amount.value,'0,00'); check(3,false);
  check(0,true); check(4,true); equal(f.elements.amount.value,'625,00'); equal(f.elements.document_mode.value,'KEEP'); equal(f.elements.date_mode.value,'KEEP');
  equal(document.getElementById('manual-selection-message').textContent.includes('Plusieurs'),true);
  check(4,false); equal(f.elements.document.value,'D');
  f.elements.amount.value='777,00'; f.elements.amount.dispatchEvent(new Event('input',{bubbles:true}));
  check(1,true); equal(f.elements.amount.value,'777,00');
  equal([...f.querySelectorAll('[name="selection_auto"]')].some(e=>e.value==='amount'),false);
  document.getElementById('manual-selection-recalculate').click(); equal(f.elements.amount.value,'1000,00');
  // Après un POST en erreur, les valeurs auto ne deviennent pas une source conservée.
  document.body.innerHTML = clean;
  const bound = document.querySelector('form'); bound.dataset.preserveDecisions='true';
  bound.elements.amount_mode.value='SET'; bound.elements.amount.value='600,00';
  const previous = document.createElement('input'); previous.type='hidden'; previous.name='selection_auto'; previous.value='amount'; bound.append(previous);
  const restore = document.createElement('script'); restore.type='application/json'; restore.id='manual-restore-values';
  restore.textContent=JSON.stringify({amount:{mode:'KEEP',value:''}}); document.body.append(restore);
  initializeManualAllocation(); equal(bound.elements.amount_mode.value,'KEEP'); equal(bound.elements.amount.value,'');
  document.body.innerHTML='<pre id="test-result">'+JSON.stringify({ok:true,assertions})+'</pre>';
} catch(error) { document.body.innerHTML='<pre id="test-result">'+JSON.stringify({ok:false,error:String(error),assertions})+'</pre>'; }
"""
    with TemporaryDirectory(prefix="atlas-browser-") as folder:
        target = Path(folder) / "test.html"
        target.write_text('<!doctype html><meta charset="utf-8"><form data-review-form>' + controls +
            '<output id="manual-selection-total"></output><span id="manual-atlas-gap"></span><p id="manual-selection-message"></p>'
            '<button type="button" id="manual-selection-recalculate">Recalculer</button></form>' +
            '<script type="application/json" id="manual-candidates">' + json.dumps(entries) + '</script>' +
            '<script type="application/json" id="manual-atlas-amount">"1000"</script>' +
            '<script src="' + (root / "app-suivi-reconciliation/static/js/manual-allocation.js").as_uri() + '"></script>' +
            '<script>' + harness + '</script>', encoding="utf-8")
        completed = subprocess.run([str(browser), '--headless', '--disable-gpu', '--disable-background-networking',
            '--no-first-run', f'--user-data-dir={Path(folder) / "profile"}', '--dump-dom', target.as_uri()],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        import re
        match = re.search(r'<pre id="test-result">(.*?)</pre>', completed.stdout, re.S)
        if not match:
            raise RuntimeError("Résultat DOM absent : " + completed.stderr[-1000:])
        result = json.loads(html.unescape(match.group(1)))
        if not result.get("ok"):
            raise RuntimeError(str(result))
        return result["assertions"]


if __name__ == "__main__":
    print(f"Recette DOM : {run()} assertions réussies")

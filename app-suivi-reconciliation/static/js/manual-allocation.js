/* Aperçu indicatif ; le calcul Decimal du service reste la référence. */
(() => {
  const data = document.getElementById('manual-candidates');
  const output = document.getElementById('manual-selection-total');
  if (!data || !output) return;
  const entries = new Map(JSON.parse(data.textContent).map(row => [row.ref, row]));
  const atlas = JSON.parse(document.getElementById('manual-atlas-amount').textContent);
  const update = () => {
    const selected = [...document.querySelectorAll('[name="manual_refs"]:checked')];
    const total = selected.reduce((sum, field) => sum + Number(entries.get(field.value).amount), 0);
    const amount = document.getElementById('id_amount');
    const value = Number((amount?.value || '').replace(',', '.'));
    output.textContent = `Somme sélectionnée : ${total.toLocaleString('fr-FR', {style:'currency', currency:'EUR'})} · écart au montant saisi : ${(total-value).toLocaleString('fr-FR', {style:'currency',currency:'EUR'})}`;
    document.getElementById('manual-atlas-gap').textContent = atlas === null ? 'montant absent' : (total-Number(atlas)).toLocaleString('fr-FR', {style:'currency',currency:'EUR'});
  };
  document.querySelectorAll('[name="manual_refs"], #id_amount').forEach(field => field.addEventListener('change', update));
  update();
})();

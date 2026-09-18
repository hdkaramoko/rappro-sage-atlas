/* Interactions locales : aucune donnée de rapprochement chargée côté navigateur. */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-edit-field]').forEach(field => {
    const mode = field.querySelector('select');
    const replacement = field.querySelector('[data-replacement]');
    const hint = field.querySelector('[data-clear-hint]');
    function update() {
      replacement.hidden = mode.value !== 'SET';
      replacement.querySelectorAll('input, select, textarea').forEach(input => { input.disabled = mode.value !== 'SET'; });
      hint.hidden = mode.value !== 'CLEAR';
    }
    mode.addEventListener('change', update); update();
  });
  const contextElement = document.getElementById('allocation-context');
  if (contextElement) {
    const context = JSON.parse(contextElement.textContent);
    const mode = document.getElementById('id_amount_mode');
    const input = document.getElementById('id_amount');
    const output = document.getElementById('allocation-preview');
    const money = new Intl.NumberFormat('fr-FR', {style:'currency', currency:'EUR'});
    function update() {
      const raw = mode.value === 'CLEAR' ? null : mode.value === 'KEEP' ? context.source : input.value;
      if (raw === null || raw === '' || context.missing_others) { output.textContent = 'Répartition encore incomplète.'; return; }
      const amount = Number(String(raw).replace(/\s/g, '').replace(',', '.'));
      if (!Number.isFinite(amount)) { output.textContent = 'Montant à vérifier.'; return; }
      const total = Number(context.others) + amount;
      output.textContent = 'Après saisie : ' + money.format(total) + ' répartis' + (context.target === null ? '.' : ' · Écart SAGE : ' + money.format(total - Number(context.target)) + '.');
    }
    mode.addEventListener('change', update); input.addEventListener('input', update); update();
  }
  document.querySelectorAll('[data-drop-zone]').forEach(zone => {
    const input = zone.querySelector('input[type=file]');
    ['dragenter', 'dragover'].forEach(name => zone.addEventListener(name, event => { event.preventDefault(); zone.classList.add('drag-over'); }));
    ['dragleave', 'drop'].forEach(name => zone.addEventListener(name, event => { event.preventDefault(); zone.classList.remove('drag-over'); }));
    zone.addEventListener('drop', event => {
      if (event.dataTransfer.files.length === 1) { input.files = event.dataTransfer.files; input.dispatchEvent(new Event('change')); }
    });
  });
  document.getElementById('matching-upload')?.addEventListener('submit', () => {
    document.getElementById('upload-notice').hidden = false;
  });
  const refresh = document.querySelector('[data-refresh-ms]');
  if (refresh) window.setTimeout(() => window.location.reload(), Number(refresh.dataset.refreshMs));
});

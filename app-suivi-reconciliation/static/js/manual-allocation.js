/** Préremplit les décisions ; le serveur recontrôle les preuves et les sommes en Decimal. */
function initializeManualAllocation() {
  const data = document.getElementById('manual-candidates');
  const output = document.getElementById('manual-selection-total');
  const form = document.querySelector('[data-review-form]');
  if (!data || !output || !form) return;
  const entries = new Map(JSON.parse(data.textContent).map(row => [row.ref, row]));
  const atlas = JSON.parse(document.getElementById('manual-atlas-amount').textContent);
  const names = ['amount', 'document', 'date'];
  const restoreData = document.getElementById('manual-restore-values');
  const restored = restoreData ? JSON.parse(restoreData.textContent) : {};
  const previousAuto = [...form.querySelectorAll('[name="selection_auto"]')].map(element => element.value);
  const states = new Map(names.map(name => [name, {
    mode: form.elements[`${name}_mode`], input: form.elements[name],
    originalMode: restored[name]?.mode ?? form.elements[`${name}_mode`].value,
    originalValue: restored[name]?.value ?? form.elements[name].value,
    manual: form.dataset.preserveDecisions === 'true' && !previousAuto.includes(name),
    automatic: previousAuto.includes(name)
  }]));
  const message = document.getElementById('manual-selection-message');
  let writing = false;

  /** Signale un mode calculé aux autres composants sans le confondre avec une saisie. */
  function notifyMode(state) {
    writing = true;
    state.mode.dispatchEvent(new Event('change', {bubbles: true}));
    writing = false;
  }

  /** Lit une chaîne française en milliardièmes signés ; null si invalide, sans effet externe. */
  function units(value) {
    const raw = String(value ?? '').replace(/[\s\u202f\u00a0]/g, '').replace(',', '.');
    if (!/^-?\d+(\.\d{1,9})?$/.test(raw)) return null;
    const [whole, fraction = ''] = raw.replace('-', '').split('.');
    return (BigInt(whole) * 1000000000n + BigInt(fraction.padEnd(9, '0'))) * (raw.startsWith('-') ? -1n : 1n);
  }
  /** Formate au centime avec arrondi pair sans modifier la somme exacte en mémoire. */
  function cents(value) {
    const negative = value < 0n;
    const positive = negative ? -value : value;
    let amount = positive / 10000000n;
    const remainder = positive % 10000000n;
    if (remainder > 5000000n || (remainder === 5000000n && amount % 2n)) amount += 1n;
    return `${negative && amount ? '-' : ''}${amount / 100n},${String(amount % 100n).padStart(2, '0')}`;
  }
  /** Synchronise les marqueurs auto ; ils n'accordent aucune autorisation serveur. */
  function markers() {
    form.querySelectorAll('[name="selection_auto"]').forEach(element => element.remove());
    states.forEach((state, name) => {
      if (!state.automatic) return;
      const hidden = document.createElement('input');
      hidden.type = 'hidden'; hidden.name = 'selection_auto'; hidden.value = name;
      form.append(hidden);
    });
  }
  /** Restaure un champ calculé à son état d'ouverture, sans écraser une saisie volontaire. */
  function restore(state) {
    if (!state.automatic) return;
    state.mode.value = state.originalMode; state.input.value = state.originalValue;
    state.automatic = false;
    notifyMode(state);
  }
  /** Recalcule la sélection et ses conflits immédiatement, sans recharger la page. */
  function update() {
    const selected = [...form.querySelectorAll('[name="manual_refs"]:checked')].map(field => entries.get(field.value));
    const amounts = selected.map(entry => units(entry?.amount));
    const total = amounts.some(value => value === null) ? null : amounts.reduce((sum, value) => sum + value, 0n);
    const warnings = [];
    ['document', 'date'].forEach(name => {
      if (new Set(selected.map(entry => entry[name] || '')).size > 1)
        warnings.push(name === 'date' ? 'Plusieurs dates ou date absente : choisissez la date comptable.' : 'Plusieurs pièces ou pièce absente : choisissez une pièce principale.');
    });
    if (!selected.length) states.forEach(restore);
    else if (total === null) warnings.push('Montant Sage absent : sélection à vérifier.');
    else names.forEach(name => {
      const state = states.get(name);
      if (state.manual) return;
      const values = new Set(selected.map(entry => entry[name] || ''));
      const value = name === 'amount' ? cents(total) : values.size === 1 ? [...values][0] : '';
      if (!value && name !== 'amount') {
        restore(state);
        warnings.push(name === 'date' ? 'Plusieurs dates ou date absente : choisissez la date comptable.' : 'Plusieurs pièces ou pièce absente : choisissez une pièce principale.');
        return;
      }
      state.mode.value = 'SET'; state.input.value = value; state.automatic = true;
      notifyMode(state);
    });
    markers();
    const entered = units(states.get('amount').input.value);
    output.textContent = total === null ? 'Somme Sage inconnue.' : `Somme sélectionnée : ${cents(total)} € · écart au montant saisi : ${entered === null ? 'montant absent' : cents(total - entered) + ' €'}`;
    const original = units(atlas);
    document.getElementById('manual-atlas-gap').textContent = original === null || total === null ? 'montant absent' : `${cents(total - original)} €`;
    message.textContent = [...new Set(warnings)].join(' ');
  }
  states.forEach(state => {
    /** Préserve une modification volontaire lors des prochaines coches. */
    function edited(event) {
      if (writing) return;
      state.manual = true; state.automatic = false; update();
    }
    state.input.addEventListener('input', edited);
    state.mode.addEventListener('change', edited);
  });
  form.querySelectorAll('[name="manual_refs"]').forEach(field => field.addEventListener('change', update));
  /** Rend explicitement les champs au calcul depuis la sélection. */
  function recalculate() { states.forEach(state => { state.manual = false; }); update(); }
  document.getElementById('manual-selection-recalculate').addEventListener('click', recalculate);
  update();
}
initializeManualAllocation();

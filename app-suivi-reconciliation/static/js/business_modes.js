/**
 * Active les deux modes exclusifs de la fiche Atlas, sans requête ni mutation métier.
 * Les panneaux restent dans le DOM : changer de mode conserve les champs saisis.
 * Les liens GET assurent le repli sans JavaScript ; l'URL garde le mode sélectionné.
 */
function initializeBusinessModes() {
  for (const workflow of document.querySelectorAll('[data-business-workflow]')) {
    const navigation = workflow.querySelector('[data-business-tabs]');
    const tabs = Array.from(navigation.querySelectorAll('[data-business-mode]'));
    const panels = Array.from(workflow.querySelectorAll('[data-business-panel]'));
    navigation.setAttribute('role', 'tablist');
    /** Affiche le mode demandé ; focus=true déplace le focus. Retour vide, aucun champ modifié. */
    function activateMode(mode, focus = false) {
      const selected = tabs.find(tab => tab.dataset.businessMode === mode) || tabs[0];
      for (const tab of tabs) {
        const active = tab === selected;
        tab.setAttribute('role', 'tab');
        tab.setAttribute('aria-selected', String(active));
        tab.removeAttribute('aria-current');
        tab.tabIndex = active ? 0 : -1;
      }
      for (const panel of panels) {
        panel.setAttribute('role', 'tabpanel');
        panel.hidden = panel.id !== selected.dataset.businessMode;
      }
      if (focus) selected.focus();
    }
    /** Reçoit le lien choisi et mémorise son mode dans l'URL locale ; retour vide, sans requête. */
    function selectMode(tab) {
      activateMode(tab.dataset.businessMode, true);
      const url = new URL(window.location.href);
      url.searchParams.set('mode', tab.dataset.businessMode);
      // Le hash historique #correct/#search reste compatible avec les liens existants.
      url.hash = tab.dataset.businessMode;
      window.history.replaceState(null, '', url);
    }
    for (const [index, tab] of tabs.entries()) {
      tab.addEventListener('click', event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        selectMode(tab);
      });
      tab.addEventListener('keydown', event => {
        let target;
        if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
        if (event.key === 'ArrowLeft') target = tabs[(index + tabs.length - 1) % tabs.length];
        if (event.key === 'Home') target = tabs[0];
        if (event.key === 'End') target = tabs[tabs.length - 1];
        if (event.key === ' ') target = tab;
        if (target) { event.preventDefault(); selectMode(target); }
      });
    }
    // Une erreur serveur garde toujours son formulaire visible, même avec un ancien hash.
    const bound = workflow.querySelector('[data-business-bound]');
    const hash = window.location.hash.slice(1);
    const selected = tabs.find(tab => tab.hasAttribute('aria-current')) || tabs[0];
    activateMode(bound ? bound.id : (['search', 'correct'].includes(hash) ? hash : selected.dataset.businessMode));
  }
}
document.addEventListener('DOMContentLoaded', initializeBusinessModes);

/**
 * Initialise les filtres multiples accessibles avec cases natives et details.
 * Toutes désélectionne les choix précis, un choix précis retire Toutes ; aucune
 * sélection revient à Toutes. Le serveur reste la référence et lit les GET répétés.
 * Le résumé est actualisé sans soumission automatique ni modification de l'URL ;
 * le formulaire GET préserve les valeurs et reste utilisable sans JavaScript.
 * Les contrôles natifs conservent leurs interactions clavier et labels.
 */
function initializeMultiFilters() {
  for (const menu of document.querySelectorAll('[data-multi-filter]')) {
    const all = menu.querySelector('[data-filter-all]');
    const choices = [];
    for (const input of menu.querySelectorAll('input[type=checkbox]')) {
      if (input !== all) choices.push(input);
    }
    const summary = menu.querySelector('[data-filter-summary]');
    /** Synchronise un changement local sans accès réseau ni altération des filtres voisins. */
    function synchronizeFilter(event) {
      if (event.target === all && all.checked) {
        for (const input of choices) input.checked = false;
      }
      if (event.target !== all && event.target.checked) all.checked = false;
      let count = 0;
      for (const input of choices) {
        if (input.checked) count += 1;
      }
      all.checked = count === 0;
      summary.textContent = count ? `${count} sélection(s)` : 'Toutes';
    }
    menu.addEventListener('change', synchronizeFilter);
  }
}
document.addEventListener('DOMContentLoaded', initializeMultiFilters);

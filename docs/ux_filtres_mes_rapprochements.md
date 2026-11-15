# Filtres de Mes rapprochements : desktop et mobile

La grille précédente prévoyait quatre menus et le champ Lignes sur la première
rangée. L'ajout de Département entraînait un retour à la ligne de la recherche.
Contrôle des montants utilisait un formulaire flex sans adaptation comparable.

Les deux templates utilisent désormais le même conteneur responsive :

- espace disponible d'au moins 1 000 px : six menus de même proportion et une
  recherche de trois parts depuis l'[ajout du Pôle](poles_atlas.md), sur une seule ligne ;
- espace intermédiaire : trois ou deux colonnes, recherche sur toute la largeur ;
- espace disponible inférieur ou égal à 400 px : une colonne ;
- Lignes et actions placés dans un pied de formulaire distinct ;
- menus ouverts bornés à la largeur disponible et alignés à droite si nécessaire.

Les seuils suivent la largeur du contenu (container queries), donc prennent en
compte la barre latérale. Les tableaux conservent leur défilement dans leur propre
conteneur. Le tableau des montants devient également accessible au clavier via
une région nommée et focusable, comme celui des rapprochements.

Fichiers de présentation modifiés : `static/css/workspace.css`,
`templates/reconciliation/reviews.html`, `global_controls.html`, dans le dossier
`app-suivi-reconciliation`. Pas de changement de JavaScript, de requêtes Django,
de paramètres GET, de données ou de règles métier.

Recette Chrome headless sur les vrais templates rendus avec données fictives,
sans accès SQL : les deux vues à 320, 375, 390, 430, 768, 1024, 1440 et 1920 px.
Les 16 combinaisons passent : aucun débordement horizontal de page (y compris
menus ouverts), choix multiples et Toutes fonctionnels. À 1440 px, les six champs
occupent une seule rangée et la recherche mesure environ 375 px, contre 134 px
pour chaque menu. Captures desktop et mobile inspectées. Les tableaux larges
restent défilants localement.

Non-régression : 38 tests Django existants réussis (`test_departments`,
`test_journey`, `test_amount_control_ux`, `test_ui`) ; `git diff --check` sans erreur.

Les fichiers de recette et captures sont dans `benchmarks/review_filters/`
(dossier local ignoré par Git). Aucun serveur ni base de campagne n'a été modifié.

Déploiement : publier les templates et les fichiers statiques selon la procédure
habituelle. Aucun nouveau JSONL, import, recalcul ou migration n'est nécessaire
pour ce correctif UX ; la migration du lot départemental précédent reste distincte.

# Améliorations UX du contrôle des montants

Évolution du 9 novembre 2026, sur la branche de développement courante.

## Mes rapprochements : contrôle des montants

Le filtre reprend le composant multisélection existant, avec cases natives et
indication « Plusieurs choix possibles ». Toutes est en premier et retire la
restriction, y compris si une requête contient aussi des choix précis. Les
autres choix correspondent aux états réellement calculés : Équilibré, Écart,
À revoir, Exclu. EXCLU est bien un état du contrôle existant.

Sans paramètre, Écart et À revoir sont sélectionnés. Le filtre porte sur
`current_state`, indépendamment du diagnostic initial. Une proposition non
confirmée reste affichée comme avertissement distinct, sous l'état courant :
un contrôle équilibré avec une proposition en attente apparaît dans Équilibré.
Cela ne confirme ni ne valide cette proposition.

Les anciennes URL ANOMALY, RECONCILED et EXCLUDED restent reconnues avec leur
ancien sens ; les choix affichés et les nouvelles soumissions utilisent les
états explicites. Les liens de pagination conservent les paramètres GET répétés,
la recherche et le projet ; Réinitialiser revient aux deux états par défaut.
Le tri projet/identifiant reste stable. Comptage et pagination portent sur les
colonnes légères ; les JSON sont chargés uniquement pour les 50 contrôles de la
page. Aucune recherche supplémentaire par ligne ni nouvelle requête lourde.

## Fiche du contrôle

Une grille verticale espace explicitement les cartes Résultat courant et
Lignes Atlas concernées. Le volet consultatif État initial utilise un chevron
ouvert/fermé et un contenu indenté ; il reste un élément details natif accessible
au clavier. Les sources Atlas sont présentées en tableau compact : identifiant
cliquable, statut source, libellé et charges Sage du fichier Atlas. Ces données
proviennent de l'inventaire déjà chargé, sans calcul supplémentaire ni N+1.
La pagination existante à 25 sources est conservée.

## Fiche de ligne Atlas

La carte Données sources et montant retenu rassemble les deux libellés, le
code projet, le tiers Sage présent dans Atlas, les identifiants et les montants.
Un projet ou tiers manquant affiche un tiret. Les champs monétaires, leurs
valeurs et leur provenance sont conservés. Les textes longs, y compris sans
espaces, se replient dans des colonnes de largeur adaptable.

Recherche et correction devient une carte repliable avec deux modes exclusifs :
Rechercher une correspondance et Corriger la ligne. La recherche est le choix
initial stable ; `?mode=correct` ouvre la correction. Un POST en erreur rend
toujours visible le formulaire qui a été soumis. Les anciens liens `#correct`
et `#search` restent utilisables avec JavaScript.

Le JavaScript modifie uniquement la visibilité et les attributs ARIA. Les deux
panneaux restent dans le DOM : les saisies sont conservées pendant les
basculements. Aucun formulaire n'est imbriqué dans un autre ; recherche GET,
correction POST, prévisualisation, confirmation et annulation gardent leurs
actions, champs, permissions, protections CSRF et validations serveur. Le
clavier permet Tab, Entrée, Espace, flèches, Début et Fin. Le mode est mémorisé
dans l'URL locale sans navigation. Sans JavaScript, les liens GET restent
fonctionnels ; un avertissement précise que le changement recharge la page et
qu'il faut enregistrer auparavant. Les saisies ne sont pas stockées durablement
dans le navigateur et ne survivent pas à un rechargement.

L'historique dispose de sa propre carte espacée et d'une liste d'événements
avec action, auteur, date, montant et affectations avant/après. Ses données,
son ordre et sa pagination sont conservés. L'état vide est explicite.

## Actualisation et périmètre

Les services existants mettent déjà à jour le résultat courant et son index
dans la transaction de correction, confirmation ou annulation. Les tests
passent une correction par la vue POST, observent Équilibré dans la liste, puis
annulent et observent Écart. Une confirmation met aussi à jour la fiche alors
que l'état initial reste inchangé. Un diagnostic À revoir à écart nul conserve
son motif et reste exclu du filtre Équilibré.

Aucune règle métier, convention de signe, affectation, auto-validation,
persistance intercampagnes, import JSONL ou moteur Python n'a été modifié.
Aucune migration, dépendance ou nouveau modèle. Aucun changement dans la base
utilisateur pendant la recette. Les modifications de requêtes utilisent des
opérations ORM communes à SQLite et PostgreSQL ; la recette automatisée a été
exécutée sur SQLite, sans serveur PostgreSQL de test disponible.

## Fichiers

- `app-suivi-reconciliation/reconciliation/global_views.py` : états courants explicites et tri léger.
- `app-suivi-reconciliation/reconciliation/business_views.py` : mode initial et erreurs visibles.
- `app-suivi-reconciliation/templates/reconciliation/global_controls.html` : état et attente distingués.
- `app-suivi-reconciliation/templates/reconciliation/global_control_detail.html` : cartes et volet initial.
- `app-suivi-reconciliation/templates/reconciliation/inventory_detail.html` : sources, modes et historique.
- `app-suivi-reconciliation/templates/components/multifilter.html` : indication multisélection.
- `app-suivi-reconciliation/templates/components/atlas_control_lines.html` : tableau compact des sources.
- `app-suivi-reconciliation/templates/components/inventory_source_identity.html` : identité et libellés source.
- `app-suivi-reconciliation/templates/components/business_mode_tabs.html` : navigation des deux modes.
- `app-suivi-reconciliation/static/css/workspace.css` : styles limités aux fiches concernées et responsive.
- `app-suivi-reconciliation/static/js/business_modes.js` : visibilité, clavier, conservation locale.
- `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` : recette des filtres et actions UX.
- `app-suivi-reconciliation/reconciliation/test_journey.py` : attente distincte de l'état équilibré.
- `app-suivi-reconciliation/reconciliation/test_multiples.py` : assertion de date alignée sur le fuseau local affiché, pour éviter l'échec autour de minuit UTC.
- Ce document et l'inventaire des docstrings associé.

## Recette manuelle Django local

Vérifications automatisées : `python manage.py test --noinput --verbosity 0`
a exécuté 310 tests en 117 secondes : 307 réussis, 3 ignorés. Les 30 tests
ciblés UX/parcours/index passent également. `makemigrations --check --dry-run`
ne détecte aucun changement de modèle et `git diff --check` ne signale aucune
erreur. L'[inventaire des docstrings](ux_controle_montants_docstrings.md)
recense 19 définitions Python nouvelles ou modifiées, toutes documentées.

1. Dans Contrôle des montants, choisir Écart et À revoir, ajouter projet et
   recherche, passer à la page suivante, sélectionner Toutes puis Réinitialiser.
2. Ouvrir une fiche en fenêtre large puis étroite : vérifier l'espace entre
   cartes, le volet initial, les textes longs et les liens des sources Atlas.
3. Saisir un commentaire de correction, basculer vers Recherche et revenir :
   le commentaire doit rester présent. Tester aussi au clavier et sans JavaScript.
4. Soumettre une correction invalide : le mode Corriger reste visible avec
   l'erreur. Tester prévisualisation, confirmation et annulation ; vérifier l'état
   courant, les alertes restantes et l'historique après chaque action.
5. Vérifier une campagne historique et un utilisateur hors portefeuille :
   consultation seule ou refus d'accès inchangés. Vérifier aussi Envoyé SAGE.

La recette visuelle dans un navigateur n'a pas pu être exécutée : aucun outil
de navigateur ni runtime Playwright/Selenium n'est disponible dans cette session.
Les tests vérifient le HTML serveur, les panneaux masqués, les liens, les
formulaires et leurs actions ; ils ne remplacent pas le contrôle visuel ni
l'exécution interactive du JavaScript sur ordinateur et fenêtre étroite.

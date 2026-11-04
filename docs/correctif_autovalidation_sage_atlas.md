# Correctif ciblé des auto-validations Sage–Atlas

## Diagnostic avant modification

Branche `dev-feature-amelioration-rappro`, arbre propre au début du correctif.

* `matching/results.py:confirmed_result` produit une preuve locale Atlas ;
  `apply_candidates` produit les correspondances exactes avec leurs positions Sage.
* `reconciliation/auto_validation.py:proposal_metadata` utilise l'écart calculé
  sur les charges projet pour toutes les catégories : il retire ainsi à tort
  l'autorisation d'un Confirmé dont seules les charges projet diffèrent.
* `collective_validation.py:prepare_piece` et `auto_validation.py:apply_automatic_validations`
  côté Django répètent ce veto. Le diagnostic `check_piece` utilise, lui, les
  charges Sage Atlas : règles de montant contradictoires.
* `apply_automatic_validations` bloque les revendications au niveau projet/pièce/date.
  `multiple_review.py:diagnose_plan` signale également toute pièce partagée entre
  groupes. Ces deux protections empêchent les écritures distinctes de coexister.
* L'identité v3 `entry_from_sage` comprend projet/exercice/pièce/journal/ligne
  comptable/ligne analytique. Le JSONL fournit déjà `entry_ref`, validé à l'import
  contre les contrôles. `ControlContribution` conserve montant et références.
* L'exécution réelle est `campaigns.py:import_campaign` → reports → publication
  transactionnelle → auto-validations → calcul initial global. Aucune fonction
  du lot 2 n'est nécessaire.
* `templates/reconciliation/review_detail.html` contient le pavé Données sources ;
  le filtre existant `euros` assure le format monétaire et les absences.

## Plan du correctif

1. Corriger uniquement la référence de montant des Confirmé, à l'export comme
   dans les contrôles Django, et afficher explicitement les deux montants sources.
2. Pour Exact v3, contrôler les références individuelles avant toute décision,
   ainsi que la capacité agrégée de la pièce, indépendamment de l'ordre.
3. Autoriser la coexistence des seules contributions automatiques Exact dont
   les preuves sont complètes, vérifiées et distinctes. Préserver les alertes
   des décisions manuelles et des autres règles.
4. Réutiliser signatures, transactions, photographies et contraintes existantes.
   Aucune migration, évolution de schéma ou nouveau contrat JSONL.

## Règles livrées

### A — Confirmé dans Atlas

Le résultat moteur conserve son montant projet et l'écart projet/Sage à titre
informatif. Seule la décision d'émettre `auto_validation` cesse d'utiliser cet
écart comme veto pour `MATCH_CONFIRMED_ATLAS` : une charge Sage Atlas finie est
requise, et l'autorisation dépend toujours de la configuration du moteur.
L'export en mode collectif ACTIVE exige toujours `PIECE_RECONCILED`.

Django compare ensuite `transaction.total_sage_charges` au montant individuel
de la proposition, avec tolérance signée de 0,01 EUR, puis vérifie la cohérence
collective et l'affectation réelle. Les autres règles continuent à utiliser
`total_project_charges`. Les montants absents ne deviennent jamais zéro ; les
avoirs et les zéros suivent les conventions existantes. Les sources ne sont
ni corrigées ni écrasées.

Exemple : une ligne porte 753,63 EUR de charges projet et 758,63 EUR de charges
Sage Atlas ; une seconde porte 109,56 EUR. Si Sage contient les écritures fiables
758,63 et 109,56, la pièce est cohérente à 868,19 EUR et les deux lignes peuvent
être validées automatiquement. Les autres contrôles (tiers/BAP, dates, exercices,
identités, autorisation moteur, absence de décision humaine prioritaire) restent requis.

Le pavé « Données sources » affiche `Total charges SAGE (€)` uniquement pour
Confirmé, à côté du montant projet existant (« Montant Atlas »). Le filtre
`euros` fournit deux décimales, séparateur français, unité EUR et tiret pour
les absences/non-nombres. Aucun nouvel écran n'est ajouté.

### B — Exact sur pièce partagée

Pour Exact v3, la preuve doit contenir **un seul candidat et une seule écriture**,
avec identité complète projet/exercice/pièce/journal/ligne comptable/ligne analytique.
Sa référence v3 et son contenu sont déjà validés contre les contrôles à l'import.
Le serveur recontrôle cardinalité, identité, montants projet/Sage et signes.

Avant les décisions, `automatic_blockers` recense les références de **toutes**
les propositions, y compris concurrentes sans autorisation AUTO. Il refuse :

* une référence revendiquée par plusieurs propositions ; aucun « premier arrivé » ;
* une identité insuffisante ou une proposition concurrente indistinguable ;
* une somme d'affectations candidates et de contributions existantes dépassant
  la pièce, en tenant compte des Comptabilisé déjà présents et des signes ;
* un périmètre/calcul de contrôle inconnu ou absent.

Les anciennes réservations AUTO devenues conflictuelles sont retirées de la
campagne courante avant l'examen des autres candidats. Les signatures sont
invalidées et les refus sont photographiés ; les états/historiques des anciennes
campagnes restent intacts. Une décision humaine, même enregistrée comme brouillon,
n'est jamais convertie silencieusement en AUTO.

Pendant la réservation, l'exception au signal « pièce partagée » ne vaut qu'entre
contributions **AUTO Exact**, actuelles, à preuves complètes et références distinctes.
Chaque contribution conserve son montant effectif et sa référence ; aucune
affectation automatique partielle ni nouvelle répartition plusieurs-vers-plusieurs
n'est introduite. Les protections contre les références communes, dépassements,
incertitudes et les avertissements du parcours **manuel** sont maintenus.

Exemple B1 : 140 + 4500 + 67,58 EUR, trois écritures distinctes de la pièce
`GNF0126051766`, peuvent être AUTO pour un total de 4707,58 EUR. Deux propositions
de 1000 sur **une seule** écriture de 1000 restent à revoir toutes les deux.
Deux écritures de 1000 sont admissibles si les preuves établissent séparément
chaque correspondance : leur seule égalité de montant ne suffit pas.

Les autres catégories et les contrats v1/v2 conservent leur garde pièce/date
historique. Une pièce partagée avec un pair manuel ou non Exact reste soumise
aux contrôles existants. Une identité v3 incomplète reste à examiner ; un fichier
v3 dont la référence obligatoire est absente/altérée reste rejeté par le contrat.

## Fichiers et fonctions documentées

| Fichier | Fonctions/méthodes créées ou modifiées et justification |
|---|---|
| `reconciliation/auto_validation.py` | `proposal_metadata` : référence Sage Atlas pour Confirmé, autres critères inchangés |
| `app-suivi-reconciliation/reconciliation/collective_validation.py` | `prepare_piece` : même référence dans le contrôle collectif, signe préservé |
| `app-suivi-reconciliation/reconciliation/auto_validation.py` | `automatic_blockers` (créée) : précontrôle des références/capacités ; `apply_automatic_validations` : décisions, invalidation des réservations AUTO refusées et motifs auditables |
| `app-suivi-reconciliation/reconciliation/multiple_review.py` | `exact_entry`, `compatible_exact_peer` (créées) : preuves/compatibilité strictes ; `diagnose_plan`, `apply_projection` : exemption limitée au parcours AUTO Exact |
| `app-suivi-reconciliation/reconciliation/review.py` | `decide` : transmet le contexte AUTO à la projection, avec les mêmes transactions/permissions/événements |
| `app-suivi-reconciliation/templates/reconciliation/review_detail.html` | ajout du montant Sage source conditionnel, filtre monétaire existant |
| `tests/test_auto_validation.py` | recette d'export à 868,19 EUR et refus des charges Sage absentes/non finies |
| `app-suivi-reconciliation/reconciliation/test_autovalidation_correctif.py` (créé) | 16 recettes intégrées : A/B, permutations, capacité, report, décisions humaines, rendu et limites monétaires |
| `docs/correctif_autovalidation_sage_atlas.md` (créé) | diagnostic initial, règles, traçabilité, compatibilité, résultats et recette |

Toutes les fonctions et classes créées/modifiées portent une docstring française
précisant leur rôle, paramètres, montants de référence, résultat, effets de bord
et conditions de refus. Le template réutilise la présentation existante.

## Matrice de traçabilité

| Exigence | Implémentation | Tests |
|---|---|---|
| A : autorisation moteur sur charges Sage | `proposal_metadata` | `test_confirmed_export_uses_sage_charges_despite_project_gap`, `test_confirmed_missing_sage_amount_never_authorizes` |
| A : contrôle collectif à 868,19 EUR, sources préservées | `prepare_piece`, `apply_automatic_validations` | `test_reference_86819_ignores_project_gap_and_preserves_sources` |
| A : affichage monétaire et absence | `review_detail.html`, filtre `euros` | test précédent, `test_missing_sage_source_displays_dash_not_zero` |
| A : zéro et avoirs | mêmes contrôles signés | `test_confirmed_zero_and_negative_reference_preserve_project_sources` |
| B1 : trois références distinctes sur une pièce | `exact_entry`, `compatible_exact_peer`, projection | `test_b1_distinct_entries_on_shared_piece_and_carry`, `test_b1_reversed_initial_import_validates_all_three` |
| B2 : vraie réutilisation | `automatic_blockers` | `test_b2_reused_entry_blocks_every_claimant_in_both_orders`, `test_new_reuse_invalidates_carried_auto_without_rewriting_history` |
| B3 : montants jumeaux mais preuves distinctes | identité v3 et cardinalité stricte | `test_b3_twin_amounts_have_distinct_identified_proofs` |
| B4 : preuve insuffisante/ambiguë | mêmes contrôles | `test_b4_missing_analytic_identity_stays_manual`, `test_identical_amount_with_ambiguous_multiple_proofs_stays_manual` |
| B5 : ordre indépendant | précontrôle des revendications et capacité | `test_b5_distinct_entries_have_same_result_after_permutation`, tests B1 inversé et B2 |
| Non-double comptage/dépassement | contrôle agrégé avant décisions, contributions existantes | `test_aggregate_excess_blocks_all_distinct_candidates` |
| Montants et autres catégories inchangés | référence projet Exact, Decimal, tolérance historique | `test_zero_negative_and_missing_amounts`, `test_exact_cent_tolerance_does_not_change_reference_policy` |
| Parcours manuel/priorité humaine | `decide`, exemption AUTO seulement | `test_manual_piece_sharing_still_requires_risk_confirmation`, `test_human_decision_remains_manual_in_successive_campaign` |
| JSONL/import/permissions/historique/export | mécanismes existants conservés | suites moteur et Django complètes, dont tests des campagnes, multiples et validation collective |

## Compatibilité et déploiement

Aucune migration ni changement de version du contrat. Les données sources et
photographies historiques sont conservées ; aucune base applicative existante
n'a été modifiée pendant le développement. Les nouvelles règles s'appliquent
au point d'exécution existant de l'import d'une **nouvelle campagne**.

Pour A, il faut **régénérer le JSONL avec le moteur corrigé** : l'ancien fichier
ne contient pas toujours l'autorisation AUTO des lignes dont les charges projet
diffèrent. Django ne réinvente pas une autorisation absente. Pour B, les preuves
v3 existantes suffisent, mais un réimport des mêmes octets reste idempotent :
il ne déclenche pas une réécriture silencieuse des décisions déjà publiées.
Le parcours recommandé est donc une nouvelle extraction/campagne avec le code
moteur et applicatif corrigé, puis revue des éventuels refus explicites.

Les preuves anciennes sans identité discriminante et les répartitions partielles
restent manuelles. Aucun arbitrage métier supplémentaire n'est utilisé pour
autoriser une réutilisation automatique ; une telle évolution reste hors périmètre.
Les verrous PostgreSQL doivent être exercés sur une instance dédiée : les tests
correspondants sont ignorés lorsque la base de test est SQLite.

## Recette manuelle courte

1. Régénérer une campagne avec le moteur corrigé puis l'importer dans l'application
   corrigée. Pour la pièce de 868,19 EUR, vérifier les deux décisions AUTO,
   les écritures affectées distinctes et les charges projet 753,63 EUR toujours
   affichées à côté des charges Sage Atlas 758,63 EUR.
2. Pour `GNF0126051766`, vérifier les trois décisions AUTO de 140, 4500 et
   67,58 EUR, leurs trois références distinctes et leur total de 4707,58 EUR.
3. Sur une fixture de recette, faire revendiquer la même écriture à deux lignes :
   les deux restent à revoir avec un motif de réutilisation, quel que soit l'ordre.

## Vérifications réalisées

* Racine : `.venv/Scripts/python.exe -m pytest -q` — **192 réussis, 1 ignoré**
  (test sur données métier complètes nécessitant une activation explicite).
* Depuis `app-suivi-reconciliation` :
  `../.venv/Scripts/python.exe manage.py test reconciliation.test_autovalidation_correctif --noinput --verbosity 0`
  — les 14 premières recettes intégrées passent ; les deux recettes de bornes
  supplémentaires sont ensuite incluses dans la dernière suite complète.
* Depuis ce même dossier : `../.venv/Scripts/python.exe manage.py test --noinput --verbosity 0`
  — **217 tests, OK, 2 ignorés** (verrouillage/concurrence PostgreSQL non disponible).
  Cela inclut les 16 nouvelles recettes intégrées. L'avertissement connu concernant
  le répertoire `staticfiles` absent n'affecte pas les assertions backend.
* `git diff --check` — aucune erreur d'espaces.
* `.venv/Scripts/python.exe app-suivi-reconciliation/manage.py makemigrations --check --dry-run`
  — aucun changement de modèle non migré.

Une reconstitution isolée utilise les cinq sources Atlas et les cinq écritures
Sage pertinentes du JSONL existant, régénère leurs propositions avec le moteur
corrigé, puis les importe dans une **base SQLite temporaire migrée neuve**.
Les lignes `1596736`, `1596737`, `1710825`, `1710826` et `1710828` sont toutes
`VALIDATED`, source `AUTO`, décision actuelle, sans motif de blocage.
Cette vérification ne constitue pas un réimport de toute la campagne réelle :
elle ne modifie ni le fichier original ni la base de l'application.

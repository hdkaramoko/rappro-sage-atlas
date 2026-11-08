# Parcours métier Sage–Atlas — lot intermédiaire

**8 novembre 2026 :** la [consultation des contrôles est désormais indexée](performance_controle_montants.md).
La migration 0021 prépare les campagnes existantes sans modifier leurs décisions
ni leurs résultats financiers ; les détails de déploiement et de performance sont
dans ce complément.

Évolution du 6 novembre 2026 sur `dev-feature-lot2-validations-manuelles`.
Le HEAD et l'arbre de travail ont été contrôlés avant modification ; le Lot 2
et la persistance étaient déjà présents, l'arbre était propre.

## Audit et cartographie de l'existant

| Notion | Référence réelle | Comportement conservé |
|---|---|---|
| Statut source Atlas | `ReconciliationTransaction.bap_status`, `CampaignInventory.data` | Ne change jamais lorsqu'une décision est prise dans Django |
| Proposition moteur | `ReviewGroup.match_status`, `rule`, `evidence`, alimentés par l'import | MATCHED, AMBIGUOUS, UNMATCHED et preuves distincts de la décision |
| Décision et fraîcheur | `LineReview.state`, `review.is_current`, `presentation.decorate` | VALIDATED/REJECTED/DRAFT et À réexaminer si périmée |
| Affichage des actions | `journey.line_actions` | Utilise état, fraîcheur et preuves ; ne modifie aucune décision |
| Annulation/remplacement | `review.decide`, `business.cancel_inventory_link`, `confirm_inventory_link` | Annulation logique, réservations libérées ou remplacées, historique conservé |
| Initial / courant | `CampaignGlobalControl.data` / `current_data` | Initial immuable ; courant produit par recalcul ciblé transactionnel |
| Calcul global | `global_control.campaign_controls`, `business_calculation.business_inputs`, contrat `consolidate` | Comptabilisé retenu + Envoyé SAGE confirmé courant, sans double compte |
| Diagnostic historique | `MultipleControl.data`, `multiple_views` | Photographie du Comptabilisé et arbitrage de suspicion, pas le solde consolidé courant |
| Droits et concurrence | `visible_for`, `projects_for`, `review.decide`, `_locked_inventory` | Portefeuille, publication/campagne courante, versions et signatures, verrous et unicité active |

La mécanique nécessaire à la révision existait déjà. Ce lot ajoute une façade
de lecture et une confirmation guidée ; il ne recrée ni moteur de rapprochement,
ni calcul financier, ni modèle d'affectation ou seconde piste d'audit.

## Deux vues dans Mes rapprochements

### Envoyé SAGE

La vue initiale porte exclusivement sur les sources `Envoyé SAGE` de la campagne
courante publiée. Elle affiche par défaut **À examiner**, avec les propositions
avant les lignes sans correspondance exploitable. Contrairement à l'ancien défaut,
aucun filtre de correspondance trouvé n'est appliqué silencieusement.
Les raccourcis donnent accès aux cas sans correspondance, validés et refusés.

Les anciennes validations invalidées par import/correction reviennent dans
À examiner : la requête utilise le snapshot de fraîcheur de campagne et les
signatures explicitement invalidées, puis le badge de chaque ligne contrôle
sa signature complète. Les validées courantes et les refusées courantes restent
consultables séparément. Toutes permet de consulter tous les états enregistrés.

Sur une proposition MATCHED avec preuves (ou preuve locale Confirmé dans Atlas),
les boutons de recherche/correction Lot 2 ne sont plus en tête de fiche.
L'utilisateur examine les preuves et valide ou refuse. Une proposition refusée
permet ensuite la recherche manuelle. Une ambiguïté conserve ses candidats et
permet leur examen ou une recherche, sans être assimilée à une absence de preuve.

La recherche est mise en avant lorsqu'aucune proposition exploitable n'existe.
Corriger le montant Atlas apparaît si le montant manque, diffère du total de
preuve ou si une correction est déjà active. Cette suggestion n'est jamais une
correction automatique ; les services Lot 2 restent seuls responsables de la
validité des montants, signes et motifs. Le formulaire reste accessible dans
l'inventaire si une correction utile doit être effectuée après examen.

### Contrôle des montants

Accès direct par l'onglet, sans passer par les campagnes et les diagnostics des
multiples. La façade lit `Coalesce(current_data, data)` en SQL, avec pagination.
Elle n'appelle ni moteur, ni import, ni recalcul lors d'un GET.

Défaut : **Anomalies à examiner**. Les filtres donnent accès aux réconciliés,
exclus et à Toutes. Les anomalies sont présentées avant les réconciliés.
Un écart nul ne suffit pas : INDETERMINE reste une anomalie. Une proposition
non confirmée dont le contexte signé vise le contrôle ajoute une alerte distincte,
même si les totaux sont égaux. Cette alerte ne réécrit pas l'état financier stocké.
Une proposition refusée ou une validation périmée reste non confirmée pour cette
alerte. On ne déduit pas une association pour une ligne sans contexte de pièce.

Standard : projet + exercice + pièce selon la clé existante. ODS/ODG : identité
composite existante, tiers/libellé/montant/unicité ; aucun regroupement nouveau
par seul numéro de pièce.

La fiche de contrôle expose Comptabilisé retenu, Envoyé confirmé, Sage, écart et
motifs courants ; l'état initial est séparé dans un volet. Elle liste les sources
Atlas liées nativement, par allocations, contributions ou contexte de proposition,
avec pagination et accès aux actions existantes. Les anciens diagnostics et
arbitrages demeurent accessibles par leurs URLs historiques, sous le libellé
« Preuves et arbitrages des pièces ». Les anciens fichiers sans inventaire Sage
ne fournissent pas de faux contrôle global.

## Réviser un rapprochement

Une validation courante montre son résultat et son origine AUTO ou MANUAL.
Le formulaire d'édition ordinaire est remplacé par une action secondaire dans un
volet **Réviser le rapprochement**. Un POST ordinaire ne permet plus d'éditer
silencieusement une validation existante depuis cette fiche.

Deux opérations sont proposées :

1. Annuler la validation : fournir un motif, cocher la confirmation puis confirmer.
   `revision.reopen_review` verrouille campagne/groupe/ligne et délègue à
   `decide(DRAFT)`. Droits, versions et signature sont revérifiés. Les hooks Lot 2
   retirent les allocations actives et recalculent uniquement les pièces touchées.
   La redirection ouvre la recherche Sage, avec le retour à la liste filtrée.
2. Remplacer l'association : ouvrir la recherche d'inventaire, prévisualiser les
   nouvelles écritures, vérifier anciennes/nouvelles pièces, saisir un commentaire
   et confirmer explicitement le remplacement. Le service Lot 2 existant contrôle
   les écritures entières, leurs réservations et la capacité dans une transaction.

Dans l'inventaire, l'annulation d'un lien exige également motif et confirmation.
Le volet de modification est replié sur une association courante. Les champs de
correction de montant et ceux d'association Sage demeurent distincts.

Une AUTO suit les mêmes contrôles explicites de contestation ; elle n'est pas
rendue librement éditable. `ReviewEvent.before` conserve maintenant l'origine et
la campagne de la décision antérieure. Le journal présente la réouverture comme
« Validation annulée pour révision ». Les événements existants, les snapshots et
`CampaignAction` conservent auteur, date, motif et anciennes/nouvelles cibles.
Aucun événement d'une campagne historique n'est réécrit.

Une campagne close est en consultation seule. Une association reprise ne peut
être révisée que dans la campagne courante ; sa réservation et sa décision
d'origine restent dans la campagne précédente. Les garde-fous de persistance
décrits dans [le guide dédié](persistance_actions_sage_atlas.md) restent actifs.

## Filtres et navigation

Projet, Règle, Décision et Origine sont des menus `details` avec cases natives,
labels et résumé. Toutes vient en premier ; les projets/règles sont triés par
code/libellé, les décisions par ordre métier, les origines AUTO et MANUAL restent
les seules valeurs stockées. Les menus sont utilisables au clavier sans widget
`select multiple` ni dépendance front-end supplémentaire.

- GET répétés : `project=P&project=Q`, `state=DRAFT&state=REJECTED`, etc.
- Union dans une dimension, intersection entre dimensions ; filtrage SQL `IN/Q`.
- Valeur vide = Toutes, prioritaire sur toute autre valeur de la même dimension.
  Le JavaScript désélectionne les choix précis quand Toutes est coché, et inversement.
  Sans JavaScript, décocher Toutes avant de cocher des choix précis.
- `rule=__NO_MATCH__` est une catégorie d'interface : couvre UNMATCHED même si une
  règle technique est renseignée, ainsi que MATCHED sans preuve exploitable.
  MATCH_CONFIRMED_ATLAS conserve sa preuve locale ; AMBIGUOUS reste une proposition.
  L'ancien `rule=UNMATCHED` reste un alias.
- Les anciennes URLs `match_status=MATCHED/AMBIGUOUS/UNMATCHED` restent filtrantes.
  Un message signale ce filtre historique ; Réinitialiser le retire. Le widget
  Correspondance est supprimé, sans suppression des badges moteur.
- Paramètres inconnus ignorés ; aucun filtre ne peut élargir le portefeuille.
- Pagination et retours fiche/inventaire conservent les GET multiples. Seuls des
  retours locaux vers les écrans du parcours sont admis, jamais un hôte externe.
- Réinitialiser revient au défaut de la vue active : À examiner pour Envoyé,
  Anomalies pour Contrôle des montants.

Les preuves ne sont chargées que pour la page de lignes. Les choix des menus
utilisent des requêtes distinctes sur les colonnes nécessaires. Les relations de
fraîcheur sont préchargées pour éviter les requêtes par ligne. L'export existant
« Corrections validées » reste un export de campagne autorisée ; il n'est pas
présenté comme une nouvelle synthèse Lot 3 des filtres à l'écran.

## Matrice de traçabilité

| Exigence | Module / fonction | Recette automatique |
|---|---|---|
| Proposition prioritaire | `journey.line_actions`, `review_detail` | `test_usable_proposal_prioritizes_decision_without_lot2_buttons` |
| Sans proposition / anomalie | `no_match_query`, `line_actions` | `test_unmatched_and_amount_anomaly_offer_contextual_actions` |
| Validation et contestation AUTO | `RevisionForm`, `reopen_review`, `review_detail` | `test_auto_revision_is_explicit_and_preserves_its_origin` |
| Annulation / audit / recalcul | `reopen_review` → `decide` → hooks Lot 2 | `test_confirmed_manual_revision_releases_and_audits` |
| Motif, confirmation, droits, versions | `RevisionForm`, `CancelLinkForm`, services existants | `test_revision_requires_confirmation_reason_permissions_and_versions`, `test_cancel_link_form_demands_confirmation_and_preserves_return` |
| Remplacement avant/après | `inventory_detail`, `confirm_inventory_link` | `test_replacement_preview_shows_old_and_new_and_keeps_history` |
| Campagne historique intacte | `reopen_review`, verrou campagne | `test_revising_carried_link_never_mutates_historical_campaign`, `test_closed_campaign_cannot_be_revised_and_return_url_is_local` |
| Union / intersection / Toutes | `selections`, `review_list` | `test_multifilters_union_intersection_all_and_return` |
| Pagination / retour / compteur | `review_list`, `safe_return`, `query_replace` existant | `test_multi_selection_pagination_preserves_every_value`, `test_ui` |
| Décisions périmées | `review_list`, `decorate` existant | `test_stale_validation_is_back_in_to_examine` |
| Anomalies et résultat courant | `global_controls_for`, `control_workspace` | `test_global_view_uses_current_totals_and_anomalies_by_default` |
| Égalité insuffisante | `ReviewControlContext`, alertes et états indexés | `test_equal_totals_with_unconfirmed_context_are_not_resolved`, `test_zero_gap_ambiguous_control_is_not_reconciled` |
| Droits / ODS | `projects_for`, clés composites existantes | `test_global_scope_and_ods_identity_are_preserved` |
| Lecture seule / charge | Querysets et Paginator | `test_filters_and_global_list_are_read_only_and_paginated`, test de volume Lot 2 existant |
| Non-régression | services Lot 1/Lot 2 inchangés hors enrichissement d'audit | suites `test_business`, auto-validations, cohérence pièce, imports et staging |

## Fichiers et documentation des fonctions

Nouveaux modules : `journey.py`, `global_views.py`, `revision.py`, `test_journey.py`.
Adaptations : `review_views.py`, `business_views.py`, `business_forms.py`, `review.py`
(provenance d'audit uniquement), `urls.py`, `test_ui.py`. Tous sont sous
`app-suivi-reconciliation/reconciliation`.

Présentation : nouveaux templates `global_controls.html`, `global_control_detail.html`,
composants `multifilter.html` et `review_tabs.html` ; adaptations des listes et fiches
de revue/inventaire, historique, base et libellés des anciens écrans de pièces.
Ajouts CSS dans `workspace.css` et nouveau `multifilter.js` documenté en français.
Le [guide utilisateur versionné](guide_utilisateur_rapprochements.md) décrit les
nouveaux écrans. La copie locale `app-suivi-reconciliation/docs/guide-utilisateur.md`
a aussi été actualisée ; ce répertoire est ignoré par le Git du sous-projet.

L'[inventaire AST](parcours_metier_docstrings.md) recense **chaque définition Python
nouvelle ou modifiée**, avec son rôle et sa docstring. Les méthodes de fixture
réutilisées par alias dans `JourneyTests` sont celles de `test_business.BusinessTests` :
`load`, `inventory`, `entry`, `result`, `confirm`, sans nouvelle implémentation.
JavaScript : `initializeMultiFilters` installe les interactions locales ;
`synchronizeFilter` gère l'exclusion Toutes/choix et le résumé. Les deux fonctions
ont un commentaire français structuré ; elles n'envoient aucune requête.

## Recette manuelle et limites

1. Ouvrir Mes rapprochements : défaut Envoyé/À examiner, propositions en premier.
   Combiner plusieurs projets/règles/décisions ; paginer puis revenir d'une fiche.
2. Sur une proposition exploitable, vérifier Valider/Refuser et l'absence des
   actions manuelles en premier plan. Refuser avec motif puis rechercher Sage.
3. Sur une validation AUTO ou MANUAL, ouvrir Réviser, saisir le motif, confirmer.
   Vérifier la libération de l'écriture et l'historique ; sélectionner une nouvelle
   écriture et prévisualiser avant confirmation.
4. Tester un remplacement d'association reprise : ancienne campagne inchangée.
5. Ouvrir Contrôle des montants : anomalies par défaut, puis Réconciliés et Toutes.
   Vérifier montants courants, état initial séparé et identité composite ODS/ODG.
6. Au clavier : ouvrir les menus par Entrée/Espace, parcourir et cocher les choix,
   vérifier Toutes et le résumé, puis soumettre. Vérifier aussi en largeur mobile.

Le lot UX initial ne nécessitait pas de migration. L'optimisation du 8 novembre
requiert la migration technique 0021 ; aucune régénération JSONL, nouvelle
configuration de base ou modification du moteur n'est requise pour celle-ci.
Redéployer l'application et ses fichiers statiques selon le circuit habituel.
Aucun déploiement ni accès à la base de production n'a été effectué.

La recherche du contexte non confirmé utilise les contextes de contrôle déjà
photographiés ; elle n'invente pas de cible pour une proposition sans contexte.
Les filtres d'état utilisent des colonnes et contextes indexés SQLite/PostgreSQL.
Leur compilation PostgreSQL a été vérifiée sans connexion ; exécution et plans de
production restent à vérifier en recette PostgreSQL dédiée. Aucun second calcul
financier n'est introduit : les colonnes techniques projettent les résultats existants.

La validation visuelle et clavier n'a pas été exécutée dans un navigateur dans
cette session. `node --check` n'a pas pu être lancé : Node n'est pas installé.
Les rendus HTML et parcours serveur sont couverts par les tests Django.

## Vérifications exécutées

- Depuis `app-suivi-reconciliation` : `../.venv/Scripts/python.exe manage.py test
  --noinput --verbosity 0` — **274 tests, succès, 3 ignorés**. Les trois tests de
  concurrence nécessitent PostgreSQL et n'ont pas été exécutés sur cette base SQLite.
- Suite ciblée `reconciliation.test_journey reconciliation.test_ui` : **22 tests
  réussis**, dont 17 nouveaux tests de parcours et 5 tests UI existants adaptés.
- Depuis la racine : `.venv/Scripts/python.exe -m pytest -q` — **192 réussis,
  1 ignoré** (recette réelle optionnelle).
- `manage.py makemigrations --check --dry-run` : aucune migration manquante.
- `git diff --check` : aucune erreur d'espacement.
- Compilation ORM avec un backend PostgreSQL non connecté : requête JSON des
  contrôles valide, sans exécution SQL ni lecture d'une base PostgreSQL.
- Inventaire AST du diff : **44 définitions Python documentées**, aucune docstring
  absente. Les deux fonctions JavaScript sont commentées en français.

Les tests utilisent des bases jetables et des sources synthétiques. Les éventuels
échecs pendant le développement (ancien défaut de liste, chemin du contexte JSON,
affichage avant/après) ont été corrigés avant les succès ci-dessus. Aucun échec
résiduel connu dans les suites exécutées. Le warning existant sur l'absence du
répertoire `staticfiles` dans l'environnement de test reste sans échec de test.

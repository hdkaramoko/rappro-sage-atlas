# Performance de la vue Contrôle des montants — 8 novembre 2026

## Cause et mesures avant changement

La liste recherchait pour chaque contrôle sa clé dans les JSON de décision du
projet. La même sous-requête corrélée apparaissait dans le filtre, l'affichage et
le tri. La pagination à 50 lignes arrivait après le comptage et ce tri global.
L'index sur l'état initial ne couvrait pas l'état courant extrait du JSON.

La base locale contient 314 150 contrôles et 13 681 décisions. En lecture seule,
le comptage et la première page dépassaient chacun 15 secondes et ont été
interrompus à cette limite. EXPLAIN SQLite indiquait trois sous-requêtes corrélées
et un tri temporaire. Une extraction unique des contextes dans une jointure
ramenait le comptage à 2,28 s et la page à 2,36 s.

## Implémentation

- `CampaignGlobalControl.current_state` projette l'état de `current_data`, sinon
  de `data`. L'état initial `state`, les JSON et leurs signatures restent intacts.
- `CampaignGlobalControl.has_pending` mémorise l'existence d'au moins une
  proposition non confirmée pour la clé et le projet. Une décision est confirmée
  si son snapshot est VALIDATED et current=True, comme dans l'ancienne requête.
- `ReviewControlContext` relie une revue photographiée à ses clés de contexte.
  C'est un index reconstructible, **pas un nouveau registre de réservation**.
  Les affectations Sage et les règles financières ne changent pas.
- Les filtres état/alerte et les choix de projets utilisent des colonnes et
  index SQL classiques. Aucun parcours JSON de décision ni sous-requête corrélée
  n'est exécuté à chaque ouverture de la liste.
- Le filtre Anomalies et les sélections d'un seul état ne trient plus une
  priorité constante. La vue Toutes conserve les anomalies avant les réconciliés,
  avec un CASE sur des colonnes légères, pas sur les preuves JSON.
- La pagination sélectionne d'abord les seuls identifiants. Les JSON complets
  sont ensuite chargés pour **la page de 50 contrôles seulement**, dans l'ordre
  choisi et avec un nouveau contrôle de visibilité portefeuille.
- La fiche de contrôle utilise aussi l'index relationnel pour retrouver ses
  propositions, sans chercher sa clé dans chaque JSON du projet.

Les nouveaux index couvrent campagne/projet/état courant/alerte,
campagne/projet/identifiant et campagne/projet/clé/alerte du contexte.
La recherche textuelle explicite `q` reste une recherche dans l'identité JSON
lorsqu'elle est nécessaire. Elle peut être plus coûteuse que les filtres d'état ;
aucun moteur de recherche supplémentaire n'est introduit.

## Cohérence transactionnelle

`control_index.sync_review` actualise les anciennes et nouvelles clés après la
sauvegarde du snapshot de décision. Il recalcule uniquement l'indicateur technique
des clés touchées via la relation indexée. Si une autre revue est encore en
attente, sa présence maintient l'alerte. Retirer ou déplacer une clé retire aussi
l'ancienne alerte. Les clés absentes de l'inventaire ne créent pas de faux contrôle.

`CampaignReview.save` et `save_decision_snapshot` synchronisent les index des
modifications unitaires. Les opérations métier restent dans leurs transactions,
verrous de campagne et vérifications de droits existants. Les recalculs ciblés
sauvegardent automatiquement l'état courant indexé sans modifier le résultat initial.

Pendant un import, `suspend_indexing` évite toute synchronisation par ligne.
`rebuild_campaign` extrait une seule fois les contextes finaux après auto-validations,
reports et actions reprises. Seules les alertes effectivement présentes sont
écrites sur les contrôles ; aucun passage supplémentaire sur les JSON financiers
n'est nécessaire pour cette étape. L'opération reste dans la publication atomique.

Les créations de contrôles par lots fournissent explicitement les colonnes
techniques. Les écritures SQL/bulk externes contournant les services ou les hooks
de sauvegarde ne sont pas une API métier supportée : elles doivent aussi maintenir
ces projections. Aucun index ne se reconstruit lors d'un GET.

## Migration et déploiement

**Nouvelle migration : `0021_control_workspace_indexes`.** Appliquer les migrations
avec la nouvelle version, avant de rouvrir le trafic et les imports :

```powershell
python manage.py migrate --noinput
python manage.py showmigrations reconciliation
```

Vérifier que `0021_control_workspace_indexes` est cochée. Sur SQLite sur disque,
utiliser le circuit existant `prepare_sqlite_imports --migrate` sans worker actif.
La migration peuple les index des campagnes existantes par lots et par campagne,
depuis les snapshots déjà stockés. Son temps dépend du nombre de contrôles et de
la taille des JSON ; ce travail initial n'est pas effectué à chaque affichage.

Les nouvelles colonnes sont nullable afin que SQLite puisse les ajouter sans
reconstruire la grosse table pour chaque champ. Le peuplement initialise toutes
les lignes existantes ; les services fournissent les valeurs des lignes nouvelles.
Les index de contrôles sont créés après ce peuplement.

**Pas besoin de relancer le moteur ou de régénérer le JSONL pour cette optimisation.**
La migration ne rejoue aucune validation automatique, ne change aucune décision,
ne recalcule pas les résultats financiers et ne touche pas aux fichiers sources.
Les paramètres PostgreSQL restent inchangés.

Le staging SQLite publie la nouvelle relation avec les projections, après les
revues qu'elle référence. Les triggers de révision couvrent aussi la relation :
une préparation ancienne reste refusée après une action concurrente.

Aucune migration de la base applicative locale ni opération sur PostgreSQL n'a
été exécutée pendant ce développement. Les migrations sont testées sur des bases
jetables. Un retour de schéma ne supprime que ces colonnes/relations dérivées ;
coordonner toute version applicative avec son schéma, selon le circuit habituel.

## Mesure après optimisation : limites exactes

Une projection **temporaire** a été construite depuis la base locale ouverte en
lecture seule, avec les mêmes colonnes, alertes et index. Les JSON affichés de la
page ont été lus dans la source d'origine ; les fichiers temporaires ont été
supprimés après fermeture des connexions.

| Mesure locale | Résultat |
|---|---:|
| Construction de la projection SQL temporaire et de ses index | 1,65 s |
| Comptage des anomalies visibles, deux passes | 0,0248 / 0,0249 s |
| Nouvelle lecture indépendante du compteur | 0,0388 s |
| Première page de 50 identifiants + lecture/parsing des JSON source | 0,0008–0,0011 s |
| Compteur obtenu | 163 072 |

Ce compteur est identique à celui du prototype par extraction unique sur le même
périmètre. Ces chiffres concernent la projection locale, avec cache disque et sans
authentification/rendu HTTP. Ils ne mesurent ni la durée de migration Django sur
314 150 contrôles, ni la latence PostgreSQL, ni celle de l'application déployée.

La requête PostgreSQL des filtres/pagination a été compilée sans connexion et ne
contient plus de sous-requête corrélée, COALESCE ou extraction JSON. La requête de
détail de la page conserve naturellement son COALESCE pour les 50 résultats.
La recette PostgreSQL et ses plans EXPLAIN restent à réaliser sur la base complète.

## Tests et traçabilité

| Vérification | Test / module |
|---|---|
| Compteur et pagination sans exploration JSON ni EXISTS | `test_count_and_pagination_do_not_read_json_or_correlated_subqueries` |
| Validation/annulation et résultat courant | `test_confirm_and_cancel_update_pending_in_same_transaction`, suite `test_journey` |
| Retrait/changement d'une clé | `test_removed_context_refreshes_both_old_and_new_keys` |
| Autre revue encore non confirmée | `test_another_pending_review_keeps_the_alert` |
| Reconstruction technique idempotente, décisions intactes | `test_rebuilding_index_is_idempotent_and_does_not_touch_decisions` |
| Migration 0020 → 0021 sur une campagne importée | `test_existing_campaign_backfill_preserves_business_data` |
| Publication réelle SQLite avec états et contextes | `test_lot1_inventory_and_controls_survive_staging` |
| Portefeuilles, ODS, filtres, contrôle courant | suites `test_journey`, `test_business` |

Commandes exécutées depuis l'application :

- `manage.py test reconciliation.test_control_index --noinput --verbosity 0` :
  **6 tests réussis**.
- `manage.py test reconciliation.test_journey reconciliation.test_business
  --noinput --verbosity 0` : **54 tests réussis**.
- `manage.py test --noinput --verbosity 0` : **292 tests, succès, 3 ignorés**.
  Les trois tests de concurrence PostgreSQL nécessitent une base dédiée.
- `makemigrations --check --dry-run` : aucune migration manquante.
- `git diff --check` : aucune erreur d'espacement.

Le [relevé des docstrings](performance_controle_montants_docstrings.md) recense
toutes les définitions Python nouvelles ou modifiées et leur rôle en français.
Les principales adaptations sont `models.py`, `control_index.py`, `global_views.py`,
`campaigns.py`, `global_control.py`, la migration 0021 et le staging SQLite.

## Recette sur la base complète

1. Déployer et appliquer 0021 avant d'ouvrir la nouvelle vue.
2. Mesurer l'ouverture de Contrôle des montants, puis Toutes et Réconciliés,
   avec/sans filtre projet ; comparer les compteurs et les résultats connus.
3. Valider puis annuler une ligne : vérifier la disparition/réapparition de son
   alerte et la conservation d'une alerte si une autre proposition reste à examiner.
4. Vérifier une correction, un rapprochement manuel et une importation de campagne.
5. En cas de lenteur résiduelle, relever le filtre, la page, le temps et le plan
   EXPLAIN PostgreSQL. Distinguer recherche textuelle, comptage, pagination et
   chargement des 50 preuves ; ne pas déduire le temps serveur du seul nombre SQL.

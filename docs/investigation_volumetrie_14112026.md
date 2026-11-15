# Investigation des volumes des campagnes du 12 et du 13 novembre 2026

Analyse en lecture seule des deux JSONL et de la base SQLite locale, le 14 novembre 2026. Aucun accès à PostgreSQL déployé et aucune modification des données.

## Comparaison des fichiers

Les deux fichiers contiennent chacun 366 451 lignes d'inventaire Atlas (1 568 projets), 511 927 lignes Sage, 12 880 propositions (598 projets) et 305 589 contrôles.

Les empreintes SHA-256 par section, calculées sur les lignes brutes dans leur ordre d'origine, sont identiques pour les inventaires Atlas et Sage, les propositions et les contrôles. Les différences d'en-tête portent sur les métadonnées de département/pôle, le nom, la génération et les sources. L'en-tête et le marqueur final diffèrent.

## Reconstitution des compteurs

| Périmètre dans SQLite | Total | Cadrés | Non cadrés | Insuffisants |
| --- | ---: | ---: | ---: | ---: |
| Référentiel Project, utilisé par les écrans | 598 | 233 | 322 | 43 |
| Inventaire Atlas complet | 1 568 | 1 018 | 505 | 45 |
| Projets Atlas absents de Project | 970 | 785 | 183 | 2 |
| Sage uniquement, hors inventaire Atlas | 56 | 43 | 13 | 0 |
| Ensemble des synthèses comptables | 1 624 | 1 061 | 518 | 45 |

Le périmètre Atlas complet de la base locale reproduit exactement les deux chiffres annoncés pour l'application déployée : 1 568 et 1 018. Il n'y a pas de perte d'inventaire ni de synthèse comptable dans SQLite.

## Cause dans le code

- `reconciliation/campaigns.py:insert_inventory` crée les photographies `CampaignInventory`, sans créer les objets `Project`.
- `reconciliation/review_import.py:upsert_group` crée un `Project` lorsqu'une proposition le référence. Les propositions couvrent seulement 598 projets dans les deux fichiers.
- `dashboard/views.py:index` compte les objets `Project` actifs.
- `reconciliation/accounting_views.py:accounting_list` limite les synthèses aux codes renvoyés par `campaign_views.py:projects_for`, même pour un administrateur global. Cette fonction utilise aussi `Project`.
- L'import de portefeuilles peut compléter le référentiel depuis l'inventaire (`projects/portfolio_import.py`). Des imports antérieurs peuvent également expliquer un référentiel plus complet sur le déploiement. Son historique exact reste à vérifier sur PostgreSQL.

Le défaut relève donc de la construction du référentiel et du filtrage des écrans. Aucun élément observé ne révèle une différence de calcul SQL entre SQLite et PostgreSQL.

## Correction recommandée

Compléter le référentiel avec tous les projets de l'inventaire Atlas lors de chaque import, y compris les projets sans proposition. Prévoir un rattrapage idempotent pour les campagnes déjà importées. Préserver les libellés existants, les désactivations explicites et les affectations de portefeuille ; ne pas attribuer automatiquement de nouveaux projets aux utilisateurs.

Conserver explicitement la distinction entre périmètre Atlas (1 568) et union Atlas/Sage (1 624) pour éviter d'introduire un second écart de compteurs en incluant implicitement les 56 projets Sage seuls.

La correction applicative et le rattrapage de base ne sont pas effectués dans cette investigation.

## Reproduction

Depuis la racine du dépôt : `.venv/Scripts/python.exe docs/investigate_project_volumes.py`. Le script ouvre SQLite en lecture seule et lit les deux JSONL en flux.

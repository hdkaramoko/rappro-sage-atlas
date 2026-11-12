# Contrôle global : charges EUR et devise d'origine — 8 novembre 2026

## Correction

Le contrôle global ne considère plus la devise d'origine Atlas comme une anomalie.
Les colonnes comparées sont déjà en euros : **Total charges SAGE (€)** (ou le champ
de charges projet EUR configuré) et **Charges (Dépenses)** Sage. Une opération
libellée XOF ou USD ne nécessite aucune conversion supplémentaire de ces charges.
La devise source et tous les montants restent conservés tels qu'importés.

Le cas du projet `16DDU0C206`, pièce `ETR0126082924`, illustre le faux positif :
Comptabilisé retenu −372,41 €, Sage −372,41 €, écart 0,00 €, avec comme seul motif
« Devise Atlas non EUR à confirmer ». Ce seul motif disparaît du calcul futur.

Les autres garde-fous restent actifs : montant absent, différence au-delà de la
tolérance, incohérence d'identité/date/exercice, signes mixtes, ODS/ODG ambigu,
réservation partagée ou non confirmée, etc. Aucun rapprochement, décision ou
autorisation AUTO n'est créé par cette évolution. La recherche manuelle et les
critères de décision ne sont pas élargis par ce correctif du contrôle global.

## Résultats déjà enregistrés

**Migration `0022_global_control_eur_charges`** : elle traite uniquement les résultats
courants indéterminés de la campagne **active et publiée** contenant le motif
obsolète. Les campagnes closes ne sont pas modifiées.

La migration retire ce seul motif des raisons globales et Comptabilisé, puis
dérive les états à partir des écarts et de la tolérance déjà enregistrés :

| Situation après retrait du motif | État |
|---|---|
| Aucun autre motif, écart dans la tolérance | EQUILIBRE |
| Aucun autre motif, écart réel | ECART |
| Autre motif ou montant non exploitable | INDETERMINE |
| Exclusion existante | EXCLU conservé |

`data`, l'état initial `state`, les sources Atlas/Sage, les décisions et leurs
historiques restent intacts. Le nouveau diagnostic est enregistré dans
`current_data`, sa signature et `current_state` sont actualisés, sa version et sa
date sont incrémentées. Le drapeau antérieur `auto_validated` est conservé :
aucune auto-validation historique n'est réactivée. `has_pending` reste également
inchangé ; une proposition non confirmée peut donc maintenir le contrôle dans
la vue des anomalies même lorsque son écart financier est nul.

Le traitement est borné à 250 lignes par page et avance par clé primaire,
pour éviter de déplacer des lignes devant un curseur sur l'état qu'il modifie.
La campagne est verrouillée dans la transaction de migration, avant les mises à
jour, suivant l'ordre des services métier. Une seconde application du traitement
ne modifie pas à nouveau les résultats nettoyés.

Le retour arrière de migration ne réintroduit pas automatiquement le motif
obsolète. Le diagnostic initial reste consultable dans son volet historique ;
aucune source n'est nécessairement réimportée pour retrouver cette trace.

## Déploiement

Déployer la nouvelle version et appliquer les migrations dans le circuit habituel,
avant de rouvrir les écritures et imports :

```bash
python manage.py migrate --noinput
python manage.py showmigrations reconciliation
```

Vérifier que `0022_global_control_eur_charges` est cochée. Sur SQLite sur disque,
le circuit existant `prepare_sqlite_imports --migrate` reste disponible hors worker
actif. La durée du traitement initial dépend du volume des diagnostics concernés.

**Pas besoin de régénérer le JSONL ni de réimporter la campagne.** Les imports et
recalculs ciblés futurs utilisent directement la règle corrigée. L'optimisation
de consultation de la migration 0021 reste en place.

Après déploiement, vérifier la pièce illustrée et le compteur d'anomalies. Les
99 728 contrôles identifiés localement avec écart nul et seul motif devise sont
des candidats à la reclassification financière ; le compteur de la vue tient
toujours compte des autres anomalies et des propositions non confirmées.
La ventilation des groupes restants par motif sera une étape distincte.

## Vérifications

- `pytest tests/test_global_currency.py -q` : **10 tests réussis** (devises EUR,
  XOF, USD, montants positifs/négatifs, vrais écarts, preuves et montants absents).
- `manage.py test reconciliation.test_global_currency reconciliation.test_control_index
  reconciliation.test_journey --noinput --verbosity 0` : **26 tests réussis**.
- `pytest -q` : **216 réussis, 1 ignoré** (recette réelle optionnelle).
- `manage.py test --noinput --verbosity 0` : **295 tests, succès, 3 ignorés**.
  Les tests de concurrence PostgreSQL nécessitent une base dédiée.
- Dernière vérification ciblée après ajout du verrou de campagne :
  `manage.py test reconciliation.test_global_currency --noinput --verbosity 0` :
  **3 tests réussis**.
- `makemigrations --check --dry-run` : aucune migration manquante.
- `git diff --check` : aucune erreur d'espacement.

La migration est testée sur plus de 250 diagnostics et vérifie le maintien des
motifs restants, des campagnes closes, de l'initial, des montants, du drapeau AUTO,
des alertes non confirmées et de l'idempotence. Aucun traitement n'a été appliqué
à la base applicative existante ou à PostgreSQL pendant ce développement.

Fonctions concernées : `reconciliation_contract.sage_inventory.consolidate`, les
helpers figés `monetary_state`, `normalize_current`, `correct_active_diagnostics`
de la migration, et les recettes du contrat et de la migration. Le test de
migration 0021 restaure désormais le schéma courant 0022 en fin de scénario.
L'[inventaire des docstrings](controle_global_charges_eur_docstrings.md) recense
les définitions nouvelles ou modifiées, toutes documentées en français.
Le relevé contient **16 définitions**, sans docstring manquante.

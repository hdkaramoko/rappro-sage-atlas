# Correctifs tiers ODS/ODG, BAP et filtres

## Règles et compatibilité

Les nouveaux JSONL v3 ajoutent `ods_party_policy: missing-equivalent-v1`.
Cette métadonnée distingue les nouvelles clés des signatures historiques : sans
elle, les fichiers et campagnes conservent leurs anciennes clés. Une politique
inconnue est refusée. Déployer le moteur et Django ensemble.

Pour ODS/ODG seulement, les tiers nuls, vides, composés d'espaces ou `NA`
(casse et espaces périphériques ignorés) partagent une clé technique d'absence.
Les tiers renseignés restent distincts ; absent et renseigné ne sont pas assimilés.
Les sources restent intactes. Le titre du groupe affiche « Non renseigné
(vide/NA) » plutôt que la clé technique. Projet, exercice, libellé et contrôles
métier restent requis ; ODA est inchangé.

Le contexte partagé s'applique aux clés de l'export, de l'import et des services
Django. Il est réinitialisé après appel et avant chaque sortie d'un générateur,
même partiellement consommé. Dans le cadrage, seul le choix des clés change :
formules, exclusions et états comptables restent inchangés.

`MATCH_BAP` réutilise l'exclusion des faux concurrents de `MATCH_FUZZY_HIGH`.
Une ligne comptabilisée cesse de bloquer seulement si son écriture Sage est
prouvée distincte : pièce/date/tiers concordants, identité technique complète,
référence unique et différente de la candidate. Une pièce différente seule ne
suffit pas. Concurrents réels, identités manquantes et références dupliquées
restent bloquants. Unicité bilatérale, équilibre, tolérances, réservations,
cascade et décisions humaines prioritaires sont conservés.

Le filtre multisélection « Type de pièce » propose les types du périmètre autorisé
de la campagne : trois premiers caractères de la pièce ou ODS/ODG. La projection
comptable existante fournit le type ; une expression SQL sur l'identité sert de
repli aux anciens contrôles sans projection. Filtrage serveur avant pagination,
compatible avec projet, état, origine et recherche. « Toutes » est exclusif et
devient le défaut de Type et Origine, également après réinitialisation.

## Résultats et mesures

- Cas réel ODG Atlas `1617252`–`1617254`, projet `22SSE0C372` : deux groupes
  auparavant (`INDETERMINE`, `ECART`), un groupe `EQUILIBRE` après normalisation,
  trois lignes par source, total −890 €. Vérification en lecture seule.
- Cas réel `1710939` : le garde BAP passe après exclusion des quatre faux
  concurrents prouvés distincts. Sa décision courante n'est pas modifiée ; les
  autres contrôles restent requis. Le jeu synthétique vérifie l'auto-validation
  complète à l'import d'une nouvelle campagne.
- Suite moteur : 306 tests réussis, un test réel optionnel ignoré.
- Suite Django complète : 425 tests, succès, trois tests PostgreSQL ignorés
  sous SQLite. Puis six tests ciblés réussis, incluant le nouveau test de filtre
  sur 1 000 contrôles. Couverture : anciennes clés/signatures, sources préservées,
  concurrence réelle/incomplète, permissions, multisélection et pagination.
- `makemigrations --check --dry-run` : aucune migration nécessaire.

Sur le projet réel `20GDH0C171`, construction de l'index pour 3 236 Atlas et
3 933 Sage : 34 ms. Pour 1 000 vérifications BAP répétées : avant, 11,8 ms
(toutes refusées) ; après, 31,0 ms (toutes autorisées). Surcoût observé : environ
19 µs par vérification, index et caches réutilisés. Ce n'est pas un benchmark
d'import complet. Filtre sur 1 000 contrôles matérialisés SQLite : 44 ms,
12 requêtes. La requête des options de type reste séparée des comptes/pages.
PostgreSQL n'a pas été mesuré ici.

## Fichiers et recette

- Contrat : `reconciliation_contract/ods_party.py`, `__init__.py`,
  `fuzzy_safety.py` ; moteur : `reconciliation/multiples.py`, `exporters/review.py`.
- Django : `campaigns.py`, `multiple_import.py`, `multiple_review.py`,
  `global_control.py`, `auto_validation.py`, `accounting.py`, `global_views.py`,
  `review_ui.py` et les trois templates affichant les groupes.
- Jeux/audit : `examples/ods_bap_filters_fixture.py`, `audit_ods_bap_rules.py`.
  Tests dédiés : `test_ods_party_policy.py`, `test_fuzzy_safety.py`,
  `test_ods_bap_filters.py`, avec adaptation des tests UX existants.

Tests moteur depuis la racine : `.venv/Scripts/python.exe -m pytest -q`.
Tests Django depuis `app-suivi-reconciliation` :
`../.venv/Scripts/python.exe manage.py test reconciliation --noinput`.
Pour le jeu ciblé, utiliser `reconciliation.test_ods_bap_filters`.

Après déploiement, générer un nouveau JSONL avec l'inventaire Sage complet,
importer une nouvelle campagne puis vérifier les deux cas et les filtres.
Les filtres fonctionnent immédiatement sur les anciennes campagnes ; leurs
regroupements et décisions restent historiques. Aucun recalcul de la campagne
courante ni lancement de `prepare_accounting` n'est requis pour cette livraison.

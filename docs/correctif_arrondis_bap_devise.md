# Correctif arrondis, BAP et devise — 10 novembre 2026

## Comportement livré

La tolérance reste **0,01 €**. Le moteur ne compare plus l'écart flottant pour
autoriser AUTO : il reconstruit les deux montants via `Decimal(str(montant))`
et soustrait ces décimaux. Pour 13 253,91 € et 13 253,92 €, l'écart devient
exactement -0,01 €, au lieu de -0,010000000000218279. Les valeurs absentes,
non finies et les écarts strictement supérieurs à un centime restent refusés.
L'exporteur somme aussi les montants sources en Decimal avant l'autorisation,
pour ne pas dépendre d'un éventuel résidu dans les sommes flottantes du matching.
Les anciens appels techniques ne fournissant que `amount_difference` conservent
une lecture décimale de cet écart ; les vrais résultats moteur portent les deux
montants. Aucun arrondi artificiel ou passage à 0,05 € n'est ajouté.

Le matching utilisait déjà projet/tiers/BAP. C'est le contrôle supplémentaire
d'unicité AUTO fuzzy qui ignorait le BAP. Son index partagé utilise désormais
**projet / tiers / exercice / BAP**, puis le montant signé compatible au centime.
Deux BAP connus et différents ne se concurrencent plus ; deux occurrences
compatibles de même BAP restent bloquantes. Le BAP de la paire doit être présent
des deux côtés et identique après normalisation des espaces et de la casse.
Un concurrent sans BAP reste potentiellement concurrent et bloque AUTO :
l'absence de référence ne constitue pas une preuve d'un autre périmètre.

Les devises d'origine ne participent plus aux refus fuzzy ni à la recherche
manuelle Sage. Les champs de charges comparés sont déjà en euros : aucune
conversion n'est réalisée. Ainsi `EUR - Euro`, `EUR`, USD ou XOF en devise
d'origine ne changent pas les charges EUR analysées. La recherche conserve
le contrôle du statut Atlas, des droits, de la publication et du périmètre.
Son message de statut ne mentionne plus la devise.

Le filtre Origine utilise **Présentes dans les deux** lorsque le paramètre GET
est absent, notamment à l'ouverture et après Réinitialiser. Une valeur vide
explicite continue de sélectionner **Toutes**, conservée par la pagination.
Les autres états, multisélections et règles de présence restent inchangés.

## Implémentation et compatibilité

- `reconciliation/auto_validation.py` : écart AUTO calculé en Decimal.
- `reconciliation_contract/fuzzy_safety.py` : BAP dans l'index bilatéral et
  suppression de la comparaison de devises d'origine.
- `reconciliation/exporters/review.py` : sommes décimales des sources pour
  l'autorisation ; alimentation du BAP de l'index Atlas
  depuis les colonnes canoniques ; référence Sage depuis les attributs existants
  de l'inventaire ; vérification de la référence de la preuve retenue.
- `app-suivi-reconciliation/reconciliation/auto_validation.py` : à l'import,
  BAP Atlas depuis les sources photographiées des revues Envoyé SAGE ;
  Comptabilisé depuis l'inventaire, conservé comme concurrent potentiel si son
  BAP n'est pas connu ; référence Sage depuis `attributes.Référence`.
- `business.py` : retrait du veto sur la devise d'origine dans `search_sage()`.
- `global_views.py` : défaut `origin=both` sans écraser Toutes explicite.

Les objets enrichis de référence sont privés au contrôle d'unicité : aucun
champ n'est ajouté aux entrées Sage signées, ni aux modèles, ni au format JSONL.
Aucune migration ou maintenance des statistiques n'est nécessaire.
Les capacités v3, identités d'écriture, réservations manuelles, conflits de
référence, capacités collectives et priorités humaines sont conservés.
Les opérations de révision et les signatures historiques ne sont pas réécrites.

Le défaut Origine implique le prédicat SQL de présence JSON déjà utilisé par
ce filtre. Il n'effectue pas de traitement global en Python, mais peut parcourir
les groupes SQL de la campagne. Les tests de filtre d'état et d'index sans
restriction d'origine utilisent désormais Toutes explicite ; ils continuent
de vérifier le comptage sans extraction JSON. Aucune optimisation ni nouvelle
projection de présence n'est ajoutée dans ce correctif.

La recherche complémentaire à l'écriture pour les Sans correspondance est hors
de ce correctif. Les règles de regroupement du moteur, le cadrage comptable,
les signes et les libellés des états ne changent pas.

## Vérification et recette

Tests synthétiques ajoutés/adaptés :

- frontière décimale 13 253,91 / 13 253,92 admise ; 13 253,93 et absence refusées ;
- groupe Exact à deux lignes par source dont les sommes flottantes dépassent
  artificiellement un centime : export AUTO admis depuis les sommes décimales ;
- même montant, même projet/tiers mais autre BAP admis ; même BAP concurrent,
  BAP absent/incompatible et preuve réutilisée refusés ;
- devises d'origine différentes admises pour des charges EUR ;
- import AUTO fuzzy, écritures distinctes sur une même pièce et réservation
  manuelle active inchangés ;
- recherche avec Atlas USD admise, statut non autorisé toujours refusé ;
- Origine par défaut, Toutes explicite et pagination.

Lecture seule de `data/outputs/campagne_10112026.jsonl`, sans importer ni modifier
la base de travail : les contrôles bilatéraux corrigés passent pour **1802228**
et **1856928** ; l'autorisation décimale est éligible pour **1797571**.
Cela vérifie ces garde-fous ; la décision finale d'une nouvelle campagne reste
soumise aux contrôles d'import et aux réservations existantes.

Pour bénéficier des AUTO, déployer le moteur et Django, **régénérer un JSONL v3
et importer une nouvelle campagne**. Une ancienne proposition sans autorisation
AUTO n'est pas recalculée rétroactivement. La recherche sans veto devise et le
défaut Origine sont actifs dès le déploiement de Django, sans réimport.

La suite moteur complète passe : **258 tests réussis, 1 ignoré**. Les 122 tests
Django ciblés auto-validation/parcours/métier passent. Le scénario supplémentaire
d'export du groupe Exact passe également (1 test), ainsi que les 13 tests
de régression UX/index adaptés à Toutes origines explicite. La suite Django complète
passe : **355 tests exécutés, succès, 3 ignorés**. `makemigrations --check --dry-run`
ne détecte aucun changement ; le contrôle AST confirme les docstrings françaises
sur les définitions modifiées et `git diff --check` ne signale aucune erreur.
Aucun serveur PostgreSQL ni navigateur
de recette n'est disponible ici : le rendu sur le déploiement et PostgreSQL
restent à vérifier. Aucun benchmark de production n'est effectué.

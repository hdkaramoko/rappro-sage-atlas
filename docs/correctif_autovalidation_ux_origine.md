# Auto-validation fuzzy, révision et filtre Origine

Le [lot sélection Sage, Sans libellé et recours BAP/individuel](matching_bap_individuel_decision.md)
étend désormais les autorisations et le préremplissage décrits dans cette note.

Le [correctif arrondis, BAP et devise](correctif_arrondis_bap_devise.md) décrit
les ajustements du 10 novembre 2026 et remplace les restrictions de devise,
le périmètre d'unicité sans BAP et le défaut Origine décrits dans cette version initiale.

## Analyse d'impact et choix retenus

La configuration effective `reconciliation/config.py` autorisait Confirmé,
Exact et Montant, alors que le contrat partagé acceptait déjà les deux règles
fuzzy. `proposal_metadata()` savait lever leur seule réserve expérimentale,
mais `candidate_count == 1` ne démontrait pas l'absence d'un concurrent écarté
par le score ou le préfiltre. L'export JSONL et son import Django nécessitent
donc une vérification supplémentaire des inventaires complets.

Le correctif active `MATCH_FUZZY_HIGH` et `MATCH_FUZZY_REVIEW`. La classification,
le score et les preuves restent ceux du moteur. Les autorisations sont toujours
émises par le moteur puis contrôlées par Django, qui ne relit pas sa configuration.

Le contrat pur `reconciliation_contract/fuzzy_safety.py` construit deux index
projet/tiers/exercice, triés par montant. La paire doit porter le même projet,
le même tiers normalisé sans approximation, le même exercice et des charges EUR
signées concordant à 0,01 € maximum. Une devise source explicitement incompatible
reste bloquante. Une seule occurrence est admise dans chaque sens, sur les
inventaires complets, indépendamment du libellé ou du score. Par prudence, un autre
BAP ou libellé ne départage pas deux occurrences de même projet/tiers/exercice et
montant ; la proposition reste disponible pour arbitrage. Les Comptabilisé sont
aussi pris en compte comme concurrents potentiels, avec leurs charges Sage.

Les fuzzy automatiques exigent un JSONL v3 avec `sage_inventory_v1`, une seule
ligne Atlas et une seule écriture Sage à référence complète. Les anciens fichiers
sans cette preuve ne peuvent pas produire une nouvelle AUTO fuzzy. Le matching
continue de proposer ses regroupements ; le correctif n'invente aucune règle
d'auto-validation de regroupement fuzzy. Les regroupements Exact justifiés restent
inchangés.

À l'import, `automatic_blockers()` revérifie l'unicité avant les décisions,
recense toutes les revendications, même sans autorisation AUTO, puis conserve les
contrôles collectifs de capacité. Les règles fuzzy réutilisent les contrôles
individuels d'Exact dans `multiple_review.py` : deux écritures identifiables
distinctes peuvent partager une pièce ; une même écriture ne peut pas être
réutilisée. Les réservations manuelles actives, les anomalies de preuve/période,
les exclusions et les priorités humaines restent bloquantes selon les services
existants. Aucun changement de signe, conversion ou nouvelle tolérance.

## Révision et sélection Sage

`RevisionForm` et `CancelLinkForm` n'exigent plus les champs `confirm_revision`
et `confirm_cancel`. Le motif reste obligatoire et soumis par le bouton explicite
existant. Les vues utilisent déjà la validation des formulaires et les services
transactionnels : pas de contournement serveur, ni de changement des droits,
versions, CSRF, campagne courante, audit ou libération des affectations.
La confirmation distincte de remplacement est conservée.

Dans `inventory_detail.html`, seules les cases `entries` reçoivent une classe
spécifique et un label cliquable. Le style local dans `workspace.css` fixe leurs
dimensions et dimensions minimales à 18 px, neutralisant aussi le minimum global
de 42 px. La cible mesure au moins 44 × 44 px, le focus clavier est visible et
l'état désactivé reste natif. Les noms, valeurs, sélection multiple, POST,
recherche et pagination sont inchangés.

## Origine : définition et requêtes

La vue concernée est **Mes rapprochements → Contrôle des montants**, pas le
cadrage autonome. Le résultat courant `Coalesce(current_data, data)` contient
déjà `atlas_count`, `sage_count` et `confirmed_allocations`, maintenus par les
imports et recalculs existants, après corrections et liens manuels.

- Présence Atlas : `atlas_count > 0`, ou au moins une affectation Envoyé SAGE
  validée et actuelle dans `confirmed_allocations`.
- Présence Sage : `sage_count > 0` dans un groupe non exclu.
- Atlas uniquement / Sage uniquement : une seule de ces présences.
- Présentes dans les deux : les deux présences, sans condition sur les montants.

Un zéro ou une compensation n'effacent jamais une présence. Les propositions
non confirmées ne sont pas des contributions Atlas. Les clés composites ODS/ODG
et les rattachements manuels sont ceux du résultat existant.

Les groupes entièrement exclus, sans compteurs exploitables (absents ou valeur JSON `null`)
ou issus d'une campagne sans inventaire Sage complet ne sont pas classés dans
une origine certaine ; ils restent visibles via **Toutes** avec les autres filtres
habituels. Un groupe partiellement exclu conserve la présence de ses sources
pertinentes et son anomalie existante. Aucun état n'est renommé ou recalculé.

`origin` accepte `atlas`, `sage`, `both`, ou une valeur vide pour Toutes. Le
composant `multifilter.html`, `filter_menu()` et `selections()` sont réutilisés.
Les origines spécifiques sont combinées en OU ; projet/état/recherche en ET.
La valeur vide annule toute restriction. Les liens de pagination gardent les
valeurs multiples et Réinitialiser conserve son comportement.

Le prédicat est exécuté en SQL avant décompte et pagination ; les JSON sont
interrogés par l'ORM, sans décodage de l'ensemble des groupes en Python,
sous-requête corrélée ni N+1. Il réutilise les données matérialisées existantes :
aucune colonne, migration ou backfill. Le filtrage JSON n'ajoute pas d'index ;
une recherche d'origine peut nécessiter un parcours SQL des groupes de la campagne.
Les opérations ORM utilisées sont disponibles sous SQLite et PostgreSQL.

## Livraison et recette

Fichiers métier : `config.py` active les règles ; `auto_validation.py` côté moteur
documente l'autorisation ; `exporters/review.py` la borne aux preuves complètes ;
`fuzzy_safety.py` porte la vérification partagée ; côté Django,
`auto_validation.py` et `multiple_review.py` recontrôlent les affectations.
Les deux formulaires, `global_views.py`, le template d'inventaire et le CSS
portent les évolutions UX. `test_fuzzy_safety.py`, `test_auto_validation.py` et
`test_journey.py` couvrent les changements. Toutes les définitions créées ou
modifiées disposent d'une docstring française.

Après déploiement du moteur et de l'application :

1. Relancer le moteur avec les sources Atlas/Sage et la commande habituelle
   produisant un nouveau JSONL v3 avec inventaire Sage complet.
2. Importer une **nouvelle campagne de test**. Aucun recalcul rétroactif,
   `prepare_accounting` manuel ou changement des décisions historiques n'est requis.
3. Vérifier les deux catégories fuzzy : paire certaine → AUTO ; concurrents,
   preuve incomplète ou écriture occupée → arbitrage, avec motif de refus.
4. Tester révision et annulation avec puis sans motif ; vérifier l'historique.
5. Tester Origine seul, multisélection, projet/état/recherche et seconde page,
   dont un groupe ODS/ODG et une présence à zéro.
6. Vérifier visuellement sur desktop/mobile les cases Sage, le focus clavier,
   les états cochés/désactivés et la sélection de plusieurs écritures.

Les tests utilisent des sources synthétiques et des bases de test jetables.
La base de travail et les JSONL réels ne sont pas réécrits. La recette graphique
et l'exécution PostgreSQL ne sont pas disponibles dans cet environnement ; elles
restent à réaliser sur le déploiement. Aucun gain de durée sur base complète
n'est revendiqué.

Ce correctif ne réalise **aucune optimisation de performance après validation**,
aucune refonte des recalculs/transactions/imports et **aucun renommage des états**
Écart / À revoir.

## Vérifications exécutées

- Suite moteur : `python -m pytest -q` — 247 tests réussis, 1 ignoré.
- Suite Django complète : `python manage.py test --noinput --verbosity 0` —
  351 tests exécutés, succès, 3 ignorés.
- Tests ciblés Django auto-validation/parcours : 81 exécutés, succès, avant
  ajout du scénario supplémentaire de réservation manuelle active.
- Scénario supplémentaire de réservation manuelle active : 1 test exécuté, succès.
- Nouvelle exécution des 15 tests du contrat/export fuzzy après ajustement du
  parcours en flux de Sage : succès.
- `python manage.py makemigrations --check --dry-run` : aucun changement détecté.
- `git diff --check` : aucune erreur d'espacement.
- Contrôle AST des définitions Python modifiées/créées : docstrings présentes.

Le test Origine sur 200 groupes supplémentaires vérifie le filtrage SQL avant
`LIMIT 50`, la conservation des choix entre pages et moins de 15 requêtes ;
ce n'est pas un benchmark de durée sur la base complète.

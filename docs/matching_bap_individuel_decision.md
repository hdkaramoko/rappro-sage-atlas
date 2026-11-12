# Sélection Sage, AUTO sans libellé et recours BAP / individuel

Le [volet A](volet_a_bap_tolerance.md) complète ce lot : nouveau libellé
« N° BAP uniquement », références visibles et tolérance de 0,05 € pour les
deux seuls recours, dans les nouveaux contrats déclarés. Les seuils historiques
décrits ci-dessous restent ceux des anciennes campagnes.

## État des lieux avant / après

Avant ce lot, le moteur agrégeait par projet, tiers, BAP et libellé puis exécutait
Confirmé Atlas → Exact → Montant → Fuzzy → Sans contrôle du libellé. Deux
libellés Atlas différents pouvaient donc rester sans proposition face à un
libellé Sage agrégé commun. Le BAP participait déjà au bloc de recherche.

Le contrat acceptait déjà `MATCH_WITHOUT_LABEL`, mais la configuration ne
l'activait pas. Les protections individuelles développées pour Exact et Fuzzy
pouvaient être réutilisées. La fiche Django proposait les écritures individuelles,
mais le JavaScript calculait seulement un aperçu : cocher ne renseignait pas
le montant de décision, qui lisait les charges Sage encore absentes dans Atlas.

Après ce lot :

1. La sélection remplit immédiatement montant affecté, pièce/date non ambiguës.
2. Sans contrôle du libellé peut recevoir AUTO après toutes les preuves structurées.
3. Les seuls groupes **UNMATCHED** passent ensuite par BAP puis Individuel.
   Les propositions antérieures, y compris ambiguës, gardent leur priorité.

La décision utilisateur ne dépend jamais d'un montant calculé uniquement par le
navigateur. Les sources, les statuts Atlas initiaux et les campagnes historiques
ne sont pas réécrits. Aucun modèle, migration ou moteur comptable parallèle.

## Sélection et décision métier

Le JavaScript utilise des entiers en milliardièmes pour sommer les charges
signées sans résidu flottant. Le champ est affiché au centime, avec l'arrondi
pair utilisé par Decimal ; les neuf décimales sources restent conservées côté
serveur. Zéro et montants négatifs sont traités comme de vraies valeurs.

Une coche/décoche actualise la somme. Une pièce/date est proposée uniquement
si chaque écriture sélectionnée porte la même valeur connue. Les conflits sont
signalés ; le service demande une pièce/date principale au lieu d'en choisir une.
Les modifications volontaires d'un champ ou de son mode sont conservées lors
des coches suivantes. Le bouton **Recalculer depuis la sélection Sage** rend
explicitement les champs au calcul automatique. Tout décocher restaure les
valeurs et modes d'ouverture des seuls champs calculés, sans effacer une saisie.

L'étiquette du montant source est **Charges SAGE dans Atlas**, distincte du
Montant Atlas (charges projet). Le script est chargé avec `{% static %}` pour
respecter le préfixe de déploiement, notamment les accès via proxy Onyxia.

Au POST, le service, sous les verrous existants :

- recharge les références parmi les preuves de la campagne ;
- exige une identité complète, le même projet/exercice et des charges présentes ;
- recalcule la somme en Decimal ;
- préremplit les champs à Conserver dont la source est vide, même sans JavaScript ;
- préserve une valeur source explicitement conservée lorsqu'elle correspond aux
  écritures et refuse un montant conservé incompatible ;
- compare la saisie manuelle à la somme exacte ; pour un champ marqué automatique,
  compare aussi son affichage au centime puis conserve la somme exacte, jamais
  la valeur arbitraire reçue du navigateur ;
- vérifie pièce/date, réservations d'inventaire, contrôle de capacité, versions,
  signature et droits selon les mécanismes existants.

Les marqueurs `selection_auto` ne donnent aucune autorisation. Une référence
étrangère/inventée, une somme falsifiée, une écriture déjà affectée ou une
capacité dépassée produisent une erreur précise sans mutation partielle.
Une sélection d'écritures entières ne peut plus passer au-delà de la capacité
par simple commentaire : ce garde-fou concerne les sélections, pas les anciens
parcours de correction sans sélection. Une pièce reste partageable avec des
écritures distinctes disponibles. Aucun nouveau partage fractionnaire.

## Autorisations AUTO et preuves communes

Les règles suivantes utilisent le même contrôle bilatéral structuré : Fuzzy,
Sans contrôle du libellé, BAP et Individuel. Chaque AUTO exige : projet, tiers,
exercice, BAP connu et cohérent ; montant signé compatible à **0,01 €** maximum ;
une occurrence Atlas et une écriture Sage admissible dans les deux sens ; identité
Sage stable ; aucun concurrent caché, aucune réservation incompatible ou anomalie
bloquante. La devise d'origine n'intervient pas dans ces charges déjà en euros.

Le contrôle porte sur les populations complètes et pas seulement les candidats
retenus par une étape. Un concurrent sans BAP ne prouve pas un autre périmètre
et reste bloquant. Les Comptabilisé connus sont aussi pris en compte comme
consommateurs potentiels. Les capacités collectives sont toujours revérifiées.

`STRUCTURED_RULES` étend le garde existant `FuzzySafety` ; il n'existe pas de
second algorithme concurrent d'AUTO. `proposal_metadata()` émet une autorisation
préliminaire, l'export la borne aux vraies preuves v3 individuelles, puis Django
la revérifie. Sans inventaire Sage complet v3, aucune nouvelle AUTO de ces règles.
Les regroupements Sans libellé restent à examiner si l'affectation individuelle
n'est pas prouvée ; la règle n'est pas artificiellement renommée Exact.

## Deux recours finaux

### `MATCH_BAP` — Correspondance par BAP

Après la cascade historique, comparer le résiduel par projet/tiers/exercice/BAP,
sans libellé. Les pièces exclues et écritures déjà proposées sont retirées des
candidats nouveaux ; les preuves Comptabilisé/Confirmé protègent également les
écritures potentiellement consommées. Si une preuve source ne permet pas de
localiser les écritures consommées dans sa pièce/date, le recours ne les reprend pas.

Un ensemble équilibré au centime est décomposé en paires seulement si chaque
montant signé identifie une écriture unique et réciproquement. Des montants
répétés non discriminables produisent une proposition collective à examiner,
avec toutes ses preuves, sans autorisation AUTO. Aucun appariement par ordre.

L'équilibre **complet** et la bijection BAP sont revérifiés à l'export et à
l'import depuis les inventaires/sources de revue ; une simple étiquette BAP ou
une métadonnée AUTO falsifiée ne suffit pas. Un cache local de résultat par BAP
évite de sommer le même bloc pour chacune de ses lignes.

Le cas témoin utilise le projet réel de la demande **17GEF0C086** (zéro après
GEF), le tiers M81412 et le BAP BAPPJT260402077 :

| Atlas | Charges EUR | Sage retenu |
|---|---:|---|
| 1681313 — ERf Solde perdiem | 660,06 | CIF0126040938 · comptable 2 / analytique 1 |
| 1681314 — Frais reel mission | 644,85 | CIF0126040938 · comptable 3 / analytique 1 |

Total de chaque côté : **1 304,91 €** ; deux références Sage distinctes.

### `MATCH_INDIVIDUAL` — Correspondance individuelle

Pour les lignes encore sans proposition BAP, rechercher des écritures individuelles
par bloc puis montant signé, sans exiger l'équilibre du groupe Sage entier.
Un BAP connu impose la même référence. Un BAP Atlas absent permet seulement une
proposition manuelle de même projet/tiers/exercice/montant ; il n'est jamais
assimilé silencieusement à un BAP Sage connu et ne permet aucune AUTO.

Tous les concurrents sont conservés. Des Atlas de même bloc/montant partagent
une proposition manuelle plutôt qu'une répétition de toutes les preuves pour
chaque ligne. Les références précises vont dans les preuves JSONL v3 existantes.
Les contrôles de capacité peuvent laisser un reste Sage non expliqué : un match
individuel sûr n'affirme pas que le groupe entier est équilibré.

Les index triés et recherches dichotomiques évitent un produit Atlas × Sage.
Le recours sans BAP possède également un index par projet/tiers/exercice : il
ne parcourt pas toutes les références BAP pour chaque ligne. Les traces et la
synthèse du moteur exposent les deux nouvelles étapes, leurs rejets et leurs
résultats. Les chiffres de règles comptent des groupes, pas toujours des lignes.

## Comparaison mesurée sur le jeu témoin

`examples/matching_bap_fixture.py` génère six lignes Atlas, des sources fictives
et deux JSONL. Le témoin « avant » désactive les recours et l'activation nouvelle
de Sans libellé ; les autres règles et les données sont identiques.

| Mesure | Avant | Après |
|---|---:|---:|
| Lignes Atlas sources | 6 | 6 |
| Groupes Sans contrôle du libellé | 1 | 1 |
| Groupes BAP | 0 | 3 |
| Groupes individuels | 0 | 1 |
| Groupes Sans correspondance | 5 | 0 |
| Propositions totales | 6 | 5 |
| Lignes autorisées AUTO puis validées à l'import | 0 | 4 |
| Lignes sans AUTO | 6 | 2 |

Les trois groupes BAP après incluent deux paires uniques et un groupe de deux
Atlas à montants répétés, maintenu manuel. Le gain ne vient pas d'un choix
arbitraire des répétitions. Les règles fiables déjà proposées conservent leurs
identités et leur priorité.

Le test d'import mesure quatre contributions à références distinctes totalisant
**2 004,91 €**. Les totaux Sage sources sont identiques avant/après. Le cadrage
après import donne Atlas retenu **2 004,91 €**, Sage retenu **2 054,91 €**, écart
**-50,00 €** : le recours individuel conserve le reste Sage de 50 € au lieu de
le masquer. Les 400 € du BAP ambigu restent non confirmés. Aucune promesse de
gain de durée ou de taux d'AUTO sur la base complète.

## Matrice exigences → code → vérification

| Exigence | Code principal | Vérification |
|---|---|---|
| Préremplir, décocher, restaurer, préserver la saisie | manual-allocation.js, review_detail.html | browser_manual_allocation.py : 20 assertions DOM réelles |
| Somme signée exacte et champs non ambigus | multiple_review.selection_values, review.decide | BapDecisionTests.test_selection_prefills_before_required_field_validation_and_no_reuse ; test_decimal_multiselection_zero_negative_and_ambiguous_dates |
| POST français, montant/référence falsifiés | review_forms.py, review_views.py, service | test_post_tampered_amount_and_foreign_ref_leave_no_mutation |
| Pas de réutilisation, pièce partageable | multiple_review.py, contrôles existants | test_selection_prefills_before_required_field_validation_and_no_reuse ; test_import_real_new_rules_and_unique_allocations |
| Capacité non dépassée par sélection | apply_projection | test_selected_entries_cannot_exceed_piece_capacity ; MultipleTests.test_validate_button_cannot_override_selected_entry_capacity |
| AUTO Sans libellé, candidats concurrents | config, contrat, export, auto_validation | AutomaticTests.test_v3_fuzzy_and_amount_project_and_carry ; test_without_label_competitors_are_not_auto ; gardes communs de test_fuzzy_safety.py ; tests d'import réel du témoin |
| BAP unique de la demande | matching/residual.py, garde BAP | test_bap_bijection_and_individual_are_additive ; test_import_real_new_rules_and_unique_allocations |
| BAP répétitif et faux équilibre | residual.py, verify_bap_balance | témoin R1/R2 manuel ; test_bap_global_balance_is_rechecked_at_import |
| Individuel malgré groupe déséquilibré | residual.py | témoin I ; contrôle du cadrage à -50 € |
| BAP manquant, projet différent, exclusions | residual.py et garde partagé | test_missing_bap_is_manual_and_never_matches_another_project ; test_excluded_types_are_not_residual_candidates |
| Priorités et sources immuables | engine.py, réservations | test_existing_candidate_group_is_not_reused ; test_priority_sources_and_trace_are_preserved |
| Volumétrie sans matrice de preuves | index et regroupement du résiduel | test_repeated_unbalanced_amounts_do_not_repeat_all_proofs : 200 Atlas / 300 Sage, une proposition |
| Historique et cadrage conservés | import/contrôles/comptabilité existants | test_comparison_keeps_source_totals_and_historical_decisions ; suite comptable existante |
| Trace des étapes ignorées/exécutées | engine.py, trace.py, residual.py | test_matching_trace.py et tests de priorité/trace |

## Fichiers livrés

Créés :

- `reconciliation/matching/residual.py` : recours indexés et non destructifs.
- `examples/matching_bap_fixture.py` : jeu témoin, JSONL avant/après et métriques.
- `tests/test_matching_residual.py` : matching, export, priorités et volumétrie.
- `tests/browser_manual_allocation.py` : recette Chrome/Edge headless sans dépendance.
- `app-suivi-reconciliation/reconciliation/test_matching_bap_decision.py` : import,
  choix, sécurité, références et cadrage bout à bout.
- Le présent document.

Modifiés :

- `reconciliation/config.py` : règles AUTO activées.
- `reconciliation/matching/engine.py` : recours après les règles historiques.
- `reconciliation/matching/models.py` : codes et option témoin enable_residual.
- `reconciliation/matching/scoring.py` : indicateurs des deux nouvelles règles.
- `reconciliation/matching/trace.py` : étapes supplémentaires.
- `reconciliation/exporters/review.py` : gardes structurés et BAP.
- `reconciliation/auto_validation.py` : documentation des autorisations préliminaires.
- `reconciliation_contract/auto_validation.py` : codes partagés acceptés.
- `reconciliation_contract/fuzzy_safety.py` : garde commun étendu et équilibre BAP.
- `app-suivi-reconciliation/reconciliation/auto_validation.py` : revérification
  des règles structurées et de l'équilibre BAP à l'import.
- `app-suivi-reconciliation/reconciliation/multiple_review.py` : sommes et
  préremplissage serveur, anti-réutilisation et capacité des sélections.
- `app-suivi-reconciliation/reconciliation/presentation.py` : intitulés français.
- `app-suivi-reconciliation/reconciliation/review.py` : contrôles avant champs requis.
- `app-suivi-reconciliation/reconciliation/review_forms.py` : marqueurs auto,
  formats français et précision des charges sources.
- `app-suivi-reconciliation/reconciliation/review_views.py` : transmission des modes.
- `app-suivi-reconciliation/templates/reconciliation/review_detail.html` : libellé,
  conflits, retour au calcul et chargement statique respectant le déploiement.
- `app-suivi-reconciliation/static/js/manual-allocation.js` : interactions.
- `app-suivi-reconciliation/reconciliation/test_auto_validation.py` : règles étendues.
- `app-suivi-reconciliation/reconciliation/test_multiples.py` : capacité et preuves.
- `tests/test_matching_trace.py` : étapes détaillées supplémentaires.
- README et documentation des correctifs précédents : liens vers ce lot.

Toutes les définitions Python créées/modifiées et les fonctions JavaScript
non triviales sont documentées en français. Aucun fichier de migration.

## Commandes et recette de déploiement

Depuis la racine du dépôt, avec les chemins d'extractions réellement utilisés :

```powershell
uv run python -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --year 2026 --review-output "data/outputs/campagne_nouvelle.jsonl"
```

Depuis `app-suivi-reconciliation`, importer une **nouvelle campagne** :

```powershell
uv run python manage.py import_review_bundle "../data/outputs/campagne_nouvelle.jsonl"
```

Pour rejouer le témoin sans données métier et les tests :

```powershell
uv run python -m examples.matching_bap_fixture "data/outputs/recette_bap"
uv run python -m pytest -q
uv run python tests/browser_manual_allocation.py
cd app-suivi-reconciliation
uv run python manage.py test --noinput --verbosity 0
uv run python manage.py makemigrations --check --dry-run
```

Le préremplissage est utilisable dès déploiement de Django sur les campagnes
v3 dont les candidats existent déjà. Les nouveaux matches et AUTO nécessitent
le moteur modifié, un nouveau JSONL et une nouvelle campagne. Aucun recalcul
rétroactif, réécriture de décisions humaines ou `prepare_accounting` manuel.

Le navigateur de recette utilise un formulaire fictif et un profil temporaire,
sans base réelle. La validation visuelle desktop/mobile en déploiement reste à
faire ; les assertions DOM ne constituent pas une revue graphique. PostgreSQL
n'est pas disponible ici ; les tests spécifiques à cette base restent ignorés.
Les opérations ORM et les modèles conservent la compatibilité SQLite/PostgreSQL.

## Résultats de vérification

- Moteur : 265 tests réussis, 1 ignoré.
- Recette navigateur Chrome headless : 20 assertions réussies.
- Django : suite complète de 362 tests exécutés, succès, 3 ignorés ; test dédié
  supplémentaire Sans libellé/concurrents exécuté séparément après son ajout.
- `makemigrations --check --dry-run` : aucun changement détecté.
- Vérifications AST des définitions Python modifiées/créées : docstrings françaises présentes.
- `git diff --check` : aucune erreur d'espacement.

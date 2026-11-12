# Volet A — BAP visibles et tolérance résiduelle ciblée

## Périmètre livré

`MATCH_BAP` s'affiche désormais **N° BAP uniquement**. Son identifiant technique,
les anciennes campagnes et les règles financières restent inchangés. Les
justificatifs affichent **uniquement le BAP issu de Sage** ; le BAP Atlas reste
dans les données sources Atlas et dans le tableau des lignes Atlas du contrôle.

Les recours BAP et Individuel acceptent **un écart absolu source ≤ 0,05 €**.
Leurs autres garanties restent obligatoires. Aucune modification du volet B,
de Données insuffisantes, des exclusions, des signes ou des calculs du cadrage.

## Mini-cartographie avant / après

Avant :

- Le BAP Atlas était déjà transmis dans les propositions sous `N° BAP (SAGE)`
  et stocké dans `ReconciliationTransaction.sage_bap_number`, mais n'était pas
  conservé par l'inventaire complet pour toutes les lignes Comptabilisé.
- Sage portait déjà sa référence dans `Référence` dans les preuves, et dans
  `sage_inventory.data.attributes.Référence` dans l'inventaire signé.
- Le filtre Règle était trié alphabétiquement. Le moteur, lui, suivait une cascade.
- Le détail du contrôle montrait les lignes Atlas avec le libellé Atlas, sans
  tableau Sage paginé.
- Les seuils résiduels étaient plafonnés à 0,01 dans `residual.py`, puis revérifiés
  dans `proposal_metadata`, `FuzzySafety`, `automatic_blockers`,
  `apply_automatic_validations` et `exact_entry`.
- `inventory_rows` et les projections Django arrondissaient les charges Atlas
  au centime : elles ne suffisaient pas à vérifier une limite exacte telle que
  0,0501 €. L'export disposait encore des décimales originales.

Après : ordre partagé, références de chaque source affichées séparément, tableaux
Atlas/Sage indépendants, politique de seuil déclarée dans les nouveaux JSONL et
preuves de montants exacts photographiées séparément des projections comptables.

## Ordre effectif du filtre Règle

Toutes est fourni en premier par le composant multifilter. Les règles présentes
dans le périmètre de campagne suivent ensuite cet ordre :

1. Confirmé dans Atlas — `MATCH_CONFIRMED_ATLAS`
2. Correspondance exacte — `MATCH_EXACT`
3. Concordance des montants — `MATCH_AMOUNT`
4. Libellé proche — `MATCH_FUZZY_HIGH`
5. Libellé à vérifier — `MATCH_FUZZY_REVIEW`
6. Sans contrôle du libellé — `MATCH_WITHOUT_LABEL`
7. N° BAP uniquement — `MATCH_BAP`
8. Correspondance individuelle — `MATCH_INDIVIDUAL`
9. Plusieurs candidats — `AMBIGUOUS`
10. Sans correspondance — valeur d'interface `__NO_MATCH__`, code `UNMATCHED`.

`reconciliation_contract.matching_policy.RULE_ORDER` est partagé par le moteur
et la présentation Django : pas de copie indépendante de l'ordre. Les anciens
codes inconnus restent consultables avant les états transverses. Les choix
multiples, URLs, pagination et Réinitialiser conservent leur fonctionnement.

## Seuils avant / après

| Règle / contrôle | Avant | Après |
|---|---|---|
| Confirmé dans Atlas | Base Sage confirmée, vérifications existantes | Inchangé |
| Exact | 0,01 € | 0,01 € |
| Montant | 0,01 € | 0,01 € |
| Fuzzy High | 0,01 € | 0,01 € |
| Fuzzy Review | 0,01 € | 0,01 € |
| Sans libellé | 0,01 € | 0,01 € |
| BAP | 0,01 € sur paire et groupe | **0,05 € sur paire ET groupe**, sur sources exactes |
| Individuel | 0,01 € | **0,05 €** sur sources exactes |
| Preuve Sage vs total Sage déclaré | Contrôle existant à 0,01 € | Inchangé |
| Réservations et capacités des pièces | Seuil de contrôle existant | Inchangé |
| EQUILIBRE / ECART / INDETERMINE | Tolérance de campagne existante | Inchangé |
| CADRE / NON_CADRE / INSUFFISANT | Calcul de cadrage existant | Inchangé |
| Ancien JSONL sans politique spécifique | Comportement historique à 0,01 € | Repli historique à 0,01 € |

Le moteur résiduel travaille sur les charges originales décimales, pas sur leur
affichage au centime. La recherche prioritaire Exact/Montant/Fuzzy ne change pas.
Les anciennes protections de réservation d'écritures ne sont pas élargies.
Les services `collective_validation`, `exact_collective` et `validation_evidence`
restent inchangés : leurs parcours Confirmé/Exact ne sont pas ceux des deux recours.

Pour BAP, une bijection dont chaque paire diffère de 0,03 €, mais dont le total
diffère de 0,06 €, reste manuelle. Elle ne repasse pas automatiquement par le
recours Individuel pour contourner le plafond global. L'export et Django
revérifient cette barrière sur les index complets. Un véritable sous-ensemble
individuel reste possible lorsque le groupe entier ne constitue pas une bijection.

Projet, tiers, exercice, BAP requis, signe, identité complète, unicité bilatérale,
absence de concurrence et disponibilité Sage sont toujours vérifiés. Élargir
le voisinage monétaire peut également révéler plusieurs candidats et donc
empêcher une AUTO : aucun appariement au premier résultat n'est ajouté.

## Contrat JSONL v3 et conservation des décimales

Les nouveaux en-têtes déclarent un champ additif :

```json
"matching_tolerances": {"MATCH_BAP": "0.05", "MATCH_INDIVIDUAL": "0.05"}
```

Le champ existant `tolerance`, utilisé pour les contrôles comptables, ne change
pas. Les règles ou valeurs de seuil non reconnues sont refusées ; un en-tête
ne peut pas déclarer 0,05 pour Exact ou Fuzzy.

Les propositions portent aussi un dictionnaire additif :

```json
"matching_source_amounts": {"1615104": "362.2616"}
```

Chaque montant doit être égal à la charge projet source de la ligne Atlas du
JSONL. Ce dictionnaire est validé avant mutation de la projection, photographié
dans `CampaignGroup.data`, et inclus dans le contexte de fraîcheur des seuls
recours concernés. Une preuve absente ou contradictoire dans un nouveau contrat
déclaré annule l'import : pas de repli silencieux sur un montant arrondi.

Les modèles et inventaires financiers à deux décimales gardent leur précision
historique. Les tests de matching lisent la preuve exacte séparée. Pour les
autres règles, l'index historique est conservé ; l'index exact concerne les
seuls recours. Les décisions AUTO réservent toujours le montant réel de Sage,
sans modifier une charge source ou une capacité pour absorber un écart.

Les anciens JSONL sans ces métadonnées restent importables et gardent leurs
seuils/projections historiques. Aucun traitement rétroactif n'est fourni. Les
identifiants d'écriture Sage et signatures des données effectivement transmises
ne sont pas remplacés par un BAP ni recalculés à partir du montant affiché.

## Origine de chaque référence affichée

| Écran / champ | Colonne source → JSONL → stockage → rendu |
|---|---|
| Données sources : N° BAP Atlas | Atlas `N° BAP (SAGE)` → `proposal.atlas` → `ReconciliationTransaction.sage_bap_number` → fiche Atlas |
| Inventaire / tableau Atlas : N° BAP Atlas | Même colonne Atlas → nouveau champ optionnel dans `inventory.atlas` → `CampaignInventory.data.display_bap` → présentation |
| Ancien inventaire Atlas sans BAP | Si disponible : photographie `CampaignReview.source.sage_bap_number` de la même campagne ; sinon **—** |
| Justificatifs : N° BAP Sage | Sage `Référence` → `proposal.evidence[].rows[].Référence` → preuves de `ReviewGroup` / `CampaignGroup` → colonne Sage |
| Recherche manuelle : N° BAP Sage | Sage `Référence` → `sage_inventory.data.attributes.Référence` → `CampaignSageEntry.data` → résultat de recherche |
| Tableau Écritures Sage concernées | Même attribut Sage, limité à `campaign + project + control_key` → tableau Sage |

La configuration existante du moteur relie déjà `matching_reference` à
`Référence` côté Sage et à `N° BAP (SAGE)` côté Atlas. Le cas BAPPJT260402077
confirme cette correspondance fonctionnelle. Le détail de contrôle conserve
l'intitulé fidèle **N° de référence / BAP Sage**. Aucune valeur Sage absente
n'est remplacée par celle d'Atlas, le numéro de pièce ou un autre champ.

`display_bap` est strictement une métadonnée d'affichage : il ne modifie pas
les clés, les montants ou l'index historique de matching. Une compatibilité
ciblée l'écarte des comparaisons historiques de reprise des actions et de
témoins de doublons, pour que son ajout à un ancien inventaire ne fasse pas
perdre une correction. Tous les anciens champs métier restent vérifiés.
La concordance inventaire/proposition reste stricte quand les deux BAP sont
présents ; leur absence dans un ancien inventaire n'interdit pas son import.

## Tableaux du contrôle des montants

Le tableau Atlas conserve le lien sur l'identifiant, le statut et les charges
Sage issues d'Atlas. Il ajoute le BAP Atlas et utilise **Libellé Sage dans Atlas**,
jamais le libellé Atlas comme repli. Les champs absents affichent —.

Le tableau Sage présente les six colonnes demandées : date, pièce, tiers,
référence/BAP Sage, libellé et charges. Il sélectionne les écritures par la clé
du contrôle, y compris pour ODS/ODG, jamais par montant. Les anciennes preuves
de contrôle peuvent fournir une consultation de repli sans inventaire complet ;
leur référence inconnue reste —. Un état vide explicite est prévu.

Les deux tableaux ont des pages de 25 lignes : `page` pour Atlas, `sage_page`
pour Sage. Changer l'une préserve l'autre, le retour et les filtres. Les liens
portent les ancres `#atlas-lines` et `#sage-lines`. Les requêtes sont bornées,
sans chargement complet de la campagne ni requête par ligne affichée.
Les mêmes droits de campagne/projet s'appliquent ; une consultation ne sauvegarde
ni état de contrôle ni agrégat comptable.

Les références longues se replient et les tableaux défilent horizontalement sur
petit écran, sans suppression des colonnes financières. Les formats restent français.

## Fichiers modifiés / créés

Contrat et moteur :

- `reconciliation_contract/matching_policy.py` **créé** : ordre, seuils ciblés,
  validation des bases monétaires exactes.
- `reconciliation_contract/fuzzy_safety.py` : index exact résiduel, seuils
  explicites, équilibre global et garde contre le contournement individuel.
- `reconciliation/matching/models.py` : ordre partagé.
- `reconciliation/matching/residual.py` : recherches décimales à 0,05 et plafond global.
- `reconciliation/auto_validation.py` : seuil de la règle dans l'autorisation.
- `reconciliation/exporters/review.py` : déclaration du contrat, bases exactes,
  BAP optionnel de l'inventaire Atlas, contrôles d'export.

Django :

- `reconciliation/matching_evidence.py` **créé** : lecture sécurisée de la base exacte,
  cache local à l'objet, ancien repli.
- `reconciliation/campaigns.py` : mappage BAP de présentation, validation et
  photographie des bases exactes, fraîcheur des recours.
- `reconciliation/multiple_import.py` : validation de politique et compatibilité
  de la métadonnée BAP avec les preuves financières.
- `reconciliation/auto_validation.py`, `multiple_review.py` : vérifications AUTO
  au bon seuil, tout en réservant le montant de Sage.
- `reconciliation/business_carry.py` : compatibilité de reprise lors de l'ajout
  de la seule métadonnée d'affichage.
- `reconciliation/presentation.py` : libellé, ordre et provenance Atlas des BAP.
- `reconciliation/review_views.py`, `business_views.py`, `global_views.py` :
  mappages de présentation et pagination bornée des écritures du groupe.
- `reconciliation/templatetags/review_ui.py` : pagination à paramètre indépendant.
- Templates `review_detail.html`, `inventory_detail.html`,
  `global_control_detail.html`, composants `atlas_control_lines.html`,
  `inventory_source_identity.html`, `pagination.html`, et nouveau composant
  `sage_control_lines.html` : colonnes et tableaux.
- `static/css/workspace.css` : références longues, largeur et ancres.

Les chemins Django ci-dessus sont relatifs à `app-suivi-reconciliation`.

Recette et documentation :

- `examples/volet_a_fixture.py`, `tests/test_volet_a_tolerance.py`,
  `tests/browser_volet_a.py` **créés**.
- `app-suivi-reconciliation/reconciliation/test_volet_a.py` **créé**.
- Préparation des variantes synthétiques adaptée dans `test_business.py` et
  `test_validation_v2.py` pour réémettre leurs preuves exactes après mutation.
- Le présent document et liens depuis les guides existants.

**Aucune migration**, aucun changement de modèle ou de pipeline de staging.
Les fonctions/classes Python modifiées et les nouveaux helpers sont documentés
en français ; les fonctions de recette navigateur le sont également.

## Tests et recette

| Exigence | Vérification |
|---|---|
| Libellé BAP, ordre de cascade, code inchangé | `VoletATests.test_rule_labels_order_and_sage_bap_never_fall_back_to_atlas` |
| Aucun BAP Atlas dans les justificatifs Sage | Même test avec références volontairement distinctes et Sage absent |
| BAP/libellés des deux sources, groupe exact, consultation sans effet | `test_control_detail_source_labels_keys_and_read_only` |
| Recherche Sage et état vide | `test_search_shows_only_sage_reference_and_control_empty_state` |
| Pagination indépendante, droits et borne de requêtes | `test_control_tables_have_independent_bounded_pagination` ; contrôle 404 hors portefeuille |
| Seuil réel 0,0116 / 0,0500 / 0,0501 | `test_volet_a_tolerance.py` et `test_new_auto_is_consumed_with_exact_precision_and_old_controls` |
| Groupe BAP dont les petites différences dépassent 0,05 global | `test_complete_bap_drift_cannot_become_individual_auto` et cas D1/D2 à l'import |
| Politique/valeurs falsifiées, ancien repli | `test_policy_cannot_expand_other_rules_or_unknown_thresholds` ; `test_legacy_tolerance_and_forged_source_are_refused_safely` |
| Anciennes corrections conservées | `test_optional_display_bap_does_not_break_existing_correction_carry` |
| Autres règles, identités, réservations et cadrage | Suites existantes matching, auto-validation, décisions, contrôles et comptabilité |
| Grand/petit écran | `browser_volet_a.py`, vrais composants et CSS, SQL interdit : 9 + 11 assertions, captures inspectées |

Les tests utilisent seulement des sources synthétiques et des bases jetables.
Les captures de recette sont dans `benchmarks/volet_a_ui` (répertoire ignoré),
avec un viewport mobile réel de 390 px. Les fichiers métier et la base locale
de l'utilisateur n'ont été ni régénérés ni réimportés.

Résultats exécutés : **284 tests moteur réussis, 1 ignoré** ; **370 tests Django
exécutés, succès, 3 ignorés** ; **20 assertions d'affichage** (9 grand écran,
11 petit écran). `makemigrations --check --dry-run` ne détecte aucun changement.
Le contrôle AST confirme les docstrings françaises sur les définitions Python
créées/modifiées ; Ruff (règles F) et `git diff --check` passent.

PostgreSQL n'est pas disponible dans cet environnement :
les tests propres à ce backend ne sont pas exécutés ; les opérations ORM et les
modèles restent compatibles. Aucune statistique de gain sur la campagne réelle
n'est annoncée sans exécution autorisée.

## Procédure de déploiement et nouvelle campagne

Après déploiement de Django, les nouvelles présentations utilisent les références
déjà disponibles. Les anciens inventaires peuvent manquer du BAP Atlas pour les
Comptabilisé : — est alors attendu, sans réécriture historique.

La tolérance élargie nécessite le moteur modifié et un **nouveau JSONL / nouvelle
campagne**, avec les métadonnées et bases exactes. Après autorisation de cette
recette sur les véritables extractions, depuis la racine du dépôt :

```powershell
uv run python -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --year 2026 --review-output "data/outputs/campagne_recette_volet_a.jsonl"
```

Depuis `app-suivi-reconciliation` :

```powershell
uv run python manage.py import_review_bundle "../data/outputs/campagne_recette_volet_a.jsonl"
```

Vérifier un cas à 0,0116, les deux bornes 0,0500/0,0501, un BAP à plusieurs
lignes, un cas de cumul >0,05, un cas ambigu et une écriture déjà réservée.
Comparer ensuite les taux de propositions/AUTO par règle sur cette nouvelle
campagne ; les autres règles doivent conserver leurs priorités et seuils.
L'état de contrôle/cadrage reste calculé avec ses anciennes règles et peut donc
encore signaler un écart, même si un rapprochement résiduel est admissible.

Pour rejouer seulement les tests et la recette fictive :

```powershell
uv run python -m pytest -q
uv run python tests/browser_volet_a.py benchmarks/volet_a_ui
cd app-suivi-reconciliation
uv run python manage.py test --noinput --verbosity 0
uv run python manage.py makemigrations --check --dry-run
```

Il n'existe aucune commande de réévaluation des anciennes campagnes. Ne pas
réutiliser le nom d'une sortie métier à conserver lors d'une recette.

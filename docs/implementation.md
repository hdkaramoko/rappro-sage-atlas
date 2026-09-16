# Implémentation du rapprochement Atlas et Sage

Le [guide des contrôles et statuts](controles_et_statuts.md) présente la suite
des vérifications et le sens métier des décisions, règles et propositions BAP.

La restitution Excel est maintenant disponible : voir [le guide d'export et des
tentatives](export_excel.md). L'option `--output` produit les trois feuilles de
contrôle, sans modifier les sources. Les mentions d'export hors périmètre plus
bas décrivent le périmètre historique de l'étape 3, avant cette évolution.

Le préfiltrage Sage est activé par défaut (`MatchingConfig.prefilter_sage=True`).
Après préparation et avant agrégation, seules les lignes des blocs non vides
projet/tiers/BAP présents dans Atlas à rechercher sont conservées. Toutes les
lignes de chaque bloc restent présentes, même sans montant ou avec un libellé
différent. Les positions originales et la numérotation globale des groupes Sage
sont conservées. Les compteurs `FILTRE_STRUCTURE` du journal restent globaux.
`prefilter_sage=False` permet une comparaison avec l'ancien calcul intégral.

La synthèse expose `sage_rows_total`, `sage_rows_retained`,
`sage_rows_excluded_by_prefilter`, `sage_groups_total` et `sage_prefilter_applied`.
`sage_groups` et le catalogue `sage_candidates` décrivent les groupes retenus.
Sans recherche Atlas nécessaire, le préfiltrage n'est pas exécuté : les groupes
ne sont pas comptés et `sage_prefilter_applied` vaut faux. Le filtre ne porte
ni sur l'année, ni sur le libellé, ni sur le montant.

## Installation et exécution

Le projet utilise Python 3.12, pandas, openpyxl et RapidFuzz. pytest est une dépendance de
développement ; hatchling construit le paquet Python. `uv.lock` fixe les versions
résolues. Toutes les opérations d'environnement passent par uv.

```powershell
uv sync
uv run pytest
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv"
```

Pour reproduire strictement le verrou : `uv sync --locked`.
La CLI affiche des compteurs, jamais les DataFrames. Les logs français vont sur
stderr ; le résumé va sur stdout. UiPath peut consulter le code de sortie :
0 pour un traitement terminé (y compris avec ambiguïtés ou non rapprochés),
1 pour une erreur de chargement/transformation, 2 pour des arguments invalides.
Si Sage échoue après Atlas, le résumé Atlas peut déjà avoir été affiché : seul le
code 0 indique le succès des deux chargements.

```python
from reconciliation.loaders.atlas import load_atlas
from reconciliation.loaders.sage import load_sage

atlas_df = load_atlas("data/JDD.xlsx")
sage_df = load_sage("data/LISTPJT4.csv")
summary = atlas_df.attrs["load_summary"]
```

## Architecture et fichiers

```text
.gitignore
.python-version
pyproject.toml
uv.lock
README.md
reconciliation/
  __init__.py
  config.py
  main.py
  loaders/
    __init__.py
    common.py
    atlas.py
    sage.py
  transformations/
    __init__.py
    atlas.py
    sage.py
    common.py
    matching.py
  matching/
    __init__.py
    engine.py
    exact.py
    aggregated.py
    ambiguous.py
    fuzzy.py
    scoring.py
    models.py
    results.py
  history/
    __init__.py
    upsert.py
  exporters/
    __init__.py
    excel.py
tests/
  test_atlas_loader.py
  test_sage_loader.py
  test_main.py
  test_transformations.py
  matching_helpers.py
  test_matching_engine.py
  test_matching_exact.py
  test_matching_aggregated.py
  test_matching_fuzzy.py
  test_matching_ambiguous.py
docs/
  implementation.md
```

Ces fichiers sont les livrables créés ; le prompt d'origine est conservé.
`config.py` centralise les schémas et paramètres. `loaders/common.py` partage les
validations, conversions et compteurs. Les loaders lisent les sources sans les modifier.
`transformations` normalise les codes et références dans de nouvelles colonnes.
`matching` applique la cascade métier détaillée dans la section étape 3.
`history` et `exporters` restent des squelettes hors périmètre.

## Atlas

Un JDD peut dépasser la limite de lignes d'une feuille Excel. Chaque feuille est
inspectée dans l'ordre du classeur, sans hypothèse de nom ou de nombre. Les en-têtes
doivent être sur la première ligne. `Id` et `Code projet` sont obligatoires selon
le paramétrage actuel ; les autres colonnes restent optionnelles.

Une feuille sans les colonnes obligatoires est ignorée avec un avertissement. Une feuille vide ou ne
contenant que des en-têtes ne contribue pas aux données. Aucune feuille valide non
vide entraîne une `AtlasLoaderError`. Une feuille retenue avec un identifiant vide
fait échouer le chargement : elle n'est pas ignorée. Les valeurs de dates et nombres
non convertibles deviennent manquantes avec avertissement.
Les lignes entièrement vides sont écartées avant comptage.

Les feuilles sont concaténées une seule fois. Toutes les colonnes supplémentaires
sont conservées ; une colonne absente d'une feuille est complétée par des valeurs
manquantes. Après typage, `drop_duplicates(subset=["Id"], keep="first")` conserve
la première occurrence selon l'ordre des feuilles puis des lignes, même si les
autres valeurs diffèrent. Les Id ne sont pas normalisés.

## Sage

Un seul CSV est lu, correspondant à l'année fournie par UiPath ; aucune concaténation
d'années ni vérification métier de l'année n'est effectuée. Le minimum retenu est
`Projet`, `Numéro pièce` et `Date comptable`. Leur présence est validée ; leurs cellules vides sont
conservées en attendant de définir les règles métier.

Par défaut, le séparateur est détecté sur l'en-tête parmi `;` et `,`. L'encodage
est `utf-8-sig` (UTF-8 avec ou sans BOM) avec relecture en `cp1252` uniquement en
cas d'erreur de décodage. Un encodage explicitement différent désactive ce repli.
Les paramètres peuvent être définis dans `config.py` ou passés à la fonction :

```python
sage_df = load_sage("data/LISTPJT4.csv", separator=";", encoding="cp1252", decimal=",")
```

Les en-têtes dupliqués, colonnes essentielles absentes et erreurs du parseur sont
signalés. Un CSV avec seulement les en-têtes requis retourne un DataFrame vide.
La suppression des doublons utilise toutes les colonnes, y compris supplémentaires,
et conserve la première occurrence. Elle précède volontairement le typage pour ne
pas fusionner des lignes sources distinctes telles que `1,0` et `1,00`. Il s'agit
de l'égalité des cellules lues, pas de l'identité binaire des lignes du CSV.

## Typage et valeurs manquantes

Les données sont initialement lues en chaînes pour préserver les identifiants,
codes, numéros de pièce et BAP. Les groupes explicités dans `config.py` couvrent
toutes les colonnes du prompt : `string` pour le texte, `datetime64[ns]` pour les
dates, `Float64` nullable pour les nombres et `Int64` nullable pour `Année` Atlas.
`Ecart vérifié` est considéré comme texte ; `Numéro d'import` comme identifiant.
Les colonnes supplémentaires restent textuelles et ne sont pas supprimées.

Les cellules vides deviennent `pd.NA` ou `NaT`. Les littéraux `NA`, `NULL`, etc.
restent des chaînes. Les blancs des colonnes numériques et dates sont traités
comme manquants, sans nettoyage des colonnes textuelles.
Les dates acceptent les représentations ISO et jour/mois/année (`dayfirst=True`).
Les montants acceptent le point, ou la virgule avec `decimal=","`, et les espaces
ordinaires/insécables de milliers. Les formats mélangeant points de milliers et
virgules décimales ne sont pas pris en charge. Les montants sont des flottants,
sans arrondi métier à cette étape.

Les types sont effectivement appliqués aux colonnes, pas simplement contrôlés.
`errors="coerce"` convertit les dates et nombres reconnus et remplace les valeurs
non convertibles par `NaT` ou `pd.NA`. Une année fractionnaire ou hors plage Int64
devient manquante sans troncature ; les nombres infinis deviennent aussi manquants.
Un avertissement indique le nombre de valeurs concernées par colonne, disponible
également dans `DataFrame.attrs["typing_issues"]`. Les cellules déjà vides ne sont
pas comptées comme anomalies. Les valeurs invalides d'origine ne sont pas conservées
dans la DataFrame typée ; le fichier source reste inchangé. La conservation des
sources par les transformations porte sur la DataFrame reçue du loader.
Les erreurs de structure, fichiers illisibles et Id Atlas vides restent bloquantes.
Les exceptions d'origine sont conservées par chaînage. Les loaders ne configurent
pas le logging global ; cette responsabilité appartient à la CLI ou à l'appelant.
Les compteurs sont disponibles dans `DataFrame.attrs["load_summary"]` : `rows_read`,
`duplicates_removed`, `rows_final`, `valid_sheets` (Atlas seulement, sinon `None`).

## Performance et points à confirmer

Le typage et la déduplication utilisent des opérations vectorisées par colonne,
sans `iterrows`. L'inspection des en-têtes évite de charger les feuilles parasites.
La concaténation n'est réalisée qu'une fois et aucune copie complète supplémentaire
n'est demandée pour les conversions. Le chargement reste en mémoire : plusieurs
millions de lignes nécessitent une machine dimensionnée et une mesure sur les vrais
fichiers. Aucun benchmark sur données métier n'a été effectué.

À confirmer avec les extractions réelles : position et orthographe des en-têtes,
colonnes minimales Sage, format des dates, encodage, conventions numériques et
politique des doublons Atlas conflictuels. Une feuille parasite contenant `Id`
et `Code projet` peut être retenue avec le schéma minimal actuel.
Les zéros initiaux sont préservés lorsque la cellule Excel stocke réellement du
texte. Un format d'affichage Excel `00000` appliqué au nombre 123 n'est pas une
chaîne `00123` et ne peut pas être restauré par cette lecture. Les dates Excel
doivent être des cellules dates reconnues par openpyxl ou des chaînes de dates ;
les numéros de série non formatés ne sont pas interprétés comme dates Excel.

## Validation

Les tests créent leurs propres fichiers temporaires : multi-feuilles, feuille vide
et parasite, déduplication, typage nullable, conservation des identifiants et des
colonnes supplémentaires, formats CSV et encodages, fichiers absents ou invalides,
erreurs de structure et typage, CLI nominale et en échec.
Exécuter `uv run pytest` pour obtenir le résultat sur l'environnement courant.

## Étape 2 : transformations

Le flux est désormais : fichier → loader → DataFrame typée → transformation →
DataFrame normalisée → matching. Le loader applique le schéma source et les
contrôles de lecture. La transformation reçoit uniquement une DataFrame déjà
chargée ; elle ne connaît aucun chemin et ne réalise aucune lecture de fichier.

Une colonne canonique donne un nom commun à une information présente dans l'une
ou l'autre extraction. Elle ne constitue ni une clé de rapprochement ni une preuve
d'équivalence métier. Les correspondances sont centralisées dans `config.py` :

| Colonne canonique | Atlas | Sage |
| --- | --- | --- |
| `project_code` | Code projet | Projet |
| `reference` | Non défini | Référence |
| `accounting_document` | N° pièce SAGE | Numéro pièce |
| `amount` | Non défini | Non défini |
| `currency` | Devise | Devise |
| `accounting_date` | Date comptable | Date comptable |
| `label` | Libellé ATLAS | Libellé pièce |
| `third_party` | Nom du tiers | Nom du Tiers |
| `source` | Constante ATLAS | Constante SAGE |

Les montants restent en `Float64` nullable mais entièrement manquants tant que
leur provenance n'est pas validée. La référence Atlas reste en `string` nullable
manquante. Il n'y a aucun repli automatique entre BAP, référence et document.
Les champs absents sont créés avec le type attendu et des valeurs manquantes.

Les champs textuels canoniques perdent leurs espaces de bord ; les espaces
insécables ordinaires et fins sont remplacés par des espaces ordinaires ; les
chaînes devenues vides deviennent `pd.NA`. Les identifiants (`project_code`,
`reference`, `accounting_document`, `currency`) passent en majuscules. La casse
des libellés et noms de tiers est conservée. Les zéros initiaux, accents, tirets,
barres obliques, points et espaces internes sont conservés. Aucune suppression
généralisée de caractères, conversion de devise, normalisation forte de projet,
agrégation, arrondi ou déduplication supplémentaire n'est effectuée.

Une copie de la DataFrame est nécessaire pour protéger l'entrée des modifications.
Toutes les colonnes sources, l'ordre, l'index (même dupliqué), le nombre de lignes
et les attributs de chargement sont conservés. Le traitement est vectorisé par
colonne. Une entrée vide produit le schéma canonique vide correctement typé.
Si un nom canonique existe déjà, la transformation lève `TransformationError`
pour éviter de remplacer une colonne source : les fonctions attendent les données
brutes du loader et ne sont pas destinées à être appliquées deux fois de suite.

```python
from reconciliation.loaders.atlas import load_atlas
from reconciliation.loaders.sage import load_sage
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage

atlas_raw = load_atlas("data/JDD.xlsx")
sage_raw = load_sage("data/LISTPJT4.csv")
atlas = transform_atlas(atlas_raw)
sage = transform_sage(sage_raw)
```

`attrs["transformation_summary"]` contient `rows_transformed` et
`missing_project_codes`. La CLI affiche ces deux compteurs après les compteurs
de chargement. Les transformations ne filtrent pas les codes projet manquants.
Les compteurs `typing_issues` reflètent les conversions effectuées : avant
déduplication pour Atlas et après déduplication technique pour Sage.

### Hypothèses historiques de l'étape 2

L'étape 3 ci-dessous résout les choix de montants et de référence pour le moteur.
Le contrat public des transformations de l'étape 2 reste inchangé, notamment les
colonnes `amount` et `reference` Atlas non renseignées. Une projection métier
distincte est préparée par `transformations/matching.py` à l'entrée du moteur.

Le prompt fourni passe de la section 5 à la section 25 ; aucune règle absente n'a
été reconstituée arbitrairement. Les correspondances descriptives ci-dessus sont
provisoires. Les décisions suivantes restent nécessaires avant le matching :

1. Quelle colonne Atlas représente le montant à rapprocher et dans quelle devise ?
2. Quelle colonne Sage doit alimenter `amount` ?
3. Quelle référence Atlas doit être comparée à quelle référence Sage ?
4. Faut-il une normalisation plus forte du code projet ?
5. Quels séparateurs éventuels retirer des références ?
6. Quel rôle donner à `N° BAP (Atlas)` ?
7. Quel rôle donner à `N° BAP (SAGE)` ?
8. `N° pièce SAGE` dans Atlas est-il une donnée source ou un enrichissement historique ?

Les deux colonnes BAP restent intégralement conservées comme colonnes sources.
Le mapping de `accounting_document` Atlas reprend la pièce disponible, sans
conclure à son origine ni à sa fiabilité pour le futur rapprochement.

### Fichiers de cette itération et résultat

Créés : `reconciliation/transformations/common.py`, `tests/test_transformations.py`.

Modifiés : `reconciliation/config.py`, `reconciliation/loaders/common.py`,
`reconciliation/loaders/atlas.py`, les trois fichiers existants de `transformations/`,
`reconciliation/main.py`, les trois fichiers de tests existants, `README.md` et
`docs/implementation.md`. Aucune dépendance ajoutée ; `uv.lock` est conservé.

Les scénarios existants sont conservés ; leurs jeux de données respectent les
colonnes obligatoires actuelles. Les attentes sur les valeurs non convertibles
vérifient maintenant la conversion tolérante et ses compteurs au lieu d'une erreur.
Les nouveaux tests vérifient les valeurs et types canoniques, les champs absents,
les entrées vides, la conservation des sources et des index, les collisions de
noms, ainsi que le flux loader → transformation et le résumé CLI.

Validation de l'étape 2 : `uv run pytest` — **34 tests réussis**, Python 3.12.0.
La validation utilise des données synthétiques, sans test sur extraction métier réelle.

## Étape 3 : moteur de rapprochement

### Utilisation

```python
from reconciliation.loaders.atlas import load_atlas
from reconciliation.loaders.sage import load_sage
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage
from reconciliation.matching import MatchingConfig, match_reconciliations, summarize_matching

atlas = transform_atlas(load_atlas("data/JDD.xlsx"))
sage = transform_sage(load_sage("data/LISTPJT4.csv"))
result = match_reconciliations(atlas, sage)
print(summarize_matching(result))
to_review = result.loc[result["requires_review"]]
```

L'API attend des DataFrames déjà transformées, conserve leurs colonnes, valeurs,
index et attributs, et renvoie un **DataFrame indépendant**. Une ligne de résultat
représente soit une preuve Atlas individuelle, soit un groupe Atlas nécessitant
une recherche. Ce n'est donc pas une sortie ligne à ligne des extractions.
Seules les lignes au statut `Envoyé SAGE` sont retenues. Les espaces de bord et
insécables sont normalisés par la couche transformations ; la casse du statut
est conservée. Un statut absent ou différent exclut la ligne ; les compteurs
de population rendent ces exclusions visibles dans les attributs du résultat.

```powershell
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv"
```

La CLI conserve les résumés de chargement/transformation et ajoute les compteurs
de rapprochement. Aucun détail métier n'est logué et aucun fichier métier n'est
écrit. Les seuils personnalisés sont accessibles par l'API Python.

### Préparation et clés

`transformations/matching.py` réutilise `project_code`, `label`,
`accounting_document`, `accounting_date` et `reference` Sage déjà normalisés.
Elle projette les champs suivants selon `MATCHING_SOURCE_COLUMNS` dans `config.py` :

| Champ métier | Atlas | Sage |
| --- | --- | --- |
| `matching_reference` | N° BAP (SAGE) | `reference`, issu de Référence |
| `third_party_code` | Code tiers SAGE | Code Tiers - Tiers doc Orig |
| `matching_amount` | Total charges projet (€) | Charges (Dépenses) |
| `source_status` | Statut BAP | Sans objet |
| `confirmed_amount` | Total charges SAGE (€) | Sans objet |

Les codes tiers et BAP passent en majuscules avec la même normalisation que
les identifiants de l'étape 2. Le nom du tiers n'est pas un code tiers.
Le BAP Atlas n'est jamais substitué au BAP Sage. L'en-tête de pièce Atlas attendu
par le loader est **`N° pièce SAGE`** (p minuscule), comme dans le mapping existant.
Les champs optionnels absents deviennent manquants. Le matching ne réalise
aucun nettoyage de texte ni conversion monétaire supplémentaire.

Les groupes utilisent la clé complète `project_code`, `label`, `third_party_code`,
`matching_reference` (`MATCHING_FULL_KEY`). La cardinalité compte toutes les
lignes après déduplication technique des loaders. Elle ne prouve pas une
correspondance individuelle entre les lignes de deux groupes.
Les sommes sont signées, sans arrondi métier. Zéro et montants négatifs sont
admis ; une seule valeur manquante invalide le montant entier de son groupe.
On n'utilise jamais une somme partielle pour valider un rapprochement.

Un projet, tiers ou BAP manquant interdit toutes les recherches, même si le même
champ manque dans Sage. Un libellé manquant interdit le strict et le fuzzy,
mais autorise le fallback sans libellé. Les groupes incomplets restent visibles
dans les résultats. Les charges Sage sont supposées comparables au montant
projet Atlas en euros, conformément au prompt : aucune conversion de devise.

### Cascade de règles

```text
Atlas Envoyé SAGE
  → pièce + date + montant Sage présents dans Atlas ? MATCH_CONFIRMED_ATLAS
  → agrégation par clé complète des lignes restantes et de Sage
  → clé complète + montant + même cardinalité ? MATCH_EXACT
  → clé complète + montant + cardinalité différente ? MATCH_AMOUNT
  → bloc structuré + montant + libellé similaire ? MATCH_FUZZY_HIGH / REVIEW
  → bloc structuré + montant, sans libellé ? MATCH_WITHOUT_LABEL
  → aucun candidat retenu : UNMATCHED
  → plusieurs candidats / preuves incompatibles / candidat partagé : AMBIGUOUS
```

| Règle | Confiance par défaut | Revue | Statut cible par défaut |
| --- | --- | --- | --- |
| MATCH_CONFIRMED_ATLAS | 1,00 | Non | Comptabilisé |
| MATCH_EXACT | 1,00 | Non si preuves complètes | Comptabilisé si preuves complètes |
| MATCH_AMOUNT | 0,90 | Oui | Aucun |
| MATCH_FUZZY_HIGH | Similarité | Oui | Aucun |
| MATCH_FUZZY_REVIEW | Similarité | Oui | Aucun |
| MATCH_WITHOUT_LABEL | 0,70 | Oui | Aucun |
| AMBIGUOUS | Non définie | Oui | Aucun |
| UNMATCHED | 0,00 | Oui | Aucun |

La preuve Atlas est prioritaire, même si son montant diffère du montant projet :
le niveau 0 du prompt exige la présence des trois champs, sans comparaison.
Zéro est un montant renseigné. Ce niveau ne recherche ni ne réserve de ligne
Sage ; `sage_row_count` reste absent et l'enrichissement provient d'Atlas.

Les autres règles s'appliquent dans l'ordre par groupe. La première qui retient
des candidats arrête la cascade, y compris si elle révèle une ambiguïté.
L'ordre est explicite dans `engine.py` ; les clés sont centralisées dans
`config.py` et les règles détaillées isolées dans leurs modules.

### Tolérance et fuzzy

`abs(atlas_amount - sage_amount) <= amount_tolerance`, avec 0,01 par défaut.
Une marge absolue de 1e-9 à la frontière positive absorbe les résidus binaires
des sommes pandas ; elle n'est pas proportionnelle aux montants. Avec une
tolérance nulle, aucune marge n'est ajoutée. `amount_difference` conserve
Atlas moins Sage et n'est pas arrondi.

Le fuzzy reçoit uniquement les groupes ayant **même projet, code tiers et BAP**
(`MATCHING_BLOCK_KEY`) et un montant compatible. RapidFuzz `token_set_ratio`
est le défaut : il tolère les permutations de mots. `ratio` reste configurable
et testé. Les textes canoniques sont transmis sans nouveau nettoyage ; la
casse, les accents et les séparateurs restent significatifs.

Un score ≥ 0,95 donne `MATCH_FUZZY_HIGH` ; un score ≥ 0,85 et < 0,95 donne
`MATCH_FUZZY_REVIEW`. Un score inférieur peut encore conduire au fallback
sans libellé, si activé. Les libellés absents ne sont jamais des preuves fuzzy.
Tous les candidats dépassant le seuil de revue sont conservés : même si l'un
obtient un meilleur score, plusieurs candidats plausibles rendent le cas ambigu.

`token_set_ratio` peut donner 1,00 lorsqu'un libellé est inclus dans un autre et
ignore la répétition des mots. Il ne valide pas la sémantique d'une facture.
Les règles **MATCH_AMOUNT, MATCH_FUZZY_HIGH, MATCH_FUZZY_REVIEW et
MATCH_WITHOUT_LABEL restent expérimentales**, à calibrer sur des cas métier
validés. Les confiances sont des indicateurs métier, jamais des probabilités
statistiques. Même un fuzzy à 1,00 demande une revue par défaut.

### Configuration

`MatchingConfig` est une dataclass immuable, validée à la construction : tolérance
finie et non négative, scores dans [0, 1], seuil de revue ≤ seuil élevé.
Ses défauts reprennent les constantes de `config.py`.

```python
options = MatchingConfig(
    amount_tolerance=0.01,
    fuzzy_high_threshold=0.95,
    fuzzy_review_threshold=0.85,
    fuzzy_method="token_set_ratio",  # ou "ratio"
    enable_fuzzy=True,
    enable_without_label=True,
    amount_confidence=0.90,
    without_label_confidence=0.70,
    auto_account_rules=frozenset(),
)
result = match_reconciliations(atlas, sage, options)
```

Pour proposer explicitement `Comptabilisé` sur un match montant, utiliser
`auto_account_rules=frozenset({"MATCH_AMOUNT"})`. Seules les quatre règles
expérimentales sont autorisables. `requires_review` reste vrai pour signaler
leur nature. Cette option ne contourne jamais une ambiguïté ou des pièces/dates
incomplètes et n'écrit rien dans Atlas.

### Ambiguïtés et qualité des preuves

Les pièces et dates distinctes d'un groupe Sage sont conservées sous forme de
tuples. Plusieurs pièces **ou** dates distinctes produisent `AMBIGUOUS`, même
sur une clé exacte. Aucune valeur scalaire n'est sélectionnée dans ce cas.
Une seule valeur distincte mais des lignes sans pièce/date donne un match
avec revue et sans statut cible : les preuves ne sont pas complètes.

Plusieurs candidats retenus par la règle produisent `AMBIGUOUS`. Le résultat
conserve `candidate_ids`, `candidate_count` et, pour le fuzzy, les couples
`(identifiant, score)` dans `candidate_scores`. Le catalogue
`result.attrs["sage_candidates"]` permet de retrouver les lignes, clés, montants,
pièces et dates de chaque candidat, y compris pour un résultat à plusieurs candidats.

Enfin, si plusieurs groupes Atlas revendiquent le même candidat Sage, tous
deviennent ambigus. Ce contrôle inclut les candidats de résultats déjà ambigus
et ne dépend pas de l'ordre d'Atlas. Par prudence, il peut déclasser un match
exact lorsqu'un autre groupe revendique le même Sage ; aucun arbitrage global
automatique n'est effectué. Les preuves Atlas du niveau 0 ne participent pas
à cette réservation, conformément à l'absence de recherche Sage à ce niveau.

### Schéma de sortie et diagnostic

`MatchResult` définit les colonnes ; le DataFrame les conserve même vide.

| Champs | Sens |
| --- | --- |
| `match_status`, `match_rule` | MATCHED / AMBIGUOUS / UNMATCHED et règle retenue |
| `confidence`, `label_similarity`, `requires_review` | Indicateurs et revue nécessaire |
| `source_status`, `target_status` | Statut Atlas normalisé et proposition, jamais une écriture |
| `atlas_group_id`, `atlas_source_ids`, `atlas_source_positions` | Groupe, Id Atlas et positions d'origine |
| `atlas_row_count`, `sage_row_count`, `cardinality_match` | Cardinalités et égalité éventuelle |
| `atlas_amount`, `sage_amount`, `amount_difference` | Totaux du groupe et différence signée |
| `sage_group_id`, `sage_source_ids` | Groupe Sage et positions des lignes sources |
| `sage_document_number`, `sage_accounting_date` | Valeurs scalaires lorsqu'elles sont uniques |
| `sage_document_numbers`, `sage_accounting_dates` | Toutes les valeurs distinctes |
| `candidate_count`, `candidate_ids`, `candidate_scores` | Candidats retenus par la règle |
| `reason` | Motif de diagnostic ci-dessous |

Les positions sont base zéro dans la DataFrame reçue, après déduplication loader,
et ne désignent pas directement des numéros de ligne Excel/CSV. Les identifiants
de groupes sont locaux à l'appel et peuvent changer avec l'ordre de l'extraction.
Un `Id` Atlas absent est remplacé par sa position ; les positions sont conservées
en complément des Id pour gérer aussi les index et identifiants dupliqués.

Les motifs sont `ATLAS_EVIDENCE_PRESENT`, `UNIQUE_CANDIDATE`,
`INCOMPLETE_STRUCTURED_KEY`, `INCOMPLETE_AMOUNT`, `NO_CANDIDATE`,
`INCOMPLETE_SAGE_EVIDENCE`, `INCOMPATIBLE_SAGE_EVIDENCE`, `MULTIPLE_CANDIDATES`
et `SAGE_CANDIDATE_SHARED`. Le dernier peut remplacer un motif précédent lors du
contrôle de concurrence. Les candidats et preuves restent disponibles.

`summarize_matching(result)` et `attrs["matching_summary"]` donnent les huit
compteurs par règle, zéros inclus. Ils comptent des résultats, pas des lignes
sources. `attrs["population_summary"]` contient `atlas_rows_total`,
`atlas_rows_selected`, `atlas_rows_excluded`, `atlas_rows_confirmed`, `sage_groups`.
Si aucune recherche n'est nécessaire, Sage n'est pas agrégé et son compteur vaut 0.

### Performance et limites

La sélection et les sommes/comptages utilisent pandas `groupby`. Les tuples de
provenance et de preuves sont collectés par groupe. L'orchestration parcourt les
agrégats, sans `iterrows()` sur les lignes sources. Un index Sage par bloc
structuré, trié sur le montant, limite les candidats par recherche dichotomique.
Aucune matrice globale Atlas × Sage n'est calculée.

Le traitement et le catalogue de provenance restent en mémoire. Un bloc contenant
beaucoup de libellés différents au même montant peut encore entraîner beaucoup
de comparaisons ; aucune troncature arbitraire des candidats n'est appliquée.
La capacité à traiter des millions de lignes doit être mesurée sur les vrais
fichiers et la machine cible. Aucun benchmark de production n'est revendiqué.
Le moteur ne cherche pas de sous-ensembles de lignes ni de regroupements nouveaux
sans libellé : le fallback compare les groupes de la clé complète déjà construits.

### Fichiers et validation de cette itération

Créés : `transformations/matching.py`, `matching/models.py`, `matching/fuzzy.py`,
`matching/scoring.py`, `matching/results.py` sous `reconciliation/`, ainsi que
`tests/matching_helpers.py` et les cinq fichiers `tests/test_matching_*.py`.

Modifiés : `reconciliation/config.py`, `reconciliation/main.py`, les cinq fichiers
préexistants de `reconciliation/matching/`, `pyproject.toml`, `uv.lock`, `README.md`
et cette documentation. Les loaders, les transformations de l'étape 2 et leurs
tests sont conservés.

Validation du 9 septembre 2026 : **`uv run pytest` — 78 tests réussis**,
dont 34 préexistants et 44 nouveaux. Les tests couvrent les dix scénarios du prompt,
les seuils fuzzy, les blocs exclus, les montants partiels, les entrées vides,
les clés manquantes, les montants nuls/négatifs, les preuves incomplètes, les
concurrences entre groupes, la configuration, les sources intactes et la CLI
avec de vrais fichiers temporaires Excel/CSV. Données synthétiques uniquement.

L'historisation, l'upsert, l'export Excel métier et les écritures automatiques
dans les systèmes sources restent hors périmètre de cette étape.

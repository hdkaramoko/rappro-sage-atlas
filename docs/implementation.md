# Implémentation des loaders Atlas et Sage

## Installation et exécution

Le projet utilise Python 3.12, pandas et openpyxl. pytest est une dépendance de
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
0 pour un succès, 1 pour une erreur de chargement, 2 pour des arguments invalides.
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
  matching/
    __init__.py
    engine.py
    exact.py
    aggregated.py
    ambiguous.py
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
docs/
  implementation.md
```

Ces fichiers sont les livrables créés ; le prompt d'origine est conservé.
`config.py` centralise les schémas et paramètres. `loaders/common.py` partage les
validations, conversions et compteurs. Les loaders lisent les sources sans les modifier.
`transformations` normalise les codes et références dans de nouvelles colonnes.
Les autres sous-packages sont des squelettes documentés : `matching` accueillera les règles exactes, agrégées
et les ambiguïtés ; `history`, l'historisation ; `exporters`, les exports métier.
Aucune règle de rapprochement ni clé métier Sage définitive n'est introduite.

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
DataFrame normalisée → futur matching. Le loader applique le schéma source et les
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

### Hypothèses et règles restant à confirmer

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

Dernière exécution : `uv run pytest` — **34 tests réussis**, Python 3.12.0.
La validation utilise des données synthétiques, sans test sur extraction métier réelle.

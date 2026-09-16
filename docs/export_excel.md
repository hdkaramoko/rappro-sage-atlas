# Restitution Excel et journal des tentatives

Pour interpréter les colonnes de décision, consulter le
[guide des contrôles et statuts](controles_et_statuts.md), qui décrit l'ordre
des vérifications et distingue statut BAP, résultat du matching et règle retenue.

## Lancer un rapprochement et obtenir le classeur

```powershell
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv" --output "output/rapprochement.xlsx"
```

Le répertoire de sortie est créé si nécessaire. Un classeur de sortie existant
est remplacé seulement après génération réussie. La CLI refuse une sortie qui
désigne l'un des fichiers sources. Sans `--output`, le fonctionnement précédent
est conservé et la collecte détaillée des tentatives est désactivée.
Une erreur d'export donne un code de sortie 1 (par exemple fichier ouvert dans Excel).

### Journal compact sur disque (défaut CLI)

Avec `--output output/rapprochement.xlsx`, les tentatives sont désormais écrites
progressivement dans `output/rapprochement.tentatives.jsonl`. L'export Excel relit
ce fichier ligne par ligne : il ne reconstruit pas tout le journal en mémoire.
Ce fichier est conservé pour permettre un audit même sans rouvrir Excel.

```powershell
uv run python -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --output "output/rapprochement.xlsx"
# Journal seul, sans produire l'énorme classeur :
uv run python -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --trace "output/tentatives.jsonl"
```

`--trace-mode compact` est le défaut. Il rassemble les étapes ignorées dans une
ligne `ETAPES_NON_EXECUTEES`, avec leurs noms, et résume les rejets non fuzzy par
règle. Tous les candidats retenus, tous les scores fuzzy calculés (même rejetés),
les compteurs de filtrage et la décision finale restent présents. Une preuve
Atlas produit trois lignes au lieu de huit. `--trace-mode detailed` restaure
le détail précédent, tout en bénéficiant de l'écriture sur disque.

L'écriture utilise un fichier temporaire `.jsonl.part`, vidé vers le système
de fichiers tous les 1 000 événements. Un marqueur final et un identifiant
d'exécution permettent de détecter un journal incomplet ou remplacé. Le fichier
définitif n'est remplacé qu'à la fin d'un matching réussi. Une exception normale
supprime le temporaire ; un arrêt brutal du processus peut laisser un `.part`,
qui ne doit pas être utilisé comme journal complet. Il n'y a pas de reprise
automatique du calcul après interruption.

Un exemple entièrement fictif, couvrant exact, montant, fuzzy, ambigu, non trouvé,
hors périmètre et preuve Atlas, est disponible :

```powershell
uv run python -m examples.demo_export
```

Il crée `data/exemple_rapprochement.xlsx` sans lire de fichier métier.

## Résultats

Une ligne par ligne Atlas **après déduplication par le loader**, dans l'ordre de
l'extraction chargée. Les champs demandés sont les 19 premières colonnes :

```text
Id ; Code projet ; Libellé projet ; Année ; Activité ; Code ligne budgétaire ;
Libellé ligne budgétaire ; Libellé ATLAS ; Nature de dépense (ATLAS) ;
Code tiers SAGE ; Nom du tiers ; N° BAP (SAGE) ; Statut BAP ; Lieu de paiement ;
Moyen de paiement ; Date comptable ; N° pièce SAGE ; Total charges projet (€) ;
Total charges SAGE (€)
```

« Canonique » désigne ici le schéma de restitution : intitulés harmonisés et
ordre fixe. Les valeurs sont celles reçues du loader, et ne sont pas remplacées
par les valeurs proposées ou les clés normalisées de comparaison. L'alias source
`Libellé ligne budgetaire` est accepté. Si les deux variantes existent et se
contredisent, l'export échoue explicitement. Les champs absents restent vides.

Les colonnes suivantes indiquent le statut, la règle, la revue, les scores, les
groupes, les cardinalités, les montants agrégés et l'écart, les pièces/dates
proposées, les candidats et le motif. Les pièces/dates multiples sont conservées
en listes JSON ; aucun choix arbitraire n'est fait pour les résumer.

Les lignes hors population portent `HORS_PERIMETRE`, sans proposition ni demande
de revue. Les autres statuts sont `MATCHED`, `AMBIGUOUS` et `UNMATCHED`.
Un `MATCHED` expérimental conserve `Revue nécessaire = VRAI`.

**Les montants du groupe sont répétés sur chacune de ses lignes Atlas et ne
doivent pas être additionnés.** Leurs titres portent « non additionnable ».
Le moteur ne répartit pas artificiellement le montant Sage sur les lignes Atlas.
Les champs originaux `Total charges SAGE (€)`, `N° pièce SAGE`, `Date comptable`
et `Statut BAP` sont séparés des propositions. Pour une preuve Atlas, la valeur
Sage proposée provient de la preuve déjà présente dans Atlas.

Le redéploiement utilise les positions Atlas, pas les Id ni l'index pandas ; il
reste correct avec des index dupliqués. Les positions sont base zéro après
chargement, et ne sont pas les numéros de ligne du fichier physique.

## Tentatives

Le journal est collecté pendant le matching. Il ne reconstitue pas un scénario
à partir de la seule décision finale. Il comporte :

- la vérification de preuve Atlas ;
- les compteurs avant/après le filtre projet/tiers/BAP, puis le filtre montant ;
- les candidats examinés par les règles exactes, montant, fuzzy et sans libellé ;
- les étapes `NON_EXECUTE`, notamment lorsqu'une règle précédente a arrêté la
  cascade ou lorsqu'une option est désactivée ;
- une `DECISION_FINALE` par résultat, après contrôle des candidats partagés.

Chaque tentative détaillée contient les Id du groupe Atlas, la clé structurée,
les libellés comparés, les montants, l'écart, les cardinalités, le groupe Sage,
ses lignes sources, ses pièces/dates et le score fuzzy lorsqu'il a été calculé.
Les scores inférieurs au seuil sont conservés, sans recalcul du fuzzy.

`RETENU` signifie que les critères de l'étape sont satisfaits, **pas une validation
définitive**. Un candidat peut ensuite devenir ambigu à cause de ses pièces/dates
ou parce que plusieurs groupes Atlas le revendiquent. Consulter `DECISION_FINALE`
et la feuille Résultats. `REJETE` signifie que les critères de la règle échouent.
Les compteurs avant/après sont répétés par candidat : ne pas les sommer.

Le journal ne matérialise jamais le produit Atlas × Sage. Les candidats exclus
par projet/tiers/BAP ou montant sont comptés globalement par filtre, sans une ligne
de rejet par couple. Le détail commence sur les candidats au montant compatible.
Un libellé absent ne déclenche aucun calcul de similarité.

## Synthèse et présentation

Le préfiltrage Sage est automatique : la rubrique Population précise les lignes
Sage totales, retenues et exclues avant agrégation. Les positions Sage affichées
restent celles de l'extraction complète après déduplication, même si le préfiltre
en écarte la majorité. Le journal garde le nombre global de groupes avant le
filtre structuré de chaque groupe Atlas.

La synthèse contient la date UTC de génération, les chemins sources fournis,
les paramètres du moteur, les populations, les comptes de résultats par règle et
les nombres de lignes Atlas concernées (dont celles à revoir). Les comptes de
résultats et de lignes sont distincts : un résultat peut représenter plusieurs lignes.

Les feuilles ont des filtres, des en-têtes figés et des couleurs discrètes sur
les issues. Les dates sont de vraies dates Excel ; les montants sont numériques.
Les scores s'affichent en pourcentage. Les identifiants textuels conservent leurs
zéros initiaux. Les chaînes commençant par `=` restent du texte, jamais des formules.

L'export est séquentiel avec openpyxl. Au-delà de 1 048 575 lignes de données,
une feuille est répartie en `Résultats_2`, `Tentatives_2`, etc., avec ses en-têtes.
Les lignes ne sont pas tronquées. Une cellule dépassant la limite Excel de
32 767 caractères provoque une erreur explicite ; réduire alors le périmètre.
En CLI, la trace reste sur disque ; les agrégats, résultats et sources restent
en mémoire. Dans l'API, `collect_trace=True` sans `trace_path` conserve le mode
mémoire pour les petits jeux de données.

## API Python

```python
from reconciliation.matching import match_reconciliations
from reconciliation.exporters.excel import export_reconciliation

# atlas et sage sont les DataFrames issues de transform_atlas / transform_sage.
result = match_reconciliations(atlas, sage, trace_path="output/tentatives.jsonl", trace_mode="compact")
export_reconciliation(
    atlas, result, "output/rapprochement.xlsx",
    source_paths={"Atlas": "data/JDD.xlsx", "Sage": "data/LISTPJT4.csv"},
)
from reconciliation.matching.trace import iter_attempts
for attempt in iter_attempts(result):
    pass  # Consommation progressive, sans list(...).
```

L'export requiert une collecte (via `trace_path` ou `collect_trace=True`) pour éviter une feuille Tentatives
trompeusement vide. Passer exactement l'extraction Atlas utilisée lors de l'appel
au moteur, sans réordonner ses lignes, et fournir `source_paths` pour protéger
les fichiers sources lors d'un appel direct à l'API.

Modules : `matching/trace.py` définit le journal ; `exporters/schema.py` centralise
les intitulés ; `exporters/excel.py` projette les lignes et écrit le classeur.
Les règles de matching restent inchangées. Aucune écriture n'est effectuée dans
Atlas ou Sage ; ce classeur est un support de consultation et de contrôle.

## Validation

Validation initiale de l'export : **90 tests réussis**, dont les 78 tests antérieurs conservés.
Les nouveaux tests relisent les fichiers Excel, vérifient les tentatives rejetées,
les décisions finales ambiguës, les filtres, les types de cellules, les sources
préservées, les feuilles fractionnées et la conservation d'une sortie précédente
si son remplacement échoue. Validation sur données synthétiques.

# Multiples Atlas, affectations SAGE et export des décisions

Évolution du 24 septembre 2026. Ce document décrit le code livré, les raisons
des choix et les limites à lever avant une utilisation comptable en production.
Les nouvelles fonctions et méthodes portent également une documentation française
dans leur code. Aucune extraction réelle n'a été importée dans Django pour ces travaux.

## 1. Traduction technique du besoin

Une exécution UiPath télécharge les deux extractions, puis appelle une seule CLI.
Le moteur conserve sa cascade de matching des `Envoyé SAGE`. Il ajoute un calcul
indépendant des multiples dans les `Comptabilisé` et des références nécessaires aux
validations futures. Le même JSONL transporte inventaire, propositions et contrôles.
Django importe cette photographie atomiquement ; il ne relance pas le moteur.

Trois objets métier restent distincts :

| Objet | Rôle |
| --- | --- |
| Proposition moteur | Résultat original MATCHED / AMBIGUOUS / UNMATCHED et sa règle |
| Décision de ligne | Brouillon, refus ou validation, corrections et éventuelle affectation MANUAL_MATCH |
| Revue d'un multiple | Suspicion à examiner, confirmée ou écartée, avec commentaire |

Confirmer un multiple ne supprime aucune ligne Atlas. Écarter une suspicion
ne retire pas son montant du calcul. Une validation Django n'est pas la preuve
que la correction a déjà été appliquée dans Atlas.

## 2. Montants : ce qui est établi, ce qui doit être confirmé

### Observations sur les extractions fournies

La lecture locale exhaustive du classeur a retrouvé **256 385 lignes Comptabilisé
pour 2026**, après déduplication par Id. Sur ces lignes :

| Mesure | Charges projet (€) | Charges SAGE (€) |
| --- | ---: | ---: |
| Valeurs absentes | 0 | 75 |
| Valeurs négatives | 17 058 | 17 084 |
| Valeurs nulles | 474 | 424 |

Les deux champs sont numériquement égaux sur 253 140 lignes. Cette fréquence
ne prouve **pas** qu'ils ont la même signification. Il reste 3 170 différences
entre valeurs renseignées, en plus des 75 absences.

SAGE contient 381 111 lignes, dont 46 826 charges négatives. La clé
`Projet + Numéro pièce + N° de ligne comptable + N° de ligne Analytique`
n'est pas répétée sur ce fichier. Les écritures d'une même pièce sont multiples.
La colonne `Devise` contient EUR et de nombreuses autres devises ; le libellé
`Charges (Dépenses)` n'établit pas à lui seul l'unité de conversion comptable.

### Politique de calcul explicite

Le montant d'une **validation projetée** est établi par le fonctionnement existant :
c'est le montant **individuel effectif** `amount` saisi pour la ligne, destiné au
champ Atlas `Total charges SAGE (€)`. Il ne s'agit jamais du `sage_total` du groupe.

Le montant de l'**existant Comptabilisé** est **Total charges SAGE (€)**.
Le métier a confirmé le 24 septembre 2026 qu'il s'agit bien d'un montant
**individuel par ligne**. Ce choix ne découle donc pas d'une simple égalité
statistique avec le montant projet. Il compare la charge SAGE représentée dans
Atlas à la charge SAGE de référence, en conservant les écarts éventuels au budget.

La CLI ajoute donc `--accounted-amount-field` :

| Valeur | Champ Atlas de l'existant |
| --- | --- |
| `total_sage_charges` (défaut) | Total charges SAGE (€), montant individuel confirmé par le métier |
| `total_project_charges` | Total charges projet (€), si le métier confirme que c'est la charge individuelle à comparer |
| Option absente | Même calcul que `total_sage_charges` |
| Politique absente/null dans un fichier v3 externe | UNKNOWN ; aucune sémantique n'est inventée par l'importeur |

Les tests et la simulation de volumétrie utilisent `total_sage_charges` sur
des valeurs individuelles, conformément à cette confirmation. Les totaux
`sage_total` des groupes moteur restent non additionnables et ne sont pas utilisés
comme charges individuelles du contrôle.

Le métier a également confirmé que **Charges (Dépenses) est toujours exprimé
en euros**, indépendamment de la devise d’origine indiquée dans SAGE. Aucune
conversion supplémentaire n’est appliquée. La devise reste une preuve descriptive,
sans rendre le contrôle incertain. Le contrat déclare et exige explicitement
`sage_amount_currency = "EUR"`. Les champs Atlas nommés « (€) » sont également
traités comme des euros.

### Comparaison monétaire

Le contrat partagé utilise `Decimal` à partir de représentations textuelles.
La tolérance vaut **0,01 €**, réglable avec `--multiple-tolerance`. Les montants
Atlas de l'inventaire sont normalisés au centime, comme dans l'application.

- Montants positifs : comparer Atlas à SAGE.
- Avoirs exclusivement négatifs : comparer les valeurs absolues des totaux.
- Zéro : montant renseigné et valide.
- Mélange de signes : UNKNOWN ; une compensation pourrait masquer un multiple.
- Montant absent/inconvertible : total concerné absent, jamais somme partielle.
- Identité SAGE manquante/non unique : aucun total SAGE fiable n'est annoncé.

## 3. Identités et stratégies

### STANDARD_BY_DOCUMENT

Clé : **projet + exercice + pièce SAGE**. L'exercice provient de `Année` côté
Atlas et de la date comptable côté SAGE. Une date Atlas manquante ou discordante
avec l'exercice rend le contrôle indéterminé. Plusieurs journaux pour une même
clé de pièce rendent aussi sa résolution indéterminée.

Le référentiel contient toutes les écritures de la pièce, y compris celles
que le préfiltre projet/tiers/BAP du matching avait écartées.

### ODS_ODG_BY_GROUP

Les pièces dont le numéro commence par ODS ou ODG, ou dont le journal porte
exactement ce code, utilisent **projet + exercice + tiers + libellé normalisé**.
Les numéros de pièce intersources ne sont jamais comparés.

Le nettoyage partagé applique NFKC, harmonise les espaces, retire les accents
pour la comparaison et utilise `casefold`. Il ne supprime aucun mot et ne fait
pas de fuzzy. Deux libellés absents donnent une clé incomplète et UNKNOWN,
jamais une correspondance. Les libellés Atlas d'origine et `original_label`
SAGE sont conservés dans les preuves.

Exemple : Atlas contient ODS-ATLAS-01 à 70 € et ODS-ATLAS-02 à 50 €, pour le
tiers 001 et « Café mission ». SAGE contient ODG-SAGE-99 à 100 € pour le même
projet/exercice/tiers et « CAFE MISSION ». Le groupe présente un excédent de
20 €. C'est une **suspicion de groupe**, car plusieurs opérations distinctes
peuvent partager ces critères. Le métier arbitre avec commentaire.

ODS/ODG ne permet aucune affectation manuelle dans la revue des Envoyé SAGE.

### Références des écritures

Une écriture analytique possède un SHA-256 construit sur : projet, exercice,
pièce, journal, numéro de ligne comptable et numéro de ligne analytique.
Les identifiants textuels gardent leurs zéros initiaux. Ce SHA ne dépend ni de
la position pandas, ni du numéro local d'un candidat, ni du montant.
Le montant, la date et le libellé font partie des preuves signées séparément :
une modification de leur contenu invalide la compatibilité même si la référence
d'écriture reste la même.

Une identité incomplète ou contradictoire ne permet pas une affectation fiable.
Les doublons stricts SAGE restent retirés par le loader existant.

### Doublons Atlas

Le loader conserve son premier Id après le filtre annuel. Il examine désormais
les lignes répétées **avant typage** : une valeur invalide ne doit pas masquer
deux textes sources différents en devenant deux valeurs nulles.
`technical_duplicates_removed` compte les copies strictement identiques ;
`conflicting_ids` compte les Id présentant plusieurs contenus distincts.
Un conflit est journalisé et rend les contrôles incertains, sans réintroduire
les copies de feuilles comme deux charges et sans changer la cascade historique.

## 4. JSONL v3 et intégrité

La CLI produit le schéma **3** lorsqu'elle écrit `--review-output`.
L'API `export_review_bundle` conserve son mode v2 historique si aucun iterable
`controls` n'est fourni ; les appels existants restent utilisables.

Ordre strict :

1. En-tête `campaign`, version, exercice, périmètre, politique de montant,
   unité SAGE EUR, tolérance, `controls_available=true` et compteurs de qualité des loaders.
2. Inventaire : les huit champs historiques, plus `Code tiers SAGE`,
   `Libellé ATLAS` et `Devise`. Tous les statuts Atlas restent présents.
3. Propositions : sources Atlas et preuves candidates ; chaque vraie écriture
   reçoit `entry_ref`. Un candidat moteur peut contenir plusieurs écritures.
4. Contrôles : clé/stratégie, composition, références SAGE, montants, effectifs,
   diagnostic, motifs d'incertitude, tolérance et signature.
5. Fin : `complete`, `inventory_count`, `control_count`, `control_statuses`.

Le fichier est écrit dans un temporaire et publié par remplacement après succès.
Un échec conserve l'ancien fichier de sortie : UiPath doit contrôler le code de
retour, et ne pas importer aveuglément un fichier ancien encore présent.

Django recontrôle les signatures, recalcule les montants avec le même contrat,
compare la composition Atlas à l'inventaire, vérifie les candidates contre les
contrôles et exige la couverture de tous les Comptabilisé. Les étapes hors ordre,
doublons, pièces hors exercice et compteurs incohérents annulent entièrement
l'import. La campagne courante précédente reste publiée.

Le fichier est une photographie fournie par l'administrateur, pas une preuve
cryptographique d'authenticité des extractions. L'application n'a pas les CSV
originaux pour refaire leur extraction.

Les fichiers v1/v2 et anciennes campagnes restent lisibles selon les règles
historiques (v1 réservé à l'initialisation sans campagnes). Une campagne sans
contrôles affiche explicitement leur indisponibilité. Revenir à un import v2
ne reporte pas silencieusement les validations issues de contrôles v3.

## 5. Validation, affectation et projection

La sélection manuelle utilise uniquement les écritures déjà candidates du moteur.
Elle affiche référence stable, projet, pièce, date, lignes comptable/analytique
et montant individuel. Le navigateur présente la somme et les écarts ; le service
recalcule avec Decimal. Sans candidate, l'écran indique « Aucune candidate disponible ».

Pour affecter manuellement, le métier choisit une ou plusieurs écritures,
renseigne un commentaire et clique sur Valider. Leur somme doit correspondre
au montant individuel corrigé. La pièce/date principale saisie doit appartenir
à la sélection. En présence de plusieurs pièces, **l'utilisateur choisit** cette
pièce/date principale : aucun choix automatique ou répartition arbitraire entre
écritures n'est fabriqué par l'application. Le détail de toutes les pièces reste
dans l'affectation et les exports ; le consommateur historique des corrections
continue à recevoir un montant et une pièce/date principale par ligne Atlas.

`MANUAL_MATCH` est une décision métier distincte : la proposition et la règle
du moteur ne sont pas réécrites. Brouillons, refus, valeurs KEEP/SET/CLEAR et
contrôles d'allocation du ReviewGroup restent disponibles.

Pour chaque pièce standard, au clic Valider :

```text
Projeté = charges Comptabilisé de la photographie source
        + contributions des autres validations actuelles de cette campagne
        + contribution proposée pour cette ligne
```

La contribution précédente de la même ligne est remplacée, jamais ajoutée deux
fois. Brouillon ou refus la retire. Plusieurs pièces sélectionnées donnent une
contribution par pièce, fondée sur les montants individuels de la sélection.

Exemple : SAGE porte 120 € sur deux écritures de 60 €. Atlas comporte déjà 40 €
Comptabilisé. Valider A à 60 € donne 100 € projetés. Valider B à 60 € donnerait
160 €, soit 40 € d'excédent. L'alerte montre la pièce, les totaux et les lignes
concernées. Le **clic Valider**, accompagné d'un commentaire justificatif, confirme
ce risque : aucune case supplémentaire n'est demandée. Le diagnostic et la
dérogation restent enregistrés dans l'historique.

Une écriture revendiquée par une autre décision, une pièce partagée entre groupes,
ou une affectation manuelle sur une pièce déjà comptabilisée fait aussi l'objet
d'un diagnostic de partage. Atlas n'indique pas toujours l'identité analytique
consommée : l'application signale alors un risque de pièce partagée, sans affirmer
qu'une écriture précise est définitivement consommée.

UNKNOWN bloque la validation v3 lorsqu'aucun calcul fiable n'est possible, même
avec confirmation. Le brouillon/refus reste disponible. Les campagnes historiques
conservent leur ancien circuit, avec l'absence de contrôle explicitement indiquée.
`MATCH_CONFIRMED_ATLAS` ne contourne pas cette exigence : la pièce doit réellement
être résolue dans les contrôles SAGE de la campagne.

## 6. Transactions, classes et raisons des choix

| Élément | Problème résolu / raison |
| --- | --- |
| `reconciliation_contract` | Même définition des clés, normalisation, Decimal et diagnostic dans Python et Django ; aucune dépendance à pandas/Django |
| `build_controls()` | Sépare le périmètre du matching du contrôle des Comptabilisé ; indexe seulement les clés utiles |
| `snapshot()` | Produit les preuves fixes et leur signature ; distingue calcul complet et indéterminé |
| `MultipleControl` | Stocke une photographie par clé/campagne et l'arbitrage de la suspicion ; distinct de ReviewGroup |
| `MultipleEvent` | Historise chaque arbitrage avec auteur, date, commentaire et signature |
| `ControlContribution` | Matérialise les réservations courantes par pièce/ligne ; remplace ou retire efficacement une décision |
| `LineReview.manual_assignment` | Conserve les vraies écritures sélectionnées sans modifier le résultat du moteur |
| `LineReview.multiple_context` | Signe les contrôles fixes pertinents, jamais le solde dérivé des autres utilisateurs |
| `LineReview.multiple_diagnostic` | Garde les calculs et dérogations au moment de la décision |
| `CampaignInventory.control_key` | Permet les recherches de composition par clé indexée plutôt qu'un scan JSON par contrôle |
| `AuditSheet` | Écriture Excel progressive, pagination et texte sûr communs aux feuilles d'audit |

`@transaction.atomic` lie décision, contributions et événement : si un contrôle
échoue, aucune réservation partielle ne subsiste. L'import reste une seule
transaction ; les nouveaux modèles n'introduisent pas un second import.

Le service verrouille **Campaign avant ReviewGroup/LineReview**. Le verrou commun
de campagne, déjà employé pour protéger publication et décisions, sérialise aussi
deux groupes distincts sur la même pièce. C'est volontairement plus large qu'un
verrou par pièce : simple et sûr sur PostgreSQL, mais moins concurrent.
Un futur verrou par agrégat demanderait un ordre déterministe pour les sélections
multi-pièces et une coordination avec la publication des campagnes.

`select_for_update()` fournit cette exclusion sur PostgreSQL en isolation normale
READ COMMITTED. SQLite ne fournit pas ce verrou de ligne : il peut répondre
« database is locked ». Les vérifications de versions ne rendent pas SQLite
équivalent à PostgreSQL. Le test à deux connexions est présent mais ignoré si
la base de tests n'est pas PostgreSQL ; cette garantie n'a pas été exercée sur
un serveur PostgreSQL pendant cette livraison.

`@login_required` protège les écrans, `@require_GET` les consultations/exports.
Les services recontrôlent le portefeuille, les versions et la campagne courante :
un POST forgé ou un ancien formulaire ne dépend pas de la seule protection visuelle.

Le package commun réside à la racine du dépôt. Django ajoute cette racine à son
chemin Python après son propre répertoire ; il n'importe pas le moteur pandas.
Un déploiement de l'application doit conserver `reconciliation_contract/` à
côté de `app-suivi-reconciliation/`. Le wheel du moteur embarque les deux packages.

## 7. Report des campagnes

Le report conserve toujours auteur, date initiale, commentaire et campagne
d'origine. Il vérifie les sources/propositions puis les contrôles fixes :

- nouveau Comptabilisé, changement de montant/date/pièce/libellé pertinent,
  changement SAGE ou composition de groupe : À revoir ;
- sélection manuelle disparue ou contradictoire : À revoir ;
- ligne absente puis réapparue : aucune résurrection automatique de validation ;
- validation matérialisée dans Atlas comme Comptabilisé : plus de proposition
  Envoyé SAGE pour cette identité, donc aucune contribution supplémentaire ;
- preuves fixes identiques : candidature au report, puis contrôle collectif.

Toutes les candidatures au report sont ajoutées **ensemble** avant l'évaluation.
Si elles dépassent SAGE ou introduisent une revendication partagée non déjà
justifiée, toutes les validations candidates de la pièce à risque sont marquées
À revoir. Aucun ordre de fichier ne désigne un gagnant. Un partage manuel déjà
justifié, inchangé et sans excédent peut être repris. Un dépassement collectif,
même précédemment dérogé, exige une nouvelle revue.

Les contrôles ODS/ODG et standards reprennent leur arbitrage uniquement à signature
de groupe identique. Une modification réinitialise l'arbitrage à examiner, sans
effacer l'ancienne campagne. Le solde utilisateur n'entre pas dans la signature :
une validation ne rend pas mécaniquement toutes les autres obsolètes en cascade.

## 8. Parcours et exports

Depuis une campagne : **Contrôles des multiples Atlas** ouvre la liste filtrable
par projet, stratégie, diagnostic et état de revue. Le détail montre les lignes
Atlas/SAGE et permet un arbitrage commenté dans la campagne courante seulement.
Les anciens écrans de campagnes restent consultables.

Deux exports distincts :

| Export | Contenu |
| --- | --- |
| Corrections validées | Uniquement les validations actuelles de la photographie sélectionnée ; les 15 colonnes historiques restent en tête, puis affectation métier, écritures sélectionnées et diagnostic |
| Audit des décisions | Toutes les décisions, y compris brouillons/refus/obsolètes, avec sources/effectifs/commentaires/auteurs/origines, affectations, multiples et journal |

Les feuilles d'audit séparent Décisions, Affectations SAGE, Multiples, Preuves
multiples et Journal. Une feuille sans enregistrement peut être absente. Les
totaux des contrôles sont dans Multiples, jamais répétés comme montants de ligne.
Le journal fusionne les deux familles d'événements par date ; il ne réécrit pas
les anciennes campagnes à partir de la projection actuelle.

Les textes Excel sont forcés au type texte (un commentaire commençant par `=`
reste un commentaire). Une feuille dépasse 1 048 575 lignes de données ? Une
nouvelle feuille reprend les en-têtes. Une preuve JSON dépassant la limite de
32 767 caractères par cellule provoque une erreur explicite dans l'audit plutôt
qu'une troncature. L'export reste une requête HTTP synchrone ; un gros périmètre
peut nécessiter un temps conséquent et une réponse mémoire volumineuse.

## 9. Volumétrie et limites mesurées

Une simulation locale sur les 256 385 Comptabilisé 2026 et les 381 111 SAGE
a exécuté les contrôles en **38,60 s**, hors chargement, matching, JSONL et Django.
La lecture du CSV Atlas intermédiaire de diagnostic et de SAGE a pris 6,71 s.
Ce CSV intermédiaire est un outil d'analyse local, pas une nouvelle entrée du
pipeline de production. Le XLSX complet n'a pas été rechargé par le loader de
production pendant cette mesure.

Le calcul a conservé 205 004 écritures SAGE comme preuves utiles ; le plus grand
groupe comptait 154 lignes Atlas+SAGE. Il ne crée pas de produit cartésien et
n'embarque pas toutes les écritures sans rapport avec Atlas.

Avec `total_sage_charges` : 174 817 contrôles standards
équilibrés, 33 excédents, 32 montants Atlas inférieurs, 1 251 standards inconnus
et 7 672 groupes ODS/ODG inconnus. **Ce ne sont pas des anomalies métier validées** :
les suspicions nécessitent un arbitrage. Les motifs les plus nombreux sont les
références absentes, les clés incomplètes et les signes mixtes ; un
contrôle peut avoir plusieurs motifs.

Les DataFrames complets de cette simulation représentent environ 691,8 Mio Atlas
et 360,3 Mio SAGE (mesure pandas des colonnes, **pas pic mémoire du processus**).
Les index, preuves et chaînes temporaires s'y ajoutent. Le filtre annuel réduit
les lignes retenues, mais la lecture XLSX parcourt toujours les feuilles.

Les étapes potentiellement longues : lecture XLSX, constitution des index et
preuves, écriture JSONL, import ORM et export Excel. L'import des contrôles utilise
désormais des lectures groupées et `bulk_create`, par lots de 500. Sous SQLite,
la préparation est isolée, les instantanés sont transférés en lots invisibles
puis publiés atomiquement. Aucun temps d'import réel Django n'est garanti sans
mesure sur le fichier cible. Voir [les imports SQLite par lots](import_sqlite_par_lots.md).

## 10. Installation, commandes et validation

Migration ajoutée :
`app-suivi-reconciliation/reconciliation/migrations/0010_multiple_controls_assignments.py`.
Elle ajoute les champs de revue/inventaire et les trois modèles de contrôle.
Elle a été exercée dans les bases de tests, **pas appliquée à la base réelle**.

Depuis `app-suivi-reconciliation`, après votre sauvegarde habituelle :

```powershell
uv run python manage.py migrate
uv run python manage.py runserver
```

Exemple de commande UiPath (le champ de montant indiqué est aussi la valeur par défaut) :

```powershell
uv run python -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --year 2026 --accounted-amount-field total_sage_charges --multiple-tolerance 0.01 --review-output "output/campagne-2026.jsonl" --campaign-name "Septembre 2026"
```

L'administrateur importe ce seul JSONL depuis l'application. Le métier consulte
la campagne, arbitre les multiples, valide/refuse ou affecte les candidates, puis
télécharge corrections et/ou audit. La prochaine extraction constate l'application
aval ; l'application ne modifie pas directement Atlas.

Pour reproduire les cas fictifs et les tests :

```powershell
uv run python -m examples.multiples_fixture .work_app/exemple-multiples
uv run pytest
# Depuis app-suivi-reconciliation :
uv run python manage.py test --noinput
uv run python manage.py makemigrations --check --dry-run
uv run ruff check .
```

Les tests couvrent le pipeline moteur→JSONL→Django, écritures multiples d'une
pièce, excédent existant/projeté, deux groupes, retrait/réapplication, affectation
multi-écritures, preuve modifiée/disparue, matérialisation dans Atlas, report
collectif, ODS/ODG à numéros différents, Unicode, dates/montants absents,
zéro/avoirs/signes mixtes, devise d’origine distincte de l’euro de comparaison, droits, export historique,
formules Excel, ancien contrat et imports tronqués/incohérents.

Validation : 121 tests moteur réussis, 1 intégration réelle ignorée ; 80 tests
Django réussis et 1 test PostgreSQL ignoré sur SQLite. Huit vues ordinateur/mobile
et une validation manuelle complète ont été contrôlées dans Edge avec une base
isolée fictive. Le test PostgreSQL à deux connexions est conditionnel ; aucun
test local SQLite ne doit être présenté comme une preuve de concurrence PostgreSQL.

## 11. Recette avant production

1. Recette comptable des 33 suspicions simulées et des groupes ODS/ODG inconnus.
2. Exécution du test de concurrence sur PostgreSQL si l’application devient partagée.

Le sens individuel de `Total charges SAGE (€)` dans Atlas et l’unité euro de
`Charges (Dépenses)` dans SAGE ont été confirmés pendant l’implémentation ;
ils ne constituent plus des points bloquants. Les données insuffisantes, pièces
non résolues et signes mixtes restent explicitement indéterminés.

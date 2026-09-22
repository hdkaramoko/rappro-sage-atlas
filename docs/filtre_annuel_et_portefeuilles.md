# Filtre annuel, import des portefeuilles et choix du statut BAP

Évolution du 20 septembre 2026. Ce guide complète le [fonctionnement des campagnes](campagnes_rapprochement.md).

## 1. Exécuter le rapprochement pour une année

Depuis `scriptsRappro`, adapter les noms de fichiers aux extractions disponibles :

```powershell
uv run python -m reconciliation.main --atlas data/inputs/JDD.xlsx --sage data/inputs/ZLISTPJT.csv --year 2026 --output data/outputs/rapprochement_2026.xlsx --review-output data/outputs/campagne_2026.jsonl --campaign-name "Septembre — exercice 2026"
```

Le paramètre `--year` est facultatif. Sans lui, les chargeurs gardent le fonctionnement toutes années. Avec lui, l'année doit être un entier entre 2000 et 2200 et s'applique aux **deux** extractions :

| Source | Critère | Effet |
| --- | --- | --- |
| Atlas | Colonne `Année` égale à l'année demandée | Les autres années sont écartées avant normalisation complète et matching |
| SAGE | Année de `Date comptable` égale à l'année demandée | Les autres exercices et les dates absentes/invalides sont exclus |

Le filtrage Atlas conserve tous les statuts de l'année choisie pour l'inventaire. Le moteur recherche ensuite les correspondances des lignes « Envoyé SAGE », comme auparavant. Une ligne « Comptabilisé » de 2026 reste dans l'inventaire de 2026 ; elle ne devient pas une proposition de matching.

L'Excel de résultats est également limité aux lignes Atlas de l'année choisie. La synthèse indique l'exercice. Les logs donnent les lignes exclues par le filtre, séparément des doublons. Les positions techniques des lignes se rapportent aux données chargées, filtrées et dédupliquées, pas aux numéros physiques de ligne du fichier source.

Une colonne `Année` manquante dans une feuille Atlas valide provoque une erreur avec `--year`. Les valeurs d'année absentes/invalides sont exclues et signalées. S'il ne reste aucune ligne Atlas **ou** aucune écriture SAGE pour l'année, le traitement s'arrête avant publication des nouveaux fichiers. Un ancien fichier de sortie déjà présent n'est pas effacé : l'orchestrateur doit toujours vérifier le code retour de la commande avant d'importer une sortie.

### Pourquoi filtrer à cet endroit ?

Le chargeur Atlas filtre chaque feuille immédiatement après sa lecture, avant d'empiler les feuilles et de dédupliquer les identifiants. Cela réduit la mémoire conservée entre feuilles et évite de perdre une ligne 2026 parce qu'un même Id apparaissait d'abord en 2025. Le typage détaillé des dates et montants ne porte ensuite que sur les lignes retenues.

Le CSV SAGE est lu, dédupliqué et typé, puis filtré sur la date comptable convertie : une recherche textuelle de « 2026 » ne serait pas un contrôle fiable de date. Le préfiltrage supplémentaire projet/tiers/BAP est ensuite conservé.

La lecture physique du XLSX reste nécessaire ; le gain principal porte sur la mémoire conservée, le typage, le matching, la taille des exports et le volume importé dans l'application. Ce n'est pas un accès direct aux seules cellules d'une année dans le fichier XLSX.

## 2. Année et campagnes

Le contrat JSONL v2 reçoit une métadonnée facultative `year`, reprise dans `Campaign.fiscal_year`. Une valeur absente ou `null` signifie « toutes années ». Les anciens JSONL v2 restent compatibles. Les clés de groupe générées en mode annuel incluent l'année afin de ne pas confondre des identifiants semblables entre exercices.

La comparaison recherche la dernière campagne du **même périmètre déclaré et du même exercice**, et non simplement le dernier import chronologique. Exemple : après 2026, puis 2025, puis de nouveau 2026, cette dernière campagne est comparée à la précédente 2026. Aucune absence 2025/2026 n'est déduite du seul changement d'année.

Une première campagne annuelle constitue une référence propre : elle n'est pas comparée à l'inventaire toutes années. Les décisions antérieures restent conservées, mais une validation provenant d'un autre contexte n'est pas automatiquement considérée comme une validation de cette nouvelle campagne annuelle. Le cas particulier de l'archive de reprise sans inventaire complet reste traité par le mécanisme de migration décrit dans le guide des campagnes.

L'application contrôle la cohérence du fichier : toutes les lignes de l'inventaire annuel doivent appartenir à l'année annoncée et les preuves SAGE doivent comporter une date comptable de cette année. Une campagne annuelle vide est refusée. Le contrôle concerne les preuves de l'extraction SAGE ; la date comptable déjà présente dans Atlas n'est pas utilisée comme filtre de l'année Atlas.

**Une seule campagne reste courante globalement**, celle du dernier import réussi. Les autres sont consultables en lecture seule, y compris lorsqu'elles concernent un autre exercice. Cette évolution permet d'alterner les années sans fausse comparaison, pas de modifier simultanément plusieurs campagnes anciennes. `--campaign-scope` reste un identifiant stable du périmètre source : ne pas le changer seulement pour indiquer une année, utiliser `--year`.

Si un même enregistrement a été travaillé dans un contexte annuel puis toutes années, le report reprend la décision photographiée dans la campagne précédente du contexte choisi. Il ne mélange pas les corrections faites dans l'autre contexte. Les droits projet restent indépendants de l'année.

## 3. Initialiser les portefeuilles depuis Excel

L'administrateur dispose du menu **Importer des portefeuilles**, également accessible depuis **Mon portefeuille**. Le bouton **Télécharger le modèle Excel** fournit un classeur vide avec les bons en-têtes.

La première feuille contient exactement deux colonnes :

| username | codes projets |
| --- | --- |
| marie.dupont | PROJET01; PROJET02 |
| paul.martin | PROJET03 |
| marie.dupont | PROJET04 |

Les comptes doivent déjà exister et être actifs. Le username est comparé exactement après retrait des espaces de bord ; il n'est pas converti en minuscules. Les codes projet sont normalisés en majuscules. Le fichier ne crée pas de compte et ne contient aucun mot de passe.

Un username peut apparaître sur plusieurs lignes. Plusieurs codes peuvent figurer dans une cellule, séparés par un point-virgule, une virgule ou un saut de ligne. Les identifiants doivent être stockés comme **texte** dans Excel, notamment pour préserver d'éventuels zéros initiaux. Les formules ne sont pas acceptées.

### Règles d'application

1. Lecture et contrôle du format XLSX, des en-têtes et des cellules.
2. Validation de tous les usernames et codes projet.
3. Si une erreur est détectée, affichage des lignes concernées et **aucun ajout**.
4. Si tout est valide, ajout des associations manquantes dans une transaction.
5. Affichage des nombres d'accès créés et déjà présents ; enregistrement d'un journal d'import réussi.

L'import est **additif** : il ne retire pas les projets absents du fichier. Les doublons dans le classeur sont dédupliqués, et renvoyer les mêmes affectations ne crée pas de doublons. Les retraits restent des actions explicites dans le parcours existant.

Limites du formulaire : fichier `.xlsx` de 10 Mo maximum, 20 000 lignes et 50 000 affectations distinctes ; taille décompressée limitée à 50 Mo. Seule la première feuille est lue. Le fichier original n'est pas archivé par cette brique : le journal garde le nom, l'administrateur, la date, les compteurs et les couples username/projet appliqués.

L'import est synchrone et convient à l'initialisation des portefeuilles. Il ne réutilise pas le worker du rapprochement, car il ne charge pas des millions de lignes sources. Un import très important d'affectations peut néanmoins prendre du temps ; les limites ne constituent pas une garantie de durée.

## 4. Quels projets sont considérés comme valides ?

Un code doit apparaître sur une ligne **présente** d'un inventaire complet de référence. Une ancienne observation marquée absente ne suffit pas à autoriser un nouvel ajout. La simple présence du code dans la table `Project` ne suffit plus non plus.

Le référentiel combine les photographies les plus récentes par exercice :

- une campagne annuelle plus récente remplace l'inventaire antérieur de son année ;
- le dernier inventaire toutes années reste la référence pour les exercices non remplacés par une campagne annuelle plus récente ;
- un nouveau fichier toutes années remplace à son tour les inventaires annuels antérieurs ;
- un code présent dans au moins un exercice de référence est admissible ;
- un projet explicitement désactivé dans l'application ne peut pas être ajouté.

Cette combinaison évite qu'un ancien inventaire toutes années réintroduise un projet disparu de l'inventaire annuel plus récent. Elle permet également d'affecter un projet encore connu dans un autre exercice, même si cet exercice n'est pas la campagne de travail courante.

Si le code est attesté par l'inventaire mais n'existe pas encore dans `Project` — par exemple parce que toutes ses lignes étaient déjà comptabilisées — sa fiche est créée avec un libellé générique. Les fiches existantes et leurs libellés ne sont pas écrasés.

**Importer d'abord les campagnes, puis les affectations.** Une archive de reprise sans inventaire complet ne constitue pas ce référentiel. Les utilisateurs peuvent ensuite enrichir leur propre portefeuille dans **Mon portefeuille**, avec exactement le même contrôle d'inventaire. Les accès déjà accordés ne sont pas automatiquement révoqués si un projet disparaît d'une extraction.

## 5. Statut BAP dans la validation

Le champ de remplacement du statut est maintenant une liste proposant :

- **Envoyé SAGE** ;
- **Comptabilisé**.

Le fonctionnement « Conserver / Modifier / Effacer » est maintenu. En mode « Modifier », l'utilisateur choisit l'un des deux statuts. « Effacer » peut être enregistré comme travail préparatoire mais ne permet pas de valider une ligne sans statut. « Conserver » reprend la source ; pour valider, cette valeur doit également appartenir aux deux statuts autorisés.

Le contrôle existe dans le formulaire **et** dans le service métier. Une requête HTTP modifiée ou un appel direct au service ne peut pas enregistrer un nouveau statut arbitraire en mode remplacement. Les anciennes photographies ne sont pas réécrites rétroactivement.

## 6. Choix techniques et maintenance

| Élément | Raison du choix |
| --- | --- |
| Argument `--year` transmis aux chargeurs | Réduire tôt le périmètre, avant les copies canoniques et les agrégats |
| Champ explicite `Campaign.fiscal_year` | Comparaisons SQL fiables, sans déduire l'année d'un nom de fichier ou de campagne |
| Métadonnée JSONL optionnelle | Maintenir la lecture des fichiers v2 existants tout en contrôlant les nouveaux fichiers annuels |
| `reference_inventory()` partagé | Appliquer la même définition d'un projet connu à l'import admin et à l'ajout individuel |
| `load_workbook(read_only=True, data_only=False)` | Lire progressivement et détecter les formules au lieu d'utiliser silencieusement leur résultat en cache |
| `@transaction.atomic` sur l'import des portefeuilles | Ne pas appliquer une partie d'un fichier contenant des erreurs |
| `get_or_create` et contrainte utilisateur/projet | Imports répétables, sans suppression ni doublon d'accès |
| `PortfolioImport` | Conserver la provenance et le bilan des affectations appliquées |
| `ChoiceField` et constantes BAP partagées | Présenter les choix métier et les faire respecter côté serveur |

Fichiers principaux : [CLI](../reconciliation/main.py), [chargeur Atlas](../reconciliation/loaders/atlas.py), [chargeur SAGE](../reconciliation/loaders/sage.py), [campagnes](../app-suivi-reconciliation/reconciliation/campaigns.py), [service des portefeuilles](../app-suivi-reconciliation/projects/portfolio_import.py), [formulaire de validation](../app-suivi-reconciliation/reconciliation/review_forms.py), [contrôles métier](../app-suivi-reconciliation/reconciliation/review.py).

Migrations : `projects/0002_year_and_portfolio_import` crée le journal des affectations ; `reconciliation/0009_year_and_portfolio_import` ajoute l'année de campagne, avec `null` pour les campagnes existantes. Elles sont additives. Sur l'installation locale, une sauvegarde a précédé leur application : `.work_app/before-year-portfolios-20260920-184849.sqlite3`. Transactions, revues, événements, portefeuilles et campagnes existants ont été conservés.

## 7. Vérifications

Les tests couvrent : sélection avant déduplication Atlas, bornes de dates SAGE, dates invalides, année vide, compatibilité sans filtre, année dans le JSONL, comparaison des campagnes du même exercice, séparation des décisions annuel/toutes années, import Excel additif, refus global des fichiers incohérents, comptes et projets inactifs, droits administrateur, contrôle d'inventaire en ajout individuel, et refus des statuts arbitraires.

Commandes de contrôle :

```powershell
# Depuis scriptsRappro
uv run pytest

# Depuis scriptsRappro/app-suivi-reconciliation
uv run python manage.py test
uv run python manage.py makemigrations --check --dry-run
uv run ruff check .
```

Les essais ne chargent pas de faux utilisateurs ni d'affectations fictives dans la base métier. Les contrôles visuels utilisent une base isolée.

Résultats de vérification : **117 tests moteur réussis, 1 ignoré ; 70 tests Django réussis**.
Ruff ne signale aucune erreur et aucune migration n'est manquante. Le scénario de bout en bout
importe deux campagnes annuelles produites par le moteur puis un Excel d'affectations.
Seize vues à 1440 px et 390 px ont été contrôlées dans Edge, sans erreur JavaScript ni
débordement horizontal de page ; le champ BAP est bien un élément `select` avec les deux statuts.

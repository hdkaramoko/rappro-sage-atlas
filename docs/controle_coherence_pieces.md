# Cohérence Atlas / SAGE — Diagnostic et activation collective

Le diagnostic correspond à l'étape 1 de
`prompts/prompt_gestion_confirme_atlas.md` : calculer, conserver et afficher les
contrôles, sans les utiliser pour déclencher de nouvelles validations automatiques.
La signification de `MATCH_CONFIRMED_ATLAS` et les règles de validation existantes
ne changent pas. Une pièce peut apparaître cohérente dans le nouveau bloc et rester
en attente de validation à cause du garde-fou de pièce partagée existant.

## Configuration et utilisation

Dans `reconciliation/config.py` :

```python
PIECE_COHERENCE = {"enabled": True, "mode": "DIAGNOSTIC"}
```

`enabled=False` omet les nouveaux diagnostics à l'export, sans toucher à
`AUTO_VALIDATION`. `DIAGNOSTIC` conserve le fonctionnement de la première brique.
L'étape 2 est maintenant disponible via `ACTIVE`, désactivé par défaut :

```python
PIECE_COHERENCE = {"enabled": True, "mode": "ACTIVE"}
```

`AUTO_VALIDATION.enabled` doit également être actif et sa liste doit autoriser
`MATCH_CONFIRMED_ATLAS` (ou le statut général `MATCHED`). La configuration existante
`AUTO_VALIDATION` n'est pas modifiée par cette livraison. Le JSONL doit être régénéré :
l'en-tête transporte `piece_coherence_mode = ACTIVE`, le diagnostic et les demandes
individuelles demeurent des champs distincts. Les demandes confirmées sont omises
si le diagnostic n'est pas `PIECE_RECONCILED`. L'activation exige le contrat v3 et
ses contrôles SAGE ; un export v2 actif est refusé explicitement.

Le champ `mode` de l'objet diagnostic lui-même reste `DIAGNOSTIC` : c'est un résultat
de calcul inchangé, pas une autorisation. Seul l'en-tête actif et les demandes
`auto_validation` peuvent activer le service collectif à l'import.

Pour afficher ces informations, produire **une nouvelle campagne** puis l'importer
par le parcours habituel, par exemple :

```powershell
.venv\Scripts\python.exe -m reconciliation.main --atlas data/inputs/JDD.xlsx --sage data/inputs/ZLISTPJT.csv --year 2026 --review-output data/outputs/campagne_diagnostic_pieces_2026.jsonl --campaign-name "Diagnostic des pièces 2026"
```

L'ancien JSONL reste inchangé. Le réimport du même fichier ne recalcule rien.
Les diagnostics utilisent les photographies JSON existantes. Pour l'étape 2,
appliquer la migration additive `0014_linereview_automatic_assignment` depuis
`app-suivi-reconciliation` avant d'importer une nouvelle campagne :

```powershell
..\.venv\Scripts\python.exe manage.py migrate
```

Cette migration n'a pas été appliquée à la base métier pendant l'implémentation.

## Étape 2 — Validation collective

`reconciliation/collective_validation.py` côté Django groupe les lignes par
projet/pièce. Il exige la composition complète de la pièce, le même diagnostic
réconcilié sur tous ses membres, une demande automatique conforme et la règle
`MATCH_CONFIRMED_ATLAS` pour chaque membre. Une autre proposition revendiquant
la pièce, un refus, un brouillon ou une validation humaine empêche de nouvelles
validations automatiques de cette pièce ; les décisions humaines sont conservées.

L'affectation établit une bijection déterministe tiers/BAP/date/montant : les
répétitions légitimes utilisent des références d'écritures distinctes. La date ne
découpe pas le diagnostic collectif, mais doit rester compatible avec la preuve
individuelle pour la validation. Les tolérances et signes restent contrôlés.

`piece_coherence.py::verified_assignment` compare chaque réservation aux vraies
écritures des contrôles v3 : même périmètre, références, montants, tiers, dates et
journaux. Une pièce déjà comptabilisée dans les contributions sources, une stratégie
non standard ou un contrôle incertain reste bloquant. Le diagnostic seul n'est
jamais suffisant pour réserver une écriture.

Toutes les contributions sont réservées avant la première décision, puis la
projection collective est vérifiée. Chaque décision passe encore par `review.decide`
sans dérogation. Un savepoint englobe toute la pièce : si le dernier membre échoue,
les décisions, événements et contributions précédents sont annulés. Les raisons
de refus sont conservées sur tous les membres. Les anciennes décisions AUTO de
la pièce deviennent périmées et leurs contributions courantes sont retirées.

`multiple_review.py` ne considère plus comme anormal le partage d'une pièce entre
affectations collectives vérifiées portant sur des écritures distinctes. Les
doubles emplois de référence, conflits avec d'autres propositions et autres risques
restent bloquants. Le comportement des autres règles de rapprochement est conservé.

### Historique, reprises et intervention humaine

Le champ `LineReview.automatic_assignment` conserve la référence de preuve de la
pièce et l'écriture attribuée. Il est distinct de `manual_assignment` et conservé
dans les photographies et événements. L'empreinte des décisions collectives inclut
cette affectation et le contexte courant du contrôle de pièce.

- Une campagne inchangée conserve les décisions sans événements supplémentaires.
- Une preuve ou un membre modifié impose une réévaluation de toute la pièce.
- Une pièce devenue incohérente, incomplète ou privée d'autorisation ne conserve
  aucune ancienne validation AUTO courante. Les photographies passées restent intactes.
- Le retour en mode diagnostic invalide les anciennes validations fondées sur
  l'affectation collective ; il ne les reconduit pas via le traitement individuel.
- Une intervention humaine efface l'affectation automatique sur la ligne,
  devient `MANUAL` et conserve l'affectation antérieure dans l'événement. Les
  imports suivants respectent cette priorité humaine.
- Le réimport du même fichier conserve l'idempotence existante par SHA-256.

Le détail courant et historique affiche l'écriture SAGE attribuée ; l'export de
campagne ajoute une colonne « Affectation automatique SAGE ». Les badges et le
tableau principal conservent leur présentation métier.

### Vérification de l'activation

Tests moteur : 154 réussites, un ignoré. Tests Django complets avant l'ajout de la
colonne d'export : 133 tests sans échec, un ignoré. Les scénarios collectifs couvrent
la pièce unique/partagée, les répétitions, le réimport, le report intercampagnes,
l'absence d'autorisation d'un membre, les preuves incohérentes, les décisions
humaines, la désactivation, l'altération du contrôle et l'échec du dernier membre.
Après l'ajout de l'affichage de l'écriture et de l'export : 41 tests ciblés
(collectif, campagnes, UI) réussis, puis un test supplémentaire réussi de rejet
d'un mode d'activation inconnu. `makemigrations --check --dry-run` ne détecte
aucune modification de modèle manquante après la migration 0014.

Fichiers propres à l'activation : `collective_validation.py` (transaction de pièce),
`piece_coherence.py` côté Django (vérification des affectations), `multiple_review.py`
(réservation par écriture et partage sûr), `review.py` (décision mutualisée et audit),
`models.py` et migration 0014 (affectation persistante), `campaigns.py` (photographies
et validation du mode), `auto_validation.py` (dispatch collectif/individuel),
`exporters/review.py` et `reconciliation/piece_coherence.py` (autorisation transportée),
les vues, le composant de détail et l'export de campagne, ainsi que
`test_collective_validation.py` et `tests/test_piece_coherence.py`.

Rejeu local en base SQLite **en mémoire** : la pièce
`24SSE0C443 / NDF0126090511` passe en AUTO/VALIDATED sur ses **six lignes**, avec
six contributions portant sur des écritures distinctes. Aucun import actif n'a
été exécuté dans la base métier. Le décompte de 1 376 lignes cohérentes ci-dessous
reste celui du diagnostic de l'étape 1 ; il ne préjuge pas du nombre final de lignes
validables après les garde-fous supplémentaires de l'étape 2.

## Calcul effectué

1. `reconciliation/piece_coherence.py::build_piece_checks` regroupe toutes les
   lignes `Envoyé SAGE` par **projet + numéro de pièce SAGE**, sans la date.
   Il recherche les écritures de même clé dans l'extraction SAGE fournie, avant
   tout préfiltrage de candidats du matching.
2. `reconciliation_contract/piece_coherence.py::check_piece` somme le montant
   **SAGE déclaré dans Atlas** et les charges extraites de SAGE avec `Decimal`.
   L'écart est `Atlas − SAGE`, signé, avec une tolérance de 0,01 €. Aucun passage
   en valeur absolue des montants ni arrondi préalable des écritures.
3. Si les totaux concordent, il compare les multisets **tiers + BAP + montant**.
   Tiers et BAP sont normalisés en Unicode, espaces et majuscules, sans supprimer
   les zéros initiaux. Les montants sont appariés une seule fois, triés par clé,
   à la tolérance près et sans accepter deux signes opposés. Des répétitions
   identiques sont admises lorsque les multiplicités concordent.
4. L'exercice comptable doit être cohérent. Un document retrouvé sur plusieurs
   exercices, une date absente/incohérente, un montant absent ou un périmètre SAGE
   incomplet empêche de conclure. Plusieurs dates du même exercice sont permises :
   elles ne découpent pas la clé de pièce.
5. Identités Atlas/SAGE absentes ou dupliquées, tiers/BAP manquants et journaux
   multiples rendent le contrôle individuel incertain. Les lignes déjà
   `Comptabilisé` ne participent pas à la somme Atlas de ce diagnostic : le périmètre
   demandé est celui des lignes `Envoyé SAGE`. Une pièce partiellement comptabilisée
   peut donc apparaître en écart, ce qui reste à analyser.

| Résultat | Signification |
| --- | --- |
| `PIECE_RECONCILED` | Totaux signés, combinaisons individuelles et multiplicités concordent. |
| `PIECE_AMBIGUOUS` | Totaux concordants, mais données individuelles insuffisantes ou identités incertaines. |
| `PIECE_MISMATCH` | Pièce SAGE absente, écart global ou incohérence individuelle démontrée. |
| `NOT_CHECKED` | Données ou périmètre insuffisants pour exécuter le contrôle. |

Les lignes sans clé projet/pièce exploitable n'ont pas de diagnostic de pièce.
Les groupes de rapprochement comportant plusieurs lignes Atlas ne reçoivent pas
de diagnostic individuel dans cette première brique. Les propositions confirmées
Atlas, individuelles, reçoivent le diagnostic collectif de leur pièce.

## JSONL, import et affichage

`exporters/review.py` ajoute un objet facultatif `piece_coherence` aux propositions
individuelles concernées. Il contient le résultat, les totaux, l'écart, les effectifs,
les motifs, les lignes Atlas et SAGE normalisées, le mode `DIAGNOSTIC`, une version
de contrat et une signature déterministe. Le statut et les métadonnées
`auto_validation` existants sont indépendants et conservés.

À l'import, `reconciliation/piece_coherence.py::validate_proposal_check` côté Django
recalcule ce diagnostic, vérifie la signature, le périmètre et l'appartenance de la
ligne Atlas. Un objet incohérent provoque le rejet atomique de la campagne.
`campaigns.py` le conserve dans `CampaignGroup.data` sans l'ajouter à l'empreinte
des décisions : ce diagnostic seul n'invalide aucune décision humaine ou automatique.
Les campagnes historiques sans cet objet restent importables.

Le composant `templates/components/piece_coherence.html` affiche le bloc
**Contrôle de cohérence SAGE** dans le détail courant et dans les photographies
historiques : résultat métier, projet/pièce, totaux, écart, contrôle individuel et
motifs. Le tableau principal et ses badges restent inchangés. L'affichage historique
utilise la photographie de sa campagne, jamais des données courantes recalculées.

## Rejeu local du 16 octobre 2026

Sources : propositions et lignes Atlas de
`data/outputs/campagne_16102026.jsonl`, confrontées à l'extraction locale
`data/inputs/ZLISTPJT.csv` chargée pour 2026. Ce rejeu a été effectué en mémoire,
sans réimporter de campagne dans la base métier ni modifier le fichier source.
Les fichiers sources sont ceux présents localement ; le JSONL ne contient pas
d'empreinte permettant de certifier leur identité avec les extractions d'origine.

| Périmètre | Cohérent | Ambigu | Incohérent |
| --- | ---: | ---: | ---: |
| Pièces contrôlées | 945 | 13 | 23 |
| Lignes `MATCH_CONFIRMED_ATLAS` (1 952) | 1 891 | 19 | 42 |
| Parmi les 1 410 lignes confirmées précédemment bloquées pour pièce partagée | 1 376 | 8 | 26 |

Les autres lignes envoyées sans pièce exploitable ne permettent pas un contrôle
de pièce : 10 201 lignes dans ce rejeu.

Cas `24SSE0C443 / NDF0126090511` : **PIECE_RECONCILED**, six lignes Atlas et six
écritures SAGE ; totaux **971,87 € / 971,87 €**, écart **0,00 €**, tiers/BAP/montants
et multiplicités concordants. Cela n'entraîne aucune nouvelle validation automatique.

## Vérifications

- Suite moteur : 151 tests réussis, un ignoré, puis 17 tests ciblés réussis après
  ajout du contrôle de périmètre SAGE incomplet.
- Suite Django : 117 tests sans échec, un ignoré, puis un test supplémentaire
  réussi prouvant qu'une pièce partagée cohérente reste bloquée en mode diagnostic.
- Vérification des migrations : aucun changement de modèle détecté.
- Cas couverts : pièce unique/partagée, dates différentes, répétitions,
  montants signés et limite d'un centime, écart global, incohérence individuelle
  avec totaux égaux, tiers/BAP absents ou divergents, pièce SAGE absente,
  identité dupliquée, périmètre incertain, export activé/désactivé sans changement
  de demande automatique, import altéré annulé, réimport, priorité humaine,
  historique et rendu UI.

Fichiers principaux : les trois modules `piece_coherence.py` (contrat partagé,
moteur, import Django), `config.py`, `exporters/review.py`, `campaigns.py`,
les vues courantes/historiques, le filtre de libellés `review_ui.py`, les deux
templates de détail et le composant dédié. Les tests sont dans
`tests/test_piece_coherence.py` et dans le module homonyme de l'application.

# Première brique — Diagnostic de cohérence Atlas / SAGE

Cette livraison correspond à l'étape 1 de
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
`AUTO_VALIDATION`. Seul `DIAGNOSTIC` est accepté ; aucun mode d'activation des
validations collectives n'est livré. La future étape 2 nécessitera notamment
l'allocation collective, le contrôle des doubles emplois et une activation explicite.

Pour afficher ces informations, produire **une nouvelle campagne** puis l'importer
par le parcours habituel, par exemple :

```powershell
.venv\Scripts\python.exe -m reconciliation.main --atlas data/inputs/JDD.xlsx --sage data/inputs/ZLISTPJT.csv --year 2026 --review-output data/outputs/campagne_diagnostic_pieces_2026.jsonl --campaign-name "Diagnostic des pièces 2026"
```

L'ancien JSONL reste inchangé. Le réimport du même fichier ne recalcule rien.
Aucune migration ni modification de la base métier n'est nécessaire pour cette
brique : les diagnostics sont stockés dans les photographies JSON existantes.

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

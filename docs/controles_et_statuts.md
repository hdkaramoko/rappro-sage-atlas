# Contrôles de rapprochement et lecture des statuts

Ce guide décrit le comportement actuel du moteur, avec ses paramètres par défaut.
Il explique les résultats du classeur Excel sans modifier les règles métier.

## Trois informations à distinguer

| Colonne Excel | Question à laquelle elle répond |
| --- | --- |
| Statut BAP | Quel est le statut présent dans l'extraction Atlas ? |
| Statut du rapprochement | Le moteur a-t-il trouvé une correspondance, une ambiguïté ou aucun résultat ? |
| Règle retenue | Sur quels critères cette décision repose-t-elle ? |
| Statut BAP proposé | Quel statut le moteur propose-t-il pour Atlas ? |
| Revue nécessaire | Le résultat nécessite-t-il un contrôle humain ? |
| Motif du résultat | Quelle est l'explication précise de la décision ou du blocage ? |

**`MATCHED` ne signifie pas nécessairement « Comptabilisé sans contrôle ».**
Un rapprochement expérimental peut être `MATCHED`, avec revue obligatoire et
sans statut BAP proposé. Les propositions ne sont jamais écrites dans Atlas.

## Suite des contrôles, dans l'ordre

### 1. Charger, typer et dédupliquer les extractions

Le loader contrôle les fichiers et les colonnes obligatoires. Il convertit les
dates et montants ; une valeur non convertible devient manquante et est signalée.
Atlas conserve la première occurrence de chaque Id, dans l'ordre des feuilles.
Sage supprime les lignes sources strictement identiques, avant conversion.
Les cardinalités utilisées ensuite portent sur les lignes après ces opérations.

Les transformations préparent les clés : espaces de bord retirés, espaces
insécables harmonisés, codes et références en majuscules. La casse des libellés
est conservée. Les séparateurs et accents ne sont pas supprimés.

### 2. Sélectionner les lignes Atlas à traiter

Seules les lignes dont le statut normalisé est exactement **`Envoyé SAGE`** sont
traitées. Les autres, y compris celles déjà `Comptabilisé` ou sans statut, figurent
dans l'export avec `HORS_PERIMETRE`. Elles ne génèrent pas de recherche Sage.

### 3. Vérifier si la preuve est déjà présente dans Atlas

Les trois champs suivants doivent être renseignés après préparation :

- `N° pièce SAGE` ;
- `Date comptable` ;
- `Total charges SAGE (€)`.

Si oui : `MATCH_CONFIRMED_ATLAS`, confiance 1,00, sans revue, statut proposé
`Comptabilisé`. Zéro est un montant renseigné. Cette règle vérifie la présence
des trois champs : elle ne compare pas le montant Sage au montant projet Atlas.
Elle ne recherche ni ne réserve de ligne dans l'extraction Sage.
Si une preuve manque, la ligne passe aux étapes suivantes.

### 4. Préfiltrer Sage avec les trois champs structurés

Le moteur relève les triplets **projet + code tiers + BAP** présents dans Atlas
restant à rechercher. Il conserve toutes les lignes Sage portant l'un de ces
triplets. Une clé structurée incomplète ne permet pas de rechercher un candidat.

Ce préfiltrage ne porte ni sur le libellé, ni sur le montant, ni sur l'année.
Il ne valide aucun match. Il conserve les positions Sage de l'extraction complète.

### 5. Regrouper séparément Atlas et Sage sur quatre champs

| Champ | Atlas | Sage |
| --- | --- | --- |
| Projet | Code projet | Projet |
| Tiers | Code tiers SAGE | Code Tiers - Tiers doc Orig |
| Libellé | Libellé ATLAS | Libellé pièce |
| BAP / référence | N° BAP (SAGE) | Référence |

**Les quatre valeurs doivent être identiques pour appartenir au même groupe.**
Le BAP utilisé est celui nommé `N° BAP (SAGE)` dans Atlas, pas `N° BAP (Atlas)`.

Un même triplet projet/tiers/BAP peut donc donner plusieurs groupes, avec chacun
son propre libellé. Aucun libellé représentatif n'est choisi arbitrairement.
Par exemple, pour un même triplet : « Hôtel Paris » à 100 € et à 150 € forment
un groupe de 250 € ; « Train Paris » à 80 € reste un autre groupe de 80 €.

Pour chaque groupe, le moteur conserve :

- le nombre de lignes et les identifiants/positions sources ;
- la somme de `Total charges projet (€)` côté Atlas ;
- la somme de `Charges (Dépenses)` côté Sage ;
- les pièces et dates comptables distinctes du groupe Sage.

Une seule valeur de montant manquante invalide la somme du groupe : aucune
somme partielle ne sert de preuve. Zéro et montants négatifs sont acceptés.

### 6. Déterminer les candidats de chaque groupe Atlas

Un candidat Sage doit avoir le même projet, tiers et BAP, et un montant compatible :

```text
|montant du groupe Atlas − montant du groupe Sage| ≤ 0,01 €
```

La tolérance est configurable. Une marge de 1e-9 à sa frontière positive absorbe
les résidus flottants ; les montants ne sont pas arrondis pour construire les groupes.
Un projet, tiers ou BAP manquant, ou une somme Atlas incomplète, entraîne un
résultat `UNMATCHED` avec un motif explicite. Les libellés manquants ne peuvent
pas valider le strict ou le fuzzy, mais peuvent passer au fallback sans libellé.

### 7. Essayer les règles dans l'ordre

| Ordre | Règle | Conditions sur les groupes |
| --- | --- | --- |
| 1 | `MATCH_EXACT` | Quatre champs identiques, montants compatibles, nombres de lignes identiques |
| 2 | `MATCH_AMOUNT` | Quatre champs identiques, montants compatibles, nombres de lignes différents |
| 3 | `MATCH_FUZZY_HIGH` | Triplet identique, montants compatibles, unique candidat plausible, similarité ≥ 95 % |
| 3 | `MATCH_FUZZY_REVIEW` | Même recherche fuzzy, unique candidat plausible, similarité ≥ 85 % et < 95 % |
| 4 | `MATCH_WITHOUT_LABEL` | Triplet identique et montants compatibles, sans condition sur le libellé |

La première règle qui retient des candidats arrête la cascade, même si les
contrôles suivants rendent le cas ambigu. Une règle suivante ne sert pas à
contourner une ambiguïté déjà détectée.

Le fuzzy utilise `token_set_ratio` de RapidFuzz : l'ordre des mots peut varier.
Le score est une similarité textuelle, pas une probabilité de rapprochement.
Des mots supplémentaires ou un libellé inclus dans l'autre peuvent donner un
score élevé. La cardinalité n'est pas une condition de validation fuzzy.

Tous les candidats de score ≥ 85 % sont plausibles. S'il y en a plusieurs,
le résultat est `AMBIGUOUS`, même si le meilleur dépasse 95 %. Si aucun n'atteint
85 %, le moteur peut essayer `MATCH_WITHOUT_LABEL`, activé par défaut.

**Le fallback sans libellé compare les groupes déjà construits sur quatre champs.**
Il ne fusionne pas les groupes aux libellés différents et ne recherche pas de
combinaison de plusieurs groupes pour reconstituer un total. Cette règle reste
inchangée : aucune seconde agrégation sur trois champs n'est appliquée.

### 8. Vérifier l'unicité du candidat et la qualité des preuves Sage

Plusieurs candidats retenus par la règle donnent `AMBIGUOUS`.
Pour un candidat unique :

- plusieurs pièces distinctes **ou** plusieurs dates distinctes dans son groupe
  donnent `AMBIGUOUS`, même après une correspondance exacte ;
- une pièce/date unique mais absente sur certaines lignes donne un résultat
  `MATCHED` avec revue et **sans statut BAP proposé** ;
- des pièces/dates uniques et renseignées sur toutes les lignes permettent
  de conserver la règle retenue et d'appliquer sa politique de statut proposé.

Les valeurs distinctes restent disponibles pour le contrôle. Le moteur ne
choisit pas silencieusement une pièce ou une date parmi plusieurs.

### 9. Contrôler les candidats Sage partagés entre groupes Atlas

Après la cascade, le moteur vérifie si plusieurs groupes Atlas revendiquent
le même groupe Sage. Tous les groupes Atlas concernés deviennent `AMBIGUOUS`.
Les candidats des résultats déjà ambigus participent aussi à ce contrôle.
Un résultat exact peut donc être déclassé ; l'ordre des lignes n'attribue pas
une priorité. Les preuves Atlas de l'étape 3 ne participent pas à cette recherche.

### 10. Produire la décision finale et la restitution

Sans règle retenue : `UNMATCHED`, revue nécessaire, aucun statut BAP proposé.
Le résultat des groupes est ensuite reporté sur leurs lignes Atlas dans Excel.
Les totaux de groupe répétés sont signalés **non additionnables**.

## Sens des statuts de rapprochement

| Statut | Signification | Revue | Statut BAP proposé |
| --- | --- | --- | --- |
| `MATCHED` | Une preuve Atlas ou un candidat Sage a été retenu sans ambiguïté finale | Dépend de la règle et des preuves | Dépend de la règle et des preuves |
| `AMBIGUOUS` | Plusieurs possibilités ou preuves incompatibles empêchent une attribution fiable | Oui | Aucun |
| `UNMATCHED` | Aucune règle n'a retenu de candidat, ou données nécessaires incomplètes | Oui | Aucun |
| `HORS_PERIMETRE` | La ligne Atlas n'est pas au statut Envoyé SAGE ; statut ajouté dans l'export | Non | Aucun |

`UNMATCHED` ne prouve pas l'absence d'une écriture comptable : le fichier Sage
peut ne pas couvrir la période, les clés peuvent différer ou les montants ne
pas satisfaire les règles. `HORS_PERIMETRE` n'est pas un échec de rapprochement.

## Confiance, revue et proposition de statut par règle

Valeurs par défaut, après tous les contrôles d'ambiguïté :

| Règle | Confiance | Revue nécessaire | Statut BAP proposé |
| --- | --- | --- | --- |
| `MATCH_CONFIRMED_ATLAS` | 1,00 | Non | Comptabilisé |
| `MATCH_EXACT` | 1,00 | Non si preuves Sage complètes ; oui sinon | Comptabilisé si preuves complètes ; aucun sinon |
| `MATCH_AMOUNT` | 0,90 | Oui | Aucun |
| `MATCH_FUZZY_HIGH` | Score de similarité | Oui | Aucun |
| `MATCH_FUZZY_REVIEW` | Score de similarité | Oui | Aucun |
| `MATCH_WITHOUT_LABEL` | 0,70 | Oui | Aucun |
| `AMBIGUOUS` | Non définie | Oui | Aucun |
| `UNMATCHED` | 0,00 | Oui | Aucun |

Les quatre règles montant, fuzzy et sans libellé sont expérimentales. Même
un fuzzy à 100 % reste à revoir. La confiance n'annule pas les contrôles sur
les pièces/dates ou les candidats partagés.

L'option API `auto_account_rules` peut autoriser explicitement un statut proposé
pour certaines règles expérimentales ; elle est vide par défaut. Elle conserve
le signal de revue et ne contourne jamais une ambiguïté ou des preuves incomplètes.

## Motifs détaillés du résultat

| Motif | Explication |
| --- | --- |
| `ATLAS_EVIDENCE_PRESENT` | Les trois champs de preuve sont déjà renseignés dans Atlas |
| `UNIQUE_CANDIDATE` | La règle a retenu un seul candidat aux preuves complètes |
| `INCOMPLETE_STRUCTURED_KEY` | Projet, code tiers ou BAP manquant côté Atlas |
| `INCOMPLETE_AMOUNT` | Le montant du groupe Atlas ne peut pas être calculé intégralement |
| `NO_CANDIDATE` | Aucun candidat retenu par les règles actives ; consulter les filtres du journal pour préciser pourquoi |
| `INCOMPLETE_SAGE_EVIDENCE` | Pièce ou date absente sur au moins une ligne du candidat Sage |
| `INCOMPATIBLE_SAGE_EVIDENCE` | Plusieurs pièces ou dates distinctes dans le groupe Sage |
| `MULTIPLE_CANDIDATES` | Plusieurs groupes Sage retenus par la règle |
| `SAGE_CANDIDATE_SHARED` | Le même groupe Sage est revendiqué par plusieurs groupes Atlas |

Le contrôle final de partage peut remplacer un motif précédent. Une ambiguïté
finale remplace aussi la règle retenue par `AMBIGUOUS` et supprime le statut proposé.
Les champs de candidat éventuellement conservés servent alors à l'investigation,
pas à une validation automatique.

## Lire les issues dans la feuille Tentatives

Les issues du journal décrivent des **étapes**, pas nécessairement le résultat final.

| Issue / étape | Sens |
| --- | --- |
| `EXECUTE` | Un filtre a été appliqué ; comparer les compteurs avant/après |
| `RETENU` | Le candidat satisfait la règle à cette étape, sous réserve des contrôles finaux |
| `REJETE` | Le candidat échoue à cette règle, ou aucun candidat ne peut être examiné |
| `NON_EXECUTE` | Étape non essayée : désactivée, prérequis absent ou cascade déjà arrêtée |
| `ETAPES_NON_EXECUTEES` | En journal compact, ligne qui rassemble les noms des étapes ignorées |
| `DECISION_FINALE` | Statut final après tous les contrôles, notamment les candidats partagés |

Une tentative `RETENU` suivie d'une décision `AMBIGUOUS` est donc cohérente.
Le mode compact résume les rejets non fuzzy mais conserve tous les scores fuzzy
calculés. Les compteurs répétés sur les candidats ne doivent pas être additionnés.
Les identifiants des candidats sont des identifiants de **groupes Sage**, pas
des numéros de pièce comptable.

Pour les détails du classeur, voir [le guide d'export](export_excel.md).
Pour les paramètres et l'API, voir [l'implémentation](implementation.md).

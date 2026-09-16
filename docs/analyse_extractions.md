# Analyse locale de JDD.xlsx et ZLISTPJT.csv

Analyse réalisée le 16 septembre 2026. Les fichiers sources sont inchangés.
Les détails restent dans `data/analysis/`, ignoré par Git ; les tests versionnés
utilisent des valeurs fictives reproduisant les formats et cas observés.

**Mise à jour : le préfiltrage Sage décrit dans l'expérience ci-dessous est
maintenant intégré au moteur et activé par défaut.** Il préserve les positions
sources, les identifiants de groupes/candidats et les compteurs globaux de trace.
Le banc `examples.benchmark_sage_scope` compare maintenant toutes les colonnes
de résultat, provenance incluse, à l'ancienne référence sans préfiltrage.
Validation après intégration : 110 tests standard réussis, un test d'intégration
réelle réussi séparément. Sur ce dernier passage, le matching intégré a pris
11,03 s (hors lecture des fichiers et export Excel), avec les 7 700 lignes Sage
retenues et l'égalité de toutes les colonnes de résultat confirmée.

## Périmètre et méthode

Atlas : parcours XML exhaustif du classeur compressé, avec dictionnaire de
chaînes partagées et comptage des lignes. Ce script de diagnostic n'est pas
un remplacement du loader Excel de production. Il conserve la première
occurrence de chaque Id, dans l'ordre des feuilles, puis extrait les lignes
« Envoyé SAGE » sans les trois champs de preuve renseignés vers un CSV local.
Les dates Excel numériques de ce sous-ensemble sont converties pour le typage.

Sage : lecture de l'intégralité du CSV par le loader existant. Le moteur réel
est ensuite exécuté sur les 16 417 lignes Atlas à rechercher et l'intégralité
des lignes Sage, avec le nouveau journal compact sur disque.

Les 2 193 preuves Atlas sont comptées ici sur la présence des trois champs
sources : ce n'est pas une validation indépendante de leur contenu comptable.
Leur chemin de validation est couvert par les tests unitaires. Le classeur
Excel complet de 1,5 million de lignes n'a pas été généré pendant cette analyse.

## Volumes observés

| Mesure | Valeur |
| --- | ---: |
| Taille JDD.xlsx | 399 122 229 octets |
| Taille ZLISTPJT.csv | 102 816 417 octets |
| Feuilles Atlas | 2 utiles, 1 vide |
| Colonnes Atlas | 47 |
| Lignes Atlas avant déduplication | 1 501 571 |
| Doublons d'Id Atlas | 1 |
| Id Atlas manquants | 0 |
| Lignes Atlas conservées | 1 501 570 |
| Atlas déjà Comptabilisé | 1 482 960 |
| Atlas Envoyé SAGE | 18 610 |
| Preuves Atlas renseignées | 2 193 |
| Atlas nécessitant une recherche | 16 417 |
| Groupes Atlas à rechercher | 14 946 |
| Lignes Sage | 381 111 |
| Doublons techniques Sage | 0 |
| Groupes Sage (clé complète) | 205 779 |

La première feuille Atlas contient 1 000 001 lignes de données ; la seconde
501 570. Les colonnes utiles et leurs orthographes correspondent au schéma
existant, dont `Libellé ligne budgetaire`. Le CSV Sage comporte une colonne
finale vide (`Unnamed: 24`). Les 19 champs demandés pour l'export sont présents
dans Atlas, avec l'alias documenté pour le libellé budgétaire.

Seulement 1,24 % des lignes Atlas sont « Envoyé SAGE ». La lecture et la
restitution de tout l'historique sont donc très différentes du volume métier
réellement recherché.

## Qualité et couverture temporelle

Les dates comptables Sage sont toutes renseignées, valides et en 2026 ; les
montants `Charges (Dépenses)` ne présentent pas de valeur manquante ou invalide.
En revanche, Sage contient 129 581 références absentes, 15 433 codes tiers
absents et 716 libellés absents. Ces lignes ne doivent pas créer des faux matches
par égalité de valeurs nulles.

Dans Atlas à rechercher, un BAP Sage manque. Le moteur le classe explicitement
`INCOMPLETE_STRUCTURED_KEY` ; il ne lui substitue pas le BAP Atlas.

| Année Atlas à rechercher | Lignes |
| --- | ---: |
| 2026 | 9 170 |
| 2025 | 6 344 |
| 2024 | 279 |
| 2023 | 31 |
| 2022 | 25 |
| 2021 | 27 |
| 2020 | 541 |

Il reste donc 7 247 lignes d'années antérieures devant un Sage limité à 2026.
Cela constitue une question de couverture métier, pas une raison suffisante
pour imposer un filtre annuel : une dépense Atlas antérieure peut être
comptabilisée en 2026. Avec les règles actuelles, 91 de ces lignes antérieures
obtiennent une proposition de rapprochement. Aucune règle annuelle nouvelle
n'a été ajoutée.

Les avertissements de typage Sage ont deux explications importantes :

- les dates secondaires vides utilisent la sentinelle `  /  /    `, notamment
  270 911 dates de modification et 340 586 dates de début de prestation ;
- les 79 412 valeurs non vides de `Taux de TVA` sont des **libellés descriptifs**,
  par exemple `SC6 TVA France 20.0%`, alors que le schéma actuel attend un nombre.

Le typage actuel les remplace par des valeurs manquantes avec avertissement.
Ces champs ne participent pas au matching. Une correction future doit distinguer
le libellé fiscal du taux numérique, et ne pas extraire arbitrairement un nombre.
Un taux de change Sage et une date de fin de prestation supplémentaire sont
également non convertibles. Dans le sous-ensemble Atlas : sept dates de début
et une date de fin sont non convertibles, sans effet sur la clé de matching.

## Résultats observés sur le sous-ensemble à rechercher

| Règle | Groupes Atlas | Lignes Atlas |
| --- | ---: | ---: |
| MATCH_EXACT | 4 121 | 4 668 |
| MATCH_AMOUNT | 2 | 2 |
| MATCH_FUZZY_HIGH | 211 | 234 |
| MATCH_FUZZY_REVIEW | 179 | 195 |
| MATCH_WITHOUT_LABEL | 501 | 542 |
| AMBIGUOUS | 1 | 1 |
| UNMATCHED | 9 931 | 10 775 |
| Total | 14 946 | 16 417 |

Ces compteurs excluent les 2 193 preuves déjà présentes dans Atlas.
Les règles expérimentales restent des propositions à revoir.
Parmi les groupes non rapprochés : 8 017 n'ont aucun bloc Sage projet/tiers/BAP,
1 913 ont un bloc mais aucun montant de groupe compatible, et un a une clé
incomplète. Il n'est pas justifié de diminuer le seuil fuzzy pour résoudre ces cas.

Le groupe Atlas le plus grand contient 12 lignes, le groupe Sage le plus grand
577. Dans tout Sage, 25 950 groupes ont plusieurs pièces et 5 274 plusieurs dates.
Ces populations peuvent se recouper ; elles ne sont pas toutes candidates pour
Atlas. Le plus gros bloc Sage contient 740 groupes, mais **au maximum deux
candidats** subsistent par groupe Atlas après le filtre montant sur ce jeu.

## Temps mesurés et expérience d'optimisation

Mesures ponctuelles sur la machine courante, sans garantie de durée en production.
Les étapes présentées ne forment pas toutes une même exécution à additionner.

| Opération | Temps observé |
| --- | ---: |
| Lecture et typage Sage complet | 4,87 s |
| Profilage XML Atlas complet | 191,28 s |
| Préparation et agrégation des lignes Atlas à rechercher | 4,12 s |
| Préparation et agrégation de Sage complet | 71,04 s |
| Moteur sur 16 417 Atlas et 381 111 Sage, journal disque inclus | 81,12 s |
| Préfiltrage expérimental Sage par les blocs Atlas | environ 0,6 s |
| Même moteur après ce préfiltrage (7 700 lignes Sage) | environ 9 s |

L'expérience de préfiltrage conserve tous les Sage appartenant à une clé
projet/tiers/BAP non vide présente dans les Atlas à rechercher, puis exécute le
même moteur. Les décisions, montants, pièces, dates, scores, cardinalités et
ambiguïtés ont été comparés à l'exécution Sage complète : **égalité vérifiée**.
Les identifiants de groupes/candidats et positions Sage locaux changent lors de
la sous-sélection ; ils sont exclus de cette comparaison. Une intégration au
moteur doit conserver les positions originales et les compteurs globaux de trace.

Le gain observé sur le matching, préfiltrage compris, est d'environ **8,5 fois**.
Il exclut la lecture complète d'Atlas, le chargement Sage et l'export Excel.
Ces temps décrivent l'expérience initiale. Le préfiltrage est désormais intégré
dans `matching/scope.py`, avec une numérotation vectorisée des groupes complets
avant sélection pour conserver les identifiants d'origine.

## Optimisations réalisées et prochaines priorités

Réalisées : journal compact ; écriture progressive JSONL sur disque ; relecture
progressive à l'export ; détection de fichier incomplet ou remplacé. Sur le
sous-ensemble réel, 111 332 événements occupent environ 68,5 Mo sur disque,
sans liste de traces en mémoire. Le gain de mémoire concerne les traces, pas
les DataFrames ni les catalogues de groupes. Une preuve Atlas passe de huit
événements à trois, en conservant les étapes non exécutées dans une synthèse.

Suivi des autres optimisations :

1. **Préfiltrer Sage avant l'agrégation** : intégré après autorisation, avec la preuve expérimentale ci-dessus.
2. **Préparer uniquement les Atlas sélectionnés**, en conservant séparément les
   lignes hors périmètre pour la restitution. La déduplication globale doit
   rester préalable au filtrage pour préserver la première occurrence d'un Id.
3. **Sortir les gros catalogues des `DataFrame.attrs`** ou éviter leur copie
   implicite : les projections pandas peuvent recopier profondément ces
   métadonnées. Ce surcoût a notamment affecté le banc de comparaison, corrigé
   en retirant les métadonnées de ses tableaux de comparaison uniquement.
4. Optimiser ensuite l'agrégation et la sérialisation répétée des champs de
   groupe à l'export. Le fuzzy n'est pas la priorité sur ces extractions.

L'export intégral conserve environ 64,6 millions d'emplacements de cellules pour
la seule feuille Résultats (1 501 570 × 43), avant les tentatives. Les deux
optimisations réalisées ne suppriment pas ce coût incompressible de restitution.

## Reproduire et tester

```powershell
uv run python -m examples.profile_inputs
uv run python -m examples.analyze_matching_inputs
uv run python -m examples.benchmark_sage_scope
uv run pytest
# Test d'intégration optionnel sur les artefacts locaux produits ci-dessus :
$env:RECONCILIATION_REAL_TESTS = "1"
uv run pytest tests/test_real_matching.py
Remove-Item Env:RECONCILIATION_REAL_TESTS
```

Les tests synthétiques couvrent les formats observés, la déduplication avant
filtrage, un historique comptabilisé volumineux, les références absentes,
les devises descriptives, la conservation des règles entre années et des
groupes Sage de 577 lignes. Les tests de journal vérifient l'égalité des décisions
compact/détaillé et mémoire/disque, les scores rejetés, l'écriture progressive,
les interruptions, les journaux tronqués et les fichiers remplacés.

L'intégration locale vérifie les décisions de préfiltrage contre le résultat
complet sauvegardé par l'analyse. Il faut régénérer tous les artefacts si les
sources changent ; ce n'est pas une validation comptable des correspondances.

Validation finale : **103 tests réussis et 1 test d'intégration ignoré par défaut**
dans la suite standard (6,74 s). Le test d'intégration a été activé séparément
sur ces fichiers : **1 test réussi** (18,24 s). `git diff --check` ne signale
aucune erreur d'espacement.

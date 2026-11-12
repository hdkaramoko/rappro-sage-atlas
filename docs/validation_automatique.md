# Validation automatique Atlas / Sage

**7 novembre 2026 — nouvelles campagnes :** le [correctif Confirmé / Exact v2](validation_confirme_exact_v2.md)
autorise les groupes Exact à bijection unique, sans élargir l'AUTO Confirmé.
Le BAP divergent seul peut être accepté en décision humaine avec preuve réelle.
Ces règles exigent un nouveau JSONL portant la politique v2 ; aucune campagne
historique n'est recalculée.

## Activation

La configuration du moteur est un module Python, `reconciliation/config.py`.
Pour désactiver la fonctionnalité :

```python
AUTO_VALIDATION = {"enabled": False, "statuses": []}
```

Exemple pour autoriser les preuves Atlas confirmées, correspondances exactes,
montants et libellés très proches :

```python
AUTO_VALIDATION = {
    "enabled": True,
    "statuses": ["MATCH_CONFIRMED_ATLAS", "MATCH_EXACT", "MATCH_AMOUNT", "MATCH_FUZZY_HIGH"],
}
```

Ces codes sont des **règles** du moteur ; son statut final est `MATCHED`.
La configuration accepte les règles existantes et le statut `MATCHED`.
Une valeur inconnue produit une erreur explicite lors de l'export JSONL.
Une autorisation ne suffit jamais à contourner les contrôles de sûreté.
Les règles de rapprochement configurées sont désormais éligibles :
`MATCH_CONFIRMED_ATLAS`, `MATCH_EXACT`, `MATCH_AMOUNT`, `MATCH_FUZZY_HIGH`,
`MATCH_FUZZY_REVIEW`, `MATCH_WITHOUT_LABEL`. Aucune règle n'est ajoutée implicitement
à votre configuration. Le statut global `MATCHED`, toujours accepté pour
compatibilité, autorise toutes ces règles : préférer une liste explicite.
`AMBIGUOUS` et `UNMATCHED` ne déclenchent jamais une auto-validation.
Les groupes comportant plusieurs lignes Atlas, les ambiguïtés et les écarts
supérieurs à 0,01 restent manuels. `MATCH_EXACT` garde sa contrainte de cardinalité.
Une preuve Atlas confirmée doit également avoir un montant Atlas connu et
compatible avec le montant Sage confirmé.

## Ce qui se passe derrière

1. Le rapprochement termine ses contrôles habituels. Il n'est pas modifié.
2. `reconciliation/auto_validation.py` examine le résultat final : autorisation,
   règle autorisée, preuve complète, unicité et concordance des montants.
   Pour une règle expérimentale, le drapeau `requires_review` est attendu :
   l'autorisation explicite lève cette réserve, mais le motif final doit être
   `UNIQUE_CANDIDATE`. Une preuve incomplète ou un conflit reste bloquant.
3. `reconciliation/exporters/review.py` ajoute un objet facultatif à la proposition
   JSONL. Le moteur ne crée ni auteur ni date de validation.
4. Django importe inventaire, propositions et contrôles dans sa transaction
   existante. Il conserve les photographies et les empreintes métier existantes.
5. Après les contrôles de campagne, `reconciliation/auto_validation.py` côté
   Django applique les demandes via `review.decide`, le même service que les
   décisions humaines : complétude, pièce/date, répartition, projection et
   contrôles des multiples restent obligatoires, sans dérogation automatique.
   Un refus de contrôle laisse un motif dans les raisons de la photographie.
6. Le service enregistre une véritable décision `VALIDATED`, une date Django,
   l'origine `AUTO`, la règle, un commentaire et un `ReviewEvent`. L'auteur est
   nul (système), ce que le modèle autorise ; aucun compte privilégié n'est créé.
   Un savepoint empêche une projection partielle lorsqu'une demande est refusée.

Pour `MATCH_AMOUNT`, une ligne Atlas peut correspondre à plusieurs écritures
Sage dans un candidat unique : toutes doivent porter la même pièce et la même
date, avec montant total compatible. Aucune répartition automatique entre
plusieurs lignes Atlas n'est introduite. Les mêmes contrôles s'appliquent aux
règles fuzzy et sans libellé. Django partage les codes admissibles avec le moteur
via `reconciliation_contract/auto_validation.py`, mais continue à appliquer ses
propres contrôles de preuve et de projection.

La configuration reste une autorisation côté moteur, transportée dans le JSONL.
Modifier la liste ne réévalue pas un ancien fichier : générer et importer une
nouvelle campagne. Les décisions humaines, même périmées, restent prioritaires.
Le contrat JSONL et le modèle de données ne changent pas ; aucune nouvelle
migration n'est nécessaire pour cette extension.

Les indicateurs et les exports utilisent déjà `VALIDATED` et l'empreinte courante :
les validations automatiques y participent par le même chemin. La liste affiche
une pastille, le détail expose règle et commentaire, et le filtre d'origine permet
de distinguer `AUTO` de `MANUAL`. L'export de campagne ajoute origine et règle.

## Contrat JSONL compatible

Avant (extrait d'une proposition, les autres champs restent obligatoires) :

```json
{"type":"proposal","schema_version":3,"match_status":"MATCHED","rule":"MATCH_EXACT"}
```

Après :

```json
{"type":"proposal","schema_version":3,"match_status":"MATCHED","rule":"MATCH_EXACT","auto_validation":{"source":"AUTO","rule":"MATCH_EXACT","state":"VALIDATED"}}
```

Un fichier historique sans cet objet ne déclenche aucune nouvelle validation.
L'objet exprime une demande : Django peut refuser de l'appliquer si les données
ne satisfont pas ses contraintes. Ce n'est pas une décision humaine importée.

## Priorités et campagnes

- Toute décision humaine enregistrée, même un refus ou un brouillon, prévaut.
- Une intervention via l'écran existant devient `MANUAL`, efface la règle
  automatique et conserve l'événement précédent dans l'historique.
- Les empreintes existantes couvrent les sources, preuves, composition du groupe
  et contexte des multiples. Un changement invalide la décision antérieure ;
  une nouvelle demande admissible est réévaluée avec les contrôles métier.
- Une validation automatique sans nouvelle autorisation n'est plus courante et
  est exclue des corrections validées. La photographie précédente est conservée.
- Un fichier strictement identique (SHA-256 de ses octets) n'est pas réimporté :
  aucune nouvelle campagne ni événement. Un fichier différent constitue une
  nouvelle campagne ; ses décisions automatiques inchangées ne sont pas dupliquées.
- Les cas incertains restent à contrôler et les raisons sont conservées dans la
  photographie de campagne. Aucune dérogation automatique n'est autorisée.

## Migration et fichiers

Appliquer depuis `app-suivi-reconciliation` :

```powershell
..\.venv\Scripts\python.exe manage.py migrate
```

La migration `0013_linereview_auto_validation_rule_and_more` ajoute deux champs :
`validation_source` (historique classé `MANUAL`) et `auto_validation_rule` (vide).
Le champ existant `validation_origin` reste la **campagne** d'origine.

Les autres fichiers concernés sont `review.py` (service mutualisé et audit),
`campaigns.py` (photographies et application en fin d'import), `review_import.py`
(idempotence), `review_views.py` (filtre), `campaign_views.py` (export),
les composants de décision et le formulaire de filtres (présentation).

## Vérification

Vérification de l'extension pilotée par configuration : 135 tests moteur réussis
(un ignoré), 92 tests Django sans échec (un ignoré), puis deux tests ciblés
supplémentaires réussis pour l'invalidation d'une décision fuzzy après changement
de contrôle et la priorité d'un refus humain. Les scénarios couvrent aussi les
projections v3, le report sans doublon, les preuves incompatibles et les règles
non autorisées. Aucun changement du modèle ni migration supplémentaire.

La configuration présente lors de cette évolution reste inchangée :
`MATCH_CONFIRMED_ATLAS`, `MATCH_EXACT`, `MATCH_AMOUNT`, fonctionnalité activée.
Pour activer également les libellés très proches, ajouter explicitement
`MATCH_FUZZY_HIGH` puis générer une nouvelle campagne JSONL.

Les tests moteur sont dans `tests/test_auto_validation.py` ; les scénarios Django
dans `reconciliation/test_auto_validation.py` de l'application. Utiliser :

```powershell
.venv\Scripts\python.exe -m pytest -q
cd app-suivi-reconciliation
..\.venv\Scripts\python.exe manage.py test reconciliation --noinput
```

Les bases de production ne sont pas migrées par ces commandes de test.

L'idempotence impose aux fixtures de campagnes successives un nom documentaire
distinct. Une vérification de non-régression a également révélé un arrondi à deux
décimales du prix unitaire dans le détail : il affiche maintenant jusqu'à six
décimales, conformément à la précision stockée.

Résultats exécutés : suite moteur initiale 128 réussites et un test ignoré,
puis six tests ciblés réussis après ajout du scénario JSONL ; suite Django
86 tests, succès avec un test ignoré. Django signale seulement l'absence du
répertoire `staticfiles` dans l'environnement de test. Le premier lancement
Django depuis la racine a rencontré une collision entre les deux paquets
`reconciliation` ; la suite a été relancée depuis le répertoire de l'application.

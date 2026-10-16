# Diagnostic : lignes « Confirmé dans Atlas » et auto-validation

> Diagnostic de l'état précédant l'extension de `AUTO_VALIDATION`. Depuis
> l'évolution autorisée ensuite, la restriction à deux règles a été remplacée
> par les règles configurées et les contrôles décrits dans
> [validation_automatique.md](validation_automatique.md). Les règles de priorité
> humaine et de fraîcheur décrites ici restent applicables.

Analyse du code existant au 16 octobre 2026. Aucune logique métier modifiée.
Les causes ci-dessous sont établies à partir du code ; sans examiner une ligne
et sa campagne en base, elles ne permettent pas d'attribuer une cause précise
à chacun des cas observés.

## Modification d'affichage

Dans « Mes rapprochements », l'inclusion de `components/decision.html` reçoit
`hide_auto_details=True`. Le composant masque alors seulement la sous-ligne
« Système · règle ». Les badges Validé et Validation automatique, leur infobulle,
les commentaires, les données et l'historique sont conservés. Les autres écrans
utilisant ce composant conservent leur présentation.

## 1. « Confirmé dans Atlas » n'est pas une décision métier

`reconciliation/matching/engine.py::_match_reconciliations` sélectionne les lignes
au statut Atlas `Envoyé SAGE`, puis applique
`reconciliation/matching/exact.py::confirmed_atlas_mask` : pièce comptable,
date comptable et montant Sage confirmé doivent être non nuls après préparation.

`reconciliation/matching/results.py::confirmed_result` produit alors :

- `match_rule = MATCH_CONFIRMED_ATLAS` ;
- `match_status = MATCHED`, `requires_review = False`, une seule ligne Atlas ;
- `sage_amount` égal au montant Sage déclaré dans Atlas ;
- une différence de montants uniquement si le montant projet Atlas est connu.

Cette branche n'exige pas de correspondance avec une écriture de l'extraction
Sage. Son statut cible `Comptabilisé` est une proposition du moteur ; il ne vaut
pas validation persistante. La création de l'auto-validation conserve d'ailleurs
le statut BAP source via `KEEP`, plutôt que d'appliquer ce statut cible.

## 2. Conditions supplémentaires du moteur et du JSONL

`reconciliation/auto_validation.py::proposal_metadata` exige cumulativement :

1. configuration activée et règle ou statut final autorisé ;
2. statut final `MATCHED` ;
3. règle parmi `MATCH_EXACT`, `MATCH_CONFIRMED_ATLAS` ;
4. aucune revue requise et une seule ligne Atlas ;
5. différence de montants connue, finie et de valeur absolue au plus 0,01.

Pour une ligne confirmée, le dernier critère compare `Total charges projet (€)`
à `Total charges SAGE (€)` présents dans Atlas. Une ligne peut donc être
« Confirmé dans Atlas » avec un montant projet absent ou différent et ne pas
recevoir de demande automatique.

`reconciliation/config.py` autorise actuellement `MATCH_CONFIRMED_ATLAS`,
`MATCH_EXACT` et `MATCH_AMOUNT`, avec activation à `True`. Toutefois,
`MATCH_AMOUNT` reste exclu par la liste de sûreté codée dans `proposal_metadata`
et dans l'import Django : sa présence dans la configuration ne suffit pas.

`reconciliation/exporters/review.py::export_review_bundle` ajoute l'objet
`auto_validation` uniquement si ces conditions passent. L'import Django lit
**cet objet**, pas la configuration actuelle du moteur. Un ancien fichier,
même importé après activation, ne reçoit pas rétroactivement cette demande.
L'absence d'objet n'est pas accompagnée d'un motif détaillé côté moteur.

## 3. Conditions supplémentaires dans Django

`app-suivi-reconciliation/reconciliation/auto_validation.py::apply_automatic_validations`
est appelée à la fin de `campaigns.py::import_campaign`, après les contrôles v3.

### Priorité humaine : blocage explicite

La première règle est exactement :

```python
if line.version and line.validation_source == "MANUAL":
    continue
```

Cela couvre validation, refus **et brouillon enregistré**, sans vérifier ici
si la décision humaine est encore courante. Une décision humaine périmée reste
donc prioritaire et empêche une nouvelle validation automatique.

La migration `0013_linereview_auto_validation_rule_and_more` attribue `MANUAL`
par défaut aux lignes historiques. Une ligne sans décision (`version == 0`)
n'est pas bloquée par ce seul défaut ; une ligne historique déjà décidée l'est.
Une intervention humaine via `review.py::decide` remet explicitement l'origine
à `MANUAL` et efface la règle automatique.

### Refus d'une demande automatique

Pour les lignes non bloquées par la priorité humaine, l'import contrôle :

- objet de métadonnées exactement conforme à la règle du groupe ;
- absence de preuve partagée : plusieurs propositions réclamant le même
  triplet projet, pièce, date sont toutes exclues, même avec des montants différents ;
- statut `MATCHED`, règle sûre et `line.group.lines.count() == 1` ; ce comptage
  porte sur la relation du groupe, sans filtre explicite de campagne ;
- montant projet et total du groupe présents et écart au plus 0,01 ;
- validation par `review.py::decide`, sans acquittement des avertissements,
  sans confirmation manuelle ni confirmation de risque multiple.

Pour `MATCH_CONFIRMED_ATLAS`, le service conserve statut, pièce et date Atlas,
et fixe le montant au total du groupe. Il exige la complétude des quatre champs.
Les preuves pièce/date peuvent être reconstituées depuis Atlas pour cette règle.

En v3, `multiple_review.py::allocation_plan` et `apply_projection` exigent aussi :
pièce résolue dans les contrôles Sage, stratégie standard compatible, calcul
fiable, date présente dans les écritures, absence d'excédent ou de partage
nécessitant une dérogation. Ainsi une preuve locale Atlas peut suffire au
libellé moteur et être insuffisante pour la validation métier v3.
En v2, `apply_projection` ne fait pas ces contrôles multiples.

Les `ValidationError` sont consignées dans `CampaignReview.reasons`. Une nouvelle
ligne reste non validée ; une ancienne validation automatique refusée voit son
empreinte effacée et devient périmée. Les sorties précoces pour priorité humaine
ou absence de métadonnées sur une ligne non automatique n'ajoutent pas de motif.

## 4. Signification de « À réexaminer » et succession des campagnes

`presentation.py::decorate` affiche « À réexaminer » lorsque :

```python
bool(line.version and not is_current(line))
```

`review.py::is_current` compare l'empreinte enregistrée à `signature(line)`.
`source_snapshot` couvre les champs Atlas, règle et statut du groupe, total,
preuves, composition et contexte des multiples. Une modification de libellé,
de BAP, de tiers ou de contexte peut donc suffire, même si la règle moteur reste
« Confirmé dans Atlas » et si le montant semble identique à l'écran.

`campaigns.py::import_campaign` reprend la campagne précédente du même périmètre
et exercice ; au retour d'un exercice, elle peut restaurer sa photographie.
Une validation courante et inchangée est marquée `CARRIED`. Un changement
efface l'empreinte d'une décision existante, tout en conservant état, commentaire
et historique. Une empreinte déjà invalidée n'est pas automatiquement réactivée
par un simple retour aux anciennes données.

`multiple_import.py::finalize_controls` peut également invalider une reprise :
contexte de contrôle modifié, pièce non résolue, risque collectif, excédent,
preuve insuffisante ou écriture partagée. Le passage d'une décision v2 à un
contexte v3 et le retour à un fichier sans contrôles peuvent provoquer une revue.

| Situation au nouvel import | Comportement du code |
| --- | --- |
| Aucune décision, demande valide, contrôles satisfaits | Création d'une décision AUTO validée et historisée. |
| Décision MANUAL inchangée et courante | Décision conservée ; aucune conversion en AUTO. |
| Décision MANUAL périmée, refus ou brouillon enregistré | Aucune auto-validation ; revue humaine nécessaire. |
| AUTO courante avec demande conforme et aucune preuve partagée | Décision conservée, sans nouvel événement de validation. |
| AUTO périmée avec nouvelle demande | Nouvelle tentative soumise à tous les contrôles ; nouvelle décision si elle réussit. |
| AUTO sans nouvelle demande | Empreinte effacée ; motif et événement STALE ; contrôle manuel requis. |
| Nouvelle ligne sans demande ou demande refusée | Pas d'auto-validation ; motif enregistré lorsqu'une ValidationError est levée. |
| Fichier strictement identique déjà importé | Retour immédiat dans `review_import.py::import_bundle` grâce au SHA-256 ; aucune réévaluation. |

Le dernier cas s'applique aussi si la configuration Python a changé depuis la
génération du fichier : il faut produire une nouvelle campagne avec les nouvelles
métadonnées pour déclencher une nouvelle évaluation, tout en respectant la priorité humaine.

## Recommandations, sans modification métier

Pour chaque ligne concernée, comparer `version`, `validation_source`, `state`,
`source_signature`, la photographie précédente, `CampaignReview.comparison`,
`CampaignReview.reasons` et `CampaignGroup.data.auto_validation`. Examiner ensuite
les deux montants Atlas et les contrôles de la pièce. Cela distingue un blocage
humain, une absence de demande moteur, un changement et un refus de contrôle.

Conserver la priorité humaine. Si le métier souhaite autoriser une réévaluation
automatique après un brouillon ou une décision humaine périmée, prévoir un parcours
explicite de remise à l'automatique plutôt que modifier silencieusement cette priorité.

Améliorations éventuelles à faire approuver séparément : exposer tous les motifs
de non-éligibilité, clarifier la configuration `MATCH_AMOUNT`, ajouter des tests
spécifiques aux preuves Atlas confirmées, et examiner la comparaison Django
`Decimal > 0.01` (flottant) ainsi que les montants flottants du moteur à la frontière
exacte d'un centime. Aucune de ces règles n'a été corrigée dans cette intervention.

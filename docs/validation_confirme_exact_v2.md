# Correctifs Confirmé / Exact v2 — 7 novembre 2026

## Complément du 8 novembre : devise d'origine des groupes Exact

Le veto EUR dans `exact_bijection` a été retiré. La devise d'origine Atlas/Sage
(par exemple XOF) ne décrit pas l'unité des champs **Total charges projet (€)**
et **Charges (Dépenses)**, déjà comparés en EUR selon le contrat existant.
Aucune conversion supplémentaire ni modification de montant source n'est ajoutée.
Toutes les vérifications de clé complète, montant signé, tolérance, bijection,
référence, réservation et capacité restent actives.

Le cas 1691538/1691539 est couvert par un export réel du moteur et un import
Django synthétique : 3 926,2706 € / 35,5282 € Atlas, 3 926,27 € / 35,53 € Sage,
devise d'origine XOF, deux réservations distinctes totalisant 3 961,80 €.
Les **14 tests moteur/contrat ciblés** et **12 tests Django v2** passent.
Les comptes de suite complète ci-dessous concernent la vérification du 7 novembre.

Après redéploiement, **régénérer le JSONL et importer une nouvelle campagne** :
l'ancien fichier du 7 novembre ne contient pas l'autorisation AUTO de ce groupe.
Aucun fichier métier ni campagne existante n'a été réécrit pour ce complément.

## Diagnostic avant modification

Le parcours réel est : loaders/transformations Atlas et Sage → règles du moteur
(`matching/exact.py`, `matching/results.py`) → `auto_validation.proposal_metadata`
→ exporteur JSONL v3 → import de nouvelle campagne → validations collectives et
individuelles → `decide` → `apply_projection` / `ControlContribution` → contrôles
globaux et recalcul ciblé du Lot 2.

Trois situations sont distinctes : une preuve absente doit rester bloquée ; une
preuve importée mais non attachée peut être résolue côté serveur ; une preuve
attachée peut être refusée à cause de contraintes de cardinalité trop strictes.

**Confirmé, 1903381** : la proposition contient une preuve locale Atlas mais aucune
candidate Sage. L'écriture existe dans le contrôle/inventaire. L'ancien plan
réservait un montant sans référence Sage ; le contrôle global refusait l'affectation.
Le diagnostic individuel détecte également le BAP divergent :
`BAPPJT261002716` / `BAPPJT26100271601042026`. Une pièce équilibrée n'identifie pas,
à elle seule, l'écriture consommée.

**Exact, 1559564/1559565** : `matching/exact.py` sait déjà classer Exact un groupe
à clé complète et cardinalités égales. Aucune modification de cette règle n'est
nécessaire. En revanche, l'autorisation moteur imposait une ligne Atlas et une
ligne Sage, et Django imposait encore cette unicité individuelle. Le total de
688,88 € ne pouvait pas être utilisé sur chacune des lignes de 652,40 € et 36,48 €.

`entry_ref` est l'empreinte SHA256 de projet, exercice, pièce, journal, ligne
comptable et ligne analytique. Pièce/date seuls ne suffisent pas. Les contrôles
de campagne vérifient les références et les preuves à l'import ; réservations,
versions, signatures et contraintes Lot 2 protègent ensuite les décisions.

## Modifications

### Confirmé : décision humaine et BAP divergent

`validation_evidence.confirmed_manual_evidence` recherche une écriture **unique**
dans le contrôle importé. Elle vérifie projet/exercice, pièce/date, tiers, charges
Sage Atlas et montant signé, puis contrôle l'inventaire et ses signatures lorsqu'il
est présent. La pièce/date/montant saisis ne peuvent pas remplacer une preuve.
Le contrôle lui-même doit avoir une signature cohérente.

Le plan réserve cette référence réelle. Le seul écart BAP ne demande ni commentaire
ni acquittement. C'est le choix validé par l'utilisateur malgré la contradiction
entre le paragraphe A.4 et la recette A1 du prompt. Le BAP reste visible dans le
diagnostic, les avertissements et `ReviewEvent.confirmed_evidence`, avec auteur,
références, différence et contrôles effectués. Aucun BAP source n'est réécrit.

Les autres avertissements et risques continuent à demander les commentaires et
confirmations existants. Une preuve ambiguë exige une sélection explicite dans
le parcours manuel existant ; aucune écriture n'est choisie arbitrairement.
Les critères de l'auto-validation Confirmé ne sont pas assouplis.

### Exact : groupe bijectif et atomique

`reconciliation_contract.exact_assignment.exact_bijection` partage les mêmes
vérifications entre exporteur et Django : clé complète projet/tiers/BAP/libellé,
projet/exercice, pièce/date cohérentes, montants signés compatibles au centime,
références complètes et distinctes, cardinalités et total de groupe.
Une source doit avoir une seule preuve compatible ; une même preuve ne peut
servir deux sources. Deux montants identiques avec plusieurs appariements
possibles sont refusés. Une somme compensée ne prouve jamais la bijection.

`proposal_metadata` permet les cardinalités égales multilignes Exact. L'exporteur
ne publie toutefois l'autorisation AUTO qu'après vérification de la bijection,
en v3 exclusivement. MATCH_AMOUNT et les règles floues restent inchangés.

`exact_collective.apply_exact_groups` prépare les groupes avant les validations
individuelles. Les photographies/revendications sont préchargées ; les groupes
sont traités dans l'ordre de leur clé stable et les sources dans l'ordre de leur
identifiant. Un savepoint englobe toutes les décisions du groupe : une erreur
sur un membre annule toutes les décisions et réservations du groupe.

Chaque ligne conserve un `automatic_assignment` de type `EXACT_GROUP` avec entrée
canonique et signature collective. `exact_entry` et `allocation_plan` revalident
ces éléments et réservent uniquement le montant individuel. Aucun registre ni
modèle nouveau : `ControlContribution`, `ReviewEvent` et les contrôles globaux
existants restent utilisés. Une autre proposition revendiquant la même référence,
une réservation d'inventaire active ou une capacité insuffisante bloque la décision.
Une décision humaine, même brouillon, une correction ou un lien Lot 2 reste prioritaire.

Les anciens validateurs collectifs Confirmé reconnaissent le discriminant Exact
et ne le retraitent pas comme une autorisation de pièce Confirmé. Les exemptions
de partage restent propres à leur catégorie ; plusieurs écritures distinctes
d'une même pièce peuvent être réservées sans réutiliser une référence.

La tolérance individuelle déjà prouvée peut être transmise au contrôle global
par une attestation **serveur** ciblée des nouvelles affectations. Elle autorise
un écart signé d'au plus la tolérance pour une seule écriture réelle, sans nouvelle
fraction ni dispense de contrôle de capacité. Sans cette attestation, le contrat
historique de consolidation conserve son comportement. Les montants et références
répétés restent bloqués.

## Périmètre : nouvelles campagnes uniquement

Le nouveau JSONL reste en **schema_version 3** et ajoute dans son en-tête :

```json
"validation_policy": "confirmed-exact-v2"
```

C'est une extension additive minimale, sans migration. Django n'active les deux
nouveaux parcours que si cette politique est présente. Les anciens JSONL restent
lisibles et conservent leurs règles. Une campagne déjà importée ne reçoit pas ce
marqueur lors du déploiement : ni consultation ni décision ne l'active rétroactivement.

Il faut **relancer le moteur, produire un nouveau fichier et importer une nouvelle
campagne de recette**. Aucune commande de réévaluation, backfill, tâche automatique,
suppression/réinitialisation, ni modification du service de persistance Lot 2.
Les campagnes historiques et leurs décisions restent intactes. Le protocole de
report existant est réutilisé sans modification ; les signatures des nouvelles
affectations sont photographiées pour éviter les événements AUTO en double.

## Tableau fonctionnel

| Situation | Résultat | Garde-fou |
|---|---|---|
| Confirmé, seul BAP divergent, preuve réelle unique compatible | Manuel avec avertissement, sans commentaire obligatoire | Preuve serveur, signature, réservation et capacité |
| Confirmé admissible à l'ancien AUTO | AUTO existante conservée | Critères collectifs Confirmé inchangés |
| Confirmé sans preuve ou avec plusieurs possibilités | Bloqué / sélection explicite à effectuer | Aucun choix par total ou numéro saisi |
| Confirmé avec autre anomalie majeure | Bloqué, ou justification existante lorsque le service l'autorise | Aucun veto comptable supprimé |
| Exact 652,40 + 36,48, preuves distinctes à clé complète | AUTO du groupe entier | Bijection, références individuelles et transaction |
| Exact avec montants répétés ambigus ou référence réutilisée | Pas d'AUTO | Unicité dans les deux sens |
| Exact avec décision humaine/correction/lien préexistant | Pas de nouvelle AUTO collective | Priorité humaine et reprise existante |
| Erreur sur un membre, capacité dépassée ou contrôle incertain | Tout le groupe refusé | Savepoint et projections existantes |
| Ancienne campagne / ancien JSONL sans politique | Comportement historique | Aucun recalcul rétroactif |

## Commandes vérifiées et protocole de recette

Utiliser **une base locale jetable ou une base de recette dédiée déjà configurée**.
L'import ci-dessous cible la base configurée par Django : il ne crée pas une base
isolée à lui seul. Ne pas lancer ces commandes d'import sur la production.
La sélection PostgreSQL par `POSTGRES_DB` et les autres paramètres de connexion
restent inchangés.

Depuis la racine du dépôt, ce générateur écrit uniquement des données fictives et
exécute le vrai moteur (les identifiants reproduisent les cas, les sources sont fictives) :

```powershell
.\.venv\Scripts\python.exe -m examples.validation_v2_fixture .\data\recette_confirm_exact_v2
```

Pour rejouer explicitement le moteur sur ces fichiers et produire une autre campagne :

```powershell
.\.venv\Scripts\python.exe -m reconciliation.main --atlas .\data\recette_confirm_exact_v2\atlas.xlsx --sage .\data\recette_confirm_exact_v2\sage.csv --year 2026 --campaign-name "Recette Confirme Exact v2 2026-11-07" --campaign-scope atlas-complet --review-output .\data\recette_confirm_exact_v2\nouvelle_campagne.jsonl
```

Les options sont celles du parseur `reconciliation.main`. Avec les données métier,
remplacer les deux chemins d'entrée et choisir une **nouvelle sortie** ; aucune
réexécution des extractions métier n'a été déclenchée pendant ce développement.

Importer ensuite dans l'environnement de recette dédié :

```powershell
Set-Location app-suivi-reconciliation
..\.venv\Scripts\python.exe manage.py import_review_bundle ..\data\recette_confirm_exact_v2\nouvelle_campagne.jsonl
```

La commande existante a été testée sur une base jetable. Elle utilise le staging
pour SQLite sur disque et la transaction ORM pour PostgreSQL. Une base de recette
neuve doit avoir reçu les migrations existantes ; ce correctif n'en ajoute aucune.

Vérifier en lecture seule :

```powershell
..\.venv\Scripts\python.exe manage.py shell -c "from reconciliation.models import Campaign; c=Campaign.objects.get(is_current=True); print(c.name); print(list(c.reviews.values_list('source__source_id','decision__state','decision__validation_source')))"
```

Résultat attendu : deux groupes importés, trois lignes ; `1559564` et `1559565`
AUTO avec 652,40 € et 36,48 €, deux références distinctes et 688,88 € au total.
`1903381` reste à décision humaine ; Valider avec les valeurs source compatibles
réserve 8 820 € et trace le BAP divergent même sans commentaire.

Le nom de campagne n'est pas une clé unique (longueur maximale 200 caractères).
Le fichier est idempotent par SHA256 : importer exactement les mêmes octets ne
crée pas une autre campagne. Une nouvelle génération contient un nouvel horodatage.
Le périmètre doit rester cumulatif et identique au périmètre actif ; l'année et
la publication courante suivent les règles d'import existantes. Aucune campagne
antérieure ni décision métier ne doit être supprimée pour effectuer la recette.

## Traçabilité et fonctions

| Exigence | Fonctions / modules | Tests |
|---|---|---|
| A1 preuve non attachée et BAP divergent | `confirmed_manual_evidence`, `decide`, `allocation_plan` | `test_manual_confirmed_bap_difference_is_audited_without_comment` |
| A2/A3 preuve absente/ambiguë, égalité insuffisante | Résolveur serveur, contrôles signés | `test_confirmed_missing_or_ambiguous_evidence_stays_blocked` |
| A4 AUTO Confirmé inchangée | Validateur collectif existant, résolution limitée au manuel | Fixture réelle : Confirmé reste DRAFT ; suites collectives existantes |
| B1/B2 attribution et références distinctes | `exact_bijection`, `validate_exact_group`, projection | `test_engine_jsonl_and_exact_group_individual_reservations`, tests purs de référence répétée |
| B3/B4 ambiguïtés et clé complète | Contrat pur partagé | Tests paramétrés `test_incompatible_entry_blocks_group`, répétitions et export sans autorisation |
| B5/I2/I3 décisions humaines et historique | Savepoint et protocole de report existant | `test_human_priority_and_old_campaign_immutability`, `test_policy_does_not_change_old_campaign_manual_path` |
| B6 atomicité | `apply_exact_groups` → `decide` | `test_second_member_error_rolls_back_entire_exact_group` |
| B7 ordre et volume | Préchargement, tri stable, montants individuels | `test_group_order_does_not_change_attribution`, `test_large_group_does_not_query_inventory_for_every_member` |
| I1 moteur/export/import réel | Générateur et commande existante | `test_management_import_command_accepts_generated_bundle`, exporteur réel en pytest |
| Idempotence / persistance | Empreinte de source et snapshots existants | `test_identical_new_campaign_carries_without_duplicate_events` |
| Tolérance ciblée sans élargissement historique | `campaign_controls`, `consolidate` | Tests du centime et attestation/absence/double référence |

L'[inventaire des docstrings](validation_confirme_exact_v2_docstrings.md) liste
chaque fonction/classe nouvelle ou modifiée et son rôle. Les sources Atlas/Sage,
le service `business_carry`, les paramètres de connexion et les écrans ne sont
pas modifiés. Les nouveaux modules sont `exact_collective.py`,
`validation_evidence.py`, le contrat pur `exact_assignment.py` et les recettes A/B.

## Limites de recette

Les écritures de même montant sans discriminant unique restent manuelles. Les
preuves incomplètes, les dates/pièces incompatibles, les conflits de réservation
et les contrôles incertains restent bloquants. Les groupes très volumineux gardent
le coût des décisions/audits existants ; aucun chargement complet de l'inventaire
n'est ajouté par membre. La recette de 30 membres vérifie moins de 15 lectures
d'inventaire Sage pendant l'import, sans contourner les services de décision.

L'exécution PostgreSQL en production et sa concurrence nécessitent la recette
dédiée ; les tests locaux utilisent SQLite. Aucun déploiement, import métier,
suppression de décision ou migration de la base applicative n'a été effectué.

## Vérifications exécutées

- `.venv/Scripts/python.exe -m pytest -q` : **205 réussis, 1 ignoré**, dont 13 nouveaux
  cas purs/moteur/contrat. L'ignoré concerne la recette sur sources réelles optionnelles.
- Depuis l'application : `../.venv/Scripts/python.exe manage.py test --noinput
  --verbosity 0` : **284 tests, succès, 3 ignorés**. La concurrence PostgreSQL
  nécessite une base dédiée et n'a pas été exécutée dans cet environnement SQLite.
- Après ajout du scénario de volume et le dernier ajustement de sérialisation :
  `manage.py test reconciliation.test_validation_v2 --noinput --verbosity 0` :
  **11 tests réussis**, dont import via commande réelle, erreur tardive, report,
  preuve BAP, tolérance et groupe de 30 membres.
- L'ancien lot ciblé `test_autovalidation_correctif test_collective_validation
  test_business` avait également passé ses **70 tests** avant la suite complète.
- Dernière vérification après limitation du préchargement aux groupes multilignes :
  `manage.py test reconciliation.test_validation_v2 reconciliation.test_autovalidation_correctif
  reconciliation.test_collective_validation reconciliation.test_business --noinput
  --verbosity 0` : **81 tests réussis**.
- `makemigrations --check --dry-run` : aucune migration manquante.
- `git diff --check` : aucune erreur d'espacement.
- Inventaire AST du diff : **46 définitions nouvelles/modifiées**, aucune
  docstring absente. Les fonctions concernées sont documentées en français.

Les fichiers locaux de la recette générée ont été nettoyés après vérification ;
le générateur et les tests reproductibles restent versionnables dans le dépôt.

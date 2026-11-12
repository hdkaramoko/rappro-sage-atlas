# Cadrage exhaustif et exception ODA — 12 novembre 2026

## Règle et flux des montants

```text
JSONL v3 → inventaires Atlas/Sage immuables + exclusions de campagne
         → contrôles courants, corrections et confirmations existantes
         → Atlas retenu : Comptabilisé corrigé/non exclu + Envoyé réellement confirmé
         → Sage retenu  : toutes les écritures éligibles du projet/exercice
         → groupes et types → projet → écart Atlas − Sage → état de cadrage
```

L’ancien `accounting.refresh_project()` retenait Sage seulement si le contrôle
possédait des sources Atlas ou des confirmations (`bound`). La ligne
`retained_sage = item["amount"] if bound else ZERO` retirait donc les Sage sans
rattachement. Elle est remplacée par la somme éligible inconditionnelle. Le
compteur et le montant « Sage sans rattachement » restent explicatifs, inclus
dans Sage retenu, sans seconde addition.

Les écritures éligibles sans numéro de pièce ou clé ODS complète restent dans
le total si projet, exercice et montant sont connus. Seuls les types/exclusions
déjà enregistrés dans la campagne retirent des montants Sage. Les lignes
comptables distinctes ne sont pas fusionnées parce qu’elles partagent un montant,
un tiers ou une pièce.

Les montants Atlas initiaux ne sont pas changés. Les corrections/exclusions de
doublons Atlas et les confirmations effectives restent traitées par les services
existants. Une exclusion de doublon **Atlas** ne supprime jamais l’écriture Sage.
Les Envoyé non confirmés ne contribuent pas au retenu. Une valeur manquante dans
leur montant initial peut rendre le poste initial inconnu, sans rendre le total
retenu inconnu à elle seule.

Les types Sage explicitement exclus restent tracés avec le montant Atlas hors
comparaison. Pour un groupe commun ODS/ODG partiellement exclu, seule la part
Atlas du type explicitement exclu est retirée ; les règles de rapprochement ODS
elles-mêmes ne sont pas assouplies.

La fonction `accounting_state()` est **inchangée** : écart Decimal quantifié au
centime selon l’arrondi existant ; CADRE lorsque cet écart est nul, NON_CADRE
sinon, INSUFFISANT en présence d’un réel blocage. Aucune tolérance de ±1 € ni
nouvelle tolérance de matching n’est introduite. Le diagnostic de pièce utilise
la tolérance de contrôle déjà enregistrée dans `campaign.metadata`.

## Totaux fiables et diagnostics individuels

Les causes précédemment bloquantes ont été séparées :

| Cause | Effet sur le projet |
| --- | --- |
| Tiers/libellé/clé ODS absent, correspondance non unique, preuve individuelle ambiguë | Diagnostic conservé ; totaux calculables si montants et périmètre connus |
| Référence technique répétée avec contenus différents | Toutes les occurrences restent comptées ; ambiguïté signalée |
| Référence complète et contenu canonique strictement identiques | Une seule occurrence financière ; doublon technique neutralisé et compté |
| Montant Sage éligible absent | INSUFFISANT, jamais converti arbitrairement en zéro |
| Montant d’un type explicitement exclu absent | Poste exclu inconnu ; total éligible non bloqué par ce seul motif |
| Projet/exercice Sage indéterminable ou incompatible avec la campagne | INSUFFISANT |
| Montant Atlas comptabilisé indispensable absent, sémantique non confirmée | INSUFFISANT |
| Inventaire essentiel incomplet/indisponible, conflits Atlas ou dates Sage invalides signalés à l’extraction | INSUFFISANT |

L’ancien veto reposait notamment sur une clé composite incomplète, une référence
répétée et des recherches de mots tels que « absent », « incomplet » ou « modifié »
dans les motifs du contrôle. Il ne transforme plus automatiquement ces anomalies
individuelles en impossibilité de calculer tout le projet.

Le dédoublonnage exige une identité technique **complète** et le même contenu
canonique, montant et éligibilité. Deux observations de la même écriture peuvent
différer par leur empreinte de collecte et être neutralisées si cette preuve est
complète. Une collision d’identité avec contenu différent n’est pas neutralisée.
Les inventaires originaux et leurs signatures restent inchangés.

Les sommes sont réalisées en Decimal. Le montant canonique Sage est extrait du
JSON comme texte par l’ORM, sans décodage Python du JSON complet de chaque ligne :
cela évite la limitation SQLite à quinze chiffres significatifs. Les totaux exacts
projet/type/groupe sont aussi conservés comme chaînes dans les JSON de projection.
L’audit compare ces valeurs, sans `SUM` flottant SQLite et sans augmenter la
tolérance pour masquer des écarts numériques. Les colonnes Decimal SQL restent
les projections existantes utilisées pour les listes et filtres.

## Exception ODA

L’analyse a établi que le contrôle comptabilisé standard se regroupe déjà par
**projet + exercice + pièce**, sans tiers dans sa clé. Le contrôle collectif strict
tiers/BAP de `piece_coherence` concerne les **Envoyé SAGE** et participe à leur
cascade de validation : il n’est pas modifié dans ce lot.

Le nouveau diagnostic ODA s’applique seulement aux sources **Comptabilisé**, avec
pièce ODA connue et au moins un tiers Atlas null, vide ou `NA`. Il compare :

- projet, exercice, pièce et cohérence des dates ;
- sommes signées selon la tolérance de contrôle existante ;
- identité complète et unique des écritures, identifiants Atlas distincts,
  journal non ambigu, cardinalités et unicité des montants individuels ;
- tiers renseignés : ils restent obligatoirement concordants pour les lignes
  qui en possèdent un, même si une voisine porte NA ;
- affectations déjà présentes : elles imposent de conserver le contrôle métier
  individuel et empêchent d’annoncer le diagnostic individuel comme fiable.

La recherche individuelle utilise des index de montants triés, avec et sans tiers,
et une recherche dichotomique ; aucun produit croisé des lignes de la pièce.
Les occurrences identiques restent concurrentes, sans sélection arbitraire.

L’interface affiche **« Tiers Atlas absent/NA, contrôle sur pièce »**, puis
« contrôle individuel fiable » ou les raisons d’une revue nécessaire. Un total
projet peut être CADRE alors que ce diagnostic individuel reste à revoir : ces
deux informations répondent à des questions différentes.

Ce diagnostic ne modifie **aucune source, correspondance, affectation, décision
ou autorisation AUTO**. Il ne s’applique ni aux autres types, ni aux ODA sans
pièce, ni à la cascade des Envoyé. Il apparaît dans le détail de cadrage et dans
la fiche du contrôle lié, sans recalcul sur GET.

## Recalculs, ventilation et performances

Les hooks existants restent actifs : `business.recalculate()` recalcule ses clés
métier ciblées, puis appelle `refresh_project()` pour les projets affectés.
Validation, refus, annulation, correction et exclusion Atlas changent le retenu
Atlas, sans changer le total Sage éligible de la campagne.

Les groupes de Sage seuls sont des postes normaux du cadrage et de ses filtres
« Avec écart ». Ils ne sont plus libellés « Hors périmètre ». Seuls les types
explicitement exclus conservent ce libellé. Les diagnostics restent consultables
dans « Périmètre et données disponibles » et sur la fiche de contrôle.

Si un contrôle technique manque alors que ses inventaires existent, il est créé
par lots depuis ces mêmes inventaires pour porter un détail stable. Les contrôles
existants ne sont pas remplacés. Les corrections/liens d’inventaire sont projetés
avec `business_inputs()`, sans relancer le matching ou une décision. Le contrôle
initial reconstruit est clairement marqué comme tel. Le test de 2 000 écritures
ajoutées après import vérifie des INSERT bornés par lots, le budget historique
hors ces INSERT indispensables et des recalculs métier limités aux clés ciblées.

Un retenu Comptabilisé retiré des projections par un lien périmé reste attribué
à sa **propre pièce source**, avec diagnostic. Aucune pièce Sage n’est choisie
par montant pour combler un résidu. Les montants des groupes et des types doivent
retrouver ceux du projet, sans additionner une seconde fois le poste sans lien.

Les inventaires sont parcourus par projet ; l’objet campagne est réutilisé pour
éviter le décodage de ses métadonnées à chaque ligne. Le JSON Sage complet est
chargé seulement pour ODA et les identités répétées à expertiser. Les écritures
SQL sont groupées et les index existants réutilisés. Aucun nouvel index, modèle
ou migration n’est ajouté. La maintenance existante des statistiques SQLite est
conservée, hors transaction d’import privé, et reste inopérante sur PostgreSQL.

## Déploiement : aucun nouveau JSONL nécessaire

Le fichier `data/outputs/campagne_12112026.jsonl` possède déjà projet, année,
pièce, tiers et montants, ainsi que l’inventaire Sage complet. Aucune évolution
du format JSONL, du moteur ou du contrat signé n’est nécessaire à ce lot.

- **Nouvel import** après déploiement : les nouveaux agrégats sont construits avec
  la nouvelle règle par le parcours normal, y compris le staging SQLite.
- **Campagne déjà importée** : reconstruire explicitement ses seuls agrégats.
  Aucun recalcul rétroactif automatique de décisions n’est ajouté.
- Les anciens agrégats restent consultables avec un avertissement de reconstruction
  et ne sont pas présentés comme utilisant déjà le périmètre exhaustif.

Procédure recommandée : activer la maintenance, vérifier la fin des traitements,
faire une sauvegarde/copie cohérente, déployer, tester la reconstruction sur la
copie, comparer les résultats puis appliquer sur la base voulue. Depuis
`app-suivi-reconciliation`, dans l’environnement et avec la base du déploiement :

```powershell
python manage.py prepare_accounting --campaign ID
```

Sans `--campaign`, la commande choisit la campagne courante publiée. Elle maintient
les statistiques SQLite si nécessaire, affiche sa progression par projet et ne
modifie pas les sources, mots de passe, permissions ou décisions. `--force-statistics`
reste disponible pour forcer explicitement ANALYZE sur SQLite. PostgreSQL suit
les mêmes règles ORM ; ne pas annoncer une recette PostgreSQL réelle sans base dédiée.

La base locale de travail était vide lors de l’analyse. Elle n’a pas été importée
ou reconstruite. L’audit utilise une **nouvelle copie privée** d’une préparation
publiée du 11 novembre, représentative mais distincte du nouveau JSONL du 12.

## Fonctions de production créées ou modifiées

| Fichier | Fonctions | Responsabilité |
| --- | --- | --- |
| `reconciliation/accounting.py` | `refresh_project` | Périmètre exhaustif, blocages réels, diagnostics, totaux et ventilation |
| `reconciliation/accounting_scope.py` | `ensure_controls`, `sage_scope`, `restore_unprojected` | Détails manquants, inventaire Sage et résidus Atlas tracés |
| `reconciliation/accounting_oda.py` | `missing_party`, `amount_indexes`, `near_entries`, `oda_diagnostic` | Exception diagnostique ODA avec contrôle d’identité et index de montants |
| `reconciliation/accounting_views.py` | `accounting_detail` | Filtre des Sage seuls, compatibilité des anciennes projections |
| `reconciliation/global_views.py` | `global_control_detail` | Jointure du diagnostic ODA préparé en lecture seule |

Les chemins ci-dessus sont relatifs à `app-suivi-reconciliation`. `prepare_campaign`,
`accounting_state`, les modèles, la commande de préparation, les règles de
matching et les services de décision restent inchangés. Les deux templates de
détail, le README et les guides de cadrage sont mis à jour.

## Matrice exigences → code → tests

| Exigence | Code principal | Tests |
| --- | --- | --- |
| Sage relié 1000 + Sage seul 200 = 1200 | `sage_scope`, `refresh_project` | `test_unattached_sage_is_included_once` |
| Type explicitement exclu, montant inconnu exclu | mêmes fonctions | `test_explicit_exclusion_remains_outside_sage`, `test_excluded_null_amount_does_not_block_eligible_total` |
| Deux vrais 500 distincts, doublon technique prouvé | `sage_scope` | `test_distinct_equal_entries_are_both_counted`, `test_proven_duplicate_only_is_neutralized` |
| ODA NA/vide/null, sources préservées | `oda_diagnostic` | `test_oda_missing_party_uses_document_without_mutation` |
| ODA déséquilibrée, montants concurrents | `amount_indexes`, `near_entries` | `test_oda_mismatch_and_repeated_amounts_do_not_authorize` |
| Pièce absente, autre projet, identité incomplète | `oda_diagnostic` | `test_missing_atlas_piece_does_not_force_oda_identification`, `test_oda_other_project_or_incomplete_identity_never_authorizes` |
| Tiers renseignés divergents, autres règles inchangées | `oda_diagnostic` | `test_exception_not_applied_to_known_parties_or_sent`, `test_oda_known_party_mismatch_is_not_hidden_by_missing_neighbor` |
| ODS sans tiers, vrai montant/périmètre inconnu | `refresh_project` | `test_ods_missing_party_is_diagnostic_only_when_totals_known`, `test_unknown_scope_stays_insufficient` |
| Actions, liens périmés, Sage stable | hooks existants + `restore_unprojected` | `test_accounting`, `test_business`, `test_stale_projection_restores_atlas_to_its_source_group` |
| Signes, neuf décimales, sommes et idempotence | totaux JSON Decimal | `test_signed_decimals_and_rebuild_are_idempotent`, `test_nine_decimals_remain_exact_above_sqlite_significant_precision` + audit intégral |
| Campagnes successives et historique | hooks et `prepare_campaign` existants | `test_explicit_historical_preparation_preserves_decisions_and_old_results`, tests de campagnes/reprises |
| Performance, permissions, import/staging, filtres | services et vues | tests du cadrage/UX, de coût avec 2 000 Sage seuls, suite Django et moteur |
| Groupe ODS/ODG partiellement exclu | `refresh_project` | `test_mixed_ods_types_respect_only_explicit_exclusion` |

Les noms non préfixés sont dans `reconciliation/test_accounting_exhaustive.py`.
Les tests existants ont été adaptés uniquement aux nouveaux montants exhaustifs
(par exemple les 50 Sage seuls de la recette Lot 1 restent désormais dans l’écart).

## Audit reproductible sur copie

Depuis la racine, avec un chemin de source SQLite explicite :

```powershell
.venv/Scripts/python.exe -m examples.audit_accounting_exhaustive --source CHEMIN_BASE_COPIE --output docs/cadrage_exhaustif_comparaison.json
```

Le script copie la source ouverte `mode=ro` via SQLite backup dans un répertoire
temporaire, maintient ses statistiques, exécute la version `accounting.py` de HEAD
puis celle du workspace sur cette seule copie. Il mesure `prepare_campaign` et
les appels `refresh_project`, signe inventaires/décisions avant/après, vérifie
les sommes par groupes/types et anonymise les codes projet. Il faut donc lancer
cette comparaison **avant de committer l’évolution** ; après commit, choisir une
référence avant/après adaptée plutôt que prétendre comparer deux versions identiques.

Le rapport JSON associé contient les états, les variations Sage, les projets
modifiés et leurs motifs, ainsi que tous les anciens INSUFFISANT, y compris ceux
qui le restent. Les nombres financiers y sont des valeurs de cadrage ; aucune
identité personnelle, mot de passe ou code projet réel n’y est publié. La copie
est fermée puis nettoyée ; la source et la base de travail ne sont pas écrites.

### Résultats de l’audit représentatif

Copie de la campagne publiée du **11 novembre 2026** : **1 620 projets,
355 793 lignes Atlas et 498 224 écritures Sage**. Le fichier du 12 novembre
n’est pas importé par cet audit.

| État projet | Avant | Après |
| --- | ---: | ---: |
| CADRE | 1 314 | 1 054 |
| NON_CADRE | 116 | 521 |
| INSUFFISANT | 190 | 45 |

Les **45 blocages restants** proviennent tous de montants Atlas comptabilisés
sources/retenus absents, et non de la seule clé ODS ou d’un tiers absent.
**145** anciens blocages individuels cessent de rendre le projet insuffisant.
Un projet peut devenir NON_CADRE lorsque les Sage autrefois exclus faute de
rattachement entrent dans le comparateur : c’est un écart réel à examiner.

Le total Sage des postes calculables passe de **279 219 296,88 €** à
**451 704 858,36 €**, soit **+172 485 561,48 €**. **568 projets** changent
de montant affiché ou d’état ; 561 présentent une variation numérique du Sage
retenu, et 145 une modification des motifs bloquants (ces catégories se recoupent).
La liste et les justifications sont dans
[le rapport comparatif anonymisé](cadrage_exhaustif_comparaison.json).

Le diagnostic ODA est présent sur **131 182 groupes** de cette copie :
**131 158** contrôles individuels fiables et **24** revues individuelles à
conserver. Il n’a créé aucune décision ni autorisation automatique.

Les empreintes des inventaires et décisions sont **identiques** avant/après.
La réconciliation exacte des groupes et types avec leurs projets ne présente
**aucune différence**. Aucun montant source Atlas n’est modifié.

Mesure indicative unique, sur la même copie avec statistiques actualisées :

| Mesure | Avant | Après |
| --- | ---: | ---: |
| Préparation complète | 91,549 s | 97,125 s |
| Requêtes SQL | 26 535 | 25 418 |
| `refresh_project` médiane | 17,736 ms | 17,380 ms |
| `refresh_project` p95 | 275,850 ms | 315,683 ms |
| `refresh_project` maximum | 731,241 ms | 752,413 ms |

Le surcoût complet mesuré est de **5,576 s (6,1 %)** pour l’exhaustivité et le
diagnostic ODA. La collecte ANALYZE sur copie prend séparément **1,129 s**.
Ce résultat local ne prédit pas les temps PostgreSQL ni ceux du nouveau fichier
du 12 novembre ; l’ordre avant/après et les caches système influencent une
mesure unique. Aucune optimisation d’index ou de durabilité hors périmètre
n’a été ajoutée.

### Vérifications exécutées

- `python manage.py test --noinput` : **420 tests recensés, 417 réussis,
  3 ignorés**, en **177,758 s**. Les tests ignorés exigent un serveur PostgreSQL
  de test (import, réservations concurrentes et verrouillage de lignes), non
  disponible dans cette recette locale.
- `python manage.py test reconciliation.test_accounting_exhaustive --noinput` :
  **18 tests réussis**, y compris le contrôle final des postes réellement inconnus.
- Depuis la racine, `.venv/Scripts/python.exe -m pytest tests -q` :
  **293 réussis, 1 ignoré**, en 11,39 s. Le cas ignoré est l’intégration métier
  nécessitant l’activation explicite `RECONCILIATION_REAL_TESTS=1` ; il n’est pas
  annoncé comme exécuté. L’audit réel de cadrage sur copie ci-dessus a bien été exécuté.
- `makemigrations --check --dry-run` : aucune migration manquante ; `manage.py check` :
  aucune anomalie.
- Ruff, règles F, sur les nouveaux modules de calcul/audit et les fichiers
  principaux modifiés : réussi ; docstrings françaises de toutes les définitions
  nouvelles et modifiées vérifiées ; `git diff --check` : aucune erreur d’espacement.

La base locale reste vide et inchangée (aucune campagne importée pour la recette).
Les essais d’écriture utilisent exclusivement les bases de test et les copies
temporaires. Les comptes et droits de l’application ne sont pas modifiés.

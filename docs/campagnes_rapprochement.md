# Campagnes de rapprochement : utilisation, contrat et conception

**Évolution du 24 septembre 2026 :** le [guide des multiples Atlas, affectations et exports](multiples_atlas_affectations_export.md) décrit le contrat JSONL v3, le contrôle des Comptabilisé, la projection des validations et le nouvel audit. Il complète et, pour ces points, remplace les règles antérieures de ce document.

Implémentation du 20 septembre 2026. Ce document complète et actualise les [choix du moteur](documentation_technique_rapprochement.md) et les [choix de l'application](documentation_technique_application.md).

**Complément annuel :** le [guide du filtre annuel et des portefeuilles](filtre_annuel_et_portefeuilles.md)
décrit `--year`, la comparaison avec la précédente campagne du même exercice et le référentiel
de projets dérivé des inventaires. L'année est maintenant une dimension explicite du périmètre
de comparaison ; la campagne de travail reste unique et correspond au dernier import réussi.

## 1. Ce qui change pour le métier

Chaque nouveau rapprochement importé devient une campagne nommée. La campagne courante alimente « Mes rapprochements » et le tableau de bord. Les campagnes précédentes restent consultables dans **Campagnes**, avec les sources, propositions, preuves et décisions qui leur appartiennent. Il n'y a pas de restauration d'une ancienne base ni de modification d'une campagne close depuis les écrans.

Une campagne réunit désormais deux populations :

- **Inventaire Atlas** : toutes les lignes après chargement et déduplication, quel que soit leur statut.
- **Propositions** : les lignes « Envoyé SAGE », y compris celles sans correspondance ou avec ambiguïté.

Cela distingue une ligne réellement absente de l'extraction d'une ligne toujours présente mais passée à « Comptabilisé » et donc sortie du matching.

### Lecture des différences

| Indication | Sens |
| --- | --- |
| Nouvelle ligne | Identité projet/année/Id non présente dans l'inventaire précédent |
| Inchangée | Les huit champs de l'inventaire sont identiques après normalisation |
| Modifiée | Au moins un champ a changé ; les anciennes et nouvelles valeurs sont affichées |
| Absente de l'extraction | La ligne était connue, mais n'est pas reçue dans l'inventaire courant |
| Réapparue | Une ligne précédemment absente revient dans l'extraction |
| Validation reprise | La décision validée reste applicable au contexte de la nouvelle campagne |
| À revoir | Le contexte source, la proposition, les preuves ou les membres du groupe ont changé |

Une absence est conservée dans les inventaires suivants tant que la ligne ne revient pas. Elle n'efface jamais la source historique ni les anciennes décisions. Un changement de projet, d'année ou d'Id est traité comme une nouvelle identité et une absence de l'ancienne, sans rapprochement implicite entre les deux.

Les différences d'inventaire et de proposition répondent à des questions distinctes : les montants Atlas peuvent être inchangés alors que de nouvelles preuves SAGE modifient la proposition.

## 2. Produire et importer une campagne

Depuis la racine `scriptsRappro`, adapter les chemins aux extractions disponibles :

```powershell
uv run python -m reconciliation.main --atlas data/inputs/JDD.xlsx --sage data/inputs/ZLISTPJT.csv --output data/outputs/rapprochement.xlsx --review-output data/outputs/campagne.jsonl --campaign-name "Septembre 2026" --campaign-scope "atlas-complet"
```

Le classeur Excel reste une sortie d'analyse. Le fichier **campagne.jsonl** est l'unique fichier à importer dans l'application : il contient inventaire et propositions, ce qui empêche d'associer involontairement deux exécutions différentes.

`--campaign-name` est facultatif : le moteur construit un nom avec la date UTC. `--campaign-scope` vaut `atlas-complet` par défaut. Cette valeur doit désigner un périmètre cumulatif stable, identique d'une campagne à la suivante. L'application refuse un changement de périmètre afin de ne pas interpréter une extraction partielle comme des disparitions.

Cette vérification porte sur le périmètre déclaré : le logiciel ne peut pas deviner qu'un fichier étiqueté « complet » a été téléchargé partiellement. Les anomalies d'absence permettent précisément de l'identifier. Il n'y a qu'une campagne courante globale ; la gestion de plusieurs périmètres indépendants simultanés n'est pas implémentée.

Dans l'application :

1. L'administrateur utilise « Importer un rapprochement » et choisit le JSONL.
2. Le worker vérifie le fichier, compare l'inventaire et prépare les photographies.
3. La nouvelle campagne n'est publiée que si tout l'import réussit.
4. « Campagnes » permet de consulter l'inventaire, filtrer les anomalies et retrouver les décisions.
5. Les utilisateurs traitent les lignes de la campagne courante dans « Mes rapprochements ».
6. L'export porte sur les validations valables pour la campagne choisie et le périmètre autorisé de l'utilisateur.

Un fichier strictement identique à un import déjà réussi reste ignoré par le mécanisme d'empreinte du worker. Un nouvel export du moteur contient une nouvelle date de génération et peut donc représenter une nouvelle campagne même si ses données métier sont identiques ; les validations sont alors reprises.

## 3. Inventaire minimal : les huit champs

| Champ | Pourquoi le conserver |
| --- | --- |
| Code projet | Périmètre métier et identité |
| Année | Identité de la ligne dans l'application |
| Id | Identifiant Atlas |
| Statut BAP | Distinguer présence dans Atlas et éligibilité au matching |
| Total charges projet (€) | Détecter une évolution du montant rapproché |
| Total charges SAGE (€) | Détecter l'apparition ou la modification d'un montant comptable dans Atlas |
| N° pièce SAGE | Expliquer une évolution comptable |
| Date comptable | Expliquer une évolution comptable |

L'inventaire est contrôlé et normalisé : projet en majuscules, identifiants non vides, année entière entre 2000 et 2200, dates ISO, montants décimaux finis normalisés au centime. Une valeur absente reste distincte de zéro. Les huit clés doivent être présentes ; les champs comptables peuvent contenir `null`.

Ce périmètre minimal ne prétend pas comparer tous les libellés et tiers des lignes hors matching. Pour les lignes rapprochées, les sources canoniques complètes et les preuves sont également photographiées ; leur empreinte métier couvre les éléments déterminants pour la décision.

## 4. Report des validations : date, auteur, origine

Le report exige une revue présente dans la campagne immédiatement précédente, une décision validée encore actuelle et une empreinte de contexte identique. L'application conserve alors :

- les modes KEEP / SET / CLEAR et les valeurs choisies ;
- le commentaire et l'auteur ;
- la date de validation métier ;
- la campagne de validation d'origine, même après plusieurs reports successifs.

Exemple : une validation faite le 12 septembre, reprise en octobre puis en novembre, reste affichée avec la date du **12 septembre** et l'origine **campagne de septembre**. Aucun nouvel événement ne prétend qu'un utilisateur a revalidé lors de l'import. La photographie de chaque campagne matérialise ce report.

Si le contexte change, les anciennes valeurs restent disponibles pour aider à la revue, mais la signature de validation est invalidée et la ligne est exclue des corrections validées. Une nouvelle validation reçoit une nouvelle date et prend la campagne courante comme origine.

Les brouillons et refus sont également conservés comme travail antérieur ; l'étiquette « Validation reprise » est réservée aux validations applicables. Une ligne ayant disparu puis réapparaissant ne récupère pas automatiquement une ancienne validation, même si ses valeurs reviennent exactement à leur état ancien.

### Contexte individuel et collectif

L'empreinte inclut les champs critiques Atlas, la règle, le statut moteur, le total SAGE, les preuves et une empreinte des membres du groupe. Une modification du montant d'une autre ligne du groupe peut donc invalider une répartition sur la ligne consultée. Une nouvelle ligne dans le groupe ou un changement de regroupement impose aussi une revue.

Les identifiants techniques des candidats SAGE et l'ordre des preuves ne sont pas considérés comme des changements métier. Les lignes de preuves sont triées pour calculer une empreinte stable. Les preuves originales restent conservées telles que reçues pour la consultation. Une modification du contenu d'une preuve, même sur une colonne SAGE secondaire, reste volontairement conservatrice et peut imposer une revue.

L'incrément de version du groupe à chaque import bloque une soumission issue d'une page ouverte avant la publication de la nouvelle campagne, même si les valeurs sont identiques. L'utilisateur doit recharger la page avant de décider.

## 5. Export des corrections et consultation historique

L'export de la campagne sélectionnée contient uniquement les décisions `VALIDATED` dont la photographie indique qu'elles sont actuelles dans cette campagne. Les sources et valeurs sont lues dans la photographie, pas dans la transaction courante.

Les colonnes historiques de conservation sont complétées par : campagne, date de validation, auteur, campagne d'origine et indicateur de reprise. Les chaînes sont forcées comme texte dans Excel pour éviter leur interprétation en formules. Les feuilles sont découpées si la limite de lignes Excel est atteinte.

Une campagne ancienne peut être exportée pour audit avec ses validations valables à cette époque. Une validation devenue obsolète dans une nouvelle campagne n'est pas rétroactivement effacée de l'ancienne. Le fichier porte le numéro de campagne dans son nom : le processus aval doit choisir explicitement la campagne à appliquer.

Les absences et sorties du matching ne sont pas proposées à l'export courant. Les validations partielles de groupes restent possibles avec les règles de justification existantes ; il n'a pas été ajouté de verrou exigeant la validation de l'ensemble d'un groupe.

## 6. Choix de modèle : projection de travail et photographies séparées

| Modèle | Rôle | Pourquoi ce choix |
| --- | --- | --- |
| `Campaign` | Nom, périmètre, métadonnées, import associé, précédente, campagne courante | Identifie une exécution métier et sa place dans la succession |
| `CampaignInventory` | Identité, huit champs, présence, catégorie et différences | Permet les comparaisons complètes sans créer une transaction métier pour chaque ligne hors matching |
| `CampaignGroup` | Règle, statut, total et preuves photographiés | Stocke les preuves une seule fois par groupe et campagne |
| `CampaignReview` | Source canonique, décision, empreinte et origine de comparaison | Rend l'historique indépendant des valeurs courantes |
| `LineReview.campaign` | Campagne à laquelle appartient la revue de travail | Exclut les lignes anciennes des écrans et exports actifs |
| `LineReview.validated_at` / `validation_origin` | Provenance de la validation | Distingue date d'import et date de décision humaine |
| `ReviewEvent.campaign` | Campagne dans laquelle la décision a été prise | Permet de restituer l'historique dans son contexte |
| `ReviewGroup.context_signature` | Empreinte des membres du groupe | Protège les allocations contre un changement sur une ligne voisine |

Les tables existantes restent la projection de travail afin de préserver le parcours de validation et les identités des lignes. Une campagne précédente ne se reconstruit pas depuis ces tables : elle dispose de ses propres données JSON. Les événements historiques restent rattachés à la ligne et à la campagne.

Les photographies de décision de la campagne courante sont mises à jour par `decide()` dans la même transaction que la décision et son événement. À la clôture de campagne, elles cessent d'être modifiées par ce parcours. Les vues historiques n'acceptent que GET et l'administration expose ces modèles en lecture seule. Il s'agit d'une immutabilité applicative, pas d'une protection contre un administrateur SQL modifiant directement la base.

Une contrainte conditionnelle garantit une seule campagne courante. Les identités d'inventaire, groupes et revues sont uniques dans chaque campagne. Le verrou de campagne est acquis avant les verrous métier lors d'une décision ; l'import verrouille également la campagne courante. Sous PostgreSQL, cela sérialise ces opérations. Les limites de concurrence SQLite restent applicables.

## 7. Contrat JSONL version 2

L'ordre des enregistrements est imposé : en-tête → inventaire → propositions → fin. Aucun enregistrement n'est autorisé après la fin, et aucun inventaire ne peut suivre une proposition.

```json
{"type":"campaign","schema_version":2,"name":"Septembre 2026","scope":"atlas-complet","generated_at":"2026-09-20T12:00:00+00:00","sources":{"Atlas":"JDD.xlsx","SAGE":"ZLISTPJT.csv"}}
{"type":"inventory","atlas":{"Code projet":"P","Année":2026,"Id":"A","Statut BAP":"Comptabilisé","Total charges projet (€)":100,"Total charges SAGE (€)":100,"N° pièce SAGE":"D","Date comptable":"2026-09-01"}}
{"complete":0,"inventory_count":1}
```

Cet exemple est une campagne valide sans ligne à rapprocher. Quand elles existent, les propositions conservent les champs `key`, `project`, `rule`, `match_status`, `sage_total`, `evidence`, `atlas`, avec `type="proposal"` et `schema_version=2`.

Contrôles supplémentaires : identité unique dans l'inventaire ; groupe et ligne de proposition non répétés ; correspondance exacte entre les huit valeurs d'une proposition et son inventaire normalisé ; statut « Envoyé SAGE » pour les propositions ; couverture de toutes les lignes de ce statut ; compteurs de fin cohérents. Toute erreur annule l'intégralité de la campagne et laisse la précédente active.

Les noms des fichiers sources sont conservés dans l'en-tête ; l'empreinte SHA-256 du fichier importé est conservée via le traitement. Ce n'est pas une empreinte individuelle des fichiers sources ni une signature d'authenticité.

## 8. Reprise de l'installation existante

Les migrations `0007_campaigns` et `0008_stable_history_order` ajoutent le schéma sans effacer les données. La seconde stabilise aussi l'ordre de l'ancien historique lorsque deux événements ont exactement le même horodatage.

Au **premier import v2 réussi**, si des revues existent déjà, l'application crée une photographie « État antérieur à la gestion des campagnes ». Elle préserve les sources disponibles, les groupes, décisions et événements. Elle recalcule le contexte des groupes pour permettre un report fiable des validations encore actuelles.

Cette archive porte `inventory_complete=False` : on ne possède pas l'inventaire complet des anciennes extractions. Le premier inventaire complet fournit donc une référence, sans déduire artificiellement des absences dans l'ancien jeu. Les campagnes suivantes permettent la comparaison complète.

Pour les anciennes validations ne disposant pas d'une date dédiée, la date de dernière décision enregistrée sur la revue est utilisée. Les versions historiques non stockées avant cette évolution ne peuvent pas être reconstituées.

Le format v1 reste accepté uniquement tant qu'aucune campagne n'existe. Après passage aux campagnes, il est refusé avec une instruction de relancer le moteur : accepter un fichier sans inventaire compromettrait les contrôles de présence.

Sur cette installation, une sauvegarde SQLite a été effectuée avant migrations sous `.work_app/before-campaigns-20260920-144525.sqlite3`. Les 18 610 transactions, 18 610 revues et 10 événements présents ont été conservés. Aucun nouveau rapprochement réel n'a été importé pour les tests.

## 9. Volumétrie, coûts et limites

Le moteur écrit l'inventaire progressivement dans le même JSONL, sans constituer une liste de dictionnaires de plus d'un million de lignes. Les DataFrames des sources restent néanmoins chargés en mémoire comme auparavant.

L'application normalise et compare l'inventaire par lots de 500 lignes, avec `bulk_create`. La détection des doublons repose sur une contrainte en base, sans ensemble Python couvrant tout l'inventaire. Seules les identités des propositions sont conservées en mémoire pendant l'import. Les absences sont obtenues par une sous-requête SQL puis insérées par lots.

Les coûts nouveaux sont réels : lecture d'un JSONL plus grand, une ligne d'inventaire par ligne Atlas et par campagne, index associés, photographies des propositions et journal transactionnel. Une extraction à 1,5 million de lignes implique environ 1,5 million d'enregistrements d'inventaire supplémentaires par campagne, avant les absences héritées. L'historisation complète augmente donc le stockage avec chaque campagne.

Depuis le correctif des imports SQLite, la préparation s'effectue sur une copie privée. Les inventaires, preuves et contrôles sont chargés par lots invisibles, puis les projections et la campagne sont publiées ensemble. WAL permet la lecture pendant les écritures ; une révision transactionnelle empêche d'écraser une décision récente. La publication finale peut encore retarder des écritures concurrentes. Il n'y a pas de reprise à mi-fichier ni de migration automatique vers PostgreSQL. Voir [le fonctionnement et la procédure d'activation](import_sqlite_par_lots.md).

Les futurs gains possibles sont des inventaires différentiels, une rétention contrôlée, des tables de préparation pour raccourcir la publication et une base PostgreSQL en usage concurrent. Ils nécessitent une conception distincte pour ne pas perdre la traçabilité. Les temps des tests synthétiques ne sont pas des mesures sur une campagne réelle de 1,5 million de lignes.

## 10. Fichiers et validation technique

- Moteur : [exporteur de campagne](../reconciliation/exporters/review.py), [CLI](../reconciliation/main.py).
- Application : [modèles](../app-suivi-reconciliation/reconciliation/models.py), [import et comparaison](../app-suivi-reconciliation/reconciliation/campaigns.py), [service d'import](../app-suivi-reconciliation/reconciliation/review_import.py), [décision](../app-suivi-reconciliation/reconciliation/review.py), [consultation et export](../app-suivi-reconciliation/reconciliation/campaign_views.py).
- Tests : [contrat moteur](../tests/test_review_bundle.py), [scénarios de campagnes](../app-suivi-reconciliation/reconciliation/test_campaigns.py).

Les scénarios couvrent le report sur plusieurs campagnes, les deux montants, le changement de statut, les absences et réapparitions, les groupes modifiés, les preuves renumérotées, les fichiers incohérents/tronqués, les droits, la fermeture des anciens formulaires et la reprise de données antérieures. Les suites existantes du moteur et de l'application complètent ces vérifications.

Vérifications réalisées le 20 septembre 2026 : **112 tests moteur réussis, 1 ignoré ;
59 tests Django réussis ; contrôle Ruff sans erreur ; aucune migration manquante**.
Un scénario de bout en bout a généré deux JSONL avec le vrai moteur, les a importés
dans une base isolée, puis vérifié les reports, changements, absences et sorties du matching.
Douze vues ont été contrôlées dans Edge, à 1440 px et 390 px : aucune erreur JavaScript
ni débordement horizontal de page. Les données réelles de l'application n'ont pas servi
de fixtures et aucun import réel de plus d'un million de lignes n'a été lancé pour cette vérification.

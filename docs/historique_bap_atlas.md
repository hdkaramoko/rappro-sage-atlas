# Historique informatif des BAP Atlas

## Génération

La commande principale du README inclut désormais l'extraction facultative :

```powershell
uv run python -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --year 2026 --atlas-projects "data/inputs/ProjetAtlas.xlsx" --department-mapping "data/inputs/transcodification.xlsx" --bap-extract "data/inputs/ExtractionBap.xlsx" --review-output "data/outputs/campagne_15112026.jsonl"
```

`--bap-extract` exige une sortie JSONL v3, mais reste indépendant des deux
référentiels organisationnels : ils peuvent être omis. Sans cette option, aucun
enregistrement BAP n'est ajouté et le comportement antérieur reste identique.
Le fichier XLSX est ouvert une seule fois en lecture seule, avant le matching.
Les contrôles de collision des chemins protègent aussi cette nouvelle source.

La feuille `Sheet1` exige cinq colonnes : `N° BAP SAGE`, `Date de création`,
`Etabli par`, `Date de modification`, `Modifié par`. Les conventions de
normalisation des en-têtes acceptent accents, casse et espaces ; `N° BAP Atlas`
ne remplace jamais la clé requise. `Code projet` est facultatif.

## Jointure et qualité

Une clé technique normalise Unicode, casse et espaces du N° BAP SAGE (préfixe
BAP, 100 caractères maximum). Les références sources ne sont jamais modifiées.
La jointure utilise **N° BAP (SAGE) du JDD** et le code projet canonique.

- Projet renseigné des deux côtés : concordance obligatoire.
- Projet absent de l'extraction : enrichissement par BAP seulement si non ambigu.
- Même BAP/projet et quatre valeurs identiques : un seul contexte, doublons comptés.
- Même clé mais valeurs différentes : clé neutralisée et conflit compté.
- Contexte sans projet et contexte spécifique contradictoires : aucun choix arbitraire.
- Si seul un contexte d'un autre projet et une source sans projet coexistent,
  le rattachement reste ambigu et n'est pas attribué.
- Plusieurs lignes Atlas du même BAP/projet partagent le même contexte.
- BAP absent, invalide ou non trouvé : aucune nouvelle ligne métier, aucun blocage
  du matching et aucune valeur inventée.

Les lignes vides sont ignorées. Les pieds sont identifiés par contenu : Total
dans la première colonne, sans clé BAP valide ni projet ; ou sommes seules dans
les colonnes `Total dépenses (€)` / `Total dépenses (dev.)`. Aucune suppression
positionnelle des dernières lignes. Les autres clés absentes ou invalides sont
comptées comme anomalies et ignorées pour l'enrichissement.

Les véritables `datetime`, dates et nombres sériels sont convertis selon l'époque
1900/1904 du classeur, fraction horaire comprise. ISO et formats français explicites
sont aussi acceptés. Date vide : null ; invalide : null et compteur d'anomalie.
Aucun fuseau n'est ajouté aux données naïves. Les auteurs sont conservés tels
quels (255 caractères maximum) ; valeurs invalides : null et compteur distinct.

Le bilan ne contient pas les noms des auteurs : lignes lues/utiles/vides,
pieds ignorés, clés/dates/auteurs invalides, doublons, conflits, BAP uniques,
BAP/contextes enrichis, BAP de l'extraction non trouvés dans le JDD et couples
projet/BAP du JDD sans historique, discordances de projet et ambiguïtés.

## JSONL et stockage

L'en-tête v3 ajoute `bap_history_policy: bap-history-v1` et le petit bilan
`bap_history_summary`. Après l'inventaire Atlas, avant l'inventaire Sage et les
propositions, un contexte dédupliqué est émis :

```json
{
  "type": "bap_history",
  "data": {
    "project_code": "PROJET",
    "bap_sage_number": "BAPEXEMPLE",
    "bap_created_at": "2026-11-02T15:30:00",
    "bap_created_by": "Auteur",
    "bap_modified_at": null,
    "bap_modified_by": null
  }
}
```

Le marqueur final ajoute `bap_history_count`. L'empreinte de flux existante
couvre l'en-tête et les nouveaux enregistrements lorsqu'un inventaire Sage complet
est déclaré. Types, longueurs, dates ISO, compteur, ordre et rattachement au JDD
sont vérifiés. Un doublon JSONL ou un contexte hors périmètre annule l'import.
Les anciennes campagnes sans politique BAP restent importables.

La migration **0028_campaign_bap_history** crée `CampaignBapHistory`, avec
unicité `(campaign, project_code, bap_sage_number)`. Les quatre champs sont
nullables. Les dates ISO sont textuelles afin de conserver exactement l'absence
de fuseau et la précision, sans conversion Django implicite. Aucune nouvelle
règle de date ni index sur les auteurs/dates : seule la clé de lecture est indexée.

L'import se fait par lots, dans la transaction existante ; SQLite copie la même
table dans son staging invisible avant publication atomique. Une nouvelle campagne
conserve son propre contexte, sans modifier celui des anciennes campagnes.
Les données sont stockées séparément des sources Atlas et des signatures métier :
changer l'historique BAP ne rend pas une décision obsolète.

## Interface et droits

Envoyé SAGE affiche deux colonnes compactes : **Date de création du BAP** et
**Dernière modification du BAP**, sans auteurs. Le défilement reste limité au tableau.
La fiche présente **Historique du BAP** dans Données sources : Créé le, Établi par,
Modifié le, Modifié par. Deux colonnes sur desktop, une sur mobile. Les fiches
historiques utilisent aussi le contexte de leur propre campagne.

Format français, heure seulement si significative, secondes/fractions conservées
si présentes ; absence affichée par — ou Non renseigné. Aucun indicateur de récence,
filtre, priorité ni formulaire supplémentaire. Les auteurs restent échappés dans
le HTML. Les droits sont ceux du portefeuille existant : aucune recherche BAP
globale accessible à l'utilisateur, aucun nouveau droit.

La liste charge les historiques de ses seules lignes autorisées en une requête
bornée par la page, même si plusieurs lignes partagent le même BAP. Les anciennes
campagnes sans capacité n'ajoutent aucune requête. La fiche lit une clé indexée.

## Déploiement et validation

Déployer moteur et Django ensemble puis, depuis `app-suivi-reconciliation` :

```powershell
../.venv/Scripts/python.exe manage.py migrate
```

Générer un nouveau JSONL avec la commande ci-dessus et importer une nouvelle
campagne par le menu habituel ou :

```powershell
../.venv/Scripts/python.exe manage.py import_review_bundle ../data/outputs/campagne_15112026.jsonl
```

Aucun recalcul rétroactif ni nouvelle génération nécessaire pour consulter une
ancienne campagne ; ses dates restent non renseignées. Aucune migration n'a été
appliquée à la base utilisateur pendant le développement.

Tests : lecteur Excel (dont l'exemple fourni), sériels/époques/heures, en-têtes,
pieds, invalides, doublons, collisions, jointures, CLI avec/sans option, contrat,
import atomique, historique, absence de changement des preuves/auto-validations,
permissions, affichage, échappement et absence de N+1 (50 lignes, une requête).
Le scénario SQLite sur disque vérifie le transfert effectif de l'historique.
La suite moteur complète passe : **342 tests réussis, un test réel optionnel ignoré**.
La suite Django complète passe : **480 tests, sans échec, quatre ignorés sous
SQLite**. PostgreSQL réel n'a pas été exécuté dans cet environnement.

Recette Chrome sur les vrais templates avec contexte fictif : liste, contrôle
des montants et fiche, à 320, 375, 390, 430, 768, 1024, 1440 et 1920 px.
24 rapports vérifiés : aucun débordement de page, multisélections conservées,
historique en une/deux colonnes selon le viewport. Artefacts locaux dans
`benchmarks/review_filters/`, hors Git ; aucun accès SQL lors du rendu.

Benchmark isolé reproductible :
`.venv/Scripts/python.exe -m examples.benchmark_departments --bap-history`.
200 projets, 400 Atlas, 2 000 Sage, 200 contextes BAP. Même matching, preuves et
autorisations identiques ; mêmes montants, états et cadrages par projet.

| Mesure locale SQLite | Sans historique | Avec historique |
|---|---:|---:|
| Export, lecture/indexation Excel incluse | 0,581 s | 0,768 s |
| JSONL | 2 603 947 octets | 2 655 182 octets |
| Import complet | 11,804 s | 11,204 s |
| Envoyé SAGE | 68 ms / 15 requêtes | 86 ms / 16 requêtes |

Mesures ponctuelles, pas de gain d'import revendiqué. Le fichier Excel complet
réel n'a pas été importé pour ce benchmark. Ces mesures ne préjugent pas des
durées de PostgreSQL ou d'une campagne entière ; aucune recherche linéaire par
ligne Atlas et aucune requête par ligne de tableau ne sont ajoutées.

Fichiers principaux : lecteur `reconciliation/bap_history.py`, contrat pur
`reconciliation_contract/bap_history.py`, CLI et export JSONL ; modèle/migration,
import et présentation `reconciliation/bap_history.py` côté Django, vues actuelles
et historiques, composant partagé, deux colonnes de liste et CSS. README mis à
jour avec le chemin réel `data/inputs/ExtractionBap.xlsx`.

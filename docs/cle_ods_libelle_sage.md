# Clé ODS/ODG : libellé SAGE du fichier Atlas

Correctif du 8 novembre 2026.

Les clés ODS/ODG utilisaient le champ `Libellé ATLAS`, souvent vide pour les
écritures comptabilisées, alors que le texte correspondant aux écritures Sage
se trouve dans `Libellé SAGE`. Les groupes des deux sources restaient séparés.

| Parcours | Libellé utilisé |
|---|---|
| Contrôle ODS/ODG, ligne Atlas Comptabilisé | `Libellé SAGE` du fichier Atlas |
| Recherche de correspondance, ligne Envoyé SAGE | `Libellé ATLAS` |
| Contrôle des autres types de pièce | Clé projet/exercice/pièce inchangée |

La clé ODS reste projet/exercice/tiers/libellé normalisé. La normalisation
commune conserve les règles existantes de casse, accents et espaces. Les deux
textes source sont conservés et affichés dans le détail d'inventaire.

Un libellé SAGE vide reste vide : aucun remplacement par le libellé Atlas.
Le contrôle est indéterminé avec le motif « Libellé SAGE Atlas absent pour le
contrôle ODS/ODG ». Les règles de montant, cardinalité, unicité et validation
automatique restent applicables : une clé commune ne garantit pas à elle seule
une validation. Leur éventuel assouplissement est une évolution distincte.

## Contrat et compatibilité

Les nouveaux exports JSONL v3 déclarent `ods_label_policy: sage-accounted-v1`,
transmettent `Libellé SAGE` dans l'inventaire brut et les propositions, et
`sage_label` dans les sources canoniques des contrôles signés. L'import exige
la colonne déclarée et rejette une politique inconnue. Une valeur vide est
admise mais signalée dans le diagnostic.

Les anciens flux, sans ce champ canonique, conservent leur clé historique et
leur ancienne exception ODS sans libellé. Les campagnes existantes ne sont pas
réécrites. La vue de contrôle signale un ancien format. Une affectation manuelle
projette le bon champ dans le calcul sans modifier les deux textes source.

## Mise en service

Redéployer le moteur et l'application, régénérer le JSONL depuis les fichiers
Excel Atlas et Sage, puis importer une **nouvelle campagne**. Un ancien JSONL
ne contient pas le libellé nécessaire. Aucune migration de schéma n'est requise :
la donnée supplémentaire est conservée dans les champs JSON existants.

Recette synthétique reproductible :

```powershell
.venv/Scripts/python.exe -m examples.ods_labels_fixture <dossier-temporaire>
```

Cette recette produit un JSONL par le moteur réel : un ODS équilibré malgré un
libellé Atlas différent, un ODS sans libellé SAGE qui reste indéterminé, et une
correspondance exacte Envoyé SAGE fondée sur le libellé Atlas.

Les tests couvrent également l'export signé, les rejets atomiques d'import,
les projections manuelles, l'import d'ancien format et la conservation des
sources historiques. Aucun fichier réel ni base utilisateur n'a été régénéré.

Validation : 223 tests moteur réussis (1 ignoré), 258 tests Django exécutés
(2 ignorés), puis les 6 tests ciblés ODS réussis après ajout de la recette
de compatibilité historique. `makemigrations --check --dry-run` : aucun
changement de modèle. L'inventaire AST des docstrings est disponible dans
[cle_ods_libelle_sage_docstrings.md](cle_ods_libelle_sage_docstrings.md).

# Unicité des rapprochements « Libellé proche »

Le garde bilatéral distingue désormais une ligne Atlas déjà comptabilisée d'une
ligne réellement susceptible de consommer la même écriture Sage. Ce traitement
est activé pour `MATCH_FUZZY_HIGH`, à l'export et au contrôle serveur, et désormais
pour `MATCH_BAP` : voir [le correctif tiers/BAP/filtres](correctifs_tiers_ods_bap_filtres.md).
Les autres catégories conservent leurs contrôles précédents.

Une concurrente comptabilisée est écartée uniquement si son projet, exercice,
numéro de pièce, date et montant signé permettent d'identifier une seule écriture
Sage complète, du même tiers, dont la référence est distincte de celle proposée
et n'apparaît qu'une fois dans l'inventaire complet. Une pièce différente seule
ne suffit pas. Une pièce/date absente, une identité incomplète ou dupliquée,
plusieurs écritures compatibles ou une référence partagée maintiennent le blocage.
La tolérance historique de 0,01 EUR reste inchangée.

Les exclusions interviennent avant la limite de deux concurrents : deux faux
concurrents ne doivent pas masquer une troisième ligne réellement concurrente.
Les populations complètes restent indexées ; le catalogue par projet/exercice/
pièce et le compteur de références sont construits en un passage sur Sage.
Chaque vérification consulte uniquement son intervalle de montants et les pièces
des concurrentes concernées. Les contrôles de réservation et capacité restent actifs.

## Mesure sur la campagne locale du 11 novembre 2026

Audit SQLite en lecture seule, sans import ni modification des décisions :

- 355 793 lignes Atlas et 498 224 écritures Sage dans les index ;
- 236 propositions individuelles « Libellé proche » examinées ;
- 222 passent le garde initial, 236 le garde affiné ;
- **14 lignes Atlas / 14 pièces Sage** libérées par ce garde, toutes déjà porteuses
  d'une autorisation AUTO dans le fichier importé ;
- la ligne **1566314** est comprise dans ces 14 cas. Ses concurrentes 1786726
  et 1903016 ont des identités Sage uniques et distinctes de FAF0126011134.

Ces chiffres décrivent le garde d'unicité, pas une validation effective : décisions
humaines et autres protections serveur restent prioritaires. Aucun recalcul
rétroactif n'est ajouté et les décisions existantes ne sont pas réécrites.
Le format JSONL est inchangé ; les nouveaux traitements utilisent le correctif.

Mesure indicative unique sur les populations complètes ci-dessus : lecture 6,879 s,
construction des deux index historiques 3,932 s, construction avec catalogue
5,163 s (environ +1,23 s). Le contrôle des 236 paires passe de 0,0033 à 0,0036 s.
Ces durées locales ne prédisent pas la durée d'un import PostgreSQL complet.

Commande reproductible depuis la racine :

```powershell
.venv/Scripts/python.exe -m examples.audit_fuzzy_uniqueness app-suivi-reconciliation/db.sqlite3
```

## Vérification

Les tests couvrent l'identité distincte prouvée, la référence partagée, la pièce
ou date absente, l'identité Sage incomplète/dupliquée et les vraies concurrences
Atlas/Sage. Ils vérifient aussi le filtrage avant troncature, le maintien du mode
historique, l'autorisation produite par un export réel et le garde Django sur
base de test isolée. Les tests existants des autres règles restent applicables.

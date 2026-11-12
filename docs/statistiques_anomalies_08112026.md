# Statistiques des anomalies au 8 novembre 2026

Source : base locale `app-suivi-reconciliation/db.sqlite3`, ouverte en lecture seule. Campagne active publiee : Rapprochement 2026 du 8 novembre. Migration 0023 presente. Aucun filtre de projet ou portefeuille applique.

Unite : groupes de controle, et non lignes comptables. Meme filtre que la vue Anomalies : ECART ou INDETERMINE ou has_pending. Resultat courant utilise (current_data, sinon data).

Total : 21 485 groupes ; 19 948 ECART et 1 537 INDETERMINE. Ce perimetre local doit etre distingue du chiffre affiche dans un environnement ou une vue filtres.

Sage seul signifie aucune contribution Atlas retenue : ni ligne Comptabilise ni affectation Envoye SAGE confirmee. Parmi les 19 771 groupes Sage seuls, 19 736 n'ont aucune ligne Atlas presente dans l'inventaire avec la meme cle ; 35 en ont une mais sans contribution retenue. Une absence de cle commune ne prouve pas une absence physique dans le fichier Atlas (cle differente ou donnee incomplete possible).

Atlas seul signifie contribution Atlas sans ecriture Sage resolue dans ce groupe. Les 2 groupes sans contribution n'ont ni ligne Comptabilise/affectation confirmee ni preuve Sage.

ODS/ODG designe la strategie de groupe projet/exercice/tiers/libelle ; les autres types sont les trois premiers caracteres du numero de piece.

| Type | Sage seul | Atlas seul | Deux sources | Aucune contribution | Total |
|---|---:|---:|---:|---:|---:|
| ODS/ODG | 5129 | 1418 | 133 | 2 | 6682 |
| ODA | 6082 | 1 | 1 | 0 | 6084 |
| CLO | 3014 | 0 | 0 | 0 | 3014 |
| FAF | 1028 | 1 | 28 | 0 | 1057 |
| CIF | 1027 | 0 | 0 | 0 | 1027 |
| GNF | 471 | 0 | 5 | 0 | 476 |
| ODT | 460 | 0 | 0 | 0 | 460 |
| NDF | 402 | 0 | 10 | 0 | 412 |
| CDF | 407 | 0 | 0 | 0 | 407 |
| RWF | 406 | 0 | 0 | 0 | 406 |
| GNN | 355 | 0 | 0 | 0 | 355 |
| ETR | 249 | 1 | 19 | 0 | 269 |
| DEC | 206 | 11 | 19 | 0 | 236 |
| LBF | 134 | 0 | 0 | 0 | 134 |
| TUF | 98 | 0 | 0 | 0 | 98 |
| FRB | 64 | 0 | 0 | 0 | 64 |
| BQE | 50 | 2 | 3 | 0 | 55 |
| RDC | 50 | 0 | 0 | 0 | 50 |
| Sans numero | 0 | 41 | 0 | 0 | 41 |
| INV | 25 | 0 | 13 | 0 | 38 |
| UAF | 34 | 0 | 0 | 0 | 34 |
| UNI | 32 | 0 | 1 | 0 | 33 |
| ENC | 17 | 5 | 0 | 0 | 22 |
| RWN | 11 | 0 | 0 | 0 | 11 |
| UAN | 9 | 0 | 0 | 0 | 9 |
| GNA | 3 | 0 | 0 | 0 | 3 |
| CAI | 3 | 0 | 0 | 0 | 3 |
| LTR | 2 | 0 | 0 | 0 | 2 |
| FFG | 2 | 0 | 0 | 0 | 2 |
| AVF | 1 | 0 | 0 | 0 | 1 |

Les 21 485 groupes contiennent 2 334 lignes Atlas Comptabilise et 36 496 ecritures Sage. Les motifs peuvent se cumuler ; ils ne sont pas une partition du total.

| Motif | Groupes |
|---|---:|
| Aucune écriture SAGE résolue | 1482 |
| Clé de résolution incomplète | 582 |
| Date Atlas absente ou exercice comptable différent | 41 |
| Montant absent ou invalide : somme incomplète | 41 |
| Candidats concurrents ODS/ODG sur projet/exercice/tiers | 13 |
| Libellé SAGE Atlas absent pour le contrôle ODS/ODG | 5 |

[Detail par groupe](statistiques_anomalies_08112026.csv) ; [repartition complete par type](statistiques_anomalies_types_08112026.csv).

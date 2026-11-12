# Sommes signees : inventaire des docstrings

Comparaison AST avec HEAD, le 8 novembre 2026.

14 definitions nouvelles/modifiees ; 0 docstrings absentes.

| Fichier | Definition | Role |
|---|---|---|
| `app-suivi-reconciliation/reconciliation/migrations/0023_group_signed_amounts.py` | `normalize_current` | Retire les trois vetos collectifs et recalcule les états sur les écarts signés. |
| `app-suivi-reconciliation/reconciliation/migrations/0023_group_signed_amounts.py` | `correct_active_diagnostics` | Corrige par lots les résultats actifs publiés, sous verrou de campagne. |
| `app-suivi-reconciliation/reconciliation/migrations/0023_group_signed_amounts.py` | `Migration` | Actualise les résultats courants ; le retour arrière conserve leur diagnostic. |
| `app-suivi-reconciliation/reconciliation/test_business.py` | `BusinessTests` | Corrections, affectations entières et contrôles ciblés dans la transaction métier. |
| `app-suivi-reconciliation/reconciliation/test_business.py` | `BusinessTests.test_multiple_ods_candidates_can_be_resolved_by_explicit_whole_selection` | Un groupe déjà équilibré accepte un lien explicite sans altérer son diagnostic initial. |
| `app-suivi-reconciliation/reconciliation/test_group_signed_amounts.py` | `SignedDiagnosticTests` | Les anciens vetos disparaissent sans effacer les autres motifs ou décisions. |
| `app-suivi-reconciliation/reconciliation/test_group_signed_amounts.py` | `SignedDiagnosticTests.test_signed_results_keep_gaps_guards_and_history` | Le nettoyage est signé, idempotent et respecte écarts, exclusions et données absentes. |
| `app-suivi-reconciliation/reconciliation/test_group_signed_amounts.py` | `SignedMigrationTests` | La pagination met à jour les diagnostics actifs sans toucher à l'historique. |
| `app-suivi-reconciliation/reconciliation/test_group_signed_amounts.py` | `SignedMigrationTests.test_active_results_only_across_batches` | Plus de 250 résultats sont corrigés une seule fois ; sources et décisions restent intactes. |
| `reconciliation_contract/sage_inventory.py` | `consolidate` | Calcule les états Comptabilisé et global pour une seule clé métier. |
| `tests/test_group_signed_amounts.py` | `test_ods_multiple_signed_entries` | Une ligne Atlas peut couvrir plusieurs écritures signées, avec tolérance au centime. |
| `tests/test_group_signed_amounts.py` | `test_opposite_totals_do_not_balance_in_absolute_value` | Deux totaux opposés créent un écart signé, même si leurs valeurs absolues coïncident. |
| `tests/test_group_signed_amounts.py` | `test_signed_group_keeps_duplicate_and_missing_guards` | Un doublon technique ou un montant absent reste indéterminé. |
| `tests/test_sage_inventory.py` | `test_ods_unique_group_with_or_without_label` | Le contrat historique conserve ses clés et son exception de libellé absent unique. |

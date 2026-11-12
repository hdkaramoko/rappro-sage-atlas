# Charges EUR : inventaire des docstrings

Comparaison AST avec HEAD, le 8 novembre 2026.

16 définitions nouvelles/modifiées ; 0 docstrings absentes.

| Fichier | Définition | Rôle |
|---|---|---|
| `app-suivi-reconciliation/reconciliation/migrations/0022_global_control_eur_charges.py` | `monetary_state` | Dérive l'état du diagnostic déjà chiffré, sans recalculer les montants. |
| `app-suivi-reconciliation/reconciliation/migrations/0022_global_control_eur_charges.py` | `normalize_current` | Retourne une copie nettoyée du seul motif obsolète, ou None si non concernée. |
| `app-suivi-reconciliation/reconciliation/migrations/0022_global_control_eur_charges.py` | `correct_active_diagnostics` | Actualise les diagnostics actifs concernés par lots, sans rejouer de décision. |
| `app-suivi-reconciliation/reconciliation/migrations/0022_global_control_eur_charges.py` | `Migration` | Corrige le diagnostic actif uniquement ; le retour arrière ne réintroduit pas le veto. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexMigrationTests` | Vérifie le peuplement initial sur des photographies réellement importées avant migration. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexMigrationTests.test_existing_campaign_backfill_preserves_business_data` | 0021 remplit les index depuis 0020 sans changer snapshot, décision ou état initial. |
| `app-suivi-reconciliation/reconciliation/test_global_currency.py` | `old_diagnostic` | Reconstitue le diagnostic signé d'avant correction pour une charge négative EUR. |
| `app-suivi-reconciliation/reconciliation/test_global_currency.py` | `CurrencyDiagnosticTests` | États, signatures et prudence du correctif des seuls résultats courants. |
| `app-suivi-reconciliation/reconciliation/test_global_currency.py` | `CurrencyDiagnosticTests.test_only_currency_reason_becomes_balanced_without_auto_revalidation` | Le solde nul devient équilibré sans changer les montants ni le drapeau AUTO antérieur. |
| `app-suivi-reconciliation/reconciliation/test_global_currency.py` | `CurrencyDiagnosticTests.test_other_reasons_gaps_and_exclusions_remain` | Un écart, un motif restant ou une exclusion ne deviennent pas artificiellement réconciliés. |
| `app-suivi-reconciliation/reconciliation/test_global_currency.py` | `CurrencyMigrationTests` | Le traitement par lots ne modifie que les diagnostics actifs concernés. |
| `app-suivi-reconciliation/reconciliation/test_global_currency.py` | `CurrencyMigrationTests.test_existing_current_results_only_are_updated_once` | Plus de 250 diagnostics sont corrigés sans omission, initial ni campagne close modifiés. |
| `reconciliation_contract/sage_inventory.py` | `consolidate` | Calcule les états Comptabilisé et global pour une seule clé métier. |
| `tests/test_global_currency.py` | `test_original_currency_does_not_make_balanced_charges_indeterminate` | Une charge EUR équilibrée, y compris un avoir, reste équilibrée quelle que soit la devise d'origine. |
| `tests/test_global_currency.py` | `test_currency_removal_does_not_hide_amount_difference` | Un véritable écart financier reste ECART après suppression du seul veto de devise. |
| `tests/test_global_currency.py` | `test_currency_removal_keeps_identity_and_missing_amount_guards` | La suppression du motif de devise ne blanchit ni collisions ni montants absents. |

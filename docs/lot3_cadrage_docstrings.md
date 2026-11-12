# Lot 3 : inventaire des docstrings

Comparaison AST avec HEAD, le 9 novembre 2026.

43 definitions nouvelles/modifiees ; 0 docstrings absentes.

| Fichier | Definition | Role |
|---|---|---|
| `app-suivi-reconciliation/reconciliation/accounting.py` | `accounting_state` | Retourne état et écart arrondi selon Decimal/quantize existant ; aucune mutation. |
| `app-suivi-reconciliation/reconciliation/accounting.py` | `new_bucket` | Retourne un poste numérique indépendant ; réservé aux agrégats internes EUR. |
| `app-suivi-reconciliation/reconciliation/accounting.py` | `refresh_project` | Matérialise un projet sous verrou campagne, sans rejouer décisions ou moteur. |
| `app-suivi-reconciliation/reconciliation/accounting.py` | `prepare_campaign` | Prépare les projets importés en flux ; retourne leur nombre, sans moteur ni décision. |
| `app-suivi-reconciliation/reconciliation/accounting_models.py` | `AccountingProject` | Synthèse reconstruisible d'un projet/campagne, sans état de validation. |
| `app-suivi-reconciliation/reconciliation/accounting_models.py` | `AccountingProject.Meta` | Une synthèse par projet ; index commun aux deux bases pour filtres et pagination. |
| `app-suivi-reconciliation/reconciliation/accounting_models.py` | `AccountingGroup` | Résultat de cadrage d'un contrôle existant, sans changer son diagnostic. |
| `app-suivi-reconciliation/reconciliation/accounting_models.py` | `AccountingGroup.Meta` | Index de navigation projet/type sans exploration JSON pour la pagination. |
| `app-suivi-reconciliation/reconciliation/accounting_views.py` | `selected_campaign` | Lit la campagne publiée demandée ou courante ; retourne None si aucune, 404 si ID interdit. |
| `app-suivi-reconciliation/reconciliation/accounting_views.py` | `accounting_list` | Affiche les synthèses autorisées avec GET multisélection et pagination, sans calcul métier. |
| `app-suivi-reconciliation/reconciliation/accounting_views.py` | `accounting_detail` | Présente un projet autorisé, ses types et groupes paginés ; 404 hors portefeuille. |
| `app-suivi-reconciliation/reconciliation/business.py` | `recalculate` | Actualise synchroniquement les seuls contrôles `keys` dans la transaction métier. |
| `app-suivi-reconciliation/reconciliation/campaigns.py` | `import_campaign` | Importe `header` et l'itérateur JSONL `stream` dans la transaction parente. |
| `app-suivi-reconciliation/reconciliation/journey.py` | `safe_return` | Conserve uniquement un retour local vers les écrans autorisés du parcours. |
| `app-suivi-reconciliation/reconciliation/management/commands/prepare_accounting.py` | `Command` | Construit les seuls agrégats techniques, sans modifier sources ou décisions. |
| `app-suivi-reconciliation/reconciliation/management/commands/prepare_accounting.py` | `Command.add_arguments` | Ajoute l'identifiant optionnel ; aucune campagne historique n'est choisie implicitement. |
| `app-suivi-reconciliation/reconciliation/management/commands/prepare_accounting.py` | `Command.handle` | Construit la projection sélectionnée et affiche durée/volume ; lève CommandError si absente. |
| `app-suivi-reconciliation/reconciliation/migrations/0024_accounting_rollups.py` | `Migration` | Crée uniquement les projections reconstructibles ; aucune décision n'est rejouée. |
| `app-suivi-reconciliation/reconciliation/templatetags/review_ui.py` | `accounting_label` | Traduit un état de cadrage stocké ; retourne un libellé explicite si non calculable. |
| `app-suivi-reconciliation/reconciliation/templatetags/review_ui.py` | `signed_euros` | Formate un écart EUR en français avec signe positif visible, sans changer son montant. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests` | Les chiffres se déduisent des groupes existants, jamais de propositions supposées confirmées. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.setUpClass` | Génère les seules sources de recette dans un dossier temporaire, puis importe en base jetable. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.tearDownClass` | Libère les fichiers synthétiques sans toucher aux extractions utilisateur. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.summary` | Retourne le résultat projet courant sans déclencher de calcul sur lecture. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_confirmed_counts_once_and_sage_without_proposal_is_included` | 6000 comptabilisés et 4000 confirmés couvrent une pièce de 10000, sans doubler Sage. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_nonconfirmed_has_no_invented_type_and_exact_cent_rule` | Le poste NA expose le non confirmé ; l'état projet dépend de l'écart arrondi à zéro. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_correction_duplicate_and_cancel_refresh_without_changing_sources` | Les ajustements changent les chiffres retenus ; annulation et doublon conservent l'initial. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_source_15000_corrected_to_10000_and_missing_amount_is_not_zero` | 15000 corrigés à 10000 cadrent ; une valeur source manquante reste absente, jamais zéro. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_explicit_historical_preparation_preserves_decisions_and_old_results` | La préparation historique lit sa photographie sans la remplacer par les décisions courantes. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_link_cancellation_removes_only_confirmed_amount` | L'annulation d'un lien retire les 4000 confirmés et rétablit le poste en attente. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_existing_validation_and_rejection_buttons_update_the_summary` | Les décisions du parcours existant alimentent le cadrage sans créer une validation supplémentaire. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_exclusion_keeps_atlas_visible_outside_scope` | Un type exclu retire son comparateur et expose l'Atlas correspondant sans le dissimuler. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_compensating_local_gaps_keep_project_balanced_and_totals_reconcile` | Deux écarts locaux se compensent au projet ; les postes par type reconstituent ses totaux. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_incomplete_ods_and_reference_collision_are_not_false_balances` | Une clé ODS incomplète ou une référence Sage dupliquée rend le périmètre insuffisant. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_views_filters_permissions_links_and_readonly_consultation` | Les pages autonomes préservent filtres et retours ; aucun accès direct hors portefeuille. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_list_cost_and_pagination_on_large_materialized_campaign` | Mesure 120 projets/12000 groupes matérialisés ; le GET ne charge aucun inventaire. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_preparation_streams_a_thousand_groups_without_per_line_queries` | Mesure la préparation de 1000 groupes Sage supplémentaires, avec écritures distinctes. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexMigrationTests` | Vérifie le peuplement initial sur des photographies réellement importées avant migration. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexMigrationTests.test_existing_campaign_backfill_preserves_business_data` | 0021 remplit les index depuis 0020 sans changer snapshot, décision ou état initial. |
| `app-suivi-reconciliation/reconciliation/test_global_currency.py` | `CurrencyMigrationTests` | Le traitement par lots ne modifie que les diagnostics actifs concernés. |
| `app-suivi-reconciliation/reconciliation/test_global_currency.py` | `CurrencyMigrationTests.test_existing_current_results_only_are_updated_once` | Plus de 250 diagnostics sont corrigés sans omission, initial ni campagne close modifiés. |
| `app-suivi-reconciliation/reconciliation/test_group_signed_amounts.py` | `SignedMigrationTests` | La pagination met à jour les diagnostics actifs sans toucher à l'historique. |
| `app-suivi-reconciliation/reconciliation/test_group_signed_amounts.py` | `SignedMigrationTests.test_active_results_only_across_batches` | Plus de 250 résultats sont corrigés une seule fois ; sources et décisions restent intactes. |

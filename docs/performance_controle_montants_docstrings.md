# Performance des contrôles : inventaire des docstrings

Comparaison AST avec HEAD, le 8 novembre 2026.

34 définitions nouvelles/modifiées ; 0 docstrings absentes.

| Fichier | Définition | Rôle documenté |
|---|---|---|
| `app-suivi-reconciliation/imports_app/sqlite_scenarios.py` | `Scenarios` | Utilise une base neuve et vérifie publication, reprises et actions Lot 2 concurrentes. |
| `app-suivi-reconciliation/imports_app/sqlite_scenarios.py` | `Scenarios.test_lot1_inventory_and_controls_survive_staging` | Transporte photographies, états indexés et contextes dans la publication atomique. |
| `app-suivi-reconciliation/reconciliation/campaigns.py` | `save_decision_snapshot` | Met à jour le snapshot courant et son index de consultation dans la transaction métier. |
| `app-suivi-reconciliation/reconciliation/campaigns.py` | `import_campaign` | Importe `header` et l'itérateur JSONL `stream` dans la transaction parente. |
| `app-suivi-reconciliation/reconciliation/control_index.py` | `suspend_indexing` | Suspend les synchronisations unitaires pendant un import, puis restaure le contexte. |
| `app-suivi-reconciliation/reconciliation/control_index.py` | `context_values` | Retourne les clés et l'alerte existantes d'un snapshot, sans interprétation métier nouvelle. |
| `app-suivi-reconciliation/reconciliation/control_index.py` | `refresh_pending` | Actualise les seuls indicateurs de contrôles touchés via une relation indexée. |
| `app-suivi-reconciliation/reconciliation/control_index.py` | `sync_review` | Synchronise les anciens/nouveaux contextes de la revue exacte après son écriture. |
| `app-suivi-reconciliation/reconciliation/control_index.py` | `rebuild_campaign` | Extrait les contextes une fois en fin d'import et matérialise les alertes. |
| `app-suivi-reconciliation/reconciliation/global_control.py` | `initialize_controls` | Persiste le calcul initial en lots de 500 dans la transaction d'import. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `global_controls_for` | Retourne les contrôles publiés du portefeuille avec leur résultat courant. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `control_workspace` | Affiche les anomalies courantes par défaut, avec filtres et pagination serveur. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `global_control_detail` | Présente les montants courant/initial et les sources autorisées du contrôle pk. |
| `app-suivi-reconciliation/reconciliation/migrations/0021_control_workspace_indexes.py` | `restore_revision` | Restaure les triggers métier SQLite après un éventuel changement de table. |
| `app-suivi-reconciliation/reconciliation/migrations/0021_control_workspace_indexes.py` | `populate_indexes` | Initialise les projections techniques existantes par campagne et lots bornés. |
| `app-suivi-reconciliation/reconciliation/migrations/0021_control_workspace_indexes.py` | `Migration` | Matérialise seulement les index de lecture, sans modifier les règles métier. |
| `app-suivi-reconciliation/reconciliation/models.py` | `CampaignReview` | Source et décision photographiées, indépendantes des lignes courantes. |
| `app-suivi-reconciliation/reconciliation/models.py` | `CampaignReview.save` | Persiste le snapshot puis synchronise ses seuls index de consultation. |
| `app-suivi-reconciliation/reconciliation/models.py` | `CampaignGlobalControl` | Calcul initial immuable et résultat courant versionné des recalculs ciblés. |
| `app-suivi-reconciliation/reconciliation/models.py` | `CampaignGlobalControl.save` | Actualise l'état indexé depuis le résultat déjà calculé, sans lancer le moteur. |
| `app-suivi-reconciliation/reconciliation/models.py` | `CampaignGlobalControl.Meta` | Identité unique et index couvrants des filtres et de la pagination par projet. |
| `app-suivi-reconciliation/reconciliation/models.py` | `ReviewControlContext` | Projection technique des clés de contexte d'une décision photographiée. |
| `app-suivi-reconciliation/reconciliation/models.py` | `ReviewControlContext.Meta` | Un contexte unique par revue/clé ; recherche ciblée par campagne/projet/clé. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `synthetic_records` | Génère le véritable JSONL fictif Lot 1 sans auto-validation, dans un répertoire jetable. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexTests` | Compare l'index aux snapshots existants et vérifie la lecture SQL légère. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexTests.setUpClass` | Prépare une fois les seules sources synthétiques nécessaires aux tests. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexTests.tearDownClass` | Libère les fichiers temporaires de la classe, sans toucher à la base applicative. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexTests.test_count_and_pagination_do_not_read_json_or_correlated_subqueries` | Le comptage et les identifiants paginés utilisent les colonnes indexées seules. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexTests.test_confirm_and_cancel_update_pending_in_same_transaction` | Une validation retire l'alerte puis son annulation la rétablit sans reconstruction globale. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexTests.test_removed_context_refreshes_both_old_and_new_keys` | Le déplacement d'un contexte retire l'ancienne alerte et crée la nouvelle. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexTests.test_another_pending_review_keeps_the_alert` | La confirmation d'une ligne ne masque pas une autre proposition du même contrôle. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexTests.test_rebuilding_index_is_idempotent_and_does_not_touch_decisions` | Une reconstruction technique conserve les décisions, résultats et versions métier. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexMigrationTests` | Vérifie le peuplement initial sur des photographies réellement importées avant migration. |
| `app-suivi-reconciliation/reconciliation/test_control_index.py` | `ControlIndexMigrationTests.test_existing_campaign_backfill_preserves_business_data` | 0021 remplit les index depuis 0020 sans changer snapshot, décision ou état initial. |

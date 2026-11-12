# Maintenance SQLite : inventaire des docstrings

Comparaison AST avec HEAD, le 9 novembre 2026.

41 definitions nouvelles/modifiees ; 0 docstrings absentes.

| Fichier | Definition | Role |
|---|---|---|
| `app-suivi-reconciliation/imports_app/sqlite_scenarios.py` | `Scenarios` | Utilise une base neuve et vérifie publication, reprises et actions Lot 2 concurrentes. |
| `app-suivi-reconciliation/imports_app/sqlite_scenarios.py` | `Scenarios.test_statistics_are_outside_import_and_before_private_preparation` | Le staging analyse la copie après commit, prépare puis publie ses synthèses atomiquement. |
| `app-suivi-reconciliation/imports_app/sqlite_scenarios.py` | `Scenarios.test_statistics_are_outside_import_and_before_private_preparation.observe_statistics` | Relève la séquence et le contexte transactionnel sans changer la maintenance réelle. |
| `app-suivi-reconciliation/imports_app/sqlite_scenarios.py` | `Scenarios.test_statistics_are_outside_import_and_before_private_preparation.observe_preparation` | Vérifie le commit privé avant d'appeler le vrai calcul, sans modifier ses valeurs. |
| `app-suivi-reconciliation/imports_app/sqlite_scenarios.py` | `Scenarios.test_statistics_failure_keeps_current_campaign_unmodified` | Un échec sur la copie empêche toute publication et laisse les données existantes intactes. |
| `app-suivi-reconciliation/imports_app/sqlite_staging.py` | `clear_unpublished` | Nettoie les lots invisibles d'un import interrompu, enfants avant parents. |
| `app-suivi-reconciliation/imports_app/sqlite_staging.py` | `staged_import` | Prépare la copie SQLite puis publie atomiquement, sans maintenance dans l'import. |
| `app-suivi-reconciliation/reconciliation/campaigns.py` | `import_campaign` | Importe `header` et l'itérateur JSONL `stream` dans la transaction parente. |
| `app-suivi-reconciliation/reconciliation/management/commands/maintain_sqlite_statistics.py` | `Command` | Vérifie les statistiques et propose --force pour un diagnostic volontaire. |
| `app-suivi-reconciliation/reconciliation/management/commands/maintain_sqlite_statistics.py` | `Command.add_arguments` | Déclare le forçage et l'alias Django ; pas de chemin arbitraire ni de commande destructive. |
| `app-suivi-reconciliation/reconciliation/management/commands/maintain_sqlite_statistics.py` | `Command.handle` | Affiche le résultat non sensible ; échoue proprement si report/erreur, sans recalcul métier. |
| `app-suivi-reconciliation/reconciliation/management/commands/prepare_accounting.py` | `Command` | Construit les seuls agrégats techniques, sans modifier sources ou décisions. |
| `app-suivi-reconciliation/reconciliation/management/commands/prepare_accounting.py` | `Command.add_arguments` | Ajoute campagne et forçage explicite des statistiques ; aucune histoire choisie implicitement. |
| `app-suivi-reconciliation/reconciliation/management/commands/prepare_accounting.py` | `Command.handle` | Maintient SQLite si nécessaire puis prépare avec progression, hors transaction globale. |
| `app-suivi-reconciliation/reconciliation/management/commands/prepare_accounting.py` | `Command.handle.progress` | Affiche compteur/total et temps écoulé, sans code projet ni donnée comptable. |
| `app-suivi-reconciliation/reconciliation/sqlite_statistics.py` | `defer_private_accounting` | Diffère le seul cadrage dans un import privé ; restaure le contexte même après erreur. |
| `app-suivi-reconciliation/reconciliation/sqlite_statistics.py` | `statistics_missing` | Teste les statistiques des tables utiles sans compter les grandes populations. |
| `app-suivi-reconciliation/reconciliation/sqlite_statistics.py` | `maintain_statistics` | Actualise les statistiques SQLite hors transaction, ou retourne un motif de non-exécution. |
| `app-suivi-reconciliation/reconciliation/sqlite_statistics.py` | `maintain_statistics.result` | Construit un bilan non sensible et journalise la décision sans paramètres métier. |
| `app-suivi-reconciliation/reconciliation/sqlite_statistics.py` | `after_campaign_commit` | Enregistre une maintenance synchrone après commit, annulée en cas de rollback. |
| `app-suivi-reconciliation/reconciliation/sqlite_statistics.py` | `after_campaign_commit.completed` | Exécute la maintenance sur la connexion committée ; n'altère aucune campagne. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests` | Exerce le vrai ANALYZE hors transaction sur une base de test exclusivement. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.setUp` | Retire les statistiques de la base jetable pour rendre chaque décision reproductible. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_missing_then_present_and_force_preserve_business_rows` | La première maintenance crée des statistiques ; les suivantes ignorent ou forcent sans mutation métier. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_commit_runs_after_transaction_and_rollback_runs_nothing` | La maintenance n'est appelée qu'après commit réel ; un rollback supprime le callback. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_commit_runs_after_transaction_and_rollback_runs_nothing.completed` | Relève l'état transactionnel sans effectuer de maintenance SQL supplémentaire. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_active_transaction_and_private_staging_defer_explicitly` | Une transaction interdit ANALYZE ; le staging privé utilise son séquencement explicite. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_non_sqlite_and_disabled_policy_never_issue_sql` | PostgreSQL est ignoré avant tout SQL spécifique ; la politique automatique est désactivable. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_errors_are_explicit_and_logs_do_not_include_parameters` | Une erreur SQL produit un bilan sans message sensible ; aucun traceback ni paramètre n'est logué. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_explicit_command_reports_backend_and_duration` | La commande d'exploitation force la collecte et rend son motif visible. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_race_rechecks_statistics_after_writer_lock` | Si une autre maintenance vient de finir, le contrôle sous verrou évite un second ANALYZE. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_race_rechecks_statistics_after_writer_lock.observe` | Relève les seuls mots SQL de la recette, puis conserve le comportement réel. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_failure_during_analyze_releases_its_transaction` | Une erreur après BEGIN IMMEDIATE fait rollback et libère le verrou de maintenance. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_failure_during_analyze_releases_its_transaction.fail` | Simule une erreur uniquement sur ANALYZE ; les autres requêtes gardent leur effet réel. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `SQLiteStatisticsTests.test_post_commit_unexpected_failure_is_reported_without_false_rollback` | Une erreur inattendue du callback est loguée sans divulgation ni échec fictif de l'import committé. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `StatisticsImportTests` | Intégration à l'import atomique, sans maintenance dans les services de correction. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `StatisticsImportTests.setUpClass` | Génère une seule fois les sources fictives, sans accès aux données utilisateur. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `StatisticsImportTests.tearDownClass` | Libère les fichiers synthétiques créés pour cette recette. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `StatisticsImportTests.test_successful_import_schedules_and_failed_import_does_not` | Un import validé enregistre sa maintenance après commit ; une erreur ne laisse aucun callback. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `StatisticsImportTests.test_business_action_and_refresh_do_not_maintain_statistics` | Correction, confirmation et lecture des agrégats ne lancent jamais ANALYZE. |
| `app-suivi-reconciliation/reconciliation/test_sqlite_statistics.py` | `StatisticsImportTests.test_prepare_command_progress_and_statistics_are_separate_from_calculation` | La commande affiche total et temps, sans modifier les montants ou états des synthèses. |

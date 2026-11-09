# UX cadrage : inventaire des docstrings

Comparaison AST avec HEAD.

20 definitions nouvelles/modifiees ; 0 docstrings absentes.

| Fichier | Definition | Role |
|---|---|---|
| `app-suivi-reconciliation/reconciliation/accounting_views.py` | `selected_campaign` | Retourne (campagne, message) pour la dernière photographie publiée prête et accessible. |
| `app-suivi-reconciliation/reconciliation/accounting_views.py` | `state_filter` | Lit un choix exclusif GET autorisé ; une valeur absente/inconnue signifie Toutes, sans effet de bord. |
| `app-suivi-reconciliation/reconciliation/accounting_views.py` | `filter_parameters` | Retourne les champs GET cachés à préserver, y compris valeurs répétées ; aucune mutation de l'URL. |
| `app-suivi-reconciliation/reconciliation/accounting_views.py` | `accounting_list` | Affiche les synthèses autorisées avec GET multisélection et pagination, sans calcul métier. |
| `app-suivi-reconciliation/reconciliation/accounting_views.py` | `accounting_detail` | Présente un projet autorisé, ses types et groupes paginés ; 404 hors portefeuille. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests` | Les chiffres se déduisent des groupes existants, jamais de propositions supposées confirmées. |
| `app-suivi-reconciliation/reconciliation/test_accounting.py` | `AccountingTests.test_list_cost_and_pagination_on_large_materialized_campaign` | Mesure 120 projets/12000 groupes ; seule la disponibilité est vérifiée par EXISTS, sans charger d'inventaire. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests` | Exerce les GET publics sur des campagnes préparées ou partielles et des groupes fictifs. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.setUpClass` | Prépare les sources synthétiques une fois ; toutes les écritures restent dans la base de test. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.tearDownClass` | Libère les seuls fichiers de recette temporaires. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.summary` | Retourne la synthèse P initiale, sans reconstruire les agrégats. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.detail` | Consulte le détail du projet de test avec les GET fournis ; aucun effet métier. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.campaign_with_summary` | Crée une photographie minimale prête ; ne change pas la campagne courante existante. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.test_latest_ready_published_accessible_campaign_and_legacy_parameter` | Une campagne cachée ou inaccessible ne supplante pas la dernière prête ; les vieux paramètres sont ignorés. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.test_partial_preparation_is_not_selected` | Une synthèse manquante pour un projet autorisé empêche la sélection d'une campagne partielle. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.test_no_published_unprepared_and_inaccessible_messages` | Les trois absences sont explicites sans noms de campagnes interdites ni erreur serveur. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.test_independent_filters_use_stored_gaps_and_keep_unknown_in_all` | Les écarts nuls comparables sont équilibrés ; insuffisants et hors périmètre restent dans Toutes. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.test_group_pagination_anchors_parameters_filter_reset_and_return` | Les pages et liens descendants gardent les deux filtres ; seul le formulaire groupes remet page à 1. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.test_summary_and_get_filters_preserve_all_financial_results` | La consultation après confirmation et correction conserve strictement tous les montants et états. |
| `app-suivi-reconciliation/reconciliation/test_accounting_ux.py` | `AccountingUXTests.test_negative_stored_amounts_are_presented_without_conversion` | Un snapshot synthétique négatif reste négatif et filtrable, sans recalcul de son contenu. |

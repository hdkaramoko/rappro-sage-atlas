# UX controles : inventaire des docstrings

Comparaison AST avec HEAD, le 9 novembre 2026.

19 definitions nouvelles/modifiees ; 0 docstrings absentes.

| Fichier | Definition | Role |
|---|---|---|
| `app-suivi-reconciliation/reconciliation/business_views.py` | `inventory_detail` | Présente une ligne Atlas exacte et les deux actions Lot 2 autorisées. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `control_workspace` | Affiche les anomalies courantes par défaut, avec filtres et pagination serveur. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests` | Exerce les vues avec sources fictives et base jetable, sans modifier le métier. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.setUpClass` | Prépare le JSONL synthétique via le moteur réel, dans un dossier temporaire. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.tearDownClass` | Libère uniquement les fichiers de recette créés par cette classe. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.workspace` | Retourne la liste filtrée par les paramètres GET, sans mutation des sources. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.create_control` | Crée un contrôle fictif dont l'état courant diffère de l'initial pour tester le filtre. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.panel` | Extrait l'en-tête HTML du panneau nommé pour contrôler sa visibilité serveur. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.test_current_states_all_and_multiple_filters` | Les états actuels s'unissent, Toutes prime, et projet/recherche se croisent en SQL. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.test_pagination_preserves_selections_and_reset` | La deuxième page conserve les GET répétés et le lien de remise à zéro reste simple. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.test_modes_and_invalid_post_keep_only_own_form_visible` | Le mode stable est Recherche ; une correction invalide reste visible et sans mutation. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.test_correct_preview_confirm_and_cancel_refresh_current_state` | Les POST existants restent indépendants et les vues suivent correction, confirmation et annulation. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.test_zero_gap_does_not_hide_remaining_reason` | L'interface affiche À revoir et son motif malgré un écart nul, sans forcer le métier. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.test_source_identity_long_labels_history_and_source_links` | Les textes longs échappés restent dans les cartes et les identifiants conservent leur lien. |
| `app-suivi-reconciliation/reconciliation/test_amount_control_ux.py` | `AmountControlUXTests.test_state_filter_does_not_load_json_for_count_or_page` | La multisélection conserve le comptage SQL léger et le chargement d'une seule page. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests` | Actions contextuelles, filtres SQL, révision et façade des contrôles courants. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_equal_totals_with_unconfirmed_context_are_not_resolved` | L'état courant équilibré conserve l'alerte distincte de proposition non confirmée. |
| `app-suivi-reconciliation/reconciliation/test_multiples.py` | `MultipleTests` | Vérifie les décisions, reports et exports avec deux groupes sur une même pièce. |
| `app-suivi-reconciliation/reconciliation/test_multiples.py` | `MultipleTests.test_prominent_validation_uses_existing_decision_state` | Le badge suit la décision et sa date locale affichée, même autour de minuit UTC. |

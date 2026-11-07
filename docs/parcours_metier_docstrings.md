# Parcours métier : inventaire des définitions

Comparaison AST du diff avec HEAD, le 6 novembre 2026. Le rôle ci-dessous est issu de la docstring française ; les détails de droits, paramètres et effets figurent dans le code.

44 définitions nouvelles/modifiées, 0 docstrings absentes.

| Fichier | Définition | Rôle documenté |
|---|---|---|
| `app-suivi-reconciliation/reconciliation/business_forms.py` | `CancelLinkForm` | Exige une confirmation et un motif pour retirer une association existante. |
| `app-suivi-reconciliation/reconciliation/business_views.py` | `inventory_detail` | Présente une ligne Atlas exacte et les deux actions Lot 2 autorisées. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `HasControlContext` | Teste une clé de contexte JSON dynamique en SQL SQLite et PostgreSQL. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `HasControlContext.as_sqlite` | Compile le test d'existence SQLite ; les clés sont des empreintes hexadécimales. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `HasControlContext.as_postgresql` | Compile l'opérateur JSONB PostgreSQL, sans conversion en recherche textuelle. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `global_controls_for` | Retourne les contrôles publiés du portefeuille avec leur résultat courant. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `control_workspace` | Affiche les anomalies courantes par défaut, avec filtres et pagination serveur. |
| `app-suivi-reconciliation/reconciliation/global_views.py` | `global_control_detail` | Présente les montants courant/initial et les sources autorisées du contrôle pk. |
| `app-suivi-reconciliation/reconciliation/journey.py` | `selections` | Lit les valeurs GET multiples autorisées ; une valeur vide signifie Toutes. |
| `app-suivi-reconciliation/reconciliation/journey.py` | `filter_menu` | Construit les cases et le résumé accessible d'un filtre serveur sans mutation. |
| `app-suivi-reconciliation/reconciliation/journey.py` | `no_match_query` | Identifie en SQL l'absence de proposition exploitable, indépendamment de sa règle. |
| `app-suivi-reconciliation/reconciliation/journey.py` | `safe_return` | Conserve uniquement un retour local vers les écrans autorisés du parcours. |
| `app-suivi-reconciliation/reconciliation/journey.py` | `line_actions` | Dérive les actions visibles de la décision, de sa fraîcheur et des preuves. |
| `app-suivi-reconciliation/reconciliation/review.py` | `decide` | Enregistre une décision avec permissions, signatures et verrous campagne/groupe. |
| `app-suivi-reconciliation/reconciliation/review_views.py` | `visible` | Retourne les lignes autorisées de la campagne publiée courante, ou héritées. |
| `app-suivi-reconciliation/reconciliation/review_views.py` | `review_list` | Présente Envoyé SAGE ou la façade de contrôles, avec filtres SQL multiples. |
| `app-suivi-reconciliation/reconciliation/review_views.py` | `review_detail` | Présente les preuves autorisées et délègue les décisions atomiques de la revue pk. |
| `app-suivi-reconciliation/reconciliation/revision.py` | `RevisionForm` | Confirmation de révision : motif requis, versions et signature cachées. |
| `app-suivi-reconciliation/reconciliation/revision.py` | `reopen_review` | Annule une validation AUTO ou MANUAL sans toucher aux sources ni à l'historique. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests` | Actions contextuelles, filtres SQL, révision et façade des contrôles courants. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.setUpClass` | Génère une campagne Lot 1 réelle à partir de sources strictement synthétiques. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.tearDownClass` | Libère les seuls fichiers de recette temporaires générés par cette classe. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.setUp` | Initialise utilisateur, portefeuille et campagne publiée de recette. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.line` | Retourne la projection courante S avec les relations nécessaires à la signature. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.detail_url` | Construit l'adresse de la fiche de décision de la ligne S synthétique. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_usable_proposal_prioritizes_decision_without_lot2_buttons` | Une proposition exploitable garde Valider/Refuser sans les actions manuelles en tête. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_unmatched_and_amount_anomaly_offer_contextual_actions` | Sans preuve, la recherche est proposée et une anomalie de montant permet Corriger. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_confirmed_manual_revision_releases_and_audits` | La révision motivée libère Sage, conserve l'ancienne décision et recalcule la pièce. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_revision_requires_confirmation_reason_permissions_and_versions` | Case/motif manquants, accès interdit ou page périmée ne libèrent aucune écriture. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_auto_revision_is_explicit_and_preserves_its_origin` | Une AUTO ne peut être éditée par un POST ordinaire ; sa contestation reste auditée. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_revising_carried_link_never_mutates_historical_campaign` | La révision ne touche que les réservations courantes d'un lien repris. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_global_view_uses_current_totals_and_anomalies_by_default` | La façade lit le résultat recalculé et inclut les Envoyé confirmés une seule fois. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_equal_totals_with_unconfirmed_context_are_not_resolved` | Une proposition non confirmée maintient l'alerte même à totaux comptables égaux. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_global_scope_and_ods_identity_are_preserved` | Les ODS utilisent leur identité composite et un contrôle hors portefeuille répond 404. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_multifilters_union_intersection_all_and_return` | Les choix multiples s'unissent par dimension et se croisent entre dimensions en SQL. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_cancel_link_form_demands_confirmation_and_preserves_return` | L'annulation depuis l'inventaire exige un motif et conserve le retour filtré. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_filters_and_global_list_are_read_only_and_paginated` | Les listes ne recalculent rien et paginent en SQL sans charger toutes les preuves. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_stale_validation_is_back_in_to_examine` | Une validation invalidée par correction revient dans la file À examiner. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_multi_selection_pagination_preserves_every_value` | La deuxième page conserve projets, règles et origines sans requêtes par preuve. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_closed_campaign_cannot_be_revised_and_return_url_is_local` | Campagne close : lecture seule ; les URL de retour externes sont neutralisées. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_zero_gap_ambiguous_control_is_not_reconciled` | Un état INDETERMINE à écart nul demeure une anomalie, sans nouveau calcul métier. |
| `app-suivi-reconciliation/reconciliation/test_journey.py` | `JourneyTests.test_replacement_preview_shows_old_and_new_and_keeps_history` | Un remplacement exige confirmation explicite et conserve les cibles avant/après. |
| `app-suivi-reconciliation/reconciliation/test_ui.py` | `ReviewUITests` | Vérifie le rendu métier, les permissions et la pagination des écrans de revue. |
| `app-suivi-reconciliation/reconciliation/test_ui.py` | `ReviewUITests.test_default_uses_status_not_rule` | Le parcours par défaut inclut les cas manuels après les propositions, sans filtre caché. |

JavaScript (`static/js/multifilter.js`) : `initializeMultiFilters` initialise les menus accessibles ; `synchronizeFilter` synchronise Toutes/choix et le résumé. Les deux fonctions ont une documentation française structurée.

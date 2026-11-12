# Correctifs Confirmé / Exact v2 : inventaire des docstrings

Comparaison AST avec HEAD, actualisée le 8 novembre 2026.

48 définitions nouvelles/modifiées ; 0 docstrings absentes.

| Fichier | Définition | Rôle |
|---|---|---|
| `app-suivi-reconciliation/reconciliation/auto_validation.py` | `automatic_blockers` | Recense les conflits avant toute AUTO, indépendamment de l'ordre des lignes. |
| `app-suivi-reconciliation/reconciliation/auto_validation.py` | `apply_automatic_validations` | Applique les autorisations moteur aux décisions futures de `campaign`. |
| `app-suivi-reconciliation/reconciliation/collective_validation.py` | `apply_collective_validations` | Applique les Confirmé collectifs existants, sans traiter les affectations Exact. |
| `app-suivi-reconciliation/reconciliation/exact_collective.py` | `atlas_source` | Projette la source photographiée vers les noms du contrat pur, sans réécriture. |
| `app-suivi-reconciliation/reconciliation/exact_collective.py` | `validate_exact_group` | Prépare puis confirme tout le groupe Exact dans le savepoint de l'appelant. |
| `app-suivi-reconciliation/reconciliation/exact_collective.py` | `apply_exact_groups` | Traite les groupes Exact v3 multilignes avant les autorisations individuelles. |
| `app-suivi-reconciliation/reconciliation/global_control.py` | `campaign_controls` | Retourne en flux les contrôles actuels d'une campagne ou des `keys` ciblées. |
| `app-suivi-reconciliation/reconciliation/multiple_review.py` | `exact_entry` | Retourne l'unique écriture complète d'une proposition Exact v3. |
| `app-suivi-reconciliation/reconciliation/multiple_review.py` | `compatible_exact_peer` | Autorise une pièce partagée entre deux contributions AUTO Exact distinctes. |
| `app-suivi-reconciliation/reconciliation/multiple_review.py` | `context_for` | Signe les preuves fixes pertinentes ; ne signe jamais le solde des autres décisions. |
| `app-suivi-reconciliation/reconciliation/multiple_review.py` | `allocation_plan` | Décompose une réservation par pièce, sans sommer un total de groupe répété. |
| `app-suivi-reconciliation/reconciliation/multiple_review.py` | `apply_projection` | Contrôle puis remplace les réservations v3 de `line` sous verrou de campagne. |
| `app-suivi-reconciliation/reconciliation/piece_coherence.py` | `compatible_piece_peer` | N'exempte que des Confirmé distincts d'une même preuve collective courante. |
| `app-suivi-reconciliation/reconciliation/review.py` | `decide` | Enregistre une décision avec permissions, signatures et verrous campagne/groupe. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests` | Exerce les autorisations et les réservations réelles sans base de production. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.setUpClass` | Exécute une fois le vrai moteur sur trois lignes fictives du protocole A/B. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.tearDownClass` | Supprime les seuls fichiers synthétiques temporaires de la recette. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.load` | Importe une nouvelle photographie signée dans la base jetable de TestCase. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.confirmed` | Charge la ligne Confirmé de recette avec les relations de signature nécessaires. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.validate_confirmed` | Soumet la décision humaine sans commentaire pour le seul écart de BAP. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_engine_jsonl_and_exact_group_individual_reservations` | 652,40 + 36,48 sont AUTO ensemble, avec deux références et total 688,88. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_manual_confirmed_bap_difference_is_audited_without_comment` | 1903381 retrouve l'écriture importée ; le BAP diverge mais n'interdit pas la décision humaine. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_confirmed_missing_or_ambiguous_evidence_stays_blocked` | Un contrôle équilibré ne remplace jamais l'identification d'une écriture unique. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_second_member_error_rolls_back_entire_exact_group` | Une erreur au second decide ne laisse ni AUTO ni réservation du premier membre. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_second_member_error_rolls_back_entire_exact_group.fail_second` | Simule un refus métier tardif dans le savepoint collectif de recette. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_human_priority_and_old_campaign_immutability` | Une décision humaine bloque tout nouveau groupe AUTO sans changer la campagne antérieure. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_policy_does_not_change_old_campaign_manual_path` | Sans marqueur de politique dans l'ancien JSONL, aucune nouvelle résolution manuelle n'est activée. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_group_order_does_not_change_attribution` | Permuter les lignes Atlas et les preuves conserve les mêmes affectations individuelles. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_identical_new_campaign_carries_without_duplicate_events` | Un nouvel import identique conserve les décisions AUTO et leurs événements d'origine. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_management_import_command_accepts_generated_bundle` | La commande réelle importe le nouveau JSONL, puis reste idempotente sur les mêmes octets. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_manual_confirmed_cent_tolerance_is_kept_by_global_control` | La tolérance déjà vérifiée sur la preuve individuelle survit au contrôle global ciblé. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_large_group_does_not_query_inventory_for_every_member` | Trente membres utilisent les services existants sans trente lectures d'inventaire Sage. |
| `app-suivi-reconciliation/reconciliation/validation_evidence.py` | `confirmed_manual_evidence` | Retrouve une preuve Confirmé unique dans le contrôle et l'inventaire courants. |
| `app-suivi-reconciliation/reconciliation/validation_evidence.py` | `exact_group_signature` | Signe les preuves et la composition immuables d'un groupe Exact ; lecture pure. |
| `app-suivi-reconciliation/reconciliation/validation_evidence.py` | `verified_exact_group_entry` | Revalide une affectation individuelle Exact créée par la préparation bijective. |
| `examples/validation_v2_fixture.py` | `generate` | Écrit les sources synthétiques A/B puis exécute le vrai moteur annuel. |
| `reconciliation/auto_validation.py` | `proposal_metadata` | Retourne l'autorisation AUTO d'un résultat moteur, ou None si non admissible. |
| `reconciliation/exporters/review.py` | `export_review_bundle` | Publie atomiquement un JSONL v2/v3 à partir des DataFrames et du résultat. |
| `reconciliation_contract/exact_assignment.py` | `exact_bijection` | Associe chaque source Atlas à une écriture réelle par clé complète et montant. |
| `reconciliation_contract/sage_inventory.py` | `consolidate` | Calcule les états Comptabilisé et global pour une seule clé métier. |
| `tests/test_validation_v2.py` | `sources` | Construit des sources Exact complètes avec références d'écritures distinctes. |
| `tests/test_validation_v2.py` | `test_unique_bijection_and_order` | Deux montants distincts donnent la même bijection quelle que soit la permutation. |
| `tests/test_validation_v2.py` | `test_incompatible_entry_blocks_group` | Une incohérence de clé, signe, année ou montant empêche toute attribution collective. |
| `tests/test_validation_v2.py` | `test_repeated_amount_or_reference_never_picks_arbitrarily` | Les répétitions créant plusieurs appariements et les références dupliquées sont refusées. |
| `tests/test_validation_v2.py` | `test_real_engine_exports_authorization_only_for_unique_group` | Le contrat v3 n'autorise le groupe moteur Exact que si sa bijection est démontrée. |
| `tests/test_validation_v2_tolerance.py` | `test_tolerance_requires_server_attestation_and_preserves_uniqueness` | La preuve unique attestée admet un centime, sans ouvrir la tolérance aux anciennes allocations. |
| `tests/test_validation_v2.py` | `test_xof_original_currency_keeps_eur_exact_authorization` | 1691538/1691539 : les charges EUR concordent malgré la devise d'origine XOF. |
| `app-suivi-reconciliation/reconciliation/test_validation_v2.py` | `ValidationV2Tests.test_xof_original_currency_auto_validates_eur_charges` | 1691538/1691539 sont AUTO en XOF d'origine, sans convertir les charges EUR. |

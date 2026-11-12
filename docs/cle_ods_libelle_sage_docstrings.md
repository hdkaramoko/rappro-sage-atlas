# Cle ODS : inventaire des docstrings

Comparaison AST avec HEAD, le 8 novembre 2026.

35 definitions nouvelles/modifiees ; 0 docstrings absentes.

| Fichier | Definition | Role |
|---|---|---|
| `app-suivi-reconciliation/reconciliation/business_calculation.py` | `business_inputs` | Projette corrections et liens dans les entrées Lot 1 des seuls groupes `keys`. |
| `app-suivi-reconciliation/reconciliation/campaigns.py` | `normalize_inventory` | Normalise la photographie Atlas sans créer de transaction hors matching. |
| `app-suivi-reconciliation/reconciliation/campaigns.py` | `import_campaign` | Importe `header` et l'itérateur JSONL `stream` dans la transaction parente. |
| `app-suivi-reconciliation/reconciliation/test_multiples.py` | `MultipleTests` | Vérifie les décisions, reports et exports avec deux groupes sur une même pièce. |
| `app-suivi-reconciliation/reconciliation/test_multiples.py` | `MultipleTests.test_ods_review_carries_only_identical_group` | Une revue ODS ne dépend pas d'une égalité intersource de numéro de pièce. |
| `app-suivi-reconciliation/reconciliation/test_multiples.py` | `MultipleTests.test_unknown_policy_blocks_without_bypassing_and_historical_v2_remains_readable` | Refuse un calcul impossible et lit le v2 historique en mode diagnostic compatible. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests` | Exerce le vrai moteur et l'import sans toucher aux campagnes de production. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.setUpClass` | Génère une fois les trois cas C/M/S sur fichiers temporaires synthétiques. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.tearDownClass` | Libère les seules sources générées pour cette recette. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.load` | Signe et importe une variante dans la base jetable, en ajustant ses compteurs. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.test_accounted_uses_sage_label_and_sent_keeps_atlas_matching` | Les deux parcours importés utilisent leur libellé propre et conservent les sources. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.test_empty_sage_label_is_visible_and_never_uses_atlas_fallback` | Un champ vide explicite reste indéterminé, malgré un libellé Atlas identique à Sage. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.test_new_policy_missing_column_or_unknown_policy_rolls_back` | Une politique inconnue ou un champ non transmis n'est pas interprété silencieusement. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.test_old_field_absence_keeps_historical_identity` | Une ancienne ligne canonique n'acquiert pas un champ vide qui changerait sa clé. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.test_manual_ods_projection_uses_new_label_without_modifying_source` | Un lien manuel ODS projette la preuve ciblée sans écraser les deux libellés source. |
| `app-suivi-reconciliation/reconciliation/test_ods_labels.py` | `OdsLabelTests.test_legacy_bundle_import_and_new_campaign_preserve_old_sources` | Un ancien v3 s'importe encore ; un nouveau flux ne réécrit pas ses preuves. |
| `app-suivi-reconciliation/reconciliation/test_sage_inventory.py` | `SageInventoryTests` | Exerce les photographies Sage sur la base de test, sans donnée de production. |
| `app-suivi-reconciliation/reconciliation/test_sage_inventory.py` | `SageInventoryTests.test_other_sage_label_does_not_merge_distinct_groups` | Un groupe identifié par Libellé SAGE n'est pas contaminé par un autre libellé du tiers. |
| `examples/lot1_fixture.py` | `generate` | Écrit dans `folder` deux sources et le JSONL du cas 6000 + 4000 = 10000. |
| `examples/ods_labels_fixture.py` | `generate` | Écrit trois sources Atlas fictives et lance le vrai moteur annuel. |
| `reconciliation/exporters/review.py` | `export_review_bundle` | Publie atomiquement un JSONL v2/v3 à partir des DataFrames et du résultat. |
| `reconciliation/multiples.py` | `inventory_rows` | Retourne en flux les dictionnaires canoniques Atlas du DataFrame `atlas`. |
| `reconciliation_contract/__init__.py` | `atlas_control_label` | Choisit le libellé du contrôle Atlas sans changer la recherche de propositions. |
| `reconciliation_contract/__init__.py` | `control_identity` | Résout la clé standard ou ODS ; les clés incomplètes restent isolées. |
| `reconciliation_contract/__init__.py` | `snapshot` | Photographie les preuves et leur diagnostic, avec signature métier stable. |
| `reconciliation_contract/sage_inventory.py` | `consolidate` | Calcule les états Comptabilisé et global pour une seule clé métier. |
| `tests/test_multiples.py` | `atlas_row` | Construit une charge comptabilisée avec deux libellés explicites pour la recette. |
| `tests/test_ods_labels.py` | `accounted` | Construit un ODS comptabilisé avec libellé Atlas volontairement différent. |
| `tests/test_ods_labels.py` | `test_accounted_ods_identity_uses_sage_label_and_preserves_both_sources` | Le texte Sage du fichier Atlas rejoint le libellé pièce Sage après normalisation commune. |
| `tests/test_ods_labels.py` | `test_missing_sage_label_is_reported_without_atlas_fallback` | Un libellé Sage vide reste vide dans la clé et bloque le contrôle, même avec un texte Atlas. |
| `tests/test_ods_labels.py` | `test_sent_matching_still_uses_atlas_label_with_different_sage_label` | La proposition Exact Envoyé reste fondée sur Libellé ATLAS, jamais sur Libellé SAGE. |
| `tests/test_ods_labels.py` | `test_old_canonical_source_keeps_historical_identity` | L'absence historique de sage_label ne réinterprète pas une clé déjà signée. |
| `tests/test_ods_labels.py` | `test_v3_exports_sage_label_and_policy_without_changing_matching` | Le vrai moteur/exporteur conserve les deux libellés dans le nouveau JSONL v3. |
| `tests/test_sage_inventory.py` | `test_ods_unique_group_with_or_without_label` | Le contrat historique conserve ses clés et son exception de libellé absent unique. |
| `tests/test_sage_inventory.py` | `test_ods_amount_mismatch_and_prefix_journal_disagreement` | Une égalité composite n'efface ni écart monétaire ni convention contradictoire. |

"""Recette du périmètre Sage exhaustif et du diagnostic ODA, sur données synthétiques."""

from decimal import Decimal

from django.test import TestCase
from reconciliation_contract import control_identity, digest, entry_from_sage
from reconciliation_contract.sage_inventory import CAPABILITY, exclusion_policy, inventory_record

from .accounting import prepare_campaign, refresh_project
from .models import Campaign, CampaignInventory, CampaignSageEntry


class ExhaustiveAccountingTests(TestCase):
    """Vérifie sommes, exclusions explicites, identités et absence d'effets métier."""

    def setUp(self):
        """Crée une photographie vide mais complète dont le périmètre est explicitement connu."""
        self.campaign = Campaign.objects.create(name="Recette exhaustive", is_current=True,
            scope="atlas-complet", fiscal_year=2026, inventory_complete=True,
            metadata={"capabilities": [CAPABILITY], "amount_field": "total_sage_charges", "tolerance": "0.01"})

    def atlas(self, amount="1000", document="FAC001", *, party="T", status="Comptabilisé"):
        """Ajoute une source Atlas synthétique sans revue ni décision, puis retourne sa photographie."""
        number = self.campaign.inventory.count() + 1
        data = {"project_code": "P", "fiscal_year": 2026, "source_id": str(number), "bap_status": status,
                "total_sage_charges": amount, "total_project_charges": amount, "accounting_date": "2026-01-01",
                "sage_document_number": document, "sage_third_party_code": party, "sage_label": "Mission", "atlas_label": "Mission"}
        return CampaignInventory.objects.create(campaign=self.campaign, project_code="P", fiscal_year=2026,
            business_key=f"P::2026::{number}", source_id=str(number), data=data, control_key=digest(control_identity(data)))

    def sage(self, amount="1000", document="FAC001", *, party="T", line="1", excluded=False, date="2026-01-01", project="P"):
        """Ajoute une écriture canonique, avec empreinte témoin distincte pour tester les doublons techniques."""
        entry = entry_from_sage({"Projet": project, "Numéro pièce": document, "Date comptable": date,
            "Journal": document[:3], "N° de ligne comptable": line, "N° de ligne Analytique": "1",
            "Code Tiers - Tiers doc Orig": party, "Libellé pièce": "Mission", "Charges (Dépenses)": amount})
        policy = exclusion_policy([document[:3]] if excluded else [])
        data = inventory_record(entry, policy, source_fingerprint=digest([self.campaign.sage_inventory.count()]))
        return CampaignSageEntry.objects.create(campaign=self.campaign, project_code=project, fiscal_year=entry["fiscal_year"],
            document=document, entry_ref=entry["ref"], record_id=data["record_id"], control_key=data["control_key"],
            amount=amount, eligible=not excluded, data=data)

    def summary(self):
        """Reconstruit uniquement les agrégats du projet puis vérifie la conservation exacte des détails."""
        result = refresh_project(self.campaign, "P")
        for field in ("atlas", "sage"):
            if getattr(result, field) is not None:
                self.assertEqual(sum((getattr(row, field) for row in self.campaign.accounting_groups.all()), Decimal(0)), getattr(result, field))
                self.assertEqual(sum((Decimal(row[field]) for row in result.data["types"]), Decimal(0)), getattr(result, field))
        return result

    def test_unattached_sage_is_included_once(self):
        """1000 Atlas contre 1000 reliés et 200 sans Atlas donnent 1200 Sage et un écart de -200."""
        self.atlas()
        self.sage()
        self.sage("200", "INV001")
        result = self.summary()
        self.assertEqual((result.atlas, result.sage, result.gap, result.state), (Decimal(1000), Decimal(1200), Decimal(-200), "NON_CADRE"))
        self.assertEqual(Decimal(result.data["totals"]["unattached_sage"]), 200)
        orphan = self.campaign.accounting_groups.get(piece_type="INV")
        self.assertFalse(orphan.data["attached"])
        self.assertEqual(orphan.state, "NON_CADRE")

    def test_explicit_exclusion_remains_outside_sage(self):
        """Les 200 explicitement exclus sont tracés mais ne quittent pas artificiellement un total relié."""
        self.atlas()
        self.sage()
        self.sage("200", "INV001", excluded=True)
        result = self.summary()
        self.assertEqual((result.state, result.sage), ("CADRE", Decimal(1000)))
        self.assertEqual(Decimal(result.data["totals"]["excluded_sage"]), 200)

    def test_distinct_equal_entries_are_both_counted(self):
        """Deux écritures réelles de 500 ne sont jamais fusionnées parce que leurs montants sont égaux."""
        self.atlas("500")
        self.sage("500", line="1")
        self.sage("500", line="2")
        result = self.summary()
        self.assertEqual((result.sage, result.gap, result.state), (Decimal(1000), Decimal(-500), "NON_CADRE"))

    def test_proven_duplicate_only_is_neutralized(self):
        """La même identité complète et le même contenu ne sont comptés qu'une fois, avec diagnostic."""
        self.atlas()
        self.sage()
        self.sage()
        result = self.summary()
        self.assertEqual((result.sage, result.state), (Decimal(1000), "CADRE"))
        self.assertEqual(result.data["counts"]["technical_duplicates"], 1)
        self.assertTrue(result.data["diagnostics"])
        self.sage("50")
        self.assertEqual(self.summary().sage, Decimal(1050))

    def test_oda_missing_party_uses_document_without_mutation(self):
        """NA, null et vide permettent le contrôle d'une ODA unique par pièce, sans toucher au tiers source."""
        for party in ("NA", "", None):
            with self.subTest(party=party):
                self.campaign.inventory.all().delete()
                self.campaign.sage_inventory.all().delete()
                self.campaign.global_controls.all().delete()
                source = self.atlas(document="ODA001", party=party)
                self.sage(document="ODA001", party="REAL_PARTY")
                before = source.data.copy()
                result = self.summary()
                self.assertEqual(result.state, "CADRE")
                oda = self.campaign.accounting_groups.get().data["oda"]
                self.assertTrue(oda["reliable"])
                self.assertFalse(oda["automatic_authorization"])
                source.refresh_from_db()
                self.assertEqual(source.data, before)

    def test_oda_mismatch_and_repeated_amounts_do_not_authorize(self):
        """Un écart ou des montants concurrents conservent la revue individuelle, sans affectation automatique."""
        self.atlas("500", "ODA001", party="NA")
        self.sage("500", "ODA001", line="1")
        self.sage("500", "ODA001", line="2")
        result = self.summary()
        self.assertEqual((result.state, result.sage), ("NON_CADRE", Decimal(1000)))
        self.assertFalse(self.campaign.accounting_groups.get().data["oda"]["reliable"])
        self.atlas("500", "ODA001", party="NA")
        # Les sources de cette variante sont rephotographiées avant son calcul.
        self.campaign.global_controls.all().delete()
        self.assertEqual(self.summary().state, "CADRE")
        self.assertFalse(self.campaign.accounting_groups.get().data["oda"]["reliable"])

    def test_exception_not_applied_to_known_parties_or_sent(self):
        """Les tiers renseignés, autres types et Envoyé SAGE ne reçoivent pas cette exception."""
        self.atlas(document="ODA001", party="KNOWN")
        self.sage(document="ODA001", party="DIFFERENT")
        self.summary()
        self.assertNotIn("oda", self.campaign.accounting_groups.get().data)
        self.atlas(document="FAC002", party="NA")
        self.sage(document="FAC002")
        self.summary()
        self.assertNotIn("oda", self.campaign.accounting_groups.get(control__data__identity__parts__2="FAC002").data)

    def test_ods_missing_party_is_diagnostic_only_when_totals_known(self):
        """Une clé ODS sans tiers ne bloque pas les totaux projet ; un montant absent reste bloquant."""
        self.atlas(document="ODS001", party="")
        self.sage(document="ODS001", party="T")
        result = self.summary()
        self.assertEqual(result.state, "CADRE")
        self.assertTrue(result.data["diagnostics"])
        self.sage(None, "ODS002")
        self.assertEqual(refresh_project(self.campaign, "P").state, "INSUFFISANT")

    def test_unknown_scope_stays_insufficient(self):
        """Un exercice absent interdit de présenter le montant connu comme un total de campagne fiable."""
        self.atlas()
        self.sage(date=None)
        result = refresh_project(self.campaign, "P")
        self.assertEqual(result.state, "INSUFFISANT")
        self.assertIsNone(result.data["totals"]["sage"])

    def test_missing_atlas_piece_does_not_force_oda_identification(self):
        """Sans pièce Atlas, les totaux restent calculables mais aucune exception ODA n'est inventée."""
        self.atlas(document="", party="NA")
        self.sage(document="ODA001")
        self.assertEqual(self.summary().state, "CADRE")
        self.assertFalse(any("oda" in row.data for row in self.campaign.accounting_groups.all()))

    def test_signed_decimals_and_rebuild_are_idempotent(self):
        """Les signes et décimales sont conservés ; deux préparations produisent les mêmes montants et diagnostics."""
        self.atlas("-12.3456789")
        self.sage("-12.3456789")
        first = self.summary()
        prepare_campaign(self.campaign)
        second = self.campaign.accounting_projects.get(project_code="P")
        self.assertEqual((first.atlas, first.sage, first.data), (second.atlas, second.sage, second.data))
        self.assertEqual(second.state, "CADRE")

    def test_absent_inventory_and_unconfirmed_missing_amount(self):
        """Un Envoyé non confirmé sans montant n'affecte pas le retenu ; l'absence d'inventaire complet bloque."""
        self.atlas(None, status="Envoyé SAGE")
        self.sage("100")
        result = self.summary()
        self.assertEqual((result.atlas, result.sage, result.state), (Decimal(0), Decimal(100), "NON_CADRE"))
        self.assertIsNone(result.data["totals"]["pending_initial"])
        self.campaign.inventory_complete = False
        self.campaign.save(update_fields=["inventory_complete"])
        self.assertEqual(refresh_project(self.campaign, "P").state, "INSUFFISANT")

    def test_stale_projection_restores_atlas_to_its_source_group(self):
        """Un retenu absent des projections reste dans sa pièce source sans création d'affectation Sage."""
        self.atlas()
        self.sage()
        self.summary()
        control = self.campaign.global_controls.get()
        control.current_data = {**control.data, "accounted_total": "0", "atlas_ids": [], "atlas_count": 0,
                                "reasons": ["Rapprochement manuel à revoir après modification métier"]}
        control.save(update_fields=["current_data"])
        result = self.summary()
        self.assertEqual((result.atlas, result.sage, result.state), (Decimal(1000), Decimal(1000), "CADRE"))
        self.assertEqual(Decimal(self.campaign.accounting_groups.get().data["unprojected_atlas"]), Decimal(1000))
        self.assertFalse(self.campaign.reviews.exists())

    def test_excluded_null_amount_does_not_block_eligible_total(self):
        """Un montant inconnu mais explicitement exclu ne rend pas le total éligible inconnu."""
        self.atlas()
        self.sage()
        self.sage(None, "INV001", excluded=True)
        result = self.summary()
        self.assertEqual((result.sage, result.state), (Decimal(1000), "CADRE"))
        self.assertIsNone(result.data["totals"]["excluded_sage"])

    def test_mixed_ods_types_respect_only_explicit_exclusion(self):
        """Un groupe commun ODS/ODG retire seulement la part ODS explicitement exclue des deux comparateurs."""
        self.atlas("100", "ODS001")
        self.atlas("100", "ODG001")
        # Le journal égal au préfixe permet le même groupe composite sans conflit.
        self.sage("100", "ODS001", excluded=True)
        self.sage("100", "ODG001")
        result = self.summary()
        self.assertEqual((result.atlas, result.sage, result.state), (Decimal(100), Decimal(100), "CADRE"))
        self.assertEqual(Decimal(result.data["totals"]["outside_atlas"]), 100)

    def test_oda_other_project_or_incomplete_identity_never_authorizes(self):
        """Une pièce homonyme d'un autre projet ne résout pas P ; une identité absente interdit le diagnostic fiable."""
        self.atlas(document="ODA001", party="NA")
        self.sage(document="ODA001", project="Q")
        self.assertEqual(self.summary().state, "NON_CADRE")
        self.assertFalse(self.campaign.accounting_groups.get().data["oda"]["reliable"])
        self.sage(document="ODA001", line="")
        self.assertEqual(self.summary().state, "CADRE")
        self.assertFalse(self.campaign.accounting_groups.get().data["oda"]["reliable"])

    def test_oda_known_party_mismatch_is_not_hidden_by_missing_neighbor(self):
        """Une ligne NA voisine ne dispense jamais une ligne au tiers renseigné de sa concordance individuelle."""
        self.atlas("300", "ODA001", party="NA")
        self.atlas("700", "ODA001", party="KNOWN")
        self.sage("300", "ODA001", party="A", line="1")
        self.sage("700", "ODA001", party="DIFFERENT", line="2")
        self.assertEqual(self.summary().state, "CADRE")
        self.assertFalse(self.campaign.accounting_groups.get().data["oda"]["reliable"])

    def test_nine_decimals_remain_exact_above_sqlite_significant_precision(self):
        """Les chaînes canoniques à neuf décimales restent exactes même au-delà de quinze chiffres significatifs SQLite."""
        self.atlas("12345678.123456789")
        self.sage("12345678.123456789")
        result = refresh_project(self.campaign, "P")
        self.assertEqual(Decimal(result.data["totals"]["sage"]), Decimal("12345678.123456789"))
        self.assertEqual(Decimal(self.campaign.accounting_groups.get().data["totals"]["sage"]), Decimal("12345678.123456789"))
        self.assertEqual(result.state, "CADRE")

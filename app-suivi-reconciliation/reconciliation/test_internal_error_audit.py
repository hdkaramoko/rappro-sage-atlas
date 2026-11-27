"""Diagnostic uniquement : parcours proposition Confirmé -> révision, SQLite isolé."""
import copy
import json
from decimal import Decimal
from unittest.mock import patch
from django.urls import reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext
from accounts.models import User
from .test_validation_v2 import ValidationV2Tests
from .models import ControlContribution, ReviewEvent, CampaignAction
from .review import signature
from .accounting import refresh_project


class InternalErrorAuditTests(ValidationV2Tests):
    # Réutilise le générateur moteur et l'import réels ; seuls les tests audit sont collectés.
    def scenario(self, negative=False, remove=False, other=False, accounting=False, fail=False, shared=False, collective=True):
        records = copy.deepcopy(self.records)
        if negative or shared:
            import subprocess
            from tempfile import TemporaryDirectory
            from pathlib import Path
            root = Path(__file__).resolve().parents[2]
            with TemporaryDirectory() as folder:
                code = (root / 'examples/validation_v2_fixture.py').read_text(encoding='utf-8').replace('"8820"', '"-2500"')
                if not negative:
                    code = code.replace('"-2500"', '"8820"')
                if shared:
                    code = code.replace('("1559564",', '("1903382", "100", "FAF0126101276", "SECOND", "4"),\n        ("1559564",')
                    code = code.replace('source == "1903381"', 'source in ("1903381", "1903382")')
                code = code[:code.index('if __name__ ==')]
                code += "\nraise SystemExit(generate(" + repr(folder) + "))"
                result = subprocess.run([str(root / '.venv/Scripts/python.exe'), '-c', code],
                    cwd=root, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                records = [json.loads(row) for row in (Path(folder) / 'campaign.jsonl').read_text(encoding='utf-8').splitlines()]
        if not collective:
            for row in records:
                if row.get('type') == 'proposal':
                    row.pop('auto_validation', None)
        campaign = self.load(records)
        line = self.confirmed()
        self.assertEqual(line.group.rule, 'MATCH_CONFIRMED_ATLAS')
        self.assertEqual(line.transaction.bap_status, 'Envoyé SAGE')
        source = {f.attname: getattr(line.transaction, f.attname) for f in line.transaction._meta.fields}
        inventories = list(campaign.inventory.values_list('pk', 'data'))
        sage = list(campaign.sage_inventory.values_list('pk', 'data'))
        peers = list(ControlContribution.objects.exclude(line=line).values_list('pk', 'amount', 'entries'))
        url = reverse('reconciliation:review-detail', args=[line.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        payload = {'action': 'VALIDATED', 'version': line.version,
                   'group_version': line.group.version, 'source': signature(line), 'comment': ''}
        for field in ('status', 'amount', 'document', 'date'):
            payload[field + '_mode'] = 'SET' if field == 'status' else 'KEEP'
        payload['status'] = 'Comptabilisé'
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        line = self.confirmed()
        self.assertEqual(line.state, 'VALIDATED')
        self.assertEqual(ControlContribution.objects.get(line=line).amount, Decimal('-2500' if negative else '8820'))
        if remove:
            ControlContribution.objects.filter(line=line).delete()
        if accounting:
            refresh_project(campaign, 'P')
        if other:
            actor = User.objects.create_superuser('audit_other', password='test')
            self.client.force_login(actor)
        before = (line.version, ReviewEvent.objects.count(), CampaignAction.objects.count())
        payload = {'action': 'REVISE', 'version': line.version,
                   'group_version': line.group.version, 'source': signature(line), 'comment': 'Diagnostic révision'}
        if fail:
            with patch('reconciliation.business.recalculate', side_effect=RuntimeError('audit panne recalcul')):
                with self.assertRaisesRegex(RuntimeError, 'audit panne recalcul'):
                    self.client.post(url, payload)
            line = self.confirmed()
            self.assertEqual(line.state, 'VALIDATED')
            self.assertEqual((line.version, ReviewEvent.objects.count(), CampaignAction.objects.count()), before)
            self.assertTrue(ControlContribution.objects.filter(line=line).exists())
        else:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(url, payload)
            self.assertEqual(response.status_code, 302)
            line = self.confirmed()
            self.assertEqual(line.state, 'DRAFT')
            self.assertFalse(ControlContribution.objects.filter(line=line).exists())
            self.assertEqual(line.events.first().snapshot['before']['state'], 'VALIDATED')
            self.assertEqual(line.events.first().snapshot['comment'], 'Diagnostic révision')
            self.assertTrue(any('LEFT OUTER JOIN "reconciliation_manualreconciliation"' in q['sql'] for q in queries))
            self.assertEqual(Decimal((campaign.global_controls.get(project_code='P', data__identity__parts__2='FAF0126101276').current_data)['confirmed_sent_total']), 0)
        self.assertEqual(list(ControlContribution.objects.exclude(line=line).values_list('pk', 'amount', 'entries')), peers)
        self.assertEqual(list(campaign.inventory.values_list('pk', 'data')), inventories)
        self.assertEqual(list(campaign.sage_inventory.values_list('pk', 'data')), sage)
        self.assertEqual({f.attname: getattr(self.confirmed().transaction, f.attname) for f in line.transaction._meta.fields}, source)

    def test_audit_shared_piece(self): self.scenario(shared=True)
    def test_audit_no_collective(self): self.scenario(collective=False)

    def test_audit_positive(self): self.scenario()
    def test_audit_credit(self): self.scenario(negative=True)
    def test_audit_without_contribution(self): self.scenario(remove=True)
    def test_audit_other_authorized_actor(self): self.scenario(other=True)
    def test_audit_prepared_accounting(self): self.scenario(negative=True, accounting=True)
    def test_audit_recalculation_failure_rolls_back(self): self.scenario(fail=True)

# Ne pas réexécuter les tests hérités du socle : ils ont leur exécution séparée.
for _name in list(vars(ValidationV2Tests)):
    if _name.startswith('test_'):
        setattr(InternalErrorAuditTests, _name, None)


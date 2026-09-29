import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_host.support_diagnostics import AgentSupportDiagnostics, CATEGORIES, MAX_PREVIEWS
from agent_host.codex_adapter import CodexAppServerAdapter
from agent_host.session_store import AgentSessionStore
from agent_host.proposal_ingress import AgentProposalIngressGate
from agent_support_routes import support_router


def service(**overrides):
    sources = dict(runtime=lambda: {}, adapter=lambda: {}, persistence=lambda: {}, validation=lambda: {})
    sources.update(overrides)
    return AgentSupportDiagnostics(**sources)


class SupportPrivacyTests(unittest.TestCase):
    def test_canaries_never_enter_preview_or_download(self):
        canaries = ['PROMPT-CANARY', 'PROJECT-CANARY', 'TOKEN-CANARY', 'EMAIL-CANARY', 'PATH-CANARY', 'PROPOSAL-CANARY']
        raw = dict(zip(['prompt','project','access_token','email','path','proposal'],canaries))
        support = service(runtime=lambda: {'runtime': {'active': {**raw, 'version': 'TOKEN-CANARY', 'schema_fingerprint': 'PROJECT-CANARY'}, 'state_error':'PATH-CANARY'}, 'job': {'error_code':'TOKEN-CANARY'}},
            adapter=lambda: {**raw, 'state':'PROMPT-CANARY', 'auth': {**raw,'challenge':{'url':'TOKEN-CANARY'}, 'error_code':'EMAIL-CANARY'}},
            persistence=lambda: {**raw, 'error_code':'PATH-CANARY'}, validation=lambda: {**raw,'error_code':'PROPOSAL-CANARY'})
        preview = support.prepare(confirm=True)
        exported = support.export(preview_id=preview['preview_id'], sha256=preview['sha256'], confirm=True)
        for canary in canaries:
            self.assertNotIn(canary, json.dumps(preview))
            self.assertNotIn(canary.encode(), exported)
        self.assertIn('unknown_error', preview['content'])

    def test_seven_diagnostic_categories_and_allowlisted_evidence(self):
        support = service(runtime=lambda: {'runtime': {'ready':False,'active': {'version':'0.143.0','schema_fingerprint':'a'*64,
            'provenance_basis':'user_confirmed_official_install'},'active_health':{'code':'schema_reverification_required'}}},
            adapter=lambda:{'state':'failed','error_code':'request_timeout','mcp_state':'failed','auth':{'state':'expired','error_code':'auth_expired'}},
            persistence=lambda:{'state':'unavailable','error_code':'store_unavailable'},
            validation=lambda:{'state':'rejected','error_code':'STALE_CGS_HASH'})
        value = support.diagnostics()
        self.assertEqual(set(value['checks']),set(CATEGORIES))
        self.assertEqual(value['checks']['compatibility']['state'],'blocked')
        self.assertEqual(value['checks']['validation']['error_code'],'STALE_CGS_HASH')
        self.assertEqual(value['runtime']['schema_fingerprint'],'a'*64)

    def test_collection_requires_consent_before_reading_sources(self):
        collect = Mock(return_value={}); support = service(runtime=collect)
        for confirm in (False, None, 1, 'true'):
            with self.assertRaises(ValueError): support.prepare(confirm=confirm)
        collect.assert_not_called()

    def test_export_is_exact_reviewed_bytes_even_if_state_changes(self):
        current = {'state':'idle'}; support = service(adapter=lambda: current)
        preview = support.prepare(confirm=True); current['state']='failed'
        data = support.export(preview_id=preview['preview_id'], sha256=preview['sha256'], confirm=True)
        self.assertEqual(data,preview['content'].encode())
        self.assertEqual(hashlib.sha256(data).hexdigest(),preview['sha256'])
        with self.assertRaises(ValueError): support.export(preview_id=preview['preview_id'],sha256=preview['sha256'],confirm=True)

    def test_export_requires_separate_consent_and_exact_digest(self):
        support=service(); preview=support.prepare(confirm=True)
        for confirm,digest in ((False,preview['sha256']), (True,'0'*64)):
            with self.assertRaises(ValueError): support.export(preview_id=preview['preview_id'],sha256=digest,confirm=confirm)
        self.assertTrue(support.export(preview_id=preview['preview_id'],sha256=preview['sha256'],confirm=True))

    def test_preview_expiry_bound_and_clear(self):
        now=[1.0]; support=service(clock=lambda:now[0])
        first=support.prepare(confirm=True)
        for _ in range(MAX_PREVIEWS): support.prepare(confirm=True)
        self.assertEqual(len(support._previews),MAX_PREVIEWS)
        with self.assertRaises(ValueError): support.export(preview_id=first['preview_id'],sha256=first['sha256'],confirm=True)
        latest=support.prepare(confirm=True); now[0]+=301
        with self.assertRaises(ValueError): support.export(preview_id=latest['preview_id'],sha256=latest['sha256'],confirm=True)
        self.assertFalse(support._previews)
        support.prepare(confirm=True); support.clear(); self.assertFalse(support._previews)

    def test_collector_exception_does_not_leak_text_or_log(self):
        def fail(): raise RuntimeError('SECRET-CANARY private/path prompt')
        support=service(runtime=fail,adapter=fail,persistence=fail,validation=fail)
        with self.assertNoLogs(): value=support.prepare(confirm=True)
        self.assertNotIn('SECRET-CANARY',json.dumps(value))
        self.assertIn('unavailable',value['content'])

    def test_bundle_collection_performs_no_implicit_files_or_provider_calls(self):
        adapter=CodexAppServerAdapter(client_factory=Mock(side_effect=AssertionError('must not launch')))
        with patch('builtins.open', side_effect=AssertionError('no file reads')), patch.object(Path,'read_text', side_effect=AssertionError('no file reads')):
            value=service(adapter=adapter.diagnostic_snapshot).prepare(confirm=True)
        self.assertIn('unknown',value['content']); self.assertIsNone(adapter._auth_controller)
        adapter._client_factory.assert_not_called()

    def test_store_health_reads_schema_metadata_not_history_or_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=AgentSessionStore(tmp,audit_jsonl=True)
            with patch.object(store,'export_session',side_effect=AssertionError('no history')), patch.object(store,'list_events',side_effect=AssertionError('no events')):
                self.assertEqual(store.diagnostic_status()['state'],'ready')
            with sqlite3.connect(store.db_path) as conn:
                conn.execute("UPDATE store_meta SET value='WRONG-CANARY' WHERE key='schema_version'")
            conn.close()
            self.assertEqual(store.diagnostic_status()['state'],'schema_mismatch')
            self.assertNotIn('CANARY',json.dumps(store.diagnostic_status()))

    def test_missing_store_is_not_created_by_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=AgentSessionStore(tmp)
            store.db_path=Path(tmp)/'not-created.sqlite'
            self.assertEqual(store.diagnostic_status()['state'],'unavailable')
            self.assertFalse(store.db_path.exists())

    def test_validation_snapshot_contains_no_proposal_payload(self):
        gate=AgentProposalIngressGate()
        self.assertEqual(gate.diagnostic_status()['state'],'not_observed')
        gate.ingest({'prompt':'SECRET-CANARY'},current_cgs={},current_cgs_hash='a'*64)
        value=gate.diagnostic_status()
        self.assertEqual(value['state'],'rejected')
        self.assertNotIn('SECRET-CANARY',json.dumps(value))
        with patch.object(gate, '_ingest', return_value=Mock(accepted=True, code='NO_OP')):
            gate.ingest({})
        self.assertEqual(gate.diagnostic_status()['state'], 'no_op')
        support = service(adapter=lambda: {'auth': {'state': 'unavailable'}}, validation=gate.diagnostic_status)
        self.assertEqual(support.diagnostics()['checks']['auth']['state'], 'unavailable')
        self.assertEqual(support.diagnostics()['checks']['validation']['state'], 'no_op')


class SupportRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from fastapi import FastAPI
        import httpx
        self.support=service(); app=FastAPI(); app.include_router(support_router(self.support))
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',7)),
            base_url='http://localhost:8000',headers={'X-XACE-Agent-Auth':'1'})

    async def asyncTearDown(self): await self.client.aclose()

    async def test_local_origin_header_and_body_guards(self):
        for headers in ({'origin':'https://evil.example'},{'host':'evil.example'},{'X-XACE-Agent-Auth':''}):
            self.assertEqual((await self.client.post('/api/agent-support/preview',json={'confirm':True},headers=headers)).status_code,403)
        for body in ({}, {'confirm':False},{'confirm':True,'path':'credential-file'}, {'confirm':True,'include_prompts':True}):
            self.assertEqual((await self.client.post('/api/agent-support/preview',json=body)).status_code,400)
        self.assertEqual((await self.client.post('/api/agent-support/preview',content='x'*2050,headers={'content-type':'application/json'})).status_code,400)
        self.assertFalse(self.support._previews)

    async def test_preview_download_exact_bytes_headers_and_clear(self):
        value=await self.client.get('/api/agent-support/diagnostics')
        self.assertEqual(value.headers['cache-control'],'no-store')
        preview=(await self.client.post('/api/agent-support/preview',json={'confirm':True})).json()
        exported=await self.client.post('/api/agent-support/export',json={'confirm':True,'preview_id':preview['preview_id'],'sha256':preview['sha256']})
        self.assertEqual(exported.content,preview['content'].encode())
        self.assertEqual(exported.headers['x-content-type-options'],'nosniff')
        self.assertIn('attachment',exported.headers['content-disposition'])
        await self.client.post('/api/agent-support/preview',json={'confirm':True})
        self.assertEqual((await self.client.post('/api/agent-support/clear',json={'confirm':True})).json(),{'cleared':True})
        self.assertFalse(self.support._previews)


if __name__=='__main__': unittest.main()

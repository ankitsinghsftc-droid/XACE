import copy
import sys
from pathlib import Path
import unittest
import os
import tempfile
from unittest.mock import patch
import httpx
from fastapi import FastAPI

ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'packages/builder-workspace/server'),str(ROOT/'packages/project-system/tests')]
from test_native_reconciliation import context,engine_edit,xace_edit
from native_reconciliation_routes import install_reconciliation_routes


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_builder_host_extension(self):
        from native_reconciliation_routes import create_reconciliation_app
        with tempfile.TemporaryDirectory(prefix='nec008-builder-') as folder:
            with patch.dict(os.environ,{'XACE_LAUNCHER_STATE':str(Path(folder)/'launcher.json')}):
                app=create_reconciliation_app(lambda:self.context,project_path=str(Path(folder)/'project'),static_dir=str(Path(folder)/'no-dist'),model_provider='auto')
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1234)),base_url='http://127.0.0.1:8765',headers={'x-xace-agent-auth':'1'}) as client:
                    self.assertEqual((await client.get('/native-review')).status_code,200)
                    response=await client.get('/api/native-reconciliation');self.assertEqual(response.status_code,200,response.text)
                    self.assertFalse(response.json()['report']['can_commit'])
                    self.assertEqual((await client.get('/api/prompt/capability-matrix')).status_code,200)

    async def asyncSetUp(self):
        self.context=context();engine_edit(self.context);xace_edit(self.context)
        self.app=FastAPI()
        @self.app.get('/{path:path}')
        async def fallback(path):return {'fallback':True}
        self.service=install_reconciliation_routes(self.app,lambda:self.context)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('127.0.0.1',1234)),base_url='http://127.0.0.1:8765',headers={'x-xace-agent-auth':'1'})

    async def asyncTearDown(self):await self.client.aclose()

    async def open(self):
        response=await self.client.get('/api/native-reconciliation');self.assertEqual(response.status_code,200,response.text);return response.json()

    async def post(self,action,review,**extra):
        body=dict(token=review['token'],**extra)
        if action!='cancel':body['proposal_digest']=review['proposal_digest']
        return await self.client.post('/api/native-reconciliation/'+action,json=body)

    async def test_conflict_review_approval_and_cancel(self):
        opened=await self.open();self.assertEqual((await self.post('approve',opened)).status_code,409)
        conflict=opened['report']['merge']['conflicts'][0]['id']
        response=await self.post('resolve',opened,resolutions={conflict:'engine'});self.assertEqual(response.status_code,200,response.text)
        resolved=response.json();approval=await self.post('approve',resolved);self.assertEqual(approval.status_code,200,approval.text)
        self.assertFalse(approval.json()['can_commit']);self.assertTrue(approval.json()['requires_coordinator'])
        self.assertEqual((await self.post('cancel',resolved)).status_code,200)
        self.assertEqual((await self.post('approve',resolved)).status_code,409)

    async def test_origin_and_local_operator_guards(self):
        for headers in [{'x-xace-agent-auth':'0'},{'origin':'https://foreign.example'},{'sec-fetch-site':'cross-site'}]:
            self.assertEqual((await self.client.get('/api/native-reconciliation',headers=headers)).status_code,403)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('192.0.2.1',1234)),base_url='http://127.0.0.1',headers={'x-xace-agent-auth':'1'}) as remote:
            self.assertEqual((await remote.get('/api/native-reconciliation')).status_code,403)

    async def test_cross_browser_session_cannot_approve(self):
        opened=await self.open()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('127.0.0.1',1234)),base_url='http://127.0.0.1:8765',headers={'x-xace-agent-auth':'1'}) as second:
            response=await second.post('/api/native-reconciliation/approve',json=dict(token=opened['token'],proposal_digest=opened['proposal_digest']))
            self.assertEqual(response.status_code,409)

    async def test_stale_source_and_unknown_apply_refused(self):
        opened=await self.open();engine_edit(self.context,value='9')
        self.assertEqual((await self.post('resolve',opened,resolutions={})).status_code,409)
        self.assertEqual((await self.post('apply',opened)).status_code,409)

    async def test_strict_body_size_type_and_duplicate_keys(self):
        opened=await self.open()
        for payload in ['{"token":"a","token":"b","proposal_digest":"c"}', '[]', '{"path":"C:/arbitrary"}', ' '*65537]:
            response=await self.client.post('/api/native-reconciliation/approve',content=payload,headers={'content-type':'application/json'})
            self.assertEqual(response.status_code,409)
        response=await self.client.post('/api/native-reconciliation/approve',content='{}');self.assertEqual(response.status_code,415)

    async def test_static_panel_precedes_builder_fallback(self):
        page=await self.client.get('/native-review');self.assertIn('Review engine changes',page.text)
        script=await self.client.get('/native-review.js');self.assertIn('textContent',script.text);self.assertNotIn('innerHTML',script.text)
        self.assertEqual(page.headers['cache-control'],'no-store')


if __name__=='__main__':unittest.main()

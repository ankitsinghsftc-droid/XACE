import sys,tempfile,unittest
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'packages/project-system/tests'),str(ROOT/'packages/builder-workspace/server')]
from fastapi import FastAPI
from native_setup_routes import install_setup_routes
from test_native_setup_review import fixture

class SetupRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_review_approve_apply_and_local_operator_guards(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,review,_=fixture(root);app=FastAPI();install_setup_routes(app,review)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1234)),base_url='http://127.0.0.1:8765') as c:
                self.assertEqual((await c.post('/api/native-setup/open',json={})).status_code,403)
                c.headers['x-xace-agent-auth']='1'
                self.assertEqual((await c.post('/api/native-setup/open',json={},headers={'Origin':'https://example.org'})).status_code,403)
                opened=(await c.post('/api/native-setup/open',json={})).json()
                body=dict(token=opened['token'],proposal_digest=opened['proposal_digest'])
                approved=(await c.post('/api/native-setup/approve',json=body)).json();self.assertFalse((root/'native.json').exists())
                body['approval']=approved['approval'];result=await c.post('/api/native-setup/apply',json=body)
                self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['state'],'committed');self.assertFalse(host.status()['play_build_blocked'])
    async def test_paths_and_duplicate_keys_never_reach_provider(self):
        with tempfile.TemporaryDirectory() as d:
            _,review,_=fixture(Path(d));app=FastAPI();install_setup_routes(app,review)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1234)),base_url='http://127.0.0.1:8765',headers={'x-xace-agent-auth':'1'}) as c:
                self.assertEqual((await c.post('/api/native-setup/open',json={'root':'C:/unapproved'})).status_code,409)
                self.assertEqual((await c.post('/api/native-setup/cancel',content='{"token":"a","token":"b"}',headers={'Content-Type':'application/json'})).status_code,409)
                self.assertEqual((await c.get('/native-setup')).status_code,200)
if __name__=='__main__':unittest.main()

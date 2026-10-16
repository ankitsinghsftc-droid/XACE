import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'packages/project-system/tests'),str(ROOT/'packages/builder-workspace/server')]
import test_native_materialization_host as fixtures
from native_reconciliation_routes import create_materialization_app

class MaterializationRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_apply_route_and_actual_player_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,_=fixtures.HostTests().fixture(root)
            with patch.dict(os.environ,{'XACE_LAUNCHER_STATE':str(root/'launcher.json')}):
                app=create_materialization_app(host,project_path=str(root),static_dir=str(root/'no-dist'),model_provider='auto')
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1234)),base_url='http://127.0.0.1:8765',headers={'x-xace-agent-auth':'1'}) as c:
                opened=(await c.get('/api/native-reconciliation')).json();self.assertTrue(opened['apply_available'])
                approved=(await c.post('/api/native-reconciliation/approve',json=dict(token=opened['token'],proposal_digest=opened['proposal_digest']))).json()
                bad=await c.post('/api/native-reconciliation/apply',json=dict(approval=approved,proposal_digest='0'*64));self.assertEqual(bad.status_code,409)
                result=await c.post('/api/native-reconciliation/apply',json=dict(approval=approved,proposal_digest=opened['proposal_digest']));self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['state'],'committed')
                (root/'.xace/authoring-transactions/broken').mkdir()
                with patch.object(app.state.player_launch,'control',return_value={'state':'unexpected'}) as launch:
                    response=await c.post('/api/player/play',json={'cgs_hash':'hash'},headers={'x-xace-player-capability':app.state.player_launch.capability})
                    self.assertEqual(response.status_code,400);self.assertIn('recovery blocks',response.json()['message']);launch.assert_not_called()
                    response=await c.post('/api/player/stop',json={},headers={'x-xace-player-capability':app.state.player_launch.capability});self.assertEqual(response.status_code,200);launch.assert_called_once()
    async def test_wrong_project_cannot_install_host(self):
        with tempfile.TemporaryDirectory() as d:
            host,_=fixtures.HostTests().fixture(Path(d))
            with self.assertRaises(ValueError):create_materialization_app(host,project_path=str(Path(d)/'other'))

if __name__=='__main__':unittest.main()

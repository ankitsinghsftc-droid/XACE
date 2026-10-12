import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from replay_debugger import ReplayDebugger,install_debugger_routes

class ReplayDebuggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.runtime=Mock()
        self.runtime.send_control.return_value={'accepted':True,'status':{'tick':25}}
        self.runtime._round_trip.return_value={'ruleset':{'phase':'preparing','activation_tick':30}}
        self.service=ReplayDebugger(self.root,(),self.runtime,'creator-test-key')
        app=FastAPI();install_debugger_routes(app,self.service);self.client=TestClient(app)
        bundle={'schema':'xace.epoch_replay.v1','host_executable_digest':'0'*64,'world_seed':42,
          'initial_artifacts':{'files':{'world.json':list(json.dumps({'objects':[{'id':'orbital.port','capabilities':['project.docking.v1']}]}).encode()),'game.cgs.json':list(json.dumps({'metadata':{'event_labels':{'project.docked.v1':'Ship docked'}}}).encode())}},'epochs':[],
          'ticks':[{'tick':4,'epoch':0,'events':[{'event_type':{'Domain':'project.docked.v1'},'source_entity_id':7}],'inputs':[{'peer_id':2}],
           'state':{'components':{'tables':{'10003':{'component_type_name':'Project docking state','rows':{'7':'{"contact_id":"orbital.port","fuel":15}'}}}}},
           'schedule':{'system_dependencies':{'project.docking.v1':['EngineInputSystem']},'system_access':{}},'required_peers':[2],'release_decision':'release','waited_ticks':0,'world_hash':'f'*64}]}
        raw=json.dumps({'schema':'xace.sealed_epoch_replay.v1','bundle':bundle}).encode();self.id=hashlib.sha256(raw).hexdigest();(self.root/(self.id+'.json')).write_bytes(raw)
    def tearDown(self):self.client.close();self.tmp.cleanup()
    def post(self,route,body):return self.client.post('/api/debugger/'+route,json=body)
    def test_generic_event_state_world_and_dependencies(self):
        view=self.post('inspect',{'id':self.id,'tick':4}).json()
        self.assertEqual(view['events'][0]['label'],'Ship docked');self.assertEqual(view['components'][0]['entities']['7']['contact_id'],'orbital.port')
        self.assertIn('project.docking.v1',view['dependencies']);self.runtime.send_control.assert_not_called()
    def test_inspection_export_and_bad_frame_never_control_live(self):
        self.assertEqual(self.post('inspect',{'id':self.id,'tick':999}).status_code,400)
        report=self.post('export',{'id':self.id,'tick':4}).json();self.assertNotIn('creator-test-key',json.dumps(report));self.runtime.send_control.assert_not_called()
    def test_guest_spoof_and_missing_confirmation_refused(self):
        self.assertEqual(self.post('control',{'action':'pause','confirm_session_wide':True}).status_code,403)
        self.assertEqual(self.post('control',{'action':'pause','role':'creator'}).status_code,400)
        response=self.client.post('/api/debugger/control',json={'action':'pause'},headers={'x-xace-creator-token':'creator-test-key'})
        self.assertEqual(response.status_code,400);self.runtime.send_control.assert_not_called()
    def test_creator_explicit_session_pause_and_restore_refusal(self):
        for action,code in [('pause',200),('restore',400)]:
            response=self.client.post('/api/debugger/control',json={'action':action,'confirm_session_wide':True},headers={'x-xace-creator-token':'creator-test-key'});self.assertEqual(response.status_code,code)
        self.runtime.send_control.assert_called_once_with('pause')
    def test_missing_host_and_path_payload_fail_closed(self):
        self.assertEqual(self.post('verify',{'id':self.id,'tick':4}).status_code,400)
        for payload in [{'id':'../secret'},{'id':self.id,'host':'evil.exe'},{'id':self.id,'directory':'C:/private'}]:self.assertEqual(self.post('inspect',payload).status_code,400)
        self.runtime.send_control.assert_not_called()
    def test_changed_recording_rejected(self):
        (self.root/(self.id+'.json')).write_text('{}');self.assertEqual(self.post('inspect',{'id':self.id}).status_code,400)
    def test_live_preparation_status_is_read_only(self):
        data=self.client.get('/api/debugger/live').json();self.assertEqual(data['ruleset']['activation_tick'],30);self.runtime.send_control.assert_called_once_with('status')
    def test_import_ignores_filenames_and_keeps_content_identity(self):
        raw=(self.root/(self.id+'.json')).read_bytes()
        response=self.client.post('/api/debugger/import',content=raw,headers={'content-type':'application/json'})
        self.assertEqual(response.json()['recording_id'],self.id);self.runtime.send_control.assert_not_called()
    def test_legacy_websocket_guest_control_is_blocked(self):
        import asyncio
        from ws_message_router import WSMessageRouter
        router=WSMessageRouter(Mock(),self.runtime,control_authorizer=lambda message:False)
        responses=[]
        async def send(message):responses.append(message)
        asyncio.run(router._handle_runtime_control('guest',{'action':'pause','role':'creator'},send,Mock(),{}))
        self.assertFalse(responses[0]['accepted']);self.runtime.send_control.assert_not_called()

if __name__=='__main__':unittest.main()

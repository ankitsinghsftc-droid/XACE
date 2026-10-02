import sys,unittest,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from player_launch import PlayerLaunchService
from player_launch_routes import player_router

class Routes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        from fastapi import FastAPI
        self.service=Mock(capability="local-capability")
        self.service.control.return_value={"state":"playing"}
        app=FastAPI();app.include_router(player_router(self.service))
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=("127.0.0.1",7)),base_url="http://localhost:8000",headers={"x-xace-agent-auth":"1","x-xace-player-capability":"local-capability"})
    async def asyncTearDown(self):await self.client.aclose()
    async def test_origin_host_and_capability(self):
        for headers in [{"origin":"https://evil.example"},{"host":"evil.example"},{"x-xace-player-capability":"wrong"},{"x-xace-agent-auth":""}]:
            self.assertEqual((await self.client.post("/api/player/play",json={"cgs_hash":"a"},headers=headers)).status_code,403)
        self.service.control.assert_not_called()
    async def test_no_browser_executable_or_path_injection(self):
        for body in [{"path":"C:/untrusted.exe"},{"cgs_hash":[]},[]]:
            self.assertEqual((await self.client.post("/api/player/play",json=body)).status_code,400)
        self.assertEqual((await self.client.post("/api/player/play",content="x"*1025,headers={"content-type":"application/json"})).status_code,400)
        self.service.control.assert_not_called()
    async def test_join_code_is_bounded_and_control_stays_local(self):
        response=await self.client.post("/api/player/join",json={"code":"XACE1-example"})
        self.assertEqual(response.status_code,200)
        self.service.control.assert_called_once_with("join","","XACE1-example")
        self.service.control.reset_mock()
        for body in [{"code":"x"*4097},{"code":[]},{"code":"x","host_path":"C:/x"}]:
            self.assertEqual((await self.client.post("/api/player/join",json=body)).status_code,400)
        self.assertEqual((await self.client.post("/api/player/join",json={"code":"x"},headers={"origin":"https://evil.example"})).status_code,403)
        self.service.control.assert_not_called()

    async def test_play_and_retry_message(self):
        self.assertEqual((await self.client.get("/api/player")).json()["capability"],"local-capability")
        response=await self.client.post("/api/player/play",json={"cgs_hash":"a"})
        self.assertEqual(response.json(),{"ok":True,"state":"playing"})
        self.service.control.assert_called_once_with("play","a")
        self.service.control.side_effect=ValueError("Restore install and Retry")
        self.assertIn("Retry",(await self.client.post("/api/player/play",json={})).json()["message"])

class Service(unittest.TestCase):
    def test_missing_release_never_starts_process(self):
        service=PlayerLaunchService(lambda:{},expected="",broker_digest="")
        with self.assertRaises(ValueError):service.control("play","a")
        self.assertIsNone(service.process)
    def test_installed_release_discovery_checks_pointer_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict("os.environ",{"LOCALAPPDATA":tmp,"XACE_PLAYER_RELEASE":"","XACE_PLAYER_RELEASE_SHA256":"","XACE_PLAYER_BROKER_SHA256":""}):
            registry=Path(tmp)/"XACE/Player";registry.mkdir(parents=True)
            (registry/"active.json").write_text(json.dumps({"version_digest":"../escape"}))
            service=PlayerLaunchService(lambda:{})
            with self.assertRaises(ValueError):service.control("play","a")
            project={"metadata":{"cgs_hash":"a"}};executable=b"trusted broker fixture"
            manifest={"cgs_hash":"a","files":[{"path":"XACE Play.exe","sha256":hashlib.sha256(executable).hexdigest()}]}
            raw=json.dumps(manifest).encode();digest=hashlib.sha256(raw).hexdigest()
            root=registry/"versions"/digest;(root/"package").mkdir(parents=True)
            (root/"distribution.json").write_bytes(raw);(root/"XACE Play.exe").write_bytes(executable)
            (root/"package/game.cgs.json").write_text(json.dumps(project))
            (registry/"active.json").write_text(json.dumps({"version_digest":digest}))
            service=PlayerLaunchService(lambda:project)
            self.assertEqual(service._validate("a"),root/"XACE Play.exe")
            (root/"XACE Play.exe").write_bytes(b"changed")
            with self.assertRaises(ValueError):service._validate("a")

    def test_unknown_action_rejects_and_stop_is_idempotent(self):
        service=PlayerLaunchService(lambda:{})
        with self.assertRaises(ValueError):service.control("execute")
        self.assertEqual(service.control("stop"),{"state":"stopped"})
        service.close();service.close()

if __name__=="__main__":unittest.main()

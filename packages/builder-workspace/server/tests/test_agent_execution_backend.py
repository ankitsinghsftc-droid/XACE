import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_host.execution_backend import ExecutionBackendStatus
from agent_host.execution_setup import ExecutionBackendSetup
from agent_host.isolated_codex_adapter import IsolatedCodexAdapter
from agent_host.docker_execution_backend import DockerExecutionBackend, DockerProfileClient, _ProcessChannel
from agent_host.execution_pin import record_build, pinned_image
from agent_host.registry import create_default_registry


class ExecutionBackendTests(unittest.TestCase):
    def test_registry_does_not_start_provider_at_construction(self):
        with patch('subprocess.Popen') as process:
            adapter=create_default_registry(enable_codex=True).get('codex_app_server')
            self.assertIsInstance(adapter,IsolatedCodexAdapter)
            adapter.close(); process.assert_not_called()

    def test_missing_future_backend_is_graceful_without_cli_fallback(self):
        backend=Mock()
        backend.inspect.return_value=ExecutionBackendStatus('future_native',False,'backend_unavailable','Backend unavailable; API/BYOK remains available.')
        with tempfile.TemporaryDirectory() as tmp:
            adapter=IsolatedCodexAdapter(project_path=tmp,execution_backend=backend)
            status=adapter.detect_sync()
            self.assertFalse(status.available)
            self.assertEqual(status.metadata['execution_backend']['backend_id'],'future_native')
            backend.open_client.assert_not_called()

    def test_setup_cannot_activate_arbitrary_executable_or_delete_storage(self):
        backend=Mock()
        backend.inspect.return_value=ExecutionBackendStatus('future_native',False,'missing','Install backend')
        setup=ExecutionBackendSetup(backend)
        self.assertEqual(setup.status()['runtime']['setup_mode'],'isolated_backend')
        for action,payload in [('install',{'confirm':True,'executable_path':'arbitrary.exe'}),('remove',{'confirm':True})]:
            with self.assertRaises(ValueError): setup.start(action,payload)
        self.assertFalse(setup.start('recover',{'confirm':True})['runtime']['ready'])

    def test_mounts_no_project_root_host_ports_or_credentials(self):
        backend=DockerExecutionBackend()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'.xace/agent_capsules'; root.mkdir(parents=True)
            good=ExecutionBackendStatus('docker_wsl_v1',True,'ready','ready')
            with patch.object(backend,'inspect',return_value=good),patch.object(backend,'_command',side_effect=lambda *args:['docker',*args]),patch('subprocess.Popen') as popen,patch('agent_host.docker_execution_backend.DockerProfileClient'):
                with self.assertRaises(ValueError): backend.open_client(Path(tmp))
                backend.open_client(root,extra_environment={'XACE_MCP_SESSION_TOKEN':'not-in-argv'})
                args=popen.call_args.args[0]
                self.assertNotIn('not-in-argv',' '.join(args))
                self.assertIn('--read-only',args); self.assertIn('no-new-privileges',args)
                self.assertFalse(any(x in args for x in ['--privileged','--publish','-p','--network=host']))
                mounts=[args[i+1] for i,x in enumerate(args) if x=='--mount']
                self.assertTrue(all(x.endswith(',readonly') for x in mounts if x.startswith('type=bind')))
                self.assertFalse(any('docker.sock' in x for x in mounts))

    def test_host_paths_map_only_to_capsule_and_turn_boundary_is_rechecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); capsule=root/'session'; capsule.mkdir()
            client=object.__new__(DockerProfileClient)
            client.root=root; client.bindings={}; client.channel=SimpleNamespace(endpoint=None)
            client.session=Mock(); client.session.request.return_value={'thread':{'id':'thread'}}
            server={'command':'host-python','args':['proxy.py','--host','127.0.0.1','--port','12345']}
            client.request('thread/start',{'cwd':str(capsule),'approvalPolicy':'never','sandbox':'read-only','config':{'mcp_servers':{'xace':server}}})
            self.assertEqual(client.session.request.call_args.args[1]['cwd'],'/capsules/session')
            self.assertEqual(client.channel.endpoint,('127.0.0.1',12345))
            with self.assertRaises(ValueError): client.request('turn/start',{'cwd':str(capsule),'threadId':'thread','sandboxPolicy':{'type':'readOnly'}})
            with self.assertRaises(ValueError): client.request('account/login/start',{'type':'chatgpt'})

    def test_container_cannot_select_host_mcp_endpoint(self):
        process=Mock(); channel=_ProcessChannel(Mock(),process,'owned-container','token')
        with self.assertRaises(ValueError): channel.relay({'channel':'mcp','id':'r','value':{'method':'tools/list'},'endpoint':['remote',80]})
        process.stdin.write.assert_not_called()

    def test_local_pin_roundtrip_and_malformed_pin_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XACE_EXECUTION_STATE_PATH':str(Path(tmp)/'pin.json')}):
            self.assertEqual(pinned_image('fallback'),'fallback')
            record_build('sha256:'+'a'*64)
            self.assertEqual(pinned_image('fallback'),'sha256:'+'a'*64)
            with self.assertRaises(ValueError): record_build('unverified-tag')
            self.assertEqual(record_build('sha256:'+'b'*64)['previous_image_id'],'sha256:'+'a'*64)

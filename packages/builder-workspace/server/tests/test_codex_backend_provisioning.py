from pathlib import Path
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_backend_provisioning import ProvisioningJob, build_runtime
from agent_host.execution_setup import ExecutionBackendSetup
from agent_host.execution_pin import pinned_image


class ProvisioningTests(unittest.TestCase):
    def test_unverified_archive_never_starts_build_or_reads_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime.tgz'
            path.write_bytes(b'not an official archive')
            backend, commit = Mock(), Mock()
            with patch('codex_backend_provisioning.subprocess.Popen') as process:
                with self.assertRaises(ValueError):
                    build_runtime(path, backend, threading.Event(), commit)
                process.assert_not_called()
                backend._run.assert_not_called()
                commit.assert_not_called()

    def test_archive_requires_exact_bytes_even_with_valid_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime.tgz'; path.write_bytes(b'bad')
            backend = Mock(); backend._run.return_value = Mock(returncode=0, stdout='npipe:////./pipe/dockerDesktopLinuxEngine')
            with patch('codex_backend_provisioning.PACKAGE_BYTES', 3), patch('codex_backend_provisioning.subprocess.Popen') as process:
                with self.assertRaisesRegex(ValueError, 'integrity'):
                    build_runtime(path, backend, threading.Event(), Mock())
                process.assert_not_called()

    def test_cancel_before_commit_preserves_pin_and_rejects_second_job(self):
        entered = threading.Event()
        def builder(package, backend, cancel, commit):
            entered.set(); cancel.wait(2); commit('sha256:' + 'a' * 64)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XACE_EXECUTION_STATE_PATH': str(Path(tmp) / 'pin.json')}):
            job = ProvisioningJob(Mock(), Mock(), builder=builder)
            job.start(str(Path(tmp) / 'runtime.tgz')); self.assertTrue(entered.wait(2))
            with self.assertRaises(ValueError): job.start(str(Path(tmp) / 'other.tgz'))
            job.cancel(); job.close()
            self.assertEqual(job.status()['state'], 'cancelled')
            self.assertEqual(pinned_image('unchanged'), 'unchanged')

    def test_cancel_after_commit_does_not_misreport_success(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XACE_EXECUTION_STATE_PATH': str(Path(tmp) / 'pin.json')}):
            def builder(package, backend, cancel, commit): commit('sha256:' + 'a' * 64)
            invalidate = Mock(); job = ProvisioningJob(Mock(), invalidate, builder=builder)
            job.start(str(Path(tmp) / 'runtime.tgz')); job.thread.join(2); job.cancel()
            self.assertEqual(job.status()['state'], 'complete')
            self.assertEqual(pinned_image('unchanged'), 'sha256:' + 'a' * 64)
            invalidate.assert_called_once()

    def test_setup_requires_operator_consent_and_rejects_arbitrary_fields(self):
        setup = ExecutionBackendSetup(Mock())
        with patch.object(setup.provisioning, 'start') as start, patch.object(setup, 'status', return_value={}):
            for payload in ({'runtime_package': 'file.tgz'}, {'confirm': True, 'runtime_package': 'file.tgz', 'command': 'shell'}):
                with self.assertRaises(ValueError): setup.start('install', payload)
            start.assert_not_called()
            setup.start('install', {'confirm': True, 'runtime_package': 'file.tgz'})
            start.assert_called_once_with('file.tgz')

"""Local-operator-only, cancellable build from an exact official archive.

Never imported by the provider worker or exposed through MCP. No downloads,
package scripts, arbitrary commands, credential access or real-project writes.
"""
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from agent_host.codex_runtime_lifecycle import CodexRuntimeLifecycle
from agent_host.execution_pin import BASE_IMAGE, PACKAGE_INTEGRITY, pin_path, record_build

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_BYTES = 142140011
DOCKERFILE_HASH = '02f9e73148054d192a5bc1149d796276a6e1784eed3d15d72f7b849af9a2d332'


def check_cancel(cancel):
    if cancel.is_set():
        raise ValueError('cancelled')


def build_runtime(package, backend, cancel, commit):
    """Verify the copied bytes, not a path which could change after validation."""
    path = Path(package)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.suffix.lower() != '.tgz' or path.stat().st_size != PACKAGE_BYTES):
        raise ValueError('official_archive_required')
    context = backend._run('context', 'inspect', 'desktop-linux', '--format', '{{.Endpoints.docker.Host}}')
    if context.returncode or context.stdout.strip() != 'npipe:////./pipe/dockerDesktopLinuxEngine':
        raise ValueError('local_backend_required')
    dockerfile = ROOT / 'tools/ag029_container/Dockerfile'
    recipe = dockerfile.read_bytes()
    if hashlib.sha256(recipe).hexdigest() != DOCKERFILE_HASH:
        raise ValueError('build_recipe_changed')
    lifecycle = CodexRuntimeLifecycle(state_dir=pin_path().parent / 'build-lock',
                                      platform_name='windows', architecture='x86_64')
    with lifecycle._operation_lock('build', path), tempfile.TemporaryDirectory(prefix='xace-codex-build-') as directory:
        target = Path(directory)
        digest = hashlib.sha512()
        copied = 0
        with path.open('rb') as source, (target / 'openai-codex-0.155.1-linux-x64.tgz').open('wb') as output:
            while chunk := source.read(1024 * 1024):
                check_cancel(cancel)
                copied += len(chunk)
                if copied > PACKAGE_BYTES:
                    raise ValueError('archive_integrity_mismatch')
                digest.update(chunk)
                output.write(chunk)
        if copied != PACKAGE_BYTES or base64.b64encode(digest.digest()).decode() != PACKAGE_INTEGRITY:
            raise ValueError('archive_integrity_mismatch')
        (target / 'Dockerfile').write_bytes(recipe)
        check_cancel(cancel)
        environment = {k: v for k, v in os.environ.items() if k.upper() in {
            'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA',
            'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA', 'PATH'}}
        environment['PATH'] = str(Path(backend._command()[0]).parent) + os.pathsep + environment.get('PATH', '')
        identity = target / 'image-id'
        process = subprocess.Popen(backend._command('build', '--build-arg', 'BASE_IMAGE=' + BASE_IMAGE,
            '--iidfile', str(identity), str(target)), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 600
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic() >= deadline:
                    raise ValueError('build_timeout')
                cancel.wait(.1)
            if process.returncode:
                raise ValueError('build_failed')
            check_cancel(cancel)
            image = identity.read_text().strip()
            inspected = backend._run('image', 'inspect', image, '--format', '{{.Id}}')
            if inspected.returncode or inspected.stdout.strip() != image:
                raise ValueError('build_identity_invalid')
            return commit(image)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


class ProvisioningJob:
    def __init__(self, backend, invalidate, *, builder=build_runtime):
        self.backend, self.invalidate, self.builder = backend, invalidate, builder
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.thread = None
        self.job = {'state': 'idle', 'operation': '', 'error_code': None}

    def status(self):
        with self.lock:
            return dict(self.job)

    def start(self, package):
        if not isinstance(package, str) or len(package) > 4096 or not Path(package).is_absolute():
            raise ValueError('absolute_archive_path_required')
        with self.lock:
            if self.job['state'] in {'running', 'cancelling'}:
                raise ValueError('runtime_operation_busy')
            self.cancelled.clear()
            self.job = {'state': 'running', 'operation': 'install', 'error_code': None}
            self.thread = threading.Thread(target=self._run, args=(package,), daemon=True,
                                           name='xace-local-runtime-build')
            self.thread.start()

    def _commit(self, image):
        with self.lock:
            check_cancel(self.cancelled)
            value = record_build(image, repair_invalid=True)
            # Commit and cancellation are serialized; a completed selection is
            # never reported as cancelled or silently rolled back.
            self.job = {'state': 'complete', 'operation': 'install', 'error_code': None}
            return value

    def _run(self, package):
        try:
            self.builder(package, self.backend, self.cancelled, self._commit)
            self.invalidate()
        except Exception:
            with self.lock:
                if self.job['state'] != 'complete':
                    cancelled = self.cancelled.is_set()
                    self.job = {'state': 'cancelled' if cancelled else 'failed', 'operation': 'install',
                                'error_code': 'cancelled' if cancelled else 'isolated_build_failed'}

    def cancel(self):
        with self.lock:
            if self.job['state'] == 'running':
                self.cancelled.set()
                self.job['state'] = 'cancelling'

    def close(self):
        self.cancel()
        if self.thread:
            self.thread.join(timeout=15)

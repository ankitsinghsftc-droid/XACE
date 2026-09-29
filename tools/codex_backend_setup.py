"""Explicit local build from a verified official runtime package; no redistribution.

Does not install Docker/WSL, download packages, read credentials or run a model.
"""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'packages/builder-workspace/server'))
from agent_host.docker_execution_backend import DockerExecutionBackend
from agent_host.execution_pin import BASE_IMAGE, PACKAGE_INTEGRITY, record_build


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-package',type=Path,required=True)
    parser.add_argument('--confirm-local-build',action='store_true',required=True)
    args=parser.parse_args()
    package=args.runtime_package.resolve(strict=True)
    digest=hashlib.sha512()
    with package.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
    if base64.b64encode(digest.digest()).decode()!=PACKAGE_INTEGRITY:
        raise ValueError('Official runtime package integrity mismatch; nothing was built or activated')
    backend=DockerExecutionBackend()
    context=backend._run('context','inspect','desktop-linux','--format','{{.Endpoints.docker.Host}}')
    if context.returncode or context.stdout.strip()!='npipe:////./pipe/dockerDesktopLinuxEngine':
        raise ValueError('Local Docker Desktop Linux context required')
    with tempfile.TemporaryDirectory(prefix='xace-codex-local-build-') as directory:
        target=Path(directory)
        shutil.copyfile(package,target/'openai-codex-0.155.1-linux-x64.tgz')
        shutil.copyfile(ROOT/'tools/ag029_container/Dockerfile',target/'Dockerfile')
        tag='xace-codex-isolated:0.155.1'
        # Docker's pinned base digest is validated by the engine. No secret
        # environment, project files or auth volume enters the build context.
        build_environment=dict(os.environ)
        build_environment['PATH']=str(Path(backend._command()[0]).parent)+os.pathsep+os.environ.get('PATH','')
        result=subprocess.run(backend._command('build','--build-arg','BASE_IMAGE='+BASE_IMAGE,
                              '-t',tag,str(target)),timeout=600,env=build_environment,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode: raise RuntimeError('Local image build failed; previous selection retained')
        inspected=backend._run('image','inspect',tag,'--format','{{.Id}}')
        if inspected.returncode: raise RuntimeError('Built image identity unavailable; previous selection retained')
        record=record_build(inspected.stdout.strip())
    print('Verified local runtime selected: '+record['image_id'])
    print('Refresh Codex setup in XACE, then use provider-managed device-code sign-in.')


if __name__=='__main__': main()

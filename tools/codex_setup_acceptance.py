"""Explicit real local provisioning through the same protected routes as Builder.

No model turn or credential access. The browser contract is tested separately.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packages/builder-workspace/server'))
from fastapi import FastAPI
import httpx
from agent_setup_routes import setup_router
from agent_host.docker_execution_backend import DockerExecutionBackend
from agent_host.execution_setup import ExecutionBackendSetup
from agent_host.execution_pin import pinned_image


async def run(package):
    setup = ExecutionBackendSetup(DockerExecutionBackend())
    app = FastAPI(); app.include_router(setup_router(setup))
    report = {'schema': 'xace.codex_setup_acceptance.v1', 'provider_calls_performed': False}
    transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 10000))
    try:
        async with httpx.AsyncClient(transport=transport, base_url='http://localhost:8000') as client:
            payload = {'confirm': True, 'runtime_package': str(package.resolve(strict=True))}
            denied = await client.post('/api/agent-runtime/install', json=payload)
            report['missing_operator_header_denied'] = denied.status_code == 403
            client.headers.update({'X-XACE-Agent-Auth': '1', 'Origin': 'http://localhost:8000'})
            no_consent = await client.post('/api/agent-runtime/install', json={'runtime_package': payload['runtime_package']})
            report['missing_consent_denied'] = no_consent.status_code == 400
            response = await client.post('/api/agent-runtime/install', json=payload)
            report['protected_build_started'] = response.status_code == 200
            deadline = time.monotonic() + 660
            while time.monotonic() < deadline:
                value = (await client.get('/api/agent-runtime')).json()
                if value['job']['state'] not in {'running', 'cancelling'}:
                    break
                await asyncio.sleep(.25)
            report['build_completed'] = value['job']['state'] == 'complete'
            report['backend_ready'] = value['runtime']['ready'] is True
            report['device_flow_selected'] = value['runtime']['preferred_auth_flow'] == 'device_code'
            report['image_id'] = pinned_image('')
            report['checks_passed'] = all(report.get(k) is True for k in (
                'missing_operator_header_denied', 'missing_consent_denied', 'protected_build_started',
                'build_completed', 'backend_ready', 'device_flow_selected'))
            return report
    finally:
        setup.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-package', type=Path, required=True)
    parser.add_argument('--confirm-local-build', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args.runtime_package))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf8')
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report['checks_passed'] else 1)

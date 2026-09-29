"""AG-029 synthetic Linux container preflight; never real-account certification.

Only mounts the selected fixed probe script read-only. No credential volume,
real project, Docker socket, network or inherited secret environment is passed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:7b59fe353f2416fd2ef2b5088830b2168689a4b89bf93ffe8af973e49e9eb506'
PROBES = ('probe.py', 'native_probe.py')


def command(docker: Path, probe: str) -> list[str]:
    if probe not in PROBES:
        raise ValueError('Unknown fixed isolation probe')
    directory = ROOT / 'tools/ag029_container'
    return [str(docker), 'run', '--rm', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--security-opt', f'seccomp={directory / "seccomp.json"}',
            '--network', 'none', '--pids-limit', '128', '--memory', '1g',
            '--tmpfs', '/provider:rw,nosuid,nodev,size=128m,uid=10001,gid=10001',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m',
            '--mount', f'type=bind,source={directory / probe},target=/probe.py,readonly',
            '--entrypoint', 'python', IMAGE, '/probe.py']


def normalize(probe: str, result: subprocess.CompletedProcess) -> dict:
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict): value = {}
    except (ValueError, TypeError):
        value = {}
    if probe == 'probe.py':
        try:
            checks = json.loads(value.get('stdout', '{}'))
            if not isinstance(checks, dict): checks = {}
        except (ValueError, TypeError): checks = {}
        checks = {key: checks.get(key) is True for key in ('allowed_read','outside_read_denied','write_denied')}
        passed = value.get('exit_code') == 0 and all(checks.values())
    elif probe == 'native_probe.py':
        checks = {'private_content_hidden': value.get('private_content_exposed') is False,
                  'private_file_unchanged':value.get('private_file_unchanged') is True,
                  'tool_roundtrip_observed':value.get('fake_model_requests') == 2 and bool(value.get('tool_outputs')),
                  'turn_completed':'turn/completed' in value.get('event_methods', [])}
        passed = value.get('error') is None and all(checks.values())
    else:
        raise ValueError('Unknown fixed isolation probe')
    passed = passed and result.returncode == 0 and value.get('account_calls_performed') is False
    return {'probe':probe, 'passed':passed, 'checks':checks, 'exit_code':result.returncode}


def run(docker: Path) -> dict:
    rows = []
    for probe in PROBES:
        try:
            result = subprocess.run(command(docker, probe), capture_output=True, text=True,
                                    encoding='utf8', errors='replace', timeout=60)
        except subprocess.TimeoutExpired:
            # Docker --rm does not guarantee removal on CLI interruption. The
            # in-container probe also has bounded subprocess/turn deadlines.
            result = subprocess.CompletedProcess([], 124, '', '')
        rows.append(normalize(probe, result))
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    return {'schema':'xace.codex_container_preflight.v1', 'image_id':IMAGE,
            'artifact_hashes':{name:digest(ROOT / 'tools/ag029_container' / name)
                               for name in (*PROBES, 'seccomp.json', 'Dockerfile')},
            'checks':rows, 'synthetic_preflight_passed':all(row['passed'] for row in rows),
            'real_account_certified':False, 'account_calls_performed':False,
            'runtime_activated':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image', help='Explicit immutable local image identity')
    args = parser.parse_args()
    if args.image:
        import re
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',args.image): parser.error('Full immutable image SHA-256 required')
        IMAGE=args.image
    report = run(args.docker)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2,sort_keys=True))
    raise SystemExit(0 if report['synthetic_preflight_passed'] else 1)

"""Source-bound XP-022 evidence. A passing subset never certifies the release.

Runs historical replay failures in real child processes, retaining exact inputs,
commands and output. This is an offline fault subset, not socket chaos or a soak.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def source_identity(root: Path) -> dict:
    names = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root
    ).decode().split('\0')
    files = []
    for name in sorted(set(filter(None, names))):
        path = root / name
        files.append({'path': name, 'sha256': sha(path) if path.is_file() else None})
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return {
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        'working_tree_sha256': hashlib.sha256(encoded).hexdigest(),
        'files': files,
    }


def replay_faults(host: Path, recording: Path, out: Path) -> list[dict]:
    raw = recording.read_bytes()
    parsed = json.loads(raw)
    changed = dict(parsed, digest='0' * 64)
    cases = [
        ('baseline', raw, True, None, None),
        ('digest-corruption', json.dumps(changed).encode(), False, 'replay schema or digest mismatch', None),
        ('partial-transfer', raw[:len(raw) // 2], False, 'EOF', None),
        ('missing-recording', None, False, 'os error 2', None),
        ('seek-out-of-range', raw, False, 'outside', str(parsed['bundle']['ticks'][-1]['tick'] + 1)),
    ]
    results = []
    for name, data, accepted, diagnostic, through in cases:
        folder = out / name
        folder.mkdir()
        source, report = folder / 'replay.json', folder / 'report.json'
        if data is not None:
            source.write_bytes(data)
        command = [str(host), '--epoch-replay-in', str(source), '--epoch-replay-report', str(report)]
        if through is not None:
            command += ['--epoch-replay-through-tick', through]
        started = time.monotonic()
        timed_out = False
        try:
            run = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90)
            code, output = run.returncode, run.stdout + run.stderr
        except subprocess.TimeoutExpired as exc:
            code, output, timed_out = None, (exc.stdout or b'') + (exc.stderr or b''), True
        (folder / 'process.log').write_bytes(output)
        replay_report = json.loads(report.read_text()) if report.exists() else None
        success = (not timed_out and code == 0 and replay_report is not None
                   and replay_report.get('ok') is True
                   and replay_report.get('verified_ticks') == len(parsed['bundle']['ticks'])
                   and replay_report.get('presentation_effects_emitted') == 0)
        rejected = (not timed_out and code is not None and code != 0
                    and diagnostic is not None and diagnostic.lower() in output.decode(errors='replace').lower()
                    and not (replay_report or {}).get('ok', False))
        results.append({
            'case': name, 'kind': 'real-process-offline-replay', 'command': command,
            'expected': 'verified replay' if accepted else 'explicit rejection',
            'ok': success if accepted else rejected, 'returncode': code,
            'timed_out': timed_out, 'elapsed_seconds': time.monotonic() - started,
            'input_sha256': sha(source) if source.exists() else None,
            'output_sha256': sha(folder / 'process.log'), 'report': replay_report,
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--recording', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--package', type=Path, help='Current-source package for real TCP fault probes')
    parser.add_argument('--historical-host', action='store_true', help='Label an archived host rather than a current-source build')
    args = parser.parse_args()
    host, recording, out = args.host.resolve(), args.recording.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    identity = source_identity(ROOT)
    (out / 'source.json').write_text(json.dumps(identity, indent=2))
    cases = replay_faults(host, recording, out)
    package_identity = None
    if args.package:
        package = args.package.resolve()
        package_identity = {p.relative_to(package).as_posix(): sha(p)
                            for p in sorted(package.rglob('*')) if p.is_file()}
        for script in ('xp012_socket_proof.py', 'xp013_socket_proof.py'):
            command = [sys.executable, str(ROOT / 'tools' / script), '--package', str(package),
                       '--out', str(out / script.removesuffix('.py'))]
            started = time.monotonic()
            # Each runner owns and cleans its authority child in a finally block.
            run = subprocess.run(command, cwd=ROOT, capture_output=True)
            log = out / (script + '.log')
            log.write_bytes(run.stdout + run.stderr)
            cases.append({'case': script, 'kind': 'real-process-loopback-socket',
                          'command': command, 'ok': run.returncode == 0, 'returncode': run.returncode,
                          'elapsed_seconds': time.monotonic() - started, 'output_sha256': sha(log)})
    pending = {
        'full_proof_a_h_current_source': 'Replay/socket subset only; full A-H certification still required.',
        'socket_fault_matrix': 'Real socket drop/reorder/duplicate/backpressure coverage still required.',
        'two_hour_four_client_soak': 'Not run by this subset; consult the independent soak and final aggregate evidence.',
        'performance': 'Authority p95, render/latency and memory budgets not measured here.',
        'clean_install': 'User reported no clean Windows machine available.',
        'separate_networks': 'User reported no public relay/two Internet connections available.',
        'release_signing': 'User reported no signing certificate available.',
        'three_first_time_testers': 'User reported no first-time testers available.',
    }
    result = {
        'schema': 'xace.xp022.certification.v1', 'certified': False,
        'local_subset_ok': all(case['ok'] for case in cases),
        'source_revision': identity['revision'], 'working_tree_sha256': identity['working_tree_sha256'],
        'platform': platform.platform(), 'machine': platform.machine(), 'processor': platform.processor(),
        'host_sha256': sha(host), 'recording_sha256': sha(recording),
        'historical_host': args.historical_host, 'cases': cases, 'pending': pending,
        'socket_package_files': package_identity,
    }
    (out / 'report.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
    return 2 if result['local_subset_ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

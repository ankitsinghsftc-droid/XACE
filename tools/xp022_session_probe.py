"""Bounded four-socket session preflight; never presented as a two-hour native soak."""
from __future__ import annotations

import argparse
import ctypes
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.xp013_socket_proof import send, receive, port, verify
from tools.xp022_certification import sha, source_identity


def memory_bytes(pid):
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'working_set': counters.WorkingSetSize, 'private_bytes': counters.PrivateUsage}
    finally:
        kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ticks', type=int, default=600)
    parser.add_argument('--tick-metrics', action='store_true', help='Requires a host supporting --tick-metrics-out')
    args = parser.parse_args()
    if not 20 <= args.ticks <= 10000:
        parser.error('preflight supports 20..10000 ticks')
    package, out = args.package.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    ep, cp = port(), port()
    command = [str(package / 'runtime/xace_runtime.exe')]
    for flag, name in [('cgs', 'game.cgs.json'), ('sgc-plan', 'execution_plan.json'),
                       ('world', 'world.json'), ('world-manifest', 'world.manifest.json'),
                       ('package-manifest', 'playable.manifest.json')]:
        command += ['--' + flag, str(package / name)]
    command += ['--session-ticket-out', str(out / 'ticket.json'), '--session-log', str(out / 'session.jsonl'),
                '--session-controller-id', '1,2,3,4', '--input-lockstep-peer', '1,2,3,4',
                '--port', str(ep), '--control-port', str(cp), '--start-paused', '--no-wait',
                '--live-engine-accept', '--live-session', '--quiet', '--ruleset-root', str(out / 'rulesets')]
    (out / 'rulesets').mkdir()
    if args.tick_metrics:
        command += ['--tick-metrics-out', str(out / 'tick-metrics.jsonl')]
    (out / 'source.json').write_text(json.dumps(source_identity(ROOT), indent=2))
    samples, durations, clients, hashes = [], [], [], []
    started = time.monotonic()
    with (out / 'authority.log').open('wb') as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        def control(action):
            with socket.create_connection(('127.0.0.1', cp), timeout=10) as connection:
                send(connection, dict(msg_type='runtime_control', protocol_version=1, request_id='preflight', action=action))
                result = receive(connection)
                if not result['accepted']:
                    raise RuntimeError(result)
                return result
        try:
            deadline = time.monotonic() + 15
            while not (out / 'ticket.peer4.json').exists():
                if proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('authority failed to start; inspect authority.log')
                time.sleep(.02)
            cgs = json.loads((package / 'game.cgs.json').read_text())['metadata']['cgs_hash']
            for peer in range(1, 5):
                grant = json.loads((out / ('ticket.json' if peer == 1 else f'ticket.peer{peer}.json')).read_text())
                connection = socket.create_connection(('127.0.0.1', ep), timeout=10)
                clients.append(connection)
                send(connection, dict(msg_type='handshake', protocol_version=1, engine_name='Godot',
                                      engine_version='socket-probe', adapter_version='0.1.0', cgs_hash=cgs,
                                      capabilities=[], session_offer_json=grant['offer_json'],
                                      session_peer_id=peer, session_credential=grant['credential']))
                baseline = receive(connection)
                if not baseline['accepted']:
                    raise RuntimeError(baseline)
                verify(baseline)
                send(connection, dict(msg_type='baseline_ack', stamp_json=baseline['sync_json']))
                grant['player'] = baseline['assigned_player_id']
                clients[-1] = (connection, peer, grant['player'])
            for tick in range(args.ticks):
                tick_start = time.monotonic()
                for connection, peer, player in clients:
                    request = receive(connection)
                    if request.get('msg_type') != 'input_tick_request' or request['tick'] != tick:
                        raise RuntimeError(request)
                    send(connection, dict(msg_type='input_packet', peer_id=peer, player_id=player,
                                          tick=tick, sequence_id=tick + 1, actions=[]))
                control('step')
                digests = []
                for connection, _, _ in clients:
                    snapshot = receive(connection)
                    if snapshot.get('msg_type') != 'tick_snapshot' or snapshot['tick'] != tick:
                        raise RuntimeError(snapshot)
                    verify(snapshot); digests.append(snapshot['sync']['projection_digest'])
                    send(connection, dict(msg_type='baseline_ack', stamp_json=snapshot['sync_json']))
                if len(set(digests)) != 1:
                    raise RuntimeError(f'projection divergence at {tick}')
                hashes.append(digests[0]); durations.append((time.monotonic() - tick_start) * 1000)
                if tick % 100 == 0 or tick == args.ticks - 1:
                    samples.append(dict(tick=tick, elapsed_seconds=time.monotonic() - started, **memory_bytes(proc.pid)))
                    (out / 'progress.json').write_text(json.dumps(samples, indent=2))
            control('shutdown'); proc.wait(timeout=10)
            if proc.returncode != 0:
                raise RuntimeError(f'authority exited {proc.returncode}')
            authority_p95 = None
            if args.tick_metrics:
                metrics = [json.loads(row) for row in (out / 'tick-metrics.jsonl').read_text().splitlines()]
                if [row['tick'] for row in metrics] != list(range(args.ticks)):
                    raise RuntimeError('incomplete authority timing samples')
                authority_p95 = sorted(row['elapsed_ns'] / 1_000_000 for row in metrics)[int(len(metrics) * .95)]
            result = dict(schema='xace.xp022.session_preflight.v1', ok=True, certified=False,
                          profile='four protocol clients, empty inputs, manually stepped; not native hosts or a realtime soak',
                          ticks=args.ticks, elapsed_seconds=time.monotonic() - started, command=command,
                          host_sha256=sha(package / 'runtime/xace_runtime.exe'), samples=samples,
                          end_to_end_step_p95_ms=sorted(durations)[int(len(durations) * .95)],
                          authority_tick_p95_ms=authority_p95,
                          authority_budget_met=None if authority_p95 is None else authority_p95 < 16.7,
                          normal_cleanup_exitcode=proc.returncode,
                          authority_process_exited=proc.poll() is not None, projection_digests=hashes)
            (out / 'report.json').write_text(json.dumps(result, indent=2))
            print(json.dumps({k: v for k, v in result.items() if k not in ('projection_digests', 'command')}, indent=2))
        finally:
            for client in clients:
                (client[0] if isinstance(client, tuple) else client).close()
            if proc.poll() is None:
                proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()

"""Verify every durable replay segment, its index chain and snapshot continuity."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def verify_archive(host, archive, out):
    out.mkdir(parents=True, exist_ok=False)
    raw = (archive / 'index.jsonl').read_bytes()
    complete = json.loads((archive / 'complete.json').read_text())
    if not raw or not raw.endswith(b'\n'):
        raise ValueError('empty or torn replay archive index')
    previous = ''; next_tick = 0; end_hash = None; reports = []
    for sequence, line in enumerate(raw.splitlines()):
        row = json.loads(line); record = row['record']
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        if row['digest'] != digest or record['previous'] != previous or record['sequence'] != sequence:
            raise ValueError('replay index chain mismatch')
        identity = record['file_sha256']
        if len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('invalid segment identity')
        source = (archive / (identity + '.json')).resolve()
        if not source.is_relative_to(archive.resolve()):
            raise ValueError('segment escaped archive')
        data = source.read_bytes()
        if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != identity:
            raise ValueError('segment missing or corrupted')
        bundle = json.loads(data)['bundle']
        if record['first_tick'] != next_tick or bundle['initial_snapshot']['tick'] != next_tick:
            raise ValueError('gap in archive ticks')
        if end_hash is not None and bundle['initial_snapshot']['world_hash'] != end_hash:
            raise ValueError('segment boundary snapshot mismatch')
        report_path = out / f'{sequence}.json'
        command = [str(host), '--epoch-replay-in', str(source), '--epoch-replay-report', str(report_path)]
        run = subprocess.run(command, capture_output=True, timeout=90)
        (out / f'{sequence}.log').write_bytes(run.stdout + run.stderr)
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        if (run.returncode != 0 or report.get('ok') is not True
                or report.get('verified_ticks') != record['last_tick'] - next_tick + 1
                or report.get('end_snapshot_hash') != record['end_snapshot_hash']):
            raise ValueError(f'segment {sequence} replay verification failed')
        reports.append({'sequence': sequence, 'command': command, 'report': report})
        previous = digest; next_tick = record['last_tick'] + 1; end_hash = report['end_snapshot_hash']
    if complete != {'schema':'xace.replay_archive_complete.v1','segments':len(reports), 'chain_head':previous,'next_tick':next_tick}:
        raise ValueError('archive completion does not bind final segment')
    result = {'schema': 'xace.replay_archive_verification.v1', 'ok': True, 'segments': len(reports),
              'verified_ticks': next_tick, 'index_sha256': hashlib.sha256(raw).hexdigest(), 'reports': reports}
    (out / 'report.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('host', 'archive', 'out'): parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = verify_archive(args.host.resolve(), args.archive.resolve(), args.out.resolve())
    print(json.dumps({k: v for k, v in result.items() if k != 'reports'}, indent=2))

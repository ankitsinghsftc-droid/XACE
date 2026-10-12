"""Repeat installed-host and socket proofs against an explicitly pinned candidate.

No staging/rebuilding of the candidate runtime or Player is allowed here. Reports
retain the exact binary hashes; each invocation uses a new output directory.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from tools.xp017_mixed_session_proof import ROOT, scenario, load, write
from tools.xp022_certification import sha, source_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=['sockets', 'hosts'], required=True)
    args = parser.parse_args()
    artifacts = args.artifacts.resolve(); out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    host = artifacts/'parent/runtime/xace_runtime.exe'
    pins = {str(p.relative_to(artifacts)).replace('\\','/'):sha(p) for p in
            [host, artifacts/'build/exported/xace-mixed-proof.exe',
             artifacts/'build/exported/xace-mixed-proof.pck']}
    write(out/'source.json', source_identity(ROOT))
    write(out/'pins.json', pins)
    results = {}
    if args.mode == 'sockets':
        for name in ['xp011_session_proof', 'xp012_socket_proof', 'xp013_socket_proof']:
            command = [sys.executable, '-m', 'tools.'+name, '--package',
                       str(artifacts/'parent'), '--out', str(out/name)]
            with (out/(name+'.log')).open('w') as log:
                run = subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=180)
            assert run.returncode == 0, name
            results[name] = dict(command=command,returncode=run.returncode,
                                 proof_sha256=sha(out/name/'proof.json'))
    else:
        for name,engines in [('pair',['player','godot']),('four',['unity','godot','unreal','player'])]:
            results[name] = scenario(out/name,engines,artifacts/'build',dict(
                parent=artifacts/'parent',candidate=artifacts/'candidate',
                native=ROOT/'target/xp019/native',record_replay=True))
        recording = out/'four/replay.json'
        for name,tick in [('before',7),('at',8),('after',39),('repeat',39),('rewind',7)]:
            report = out/(name+'.json')
            command = [str(host),'--epoch-replay-in',str(recording),'--epoch-replay-report',str(report),
                       '--epoch-replay-through-tick',str(tick)]
            run = subprocess.run(command,capture_output=True,timeout=90)
            (out/(name+'.log')).write_bytes(run.stdout+run.stderr)
            value = load(report)
            assert run.returncode == 0 and value['ok'] and value['verified_ticks']==tick+1
            assert value['presentation_effects_emitted']==0
            results[name] = dict(command=command,returncode=run.returncode,report=value)
    assert pins == {name:sha(artifacts/name) for name in pins}, 'candidate changed during proof'
    write(out/'proof.json',dict(schema='xace.xp022.final_proofs.v1',ok=True,pins=pins,
          scope='Installed Windows hosts and loopback only; external gates are separate',results=results))
    print(json.dumps(dict(ok=True,mode=args.mode,out=str(out))))


if __name__ == '__main__': main()

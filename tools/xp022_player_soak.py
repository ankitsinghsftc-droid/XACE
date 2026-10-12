"""Wall-clock soak of four exported Player processes, mutations and a real rejoin.

All clients run their production adapters in headless mode. This measures neither
render latency nor human usability, and does not replace the mixed-engine proof.
"""
import argparse
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.xp013_socket_proof import send, receive, port
from tools.xp017_mixed_session_proof import load, write
from tools.xp022_session_probe import memory_bytes
from tools.xp022_certification import sha, source_identity


def soak_recording(peer):
    """Reference-arena route: bounded forward/back motion, never a one-way loop.

    The 40-tick golden proof retains jumps/effects. This endurance route exercises
    nonempty owned input continuously without walking off the finite fixture floor.
    """
    speed = peer / 32
    return [[dict(action='move_x', kind='axis_1d', phase='changed', value=0, secondary_value=0),
             dict(action='move_z', kind='axis_1d', phase='changed',
                  value=speed if tick < 30 else -speed, secondary_value=0),
             dict(action='Jump', kind='button', phase='cancelled', value=0, secondary_value=0)]
            for tick in range(60)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=7200)
    args = parser.parse_args()
    if args.seconds < 60: parser.error('minimum smoke duration is 60 seconds')
    base, out = args.artifacts.resolve(), args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    pkg = base/'parent'; rules = out/'rulesets'; rules.mkdir()
    ep, cp = port(), port(); processes = []; streams = []; clients = {}; readers = {}; pending = {}
    latest = {i:-1 for i in range(1,5)}; epochs = {}; samples = []; mutations = []; rejoined = False
    def spawn(command, name):
        log=(out/(name+'.log')).open('wb');streams.append(log)
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(child); return child
    command=[str(pkg/'runtime/xace_runtime.exe')]
    for flag,name in [('cgs','game.cgs.json'),('sgc-plan','execution_plan.json'),('world','world.json'),('world-manifest','world.manifest.json'),('package-manifest','playable.manifest.json')]:command+=['--'+flag,str(pkg/name)]
    command+=['--session-ticket-out',str(out/'ticket.json'),'--session-log',str(out/'session.jsonl'),
              '--session-controller-id','1,2,3,4','--input-lockstep-peer','1,2,3,4','--port',str(ep),
              '--control-port',str(cp),'--start-paused','--no-wait','--live-engine-accept','--live-session',
              '--quiet','--ruleset-root',str(rules),'--tick-metrics-out',str(out/'metrics.jsonl')]
    write(out/'source.json', source_identity(ROOT));write(out/'command.json',command)
    authority=spawn(command,'authority');started=time.monotonic();last_progress=started
    def control(action,**extra):
        with socket.create_connection(('127.0.0.1',cp),timeout=20) as connection:
            send(connection,dict(msg_type='runtime_control',protocol_version=1,request_id='soak',action=action,**extra))
            result=receive(connection)
            if not result['accepted']:raise RuntimeError(result)
            return result
    def pump():
        for peer in range(1,5):
            path=out/f'peer{peer}.jsonl'
            if peer not in readers and path.exists():readers[peer]=path.open('r',encoding='utf8')
            if peer not in readers:continue
            stream=readers[peer]
            while True:
                position=stream.tell();line=stream.readline()
                if not line or not line.endswith('\n'):stream.seek(position);break
                row=json.loads(line)
                if row['kind']=='error':raise RuntimeError(row)
                if row['kind']!='tick':continue
                if not row['applied']:raise RuntimeError('native projection did not apply')
                tick=row['tick'];latest[peer]=tick;epochs[peer]=row['sync']['ruleset_epoch']
                key=(row['sync']['projection_digest'],row['sync']['ruleset_epoch'],row['events'])
                if tick in pending and pending[tick]!=key:raise RuntimeError(f'client divergence at {tick}')
                pending[tick]=key
        # A bounded comparison window also detects stalled clients during the run.
        floor=max(latest.values())-1024
        for tick in list(pending):
            if tick<floor:del pending[tick]
        if max(latest.values())-min(latest.values())>512:raise RuntimeError('client lag exceeded 512 ticks')
        if authority.poll() is not None:raise RuntimeError(f'authority exited with code {authority.returncode}; inspect authority.log')
        for child in clients.values():
            if child.poll() is not None:raise RuntimeError('Player exited unexpectedly')
    def wait(predicate, timeout=30):
        deadline=time.monotonic()+timeout
        while not predicate():
            if time.monotonic()>deadline:raise TimeoutError('soak condition timed out')
            pump();time.sleep(.01)
    def start_client(peer,ticket,rejoin=False):
        config=out/f'peer{peer}-config.json'
        write(config,dict(ticket=str(ticket),grant=load(ticket),port=ep,cgs_hash=load(pkg/'game.cgs.json')['metadata']['cgs_hash'],
                          inputs=soak_recording(peer),stop_tick=2**31-1,transcript=str(out/f'peer{peer}.jsonl'),
                          compact=True,reconnect_ticket=str(out/f'peer{peer}-reconnect.json')))
        clients[peer]=spawn([str(base/'build/exported/xace-mixed-proof.exe'),'--headless','--',
                             '--config='+str(config),'--session-ticket='+str(ticket),'--port='+str(ep),'--package='+str(pkg)],
                            f'player-{peer}'+('-rejoin' if rejoin else ''))
    def mutate(package,tick):
        control('pause')
        files={name:list((package/name).read_bytes()) for name in ['game.cgs.json','execution_plan.json','world.json','world.manifest.json','compiled_schema.json','playable.manifest.json']}
        identity=hashlib.sha256(json.dumps({'files':files},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        incoming=rules/'incoming'/identity;incoming.mkdir(parents=True,exist_ok=True)
        for name in files:shutil.copy2(package/name,incoming/name)
        preview=control('ruleset',ruleset={'operation':'preview','artifact_digest':identity})['ruleset']
        staged=control('ruleset',ruleset={'operation':'stage','artifact_digest':identity,'approved_proposal_digest':preview['proposal_digest']})['ruleset']
        prepared=control('ruleset',ruleset={'operation':'prepare','candidate_digest':staged['candidate_digest'],'proof_digest':staged['proof_digest'],'activation_tick':tick})['ruleset']
        mutations.append(dict(tick=tick,preview=preview,staged=staged,prepared=prepared));write(out/'mutations.json',mutations)
        control('play')
    try:
        deadline=time.monotonic()+20
        while not (out/'ticket.peer4.json').exists():
            if time.monotonic()>deadline:raise TimeoutError('authority startup')
            time.sleep(.02)
        for peer in range(1,5):start_client(peer,out/('ticket.json' if peer==1 else f'ticket.peer{peer}.json'))
        wait(lambda:all((out/f'peer{i}-reconnect.json').exists() for i in range(1,5)))
        mutate(base/'candidate',256)
        wait(lambda:min(latest.values())>=280,60)
        mutate(base/'parent',512)
        wait(lambda:min(latest.values())>=540 and set(epochs.values())=={2},60)
        # Restart one actual Player using its rotated reconnect credential and the
        # current contract, preserving its assigned entity and authority session.
        control('pause'); clients.pop(4).terminate(); processes[-1].wait(timeout=10)
        time.sleep(.2)
        grant=load(out/'peer4-reconnect.json'); offer=json.loads(grant['offer_json'])
        offer['contract']=control('ruleset',ruleset={'operation':'current'})['ruleset']
        grant['offer']=offer;grant['offer_json']=json.dumps(offer);write(out/'peer4-rejoin-ticket.json',grant)
        old_latest=latest[4];start_client(4,out/'peer4-rejoin-ticket.json',True)
        time.sleep(.5);control('play');wait(lambda:latest[4]>old_latest,20);rejoined=True
        while time.monotonic()-started<args.seconds:
            pump()
            if time.monotonic()-last_progress>=10:
                sample=dict(elapsed_seconds=time.monotonic()-started,ticks=dict(latest),epochs=dict(epochs),
                            authority=memory_bytes(authority.pid),players={i:memory_bytes(p.pid) for i,p in clients.items()})
                if sample['authority']['private_bytes']>256*1024*1024:raise RuntimeError('authority exceeded 256 MiB budget')
                if any(v['private_bytes']>1024*1024*1024 for v in sample['players'].values()):raise RuntimeError('Player exceeded 1 GiB budget')
                samples.append(sample);write(out/'progress.json',dict(samples=samples,rejoined=rejoined));last_progress=time.monotonic()
            time.sleep(.01)
        control('pause');pump();control('shutdown');authority.wait(timeout=15)
        if authority.returncode!=0:raise RuntimeError('authority cleanup failed')
        timing=[json.loads(line)['elapsed_ns']/1e6 for line in (out/'metrics.jsonl').read_text().splitlines()]
        p95=sorted(timing)[int(len(timing)*.95)]
        result=dict(schema='xace.xp022.player_soak.v1',ok=True,certified=False,full_duration=args.seconds>=7200,
                    elapsed_seconds=time.monotonic()-started,authority_ticks=len(timing),authority_p95_ms=p95,
                    authority_budget_met=p95<16.7,rejoined=rejoined,mutations=mutations,samples=samples,
                    host_sha256=sha(pkg/'runtime/xace_runtime.exe'),player_sha256=sha(base/'build/exported/xace-mixed-proof.exe'),
                    player_pack_sha256=sha(base/'build/exported/xace-mixed-proof.pck'),
                    scope='Four actual exported Players, headless, loopback, one Windows computer; render and Internet claims excluded',
                    authority_exited=True)
        write(out/'report.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('samples','mutations')},indent=2))
    finally:
        for child in processes:
            if child.poll() is None:child.terminate();child.wait(timeout=10)
        for stream in streams+list(readers.values()):stream.close()


if __name__=='__main__':main()

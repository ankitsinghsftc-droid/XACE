"""Production-binary crash, staged-artifact corruption and non-reading socket proof."""
import argparse, hashlib, json, shutil, socket, struct, subprocess, time, threading
from pathlib import Path
from tools.xp013_socket_proof import port, send, receive, verify
from tools.xp022_session_probe import memory_bytes
from tools.xp022_certification import sha


class Host:
    def __init__(self, artifacts, out):
        self.out=out;out.mkdir(parents=True,exist_ok=False)
        self.artifacts=artifacts;self.pkg=artifacts/'parent';self.ep=port();self.cp=port();self.sockets=[]
        self.command=[str(self.pkg/'runtime/xace_runtime.exe')]
        for flag,name in [('cgs','game.cgs.json'),('sgc-plan','execution_plan.json'),('world','world.json'),('world-manifest','world.manifest.json'),('package-manifest','playable.manifest.json')]:
            self.command+=['--'+flag,str(self.pkg/name)]
        self.command+=['--session-ticket-out',str(out/'ticket.json'),'--session-log',str(out/'session.jsonl'),
                       '--session-controller-id','1,2','--input-lockstep-peer','1,2','--port',str(self.ep),
                       '--control-port',str(self.cp),'--no-wait','--live-engine-accept','--start-paused',
                       '--live-session','--quiet','--ruleset-root',str(out/'rulesets')]
        (out/'rulesets').mkdir();self.log=(out/'authority.log').open('w')
        self.proc=subprocess.Popen(self.command,stdout=self.log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+20
        while not (out/'ticket.peer2.json').exists():
            assert self.proc.poll() is None and time.monotonic()<deadline,'startup failed'
            time.sleep(.03)
    def control(self,action='ruleset',accept=True,**fields):
        with socket.create_connection(('127.0.0.1',self.cp),timeout=15) as sock:
            send(sock,dict(msg_type='runtime_control',protocol_version=1,request_id='final-fault',action=action,**fields))
            response=receive(sock)
        assert response['accepted']==accept,response
        return response
    def inspect(self):return self.control(ruleset={'operation':'inspect'})['ruleset']
    def participant(self,peer=1):
        grant=json.loads((self.out/('ticket.json' if peer==1 else f'ticket.peer{peer}.json')).read_text())
        sock=socket.create_connection(('127.0.0.1',self.ep),timeout=15);self.sockets.append(sock)
        cgs=json.loads((self.pkg/'game.cgs.json').read_text())['metadata']['cgs_hash']
        send(sock,dict(msg_type='handshake',protocol_version=1,engine_name='Godot',engine_version='4.6.3',adapter_version='0.1.0',cgs_hash=cgs,capabilities=[],session_offer_json=grant['offer_json'],session_peer_id=peer,session_credential=grant['credential']))
        baseline=receive(sock);assert baseline['accepted'];verify(baseline)
        send(sock,dict(msg_type='baseline_ack',stamp_json=baseline['sync_json']))
        self.ready=threading.Event();self.prepared=threading.Event();self.client_errors=[]
        def run():
            epoch=0;sequence=0
            try:
                while True:
                    row=receive(sock);kind=row['msg_type']
                    if kind=='input_tick_request':
                        sequence+=1
                        send(sock,dict(msg_type='input_packet',peer_id=peer,player_id=baseline['assigned_player_id'],tick=row['tick'],sequence_id=sequence,ruleset_epoch=epoch,actions=[]))
                        self.ready.set()
                    elif kind=='ruleset_prepare':
                        send(sock,dict(msg_type='ruleset_ready',activation_id=row['activation_id']));self.prepared.set()
                    elif kind in ['session_baseline','tick_snapshot']:
                        verify(row);epoch=row['sync']['ruleset_epoch'];send(sock,dict(msg_type='baseline_ack',stamp_json=row['sync_json']))
                    elif kind=='ruleset_commit':epoch+=1
                    elif kind=='disconnect':break
            except (OSError,EOFError):pass
            except Exception as exc:self.client_errors.append(repr(exc))
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
        assert self.ready.wait(10),'participant did not become ready'
    def stage(self,source=None,refusal=None):
        names=['game.cgs.json','execution_plan.json','world.json','world.manifest.json','compiled_schema.json','playable.manifest.json']
        source=source or self.artifacts/'candidate'
        files={n:list((source/n).read_bytes()) for n in names}
        identity=hashlib.sha256(json.dumps({'files':files},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        folder=self.out/'rulesets/incoming'/identity;folder.mkdir(parents=True)
        for n in names:shutil.copy2(source/n,folder/n)
        before=self.inspect()
        self.control(accept=False,ruleset=dict(operation='stage',artifact_digest=identity,approved_proposal_digest='0'*64))
        assert self.inspect()==before,'rejected approval changed live state'
        preview=self.control(ruleset=dict(operation='preview',artifact_digest=identity))['ruleset']
        response=self.control(accept=not bool(refusal),ruleset=dict(operation='stage',artifact_digest=identity,approved_proposal_digest=preview['proposal_digest']))
        if refusal:
            assert refusal in response['reason'],response
            assert self.inspect()==before,'failed migration changed live state'
            return response
        staged=response['ruleset']
        prepared=self.control(ruleset=dict(operation='prepare',candidate_digest=staged['candidate_digest'],proof_digest=staged['proof_digest'],activation_tick=3))['ruleset']
        assert self.prepared.wait(5),'participant did not acknowledge preparation'
        time.sleep(.05)
        self.prepare=dict(operation='prepare',candidate_digest=staged['candidate_digest'],proof_digest=staged['proof_digest'],activation_tick=3)
        return staged,prepared
    def step(self):
        tick=self.inspect()['tick'];self.control('step')
        deadline=time.monotonic()+15
        while self.inspect()['tick']<=tick:
            assert time.monotonic()<deadline,'step timed out'
            time.sleep(.02)
    def close(self):
        for sock in self.sockets:sock.close()
        if self.proc.poll() is None:self.proc.terminate();self.proc.wait(timeout=10)
        self.log.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();base=a.artifacts.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);results={}
    for case in ['crash-before-decision','crash-after-decision','changed-staged-artifact','unsupported-world-migration','slow-reader']:
        h=Host(base,out/case)
        try:
            if case=='slow-reader':
                grant=json.loads((h.out/'ticket.json').read_text())
                sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024);sock.settimeout(8)
                sock.connect(('127.0.0.1',h.ep));h.sockets.append(sock)
                cgs=json.loads((h.pkg/'game.cgs.json').read_text())['metadata']['cgs_hash']
                send(sock,dict(msg_type='handshake',protocol_version=1,engine_name='Godot',engine_version='4.6.3',adapter_version='0.1.0',cgs_hash=cgs,capabilities=[],session_offer_json=grant['offer_json'],session_peer_id=1,session_credential=grant['credential']))
                baseline=receive(sock);assert baseline['accepted'];verify(baseline)
                send(sock,dict(msg_type='baseline_ack',stamp_json=baseline['sync_json']));assert receive(sock)['msg_type']=='input_tick_request'
                # Real client keeps asking for full recovery but stops reading.
                packet=json.dumps(dict(msg_type='resync_request',connection_generation=1)).encode()
                raw=(struct.pack('<I',len(packet))+packet)*4000
                sock.settimeout(.5);started=time.monotonic()
                try:sock.sendall(raw)
                except OSError:pass
                peak=0;deadline=time.monotonic()+15;fenced=False
                while time.monotonic()<deadline:
                    peak=max(peak,memory_bytes(h.proc.pid)['private_bytes'])
                    assert peak<256*1024*1024
                    rows=[json.loads(line) for line in (h.out/'session.jsonl').read_text().splitlines() if line]
                    if any(r.get('peer_id')==1 and r.get('action') in ['disconnected','transport_closed'] for r in rows):fenced=True;break
                    time.sleep(.1)
                assert fenced,'non-reading client not fenced'
                h.participant(peer=2)
                h.step()
                results[case]=dict(fenced=True,authority_survived=True,elapsed_seconds=time.monotonic()-started,peak_private_bytes=peak,offered_resync_requests=4000)
            elif case=='unsupported-world-migration':
                import io,zipfile
                from tools.xp007_package_proof import compile_plan
                from tools.world_extensibility_proof import rehash
                from playable_package import RuntimeSupport,build_package,digest
                cgs=json.loads((base/'candidate/game.cgs.json').read_text())
                actor=next(actor for actor in cgs['modes'][0]['actors'] if actor['id']=='floor')
                component=next(c for c in actor['components'] if c['type_id']==1)
                component['defaults']['position']['x']+=1000000
                rehash(cgs);plan,compiled=compile_plan(cgs)
                runtime=(base/'parent/runtime/xace_runtime.exe').read_bytes()
                support=RuntimeSupport(digest(runtime),'xace.runtime_executor.v1',tuple(compiled.to_sgc_input()))
                raw=build_package(cgs,plan,runtime,support,package_id='reference.activation',version='1.0.0')
                altered=h.out/'altered'
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:archive.extractall(altered)
                response=h.stage(source=altered,refusal='world/capability migration requires a proven hook')
                results[case]=dict(rejected=True,reason=response['reason'],live_state_unchanged=True)
            else:
                h.participant()
                staged,prepared=h.stage()
                if case=='changed-staged-artifact':
                    target=h.out/'rulesets/candidates'/staged['candidate_digest']/'game.cgs.json'
                    # The staged content is modified after validation, before tick N.
                    assert target.exists();target.write_bytes(b'{}')
                if case!='crash-before-decision':
                    for _ in range(4):h.step()
                rows=[json.loads(line) for path in (h.out/'rulesets/activations').glob('*.jsonl') for line in path.read_text().splitlines()]
                kinds=[r['record'] for r in rows]
                if case=='changed-staged-artifact':
                    state=h.inspect();assert state['contract']['epoch']['ruleset_epoch']==0 and state['phase']=='live'
                    assert any('aborted' in json.dumps(k).lower() for k in kinds)
                    results[case]=dict(old_epoch_continued=True,activation_aborted=True,tick=state['tick'])
                else:
                    state=h.inspect();expected=0 if case=='crash-before-decision' else 1
                    assert state['contract']['epoch']['ruleset_epoch']==expected
                    if expected==1:
                        assert h.control(ruleset=h.prepare)['ruleset']==prepared,'duplicate commit not idempotent'
                    h.proc.kill();h.proc.wait(timeout=10)
                    restart_command=list(h.command)
                    restart_command[restart_command.index('--session-ticket-out')+1]=str(h.out/'restart-ticket.json')
                    restart_command[restart_command.index('--session-log')+1]=str(h.out/'restart-session.jsonl')
                    with (h.out/'restart.log').open('w') as log:
                        restart=subprocess.Popen(restart_command,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                        try:
                            if expected==1:
                                code=restart.wait(timeout=15);assert code!=0
                                assert 'recovered durable ruleset decision' in (h.out/'restart.log').read_text()
                            else:
                                deadline=time.monotonic()+15
                                while True:
                                    assert restart.poll() is None
                                    try:
                                        fresh=h.inspect();assert fresh['contract']['epoch']['ruleset_epoch']==0 and fresh['phase']=='live';break
                                    except OSError:
                                        assert time.monotonic()<deadline;time.sleep(.05)
                        finally:
                            if restart.poll() is None:restart.terminate();restart.wait(timeout=10)
                    results[case]=dict(actual_process_killed=True,epoch_at_kill=expected,restart_outcome='parent_refused_visible_halt' if expected else 'fresh_parent_no_activation',duplicate_commit_idempotent=expected==1)
            if h.proc.poll() is None:h.control('shutdown');assert h.proc.wait(timeout=10)==0
            (out/'progress.json').write_text(json.dumps(results,indent=2))
        finally:h.close()
    result=dict(schema='xace.xp022.process_faults.v1',ok=True,host_sha256=sha(base/'parent/runtime/xace_runtime.exe'),results=results,
                boundary='Black-box process kill before prepared decision and after published decision; no claim of sub-instruction fault injection.')
    (out/'proof.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()

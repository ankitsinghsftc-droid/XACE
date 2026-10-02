"""XP-013 real authority socket proof; full projections, late join, reconnect and recovery."""
import argparse, hashlib, json, socket, struct, subprocess, time
from pathlib import Path

def send(s,v):
    b=json.dumps(v,separators=(',',':')).encode();s.sendall(struct.pack('<I',len(b))+b)
def receive(s):
    def exact(n):
        b=b''
        while len(b)<n:
            c=s.recv(n-len(b))
            if not c: raise EOFError('closed')
            b+=c
        return b
    return json.loads(exact(struct.unpack('<I',exact(4))[0]))
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def verify(m):
    assert hashlib.sha256(m['projection_json'].encode()).hexdigest()==m['sync']['projection_digest']
    entities=json.loads(m['projection_json'])
    if 'entities' in m: assert entities==m['entities']
    if 'initial_entities' in m: assert entities==m['initial_entities']
    return entities
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--package',required=True);ap.add_argument('--out',required=True)
    a=ap.parse_args();pkg=Path(a.package).resolve();out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False)
    ep,cp=port(),port();ticket=out/'ticket.json';log=out/'session.jsonl'
    cmd=[str(pkg/'runtime/xace_runtime.exe')]
    for flag,name in [('cgs','game.cgs.json'),('sgc-plan','execution_plan.json'),('world','world.json'),('world-manifest','world.manifest.json'),('package-manifest','playable.manifest.json')]:cmd += ['--'+flag,str(pkg/name)]
    cmd += ['--session-ticket-out',str(ticket),'--session-log',str(log),'--session-controller-id','1,2','--input-lockstep-peer','1,2','--port',str(ep),'--control-port',str(cp),'--no-wait','--live-engine-accept','--start-paused','--live-session','--quiet']
    err=(out/'stderr.txt').open('w');proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    sockets=[];proof={}
    try:
        deadline=time.monotonic()+15
        while not (out/'ticket.peer2.json').exists() and time.monotonic()<deadline:time.sleep(.03)
        grants=[json.loads(ticket.read_text()),json.loads((out/'ticket.peer2.json').read_text())]
        cgs=json.loads((pkg/'game.cgs.json').read_text())['metadata']['cgs_hash']
        def connect(i,credential=None):
            s=socket.create_connection(('127.0.0.1',ep),timeout=8);sockets.append(s)
            send(s,{'msg_type':'handshake','protocol_version':1,'engine_name':'Godot','engine_version':'4.x','adapter_version':'0.1.0','cgs_hash':cgs,'capabilities':[], 'session_offer_json':grants[i]['offer_json'],'session_peer_id':i+1,'session_credential':credential or grants[i]['credential']})
            return s,receive(s)
        def control(action):
            with socket.create_connection(('127.0.0.1',cp),timeout=8) as s:
                send(s,{'msg_type':'runtime_control','protocol_version':1,'request_id':'proof','action':action});m=receive(s);assert m['accepted'],m;return m
        def ack(s,m):
            verify(m);send(s,{'msg_type':'baseline_ack','stamp_json':m['sync_json']})
        def request(s,t):
            m=receive(s);assert m['msg_type']=='input_tick_request' and m['tick']==t,m
        def packet(s,who,player,t,seq):
            send(s,{'msg_type':'input_packet','peer_id':who,'player_id':player,'tick':t,'sequence_id':seq,'actions':[]})
        def snapshot(s,t):
            m=receive(s);assert m['msg_type']=='tick_snapshot' and m['tick']==t,m;verify(m);return m
        def quiet(s):
            s.settimeout(.12)
            try: m=receive(s);raise AssertionError(('unexpected frame',m))
            except socket.timeout: pass
            finally:s.settimeout(8)
        s1,b1=connect(0);assert b1['accepted'];ack(s1,b1);request(s1,0);p1=b1['assigned_player_id']
        packet(s1,1,p1,0,1);control('step');m1=snapshot(s1,0);ack(s1,m1);request(s1,1)
        s2,b2=connect(1);assert b2['accepted'];assert b2['sync']['next_tick']==1;verify(b2);p2=b2['assigned_player_id'];assert p1!=p2
        # An unready joiner never stalls the existing player.
        packet(s1,1,p1,1,2);control('step');m1=snapshot(s1,1);ack(s1,m1);request(s1,2);quiet(s2)
        ack(s2,b2);refresh=receive(s2);assert refresh['msg_type']=='session_baseline' and refresh['sync']['next_tick']==2
        bad=json.loads(json.dumps(refresh['sync']));bad['projection_digest']='0'*64
        send(s2,{'msg_type':'baseline_ack','stamp_json':json.dumps(bad)});quiet(s2)
        ack(s2,refresh);request(s2,2)
        packet(s1,1,p1,2,3);packet(s2,2,p2,2,1);control('step');m1=snapshot(s1,2);m2=snapshot(s2,2)
        assert verify(m1)==verify(m2);ack(s1,m1);ack(s2,m2);request(s1,3);request(s2,3)
        proof['late_join']={'initial_next_tick':1,'activated_next_tick':2,'projection_digest':m2['sync']['projection_digest'],'unready_peer_did_not_block':True,'bad_digest_ack_rejected':True}
        token=b2['reconnect_credential'];s2.close();time.sleep(.15)
        packet(s1,1,p1,3,4);control('step');m1=snapshot(s1,3);ack(s1,m1);request(s1,4)
        stale,reject=connect(1);assert not reject['accepted'];stale.close()
        s2,b3=connect(1,token);assert b3['accepted'] and b3['assigned_player_id']==p2 and b3['sync']['connection_generation']==2 and b3['sync']['next_tick']==4
        send(s2,{'msg_type':'baseline_ack','stamp_json':m2['sync_json']});quiet(s2);ack(s2,b3);request(s2,4)
        proof['reconnect']={'player_id':p2,'generation':2,'next_tick':4,'spent_token_rejected':True,'stale_generation_ack_rejected':True}
        # Explicit recovery fences the peer and replaces its baseline after host advances.
        send(s2,{'msg_type':'resync_request','connection_generation':2});r=receive(s2);assert r['msg_type']=='session_baseline';quiet(s2)
        packet(s1,1,p1,4,5);control('step');m1=snapshot(s1,4);ack(s1,m1);request(s1,5)
        ack(s2,r);r=receive(s2);assert r['sync']['next_tick']==5;ack(s2,r);request(s2,5)
        packet(s1,1,p1,5,6);packet(s2,2,p2,5,1);control('step');m1=snapshot(s1,5);m2=snapshot(s2,5);assert verify(m1)==verify(m2)
        ack(s1,m1);request(s1,6)
        # Treat the peer's tick update as dropped; request and verify a full replacement.
        send(s2,{'msg_type':'resync_request','connection_generation':2});r=receive(s2);assert r['sync']['next_tick']==6
        assert verify(r)==verify(m1);ack(s2,r);request(s2,6)
        proof['recovery']={'next_tick':6,'restored_digest':r['sync']['projection_digest'],'matches_authority':True,'catch_up_baselines_retained':1}
        # A dropped baseline must time out without admitting this peer.
        send(s2,{'msg_type':'resync_request','connection_generation':2});dropped=receive(s2);assert dropped['msg_type']=='session_baseline'
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            rows=[json.loads(x) for x in log.read_text().splitlines()]
            if any(x.get('action')=='disconnected' and x.get('peer_id')==2 for x in rows[-3:]):break
            time.sleep(.08)
        assert any(x.get('action')=='disconnected' and x.get('peer_id')==2 for x in rows[-3:]),rows[-3:]
        packet(s1,1,p1,6,7);control('step');m1=snapshot(s1,6)
        proof['dropped_baseline']={'fenced_after_timeout':True,'other_player_completed_tick':6}
        control('shutdown');proc.wait(timeout=8)
        assert proc.returncode==0
        (out/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
    finally:
        for s in sockets:s.close()
        if proc.poll() is None:proc.terminate();proc.wait(timeout=8)
        err.close()
if __name__=='__main__':main()

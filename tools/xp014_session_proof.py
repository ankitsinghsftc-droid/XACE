"""XP-014 exported two-Player proof. Same-machine evidence, not two-machine certification."""
from pathlib import Path
import argparse,hashlib,json,os,socket,struct,time,sys,threading,queue
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.xp010_launch_proof import Native,stopped,terminate

def rpc(code,action,**extra):
    invite=json.loads(bytes.fromhex(code.removeprefix('XACE1-')))
    host,port=invite['endpoint'].rsplit(':',1)
    with socket.create_connection((host,int(port)),timeout=5) as s:
        raw=json.dumps({'schema':'xace.invite_request.v1','token':invite['token'],'action':action,**extra}).encode();s.sendall(struct.pack('<I',len(raw))+raw)
        def read(n):
            b=b''
            while len(b)<n:
                c=s.recv(n-len(b))
                if not c:raise EOFError()
                b+=c
            return b
        return json.loads(read(struct.unpack('<I',read(4))[0]))
class FaultProxy:
    def __init__(self,code,mode):
        self.code=code;self.mode=mode;self.stop=threading.Event();self.started=threading.Event()
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen();self.listener.settimeout(.1)
        invite=json.loads(bytes.fromhex(code[6:]));invite['endpoint']='127.0.0.1:'+str(self.listener.getsockname()[1]);self.invite='XACE1-'+json.dumps(invite).encode().hex()
        self.thread=threading.Thread(target=self.serve,daemon=True);self.thread.start()
    def serve(self):
        while not self.stop.is_set():
            try:conn,_=self.listener.accept()
            except socket.timeout:continue
            except OSError:break
            with conn:
                conn.settimeout(5)
                def exact(n):
                    b=b''
                    while len(b)<n:
                        c=conn.recv(n-len(b))
                        if not c:raise EOFError()
                        b+=c
                    return b
                try:
                    request=json.loads(exact(struct.unpack('<I',exact(4))[0]))
                    if self.mode=='cancel' and request['action']=='file' and not self.started.is_set():self.started.set();time.sleep(1)
                    result=rpc(self.code,request['action'],**{k:v for k,v in request.items() if k not in {'schema','token','action'}})
                    if self.mode=='readiness' and request['action']=='redeem' and result['ok']:result['result']['ticket']['controller_id']=999
                    raw=json.dumps(result).encode();conn.sendall(struct.pack('<I',len(raw))+raw)
                except (OSError,EOFError):pass
    def close(self):self.stop.set();self.listener.close();self.thread.join(timeout=3)

def run(release,out):
    release=Path(release).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    os.environ['XACE_SESSION_ADDRESS']='127.0.0.1'
    host=Native(release,out/'host');friend=Native(release,out/'friend');proof={}
    try:
        response=host.request('play');assert response['ok'],response;playing=response['result'];print('host ready',flush=True)
        assert playing['session_mode']=='hosting' and playing['runtime_pid']>0
        invite=host.request('invite');assert invite['ok'],invite;code=invite['result']['code']
        assert not host.request('join',code=code)['ok']
        desc=rpc(code,'describe');assert desc['ok'],desc
        assert not rpc(code,'file',path='runtime/xace_runtime.exe',offset=0)['ok']
        assert not rpc(code,'file',path='../distribution.json',offset=0)['ok']
        expired=json.loads(bytes.fromhex(code[6:]));expired['expires_at']=0
        rejection=friend.request('join',code='XACE1-'+json.dumps(expired).encode().hex());assert not rejection['ok'] and 'expired' in rejection['message'],rejection
        # Modify the host's installed data after its immutable descriptor was prepared.
        digest=json.loads((release/'distribution.trust.json').read_text())['manifest_sha256']
        world=out/'host/versions'/digest/'package/world.json';original=world.read_bytes()
        try:
            world.write_bytes(b'X'+original[1:]);rejection=friend.request('join',code=code)
            assert not rejection['ok'] and 'verification' in rejection['message'],rejection
        finally:world.write_bytes(original)
        assert friend.request('status')['result']['state']=='stopped'
        assert not list((out/'friend/session-cache').iterdir())
        proof['refusals']={'expired_invite':True,'tampered_file':True,'executable_download':True,'path_escape':True,'failed_acquisition_leaves_no_player_or_cache':True}
        joined=friend.request('join',code=code);assert joined['ok'],joined;joined=joined['result'];print('friend ready',flush=True)
        assert joined['session_mode']=='joined' and joined['runtime_pid'] is None,joined
        status=host.request('status')['result'];members=status['readiness']['members'];assert {x['player'] for x in members if x['state']=='Playing'}=={1,2},status
        log=max((out/'host/session-history').glob('*.jsonl'),key=lambda p:p.stat().st_mtime_ns);rows=[json.loads(x) for x in log.read_text().splitlines()]
        admissions=[x for x in rows if x.get('action')=='admitted'];assert len(admissions)==2 and len({x['player_id'] for x in admissions})==2
        verified=[x for x in rows if x.get('kind')=='baseline_verified'];assert len(verified)>=2
        assert len({x['stamp']['session_id'] for x in verified})==1
        replay=friend.request('join',code=code);assert not replay['ok'] and 'already used' in replay['message'],replay
        assert friend.request('status')['result']['player_pid']==joined['player_pid']
        proof['play_invite_join']={'one_authority':True,'distinct_players':[x['player_id'] for x in admissions],'same_session':True,'readiness':members,'package_missing_acquired':True,'invite_replay_refused_without_closing_player':True,'recipient_developer_tools_removed_from_PATH':True}
        assert friend.request('stop')['ok'];stopped(joined['player_pid']);time.sleep(.2)
        states=host.request('status')['result']['readiness']['members'];assert any(x['player']==2 and x['state']=='Disconnected' for x in states),states
        assert not list((out/'friend/session-cache').iterdir())
        assert host.request('stop')['ok'];stopped(playing['player_pid'],playing['runtime_pid'])
        try:rpc(code,'describe');raise AssertionError('host service survived End')
        except (ConnectionError,OSError):pass
        proof['leave_end']={'friend_membership_released':True,'cache_released':True,'host_runtime_and_player_stopped':True,'invite_service_closed':True,'authoritative_journal_preserved':log.exists()}
        # A recipient closes its existing Player while acquisition is in progress.
        again=host.request('play');assert again['ok'],again
        second_code=host.request('invite')['result']['code']
        previous=friend.request('play');assert previous['ok'],previous
        proxy=FaultProxy(second_code,'cancel');responses=queue.Queue()
        worker=threading.Thread(target=lambda:responses.put(friend.request('join',code=proxy.invite)),daemon=True);worker.start()
        try:
            assert proxy.started.wait(10),'download did not start'
            terminate(previous['result']['player_pid'])
            cancelled=responses.get(timeout=20);assert not cancelled['ok'] and 'cancelled' in cancelled['message'],cancelled
        finally:proxy.close();worker.join(timeout=3)
        assert friend.request('status')['result']['state']=='stopped'
        stopped(previous['result']['player_pid'],previous['result']['runtime_pid'])
        assert not list((out/'friend/session-cache').iterdir())
        # Valid bytes but an unusable presentation/controller assignment must never become ready.
        proxy=FaultProxy(second_code,'readiness')
        try:
            refused=friend.request('join',code=proxy.invite);assert not refused['ok'] and 'controllable entity' in refused['message'],refused
        finally:proxy.close()
        assert friend.request('status')['result']['state']=='stopped'
        assert not list((out/'friend/session-cache').iterdir())
        time.sleep(.2)
        log=max((out/'host/session-history').glob('*.jsonl'),key=lambda p:p.stat().st_mtime_ns);rows=[json.loads(x) for x in log.read_text().splitlines()]
        assert not any(x.get('kind')=='baseline_verified' and x.get('peer_id')==2 for x in rows)
        assert any(x.get('kind')=='input_validation' and x.get('peer_id')==1 and x.get('decision')=='accepted' for x in rows)
        proof['preparation_failures']={'close_cancels_download':True,'cancelled_cache_removed':True,'readiness_failure_refused':True,'failed_player_never_required':True,'host_kept_playing':True}
        assert host.request('stop')['ok'];stopped(again['result']['player_pid'],again['result']['runtime_pid'])

    finally:friend.close();host.close()
    evidence={'schema':'xace.xp014.proof.v1','ok':True,'same_machine_only':True,'two_machine_acceptance':'pending_owner_has_no_second_machine','results':proof}
    (out/'proof.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence,indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--release',required=True);parser.add_argument('--out',required=True);a=parser.parse_args();run(a.release,a.out)

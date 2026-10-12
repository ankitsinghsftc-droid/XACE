"""XP-015 local TLS relay proof. Public deployment/two-network acceptance remains pending."""
from pathlib import Path
import argparse,hashlib,json,os,socket,ssl,struct,subprocess,sys,time,threading,queue,secrets,select
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.xp010_launch_proof import Native as BaseNative,stopped
class Native(BaseNative):
    def request(self,action,**extra):
        self.p.stdin.write(json.dumps({"schema":"xace.player.broker_request.v1","capability":self.cap,"action":action,**extra})+"\n");self.p.stdin.flush();return self.q.get(timeout=150 if action=="join" else 25)
    def close(self):
        try:super().close()
        except subprocess.TimeoutExpired:self.p.kill();self.p.wait(timeout=10)

OPENSSL=Path('C:/Program Files/Git/usr/bin/openssl.exe')

def certificates(out):
    # Ephemeral test key: never a deployment certificate or checked-in secret.
    subprocess.run([str(OPENSSL),'req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=XACE Test CA','-addext','basicConstraints=critical,CA:TRUE','-keyout',str(out/'ca-key.pem'),'-out',str(out/'ca.pem')],check=True,capture_output=True)
    subprocess.run([str(OPENSSL),'req','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout',str(out/'key.pem'),'-out',str(out/'request.pem')],check=True,capture_output=True)
    (out/'extensions.txt').write_text('subjectAltName=DNS:localhost\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
    subprocess.run([str(OPENSSL),'x509','-req','-in','request.pem','-CA','ca.pem','-CAkey','ca-key.pem','-CAcreateserial','-days','2','-extfile','extensions.txt','-out','cert.pem'],cwd=out,check=True,capture_output=True)
    for args in [('x509','-in','cert.pem','-outform','DER','-out','cert.der'),('x509','-in','ca.pem','-outform','DER','-out','ca.der'),('pkcs8','-topk8','-nocrypt','-in','key.pem','-outform','DER','-out','key.der')]:
        subprocess.run([str(OPENSSL),*args],cwd=out,check=True,capture_output=True)

def exact(s,n):
    b=b''
    while len(b)<n:
        part=s.recv(n-len(b))
        if not part:raise EOFError('relay refused or disconnected')
        b+=part
    return b

def send(s,request):
    data=json.dumps({'schema':'xace.relay.request.v1','request':request}).encode();s.sendall(struct.pack('<I',len(data))+data)
def receive(s):return json.loads(exact(s,struct.unpack('<I',exact(s,4))[0]))
class FaultLink:
    """Opaque TCP fault injector: cannot decode or modify authenticated TLS records."""
    def __init__(self,target):
        self.target=target;self.stop=threading.Event();self.lock=threading.Lock();self.connections=[];self.capture=bytearray()
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.port=self.listener.getsockname()[1];self.listener.listen();self.listener.settimeout(.1)
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        while not self.stop.is_set():
            try:a,_=self.listener.accept()
            except socket.timeout:continue
            except OSError:break
            threading.Thread(target=self.forward,args=(a,),daemon=True).start()
    def forward(self,a):
        b=None
        try:
            b=socket.create_connection(('127.0.0.1',self.target),timeout=5)
            with self.lock:self.connections.append((a,b))
            while not self.stop.is_set():
                ready,_,_=select.select([a,b],[],[],.1)
                for source in ready:
                    data=source.recv(16384)
                    if not data:return
                    with self.lock:
                        if len(self.capture)<65536:self.capture.extend(data[:65536-len(self.capture)])
                    (b if source is a else a).sendall(data)
        except (OSError,ValueError):pass
        finally:
            with self.lock:
                if (a,b) in self.connections:self.connections.remove((a,b))
            a.close()
            if b:b.close()
    def drop_connections(self):
        with self.lock:
            for pair in self.connections:
                for s in pair:
                    try:s.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
    def close(self):
        self.stop.set();self.drop_connections();self.listener.close();self.thread.join(timeout=2)

class Relay:
    def __init__(self,out):
        self.out=out;certificates(out);self.secret=secrets.token_hex(32)
        with socket.socket() as s:s.bind(('127.0.0.1',0));self.port=s.getsockname()[1]
        self.link=FaultLink(self.port)
        self.ctx=ssl.create_default_context(cafile=str(out/'ca.pem'));self.ctx.minimum_version=ssl.TLSVersion.TLSv1_3
        env=dict(os.environ,XACE_RELAY_OPERATOR_TOKEN=self.secret)
        self.log=(out/'relay.log').open('w')
        executable=Path(os.environ.get('XACE_PROOF_RELAY',str(ROOT/'target/debug/xace-session-relay.exe'))).resolve()
        (out/'relay-identity.json').write_text(json.dumps({'executable':str(executable),'sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}))
        self.p=subprocess.Popen([str(executable),'127.0.0.1:'+str(self.port),str(out/'cert.der'),str(out/'key.der')],env=env,stdout=self.log,stderr=self.log,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            try:
                with self.dial():break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('relay startup failed')
    def dial(self,ctx=None):
        tcp=socket.create_connection(('127.0.0.1',self.port),timeout=6)
        try:return (ctx or self.ctx).wrap_socket(tcp,server_hostname='localhost')
        except BaseException:tcp.close();raise
    def rpc(self,action,**fields):
        with self.dial() as s:send(s,dict(action=action,**fields));r=receive(s);assert r['ok'],r;return r
    def refused(self,action,**fields):
        try:self.rpc(action,**fields)
        except (EOFError,OSError,AssertionError):return
        raise AssertionError('unexpectedly accepted '+action)
    def close(self):
        if self.p.poll() is None:self.p.terminate()
        self.p.wait(timeout=10);self.log.close();self.link.close()
    def config(self,name,host=False):
        p=self.out/(name+'.json');p.write_text(json.dumps({'schema':'xace.relay.config.v1','host':'localhost','port':self.link.port,'ca_der':str(self.out/'ca.der'),'host_credential':self.secret if host else None}));return p

def protocol(relay):
    try:relay.dial(ssl.create_default_context());raise AssertionError('untrusted certificate accepted')
    except ssl.SSLError:pass
    relay.refused('register',credential='0'*64)
    relay.refused('shutdown')
    r=relay.rpc('register',credential=relay.secret);session=r['session'];host=r['credential'];cap=secrets.token_hex(32)
    relay.refused('publish',session=session,host=host,capability=cap,expires=int(time.time())-1)
    relay.rpc('publish',session=session,host=host,capability=cap,expires=int(time.time())+600)
    lease=relay.rpc('exchange',session=session,capability=cap)['credential']
    relay.refused('exchange',session=session,capability=cap)
    relay.refused('connect',session=session,lease=lease,service='control')
    relay.refused('connect',session=session,lease=lease,service='game',target='127.0.0.1:22')
    relay.refused('poll',session=session,host=lease)
    # Pair a real TLS byte stream; attach channel capabilities are one use.
    guest=relay.dial();send(guest,dict(action='connect',session=session,lease=lease,service='game'))
    incoming=[]
    for _ in range(30):
        incoming=relay.rpc('poll',session=session,host=host)['incoming']
        if incoming:break
        time.sleep(.03)
    assert incoming
    channel=incoming[0]['channel'];authority=relay.dial();send(authority,dict(action='attach',session=session,host=host,channel=channel));assert receive(authority)['ok'];assert receive(guest)['ok']
    guest.sendall(b'canonical bytes');assert exact(authority,15)==b'canonical bytes'
    authority.sendall(b'unchanged');assert exact(guest,9)==b'unchanged'
    relay.refused('attach',session=session,host=host,channel=channel)
    relay.rpc('end',session=session,host=host)
    try:assert guest.recv(1)==b''
    except (OSError,ssl.SSLError):pass
    guest.close();authority.close();relay.refused('connect',session=session,lease=lease,service='game')
    # Session table cannot exceed the declared bound.
    sessions=[relay.rpc('register',credential=relay.secret) for _ in range(16)]
    relay.refused('register',credential=relay.secret)
    for s in sessions:relay.rpc('end',session=s['session'],host=s['credential'])
    return dict(tls13_verified=True,untrusted_certificate_refused=True,host_auth_required=True,expired_invite_refused=True,invite_replay_refused=True,channel_replay_refused=True,control_and_arbitrary_target_refused=True,guest_cannot_poll_host=True,bytes_preserved=True,end_closes_tunnels=True,session_bound_16=True)

def limits(relay):
    with relay.dial() as sock:
        sock.sendall(struct.pack('<I',8193))
        try:assert sock.recv(1)==b''
        except OSError:pass
    r=relay.rpc('register',credential=relay.secret);sid=r['session'];host=r['credential'];cap=secrets.token_hex(32)
    relay.rpc('publish',session=sid,host=host,capability=cap,expires=int(time.time())+1)
    time.sleep(1.1);relay.refused('exchange',session=sid,capability=cap)
    cap=secrets.token_hex(32);relay.rpc('publish',session=sid,host=host,capability=cap,expires=int(time.time())+600)
    lease=relay.rpc('exchange',session=sid,capability=cap)['credential']
    def pair():
        guest=relay.dial();send(guest,dict(action='connect',session=sid,lease=lease,service='game'))
        incoming=[]
        while not incoming:
            incoming=relay.rpc('poll',session=sid,host=host)['incoming']
            if not incoming:time.sleep(.01)
        authority=relay.dial();send(authority,dict(action='attach',session=sid,host=host,channel=incoming[0]['channel']));receive(authority);receive(guest);return guest,authority
    a,b=pair();c,d=pair()
    relay.refused('connect',session=sid,lease=lease,service='game')
    c.close();d.close()
    # Overrun the aggregate per-session traffic budget. The relay must close,
    # not buffer an unbounded backlog or forward all offered bytes.
    received=[]
    def drain():
        count=0
        try:
            while True:
                data=b.recv(65536)
                if not data:break
                count+=len(data)
        except OSError:pass
        received.append(count)
    reader=threading.Thread(target=drain,daemon=True);reader.start();started=time.monotonic()
    try:
        for _ in range(512):a.sendall(b'x'*65536)
    except OSError:pass
    reader.join(timeout=8);a.close();b.close();assert received and received[0]<32*1024*1024,received
    relay.rpc('end',session=sid,host=host)
    expired=relay.rpc('register',credential=relay.secret);time.sleep(11)
    relay.refused('poll',session=expired['session'],host=expired['credential'])
    return dict(frame_size_enforced=True,expired_capability_refused=True,two_connections_per_lease=True,traffic_limit_closes_tunnel=True,forwarded_before_limit=received[0],traffic_test_seconds=round(time.monotonic()-started-11,3),abandoned_host_expires=True)

def journal_rows(path):
    # The authority can be appending the final record during a proof read.
    data=path.read_bytes();complete=data[:data.rfind(b'\n')+1]
    return [json.loads(line) for line in complete.splitlines()]

def run(release,out):
    release=Path(release).resolve() if release else None;out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    relay=Relay(out);host=friend=None;old=os.environ.get('XACE_RELAY_CONFIG');proof={}
    try:
        proof['protocol']=protocol(relay);proof['limits']=limits(relay);print('TLS relay protocol proof passed',flush=True)
        if release:
            os.environ['XACE_RELAY_CONFIG']=str(relay.config('host-config',True));host=Native(release,out/'host')
            os.environ['XACE_RELAY_CONFIG']=str(relay.config('friend-config'));friend=Native(release,out/'friend')
            playing=host.request('play');assert playing['ok'],playing;playing=playing['result']
            invite=host.request('invite');assert invite['ok'],invite;code=invite['result']['code'];v=json.loads(bytes.fromhex(code[6:]));assert v['schema']=='xace.invite.v2'
            assert not host.request('join',code=code)['ok']
            good_config=relay.config('friend-config')
            bad_ca=out/'untrusted';bad_ca.mkdir();certificates(bad_ca)
            for label,change in [('wrong-hostname',{'host':'127.0.0.1'}),('wrong-ca',{'ca_der':str(bad_ca/'ca.der')})]:
                config=json.loads(good_config.read_text());config.update(change);bad_config=out/(label+'.json');bad_config.write_text(json.dumps(config))
                os.environ['XACE_RELAY_CONFIG']=str(bad_config);untrusted=Native(release,out/label)
                try:
                    refused=untrusted.request('join',code=code);assert not refused['ok'],label
                    assert untrusted.request('status')['result']['state']=='stopped'
                finally:untrusted.close()
            os.environ['XACE_RELAY_CONFIG']=str(good_config)
            proof['native_certificate_refusals']=dict(wrong_hostname=True,wrong_ca=True,no_player_started=True)

            response=friend.request('join',code=code)
            if not response['ok']:print('join failure',response,'host',host.request('status'),flush=True)
            assert response['ok'],response;joined=response['result'];assert joined['runtime_pid'] is None
            status=host.request('status')['result'];assert status['readiness']['scope']=='relay';assert {m['player'] for m in status['readiness']['members'] if m['state']=='Playing'}=={1,2},status
            assert not friend.request('join',code=code)['ok'];assert friend.request('status')['result']['player_pid']==joined['player_pid']
            log=max((out/'host/session-history').glob('*.jsonl'),key=lambda p:p.stat().st_mtime_ns)
            rows=journal_rows(log);admitted=[x for x in rows if x.get('action')=='admitted'];assert len({x['player_id'] for x in admitted})==2
            proof['players']=dict(one_authority=True,distinct_players=[x['player_id'] for x in admitted],package_acquired_through_tls=True,gameplay_through_tls=True,replay_keeps_existing_player=True,tools_absent_from_player_path=True)
            print('Exported Players joined through TLS relay',flush=True)
            relay.link.drop_connections()
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                rows=journal_rows(log)
                verified=[x for x in rows if x.get('kind')=='baseline_verified' and x.get('peer_id')==2 and x['stamp']['connection_generation']>=2]
                if verified:break
                time.sleep(.15)
            else:raise AssertionError('remote Player did not regain verified membership after tunnel loss')
            after=host.request('status')['result'];assert after['player_pid']==playing['player_pid'];assert friend.request('status')['result']['player_pid']==joined['player_pid']
            captured=bytes(relay.link.capture);assert b'xace.relay.request.v1' not in captured and v['token'].encode() not in captured
            proof['reconnect']=dict(same_players_and_authority=True,verified_generation=verified[-1]['stamp']['connection_generation'],tls_capture_bytes=len(captured),application_plaintext_absent=True)
            print('Transient relay link loss recovered with a new verified baseline',flush=True)
            # A relay outage must fence the remote input owner, preserving the same host.
            relay.close();deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                status=host.request('status')['result'];members=status['readiness']['members']
                if any(m['player']==2 and m['state']=='Disconnected' for m in members) and status['readiness']['transport_health']!='connected':break
                time.sleep(.2)
            else:raise AssertionError(('relay loss not fenced',status))
            assert status['player_pid']==playing['player_pid'];assert not host.request('invite')['ok']
            rows=journal_rows(log);assert len([x for x in rows if x.get('kind')=='start'])==1
            proof['outage']=dict(remote_membership_fenced=True,host_preserved=True,no_second_authority=True,visible_health_failure=True,no_silent_private_fallback=True)
            assert friend.request('stop')['ok'];stopped(joined['player_pid']);assert host.request('stop')['ok'];stopped(playing['player_pid'],playing['runtime_pid']);assert log.exists();assert not list((out/'friend/session-cache').iterdir())
            proof['cleanup']=dict(players_stopped=True,cache_removed=True,journal_preserved=True)
    finally:
        if friend:friend.close()
        if host:host.close()
        relay.close()
        if old is None:os.environ.pop('XACE_RELAY_CONFIG',None)
        else:os.environ['XACE_RELAY_CONFIG']=old
    result=dict(schema='xace.xp015.proof.v1',ok=True,same_machine_only=True,public_deployment='pending_owner_has_no_hosting',two_network_acceptance='pending',results=proof)
    (out/'proof.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release');p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(run(a.release,a.out),indent=2))

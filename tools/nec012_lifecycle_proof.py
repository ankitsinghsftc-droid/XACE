"""Create-only local process proof, not native engine build certification."""
from pathlib import Path
import copy,hashlib,json,os,queue,shutil,socket,subprocess,sys,threading
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.xp010_launch_proof import terminate,stopped

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class Host:
    def __init__(self,exe,release,expected,history):
        env=dict(os.environ);env['LOCALAPPDATA']=str(history.parent/'user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
        for key in ['PYTHONPATH','CARGO_HOME','RUSTUP_HOME']:env.pop(key,None)
        self.p=subprocess.Popen([str(exe),'--native-host','--source',str(release),'--expected',expected,'--history',str(history),'--controller','1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        self.q=queue.Queue()
        def read():
            for line in self.p.stdout:self.q.put(json.loads(line))
        threading.Thread(target=read,daemon=True).start()
        self.initial=self.q.get(timeout=15)
    def ask(self,action,**args):
        self.p.stdin.write(json.dumps(dict(action=action,**args))+'\n');self.p.stdin.flush();return self.q.get(timeout=15)
    def close(self):
        self.p.stdin.close();self.p.wait(timeout=15);self.p.stdout.close();self.p.stderr.close()
def main(out):
    out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec012') and not out.exists()
    out.mkdir(parents=True);release=out/'release';release.mkdir()
    shutil.copytree(ROOT/'evidence/nec011/20261023/godot-input-authority-f/original/package',release/'package')
    shutil.copyfile(ROOT/'evidence/nec011/20261021/reference-admission-a/executor-receipt.json',release/'executor-receipt.json')
    executor=json.loads((release/'executor-receipt.json').read_bytes())
    receipt=dict(schema='xace.native_release.v1',game_id='nec012-proof',engine='Godot',executor_receipt_sha256=sha(release/'executor-receipt.json'),package_manifest_sha256=sha(release/'package/playable.manifest.json'),compatibility=executor['compatibility'],required_capabilities=['native.structured_transform.v1'],resources=[],save_schema='nec012.proof_save.v1')
    resource=release/'native/audio.tres';resource.parent.mkdir();shutil.copyfile(release/'package/presentation/player/audio.tres',resource)
    receipt['resources']=[dict(path='native/audio.tres',sha256=sha(resource),size=resource.stat().st_size)]
    def publish(value):
        (release/'native-release.json').write_text(json.dumps(value,sort_keys=True),encoding='utf-8');return sha(release/'native-release.json')
    expected=publish(receipt)
    exe=out/'xace-player-launcher.exe';shutil.copyfile(Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-player-launcher.exe'),exe)
    checks={};h=None
    sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        h=Host(exe,release,expected,out/'history');assert h.initial['state']=='stopped',h.initial
        assert h.ask('verify')['ok']
        original_resource=resource.read_bytes();resource.write_bytes(original_resource+b'changed')
        assert not h.ask('play')['ok'];resource.write_bytes(original_resource);checks['changed_native_resource_refused']=True
        save_root=Path(h.initial['save_root']);save_root.mkdir(parents=True)
        identity=h.initial['save_identity'];snapshot=dict(tick=42,rng_state=dict(world_seed=17))
        envelope=dict(schema='xace.native_save.v1',identity=identity,payload_sha256=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest(),snapshot=snapshot)
        save=save_root/'slot-proof.json';save.write_text(json.dumps(envelope));original_save=save.read_bytes()
        assert h.ask('check-save',slot='proof')['result']==dict(state='save_compatible',restored=False)
        envelope['identity']['executor_sha256']='0'*64;save.write_text(json.dumps(envelope));incompatible=save.read_bytes()
        assert not h.ask('check-save',slot='proof')['ok'];assert save.read_bytes()==incompatible
        save.write_bytes(original_save);checks['save_admission_and_non_destructive_refusal']=True
        assert not h.ask('check-save',slot='../outside')['ok'];checks['save_slot_traversal_refused']=True
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen();port=occupied.getsockname()[1]
            response=h.ask('play',preferred_port=port);assert response['ok'],response
            first=response['result'];assert not first['endpoint'].endswith(':'+str(port))
            assert h.ask('play')['result']['runtime_pid']==first['runtime_pid']
            assert h.ask('stop')['ok'];stopped(first['runtime_pid'])
        active=out/'user-data/XACE/NativeGames/game-nec012-proof/release-state/active.json';previous=active.read_bytes()
        checks.update(offline_without_toolchain_start=True,collision_fallback=True,repeated_play_same_owner=True,explicit_stop=True)
        live=h.ask('play')['result'];h.close();h=None;stopped(live['runtime_pid']);checks['eof_stops_owned_authority']=True
        h=Host(exe,release,expected,out/'history');live=h.ask('play')['result'];terminate(live['runtime_pid']);event=h.q.get(timeout=10);assert event['state']=='authority_lost' and event['native_fallback'] is False,event
        h.close();h=None;checks['authority_crash_visible_no_fallback']=True
        h=Host(exe,release,expected,out/'history');live=h.ask('play')['result'];h.p.kill();h.p.wait(timeout=10);h.close();h=None;stopped(live['runtime_pid']);checks['owner_crash_job_cleanup']=True
        h=Host(exe,release,expected,out/'history')
        target=release/'package/world.json';original=target.read_bytes();target.write_bytes(b'{}')
        assert not h.ask('play')['ok'];assert active.read_bytes()==previous;checks['failed_start_retains_active']=True;target.write_bytes(original);h.close();h=None;checks['changed_package_refused_before_spawn']=True
        for label,change in [('stale_executor',lambda r:r.update(executor_receipt_sha256='0'*64)),('missing_capability',lambda r:r.update(required_capabilities=['absent.v1'])),('incompatible_snapshot',lambda r:r['compatibility'].update(snapshot_schema='unknown.v1'))]:
            altered=copy.deepcopy(receipt);change(altered);pin=publish(altered)
            h=Host(exe,release,pin,out/'history');assert h.initial.get('ok') is False,h.initial;h.close();h=None;checks[label]=True;assert active.read_bytes()==previous
        original_executor=(release/'executor-receipt.json').read_bytes()
        for label,change in [('source_inventory_mismatch',lambda r:r['source_files'].update({'Cargo.lock':'0'*64})),('online_creator_recipe',lambda r:r['build'].update(command=['cargo','build','--locked'])),('nondeterministic_executor',lambda r:r['systems'][0].update(deterministic=False))]:
            changed=json.loads(original_executor);change(changed);(release/'executor-receipt.json').write_text(json.dumps(changed))
            altered=copy.deepcopy(receipt);altered['executor_receipt_sha256']=sha(release/'executor-receipt.json');pin=publish(altered)
            h=Host(exe,release,pin,out/'history');assert h.initial.get('ok') is False,h.initial;h.close();h=None;checks[label]=True
        (release/'executor-receipt.json').write_bytes(original_executor)
        publish(receipt);assert sentinel.poll() is None;checks['unrelated_process_survives']=True
    finally:
        if h:h.close()
        sentinel.terminate();sentinel.wait()
    sources={p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'packages/player-launcher/src').glob('*.rs'))}
    (out/'proof.json').write_text(json.dumps(dict(ok=True,checks=checks,source_files=sources,launcher_sha256=sha(exe),release_sha256=expected,native_engine_build=False,clean_machine=False,updates_and_saves_verified=False),indent=2))
    print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]))

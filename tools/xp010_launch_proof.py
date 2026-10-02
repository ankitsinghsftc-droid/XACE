"""Same-host native launch proof; explicitly not a clean-machine certificate."""
from pathlib import Path
import json,os,subprocess,sys,time,queue,threading,socket,shutil,hashlib,ctypes
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/builder-workspace/server')]
from tools.xp008_player_proof import process_alive
from player_launch import PlayerLaunchService

def terminate(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(1,False,pid)
    if handle:
        kernel.TerminateProcess(ctypes.c_void_p(handle),1);kernel.CloseHandle(ctypes.c_void_p(handle))

def stopped(*pids):
    end=time.monotonic()+5
    while time.monotonic()<end and any(process_alive(pid) for pid in pids):time.sleep(.05)
    assert not any(process_alive(pid) for pid in pids),pids

class Native:
    def __init__(self,release,install,expected=None):
        self.release=release;trust=json.loads((release/'distribution.trust.json').read_text())
        env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
        for name in ['CARGO_HOME','RUSTUP_HOME','PYTHONPATH']:env.pop(name,None)
        self.p=subprocess.Popen([str(release/'XACE Play.exe'),'--source',str(release),'--expected',expected or trust['manifest_sha256'],'--install',str(install),'--serve','--headless-player'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        self.q=queue.Queue()
        def reader():
            for line in self.p.stdout:self.q.put(json.loads(line))
        threading.Thread(target=reader,daemon=True).start();self.hello=self.q.get(timeout=30);self.cap=self.hello.get('capability','')
    def request(self,action,**extra):
        self.p.stdin.write(json.dumps({'schema':'xace.player.broker_request.v1','capability':self.cap,'action':action,**extra})+'\n');self.p.stdin.flush();return self.q.get(timeout=25)
    def close(self):
        if self.p.stdin and not self.p.stdin.closed:self.p.stdin.close()
        self.p.wait(timeout=20)
        self.p.stdout.close()

def reseal(root):
    data=json.loads((root/'distribution.json').read_text())
    for item in data['files']:
        raw=(root/item['path']).read_bytes();item.update(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    raw=json.dumps(data,sort_keys=True,separators=(',',':')).encode();(root/'distribution.json').write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()

def run(release,out):
    release=Path(release).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True);install=out/'install';results={}
    sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(180)'],creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        n=Native(release,install)
        assert not n.request('play',capability='wrong')['ok']
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen();port=occupied.getsockname()[1]
            response=n.request('play',preferred_port=port);assert response['ok'],response
            first=response['result'];assert first['port']!=port
            repeat=n.request('play')['result'];assert repeat['player_pid']==first['player_pid']
            assert n.request('stop')['ok'];stopped(first['player_pid'],first['runtime_pid'])
        results.update(capability_rejected=True,port_collision_recovered=True,repeated_play_reused=True,startup_ms=first['startup_ms'],stop_tree_clean=True)
        live=n.request('play')['result'];n.close();stopped(live['player_pid'],live['runtime_pid']);results['eof_tree_clean']=True
        n=Native(release,install);live=n.request('play')['result'];n.p.kill();n.p.wait();stopped(live['player_pid'],live['runtime_pid']);n.close();results['broker_crash_tree_clean']=True
        n=Native(release,install);live=n.request('play')['result'];terminate(live['player_pid']);stopped(live['player_pid'],live['runtime_pid']);assert n.request('status')['result']['state']=='stopped';n.close();results['player_crash_tree_clean']=True
        before=(install/'active.json').read_bytes()
        broken=out/'broken-release';shutil.copytree(release,broken,dirs_exist_ok=True);(broken/'package/world.json').write_bytes(b'{}');expected=reseal(broken)
        n=Native(broken,install,expected);response=n.request('play');assert not response['ok'];n.close();assert (install/'active.json').read_bytes()==before;results['failed_launch_preserved_active']=True
        active=json.loads(before)['version_digest'];(install/'versions'/active/'xace-player.exe').write_bytes(b'stale')
        n=Native(release,install);live=n.request('play')['result'];n.request('stop');n.close();stopped(live['player_pid'],live['runtime_pid']);results['stale_install_repaired']=True
        denied=out/'denied';denied.mkdir(exist_ok=True);user=subprocess.check_output(['whoami'],text=True).strip()
        subprocess.run(['icacls',str(denied),'/deny',user+':(OI)(CI)(W)'],capture_output=True,check=True)
        try:
            n=Native(release,denied);assert n.hello.get('ok') is False;n.close();results['denied_install_rejected']=True
        finally:subprocess.run(['icacls',str(denied),'/remove:d',user],capture_output=True,check=True)
        n=Native(release,denied);live=n.request('play')['result'];n.request('stop');n.close();stopped(live['player_pid'],live['runtime_pid']);results['denied_install_retry_recovered']=True
        trust=json.loads((release/'distribution.trust.json').read_text());cgs=json.loads((release/'package/game.cgs.json').read_text())
        service=PlayerLaunchService(lambda:cgs,release=release,expected=trust['manifest_sha256'],broker_digest=trust['broker_sha256'],install=out/'builder-install',headless=True)
        try:
            live=service.control('play',cgs['metadata']['cgs_hash']);assert service.control('play',cgs['metadata']['cgs_hash'])['player_pid']==live['player_pid']
            cgs['metadata']['name']='Unsaved replacement'
            try:service.control('play',cgs['metadata']['cgs_hash']);raise AssertionError('stale project accepted')
            except ValueError:pass
            assert process_alive(live['player_pid']);service.control('stop');stopped(live['player_pid'],live['runtime_pid'])
        finally:service.close()
        results['builder_saved_project_and_owned_launch']=True
        assert sentinel.poll() is None;results['unowned_process_retained']=True
    finally:sentinel.terminate();sentinel.wait()
    result={'schema':'xace.xp010.launch_proof.v1','same_host_only':True,'clean_machine_certified':False,'development_tools_absent_from_child_path':True,'results':results}
    (out/'proof.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--release',required=True);p.add_argument('--out',default='tmp/xp010-proof');a=p.parse_args();print(json.dumps(run(a.release,a.out),indent=2))

"""Fresh native lifecycle/update reuse plus interrupted candidate admission."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec012_update_proof import main as update
from tools.nec012_lifecycle_proof import main as lifecycle,Host,sha

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec016') and not out.exists();out.mkdir(parents=True)
 updates=ROOT/'evidence/nec012'/('nec016-'+out.name+'-update');life=ROOT/'evidence/nec012'/('nec016-'+out.name+'-lifecycle')
 update(updates);lifecycle(life)
 active=updates/'user-data/XACE/NativeGames/game-nec012-proof/release-state/active.json';before=active.read_bytes()
 exe=updates/'xace-player-launcher.exe';candidate=updates/'release-b';host=Host(exe,candidate,sha(candidate/'native-release.json'),updates/'history')
 assert host.initial['state']=='stopped';host.p.kill();host.p.wait(timeout=10)
 host.p.stdin.close();host.p.stdout.close();host.p.stderr.close()
 assert active.read_bytes()==before,'Interrupted candidate changed active release'
 prior=updates/'release-a';host=Host(exe,prior,sha(prior/'native-release.json'),updates/'history')
 try:assert host.ask('play')['ok'];assert host.ask('stop')['ok']
 finally:host.close()
 assert active.read_bytes()==before
 proof=dict(ok=True,interrupted_before_readiness_preserves_active=True,old_release_still_launchable=True,update_proof=str(updates/'proof.json'),lifecycle_proof=str(life/'proof.json'),save_policy='exact compatibility admission; incompatible original preserved; automatic migration not implemented',automatic_migration=False)
 (out/'proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]))

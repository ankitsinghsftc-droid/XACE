"""Observe native map reload retiring old authority and starting a new owned session."""
from pathlib import Path
import json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec013_unity_player_proof import gone

def main(game,out):
 game=game.resolve();out=out.resolve();assert game.is_relative_to(ROOT/'evidence/nec015') and out.is_relative_to(ROOT/'evidence/nec015') and not out.exists()
 out.mkdir(parents=True);env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 cmd=[str(game/'NEC015.exe'),'-d3d11','-RenderOffscreen','-unattended','-XaceSceneReload',f'-XaceNativeReport={out/"player.json"}',f'-abslog={out/"engine.log"}']
 (out/'command.json').write_text(json.dumps(cmd),encoding='utf-8')
 with (out/'run.log').open('xb') as f:r=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=150,creationflags=subprocess.CREATE_NO_WINDOW)
 proof=json.loads((out/'player.json').read_text(encoding='utf-8-sig'))
 assert r.returncode==0 and proof['ok'] and proof['scene_transition_verified'] and proof['audio'] and proof['animation'],proof
 assert all(proof[k]>0 and gone(proof[k]) for k in ['owner_pid','runtime_pid','previous_owner_pid','previous_runtime_pid']),proof
 proof.update(old_and_new_owned_cleanup=True,seamless_state_continuity=False,clean_machine=False)
 (out/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

"""Fresh existing-native-node Godot Play proof, without reference Player scene."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.nec013_unity_player_proof import gone
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec014') and not out.exists()
 project=out/'project';project.mkdir(parents=True)
 for src in (ROOT/'adapters/godot').glob('*.gd'):shutil.copyfile(src,project/src.name)
 shutil.copyfile(ROOT/'tools/nec014_godot_play.gd',project/'proof.gd')
 (project/'project.godot').write_text('config_version=5\n[application]\nconfig/name="NEC014 Native Proof"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n',encoding='utf-8')
 release=project/'release';shutil.copytree(ROOT/'evidence/nec012/20261024/engine-claims-listener-final/Godot/release',release)
 shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',release/'xace-player-launcher.exe')
 world=json.loads((release/'package/world.json').read_bytes())
 profile=dict(schema='xace.godot.native_profile.v1',game_id='nec012-proof',release_directory='release',release_sha256=sha(release/'native-release.json'),launcher_sha256=sha(release/'xace-player-launcher.exe'),controller_id=1,objects={o['id']:['../Existing0','../Existing0/Existing1'][i] for i,o in enumerate(world['objects'])},input_bindings=[dict(action='move_x',kind='axis_1d',native_selector='proof.move')])
 (project/'profile.json').write_text(json.dumps(profile),encoding='utf-8')
 config=dict(release=str(release),profile='res://profile.json',report=str(out/'proof.json'));(out/'config.json').write_text(json.dumps(config),encoding='utf-8')
 exe='C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe'
 args=[exe,'--headless','--path',str(project),'--script','res://proof.gd','--',str(out/'config.json')]
 (out/'command.json').write_text(json.dumps(args,indent=2),encoding='utf-8');(out/'sources.json').write_text(json.dumps({p.name:sha(p) for p in project.glob('*.gd')},indent=2),encoding='utf-8')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 with (out/'run.log').open('wb') as log:r=subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,(out/'run.log').read_text(encoding='utf-8')
 proof=json.loads((out/'proof.json').read_text(encoding='utf-8'));proof['process_cleanup']=gone(proof['runtime_pid']) and gone(proof['owner_pid']);proof['ok'] &= proof['process_cleanup']
 (out/'proof-with-cleanup.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');assert proof['ok'],proof;print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]))

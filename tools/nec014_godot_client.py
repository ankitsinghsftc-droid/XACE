"""Create-only actual Godot inherited-pipe lifecycle proof."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec014') and not out.exists()
 project=out/'project';project.mkdir(parents=True)
 for src in [ROOT/'adapters/godot/xace_native_host_client.gd',ROOT/'tools/nec014_godot_client.gd']:shutil.copyfile(src,project/src.name)
 (project/'project.godot').write_text('config_version=5\n[application]\nconfig/name="NEC014 Client Proof"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n',encoding='utf-8')
 release=ROOT/'evidence/nec012/20261024/engine-claims-listener-final/Godot/release'
 launcher=ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe'
 config=dict(launcher=str(launcher),launcher_hash=sha(launcher),release=str(release),release_hash=sha(release/'native-release.json'),history=str(out/'history'),report=str(out/'proof.json'))
 (out/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
 exe=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
 args=[str(exe),'--headless','--path',str(project),'--script','res://nec014_godot_client.gd','--',str(out/'config.json')]
 (out/'command.json').write_text(json.dumps(args,indent=2),encoding='utf-8')
 (out/'sources.json').write_text(json.dumps({p.name:sha(p) for p in project.glob('*.gd')},indent=2),encoding='utf-8')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 with (out/'run.log').open('wb') as log:r=subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,(out/'run.log').read_text(encoding='utf-8')
 proof=json.loads((out/'proof.json').read_text(encoding='utf-8'));assert proof['ok'],proof;print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]))

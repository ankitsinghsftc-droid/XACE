"""Run two native PIE worlds using byte-pinned previously compiled fixture binaries."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out,build):
 out=out.resolve();build=build.resolve()
 assert out.is_relative_to(ROOT/'evidence/nec015') and not out.exists()
 assert build.is_relative_to(ROOT/'evidence/nec015')
 assert 'Result: Succeeded' in (build/'editor-build.log').read_text(encoding='utf-8')
 assert 'XaceTwoPIE' in (build/'project/Plugins/XACE/Source/XACEAdapter/Public/NEC015PIEProof.h').read_text(encoding='utf-8'),'Binary fixture does not implement two-world proof'
 expected=json.loads((build/'source-identities.json').read_text(encoding='utf-8'))
 changed={k:dict(before=v,after=sha(build/'project'/k)) for k,v in expected.items() if sha(build/'project'/k)!=v}
 assert all(k=='Config/DefaultEngine.ini' for k in changed),'Built source changed'
 # This fixture copies only Plugins and release, never source Config. UE may add Android tool settings during commandlets.
 assert all(not k.startswith(('Plugins/','release/')) for k in changed)
 project=out/'project';project.mkdir(parents=True)
 shutil.copytree(build/'project/Plugins',project/'Plugins',ignore=shutil.ignore_patterns('Intermediate','Saved'))
 shutil.copytree(build/'project/release',project/'release')
 descriptor=project/'NEC015.uproject';descriptor.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name='XACE',Enabled=True),dict(Name='AndroidFileServer',Enabled=False)])),encoding='utf-8')
 pins={p.relative_to(project).as_posix():sha(p) for p in project.rglob('*') if p.is_file()}
 (out/'reused-build.json').write_text(json.dumps(dict(build=str(build),built_source=expected,fixture_files=pins,not_reused_config_drift=changed),indent=2),encoding='utf-8')
 engine=Path('C:/Program Files/Epic Games/UE_5.7/Engine')
 cmd=[str(engine/'Binaries/Win64/UnrealEditor-Cmd.exe'),str(descriptor),'-unattended','-nocef','-d3d11','-nosplash','-RenderOffscreen','-XaceTwoPIE',f'-XacePIEReport={out/"proof.json"}',f'-abslog={out/"editor.log"}']
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 (out/'command.json').write_text(json.dumps(cmd),encoding='utf-8')
 with (out/'run.txt').open('xb') as f:r=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,'Two PIE test failed; evidence retained'
 proof=json.loads((out/'proof.json').read_text(encoding='utf-8-sig'));assert proof['ok'] and proof['two_instances'];print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

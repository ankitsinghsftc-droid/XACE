"""Real production discovery/enrollment/cold capture on a new independent fixture copy.
Test commandlet is fixture-only; no production plugin sources are changed.
"""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
EDITOR=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out,source):
 out=out.resolve();source=source.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source.is_relative_to(ROOT/'evidence/nec017')
 assert shutil.disk_usage(ROOT).free>8*1024**3,'Need8GiB for fresh proof build; no cleanup performed'
 manifest=json.loads((source/'pre-adoption-manifest.json').read_bytes());project=out/'project';project.mkdir(parents=True);(project/'.xace').mkdir()
 for name,expected in manifest['files'].items():
  original=source/'project'/name;assert sha(original)==expected
  dest=project/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
 plugin=project/'Plugins/XACEAuthoring';shutil.copytree(ROOT/'adapters/unreal/Authoring',plugin)
 pins={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'adapters/unreal/Authoring').rglob('*') if p.is_file()}
 for name,folder in [('NEC017ExistingCommandlet.h','Public'),('NEC017ExistingCommandlet.cpp','Private')]:
  p=ROOT/'tools'/name;pins[p.relative_to(ROOT).as_posix()]=sha(p);shutil.copyfile(p,plugin/'Source/XACEAuthoring'/folder/name)
 pins[Path(__file__).relative_to(ROOT).as_posix()]=sha(Path(__file__))
 (out/'source-pins.json').write_text(json.dumps(pins,indent=2))
 uproject=project/'NEC017Existing.uproject';config=json.loads(uproject.read_bytes());config['Plugins'].append(dict(Name='XACEAuthoring',Enabled=True));uproject.write_text(json.dumps(config,indent=2))
 (project/'NEC017.enroll-approved').write_text(sha(project/'Content/World.umap'))
 (out/'explicit-enrollment-review.json').write_text(json.dumps(dict(source=str(source),source_manifest_sha256=sha(source/'pre-adoption-manifest.json'),scope='New fixture copy, World map only',action='Enroll all discovered native identities through production Enroll API',gameplay_conversion=False),indent=2))
 engine=EDITOR.parents[2]
 command=[str(engine/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(engine/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'UnrealEditor','Win64','Development',f'-Project={uproject}',f'-plugin={plugin/"XACEAuthoring.uplugin"}','-nohotreload','-installed','-NoUBA','-MaxParallelActions=1','-NoUBTMakefiles',f'-log={out/"build-ubt.log"}']
 (out/'build-command.json').write_text(json.dumps(command,indent=2))
 with (out/'build.log').open('wb') as log:
  proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);started=time.monotonic()
  while proc.poll() is None:
   if shutil.disk_usage(ROOT).free<2*1024**3 or time.monotonic()-started>900:
    proc.terminate();raise RuntimeError('Build reserve/timeout reached; files retained')
   time.sleep(1)
 assert proc.returncode==0,'Build failed; retained logs'
 for phase in ['enroll','cold']:
  command=[str(EDITOR),str(uproject),'-run=NEC017Existing','-unattended','-nop4','-nosplash','-NullRHI','-nocef','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={out/(phase+"-editor.log")}']+(['-ColdReopen'] if phase=='cold' else [])
  (out/(phase+'-command.json')).write_text(json.dumps(command,indent=2))
  with (out/(phase+'.log')).open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
  assert r.returncode==0,'Native enrollment/capture failed; logs retained'
 a=(project/'.xace/existing-enrolled.json').read_bytes();b=(project/'.xace/existing-cold.json').read_bytes();assert a==b
 capture=json.loads(a);crates=[r for r in capture['objects'].values() if r['name'] in ['Crate'+str(i) for i in range(50)]];assert len(crates)==50
 for name,expected in manifest['files'].items():
  assert sha(source/'project'/name)==expected
  if name not in ['Content/World.umap','NEC017Existing.uproject']:assert sha(project/name)==expected,name
 assert all(sha(ROOT/name)==expected for name,expected in pins.items())
 (out/'proof.json').write_text(json.dumps(dict(ok=True,native_enrolled_objects=len(capture['objects']),selected_static_mesh_objects=50,original_preserved=True,other_scene_assets_preserved=True,cold_capture_identical=True,production_enrollment=True,fixture_only_wrapper=True,full_adoption_verified=False),indent=2));print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

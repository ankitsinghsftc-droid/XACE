"""Explicit static-authoring test migration in a new copy; original preserved."""
from pathlib import Path
import sys,json,hashlib,subprocess,shutil
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out,source):
 out=out.resolve();source=source.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source.is_relative_to(ROOT/'evidence/nec017');assert shutil.disk_usage(ROOT).free>4*1024**3
 manifest=json.loads((source/'pre-adoption-manifest.json').read_bytes());project=out/'project'
 for name,expected in manifest['files'].items():
  original=source/'project'/name;assert sha(original)==expected;dest=project/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
 shutil.copyfile(ROOT/'tools/nec017_unity_existing_disposition.cs',project/'Assets/Editor/NEC017StaticDisposition.cs')
 (project/'NEC017.static-copy-approved').write_text('Explicit NEC017 test copy; original preserved')
 (out/'explicit-fixture-review.json').write_text(json.dumps(dict(source=str(source),action='Remove BoxCollider from shared Crate prefab and three native-authority nodes from World COPY',changed_behavior='Native collision removed for prefab instances in both scenes; native audio/animation/counter nodes removed from World',automatic_conversion=False,original_preserved=True),indent=2))
 exe=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')
 for phase in ['Apply','Cold']:
  command=[str(exe),'-batchmode','-nographics','-projectPath',str(project),'-executeMethod','NEC017StaticDisposition.'+phase,'-logFile',str(out/(phase+'-editor.log'))]
  (out/(phase+'-command.json')).write_text(json.dumps(command,indent=2))
  with (out/(phase+'-process.log')).open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
  assert r.returncode==0,'Native disposition failed; original preserved; logs retained'
 report=json.loads((project/'disposition-cold.json').read_bytes());assert report['ok']
 allowed=['Assets/Game/World.unity','Assets/Game/Crate.prefab']
 for name,expected in manifest['files'].items():
  assert sha(source/'project'/name)==expected
  if name not in allowed:assert sha(project/name)==expected,name
 files={p.relative_to(project).as_posix():sha(p) for folder in ['Assets','Packages','ProjectSettings'] for p in (project/folder).rglob('*') if p.is_file()}
 (out/'pre-adoption-manifest.json').write_text(json.dumps(dict(files=files,fixture=manifest['fixture'],explicit_disposition=report,original_project=str(source)),indent=2))
 (out/'proof.json').write_text(json.dumps(dict(ok=True,original_preserved=True,native_documents_changed=allowed,cold_native_readback=report,adoption_verified=False,physics_preserved=False),indent=2));print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

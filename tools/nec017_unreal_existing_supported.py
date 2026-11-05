"""Make a new reviewed static-authoring test copy; retain the entire original."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
EDITOR=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out,source):
 out=out.resolve();source=source.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source.is_relative_to(ROOT/'evidence/nec017')
 manifest=json.loads((source/'pre-adoption-manifest.json').read_bytes());project=out/'project'
 for name,expected in manifest['files'].items():
  original=source/'project'/name;assert sha(original)==expected
  dest=project/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
 (out/'explicit-fixture-review.json').write_text(json.dumps(dict(source=str(source),action='Disable native collision on static fixture objects; remove SpawnMarker and UnsupportedCritical native-authority actors from World COPY only',preserve_original=True,preserve_assets=True,automatic_gameplay_conversion=False,physics_preserved=False),indent=2))
 script=ROOT/'tools/nec017_unreal_existing_disposition.py';shutil.copyfile(script,out/'native-disposition.py')
 command=[str(EDITOR),str(project/'NEC017Existing.uproject'),'-run=pythonscript',f'-script={out/"native-disposition.py"}','-unattended','-nop4','-nosplash','-NullRHI','-nocef','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={out/"editor.log"}']
 (out/'command.json').write_text(json.dumps(command,indent=2))
 with (out/'native.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,'Native test disposition failed; files retained'
 report=json.loads((project/'explicit-disposition.json').read_bytes());assert report['ok']
 cold=ROOT/'tools/nec017_unreal_existing_disposition_readback.py';shutil.copyfile(cold,out/'native-disposition-readback.py')
 cold_command=[v if not v.startswith('-script=') and not v.startswith('-abslog=') else ('-script='+str(out/'native-disposition-readback.py') if v.startswith('-script=') else '-abslog='+str(out/'cold-editor.log')) for v in command]
 (out/'cold-command.json').write_text(json.dumps(cold_command,indent=2))
 with (out/'cold.log').open('wb') as log:c=subprocess.run(cold_command,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
 assert c.returncode==0 and json.loads((project/'disposition-cold.json').read_bytes())['ok'],'Disposition did not survive native cold reopen'
 for name,expected in manifest['files'].items():
  assert sha(source/'project'/name)==expected
  if name!='Content/World.umap':assert sha(project/name)==expected,name
 files={name:sha(project/name) for name in manifest['files']}
 (out/'pre-adoption-manifest.json').write_text(json.dumps(dict(files=files,fixture=manifest['fixture'],explicit_disposition=report,original_project=str(source)),indent=2))
 (out/'proof.json').write_text(json.dumps(dict(ok=True,original_preserved=True,only_native_content_changed='Content/World.umap',native=report,automatic_gameplay_conversion=False,full_adoption_verified=False),indent=2));print('Explicit fixture disposition PASS; original preserved; not automatic physics/gameplay conversion')
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

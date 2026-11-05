"""Cold-open a copy, verifying all original native content bytes are preserved."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
EDITOR=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
def main(out,source):
 out=out.resolve();source=source.resolve()
 assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists()
 assert source.is_relative_to(ROOT/'evidence/nec017')
 manifest=json.loads((source/'pre-adoption-manifest.json').read_bytes());project=out/'project'
 for name,expected in manifest['files'].items():
  original=source/'project'/name;assert hashlib.sha256(original.read_bytes()).hexdigest()==expected
  dest=project/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
 assert 'Key=SpaceBar' in (project/'Config/DefaultInput.ini').read_text()
 script=ROOT/'tools/nec017_unreal_existing_readback.py';shutil.copyfile(script,out/'native-readback-script.py')
 command=[str(EDITOR),str(project/'NEC017Existing.uproject'),'-run=pythonscript',f'-script={out/"native-readback-script.py"}','-unattended','-nop4','-nosplash','-NullRHI','-nocef','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={out/"editor.log"}']
 (out/'command.json').write_text(json.dumps(command,indent=2))
 with (out/'native.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,'Cold readback failed; retained logs'
 report=json.loads((project/'cold-readback.json').read_bytes());assert report['ok']
 for base in [project,source/'project']:
  for name,expected in manifest['files'].items():assert hashlib.sha256((base/name).read_bytes()).hexdigest()==expected,name
 (out/'proof.json').write_text(json.dumps(dict(ok=True,native=report,original_preserved=True,cold_native_content_unchanged=True,physical_input_declaration=True,source=str(source),full_nec017_certification=False),indent=2))
 print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

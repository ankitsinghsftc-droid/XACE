"""Create-only native Godot export, using the developer main scene and approved preset."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(root):
 return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and not any(v in ['.godot','.git','XACEEvidence'] for v in p.relative_to(root).parts) and p.relative_to(root).as_posix()!='XACEApproval.json'}
def validate(project):
 approval=json.loads((project/'XACEApproval.json').read_text(encoding='utf-8'))
 assert approval['schema']=='xace.godot.source_approval.v1' and approval['files']==inventory(project),'Native source/resource approval stale'
 return approval

def export(project,out,godot):
 project=project.resolve();out=out.resolve();assert project.is_dir() and not out.exists() and not out.is_relative_to(project),'Fresh output outside project required'
 validate(project);out.mkdir(parents=True)
 receipt=dict(schema='xace.godot.native_export.v1',status='staging',approval_sha256=sha(project/'XACEApproval.json'),source=str(project),godot_sha256=sha(godot))
 (out/'staging.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
 try:
  profile=json.loads((project/'xace-native-profile.json').read_text(encoding='utf-8'))
  relative=Path(profile['release_directory']);assert not relative.is_absolute() and '..' not in relative.parts
  source=project/relative
  assert sha(source/'native-release.json')==profile['release_sha256'] and sha(source/'xace-player-launcher.exe')==profile['launcher_sha256']
  shipping=out/'shipping';shipping.mkdir()
  command=[str(godot),'--headless','--path',str(project),'--export-release','Windows Desktop',str(shipping/'NativeGame.exe')]
  (out/'command.json').write_text(json.dumps(command,indent=2),encoding='utf-8')
  with (out/'export.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
  assert r.returncode==0 and all(marker not in (out/'export.log').read_text(encoding='utf-8') for marker in ['SCRIPT ERROR','[XACE] Export refused:']), 'Godot export failed; retained log'
  validate(project)
  target=shipping/relative;target.mkdir(parents=True)
  native=json.loads((source/'native-release.json').read_text(encoding='utf-8'));manifest=json.loads((source/'package/playable.manifest.json').read_text(encoding='utf-8'))
  paths=['native-release.json','executor-receipt.json','xace-player-launcher.exe','package/playable.manifest.json']+['package/'+row['path'] for row in manifest['files']]+[row['path'] for row in native['resources']]
  for name in sorted(set(paths)):
   src=(source/name).resolve();dst=(target/name).resolve();assert src.is_relative_to(source.resolve()) and dst.is_relative_to(target.resolve())
   dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
  args=[str(target/'xace-player-launcher.exe'),'--native-host','--source',str(target),'--expected',profile['release_sha256'],'--history',str(out/'admission-history'),'--controller',str(profile['controller_id'])]
  admitted=subprocess.run(args,input='',capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
  assert admitted.returncode==0 and json.loads(admitted.stdout.splitlines()[0])['state']=='stopped','Cooked native package refused'
  receipt.update(status='built-not-certified',release_sha256=profile['release_sha256'],launcher_sha256=profile['launcher_sha256'],files={p.relative_to(shipping).as_posix():sha(p) for p in sorted(shipping.rglob('*')) if p.is_file()},clean_machine=False)
 except Exception as error:
  receipt.update(status='failed',error=str(error));raise
 finally:
  (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
 return receipt
if __name__=='__main__':print(json.dumps(export(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))))

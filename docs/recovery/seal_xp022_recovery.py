"""Create a new recovery-only technical baseline; never modify an existing seal."""
from pathlib import Path
import hashlib,json,shutil,subprocess,zipfile,datetime
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'recovery-evidence/20261015/xp022-ingress-batch'
COMPACT=ROOT/'docs/recovery/evidence/xp022-closeout-20261015'
OUT=Path('C:/Users/ankit/XACE-Recovery/baselines/xp022-recovered-20261015')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
assert not OUT.exists(),'Never replace a baseline'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip(),'Checkpoint all changes before sealing'
assert load(BASE/'background-run/final-result.json')['status']=='passed'
assert load(BASE/'evidence-writer-regression/summary.json')['ok']
assert load(COMPACT/'packaging-verification.json')['ok']
for gate in ['sockets','process-faults','hosts','replay-faults','debugger','player-input','presentation','launch','invite','relay','smoke']:
 assert load(BASE/'gate-logs'/f'{gate}.json')['passed'],gate
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
assert not subprocess.check_output(['git','diff','--name-only','dd2741c','HEAD','--','packages','examples','Cargo.toml','Cargo.lock'],cwd=ROOT).strip()
OUT.mkdir(parents=True,exist_ok=False)
files=[]
names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
with zipfile.ZipFile(OUT/'source.zip','x',zipfile.ZIP_DEFLATED) as z:
 for name in sorted(filter(None,names)):
  p=ROOT/name
  assert p.is_file() and not p.is_symlink(),name
  z.write(p,name);files.append(dict(path=name,sha256=sha(p),bytes=p.stat().st_size))
(OUT/'source-manifest.json').write_text(json.dumps(dict(source_checkpoint=revision,files=files),indent=2))
shutil.copy2(BASE/'release.zip',OUT/'unsigned-release.zip')
for name in ['xace_reference_host.exe','xace-player-launcher.exe','xace-session-relay.exe']:shutil.copy2(BASE/'pinned-binaries'/name,OUT/name)
native=ROOT/'recovery-evidence/ue022/target-codex-task66-unreal-vertical-slice/Plugins/XACE/Binaries/Win64/UnrealEditor-XACEAdapter.dll'
shutil.copy2(native,OUT/'UnrealEditor-XACEAdapter-proof.dll')
reports=[]
for folder in [COMPACT,ROOT/'docs/recovery/evidence/xp022-ingress-batch-20261015']:
 for p in sorted(folder.rglob('*')):
  if not p.is_file():continue
  relative=p.relative_to(ROOT/'docs/recovery/evidence');dest=OUT/'reports'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
  reports.append(dict(path=dest.relative_to(OUT).as_posix(),source=str(p),sha256=sha(dest)))
manifest=dict(schema='xace.recovery_baseline.v1',source_checkpoint=revision,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),original_seal=False,local_engineering_gates='passed',external_release_gates='OPEN: REL01-REL05',off_device_backup=False,host_sha256=sha(OUT/'xace_reference_host.exe'),reports=reports,files=[])
for p in sorted(OUT.rglob('*')):
 if p.is_file():manifest['files'].append(dict(path=p.relative_to(OUT).as_posix(),sha256=sha(p),bytes=p.stat().st_size))
with (OUT/'baseline.json').open('x') as f:json.dump(manifest,f,indent=2)
# Read back every sealed byte and every archived source entry.
for r in manifest['files']:assert sha(OUT/r['path'])==r['sha256']
with zipfile.ZipFile(OUT/'source.zip') as z:
 assert len(z.namelist())==len(files)
 for r in files:assert hashlib.sha256(z.read(r['path'])).hexdigest()==r['sha256']
print(json.dumps(dict(baseline=str(OUT/'baseline.json'),sha256=sha(OUT/'baseline.json'),source_checkpoint=revision,files=len(manifest['files']),source_files=len(files))))

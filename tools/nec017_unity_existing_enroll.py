"""Explicit metadata enrollment in a copy of the native Unity fixture."""
from pathlib import Path
import sys,json,shutil,hashlib,subprocess
ROOT=Path(__file__).resolve().parents[1];out=Path(sys.argv[1]).resolve();source=Path(sys.argv[2]).resolve()
assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source.is_relative_to(ROOT/'evidence/nec017');assert shutil.disk_usage(ROOT).free>6*1024**3
manifest=json.loads((source/'pre-adoption-manifest.json').read_bytes());project=out/'project';project.mkdir(parents=True)
for name,expected in manifest['files'].items():
 src=source/'project'/name;assert hashlib.sha256(src.read_bytes()).hexdigest()==expected
 dest=project/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
shutil.copytree(ROOT/'adapters/unity/Authoring',project/'Assets/XaceAuthoring');shutil.copyfile(ROOT/'tools/nec017_unity_existing_enroll.cs',project/'Assets/XaceAuthoring/Editor/NEC017ExistingEnrollment.cs')
(out/'explicit-fixture-review.json').write_text(json.dumps(dict(source=str(source),source_files=manifest['files'],action='Explicit identity metadata enrollment; preserve native behavior and do not publish CGS'),indent=2))
exe=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe');command=[str(exe),'-batchmode','-nographics','-projectPath',str(project),'-executeMethod',('Xace.Authoring.Editor.NEC017ColliderProfile.Run' if '--collider-only' in sys.argv else 'Xace.Authoring.Editor.NEC017ExistingEnrollment.Run'),'-logFile',str(out/'editor.log')]
(out/'command.json').write_text(json.dumps(command))
with (out/'process.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
assert r.returncode==0,'Native enrollment failed; logs retained'
proof=json.loads((project/'existing-enrollment.json').read_bytes());assert proof['ok']
for name,expected in manifest['files'].items():assert hashlib.sha256((source/'project'/name).read_bytes()).hexdigest()==expected
(out/'proof.json').write_text(json.dumps(dict(ok=True,enrolled_objects=len(proof['objects']),original_unchanged=True,adoption_verified=False),indent=2));print((out/'proof.json').read_text(),flush=True)

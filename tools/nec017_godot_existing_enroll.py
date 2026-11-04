"""Discover and explicitly enroll a copy of the independent native fixture."""
from pathlib import Path
import sys,shutil,json,hashlib,subprocess
ROOT=Path(__file__).resolve().parents[1]
out=Path(sys.argv[1]).resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists()
source=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else ROOT/'evidence/nec017/20261030/godot-existing-seed-a';assert source.is_relative_to(ROOT/'evidence/nec017');manifest=json.loads((source/'pre-adoption-manifest.json').read_bytes());project=out/'project';project.mkdir(parents=True)
for name,expected in manifest['files'].items():
 p=source/'project'/name;assert hashlib.sha256(p.read_bytes()).hexdigest()==expected
 target=project/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
addon=project/'addons/xace_authoring';shutil.copytree(ROOT/'adapters/godot/authoring',addon);shutil.copyfile(ROOT/'adapters/godot/xace_protocol.gd',project/'xace_protocol.gd');shutil.copyfile(ROOT/'tools/nec017_godot_existing_enroll.gd',addon/'existing_enroll.gd')
p=addon/'plugin.cfg';p.write_text(p.read_text().replace('script="authoring_plugin.gd"','script="existing_enroll.gd"'))
with (project/'project.godot').open('a') as f:f.write('\n[editor_plugins]\nenabled=PackedStringArray("res://addons/xace_authoring/plugin.cfg")\n')
command=['C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe','--headless','--editor','--path',str(project)]
(out/'command.json').write_text(json.dumps(command,indent=2))
with (out/'enroll.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
assert r.returncode==0,'Native enrollment failed; retained logs'
proof=json.loads((project/'existing-enrollment.json').read_bytes());assert proof['ok']
for name,expected in manifest['files'].items():assert hashlib.sha256((source/'project'/name).read_bytes()).hexdigest()==expected
(out/'proof.json').write_text(json.dumps(dict(ok=True,phase='discovery and explicit enrollment only',enrollment=proof,original_fixture_preserved=True,adoption_verified=False),indent=2));print(json.dumps(dict(ok=True,enrolled_objects=len(proof['objects']),adoption_verified=False)))

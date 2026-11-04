"""Explicit reviewed migration of a new COPY of the original test fixture.
Retains original files and records the exact native authority removed. This is
not automatic script conversion or a full adoption/Play/build certification.
"""
from pathlib import Path
import sys,json,hashlib,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
out=Path(sys.argv[1]).resolve();source=Path(sys.argv[2]).resolve()
assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists()
assert source.is_relative_to(ROOT/'evidence/nec017')
manifest=json.loads((source/'pre-adoption-manifest.json').read_bytes())
project=out/'project';project.mkdir(parents=True)
for name,expected in manifest['files'].items():
 original=source/'project'/name;assert hashlib.sha256(original.read_bytes()).hexdigest()==expected
 dest=project/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
review=dict(scope='Original NEC017 test content only; copied destination',source=str(source),source_files=manifest['files'],changes=[dict(document='Game/World.tscn',node=n,action='remove_native_authority') for n in ['NativeAudio','NativeAnimation','UnsupportedCriticalScore']],preserve_native_files=True,automatic_gameplay_conversion=False)
(out/'explicit-fixture-review.json').write_text(json.dumps(review,indent=2))
script=ROOT/'tools/nec017_godot_existing_disposition.gd';shutil.copyfile(script,project/'prepare_supported.gd')
command=['C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe','--headless','--path',str(project),'--script','res://prepare_supported.gd']
(out/'command.json').write_text(json.dumps(command))
with (out/'native.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
assert r.returncode==0
report=json.loads((project/'explicit-disposition.json').read_bytes());assert report['ok']
assert report['before']==manifest['files']['Game/World.tscn'] and report['before']!=report['after']
for name,expected in manifest['files'].items():
 assert hashlib.sha256((source/'project'/name).read_bytes()).hexdigest()==expected
 if name!='Game/World.tscn':assert hashlib.sha256((project/name).read_bytes()).hexdigest()==expected,name
files={p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob('*') if p.is_file() and '.godot' not in p.parts}
(out/'pre-adoption-manifest.json').write_text(json.dumps(dict(files=files,fixture=manifest['fixture'],explicit_disposition=report,original_project=str(source)),indent=2))
(out/'proof.json').write_text(json.dumps(dict(ok=True,original_unchanged=True,only_original_document_changed='Game/World.tscn',review=review,native=report,full_adoption_verified=False),indent=2))
print(json.dumps(dict(ok=True,original_preserved=True,full_adoption_verified=False)))

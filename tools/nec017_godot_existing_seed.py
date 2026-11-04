"""Create-only independently authored native Godot project before enrollment."""
from pathlib import Path
import sys,shutil,subprocess,json,hashlib
ROOT=Path(__file__).resolve().parents[1];out=Path(sys.argv[1]).resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();project=out/'project';project.mkdir(parents=True)
(project/'project.godot').write_text('config_version=5\n[application]\nconfig/name="Independent Native Warehouse"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
shutil.copyfile(ROOT/'tools/nec017_godot_existing_fixture.gd',project/'create_fixture.gd')
command=['C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe','--headless','--path',str(project),'--script','res://create_fixture.gd','--','--surface-material']
(out/'command.json').write_text(json.dumps(command))
with (out/'create.log').open('wb') as f:r=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
assert r.returncode==0,'Native fixture creation failed; retained log'
proof=json.loads((project/'fixture-created.json').read_bytes());assert proof['ok'] and proof['authored_crate_instances']==50 and proof['surface_material']
files={p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob('*') if p.is_file() and '.godot' not in p.parts}
(out/'pre-adoption-manifest.json').write_text(json.dumps(dict(files=files,fixture=proof),indent=2));print(json.dumps(proof))

"""Fresh installed-Godot playback probe, retained outside disposable paths."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    project=out/'project';project.mkdir(parents=True)
    sources={}
    for src in sorted((ROOT/'adapters/godot').glob('*.gd')):
        shutil.copyfile(src,project/src.name);sources[src.relative_to(ROOT).as_posix()]=hashlib.sha256(src.read_bytes()).hexdigest()
    shutil.copyfile(ROOT/'adapters/tests/fixtures/xp016-contract-v1.json',project/'session-fixture.json')
    probe=ROOT/'tools/nec011_godot_fidelity.gd';shutil.copyfile(probe,project/'proof.gd');sources[probe.relative_to(ROOT).as_posix()]=hashlib.sha256(probe.read_bytes()).hexdigest()
    (project/'project.godot').write_text('config_version=5\n[application]\nconfig/name="NEC011 Fidelity Proof"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    exe=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
    command=[str(exe),'--headless','--path',str(project),'--script','res://proof.gd','--',str(out/'proof.json')]
    (out/'sources.json').write_text(json.dumps(sources,indent=2));(out/'command.json').write_text(json.dumps(command,indent=2))
    with (out/'run.txt').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
    assert r.returncode==0,(out/'run.txt').read_text()
    report=json.loads((out/'proof.json').read_text());assert report['ok'],report
    print(json.dumps(report,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]).resolve())

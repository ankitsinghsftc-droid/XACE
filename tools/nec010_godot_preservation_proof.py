from pathlib import Path
import json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec010') and not out.exists();out.mkdir(parents=True)
    project=out/'godot-project';addon=project/'addons/xace_authoring';addon.mkdir(parents=True)
    shutil.copytree(ROOT/'recovery-evidence/20261016/nec005/native-final/godot-project/Fixture',project/'Fixture')
    for p in (ROOT/'adapters/godot/authoring').iterdir():
        if p.is_file():shutil.copy2(p,addon/p.name)
    shutil.copy2(ROOT/'tools/nec010_godot_preservation_probe.gd',addon/'preservation_probe.gd')
    p=addon/'plugin.cfg';p.write_text(p.read_text().replace('authoring_plugin.gd','preservation_probe.gd'))
    shutil.copy2(ROOT/'evidence/nec010/20261016/godot-semantic-b/godot-project/project.godot',project/'project.godot')
    cmd=['C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe','--headless','--editor','--path',str(project),'--quit-after','600']
    (out/'command.json').write_text(json.dumps(cmd));r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW);(out/'editor.log').write_bytes(r.stdout)
    assert r.returncode==0 and b'SCRIPT ERROR:' not in r.stdout,r.stdout[-4000:]
    proof=json.loads((project/'preservation-proof.json').read_text());assert proof['ok'],proof
    shutil.copy2(project/'preservation-proof.json',out/'proof.json');print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]).resolve())

"""Fresh Unity hierarchy fixture; production reviewed round-trip and monitor proof."""
import json,shutil,subprocess,sys
from pathlib import Path
from nec011_godot_hierarchy import ROOT,sha,NativeEditorGateway,roundtrip

def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    root=out/'project';(root/'Assets/Editor').mkdir(parents=True)
    addon='Assets/XaceAuthoring';shutil.copytree(ROOT/'adapters/unity/Authoring',root/addon,ignore=shutil.ignore_patterns('*Proof*'))
    shutil.copyfile(ROOT/'tools/NEC011UnityHierarchy.cs',root/'Assets/Editor/NEC011UnityHierarchy.cs')
    (root/'Packages').mkdir();(root/'Packages/manifest.json').write_text(json.dumps(dict(dependencies={'com.unity.modules.jsonserialize':'1.0.0','com.unity.modules.physics':'1.0.0','com.unity.modules.animation':'1.0.0','com.unity.modules.audio':'1.0.0'})))
    (root/'ProjectSettings').mkdir();(root/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.9f1\n')
    exe=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')
    command=[str(exe),'-batchmode','-quit','-projectPath',str(root),'-executeMethod','NEC011UnityHierarchy.Run','-logFile',str(out/'fixture.log')]
    (out/'command.json').write_text(json.dumps(command,indent=2))
    with (out/'fixture-run.txt').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
    assert r.returncode==0,'Unity fixture failed; logs retained'
    pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/addon).rglob('*') if p.is_file() and p.suffix!='.meta'}
    (out/'sources.json').write_text(json.dumps(pins,indent=2))
    gateway=NativeEditorGateway(root,engine='unity',executable=str(exe),executable_sha256=sha(exe.read_bytes()),documents=['Assets/Fixture/World.unity'],source_roots=['Assets','Packages','ProjectSettings'],plugin_hashes=pins,trusted_closed_project=True)
    roundtrip(out,root,gateway,'unity','Assets/Fixture/World.unity')
if __name__=='__main__':main(Path(sys.argv[1]).resolve())

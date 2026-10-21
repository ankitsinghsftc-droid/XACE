import hashlib,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    project=out/'project';(project/'Assets/XACE/Editor').mkdir(parents=True)
    sources={}
    for src in sorted((ROOT/'adapters/unity').glob('*.cs')):
        shutil.copyfile(src,project/'Assets/XACE'/src.name);sources[src.relative_to(ROOT).as_posix()]=hashlib.sha256(src.read_bytes()).hexdigest()
    src=ROOT/'tools/NEC011UnityFidelity.cs';shutil.copyfile(src,project/'Assets/XACE/Editor'/src.name);sources[src.relative_to(ROOT).as_posix()]=hashlib.sha256(src.read_bytes()).hexdigest()
    (project/'Packages').mkdir();(project/'Packages/manifest.json').write_text(json.dumps({'dependencies':{'com.unity.modules.particlesystem':'1.0.0','com.unity.modules.physics':'1.0.0','com.unity.modules.audio':'1.0.0','com.unity.modules.animation':'1.0.0','com.unity.modules.jsonserialize':'1.0.0','com.unity.modules.ui':'1.0.0','com.unity.modules.imgui':'1.0.0'}}))
    (project/'ProjectSettings').mkdir();(project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.9f1\n')
    command=['C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe','-batchmode','-projectPath',str(project),'-executeMethod','NEC011UnityFidelity.Run','-xaceReport',str(out/'proof.json'),'-logFile',str(out/'editor.log')]
    (out/'sources.json').write_text(json.dumps(sources,indent=2));(out/'command.json').write_text(json.dumps(command,indent=2))
    with (out/'run.txt').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
    assert r.returncode==0,'Native probe failed: '+str(out/'editor.log')
    report=json.loads((out/'proof.json').read_text());assert report['ok'],report
    print(json.dumps(report,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]).resolve())

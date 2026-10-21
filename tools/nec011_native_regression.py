"""Run existing native contract proofs in new persistent, create-only fixtures."""
import json,shutil,subprocess,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main(out,engine):
    assert engine in ['godot','unity'] and out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    project=out/'project';project.mkdir(parents=True);sources={}
    fixture=ROOT/'adapters/tests/fixtures/xp016-contract-v1.json'
    if engine=='godot':
        for src in (ROOT/'adapters/godot').glob('*.gd'):shutil.copyfile(src,project/src.name)
        (project/'tests').mkdir();shutil.copyfile(ROOT/'adapters/godot/tests/native_contract_proof.gd',project/'tests/native_contract_proof.gd')
        (project/'project.godot').write_text('config_version=5\n')
        command=['C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe','--headless','--path',str(project),'--script','res://tests/native_contract_proof.gd','--',f'--fixture={fixture}',f'--report={out/"proof.json"}']
    else:
        (project/'Assets/XACE/Editor').mkdir(parents=True)
        for src in (ROOT/'adapters/unity').glob('*.cs'):shutil.copyfile(src,project/'Assets/XACE'/src.name)
        shutil.copyfile(ROOT/'adapters/unity/Editor/XaceNativeContractProof.cs',project/'Assets/XACE/Editor/XaceNativeContractProof.cs')
        (project/'Packages').mkdir();(project/'Packages/manifest.json').write_text(json.dumps(dict(dependencies={'com.unity.modules.particlesystem':'1.0.0','com.unity.modules.physics':'1.0.0','com.unity.modules.audio':'1.0.0','com.unity.modules.animation':'1.0.0','com.unity.modules.jsonserialize':'1.0.0','com.unity.modules.ui':'1.0.0','com.unity.modules.imgui':'1.0.0'})))
        (project/'ProjectSettings').mkdir();(project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.9f1\n')
        command=['C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe','-batchmode','-nographics','-quit','-projectPath',str(project),'-executeMethod','Xace.Adapter.Unity.Editor.XaceNativeContractProof.Run','-xaceFixture',str(fixture),'-xaceReport',str(out/'proof.json'),'-logFile',str(out/'editor.log')]
    sources={p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob('*') if p.is_file()}
    (out/'sources.json').write_text(json.dumps(sources,indent=2));(out/'command.json').write_text(json.dumps(command,indent=2))
    with (out/'run.txt').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
    assert r.returncode==0,'native proof failed; retained logs'
    result=json.loads((out/'proof.json').read_text(encoding='utf-8-sig'));assert result['ok'],result;print(json.dumps(result,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),sys.argv[2])

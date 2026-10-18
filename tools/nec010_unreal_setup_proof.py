"""Verify CGS-driven Unreal setup through the production native commandlet."""
import json,sys,shutil,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from authoring_identity import canonical
from native_setup_plan import plan_setup,verify_setup
EDITOR=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
def main(out,compiled):
    assert out.is_relative_to(ROOT/'evidence/nec010/ue') and not out.exists()
    assert compiled.is_relative_to(ROOT/'evidence/nec010/ue')
    project=out/'unreal-project';project.mkdir(parents=True);(project/'.xace').mkdir();(project/'Config').mkdir()
    shutil.copytree(compiled/'unreal-project/Plugins',project/'Plugins',ignore=shutil.ignore_patterns('Intermediate'))
    (project/'XACESetup.uproject').write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name='XACEAuthoring',Enabled=True)])))
    (project/'Config/DefaultEngine.ini').write_text('[/Script/Engine.RendererSettings]\nr.RayTracing=False\nr.AllowStaticLighting=False\n')
    cgs=json.loads((ROOT/'recovery-evidence/20261016/nec007/native-runtime/unreal/plan.json').read_text())['proposed_cgs']
    plan=plan_setup(cgs,engine='unreal',namespace_id='a'*32,project_id='native-setup-proof',branch_id='b'*32,mode_id=cgs['modes'][0]['id']);spec=plan.to_dict()['native_request']
    (out/'setup-plan.json').write_bytes(plan.payload);(out/'source.cgs.json').write_bytes(canonical(cgs))
    journal=project/'.xace';(journal/'spec.json').write_bytes(canonical(spec));(journal/'native-setup-approved.json').write_bytes(canonical(dict(digest=hashlib.sha256(canonical(spec)).hexdigest(),stage_root=project.as_posix())))
    for phase in ['create','reload']:
        command=[str(EDITOR),str(project/'XACESetup.uproject'),'-run=XaceNativeSetup','-unattended','-nop4','-nosplash','-NullRHI','-NoSound','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={out/(phase+"-editor.log")}']+(['-ColdReopen'] if phase=='reload' else [])
        (out/(phase+'-command.json')).write_text(json.dumps(command,indent=2))
        with (out/(phase+'.log')).open('wb') as f:r=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
        result=json.loads((journal/('result-'+phase+'.json')).read_text());assert r.returncode==0,result
        data=canonical(result['result']['inventory']);verify_setup(plan,cgs,data)
        if phase=='create':before=data
        else:assert before==data and result['result']['existing_refused'] and result['result']['unchanged']
        (out/(phase+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    (out/'proof.json').write_text(json.dumps(dict(ok=True,real_editor=True,created_native_binary_map=True,cold_capture_identical=True,existing_content_preserved=True,exact_transform=True),indent=2)+'\n');print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())

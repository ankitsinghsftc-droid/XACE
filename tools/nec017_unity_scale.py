"""NEC017 actual installed Unity 1,000-object setup and reopen proof."""
import json,sys,shutil,subprocess,hashlib,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from authoring_identity import canonical
from unity_authoring import prepare_identity_map,capture
UNITY=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')
DRIVER='''using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
namespace Xace.Authoring.Editor {
public static class NativeSetupProof {
public static void Run() {
try {
var spec=AuthoringJson.Obj(AuthoringJson.Parse(File.ReadAllText(".xace/spec.json")));
var digest=AuthoringJson.Hash(AuthoringJson.Encode(spec));
bool reload=Environment.GetCommandLineArgs().Contains("-coldReopen");
object result;
if(!reload)result=UnityNativeSetup.Create(spec,digest);
else {
EditorSceneManager.OpenScene(UnityNativeSetup.ScenePath);
var inventory=UnityAuthoringReader.Capture(new AuthoringScope(new[]{UnityNativeSetup.ScenePath}));
var before=AuthoringJson.Hash(File.ReadAllBytes(UnityNativeSetup.ScenePath));bool refused=false;
try{UnityNativeSetup.Create(spec,digest);}catch(InvalidDataException){refused=true;}
result=UnityAuthoringReader.Map("inventory",inventory,"existing_refused",refused,"unchanged",before==AuthoringJson.Hash(File.ReadAllBytes(UnityNativeSetup.ScenePath)));
}
File.WriteAllText(".xace/result-"+(reload?"reload":"create")+".json",AuthoringJson.Encode(result));EditorApplication.Exit(0);
}catch(Exception e){UnityEngine.Debug.LogException(e);EditorApplication.Exit(1);}
}
}}
'''
def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists()
    project=out/'unity-project';addon=project/'Assets/XaceAuthoring';shutil.copytree(ROOT/'adapters/unity/Authoring',addon)
    (addon/'Editor/NativeSetupProof.cs').write_text(DRIVER)
    for name in ['Packages','ProjectSettings','.xace']:(project/name).mkdir()
    (project/'Packages/manifest.json').write_text(json.dumps({'dependencies':{'com.unity.modules.physics':'1.0.0','com.unity.modules.audio':'1.0.0','com.unity.modules.animation':'1.0.0','com.unity.modules.jsonserialize':'1.0.0'}}))
    (project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.9f1\n')
    from native_setup_plan import plan_setup,verify_setup
    if shutil.disk_usage(out).free<6*1024**3:raise RuntimeError('Insufficient creator build disk reserve')
    sys.path.insert(0,str(ROOT/'packages/project-system/tests'))
    from test_native_scale import scaled
    from test_native_adoption import plan as adoption_plan
    data,mapping,initial,selected,choices=scaled('unity',1000)
    cgs=adoption_plan(data,mapping,initial,selected,choices).to_dict()['proposed_cgs']
    timings={};env=dict(os.environ)
    plan=plan_setup(cgs,engine='unity',namespace_id='a'*32,project_id='native-setup-proof',branch_id='b'*32,mode_id=cgs['modes'][0]['id'])
    spec=plan.to_dict()['native_request']
    (out/'setup-plan.json').write_bytes(plan.payload);(out/'source.cgs.json').write_bytes(canonical(cgs))
    journal=project/'.xace';(journal/'spec.json').write_bytes(canonical(spec));(journal/'native-setup-approved.json').write_bytes(canonical(dict(digest=hashlib.sha256(canonical(spec)).hexdigest(),stage_root=str(project))))
    for phase in ['create','reload']:
        command=[str(UNITY),'-batchmode','-nographics','-projectPath',str(project),'-executeMethod','Xace.Authoring.Editor.NativeSetupProof.Run','-logFile',str(out/(phase+'-editor.log'))]+(['-coldReopen'] if phase=='reload' else [])
        (out/(phase+'-command.json')).write_text(json.dumps(command,indent=2))
        started=time.perf_counter()
        with (out/(phase+'.log')).open('wb') as f:r=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
        timings[phase]=time.perf_counter()-started
        assert r.returncode==0,(phase,r.returncode)
        result=json.loads((journal/('result-'+phase+'.json')).read_text());data=canonical(result['inventory'])
        verified_mapping,verified_rows=verify_setup(plan,cgs,data)
        assert len([r for r in verified_mapping.objects.values() if r.world_binding])==1000 and verified_rows
        if phase=='create':before=data
        else:assert before==data and result['existing_refused'] and result['unchanged']
        (out/(phase+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    (out/'proof.json').write_text(json.dumps(dict(ok=True,objects=1000,timings_seconds=timings,full_nec017_certification=False,real_editor=True,created_native_scene=True,cold_capture_identical=True,existing_content_preserved=True,exact_transform=True),indent=2)+'\n');print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]).resolve())

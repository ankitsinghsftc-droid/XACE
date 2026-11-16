"""Fresh copy: explicit binding of existing Unity objects, real Play and native build."""
from pathlib import Path
import json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from tools.nec013_unity_player_proof import inventory,gone
from tools.nec014_export import sha
import playable_package as pp
from native_executor_contract import admit,digest
UNITY='C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe'
SETUP=r'''    public static void Setup()
    {
        PlayerSettings.SetScriptingBackend(UnityEditor.Build.NamedBuildTarget.Standalone,ScriptingImplementation.Mono2x);
        PlayerSettings.runInBackground=true;
        string release=Path.Combine(Application.streamingAssetsPath,"XACERelease");
        var world=XaceCanonical.Parse(File.ReadAllText(Path.Combine(release,"package/world.json")));
        var objects=(List<object>)world["objects"];
        var scene=EditorSceneManager.OpenScene("Assets/Game/World.unity",OpenSceneMode.Single);
        var byId=new Dictionary<string,GameObject>();
        foreach(var identity in UnityEngine.Object.FindObjectsByType<Xace.Authoring.XaceAuthoringIdentity>(FindObjectsInactive.Include,FindObjectsSortMode.None))
            byId.Add("native_"+identity.NamespaceId+"_"+identity.AuthoringId,identity.gameObject);
        foreach(var value in objects){var item=XaceCanonical.Object(value);string id=XaceCanonical.Text(item,"id");if(!byId.TryGetValue(id,out var go))throw new Exception("Original object absent: "+id);if(go.GetComponent<XaceNativeSceneBinding>()!=null)throw new Exception("Unexpected existing runtime binding");go.AddComponent<XaceNativeSceneBinding>().worldObjectId=id;}
        Directory.CreateDirectory("Assets/Resources");
        var profile=ScriptableObject.CreateInstance<XaceNativeHostProfile>();profile.gameId="nec017-existing-unity";profile.inputBindings=new[]{new XaceLiveInputBinding{action="move_x",kind="axis_1d",nativeSelector="proof.move"}};profile.releaseSha256=XaceNativeHostClient.FileHash(Path.Combine(release,"native-release.json"));profile.launcherSha256=XaceNativeHostClient.FileHash(Path.Combine(release,"xace-player-launcher.exe"));
        AssetDatabase.CreateAsset(profile,"Assets/Resources/XaceNativeHost.asset");AssetDatabase.SaveAssets();EditorSceneManager.MarkSceneDirty(scene);if(!EditorSceneManager.SaveScene(scene))throw new Exception("Save failed");AssetDatabase.Refresh();
        EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene("Assets/Game/World.unity",true)};
        XaceNativeBuild.RecordApproval();
    }
'''
BUILD=r'''using System;
using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using Xace.Adapter.Unity;
public static class NEC017ExistingBuild {
 [Serializable]public sealed class Outcome{public bool ok=true;public bool clean_machine=false;}
 static string Arg(string name){var args=Environment.GetCommandLineArgs();return args[Array.IndexOf(args,name)+1];}
 public static void Run(){try{
  // Cold batch editor must explicitly open the saved approved scene.
  UnityEditor.SceneManagement.EditorSceneManager.OpenScene("Assets/Game/World.unity",UnityEditor.SceneManagement.OpenSceneMode.Single);
  // Build the already approved source revision; never refresh/overwrite approval.
  XaceNativeBuild.Validate();
  var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{"Assets/Game/World.unity"},locationPathName=Arg("-xaceBuild"),target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});
  if(report.summary.result!=BuildResult.Succeeded)throw new Exception("Build failed");
  XaceNativeBuild.RequireBuildReceipt(Arg("-xaceBuild"));File.WriteAllText(Arg("-xaceReport"),JsonUtility.ToJson(new Outcome()));EditorApplication.Exit(0);
 }catch(Exception error){Debug.LogException(error);EditorApplication.Exit(1);}}
}
'''
def main(out,source=None,package_base=None):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert shutil.disk_usage(ROOT).free>4*1024**3;out.mkdir(parents=True)
 source=Path(source).resolve() if source is not None else ROOT/'evidence/nec017/20261105/unity-existing-publish-b/project';assert source.is_relative_to(ROOT/'evidence/nec017');before={folder:inventory(source/folder) for folder in ['Assets','Packages','ProjectSettings']};project=out/'project'
 for name in before:shutil.copytree(source/name,project/name)
 # Explicit reviewed runtime prerequisites in this copied project; originals remain untouched.
 manifest_path=project/'Packages/manifest.json';manifest=json.loads(manifest_path.read_bytes());added={}
 for module in ['imgui','particlesystem']:
  key='com.unity.modules.'+module
  if key not in manifest['dependencies']:manifest['dependencies'][key]='1.0.0';added[key]='1.0.0'
 manifest_path.write_bytes(pp.encode(manifest));(out/'explicit-runtime-modules.json').write_bytes(pp.encode(dict(added=added,scope='Copied native runtime integration only',original_manifest_unchanged=True)))
 runtime=project/'Assets/XACE';(runtime/'Editor').mkdir(parents=True)
 for p in (ROOT/'adapters/unity').glob('*.cs'):shutil.copyfile(p,runtime/p.name)
 play=(ROOT/'tools/NEC013UnityPlayProof.cs').read_text(encoding='utf-8');start=play.index('    public static void Setup()');end=play.index('    static bool Gone',start);play=play[:start]+SETUP+play[end:]
 play=play.replace('NEC013UnityPlayProof','NEC017UnityPlayProof').replace('report.entities==2&&bindings.Length==2','report.entities==51&&bindings.Length==51').replace('report.input_moves_authority=b.transform.position.x>7.1f','if(b.name=="Crate0")report.input_moves_authority=b.transform.position.x>18.1f')
 play=play.replace('report.no_mirrors &= pair.Value.transform.Find("CanonicalVisual")==null;', 'report.no_mirrors &= pair.Value.transform.Find("CanonicalVisual")==null; if(pair.Value.name.StartsWith("Crate")) report.native_identity &= pair.Value.GetComponent<MeshFilter>()!=null && pair.Value.GetComponent<MeshFilter>().sharedMesh!=null && pair.Value.GetComponent<MeshRenderer>()!=null && pair.Value.GetComponent<MeshRenderer>().sharedMaterial!=null;')
 (runtime/'Editor/NEC017UnityPlayProof.cs').write_text(play,encoding='utf-8');(runtime/'Editor/NEC017ExistingBuild.cs').write_text(BUILD,encoding='utf-8')
 probe=(ROOT/'tools/NEC013UnityPlayerProbe.cs').read_text(encoding='utf-8').replace('NEC013UnityPlayerProbe','NEC017UnityPlayerProbe').replace('r.entities==2','r.entities==51').replace('r.input_moves_authority=go.transform.position.x>7.1f','if(go.name=="Crate0")r.input_moves_authority=go.transform.position.x>18.1f')
 probe=probe.replace('var go=pair.Value;', 'var go=pair.Value; if(go.name.StartsWith("Crate")) r.native_identity &= go.GetComponent<MeshFilter>()!=null && go.GetComponent<MeshFilter>().sharedMesh!=null && go.GetComponent<MeshRenderer>()!=null && go.GetComponent<MeshRenderer>().sharedMaterial!=null;')
 (runtime/'NEC017UnityPlayerProbe.cs').write_text(probe,encoding='utf-8')
 base=Path(package_base).resolve() if package_base is not None else ROOT/'evidence/nec017/20261106/existing-execution-b/unity';assert base.is_relative_to(ROOT/'evidence/nec017');files=pp.read_archive((base/'game.xacepkg').read_bytes());cgs=json.loads(files['game.cgs.json']);compiled,_=pp.compiled_artifacts(cgs)
 receipt_path=ROOT/'evidence/nec011/20261021/reference-admission-a/executor-receipt.json';receipt=json.loads(receipt_path.read_bytes());exe=base/'relocated/runtime/xace_runtime.exe';support=admit(receipt,expected_receipt_digest=digest(receipt),executable=exe,required_capabilities=['native.structured_transform.v1'],expected_compatibility=receipt['compatibility'],package=compiled)
 presentation={p:data for p,data in files.items() if p.startswith('presentation/')};presentation['presentation/player/settings.json']=pp.encode(dict(schema='xace.player.controls.v1',controller_id=1,instructions='D/A move',bindings=[dict(action='move_x',positive=68,negative=65,kind='axis_1d')]))
 archive=pp.build_package(cgs,files['execution_plan.json'],exe.read_bytes(),support,package_id='nec017.existing.unity',version='0.1.0',presentation_files=presentation);(out/'game.xacepkg').write_bytes(archive)
 release=project/'Assets/StreamingAssets/XACERelease';release.mkdir(parents=True)
 for name,data in pp.read_archive(archive).items():
  p=release/'package'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 shutil.copyfile(receipt_path,release/'executor-receipt.json');shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',release/'xace-player-launcher.exe')
 (release/'native-release.json').write_bytes(pp.encode(dict(schema='xace.native_release.v1',engine='Unity',game_id='nec017-existing-unity',package_manifest_sha256=sha(release/'package/playable.manifest.json'),executor_receipt_sha256=sha(release/'executor-receipt.json'),required_capabilities=['native.structured_transform.v1'],compatibility=receipt['compatibility'],save_schema='nec017.existing.v1',resources=[])))
 pins={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),ROOT/'tools/NEC013UnityPlayProof.cs',ROOT/'tools/NEC013UnityPlayerProbe.cs',*sorted((ROOT/'adapters/unity').rglob('*.cs')),*sorted((ROOT/'packages/project-system').glob('*.py'))]};(out/'source-pins.json').write_bytes(pp.encode(pins));env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 def run(method,name,extra=[]):
  command=[UNITY,'-batchmode','-nographics','-projectPath',str(project),'-executeMethod',method,'-xaceReport',str(out/(name+'.json')),'-logFile',str(out/(name+'.log'))]+extra
  (out/(name+'-command.json')).write_bytes(pp.encode(command));start=time.perf_counter()
  with (out/(name+'-run.log')).open('wb') as log:
   r=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
   while r.poll() is None:
    if shutil.disk_usage(ROOT).free<2*1024**3 or time.perf_counter()-start>900:
     subprocess.run(['taskkill','/PID',str(r.pid),'/T','/F'],capture_output=True);raise RuntimeError('Owned Unity stopped at2GiB reserve/timeout; outputs retained')
    time.sleep(1)
  assert r.returncode==0,name+' failed; log retained';result=json.loads((out/(name+'.json')).read_text(encoding='utf-8-sig'));assert result['ok'];return time.perf_counter()-start
 run('NEC017UnityPlayProof.Run','editor-play');print('Existing Unity editor Play passed',flush=True)
 seconds=run('NEC017ExistingBuild.Run','build',['-xaceBuild',str(out/'shipping/NativeGame.exe')]);game=out/'relocated';shutil.copytree(out/'shipping',game);installation=inventory(game)
 env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');env['LOCALAPPDATA']=str(out/'player-user-data')
 with (out/'player-run.log').open('wb') as log:r=subprocess.run([str(game/'NativeGame.exe'),'-batchmode','-nographics','-xacePlayerReport',str(out/'player.json'),'-logFile',str(out/'player.log')],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
 player=json.loads((out/'player.json').read_text(encoding='utf-8-sig'));assert r.returncode==0 and player['ok'] and gone(player['runtime_pid']) and gone(player['owner_pid']) and inventory(game)==installation
 assert all(inventory(source/folder)==data for folder,data in before.items()) and all(sha(ROOT/name)==h for name,h in pins.items())
 original_assets=before['Assets'];unchanged={name:h for name,h in original_assets.items() if name!='Game/World.unity'};assert all(sha(project/'Assets'/name)==h for name,h in unchanged.items())
 (out/'proof.json').write_bytes(pp.encode(dict(ok=True,objects=51,editor_play=json.loads((out/'editor-play.json').read_text(encoding='utf-8-sig')),player=player,build_seconds=seconds,original_source_unchanged=True,only_original_asset_changed='Game/World.unity: explicit runtime identity bindings',source_stable=True,clean_machine=False,full_nec017_complete=False)));print('Existing Unity native build/player passed',flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))

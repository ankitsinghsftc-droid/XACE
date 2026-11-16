"""Three real Unity builds/readbacks of1,000 serialized authoring objects."""
from pathlib import Path
import json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import inventory,sha
from tools.nec017_process_metrics import memory,DescendantMemory
UNITY='C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe'
EDITOR=r'''using System;
using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditor.Build.Reporting;
public static class NEC017ScaleBuild {
 static string Arg(string key){var args=Environment.GetCommandLineArgs();return args[Array.IndexOf(args,key)+1];}
 public static void Configure(){try{PlayerSettings.SetScriptingBackend(UnityEditor.Build.NamedBuildTarget.Standalone,ScriptingImplementation.Mono2x);PlayerSettings.runInBackground=true;EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene("Assets/XACEGenerated/World.unity",true)};AssetDatabase.SaveAssets();EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);EditorApplication.Exit(1);}}
 public static void Run(){try{EditorSceneManager.OpenScene("Assets/XACEGenerated/World.unity",OpenSceneMode.Single);var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{"Assets/XACEGenerated/World.unity"},locationPathName=Arg("-scaleBuild"),target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});if(report.summary.result!=BuildResult.Succeeded)throw new Exception("Scale build failed");EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);EditorApplication.Exit(1);}}
}
'''
PROBE=r'''using System;
using System.IO;
using UnityEngine;
using Xace.Authoring;
public sealed class NEC017ScaleProbe:MonoBehaviour {
 [Serializable]public sealed class Expected{public Item[] items;}
 [Serializable]public sealed class Item{public string id;public float x,y,z;}
 [Serializable]public sealed class Result{public bool ok,exported;public int objects;public string scope="Static serialized transforms; no XACE gameplay runtime or graphics workload";}
 [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]static void Init(){new GameObject("NEC017 Data Observer").AddComponent<NEC017ScaleProbe>();}
 void Start(){var expected=JsonUtility.FromJson<Expected>(Resources.Load<TextAsset>("scale-expected").text);var objects=UnityEngine.Object.FindObjectsByType<XaceAuthoringIdentity>(FindObjectsInactive.Include,FindObjectsSortMode.None);var map=new System.Collections.Generic.Dictionary<string,GameObject>();bool ok=objects.Length==1000;foreach(var item in objects){if(map.ContainsKey(item.name))ok=false;else map.Add(item.name,item.gameObject);}foreach(var item in expected.items){if(!map.TryGetValue(item.id,out var go)){ok=false;continue;}ok &= Vector3.Distance(go.transform.position,new Vector3(item.x,item.y,item.z))<0.00001f && Vector3.Distance(go.transform.localScale,Vector3.one)<0.00001f && Quaternion.Angle(go.transform.rotation,Quaternion.identity)<0.00001f;}
 var result=new Result{ok=ok&&expected.items.Length==1000,exported=!Application.isEditor,objects=objects.Length};var args=Environment.GetCommandLineArgs();File.WriteAllText(args[Array.IndexOf(args,"-scaleReport")+1],JsonUtility.ToJson(result));Application.Quit(result.ok?0:1);}
}
'''
def run(command,out,name,env,timeout=900):
 started=time.perf_counter();(out/(name+'-command.json')).write_text(json.dumps(command,indent=2))
 with (out/(name+'.log')).open('wb') as log:
  process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);tree=DescendantMemory(process.pid)
  try:
   while process.poll() is None:
    tree.sample()
    if shutil.disk_usage(ROOT).free<2*1024**3 or time.perf_counter()-started>timeout:
     subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True);process.wait();raise RuntimeError('Owned process stopped at disk/time reserve; all files retained')
    time.sleep(.1)
   tree.sample();result=dict(seconds=time.perf_counter()-started,returncode=process.returncode,root_memory=memory(int(process._handle)),descendants=list(tree.rows.values()),sampled_descendant_peak_bytes=tree.sampled_peak,sampling_ms=100,aggregate_peak_exact=False)
  finally:tree.close()
 (out/(name+'-metrics.json')).write_text(json.dumps(result,indent=2));assert result['returncode']==0,name+' failed; retained logs';return result

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists() and shutil.disk_usage(ROOT).free>4*1024**3;out.mkdir(parents=True)
 seed=ROOT/'evidence/nec017/20261028/unity-scale-a';source=seed/'unity-project';before={n:inventory(source/n) for n in ['Assets','Packages','ProjectSettings']};project=out/'project'
 for n in before:shutil.copytree(source/n,project/n)
 scene='Assets/XACEGenerated/World.unity';scene_hash=sha(project/scene);cgs=json.loads((seed/'source.cgs.json').read_bytes());items=[]
 for actor in cgs['modes'][0]['actors']:
  p=actor['components'][0]['defaults']['position'];items.append(dict(id=actor['id'],x=p['x']/1000000,y=p['y']/1000000,z=-p['z']/1000000))
 assert len(items)==1000
 (project/'Assets/Resources').mkdir(exist_ok=True);(project/'Assets/Resources/scale-expected.json').write_text(json.dumps(dict(items=items),sort_keys=True));(project/'Assets/NEC017ScaleProbe.cs').write_text(PROBE);(project/'Assets/Editor').mkdir(exist_ok=True);(project/'Assets/Editor/NEC017ScaleBuild.cs').write_text(EDITOR)
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');command=[UNITY,'-batchmode','-nographics','-projectPath',str(project)];run(command+['-executeMethod','NEC017ScaleBuild.Configure','-logFile',str(out/'configure-engine.log')],out,'configure',env)
 approved={n:inventory(project/n) for n in before};(out/'source-pins.json').write_text(json.dumps(approved,sort_keys=True,indent=2));samples=[]
 for n in range(3):
  target=out/('build-'+str(n));metric=run(command+['-executeMethod','NEC017ScaleBuild.Run','-scaleBuild',str(target/'Scale.exe'),'-logFile',str(out/('build-'+str(n)+'-engine.log'))],out,'build-'+str(n),env)
  report=out/('player-'+str(n)+'.json');run([str(target/'Scale.exe'),'-batchmode','-nographics','-scaleReport',str(report),'-logFile',str(out/('player-'+str(n)+'-engine.log'))],out,'player-'+str(n),env,90)
  value=json.loads(report.read_bytes());assert value['ok'] and value['objects']==1000 and value['exported'] and sha(project/scene)==scene_hash and all(inventory(project/k)==approved[k] and inventory(source/k)==before[k] for k in before)
  samples.append(dict(build=n,measurement=metric,player=value,output_bytes=sum(p.stat().st_size for p in target.rglob('*') if p.is_file())));print(json.dumps(dict(build=n,objects=1000,seconds=metric['seconds'],ok=True)),flush=True)
 (out/'proof.json').write_text(json.dumps(dict(ok=True,engine='Unity6000.4.9f1',objects=1000,rebuilds=3,samples=samples,original_unchanged=True,scene_bytes_unchanged=True,source_unchanged=True,compiler_cache_reused_between_builds=True,scale_scope='Native serialized transform-node builds/readback; not graphics or1,000-object XACE gameplay-runtime certification',gameplay_runtime_scale_certified=False,full_nec017_complete=False),indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))

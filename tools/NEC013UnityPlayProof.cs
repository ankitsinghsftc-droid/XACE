using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Xace.Adapter.Unity;

[InitializeOnLoad]
public static class NEC013UnityPlayProof
{
    [Serializable] public sealed class Report { public bool ok; public bool required_playback; public bool runtime_audio_started; public bool runtime_animation_started; public string version; public string error; public int entities; public ulong tick; public bool native_identity; public bool hierarchy; public bool no_mirrors; public bool projection_positions; public bool process_cleanup; public int cycles; public bool domain_reload_disabled; public bool input_moves_authority; public int runtime_pid; public int owner_pid; }
    static XaceDeltaApplicator observed; static bool audioObserved, animationObserved;
    static string Arg(string key) { var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,key);if(i<0)throw new Exception("Missing "+key);return args[i+1]; }
    static NEC013UnityPlayProof(){EditorApplication.update-=Update;EditorApplication.update+=Update;}
    public static void Run()
    {
        try
        {
            Setup();
            SessionState.SetInt("NEC013.Cycle",1);
            SessionState.SetBool("NEC013.PlayActive",true);SessionState.SetBool("NEC013.PlayFinish",false);SessionState.SetString("NEC013.Start",DateTime.UtcNow.Ticks.ToString());
            EditorApplication.EnterPlaymode();
        }
        catch(Exception error){File.WriteAllText(Arg("-xaceReport"),JsonUtility.ToJson(new Report{ok=false,error=error.ToString()},true));EditorApplication.Exit(1);}
    }
    public static void Setup()
    {
            string release=Path.Combine(Application.streamingAssetsPath,"XACERelease");
            var world=XaceCanonical.Parse(File.ReadAllText(Path.Combine(release,"package/world.json")));
            var objects=(List<object>)world["objects"];
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
            var byId=new Dictionary<string,GameObject>();
            foreach(var value in objects){var item=XaceCanonical.Object(value);string id=XaceCanonical.Text(item,"id");var go=GameObject.CreatePrimitive(PrimitiveType.Cube);go.name="Native_"+byId.Count;go.AddComponent<XaceNativeSceneBinding>().worldObjectId=id;byId.Add(id,go);}
            foreach(var value in objects){var item=XaceCanonical.Object(value);var go=byId[XaceCanonical.Text(item,"id")];var relations=XaceCanonical.Object(item["relationships"]);if(relations.TryGetValue("xace.authoring_parent.v1",out var parents))go.transform.SetParent(byId[(string)((List<object>)parents)[0]].transform,false);go.transform.position=XaceCanonical.Vector(XaceCanonical.Object(XaceCanonical.Object(item["transform"])["position"]));}
            Directory.CreateDirectory("Assets/Resources");
            var game=XaceCanonical.Parse(File.ReadAllText(Path.Combine(release,"package/game.cgs.json")));
            if(game.ContainsKey("semantic_bindings"))
            {
                var clip=new AnimationClip{legacy=true};clip.SetCurve("Visual",typeof(Transform),"localPosition.x",AnimationCurve.Linear(0,0,1,0.2f));AssetDatabase.CreateAsset(clip,"Assets/Resources/nec013-echo.anim");
                using(var w=new BinaryWriter(File.Create("Assets/Resources/nec013-tone.wav"))){w.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"));w.Write(16036);w.Write(System.Text.Encoding.ASCII.GetBytes("WAVEfmt "));w.Write(16);w.Write((short)1);w.Write((short)1);w.Write(8000);w.Write(16000);w.Write((short)2);w.Write((short)16);w.Write(System.Text.Encoding.ASCII.GetBytes("data"));w.Write(16000);for(int i=0;i<8000;i++)w.Write((short)(Math.Sin(i*2*Math.PI*440/8000)*1000));}
                AssetDatabase.ImportAsset("Assets/Resources/nec013-tone.wav",ImportAssetOptions.ForceSynchronousImport);
                foreach(var go in byId.Values){go.AddComponent<Animation>();var visual=new GameObject("Visual");visual.transform.SetParent(go.transform,false);}
            }
            var profile=ScriptableObject.CreateInstance<XaceNativeHostProfile>();profile.gameId="nec012-proof";profile.inputBindings=new[]{new XaceLiveInputBinding{action="move_x",kind="axis_1d",nativeSelector="proof.move"},new XaceLiveInputBinding{action="jump",kind="button",nativeSelector="proof.jump"}};profile.releaseSha256=XaceNativeHostClient.FileHash(Path.Combine(release,"native-release.json"));profile.launcherSha256=XaceNativeHostClient.FileHash(Path.Combine(release,"xace-player-launcher.exe"));
            AssetDatabase.CreateAsset(profile,"Assets/Resources/XaceNativeHost.asset");AssetDatabase.SaveAssets();EditorSceneManager.SaveScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene(),"Assets/NativeGame.unity");AssetDatabase.Refresh();
            EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene("Assets/NativeGame.unity",true)};
            XaceNativeBuild.RecordApproval();
    }
    static bool Gone(int pid){if(pid==0)return true;try{using(var p=Process.GetProcessById(pid))return p.HasExited;}catch(ArgumentException){return true;}}
    static void Update()
    {
        if(!SessionState.GetBool("NEC013.PlayActive",false))return;
        if(SessionState.GetBool("NEC013.PlayFinish",false))
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode)return;
            var report=JsonUtility.FromJson<Report>(File.ReadAllText(Arg("-xaceReport")));report.process_cleanup=Gone(report.runtime_pid)&&Gone(report.owner_pid);report.ok&=report.process_cleanup;
            int cycle=SessionState.GetInt("NEC013.Cycle",1);report.cycles=cycle;report.domain_reload_disabled=EditorSettings.enterPlayModeOptionsEnabled;
            File.WriteAllText(Arg("-xaceReport")+".cycle-"+cycle+".json",JsonUtility.ToJson(report,true));
            if(report.ok&&cycle<3)
            {
                SessionState.SetInt("NEC013.Cycle",cycle+1);SessionState.SetBool("NEC013.PlayFinish",false);SessionState.SetString("NEC013.Start",DateTime.UtcNow.Ticks.ToString());
                if(cycle==2){EditorSettings.enterPlayModeOptionsEnabled=true;EditorSettings.enterPlayModeOptions=EnterPlayModeOptions.DisableDomainReload;}
                EditorApplication.EnterPlaymode();return;
            }
            File.WriteAllText(Arg("-xaceReport"),JsonUtility.ToJson(report,true));SessionState.SetBool("NEC013.PlayActive",false);EditorApplication.Exit(report.ok?0:1);return;
        }
        try
        {
            if(DateTime.UtcNow.Ticks-long.Parse(SessionState.GetString("NEC013.Start","0"))>TimeSpan.FromSeconds(60).Ticks)throw new TimeoutException("Editor native Play timed out");
            if(!EditorApplication.isPlaying)return;
            var host=UnityEngine.Object.FindAnyObjectByType<XaceNativeHost>();if(host==null)return;
            if(host.State=="failed")throw new Exception(host.Error);
            var apply=host.GetComponent<XaceDeltaApplicator>();
            if(observed!=apply){observed=apply;audioObserved=false;animationObserved=false;apply.OnPlaybackCommandApplied+=(command,applied)=>{var actor=apply.GetEntity(command.entity_id);if(actor==null)return;if(command.binding_id=="nec013.audio")audioObserved|=applied&&actor.GetComponentInChildren<AudioSource>()!=null&&actor.GetComponentInChildren<AudioSource>().isPlaying;if(command.binding_id=="nec013.animation")animationObserved|=applied&&actor.GetComponentInChildren<Animation>()!=null&&actor.GetComponentInChildren<Animation>().IsPlaying("play");};}
            host.GetComponent<XaceInputCollector>().SubmitNativeAction("proof.move",1);
            host.GetComponent<XaceInputCollector>().SubmitNativeAction("proof.jump",apply.CurrentTick%20>=10?1:0);
            bool required=Resources.Load<AudioClip>("nec013-tone")!=null;
            if(host.State!="playing"||apply.CurrentTick<12||(required&&(!audioObserved||!animationObserved)))return;
            var bindings=UnityEngine.Object.FindObjectsByType<XaceNativeSceneBinding>(FindObjectsInactive.Include,FindObjectsSortMode.None);
            var report=new Report{ok=true,version=Application.unityVersion,entities=apply.EntityCount,tick=apply.CurrentTick,native_identity=true,hierarchy=false,no_mirrors=true,projection_positions=true,runtime_pid=host.RuntimeProcessId,owner_pid=host.OwnerProcessId};
            foreach(var pair in apply.Entities)
            {
                report.native_identity &= pair.Value.GetComponent<XaceNativeSceneBinding>()!=null;
                report.no_mirrors &= pair.Value.transform.Find("CanonicalVisual")==null;
                string raw;pair.Value.GetComponent<XaceEntityMarker>().TryGetComponentData(1,out raw);var state=XaceCanonical.Parse(raw);var expected=XaceCanonical.Vector(XaceCanonical.Object(state["position"]));report.projection_positions &= Vector3.Distance(pair.Value.transform.position,expected)<0.0001f;
            }
            foreach(var b in bindings)if(b.transform.parent!=null&&b.transform.parent.GetComponent<XaceNativeSceneBinding>()!=null){report.hierarchy=true;report.input_moves_authority=b.transform.position.x>7.1f;}
            report.ok=report.entities==2&&bindings.Length==2&&report.native_identity&&report.no_mirrors&&report.projection_positions&&report.hierarchy&&report.input_moves_authority;
            report.required_playback=required;report.runtime_audio_started=audioObserved;report.runtime_animation_started=animationObserved;
            Finish(report);
        }
        catch(Exception error){UnityEngine.Debug.LogException(error);Finish(new Report{ok=false,error=error.ToString(),version=Application.unityVersion});}
    }
    static void Finish(Report report){File.WriteAllText(Arg("-xaceReport"),JsonUtility.ToJson(report,true));SessionState.SetBool("NEC013.PlayFinish",true);EditorApplication.ExitPlaymode();}
}

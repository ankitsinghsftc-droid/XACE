using System;
using System.IO;
using System.Collections.Generic;
using UnityEngine;
using Xace.Adapter.Unity;
public sealed class NEC013UnityPlayerProbe:MonoBehaviour
{
    string report;float deadline;int saveStage;string badSave;string badHash;bool saveCompatible;bool saveRefused;string failureMode;int failureStage;int runtimePid;int ownerPid;float freezeAt;ulong frozenTick;bool playbackSubscribed;bool audioObserved;bool animationObserved;
    [Serializable]public sealed class Result{public bool ok;public string error;public string unity;public ulong tick;public int entities;public int runtime_pid;public int owner_pid;public bool native_identity;public bool hierarchy;public bool positions;public bool input_moves_authority;public bool save_compatible_not_restored;public bool incompatible_save_retained;public string save_root;public string fault;public bool authority_stopped;public bool frozen;public bool required_playback;public bool runtime_audio_started;public bool runtime_animation_started;}
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Install(){var args=Environment.GetCommandLineArgs();int index=Array.IndexOf(args,"-xacePlayerReport");if(index<0)return;var go=new GameObject("NEC013Proof");DontDestroyOnLoad(go);var probe=go.AddComponent<NEC013UnityPlayerProbe>();probe.report=args[index+1];probe.deadline=Time.realtimeSinceStartup+40;int fault=Array.IndexOf(args,"-xaceFailure");if(fault>=0)probe.failureMode=args[fault+1];}
    void Update()
    {
        var host=FindAnyObjectByType<XaceNativeHost>();
        if(host!=null&&!playbackSubscribed)
        {
            playbackSubscribed=true;
            host.GetComponent<XaceDeltaApplicator>().OnPlaybackCommandApplied+=(command,applied)=>{
                var actor=host.GetComponent<XaceDeltaApplicator>().GetEntity(command.entity_id);if(actor==null)return;
                if(command.binding_id=="nec013.audio")audioObserved|=applied&&actor.GetComponentInChildren<AudioSource>()!=null&&actor.GetComponentInChildren<AudioSource>().isPlaying;
                if(command.binding_id=="nec013.animation")animationObserved|=applied&&actor.GetComponentInChildren<Animation>()!=null&&actor.GetComponentInChildren<Animation>().IsPlaying("play");
            };
        }
        if(!string.IsNullOrEmpty(failureMode)&&host!=null)
        {
            var projection=host.GetComponent<XaceDeltaApplicator>();
            if(failureStage==0&&host.State=="playing"&&projection.CurrentTick>=5)
            {
                runtimePid=host.RuntimeProcessId;ownerPid=host.OwnerProcessId;failureStage=1;
                if(failureMode=="authority"){using(var process=System.Diagnostics.Process.GetProcessById(runtimePid))process.Kill();}
                else if(failureMode=="scene")UnityEngine.SceneManagement.SceneManager.LoadSceneAsync(0);
                else{Finish(new Result{error="Unknown failure mode"});return;}
            }
            if(failureStage==1&&host.State=="failed"){failureStage=2;freezeAt=Time.realtimeSinceStartup+1;}
            if(failureStage==2&&Time.realtimeSinceStartup>freezeAt){frozenTick=projection.CurrentTick;freezeAt=Time.realtimeSinceStartup+1;failureStage=3;}
            if(failureStage==3&&Time.realtimeSinceStartup>freezeAt){bool frozen=projection.CurrentTick==frozenTick;Finish(new Result{ok=frozen&&host.State=="failed",error=host.Error,fault=failureMode,authority_stopped=host.OwnerProcessId==0,frozen=frozen,runtime_pid=runtimePid,owner_pid=ownerPid});return;}
            if(Time.realtimeSinceStartup>deadline)Finish(new Result{error="Failure did not stop/freeze native gameplay",fault=failureMode});
            return;
        }
        if(Time.realtimeSinceStartup>deadline || (host!=null&&host.State=="failed")){Finish(new Result{error=host==null?"Host absent":host.Error});return;}
        if(host==null||host.State!="playing")return;host.GetComponent<XaceInputCollector>().SubmitNativeAction("proof.move",1);var apply=host.GetComponent<XaceDeltaApplicator>();host.GetComponent<XaceInputCollector>().SubmitNativeAction("proof.jump",apply.CurrentTick%20>=10?1:0);bool playbackRequired=Resources.Load<AudioClip>("nec013-tone")!=null;if(apply.CurrentTick<12||(playbackRequired&&(!audioObserved||!animationObserved)))return;
        if(saveStage==0)
        {
            Directory.CreateDirectory(host.SaveRoot);
            var identity=XaceCanonical.Parse(host.SaveIdentityJson);var snapshot=new Dictionary<string,object>{{"tick",12L}};
            var envelope=new Dictionary<string,object>{{"schema","xace.native_save.v1"},{"identity",identity},{"snapshot",snapshot},{"payload_sha256",XaceCanonical.Hash(XaceJson.Serialize(snapshot))}};
            WriteNew(Path.Combine(host.SaveRoot,"slot-nec013-compatible.json"),XaceJson.Serialize(envelope));
            identity["game_id"]="incompatible-other-game";badSave=Path.Combine(host.SaveRoot,"slot-nec013-incompatible.json");WriteNew(badSave,XaceJson.Serialize(envelope));badHash=XaceNativeHostClient.FileHash(badSave);
            host.CheckSave("nec013-compatible");saveStage=1;return;
        }
        if(saveStage==1)
        {
            if(host.SaveStatus=="checking")return;
            saveCompatible=host.SaveStatus=="compatible-not-restored";
            if(!saveCompatible){Finish(new Result{error="Compatible save check failed: "+host.SaveError});return;}
            host.CheckSave("nec013-incompatible");saveStage=2;return;
        }
        if(saveStage==2)
        {
            if(host.SaveStatus=="checking")return;
            saveRefused=host.SaveStatus=="refused"&&XaceNativeHostClient.FileHash(badSave)==badHash&&host.State=="playing";saveStage=3;
        }
        var r=new Result{ok=true,unity=Application.unityVersion,tick=apply.CurrentTick,entities=apply.EntityCount,runtime_pid=host.RuntimeProcessId,owner_pid=host.OwnerProcessId,native_identity=true,positions=true};
        foreach(var pair in apply.Entities){var go=pair.Value;r.native_identity&=go.GetComponent<XaceNativeSceneBinding>()!=null&&go.transform.Find("CanonicalVisual")==null;if(go.transform.parent!=null&&go.transform.parent.GetComponent<XaceNativeSceneBinding>()!=null){r.hierarchy=true;r.input_moves_authority=go.transform.position.x>7.1f;}go.GetComponent<XaceEntityMarker>().TryGetComponentData(1,out var raw);r.positions&=Vector3.Distance(go.transform.position,XaceCanonical.Vector(XaceCanonical.Object(XaceCanonical.Parse(raw)["position"])))<0.0001f;}
        r.required_playback=playbackRequired;r.runtime_audio_started=audioObserved;r.runtime_animation_started=animationObserved;
        r.save_compatible_not_restored=saveCompatible;r.incompatible_save_retained=saveRefused;r.save_root=host.SaveRoot;
        r.ok=saveCompatible&&saveRefused&&r.entities==2&&r.native_identity&&r.positions&&r.hierarchy&&r.input_moves_authority;Finish(r);
    }
    static void WriteNew(string path,string contents){using(var f=new FileStream(path,FileMode.CreateNew,FileAccess.Write))using(var w=new StreamWriter(f,new System.Text.UTF8Encoding(false)))w.Write(contents);}
    void Finish(Result r){File.WriteAllText(report,JsonUtility.ToJson(r,true));enabled=false;Application.Quit(r.ok?0:1);}
}

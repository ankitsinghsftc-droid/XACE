using System;
using System.IO;
using UnityEngine;
using Xace.Adapter.Unity;
public sealed class NEC013UnityPlayerProbe:MonoBehaviour
{
    string report;float deadline;
    [Serializable]public sealed class Result{public bool ok;public string error;public string unity;public ulong tick;public int entities;public int runtime_pid;public int owner_pid;public bool native_identity;public bool hierarchy;public bool positions;}
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Install(){var args=Environment.GetCommandLineArgs();int index=Array.IndexOf(args,"-xacePlayerReport");if(index<0)return;var go=new GameObject("NEC013Proof");var probe=go.AddComponent<NEC013UnityPlayerProbe>();probe.report=args[index+1];probe.deadline=Time.realtimeSinceStartup+40;}
    void Update()
    {
        var host=FindAnyObjectByType<XaceNativeHost>();
        if(Time.realtimeSinceStartup>deadline || (host!=null&&host.State=="failed")){Finish(new Result{error=host==null?"Host absent":host.Error});return;}
        if(host==null||host.State!="playing")return;var apply=host.GetComponent<XaceDeltaApplicator>();if(apply.CurrentTick<12)return;
        var r=new Result{ok=true,unity=Application.unityVersion,tick=apply.CurrentTick,entities=apply.EntityCount,runtime_pid=host.RuntimeProcessId,owner_pid=host.OwnerProcessId,native_identity=true,positions=true};
        foreach(var pair in apply.Entities){var go=pair.Value;r.native_identity&=go.GetComponent<XaceNativeSceneBinding>()!=null&&go.transform.Find("CanonicalVisual")==null;if(go.transform.parent!=null&&go.transform.parent.GetComponent<XaceNativeSceneBinding>()!=null)r.hierarchy=true;go.GetComponent<XaceEntityMarker>().TryGetComponentData(1,out var raw);r.positions&=Vector3.Distance(go.transform.position,XaceCanonical.Vector(XaceCanonical.Object(XaceCanonical.Parse(raw)["position"])))<0.0001f;}
        r.ok=r.entities==2&&r.native_identity&&r.positions&&r.hierarchy;Finish(r);
    }
    void Finish(Result r){File.WriteAllText(report,JsonUtility.ToJson(r,true));enabled=false;Application.Quit(r.ok?0:1);}
}

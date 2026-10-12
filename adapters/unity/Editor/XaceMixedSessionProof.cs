using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading;
using UnityEditor;
using UnityEngine;

namespace Xace.Adapter.Unity.Editor
{
    // Test host only. All actions come from a versioned external recording.
    public static class XaceMixedSessionProof
    {
        static string Arg(string key) { var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,key);return i<0?"":a[i+1]; }
        static string Json(object value) { return (string)typeof(XaceCanonical).Assembly.GetType("Xace.Adapter.Unity.XaceJson").GetMethod("Serialize").Invoke(null,new[]{value}); }
        public static void Run()
        {
            GameObject root=null;XaceTransport transport=null;
            try
            {
                var config=XaceCanonical.Parse(File.ReadAllText(Arg("-xaceConfig")));
                var rows=(List<object>)config["inputs"];long last=-1,stop=XaceCanonical.Integer(config["stop_tick"]);
                string transcript=(string)config["transcript"];
                Action<object> record=value=>File.AppendAllText(transcript,Json(value)+"\n");
                root=new GameObject("XACE mixed-session proof");
                transport=root.AddComponent<XaceTransport>();
                typeof(XaceTransport).GetField("disableCompanionComponents",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(transport,true);
                transport.ConfigureConnection("127.0.0.1",(int)XaceCanonical.Integer(config["port"]),(string)config["cgs_hash"]);
                transport.ConfigureLiveSession(File.ReadAllText((string)config["ticket"]),File.ReadAllText((string)config["world"]));
                var apply=root.AddComponent<XaceDeltaApplicator>();apply.BindTransportNow();
                transport.OnProtocolError+=error=>record(new Dictionary<string,object>{{"kind","error"},{"message",error}});
                transport.OnSessionInputTick+=tick=>{
                    var actions=new List<XaceInputAction>();
                    foreach(var v in (List<object>)rows[(int)tick]) { var a=XaceCanonical.Object(v);actions.Add(new XaceInputAction{action=(string)a["action"],kind=(string)a["kind"],phase=(string)a["phase"],value=Convert.ToSingle(a["value"])}); }
                    var packet=new XaceInputPacket{tick=tick,peer_id=(ulong)transport.Session.PeerId,player_id=(ulong)transport.Session.PlayerId,sequence_id=transport.NextSequenceId(),actions=actions.ToArray(),device_id="xp017-unity"};
                    if(!transport.SendInputPacket(packet))throw new Exception("Input not sent");
                    record(new Dictionary<string,object>{{"kind","input"},{"tick",tick},{"actions",rows[(int)tick]}});
                };
                transport.OnMessageReceived+=message=>{
                    if(message.MessageType=="handshake_ack")record(new Dictionary<string,object>{{"kind","ready"},{"player",transport.Session.PlayerId},{"peer",transport.Session.PeerId},{"epoch",message.Data["sync"]},{"version",Application.unityVersion}});
                    if(message.MessageType!="tick_snapshot")return;
                    bool applied=true;
                    foreach(var v in (List<object>)message.Data["entities"]) {
                        var e=XaceCanonical.Object(v);var go=apply.GetEntity((ulong)XaceCanonical.Integer(e["id"]));var c=XaceCanonical.Object(e["components"]);
                        applied=go!=null&&applied;if(go==null)continue;
                        foreach(var p in c) { string actual;applied=go.GetComponent<XaceEntityMarker>().TryGetComponentData(uint.Parse(p.Key),out actual)&&actual==(string)p.Value&&applied; }
                        if(c.ContainsKey("1")){var t=XaceCanonical.Parse((string)c["1"]);applied=Vector3.Distance(go.transform.localPosition,XaceCanonical.Vector(XaceCanonical.Object(t["position"])))<0.0001f&&applied;}
                    }
                    last=XaceCanonical.Integer(message.Data["tick"]);
                    record(new Dictionary<string,object>{{"kind","tick"},{"tick",last},{"applied",applied},{"projection_json",message.Data["projection_json"]},{"sync",message.Data["sync"]},{"events",message.Data["events"]}});
                };
                transport.Connect();var watch=System.Diagnostics.Stopwatch.StartNew();
                while(last<stop && watch.Elapsed.TotalSeconds<180){transport.PumpOnce();Thread.Sleep(5);}
                transport.Disconnect("proof leave");record(new Dictionary<string,object>{{"kind","done"},{"ok",last==stop}});
                EditorApplication.Exit(last==stop?0:1);
            }
            catch(Exception e){Debug.LogException(e);if(transport!=null)transport.Disconnect("proof failure");EditorApplication.Exit(1);}
            finally {if(root!=null)UnityEngine.Object.DestroyImmediate(root);}
        }
    }
}

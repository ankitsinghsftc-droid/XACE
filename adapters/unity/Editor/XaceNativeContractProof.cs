using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace Xace.Adapter.Unity.Editor
{
    public static class XaceNativeContractProof
    {
        static string Arg(string key)
        {var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,key);return i>=0 && i+1<args.Length ? args[i+1] : "";}
        public static void Run()
        {
            try
            {
                var fixture=XaceCanonical.Parse(File.ReadAllText(Arg("-xaceFixture")));
                var ticket=XaceCanonical.Text(fixture,"ticket_json");var world=XaceCanonical.Text(fixture,"world_json");
                bool ok=true;var results=new List<object>();
                foreach(var value in (List<object>)fixture["cases"])
                {
                    var test=XaceCanonical.Object(value);var session=new XaceSessionState();string result="reject";bool prefix=true;
                    try
                    {
                        session.Configure(ticket,world);
                        foreach(var m in (List<object>)test["messages"])prefix=session.Verify(XaceCanonical.Parse(XaceJsonSerialize(m)))=="accept" && prefix;
                        result=session.Verify(XaceCanonical.Parse(XaceJsonSerialize(test["message"])));
                    }
                    catch(FormatException){result="reject";}
                    bool pass=prefix && result==(string)test["expected"];ok=pass&&ok;
                    results.Add(new Dictionary<string,object>{{"name",test["name"]},{"result",result},{"ok",pass}});
                }
                var gameObject=new GameObject("XACE Native Contract Proof");
                var transport=gameObject.AddComponent<XaceTransport>();transport.ConfigureLiveSession(ticket,world);
                var applicator=gameObject.AddComponent<XaceDeltaApplicator>();
                applicator.BindTransportNow();
                var dispatch=typeof(XaceTransport).GetMethod("DispatchInbound",BindingFlags.Instance|BindingFlags.NonPublic);
                var baseline=XaceCanonical.Object(fixture["baseline"]);
                dispatch.Invoke(transport,new object[]{new XaceRuntimeMessage(XaceJsonSerialize(baseline),baseline)});
                var marker=applicator.GetEntity(42);var solid=applicator.GetEntity(77).transform.Find("CanonicalVisual");
                var position=marker.transform.position;var normal=marker.transform.rotation*new Vector3(0,0,-1);
                bool geometry=Vector3.Distance(position,new Vector3(6,2,-3))<0.0001f && Vector3.Distance(normal,new Vector3(1,0,0))<0.0001f && solid.localScale==new Vector3(2,4,6) && marker.GetComponent<XaceCanonicalObject>().ObjectId=="marker";
                foreach(var collider in gameObject.GetComponentsInChildren<Collider>(true))geometry=!collider.enabled && geometry;
                geometry=geometry && marker.GetComponent<XaceCanonicalObject>().WorldObjects.Count==2;
                var state=transport.Session;
                bool input=!state.CanSend(7,2,42) && state.Request(7) && state.CanSend(7,2,42);state.Sent();input=input && !state.CanSend(7,2,42) && !state.Request(7);
                ok=ok&&geometry&&input;
                File.WriteAllText(Arg("-xaceReport"),XaceJsonSerialize(new Dictionary<string,object>{{"schema","xace.native_contract_proof.v1"},{"engine","unity"},{"version",Application.unityVersion},{"ok",ok},{"cases",results},{"geometry",geometry},{"input_fence",input},{"position",new[]{position.x,position.y,position.z}},{"normal",new[]{normal.x,normal.y,normal.z}}}));
                UnityEngine.Object.DestroyImmediate(gameObject);
                EditorApplication.Exit(ok?0:1);
            }
            catch(Exception ex){Debug.LogException(ex);EditorApplication.Exit(1);}
        }
        // Runtime assembly exposes validated readers; reflection is confined to proof code.
        static string XaceJsonSerialize(object value)
        {var type=typeof(XaceCanonical).Assembly.GetType("Xace.Adapter.Unity.XaceJson");return (string)type.GetMethod("Serialize",BindingFlags.Static|BindingFlags.Public).Invoke(null,new[]{value});}
    }
}

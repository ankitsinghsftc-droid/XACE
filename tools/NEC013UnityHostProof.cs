using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using UnityEditor;
using UnityEngine;
using Xace.Adapter.Unity;

public static class NEC013UnityHostProof
{
    [Serializable] public sealed class Report { public bool ok; public string version; public int checks; public string error; public bool full_native_play; }
    static string Arg(string key) { var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,key);if(i<0)throw new Exception("Missing "+key);return args[i+1]; }
    static void Check(bool value,string message) { if(!value)throw new Exception(message); }
    static System.Collections.Generic.Dictionary<string,object> Receive(XaceNativeHostClient client)
    {
        var watch=Stopwatch.StartNew();
        while(watch.Elapsed.TotalSeconds<15) { if(client.TryReceive(out var result))return result;Thread.Sleep(10); }
        throw new TimeoutException("Native host response timeout");
    }
    public static void Run()
    {
        var report=new Report {version=Application.unityVersion};
        try
        {
            string release=Arg("-xaceRelease"),launcher=Arg("-xaceLauncher"),pin=Arg("-xaceLauncherHash"),expected=Arg("-xaceReleaseHash"),history=Arg("-xaceHistory");
            using(var refused=new XaceNativeHostClient()) {
                bool rejected=false;try{refused.Start(launcher,new string('0',64),release,expected,history,1);}catch(InvalidOperationException){rejected=true;}
                Check(rejected,"Changed launcher was accepted");report.checks++;
            }
            int runtime=0;
            using(var client=new XaceNativeHostClient())
            {
                client.Start(launcher,pin,release,expected,history,1);
                var hello=Receive(client);Check(XaceCanonical.Text(hello,"state")=="stopped","Not admitted");report.checks++;
                client.Play();var reply=Receive(client);Check(XaceCanonical.Get(reply,"ok") is bool ok && ok,"Play was refused");
                var result=XaceCanonical.Object(reply["result"]);runtime=(int)XaceCanonical.Integer(result["runtime_pid"]);Check(runtime>0&&File.Exists(XaceCanonical.Text(result,"ticket")),"Missing runtime/ticket");report.checks++;
                client.Play();reply=Receive(client);Check(XaceCanonical.Integer(XaceCanonical.Object(reply["result"])["runtime_pid"])==runtime,"Repeated Play replaced owner");report.checks++;
                client.Stop();reply=Receive(client);Check(XaceCanonical.Text(XaceCanonical.Object(reply["result"]),"state")=="stopped","Stop failed");report.checks++;
                client.Play();reply=Receive(client);runtime=(int)XaceCanonical.Integer(XaceCanonical.Object(reply["result"])["runtime_pid"]);
            }
            bool gone=false;for(int i=0;i<100&&!gone;i++){try{using(var process=Process.GetProcessById(runtime))gone=process.HasExited;}catch(ArgumentException){gone=true;}if(!gone)Thread.Sleep(20);}
            Check(gone,"Owned runtime survived Unity client disposal");report.checks++;
            var profile=ScriptableObject.CreateInstance<XaceNativeHostProfile>();profile.gameId="proof";profile.releaseDirectory="../escape";
            bool badPath=false;try{profile.ResolveRelease(Application.streamingAssetsPath);}catch(InvalidOperationException){badPath=true;}
            UnityEngine.Object.DestroyImmediate(profile);Check(badPath,"Release traversal accepted");report.checks++;
            report.ok=true;
        }
        catch(Exception error){report.error=error.ToString();UnityEngine.Debug.LogException(error);}
        File.WriteAllText(Arg("-xaceReport"),JsonUtility.ToJson(report,true));EditorApplication.Exit(report.ok?0:1);
    }
}

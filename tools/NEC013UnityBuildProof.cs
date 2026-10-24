using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using Xace.Adapter.Unity;
public static class NEC013UnityBuildProof
{
    static string Arg(string key){var args=Environment.GetCommandLineArgs();return args[Array.IndexOf(args,key)+1];}
    public static void Run()
    {
        try
        {
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone,ScriptingImplementation.Mono2x);
            PlayerSettings.companyName="XACE";PlayerSettings.productName="NEC013Proof";PlayerSettings.runInBackground=true;
            NEC013UnityPlayProof.Setup();
            string scene="Assets/NativeGame.unity";byte[] original=File.ReadAllBytes(scene);
            File.AppendAllText(scene,"\n# stale source proof\n");bool refused=false;
            try{XaceNativeBuild.Validate();}catch(BuildFailedException){refused=true;}
            finally{File.WriteAllBytes(scene,original);}
            if(!refused)throw new Exception("Stale scene accepted");
            XaceNativeBuild.Validate();
            var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{scene},locationPathName=Arg("-xaceBuild"),target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});
            if(report.summary.result!=BuildResult.Succeeded)throw new Exception("Windows build failed: "+report.summary.result);
            XaceNativeBuild.RequireBuildReceipt(Arg("-xaceBuild"));
            File.WriteAllText(Arg("-xaceReport"),"{\"ok\":true,\"backend\":\"Mono\",\"stale_scene_refused\":true,\"clean_machine\":false}");EditorApplication.Exit(0);
        }
        catch(Exception error){Debug.LogException(error);File.WriteAllText(Arg("-xaceReport"),JsonUtility.ToJson(new Failure{error=error.ToString()},true));EditorApplication.Exit(1);}
    }
    [Serializable]public sealed class Failure{public bool ok=false;public string error;}
}

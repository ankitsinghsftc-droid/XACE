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
            var profile=Resources.Load<XaceNativeHostProfile>("XaceNativeHost");
            string release=profile.ResolveRelease(Application.streamingAssetsPath);
            string manifest=Path.Combine(release,"package/playable.manifest.json");byte[] manifestOriginal=File.ReadAllBytes(manifest);
            bool presentationRefused=false;
            try{File.WriteAllText(manifest,File.ReadAllText(manifest).Replace("\"player\":","\"absent-player\":"));try{profile.ValidateRequiredResources(release);}catch(InvalidOperationException){presentationRefused=true;}}
            finally{File.WriteAllBytes(manifest,manifestOriginal);}
            if(!presentationRefused)throw new Exception("Missing presentation identity accepted");
            string cgs=Path.Combine(release,"package/game.cgs.json");byte[] cgsOriginal=File.ReadAllBytes(cgs);int resourceRefusals=0;
            var game=XaceCanonical.Parse(File.ReadAllText(cgs));
            if(game.TryGetValue("semantic_bindings",out var semantic))
            foreach(var value in (System.Collections.Generic.List<object>)XaceCanonical.Object(semantic)["bindings"])
            {
                var binding=XaceCanonical.Object(value);var parameters=XaceCanonical.Object(binding["parameters"]);var previous=parameters["resource_path"];
                try{File.WriteAllText(cgs,File.ReadAllText(cgs).Replace(Convert.ToString(previous),"nec013-absent-resource"));try{profile.ValidateRequiredResources(release);}catch(InvalidOperationException){resourceRefusals++;}}
                finally{parameters["resource_path"]=previous;File.WriteAllBytes(cgs,cgsOriginal);}
            }
            if(game.ContainsKey("semantic_bindings")&&resourceRefusals!=2)throw new Exception("Required audio/animation not refused");
            string scene="Assets/NativeGame.unity";byte[] original=File.ReadAllBytes(scene);
            File.AppendAllText(scene,"\n# stale source proof\n");bool refused=false;
            try{XaceNativeBuild.Validate();}catch(BuildFailedException){refused=true;}
            finally{File.WriteAllBytes(scene,original);}
            if(!refused)throw new Exception("Stale scene accepted");
            XaceNativeBuild.Validate();
            var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{scene},locationPathName=Arg("-xaceBuild"),target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});
            if(report.summary.result!=BuildResult.Succeeded)throw new Exception("Windows build failed: "+report.summary.result);
            XaceNativeBuild.RequireBuildReceipt(Arg("-xaceBuild"));
            File.WriteAllText(Arg("-xaceReport"),"{\"ok\":true,\"backend\":\"Mono\",\"stale_scene_refused\":true,\"missing_presentation_refused\":true,\"required_resource_refusals\":"+resourceRefusals+",\"clean_machine\":false}");EditorApplication.Exit(0);
        }
        catch(Exception error){Debug.LogException(error);File.WriteAllText(Arg("-xaceReport"),JsonUtility.ToJson(new Failure{error=error.ToString()},true));EditorApplication.Exit(1);}
    }
    [Serializable]public sealed class Failure{public bool ok=false;public string error;}
}

#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    // Approval is explicit. Play/build validate an existing receipt and never refresh it.
    [InitializeOnLoad]
    public sealed class XaceNativeBuild : IPreprocessBuildWithReport, IPostprocessBuildWithReport
    {
        [Serializable] public sealed class Entry { public string path; public string sha256; }
        [Serializable] public sealed class Approval { public string schema = "xace.unity.source_approval.v1"; public string unity; public string game; public string release; public string launcher; public string[] scenes; public Entry[] files; }
        [Serializable] public sealed class Receipt { public string schema = "xace.unity.build_receipt.v1"; public string status; public string error; public string approval; public string release; public string launcher; public string unity; public string backend; public string output; public Entry[] files; }
        public int callbackOrder => -10000;
        static string Root => Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        static string ApprovalPath => Path.Combine(Root, "XACEApproval.json");
        static string pending;
        static string approvedHash;
        static XaceNativeBuild()
        {
            EditorApplication.playModeStateChanged += state => {
                if (state != PlayModeStateChange.ExitingEditMode || (!File.Exists(ApprovalPath) && Resources.Load<XaceNativeHostProfile>("XaceNativeHost") == null)) return;
                try { Validate(); }
                catch (Exception error) { Journal(new Receipt {status="play-refused",error=error.Message}); Debug.LogError("[XACE] Play refused: " + error.Message); EditorApplication.isPlaying = false; }
            };
        }
        static XaceNativeHostProfile Profile()
        {
            var profile = Resources.Load<XaceNativeHostProfile>("XaceNativeHost");
            if (profile == null) throw new BuildFailedException("Approved native host profile missing");
            return profile;
        }
        static Entry[] Inventory()
        {
            var paths = Directory.GetFiles(Application.dataPath, "*", SearchOption.AllDirectories).ToList();
            foreach (var path in new[]{"Packages/manifest.json", "ProjectSettings/ProjectSettings.asset"}) if(File.Exists(Path.Combine(Root,path))) paths.Add(Path.Combine(Root,path));
            return paths.OrderBy(p=>p,StringComparer.Ordinal).Select(p=>new Entry {path=p.Substring(Root.Length+1).Replace('\\','/'),sha256=XaceNativeHostClient.FileHash(p)}).ToArray();
        }
        static string[] Scenes() => EditorBuildSettings.scenes.Where(s=>s.enabled).Select(s=>s.path).ToArray();
        static Approval Current()
        {
            var p=Profile();
            return new Approval {unity=Application.unityVersion,game=p.gameId,release=p.releaseSha256,launcher=p.launcherSha256,scenes=Scenes(),files=Inventory()};
        }
        static void VerifyRelease(string cookedRelease = null)
        {
            var p=Profile();string release=cookedRelease ?? p.ResolveRelease(Application.streamingAssetsPath);
            using(var client=new XaceNativeHostClient())
            {
                // Admission only: no Play, save restoration, or active-release mutation.
                client.Start(Path.Combine(release,p.launcherFile),p.launcherSha256,release,p.releaseSha256,Path.Combine(Root,"XACEEvidence","admission"),p.controllerId);
                var until=DateTime.UtcNow.AddSeconds(20);
                while(DateTime.UtcNow<until)
                {
                    if(client.TryReceive(out var message))
                    {
                        if(message.TryGetValue("ok",out var ok)&&ok is bool accepted&&!accepted) throw new BuildFailedException("Native release admission refused: "+XaceJson.Serialize(message));
                        if(message.TryGetValue("schema",out var schema)&&Convert.ToString(schema)=="xace.native_host.ready.v1")
                        {
                            if(XaceCanonical.Text(XaceCanonical.Object(message["save_identity"]),"game_id")!=p.gameId) throw new BuildFailedException("Game/save identity mismatch");
                            return;
                        }
                    }
                    Thread.Sleep(10);
                }
                throw new BuildFailedException("Native release admission timed out");
            }
        }
        // Called by an explicit review/approval operation, never by Play or Build callbacks.
        public static void RecordApproval()
        {
            if(File.Exists(ApprovalPath)) throw new BuildFailedException("Approval already exists; retain it and use a reviewed new project revision");
            AssetDatabase.SaveAssets(); AssetDatabase.Refresh();
            if(Scenes().Length==0) throw new BuildFailedException("At least one enabled saved scene required");
            VerifyRelease();
            using(var stream=new FileStream(ApprovalPath,FileMode.CreateNew,FileAccess.Write))
            using(var writer=new StreamWriter(stream)) writer.Write(JsonUtility.ToJson(Current(),true));
        }
        public static void Validate(bool inspectScene = true)
        {
            if(!File.Exists(ApprovalPath)) throw new BuildFailedException("Explicit native source approval required before Play/build");
            if(UnityEngine.SceneManagement.SceneManager.GetActiveScene().isDirty) throw new BuildFailedException("Save and review native scene changes first");
            var approved=JsonUtility.FromJson<Approval>(File.ReadAllText(ApprovalPath));
            if(JsonUtility.ToJson(approved)!=JsonUtility.ToJson(Current())) throw new BuildFailedException("Native source, resource, profile or scene inventory changed since approval");
            if(inspectScene)
            {
            var bindings=new Dictionary<string,GameObject>(StringComparer.Ordinal);
            foreach(var b in UnityEngine.Object.FindObjectsByType<XaceNativeSceneBinding>(FindObjectsInactive.Include,FindObjectsSortMode.None))
            {if(string.IsNullOrWhiteSpace(b.worldObjectId)||bindings.ContainsKey(b.worldObjectId))throw new BuildFailedException("Duplicate native scene identity");bindings.Add(b.worldObjectId,b.gameObject);}
            var p=Profile();XaceNativeSceneBinding.ValidateWorld(File.ReadAllText(Path.Combine(p.ResolveRelease(Application.streamingAssetsPath),"package","world.json")),bindings);
            }
            Profile().ValidateRequiredResources(Profile().ResolveRelease(Application.streamingAssetsPath));
            VerifyRelease();
        }
        static string Journal(Receipt value)
        {
            string root=Path.Combine(Root,"XACEEvidence","builds");Directory.CreateDirectory(root);
            string path=Path.Combine(root,DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffffff")+"-"+Guid.NewGuid().ToString("N")+".json");
            File.WriteAllText(path,JsonUtility.ToJson(value,true));return path;
        }
        public void OnPreprocessBuild(BuildReport report)
        {
            if(!File.Exists(ApprovalPath)&&Resources.Load<XaceNativeHostProfile>("XaceNativeHost")==null) return;
            SessionState.EraseString("XACE.NativeBuildResult");
            var receipt=new Receipt{status="staging",unity=Application.unityVersion,backend="Mono",output=report.summary.outputPath};
            try
            {
                if(report.summary.platform!=BuildTarget.StandaloneWindows64 || PlayerSettings.GetScriptingBackend(NamedBuildTarget.Standalone)!=ScriptingImplementation.Mono2x) throw new BuildFailedException("Only Windows x64 Mono is admitted by this native profile");
                string output=Path.GetDirectoryName(Path.GetFullPath(report.summary.outputPath));
                if(Directory.Exists(output)&&Directory.EnumerateFiles(output,"*",SearchOption.AllDirectories).Any()) throw new BuildFailedException("Use a fresh empty release directory; previous releases must remain intact");
                Validate(); approvedHash=XaceNativeHostClient.FileHash(ApprovalPath);
                var p=Profile();receipt.approval=approvedHash;receipt.release=p.releaseSha256;receipt.launcher=p.launcherSha256;
                pending=Journal(receipt);SessionState.SetString("XACE.NativeBuildJournal",pending);
            }
            catch(Exception error){receipt.status="refused";receipt.error=error.Message;Journal(receipt);throw;}
        }
        public static void RequireBuildReceipt(string output)
        {
            string path=SessionState.GetString("XACE.NativeBuildResult","");
            if(string.IsNullOrEmpty(path)||!File.Exists(path))throw new BuildFailedException("XACE build receipt missing; release is not admitted");
            var receipt=JsonUtility.FromJson<Receipt>(File.ReadAllText(path));
            if(receipt.status!="built-not-certified"||Path.GetFullPath(receipt.output)!=Path.GetFullPath(output))throw new BuildFailedException("XACE build refused: "+receipt.error);
            string root=Path.GetDirectoryName(Path.GetFullPath(output));
            foreach(var item in receipt.files)if(XaceNativeHostClient.FileHash(Path.Combine(root,item.path))!=item.sha256)throw new BuildFailedException("Cooked output changed after verification");
        }
        public void OnPostprocessBuild(BuildReport report)
        {
            if(string.IsNullOrEmpty(pending)) pending=SessionState.GetString("XACE.NativeBuildJournal","");
            if(string.IsNullOrEmpty(pending)) return;
            var receipt=JsonUtility.FromJson<Receipt>(File.ReadAllText(pending));
            try
            {
                Validate(false);
                if(XaceNativeHostClient.FileHash(ApprovalPath)!=receipt.approval)throw new BuildFailedException("Approval changed during build");
                string root=Path.GetDirectoryName(Path.GetFullPath(report.summary.outputPath));
                string release=Profile().ResolveRelease(Path.Combine(root,Path.GetFileNameWithoutExtension(report.summary.outputPath)+"_Data","StreamingAssets"));
                if(XaceNativeHostClient.FileHash(Path.Combine(release,"native-release.json"))!=receipt.release || XaceNativeHostClient.FileHash(Path.Combine(release,Profile().launcherFile))!=receipt.launcher)throw new BuildFailedException("Cooked release identity mismatch");
                VerifyRelease(release);
                receipt.files=Directory.GetFiles(root,"*",SearchOption.AllDirectories).OrderBy(p=>p,StringComparer.Ordinal).Select(p=>new Entry{path=p.Substring(root.Length+1).Replace('\\','/'),sha256=XaceNativeHostClient.FileHash(p)}).ToArray();
                receipt.status="built-not-certified";SessionState.SetString("XACE.NativeBuildResult",Journal(receipt));
            }
            catch(Exception error){receipt.status="failed";receipt.error=error.Message;SessionState.SetString("XACE.NativeBuildResult",Journal(receipt));throw;}
            finally{pending=null;SessionState.EraseString("XACE.NativeBuildJournal");}
        }
    }
}
#endif

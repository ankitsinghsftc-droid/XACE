using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
namespace Xace.Authoring.Editor
{
    // Explicit batch authoring entry point. Never runs on import or Play.
    public static class UnityAuthoringCommand
    {
        public static void Run()
        {
            string output=null;int code=1;object result;
            try {
                var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-xaceAuthoringCommand");AuthoringJson.Need(i>=0 && i+1<args.Length,"Explicit authoring command required");
                string path=Path.GetFullPath(args[i+1]);string root=Path.GetFullPath(".xace/native-authoring-calls")+Path.DirectorySeparatorChar;
                AuthoringJson.Need(path.StartsWith(root,StringComparison.OrdinalIgnoreCase) && Path.GetFileName(path)=="command.json","Command outside host call store");
                for(var d=new FileInfo(path) as FileSystemInfo;d!=null;d=d is FileInfo f?f.Directory:((DirectoryInfo)d).Parent)if(d.Exists)AuthoringJson.Need((d.Attributes&FileAttributes.ReparsePoint)==0,"Linked command path");
                output=Path.Combine(Path.GetDirectoryName(path),"result.json");AuthoringJson.Need(!File.Exists(output),"Command already executed");
                var config=AuthoringJson.Obj(AuthoringJson.Parse(File.ReadAllText(".xace/native-authoring-host.json")));
                AuthoringJson.Need(AuthoringJson.Text(config,"engine")=="unity" && Path.GetFullPath(AuthoringJson.Text(config,"root"))==Path.GetFullPath("."),"Foreign authoring host");
                var documents=((List<object>)config["documents"]).Cast<string>().ToArray();var scope=new AuthoringScope(documents);
                var command=AuthoringJson.Obj(AuthoringJson.Parse(File.ReadAllText(path)));string action=AuthoringJson.Text(command,"action");object value;
                foreach(var doc in documents.Where(d=>d.EndsWith(".unity")))EditorSceneManager.OpenScene(doc,OpenSceneMode.Single);
                if(action=="capture")value=UnityAuthoringReader.Capture(scope);
                else if(action=="prepare") {var write=UnityAuthoringWriter.PrepareRequest(scope,AuthoringJson.Encode(command["request"]));value=UnityAuthoringReader.Map("directory",write.Directory,"receipt",write.Journal,"approval_digest",write.ApprovalDigest);}
                else {
                    var p=AuthoringJson.Obj(command["prepared"]);var write=new PreparedAuthoringWrite{Directory=AuthoringJson.Text(p,"directory"),Journal=AuthoringJson.Obj(p["receipt"])};
                    AuthoringJson.Need(Path.GetFullPath(write.Directory).StartsWith(Path.GetFullPath(".xace/unity-authoring-transactions")+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase),"Foreign native transaction");
                    if(action=="commit")UnityAuthoringWriter.Commit(write,AuthoringJson.Text(p,"approval_digest"));
                    else if(action=="recover")AuthoringJson.Need(UnityAuthoringWriter.Rollback(write),"Native rollback conflict");
                    else throw new InvalidDataException("Unknown authoring action");value=write.Journal;
                }
                result=UnityAuthoringReader.Map("ok",true,"result",value);code=0;
            }catch(Exception error){result=UnityAuthoringReader.Map("ok",false,"error",error.ToString());}
            if(output!=null && !File.Exists(output))File.WriteAllText(output,AuthoringJson.Encode(result));EditorApplication.Exit(code);
        }
    }
}

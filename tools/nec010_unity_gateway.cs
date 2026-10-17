using System;
using System.IO;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
namespace Xace.Authoring.Editor
{
    // Explicit isolated proof fixture only. Never installed as a user-project gateway.
    public static class Nec010Gateway
    {
        public static void Run()
        {
            var result=new Dictionary<string,object>();int code=1;
            try
            {
                AuthoringJson.Need(File.Exists("NEC010.fixture"),"Isolated proof marker required");
                var command=AuthoringJson.Obj(AuthoringJson.Parse(File.ReadAllText(".xace/nec010-command.json")));
                var scope=new AuthoringScope(new[]{"Assets/Fixture/World.unity","Assets/Fixture/Template.prefab"});
                EditorSceneManager.OpenScene("Assets/Fixture/World.unity",OpenSceneMode.Single);
                string action=AuthoringJson.Text(command,"action");object value=null;
                if(action=="capture")value=UnityAuthoringReader.Capture(scope);
                else if(action=="prepare")
                {
                    var prepared=UnityAuthoringWriter.PrepareRequest(scope,AuthoringJson.Encode(command["request"]));
                    value=UnityAuthoringReader.Map("directory",prepared.Directory,"receipt",prepared.Journal,"approval_digest",prepared.ApprovalDigest);
                }
                else
                {
                    var p=AuthoringJson.Obj(command["prepared"]);
                    var prepared=new PreparedAuthoringWrite{Directory=AuthoringJson.Text(p,"directory"),Journal=AuthoringJson.Obj(p["receipt"])};
                    AuthoringJson.Need(Path.GetFullPath(prepared.Directory).StartsWith(Path.GetFullPath(".xace/unity-authoring-transactions")+Path.DirectorySeparatorChar),"Fixture transaction scope");
                    if(action=="commit")UnityAuthoringWriter.Commit(prepared,AuthoringJson.Text(p,"approval_digest"));
                    else if(action=="recover")AuthoringJson.Need(UnityAuthoringWriter.Rollback(prepared),"Fixture rollback conflict");
                    else throw new InvalidDataException("Unsupported proof action");
                    value=prepared.Journal;
                }
                result=UnityAuthoringReader.Map("ok",true,"result",value);code=0;
            }
            catch(Exception error){result=UnityAuthoringReader.Map("ok",false,"error",error.ToString());}
            File.WriteAllText(".xace/nec010-result.json",AuthoringJson.Encode(result));EditorApplication.Exit(code);
        }
    }
}

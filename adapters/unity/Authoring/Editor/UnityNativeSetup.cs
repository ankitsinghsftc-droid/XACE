using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
namespace Xace.Authoring.Editor
{
    // Explicit factory for fresh staging projects. Publication is host-owned.
    public static class UnityNativeSetup
    {
        public const string ScenePath="Assets/XACEGenerated/World.unity";
        static void Need(bool value,string message)=>AuthoringJson.Need(value,message);
        static string Text(Dictionary<string,object> row,string key)=>AuthoringJson.Text(row,key);
        static void Identity(GameObject go,Dictionary<string,object> row,string kind,string ns)
        {
            Need(row.Keys.OrderBy(k=>k).SequenceEqual(new[]{"authoring_id","generation","kind","namespace_id","prefab_id"}),"Identity fields");
            Need(Text(row,"kind")==kind && Text(row,"namespace_id")==ns && row["prefab_id"]==null,"Foreign setup identity");
            var id=go.AddComponent<XaceAuthoringIdentity>();id.NamespaceId=ns;id.AuthoringId=Text(row,"authoring_id");id.Kind=kind;id.Generation=Text(row,"generation");
            UnityAuthoringReader.Identity(id);
        }
        public static void Run()
        {
            const string output=".xace/result-create.json";
            if(File.Exists(output)){EditorApplication.Exit(2);return;}
            try {
                var spec=AuthoringJson.Obj(AuthoringJson.Parse(File.ReadAllText(".xace/spec.json")));
                var result=Create(spec,AuthoringJson.Hash(AuthoringJson.Encode(spec)));
                File.WriteAllText(output,AuthoringJson.Encode(UnityAuthoringReader.Map("ok",true,"result",result)));EditorApplication.Exit(0);
            }catch(Exception error){Debug.LogException(error);File.WriteAllText(output,AuthoringJson.Encode(UnityAuthoringReader.Map("ok",false,"error",error.ToString())));EditorApplication.Exit(1);}
        }
        public static Dictionary<string,object> Create(Dictionary<string,object> spec,string approvedDigest)
        {
            UnityAuthoringReader.EditMode();
            Need(AuthoringJson.Hash(AuthoringJson.Encode(spec))==approvedDigest,"Setup differs from approval");
            Need(spec.Count==3 && Text(spec,"schema")=="xace.unity_native_setup.v1","Setup schema");
            var approval=AuthoringJson.Obj(AuthoringJson.Parse(File.ReadAllText(".xace/native-setup-approved.json")));
            Need(Text(approval,"digest")==approvedDigest && Path.GetFullPath(Text(approval,"stage_root"))==Path.GetFullPath("."),"Foreign setup stage");
            UnityAuthoringReader.AssetPath(ScenePath);Need(!Directory.Exists("Assets/XACEGenerated"),"Existing generated content must not be replaced");
            var sceneId=AuthoringJson.Obj(spec["scene"]);string ns=Text(sceneId,"namespace_id");
            var rows=spec["objects"] as List<object>;Need(rows!=null && rows.Count>0 && rows.Count<=128,"Setup object limit");
            var seen=new HashSet<string>{Text(sceneId,"authoring_id")};
            var first=SceneManager.GetSceneAt(0);
            bool emptyStartup=SceneManager.sceneCount==1 && first.path=="" && first.rootCount==0 && !first.isDirty;
            for(int i=0;i<SceneManager.sceneCount;i++)Need(emptyStartup || (!SceneManager.GetSceneAt(i).isDirty && SceneManager.GetSceneAt(i).path!=""),"Save existing editor scenes before setup");
            var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,emptyStartup?NewSceneMode.Single:NewSceneMode.Additive);
            try
            {
                var holder=new GameObject("XACEWorld");SceneManager.MoveGameObjectToScene(holder,scene);Identity(holder,sceneId,"scene",ns);
                foreach(var raw in rows)
                {
                    var row=AuthoringJson.Obj(raw);Need(row.Count==3,"Setup object fields");var id=AuthoringJson.Obj(row["identity"]);
                    Need(seen.Add(Text(id,"authoring_id")),"Duplicate setup identity");
                    string name=Text(row,"name");Need(name.Length>0 && name.Length<=128,"Setup name");
                    var fields=AuthoringJson.Obj(row["fields"]);Need(new[]{"transform.position","transform.rotation","transform.scale"}.All(fields.ContainsKey) && fields.Keys.All(k=>new[]{"transform.position","transform.rotation","transform.scale","presentation.asset","input.action","binding.playback"}.Contains(k)),"Explicit supported setup fields required");
                    var go=new GameObject(name);SceneManager.MoveGameObjectToScene(go,scene);Identity(go,id,"object",ns);
                    if(fields.ContainsKey("presentation.asset")){go.AddComponent<MeshFilter>();go.AddComponent<MeshRenderer>();}
                    if(fields.ContainsKey("input.action") || fields.ContainsKey("binding.playback"))go.AddComponent<XaceAuthoringBinding>();
                    UnityAuthoringWriter.Apply(go,fields);
                }
                Directory.CreateDirectory("Assets/XACEGenerated");AssetDatabase.Refresh();
                Need(EditorSceneManager.SaveScene(scene,ScenePath),"Native scene save failed");AssetDatabase.SaveAssets();
            }
            finally {if(!emptyStartup)EditorSceneManager.CloseScene(scene,true);}
            var reopened=EditorSceneManager.OpenScene(ScenePath,emptyStartup?OpenSceneMode.Single:OpenSceneMode.Additive);
            try {return UnityAuthoringReader.Map("schema","xace.unity_native_setup_result.v1","inventory",UnityAuthoringReader.Capture(new AuthoringScope(new[]{ScenePath})),"request_digest",approvedDigest);}
            finally {if(!emptyStartup)EditorSceneManager.CloseScene(reopened,true);}
        }
    }
}

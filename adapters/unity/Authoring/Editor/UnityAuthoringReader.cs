using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Xace.Authoring.Editor
{
    // Opt-in API for an already open, trusted editor project. Never opens another
    // project, imports user scripts, or starts Play to discover authored content.
    public sealed class AuthoringScope
    {
        readonly string[] documents;
        public string[] Documents=>(string[])documents.Clone();
        public AuthoringScope(IEnumerable<string> approvedSavedDocuments)
        {
            UnityAuthoringReader.EditMode();
            documents=approvedSavedDocuments.OrderBy(p=>p,StringComparer.Ordinal).ToArray();
            AuthoringJson.Need(Documents.Length>0 && Documents.Length<=10000 && Documents.Distinct().Count()==Documents.Length,"Invalid document scope");
            foreach(var p in Documents){UnityAuthoringReader.AssetPath(p);AuthoringJson.Need(p.EndsWith(".unity",StringComparison.Ordinal)||p.EndsWith(".prefab",StringComparison.Ordinal),"Unsupported document");AuthoringJson.Need(File.Exists(p),"Unsaved document");}
        }
        public void Contains(string path){AuthoringJson.Need(Array.IndexOf(Documents,path)>=0,"Outside approved document set");}
    }

    public static class UnityAuthoringReader
    {
        public const string Version="unity.authoring.reader.v1";
        public const string WriterVersion="unity.authoring.writer.v1";
        public const string EngineVersion="6000.4.9f1";
        public static Dictionary<string,object> Map(params object[] pairs)
        {var result=new Dictionary<string,object>(StringComparer.Ordinal);for(int i=0;i<pairs.Length;i+=2)result.Add((string)pairs[i],pairs[i+1]);return result;}
        public static void EditMode()
        {AuthoringJson.Need(Application.unityVersion==EngineVersion,"Uncertified Unity version");AuthoringJson.Need(!EditorApplication.isPlayingOrWillChangePlaymode && !EditorApplication.isCompiling && !EditorApplication.isUpdating,"Editor not idle in Edit mode");}
        public static void AssetPath(string path)
        {
            AuthoringJson.Need(path!=null && path.StartsWith("Assets/",StringComparison.Ordinal) && !path.Contains('\\') && !path.Split('/').Any(p=>p==".."||p=="."||p==""),"Unsafe asset path");
            var full=Path.GetFullPath(path);var root=Path.GetFullPath("Assets")+Path.DirectorySeparatorChar;
            AuthoringJson.Need(full.StartsWith(root,StringComparison.OrdinalIgnoreCase),"Asset escaped project");
            for(var current=new FileInfo(full) as FileSystemInfo;current!=null;current=current is FileInfo f?f.Directory:((DirectoryInfo)current).Parent)
                if(current.Exists)AuthoringJson.Need((current.Attributes&FileAttributes.ReparsePoint)==0,"Linked asset path");
        }
        public static string Document(GameObject go)
        {return EditorUtility.IsPersistent(go)?AssetDatabase.GetAssetPath(go):go.scene.path;}
        public static string Locator(Object obj)
        {var id=GlobalObjectId.GetGlobalObjectIdSlow(obj);AuthoringJson.Need(id.identifierType!=0,"Object has no saved GlobalObjectId");return id.ToString();}
        public static void Identity(XaceAuthoringIdentity id)
        {
            AuthoringJson.Need(id!=null && Regex.IsMatch(id.NamespaceId??"","^[0-9a-f]{32}$") && Regex.IsMatch(id.AuthoringId??"","^[0-9a-f]{32}$"),"Missing/corrupt authoring identity");
            AuthoringJson.Need(new[]{"scene","prefab_definition","prefab_instance","object"}.Contains(id.Kind),"Invalid identity kind");
            AuthoringJson.Need(long.TryParse(id.Generation,NumberStyles.None,CultureInfo.InvariantCulture,out var generation) && generation>0 && generation.ToString(CultureInfo.InvariantCulture)==id.Generation,"Invalid identity generation");
            AuthoringJson.Need((id.Kind=="prefab_instance")==!string.IsNullOrEmpty(id.PrefabId),"Invalid prefab definition reference");
        }
        // Explicit enrollment only: no ID generation or repair during capture/reload.
        public static void Attach(AuthoringScope scope, GameObject go, string ns, string id, string kind, string generation="1", string prefabId="")
        {
            EditMode();scope.Contains(Document(go));
            AuthoringJson.Need(go.GetComponent<XaceAuthoringIdentity>()==null,"Identity already attached; explicit reviewed repair required");
            int group=Undo.GetCurrentGroup();Undo.IncrementCurrentGroup();group=Undo.GetCurrentGroup();
            try{var metadata=Undo.AddComponent<XaceAuthoringIdentity>(go);
                metadata.NamespaceId=ns;metadata.AuthoringId=id;metadata.Kind=kind;metadata.Generation=generation;metadata.PrefabId=prefabId;Identity(metadata);
                if(PrefabUtility.IsPartOfPrefabInstance(go))PrefabUtility.RecordPrefabInstancePropertyModifications(metadata);
                EditorUtility.SetDirty(metadata);Undo.CollapseUndoOperations(group);}
            catch{Undo.RevertAllDownToGroup(group);throw;}
        }
        public static void ReidentifyDuplicate(AuthoringScope scope,GameObject go,string expectedLocator,string expectedDocumentFingerprint,string newAuthoringId)
        {
            EditMode();string path=Document(go);scope.Contains(path);
            AuthoringJson.Need(!Dirty(path) && Locator(go)==expectedLocator && Fingerprint(path)==expectedDocumentFingerprint,"Stale identity repair");
            var metadata=go.GetComponent<XaceAuthoringIdentity>();Identity(metadata);
            AuthoringJson.Need(Regex.IsMatch(newAuthoringId??"","^[0-9a-f]{32}$") && newAuthoringId!=metadata.AuthoringId,"Explicit distinct identity required");
            Undo.RecordObject(metadata,"Assign reviewed duplicate identity");metadata.AuthoringId=newAuthoringId;metadata.Generation="1";
            if(PrefabUtility.IsPartOfPrefabInstance(metadata))PrefabUtility.RecordPrefabInstancePropertyModifications(metadata);
            EditorUtility.SetDirty(metadata);
        }
        public static string Decimal(float value)
        {
            AuthoringJson.Need(!float.IsNaN(value)&&!float.IsInfinity(value),"Nonfinite native number");
            // Round-trip float text, expanded without an exponent for NEC-003.
            string text=value.ToString("R",CultureInfo.InvariantCulture);
            int e=text.IndexOfAny(new[]{'e','E'});if(e<0)return text=="-0"?"0":text;
            int exponent=int.Parse(text.Substring(e+1),CultureInfo.InvariantCulture);string mantissa=text.Substring(0,e);bool negative=mantissa.StartsWith("-");if(negative)mantissa=mantissa.Substring(1);
            int point=mantissa.IndexOf('.');if(point<0)point=mantissa.Length;string digits=mantissa.Replace(".","");point+=exponent;
            string expanded=point<=0?"0."+new string('0',-point)+digits:point>=digits.Length?digits+new string('0',point-digits.Length):digits.Insert(point,".");
            return (negative?"-":"")+expanded;
        }
        public static Dictionary<string,object> Vector(Vector3 value)
        {return Map("x",Decimal(value.x),"y",Decimal(value.y),"z",Decimal(value.z));}
        static Dictionary<string,object> Rotation(Quaternion value)
        {return Map("x",Decimal(value.x),"y",Decimal(value.y),"z",Decimal(value.z),"w",Decimal(value.w));}
        public static Dictionary<string,object> Asset(Object value)
        {
            string guid=null;long local=0;
            AuthoringJson.Need(value!=null && AssetDatabase.TryGetGUIDAndLocalFileIdentifier(value,out guid,out local),"Unsaved/builtin resource is not a linked asset");
            string type=value is Mesh?"MESH":value is Material?"MATERIAL":value is AudioClip?"AUDIO_CLIP":value is AnimationClip?"ANIMATION_CLIP":value is RuntimeAnimatorController?"ANIMATION_CONTROLLER":null;
            AuthoringJson.Need(type!=null,"Unsupported typed resource");
            return Map("asset_id","unity_"+guid+"_"+local.ToString(CultureInfo.InvariantCulture),"asset_type",type,"status","LINKED","resolved_path",AssetDatabase.GetAssetPath(value));
        }
        public static string Fingerprint(string document)
        {
            AssetPath(document);var paths=new SortedSet<string>(AssetDatabase.GetDependencies(document,true),StringComparer.Ordinal){document,"ProjectSettings/InputManager.asset"};
            var inventory=new List<object>();
            foreach(var path in paths)
            {
                AuthoringJson.Need(File.Exists(path),"Missing dependency: "+path);
                foreach(var asset in AssetDatabase.LoadAllAssetsAtPath(path))
                    AuthoringJson.Need(asset==null || !EditorUtility.IsDirty(asset),"Unsaved dependency: "+path);
                // Dependencies outside Assets/ can be read, never written. Include import settings.
                inventory.Add(Map("path",path,"sha256",AuthoringJson.Hash(File.ReadAllBytes(path)),"meta",File.Exists(path+".meta")?AuthoringJson.Hash(File.ReadAllBytes(path+".meta")):null));
            }
            return AuthoringJson.Hash(AuthoringJson.Encode(inventory));
        }
        public static bool Dirty(string path)
        {
            var scene=SceneManager.GetSceneByPath(path);if(scene.IsValid() && scene.isLoaded)return scene.isDirty;
            var stage=PrefabStageUtility.GetCurrentPrefabStage();if(stage!=null && stage.assetPath==path)return stage.scene.isDirty;
            var asset=AssetDatabase.LoadMainAssetAtPath(path);
            if(asset is GameObject root)
                foreach(var transform in root.GetComponentsInChildren<Transform>(true))
                    if(EditorUtility.IsDirty(transform.gameObject) || transform.GetComponents<Component>().Any(c=>c!=null&&EditorUtility.IsDirty(c)))return true;
            return asset!=null && EditorUtility.IsDirty(asset);
        }
        public static bool InputExists(string name)
        {
            var settings=AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/InputManager.asset");if(settings.Length==0)return false;
            AuthoringJson.Need(!EditorUtility.IsDirty(settings[0]),"Unsaved InputManager settings");
            using(var serialized=new SerializedObject(settings[0]))
            {var axes=serialized.FindProperty("m_Axes");for(int i=0;i<axes.arraySize;i++)if(axes.GetArrayElementAtIndex(i).FindPropertyRelative("m_Name").stringValue==name)return true;}
            return false;
        }
        internal static Dictionary<string,object> Fields(GameObject go)
        {
            var fields=Map();using(var transform=new SerializedObject(go.transform))
            {fields["transform.position"]=Vector(transform.FindProperty("m_LocalPosition").vector3Value);fields["transform.rotation"]=Rotation(transform.FindProperty("m_LocalRotation").quaternionValue);fields["transform.scale"]=Vector(transform.FindProperty("m_LocalScale").vector3Value);}
            fields["native.name"]=go.name;
            var box=go.GetComponent<BoxCollider>();if(box!=null)
            {using(var serialized=new SerializedObject(box)){fields["collision.size"]=Vector(serialized.FindProperty("m_Size").vector3Value);fields["collision.offset"]=Vector(serialized.FindProperty("m_Center").vector3Value);fields["collision.trigger"]=serialized.FindProperty("m_IsTrigger").boolValue;}fields["collision.shape"]="BOX";fields["collision.profile"]="world.aabb.v1";}
            var mesh=go.GetComponent<MeshFilter>();if(mesh!=null && mesh.sharedMesh!=null)fields["presentation.asset"]=Asset(mesh.sharedMesh);
            var renderer=go.GetComponent<Renderer>();if(renderer!=null && renderer.sharedMaterials.Length==1 && renderer.sharedMaterial!=null)fields["presentation.material"]=Asset(renderer.sharedMaterial);
            var binding=go.GetComponent<XaceAuthoringBinding>();if(binding!=null)
            {
                if(!string.IsNullOrEmpty(binding.InputAction)){AuthoringJson.Need(InputExists(binding.InputAction),"Input action absent from saved InputManager");fields["input.action"]=binding.InputAction;}
                if(!string.IsNullOrEmpty(binding.BindingId))fields["binding.playback"]=Map("binding_id",binding.BindingId,"event_name",binding.EventName,"playback_kind",binding.PlaybackKind,"asset",Asset(binding.Resource));
            }
            return fields;
        }
        public static List<object> Opaque(GameObject go,string documentFingerprint)
        {
            var entries=new List<object>();int index=0;
            entries.Add(Map("id","native.gameobject","sha256",UnityAuthoringPreservation.Fingerprint(go),"critical",false,"reason","Unowned GameObject properties retained"));
            entries.Add(Map("id","native.transform","sha256",UnityAuthoringPreservation.Fingerprint(go.transform,go.GetComponent<XaceAuthoringIdentity>()?.Kind!="scene"),"critical",false,"reason","Unowned Transform properties retained"));
            foreach(var component in go.GetComponents<Component>())
            {
                AuthoringJson.Need(component!=null,"Missing script must be resolved before capture");
                if(component is Transform || component is XaceAuthoringIdentity || component is XaceAuthoringBinding)continue;
                // Even supported components retain their unowned serialized properties.
                bool critical=!(component is MeshFilter || component is Renderer || component is Light || component is BoxCollider);
                entries.Add(Map("id","component:"+(index++).ToString(CultureInfo.InvariantCulture)+":"+component.GetType().FullName,
                    "sha256",UnityAuthoringPreservation.Fingerprint(component),"critical",critical,
                    "reason",critical?"Native behavior retained; translation/adoption review required":"Native serialized properties retained; only declared fields are mapped"));
            }
            return entries;
        }
        static List<GameObject> ObjectsAt(string path)
        {
            var objects=new List<GameObject>();
            if(path.EndsWith(".unity",StringComparison.Ordinal))
            {var scene=SceneManager.GetSceneByPath(path);AuthoringJson.Need(scene.IsValid()&&scene.isLoaded,"Capture requires an already open scene");UnityAuthoringNotifications.RequireSavedReload(path);foreach(var root in scene.GetRootGameObjects())objects.AddRange(root.GetComponentsInChildren<Transform>(true).Select(t=>t.gameObject));}
            else{var root=AssetDatabase.LoadAssetAtPath<GameObject>(path);AuthoringJson.Need(root!=null,"Cannot read prefab");objects.AddRange(root.GetComponentsInChildren<Transform>(true).Select(t=>t.gameObject));}
            return objects;
        }
        public static Dictionary<string,object> Discover(AuthoringScope scope)
        {
            // First-adoption inventory before metadata attachment. Locators are not
            // authoring IDs; this does not invent entities, IDs or canonical defaults.
            EditMode();var documents=new List<object>();int count=0;
            foreach(string path in scope.Documents)
            {
                AuthoringJson.Need(!Dirty(path),"Dirty document; save before discovery");string before=Fingerprint(path);var objects=new List<object>();
                foreach(var go in ObjectsAt(path).OrderBy(g=>Locator(g),StringComparer.Ordinal))
                {
                    AuthoringJson.Need(++count<=10000,"Discovery object count limit");object fields=null;string blocked=null;
                    try{fields=Fields(go);}catch(InvalidDataException error){blocked=error.Message;}
                    var source=PrefabUtility.GetCorrespondingObjectFromSource(go);
                    objects.Add(Map("locator",Locator(go),"parent_locator",go.transform.parent==null?null:Locator(go.transform.parent.gameObject),
                        "prefab_source_locator",source==null?null:Locator(source),"name",go.name,"registered",go.GetComponent<XaceAuthoringIdentity>()!=null,
                        "fields",fields,"blocking_reason",blocked,"opaque",Opaque(go,before)));
                }
                string after=Fingerprint(path);AuthoringJson.Need(before==after&&!Dirty(path),"Discovery source changed");
                documents.Add(Map("path",path,"document_id",AssetDatabase.AssetPathToGUID(path),"before",before,"after",after,"objects",objects));
            }
            var result=Map("schema","xace.unity_native_discovery.v1","engine_version",Application.unityVersion,"reader_version",Version,"documents",documents);AuthoringJson.Encode(result);return result;
        }
        public static Dictionary<string,object> Capture(AuthoringScope scope)
        {
            EditMode();var before=scope.Documents.ToDictionary(p=>p,Fingerprint,StringComparer.Ordinal);
            var rows=Map();var docs=new List<object>();string ns=null;int count=0;
            foreach(var path in scope.Documents)
            {
                AuthoringJson.Need(!Dirty(path),"Dirty document; save and recapture");
                var gameObjects=ObjectsAt(path);
                var definitions=gameObjects.Where(g=>g.GetComponent<XaceAuthoringIdentity>()?.Kind==(path.EndsWith(".unity")?"scene":"prefab_definition")).ToArray();
                AuthoringJson.Need(definitions.Length==1,"Document must have exactly one explicit scene/prefab definition identity");
                var definition=definitions[0].GetComponent<XaceAuthoringIdentity>();
                foreach(var go in gameObjects)
                {
                    AuthoringJson.Need(++count<=10000,"Object count limit");var id=go.GetComponent<XaceAuthoringIdentity>();Identity(id);
                    if(id.Kind=="scene")AuthoringJson.Need(go.transform.parent==null && go.transform.childCount==0 && go.GetComponents<Component>().Length==2,"Scene identity holder must not hide native content");
                    if(!EditorUtility.IsPersistent(go) && PrefabUtility.IsAnyPrefabInstanceRoot(go))AuthoringJson.Need(id.Kind=="prefab_instance","Prefab instance must have distinct instance metadata");
                    if(ns==null)ns=id.NamespaceId;AuthoringJson.Need(id.NamespaceId==ns && !rows.ContainsKey(id.AuthoringId),"Foreign/duplicate authoring metadata; no automatic repair");
                    string parent=null;if(go.transform.parent!=null){var p=go.transform.parent.GetComponent<XaceAuthoringIdentity>();Identity(p);parent=p.AuthoringId;}
                    if(id.Kind=="prefab_instance")
                    {var source=PrefabUtility.GetCorrespondingObjectFromSource(go);AuthoringJson.Need(source!=null && source.GetComponent<XaceAuthoringIdentity>()?.AuthoringId==id.PrefabId,"Prefab definition drift");}
                    rows.Add(id.AuthoringId,Map("metadata",Map("schema","xace.native_identity.v1","namespace_id",id.NamespaceId,"authoring_id",id.AuthoringId,"kind",id.Kind,"generation",id.Generation),
                        "locator",Map("engine","unity","document_id",AssetDatabase.AssetPathToGUID(path),"object_id",Locator(go)),
                        "scene_id",path.EndsWith(".unity") && id!=definition?definition.AuthoringId:null,"prefab_id",string.IsNullOrEmpty(id.PrefabId)?null:id.PrefabId,
                        "parent_id",parent,"fields",id.Kind=="scene"?Map():Fields(go),"dependencies",new List<object>(),"opaque",Opaque(go,before[path]),"name",go.name,"path_hint",path));
                }
                var after=Fingerprint(path);AuthoringJson.Need(before[path]==after && !Dirty(path),"Source changed during capture");
                docs.Add(Map("id",AssetDatabase.AssetPathToGUID(path),"before",before[path],"after",after,"dirty",false));
            }
            // Explicit closed selection; no inferred behavior from names or missing rows.
            foreach(var value in rows.Values)
            {var row=AuthoringJson.Obj(value);foreach(var key in new[]{"parent_id","prefab_id","scene_id"})if(row[key]!=null)AuthoringJson.Need(rows.ContainsKey((string)row[key]),"Selected scope omits required dependency");}
            docs.Sort((a,b)=>StringComparer.Ordinal.Compare(AuthoringJson.Text(AuthoringJson.Obj(a),"id"),AuthoringJson.Text(AuthoringJson.Obj(b),"id")));
            var result=Map("schema","xace.unity_authoring_inventory.v1","namespace_id",ns,"source",Map("engine","unity","engine_version",Application.unityVersion,"reader_version",Version,"materializer_version",WriterVersion,"play_mode",false,"documents",docs),"objects",rows);
            AuthoringJson.Encode(result);return result;
        }
    }

    [InitializeOnLoad]
    public static class UnityAuthoringNotifications
    {
        public static bool RescanRequired {get;private set;}=true;
        public static string LastCaptureDigest {get;private set;}
        static UnityAuthoringNotifications()
        {
            EditorApplication.hierarchyChanged+=Invalidate;EditorApplication.projectChanged+=Invalidate;
            Undo.undoRedoPerformed+=Invalidate;EditorSceneManager.sceneSaved+=Saved;
            EditorApplication.playModeStateChanged+=PlayChanged;
            EditorSceneManager.sceneOpened+=(scene,mode)=>Saved(scene);
            ObjectChangeEvents.changesPublished+=Changed;
        }
        static void Changed(ref ObjectChangeEventStream stream){Invalidate();}
        static void PlayChanged(PlayModeStateChange state)
        {Invalidate();if(state==PlayModeStateChange.ExitingEditMode)SessionState.SetInt("XACE.Authoring.PlayEpoch",checked(SessionState.GetInt("XACE.Authoring.PlayEpoch",0)+1));}
        static void Saved(Scene scene)
        {
            Invalidate();if(EditorApplication.isPlayingOrWillChangePlaymode || string.IsNullOrEmpty(scene.path) || !File.Exists(scene.path))return;
            string guid=AssetDatabase.AssetPathToGUID(scene.path);
            SessionState.SetInt("XACE.Authoring.OpenEpoch:"+guid,SessionState.GetInt("XACE.Authoring.PlayEpoch",0));
            SessionState.SetString("XACE.Authoring.SavedSource:"+guid,UnityAuthoringReader.Fingerprint(scene.path));
        }
        public static void RequireSavedReload(string path)
        {
            string guid=AssetDatabase.AssetPathToGUID(path);
            AuthoringJson.Need(SessionState.GetInt("XACE.Authoring.OpenEpoch:"+guid,0)==SessionState.GetInt("XACE.Authoring.PlayEpoch",0),"Scene crossed Play boundary; explicitly reopen saved scene before capture");
            AuthoringJson.Need(SessionState.GetString("XACE.Authoring.SavedSource:"+guid,"")==UnityAuthoringReader.Fingerprint(path),"Saved document/dependency changed without matching editor load/save; refresh in Unity and reopen before capture");
        }
        public static void Invalidate(){RescanRequired=true;}
        public static Dictionary<string,object> Rescan(AuthoringScope scope)
        {var inventory=UnityAuthoringReader.Capture(scope);LastCaptureDigest=AuthoringJson.Hash(AuthoringJson.Encode(inventory));RescanRequired=false;return inventory;}
        // Every rescan is complete, even if notifications were missed or domain reload is disabled.
    }
}

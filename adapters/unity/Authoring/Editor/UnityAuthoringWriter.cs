using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Object=UnityEngine.Object;

namespace Xace.Authoring.Editor
{
    public sealed class AuthoringEdit
    {
        public string Document;
        public string AuthoringId;
        // Values from a verified NEC-003 canonical proposal, not native decimal inputs.
        public Dictionary<string,object> Fields;
    }
    public sealed class PreparedAuthoringWrite
    {
        internal string Directory;
        internal Dictionary<string,object> Journal;
        public string ReceiptPath=>Path.Combine(Directory,"journal.json");
        public string ApprovalDigest=>AuthoringJson.Hash(AuthoringJson.Encode(Journal));
    }
    public static class UnityAuthoringWriter
    {
        static Dictionary<string,object> Map(params object[] pairs)=>UnityAuthoringReader.Map(pairs);
        static void Need(bool condition,string message)=>AuthoringJson.Need(condition,message);
        static string FileHash(string path)=>AuthoringJson.Hash(File.ReadAllBytes(path));
        static void ReplaceFile(string temporary,string destination,string backup)
        {
            string expected=FileHash(temporary);
            for(int attempt=0;;attempt++)
            {
                try{File.Replace(temporary,destination,backup);return;}
                catch(IOException)
                {
                    // Windows indexing/AV may briefly hold a just-published file.
                    // Retry the same atomic operation; never fall back to delete/write.
                    if(File.Exists(destination) && FileHash(destination)==expected && (backup==null || File.Exists(backup)))return;
                    if(attempt>=7 || !File.Exists(temporary))throw;
                    System.Threading.Thread.Sleep(50);
                }
            }
        }
        static void Persist(PreparedAuthoringWrite write)
        {
            string temporary=write.ReceiptPath+".tmp";
            using(var stream=new FileStream(temporary,FileMode.Create,FileAccess.Write,FileShare.None))
            {var bytes=System.Text.Encoding.UTF8.GetBytes(AuthoringJson.Encode(write.Journal));stream.Write(bytes,0,bytes.Length);stream.Flush(true);}
            if(File.Exists(write.ReceiptPath))ReplaceFile(temporary,write.ReceiptPath,null);else File.Move(temporary,write.ReceiptPath);
        }
        static long Raw(object value)
        {Need(value is string && long.TryParse((string)value,NumberStyles.AllowLeadingSign,CultureInfo.InvariantCulture,out _),"Expected fixed64 string");long raw=long.Parse((string)value,CultureInfo.InvariantCulture);Need(raw.ToString(CultureInfo.InvariantCulture)==(string)value,"Noncanonical fixed64");return raw;}
        static float Float(long raw)
        {
            float result=(float)((decimal)raw/1000000m);
            Need(decimal.TryParse(UnityAuthoringReader.Decimal(result),NumberStyles.AllowLeadingSign|NumberStyles.AllowDecimalPoint,CultureInfo.InvariantCulture,out var back) && back*1000000m==raw,"Native float cannot preserve approved fixed64 value");return result;
        }
        static Vector3 Vector(object value,bool reflect,bool position)
        {
            var v=AuthoringJson.Obj(value);Need(v.Keys.OrderBy(x=>x).SequenceEqual(new[]{"x","y","z"}),"Vector fields");
            long x=Raw(v["x"]),y=Raw(v["y"]),z=Raw(v["z"]);
            if(position)Need(x>=-8192000000L&&x<=8192000000L&&y>=-8192000000L&&y<=8192000000L&&z>=-8192000000L&&z<=8192000000L,"World bounds");
            return new Vector3(Float(x),Float(y),Float(reflect?checked(-z):z));
        }
        static Object Resource(object value)
        {
            var asset=AuthoringJson.Obj(value);string path=AuthoringJson.Text(asset,"resolved_path");UnityAuthoringReader.AssetPath(path);
            foreach(var candidate in AssetDatabase.LoadAllAssetsAtPath(path))
            {try{if(AuthoringJson.Encode(UnityAuthoringReader.Asset(candidate))==AuthoringJson.Encode(asset))return candidate;}catch(InvalidDataException){}}
            throw new InvalidDataException("Resource identity/type/status mismatch");
        }
        static void Apply(GameObject go,Dictionary<string,object> fields)
        {
            Need(fields!=null && fields.Count>0 && fields.Count<=14,"Empty/oversized edit");
            foreach(var field in fields.OrderBy(p=>p.Key,StringComparer.Ordinal))
            {
                switch(field.Key)
                {
                    case "transform.position":go.transform.localPosition=Vector(field.Value,true,true);break;
                    case "transform.scale":var scale=Vector(field.Value,false,false);Need(scale.x!=0&&scale.y!=0&&scale.z!=0,"Zero scale");go.transform.localScale=scale;break;
                    case "transform.rotation":
                        var q=AuthoringJson.Obj(field.Value);Need(q.Keys.OrderBy(x=>x).SequenceEqual(new[]{"w","x","y","z"}),"Quaternion fields");
                        decimal norm=q.Values.Sum(v=>(decimal)Raw(v)*Raw(v));Need(Math.Abs(norm-1000000000000m)<=4000000m,"Nonunit quaternion");
                        go.transform.localRotation=new Quaternion(Float(checked(-Raw(q["x"]))),Float(checked(-Raw(q["y"]))),Float(Raw(q["z"])),Float(Raw(q["w"])));break;
                    case "collision.size":var size=Vector(field.Value,false,true);Need(size.x>0&&size.y>0&&size.z>0,"Invalid collider size");Need(go.GetComponent<BoxCollider>()!=null,"No mapped collider");go.GetComponent<BoxCollider>().size=size;break;
                    case "collision.offset":Need(go.GetComponent<BoxCollider>()!=null,"No mapped collider");go.GetComponent<BoxCollider>().center=Vector(field.Value,true,true);break;
                    case "collision.trigger":Need(go.GetComponent<BoxCollider>()!=null && field.Value is bool,"No collider/bad trigger");go.GetComponent<BoxCollider>().isTrigger=(bool)field.Value;break;
                    case "input.action":
                        var input=go.GetComponent<XaceAuthoringBinding>();Need(input!=null && field.Value is string,"No explicit input binding");
                        Need(UnityAuthoringReader.InputExists((string)field.Value),"Unknown input action");input.InputAction=(string)field.Value;break;
                    case "binding.playback":
                        var binding=go.GetComponent<XaceAuthoringBinding>();Need(binding!=null,"No explicit semantic binding");var value=AuthoringJson.Obj(field.Value);
                        Need(value.Keys.OrderBy(x=>x).SequenceEqual(new[]{"asset","binding_id","event_name","playback_kind"}),"Binding fields");
                        var resource=Resource(value["asset"]);string playback=AuthoringJson.Text(value,"playback_kind");
                        Need((playback=="Animation" && (resource is AnimationClip || resource is RuntimeAnimatorController)) || (playback=="Audio" && resource is AudioClip),"Unsupported playback/type pairing");
                        binding.BindingId=AuthoringJson.Text(value,"binding_id");binding.EventName=AuthoringJson.Text(value,"event_name");binding.PlaybackKind=playback;binding.Resource=resource;break;
                    default:throw new InvalidDataException("Field not in Unity writer allowlist: "+field.Key);
                }
            }
            // Keep unrelated overrides; record only the actual changed serialized objects.
            foreach(var component in go.GetComponents<Component>())
                if(component is Transform || component is BoxCollider || component is XaceAuthoringBinding)
                {EditorUtility.SetDirty(component);if(PrefabUtility.IsPartOfPrefabInstance(component))PrefabUtility.RecordPrefabInstancePropertyModifications(component);}
            var collider=go.GetComponent<BoxCollider>();
            if(collider!=null)
            {
                Need(go.transform.parent==null && go.transform.localRotation==Quaternion.identity && go.transform.localScale==Vector3.one,"Unsupported authoritative geometry transform");
                foreach(var axis in new[]{0,1,2})
                {
                    decimal size=decimal.Parse(UnityAuthoringReader.Decimal(collider.size[axis]),CultureInfo.InvariantCulture)*1000000m;
                    decimal center=(decimal.Parse(UnityAuthoringReader.Decimal(collider.center[axis]),CultureInfo.InvariantCulture)+decimal.Parse(UnityAuthoringReader.Decimal(go.transform.localPosition[axis]),CultureInfo.InvariantCulture))*1000000m;
                    Need(size>0 && size<=8192000000m && size%2==0 && Math.Abs(center)+size/2<=8192000000m,"Unsupported AABB dimensions/bounds");
                }
            }
        }
        static void VerifyFields(GameObject go,Dictionary<string,object> approved)
        {
            var observed=UnityAuthoringReader.Fields(go);
            foreach(var field in approved)
            {
                object actual=observed[field.Key];
                if(field.Key.StartsWith("transform.") || field.Key=="collision.size" || field.Key=="collision.offset")
                {
                    var vector=AuthoringJson.Obj(actual);var converted=Map();
                    foreach(var axis in vector.Keys)
                    {decimal raw=decimal.Round(decimal.Parse((string)vector[axis],CultureInfo.InvariantCulture)*1000000m,0,MidpointRounding.ToEven);if((field.Key=="transform.position"||field.Key=="collision.offset") && axis=="z")raw=-raw;if(field.Key=="transform.rotation" && (axis=="x"||axis=="y"))raw=-raw;converted[axis]=raw.ToString("0",CultureInfo.InvariantCulture);}
                    if(field.Key=="transform.rotation")
                    {long sign=new[]{"w","x","y","z"}.Select(k=>Raw(converted[k])).First(n=>n!=0);if(sign<0)foreach(var key in converted.Keys.ToArray())converted[key]=checked(-Raw(converted[key])).ToString(CultureInfo.InvariantCulture);}
                    actual=converted;
                }
                Need(AuthoringJson.Encode(actual)==AuthoringJson.Encode(field.Value),"Native save readback does not match approved field: "+field.Key);
            }
        }
        static void VerifySaved(string staged,IEnumerable<AuthoringEdit> edits)
        {
            var scene=default(UnityEngine.SceneManagement.Scene);GameObject prefab=null;
            try
            {
                GameObject[] roots;if(staged.EndsWith(".unity")){scene=EditorSceneManager.OpenScene(staged,OpenSceneMode.Additive);roots=scene.GetRootGameObjects();}else{prefab=PrefabUtility.LoadPrefabContents(staged);roots=new[]{prefab};}
                var objects=roots.SelectMany(r=>r.GetComponentsInChildren<XaceAuthoringIdentity>(true)).ToArray();
                foreach(var edit in edits){var matches=objects.Where(o=>o.AuthoringId==edit.AuthoringId).ToArray();Need(matches.Length==1,"Readback identity mismatch");VerifyFields(matches[0].gameObject,edit.Fields);}
            }
            finally{if(prefab!=null)PrefabUtility.UnloadPrefabContents(prefab);if(scene.IsValid())EditorSceneManager.CloseScene(scene,true);}
        }
        public static PreparedAuthoringWrite Prepare(AuthoringScope scope,string expectedInventoryDigest,IEnumerable<AuthoringEdit> proposed)
        {
            UnityAuthoringReader.EditMode();var inventory=UnityAuthoringReader.Capture(scope);
            Need(AuthoringJson.Hash(AuthoringJson.Encode(inventory))==expectedInventoryDigest,"Stale capture");
            var edits=proposed.Select(e=>new AuthoringEdit{Document=e.Document,AuthoringId=e.AuthoringId,Fields=AuthoringJson.Obj(AuthoringJson.Parse(AuthoringJson.Encode(e.Fields)))}).ToArray();Need(edits.Length>0&&edits.Length<=10000,"Edit count");
            foreach(var edit in edits)scope.Contains(edit.Document);
            Need(edits.Select(e=>e.Document+":"+e.AuthoringId).Distinct().Count()==edits.Length,"Duplicate edit target");
            string id=Guid.NewGuid().ToString("N"),stageRoot="Assets/__XaceAuthoringStage/"+id;
            var write=new PreparedAuthoringWrite{Directory=".xace/authoring-transactions/"+id};
            Directory.CreateDirectory(write.Directory);Directory.CreateDirectory(stageRoot);
            var files=new List<object>();
            write.Journal=Map("schema","xace.unity_authoring_write.v1","state","preparing","id",id,"capture_digest",expectedInventoryDigest,"files",files);
            Persist(write);
            try
            {
                foreach(var group in edits.GroupBy(e=>e.Document).OrderBy(g=>g.Key,StringComparer.Ordinal))
                {
                    string source=group.Key,staged=stageRoot+"/"+files.Count.ToString(CultureInfo.InvariantCulture)+Path.GetExtension(source),backup=Path.Combine(write.Directory,files.Count+".before");
                    File.Copy(source,backup,false);File.Copy(source,staged,false);AssetDatabase.ImportAsset(staged,ImportAssetOptions.ForceSynchronousImport);
                    var row=Map("source",source,"staged",staged,"backup",backup,"before",FileHash(source),"meta",FileHash(source+".meta"),"fingerprint",UnityAuthoringReader.Fingerprint(source),"after",null,"edits",group.Select(e=>Map("authoring_id",e.AuthoringId,"fields",e.Fields)).ToList());
                    files.Add(row);Persist(write);
                    var scene=default(UnityEngine.SceneManagement.Scene);GameObject prefab=null;
                    try
                    {
                        GameObject[] roots;
                        if(source.EndsWith(".unity")){scene=EditorSceneManager.OpenScene(staged,OpenSceneMode.Additive);roots=scene.GetRootGameObjects();}
                        else {prefab=PrefabUtility.LoadPrefabContents(staged);roots=new[]{prefab};}
                        var objects=roots.SelectMany(r=>r.GetComponentsInChildren<XaceAuthoringIdentity>(true)).ToArray();
                        foreach(var edit in group){var matches=objects.Where(o=>o.AuthoringId==edit.AuthoringId).ToArray();Need(matches.Length==1,"Ambiguous/missing staged object");Apply(matches[0].gameObject,edit.Fields);}
                        if(prefab!=null)PrefabUtility.SaveAsPrefabAsset(prefab,staged);else Need(EditorSceneManager.SaveScene(scene,staged),"Staged scene save failed");
                    }
                    finally {if(prefab!=null)PrefabUtility.UnloadPrefabContents(prefab);if(scene.IsValid())EditorSceneManager.CloseScene(scene,true);}
                    VerifySaved(staged,group);row["readback_verified"]=true;row["after"]=FileHash(staged);Persist(write);
                }
                // Originals must still be untouched after preparing native copies.
                Need(AuthoringJson.Hash(AuthoringJson.Encode(UnityAuthoringReader.Capture(scope)))==expectedInventoryDigest,"Source changed during staging");
                write.Journal["state"]="prepared";Persist(write);return write;
            }
            catch {write.Journal["state"]="prepare_failed";Persist(write);throw;}
        }
        public static PreparedAuthoringWrite PrepareRequest(AuthoringScope scope,string json)
        {
            var request=AuthoringJson.Obj(AuthoringJson.Parse(json));
            Need(request.Keys.OrderBy(x=>x).SequenceEqual(new[]{"edits","expected_inventory_digest","schema"}) && (string)request["schema"]=="xace.unity_authoring_write_request.v1","Write request schema");
            var edits=new List<AuthoringEdit>();
            foreach(var value in (List<object>)request["edits"])
            {var row=AuthoringJson.Obj(value);Need(row.Keys.OrderBy(x=>x).SequenceEqual(new[]{"authoring_id","document","fields"}),"Write request fields");edits.Add(new AuthoringEdit{Document=AuthoringJson.Text(row,"document"),AuthoringId=AuthoringJson.Text(row,"authoring_id"),Fields=AuthoringJson.Obj(row["fields"])});}
            return Prepare(scope,AuthoringJson.Text(request,"expected_inventory_digest"),edits);
        }
        static void Refresh(IEnumerable<Dictionary<string,object>> files)
        {
            var paths=files.Select(r=>AuthoringJson.Text(r,"source")).Distinct().ToArray();
            var opened=new List<string>();string active=UnityEngine.SceneManagement.SceneManager.GetActiveScene().path;
            foreach(var source in paths)
                Need(!UnityAuthoringReader.Dirty(source),"New dirty edits block refresh");
            var scratch=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);
            try
            {
                foreach(var source in paths){var scene=UnityEngine.SceneManagement.SceneManager.GetSceneByPath(source);if(scene.IsValid()&&scene.isLoaded){Need(EditorSceneManager.CloseScene(scene,true),"Cannot close approved scene");opened.Add(source);}}
                foreach(var source in paths)AssetDatabase.ImportAsset(source,ImportAssetOptions.ForceSynchronousImport);
                foreach(var source in opened)EditorSceneManager.OpenScene(source,OpenSceneMode.Additive);
                var previous=UnityEngine.SceneManagement.SceneManager.GetSceneByPath(active);if(previous.IsValid()&&previous.isLoaded)UnityEngine.SceneManagement.SceneManager.SetActiveScene(previous);
            }
            finally{if(UnityEngine.SceneManagement.SceneManager.sceneCount>1)EditorSceneManager.CloseScene(scratch,true);}
            UnityAuthoringNotifications.Invalidate();
        }
        public static void Commit(PreparedAuthoringWrite write,string approvedDigest,Action<int> faultInjection=null)
        {
            UnityAuthoringReader.EditMode();Need(write.ApprovalDigest==approvedDigest && (string)write.Journal["state"]=="prepared","Unapproved/stale write");
            var files=((List<object>)write.Journal["files"]).Select(AuthoringJson.Obj).ToArray();
            foreach(var row in files)
            {string source=AuthoringJson.Text(row,"source");Need(!UnityAuthoringReader.Dirty(source)&&FileHash(source)==(string)row["before"]&&FileHash(source+".meta")== (string)row["meta"]&&UnityAuthoringReader.Fingerprint(source)==(string)row["fingerprint"]&&FileHash((string)row["staged"])==(string)row["after"],"Stale/dirty/tampered staged set");}
            write.Journal["state"]="applying";Persist(write);
            try
            {
                for(int i=0;i<files.Length;i++)
                {
                    var row=files[i];string source=(string)row["source"];
                    Need(FileHash(source)==(string)row["before"] && !UnityAuthoringReader.Dirty(source),"Concurrent source edit");
                    // Replace atomically per document; journal covers recovery of the set.
                    string temporary=source+".xace-"+(string)write.Journal["id"];
                    string displaced=Path.Combine(write.Directory,i+".displaced");
                    File.Copy((string)row["staged"],temporary,false);ReplaceFile(temporary,source,displaced);
                    row["displaced"]=displaced;row["displaced_hash"]=FileHash(displaced);Persist(write);
                    Need((string)row["displaced_hash"]==(string)row["before"],"Concurrent replace; displaced edit retained for recovery");
                    faultInjection?.Invoke(i);
                }
                Refresh(files);write.Journal["state"]="committed";Persist(write);
            }
            catch {Rollback(write);throw;}
        }
        public static bool Rollback(PreparedAuthoringWrite write)
        {
            UnityAuthoringReader.EditMode();bool conflict=false;
            var files=((List<object>)write.Journal["files"]).Select(AuthoringJson.Obj).ToArray();var restored=new List<Dictionary<string,object>>();
            foreach(var row in files)
            {
                string source=(string)row["source"];string current=File.Exists(source)?FileHash(source):"missing";
                if(current==(string)row["before"])continue;
                if(current!=(string)row["after"] || UnityAuthoringReader.Dirty(source) || !File.Exists(source+".meta") || FileHash(source+".meta")!=(string)row["meta"]){conflict=true;continue;}
                string backup=row.ContainsKey("displaced")?(string)row["displaced"]:(string)row["backup"];
                string expected=row.ContainsKey("displaced_hash")?(string)row["displaced_hash"]:(string)row["before"];
                if(expected!=(string)row["before"])conflict=true;
                Need(FileHash(backup)==expected,"Corrupt before-image");
                string temporary=source+".xace-restore-"+(string)write.Journal["id"];
                File.Copy(backup,temporary,false);ReplaceFile(temporary,source,Path.Combine(write.Directory,Guid.NewGuid().ToString("N")+".restore-displaced"));restored.Add(row);
            }
            Refresh(restored);write.Journal["state"]=conflict?"recovery_conflict":"rolled_back";Persist(write);return !conflict;
        }
        public static PreparedAuthoringWrite Recover(string transactionId,string expectedJournalDigest,AuthoringScope approvedScope)
        {
            Need(System.Text.RegularExpressions.Regex.IsMatch(transactionId??"","^[0-9a-f]{32}$"),"Invalid recovery ID");
            var write=new PreparedAuthoringWrite{Directory=".xace/authoring-transactions/"+transactionId};
            string json=File.ReadAllText(write.ReceiptPath);Need(AuthoringJson.Hash(json)==expectedJournalDigest,"Recovery receipt changed");
            write.Journal=AuthoringJson.Obj(AuthoringJson.Parse(json));
            Need((string)write.Journal["id"]==transactionId && (string)write.Journal["schema"]=="xace.unity_authoring_write.v1","Recovery journal identity");
            foreach(var item in (List<object>)write.Journal["files"])
            {var row=AuthoringJson.Obj(item);approvedScope.Contains((string)row["source"]);UnityAuthoringReader.AssetPath((string)row["source"]);foreach(var key in new[]{"backup","displaced"})if(row.ContainsKey(key))Need(Path.GetFullPath((string)row[key]).StartsWith(Path.GetFullPath(write.Directory)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase),"Recovery backup escaped transaction");}
            Rollback(write);return write;
        }
    }
}

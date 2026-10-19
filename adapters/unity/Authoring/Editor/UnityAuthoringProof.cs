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
    // Installed-editor proof fixture only. Never invoked automatically by integration.
    [InitializeOnLoad]
    public static class UnityAuthoringProof
    {
        const string ScenePath="Assets/Fixture/World.unity",PrefabPath="Assets/Fixture/Template.prefab";
        static readonly string Namespace=new string('a',32);
        static Dictionary<string,object> Map(params object[] pairs)=>UnityAuthoringReader.Map(pairs);
        static string Id(int n)=>n.ToString("x32");
        static List<object> cases=new List<object>();
        static UnityAuthoringProof(){EditorApplication.playModeStateChanged+=PlayState;}
        static string Arg(string key){var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,key);return i>=0?args[i+1]:"";}
        static void Check(string name,bool value){cases.Add(Map("name",name,"ok",value));AuthoringJson.Need(value,name);}
        static void Reject(string name,Action action){bool refused=false;try{action();}catch(InvalidDataException){refused=true;}Check(name,refused);}
        static void Finish(Exception error=null)
        {if(error!=null)Debug.LogException(error);File.WriteAllText(Arg("-necReport"),AuthoringJson.Encode(Map("schema","xace.nec004.unity_proof.v1","engine_version",Application.unityVersion,"ok",error==null,"cases",cases,"error",error?.ToString())));EditorApplication.Exit(error==null?0:1);}
        static XaceAuthoringIdentity SetId(GameObject go,int id,string kind,string prefab="")
        {var value=go.AddComponent<XaceAuthoringIdentity>();value.NamespaceId=Namespace;value.AuthoringId=Id(id);value.Kind=kind;value.PrefabId=prefab;return value;}
        static GameObject Find(int id)=>UnityEngine.Object.FindObjectsByType<XaceAuthoringIdentity>().Single(o=>o.AuthoringId==Id(id)).gameObject;
        static AuthoringScope Scope()=>new AuthoringScope(new[]{ScenePath,PrefabPath});
        static void Save(){EditorSceneManager.SaveScene(SceneManager.GetSceneByPath(ScenePath));AssetDatabase.SaveAssets();}
        static string Hash(object value)=>AuthoringJson.Hash(AuthoringJson.Encode(value));
        public static void Run()
        {
            try
            {
                Directory.CreateDirectory("Assets/Fixture");AssetDatabase.Refresh();
                var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
                var doc=new GameObject("Authoring document");SetId(doc,1,"scene");
                var source=new GameObject("Ordinary Name");SetId(source,2,"prefab_definition");
                source.transform.localPosition=new Vector3(1,2,3);var light=source.AddComponent<Light>();light.intensity=3.25f;
                PrefabUtility.SaveAsPrefabAsset(source,PrefabPath);UnityEngine.Object.DestroyImmediate(source);
                var template=AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
                var instance=(GameObject)PrefabUtility.InstantiatePrefab(template,scene);instance.name="Ordinary Name";
                var inherited=instance.GetComponent<XaceAuthoringIdentity>();inherited.AuthoringId=Id(3);inherited.Kind="prefab_instance";inherited.PrefabId=Id(2);PrefabUtility.RecordPrefabInstancePropertyModifications(inherited);
                instance.GetComponent<Light>().intensity=7.5f;PrefabUtility.RecordPrefabInstancePropertyModifications(instance.GetComponent<Light>());
                var sibling=new GameObject("Ordinary Name");SetId(sibling,4,"object");
                var nested=new GameObject("Nested");SetId(nested,5,"object");nested.transform.SetParent(sibling.transform,false);
                var mesh=new Mesh{name="FixtureMesh"};mesh.vertices=new[]{Vector3.zero,Vector3.right,Vector3.up};mesh.triangles=new[]{0,1,2};AssetDatabase.CreateAsset(mesh,"Assets/Fixture/Mesh.asset");
                sibling.AddComponent<MeshFilter>().sharedMesh=mesh;
                var clip=new AnimationClip{name="Clip"};AssetDatabase.CreateAsset(clip,"Assets/Fixture/Clip.anim");
                var binding=sibling.AddComponent<XaceAuthoringBinding>();binding.InputAction="Horizontal";binding.BindingId="walk";binding.EventName="actor.walk";binding.PlaybackKind="Animation";binding.Resource=clip;
                Check("save_actual_scene",EditorSceneManager.SaveScene(scene,ScenePath));AssetDatabase.SaveAssets();
                var scope=Scope();var first=UnityAuthoringNotifications.Rescan(scope);var rows=AuthoringJson.Obj(first["objects"]);
                Check("distinct_duplicate_names",rows.Count==5 && Hash(AuthoringJson.Obj(rows[Id(3)])["locator"])!=Hash(AuthoringJson.Obj(rows[Id(4)])["locator"]));
                File.WriteAllText(".xace/nec004-before.json",AuthoringJson.Encode(first));
                EditorUtility.SetDirty(mesh);Reject("unsaved_resource_dependency_refused",()=>UnityAuthoringReader.Capture(scope));AssetDatabase.SaveAssets();
                foreach(var value in (List<object>)AuthoringJson.Parse(File.ReadAllText(Arg("-necGolden"))))
                {
                    var golden=AuthoringJson.Obj(value);string field="transform."+(string)golden["kind"];
                    var proposal=new AuthoringEdit{Document=ScenePath,AuthoringId=Id(3),Fields=Map(field,golden["expected"])};
                    var stagedGolden=UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{proposal});UnityAuthoringWriter.Commit(stagedGolden,stagedGolden.ApprovalDigest);
                    Check("shared_golden_native_"+(string)golden["kind"],AuthoringJson.Encode(UnityAuthoringReader.Fields(Find(3))[field])==AuthoringJson.Encode(golden["value"]));
                    Check("shared_golden_rollback_"+(string)golden["kind"],UnityAuthoringWriter.Rollback(stagedGolden));
                }
                instance=Find(3);sibling=Find(4);nested=Find(5);scene=SceneManager.GetSceneByPath(ScenePath);
                byte[] unchangedScene=File.ReadAllBytes(ScenePath);File.AppendAllText(ScenePath,"\n# missed external save notification\n");
                Reject("missed_file_notification_refuses_stale_memory",()=>UnityAuthoringNotifications.Rescan(scope));File.WriteAllBytes(ScenePath,unchangedScene);
                Check("full_rescan_recovers_after_source_restoration",Hash(UnityAuthoringNotifications.Rescan(scope))==Hash(first));
                // External Unity editing, with missed notifications deliberately ignored.
                var priorLocator=Hash(AuthoringJson.Obj(rows[Id(4)])["locator"]);
                Undo.RecordObject(sibling.transform,"Move authored object");sibling.transform.localPosition=new Vector3(4,5,6);Undo.FlushUndoRecordObjects();
                Reject("dirty_capture_refused",()=>UnityAuthoringReader.Capture(scope));
                Undo.PerformUndo();Check("native_undo",sibling.transform.localPosition==Vector3.zero);
                Undo.PerformRedo();Check("native_redo",sibling.transform.localPosition==new Vector3(4,5,6));
                Undo.PerformUndo();Check("native_undo_after_redo",sibling.transform.localPosition==Vector3.zero);Save();
                sibling.name="Renamed freely";nested.transform.SetParent(instance.transform,false);EditorSceneManager.MarkSceneDirty(scene);Save();
                var rescanned=UnityAuthoringNotifications.Rescan(scope);rows=AuthoringJson.Obj(rescanned["objects"]);
                Check("rename_identity_stable",Hash(AuthoringJson.Obj(rows[Id(4)])["locator"])==priorLocator);
                Check("reparent_extracted",(string)AuthoringJson.Obj(rows[Id(5)])["parent_id"]==Id(3));
                var duplicate=UnityEngine.Object.Instantiate(sibling);Save();Reject("duplicate_metadata_refused",()=>UnityAuthoringReader.Capture(scope));
                UnityAuthoringReader.ReidentifyDuplicate(scope,duplicate,UnityAuthoringReader.Locator(duplicate),UnityAuthoringReader.Fingerprint(ScenePath),Id(7));Save();
                Check("explicit_duplicate_identity_repair",AuthoringJson.Obj(UnityAuthoringReader.Capture(scope)["objects"]).Count==6);UnityEngine.Object.DestroyImmediate(duplicate);Save();
                var fresh=new GameObject("Enrollment fixture");fresh.transform.localPosition=new Vector3(12,13,14);Save();
                string discoveryBefore=AuthoringJson.Hash(File.ReadAllBytes(ScenePath));var discovery=UnityAuthoringReader.Discover(scope);
                var candidates=((List<object>)discovery["documents"]).SelectMany(d=>(List<object>)AuthoringJson.Obj(d)["objects"]).Select(AuthoringJson.Obj).Where(r=>(string)r["name"]=="Enrollment fixture").ToArray();
                Check("unenrolled_discovery_has_real_transform",candidates.Length==1 && !(bool)candidates[0]["registered"] && (string)AuthoringJson.Obj(AuthoringJson.Obj(candidates[0]["fields"])["transform.position"])["x"]=="12");
                Check("discovery_is_read_only",discoveryBefore==AuthoringJson.Hash(File.ReadAllBytes(ScenePath)));
                File.WriteAllText(".xace/nec004-discovery.json",AuthoringJson.Encode(discovery));
                Reject("invalid_enrollment_rolls_back",()=>UnityAuthoringReader.Attach(scope,fresh,Namespace,"invalid","object"));Check("invalid_enrollment_no_component",fresh.GetComponent<XaceAuthoringIdentity>()==null);
                UnityAuthoringReader.Attach(scope,fresh,Namespace,Id(8),"object");Save();Check("explicit_metadata_attachment_persists",AuthoringJson.Obj(UnityAuthoringReader.Capture(scope)["objects"]).ContainsKey(Id(8)));UnityEngine.Object.DestroyImmediate(fresh);Save();
                Reject("numeric_wire_token_refused",()=>AuthoringJson.Parse("{\"raw\":9007199254740993}"));Reject("duplicate_wire_key_refused",()=>AuthoringJson.Parse("{\"id\":\"a\",\"id\":\"b\"}"));
                var unknown=Find(3).AddComponent<AudioSource>();unknown.volume=0.37f;unknown.pitch=1.25f;unknown.loop=true;EditorSceneManager.MarkSceneDirty(SceneManager.GetSceneByPath(ScenePath));Save();
                var opaqueInventory=UnityAuthoringReader.Capture(scope);File.WriteAllText(".xace/nec004-unknown-component.json",AuthoringJson.Encode(opaqueInventory));
                Check("unknown_component_has_blocking_disposition",((List<object>)AuthoringJson.Obj(AuthoringJson.Obj(opaqueInventory["objects"])[Id(3)])["opaque"]).Any(r=>(bool)AuthoringJson.Obj(r)["critical"]));
                var opaqueEdit=new AuthoringEdit{Document=ScenePath,AuthoringId=Id(3),Fields=Map("transform.position",Map("x","5000000","y","6000000","z","-7000000"))};
                var opaqueWrite=UnityAuthoringWriter.Prepare(scope,Hash(opaqueInventory),new[]{opaqueEdit});UnityAuthoringWriter.Commit(opaqueWrite,opaqueWrite.ApprovalDigest);
                unknown=Find(3).GetComponent<AudioSource>();Check("unknown_component_native_properties_preserved",unknown!=null && unknown.volume==0.37f && unknown.pitch==1.25f && unknown.loop);
                Check("unknown_component_write_undo",UnityAuthoringWriter.Rollback(opaqueWrite));UnityEngine.Object.DestroyImmediate(Find(3).GetComponent<AudioSource>());EditorSceneManager.MarkSceneDirty(SceneManager.GetSceneByPath(ScenePath));Save();
                var ownedBefore=File.ReadAllBytes(ScenePath);
                var ownedFields=Map("input.action","Vertical","binding.playback",Map("binding_id","walk","event_name","actor.changed","playback_kind","Animation","asset",UnityAuthoringReader.Asset(clip)));
                var ownedWrite=UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{new AuthoringEdit{Document=ScenePath,AuthoringId=Id(4),Fields=ownedFields}});
                Check("owned_input_binding_preview_preserves_source",ownedBefore.SequenceEqual(File.ReadAllBytes(ScenePath)));
                UnityAuthoringWriter.Commit(ownedWrite,ownedWrite.ApprovalDigest);
                Check("owned_input_binding_saved",Find(4).GetComponent<XaceAuthoringBinding>().InputAction=="Vertical" && Find(4).GetComponent<XaceAuthoringBinding>().EventName=="actor.changed");
                Check("owned_input_binding_preserves_resource_mesh",Find(4).GetComponent<XaceAuthoringBinding>().Resource==clip && Find(4).GetComponent<MeshFilter>().sharedMesh==mesh);
                Check("owned_input_binding_rollback",UnityAuthoringWriter.Rollback(ownedWrite) && ownedBefore.SequenceEqual(File.ReadAllBytes(ScenePath)));
                var replacementClip=new AnimationClip{name="ReplacementClip"};AssetDatabase.CreateAsset(replacementClip,"Assets/Fixture/Replacement.anim");AssetDatabase.SaveAssets();
                var replacementFields=Map("binding.playback",Map("binding_id","walk","event_name","actor.replaced","playback_kind","Animation","asset",UnityAuthoringReader.Asset(replacementClip)));
                var replacementWrite=UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{new AuthoringEdit{Document=ScenePath,AuthoringId=Id(4),Fields=replacementFields}});
                replacementClip.name="ChangedAfterApproval";EditorUtility.SetDirty(replacementClip);AssetDatabase.SaveAssets();
                Reject("new_playback_dependency_drift_refused",()=>UnityAuthoringWriter.Commit(replacementWrite,replacementWrite.ApprovalDigest));
                Check("dependency_refusal_leaves_scene_unchanged",ownedBefore.SequenceEqual(File.ReadAllBytes(ScenePath)));
                var replacementMesh=new Mesh{name="ReplacementMesh"};replacementMesh.vertices=new[]{Vector3.zero,Vector3.right*2,Vector3.up};replacementMesh.triangles=new[]{0,1,2};AssetDatabase.CreateAsset(replacementMesh,"Assets/Fixture/ReplacementMesh.asset");AssetDatabase.SaveAssets();
                var meshBefore=UnityAuthoringReader.Capture(scope);var originalMeshBytes=File.ReadAllBytes(ScenePath);
                var meshWrite=UnityAuthoringWriter.Prepare(scope,Hash(meshBefore),new[]{new AuthoringEdit{Document=ScenePath,AuthoringId=Id(4),Fields=Map("presentation.asset",UnityAuthoringReader.Asset(replacementMesh))}});
                Check("mesh_preview_preserves_scene",originalMeshBytes.SequenceEqual(File.ReadAllBytes(ScenePath)));
                UnityAuthoringWriter.Commit(meshWrite,meshWrite.ApprovalDigest);var meshAfter=UnityAuthoringReader.Capture(scope);
                Check("mesh_resource_saved",Find(4).GetComponent<MeshFilter>().sharedMesh==replacementMesh);
                Check("mesh_change_preserves_unowned_properties",Hash(AuthoringJson.Obj(AuthoringJson.Obj(meshBefore["objects"])[Id(4)])["opaque"])==Hash(AuthoringJson.Obj(AuthoringJson.Obj(meshAfter["objects"])[Id(4)])["opaque"]));
                Check("mesh_write_exact_rollback",UnityAuthoringWriter.Rollback(meshWrite) && originalMeshBytes.SequenceEqual(File.ReadAllBytes(ScenePath)));
                var before=UnityAuthoringReader.Capture(scope);var sourceBytes=File.ReadAllBytes(ScenePath);
                var edit=new AuthoringEdit{Document=ScenePath,AuthoringId=Id(3),Fields=Map("transform.position",Map("x","8000000","y","9000000","z","-10000000"))};
                var prepared=UnityAuthoringWriter.Prepare(scope,Hash(before),new[]{edit});
                Check("prepare_preserves_original",sourceBytes.SequenceEqual(File.ReadAllBytes(ScenePath)));
                Reject("approval_digest_refused",()=>UnityAuthoringWriter.Commit(prepared,new string('0',64)));
                UnityAuthoringWriter.Commit(prepared,prepared.ApprovalDigest);
                var after=UnityAuthoringReader.Capture(scope);File.WriteAllText(".xace/nec004-after.json",AuthoringJson.Encode(after));
                Check("native_save_reextract",Find(3).transform.localPosition==new Vector3(8,9,10));
                Check("unknown_properties_and_overrides_preserved",Find(3).GetComponent<Light>().intensity==7.5f && PrefabUtility.IsPartOfPrefabInstance(Find(3)));
                Check("resources_input_bindings_preserved",Find(4).GetComponent<MeshFilter>().sharedMesh==mesh && Find(4).GetComponent<XaceAuthoringBinding>().InputAction=="Horizontal" && Find(4).GetComponent<XaceAuthoringBinding>().Resource==clip);
                Check("writer_receipt_undo",UnityAuthoringWriter.Rollback(prepared));
                Check("rollback_bytes_exact",sourceBytes.SequenceEqual(File.ReadAllBytes(ScenePath)));
                var retry=UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{edit});
                bool fault=false;try{UnityAuthoringWriter.Commit(retry,retry.ApprovalDigest,_=>throw new IOException("injected after replace"));}catch(IOException){fault=true;}
                Check("failure_restores_before_image",fault&&sourceBytes.SequenceEqual(File.ReadAllBytes(ScenePath)));
                var precision=new AuthoringEdit{Document=ScenePath,AuthoringId=Id(3),Fields=Map("transform.scale",Map("x","9007199254740993","y","1000000","z","1000000"))};
                Reject("unrepresentable_float_refused",()=>UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{precision}));
                var forbidden=new AuthoringEdit{Document="Assets/Unapproved.unity",AuthoringId=Id(3),Fields=edit.Fields};
                Reject("outside_approved_set_refused",()=>UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{forbidden}));
                var latest=UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{edit});
                Find(4).transform.localPosition=Vector3.one;EditorSceneManager.MarkSceneDirty(SceneManager.GetSceneByPath(ScenePath));Save();
                Reject("newer_saved_edits_refuse_commit",()=>UnityAuthoringWriter.Commit(latest,latest.ApprovalDigest));
                var prefabEdit=new AuthoringEdit{Document=PrefabPath,AuthoringId=Id(2),Fields=Map("transform.position",Map("x","2000000","y","3000000","z","-4000000"))};
                var multi=UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{edit,prefabEdit});UnityAuthoringWriter.Commit(multi,multi.ApprovalDigest);
                Check("prefab_and_scene_staged_set",AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath).transform.localPosition==new Vector3(2,3,4) && Find(3).transform.localPosition==new Vector3(8,9,10));
                Check("prefab_unknown_properties_preserved",AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath).GetComponent<Light>().intensity==3.25f && Find(3).GetComponent<Light>().intensity==7.5f);
                string transaction=Path.GetFileName(Path.GetDirectoryName(multi.ReceiptPath));string journal=File.ReadAllText(multi.ReceiptPath);
                UnityAuthoringWriter.Recover(transaction,AuthoringJson.Hash(journal),scope);
                Check("journal_reload_recovery",AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath).transform.localPosition==new Vector3(1,2,3));
                var conflict=UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{edit});UnityAuthoringWriter.Commit(conflict,conflict.ApprovalDigest);
                Find(4).name="Newer native edit";EditorSceneManager.MarkSceneDirty(SceneManager.GetSceneByPath(ScenePath));Save();string newer=AuthoringJson.Hash(File.ReadAllBytes(ScenePath));
                Check("rollback_reports_newer_edit_conflict",!UnityAuthoringWriter.Rollback(conflict) && AuthoringJson.Hash(File.ReadAllBytes(ScenePath))==newer);
                var final=UnityAuthoringWriter.Prepare(scope,Hash(UnityAuthoringReader.Capture(scope)),new[]{edit});UnityAuthoringWriter.Commit(final,final.ApprovalDigest);
                File.WriteAllText(".xace/nec004-reload-expected.json",AuthoringJson.Encode(UnityAuthoringReader.Capture(scope)));
                File.WriteAllText(".xace/nec004-run-cases.json",AuthoringJson.Encode(cases));
                Finish();
            }
            catch(Exception error){Finish(error);}
        }
        public static void Reload()
        {
            try
            {
                EditorSceneManager.OpenScene(ScenePath,OpenSceneMode.Single);var actual=UnityAuthoringReader.Capture(Scope());Check("fresh_editor_reload_capture_stable",AuthoringJson.Encode(actual)==File.ReadAllText(".xace/nec004-reload-expected.json"));
                Check("cold_reload_rescan_required",UnityAuthoringNotifications.RescanRequired);UnityAuthoringNotifications.Rescan(Scope());Check("complete_rescan_clears_hint",!UnityAuthoringNotifications.RescanRequired);
                var staged=UnityAuthoringWriter.PrepareRequest(Scope(),File.ReadAllText(".xace/nec004-python-request.json"));UnityAuthoringWriter.Commit(staged,staged.ApprovalDigest);
                Check("python_request_native_write",Find(3).transform.localPosition==new Vector3(11,12,13));
                File.WriteAllText(".xace/nec004-python-after.json",AuthoringJson.Encode(UnityAuthoringReader.Capture(Scope())));Finish();
            }
            catch(Exception error){Finish(error);}
        }
        public static void Play()
        {
            try
            {
                SessionState.SetBool("nec004.play.active",true);SessionState.SetInt("nec004.play.phase",0);
                SessionState.SetBool("nec004.play.oldEnabled",EditorSettings.enterPlayModeOptionsEnabled);
                SessionState.SetInt("nec004.play.oldOptions",(int)EditorSettings.enterPlayModeOptions);
                SessionState.SetString("nec004.play.cases","[]");SessionState.SetString("nec004.play.source",AuthoringJson.Hash(File.ReadAllBytes(ScenePath)));
                StartPlay();
            }
            catch(Exception error){Finish(error);}
        }
        static void StartPlay()
        {
            EditorSceneManager.OpenScene(ScenePath,OpenSceneMode.Single);UnityAuthoringNotifications.Rescan(Scope());
            SessionState.SetString("nec004.play.position",AuthoringJson.Encode(UnityAuthoringReader.Vector(Find(3).transform.localPosition)));
            EditorSettings.enterPlayModeOptionsEnabled=true;
            EditorSettings.enterPlayModeOptions=SessionState.GetInt("nec004.play.phase",0)==0?EnterPlayModeOptions.DisableDomainReload|EnterPlayModeOptions.DisableSceneReload:EnterPlayModeOptions.None;
            EditorApplication.isPlaying=true;
        }
        static void PlayState(PlayModeStateChange state)
        {
            if(!SessionState.GetBool("nec004.play.active",false))return;
            try
            {
                cases=(List<object>)AuthoringJson.Parse(SessionState.GetString("nec004.play.cases","[]"));
                string phase=SessionState.GetInt("nec004.play.phase",0)==0?"reload_disabled":"reload_enabled";
                if(state==PlayModeStateChange.EnteredPlayMode)
                {
                    Reject("play_capture_refused_"+phase,()=>UnityAuthoringReader.Capture(null));
                    Find(3).transform.localPosition=new Vector3(99,98,97);
                    SessionState.SetString("nec004.play.cases",AuthoringJson.Encode(cases));EditorApplication.isPlaying=false;
                }
                if(state==PlayModeStateChange.EnteredEditMode)EditorApplication.delayCall+=()=>AfterPlay(phase);
            }
            catch(Exception error){SessionState.SetBool("nec004.play.active",false);Finish(error);}
        }
        static void AfterPlay(string phase)
        {
            try
            {
                Check("play_saved_source_unchanged_"+phase,AuthoringJson.Hash(File.ReadAllBytes(ScenePath))==SessionState.GetString("nec004.play.source",""));
                EditorSceneManager.OpenScene(ScenePath,OpenSceneMode.Single);
                UnityAuthoringNotifications.Rescan(Scope());Check("saved_reload_excludes_play_changes_"+phase,AuthoringJson.Encode(UnityAuthoringReader.Vector(Find(3).transform.localPosition))==SessionState.GetString("nec004.play.position",""));
                if(SessionState.GetInt("nec004.play.phase",0)==0)
                {SessionState.SetString("nec004.play.cases",AuthoringJson.Encode(cases));SessionState.SetInt("nec004.play.phase",1);StartPlay();}
                else
                {SessionState.SetBool("nec004.play.active",false);EditorSettings.enterPlayModeOptionsEnabled=SessionState.GetBool("nec004.play.oldEnabled",false);EditorSettings.enterPlayModeOptions=(EnterPlayModeOptions)SessionState.GetInt("nec004.play.oldOptions",0);Finish();}
            }
            catch(Exception error){SessionState.SetBool("nec004.play.active",false);Finish(error);}
        }
    }
}

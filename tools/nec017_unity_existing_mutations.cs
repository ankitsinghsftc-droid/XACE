using System;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
namespace Xace.Authoring.Editor {
// Test-only mutations in an explicitly new private imported-fixture copy.
public static class NEC017ExistingMutations {
 static readonly string[] Paths={"Assets/Game/Crate.prefab","Assets/Game/World.unity","Assets/Game/Annex.unity"};
 static void Open(string annex){EditorSceneManager.OpenScene(Paths[1],OpenSceneMode.Single);EditorSceneManager.OpenScene(annex,OpenSceneMode.Additive);}
 public static void Run(){try{
  var args=Environment.GetCommandLineArgs();string phase=args[Array.IndexOf(args,"-nec017Mutation")+1];Open(Paths[2]);var before=UnityAuthoringReader.Capture(new AuthoringScope(Paths));var result=UnityAuthoringReader.Map("phase",phase,"ok",false,"before",before);string annex=Paths[2];
  if(phase=="move"){annex="Assets/Game/MovedAnnex.unity";string error=AssetDatabase.MoveAsset(Paths[2],annex);if(error!="")throw new Exception(error);AssetDatabase.Refresh();Open(annex);}
  else{
   var scene=UnityEngine.SceneManagement.SceneManager.GetSceneByPath(Paths[1]);UnityEngine.SceneManagement.SceneManager.SetActiveScene(scene);
   if(phase=="rename")GameObject.Find("Warehouse/Crate1").name="CrateOne";
   else if(phase=="reparent")GameObject.Find("Warehouse/North/DuplicateDisplayName").transform.SetParent(GameObject.Find("Warehouse/South").transform,true);
   else if(phase=="delete")UnityEngine.Object.DestroyImmediate(GameObject.Find("Warehouse/Crate49"));
   else if(phase=="duplicate"){var go=UnityEngine.Object.Instantiate(GameObject.Find("Warehouse/Crate1"),GameObject.Find("Warehouse").transform);go.name="DuplicatedCrate";}
   else throw new Exception("Unknown mutation phase");
   EditorSceneManager.MarkSceneDirty(scene);if(!EditorSceneManager.SaveScene(scene))throw new Exception("Native save failed");AssetDatabase.SaveAssets();
   if(phase=="duplicate"){
    bool refused=false;string refusal="";try{UnityAuthoringReader.Capture(new AuthoringScope(Paths));}catch(Exception failure){refused=true;refusal=failure.Message;}if(!refused)throw new Exception("Duplicate identity silently admitted");result["collision_refused"]=true;result["collision_error"]=refusal;
    var identity=GameObject.Find("Warehouse/DuplicatedCrate").GetComponent<XaceAuthoringIdentity>();if(identity==null)throw new Exception("Duplicated identity missing");Undo.RecordObject(identity,"Explicit distinct fixture identity");identity.AuthoringId=990001.ToString("x32");PrefabUtility.RecordPrefabInstancePropertyModifications(identity);EditorUtility.SetDirty(identity);EditorSceneManager.MarkSceneDirty(scene);if(!EditorSceneManager.SaveScene(scene))throw new Exception("Distinct identity save failed");AssetDatabase.SaveAssets();result["explicit_distinct_identity"]=true;
   }
  }
  var paths=new[]{Paths[0],Paths[1],annex};result["after"]=UnityAuthoringReader.Capture(new AuthoringScope(paths));result["ok"]=true;File.WriteAllText("mutation-"+phase+".json",AuthoringJson.Encode(result));EditorApplication.Exit(0);
 }catch(Exception error){Debug.LogException(error);EditorApplication.Exit(1);}}
}}

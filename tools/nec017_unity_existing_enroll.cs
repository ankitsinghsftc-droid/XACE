using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEditor;
using UnityEditor.SceneManagement;
namespace Xace.Authoring.Editor {
public static class NEC017ExistingEnrollment {
 static string Id(int n)=>n.ToString("x32");
 static readonly string[] Paths={"Assets/Game/Crate.prefab","Assets/Game/World.unity","Assets/Game/Annex.unity"};
 static void OpenScenes(){EditorSceneManager.OpenScene(Paths[1],OpenSceneMode.Single);EditorSceneManager.OpenScene(Paths[2],OpenSceneMode.Additive);}
 static string NodePath(Transform t)=>t.parent==null?t.name:NodePath(t.parent)+"/"+t.name;
 public static void Run(){try {
  OpenScenes();var scope=new AuthoringScope(Paths);var before=Paths.ToDictionary(p=>p,p=>AuthoringJson.Hash(File.ReadAllBytes(p)));
  var discovered=UnityAuthoringReader.Discover(scope);File.WriteAllText("existing-discovery.json",AuthoringJson.Encode(discovered));
  foreach(var row in before)if(AuthoringJson.Hash(File.ReadAllBytes(row.Key))!=row.Value)throw new Exception("Discovery mutated native document");
  // Explicit metadata enrollment in a new fixture copy. No gameplay conversion.
  var prefab=PrefabUtility.LoadPrefabContents(Paths[0]);var definition=prefab.AddComponent<XaceAuthoringIdentity>();definition.NamespaceId=Id(9000);definition.AuthoringId=Id(1);definition.Kind="prefab_definition";definition.Generation="1";definition.PrefabId="";PrefabUtility.SaveAsPrefabAsset(prefab,Paths[0]);PrefabUtility.UnloadPrefabContents(prefab);AssetDatabase.SaveAssets();OpenScenes();
  int next=2;var manifest=new List<object>();manifest.Add(UnityAuthoringReader.Map("id",Id(1),"document",Paths[0],"path","Crate","kind","prefab_definition"));
  foreach(var path in Paths.Skip(1)){
   var scene=SceneManager.GetSceneByPath(path);SceneManager.SetActiveScene(scene);var holder=new GameObject("XACE document identity");UnityAuthoringReader.Attach(scope,holder,Id(9000),Id(next++),"scene");
   foreach(var go in scene.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Transform>(true)).Select(t=>t.gameObject)){
    if(go==holder){manifest.Add(UnityAuthoringReader.Map("id",holder.GetComponent<XaceAuthoringIdentity>().AuthoringId,"document",path,"path",go.name,"kind","scene"));continue;}
    var inherited=go.GetComponent<XaceAuthoringIdentity>();var kind=PrefabUtility.IsAnyPrefabInstanceRoot(go)?"prefab_instance":"object";var id=Id(next++);
    if(inherited!=null){if(kind!="prefab_instance"||inherited.AuthoringId!=Id(1)||inherited.Kind!="prefab_definition")throw new Exception("Unexpected existing metadata; no overwrite");Undo.RecordObject(inherited,"Explicit fixture instance identity");inherited.AuthoringId=id;inherited.Kind=kind;inherited.PrefabId=Id(1);PrefabUtility.RecordPrefabInstancePropertyModifications(inherited);EditorUtility.SetDirty(inherited);}
    else UnityAuthoringReader.Attach(scope,go,Id(9000),id,kind,"1",kind=="prefab_instance"?Id(1):"");
    manifest.Add(UnityAuthoringReader.Map("id",id,"document",path,"path",NodePath(go.transform),"kind",kind));
   }
   EditorSceneManager.MarkSceneDirty(scene);if(!EditorSceneManager.SaveScene(scene,path))throw new Exception("Save failed");
  }
  AssetDatabase.SaveAssets();OpenScenes();var inventory=UnityAuthoringReader.Capture(scope);File.WriteAllText("existing-native.json",AuthoringJson.Encode(inventory));File.WriteAllText("existing-enrollment.json",AuthoringJson.Encode(UnityAuthoringReader.Map("ok",true,"objects",manifest,"discovery_preserved_source",true,"adoption_verified",false,"explicit_fixture_metadata_enrollment",true)));EditorApplication.Exit(0);
 }catch(Exception e){Debug.LogException(e);EditorApplication.Exit(1);}}
}}

namespace Xace.Authoring.Editor {
public static class NEC017ColliderProfile {
 public static void Run(){try{
  const string path="Assets/Game/RootColliderProfile.unity";if(File.Exists(path))throw new Exception("Refuse existing fixture document");
  var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);var holder=new GameObject("Document identity");
  for(int n=0;n<50;n++){var box=new GameObject("StaticBox"+n);box.transform.position=new Vector3(n%10,0,n/10);box.AddComponent<BoxCollider>().size=Vector3.one*2;}
  if(!EditorSceneManager.SaveScene(scene,path))throw new Exception("Initial save failed");
  File.Copy(path,"root-collider-before-enrollment.unity");var scope=new AuthoringScope(new[]{path});File.WriteAllText("existing-discovery.json",AuthoringJson.Encode(UnityAuthoringReader.Discover(scope)));
  int index=1;var manifest=new List<object>();
  foreach(var go in scene.GetRootGameObjects()){
   var kind=go==holder?"scene":"object";var id=(index++).ToString("x32");UnityAuthoringReader.Attach(scope,go,9000.ToString("x32"),id,kind);manifest.Add(UnityAuthoringReader.Map("id",id,"document",path,"path",go.name,"kind",kind));
  }
  EditorSceneManager.MarkSceneDirty(scene);if(!EditorSceneManager.SaveScene(scene,path))throw new Exception("Enrollment save failed");AssetDatabase.SaveAssets();EditorSceneManager.OpenScene(path,OpenSceneMode.Single);
  File.WriteAllText("existing-native.json",AuthoringJson.Encode(UnityAuthoringReader.Capture(scope)));File.WriteAllText("existing-enrollment.json",AuthoringJson.Encode(UnityAuthoringReader.Map("ok",true,"objects",manifest,"scope","Focused unparented AABB cell only; not full existing project certification","adoption_verified",false)));EditorApplication.Exit(0);
 }catch(Exception e){Debug.LogException(e);EditorApplication.Exit(1);}}
}}

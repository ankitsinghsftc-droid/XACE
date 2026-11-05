using System;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
// Manual test-fixture disposition only. Always run on a separately copied project.
public static class NEC017StaticDisposition {
 public static void Apply(){try{
  if(!File.Exists("NEC017.static-copy-approved"))throw new Exception("Missing copied-fixture approval");
  var prefab=PrefabUtility.LoadPrefabContents("Assets/Game/Crate.prefab");
  var box=prefab.GetComponent<BoxCollider>();if(box==null)throw new Exception("Expected original collider");
  UnityEngine.Object.DestroyImmediate(box,true);PrefabUtility.SaveAsPrefabAsset(prefab,"Assets/Game/Crate.prefab");PrefabUtility.UnloadPrefabContents(prefab);
  var scene=EditorSceneManager.OpenScene("Assets/Game/World.unity",OpenSceneMode.Single);
  foreach(var name in new[]{"NativeAudio","NativeAnimation","UnsupportedCriticalScore"}){
   var go=GameObject.Find("Warehouse/"+name);if(go==null)throw new Exception("Expected original native authority "+name);UnityEngine.Object.DestroyImmediate(go);
  }
  EditorSceneManager.MarkSceneDirty(scene);if(!EditorSceneManager.SaveScene(scene))throw new Exception("Save failed");AssetDatabase.SaveAssets();
  File.WriteAllText("disposition-applied.json","{\"ok\":true,\"automatic_conversion\":false,\"native_physics_preserved\":false}");EditorApplication.Exit(0);
 }catch(Exception e){Debug.LogException(e);EditorApplication.Exit(1);}}
 public static void Cold(){try{
  var scene=EditorSceneManager.OpenScene("Assets/Game/World.unity",OpenSceneMode.Single);
  var nodes=scene.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Transform>(true)).ToArray();
  if(nodes.Any(t=>t.GetComponent<BoxCollider>()!=null))throw new Exception("Collider survived");
  if(nodes.Any(t=>new[]{"NativeAudio","NativeAnimation","UnsupportedCriticalScore"}.Contains(t.name)))throw new Exception("Native authority survived");
  if(nodes.Count(t=>t.name.StartsWith("Crate")&&PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject))!=50)throw new Exception("Instance count mismatch");
  if(nodes.Where(t=>t.name.StartsWith("Crate")).Any(t=>t.GetComponent<MeshFilter>().sharedMesh==null||t.GetComponent<MeshRenderer>().sharedMaterial==null))throw new Exception("Presentation lost");
  EditorSceneManager.OpenScene("Assets/Game/Annex.unity",OpenSceneMode.Single);
  var prefab=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Game/Crate.prefab");if(prefab.GetComponent<BoxCollider>()!=null)throw new Exception("Prefab collider survived");
  File.WriteAllText("disposition-cold.json","{\"ok\":true,\"prefab_instances\":50,\"native_mesh_material_retained\":true,\"cold_verified\":true,\"automatic_conversion\":false}");EditorApplication.Exit(0);
 }catch(Exception e){Debug.LogException(e);EditorApplication.Exit(1);}}
}

using System;
using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
public static class NEC017ExistingFixture {
 [Serializable] public class Report { public bool ok=true; public int authored_instances=50; public int scenes=2; public bool xace_enrolled=false; public string license="Original test content; CC0-1.0"; public string engine; }
 public static void Create() {
  try {
   Directory.CreateDirectory("Assets/Game"); AssetDatabase.Refresh();
   var cube=GameObject.CreatePrimitive(PrimitiveType.Cube);
   var mesh=UnityEngine.Object.Instantiate(cube.GetComponent<MeshFilter>().sharedMesh);AssetDatabase.CreateAsset(mesh,"Assets/Game/CrateMesh.asset");cube.GetComponent<MeshFilter>().sharedMesh=mesh;
   var material=new Material(Shader.Find("Standard"));material.color=new Color(.2f,.6f,.8f);AssetDatabase.CreateAsset(material,"Assets/Game/CrateMaterial.mat");cube.GetComponent<MeshRenderer>().sharedMaterial=material;
   cube.name="Crate";var prefab=PrefabUtility.SaveAsPrefabAsset(cube,"Assets/Game/Crate.prefab");UnityEngine.Object.DestroyImmediate(cube);
   var clip=new AnimationClip();clip.legacy=true;clip.SetCurve("",typeof(Transform),"localPosition.y",AnimationCurve.Linear(0,0,1,1));AssetDatabase.CreateAsset(clip,"Assets/Game/Move.anim");
   var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);var root=new GameObject("Warehouse");
   for(int n=0;n<50;n++){var go=(GameObject)PrefabUtility.InstantiatePrefab(prefab);go.name="Crate"+n;go.transform.SetParent(root.transform);go.transform.localPosition=new Vector3(n%10,0,n/10);}
   foreach(var name in new[]{"North","South"}) {var group=new GameObject(name);group.transform.SetParent(root.transform);var child=new GameObject("DuplicateDisplayName");child.transform.SetParent(group.transform);}
   var sound=new GameObject("NativeAudio");sound.transform.SetParent(root.transform);sound.AddComponent<AudioSource>().clip=AssetDatabase.LoadAssetAtPath<AudioClip>("Assets/Game/Tone.wav");
   var animated=new GameObject("NativeAnimation");animated.transform.SetParent(root.transform);var animation=animated.AddComponent<Animation>();animation.AddClip(clip,"move");animation.clip=clip;
   var counter=new GameObject("UnsupportedCriticalScore");counter.transform.SetParent(root.transform);counter.AddComponent<NEC017NativeCounter>();
   var spawn=new GameObject("SpawnMarker");spawn.transform.SetParent(root.transform);spawn.transform.localPosition=new Vector3(2,1,2);
   EditorSceneManager.SaveScene(scene,"Assets/Game/World.unity");
   var annex=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);var annexRoot=new GameObject("Annex");var other=(GameObject)PrefabUtility.InstantiatePrefab(prefab);other.transform.SetParent(annexRoot.transform);EditorSceneManager.SaveScene(annex,"Assets/Game/Annex.unity");
   var settings=AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/InputManager.asset");if(settings.Length==0)throw new Exception("InputManager absent");var input=new SerializedObject(settings[0]);var axes=input.FindProperty("m_Axes");axes.arraySize=1;var jump=axes.GetArrayElementAtIndex(0);jump.FindPropertyRelative("m_Name").stringValue="Jump";jump.FindPropertyRelative("positiveButton").stringValue="space";jump.FindPropertyRelative("type").intValue=0;input.ApplyModifiedPropertiesWithoutUndo();
   EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene("Assets/Game/World.unity",true),new EditorBuildSettingsScene("Assets/Game/Annex.unity",true)};
   AssetDatabase.SaveAssets();File.WriteAllText("fixture-created.json",JsonUtility.ToJson(new Report{engine=Application.unityVersion},true));EditorApplication.Exit(0);
  } catch(Exception e){Debug.LogException(e);EditorApplication.Exit(1);}
 }
}

using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using Xace.Authoring;
public static class NEC011UnityHierarchy {
 static GameObject Make(string name,int id,string kind){var go=new GameObject(name);var identity=go.AddComponent<XaceAuthoringIdentity>();identity.NamespaceId=100.ToString("x32");identity.AuthoringId=id.ToString("x32");identity.Kind=kind;return go;}
 public static void Run(){EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);Make("World",1,"scene");var parent=Make("Parent",2,"object");parent.transform.position=new Vector3(2,0,0);var child=Make("Child",3,"object");child.transform.SetParent(parent.transform,false);child.transform.localPosition=new Vector3(1,0,0);System.IO.Directory.CreateDirectory("Assets/Fixture");if(!EditorSceneManager.SaveScene(EditorSceneManager.GetActiveScene(),"Assets/Fixture/World.unity"))throw new System.Exception("save failed");AssetDatabase.SaveAssets();}
}

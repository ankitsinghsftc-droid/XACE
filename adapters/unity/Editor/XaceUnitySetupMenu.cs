// XaceUnitySetupMenu.cs
// Unity editor helpers for adding XACE runtime adapter objects to a scene.

using UnityEditor;
using UnityEngine;

namespace Xace.Adapter.Unity.Editor
{
    public static class XaceUnitySetupMenu
    {
        private const string RuntimeObjectName = "XACE Runtime";

        [MenuItem("Tools/XACE/Create Runtime Object")]
        public static void CreateRuntimeObject()
        {
            var existing = GameObject.Find(RuntimeObjectName);
            var root = existing != null ? existing : new GameObject(RuntimeObjectName);
            if (existing == null)
                Undo.RegisterCreatedObjectUndo(root, "Create XACE Runtime Object");

            EnsureComponent<XaceTransport>(root);
            EnsureComponent<XaceInputCollector>(root);
            EnsureComponent<XaceDeltaApplicator>(root);
            EnsureComponent<XaceConsoleWidget>(root);

            Selection.activeGameObject = root;
            EditorGUIUtility.PingObject(root);
            Debug.Log("[XACE] Runtime object is ready. Start xace_runtime, then press Play.");
        }

        [MenuItem("Tools/XACE/Create Runtime Object", true)]
        public static bool ValidateCreateRuntimeObject()
        {
            return !EditorApplication.isPlayingOrWillChangePlaymode;
        }

        private static T EnsureComponent<T>(GameObject root) where T : Component
        {
            var component = root.GetComponent<T>();
            if (component != null)
                return component;
            return Undo.AddComponent<T>(root);
        }
    }
}

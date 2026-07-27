// XaceUnityPlayBootstrap.cs
// Ensures the Unity adapter stack exists when the editor enters Play mode.

using UnityEditor;
using UnityEngine;

namespace Xace.Adapter.Unity.Editor
{
    [InitializeOnLoad]
    internal static class XaceUnityPlayBootstrap
    {
        static XaceUnityPlayBootstrap()
        {
            EditorApplication.playModeStateChanged -= OnPlayModeStateChanged;
            EditorApplication.playModeStateChanged += OnPlayModeStateChanged;
        }

        private static void OnPlayModeStateChanged(PlayModeStateChange state)
        {
            if (state != PlayModeStateChange.EnteredPlayMode)
                return;

            var root = XaceRuntimeBootstrap.EnsureRuntimeObjectForPlay();
            if (root != null)
                Debug.Log("[XACE] Unity runtime adapter is ready for Play mode.");
        }
    }
}

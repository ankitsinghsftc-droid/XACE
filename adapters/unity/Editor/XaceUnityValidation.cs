// XaceUnityValidation.cs
// Editor-only validation entry point for Unity package import/compile smoke.

using UnityEditor;
using UnityEngine;

namespace Xace.Adapter.Unity.Editor
{
    public static class XaceUnityValidation
    {
        public static void RunImportValidation()
        {
            GameObject root = null;
            try
            {
                root = new GameObject("XACE Validation Runtime Object")
                {
                    hideFlags = HideFlags.HideAndDontSave
                };

                ValidateComponent<XaceTransport>(root);
                ValidateComponent<XaceInputCollector>(root);
                ValidateComponent<XaceDeltaApplicator>(root);
                ValidateComponent<XaceConsoleWidget>(root);

                Debug.Log("[XACE] Unity adapter import validation passed.");
                if (Application.isBatchMode)
                    EditorApplication.Exit(0);
            }
            catch (System.Exception ex)
            {
                Debug.LogError("[XACE] Unity adapter import validation failed: " + ex);
                if (Application.isBatchMode)
                    EditorApplication.Exit(1);
            }
            finally
            {
                if (root != null)
                    Object.DestroyImmediate(root);
            }
        }

        private static void ValidateComponent<T>(GameObject root) where T : Component
        {
            var component = root.AddComponent<T>();
            if (component == null)
                throw new System.InvalidOperationException("Could not add component " + typeof(T).Name);
        }
    }
}

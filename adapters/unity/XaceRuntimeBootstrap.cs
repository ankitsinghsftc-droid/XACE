// XaceRuntimeBootstrap.cs
// Creates the Unity live-bridge object automatically when Play mode starts.

using UnityEngine;

namespace Xace.Adapter.Unity
{
    public static class XaceRuntimeBootstrap
    {
        private const string RuntimeObjectName = "XACE Runtime";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void EnsureRuntimeObject()
        {
            EnsureRuntimeObjectForPlay();
        }

        public static GameObject EnsureRuntimeObjectForPlay()
        {
            var transport = Object.FindAnyObjectByType<XaceTransport>();
            var root = transport != null ? transport.gameObject : new GameObject(RuntimeObjectName);

            root.name = RuntimeObjectName;
            if (Application.isPlaying)
                Object.DontDestroyOnLoad(root);
            var profile = Resources.Load<XaceNativeHostProfile>("XaceNativeHost");
            EnsureComponent<XaceTransport>(root);
            if (profile != null) root.GetComponent<XaceTransport>().ConfigureOwnedLifecycle();
            EnsureComponent<XaceInputCollector>(root);
            EnsureComponent<XaceDeltaApplicator>(root);
            EnsureComponent<XaceConsoleWidget>(root);
            if (profile != null && root.GetComponent<XaceNativeHost>() == null)
            {
                var native = root.AddComponent<XaceNativeHost>(); native.profile = profile;
            }
            return root;
        }

        private static void EnsureComponent<T>(GameObject root) where T : Component
        {
            if (root.GetComponent<T>() == null)
                root.AddComponent<T>();
        }
    }
}

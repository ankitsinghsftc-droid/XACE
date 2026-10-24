using System;
using System.IO;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    [CreateAssetMenu(menuName = "XACE/Approved Native Host Profile")]
    public sealed class XaceNativeHostProfile : ScriptableObject
    {
        public string gameId;
        public string releaseDirectory = "XACERelease";
        public string launcherFile = "xace-player-launcher.exe";
        public string launcherSha256;
        public string releaseSha256;
        public uint controllerId = 1;
        public XaceLiveInputBinding[] inputBindings = new XaceLiveInputBinding[0];
        public string ResolveRelease(string streamingAssets)
        {
            if (string.IsNullOrWhiteSpace(releaseDirectory) || Path.IsPathRooted(releaseDirectory)) throw new InvalidOperationException("Relative release directory required");
            string parent = Path.GetFullPath(streamingAssets).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string root = Path.GetFullPath(Path.Combine(parent, releaseDirectory));
            if (!root.StartsWith(parent, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Release escapes StreamingAssets");
            if (string.IsNullOrEmpty(launcherFile) || Path.GetFileName(launcherFile) != launcherFile) throw new InvalidOperationException("Launcher filename required");
            if (string.IsNullOrEmpty(gameId)) throw new InvalidOperationException("Stable game identity required");
            foreach (char c in gameId) if (!(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') && c != '-' && c != '_') throw new InvalidOperationException("Invalid game identity");
            return root;
        }
    }
}

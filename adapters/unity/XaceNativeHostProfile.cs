using System;
using System.IO;
using System.Collections.Generic;
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
        public void ValidateRequiredResources(string release)
        {
            var cgs=XaceCanonical.Parse(File.ReadAllText(Path.Combine(release,"package","game.cgs.json")));
            if(!cgs.TryGetValue("semantic_bindings",out var semantic))return;
            foreach(var value in (List<object>)XaceCanonical.Object(semantic)["bindings"])
            {
                var binding=XaceCanonical.Object(value);
                if(!binding.TryGetValue("parameters",out var raw))continue;
                var parameters=XaceCanonical.Object(raw);
                if(!parameters.TryGetValue("xace_binding_required",out var required)||Convert.ToString(required)!="true")continue;
                string path=XaceCanonical.Text(parameters,"resource_path");
                if(string.IsNullOrEmpty(path)||path.StartsWith("/",StringComparison.Ordinal)||path.Contains("..")||path.Contains("\\"))throw new InvalidOperationException("Invalid required native resource path");
                string kind=XaceCanonical.Text(binding,"playback_kind");
                if(kind=="Audio")
                {var clip=Resources.Load<AudioClip>(path);if(clip==null||clip.length<=0||clip.loadState==AudioDataLoadState.Failed)throw new InvalidOperationException("Required native audio missing: "+path);}
                else if(kind=="Animation")
                {var clip=Resources.Load<AnimationClip>(path);if(clip==null||!clip.legacy||clip.length<=0)throw new InvalidOperationException("Required native legacy animation missing/unsupported: "+path);}
                else throw new InvalidOperationException("Required native playback resource profile not supported: "+kind);
            }
        }
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

using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Xace.Adapter.Unity
{
    [DefaultExecutionOrder(-1000)]
    public sealed class XaceNativeHost : MonoBehaviour
    {
        public XaceNativeHostProfile profile;
        public string State { get; private set; } = "stopped";
        public string Error { get; private set; } = "";
        public int RuntimeProcessId { get; private set; }
        public string SaveRoot { get; private set; }
        public string SaveIdentityJson { get; private set; }
        public string SaveStatus { get; private set; } = "unchecked";
        public string SaveError { get; private set; } = "";
        bool savePending;
        // Admission only. Runtime restoration/migration is not performed by this API.
        public void CheckSave(string slot)
        {
            if(State!="playing" || savePending)throw new InvalidOperationException("Save check requires an admitted idle host");
            if(string.IsNullOrEmpty(slot)||slot.Length>64)throw new ArgumentException("Invalid save slot");
            foreach(char c in slot)if(!(c>='a'&&c<='z')&&!(c>='A'&&c<='Z')&&!(c>='0'&&c<='9')&&c!='-'&&c!='_')throw new ArgumentException("Invalid save slot");
            owner.CheckSave(slot);savePending=true;SaveStatus="checking";SaveError="";
        }
        public int OwnerProcessId => owner == null ? 0 : owner.ProcessId;
        XaceNativeHostClient owner;
        XaceTransport transport;
        string release;
        bool admitted;
        bool stopping;
        float deadline;
        void Start()
        {
            try
            {
                if (Application.platform != RuntimePlatform.WindowsEditor && Application.platform != RuntimePlatform.WindowsPlayer) throw new InvalidOperationException("Windows native host required");
                if (profile == null) throw new InvalidOperationException("Approved native host profile missing");
                transport = GetComponent<XaceTransport>();
                if (transport == null) throw new InvalidOperationException("Native transport missing");
                transport.ConfigureOwnedLifecycle();
                GetComponent<XaceInputCollector>().liveBindings = profile.inputBindings;
                transport.OnHandshakeAccepted += OnAdmitted;
                transport.OnConnectionChanged += OnConnection;
                transport.OnProtocolError += Fail;
                transport.OnHandshakeRejected += Fail;
                GetComponent<XaceDeltaApplicator>().OnPlaybackCommandApplied += OnPlayback;
                var bindings = new Dictionary<string, GameObject>(StringComparer.Ordinal);
                foreach (var binding in UnityEngine.Object.FindObjectsByType<XaceNativeSceneBinding>(FindObjectsInactive.Include, FindObjectsSortMode.None))
                {
                    if (string.IsNullOrWhiteSpace(binding.worldObjectId) || bindings.ContainsKey(binding.worldObjectId)) throw new InvalidOperationException("Duplicate or missing native World identity");
                    bindings.Add(binding.worldObjectId, binding.gameObject);
                }
                GetComponent<XaceDeltaApplicator>().ConfigureNativeObjects(bindings);
                release = profile.ResolveRelease(Application.streamingAssetsPath);
                profile.ValidateRequiredResources(release);
                XaceNativeSceneBinding.ValidateWorld(File.ReadAllText(Path.Combine(release,"package","world.json")),bindings);
                string userData = Environment.GetEnvironmentVariable("LOCALAPPDATA");
                if(string.IsNullOrEmpty(userData)||!Path.IsPathRooted(userData))throw new InvalidOperationException("Absolute per-user LocalAppData required");
                string history = Path.Combine(userData, "XACE", "NativeGames", "game-" + profile.gameId, "native-history");
                owner = new XaceNativeHostClient();
                owner.Start(Path.Combine(release, profile.launcherFile), profile.launcherSha256, release, profile.releaseSha256, history, profile.controllerId);
                State = "verifying"; deadline = Time.realtimeSinceStartup + 20;
                SceneManager.sceneUnloaded += OnSceneUnloaded;
            }
            catch (Exception error) { Fail(error.Message); }
        }
        void Update()
        {
            if (owner == null || stopping) return;
            try
            {
                while (owner.TryReceive(out var message))
                {
                    if (message.TryGetValue("ok", out var ok) && ok is bool accepted && !accepted)
                    {
                        string why=message.TryGetValue("message",out var reason)?Convert.ToString(reason):"Authority lost";
                        if(savePending&&message.TryGetValue("state",out var failure)&&Convert.ToString(failure)=="refused")
                        {savePending=false;SaveStatus="refused";SaveError=why;continue;}
                        throw new InvalidOperationException(why);
                    }
                    string schema = message.TryGetValue("schema", out var kind) ? Convert.ToString(kind) : "";
                    if (schema == "xace.native_host.ready.v1")
                    {
                        var identity = XaceCanonical.Object(message["save_identity"]);
                        if (XaceCanonical.Text(identity, "game_id") != profile.gameId) throw new InvalidOperationException("Native game/save identity differs from approved profile");
                        SaveRoot=XaceCanonical.Text(message,"save_root");SaveIdentityJson=XaceJson.Serialize(identity);
                        State = "starting"; owner.Play(); continue;
                    }
                    if (!message.TryGetValue("result", out var value)) continue;
                    var result = XaceCanonical.Object(value);
                    if(XaceCanonical.Text(result,"state")=="save_compatible")
                    {if(!savePending||!(result["restored"] is bool restored)||restored)throw new InvalidOperationException("Unexpected save response");savePending=false;SaveStatus="compatible-not-restored";continue;}
                    if (XaceCanonical.Text(result, "state") != "ready") continue;
                    if (XaceCanonical.Text(result, "release") != profile.releaseSha256) throw new InvalidOperationException("Native release identity differs");
                    RuntimeProcessId = (int)XaceCanonical.Integer(result["runtime_pid"]);
                    string ticket = File.ReadAllText(XaceCanonical.Text(result, "ticket"));
                    var grant = XaceCanonical.Parse(ticket);
                    var offer = XaceCanonical.Object(grant["offer"]);
                    var gameplay = XaceCanonical.Object(XaceCanonical.Object(offer["contract"])["gameplay"]);
                    string hash = XaceCanonical.Text(XaceCanonical.Object(gameplay["cgs"]), "cgs_hash");
                    string endpoint = XaceCanonical.Text(result, "endpoint");
                    if (!endpoint.StartsWith("127.0.0.1:", StringComparison.Ordinal)) throw new InvalidOperationException("Native endpoint is not local");
                    int port = int.Parse(endpoint.Substring(10), System.Globalization.CultureInfo.InvariantCulture);
                    transport.ConfigureConnection("127.0.0.1", port, hash);
                    transport.ConfigureLiveSession(ticket, File.ReadAllText(Path.Combine(release, "package", "world.json")));
                    State = "connecting"; transport.Connect();
                }
                if (!admitted && Time.realtimeSinceStartup > deadline) throw new TimeoutException("Native Play readiness timeout");
            }
            catch (Exception error) { Fail(error.Message); }
        }
        void OnPlayback(XacePlaybackCommand command,bool applied){if(!applied)Fail("Native playback resource failed: "+command.binding_id);}
        void OnAdmitted(XaceHandshakeAck ack) { admitted = true; State = "playing"; }
        void OnConnection(bool connected) { if (!connected && admitted && !stopping) Fail("Native authority disconnected; gameplay frozen"); }
        void OnSceneUnloaded(Scene scene) { if (!stopping) Fail("Native scene changed; stop and reopen the approved scene before Play"); }
        void Fail(string message)
        {
            if (stopping) return;
            Error = message; State = "failed"; Debug.LogError("[XACE] " + message); StopOwned();
        }
        void StopOwned()
        {
            stopping = true;
            SceneManager.sceneUnloaded -= OnSceneUnloaded;
            if (transport != null)
            {
                transport.OnHandshakeAccepted -= OnAdmitted; transport.OnConnectionChanged -= OnConnection;
                transport.OnProtocolError -= Fail; transport.OnHandshakeRejected -= Fail;
                transport.Disconnect("native host stopped");
            }
            var applicator=GetComponent<XaceDeltaApplicator>();if(applicator!=null)applicator.OnPlaybackCommandApplied-=OnPlayback;
            if (owner != null) { owner.Dispose(); owner = null; }
        }
        void OnDisable() { StopOwned(); }
        void OnDestroy() { StopOwned(); }
        void OnApplicationQuit() { StopOwned(); }
        void OnGUI() { if (State == "failed") GUI.Label(new Rect(15, 15, Screen.width - 30, 70), "XACE stopped: " + Error); }
    }
}

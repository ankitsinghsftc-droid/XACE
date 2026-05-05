// Unity TCP client — // XaceTransport.cs
// Unity TCP client — connects to the XACE runtime, sends and receives
// WireMessages using the 4-byte big-endian length-prefix framing protocol.
//
// ## Architecture
// XACE is the TCP server. Unity is the client. XaceTransport owns the socket,
// the receive loop, and the outbound queue. All other Unity adapter scripts
// call XaceTransport.Send() to push messages, and subscribe to OnMessageReceived
// to get inbound messages.
//
// ## Reconnect
// If the connection drops, XaceTransport attempts reconnect with exponential
// backoff (1s, 2s, 4s, 8s, cap 30s). All queued outbound messages are
// discarded on disconnect — the XACE runtime will send a fresh SNAPSHOT
// on reconnect.
//
// ## Thread Safety
// The receive loop runs on a background Thread. Inbound messages are queued
// in a thread-safe ConcurrentQueue and dispatched on the Unity main thread
// in Update(). Send() is also safe to call from any thread.
//
// ## Asset Resolution on Connect
// When the handshake completes, XaceTransport scans all loaded Unity assets
// and sends an AssetResolutionUpdateFeedback containing all asset_ids that
// Unity has successfully loaded. This transitions PLACEHOLDER → LINKED in
// the XACE Asset Registry (Audit 2, Audit 6).
//
// ## Wire Protocol
// Each WireMessage is framed as:
//   [4 bytes big-endian uint32 = payload length][JSON payload bytes]
// Maximum message size: 16 MiB (enforced on receive, matches Rust).

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    /// <summary>
    /// Manages the TCP connection between Unity and the XACE runtime.
    /// Attach to a persistent GameObject in your scene (DontDestroyOnLoad).
    /// </summary>
    public class XaceTransport : MonoBehaviour
    {
        // ── Inspector Configuration ────────────────────────────────────────

        [Header("Connection")]
        [Tooltip("IP address of the XACE runtime host.")]
        [SerializeField] private string _host = "127.0.0.1";

        [Tooltip("TCP port the XACE runtime is listening on.")]
        [SerializeField] private int _port = 7890;

        [Tooltip("World ID — must match world_id in game_config.yaml.")]
        [SerializeField] private string _worldId = "default";

        [Header("Reconnect")]
        [SerializeField] private float _initialReconnectDelaySec = 1f;
        [SerializeField] private float _maxReconnectDelaySec     = 30f;

        [Header("Protocol")]
        [SerializeField] private string _schemaVersion       = "0.1.0";
        [SerializeField] private uint   _executionPlanVersion = 1;

        // ── Events ─────────────────────────────────────────────────────────

        /// <summary>Fired on the Unity main thread when a WireMessage arrives.</summary>
        public event Action<WireMessage> OnMessageReceived;

        /// <summary>Fired on the Unity main thread when the connection state changes.</summary>
        public event Action<bool> OnConnectionChanged;

        // ── State ──────────────────────────────────────────────────────────

        private TcpClient             _client;
        private NetworkStream         _stream;
        private Thread                _receiveThread;
        private volatile bool         _connected;
        private volatile bool         _shutdown;
        private float                 _reconnectDelay;
        private float                 _reconnectTimer;

        // Outbound queue — filled by Send(), drained in Update()
        private readonly ConcurrentQueue<byte[]> _sendQueue    = new();
        // Inbound queue — filled by receive thread, dispatched in Update()
        private readonly ConcurrentQueue<WireMessage> _recvQueue = new();

        // Sequence counters (one per outbound message type)
        private uint _deltaSequence    = 0;
        private uint _feedbackSequence = 0;
        private uint _inputSequence    = 0;
        private uint _controlSequence  = 0;

        // Maximum frame size — matches Rust MAX_MESSAGE_SIZE
        private const int MaxFrameSize = 16 * 1024 * 1024;

        // ── Unity Lifecycle ────────────────────────────────────────────────

        private void Start()
        {
            DontDestroyOnLoad(gameObject);
            _reconnectDelay = _initialReconnectDelaySec;
            BeginConnect();
        }

        private void Update()
        {
            // Dispatch inbound messages on the main thread
            while (_recvQueue.TryDequeue(out WireMessage msg))
                OnMessageReceived?.Invoke(msg);

            // Flush outbound queue to socket
            if (_connected && _stream != null)
                FlushSendQueue();

            // Reconnect timer
            if (!_connected && !_shutdown)
            {
                _reconnectTimer += Time.unscaledDeltaTime;
                if (_reconnectTimer >= _reconnectDelay)
                {
                    _reconnectTimer = 0f;
                    _reconnectDelay = Mathf.Min(_reconnectDelay * 2f, _maxReconnectDelaySec);
                    BeginConnect();
                }
            }
        }

        private void OnDestroy()
        {
            _shutdown = true;
            Disconnect();
        }

        // ── Public API ─────────────────────────────────────────────────────

        /// <summary>
        /// Sends a WireMessage to the XACE runtime.
        /// Thread-safe — can be called from any thread.
        /// </summary>
        public void Send(WireMessage msg)
        {
            if (!_connected) return;
            byte[] frame = FrameMessage(msg);
            _sendQueue.Enqueue(frame);
        }

        /// <summary>Sends a FEEDBACK WireMessage.</summary>
        public void SendFeedback(object feedbackPayload)
        {
            string json = JsonUtility.ToJson(feedbackPayload);
            Send(BuildMessage(MessageType.Feedback, json, ref _feedbackSequence));
        }

        /// <summary>Whether the transport is currently connected to XACE.</summary>
        public bool IsConnected => _connected;

        // ── Connection Management ──────────────────────────────────────────

        private void BeginConnect()
        {
            try
            {
                _client = new TcpClient();
                _client.Connect(_host, _port);
                _stream = _client.GetStream();
                _connected = true;
                _reconnectDelay = _initialReconnectDelaySec;

                Debug.Log($"[XaceTransport] Connected to XACE at {_host}:{_port}");
                OnConnectionChanged?.Invoke(true);

                PerformHandshake();
                SendInitialAssetResolution();

                _receiveThread = new Thread(ReceiveLoop)
                {
                    IsBackground = true,
                    Name = "XaceReceiveThread",
                };
                _receiveThread.Start();
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[XaceTransport] Connect failed: {ex.Message}. " +
                                 $"Retrying in {_reconnectDelay:F1}s...");
                _connected = false;
            }
        }

        private void Disconnect()
        {
            _connected = false;
            try { _stream?.Close(); } catch { /* ignored */ }
            try { _client?.Close(); } catch { /* ignored */ }
            _stream = null;
            _client = null;
            OnConnectionChanged?.Invoke(false);
        }

        // ── Handshake ──────────────────────────────────────────────────────

        private void PerformHandshake()
        {
            var hello = new HandshakeHello
            {
                control_type          = "Hello",
                protocol_version      = WireProtocol.ProtocolVersion,
                schema_version        = _schemaVersion,
                execution_plan_version = _executionPlanVersion,
                world_id              = _worldId,
                engine_name           = "Unity",
                adapter_version       = Application.unityVersion,
            };
            Send(BuildMessage(MessageType.Control, JsonUtility.ToJson(hello), ref _controlSequence));
            Debug.Log("[XaceTransport] Handshake Hello sent.");
        }

        // ── Asset Resolution on Connect (Audit 2 + Audit 6) ───────────────

        /// <summary>
        /// Scans all loaded Unity assets and sends an AssetResolutionUpdateFeedback
        /// to transition PLACEHOLDER → LINKED in the XACE Asset Registry.
        /// Called once after the handshake completes.
        /// </summary>
        private void SendInitialAssetResolution()
        {
            var resolved = new Dictionary<string, string>();

            // Scan all loaded prefabs and meshes for XACE asset_id naming pattern
            // In production, this is populated from the project's AssetManifest
            // (imported via a Unity Editor tool that maps asset_ids to GUIDs).
            // In Phase 7 we send all loaded resources that match the naming convention.
            var resources = Resources.LoadAll<UnityEngine.Object>("");
            foreach (var resource in resources)
            {
                string assetId = AssetIdFromUnityName(resource.name);
                if (!string.IsNullOrEmpty(assetId))
                    resolved[assetId] = $"unity_resource://{resource.name}";
            }

            if (resolved.Count == 0) return;

            var payload = new AssetResolutionUpdateFeedback
            {
                resolved_assets = resolved,
                generated_frame = 0,
            };

            SendFeedback(payload);
            Debug.Log($"[XaceTransport] Sent initial asset resolution: {resolved.Count} assets.");
        }

        /// <summary>
        /// Derives an XACE canonical asset_id from a Unity resource name.
        /// Only returns a value if the name matches the XACE naming pattern.
        /// Pattern: [entity_type]_[entity_name]_[suffix]_v[N]
        /// </summary>
        private static string AssetIdFromUnityName(string unityName)
        {
            // Simple pattern check — matches known XACE asset suffixes
            string[] knownSuffixes = { "_mesh_v", "_tex_v", "_mat_v", "_anim_v",
                                       "_sfx_v", "_music_v", "_sprite_v", "_vfx_v",
                                       "_prefab_v", "_font_v" };
            string lower = unityName.ToLowerInvariant();
            foreach (string suffix in knownSuffixes)
            {
                if (lower.Contains(suffix))
                    return lower; // already in XACE format
            }
            return null;
        }

        // ── Receive Loop (Background Thread) ──────────────────────────────

        private void ReceiveLoop()
        {
            byte[] lenBuf = new byte[4];
            while (_connected && !_shutdown)
            {
                try
                {
                    // Read 4-byte big-endian length prefix
                    if (!ReadExact(lenBuf, 4)) break;
                    uint payloadLen = ReadUInt32BigEndian(lenBuf);

                    if (payloadLen > MaxFrameSize)
                    {
                        Debug.LogError($"[XaceTransport] Frame too large: {payloadLen} bytes. Disconnecting.");
                        break;
                    }

                    // Read payload
                    byte[] payload = new byte[payloadLen];
                    if (!ReadExact(payload, (int)payloadLen)) break;

                    string json = Encoding.UTF8.GetString(payload);
                    WireMessage msg = JsonUtility.FromJson<WireMessage>(json);

                    if (msg != null)
                        _recvQueue.Enqueue(msg);
                }
                catch (Exception ex) when (!_shutdown)
                {
                    Debug.LogWarning($"[XaceTransport] Receive error: {ex.Message}");
                    break;
                }
            }

            if (!_shutdown)
            {
                _connected = false;
                Debug.LogWarning("[XaceTransport] Connection lost. Will reconnect...");
            }
        }

        private bool ReadExact(byte[] buffer, int count)
        {
            int offset = 0;
            while (offset < count)
            {
                try
                {
                    int read = _stream.Read(buffer, offset, count - offset);
                    if (read == 0) return false; // connection closed
                    offset += read;
                }
                catch { return false; }
            }
            return true;
        }

        // ── Send Queue Flush ───────────────────────────────────────────────

        private void FlushSendQueue()
        {
            while (_sendQueue.TryDequeue(out byte[] frame))
            {
                try
                {
                    _stream.Write(frame, 0, frame.Length);
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[XaceTransport] Send error: {ex.Message}");
                    Disconnect();
                    return;
                }
            }
        }

        // ── Wire Helpers ───────────────────────────────────────────────────

        private WireMessage BuildMessage(MessageType type, string payload, ref uint sequence)
        {
            return new WireMessage
            {
                protocol_version       = WireProtocol.ProtocolVersion,
                world_id               = _worldId,
                schema_version         = _schemaVersion,
                execution_plan_version = _executionPlanVersion,
                tick                   = 0,
                sequence_id            = sequence++,
                message_type           = (int)type,
                payload                = payload,
            };
        }

        private static byte[] FrameMessage(WireMessage msg)
        {
            byte[] payload = Encoding.UTF8.GetBytes(JsonUtility.ToJson(msg));
            byte[] frame   = new byte[4 + payload.Length];
            WriteUInt32BigEndian(frame, 0, (uint)payload.Length);
            Buffer.BlockCopy(payload, 0, frame, 4, payload.Length);
            return frame;
        }

        private static uint ReadUInt32BigEndian(byte[] buf)
            => (uint)((buf[0] << 24) | (buf[1] << 16) | (buf[2] << 8) | buf[3]);

        private static void WriteUInt32BigEndian(byte[] buf, int offset, uint value)
        {
            buf[offset + 0] = (byte)(value >> 24);
            buf[offset + 1] = (byte)(value >> 16);
            buf[offset + 2] = (byte)(value >> 8);
            buf[offset + 3] = (byte)(value);
        }
    }

    // ── Wire Protocol Constants ────────────────────────────────────────────────

    public static class WireProtocol
    {
        public const uint ProtocolVersion = 1;
    }

    public enum MessageType { Snapshot = 0, Delta = 1, Input = 2, Event = 3, Control = 4, Feedback = 5 }

    // ── Wire Message (matches Rust WireMessage) ────────────────────────────────

    [Serializable]
    public class WireMessage
    {
        public uint   protocol_version;
        public string world_id;
        public string schema_version;
        public uint   execution_plan_version;
        public ulong  tick;
        public ulong  sequence_id;
        public int    message_type;
        public string payload;

        public bool IsSnapshot => message_type == (int)MessageType.Snapshot;
        public bool IsDelta    => message_type == (int)MessageType.Delta;
        public bool IsInput    => message_type == (int)MessageType.Input;
        public bool IsFeedback => message_type == (int)MessageType.Feedback;
        public bool IsControl  => message_type == (int)MessageType.Control;
    }

    // ── Handshake Payloads ─────────────────────────────────────────────────────

    [Serializable]
    public class HandshakeHello
    {
        public string control_type;
        public uint   protocol_version;
        public string schema_version;
        public uint   execution_plan_version;
        public string world_id;
        public string engine_name;
        public string adapter_version;
    }

    // ── Asset Resolution Feedback Payload ──────────────────────────────────────

    [Serializable]
    public class AssetResolutionUpdateFeedback
    {
        public Dictionary<string, string> resolved_assets;
        public ulong generated_frame;
    }
}connects to XACE runtime, sends/receives WireMessages, handles reconnect — Phase 7

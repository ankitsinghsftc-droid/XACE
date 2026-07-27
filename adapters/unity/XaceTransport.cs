// XaceTransport.cs
// Unity TCP client for the Phase 15 runtime bridge.
//
// Contract source:
//   packages/runtime-core/src/engine_protocol.rs
//
// Frames are:
//   [u32 little-endian payload_length][UTF-8 JSON payload]
//
// Runtime messages use the lightweight engine bridge schema:
//   engine -> runtime: handshake, input_packet, feedback_payload
//   runtime -> engine: handshake_ack, tick_snapshot, disconnect, error
//
// This file also exposes a small dictionary JSON reader because Unity's
// JsonUtility cannot deserialize arbitrary JSON objects such as the component
// maps inside EntityState.

using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    public sealed class XaceTransport : MonoBehaviour
    {
        public const uint ProtocolVersion = 1;
        public const int DefaultPort = 7777;
        public const int MaxFrameBytes = 4 * 1024 * 1024;

        [Header("Connection")]
        [SerializeField] private string host = "127.0.0.1";
        [SerializeField] private int port = DefaultPort;
        [SerializeField] private bool autoConnect = true;
        [SerializeField] private bool reconnect = true;
        [SerializeField] private float initialReconnectDelaySeconds = 1f;
        [SerializeField] private float maxReconnectDelaySeconds = 30f;
        [SerializeField] private bool disableCompanionComponents = false;

        [Header("Validation Feedback")]
        [SerializeField] private bool disableLiveValidationFeedback = false;
        [SerializeField] private int liveValidationFeedbackEverySnapshots = 30;

        [Header("Handshake")]
        [SerializeField] private string engineName = "Unity";
        [SerializeField] private string adapterVersion = "0.1.0";
        [SerializeField] private string cgsHash = "";
        [SerializeField] private string[] capabilities =
        {
            "length_prefixed_json",
            "tick_snapshot_v1",
            "input_packet_v1",
            "feedback_payload_v1",
            "unity"
        };

        public event Action<bool> OnConnectionChanged;
        public event Action<XaceHandshakeAck> OnHandshakeAccepted;
        public event Action<string> OnHandshakeRejected;
        public event Action<XaceRuntimeMessage> OnMessageReceived;
        public event Action<XaceTickSnapshot> OnTickSnapshot;
        public event Action<string> OnProtocolError;

        private readonly ConcurrentQueue<string> outboundJson = new ConcurrentQueue<string>();
        private readonly ConcurrentQueue<XaceRuntimeMessage> inboundMessages = new ConcurrentQueue<XaceRuntimeMessage>();
        private readonly ConcurrentQueue<Action> mainThreadActions = new ConcurrentQueue<Action>();
        private readonly object streamLock = new object();

        private TcpClient client;
        private NetworkStream stream;
        private Thread receiveThread;
        private volatile bool connected;
        private volatile bool stopping;
        private volatile bool handshakeComplete;
        private float reconnectDelay;
        private float reconnectTimer;
        private ulong sequenceId = 1;
        private ulong snapshotsDispatched;
        private XaceTransportStats stats;
        private string lastError = "";

        public bool IsConnected => connected;
        public bool IsHandshakeComplete => handshakeComplete;
        public ulong NextSequenceId() => sequenceId++;
        public XaceTransportStats Stats => stats;
        public string LastError => lastError;

        private void Awake()
        {
            reconnectDelay = Mathf.Max(0.1f, initialReconnectDelaySeconds);
            EnsureCompanionComponents();
        }

        private void OnEnable()
        {
            EnsureCompanionComponents();
        }

        private void Start()
        {
            EnsureCompanionComponents();
            if (autoConnect)
                Connect();
        }

        private void Update()
        {
            PumpOnce();
        }

        public void ConfigureConnection(string newHost, int newPort, string newCgsHash = null)
        {
            if (!string.IsNullOrWhiteSpace(newHost))
                host = newHost.Trim();
            port = Mathf.Clamp(newPort, 1, 65535);
            if (newCgsHash != null)
                cgsHash = PortableText(newCgsHash, 128, "");
        }

        public void PumpOnce()
        {
            while (mainThreadActions.TryDequeue(out var action))
                action?.Invoke();

            while (inboundMessages.TryDequeue(out var message))
                DispatchInbound(message);

            if (connected)
                FlushOutbound();
            else if (!stopping && reconnect)
                TickReconnectTimer();
        }

        private void OnDestroy()
        {
            stopping = true;
            Disconnect("destroyed");
        }

        public void Connect()
        {
            if (connected)
                return;

            try
            {
                Disconnect("reconnect");
                stopping = false;
                client = new TcpClient();
                client.NoDelay = true;
                client.Connect(host, Mathf.Clamp(port, 1, 65535));
                stream = client.GetStream();
                connected = true;
                handshakeComplete = false;
                reconnectDelay = Mathf.Max(0.1f, initialReconnectDelaySeconds);
                reconnectTimer = 0f;

                SendHandshakeImmediately();
                receiveThread = new Thread(ReceiveLoop)
                {
                    IsBackground = true,
                    Name = "XACE Unity Receive"
                };
                receiveThread.Start();

                mainThreadActions.Enqueue(() => OnConnectionChanged?.Invoke(true));
            }
            catch (Exception ex)
            {
                Fail("connect failed: " + ex.Message);
                connected = false;
                handshakeComplete = false;
                CloseSocket();
            }
        }

        public void Disconnect(string reason = "disconnect")
        {
            connected = false;
            handshakeComplete = false;
            ClearOutboundQueue();
            CloseSocket();
            mainThreadActions.Enqueue(() => OnConnectionChanged?.Invoke(false));
            if (!string.IsNullOrEmpty(reason))
                Debug.Log("[XACE] Unity transport disconnected: " + reason);
        }

        public bool SendInputPacket(XaceInputPacket packet)
        {
            if (packet == null)
                return false;
            packet.msg_type = XaceProtocolNames.InputPacket;
            if (packet.peer_id <= 0)
                packet.peer_id = 1;
            if (packet.sequence_id == 0)
                packet.sequence_id = NextSequenceId();
            return SendJson(XaceJson.Serialize(packet.ToDictionary()));
        }

        public bool SendDictionary(IDictionary<string, object> message)
        {
            if (message == null)
                return false;
            return SendJson(XaceJson.Serialize(message));
        }

        public bool SendDictionaryImmediately(IDictionary<string, object> message)
        {
            if (message == null)
                return false;
            return SendJsonImmediately(XaceJson.Serialize(message));
        }

        public bool SendJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
                return false;
            if (!connected || stream == null)
                return false;
            outboundJson.Enqueue(json);
            stats.queuedMessages = outboundJson.Count;
            return connected;
        }

        public bool SendJsonImmediately(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
                return false;
            if (!connected || stream == null)
                return false;
            try
            {
                WriteFrame(json);
                stats.framesSent++;
                stats.queuedMessages = outboundJson.Count;
                return true;
            }
            catch (Exception ex)
            {
                Fail("send failed: " + ex.Message);
                connected = false;
                handshakeComplete = false;
                CloseSocket();
                return false;
            }
        }

        private void TickReconnectTimer()
        {
            reconnectTimer += Time.unscaledDeltaTime;
            if (reconnectTimer < reconnectDelay)
                return;
            reconnectTimer = 0f;
            reconnectDelay = Mathf.Min(Mathf.Max(0.1f, reconnectDelay * 2f), maxReconnectDelaySeconds);
            Connect();
        }

        private void SendHandshakeImmediately()
        {
            var hello = new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["msg_type"] = XaceProtocolNames.Handshake,
                ["protocol_version"] = ProtocolVersion,
                ["engine_name"] = PortableText(engineName, 96, "Unity"),
                ["engine_version"] = PortableText(Application.unityVersion, 64, "unknown"),
                ["adapter_version"] = PortableText(adapterVersion, 64, "0.1.0"),
                ["cgs_hash"] = PortableText(cgsHash, 128, ""),
                ["capabilities"] = NormaliseCapabilities(capabilities)
            };
            WriteFrame(XaceJson.Serialize(hello));
            stats.framesSent++;
        }

        private void FlushOutbound()
        {
            while (connected && outboundJson.TryDequeue(out var json))
            {
                try
                {
                    WriteFrame(json);
                    stats.framesSent++;
                    stats.queuedMessages = outboundJson.Count;
                }
                catch (Exception ex)
                {
                    Fail("send failed: " + ex.Message);
                    connected = false;
                    CloseSocket();
                    break;
                }
            }
        }

        private void ReceiveLoop()
        {
            var lengthBytes = new byte[4];
            while (connected && !stopping)
            {
                try
                {
                    if (!ReadExact(lengthBytes, 4))
                        break;

                    var length = ReadUInt32LittleEndian(lengthBytes);
                    if (length == 0 || length > MaxFrameBytes)
                        throw new InvalidDataException("invalid frame length: " + length);

                    var payload = new byte[length];
                    if (!ReadExact(payload, (int)length))
                        break;

                    stats.bytesReceived += length + 4;
                    var json = Encoding.UTF8.GetString(payload);
                    var parsed = XaceJson.DeserializeObject(json);
                    if (parsed == null)
                        throw new InvalidDataException("frame payload is not a JSON object");

                    var message = new XaceRuntimeMessage(json, parsed);
                    inboundMessages.Enqueue(message);
                    stats.framesReceived++;
                }
                catch (Exception ex)
                {
                    if (!stopping)
                        Fail("receive failed: " + ex.Message);
                    break;
                }
            }

            if (!stopping)
            {
                connected = false;
                handshakeComplete = false;
                CloseSocket();
                mainThreadActions.Enqueue(() => OnConnectionChanged?.Invoke(false));
            }
        }

        private bool ReadExact(byte[] buffer, int count)
        {
            var offset = 0;
            while (offset < count && connected && !stopping)
            {
                var read = stream.Read(buffer, offset, count - offset);
                if (read <= 0)
                    return false;
                offset += read;
            }
            return offset == count;
        }

        private void WriteFrame(string json)
        {
            var payload = Encoding.UTF8.GetBytes(json);
            if (payload.Length <= 0 || payload.Length > MaxFrameBytes)
                throw new InvalidDataException("outbound frame size invalid: " + payload.Length);

            var frame = new byte[payload.Length + 4];
            WriteUInt32LittleEndian(frame, 0, (uint)payload.Length);
            Buffer.BlockCopy(payload, 0, frame, 4, payload.Length);

            lock (streamLock)
            {
                if (stream == null)
                    throw new IOException("not connected");
                stream.Write(frame, 0, frame.Length);
                stream.Flush();
            }
            stats.bytesSent += (ulong)frame.Length;
        }

        private void DispatchInbound(XaceRuntimeMessage message)
        {
            var type = message.MessageType;
            switch (type)
            {
                case XaceProtocolNames.HandshakeAck:
                    DispatchHandshakeAck(message);
                    break;
                case XaceProtocolNames.TickSnapshot:
                    var snapshot = XaceTickSnapshot.FromMessage(message);
                    QueueLiveValidationFeedback(snapshot);
                    DispatchTickSnapshot(snapshot);
                    OnMessageReceived?.Invoke(message);
                    break;
                case XaceProtocolNames.Disconnect:
                    Disconnect(message.GetString("reason", "runtime disconnect"));
                    break;
                case XaceProtocolNames.Error:
                    Fail(message.GetString("message", "runtime error"));
                    OnMessageReceived?.Invoke(message);
                    break;
                default:
                    OnMessageReceived?.Invoke(message);
                    break;
            }
        }

        private void DispatchHandshakeAck(XaceRuntimeMessage message)
        {
            var ack = XaceHandshakeAck.FromMessage(message);
            if (ack.accepted)
            {
                handshakeComplete = true;
                OnHandshakeAccepted?.Invoke(ack);
                OnMessageReceived?.Invoke(message);
            }
            else
            {
                handshakeComplete = false;
                var reason = string.IsNullOrEmpty(ack.reject_reason) ? "handshake rejected" : ack.reject_reason;
                OnHandshakeRejected?.Invoke(reason);
                Disconnect(reason);
            }
        }

        private void DispatchTickSnapshot(XaceTickSnapshot snapshot)
        {
            var handlers = OnTickSnapshot;
            if (handlers == null)
                return;

            foreach (Action<XaceTickSnapshot> handler in handlers.GetInvocationList())
            {
                try
                {
                    handler?.Invoke(snapshot);
                }
                catch (Exception ex)
                {
                    Fail("tick snapshot listener failed: " + ex.Message);
                }
            }
        }

        private void CloseSocket()
        {
            try { stream?.Close(); } catch { }
            try { client?.Close(); } catch { }
            stream = null;
            client = null;
        }

        private void ClearOutboundQueue()
        {
            while (outboundJson.TryDequeue(out _)) { }
            stats.queuedMessages = 0;
        }

        private void Fail(string message)
        {
            lastError = message;
            stats.protocolErrors++;
            Debug.LogWarning("[XACE] " + message);
            mainThreadActions.Enqueue(() => OnProtocolError?.Invoke(message));
        }

        private void EnsureCompanionComponents()
        {
            if (disableCompanionComponents)
                return;
            EnsureComponent<XaceInputCollector>();
            EnsureComponent<XaceDeltaApplicator>();
            EnsureComponent<XaceConsoleWidget>();
        }

        private void EnsureComponent<T>() where T : Component
        {
            if (GetComponent<T>() == null)
                gameObject.AddComponent<T>();
        }

        private void QueueLiveValidationFeedback(XaceTickSnapshot snapshot)
        {
            if (disableLiveValidationFeedback || snapshot == null || !connected)
                return;
            snapshotsDispatched++;
            var stride = Mathf.Max(1, liveValidationFeedbackEverySnapshots);
            if (snapshotsDispatched != 1 && snapshotsDispatched % (ulong)stride != 0)
                return;

            var payload = new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["adapter_engine"] = "unity",
                ["delta_applicator_present"] = GetComponent<XaceDeltaApplicator>() != null,
                ["draw_calls"] = 0,
                ["engine_delta_apply_ms"] = 0f,
                ["engine_entity_count"] = snapshot.entities != null ? snapshot.entities.Count : 0,
                ["generated_frame"] = snapshot.tick,
                ["input_collector_present"] = GetComponent<XaceInputCollector>() != null,
                ["message_type"] = "tick_snapshot_dispatched",
                ["physics_contacts"] = 0,
                ["runtime_tick"] = snapshot.tick,
                ["transport_frames_received"] = stats.framesReceived,
                ["xace_live_validation"] = true
            };
            var message = new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["feedback_type"] = "PerformanceMetrics",
                ["entity_id"] = 0,
                ["generated_frame"] = snapshot.tick,
                ["payload_json"] = XaceJson.Serialize(payload)
            };
            var batch = new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["msg_type"] = "feedback_payload",
                ["tick"] = snapshot.tick,
                ["messages"] = new List<object> { message }
            };
            SendDictionaryImmediately(batch);
        }

        private static uint ReadUInt32LittleEndian(byte[] bytes)
        {
            return (uint)(bytes[0] | (bytes[1] << 8) | (bytes[2] << 16) | (bytes[3] << 24));
        }

        private static void WriteUInt32LittleEndian(byte[] bytes, int offset, uint value)
        {
            bytes[offset] = (byte)(value & 0xff);
            bytes[offset + 1] = (byte)((value >> 8) & 0xff);
            bytes[offset + 2] = (byte)((value >> 16) & 0xff);
            bytes[offset + 3] = (byte)((value >> 24) & 0xff);
        }

        private static string[] NormaliseCapabilities(IEnumerable<string> input)
        {
            var set = new SortedSet<string>(StringComparer.Ordinal);
            if (input != null)
            {
                foreach (var item in input)
                {
                    var normalised = PortableText(item, 64, "");
                    if (!string.IsNullOrEmpty(normalised))
                        set.Add(normalised);
                }
            }
            return new List<string>(set).ToArray();
        }

        private static string PortableText(string value, int maxBytes, string fallback)
        {
            if (string.IsNullOrWhiteSpace(value))
                return fallback;

            var builder = new StringBuilder();
            foreach (var ch in value.Trim())
            {
                if ((ch >= 'a' && ch <= 'z') ||
                    (ch >= 'A' && ch <= 'Z') ||
                    (ch >= '0' && ch <= '9') ||
                    ch == '_' || ch == '-' || ch == '.' || ch == '/' || ch == ' ')
                {
                    builder.Append(ch);
                }
            }

            var text = builder.ToString();
            while (Encoding.UTF8.GetByteCount(text) > maxBytes && text.Length > 0)
                text = text.Substring(0, text.Length - 1);
            return string.IsNullOrEmpty(text) ? fallback : text;
        }
    }

    public static class XaceProtocolNames
    {
        public const string Handshake = "handshake";
        public const string HandshakeAck = "handshake_ack";
        public const string TickSnapshot = "tick_snapshot";
        public const string PlaybackCommands = "playback_commands";
        public const string InputPacket = "input_packet";
        public const string Disconnect = "disconnect";
        public const string Error = "error";
    }

    [Serializable]
    public sealed class XaceHandshake
    {
        public string msg_type;
        public uint protocol_version;
        public string engine_name;
        public string engine_version;
        public string adapter_version;
        public string cgs_hash;
        public string[] capabilities;
    }

    [Serializable]
    public sealed class XaceInputPacket
    {
        public string msg_type = XaceProtocolNames.InputPacket;
        public ulong peer_id = 1;
        public ulong tick;
        public ulong player_id;
        public ulong sequence_id;
        public XaceInputAction[] actions = new XaceInputAction[0];
        public ulong timestamp_ms;
        public string device_id = "unity";
        public bool predicted;

        public SortedDictionary<string, object> ToDictionary()
        {
            var actionList = new List<object>();
            if (actions != null)
            {
                foreach (var action in actions)
                {
                    if (action == null)
                        continue;
                    actionList.Add(action.ToDictionary());
                }
            }

            return new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["msg_type"] = string.IsNullOrEmpty(msg_type) ? XaceProtocolNames.InputPacket : msg_type,
                ["peer_id"] = peer_id,
                ["tick"] = tick,
                ["player_id"] = player_id,
                ["sequence_id"] = sequence_id,
                ["actions"] = actionList,
                ["timestamp_ms"] = timestamp_ms,
                ["device_id"] = device_id ?? "",
                ["predicted"] = predicted
            };
        }
    }

    [Serializable]
    public sealed class XaceInputAction
    {
        public string action;
        public float value;
        public float secondary_value;
        public string kind;
        public string phase;

        public SortedDictionary<string, object> ToDictionary()
        {
            return new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["action"] = action ?? "",
                ["value"] = value,
                ["secondary_value"] = secondary_value,
                ["kind"] = kind ?? "custom",
                ["phase"] = phase ?? "performed"
            };
        }
    }

    public struct XaceTransportStats
    {
        public ulong framesSent;
        public ulong framesReceived;
        public ulong bytesSent;
        public ulong bytesReceived;
        public ulong protocolErrors;
        public int queuedMessages;
    }

    public sealed class XaceRuntimeMessage
    {
        public readonly string RawJson;
        public readonly Dictionary<string, object> Data;

        public XaceRuntimeMessage(string rawJson, Dictionary<string, object> data)
        {
            RawJson = rawJson ?? "";
            Data = data ?? new Dictionary<string, object>();
        }

        public string MessageType => GetString("msg_type", "");
        public ulong Tick => GetUInt64("tick", 0);

        public string GetString(string key, string fallback)
        {
            return Data.TryGetValue(key, out var value) && value != null ? Convert.ToString(value, CultureInfo.InvariantCulture) : fallback;
        }

        public ulong GetUInt64(string key, ulong fallback)
        {
            if (!Data.TryGetValue(key, out var value) || value == null)
                return fallback;
            try { return Convert.ToUInt64(value, CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        public bool GetBool(string key, bool fallback)
        {
            if (!Data.TryGetValue(key, out var value) || value == null)
                return fallback;
            try { return Convert.ToBoolean(value, CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        public List<object> GetList(string key)
        {
            return Data.TryGetValue(key, out var value) && value is List<object> list ? list : new List<object>();
        }

        public Dictionary<string, object> GetObject(string key)
        {
            return Data.TryGetValue(key, out var value) && value is Dictionary<string, object> obj ? obj : new Dictionary<string, object>();
        }
    }

    public sealed class XaceHandshakeAck
    {
        public bool accepted;
        public string reject_reason;
        public string session_id;
        public uint tick_rate;
        public string cgs_hash;
        public string schema_version;
        public List<XaceEntityState> initial_entities = new List<XaceEntityState>();

        public static XaceHandshakeAck FromMessage(XaceRuntimeMessage message)
        {
            var ack = new XaceHandshakeAck
            {
                accepted = message.GetBool("accepted", false),
                reject_reason = message.GetString("reject_reason", ""),
                session_id = message.GetString("session_id", ""),
                tick_rate = (uint)message.GetUInt64("tick_rate", 60),
                cgs_hash = message.GetString("cgs_hash", ""),
                schema_version = message.GetString("schema_version", "")
            };
            foreach (var item in message.GetList("initial_entities"))
            {
                if (item is Dictionary<string, object> obj)
                    ack.initial_entities.Add(XaceEntityState.FromDictionary(obj));
            }
            return ack;
        }
    }

    public sealed class XaceTickSnapshot
    {
        public ulong tick;
        public ulong timestamp_ms;
        public List<XaceEntityState> entities = new List<XaceEntityState>();
        public List<ulong> spawned_ids = new List<ulong>();
        public List<ulong> destroyed_ids = new List<ulong>();
        public List<XacePlaybackCommand> playback_commands = new List<XacePlaybackCommand>();

        public static XaceTickSnapshot FromMessage(XaceRuntimeMessage message)
        {
            var snapshot = new XaceTickSnapshot
            {
                tick = message.GetUInt64("tick", 0),
                timestamp_ms = message.GetUInt64("timestamp_ms", 0)
            };
            foreach (var item in message.GetList("entities"))
            {
                if (item is Dictionary<string, object> obj)
                    snapshot.entities.Add(XaceEntityState.FromDictionary(obj));
            }
            foreach (var id in message.GetList("spawned_ids"))
                snapshot.spawned_ids.Add(XaceJsonValue.ToUInt64(id, 0));
            foreach (var id in message.GetList("destroyed_ids"))
                snapshot.destroyed_ids.Add(XaceJsonValue.ToUInt64(id, 0));
            foreach (var item in message.GetList("playback_commands"))
            {
                if (item is Dictionary<string, object> obj)
                    snapshot.playback_commands.Add(XacePlaybackCommand.FromDictionary(obj));
            }
            return snapshot;
        }
    }

    public sealed class XaceAssetReference
    {
        public string id = "";
        public string asset_type = "";
        public string status = "";

        public static XaceAssetReference FromDictionary(Dictionary<string, object> obj)
        {
            if (obj == null)
                return new XaceAssetReference();
            return new XaceAssetReference
            {
                id = XaceJsonValue.ToString(XaceJsonValue.Get(obj, "id"), ""),
                asset_type = XaceJsonValue.ToString(XaceJsonValue.Get(obj, "asset_type"), ""),
                status = XaceJsonValue.ToString(XaceJsonValue.Get(obj, "status"), "")
            };
        }
    }

    public sealed class XacePlaybackCommand
    {
        public string binding_id = "";
        public string event_name = "";
        public string playback_kind = "";
        public ulong entity_id;
        public XaceAssetReference asset = new XaceAssetReference();
        public string semantic_action = "";
        public SortedDictionary<string, string> parameters = new SortedDictionary<string, string>(StringComparer.Ordinal);
        public int priority;

        public static XacePlaybackCommand FromDictionary(Dictionary<string, object> obj)
        {
            var command = new XacePlaybackCommand();
            if (obj == null)
                return command;

            command.binding_id = XaceJsonValue.ToString(XaceJsonValue.Get(obj, "binding_id"), "");
            command.event_name = XaceJsonValue.ToString(XaceJsonValue.Get(obj, "event_name"), "");
            command.playback_kind = XaceJsonValue.ToString(XaceJsonValue.Get(obj, "playback_kind"), "");
            command.entity_id = XaceJsonValue.ToUInt64(XaceJsonValue.Get(obj, "entity_id"), 0);
            command.semantic_action = XaceJsonValue.ToString(XaceJsonValue.Get(obj, "semantic_action"), "");
            command.priority = XaceJsonValue.ToInt32(XaceJsonValue.Get(obj, "priority"), 0);

            if (XaceJsonValue.Get(obj, "asset") is Dictionary<string, object> asset)
                command.asset = XaceAssetReference.FromDictionary(asset);
            if (XaceJsonValue.Get(obj, "parameters") is Dictionary<string, object> parameters)
            {
                foreach (var pair in parameters)
                    command.parameters[pair.Key] = XaceJsonValue.ToString(pair.Value, "");
            }
            return command;
        }
    }

    public sealed class XaceEntityState
    {
        public ulong id;
        public string actor_id;
        public SortedDictionary<uint, string> components = new SortedDictionary<uint, string>();

        public static XaceEntityState FromDictionary(Dictionary<string, object> obj)
        {
            var state = new XaceEntityState
            {
                id = XaceJsonValue.ToUInt64(XaceJsonValue.Get(obj, "id"), 0),
                actor_id = Convert.ToString(XaceJsonValue.Get(obj, "actor_id") ?? "", CultureInfo.InvariantCulture)
            };

            if (XaceJsonValue.Get(obj, "components") is Dictionary<string, object> components)
            {
                foreach (var pair in components)
                {
                    if (uint.TryParse(pair.Key, NumberStyles.Integer, CultureInfo.InvariantCulture, out var typeId))
                        state.components[typeId] = Convert.ToString(pair.Value ?? "", CultureInfo.InvariantCulture);
                }
            }
            return state;
        }
    }

    internal static class XaceJson
    {
        public static Dictionary<string, object> DeserializeObject(string json)
        {
            var value = Parser.Parse(json);
            return value as Dictionary<string, object>;
        }

        public static string Serialize(object value)
        {
            var builder = new StringBuilder();
            WriteValue(builder, value);
            return builder.ToString();
        }

        private static void WriteValue(StringBuilder builder, object value)
        {
            if (value == null)
            {
                builder.Append("null");
            }
            else if (value is string str)
            {
                WriteString(builder, str);
            }
            else if (value is bool boolean)
            {
                builder.Append(boolean ? "true" : "false");
            }
            else if (value is IDictionary<string, object> dict)
            {
                builder.Append('{');
                var first = true;
                var keys = new List<string>(dict.Keys);
                keys.Sort(StringComparer.Ordinal);
                foreach (var key in keys)
                {
                    if (!first) builder.Append(',');
                    first = false;
                    WriteString(builder, key);
                    builder.Append(':');
                    WriteValue(builder, dict[key]);
                }
                builder.Append('}');
            }
            else if (value is IDictionary genericDict)
            {
                var sorted = new SortedDictionary<string, object>(StringComparer.Ordinal);
                foreach (DictionaryEntry entry in genericDict)
                    sorted[Convert.ToString(entry.Key, CultureInfo.InvariantCulture)] = entry.Value;
                WriteValue(builder, sorted);
            }
            else if (value is IEnumerable enumerable && !(value is string))
            {
                builder.Append('[');
                var first = true;
                foreach (var item in enumerable)
                {
                    if (!first) builder.Append(',');
                    first = false;
                    WriteValue(builder, item);
                }
                builder.Append(']');
            }
            else if (value is float f)
            {
                builder.Append((!float.IsNaN(f) && !float.IsInfinity(f)) ? f.ToString("R", CultureInfo.InvariantCulture) : "0");
            }
            else if (value is double d)
            {
                builder.Append((!double.IsNaN(d) && !double.IsInfinity(d)) ? d.ToString("R", CultureInfo.InvariantCulture) : "0");
            }
            else if (value is IFormattable formattable)
            {
                builder.Append(formattable.ToString(null, CultureInfo.InvariantCulture));
            }
            else
            {
                WriteString(builder, Convert.ToString(value, CultureInfo.InvariantCulture));
            }
        }

        private static void WriteString(StringBuilder builder, string value)
        {
            builder.Append('"');
            foreach (var ch in value ?? "")
            {
                switch (ch)
                {
                    case '"': builder.Append("\\\""); break;
                    case '\\': builder.Append("\\\\"); break;
                    case '\b': builder.Append("\\b"); break;
                    case '\f': builder.Append("\\f"); break;
                    case '\n': builder.Append("\\n"); break;
                    case '\r': builder.Append("\\r"); break;
                    case '\t': builder.Append("\\t"); break;
                    default:
                        if (ch < ' ')
                            builder.Append("\\u").Append(((int)ch).ToString("x4", CultureInfo.InvariantCulture));
                        else
                            builder.Append(ch);
                        break;
                }
            }
            builder.Append('"');
        }

        private sealed class Parser
        {
            private readonly string json;
            private int index;

            private Parser(string json) { this.json = json ?? ""; }

            public static object Parse(string json)
            {
                var parser = new Parser(json);
                var value = parser.ParseValue();
                parser.SkipWhitespace();
                return parser.index == parser.json.Length ? value : null;
            }

            private object ParseValue()
            {
                SkipWhitespace();
                if (index >= json.Length) return null;
                switch (json[index])
                {
                    case '{': return ParseObject();
                    case '[': return ParseArray();
                    case '"': return ParseString();
                    case 't': return Consume("true") ? true : null;
                    case 'f': return Consume("false") ? false : null;
                    case 'n': return Consume("null") ? null : null;
                    default: return ParseNumber();
                }
            }

            private Dictionary<string, object> ParseObject()
            {
                var obj = new Dictionary<string, object>(StringComparer.Ordinal);
                index++;
                SkipWhitespace();
                if (Peek('}')) { index++; return obj; }
                while (index < json.Length)
                {
                    var key = ParseString();
                    SkipWhitespace();
                    if (!Peek(':')) return null;
                    index++;
                    obj[key] = ParseValue();
                    SkipWhitespace();
                    if (Peek('}')) { index++; return obj; }
                    if (!Peek(',')) return null;
                    index++;
                }
                return null;
            }

            private List<object> ParseArray()
            {
                var list = new List<object>();
                index++;
                SkipWhitespace();
                if (Peek(']')) { index++; return list; }
                while (index < json.Length)
                {
                    list.Add(ParseValue());
                    SkipWhitespace();
                    if (Peek(']')) { index++; return list; }
                    if (!Peek(',')) return null;
                    index++;
                }
                return null;
            }

            private string ParseString()
            {
                if (!Peek('"')) return null;
                index++;
                var builder = new StringBuilder();
                while (index < json.Length)
                {
                    var ch = json[index++];
                    if (ch == '"') return builder.ToString();
                    if (ch != '\\')
                    {
                        builder.Append(ch);
                        continue;
                    }
                    if (index >= json.Length) return null;
                    var esc = json[index++];
                    switch (esc)
                    {
                        case '"': builder.Append('"'); break;
                        case '\\': builder.Append('\\'); break;
                        case '/': builder.Append('/'); break;
                        case 'b': builder.Append('\b'); break;
                        case 'f': builder.Append('\f'); break;
                        case 'n': builder.Append('\n'); break;
                        case 'r': builder.Append('\r'); break;
                        case 't': builder.Append('\t'); break;
                        case 'u':
                            if (index + 4 > json.Length) return null;
                            var hex = json.Substring(index, 4);
                            if (!ushort.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var code)) return null;
                            builder.Append((char)code);
                            index += 4;
                            break;
                        default:
                            return null;
                    }
                }
                return null;
            }

            private object ParseNumber()
            {
                var start = index;
                if (Peek('-')) index++;
                while (index < json.Length && char.IsDigit(json[index])) index++;
                var isFloat = false;
                if (Peek('.'))
                {
                    isFloat = true;
                    index++;
                    while (index < json.Length && char.IsDigit(json[index])) index++;
                }
                if (index < json.Length && (json[index] == 'e' || json[index] == 'E'))
                {
                    isFloat = true;
                    index++;
                    if (index < json.Length && (json[index] == '+' || json[index] == '-')) index++;
                    while (index < json.Length && char.IsDigit(json[index])) index++;
                }
                var text = json.Substring(start, index - start);
                if (isFloat && double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var d)) return d;
                if (long.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var l)) return l;
                return null;
            }

            private bool Consume(string text)
            {
                if (index + text.Length > json.Length) return false;
                if (string.CompareOrdinal(json, index, text, 0, text.Length) != 0) return false;
                index += text.Length;
                return true;
            }

            private bool Peek(char ch) => index < json.Length && json[index] == ch;

            private void SkipWhitespace()
            {
                while (index < json.Length && char.IsWhiteSpace(json[index]))
                    index++;
            }
        }
    }

    internal static class XaceJsonValue
    {
        public static object Get(Dictionary<string, object> obj, string key)
        {
            return obj != null && obj.TryGetValue(key, out var value) ? value : null;
        }

        public static ulong ToUInt64(object value, ulong fallback)
        {
            if (value == null) return fallback;
            try { return Convert.ToUInt64(value, CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        public static int ToInt32(object value, int fallback)
        {
            if (value == null) return fallback;
            try { return Convert.ToInt32(value, CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        public static string ToString(object value, string fallback)
        {
            return value == null ? fallback : Convert.ToString(value, CultureInfo.InvariantCulture);
        }
    }
}

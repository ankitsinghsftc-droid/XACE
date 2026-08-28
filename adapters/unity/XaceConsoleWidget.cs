// XaceConsoleWidget.cs
// Lightweight in-game console for live XACE edit prompts.
//
// The widget owns only UI state. It emits explicit prompt/apply/cancel events
// and can optionally send CONTROL-style dictionaries through XaceTransport for
// future builder/runtime integrations.

using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    public sealed class XaceConsoleWidget : MonoBehaviour
    {
        public enum ConsoleState
        {
            Idle,
            PromptSubmitted,
            PreviewReceived,
            UserDecision,
            Applying,
            Error
        }

        [Header("Input")]
        [SerializeField] private KeyCode toggleKey = KeyCode.F1;
        [SerializeField] private bool startVisible = false;
        [SerializeField] private bool sendControlToRuntime = false;

        [Header("Window")]
        [SerializeField] private Rect windowRect = new Rect(20f, 20f, 620f, 420f);
        [SerializeField] private int maxLogLines = 12;

        public event Action<string> OnPromptSubmitted;
        public event Action<string> OnApplyRequested;
        public event Action<string> OnCancelRequested;

        private XaceTransport transport;
        private ConsoleState state = ConsoleState.Idle;
        private bool visible;
        private string prompt = "";
        private string preview = "";
        private string mutationId = "";
        private string runtimeCgsHash = "";
        private string lastSnapshotHash = "";
        private ulong lastRuntimeTick;
        private float confidence;
        private string sessionId;
        private Vector2 logScroll;
        private readonly List<string> logLines = new List<string>();
        private readonly List<string> history = new List<string>();
        private int historyIndex = -1;
        private ulong controlSequence = 1;

        private GUIStyle labelStyle;
        private GUIStyle logStyle;
        private GUIStyle windowStyle;
        private bool stylesReady;

        public ConsoleState State => state;
        public bool IsVisible => visible;

        private void Awake()
        {
            transport = GetComponent<XaceTransport>() ?? FindAnyObjectByType<XaceTransport>();
            visible = startVisible;
            sessionId = Guid.NewGuid().ToString("N").Substring(0, 8);
        }

        private void OnEnable()
        {
            if (transport != null)
            {
                transport.OnHandshakeAccepted += OnHandshakeAccepted;
                transport.OnProtocolError += OnProtocolError;
                transport.OnMessageReceived += OnRuntimeMessage;
            }
        }

        private void OnDisable()
        {
            if (transport != null)
            {
                transport.OnHandshakeAccepted -= OnHandshakeAccepted;
                transport.OnProtocolError -= OnProtocolError;
                transport.OnMessageReceived -= OnRuntimeMessage;
            }
        }

        private void Update()
        {
            if (SafeKeyDown(toggleKey))
                visible = !visible;

            if (!visible)
                return;

            if (SafeKeyDown(KeyCode.UpArrow) && history.Count > 0)
            {
                historyIndex = Mathf.Clamp(historyIndex + 1, 0, history.Count - 1);
                prompt = history[history.Count - 1 - historyIndex];
            }
            else if (SafeKeyDown(KeyCode.DownArrow) && history.Count > 0)
            {
                historyIndex = Mathf.Clamp(historyIndex - 1, -1, history.Count - 1);
                prompt = historyIndex < 0 ? "" : history[history.Count - 1 - historyIndex];
            }
        }

        private void OnGUI()
        {
            if (!visible)
                return;
            EnsureStyles();
            windowRect = GUI.Window(915042, windowRect, DrawWindow, "XACE Console", windowStyle);
        }

        public void ReceivePreview(string mutationPreview, float previewConfidence, string previewMutationId = "")
        {
            preview = mutationPreview ?? "";
            confidence = Mathf.Clamp01(previewConfidence);
            mutationId = previewMutationId ?? "";
            state = ConsoleState.UserDecision;
            AppendLog("preview: " + preview);
        }

        public void SetError(string message)
        {
            state = ConsoleState.Error;
            AppendLog("error: " + message);
        }

        private void DrawWindow(int id)
        {
            GUILayout.Space(8f);
            GUILayout.Label("State: " + state + "  Runtime: " + ((transport != null && transport.IsConnected) ? "Connected" : "Disconnected"), labelStyle);
            GUILayout.Label("Tick: " + lastRuntimeTick + "  CGS: " + ShortHash(runtimeCgsHash) + "  Snapshot: " + ShortHash(lastSnapshotHash), labelStyle);
            GUILayout.Space(4f);

            GUI.enabled = state == ConsoleState.Idle || state == ConsoleState.Error;
            GUILayout.BeginHorizontal();
            GUILayout.Label("Prompt", GUILayout.Width(54f));
            GUI.SetNextControlName("XacePromptField");
            prompt = GUILayout.TextField(prompt ?? "", GUILayout.ExpandWidth(true));
            var submitPressed = GUILayout.Button("Send", GUILayout.Width(68f));
            GUILayout.EndHorizontal();
            GUI.enabled = true;

            if (submitPressed || (Event.current.type == EventType.KeyDown && Event.current.keyCode == KeyCode.Return))
            {
                if ((state == ConsoleState.Idle || state == ConsoleState.Error) && !string.IsNullOrWhiteSpace(prompt))
                    SubmitPrompt(prompt.Trim());
            }

            GUILayout.Space(8f);
            DrawConfidence();

            if (!string.IsNullOrEmpty(preview))
            {
                GUILayout.Label("Preview", labelStyle);
                GUILayout.TextArea(preview, GUILayout.MinHeight(72f));
                GUILayout.BeginHorizontal();
                GUI.enabled = state == ConsoleState.UserDecision;
                if (GUILayout.Button("Apply", GUILayout.Width(100f)))
                    Apply();
                if (GUILayout.Button("Cancel", GUILayout.Width(100f)))
                    Cancel();
                GUI.enabled = true;
                GUILayout.EndHorizontal();
            }

            GUILayout.Space(8f);
            GUILayout.Label("Log", labelStyle);
            logScroll = GUILayout.BeginScrollView(logScroll, GUILayout.ExpandHeight(true));
            foreach (var line in logLines)
                GUILayout.Label(line, logStyle);
            GUILayout.EndScrollView();

            if (GUI.Button(new Rect(windowRect.width - 30f, 2f, 24f, 20f), "x"))
                visible = false;
            GUI.DragWindow(new Rect(0f, 0f, windowRect.width - 34f, 24f));
        }

        private void DrawConfidence()
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label("Confidence", GUILayout.Width(82f));
            var rect = GUILayoutUtility.GetRect(180f, 16f, GUILayout.Width(180f));
            var old = GUI.color;
            GUI.color = Color.gray;
            GUI.DrawTexture(rect, Texture2D.whiteTexture);
            GUI.color = confidence >= 0.7f ? Color.green : confidence >= 0.4f ? Color.yellow : Color.red;
            GUI.DrawTexture(new Rect(rect.x, rect.y, rect.width * confidence, rect.height), Texture2D.whiteTexture);
            GUI.color = old;
            GUILayout.Label((confidence * 100f).ToString("0") + "%");
            GUILayout.EndHorizontal();
        }

        private void SubmitPrompt(string text)
        {
            prompt = "";
            preview = "";
            confidence = 0f;
            mutationId = "";
            state = ConsoleState.PromptSubmitted;
            history.Add(text);
            if (history.Count > 50)
                history.RemoveAt(0);
            historyIndex = -1;
            AppendLog("> " + text);
            OnPromptSubmitted?.Invoke(text);
            SendControl("PromptSubmit", new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["prompt"] = text,
                ["session_id"] = sessionId
            });
        }

        private void Apply()
        {
            state = ConsoleState.Applying;
            AppendLog("apply requested");
            OnApplyRequested?.Invoke(mutationId);
            SendControl("MutationDecision", new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["decision"] = "Apply",
                ["mutation_id"] = mutationId,
                ["session_id"] = sessionId
            });
        }

        private void Cancel()
        {
            state = ConsoleState.Idle;
            AppendLog("cancelled");
            OnCancelRequested?.Invoke(mutationId);
            SendControl("MutationDecision", new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["decision"] = "Cancel",
                ["mutation_id"] = mutationId,
                ["session_id"] = sessionId
            });
            preview = "";
            mutationId = "";
            confidence = 0f;
        }

        private void SendControl(string controlType, SortedDictionary<string, object> payload)
        {
            if (!sendControlToRuntime || transport == null)
                return;
            payload["msg_type"] = "control";
            payload["control_type"] = controlType;
            payload["sequence_id"] = controlSequence++;
            transport.SendDictionary(payload);
        }

        private void OnHandshakeAccepted(XaceHandshakeAck ack)
        {
            runtimeCgsHash = ack.cgs_hash ?? "";
            AppendLog("connected: " + ack.session_id);
            AppendLog("cgs hash: " + ShortHash(runtimeCgsHash));
            if (state == ConsoleState.Error)
                state = ConsoleState.Idle;
        }

        private void OnProtocolError(string message)
        {
            SetError(message);
        }

        private void OnRuntimeMessage(XaceRuntimeMessage message)
        {
            if (message.MessageType == XaceProtocolNames.TickSnapshot)
            {
                lastRuntimeTick = message.Tick;
                lastSnapshotHash = SnapshotProofHash(message.RawJson);
                return;
            }

            if (message.MessageType == XaceProtocolNames.AdapterSideEffectRollback)
            {
                preview = "";
                mutationId = "";
                confidence = 0f;
                state = ConsoleState.Idle;
                AppendLog("rollback: " + message.GetString("reason", "adapter side effects restored"));
                return;
            }

            if (message.MessageType != "control")
                return;
            var controlType = message.GetString("control_type", "");
            if (controlType == "MutationPreview")
            {
                ReceivePreview(
                    message.GetString("description", message.GetString("message", "")),
                    Convert.ToSingle(message.Data.TryGetValue("confidence", out var c) ? c : 0f),
                    message.GetString("mutation_id", "")
                );
            }
            else if (controlType == "MutationApplied")
            {
                AppendLog("applied");
                state = ConsoleState.Idle;
                preview = "";
            }
            else if (controlType == "MutationCancelled")
            {
                AppendLog("cancelled by runtime");
                state = ConsoleState.Idle;
                preview = "";
            }
        }

        private void AppendLog(string line)
        {
            logLines.Add("[" + DateTime.Now.ToString("HH:mm:ss") + "] " + line);
            while (logLines.Count > maxLogLines)
                logLines.RemoveAt(0);
            logScroll = new Vector2(0f, float.MaxValue);
        }

        private static string SnapshotProofHash(string rawJson)
        {
            if (string.IsNullOrEmpty(rawJson))
                return "";
            using (var sha = SHA256.Create())
            {
                var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(rawJson));
                var builder = new StringBuilder(bytes.Length * 2);
                foreach (var b in bytes)
                    builder.Append(b.ToString("x2"));
                return builder.ToString();
            }
        }

        private static string ShortHash(string value)
        {
            return string.IsNullOrEmpty(value) ? "-" : value.Substring(0, Math.Min(12, value.Length));
        }

        private static bool SafeKeyDown(KeyCode key)
        {
            try { return Input.GetKeyDown(key); }
            catch (InvalidOperationException) { return false; }
            catch (ArgumentException) { return false; }
        }

        private void EnsureStyles()
        {
            if (stylesReady)
                return;
            windowStyle = new GUIStyle(GUI.skin.window)
            {
                fontSize = 13,
                padding = new RectOffset(10, 10, 22, 10)
            };
            labelStyle = new GUIStyle(GUI.skin.label)
            {
                fontStyle = FontStyle.Bold
            };
            logStyle = new GUIStyle(GUI.skin.label)
            {
                wordWrap = true,
                normal = { textColor = new Color(0.78f, 0.9f, 0.78f) }
            };
            stylesReady = true;
        }
    }
}

// XaceConsoleWidget.cs
// In-game prompt console UI — lets the designer submit natural-language prompts
// to the XACE PIL from within a running Unity build without leaving the game.
//
// ## Purpose
// The builder workflow (Phase 14) has the full editor UI. The in-game console
// is the lightweight equivalent — useful for:
//   - Live testing: "make the enemies faster" while the game runs
//   - Iterating on balance without restarting
//   - Demonstrating the XACE live-mutation capability
//
// ## State Machine (CLAUDE.md Phase 14)
// Idle → PromptSubmitted → PreviewReceived → UserDecision → Idle
//   - Idle: console hidden or prompt field ready
//   - PromptSubmitted: prompt sent via CONTROL WireMessage, awaiting response
//   - PreviewReceived: XACE sent back a schema diff preview, show Apply/Cancel
//   - UserDecision: designer clicked Apply or Cancel, result dispatched
//
// ## UI Layout
// Toggle key: F1 (configurable)
// ┌─────────────────────────────────────────────────┐
// │ XACE Console                          [×]        │
// ├─────────────────────────────────────────────────┤
// │ Prompt: [______________________________] [Send]  │
// │ ─────────────────────────────────────────────── │
// │ ● Confidence: ████████░░ 82%                    │
// │ ─────────────────────────────────────────────── │
// │ Preview: "Increase zombie speed from 3→5"        │
// │ [  Apply  ]    [  Cancel  ]                      │
// │ ─────────────────────────────────────────────── │
// │ [Output log — last 8 lines]                      │
// └─────────────────────────────────────────────────┘
//
// ## CONTROL Message Format
// Prompts are sent as CONTROL WireMessages with payload:
//   { "control_type": "PromptSubmit", "prompt": "...", "session_id": "..." }
// The XACE PIL processes these and sends back CONTROL messages with:
//   { "control_type": "MutationPreview", "description": "...", "confidence": 0.82 }
//   { "control_type": "MutationApplied" } or { "control_type": "MutationCancelled" }

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    /// <summary>
    /// In-game XACE prompt console overlay.
    /// Uses Unity's legacy IMGUI for zero-dependency rendering.
    /// Attach to a persistent GameObject. Toggle with F1.
    /// </summary>
    public class XaceConsoleWidget : MonoBehaviour
    {
        // ── Configuration ──────────────────────────────────────────────────

        [Header("Toggle")]
        [SerializeField] private KeyCode _toggleKey = KeyCode.F1;

        [Header("Window")]
        [SerializeField] private float _windowWidth  = 600f;
        [SerializeField] private float _windowHeight = 400f;
        [SerializeField] private float _windowX      = 20f;
        [SerializeField] private float _windowY      = 20f;

        [Header("Log")]
        [SerializeField] private int _maxLogLines = 8;

        // ── State Machine ──────────────────────────────────────────────────

        private enum ConsoleState
        {
            Idle,
            PromptSubmitted,
            PreviewReceived,
            UserDecision,
        }

        private ConsoleState _state       = ConsoleState.Idle;
        private bool         _visible     = false;
        private string       _promptText  = string.Empty;
        private string       _previewText = string.Empty;
        private float        _confidence  = 0f;
        private string       _sessionId   = string.Empty;
        private string       _pendingMutationId = string.Empty;

        private readonly List<string> _log = new();
        private Vector2 _logScroll = Vector2.zero;

        // IMGUI skin customisation
        private GUIStyle _windowStyle;
        private GUIStyle _labelStyle;
        private GUIStyle _buttonStyle;
        private GUIStyle _textFieldStyle;
        private GUIStyle _logStyle;
        private bool     _stylesInitialised;

        private XaceTransport _transport;
        private ulong         _controlSequence;

        // Prompt history (up-arrow to recall)
        private readonly List<string> _history = new();
        private int _historyIndex = -1;

        // ── Unity Lifecycle ────────────────────────────────────────────────

        private void Awake()
        {
            _transport = GetComponent<XaceTransport>()
                ?? FindObjectOfType<XaceTransport>();
            _sessionId = Guid.NewGuid().ToString("N").Substring(0, 8);
        }

        private void OnEnable()
        {
            if (_transport != null)
                _transport.OnMessageReceived += OnMessageReceived;
        }

        private void OnDisable()
        {
            if (_transport != null)
                _transport.OnMessageReceived -= OnMessageReceived;
        }

        private void Update()
        {
            if (UnityEngine.Input.GetKeyDown(_toggleKey))
                _visible = !_visible;

            // History navigation when console is visible and focused
            if (_visible)
            {
                if (UnityEngine.Input.GetKeyDown(KeyCode.UpArrow) && _history.Count > 0)
                {
                    _historyIndex = Mathf.Max(0, _historyIndex - 1);
                    _promptText   = _history[_history.Count - 1 - _historyIndex];
                }
                if (UnityEngine.Input.GetKeyDown(KeyCode.DownArrow))
                {
                    _historyIndex = Mathf.Min(_history.Count, _historyIndex + 1);
                    _promptText   = _historyIndex < _history.Count
                        ? _history[_history.Count - 1 - _historyIndex]
                        : string.Empty;
                }
            }
        }

        // ── IMGUI Rendering ────────────────────────────────────────────────

        private void OnGUI()
        {
            if (!_visible) return;
            InitStyles();

            var windowRect = new Rect(_windowX, _windowY, _windowWidth, _windowHeight);
            GUI.Window(42, windowRect, DrawWindow, "XACE Console", _windowStyle);
        }

        private void DrawWindow(int windowId)
        {
            GUILayout.Space(8);

            // ── Status bar ─────────────────────────────────────────────────
            string statusText = _state switch
            {
                ConsoleState.Idle             => _transport?.IsConnected == true ? "● Connected" : "○ Disconnected",
                ConsoleState.PromptSubmitted  => "⏳ Processing...",
                ConsoleState.PreviewReceived  => "👁 Preview ready — review and apply or cancel",
                ConsoleState.UserDecision     => "✓ Decision sent",
                _ => string.Empty,
            };
            GUILayout.Label(statusText, _labelStyle);
            GUILayout.Space(4);

            // ── Prompt input ────────────────────────────────────────────────
            GUI.enabled = _state == ConsoleState.Idle && _transport?.IsConnected == true;
            GUILayout.BeginHorizontal();
            GUILayout.Label("Prompt:", GUILayout.Width(55));
            _promptText = GUILayout.TextField(_promptText, _textFieldStyle, GUILayout.ExpandWidth(true));

            bool sendPressed = GUILayout.Button("Send", _buttonStyle, GUILayout.Width(60));
            GUILayout.EndHorizontal();
            GUI.enabled = true;

            // Submit on Enter or Send button
            if ((sendPressed || (Event.current.type == EventType.KeyDown &&
                                 Event.current.keyCode == KeyCode.Return)) &&
                !string.IsNullOrWhiteSpace(_promptText) &&
                _state == ConsoleState.Idle)
            {
                SubmitPrompt(_promptText.Trim());
            }

            GUILayout.Space(8);

            // ── Confidence meter ────────────────────────────────────────────
            if (_state == ConsoleState.PreviewReceived || _state == ConsoleState.UserDecision)
            {
                GUILayout.BeginHorizontal();
                GUILayout.Label($"Confidence:", GUILayout.Width(80));

                Rect meterRect = GUILayoutUtility.GetRect(200, 16, GUILayout.ExpandWidth(false));
                DrawConfidenceMeter(meterRect, _confidence);
                GUILayout.Label($" {(_confidence * 100f):F0}%", GUILayout.Width(40));
                GUILayout.EndHorizontal();
                GUILayout.Space(4);
            }

            // ── Preview pane ────────────────────────────────────────────────
            if (!string.IsNullOrEmpty(_previewText))
            {
                GUILayout.Box(_previewText, GUILayout.ExpandWidth(true));
                GUILayout.Space(4);

                if (_state == ConsoleState.PreviewReceived)
                {
                    GUILayout.BeginHorizontal();
                    GUILayout.FlexibleSpace();
                    if (GUILayout.Button("  Apply  ", _buttonStyle, GUILayout.Width(100)))
                        ApplyMutation();
                    GUILayout.Space(12);
                    if (GUILayout.Button("  Cancel  ", _buttonStyle, GUILayout.Width(100)))
                        CancelMutation();
                    GUILayout.FlexibleSpace();
                    GUILayout.EndHorizontal();
                    GUILayout.Space(4);
                }
            }

            // ── Output log ──────────────────────────────────────────────────
            GUILayout.Label("Output:", _labelStyle);
            _logScroll = GUILayout.BeginScrollView(_logScroll, GUILayout.ExpandHeight(true));
            foreach (string line in _log)
                GUILayout.Label(line, _logStyle);
            GUILayout.EndScrollView();

            // Close button
            if (GUI.Button(new Rect(_windowWidth - 28, 2, 24, 18), "×"))
                _visible = false;

            // Make the window draggable
            GUI.DragWindow(new Rect(0, 0, _windowWidth - 30, 20));
        }

        private void DrawConfidenceMeter(Rect rect, float value)
        {
            // Background
            GUI.DrawTexture(rect, Texture2D.grayTexture);
            // Fill
            float filled = Mathf.Clamp01(value);
            Color fillColor = filled >= 0.7f ? Color.green
                            : filled >= 0.4f ? Color.yellow
                            : Color.red;
            var fillRect = new Rect(rect.x, rect.y, rect.width * filled, rect.height);
            var prevColor = GUI.color;
            GUI.color = fillColor;
            GUI.DrawTexture(fillRect, Texture2D.whiteTexture);
            GUI.color = prevColor;
        }

        // ── Prompt Submission ──────────────────────────────────────────────

        private void SubmitPrompt(string prompt)
        {
            _state = ConsoleState.PromptSubmitted;
            _previewText = string.Empty;
            _confidence  = 0f;

            _history.Add(prompt);
            if (_history.Count > 50) _history.RemoveAt(0);
            _historyIndex = -1;
            _promptText   = string.Empty;

            AppendLog($"▶ {prompt}");

            var payload = new PromptSubmitControl
            {
                control_type = "PromptSubmit",
                prompt       = prompt,
                session_id   = _sessionId,
            };
            SendControl(JsonUtility.ToJson(payload));
        }

        // ── Mutation Apply / Cancel ────────────────────────────────────────

        private void ApplyMutation()
        {
            _state = ConsoleState.UserDecision;
            var payload = new MutationDecisionControl
            {
                control_type  = "MutationDecision",
                decision      = "Apply",
                mutation_id   = _pendingMutationId,
                session_id    = _sessionId,
            };
            SendControl(JsonUtility.ToJson(payload));
            AppendLog("✓ Mutation applied.");
            ResetToIdle(1.5f);
        }

        private void CancelMutation()
        {
            _state = ConsoleState.UserDecision;
            var payload = new MutationDecisionControl
            {
                control_type  = "MutationDecision",
                decision      = "Cancel",
                mutation_id   = _pendingMutationId,
                session_id    = _sessionId,
            };
            SendControl(JsonUtility.ToJson(payload));
            AppendLog("✗ Mutation cancelled.");
            ResetToIdle(0.5f);
        }

        private void ResetToIdle(float afterSeconds)
        {
            // Reset state after a short display delay
            Invoke(nameof(DoResetToIdle), afterSeconds);
        }

        private void DoResetToIdle()
        {
            _state       = ConsoleState.Idle;
            _previewText = string.Empty;
            _confidence  = 0f;
            _pendingMutationId = string.Empty;
        }

        // ── Inbound Message Handling ───────────────────────────────────────

        private void OnMessageReceived(WireMessage msg)
        {
            if (!msg.IsControl) return;

            var control = JsonUtility.FromJson<XaceControlMessage>(msg.payload);
            if (control == null) return;

            switch (control.control_type)
            {
                case "MutationPreview":
                    OnMutationPreview(control);
                    break;
                case "ClarificationRequired":
                    OnClarificationRequired(control);
                    break;
                case "MutationApplied":
                    AppendLog("✓ XACE applied the mutation.");
                    _state = ConsoleState.Idle;
                    break;
                case "MutationCancelled":
                    AppendLog("✗ XACE cancelled the mutation.");
                    _state = ConsoleState.Idle;
                    break;
                case "Error":
                    AppendLog($"⚠ Error: {control.message}");
                    _state = ConsoleState.Idle;
                    break;
                case "HandshakeAck":
                    AppendLog("✓ Connected to XACE runtime.");
                    break;
            }
        }

        private void OnMutationPreview(XaceControlMessage control)
        {
            _state             = ConsoleState.PreviewReceived;
            _previewText       = control.description ?? control.message ?? "(no preview)";
            _confidence        = control.confidence;
            _pendingMutationId = control.mutation_id ?? string.Empty;
            AppendLog($"Preview: {_previewText} (confidence: {_confidence * 100:F0}%)");
        }

        private void OnClarificationRequired(XaceControlMessage control)
        {
            _state       = ConsoleState.Idle;
            _previewText = string.Empty;
            AppendLog($"❓ Clarification: {control.question ?? control.message}");
        }

        // ── Log ────────────────────────────────────────────────────────────

        private void AppendLog(string line)
        {
            string timestamp = DateTime.Now.ToString("HH:mm:ss");
            _log.Add($"[{timestamp}] {line}");
            if (_log.Count > _maxLogLines)
                _log.RemoveAt(0);
            // Scroll to bottom
            _logScroll = new Vector2(0, float.MaxValue);
        }

        // ── Wire Helpers ───────────────────────────────────────────────────

        private void SendControl(string payload)
        {
            var msg = new WireMessage
            {
                protocol_version       = WireProtocol.ProtocolVersion,
                world_id               = "default",
                schema_version         = "0.1.0",
                execution_plan_version = 1,
                tick                   = 0,
                sequence_id            = _controlSequence++,
                message_type           = (int)MessageType.Control,
                payload                = payload,
            };
            _transport?.Send(msg);
        }

        // ── Style Initialisation ───────────────────────────────────────────

        private void InitStyles()
        {
            if (_stylesInitialised) return;

            _windowStyle = new GUIStyle(GUI.skin.window)
            {
                fontSize  = 13,
                fontStyle = FontStyle.Bold,
                padding   = new RectOffset(10, 10, 20, 10),
            };

            _labelStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 12,
            };

            _buttonStyle = new GUIStyle(GUI.skin.button)
            {
                fontSize = 12,
                padding  = new RectOffset(8, 8, 4, 4),
            };

            _textFieldStyle = new GUIStyle(GUI.skin.textField)
            {
                fontSize = 12,
            };

            _logStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize  = 11,
                wordWrap  = true,
                normal    = { textColor = new Color(0.8f, 0.9f, 0.8f) },
            };

            _stylesInitialised = true;
        }
    }

    // ── CONTROL Message Payload Types ──────────────────────────────────────────

    [Serializable]
    public class PromptSubmitControl
    {
        public string control_type;
        public string prompt;
        public string session_id;
    }

    [Serializable]
    public class MutationDecisionControl
    {
        public string control_type;
        public string decision;         // "Apply" | "Cancel"
        public string mutation_id;
        public string session_id;
    }

    [Serializable]
    public class XaceControlMessage
    {
        public string control_type;     // "MutationPreview" | "ClarificationRequired" | etc.
        public string description;      // Human-readable preview of the mutation
        public string message;          // Fallback message
        public string question;         // Clarification question
        public float  confidence;       // 0.0 – 1.0
        public string mutation_id;      // ID to include in MutationDecision
        public string session_id;
        public string error_code;
    }
}
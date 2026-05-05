// XaceInputCollector.cs
// Collects player input each frame, packages it as an INPUT WireMessage with
// a tick stamp, and sends it to the XACE runtime once per simulation tick.
//
// ## Global Invariant I14
// Every input packet carries the tick it was generated. No untimed inputs.
// Input received without a tick stamp would break deterministic replay (D14).
// XaceInputCollector stamps each InputPacket with the current simulation tick
// received from the most recent DELTA or SNAPSHOT message.
//
// ## Frame vs Tick
// Unity runs at variable frame rate. XACE simulates at fixed tick rate (60Hz).
// XaceInputCollector collects input every frame (accumulate) and sends once
// per tick (flush). If multiple frames fall within one tick, input is merged:
//   - Digital actions (jump, interact): OR-merged (any frame press = pressed)
//   - Analog axes (move, look): averaged across frames
//   - Tick timestamp: current simulation tick from latest received message
//
// ## Extended Input (InputDeviceUpdate Feedback)
// Touch, gyroscope, and voice data are sent as InputDeviceUpdate feedback
// rather than the standard INPUT message. This matches the Audit 6 design
// where extended input uses the feedback channel.
//
// ## Multi-Player (Phase 15)
// In Phase 15, XaceInputCollector sends the local player's input only.
// The Phase 15 InputSynchroniser collects remote peer inputs.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    /// <summary>
    /// Collects player input each frame and sends it to the XACE runtime
    /// as a stamped INPUT WireMessage once per tick.
    /// </summary>
    [RequireComponent(typeof(XaceTransport))]
    public class XaceInputCollector : MonoBehaviour
    {
        // ── Configuration ──────────────────────────────────────────────────

        [Header("Input")]
        [Tooltip("Controller ID this collector represents (0 = local player).")]
        [SerializeField] private int _controllerId = 0;

        [Tooltip("Input profile ID — matched to COMP_INPUT_V1.input_profile_id.")]
        [SerializeField] private string _inputProfileId = "default";

        [Header("Tick Rate")]
        [Tooltip("Simulation tick rate in Hz. Must match XACE fixed_simulation_rate.")]
        [SerializeField] private float _tickRateHz = 60f;

        [Header("Extended Input")]
        [SerializeField] private bool _sendTouchFeedback = true;
        [SerializeField] private bool _sendGyroFeedback  = false;

        // ── State ──────────────────────────────────────────────────────────

        private XaceTransport _transport;
        private ulong         _currentTick;       // from latest DELTA/SNAPSHOT
        private ulong         _sequenceId;
        private float         _tickAccumulator;
        private float         _tickInterval;

        // Accumulated input within current tick window
        private readonly FrameInput _accumulated = new();
        private int   _framesThisTick;

        // ── Unity Lifecycle ────────────────────────────────────────────────

        private void Awake()
        {
            _transport    = GetComponent<XaceTransport>();
            _tickInterval = 1f / Mathf.Max(1f, _tickRateHz);

            if (_sendGyroFeedback && SystemInfo.supportsGyroscope)
                Input.gyro.enabled = true;
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
            if (!_transport.IsConnected) return;

            // Accumulate input for this frame
            AccumulateInput();
            _framesThisTick++;

            // Tick boundary: send accumulated input
            _tickAccumulator += Time.deltaTime;
            if (_tickAccumulator >= _tickInterval)
            {
                _tickAccumulator -= _tickInterval;
                FlushInput();
                _accumulated.Reset();
                _framesThisTick = 0;
            }

            // Extended input via feedback channel (I13: sent at tick boundary in LateUpdate)
        }

        private void LateUpdate()
        {
            if (!_transport.IsConnected) return;
            SendExtendedInputFeedback();
        }

        // ── Tick Tracking ──────────────────────────────────────────────────

        private void OnMessageReceived(WireMessage msg)
        {
            // Track current simulation tick from runtime messages (I14)
            if (msg.IsDelta || msg.IsSnapshot)
                _currentTick = msg.tick;
        }

        // ── Input Accumulation ─────────────────────────────────────────────

        private void AccumulateInput()
        {
            // Movement axes — average across frames
            _accumulated.move_x    += Input.GetAxis("Horizontal");
            _accumulated.move_y    += Input.GetAxis("Vertical");
            _accumulated.look_x    += Input.GetAxis("Mouse X");
            _accumulated.look_y    += Input.GetAxis("Mouse Y");

            // Digital actions — OR across frames (any frame press = pressed this tick)
            if (Input.GetButton("Jump"))         _accumulated.jump         = true;
            if (Input.GetButton("Fire1"))        _accumulated.primary_fire = true;
            if (Input.GetButton("Fire2"))        _accumulated.secondary_fire = true;
            if (Input.GetButtonDown("Interact")) _accumulated.interact     = true;
            if (Input.GetButton("Sprint"))       _accumulated.sprint       = true;
            if (Input.GetButton("Crouch"))       _accumulated.crouch       = true;

            // Escape / pause
            if (Input.GetKeyDown(KeyCode.Escape)) _accumulated.pause = true;
        }

        // ── Input Flush (per tick) ─────────────────────────────────────────

        private void FlushInput()
        {
            float n = Mathf.Max(1, _framesThisTick);

            var packet = new InputPacket
            {
                // I14: every input carries the tick it was generated
                tick               = _currentTick,
                sequence_id        = _sequenceId++,
                controller_id      = _controllerId,
                input_profile_id   = _inputProfileId,
                timestamp_ms       = (ulong)(Time.realtimeSinceStartup * 1000.0),

                // Averaged analog axes
                move_x             = _accumulated.move_x / n,
                move_y             = _accumulated.move_y / n,
                look_x             = _accumulated.look_x / n,
                look_y             = _accumulated.look_y / n,

                // Digital actions (OR-merged)
                jump               = _accumulated.jump,
                primary_fire       = _accumulated.primary_fire,
                secondary_fire     = _accumulated.secondary_fire,
                interact           = _accumulated.interact,
                sprint             = _accumulated.sprint,
                crouch             = _accumulated.crouch,
                pause              = _accumulated.pause,
            };

            string json  = JsonUtility.ToJson(packet);
            var    msg   = BuildInputMessage(json);
            _transport.Send(msg);
        }

        // ── Extended Input Feedback (Audit 6) ──────────────────────────────

        private void SendExtendedInputFeedback()
        {
            // Touch input
            if (_sendTouchFeedback && Input.touchCount > 0)
            {
                var touches = new TouchData[Input.touchCount];
                for (int i = 0; i < Input.touchCount; i++)
                {
                    var t = Input.GetTouch(i);
                    touches[i] = new TouchData
                    {
                        finger_id = t.fingerId,
                        phase     = t.phase.ToString(),
                        position_x = t.position.x,
                        position_y = t.position.y,
                        delta_x    = t.deltaPosition.x,
                        delta_y    = t.deltaPosition.y,
                        pressure   = t.pressure,
                    };
                }
                var touchPayload = new InputDeviceUpdatePayload
                {
                    entity_id    = 0,   // device-level, not entity-specific
                    device_type  = "touch",
                    touches      = touches,
                    generated_frame = (ulong)(Time.frameCount),
                };
                SendInputFeedback(touchPayload);
            }

            // Gyroscope
            if (_sendGyroFeedback && SystemInfo.supportsGyroscope)
            {
                var gyro = Input.gyro;
                var gyroPayload = new InputDeviceUpdatePayload
                {
                    entity_id   = 0,
                    device_type = "gyroscope",
                    gyro_x      = gyro.rotationRate.x,
                    gyro_y      = gyro.rotationRate.y,
                    gyro_z      = gyro.rotationRate.z,
                    generated_frame = (ulong)(Time.frameCount),
                };
                SendInputFeedback(gyroPayload);
            }
        }

        private void SendInputFeedback(InputDeviceUpdatePayload payload)
        {
            var feedbackMsg = new FeedbackMessage
            {
                feedback_type   = (int)FeedbackType.InputDeviceUpdate,
                entity_id       = 0,
                generated_frame = payload.generated_frame,
                payload_json    = JsonUtility.ToJson(payload),
            };
            var batch = new FeedbackPayload
            {
                tick     = _currentTick,
                messages = new[] { feedbackMsg },
            };
            _transport.SendFeedback(batch);
        }

        // ── Wire Helpers ───────────────────────────────────────────────────

        private WireMessage BuildInputMessage(string payload)
        {
            return new WireMessage
            {
                protocol_version       = WireProtocol.ProtocolVersion,
                world_id               = gameObject.scene.name,
                schema_version         = "0.1.0",
                execution_plan_version = 1,
                tick                   = _currentTick,  // I14
                sequence_id            = _sequenceId,
                message_type           = (int)MessageType.Input,
                payload                = payload,
            };
        }
    }

    // ── Frame Input Accumulator ────────────────────────────────────────────────

    /// <summary>Mutable accumulator for input across frames within one tick.</summary>
    public class FrameInput
    {
        public float move_x, move_y, look_x, look_y;
        public bool  jump, primary_fire, secondary_fire, interact, sprint, crouch, pause;

        public void Reset()
        {
            move_x = move_y = look_x = look_y = 0f;
            jump = primary_fire = secondary_fire = interact = sprint = crouch = pause = false;
        }
    }

    // ── Input Packet (matches XACE wire protocol) ──────────────────────────────

    [Serializable]
    public class InputPacket
    {
        // I14: tick this input was generated
        public ulong  tick;
        public ulong  sequence_id;
        public int    controller_id;
        public string input_profile_id;
        public ulong  timestamp_ms;

        // Analog axes (averaged across frames)
        public float move_x;
        public float move_y;
        public float look_x;
        public float look_y;

        // Digital actions (OR-merged across frames)
        public bool jump;
        public bool primary_fire;
        public bool secondary_fire;
        public bool interact;
        public bool sprint;
        public bool crouch;
        public bool pause;
    }

    // ── Extended Input Payload Types ───────────────────────────────────────────

    [Serializable]
    public class TouchData
    {
        public int    finger_id;
        public string phase;
        public float  position_x, position_y;
        public float  delta_x, delta_y;
        public float  pressure;
    }

    [Serializable]
    public class InputDeviceUpdatePayload
    {
        public ulong       entity_id;
        public string      device_type;
        public ulong       generated_frame;
        // Touch
        public TouchData[] touches;
        // Gyro
        public float gyro_x, gyro_y, gyro_z;
    }
}
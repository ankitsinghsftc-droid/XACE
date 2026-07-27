// XaceInputCollector.cs
// Collects Unity input and sends Phase 15 runtime input_packet messages.
//
// The runtime bridge consumes the schema defined in
// packages/runtime-core/src/engine_protocol.rs:
//   { msg_type, peer_id, tick, player_id, sequence_id, actions, timestamp_ms,
//     device_id, predicted }
//
// Input is sampled every Unity frame and flushed once per XACE tick. The tick
// stamp is derived from the latest runtime snapshot plus one, preserving the
// "no untimed input" replay invariant.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    [RequireComponent(typeof(XaceTransport))]
    public sealed class XaceInputCollector : MonoBehaviour
    {
        [Header("Identity")]
        [SerializeField] private ulong peerId = 1;
        [SerializeField] private ulong playerId = 1;
        [SerializeField] private string deviceId = "unity";

        [Header("Ticking")]
        [SerializeField] private float fallbackTickRateHz = 60f;
        [SerializeField] private bool predicted = true;
        [SerializeField] private bool sendIdleMovement = false;
        [SerializeField] private float deadzone = 0.01f;

        [Header("Input Manager Names")]
        [SerializeField] private string horizontalAxis = "Horizontal";
        [SerializeField] private string verticalAxis = "Vertical";
        [SerializeField] private string mouseXAxis = "Mouse X";
        [SerializeField] private string mouseYAxis = "Mouse Y";
        [SerializeField] private string jumpButton = "Jump";
        [SerializeField] private string primaryFireButton = "Fire1";
        [SerializeField] private string secondaryFireButton = "Fire2";
        [SerializeField] private string interactButton = "Interact";
        [SerializeField] private string sprintButton = "Sprint";
        [SerializeField] private string crouchButton = "Crouch";

        public event Action<XaceInputPacket> OnInputPacketBuilt;

        private XaceTransport transport;
        private readonly InputAccumulator accumulator = new InputAccumulator();
        private ulong latestRuntimeTick;
        private ulong lastSentTick;
        private float tickInterval;
        private float tickAccumulator;
        private int framesAccumulated;

        private void Awake()
        {
            EnsureTransport();
            tickInterval = 1f / Mathf.Max(1f, fallbackTickRateHz);
        }

        private void OnEnable()
        {
            if (EnsureTransport())
            {
                transport.OnTickSnapshot += OnTickSnapshot;
                transport.OnHandshakeAccepted += OnHandshakeAccepted;
            }
        }

        private void OnDisable()
        {
            if (EnsureTransport())
            {
                transport.OnTickSnapshot -= OnTickSnapshot;
                transport.OnHandshakeAccepted -= OnHandshakeAccepted;
            }
        }

        private void Update()
        {
            if (!EnsureTransport() || !transport.IsConnected)
                return;

            SampleFrame();
            framesAccumulated++;

            tickAccumulator += Time.unscaledDeltaTime;
            while (tickAccumulator >= tickInterval)
            {
                tickAccumulator -= tickInterval;
                FlushTick();
            }
        }

        public void FlushNow()
        {
            if (!EnsureTransport())
                return;
            FlushTick();
        }

        private void OnHandshakeAccepted(XaceHandshakeAck ack)
        {
            if (ack.tick_rate > 0)
                tickInterval = 1f / ack.tick_rate;
        }

        private void OnTickSnapshot(XaceTickSnapshot snapshot)
        {
            latestRuntimeTick = Math.Max(latestRuntimeTick, snapshot.tick);
        }

        private void SampleFrame()
        {
            accumulator.moveX += SafeAxis(horizontalAxis);
            accumulator.moveY += SafeAxis(verticalAxis);
            accumulator.lookX += SafeAxis(mouseXAxis);
            accumulator.lookY += SafeAxis(mouseYAxis);

            accumulator.jump |= SafeButton(jumpButton);
            accumulator.primaryFire |= SafeButton(primaryFireButton);
            accumulator.secondaryFire |= SafeButton(secondaryFireButton);
            accumulator.interact |= SafeButtonDown(interactButton);
            accumulator.sprint |= SafeButton(sprintButton);
            accumulator.crouch |= SafeButton(crouchButton);
            accumulator.pause |= SafeKeyDown(KeyCode.Escape);
        }

        private void FlushTick()
        {
            if (!EnsureTransport())
                return;

            var frameCount = Mathf.Max(1, framesAccumulated);
            var actions = new List<XaceInputAction>(12);

            AddAxis2D(actions, "move", accumulator.moveX / frameCount, accumulator.moveY / frameCount, sendIdleMovement);
            AddAxis2D(actions, "look", accumulator.lookX / frameCount, accumulator.lookY / frameCount, false);
            AddButton(actions, "jump", accumulator.jump);
            AddButton(actions, "primary_fire", accumulator.primaryFire);
            AddButton(actions, "secondary_fire", accumulator.secondaryFire);
            AddButton(actions, "interact", accumulator.interact);
            AddButton(actions, "sprint", accumulator.sprint);
            AddButton(actions, "crouch", accumulator.crouch);
            AddButton(actions, "pause", accumulator.pause);

            actions.Sort((left, right) => string.CompareOrdinal(left.action, right.action));

            var packetTick = Math.Max(latestRuntimeTick + 1, lastSentTick + 1);
            var packet = new XaceInputPacket
            {
                peer_id = peerId == 0 ? 1 : peerId,
                player_id = playerId,
                tick = packetTick,
                sequence_id = transport.NextSequenceId(),
                actions = actions.ToArray(),
                timestamp_ms = (ulong)Math.Max(0.0f, Time.realtimeSinceStartup * 1000.0f),
                device_id = string.IsNullOrWhiteSpace(deviceId) ? "unity" : deviceId.Trim(),
                predicted = predicted
            };

            if (transport.SendInputPacket(packet))
            {
                lastSentTick = packetTick;
                OnInputPacketBuilt?.Invoke(packet);
            }

            accumulator.Reset();
            framesAccumulated = 0;
        }

        private void AddAxis2D(List<XaceInputAction> actions, string name, float x, float y, bool includeIdle)
        {
            x = ClampUnit(x);
            y = ClampUnit(y);
            var active = Mathf.Abs(x) > deadzone || Mathf.Abs(y) > deadzone;
            if (!active && !includeIdle)
                return;

            actions.Add(new XaceInputAction
            {
                action = name,
                value = active ? x : 0f,
                secondary_value = active ? y : 0f,
                kind = "axis_2d",
                phase = active ? "changed" : "cancelled"
            });
        }

        private static void AddButton(List<XaceInputAction> actions, string name, bool pressed)
        {
            if (!pressed)
                return;
            actions.Add(new XaceInputAction
            {
                action = name,
                value = 1f,
                secondary_value = 0f,
                kind = "button",
                phase = "performed"
            });
        }

        private static float SafeAxis(string axisName)
        {
            if (string.IsNullOrWhiteSpace(axisName))
                return 0f;
            try { return ClampUnit(Input.GetAxisRaw(axisName)); }
            catch (Exception ex) when (IsInputUnavailable(ex)) { return 0f; }
        }

        private static bool SafeButton(string buttonName)
        {
            if (string.IsNullOrWhiteSpace(buttonName))
                return false;
            try { return Input.GetButton(buttonName); }
            catch (Exception ex) when (IsInputUnavailable(ex)) { return false; }
        }

        private static bool SafeButtonDown(string buttonName)
        {
            if (string.IsNullOrWhiteSpace(buttonName))
                return false;
            try { return Input.GetButtonDown(buttonName); }
            catch (Exception ex) when (IsInputUnavailable(ex)) { return false; }
        }

        private static bool SafeKeyDown(KeyCode key)
        {
            try { return Input.GetKeyDown(key); }
            catch (Exception ex) when (IsInputUnavailable(ex)) { return false; }
        }

        private static bool IsInputUnavailable(Exception ex)
        {
            return ex is ArgumentException || ex is InvalidOperationException;
        }

        private bool EnsureTransport()
        {
            if (transport == null)
                transport = GetComponent<XaceTransport>();
            return transport != null;
        }

        private static float ClampUnit(float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value))
                return 0f;
            return Mathf.Clamp(value, -1f, 1f);
        }

        private sealed class InputAccumulator
        {
            public float moveX;
            public float moveY;
            public float lookX;
            public float lookY;
            public bool jump;
            public bool primaryFire;
            public bool secondaryFire;
            public bool interact;
            public bool sprint;
            public bool crouch;
            public bool pause;

            public void Reset()
            {
                moveX = 0f;
                moveY = 0f;
                lookX = 0f;
                lookY = 0f;
                jump = false;
                primaryFire = false;
                secondaryFire = false;
                interact = false;
                sprint = false;
                crouch = false;
                pause = false;
            }
        }
    }
}

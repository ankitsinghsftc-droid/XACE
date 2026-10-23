// XaceInputCollector.cs
// Collects Unity input and sends Phase 15 runtime input_packet messages.
//
// The runtime bridge consumes the schema defined in
// packages/runtime-core/src/engine_protocol.rs:
//   { msg_type, peer_id, tick, player_id, sequence_id, actions, timestamp_ms,
//     device_id, predicted }
//
// Live sessions sample generic bindings only for an authority input request.
// The legacy standalone transport retains its frame accumulator.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    [Serializable]
    public sealed class XaceLiveInputBinding
    {
        public string action;
        public string kind = "axis_1d";
        // Optional explicit native event selector; empty retains physical-key sampling.
        public string nativeSelector = "";
        public KeyCode positive;
        public KeyCode negative;
    }
    [RequireComponent(typeof(XaceTransport))]
    public sealed class XaceInputCollector : MonoBehaviour
    {
        [Header("Identity")]
        [SerializeField] private ulong peerId = 1;
        [SerializeField] private ulong playerId = 1;
        public XaceLiveInputBinding[] liveBindings = new XaceLiveInputBinding[0];
        private readonly Dictionary<string,float> nativeSamples = new Dictionary<string,float>(StringComparer.Ordinal);
        private readonly Dictionary<string,float> livePrevious = new Dictionary<string,float>(StringComparer.Ordinal);
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
                transport.OnSessionInputTick += OnSessionInputTick;
            }
        }

        private void OnDisable()
        {
            if (EnsureTransport())
            {
                transport.OnTickSnapshot -= OnTickSnapshot;
                transport.OnHandshakeAccepted -= OnHandshakeAccepted;
                transport.OnSessionInputTick -= OnSessionInputTick;
            }
        }

        private void Update()
        {
            if (!EnsureTransport() || !transport.IsConnected)
                return;
            if (transport.Session.Enabled) return;

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
            if (transport.Session.Enabled) return;
            FlushTick();
        }

        private void OnHandshakeAccepted(XaceHandshakeAck ack)
        {
            livePrevious.Clear();
            nativeSamples.Clear();
            if (ack.tick_rate > 0)
                tickInterval = 1f / ack.tick_rate;
        }

        // Native Input System callbacks/UI events can submit a named sample. This
        // only buffers input; it cannot send a packet or mutate gameplay.
        public bool SubmitNativeAction(string selector, float value)
        {
            if (string.IsNullOrEmpty(selector) || float.IsNaN(value) || float.IsInfinity(value) || value < -1 || value > 1) return false;
            bool declared=false;
            foreach (var binding in liveBindings)
                if (binding.nativeSelector == selector) declared=true;
            if (!declared) return false;
            nativeSamples[selector]=value;
            return true;
        }

        public XaceInputAction[] CollectDeclaredLiveActions()
        {
            var actions=new List<XaceInputAction>();
            var names=new HashSet<string>(StringComparer.Ordinal);
            if (liveBindings.Length > 256) throw new FormatException("Too many live input bindings");
            foreach(var binding in liveBindings)
            {
                if(binding == null || string.IsNullOrEmpty(binding.action) || !names.Add(binding.action) || (binding.kind!="axis_1d" && binding.kind!="button")) throw new FormatException("Invalid live input binding");
                float value;
                if (!string.IsNullOrEmpty(binding.nativeSelector)) nativeSamples.TryGetValue(binding.nativeSelector,out value);
                else value=Application.isFocused ? (SafeKey(binding.positive)?1:0)-(SafeKey(binding.negative)?1:0) : 0;
                if (binding.kind=="button" && value!=0 && value!=1) throw new FormatException("Button input must be zero or one");
                livePrevious.TryGetValue(binding.action,out var previous);
                actions.Add(new XaceInputAction{action=binding.action,kind=binding.kind,value=value,phase=value==0?"cancelled":binding.kind=="button"?(previous==0?"started":"performed"):"changed"});
            }
            actions.Sort((a,b)=>string.CompareOrdinal(a.action,b.action));
            return actions.ToArray();
        }

        private void OnSessionInputTick(ulong tick)
        {
            var actions=CollectDeclaredLiveActions();
            var packet=new XaceInputPacket{tick=tick,peer_id=(ulong)transport.Session.PeerId,player_id=(ulong)transport.Session.PlayerId,
                sequence_id=transport.NextSequenceId(),actions=actions,device_id="unity",predicted=false};
            if(transport.SendInputPacket(packet))
            {
                foreach(var action in actions)livePrevious[action.action]=action.value;
                OnInputPacketBuilt?.Invoke(packet);
            }
        }

        private void OnApplicationFocus(bool focused)
        {
            if (!focused) nativeSamples.Clear();
        }

        private static bool SafeKey(KeyCode key) => key!=KeyCode.None && Input.GetKey(key);

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

// Applies DELTA messages // XaceDeltaApplicator.cs
// Applies DELTA and SNAPSHOT WireMessages from the XACE runtime to the Unity scene.
// Spawns/destroys GameObjects, updates component data, and collects animation
// and physics callbacks to send back as feedback (Audit 6).
//
// ## Responsibility (Layer 6 — Engine Adapter)
// This script is the write path: XACE→Unity. It receives canonical component
// data (COMP_TRANSFORM_V1, COMP_RENDER_V1, COMP_ANIMATION_V2, etc.) and maps
// it to Unity-native types (Transform, MeshRenderer, Animator, Rigidbody).
//
// It NEVER writes back to the XACE runtime directly. Feedback (animation state,
// physics settled positions) is collected here and handed to XaceTransport.Send()
// — the authoritative write stays in XACE via the Mutation Gate (I5, D13).
//
// ## Feedback Collection (Audit 6)
// After applying animation commands, XaceDeltaApplicator registers Unity
// Animator callbacks (AnimatorStateInfo per layer) and Rigidbody sleep events.
// These are batched and sent as FeedbackMessage payloads at the end of each
// Unity LateUpdate, which maps to the XACE tick boundary (I13).
//
// ## Entity → GameObject Mapping
// XACE EntityIDs are mapped to Unity GameObjects via _entityMap.
// On spawn: instantiate a prefab (from PrefabRegistry by actor_id) or an empty GO.
// On destroy: destroy the GO and remove from map.
// On component update: find the GO, update its Unity components.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    /// <summary>
    /// Applies XACE DELTA and SNAPSHOT messages to the Unity scene.
    /// Requires XaceTransport on the same or a parent GameObject.
    /// </summary>
    [RequireComponent(typeof(XaceTransport))]
    public class XaceDeltaApplicator : MonoBehaviour
    {
        // ── Configuration ──────────────────────────────────────────────────

        [Header("Prefab Registry")]
        [Tooltip("Root Transform under which all XACE-spawned GameObjects are placed.")]
        [SerializeField] private Transform _sceneRoot;

        [Tooltip("Fallback prefab used when no specific prefab is registered for an actor.")]
        [SerializeField] private GameObject _fallbackPrefab;

        // ── State ──────────────────────────────────────────────────────────

        // EntityID → Unity GameObject
        private readonly Dictionary<ulong, GameObject> _entityMap = new();

        // Prefab registry: actor_id → Prefab
        private readonly Dictionary<string, GameObject> _prefabRegistry = new();

        // Pending feedback to send this tick (collected during Apply*, dispatched in LateUpdate)
        private readonly List<FeedbackMessage> _pendingFeedback = new();

        private XaceTransport _transport;
        private ulong         _currentTick;
        private ulong         _currentFrame;

        // ── Unity Lifecycle ────────────────────────────────────────────────

        private void Awake()
        {
            _transport = GetComponent<XaceTransport>();
            if (_sceneRoot == null)
            {
                var root = new GameObject("XaceScene");
                _sceneRoot = root.transform;
            }
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

        private void LateUpdate()
        {
            // Collect animation state feedback from all tracked Animators
            CollectAnimationFeedback();

            // Dispatch all pending feedback messages as one FEEDBACK WireMessage
            if (_pendingFeedback.Count > 0)
                FlushFeedback();

            _currentFrame++;
        }

        // ── Message Routing ────────────────────────────────────────────────

        private void OnMessageReceived(WireMessage msg)
        {
            if (msg.IsSnapshot)
                ApplySnapshot(msg);
            else if (msg.IsDelta)
                ApplyDelta(msg);
        }

        // ── Snapshot Application ───────────────────────────────────────────

        private void ApplySnapshot(WireMessage msg)
        {
            var snapshot = JsonUtility.FromJson<SnapshotPayload>(msg.payload);
            if (snapshot == null) return;

            _currentTick = snapshot.tick;

            // Clear all existing scene entities — full rebuild
            foreach (var go in _entityMap.Values)
                if (go != null) Destroy(go);
            _entityMap.Clear();

            foreach (var entity in snapshot.entities)
                SpawnEntity(entity.entity_id, entity.actor_id, entity.components);

            Debug.Log($"[XaceDeltaApplicator] Snapshot applied: tick={snapshot.tick}, " +
                      $"entities={snapshot.entities?.Length ?? 0}");
        }

        // ── Delta Application ──────────────────────────────────────────────

        private void ApplyDelta(WireMessage msg)
        {
            var delta = JsonUtility.FromJson<DeltaPayload>(msg.payload);
            if (delta == null) return;

            _currentTick = delta.tick;

            // D4 order: spawn → add_components → modify → remove_components → destroy
            if (delta.spawned_entities != null)
                foreach (var spawned in delta.spawned_entities)
                    SpawnEntity(spawned.entity_id, spawned.actor_id, spawned.initial_components);

            if (delta.added_components != null)
                foreach (var added in delta.added_components)
                    ApplyComponentAdd(added.entity_id, added.component);

            if (delta.modified_entities != null)
                foreach (var modified in delta.modified_entities)
                    ApplyEntityUpdate(modified);

            if (delta.removed_components != null)
                foreach (var removed in delta.removed_components)
                    ApplyComponentRemove(removed.entity_id, removed.component_type_id);

            if (delta.destroyed_entities != null)
                foreach (var destroyed in delta.destroyed_entities)
                    DestroyEntity(destroyed.entity_id);
        }

        // ── Entity Spawn / Destroy ─────────────────────────────────────────

        private void SpawnEntity(ulong entityId, string actorId, WireComponentData[] components)
        {
            if (_entityMap.ContainsKey(entityId))
            {
                Debug.LogWarning($"[XaceDeltaApplicator] Entity {entityId} already exists. Skipping spawn.");
                return;
            }

            GameObject go = InstantiateForActor(actorId);
            go.name = $"Entity_{entityId}_{actorId}";
            go.transform.SetParent(_sceneRoot, false);

            // Tag with XACE entity ID for lookup
            var marker = go.AddComponent<XaceEntityMarker>();
            marker.EntityId = entityId;
            marker.ActorId  = actorId;

            _entityMap[entityId] = go;

            if (components != null)
                foreach (var comp in components)
                    ApplyComponent(go, comp);
        }

        private void DestroyEntity(ulong entityId)
        {
            if (!_entityMap.TryGetValue(entityId, out GameObject go))
                return;

            // If Rigidbody is sleeping when destroyed, record its final position
            var rb = go.GetComponent<Rigidbody>();
            if (rb != null && rb.IsSleeping())
                EnqueuePhysicsSettled(entityId, go.transform);

            Destroy(go);
            _entityMap.Remove(entityId);
        }

        private GameObject InstantiateForActor(string actorId)
        {
            if (!string.IsNullOrEmpty(actorId) && _prefabRegistry.TryGetValue(actorId, out var prefab) && prefab != null)
                return Instantiate(prefab);
            if (_fallbackPrefab != null)
                return Instantiate(_fallbackPrefab);
            return new GameObject();
        }

        // ── Component Application ──────────────────────────────────────────

        private void ApplyEntityUpdate(EntityUpdate update)
        {
            if (!_entityMap.TryGetValue(update.entity_id, out GameObject go))
                return;

            if (update.component_updates == null) return;
            foreach (var cu in update.component_updates)
                ApplyComponent(go, cu);
        }

        private void ApplyComponentAdd(ulong entityId, WireComponentData component)
        {
            if (!_entityMap.TryGetValue(entityId, out GameObject go)) return;
            ApplyComponent(go, component);
        }

        private void ApplyComponentRemove(ulong entityId, uint componentTypeId)
        {
            // Component removal — handled per-type; most types have no Unity remove equivalent
            // For simplicity: log only. Full implementation per-component in Phase 9.
            Debug.Log($"[XaceDeltaApplicator] Remove component {componentTypeId} from entity {entityId}");
        }

        private void ApplyComponent(GameObject go, WireComponentData comp)
        {
            if (comp == null || string.IsNullOrEmpty(comp.data_json)) return;

            // Route by component_type_id (UCL Core IDs 1–10, DCL IDs 100+)
            switch (comp.component_type_id)
            {
                case 1: ApplyTransform(go, comp.data_json); break;       // COMP_TRANSFORM_V1
                case 3: ApplyRender(go, comp.data_json); break;           // COMP_RENDER_V1
                case 7: ApplyInput(go, comp.data_json); break;            // COMP_INPUT_V1
                case 121: ApplyAnimation(go, comp.data_json); break;      // COMP_ANIMATION_V2 (DCL)
                case 141: ApplyRigidbody(go, comp.data_json); break;      // COMP_RIGIDBODY_V1 (DCL)
                // Other components: stored for later use
                default:
                    var marker = go.GetComponent<XaceEntityMarker>();
                    if (marker != null)
                        marker.SetComponentData(comp.component_type_id, comp.data_json);
                    break;
            }
        }

        // ── COMP_TRANSFORM_V1 ──────────────────────────────────────────────

        private static void ApplyTransform(GameObject go, string json)
        {
            var data = JsonUtility.FromJson<TransformComponentData>(json);
            if (data == null) return;
            go.transform.localPosition = new Vector3(data.position.x, data.position.y, data.position.z);
            go.transform.localRotation = new Quaternion(data.rotation.x, data.rotation.y, data.rotation.z, data.rotation.w);
            go.transform.localScale    = new Vector3(data.scale.x, data.scale.y, data.scale.z);
        }

        // ── COMP_RENDER_V1 ─────────────────────────────────────────────────

        private static void ApplyRender(GameObject go, string json)
        {
            var data = JsonUtility.FromJson<RenderComponentData>(json);
            if (data == null) return;
            var renderer = go.GetComponent<Renderer>();
            if (renderer == null) return;
            renderer.enabled = data.visible;
            renderer.shadowCastingMode = data.cast_shadows
                ? UnityEngine.Rendering.ShadowCastingMode.On
                : UnityEngine.Rendering.ShadowCastingMode.Off;
        }

        // ── COMP_ANIMATION_V2 (Audit 3) ────────────────────────────────────

        private void ApplyAnimation(GameObject go, string json)
        {
            var data = JsonUtility.FromJson<AnimationComponentData>(json);
            var animator = go.GetComponent<Animator>();
            if (animator == null || data == null) return;

            // Apply playback speed
            animator.speed = data.playback_speed;

            // Apply parameters
            if (data.parameters != null)
                foreach (var param in data.parameters)
                    ApplyAnimatorParameter(animator, param);

            // Register this animator for feedback collection in LateUpdate
            var marker = go.GetComponent<XaceEntityMarker>();
            if (marker != null)
                marker.TrackedAnimator = animator;

            // Apply pending animation events → register callbacks on Animator
            // Events fire as AnimationEventFiredFeedback when triggered (Audit 3)
            if (data.pending_events != null)
                foreach (var evt in data.pending_events)
                    if (!evt.is_consumed)
                        RegisterAnimationEventCallback(go, marker?.EntityId ?? 0, evt);
        }

        private static void ApplyAnimatorParameter(Animator animator, AnimationParameter param)
        {
            switch (param.type?.ToUpperInvariant())
            {
                case "FLOAT":   animator.SetFloat(param.name, param.float_value); break;
                case "BOOL":    animator.SetBool(param.name, param.bool_value); break;
                case "INT":     animator.SetInteger(param.name, param.int_value); break;
                case "TRIGGER": animator.SetTrigger(param.name); break;
            }
        }

        private void RegisterAnimationEventCallback(GameObject go, ulong entityId, PendingAnimEvent evt)
        {
            // StateMachineBehaviour-based event detection for specific normalized times
            // Registered per-state on the Animator Controller states
            // In Phase 9 this is replaced by a proper AnimationEventBehaviour component
            var probe = go.AddComponent<XaceAnimationEventProbe>();
            probe.Init(entityId, evt.event_id, evt.state_name, evt.trigger_at_normalized_time,
                       _pendingFeedback, _currentFrame);
        }

        // ── COMP_RIGIDBODY_V1 ──────────────────────────────────────────────

        private static void ApplyRigidbody(GameObject go, string json)
        {
            var data = JsonUtility.FromJson<RigidbodyComponentData>(json);
            var rb   = go.GetComponent<Rigidbody>() ?? go.AddComponent<Rigidbody>();
            if (data == null) return;

            rb.mass          = data.mass;
            rb.linearDamping        = data.drag;
            rb.angularDamping = data.angular_drag;
            rb.useGravity    = data.use_gravity;
            rb.isKinematic   = data.is_kinematic;
        }

        // ── COMP_INPUT_V1 ──────────────────────────────────────────────────

        private static void ApplyInput(GameObject go, string json)
        {
            // Input component sets which controller index this entity responds to.
            // XaceInputCollector reads this to know which player's input to collect.
            var data   = JsonUtility.FromJson<InputComponentData>(json);
            var marker = go.GetComponent<XaceEntityMarker>();
            if (marker != null && data != null)
                marker.ControllerId = data.controller_id;
        }

        // ── Feedback Collection ────────────────────────────────────────────

        /// <summary>
        /// Collects animation state from all tracked Animators.
        /// Called every LateUpdate — dispatched to XACE as AnimationStateUpdateFeedback.
        /// </summary>
        private void CollectAnimationFeedback()
        {
            foreach (var kv in _entityMap)
            {
                var marker = kv.Value?.GetComponent<XaceEntityMarker>();
                if (marker?.TrackedAnimator == null) continue;

                var animator = marker.TrackedAnimator;
                var stateUpdate = new AnimationStateUpdateFeedback
                {
                    entity_id           = kv.Key,
                    generated_frame     = _currentFrame,
                    is_transitioning    = animator.IsInTransition(0),
                };

                // Collect state info per layer
                int layerCount = animator.layerCount;
                stateUpdate.active_state_per_layer    = new string[layerCount];
                stateUpdate.normalized_time_per_layer = new float[layerCount];

                for (int i = 0; i < layerCount; i++)
                {
                    var info = animator.GetCurrentAnimatorStateInfo(i);
                    stateUpdate.active_state_per_layer[i]    = animator.GetLayerName(i);
                    stateUpdate.normalized_time_per_layer[i] = info.normalizedTime % 1.0f;
                }

                EnqueueFeedback(FeedbackType.AnimationStateUpdate, kv.Key,
                                JsonUtility.ToJson(stateUpdate));
            }
        }

        private void EnqueuePhysicsSettled(ulong entityId, Transform t)
        {
            var settled = new PhysicsSettledFeedback
            {
                entity_id          = entityId,
                generated_frame    = _currentFrame,
                final_position_json = $"{{\"x\":{t.position.x},\"y\":{t.position.y},\"z\":{t.position.z}}}",
                final_rotation_json = $"{{\"x\":{t.rotation.x},\"y\":{t.rotation.y}," +
                                      $"\"z\":{t.rotation.z},\"w\":{t.rotation.w}}}",
            };
            EnqueueFeedback(FeedbackType.PhysicsSettled, entityId, JsonUtility.ToJson(settled));
        }

        private void EnqueueFeedback(FeedbackType type, ulong entityId, string payloadJson)
        {
            _pendingFeedback.Add(new FeedbackMessage
            {
                feedback_type   = (int)type,
                entity_id       = entityId,
                generated_frame = _currentFrame,
                payload_json    = payloadJson,
            });
        }

        private void FlushFeedback()
        {
            var batch = new FeedbackPayload
            {
                tick     = _currentTick,
                messages = _pendingFeedback.ToArray(),
            };
            _transport.SendFeedback(batch);
            _pendingFeedback.Clear();
        }

        // ── Prefab Registry ────────────────────────────────────────────────

        /// <summary>
        /// Registers a prefab for a given actor_id. Call from your game setup code
        /// before the first SNAPSHOT arrives.
        /// </summary>
        public void RegisterPrefab(string actorId, GameObject prefab)
        {
            _prefabRegistry[actorId] = prefab;
        }

        /// <summary>Returns the GameObject for a given EntityID, or null.</summary>
        public GameObject GetEntity(ulong entityId)
            => _entityMap.TryGetValue(entityId, out var go) ? go : null;
    }

    // ── Entity Marker Component ────────────────────────────────────────────────

    public class XaceEntityMarker : MonoBehaviour
    {
        public ulong   EntityId;
        public string  ActorId;
        public int     ControllerId;
        public Animator TrackedAnimator;

        private readonly Dictionary<uint, string> _componentData = new();

        public void SetComponentData(uint typeId, string json) => _componentData[typeId] = json;
        public bool TryGetComponentData(uint typeId, out string json) => _componentData.TryGetValue(typeId, out json);
    }

    // ── Animation Event Probe ──────────────────────────────────────────────────

    /// <summary>
    /// Watches a specific animation state and fires feedback when the
    /// normalizedTime passes the trigger point (Audit 3 pending_events).
    /// </summary>
    public class XaceAnimationEventProbe : MonoBehaviour
    {
        private ulong   _entityId;
        private string  _eventId;
        private string  _stateName;
        private float   _triggerTime;
        private bool    _fired;
        private List<FeedbackMessage> _feedbackQueue;
        private ulong   _baseFrame;
        private Animator _animator;

        public void Init(ulong entityId, string eventId, string stateName,
                         float triggerTime, List<FeedbackMessage> queue, ulong baseFrame)
        {
            _entityId      = entityId;
            _eventId       = eventId;
            _stateName     = stateName;
            _triggerTime   = triggerTime;
            _feedbackQueue = queue;
            _baseFrame     = baseFrame;
            _animator      = GetComponent<Animator>();
        }

        private void Update()
        {
            if (_fired || _animator == null) return;
            var info = _animator.GetCurrentAnimatorStateInfo(0);
            if (!info.IsName(_stateName)) return;
            float normalized = info.normalizedTime % 1.0f;
            if (normalized >= _triggerTime)
            {
                _fired = true;
                var firedFeedback = new AnimationEventFiredFeedback
                {
                    entity_id                  = _entityId,
                    event_id                   = _eventId,
                    state_name                 = _stateName,
                    trigger_at_normalized_time = normalized,
                    generated_frame            = _baseFrame,
                };
                _feedbackQueue.Add(new FeedbackMessage
                {
                    feedback_type   = (int)FeedbackType.AnimationEventFired,
                    entity_id       = _entityId,
                    generated_frame = _baseFrame,
                    payload_json    = JsonUtility.ToJson(firedFeedback),
                });
                Destroy(this); // one-shot
            }
        }
    }

    // ── Serializable Wire Payload Types ───────────────────────────────────────

    [Serializable] public class Vec3  { public float x, y, z; }
    [Serializable] public class Quat  { public float x, y, z, w; }

    [Serializable] public class TransformComponentData
    { public Vec3 position; public Quat rotation; public Vec3 scale; }

    [Serializable] public class RenderComponentData
    { public bool visible; public bool cast_shadows; }

    [Serializable] public class RigidbodyComponentData
    { public float mass; public float drag; public float angular_drag; public bool use_gravity; public bool is_kinematic; }

    [Serializable] public class InputComponentData
    { public int controller_id; public string control_type; }

    [Serializable] public class AnimationParameter
    { public string name; public string type; public float float_value; public bool bool_value; public int int_value; }

    [Serializable] public class PendingAnimEvent
    { public string event_id; public string state_name; public float trigger_at_normalized_time; public bool is_consumed; }

    [Serializable] public class AnimationComponentData
    {
        public float playback_speed;
        public AnimationParameter[] parameters;
        public PendingAnimEvent[]   pending_events;
    }

    [Serializable] public class WireComponentData
    { public uint component_type_id; public string component_type_name; public string data_json; }

    [Serializable] public class WireSpawnedEntity
    { public ulong entity_id; public string actor_id; public WireComponentData[] initial_components; }

    [Serializable] public class WireDestroyedEntity { public ulong entity_id; }

    [Serializable] public class WireRemovedComponent { public ulong entity_id; public uint component_type_id; }

    [Serializable] public class WireAddedComponent { public ulong entity_id; public WireComponentData component; }

    [Serializable] public class EntityUpdate
    { public ulong entity_id; public WireComponentData[] component_updates; }

    [Serializable] public class DeltaPayload
    {
        public ulong  tick;
        public ulong  sequence_id;
        public string schema_version;
        public WireSpawnedEntity[]  spawned_entities;
        public WireAddedComponent[] added_components;
        public EntityUpdate[]       modified_entities;
        public WireRemovedComponent[] removed_components;
        public WireDestroyedEntity[]  destroyed_entities;
    }

    [Serializable] public class SnapshotEntity
    { public ulong entity_id; public string actor_id; public WireComponentData[] components; }

    [Serializable] public class SnapshotPayload
    { public ulong tick; public string schema_version; public SnapshotEntity[] entities; }

    // ── Feedback Payload Types ─────────────────────────────────────────────────

    public enum FeedbackType { AnimationStateUpdate=0, AnimationEventFired=1, PhysicsSettled=2, VisibilityQueryResult=3, AudioComplete=4, AudioPositionUpdate=5, InputDeviceUpdate=6, PerformanceMetrics=7, AssetResolutionUpdate=8, EngineError=9 }

    [Serializable] public class FeedbackMessage
    { public int feedback_type; public ulong entity_id; public ulong generated_frame; public string payload_json; }

    [Serializable] public class FeedbackPayload { public ulong tick; public FeedbackMessage[] messages; }

    [Serializable] public class AnimationStateUpdateFeedback
    { public ulong entity_id; public ulong generated_frame; public bool is_transitioning; public string[] active_state_per_layer; public float[] normalized_time_per_layer; }

    [Serializable] public class AnimationEventFiredFeedback
    { public ulong entity_id; public string event_id; public string state_name; public float trigger_at_normalized_time; public ulong generated_frame; }

    [Serializable] public class PhysicsSettledFeedback
    { public ulong entity_id; public string final_position_json; public string final_rotation_json; public ulong generated_frame; }
}— spawns/destroys GameObjects, updates components, maps canonical->Unity data — Phase 7

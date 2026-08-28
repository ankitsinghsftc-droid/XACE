// XaceDeltaApplicator.cs
// Mirrors XACE runtime snapshots into a Unity scene.
//
// Adapter invariant: Unity is a mirror. This script applies runtime-owned
// state to GameObjects and never mutates XACE authoritative state directly.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xace.Adapter.Unity
{
    [RequireComponent(typeof(XaceTransport))]
    public sealed class XaceDeltaApplicator : MonoBehaviour
    {
        private const uint TransformComponent = 1;
        private const uint IdentityComponent = 2;
        private const uint InputComponent = 6;
        private const uint HealthComponent = 100;

        [Header("Scene")]
        [SerializeField] private Transform sceneRoot;
        [SerializeField] private GameObject fallbackPrefab;
        [SerializeField] private bool createDebugCapsules = true;
        [SerializeField] private bool removeMissingSnapshotEntities = true;

        [Header("Debug Materials")]
        [SerializeField] private Material playerMaterial;
        [SerializeField] private Material zombieMaterial;
        [SerializeField] private Material neutralMaterial;

        [Header("Feedback")]
        [SerializeField] private bool collectFeedback = true;
        [SerializeField] private bool sendFeedbackToRuntime = true;
        [SerializeField] private bool sendLiveValidationFeedback = true;

        public event Action<ulong, int> OnSnapshotApplied;
        public event Action<Dictionary<string, object>> OnFeedbackReady;
        public event Action<XacePlaybackCommand, bool> OnPlaybackCommandApplied;

        private readonly Dictionary<ulong, GameObject> entityMap = new Dictionary<ulong, GameObject>();
        private readonly Dictionary<string, GameObject> prefabRegistry = new Dictionary<string, GameObject>(StringComparer.Ordinal);
        private readonly Dictionary<string, XaceAssetReference> assetBindingState = new Dictionary<string, XaceAssetReference>(StringComparer.Ordinal);
        private readonly Dictionary<string, Dictionary<string, object>> assetBindingStatusReport = new Dictionary<string, Dictionary<string, object>>(StringComparer.Ordinal);
        private readonly List<Dictionary<string, object>> feedbackQueue = new List<Dictionary<string, object>>();
        private readonly List<GameObject> spawnedPlaybackObjects = new List<GameObject>();

        private XaceTransport transport;
        private ulong currentTick;
        private ulong generatedFrame;
        private bool transportSubscribed;

        public int EntityCount => entityMap.Count;
        public ulong CurrentTick => currentTick;

        private void Awake()
        {
            EnsureTransport();
            EnsureSceneRoot();
        }

        private void OnEnable()
        {
            SubscribeTransport();
        }

        private void Start()
        {
            SubscribeTransport();
        }

        private void OnDisable()
        {
            UnsubscribeTransport();
        }

        private bool EnsureTransport()
        {
            if (transport == null)
                transport = GetComponent<XaceTransport>();
            return transport != null;
        }

        private void SubscribeTransport()
        {
            if (transportSubscribed || !EnsureTransport())
                return;
            transport.OnHandshakeAccepted += OnHandshakeAccepted;
            transport.OnTickSnapshot += ApplyTickSnapshot;
            transport.OnAdapterSideEffectRollback += ApplyAdapterSideEffectRollback;
            transportSubscribed = true;
        }

        private void UnsubscribeTransport()
        {
            if (!transportSubscribed || transport == null)
                return;
            transport.OnHandshakeAccepted -= OnHandshakeAccepted;
            transport.OnTickSnapshot -= ApplyTickSnapshot;
            transport.OnAdapterSideEffectRollback -= ApplyAdapterSideEffectRollback;
            transportSubscribed = false;
        }

        private void LateUpdate()
        {
            generatedFrame++;
            if (!collectFeedback)
                return;
            CollectAnimationFeedback();
            CollectPhysicsFeedback();
            FlushFeedback();
        }

        public void RegisterPrefab(string actorId, GameObject prefab)
        {
            if (string.IsNullOrWhiteSpace(actorId) || prefab == null)
                return;
            prefabRegistry[actorId.Trim()] = prefab;
        }

        public GameObject GetEntity(ulong entityId)
        {
            entityMap.TryGetValue(entityId, out var go);
            return go;
        }

        public IReadOnlyDictionary<ulong, GameObject> Entities => entityMap;
        public IReadOnlyDictionary<string, XaceAssetReference> AssetBindingState => assetBindingState;
        public IReadOnlyDictionary<string, Dictionary<string, object>> AssetBindingStatusReport => assetBindingStatusReport;

        public Dictionary<string, object> BuildAssetBindingStatusReport()
        {
            return new Dictionary<string, object>(StringComparer.Ordinal)
            {
                ["schema"] = "xace.adapter.semantic_binding_status_report.v1",
                ["engine"] = "unity",
                ["statuses"] = new[] { "resolved", "unresolved", "unsupported", "missing", "fallback" },
                ["records"] = new List<Dictionary<string, object>>(assetBindingStatusReport.Values)
            };
        }

        public void BindTransportNow()
        {
            SubscribeTransport();
        }

        private void OnHandshakeAccepted(XaceHandshakeAck ack)
        {
            EnsureSceneRoot();
            ApplyEntityList(0, ack.initial_entities, true, new List<ulong>());
        }

        private void ApplyTickSnapshot(XaceTickSnapshot snapshot)
        {
            var started = Time.realtimeSinceStartupAsDouble;
            EnsureSceneRoot();
            currentTick = snapshot.tick;
            ApplyEntityList(snapshot.tick, snapshot.entities, removeMissingSnapshotEntities, snapshot.destroyed_ids);
            ApplyPlaybackCommands(snapshot.playback_commands);
            var elapsedMs = Math.Max(0.0, (Time.realtimeSinceStartupAsDouble - started) * 1000.0);
            QueueLiveValidationFeedback(snapshot.tick, "tick_snapshot", OperationCount(snapshot.entities, snapshot.destroyed_ids), elapsedMs);
            FlushFeedback();
        }

        private void ApplyAdapterSideEffectRollback(XaceAdapterSideEffectRollback rollback)
        {
            if (rollback == null)
                return;
            currentTick = rollback.restore_tick;
            if (rollback.clear_feedback_queue)
                feedbackQueue.Clear();
            ClearPlaybackSideEffects();
            if (rollback.reset_asset_bindings)
            {
                assetBindingState.Clear();
                assetBindingStatusReport.Clear();
            }
            ApplyEntityList(rollback.restore_tick, rollback.restored_snapshot.entities, true, rollback.restored_snapshot.destroyed_ids);
        }

        private void ClearPlaybackSideEffects()
        {
            foreach (var spawned in spawnedPlaybackObjects)
            {
                if (spawned != null)
                    Destroy(spawned);
            }
            spawnedPlaybackObjects.Clear();

            foreach (var pair in entityMap)
            {
                var go = pair.Value;
                if (go == null)
                    continue;
                foreach (var source in go.GetComponentsInChildren<AudioSource>(true))
                    source.Stop();
                foreach (var particle in go.GetComponentsInChildren<ParticleSystem>(true))
                    particle.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
                foreach (var animation in go.GetComponentsInChildren<Animation>(true))
                    animation.Stop();
                foreach (var animator in go.GetComponentsInChildren<Animator>(true))
                    animator.Rebind();
                var marker = go.GetComponent<XaceEntityMarker>();
                if (marker != null)
                    marker.ClearPlaybackCommands();
            }
        }
        private void ApplyEntityList(ulong tick, List<XaceEntityState> entities, bool removeMissing, List<ulong> destroyedIds)
        {
            EnsureSceneRoot();

            if (destroyedIds != null)
            {
                foreach (var entityId in destroyedIds)
                    DestroyEntity(entityId);
            }

            var seen = new HashSet<ulong>();
            if (entities != null)
            {
                foreach (var entity in entities)
                {
                    if (entity == null || entity.id == 0)
                        continue;
                    seen.Add(entity.id);
                    UpsertEntity(entity);
                }
            }

            if (removeMissing)
            {
                var toRemove = new List<ulong>();
                foreach (var entityId in entityMap.Keys)
                {
                    if (!seen.Contains(entityId))
                        toRemove.Add(entityId);
                }
                foreach (var entityId in toRemove)
                    DestroyEntity(entityId);
            }

            OnSnapshotApplied?.Invoke(tick, entityMap.Count);
        }

        private void QueueLiveValidationFeedback(ulong tick, string messageType, int operationCount, double elapsedMs)
        {
            if (!sendLiveValidationFeedback)
                return;

            EnqueueFeedback("PerformanceMetrics", 0, new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["engine_delta_apply_ms"] = (float)Math.Max(0.0, elapsedMs),
                ["draw_calls"] = 0,
                ["physics_contacts"] = 0,
                ["engine_entity_count"] = entityMap.Count,
                ["generated_frame"] = tick,
                ["xace_live_validation"] = true,
                ["adapter_engine"] = "unity",
                ["message_type"] = messageType ?? "",
                ["operation_count"] = Math.Max(0, operationCount),
                ["runtime_tick"] = tick
            });
        }

        private static int OperationCount(List<XaceEntityState> entities, List<ulong> destroyedIds)
        {
            var count = entities != null ? entities.Count : 0;
            count += destroyedIds != null ? destroyedIds.Count : 0;
            return Math.Max(1, count);
        }

        private void ApplyPlaybackCommands(List<XacePlaybackCommand> commands)
        {
            if (commands == null)
                return;

            foreach (var command in commands)
            {
                if (command == null || command.entity_id == 0)
                    continue;
                if (!entityMap.TryGetValue(command.entity_id, out var go) || go == null)
                {
                    RecordAssetBindingStatus(command, false, "entity_missing");
                    OnPlaybackCommandApplied?.Invoke(command, false);
                    continue;
                }

                var marker = go.GetComponent<XaceEntityMarker>();
                if (marker != null)
                    marker.RecordPlaybackCommand(command);
                if (!string.IsNullOrWhiteSpace(command.binding_id) && command.asset != null)
                    assetBindingState[command.binding_id.Trim()] = command.asset;
                var applied = TryApplyPlaybackCommand(go, command);
                var reason = applied ? "applied" : "playback_resource_missing";
                if (applied && ShouldUseFallback(command))
                    reason = "fallback_applied";
                RecordAssetBindingStatus(command, applied, reason);
                OnPlaybackCommandApplied?.Invoke(command, applied);
            }
        }

        private void RecordAssetBindingStatus(XacePlaybackCommand command, bool applied, string reason)
        {
            if (command == null)
                return;
            var bindingId = string.IsNullOrWhiteSpace(command.binding_id) ? "<unbound>" : command.binding_id.Trim();
            var status = SemanticBindingStatus(command, applied);
            assetBindingStatusReport[bindingId] = new Dictionary<string, object>(StringComparer.Ordinal)
            {
                ["schema"] = "xace.adapter.semantic_binding_status_record.v1",
                ["engine"] = "unity",
                ["binding_id"] = bindingId,
                ["status"] = status,
                ["asset_id"] = command.asset != null ? command.asset.id ?? "" : "",
                ["playback_kind"] = command.playback_kind ?? "",
                ["reason"] = reason ?? "",
                ["blocks_runtime"] = status == "unresolved" || status == "unsupported" || status == "missing",
                ["blocks_handoff"] = status == "unresolved" || status == "unsupported" || status == "missing"
            };
        }

        private static string SemanticBindingStatus(XacePlaybackCommand command, bool applied)
        {
            var declared = DeclaredBindingStatus(command);
            if (!string.IsNullOrEmpty(declared))
                return declared;
            if (ShouldUseFallback(command))
                return "fallback";
            if (applied)
                return "resolved";
            var kind = (command.playback_kind ?? "").Trim().ToLowerInvariant();
            if (kind != "audio" && kind != "animation" && kind != "vfx")
                return "unsupported";
            return string.IsNullOrWhiteSpace(CommandResourcePath(command)) ? "unresolved" : "missing";
        }

        private static string DeclaredBindingStatus(XacePlaybackCommand command)
        {
            var declared = CommandParameter(command, "xace_binding_status", "").Trim().ToLowerInvariant();
            switch (declared)
            {
                case "resolved":
                case "unresolved":
                case "unsupported":
                case "missing":
                case "fallback":
                    return declared;
                default:
                    return "";
            }
        }

        private bool TryApplyPlaybackCommand(GameObject go, XacePlaybackCommand command)
        {
            var kind = (command.playback_kind ?? "").Trim().ToLowerInvariant();
            var applied = false;
            switch (kind)
            {
                case "audio":
                    applied = TryApplyAudioCommand(go, command);
                    break;
                case "animation":
                    applied = TryApplyAnimationCommand(go, command);
                    break;
                case "vfx":
                    applied = TryApplyVfxCommand(go, command);
                    break;
                default:
                    applied = false;
                    break;
            }
            if (applied)
                return true;
            return ShouldUseFallback(command) && TryApplyFallbackCommand(go, command);
        }

        private bool TryApplyFallbackCommand(GameObject go, XacePlaybackCommand command)
        {
            if (go == null || command == null)
                return false;
            var marker = GameObject.CreatePrimitive(PrimitiveType.Cube);
            marker.name = "XACE_Fallback_" + SafeAssetName(command);
            marker.transform.SetParent(go.transform, false);
            marker.transform.localPosition = new Vector3(0f, 1.65f, 0f);
            marker.transform.localRotation = Quaternion.identity;
            marker.transform.localScale = new Vector3(0.35f, 0.35f, 0.35f);
            var renderer = marker.GetComponent<Renderer>();
            if (renderer != null)
            {
                renderer.material.color = FallbackColor(FallbackKind(command));
            }

            var labelObject = new GameObject("XACE Fallback Label");
            labelObject.transform.SetParent(marker.transform, false);
            labelObject.transform.localPosition = new Vector3(0f, 0.55f, 0f);
            var label = labelObject.AddComponent<TextMesh>();
            label.text = FallbackLabel(command);
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.characterSize = 0.1f;
            label.fontSize = 42;
            spawnedPlaybackObjects.Add(marker);
            return true;
        }

        private bool TryApplyAudioCommand(GameObject go, XacePlaybackCommand command)
        {
            var source = go.GetComponentInChildren<AudioSource>();
            var clip = LoadCommandResource<AudioClip>(command);
            if (source == null && clip != null)
                source = go.AddComponent<AudioSource>();
            if (source == null)
                return false;
            if (clip != null)
            {
                source.PlayOneShot(clip);
                return true;
            }
            if (source.clip != null)
            {
                source.Play();
                return true;
            }
            return false;
        }

        private bool TryApplyAnimationCommand(GameObject go, XacePlaybackCommand command)
        {
            var animator = go.GetComponentInChildren<Animator>();
            var state = CommandParameter(command, "state", CommandParameter(command, "animation", command.semantic_action));
            if (animator != null && !string.IsNullOrWhiteSpace(state))
            {
                var fade = CommandFloat(command, "fade_seconds", 0.05f);
                animator.CrossFade(state.Trim(), Mathf.Max(0f, fade));
                return true;
            }

            var legacy = go.GetComponentInChildren<Animation>();
            var clip = LoadCommandResource<AnimationClip>(command);
            if (legacy != null && clip != null)
            {
                var clipName = string.IsNullOrWhiteSpace(state) ? SafeAssetName(command) : state.Trim();
                legacy.AddClip(clip, clipName);
                legacy.Play(clipName);
                return true;
            }
            return false;
        }

        private bool TryApplyVfxCommand(GameObject go, XacePlaybackCommand command)
        {
            var prefab = LoadCommandResource<GameObject>(command);
            if (prefab != null)
            {
                var instance = Instantiate(prefab, go.transform);
                instance.name = "XACE_VFX_" + SafeAssetName(command);
                spawnedPlaybackObjects.Add(instance);
                foreach (var particle in instance.GetComponentsInChildren<ParticleSystem>())
                    particle.Play(true);
                return true;
            }

            var existing = go.GetComponentInChildren<ParticleSystem>();
            if (existing == null)
                return false;
            existing.Play(true);
            return true;
        }

        private T LoadCommandResource<T>(XacePlaybackCommand command) where T : UnityEngine.Object
        {
            var path = CommandResourcePath(command);
            if (string.IsNullOrWhiteSpace(path))
                return null;
            return Resources.Load<T>(NormaliseResourcesPath(path));
        }

        private static string CommandResourcePath(XacePlaybackCommand command)
        {
            var path = CommandParameter(command, "resource_path", "");
            if (string.IsNullOrWhiteSpace(path))
                path = CommandParameter(command, "asset_path", "");
            if (string.IsNullOrWhiteSpace(path))
                path = CommandParameter(command, "path", "");
            if (string.IsNullOrWhiteSpace(path) && command.asset != null)
                path = command.asset.id ?? "";
            return path.Trim();
        }

        private static bool ShouldUseFallback(XacePlaybackCommand command)
        {
            if (command == null)
                return false;
            if (DeclaredBindingStatus(command) == "fallback")
                return true;
            if (TruthyParameter(command, "xace_runtime_fallback") || TruthyParameter(command, "xace_fallback_visible") || TruthyParameter(command, "allow_fallback"))
                return true;
            var status = (command.asset != null ? command.asset.status ?? "" : "").Trim().ToLowerInvariant();
            return status == "missing" || status == "placeholder";
        }

        private static bool TruthyParameter(XacePlaybackCommand command, string key)
        {
            var value = CommandParameter(command, key, "").Trim().ToLowerInvariant();
            return value == "true" || value == "1" || value == "yes" || value == "fallback";
        }

        private static string FallbackKind(XacePlaybackCommand command)
        {
            var explicitKind = CommandParameter(command, "xace_fallback_kind", "").Trim().ToLowerInvariant();
            if (!string.IsNullOrWhiteSpace(explicitKind))
                return explicitKind;
            var kind = (command.playback_kind ?? "").Trim().ToLowerInvariant();
            var assetType = (command.asset != null ? command.asset.asset_type ?? "" : "").Trim().ToLowerInvariant();
            if (kind == "animation" || assetType.Contains("animation"))
                return "visible_animation_marker";
            if (kind == "audio" || assetType.Contains("audio"))
                return "visible_audio_pulse";
            if (kind == "vfx" || assetType == "particle")
                return "visible_vfx_marker";
            if (kind == "mesh" || assetType == "mesh")
                return "visible_mesh_proxy";
            if (kind == "prefab" || assetType == "prefab")
                return "visible_prefab_proxy";
            return "visible_asset_proxy";
        }

        private static string FallbackLabel(XacePlaybackCommand command)
        {
            var explicitLabel = CommandParameter(command, "xace_fallback_label", "").Trim();
            if (!string.IsNullOrWhiteSpace(explicitLabel))
                return explicitLabel;
            return "XACE fallback\n" + FallbackKind(command).Replace("visible_", "") + "\n" + SafeAssetName(command);
        }

        private static Color FallbackColor(string fallbackKind)
        {
            var kind = (fallbackKind ?? "").ToLowerInvariant();
            if (kind.Contains("audio"))
                return new Color(0.25f, 0.65f, 1.0f, 0.9f);
            if (kind.Contains("animation"))
                return new Color(0.7f, 0.45f, 1.0f, 0.9f);
            if (kind.Contains("vfx"))
                return new Color(0.2f, 1.0f, 0.55f, 0.9f);
            if (kind.Contains("mesh") || kind.Contains("prefab"))
                return new Color(1.0f, 0.72f, 0.25f, 0.9f);
            return new Color(1.0f, 0.55f, 0.25f, 0.9f);
        }

        private static string NormaliseResourcesPath(string path)
        {
            var clean = (path ?? "").Replace("\\", "/").Trim();
            var resourcesIndex = clean.IndexOf("/Resources/", StringComparison.OrdinalIgnoreCase);
            if (resourcesIndex >= 0)
                clean = clean.Substring(resourcesIndex + "/Resources/".Length);
            if (clean.StartsWith("Resources/", StringComparison.OrdinalIgnoreCase))
                clean = clean.Substring("Resources/".Length);
            var extension = System.IO.Path.GetExtension(clean);
            if (!string.IsNullOrEmpty(extension))
                clean = clean.Substring(0, clean.Length - extension.Length);
            return clean;
        }

        private static string CommandParameter(XacePlaybackCommand command, string key, string fallback)
        {
            if (command == null || command.parameters == null || string.IsNullOrEmpty(key))
                return fallback;
            return command.parameters.TryGetValue(key, out var value) && value != null ? value : fallback;
        }

        private static float CommandFloat(XacePlaybackCommand command, string key, float fallback)
        {
            var raw = CommandParameter(command, key, "");
            if (string.IsNullOrWhiteSpace(raw))
                return fallback;
            try { return Convert.ToSingle(raw, System.Globalization.CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        private static string SafeAssetName(XacePlaybackCommand command)
        {
            var id = command != null && command.asset != null ? command.asset.id : "";
            if (string.IsNullOrWhiteSpace(id))
                id = command != null ? command.binding_id : "playback";
            return id.Replace(" ", "_").Replace("/", "_").Replace("\\", "_");
        }

        private void UpsertEntity(XaceEntityState state)
        {
            if (!entityMap.TryGetValue(state.id, out var go) || go == null)
            {
                go = InstantiateForEntity(state);
                entityMap[state.id] = go;
            }

            var marker = go.GetComponent<XaceEntityMarker>();
            if (marker == null)
                marker = go.AddComponent<XaceEntityMarker>();
            marker.EntityId = state.id;
            marker.ActorId = ResolveActorId(state);
            marker.SetComponents(state.components);

            ApplyComponents(go, marker, state.components);
        }

        private GameObject InstantiateForEntity(XaceEntityState state)
        {
            EnsureSceneRoot();
            var actorId = ResolveActorId(state);
            GameObject go = null;
            if (!string.IsNullOrEmpty(actorId) && prefabRegistry.TryGetValue(actorId, out var prefab) && prefab != null)
                go = Instantiate(prefab, sceneRoot);
            else if (fallbackPrefab != null)
                go = Instantiate(fallbackPrefab, sceneRoot);
            else if (createDebugCapsules)
                go = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            else
                go = new GameObject();

            go.name = "XACE_" + state.id + "_" + (string.IsNullOrEmpty(actorId) ? "Entity" : actorId);
            go.transform.SetParent(sceneRoot, false);
            EnsureLabel(go);
            return go;
        }

        private void DestroyEntity(ulong entityId)
        {
            if (!entityMap.TryGetValue(entityId, out var go))
                return;
            if (go != null)
                Destroy(go);
            entityMap.Remove(entityId);
        }

        private void ApplyComponents(GameObject go, XaceEntityMarker marker, SortedDictionary<uint, string> components)
        {
            if (components == null)
                return;

            if (components.TryGetValue(TransformComponent, out var transformJson))
                ApplyTransform(go.transform, transformJson);

            if (components.TryGetValue(InputComponent, out var inputJson))
                marker.ControllerId = (int)GetNumber(ParseObject(inputJson), "controller_id", marker.ControllerId);

            var actorId = ResolveActorId(marker.ActorId, components);
            ApplyDebugMaterial(go, actorId);

            var healthText = "";
            if (components.TryGetValue(HealthComponent, out var healthJson))
            {
                var health = ParseObject(healthJson);
                var current = GetNumber(health, "current", 0f);
                var max = GetNumber(health, "max", 0f);
                healthText = max > 0f ? string.Format(" {0:0}/{1:0}", current, max) : string.Format(" {0:0}", current);
            }

            var label = go.GetComponentInChildren<TextMesh>();
            if (label != null)
                label.text = (string.IsNullOrEmpty(actorId) ? marker.EntityId.ToString() : actorId) + healthText;
        }

        private static void ApplyTransform(Transform transform, string json)
        {
            var data = ParseObject(json);
            var position = GetObject(data, "position");
            var rotation = GetObject(data, "rotation");
            var scale = GetObject(data, "scale");

            if (position != null)
                transform.localPosition = new Vector3(GetNumber(position, "x", 0f), GetNumber(position, "y", 0f), GetNumber(position, "z", 0f));
            else if (HasAnyKey(data, "position_x", "position_y", "position_z"))
                transform.localPosition = new Vector3(
                    GetNumber(data, "position_x", transform.localPosition.x),
                    GetNumber(data, "position_y", transform.localPosition.y),
                    GetNumber(data, "position_z", transform.localPosition.z));
            if (rotation != null)
                transform.localRotation = new Quaternion(GetNumber(rotation, "x", 0f), GetNumber(rotation, "y", 0f), GetNumber(rotation, "z", 0f), GetNumber(rotation, "w", 1f));
            else if (HasAnyKey(data, "rotation_x", "rotation_y", "rotation_z", "rotation_w"))
                transform.localRotation = new Quaternion(
                    GetNumber(data, "rotation_x", transform.localRotation.x),
                    GetNumber(data, "rotation_y", transform.localRotation.y),
                    GetNumber(data, "rotation_z", transform.localRotation.z),
                    GetNumber(data, "rotation_w", transform.localRotation.w));
            if (scale != null)
                transform.localScale = new Vector3(GetNumber(scale, "x", 1f), GetNumber(scale, "y", 1f), GetNumber(scale, "z", 1f));
            else if (HasAnyKey(data, "scale_x", "scale_y", "scale_z"))
                transform.localScale = new Vector3(
                    GetNumber(data, "scale_x", transform.localScale.x),
                    GetNumber(data, "scale_y", transform.localScale.y),
                    GetNumber(data, "scale_z", transform.localScale.z));
        }

        private void EnsureSceneRoot()
        {
            if (sceneRoot != null)
                return;

            var root = new GameObject("XACE Scene");
            sceneRoot = root.transform;
            sceneRoot.SetParent(transform, false);
            sceneRoot.localPosition = Vector3.zero;
            sceneRoot.localRotation = Quaternion.identity;
            sceneRoot.localScale = Vector3.one;
        }

        private string ResolveActorId(XaceEntityState state)
        {
            if (!string.IsNullOrWhiteSpace(state.actor_id))
                return state.actor_id.Trim();
            return ResolveActorId("", state.components);
        }

        private static string ResolveActorId(string fallback, SortedDictionary<uint, string> components)
        {
            if (components != null && components.TryGetValue(IdentityComponent, out var identityJson))
            {
                var identity = ParseObject(identityJson);
                var name = GetString(identity, "entity_name", "");
                if (!string.IsNullOrWhiteSpace(name))
                    return name.Trim();
                var type = GetString(identity, "entity_type", "");
                if (!string.IsNullOrWhiteSpace(type))
                    return type.Trim();
            }
            return fallback ?? "";
        }

        private void ApplyDebugMaterial(GameObject go, string actorId)
        {
            var renderer = go.GetComponentInChildren<Renderer>();
            if (renderer == null)
                return;
            var lower = (actorId ?? "").ToLowerInvariant();
            if (lower.Contains("player") && playerMaterial != null)
                renderer.sharedMaterial = playerMaterial;
            else if ((lower.Contains("zombie") || lower.Contains("enemy")) && zombieMaterial != null)
                renderer.sharedMaterial = zombieMaterial;
            else if (neutralMaterial != null)
                renderer.sharedMaterial = neutralMaterial;
        }

        private static void EnsureLabel(GameObject go)
        {
            if (go.GetComponentInChildren<TextMesh>() != null)
                return;
            var labelObject = new GameObject("XACE Label");
            labelObject.transform.SetParent(go.transform, false);
            labelObject.transform.localPosition = new Vector3(0f, 1.25f, 0f);
            var text = labelObject.AddComponent<TextMesh>();
            text.anchor = TextAnchor.MiddleCenter;
            text.alignment = TextAlignment.Center;
            text.characterSize = 0.12f;
            text.fontSize = 48;
        }

        private void CollectAnimationFeedback()
        {
            foreach (var pair in entityMap)
            {
                var marker = pair.Value != null ? pair.Value.GetComponent<XaceEntityMarker>() : null;
                var animator = marker != null ? marker.GetComponentInChildren<Animator>() : null;
                if (animator == null || animator.layerCount == 0)
                    continue;

                var layers = new List<object>();
                var times = new List<object>();
                for (var layer = 0; layer < animator.layerCount; layer++)
                {
                    layers.Add(animator.GetLayerName(layer));
                    times.Add(animator.GetCurrentAnimatorStateInfo(layer).normalizedTime % 1f);
                }

                EnqueueFeedback("AnimationStateUpdate", pair.Key, new SortedDictionary<string, object>(StringComparer.Ordinal)
                {
                    ["entity_id"] = pair.Key,
                    ["generated_frame"] = generatedFrame,
                    ["is_transitioning"] = animator.IsInTransition(0),
                    ["active_state_per_layer"] = layers,
                    ["normalized_time_per_layer"] = times
                });
            }
        }

        private void CollectPhysicsFeedback()
        {
            foreach (var pair in entityMap)
            {
                var body = pair.Value != null ? pair.Value.GetComponent<Rigidbody>() : null;
                if (body == null || !body.IsSleeping())
                    continue;

                var t = pair.Value.transform;
                EnqueueFeedback("PhysicsSettled", pair.Key, new SortedDictionary<string, object>(StringComparer.Ordinal)
                {
                    ["entity_id"] = pair.Key,
                    ["generated_frame"] = generatedFrame,
                    ["final_position_json"] = VectorJson(t.position),
                    ["final_rotation_json"] = QuaternionJson(t.rotation)
                });
            }
        }

        private void EnqueueFeedback(string feedbackType, ulong entityId, SortedDictionary<string, object> payload)
        {
            var feedback = new SortedDictionary<string, object>(StringComparer.Ordinal)
            {
                ["feedback_type"] = feedbackType,
                ["entity_id"] = entityId,
                ["generated_frame"] = generatedFrame,
                ["payload_json"] = XaceJson.Serialize(payload)
            };
            feedbackQueue.Add(new Dictionary<string, object>(feedback));
        }

        private void FlushFeedback()
        {
            if (feedbackQueue.Count == 0)
                return;

            foreach (var feedback in feedbackQueue)
                OnFeedbackReady?.Invoke(feedback);

            if (sendFeedbackToRuntime && transport != null)
            {
                var batch = new SortedDictionary<string, object>(StringComparer.Ordinal)
                {
                    ["msg_type"] = "feedback_payload",
                    ["tick"] = currentTick,
                    ["messages"] = new List<object>(feedbackQueue)
                };
                transport.SendDictionaryImmediately(batch);
            }

            feedbackQueue.Clear();
        }

        private static Dictionary<string, object> ParseObject(string json)
        {
            return XaceJson.DeserializeObject(json) ?? new Dictionary<string, object>();
        }

        private static Dictionary<string, object> GetObject(Dictionary<string, object> obj, string key)
        {
            return XaceJsonValue.Get(obj, key) as Dictionary<string, object>;
        }

        private static string GetString(Dictionary<string, object> obj, string key, string fallback)
        {
            var value = XaceJsonValue.Get(obj, key);
            return value == null ? fallback : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
        }

        private static float GetNumber(Dictionary<string, object> obj, string key, float fallback)
        {
            var value = XaceJsonValue.Get(obj, key);
            if (value == null)
                return fallback;
            try { return Convert.ToSingle(value, System.Globalization.CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        private static bool HasAnyKey(Dictionary<string, object> obj, params string[] keys)
        {
            if (obj == null || keys == null)
                return false;
            foreach (var key in keys)
            {
                if (!string.IsNullOrEmpty(key) && obj.ContainsKey(key))
                    return true;
            }
            return false;
        }

        private static string VectorJson(Vector3 v)
        {
            return string.Format(System.Globalization.CultureInfo.InvariantCulture, "{{\"x\":{0:R},\"y\":{1:R},\"z\":{2:R}}}", v.x, v.y, v.z);
        }

        private static string QuaternionJson(Quaternion q)
        {
            return string.Format(System.Globalization.CultureInfo.InvariantCulture, "{{\"x\":{0:R},\"y\":{1:R},\"z\":{2:R},\"w\":{3:R}}}", q.x, q.y, q.z, q.w);
        }
    }

    public sealed class XaceEntityMarker : MonoBehaviour
    {
        public ulong EntityId;
        public string ActorId;
        public int ControllerId;

        private readonly SortedDictionary<uint, string> componentData = new SortedDictionary<uint, string>();
        private readonly List<XacePlaybackCommand> playbackCommands = new List<XacePlaybackCommand>();

        public void SetComponents(SortedDictionary<uint, string> components)
        {
            componentData.Clear();
            if (components == null)
                return;
            foreach (var pair in components)
                componentData[pair.Key] = pair.Value;
        }

        public bool TryGetComponentData(uint typeId, out string json)
        {
            return componentData.TryGetValue(typeId, out json);
        }

        public IReadOnlyList<XacePlaybackCommand> PlaybackCommands => playbackCommands;

        public void ClearPlaybackCommands()
        {
            playbackCommands.Clear();
        }

        public void RecordPlaybackCommand(XacePlaybackCommand command)
        {
            if (command == null)
                return;
            playbackCommands.Add(command);
            while (playbackCommands.Count > 32)
                playbackCommands.RemoveAt(0);
        }
    }
}

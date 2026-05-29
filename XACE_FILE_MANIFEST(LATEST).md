# XACE COMPLETE FILE MANIFEST
# Version: Post-Audit v2 (Audits 1–9 Integrated)
# Derived from: MASTER_PLAN (latest).md + Final Claude.md
# Status: SINGLE SOURCE OF TRUTH — Retire all previous manifest versions
# Total Files: ~570 (up from ~345 pre-audit)

---

## HOW TO USE THIS DOCUMENT

This manifest defines every file that must exist in XACE before it becomes a platform-level system.
Pre-defining filenames is an architectural act — it prevents Claude Code from collapsing your platform into a small tool.

**Language Assignment per Package**

| Package | Language | Phases |
|---|---|---|
| packages/core | Rust (.rs) | 1, 7 |
| packages/dcl | Python (.py) | 1 |
| packages/runtime-core | Rust (.rs) | 2–6 |
| packages/system-graph-compiler | Rust (.rs) | 10 |
| packages/schema-factory | Python (.py) | 11 |
| packages/gde | Python (.py) | 12 |
| packages/engine-adapter | Rust (.rs) | 7–8 |
| packages/engine-feedback | Rust (.rs) | 7 (Audit 6) |
| packages/asset-registry | Python (.py) | 7 (Audit 2) |
| packages/prompt-intelligence | Python (.py) | 13 |
| packages/inference | Python (.py) | 13.16 (Audit 8) |
| packages/builder-workspace | TypeScript (.ts/.tsx) | 14 |
| packages/network-core | Mixed (.rs/.py) | 15 (Audit 5) |
| packages/save-engine | Mixed (.rs/.py) | 16 (Audit 7) |
| packages/game-genesis-engine | Python (.py) | 16 (Audit 4) |
| packages/natural-language-translation | Python (.py) | 16 (Audit 4) |
| packages/design-mentor | Python (.py) | 16 (Audit 4) |
| adapters/unity | C# (.cs) | 7 |
| adapters/unreal | C++ (.cpp/.h) | 7 |
| adapters/godot | GDScript or C# | 7 |
| tests/determinism | Rust (.rs) | 3–9 |
| tests/unit + integration | Mixed | All phases |
| docs/ | Markdown (.md) | Cross-cutting |

**Rust Crate Structure Note**

Every Rust package needs a `lib.rs` at its crate root and a `mod.rs` in each subfolder to expose modules. These are scaffold files — Claude Code creates them automatically when you run `cargo new --lib`. They contain only `pub mod xyz;` declarations, no logic. They are NOT counted in the file totals below.

---

## CRITICAL CHANGES FROM PREVIOUS MANIFEST

1. **UCL frozen at 10 components** (Audit 1). Old manifest listed 25 UCL components — 15 have been moved to DCL domains.
2. **DCL is now 10 domain packages** (Audit 1). All domain components live in `packages/dcl/`, versioned and extensible.
3. **AssetReference is a typed struct everywhere** (Audit 2). Never a raw String. New `packages/asset-registry/` added.
4. **COMP_ANIMATION_V2** replaces V1 (Audit 3). Lives in `dcl/character/` with layers, pending_events, IK fields.
5. **Engine Feedback Protocol** is bidirectional (Audit 6). New `packages/engine-feedback/` with 10 feedback types.
6. **Save/Load/Persistence** expanded to 3 layers (Audit 7). New `packages/save-engine/`.
7. **Inference Package is a hard boundary** (Audit 8). New `packages/inference/` — all LLM calls go through `inference_adapter.py`. No direct HTTP anywhere in PIL.
8. **Context Assembly capped** (Audit 9). 8K dynamic token hard cap. Static sections in cached prefix.
9. **Diagnostic Orchestrator** added (Audit 9). Routes explain/debug prompts through 2-pass path, NOT the 5-pass mutation pipeline.
10. **Zero-Experience Layer** fully specified (Audit 4). 30 genre templates across `packages/game-genesis-engine/`, `packages/natural-language-translation/`, `packages/design-mentor/`.
11. **Network Core** detailed (Audit 5). Lockstep + rollback, cheat guard always on.

---

## PROJECT SIZE SUMMARY

| Package / Module | Files | ~Lines | Build Phases | Language |
|---|---|---|---|---|
| **packages/core** | **42** | ~5,500 | Phase 1, 7 | Rust |
| **packages/dcl** | **58** | ~5,800 | Phase 1 | Python |
| **packages/runtime-core** | **37** | ~4,800 | Phases 2–6 | Rust |
| **packages/system-graph-compiler** | **22** | ~3,500 | Phase 10 | Rust |
| **packages/schema-factory** | **20** | ~3,200 | Phase 11 | Python |
| **packages/gde** | **33** | ~5,800 | Phase 12 | Python |
| **packages/engine-adapter** | **15** | ~3,000 | Phases 7–8 | Rust |
| **packages/engine-feedback** | **18** | ~2,200 | Phase 7 (Audit 6) | Rust |
| **packages/asset-registry** | **18** | ~2,400 | Phase 7 (Audit 2) | Python |
| **packages/prompt-intelligence** | **59** | ~9,200 | Phase 13 | Python |
| **packages/inference** | **25** | ~4,500 | Phase 13.16 (Audit 8) | Python |
| **packages/builder-workspace** | **35** | ~6,000 | Phase 14 | TypeScript |
| **packages/network-core** | **29** | ~4,200 | Phase 15 (Audit 5) | Mixed |
| **packages/save-engine** | **16** | ~2,400 | Phase 16 (Audit 7) | Mixed |
| **packages/game-genesis-engine** | **43** | ~5,500 | Phase 16 (Audit 4) | Python |
| **packages/natural-language-translation** | **17** | ~2,800 | Phase 16 (Audit 4) | Python |
| **packages/design-mentor** | **15** | ~2,200 | Phase 16 (Audit 4) | Python |
| **adapters/unity** | **4** | ~800 | Phase 7 | C# |
| **adapters/unreal** | **4** | ~800 | Phase 7 | C++ |
| **adapters/godot** | **4** | ~600 | Phase 7 | GDScript |
| **tests/determinism** | **14** | ~2,200 | Phases 3–9 | Rust |
| **tests/unit + integration** | **~80** | ~12,000 | All phases | Mixed |
| **docs/** | **12** | ~3,000 | Cross-cutting | Markdown |
| **TOTAL** | **~571** | **~84,200+** | **Phases 1–16** | **Multi-language** |

---

## AUDIT DECISIONS LOCKED (Reference Before Building Any File)

- **Audit 1 — Component Architecture:** UCL = 10 frozen. DCL = 10 domain packages, XACE-owned. GCL = developer-owned in game project.
- **Audit 2 — Asset Pipeline:** AssetReference typed struct, 4 states (PLACEHOLDER/LINKED/MISSING/UNRESOLVED), auto-naming convention, Animation Contract generated from COMP_ANIMATION_V2.
- **Audit 3 — Animation Depth:** COMP_ANIMATION_V2 with layers dict + pending_events list. COMP_IK_V1 in dcl/character/. AnimationEventSystem in Rust.
- **Audit 4 — Zero-Experience User:** Game Genesis Engine + NLTL + Design Mentor. 30 genre templates. All Phase 16.
- **Audit 5 — Multiplayer:** Lockstep + rollback (auto-selected by game type). InputSynchroniser lockstep gate. Cheat guard ALWAYS ON all modes. Phase 15.
- **Audit 6 — Engine Feedback:** Bidirectional XACE-Engine. 10 feedback message types. Feedback enters XACE at tick boundaries only. Visibility queries one-tick delayed.
- **Audit 7 — Save/Load/Persistence:** 3-layer save (game progress, player profile, schema version). 4 new DCL persistence components. Schema migration on load. Cloud sync abstraction.
- **Audit 8 — AI Inference Pipeline:** `packages/inference/` built BEFORE other Phase 13 files. All LLM calls through `inference_adapter.py`. TIER_S routed to deterministic Phase 12 path. Code generation retry hard-capped at 2. No BYOK before beta.
- **Audit 9 — Context Assembly:** 8K dynamic token hard cap. dependency_expander capped to 1-hop reads, 2-hop writes. Static sections in cached prefix via prompt_cache. Diagnostic prompts routed through 2-pass diagnostic_orchestrator, NOT 5-pass mutation pipeline.

---

## packages/core — Shared Types & Contracts [RUST]

The foundation layer. Every other module imports from here. Define these perfectly before touching any other package.

**Total files in this module: 42**

### Entity & Identity Types

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| entity_id.rs | EntityID type alias (64-bit int), ID generation counter, never-reuse guarantee | **60** | **1** |
| entity_state.rs | EntityState enum: Active \| Disabled \| DestroyRequested \| Destroyed \| Archived | **40** | **1** |
| entity_metadata.rs | EntityMetadata struct: id, state, created_tick, destroyed_tick, tags snapshot | **70** | **1** |

### UCL v1 — 10 Components Only (FROZEN FOREVER)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| ucl/transform_component.rs | COMP_TRANSFORM_V1 — position(x,y,z), rotation(x,y,z,w), scale(x,y,z), parent_entity_id | **90** | **1** |
| ucl/identity_component.rs | COMP_IDENTITY_V1 — entity_name, entity_type enum, faction, tags[], prefab_id, is_runtime_spawned | **90** | **1** |
| ucl/render_component.rs | COMP_RENDER_V1 — render_type, asset_reference (AssetReference typed struct), material_ref, visible, cast_shadows, layer, render_order, lod_group | **100** | **1** |
| ucl/collider_component.rs | COMP_COLLIDER_V1 — shape enum, size, offset, is_trigger, layer_mask, physics_material_id | **100** | **1** |
| ucl/velocity_component.rs | COMP_VELOCITY_V1 — linear(x,y,z), angular(x,y,z), max_linear_speed, max_angular_speed | **75** | **1** |
| ucl/input_component.rs | COMP_INPUT_V1 — controller_id, control_type enum (HUMAN/AI_PROXY/NETWORK_REMOTE), input_profile_id, is_enabled | **85** | **1** |
| ucl/event_component.rs | COMP_EVENT_V1 — event_type, payload dict, is_consumed, emitted_tick, target_entity_id | **75** | **1** |
| ucl/lifetime_component.rs | COMP_LIFETIME_V1 — max_lifetime_ticks, current_lifetime_ticks, on_expire_action enum | **65** | **1** |
| ucl/game_state_component.rs | COMP_GAMESTATE_V1 — current_phase enum, score, time_elapsed_ticks, active_mode_id, match_state | **90** | **1** |
| ucl/authority_component.rs | COMP_AUTHORITY_V1 — prediction_enabled, reconciliation_mode SNAP\|INTERPOLATE, sync_rate_divisor, is_replicated, authority_type, owner_peer_id | **75** | **1** |
| ucl/ucl_registry.rs | UCL v1 registry — maps ComponentTypeID → schema definition, validates type IDs, frozen set enforcement (10 components only) | **120** | **1** |

### Asset Reference Types (Audit 2)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| assets/asset_reference.rs | AssetReference struct — id + asset_type + status. Typed struct everywhere, NEVER a raw String | **80** | **1** |
| assets/asset_type_enum.rs | AssetType enum — MESH\|TEXTURE\|MATERIAL\|ANIMATION_CONTROLLER\|AUDIO_CLIP\|AUDIO_MUSIC\|SPRITE\|PARTICLE\|PREFAB\|FONT | **40** | **1** |
| assets/asset_status_enum.rs | AssetStatus enum — PLACEHOLDER\|LINKED\|MISSING\|UNRESOLVED | **40** | **1** |

### Schema Types

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| schema/canonical_game_schema.rs | CGS struct — metadata, global_systems, modes[], cgs_version, cgs_hash, created_at | **150** | **1** |
| schema/game_mode.rs | GameMode struct — id, description, world, actors[], systems[], rules[], ui | **100** | **1** |
| schema/world_definition.rs | WorldDefinition — map_type, environment_type, size, physics_profile, time_system, gravity | **80** | **1** |
| schema/actor_definition.rs | ActorDefinition — id, actor_type enum, components[], stats, abilities[], control_type, prefab_id | **110** | **1** |
| schema/system_definition.rs | SystemDefinition — id, phase enum, reads[], writes[], depends_on[], deterministic flag, version | **90** | **1** |
| schema/rule_definition.rs | RuleDefinition — id, condition expression, effect expression, priority, is_active, mode_scope | **100** | **1** |

### Mutation Types

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| mutation/mutation_transaction.rs | MutationTransaction — id(UUID), operations[], atomic bool, metadata, schema_version_target | **110** | **1** |
| mutation/dsl_operation.rs | DSLOperation — op enum (SET/ADD/REMOVE/MULTIPLY/DIVIDE/APPEND/DELETE), target path, value, type_hint | **80** | **1** |
| mutation/schema_delta.rs | SchemaDelta — version_before, version_after, operations[], timestamp, source, cgs_hash_after | **90** | **1** |
| mutation/usmc_categories.rs | USMC enum — Create\|Modify\|Remove\|Constrain\|Compose\|ProgressionDefine\|EnvironmentDefine\|Interaction | **60** | **1** |

### Runtime Types

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| runtime/execution_plan.rs | ExecutionPlan — phases[], schema_version, plan_version, created_tick, hash | **90** | **1** |
| runtime/phase_enum.rs | PhaseEnum — Initialization\|Input\|Simulation\|PostSimulation\|Cleanup — immutable fixed order | **40** | **1** |
| runtime/execution_group.rs | ExecutionGroup — parallel bool, systems[], group_id, phase, serialization_constraints | **70** | **1** |
| runtime/world_snapshot.rs | WorldSnapshot — full struct: tick, schema_version, entity_store_snapshot, component_tables_snapshot, rng_state, event_queue_state | **180** | **1** |
| runtime/state_delta.rs | StateDelta — tick, created_entities[], destroyed_entities[], updated_components[], added_components[], removed_components[] | **90** | **1** |

### Event Types

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| events/event_type.rs | EventType enum — all domains including ANIMATION_EVENT_FIRED, PHYSICS_SETTLED, AUDIO_COMPLETE (30+ event types) | **100** | **1** |
| events/event_struct.rs | Event struct — event_id, tick, phase, type, source_entity_id, target_entity_id, payload (serializable only) | **80** | **1** |

### Wire Protocol Types

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| wire/wire_message.rs | WireMessage envelope — protocol_version, world_id, schema_version, execution_plan_version, tick, sequence_id, message_type, payload | **90** | **7** |
| wire/message_type.rs | MessageType enum — SNAPSHOT\|DELTA\|INPUT\|EVENT\|CONTROL\|FEEDBACK | **30** | **7** |
| wire/delta_payload.rs | DeltaPayload — created_entities[], destroyed_entities[], updated_components[], ordering enforced | **80** | **7** |
| wire/snapshot_payload.rs | SnapshotPayload — full world state for initial connection or desync recovery | **90** | **7** |
| wire/feedback_payload.rs | Engine feedback message wrapper — 10 feedback types batched (new per Audit 6) | **80** | **7** |

### Error Types

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| errors/xace_error.rs | XaceError base + subclasses: FatalError, RecoverableError, ValidationFailure, ClarificationRequired, RetryableLLMFailure, SaveMigrationRequired (Audit 7), NetworkDesyncError (Audit 5) | **100** | **1** |
| errors/determinism_error.rs | DeterminismViolation — rule_id (D1–D15), system_context, tick, expected_hash, actual_hash | **80** | **1** |

### Contracts

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| contracts/interfaces.rs | All module boundary interfaces: ISystem, IMutationGate, IEntityStore, IComponentTable, ISnapshotEngine, IEventBus, IDeterminismGuard, IEngineAdapter (with receive_feedback_batch() and send_visibility_queries()), ISaveEngine | **200** | **1** |

---

## packages/dcl — Domain Component Library [PYTHON]

10 domain packages. Versioned & extensible. XACE-owned. Game project declares domains in game_config.yaml. Assembled at game load with UCL + GCL into CompositeComponentRegistry.

**Total files in this module: 58**

### Registry & Loader

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| dcl_registry.py | CompositeComponentRegistry — assembles core + domains + GCL at game load. Validates against full composite set, not just UCL | **150** | **1** |
| dcl_loader.py | Loads DCL domains from game_config.yaml | **120** | **1** |
| domain_package.py | DomainPackage struct — name, version, components[], dependencies[] | **80** | **1** |
| gcl_loader.py | Loads GCL from game project gcl/ folder | **100** | **1** |
| gcl_validator.py | Validates GCL — no name collision with UCL/DCL, valid field types, no engine-specific types | **130** | **1** |

### dcl/combat/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| combat/health_component.py | COMP_HEALTH_V1 — current, max, regen_rate, is_invincible, death_behavior enum, last_damage_tick | **95** | **1** |
| combat/damage_component.py | COMP_DAMAGE_V1 — damage_type enum, amount, source_entity_id, applied_tick, is_consumed | **80** | **1** |
| combat/hitbox_component.py | COMP_HITBOX_V1 — shape, size, offset, filter_tags[], damage_multiplier, is_active | **85** | **1** |
| combat/shield_component.py | COMP_SHIELD_V1 — current, max, regen_rate, damage_type_vulnerabilities[], is_active | **90** | **1** |
| combat/status_effect_component.py | COMP_STATUS_EFFECT_V1 — active_effects[], duration_ticks, potency, source_entity_id | **85** | **1** |

### dcl/character/ Domain (Audit 3)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| character/movement_intent_component.py | COMP_MOVEMENT_INTENT_V1 — direction(x,y,z), sprint_requested, jump_requested, crouch_requested | **70** | **1** |
| character/animation_component.py | COMP_ANIMATION_V2 — controller_ref(AssetReference), playback_speed, layers dict, parameters dict, blend_parameters dict, pending_events list, ik_enabled, engine feedback fields (current_normalized_time, is_transitioning, active_state_per_layer) | **140** | **1** |
| character/ik_component.py | COMP_IK_V1 — ik_mode, look_at_target, hand/foot targets, carry_ik_preset (DRAG_BY_FEET\|CARRY_OVER_SHOULDER\|FIREMAN_CARRY\|TWO_HAND_CARRY), solve_order | **110** | **1** |
| character/carry_component.py | COMP_CARRY_V1 — carried_entity_id, carry_state, weight_factor, drop_on_damage | **75** | **1** |
| character/ragdoll_component.py | COMP_RAGDOLL_V1 — is_ragdolled, bone_states[], recovery_timer, recovery_animation_ref | **80** | **1** |

### dcl/physics/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| physics/rigidbody_component.py | COMP_RIGIDBODY_V1 — mass, drag, angular_drag, use_gravity, is_kinematic, freeze_constraints | **95** | **1** |
| physics/surface_properties_component.py | COMP_SURFACE_PROPERTIES_V1 — friction, bounciness, surface_type enum, audio_material | **80** | **1** |
| physics/buoyancy_component.py | COMP_BUOYANCY_V1 — water_level, buoyancy_force, drag_in_water, is_submerged | **75** | **1** |
| physics/soft_body_component.py | COMP_SOFT_BODY_V1 — stiffness, damping, pressure, anchor_points[], mesh_deformation_enabled | **85** | **1** |

### dcl/ai/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| ai/ai_component.py | COMP_AI_V1 — behavior_model enum, current_state, target_entity_id, detection_radius, aggression_level, memory{} | **120** | **1** |
| ai/patrol_component.py | COMP_PATROL_V1 — waypoints[], current_index, patrol_mode (LOOP\|PING_PONG\|ONCE), wait_ticks | **85** | **1** |
| ai/perception_component.py | COMP_PERCEPTION_V1 — visibility_query_pending flag (Audit 6), detected_entities[], last_sensed_tick, suspicion_level | **90** | **1** |
| ai/crowd_agent_component.py | COMP_CROWD_AGENT_V1 — lightweight Logic LOD for large crowds: desired_velocity, neighbor_radius, separation_weight | **70** | **1** |

### dcl/stealth/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| stealth/stealth_component.py | COMP_STEALTH_V1 — visibility_level, noise_level, light_level, is_detected, detection_memory[] | **85** | **1** |
| stealth/disguise_component.py | COMP_DISGUISE_V1 — active_disguise_id, suspicion_multiplier, disguise_entities[], is_wearing | **80** | **1** |
| stealth/detection_component.py | COMP_DETECTION_V1 — detection_angle, detection_range, hearing_radius, alert_level, last_known_position | **90** | **1** |

### dcl/rpg/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| rpg/stats_component.py | COMP_STATS_V1 — speed, strength, defense, agility, base_values{}, current_values{}, modifiers[] | **110** | **1** |
| rpg/inventory_component.py | COMP_INVENTORY_V1 — slots[], max_capacity, current_count, item_ids[], equipped_slot | **100** | **1** |
| rpg/ability_component.py | COMP_ABILITY_V1 — abilities[], cooldowns[], active_ability_id, cast_time_ticks | **95** | **1** |
| rpg/progression_component.py | COMP_PROGRESSION_V1 — level, experience, skill_points, unlocked_abilities[], progression_tree_id | **90** | **1** |
| rpg/economy_component.py | COMP_ECONOMY_V1 — currency{}, transaction_history[], shop_multiplier, debt | **85** | **1** |

### dcl/world/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| world/spawner_component.py | COMP_SPAWNER_V1 — blueprint_id, spawn_rate_ticks, max_count, current_count, spawn_radius, is_active | **90** | **1** |
| world/triggerzone_component.py | COMP_TRIGGERZONE_V1 — shape, dimensions, filter_tags[], on_enter_action, on_exit_action, is_active | **90** | **1** |
| world/persistence_component.py | COMP_PERSISTENCE_V1 — save_key, auto_save, data_schema_id, last_saved_tick, is_dirty | **80** | **1** |
| world/worldstreaming_component.py | COMP_WORLDSTREAMING_V1 — chunk_id, load_radius, priority, is_loaded, streaming_state enum | **75** | **1** |
| world/environment_component.py | COMP_ENVIRONMENT_V1 — time_of_day, weather_state, gravity_override, ambient_light_color | **85** | **1** |
| world/destructible_component.py | COMP_DESTRUCTIBLE_V1 — health_segments[], destruction_stages[], destroyed_state_prefab, debris_entity_ids[] | **95** | **1** |

### dcl/interaction/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| interaction/interaction_component.py | COMP_INTERACTION_V1 — interaction_type enum, range, is_interactable, required_tag, prompt_text | **85** | **1** |
| interaction/dialogue_component.py | COMP_DIALOGUE_V1 — dialogue_tree_id, current_node_id, available_responses[], speaker_entity_id | **90** | **1** |
| interaction/puzzle_component.py | COMP_PUZZLE_V1 — puzzle_state, required_items[], solution_steps[], is_solved, reward_entity_id | **85** | **1** |
| interaction/usable_component.py | COMP_USABLE_V1 — use_type enum, charges, max_charges, cooldown_ticks, is_consumed_on_use | **80** | **1** |

### dcl/camera/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| camera/camera_component.py | COMP_CAMERA_V1 — mode enum, fov, near/far_clip, follow_target, offset, rotation_lock, smoothing, active | **110** | **1** |
| camera/camera_shake_component.py | COMP_CAMERA_SHAKE_V1 — intensity, duration_ticks, frequency, trauma, decay_rate | **75** | **1** |
| camera/cinematic_component.py | COMP_CINEMATIC_V1 — cinematic_id, current_shot, playback_mode, skippable, target_entities[] | **85** | **1** |

### dcl/audio/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| audio/audio_emitter_component.py | COMP_AUDIO_EMITTER_V1 — clip_ref(AssetReference), volume, pitch, loop, 3d_position, attenuation_radius | **90** | **1** |
| audio/audio_listener_component.py | COMP_AUDIO_LISTENER_V1 — active, listener_entity_id, occlusion_enabled, reverb_zone_id | **70** | **1** |
| audio/music_state_component.py | COMP_MUSIC_STATE_V1 — current_track_ref, intensity_value (driven by distance), transition_ticks, crossfade_enabled | **85** | **1** |
| audio/audio_zone_component.py | COMP_AUDIO_ZONE_V1 — zone_shape, reverb_preset, priority, ducking_factor, affected_emitters[] | **80** | **1** |

### dcl/network/ Domain (Audit 5)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| network/replication_component.py | COMP_REPLICATION_V1 — replication_mode, priority, last_replicated_tick, dirty_flags[] | **85** | **1** |
| network/network_transform_component.py | COMP_NETWORK_TRANSFORM_V1 — last_known_position, interpolation_target, extrapolation_velocity, network_timestamp | **90** | **1** |
| network/player_session_component.py | COMP_PLAYER_SESSION_V1 — peer_id, session_state, latency_ms, input_sequence_id, authority_level | **85** | **1** |

### dcl/ui/ Domain

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| ui/ui_element_component.py | COMP_UI_ELEMENT_V1 — element_type, position, size, anchor, visibility, z_order, style_id | **85** | **1** |
| ui/hud_binding_component.py | COMP_HUD_BINDING_V1 — target_entity_id, bound_stat, display_mode, refresh_rate_ticks, alert_threshold | **80** | **1** |
| ui/minimap_component.py | COMP_MINIMAP_V1 — zoom_level, tracked_entities[], fog_of_war_enabled, map_texture_ref | **75** | **1** |

### dcl/persistence/ Domain (Audit 7)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| persistence/save_slot_component.py | COMP_SAVE_SLOT_V1 — slot_id, schema_version field, created_at, last_played, play_time_ticks | **85** | **1** |
| persistence/checkpoint_component.py | COMP_CHECKPOINT_V1 — checkpoint_type (MANUAL\|AUTO\|STORY\|RESPAWN), world_state_hash, respawn_position | **90** | **1** |
| persistence/player_profile_component.py | COMP_PLAYER_PROFILE_V1 — profile_id, display_name, achievements[], settings{}, total_play_time | **95** | **1** |
| persistence/cloud_sync_component.py | COMP_CLOUD_SYNC_V1 — provider (STEAM\|EPIC\|PSN\|XBOX\|CUSTOM\|NONE), last_sync_tick, sync_state | **85** | **1** |

### DCL Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_dcl_registry.py | Domain loading, composite assembly, GCL validation | **180** | **1** |
| tests/test_gcl_loader.py | Valid GCL loads, name collision rejection, invalid type rejection | **150** | **1** |
| tests/test_domain_isolation.py | Game using only dcl-combat cannot access dcl-rpg components | **140** | **1** |

---

## packages/runtime-core — ECS Runtime Engine [RUST]

The deterministic simulation engine. Tick-driven, not frame-driven. Build phases 2–6 entirely here before touching anything else.

**Total files in this module: 37**

### Entity Store

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| entity_store/entity_store.rs | EntityStore — create_entity(), destroy_entity(), exists(), get_all_alive() sorted by EntityID ASC (D3) | **180** | **2** |
| entity_store/entity_id_generator.rs | Monotonic 64-bit ID generator — never reuses IDs, archived ID registry, thread-safe increment | **80** | **2** |
| entity_store/entity_archive.rs | Archive of destroyed entity IDs — permanently reserved, used for replay integrity and network determinism | **70** | **2** |
| entity_store/tests/test_entity_store.rs | Tests: create/destroy/exists/sort-order/id-uniqueness/archive behavior | **150** | **2** |

### Component Tables

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| component_tables/component_table.rs | Single ComponentTable — rows: BTreeMap<EntityID→ComponentData>, add/remove/get/set/iterate deterministically | **160** | **2** |
| component_tables/component_table_store.rs | ComponentTableStore — Map<ComponentTypeID→ComponentTable>, factory, bulk snapshot, version metadata | **140** | **2** |
| component_tables/sorted_entity_map.rs | Deterministic sorted map guaranteeing EntityID-ordered iteration — core of determinism rule D3 | **120** | **2** |
| component_tables/tests/test_component_tables.rs | Tests: add/remove/get/iteration-order/sort-determinism/snapshot consistency | **180** | **2** |

### Query Engine

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| query_engine/query_engine.rs | Intersection queries — query(component_types[]) → sorted EntityID[], always deterministic output | **140** | **2** |
| query_engine/query_cache.rs | Query result caching — invalidation on component add/remove, per-component-type dirty flags | **110** | **2** |
| query_engine/tests/test_query_engine.rs | Tests: single/multi-component queries, empty results, tag filters, cache invalidation | **160** | **2** |

### Mutation Gate

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| mutation_gate/mutation_gate.rs | MutationGate — 4 deferred queues, request methods, apply_all() in enforced order (spawn→add→modify→remove→destroy) | **200** | **3** |
| mutation_gate/mutation_queue.rs | Per-type deferred mutation queues — entity_create, entity_destroy, component_add, component_remove | **120** | **3** |
| mutation_gate/mutation_validator.rs | Pre-application validation — entity existence, component type validity against CompositeComponentRegistry (not just UCL), duplicate checks | **130** | **3** |
| mutation_gate/tests/test_mutation_gate.rs | Tests: ordering enforcement, atomicity, phase-boundary-only application, direct-mutation rejection | **200** | **3** |

### Phase Orchestrator & System Executor

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| phase_orchestrator/phase_orchestrator.rs | Tick loop — drain EngineFeedbackBuffer at tick START, then for each phase: run_systems → apply_mutations → dispatch_events. Enforces phase order | **220** | **4** |
| phase_orchestrator/parallel_executor.rs | Thread-safe parallel system execution — thread-local event buffers, deterministic merge at phase end | **180** | **4** |
| phase_orchestrator/system_context.rs | SystemContext passed to each system — read/write access to stores, enforced by declared component contracts | **120** | **4** |
| phase_orchestrator/system_registry.rs | SystemRegistry — Map<SystemID→ISystem>, registration, lookup, validation against ExecutionPlan | **100** | **4** |
| phase_orchestrator/tests/test_phase_orchestrator.rs | Tests: phase order, mutation timing, system isolation, parallel safety, tick increment | **200** | **4** |

### Time Controller

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| time_controller/time_controller.rs | TimeController — fixed timestep accumulation loop, max_catchup_ticks, pause/resume, time_scale, modes: NORMAL\|REPLAY\|SCRUB\|SERVER_AUTH\|MULTIPLAYER | **200** | **4** |
| time_controller/deterministic_rng.rs | DeterministicRNG — seed=hash(world_seed, system_id, tick), reproducible sequences, blocks OS/language RNG (D6) | **130** | **4** |
| time_controller/tests/test_time_controller.rs | Tests: fixed-timestep math, pause, time_scale, spiral-of-death prevention, replay mode | **150** | **4** |

### Event Bus

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| event_bus/event_bus.rs | EventBus — phase_event_buffers, deferred dispatch (events dispatched at END of phase), phase isolation | **180** | **4** |
| event_bus/event_dispatcher.rs | Deterministic dispatch — sorts by (tick, phase, event_id), routes to subscribed systems in ExecutionPlan order | **140** | **4** |
| event_bus/event_subscription_registry.rs | SystemEventSubscription registry — maps SystemID→event_types, validates phase matching, no dynamic subscription | **100** | **4** |
| event_bus/tests/test_event_bus.rs | Tests: deferred dispatch timing, ordering determinism, cross-phase isolation, replay compatibility | **180** | **4** |

### DCL Character Animation Systems (Rust, Audit 3)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| dcl/character/animation_event_system.rs | Reads pending_events from COMP_ANIMATION_V2, fires game events at tick boundary, marks consumed | **150** | **4** |
| dcl/character/animation_layer_manager.rs | Multi-layer animation state management — layer weights, blending, additive modes | **140** | **4** |
| dcl/character/animation_state_validator.rs | Validates animation state transitions against AnimationContract — rejects invalid state changes | **120** | **4** |
| dcl/character/tests/test_animation_event_system.rs | Tests: event firing at correct normalized time, consumption, tick boundary correctness | **160** | **4** |
| dcl/character/tests/test_animation_layers.rs | Tests: layer blending math, weight normalization, additive vs override modes | **150** | **4** |

### Snapshot Engine

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| snapshot_engine/snapshot_engine.rs | take_snapshot() → WorldSnapshot, restore_snapshot() — deep copy initially, copy-on-write in v2 | **200** | **5** |
| snapshot_engine/snapshot_store.rs | SnapshotStore — Map<Tick→WorldSnapshot>, retention policy: keep-last-N or CHECKPOINT, purge logic | **130** | **5** |
| snapshot_engine/snapshot_serializer.rs | Deterministic serialization/deserialization of WorldSnapshot — stable key ordering, fixed precision | **150** | **5** |
| snapshot_engine/tests/test_snapshot_engine.rs | Tests: save/restore exact state, rollback to earlier tick, hash match after restore, retention policy | **200** | **5** |

### Determinism Guard

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| determinism_guard/determinism_guard.rs | DeterminismGuard — 6 runtime hooks, enforce all 15 D-rules, modes: STRICT(crash)\|DEV(log)\|SILENT(record) | **280** | **6** |
| determinism_guard/world_hasher.rs | Deterministic world state hash — hash(entity_store + component_tables + tick), same world = same hash | **120** | **6** |
| determinism_guard/replay_validator.rs | Replay hash comparison — expected vs actual per tick, produces ReplayDeterminismError with full context | **130** | **6** |
| determinism_guard/rng_interceptor.rs | Intercepts illegal RNG usage — blocks language-native random(), blocks OS randomness — rule D6 | **90** | **6** |
| determinism_guard/tests/test_determinism_guard.rs | Tests: each D1–D15 rule violation triggers correct error, STRICT mode halts, replay hash validation | **250** | **6** |

---

## packages/system-graph-compiler — SGC [RUST]

Converts system definitions into a deterministic ExecutionPlan. 7 submodules, each a separate compiler stage. Build after Runtime Core works.

**Total files in this module: 22**

### 7 Compiler Stages

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| graph_construction/graph_construction_layer.rs | Builds RawSystemGraph — SystemNode per system, edges by type: EXPLICIT_DEPENDENCY\|READ_AFTER_WRITE\|WRITE_AFTER_WRITE\|PHASE_ORDER | **220** | **10** |
| graph_construction/system_node.rs | SystemNode struct — system_id, phase, read_set, write_set, deterministic flag, explicit depends_on | **80** | **10** |
| graph_construction/system_edge.rs | SystemEdge struct — from_system, to_system, edge_type enum, reason description | **70** | **10** |
| graph_construction/hazard_detector.rs | Detects RAW (read-after-write) and WAW (write-after-write) hazards — WAW tie-breaking by lexicographic system_id | **150** | **10** |
| phase_segmentation/phase_segmentation_layer.rs | Partitions RawSystemGraph into PhaseBuckets — validates phase assignments, enforces global phase order, filters cross-phase edges | **180** | **10** |
| phase_segmentation/phase_validator.rs | Validates system phase declarations — SYSTEM_PHASE_UNDEFINED, INVALID_SYSTEM_PHASE, PHASE_DEPENDENCY_VIOLATION errors | **120** | **10** |
| dependency_resolution/dependency_resolution_engine.rs | Topological sort with stable tie-breaking (lexicographic system_id) — produces OrderedGraph | **200** | **10** |
| dependency_resolution/topological_sorter.rs | Kahn's algorithm implementation — deterministic, handles tie-breaks, stable across runs | **150** | **10** |
| conflict_analyzer/conflict_analyzer.rs | Detects write-write conflicts and read-write hazards — produces ConflictReport and SerializationGroups | **200** | **10** |
| conflict_analyzer/serialization_group_builder.rs | Builds groups of systems that must NOT run in parallel — feeds into scheduler | **130** | **10** |
| scheduler/deterministic_scheduler_builder.rs | Assigns execution index per system, builds parallel groups, produces ExecutionPlan v1 | **220** | **10** |
| scheduler/parallel_group_analyzer.rs | Evaluates parallel safety per group — criteria: no shared writes, no RAW hazards, no phase conflicts | **160** | **10** |
| cycle_detection/cycle_detector.rs | DFS cycle detection — hard cycles = CompilationError with full cycle path; soft cycles = phase adjustment suggestion | **170** | **10** |
| cycle_detection/cycle_diagnostics.rs | Rich cycle diagnostic output — names all systems in cycle, suggests resolution strategies | **100** | **10** |
| parallelization/parallelization_safety_model.rs | Final parallelization safety evaluation — integrates SerializationGroups, validates output ExecutionPlan groups | **140** | **10** |
| sgc_pipeline.rs | SGC entry point — orchestrates all 7 stages in order, returns ExecutionPlan or raises CompilationError | **120** | **10** |
| compilation_error.rs | SGC error types — CycleError, PhaseViolation, ConflictError, InvalidSystemDefinition with diagnostic payloads | **80** | **10** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_graph_construction.rs | Tests: edge generation for all 4 edge types, phase order edges, determinism of output graph | **180** | **10** |
| tests/test_phase_segmentation.rs | Tests: valid assignments, invalid phase names, cross-phase violations, edge filtering | **150** | **10** |
| tests/test_dependency_resolution.rs | Tests: simple chains, diamond dependencies, multi-system graphs, stable ordering verification | **180** | **10** |
| tests/test_conflict_analyzer.rs | Tests: known conflict patterns, safe parallel groups, serialization group correctness | **160** | **10** |
| tests/test_cycle_detection.rs | Tests: simple 2-node cycle, multi-node cycle, no-cycle graphs, soft cycle suggestions | **150** | **10** |

---

## packages/schema-factory — Schema Compiler [PYTHON]

Compiles CGS into a structured Compiled Schema Package. Pure transformation — no execution, no mutation authority. Validates against CompositeComponentRegistry (UCL+DCL+GCL), not just UCL.

**Total files in this module: 20**

### Factory Submodules

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| entity_blueprint/blueprint_compiler.py | Compiles CGS actors → EntityBlueprint structs — resolves component defaults, validates against UCL v1 | **180** | **11** |
| entity_blueprint/entity_blueprint.py | EntityBlueprint struct — id, component_defaults dict, tags, prefab_id, mode_scope | **80** | **11** |
| entity_blueprint/blueprint_registry.py | BlueprintRegistry — stores compiled blueprints, lookup by id or type, validate no duplicates | **100** | **11** |
| component_registry/component_definition_registry.py | ComponentDefinitionRegistry — maps ComponentTypeID→definition, validates all types against CompositeComponentRegistry (UCL+DCL+GCL), not frozen UCL only | **150** | **11** |
| component_registry/component_definition.py | ComponentDefinition struct — type_id, schema version, field_definitions[], validation_rules[], serialization_rules[] | **110** | **11** |
| system_registry/system_definition_registry.py | SystemDefinitionRegistry — maps SystemID→SystemDefinition, validates read/write declarations, phase assignments | **140** | **11** |
| system_registry/system_validator.py | Validates each system definition — components referenced exist in registry, phase is valid, no undeclared writes | **130** | **11** |
| versioning/schema_version_manager.py | MAJOR.MINOR.PATCH versioning, cgs_hash computation after each mutation, immutable snapshot chaining | **150** | **11** |
| versioning/schema_snapshot.py | Immutable CGS snapshot — version, hash, timestamp, parent_version_hash, mutation_source, DSLTransaction ref | **100** | **11** |
| diff_migration/schema_diff_engine.py | Computes structural diff between two CGS versions — added/removed/modified entities, systems, components | **180** | **11** |
| diff_migration/migration_rule_generator.py | Generates migration rules for CGS_v1→CGS_v2 upgrades — field additions, renames, removals with defaults | **160** | **11** |
| mode_composition/mode_composition_engine.py | Composes base schema with mode-specific overrides — merges global_systems with mode systems, validates isolation | **160** | **11** |
| mode_composition/mode_validator.py | Validates mode definitions — no duplicate IDs, default mode exists, required fields present, component refs valid | **120** | **11** |
| validation/schema_validation_contract.py | Full CGS validation — entity refs, system refs, no cycles, valid phases, no duplicate IDs, no orphaned components, no UNRESOLVED asset refs (I11), save schema version (I14) | **220** | **11** |
| validation/invariant_checker.py | Checks all 14 global invariants (I1–I14) — blocks commit on any violation, full diagnostic report | **180** | **11** |
| schema_factory.py | SchemaFactory entry point — orchestrates all submodules, returns CompiledSchemaPackage or raises ValidationError | **140** | **11** |
| compiled_schema_package.py | CompiledSchemaPackage struct — entity blueprints, component registry, system registry, dependency graph, version metadata | **90** | **11** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_blueprint_compiler.py | Tests: valid blueprints, invalid component refs, UCL violation detection, missing required fields | **180** | **11** |
| tests/test_schema_validation.py | Tests: all validation rules, invariant violations, partial commit rejection, full valid schema acceptance | **220** | **11** |
| tests/test_diff_migration.py | Tests: diff accuracy, migration rule generation, backward compatibility enforcement | **160** | **11** |

---

## packages/gde — Game Definition Engine [PYTHON]

The game design compiler — converts user intent into validated CGS mutations. Contains the DSL, prompt interpretation, validation, and mode profiles.

**Total files in this module: 33**

### CGS Module

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| cgs/cgs_manager.py | CGS lifecycle manager — holds current CGS, applies validated deltas, maintains snapshot chain, exposes rollback | **200** | **12** |
| cgs/mutation_target_resolver.py | Resolves fully-qualified DSL paths to CGS nodes — rejects partial/implicit paths, validates node existence | **180** | **12** |
| cgs/cgs_serializer.py | Deterministic CGS serialization — stable key order, fixed precision, produces identical output for identical state | **150** | **12** |

### Domain DSL — 5 Submodules

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| domain_dsl/usmc/usmc_classifier.py | Classifies mutation intent into USMC category — Create\|Modify\|Remove\|Constrain\|Compose\|ProgressionDefine\|EnvironmentDefine\|Interaction | **130** | **12** |
| domain_dsl/path_addressing/path_parser.py | Parses fully-qualified mutation paths — tokenizer, validator, rejects all implicit/partial paths | **150** | **12** |
| domain_dsl/path_addressing/path_resolver.py | Resolves parsed path against current CGS — returns target node reference or SchemaResolutionError | **140** | **12** |
| domain_dsl/rule_grammar/rule_expression_parser.py | Parses condition/effect rule expressions — grammar definition, AST builder, validates against component vocabulary | **200** | **12** |
| domain_dsl/rule_grammar/rule_expression_validator.py | Validates parsed rule AST — component refs exist, effect targets are writable, no circular conditions | **150** | **12** |
| domain_dsl/transaction_model/transaction_builder.py | Builds atomic DSLTransaction from ordered operations — validates atomicity, assigns UUID, sets metadata | **160** | **12** |
| domain_dsl/transaction_model/transaction_executor.py | Executes atomic transaction against CGS — commit fully or abort entirely, no partial state allowed | **180** | **12** |
| domain_dsl/mutation_metadata/mutation_metadata_model.py | MutationMetadata — version, source(prompt/manual/migration), timestamp, session_id, parent_version, confidence | **90** | **12** |

### Prompt Interpretation Layer

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| prompt_interpretation/context_loader.py | Loads current CGS context slice relevant to incoming prompt — minimal, not full schema | **120** | **12** |
| prompt_interpretation/intent_classifier.py | Classifies prompt into IntentType — lightweight heuristics + classifier, deterministic output | **140** | **12** |
| prompt_interpretation/scope_resolver.py | Resolves the schema scope affected by the intent — entity refs, component refs, system refs | **150** | **12** |
| prompt_interpretation/slot_extractor.py | Extracts named slots from prompt — entity names, component types, parameter values, conditions | **160** | **12** |
| prompt_interpretation/ambiguity_detector.py | Detects ambiguous prompt targets — triggers ClarificationRequired when confidence below threshold | **130** | **12** |
| prompt_interpretation/intent_object.py | IntentObject struct — intent_type, scope{}, action{}, parameters[], conditions[], confidence float | **90** | **12** |

### Question Engine

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| question_engine/question_engine.py | Generates structured clarification questions from ambiguity signals — CHOICE\|CONFIRM\|FILL\|SCOPE_SELECT types | **160** | **12** |
| question_engine/question_types.py | Question type definitions — each type has structure, options, response validator, resume callback | **100** | **12** |
| question_engine/question_session_manager.py | Manages in-progress clarification sessions — state, pending question, user response handling, resume pipeline | **130** | **12** |

### Consistency Validator

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| consistency_validator/consistency_validator.py | Pre-commit validator — schema existence, component compatibility, type safety, rule conflicts, system invariants | **220** | **12** |
| consistency_validator/type_checker.py | Type safety checks on mutation values — validates value type matches field definition in component registry | **130** | **12** |
| consistency_validator/conflict_detector.py | Detects rule conflicts in single transaction — SET x=10 and SET x=5 in same transaction | **110** | **12** |
| consistency_validator/invariant_enforcer.py | Enforces all 14 global invariants at design-time — validates before allowing schema commit | **150** | **12** |

### Mode Profiles

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| mode_profiles/mode_profile_loader.py | Loads and validates game mode profile definitions — arena shooter, survival, RPG, sandbox base templates | **130** | **12** |
| mode_profiles/mode_profile.py | ModeProfile struct — archetype, base_cgs_snapshot, structural_invariants, allowed_systems[], default_components[] | **100** | **12** |
| mode_profiles/profile_expander.py | Expands mode profile into full CGS skeleton — used as starting point for new game creation | **140** | **12** |

### GDE Orchestrator & Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| gde_orchestrator.py | GDE entry point — routes inputs (prompt/IntentObject/DSLTransaction), coordinates submodules, returns CGS update or ClarificationRequest. Checks if genesis session routes to GGE else normal mutation pipeline | **200** | **12** |
| tests/test_cgs_manager.py | Tests: delta application, snapshot chain, rollback correctness, hash integrity | **180** | **12** |
| tests/test_dsl_path_addressing.py | Tests: valid paths, invalid paths, partial path rejection, deep nested paths | **150** | **12** |
| tests/test_transaction_executor.py | Tests: atomic commit, partial failure rollback, ordering enforcement, conflict detection | **180** | **12** |
| tests/test_consistency_validator.py | Tests: type errors, missing refs, invariant violations, rule conflicts, all validator rules | **200** | **12** |
| tests/test_gde_orchestrator.py | Integration tests: full prompt → CGS pipeline, clarification triggers, error paths, performance targets | **220** | **12** |

---

## packages/engine-adapter — Transport & Protocol [RUST]

Translates canonical StateDelta into engine-specific commands. Build after runtime works. Start with one engine adapter (Unity or Godot).

**Total files in this module: 16**

### Transport Layer

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| transport/tcp_transport.rs | Local TCP socket transport — connect, disconnect, send/receive WireMessage bytes, multi-peer capable | **160** | **7** |
| transport/shm_transport.rs | Shared memory transport — zero-copy, kernel-bypass for same-machine XACE↔Engine communication using memory-mapped dual ring buffers. Drop-in replacement for TCP on local development. Frame format identical to TCP. Uses AtomicU64 head indices, single-writer/single-reader per ring | **200** | **7** |
| transport/message_serializer.rs | Deterministic WireMessage serialization — stable key order, fixed precision, identical bytes for identical state | **150** | **7** |
| transport/message_deserializer.rs | WireMessage deserialization — strict schema validation on receipt, rejects malformed messages | **130** | **7** |
| transport/protocol_handshake.rs | Version handshake — validates protocol_version, schema_version, execution_plan_version match; rejects on mismatch | **120** | **7** |
| transport/sequence_tracker.rs | Message sequence tracking — detects out-of-order messages, triggers SNAPSHOT request on gap | **100** | **7** |

### Adapter Contract

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| adapter_contract/engine_adapter_interface.rs | IEngineAdapter interface — spawn_entity, destroy_entity, apply_component_delta, collect_local_input(tick), send_event, receive_feedback_batch(), send_to_peer(peer_id,msg), send_visibility_queries() | **100** | **7** |
| adapter_contract/adapter_authority_enforcer.rs | Enforces adapter cannot mutate runtime state — blocks any incoming mutation attempts from engine side | **90** | **7** |

### Delta Sync Engine

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| delta_sync/delta_sync_engine.rs | Produces minimal DELTA messages — compares last-sent state vs current StateDelta, only changed components | **200** | **8** |
| delta_sync/delta_builder.rs | Builds DeltaPayload in enforced order: spawn → add_components → modify_components → remove_components → destroy | **150** | **8** |
| delta_sync/delta_compressor.rs | Removes unchanged fields from delta — only genuinely changed component fields included in payload | **120** | **8** |
| delta_sync/snapshot_recovery.rs | Full SNAPSHOT send on initial connection or desync — triggered by engine sequence gap or explicit request | **130** | **8** |
| delta_sync/resync_detector.rs | Detects engine desync conditions — sequence gaps, schema mismatches, tick drift; triggers recovery | **110** | **8** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_transport.rs | Tests: connect/disconnect, message send/receive, serialization determinism, handshake rejection on version mismatch | **180** | **7** |
| tests/test_delta_sync.rs | Tests: minimal delta production, ordering enforcement, snapshot recovery triggers, resync detection | **180** | **8** |
| tests/test_protocol_handshake.rs | Tests: matching versions accepted, mismatched versions rejected, all 3 version fields checked independently | **130** | **7** |

---

## packages/engine-feedback — Engine Feedback Protocol [RUST]

Bidirectional XACE-Engine communication. 10 feedback message types. Feedback enters XACE at tick boundaries only. Visibility queries one-tick delayed (Audit 6).

**Total files in this module: 18**

### Core Feedback Types

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| feedback_message.rs | FeedbackMessage struct — type, payload, generated_frame, entity_id, timestamp | **80** | **7** |
| feedback_type_enum.rs | FeedbackType enum — 10 types: ANIMATION_STATE_UPDATE, ANIMATION_EVENT_FIRED, PHYSICS_SETTLED, VISIBILITY_QUERY_RESULT, AUDIO_COMPLETE, AUDIO_POSITION_UPDATE, INPUT_DEVICE_UPDATE, PERFORMANCE_METRICS, ASSET_RESOLUTION_UPDATE, ENGINE_ERROR | **60** | **7** |
| feedback_buffer.rs | Thread-safe append, deterministic drain — sorted by (generated_frame ASC, entity_id ASC) at tick START | **140** | **7** |
| feedback_router.rs | Routes feedback messages to appropriate handlers based on FeedbackType | **100** | **7** |

### Handlers

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| handlers/animation_feedback_handler.rs | Processes ANIMATION_STATE_UPDATE and ANIMATION_EVENT_FIRED — updates COMP_ANIMATION_V2 via MutationGate | **120** | **7** |
| handlers/physics_feedback_handler.rs | Processes PHYSICS_SETTLED — updates COMP_TRANSFORM_V1 via MutationGate with final resting position | **110** | **7** |
| handlers/visibility_feedback_handler.rs | Processes VISIBILITY_QUERY_RESULT — updates COMP_PERCEPTION_V1, clears visibility_query_pending flag | **100** | **7** |
| handlers/audio_feedback_handler.rs | Processes AUDIO_COMPLETE and AUDIO_POSITION_UPDATE — updates audio component states | **90** | **7** |
| handlers/input_feedback_handler.rs | Processes INPUT_DEVICE_UPDATE — extended input (touch, gyro, voice) forwarded to InputSystem | **95** | **7** |
| handlers/performance_feedback_handler.rs | Processes PERFORMANCE_METRICS — feeds real engine data to PIL performance_risk_guard | **105** | **7** |

### Visibility Query System

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| visibility_query/visibility_query.rs | VisibilityQuery struct — source_entity, target_entity, query_type, raycast_parameters | **70** | **7** |
| visibility_query/visibility_query_batcher.rs | Collects COMP_PERCEPTION_V1.visibility_query_pending each tick, batches for engine send | **110** | **7** |
| visibility_query/visibility_result_store.rs | Stores visibility results — results expire after 1 tick (one-tick delay confirmed correct) | **90** | **7** |

### Logging & Validation

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| feedback_log.rs | Append-only feedback log for replay — all feedback messages recorded with tick stamp | **80** | **7** |
| feedback_replay_loader.rs | Loads feedback log during replay — injects into EngineFeedbackBuffer at correct ticks | **100** | **7** |
| feedback_validator.rs | Validates feedback message integrity — rejects out-of-order, malformed, or impossible feedback | **90** | **7** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_feedback_buffer.rs | Tests: thread-safe append, deterministic drain order, tick boundary injection | **160** | **7** |
| tests/test_visibility_queries.rs | Tests: one-tick delay confirmed, batching correctness, result expiration, perception component updates | **150** | **7** |

---

## packages/asset-registry — Asset Management [PYTHON]

AssetReference typed struct everywhere (Audit 2). Auto-naming convention. Animation Contract generated from COMP_ANIMATION_V2. Blocks UNRESOLVED from CGS commit (I11).

**Total files in this module: 18**

### Core Registry

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| asset_manifest.py | Master manifest of all assets in game — maps AssetReference → file path, status, dependencies | **140** | **7** |
| asset_reference.py | Python-side AssetReference struct — id, asset_type, status. Mirrors Rust struct exactly | **80** | **7** |
| asset_type_enum.py | Python-side AssetType enum — mirrors Rust enum for cross-language consistency | **40** | **7** |
| asset_status_enum.py | Python-side AssetStatus enum — PLACEHOLDER\|LINKED\|MISSING\|UNRESOLVED | **40** | **7** |
| asset_naming_policy.py | Auto-naming convention: [entity_type][entity_name][asset_type]_[version]. Enforces uniqueness | **90** | **7** |
| placeholder_registry.py | Registry of all PLACEHOLDER assets — tracks which entities need visual assets, grey-box status | **100** | **7** |
| asset_linker.py | Handles PLACEHOLDER→LINKED transition — maps real asset files to placeholder refs, validates format | **110** | **7** |
| asset_validator.py | Blocks UNRESOLVED refs from CGS commit (I11). Validates all AssetReferences in schema before commit | **120** | **7** |
| asset_cleanup_manager.py | Removes orphaned assets — detects unused refs, handles deletion, updates manifest | **90** | **7** |
| engine_sync_receiver.py | Receives bulk PLACEHOLDER→LINKED updates from engine feedback — applies to registry atomically | **95** | **7** |

### Animation Contract

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| animation_contract_generator.py | Generates AnimationContract from COMP_ANIMATION_V2 data — extracts states, params, IK, events | **130** | **7** |
| animation_contract.py | AnimationContract struct — states[], parameters{}, ik_requirements[], events[], version | **90** | **7** |

### Reporting & Config

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| asset_report.py | Status report for builder UI — placeholder count, link options, "game runs as grey boxes" message | **85** | **7** |
| audio_manifest.py | Audio-specific manifest — music tracks, sfx banks, spatial audio configs, streaming settings | **80** | **7** |
| asset_registry_manager.py | AssetRegistryManager entry point — orchestrates all submodules, exposes status API | **120** | **7** |
| game_config_loader.py | Loads game_config.yaml domain declarations — parses DCL domain list, validates against installed domains | **100** | **7** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_asset_manifest.py | Tests: manifest loading, reference validation, naming policy enforcement, duplicate rejection | **160** | **7** |
| tests/test_asset_validation.py | Tests: UNRESOLVED blocks commit (I11), PLACEHOLDER allows commit, LINKED validates file existence | **150** | **7** |

---

## packages/prompt-intelligence — PIL [PYTHON]

13-submodule AI pipeline. Natural language → validated, safe MutationTransaction + automatic Rust system code generation. Multi-pass LLM orchestration with self-critique. Build last, after runtime and schema pipeline work.

**Total files in this module: 59**

**CRITICAL RULE:** All LLM calls go through `packages/inference/`. No PIL submodule speaks HTTP directly. No exceptions.

### 13.1 Intent Intake

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| intent_intake/intent_intake_layer.py | Entry point — normalize prompt, classify intent (9 categories), risk pre-scan, build IntentEnvelope | **180** | **13** |
| intent_intake/prompt_normalizer.py | Trims whitespace, normalizes quotes, removes control chars, detects language, estimates token count | **100** | **13** |
| intent_intake/intent_classifier.py | Classifies into 9 intent categories — CreateFeature\|ModifyFeature\|RemoveFeature\|QueryExplain\|DebugIssue\|BalanceAdjustment\|StructuralChange\|WorldDesign\|Unknown | **150** | **13** |
| intent_intake/risk_prescanner.py | Safety pre-scan — detects engine-internal mutation attempts, code injection, invalid scope requests, routes to Safety Guard | **140** | **13** |
| intent_intake/intent_envelope.py | IntentEnvelope struct — intent_category, normalized_text, assistance_mode, requires_clarification, risk_score, confidence_estimate | **80** | **13** |

### 13.2 Context Assembler

**Note:** All output fed to `context_budgeter.py` (inference package) before reaching LLMContextPacket. dependency_expander capped 1-hop reads / 2-hop writes per Audit 9. FULL SCHEMA TRANSMISSION FORBIDDEN.

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| context_assembler/context_assembler.py | Orchestrates context assembly — produces LLMContextPacket. Calls context_budgeter to validate token count | **180** | **13** |
| context_assembler/relevance_extractor.py | Identifies relevant entities/components/systems/rules from intent — excludes irrelevant schema elements | **160** | **13** |
| context_assembler/dependency_expander.py | Expands relevance set to include required dependencies — HARD CAP 1-hop reads, 2-hop writes. Feeds system_graph_pruner on overflow | **150** | **13** |
| context_assembler/constraint_aggregator.py | Injects architectural constraints — determinism rules (D1-D15), read/write contracts, phase rules, mode restrictions. OUTPUT GOES IN CACHED PREFIX, not per-prompt body | **140** | **13** |
| context_assembler/scope_builder.py | Builds AllowedMutationScope — allowed_paths, forbidden_paths, max_mutation_depth, structural_change_allowed per mode | **130** | **13** |
| context_assembler/schema_simplifier.py | Converts ECS structures to compact LLM-friendly format — TARGET 60% size reduction vs raw CGS slice | **160** | **13** |
| context_assembler/llm_context_packet.py | LLMContextPacket struct — game_metadata, relevant entities/components/systems/rules, constraints, allowed_mutation_scope, simplified_schema_view | **90** | **13** |

### 13.3 LLM Orchestrator (5-Pass)

**Note:** All passes call `inference_adapter.py` from `packages/inference/` — NO direct HTTP. Passes 3 and 4 routed to TIER_M by model_router.

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| llm_orchestrator/llm_orchestrator.py | 5-pass reasoning pipeline orchestrator — Planning→Draft→Self-Critique→Determinism Audit→Final Output, bounded retry. Consumes LLMContextPacket once; passes share cached context | **250** | **13** |
| llm_orchestrator/pass1_planning.py | PASS 1 — Structured Planning: ReasoningPlan with target_entities, intended_mutation_type, risk_assessment. No DSL yet | **140** | **13** |
| llm_orchestrator/pass2_dsl_draft.py | PASS 2 — DSL Mutation Draft: DraftMutationTransaction with paths, operations, values matching component field types | **150** | **13** |
| llm_orchestrator/pass3_self_critique.py | PASS 3 — Self-Critique: validates draft against path validity, constraints, unintended modifications, scope violations. Triggers regen on failure | **170** | **13** |
| llm_orchestrator/pass4_determinism_audit.py | PASS 4 — Determinism Audit: checks D-rules, detects hidden dependencies, flags required_execution_graph_recompile | **150** | **13** |
| llm_orchestrator/pass5_final_output.py | PASS 5 — Final Structured Output: MutationTransaction with confidence_score, risk_level, schema_delta_type, required_recompile | **130** | **13** |
| llm_orchestrator/pil_retry_policy.py | PIL-level retry — bounded max 3 total passes per re-attempt; escalate to ClarificationEngine on exhaustion. Distinct from inference-level retry | **90** | **13** |

### 13.4 Structured Output Parser

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| output_parser/structured_output_parser.py | Strict JSON→CanonicalMutation parser — safety boundary between probabilistic LLM output and deterministic pipeline. Any deviation = reject | **180** | **13** |
| output_parser/schema_path_validator.py | Validates all paths in parsed mutation exist in current CGS — no hallucinated schema references allowed | **130** | **13** |
| output_parser/operation_type_validator.py | Validates operation types against USMC, value types match component field definitions, no extra keys | **120** | **13** |

### 13.5 Validation Loop

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| validation_loop/validation_loop.py | Multi-layer validation — structural, type, dependency, invariant. Runs Phase 12 ConsistencyValidator before any commit attempt | **180** | **13** |

### 13.6 Critique Engine

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| critique_engine/critique_engine.py | Pre-commit internal review — cross-system impact, version compatibility, mutation completeness, side-effect analysis | **160** | **13** |

### 13.7 Clarification Engine

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| clarification_engine/clarification_engine.py | Ambiguity resolution — detects ambiguous targets, generates CHOICE\|CONFIRM\|FILL\|SCOPE_SELECT structured questions | **180** | **13** |
| clarification_engine/clarification_session.py | Manages clarification session state — pending question, user response, pipeline resume point, timeout handling | **120** | **13** |
| clarification_engine/question_generator.py | Generates structured micro-form questions (not long chat) — options are schema-aware, validated against CGS | **140** | **13** |

### 13.8 Mutation Planner

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| mutation_planner/mutation_planner.py | Builds CommittedMutationPlan — operation ordering, dependency resolution, rollback plan preparation | **160** | **13** |
| mutation_planner/rollback_plan_builder.py | Prepares rollback plan for each mutation — inverse operations, previous-state capture, commit/rollback atomicity | **130** | **13** |

### 13.9 Safety and Scope Guard

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| safety_scope_guard/safety_scope_guard.py | Final governance gate — evaluates 5 risk dimensions, applies risk threshold system, returns Approved\|SoftWarning\|Blocked | **200** | **13** |
| safety_scope_guard/scope_boundary_guard.py | Enforces mutation stays within allowed scope for current mode — blocks forbidden domains (engine core, runtime scheduler) | **130** | **13** |
| safety_scope_guard/destructive_change_guard.py | Prevents deletion of core components/systems — analyzes cascade impact, requires confirmation in ADVANCED mode | **140** | **13** |
| safety_scope_guard/cascade_risk_guard.py | Simulates indirect mutation impact across dependent systems — warns when too many systems affected | **150** | **13** |
| safety_scope_guard/performance_risk_guard.py | Estimates runtime cost of mutation — memory, CPU, event load. Uses real engine metrics from Phase 7 feedback handler | **120** | **13** |
| safety_scope_guard/determinism_safety_guard.py | Blocks mutations that violate determinism — nondeterministic rules, unseeded random, cross-phase state changes | **130** | **13** |

### 13.10 Memory Model (5 Layers)

**Note:** Design + Structural + Behavioral layers loaded into CACHED PREFIX via prompt_cache. Session + Safety loaded per-prompt body per Audit 9.

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| memory_model/memory_model.py | 5-layer memory architecture — Session\|Design\|Structural\|Behavioral\|Safety. Memory influences reasoning ONLY, never runtime | **180** | **13** |
| memory_model/session_memory.py | Short-term conversation memory — recent prompts, mutations, clarifications, failures. Cleared on session end. IN PER-PROMPT BODY | **100** | **13** |
| memory_model/design_memory.py | Persistent game vision — game vision summary, difficulty philosophy, core constraints. Flags contradictory design drift. IN CACHED PREFIX | **120** | **13** |
| memory_model/structural_memory.py | Tracks all components/systems/rules created — assists DSL path resolution, prevents duplicates. IN CACHED PREFIX | **110** | **13** |
| memory_model/behavioral_memory.py | Tracks player-observable patterns — pacing concerns, known broken moments. IN CACHED PREFIX | **100** | **13** |
| memory_model/safety_memory.py | Records blocked mutations and accepted risk confirmations — prevents redundant safety alerts. IN PER-PROMPT BODY | **90** | **13** |
| memory_model/memory_lifecycle_manager.py | Load: cached layers assembled once + per-prompt layers assembled each call. Update after commit only. Versioned alongside CGS | **120** | **13** |

### 13.11 Mode Controller

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| mode_controller/mode_controller.py | Cross-cutting policy layer — FULLY_ASSISTED\|COLLABORATIVE\|ADVANCED\|ARCHITECT_MODE profiles, mode switching logic | **160** | **13** |
| mode_controller/pil_mode_profile.py | ModeProfile struct — clarification_threshold, auto_assumption_level, risk_block_level, explanation_level, auto_commit_policy, suggestion_policy | **90** | **13** |

### 13.12 History Manager

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| history_manager/history_manager.py | Manages prompt history, mutation success/failure log, session lifecycle, history retrieval for context | **150** | **13** |
| history_manager/session_store.py | Session data store — recent prompts, recent mutations, recent clarifications, recent validation failures | **100** | **13** |

### 13.13 Code Generation Engine

**Note:** `rust_code_generator.py` calls `inference_adapter.py` — NOT direct Claude API. Retry loop hard-capped at 2 per Audit 8; third failure escalates to clarification.

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| code_generation/code_generation_engine.py | Orchestrates full code generation pipeline — receives SystemSpec from CGS, calls inference_adapter, validates output, returns compiled Rust implementation or error | **200** | **13** |
| code_generation/system_spec_builder.py | Builds complete SystemSpec from schema — component types, field names, phase, determinism constraints, performance targets, ISystem interface requirements | **150** | **13** |
| code_generation/rust_code_generator.py | Calls inference_adapter with full SystemSpec context, generates Rust struct implementing ISystem trait, handles bounded retry on compile failure (max 2) | **160** | **13** |
| code_generation/code_contract_validator.py | Validates generated code against XACE contracts — correct ISystem interface, only declared components accessed, all writes via MutationGate, no direct store mutation | **140** | **13** |
| code_generation/cargo_compiler.py | Runs cargo check on generated code, captures precise compile errors, feeds error + original spec back to generator for self-correction loop. HARD CAP 2 retries | **120** | **13** |
| code_generation/determinism_code_checker.py | Static analysis on generated Rust — detects system random usage (rand::random, thread_rng), direct mutation bypassing MutationGate, unordered iteration | **130** | **13** |

### 13.14 Pipeline Entry Point

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| pil_pipeline.py | PIL entry point — orchestrates all 13 submodules in sequence, returns MutationTransaction or ClarificationRequest or BlockedMutation | **180** | **13** |

### 13.15 PIL Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_intent_intake.py | Tests: all 9 classifications, normalization edge cases, risk detection, IntentEnvelope output | **200** | **13** |
| tests/test_context_assembler.py | Tests: relevance extraction accuracy, dependency expansion cap enforcement, constraint injection, no full-schema leak, token budget rejection | **200** | **13** |
| tests/test_llm_orchestrator.py | Tests: all 5 passes, self-critique regen, determinism audit flags, retry policy, escalation path | **220** | **13** |
| tests/test_safety_scope_guard.py | Tests: all 4 risk levels, each guard module independently, determinism violations blocked, cascade detection | **200** | **13** |
| tests/test_pil_pipeline.py | Full integration tests: prompt→MutationTransaction, clarification triggers, blocking scenarios, mode behavior | **250** | **13** |
| tests/test_code_generation.py | Tests: valid SystemSpec produces compilable Rust code, contract violations rejected, determinism violations caught, cargo error triggers self-correction, user diff shown before commit | **200** | **13** |

### 13.17 Diagnostic Orchestrator (NEW, Audit 9)

**Note:** Explain/debug/replay-divergence prompts MUST NOT go through the 5-pass mutation pipeline. This 2-pass path returns explanation + optional suggested mutation, not a committed mutation.

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| diagnostic_orchestrator.py | Routes diagnostic intent types (QueryExplain\|DebugIssue) through 2-pass explain→suggest flow. PASS 1 analysis: reads relevant systems + hashes + runtime telemetry. PASS 2 suggest: optionally generates IntentObject for mutation pipeline if fix is clear. Never commits directly. | **180** | **13** |

---

## packages/inference — Inference Package [PYTHON]

**BUILD THIS BEFORE ANY OTHER PHASE 13 FILE.** Every PIL submodule imports from here. Zero direct HTTP/API calls permitted outside this package.

**Total files in this module: 25**

### Core Dispatch

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| inference_adapter.py | Single provider-agnostic dispatch point for all LLM calls — accepts InferenceRequest, returns InferenceResponse. Every PIL submodule imports this ONLY | **150** | **13.16** |
| provider_registry.py | Maps logical model names (premium_reasoning\|standard_mutation\|cheap_validation\|local_dev) to concrete provider client instances — hot-reloadable config | **120** | **13.16** |
| model_descriptor.py | Per-model metadata struct — provider, model_id, context_window_tokens, price_per_1k_input, price_per_1k_output, supports_cache_control, max_output_tokens, capabilities[] | **90** | **13.16** |

### Routing and Classification

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| model_router.py | Given ComplexityTier + BudgetContext + FailureContext selects provider+model — routes TIER_S back to deterministic Phase 12 path with no LLM call | **140** | **13.16** |
| complexity_classifier.py | Classifies IntentObject + LLMContextPacket size → TIER_S (deterministic shortcut, no LLM)\|TIER_M (cheap model)\|TIER_L (standard model)\|TIER_XL (premium + code generation) | **130** | **13.16** |

### Token and Cost

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| token_estimator.py | Pre-flight tokenizer wrapper — approximates prompt token count before inference call | **80** | **13.16** |
| cost_estimator.py | Pre-flight cost calculation — token_estimate × price_per_1k → cents. Validates against inference_budget, emits telemetry on over-budget | **90** | **13.16** |
| inference_budget.py | Per-session + per-user + per-day token budget enforcement — default infinite, interface ready for hard-cutoff without restructure | **110** | **13.16** |

### Reliability

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| fallback_policy.py | Declarative provider chain — try primary → secondary → tertiary → refuse_with_clarification. Configurable per model_router tier | **100** | **13.16** |
| inference_retry_policy.py | Tier-aware retry distinct from PIL retry — transport errors (retry immediately), schema failures (retry with correction), model quality failures (escalate). Max 2 per tier | **110** | **13.16** |

### Caching

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| prompt_cache.py | Wraps Anthropic cache_control directive — marks static sections (constraints, stable memory layers) as cacheable prefix. Transparent to callers | **120** | **13.16** |
| response_cache.py | Deterministic output cache keyed by (intent_class + structural_cgs_hash + mode_profile) — avoids re-inference on identical prompts against unchanged CGS | **100** | **13.16** |
| cache_key_builder.py | Stable cache key computation — structural_hash of CGS + intent_classification + mode_name. Ensures cache keys survive cosmetic CGS changes | **90** | **13.16** |

### Telemetry and BYOK

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| telemetry_pipeline.py | Emits one InferenceTelemetryEvent per call — provider, model, prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens, latency_ms, outcome, cost_cents, tier. Append-only log | **110** | **13.16** |
| byok_manager.py | User-supplied API key management — encrypted at rest, per-user dispatch override in inference_adapter. Pre-beta placeholder with full interface | **130** | **13.16** |

### Context Efficiency (Audit 9)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| context_budgeter.py | Per-call token budget enforcer — hard-rejects context_assembler output exceeding 8K dynamic tokens. Emits telemetry + raises ContextBudgetExceeded on breach | **100** | **13.16** |
| cgs_diff_packer.py | Computes structural delta from last cached CGS for repeat-prompt optimisation — avoids re-sending unchanged component defaults | **90** | **13.16** |
| rule_compactor.py | Summarises rule expressions for context efficiency — sends compact rule_id + condition_outline + effect_summary instead of full expression strings | **85** | **13.16** |
| system_graph_pruner.py | Caps dependency_expander output to 1-hop reads + 2-hop writes by default. Configurable max_hops per mode. Hard token-count fallback if hop budget still exceeds context budget | **110** | **13.16** |

### Providers Sub-package

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| providers/anthropic_provider.py | Concrete Anthropic API client — handles cache_control headers, streaming, error normalisation | **140** | **13.16** |
| providers/openai_provider.py | Concrete OpenAI-compatible client — for future GPT-4o + local vLLM OpenAI-shim routing | **120** | **13.16** |
| providers/local_provider.py | Ollama adapter — strips cache_control directives unsupported by local models. For local dev and enterprise self-hosted inference | **110** | **13.16** |

### Prompt Templates

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| prompt_template_registry.py | Named versioned prompt templates for all PIL passes — prevents string literals scattered across submodules. Version-pinnable per model | **90** | **13.16** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_model_router.py | All 4 tiers + TIER_S deterministic shortcut + budget enforcement + fallback chain execution + provider registry lookup | **180** | **13.16** |
| tests/test_complexity_classifier.py | TIER_S correctly classifies simple SET mutations + TIER_M covers balance changes + TIER_XL triggers code generation flag + edge cases | **170** | **13.16** |
| tests/test_inference_budget.py | Per-session cap enforcement + per-user cap + day reset + hard cutoff behaviour + telemetry emission on approach | **160** | **13.16** |
| tests/test_prompt_cache.py | cache_control directives correct + static prefix cache hit + dynamic body always uncached + cache key stability across cosmetic CGS changes | **150** | **13.16** |
| tests/test_telemetry_pipeline.py | Event emission on every call + cost calculation accuracy + cache token accounting + append-only guarantee | **140** | **13.16** |

---

## packages/builder-workspace — Builder UI [TYPESCRIPT]

The visual interface for the XACE platform. Phase 14.

**Total files in this module: 35**

### Layout & Shell

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| app.tsx | Root application shell — layout composition, global state providers, theme | **120** | **14** |
| layout/main_layout.tsx | Three-panel layout — left sidebar, center canvas, right preview | **80** | **14** |
| layout/bottom_bar.tsx | Bottom bar — version timeline, snapshot history, branch manager | **90** | **14** |

### Left Sidebar — CGS Explorer

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| sidebar/cgs_explorer.tsx | Tree view of entities/components/systems/rules/versions | **140** | **14** |
| sidebar/entity_tree.tsx | Hierarchical entity browser with search/filter | **110** | **14** |
| sidebar/component_inspector.tsx | Read-only component detail view | **90** | **14** |
| sidebar/system_list.tsx | System registry view with phase grouping | **85** | **14** |
| sidebar/rule_browser.tsx | Rule definitions with condition/effect preview | **95** | **14** |
| sidebar/version_timeline.tsx | Schema version history, rollback points | **100** | **14** |

### Center Canvas — Builder

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| canvas/prompt_input.tsx | Natural language prompt input with mode indicator | **120** | **14** |
| canvas/clarification_cards.tsx | Renders CHOICE\|CONFIRM\|FILL\|SCOPE_SELECT cards | **150** | **14** |
| canvas/diff_viewer.tsx | Side-by-side schema changes + generated code diff | **180** | **14** |
| canvas/impact_preview.tsx | Mutation impact preview — affected systems, entities, performance estimate | **130** | **14** |
| canvas/inference_cost_indicator.tsx | Per-mutation token/cost estimate display | **80** | **14** |
| canvas/technical_detail_toggle.tsx | Behavior varies per mode — FULLY_ASSISTED shows translated technical, ARCHITECT shows raw | **90** | **14** |

### Right Preview — Engine Viewport

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| preview/engine_viewport.tsx | Embedded engine render view (Unity/Godot/WebGL) | **140** | **14** |
| preview/entity_inspector.tsx | Click entity → view components. Edit triggers prompt, NOT direct mutation | **120** | **14** |
| preview/runtime_stats.tsx | Tick rate, entity count, system timing, memory | **90** | **14** |
| preview/tick_debugger.tsx | Step-through tick inspector, state inspection | **110** | **14** |

### Asset Status Panel

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| panels/asset_status_panel.tsx | Placeholder count, link options, "game runs as grey boxes" message | **100** | **14** |
| panels/asset_link_dialog.tsx | UI for mapping real assets to placeholders | **120** | **14** |

### Command Palette & Search

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| command_palette/command_palette.tsx | Cmd+K search across all schema nodes | **110** | **14** |
| command_palette/search_engine.tsx | Fuzzy search index over CGS nodes | **90** | **14** |

### Schema Graph Visualization

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| graph/schema_graph_view.tsx | Execution dependency graph visualization | **140** | **14** |
| graph/system_node_graph.tsx | Interactive system node graph with hazard highlighting | **130** | **14** |

### In-Game Console

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| console/ingame_console.tsx | Overlay inside engine adapters — Idle→PromptSubmitted→PreviewReceived→UserDecision state machine | **150** | **14** |
| console/console_state_machine.ts | State machine definition for console lifecycle | **80** | **14** |

### Inference Telemetry Panel (ARCHITECT_MODE only)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| telemetry/inference_telemetry_panel.tsx | Per-session token spend, cost, cache hit rate, tier distribution | **110** | **14** |
| telemetry/cost_chart.tsx | Visual chart of inference costs over session | **90** | **14** |

---

## packages/network-core — Network & Multiplayer [MIXED]

Lockstep + rollback (auto-selected by game type). InputSynchroniser lockstep gate. Cheat guard ALWAYS ON all modes (Audit 5). Phase 15.

**Total files in this module: 29**

### Session Management

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| network_orchestrator.py | High-level network orchestration — manages network lifecycle, mode transitions | **140** | **15** |
| network_mode.py | NetworkMode enum — OFFLINE\|HOST\|CLIENT\|DEDICATED_SERVER\|PEER_TO_PEER | **40** | **15** |
| session/peer_manager.rs | Manages peer connections — add/remove/lookup by peer_id | **120** | **15** |
| session/peer.rs | Peer struct — id, connection_state, latency, last_input_tick | **80** | **15** |
| session/connection_state.rs | ConnectionState enum — CONNECTING\|HANDSHAKING\|SYNCING\|LIVE\|DESYNCED\|RECONNECTING\|DISCONNECTED | **50** | **15** |
| session/session_manager.rs | Manages overall session state — peer list, session tick, global pause | **130** | **15** |

### Input Synchronisation (Lockstep Gate)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| input/input_packet.rs | InputPacket — peer_id, tick, sequence_id, actions[], timestamp, signature | **90** | **15** |
| input/input_synchroniser.rs | Holds tick boundary until ALL peer inputs buffered, then releases to PhaseOrchestrator | **180** | **15** |
| input/input_buffer.rs | Per-peer input buffer — detects gaps, handles late arrival, requests resend | **140** | **15** |
| input/input_delay_manager.rs | Fixed input delay from peer latencies — computes optimal delay for session | **110** | **15** |
| input/input_broadcaster.rs | Reliable delivery of input packets to all peers — ack/nack, retransmit | **130** | **15** |
| input/input_log.rs | Append-only input log — replay + cheat detection source of truth | **120** | **15** |

### Authority and Cheat Prevention

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| authority/authority_resolver.rs | Resolves which peer has authority over which entity — dynamic redistribution | **110** | **15** |
| authority/authority_transfer.rs | Handles authority handoff — state transfer, validation, rollback on failure | **100** | **15** |
| authority/cheat_guard.rs | ALWAYS ON in ALL network modes including peer-to-peer — validates input sanity, detects impossible state changes, no exceptions | **200** | **15** |

### Synchronisation and Desync Recovery

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| synchronisation/tick_barrier.rs | All peers confirm ready before tick advances — heartbeat/timeout handling | **120** | **15** |
| synchronisation/desync_detector.rs | World hash comparison every 30 ticks — detects divergence immediately | **140** | **15** |
| synchronisation/resync_engine.rs | Sends authoritative snapshot to desynced client — full state rebuild at correct tick | **160** | **15** |
| synchronisation/late_join_handler.rs | Snapshot + catch-up to live tick — fast-forward simulation for joining clients | **150** | **15** |

### Client Prediction and Rollback

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| prediction/client_predictor.rs | Predicts local entity movement between server ticks — reduces perceived latency | **130** | **15** |
| prediction/reconciliation_engine.rs | Reconciles predicted vs actual state — SNAP or INTERPOLATE per entity per COMP_AUTHORITY_V1 | **160** | **15** |
| prediction/prediction_buffer.rs | Circular buffer of predicted states — stores last N ticks for rollback | **110** | **15** |
| prediction/rollback_manager.rs | GGPO-style rollback — auto-selected for action\|shooter\|fighting\|sports game types | **180** | **15** |

### Replication and Interest Management

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| replication/relevance_filter.rs | Filters entities by distance, team, relevance_radius — per-peer view | **120** | **15** |
| replication/replication_manager.rs | Per-peer entity delta state — sends only what changed for each peer's view | **150** | **15** |
| replication/interest_zone_manager.rs | Area-of-interest zones — dynamic region-based entity filtering | **110** | **15** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_input_synchroniser.rs | Tests: lockstep gate holds until all inputs arrive, late input handling, timeout behavior | **200** | **15** |
| tests/test_desync_detection.rs | Tests: hash divergence detection at 30-tick interval, resync trigger, snapshot recovery | **180** | **15** |
| tests/test_client_prediction.rs | Tests: prediction accuracy, reconciliation SNAP vs INTERPOLATE, rollback correctness | **190** | **15** |

---

## packages/save-engine — Save/Load/Persistence [MIXED]

3-layer save: Session (temporary), Progress (persistent), World (persistent). Schema migration on load. Cloud sync abstraction (Audit 7). Phase 16.

**Total files in this module: 16**

### Core Save Engine

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| save_engine_orchestrator.py | Orchestrates save/load operations — routes to correct layer, handles migration, cloud sync | **160** | **16** |
| save_serializer.py | Deterministic JSON serialization — engine-agnostic, stable key ordering, fixed precision | **140** | **16** |
| save_deserializer.py | Validates schema_version on load (I14), enforces migration before state restoration | **130** | **16** |
| save_migration_engine.py | Applies CGS migration rules to old saves automatically — field additions, renames, removals | **150** | **16** |
| save_slot_manager.py | List/create/delete/rename save slots — metadata management, thumbnail storage | **110** | **16** |

### Runtime Systems (Rust)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| autosave_trigger_system.rs | Rust runtime reads autosave rules from CGS, marks dirty components, triggers save at safe phase | **120** | **16** |
| checkpoint_system.rs | Rust runtime manages checkpoint state — writes checkpoint on trigger, restores on death/loading | **130** | **16** |

### Cloud & Profile

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| cloud_sync_adapter.py | Abstract interface — STEAM\|PSN\|EPIC\|XBOX\|CUSTOM\|NONE. Platform-agnostic cloud operations | **110** | **16** |
| cloud_sync_conflict_resolver.py | Conflict resolution — LOCAL_WINS\|CLOUD_WINS\|ASK_USER. Merge strategy for divergent saves | **120** | **16** |
| player_profile_manager.py | Cross-session persistence — achievements, settings, statistics, display name | **100** | **16** |

### Utilities

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| save_encryption.py | Optional encryption layer — AES-256 or user-selected cipher | **90** | **16** |
| save_compression.py | LZ4 compression for save files — reduces save file size | **70** | **16** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_save_roundtrip.py | Save → load → identical world state. Determinism proof for persistence | **160** | **16** |
| tests/test_schema_migration.py | Old save loads correctly in updated game — migration rules applied, no data loss | **180** | **16** |
| tests/test_autosave_triggers.py | Tests: dirty component detection, safe-phase saving, trigger conditions from CGS | **140** | **16** |
| tests/test_cloud_conflict.py | Tests: conflict detection, resolution strategies, merge correctness | **150** | **16** |

---

## packages/game-genesis-engine — GGE [PYTHON]

30 genre templates. 3-question guided flow. First playable CGS in 90 seconds. Zero-experience entry point (Audit 4). Phase 16.

**Total files in this module: 43**

### Core GGE

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| gge_orchestrator.py | Orchestrates genesis flow — routes from creative intent to first CGS | **160** | **16** |
| creative_intent_capture.py | Parses initial user description — extracts keywords, mood, mechanics, scope | **120** | **16** |
| genre_detector.py | Detects genre from 30 templates — confidence scoring, multi-genre handling | **140** | **16** |
| genesis_question_engine.py | Generates 3 questions max, always multiple choice — narrows template selection | **130** | **16** |
| genesis_answer_processor.py | Processes answers — maps choices to template parameters, validates consistency | **110** | **16** |
| genre_template_loader.py | Loads genre template modules dynamically — validates template integrity | **100** | **16** |
| template_customiser.py | Applies user answers to base template — parameter substitution, component tuning | **140** | **16** |
| first_cgs_generator.py | Generates first Canonical Game Schema from template + answers — complete but minimal | **180** | **16** |
| genesis_asset_seeder.py | Pre-populates Asset Registry with PLACEHOLDERs for all entities in generated CGS | **120** | **16** |
| genesis_completion_presenter.py | Power signal message + sidebar tree reveal — "Your game is ready" presentation | **90** | **16** |

### Core 8 Genre Templates

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| genre_templates/horror_stealth.py | Amnesia/FNAF/Outlast style — hiding, limited vision, audio cues | **150** | **16** |
| genre_templates/action_combat.py | God of War style simple — melee combat, enemy waves, health/upgrade | **140** | **16** |
| genre_templates/platformer.py | Mario/Hollow Knight style — jump physics, collectibles, level progression | **140** | **16** |
| genre_templates/puzzle.py | Portal/The Room style — physics puzzles, logic gates, environmental storytelling | **130** | **16** |
| genre_templates/racing.py | Mario Kart style simple — lap timing, power-ups, AI opponents | **130** | **16** |
| genre_templates/rpg_exploration.py | Zelda/Stardew Valley style simple — open world, quests, inventory, NPCs | **160** | **16** |
| genre_templates/survival.py | Don't Starve/Minecraft basic — hunger, crafting, day/night, building | **150** | **16** |
| genre_templates/tower_defense.py | Bloons/Plants vs Zombies style — pathing, tower types, wave spawning | **140** | **16** |

### Expanded 14 Genre Templates

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| genre_templates/sandbox_builder.py | Minecraft full/Terraria style — voxel/block building, resource gathering, crafting trees | **160** | **16** |
| genre_templates/survival_horror.py | Resident Evil/Silent Hill style — limited resources, fixed cameras, puzzle combat | **150** | **16** |
| genre_templates/narrative_action.py | Last of Us/Uncharted style — cover shooting, companion AI, story beats | **150** | **16** |
| genre_templates/endless_runner.py | Temple Run/Subway Surfers style — lane switching, obstacles, score chasing | **130** | **16** |
| genre_templates/open_world_sandbox.py | GTA/RDR simple — mission markers, driving/shooting, wanted system | **150** | **16** |
| genre_templates/stealth_action.py | Hitman/Splinter Cell style — disguises, silent takedowns, detection meters | **140** | **16** |
| genre_templates/fighting.py | Street Fighter style simple — health bars, special moves, rounds | **130** | **16** |
| genre_templates/sports.py | FIFA/basketball style — team AI, match timers, score keeping | **140** | **16** |
| genre_templates/top_down_shooter.py | Hotline Miami/Enter the Gungeon style — dual stick aiming, room clearing, weapons | **140** | **16** |
| genre_templates/metroidvania.py | Hollow Knight full — ability gating, map unlocks, backtracking, boss fights | **160** | **16** |
| genre_templates/visual_novel.py | Story/dialogue games — branching narrative, character sprites, choice consequences | **120** | **16** |
| genre_templates/rhythm.py | Guitar Hero/Beat Saber style — note highways, scoring, beat matching | **130** | **16** |
| genre_templates/city_builder.py | Cities Skylines simple — zoning, utilities, traffic simulation, budgets | **150** | **16** |
| genre_templates/management_sim.py | Theme Hospital style simple — resource management, queue systems, happiness | **140** | **16** |

### Niche 8 Genre Templates

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| genre_templates/turn_based_strategy.py | XCOM simple — grid movement, cover, action points, enemy turns | **150** | **16** |
| genre_templates/card_game.py | Slay the Spire/Hearthstone style — deck building, card effects, enemy intents | **140** | **16** |
| genre_templates/roguelike.py | Binding of Isaac structure — procedural rooms, item stacking, permadeath | **140** | **16** |
| genre_templates/battle_royale.py | PUBG/Fortnite structure — shrinking zone, loot tiers, last-man-standing | **140** | **16** |
| genre_templates/moba_single.py | Solo MOBA practice mode — lane pushing, tower defense, hero abilities | **150** | **16** |
| genre_templates/walking_simulator.py | Edith Finch type — environmental storytelling, no fail state, exploration | **110** | **16** |
| genre_templates/idle_clicker.py | Cookie Clicker style — exponential growth, prestige loops, automation | **120** | **16** |
| genre_templates/social_deduction.py | Among Us structure — tasks, meetings, voting, impostor sabotage | **140** | **16** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_genre_detection.py | Tests: genre detection accuracy from descriptions, confidence thresholds, multi-genre handling | **160** | **16** |
| tests/test_template_customisation.py | Tests: answer application, parameter bounds, invalid answer rejection | **150** | **16** |
| tests/test_first_cgs_validity.py | Tests: generated CGS passes SchemaFactory validation, contains all required components | **180** | **16** |

---

## packages/natural-language-translation — NLTL [PYTHON]

Zero technical vocabulary in user-facing output. Inbound: feelings → design parameters. Outbound: schema diffs → plain English (Audit 4). Phase 16.

**Total files in this module: 17**

### Core NLTL

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| nltl_orchestrator.py | Orchestrates translation layer — routes inbound feelings and outbound schema diffs | **120** | **16** |
| feeling_classifier.py | Classifies user feelings — speed/difficulty/atmosphere complaints → categories | **100** | **16** |
| feeling_to_design_mapper.py | Maps feelings to design parameters — "too slow" → speed value range | **110** | **16** |
| design_question_generator.py | Generates multiple choice questions max 3 options — always schema-aware | **100** | **16** |
| design_answer_to_intent.py | Converts user choice → IntentObject for PIL pipeline | **90** | **16** |

### Schema Translation (Outbound)

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| schema_to_english_translator.py | Converts schema structures to plain English — ZERO technical vocabulary in output | **140** | **16** |
| entity_namer.py | Maps entity IDs to friendly names — entity_4521 → "the ghost" | **80** | **16** |
| system_explainer.py | Explains systems in plain English — MovementSystem → "controls how things move" | **85** | **16** |
| component_explainer.py | Explains components in plain English — COMP_STEALTH_V1.visibility_level:0.3 → "barely visible" | **90** | **16** |
| diff_summariser.py | SchemaDelta → 2-3 sentence plain English summary — what changed and why it matters | **110** | **16** |

### Language & Tone

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| vocabulary_filter.py | Strips ECS/system/component/phase/tick from ALL user-facing text | **70** | **16** |
| context_tracker.py | Tracks entity names within session — maintains consistent naming | **75** | **16** |
| tone_manager.py | Encouraging calm game-world language always — never robotic or dismissive | **80** | **16** |
| technical_detail_level_manager.py | Tracks user growth pattern — suggests mode upgrade when appropriate | **90** | **16** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_feeling_classifier.py | Tests: feeling categories, edge cases, ambiguous input handling | **120** | **16** |
| tests/test_schema_to_english.py | Tests: zero technical vocab in output, accuracy of translations, entity naming | **130** | **16** |
| tests/test_vocabulary_filter.py | Tests: all banned terms removed, context preservation, false positive avoidance | **110** | **16** |

---

## packages/design-mentor — Design Mentor [PYTHON]

Runs after every schema change. Suggests improvements, detects broken moments, explains symptoms in plain English (Audit 4). Phase 16.

**Total files in this module: 16**

### Core Mentor

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| mentor_orchestrator.py | Runs after every schema change — coordinates analysis, suggestion generation, display | **140** | **16** |
| game_analyser.py | Analyses current CGS — what is working, what is incomplete, genre alignment | **130** | **16** |
| suggestion_generator.py | Generates 2-3 suggestions, always optional — ranked by impact and ease | **120** | **16** |
| suggestion_ranker.py | Ranks suggestions — most impactful and easiest first | **90** | **16** |
| suggestion_display_policy.py | Display frequency by mode — FULLY_ASSISTED: automatic, ADVANCED: collapsed, ARCHITECT: hidden | **80** | **16** |

### Diagnostics

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| broken_moment_detector.py | Detects common broken patterns from CGS — missing win condition, unbeatable enemies, etc. | **110** | **16** |
| symptom_tracer.py | Symptom → root cause in CGS in plain English — "enemies too hard" → damage value too high | **100** | **16** |
| fix_option_generator.py | Always 2+ fix options with tradeoffs explained — never single solutions | **95** | **16** |
| game_feel_advisor.py | Genre-appropriate parameter ranges — normal speed/health/detection values per genre | **85** | **16** |
| completeness_checker.py | Validates minimum game requirements — win/lose condition, player control, at least one challenge | **90** | **16** |

### Knowledge

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| pattern_library.py | Known good design patterns with CGS signatures — reusable solutions | **100** | **16** |
| genre_standards.py | Normal values per genre — speed ranges, health defaults, detection radii | **80** | **16** |
| mentor_memory.py | Tracks shown/accepted/declined suggestions — avoids repeating declined suggestions | **85** | **16** |

### Tests

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| tests/test_suggestion_generator.py | Tests: suggestion relevance, genre appropriateness, option count, tradeoff clarity | **120** | **16** |
| tests/test_symptom_tracer.py | Tests: symptom→cause accuracy, plain English output, multiple root cause handling | **110** | **16** |

---

## adapters/ — Engine Adapters

### adapters/unity [C#]

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| XaceTransport.cs | Unity TCP client — connects to XACE runtime, sends/receives WireMessages, multi-peer, sends resolved asset list on connect | **200** | **7** |
| XaceDeltaApplicator.cs | Applies DELTA messages — spawns/destroys GameObjects, updates components, maps canonical→Unity data, collects animation and physics callbacks for feedback | **250** | **7** |
| XaceInputCollector.cs | Collects player input each frame — packages as INPUT message with tick stamp, sends to runtime per-tick | **150** | **7** |
| XaceConsoleWidget.cs | In-game prompt console UI — UMG overlay with prompt input, confidence meter, apply/cancel, output log, Idle→PromptSubmitted→PreviewReceived→UserDecision state machine | **200** | **7** |

### adapters/unreal [C++]

**Note:** Follows same architectural pattern as Unity adapter. Exact file names may vary by Unreal project conventions.

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| XaceTransport.cpp/.h | Unreal TCP client — connects to XACE runtime, WireMessage protocol | **200** | **7** |
| XaceDeltaApplicator.cpp/.h | Applies DELTA to Unreal actors/components, collects engine feedback | **250** | **7** |
| XaceInputCollector.cpp/.h | Gathers input from Unreal input system, packages per-tick | **150** | **7** |
| XaceConsoleWidget.cpp/.h | Slate/UMG console widget for in-engine prompt interface | **200** | **7** |

### adapters/godot [GDScript or C#]

**Note:** Follows same architectural pattern. Godot 4.x preferred.

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| XaceTransport.gd | Godot TCP client — connects to XACE runtime | **150** | **7** |
| XaceDeltaApplicator.gd | Applies DELTA to Godot nodes, updates properties, collects feedback | **180** | **7** |
| XaceInputCollector.gd | Gathers Godot input events, packages per-tick | **120** | **7** |
| XaceConsole.gd | In-game console UI for prompt input and status display | **150** | **7** |

---

## tests/determinism — Determinism Test Suite [RUST]

The most critical test suite. These tests prove XACE is a real deterministic platform, not just a prototype.

**Total files in this module: 14**

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| test_vertical_slice_determinism.rs | THE KEY TEST — runs example game 3 times from identical initial state, compares world_hash at tick 1000. Must be identical | **250** | **9** |
| test_snapshot_roundtrip.rs | Saves snapshot, restores, runs N ticks — output must be identical to original run from same tick | **200** | **5** |
| test_execution_order_stability.rs | Runs system executor 100 times — system execution order must be identical every run, independent of machine | **180** | **4** |
| test_entity_iteration_order.rs | Iterates entity set 1000 times in different runs — must always return same EntityID-sorted sequence (D3) | **150** | **2** |
| test_event_ordering.rs | Emits events in varied order, verifies dispatch always sorted by (tick, phase, event_id) regardless of emission order (D5) | **160** | **4** |
| test_mutation_gate_ordering.rs | Tests mutation application order is always: spawn→add→modify→remove→destroy across multiple runs (D4) | **150** | **3** |
| test_rng_determinism.rs | Same world_seed + system_id + tick always produces identical random sequences. OS/language RNG usage detected and fails (D6) | **180** | **6** |
| test_schema_version_lock.rs | Runtime with mismatched schema/execution_plan versions must halt immediately — no partial execution (D10) | **130** | **6** |
| test_replay_validation.rs | Records full game session, replays from initial snapshot — all per-tick world_hashes must match original (D14) | **220** | **6** |
| test_parallel_execution_safety.rs | Parallel execution groups produce same result as sequential execution — proves no parallel nondeterminism | **200** | **4** |
| test_mutation_transaction_atomicity.rs | Injected failure mid-transaction — schema must be fully rolled back, no partial commit ever (I8) | **160** | **3** |
| test_world_hash_consistency.rs | Builds two identical worlds independently — world_hash must be identical byte-for-byte (D9) | **150** | **6** |
| test_feedback_determinism.rs | NEW — same feedback sequence = same world hash. Proves engine feedback does not introduce nondeterminism | **170** | **7** |
| test_multiplayer_lockstep.rs | NEW — two simulations with identical inputs stay in sync. Lockstep determinism proof | **200** | **15** |

---

## tests/unit + integration — Unit & Integration Tests [MIXED]

Comprehensive test coverage across all packages. ~80 files total.

**Distribution by Package:**
- packages/core: ~8 test files (type serialization, contract validation, error handling)
- packages/dcl: ~6 test files (domain loading, component validation, GCL integration)
- packages/runtime-core: ~10 test files (entity lifecycle, component tables, query engine, mutation gate, event bus, snapshot, determinism)
- packages/system-graph-compiler: ~5 test files (included in SGC section above)
- packages/schema-factory: ~3 test files (included in Schema Factory section above)
- packages/gde: ~5 test files (included in GDE section above)
- packages/engine-adapter: ~3 test files (transport, delta sync, protocol)
- packages/engine-feedback: ~2 test files (included in Engine Feedback section above)
- packages/asset-registry: ~2 test files (included in Asset Registry section above)
- packages/prompt-intelligence: ~6 test files (included in PIL section above)
- packages/inference: ~5 test files (included in Inference section above)
- packages/network-core: ~3 test files (included in Network Core section above)
- packages/save-engine: ~4 test files (included in Save Engine section above)
- packages/game-genesis-engine: ~3 test files (included in GGE section above)
- packages/natural-language-translation: ~3 test files (included in NLTL section above)
- packages/design-mentor: ~2 test files (included in Design Mentor section above)
- packages/builder-workspace: ~4 test files (UI component tests, integration tests)
- adapters/unity: ~2 test files (C# playmode tests for delta application)
- Cross-package integration: ~10 test files (end-to-end pipelines, full system tests)

**Note:** Exact file names for unit tests outside the explicitly listed determinism and package-specific tests are left to implementation discretion, but MUST follow the naming convention `test_<module>_<feature>.py` or `test_<feature>.rs`.

---

## docs/ — Documentation [MARKDOWN]

**Total files: 12**

| Filename | Single Responsibility | ~Lines | Phase |
|---|---|---|---|
| docs/00_philosophy.md | Core philosophy — why XACE exists, North Star, design principles | **150** | Cross-cutting |
| docs/01_system_overview.md | 7-layer architecture overview — no bypass rules, data flow | **200** | Cross-cutting |
| docs/02_canonical_data_models.md | UCL/DCL/GCL three-layer architecture — component ownership, versioning, assembly | **250** | Cross-cutting |
| docs/03_module_specs.md | Per-module detailed specifications — interfaces, invariants, responsibilities | **300** | Cross-cutting |
| docs/04_contracts.md | All cross-module contracts — ISystem, IMutationGate, IEngineAdapter, etc. | **200** | Cross-cutting |
| docs/05_mutation_lifecycle.md | Full mutation lifecycle — from prompt to engine sync, state machine diagram | **250** | Cross-cutting |
| docs/06_determinism_guarantees.md | D1-D15 rules explained — how each is enforced, what happens on violation | **250** | Cross-cutting |
| docs/07_global_invariants.md | I1-I14 + II1-II10 — laws, never break, enforcement points | **200** | Cross-cutting |
| docs/08_failure_classification.md | Error taxonomy — FatalError, RecoverableError, ValidationFailure, ClarificationRequired, etc. | **150** | Cross-cutting |
| docs/09_state_machines.md | All state machines — Mutation, Entity, Asset, Network Peer, Save, Genesis | **180** | Cross-cutting |
| docs/10_versioning_and_build_order.md | Phase order, version semantics, build dependencies, crate graph | **120** | Cross-cutting |
| docs/11_inference_architecture.md | Provider abstraction, routing, caching, telemetry, BYOK — full PIL inference docs | **200** | Cross-cutting |

---

## ANTI-SUMMARIZATION RULES FOR CLAUDE CODE SESSIONS

Copy these rules into every Claude Code session when starting a new module.

### Start of Session Prompt Template

```
Read CLAUDE.md and MASTER_PLAN.md. Today we are building [FILENAME] inside [MODULE]. 
This file has ONE responsibility: [PASTE RESPONSIBILITY FROM THIS MANIFEST]. 
Target length: approximately [N] lines. 
Do NOT merge this with adjacent files. Do NOT summarize the module. 
This is one file of [TOTAL FILES IN MODULE] in this module.
When done, mark it complete in MASTER_PLAN.md and we will move to the next file.
```

### Session Discipline Rules

**Rule 1 — File as contract:** Each filename has one stated responsibility. Claude Code fills it, never invents a different scope.

**Rule 2 — Size as signal:** If Claude Code produces a file shorter than 60% of the target line count, ask it to expand. Short files mean collapsed responsibilities.

**Rule 3 — No module-level summarization:** Never say "build the Schema Factory." Always say "build this specific file." One file per session task.

**Rule 4 — Phase discipline:** Only work on files in the phase you are currently building. Do not skip ahead. Do not go back to "fix" earlier phases unless a test is failing.

**Rule 5 — Audit discipline:** Before building any file, reference the Audit Decisions Locked section. If a file violates any audit decision, stop and correct.

**Rule 6 — Test before move:** A file is not "done" until its corresponding test passes. If a file has no test yet, write the test first.

**Rule 7 — Manifest is law:** If Claude Code wants to finish a module in 4 files when this manifest says 18, stop and correct it. The manifest wins.

**Rule 8 — No direct HTTP in PIL:** If any PIL submodule imports requests, httpx, or any HTTP library directly instead of via inference_adapter.py, reject immediately. This is II1.

**Rule 9 — UCL is frozen:** If Claude Code tries to add an 11th component to UCL or modify UCL v1 definitions, reject. UCL = 10 forever. New components go to DCL.

**Rule 10 — Determinism first:** Any code that touches the runtime (Rust) must be reviewed for D-rule violations before moving to the next file. When in doubt, add a determinism test.

---

## INFERENCE INVARIANTS (LAWS — NEVER BREAK)

| ID | Invariant | Enforcement File |
|---|---|---|
| II1 | All LLM calls go through inference_adapter.py. No PIL submodule speaks HTTP directly. | inference_adapter.py |
| II2 | complexity_classifier routes TIER_S intents to deterministic Phase 12 path. No LLM call for trivial SET mutations. | model_router.py |
| II3 | prompt_cache wraps all static prefix sections (constraints, stable memory, determinism rules). Never sends static text uncached. | prompt_cache.py |
| II4 | context_budgeter enforces 8K dynamic token hard cap. Context that exceeds this is rejected before any LLM call. | context_budgeter.py |
| II5 | dependency_expander runs behind system_graph_pruner. Max 1-hop reads, 2-hop writes. No unbounded graph traversal. | system_graph_pruner.py |
| II6 | code_generation retry loop hard-capped at 2. Third failure escalates to ClarificationEngine. | cargo_compiler.py |
| II7 | diagnostic_orchestrator handles QueryExplain\|DebugIssue. These prompts never enter the 5-pass mutation pipeline. | diagnostic_orchestrator.py |
| II8 | telemetry_pipeline emits per-call event for every inference call. Zero silent calls. | telemetry_pipeline.py |
| II9 | Design + Structural + Behavioral memory layers go in cached prefix. Session + Safety go in per-prompt body. | memory_lifecycle_manager.py |
| II10 | BYOK interface exists at startup. byok_manager.py is a pre-beta placeholder with full interface ready to activate. | byok_manager.py |

---

## PROGRESS TRACKING TABLE

| Phase | Name | Status | Files Total | Files Done | Notes |
|---|---|---|---|---|---|
| 0 | Project Skeleton | [x] | 4 | 4 | cargo check passes |
| 1 | Core Types + DCL + GCL | [x] | 100 | 100 | UCL 10 + DCL 58 + Core 42 |
| 2 | Runtime Core Foundation | [x] | 16 | 16 | Entity Store, Component Tables, Query Engine |
| 3 | Mutation Gate | [x] | 8 | 8 | 4 deferred queues, D4 enforcement |
| 4 | System Executor + Event Bus | [x] | 24 | 24 | + DCL Animation Systems (Audit 3) |
| 5 | Snapshot Engine | [x] | 8 | 8 | Deep copy v1, retention policy |
| 6 | Determinism Guard | [x] | 10 | 10 | D1-D15 enforcement, STRICT/DEV/SILENT |
| 7 | Engine Adapter + Feedback + Asset Registry | [x] | 56 | 56 | + Engine Feedback (Audit 6) + Asset Registry (Audit 2) + SHM Transport |
| 8 | Delta Sync | [x] | 5 | 5 | End-to-end tested with Unity |
| 9 | Minimal Example Game | [x] | 6 | 6 | hash@1000 proven |
| 10 | System Graph Compiler | [x] | 22 | 22 | 7 compiler stages |
| 11 | Schema Factory | [x] | 20 | 20 | 127/127 tests passing |
| 12 | Game Definition Engine | [x] | 33 | 33 | 187 tests passing |
| 13.16 | Inference Package | [x] | 25 | 25 | Built FIRST per Audit 8 |
| 13.1-13.15 + 13.17 | Prompt Intelligence Layer | [ ] | 59 | 0 | NEXT BUILD TARGET |
| 14 | Builder Workspace UI | [ ] | 35 | 0 | Blocked on PIL |
| 15 | Network Core + Save Engine | [ ] | 45 | 0 | Blocked on runtime |
| 16 | Zero-Experience Layer | [ ] | 75 | 0 | Blocked on PIL + GGE |

---

*End of Manifest. This document is the single source of truth for all XACE file responsibilities. Update only when MASTER_PLAN.md or CLAUDE.md changes.*

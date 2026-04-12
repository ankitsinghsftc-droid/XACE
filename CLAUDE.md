# XACE — Master Context File for Claude Code
# Read this completely before every session.
# Version: Post-Audit v2 (Audits 1-10 integrated)

---

## WHAT XACE IS

XACE is a deterministic, engine-agnostic, schema-driven game definition compiler
and complete game creation platform.

NOT a game engine. NOT a scripting assistant. NOT an engine plugin.

North Star: Anyone — zero experience, zero code knowledge — can build a high-end game
by describing what they want in plain English. XACE handles everything else.

Core principle: User Intent → Schema Mutation → Execution Plan → Runtime Simulation → Engine Sync

---

## ARCHITECTURE — 7 LAYERS (NO BYPASS EVER)

Layer 1 — Prompt Intelligence Layer (PIL)
  Input:  Natural language prompt
  Output: MutationTransaction + generated Rust implementation when needed
  Never:  Mutates schema or runtime directly

Layer 2 — Game Definition Engine (GDE)
  Input:  MutationTransaction / IntentObject / DSLTransaction
  Output: Validated SchemaDelta → Updated CGS
  Never:  Executes logic, touches runtime, touches engine

Layer 3 — Schema Factory
  Input:  CGS
  Output: Compiled Schema Package (Blueprints, Composite Registry, Dependency Graph)
  Never:  Runs systems, modifies runtime

Layer 4 — System Graph Compiler (SGC)
  Input:  Compiled Schema Package
  Output: ExecutionPlan vN (deterministic, acyclic, parallel-grouped)
  Never:  Executes systems itself

Layer 5 — Runtime Core
  Input:  ExecutionPlan + Runtime State
  Output: StateDelta per tick
  Never:  Modifies CGS directly

Layer 6 — Engine Adapter Layer
  Input:  StateDelta from Runtime + VisibilityQueryBatch
  Output: Engine-specific commands
  Also receives: EngineFeedbackBatch (10 types — Audit 6)
  Never:  Contains gameplay logic, mutates runtime state

Layer 7 — External Game Engine
  Responsibility: Render, animate, audio, input, send feedback
  Never:  Defines game rules, modifies runtime state

---

## COMPONENT ARCHITECTURE — THREE LAYERS (Audit 1)

Old flat UCL of 25 components REPLACED by three-layer system.

=== UCL CORE — 10 components, FROZEN FOREVER ===
Owner: XACE. Every game uses all 10.
Test: "Can I make ANY genre without this?" If yes for any genre, it does not belong here.

COMP_TRANSFORM_V1   — position(x,y,z), rotation(x,y,z,w), scale(x,y,z), parent_entity_id
COMP_IDENTITY_V1    — entity_name, entity_type, faction, tags[], prefab_id, is_runtime_spawned
COMP_RENDER_V1      — render_type, asset_reference(AssetReference typed), material_ref, visible, layer
COMP_COLLIDER_V1    — shape, size, offset, is_trigger, layer_mask, physics_material_id
COMP_VELOCITY_V1    — linear(x,y,z), angular(x,y,z), max_linear_speed, max_angular_speed
COMP_INPUT_V1       — controller_id, control_type(HUMAN/AI_PROXY/NETWORK_REMOTE), input_profile_id
COMP_EVENT_V1       — event_type, payload, is_consumed, emitted_tick, target_entity_id
COMP_LIFETIME_V1    — max_lifetime_ticks, current_lifetime_ticks, on_expire_action
COMP_GAMESTATE_V1   — current_phase, score, time_elapsed_ticks, active_mode_id, match_state
COMP_AUTHORITY_V1   — authority_type(LOCAL/SERVER/CLIENT_OWNED/SHARED), owner_peer_id,
                      replication_mode(UNRELIABLE/RELIABLE/SERVER_ONLY),
                      prediction_enabled, reconciliation_mode(SNAP/INTERPOLATE),
                      sync_rate_divisor, is_replicated

=== DCL — Domain Component Library, 10 domain packages, VERSIONED & EXTENSIBLE ===
Owner: XACE. Game project declares domains in game_config.yaml.

dcl/combat/      HEALTH, DAMAGE, HITBOX, SHIELD, STATUS_EFFECT
dcl/character/   MOVEMENT_INTENT, ANIMATION_V2, IK, CARRY, RAGDOLL
dcl/physics/     RIGIDBODY, SURFACE_PROPERTIES, BUOYANCY, SOFT_BODY
dcl/ai/          AI, PATROL, PERCEPTION, CROWD_AGENT
dcl/stealth/     STEALTH, DISGUISE, DETECTION
dcl/rpg/         STATS, INVENTORY, ABILITY, PROGRESSION, ECONOMY
dcl/world/       SPAWNER, TRIGGERZONE, PERSISTENCE, WORLDSTREAMING, ENVIRONMENT, DESTRUCTIBLE
dcl/interaction/ INTERACTION, DIALOGUE, PUZZLE, USABLE
dcl/camera/      CAMERA, CAMERA_SHAKE, CINEMATIC
dcl/audio/       AUDIO_EMITTER, AUDIO_LISTENER, MUSIC_STATE, AUDIO_ZONE
dcl/network/     REPLICATION, NETWORK_TRANSFORM, PLAYER_SESSION
dcl/ui/          UI_ELEMENT, HUD_BINDING, MINIMAP

COMP_ANIMATION_V2 full spec (Audit 3 — replaces V1):
  controller_ref: AssetReference
  playback_speed: float
  layers: dict { layer_name: { current_state, weight, mask, additive } }
  parameters: dict { param_name: { value, type(BOOL/FLOAT/INT/TRIGGER) } }
  blend_parameters: dict { tree_name: { x_parameter, y_parameter, blend_type } }
  pending_events: list [{
    event_id, state_name,
    trigger_at_normalized_time: float,
    game_event_type: EventType,
    payload: dict, is_consumed: bool
  }]
  ik_enabled: bool
  current_normalized_time: float   <- written back by engine via feedback
  is_transitioning: bool           <- written back by engine via feedback
  active_state_per_layer: dict     <- written back by engine via feedback

Animation events: XACE writes pending_event with trigger time -> engine watches ->
fires feedback when reached -> XACE processes at tick boundary -> game event fires ->
Mutation Gate acts. Animation is no longer a floating string.

COMP_IK_V1 spec (Audit 3 — new in dcl/character/):
  ik_mode: DISABLED|LOOK_AT|HANDS|FEET|HANDS_AND_FEET|FULL_BODY
  look_at_target_entity, look_at_weight, look_at_clamp_degrees
  left_hand_target_entity, left_hand_target_offset, left_hand_weight
  right_hand_target_entity, right_hand_target_offset, right_hand_weight
  foot_placement_enabled, foot_placement_weight
  carry_ik_preset: NONE|DRAG_BY_FEET|CARRY_OVER_SHOULDER|FIREMAN_CARRY|TWO_HAND_CARRY
  solve_order: FABRIK|CCD|TWO_BONE

=== GCL — Game Component Library, PER-GAME, UNLIMITED ===
Owner: Individual game developer. Lives in game project folder. XACE validates only.
Must follow XACE field type rules. No name collisions with UCL/DCL.

=== Composite Registry ===
Assembled at game load: UCL Core (always) + declared DCL domains + GCL.
File: dcl/dcl_registry.py — replaces old frozen ucl_registry.py.

---

## ASSET MANAGEMENT (Audit 2)

Asset references are typed AssetReference objects — NEVER raw strings.

Four asset states:
  PLACEHOLDER  — auto-created by XACE. No real asset. Game logic works. Visuals blocked.
  LINKED       — real asset mapped. Engine renders it.
  MISSING      — was linked, file not found now. Warning, not blocker.
  UNRESOLVED   — reference in CGS never registered. BUG. Blocked from CGS commit (I12).

Auto-naming convention: [entity_type]_[entity_name]_[asset_type]_[version]
Examples: character_knight_mesh_v1, enemy_dragon_roar_sfx_v1

Animation Contract: auto-generated from COMP_ANIMATION_V2 — tells engine exactly what
states, parameters, IK, animation event timings are needed. Lives in packages/asset-registry/.

Zero-experience flow: Entity created -> refs auto-registered PLACEHOLDER ->
builder shows "7 assets are placeholders — game runs but looks like grey boxes" ->
user builds logic first, links visuals when ready.

---

## ENGINE FEEDBACK PROTOCOL (Audit 6)

Communication is bidirectional. Engine sends feedback batch every tick.

10 feedback types:
  ANIMATION_STATE_UPDATE  — current state, normalized time, layer states
  ANIMATION_EVENT_FIRED   — specific animation trigger point reached
  PHYSICS_SETTLED         — ragdoll/physics object final resting position
  VISIBILITY_QUERY_RESULT — raycast: entity A can/cannot see entity B
  AUDIO_COMPLETE          — audio clip finished playing
  AUDIO_POSITION_UPDATE   — 3D audio source moved
  INPUT_DEVICE_UPDATE     — extended input: touch, gyro, voice amplitude
  PERFORMANCE_METRICS     — ms/tick per system, draw calls, physics contacts
  ASSET_RESOLUTION_UPDATE — which asset refs are now resolved
  ENGINE_ERROR            — engine-side error XACE should know about

Determinism rule (I13): All feedback buffered between ticks.
Drained at START of each tick. Sorted by (generated_frame ASC, entity_id ASC).
One-tick delay confirmed correct and acceptable.

Visibility queries: XACE writes query_pending to COMP_PERCEPTION_V1 ->
batched -> sent to engine -> results return next tick. Real raycasting replaces distance approximation.

---

## SAVE / LOAD / PERSISTENCE (Audit 7)

Three save layers:
  SessionSave   — temporary. Active game state snapshot. Lost on quit.
  ProgressSave  — persistent. Level, inventory, unlocks, story flags, achievements.
  WorldSave     — persistent. World changes: doors, NPCs, objects, terrain.

Save determinism (I15): Same WorldSnapshot + ProgressSave -> identical gameplay playback.

Save versioning: Save files carry CGS version. Old saves migrated via SchemaDiff rules.
User warned if migration fails.

Auto-save: Driven by COMP_PERSISTENCE_V1 (auto_save, last_saved_tick, is_dirty).
Systems mark components dirty. SaveSystem saves at safe phase boundary.

---

## CANONICAL DATA MODELS

CGS v1: metadata, global_systems, modes[]. Each mode: world, actors[], systems[], rules[], ui.
Versioning: MAJOR.MINOR.PATCH. Every mutation increments and recomputes cgs_hash.

ExecutionPlan v1:
  {"phases": [{"name": "Simulation", "execution_groups": [
    {"parallel": false, "systems": ["MovementSystem"]},
    {"parallel": true, "systems": ["HealthRegenSystem", "EnergyRegenSystem"]}
  ]}]}

WorldSnapshot v1: tick, time_seconds, schema_version, execution_plan_version,
entity_store_snapshot, component_tables_snapshot, mutation_queue_state,
event_queue_state, rng_state{world_seed, stream_positions}

Wire payload v1 message types: SNAPSHOT|DELTA|INPUT|EVENT|CONTROL|FEEDBACK

---

## ALL MODULES

Module 1 — GDE (Python, Phase 12)
  DSL: USMC|PAM(fully qualified only)|REG|Transaction Model|MMM
  Performance: total prompt processing <150ms

Module 2 — Schema Factory (Python, Phase 11)
  Validates against CompositeComponentRegistry (UCL+DCL+GCL), not frozen UCL.

Module 3 — SGC (Rust, Phase 10)
  7 stages: Graph Construction -> Phase Segmentation -> Dependency Resolution ->
  Conflict Analyzer -> Scheduler -> Cycle Detection -> Parallelization Safety

Module 4 — Runtime Core (Rust, Phases 2-6)
  Entity Store|Component Tables|Query Engine|Mutation Gate|Phase Orchestrator|
  Time Controller|Snapshot Engine|Event Bus|Determinism Guard
  Phase Orchestrator: drains engine feedback buffer at START of each tick (Audit 6)

Module 5 — Engine Adapter (Rust, Phases 7-8)
  Includes packages/engine-feedback/ (18 files).
  Sends: StateDelta + VisibilityQueryBatch
  Receives: InputPacket + EngineFeedbackBatch

Module 6 — PIL (Python, Phase 13) — 13 submodules
  1.Intent Intake 2.History Manager 3.Mode Router 4.Context Assembler
  5.LLM Orchestrator(5-pass) 6.Structured Output Parser 7.Validation Loop
  8.Critique Engine 9.Clarification Engine 10.Safety&Scope Guard
  11.Memory Model 12.Mode Controller
  13.Code Generation Engine — SystemSpec from CGS -> Claude API -> Rust code ->
     validates ISystem contract -> cargo check -> self-corrects -> user confirms diff

Module 7 — Game Genesis Engine (Python, Phase 16)
  30 genre templates. 3-question guided flow. First playable CGS in 90 seconds.
  Templates: horror_stealth, action_combat, platformer, puzzle, racing,
  rpg_exploration, survival, tower_defense, sandbox_builder, survival_horror,
  narrative_action, endless_runner, open_world_sandbox, stealth_action,
  fighting, sports, top_down_shooter, metroidvania, visual_novel, rhythm,
  city_builder, management_sim, turn_based_strategy, card_game, roguelike,
  battle_royale, moba_single, walking_simulator, idle_clicker, social_deduction

Module 8 — NLTL (Python, Phase 16)
  Inbound: feeling/emotion -> design parameter -> IntentObject for PIL
  Outbound: schema diff -> plain English (ZERO technical vocabulary shown to user)
  Technical details toggle: learning pathway, exists in all modes.

Module 9 — Design Mentor (Python, Phase 16)
  Suggestion frequency by mode:
    FULLY_ASSISTED: automatic after every change
    COLLABORATIVE: after significant changes only
    ADVANCED: collapsed by default
    ARCHITECT_MODE: completely hidden
  Symptom tracer + fix options in plain English. Zero ECS vocabulary to user.

Module 10 — Network Core (Phase 15)
  Models: Lockstep|Server Auth+Prediction|Interest Management
  Fixed input delay + rollback both Phase 15.
  Cheat guard ALWAYS ON across all network modes.
  NLTL guides zero-experience multiplayer setup (3 questions).

Module 11 — Save System (Python, Phase 15)
  3 layers: Session|Progress|World
  Auto-save driven by COMP_PERSISTENCE_V1
  Save migration via SchemaDiff rules

---

## GLOBAL INVARIANTS (LAWS — NEVER BREAK)

I1  Component tables never contain EntityIDs not in EntityStore
I2  ALL structural changes through Mutation Gate. Direct mutation FORBIDDEN
I3  CGS is single source of truth. No runtime system modifies schema directly
I4  System order defined ONLY by ExecutionPlan. No self-scheduling
I5  Engine adapters mirror state only. Never mutate authoritative world state
I6  No module may introduce nondeterministic behavior into runtime
I7  Runtime never runs with schema version mismatch. Mismatch = halt
I8  Schema mutations applied atomically. Partial commits FORBIDDEN
I9  Events never modify state directly. All mutation through Mutation Gate
I10 Snapshot restore must reconstruct world state exactly
I11 GCL components never enter DCL or UCL namespaces
I12 UNRESOLVED asset references never enter committed CGS
I13 Engine feedback processed only at tick boundaries, never mid-tick
I14 Every input packet carries the tick it was generated. No untimed inputs
I15 Same WorldSnapshot + ProgressSave must produce identical gameplay

---

## DETERMINISM RULES D1-D15

D1  System order = ExecutionPlan only
D2  EntityID never reused, destroyed = archived
D3  Entity iteration sorted by EntityID ASC
D4  Mutations only after phase completion, via Mutation Gate
D5  Events sorted by (creation_tick, creation_phase, event_id)
D6  DeterministicRNG only. seed=hash(world_seed,system_id,tick). No OS/language RNG
D7  Fixed timestep only. delta_time=1/simulation_rate. Rendering FPS never affects sim
D8  Consistent float precision, avoid frame-dependent accumulation
D9  world_hash computed after each tick. Replay hashes must match
D10 runtime.schema_version == execution_plan.schema_version always
D11 Stable key ordering in serialization. Fixed decimal precision. No unordered maps
D12 External input applied at tick boundaries only
D13 Adapters never modify authoritative simulation state
D14 Replay = initial snapshot + deterministic input stream + identical schema version
D15 Determinism Guard hooks at every execution boundary

---

## FAILURE CLASSIFICATION

FatalError       — determinism violation, schema mismatch, corrupted snapshot
RecoverableError — network drop, asset resolution delay
ValidationFailure — invalid schema path, type mismatch, dependency violation
ClarificationRequired — ambiguous prompt, needs user input
RetryableLLMFailure — invalid LLM output, retry then clarify
AssetUnresolved  — UNRESOLVED ref blocks CGS commit
NetworkDesync    — peer hash mismatch, trigger resync
SaveVersionMismatch — attempt migration, warn if failed

---

## STATE MACHINES

Mutation:     PromptReceived->IntentParsed->DSLGenerated->Parsed->Validated->
              Critiqued->Approved->SchemaCommitted->RuntimeApplied->EngineSynced
Entity:       Created->Active->Disabled->DestroyRequested->Destroyed->Archived
Asset:        UNRESOLVED->PLACEHOLDER->LINKED|MISSING
Network Peer: CONNECTING->HANDSHAKING->SYNCING->LIVE->DESYNCED->RECONNECTING->DISCONNECTED
Save:         Dirty->Saving->Saved|SaveFailed->Migrating->MigrationComplete|MigrationFailed
Genesis:      DescribeGame->GenreDetected->QuestionsAnswered->TemplateSelected->
              CGSGenerated->FirstPreview->BuildingGame

---

## TECH STACK

Runtime Core, SGC, Engine Adapter Protocol, UCL+DCL core types -> Rust
Schema Factory, GDE, PIL, GGE, NLTL, Design Mentor, Asset Registry,
  Network Core (high level), Save System -> Python
Builder Workspace UI -> TypeScript + React
Unity Adapter -> C#
Unreal Adapter -> C++
Godot Adapter -> GDScript

---

## PHASE ORDER

0  Skeleton
1  Canonical Data (UCL Core 10, all DCL domain components, error types, contracts)
2  Entity Store + Component Tables + Query Engine
3  Mutation Gate
4  System Executor + Phase Orchestrator + Event Bus
5  Snapshot Engine
6  Determinism Guard
7  Engine Adapter + Engine Feedback Protocol + Transport
8  Delta Sync
9  Vertical Slice Determinism Proof (zombie chase, hash test)
10 System Graph Compiler
11 Schema Factory (composite UCL+DCL+GCL registry)
12 Game Definition Engine
13 PIL (13 submodules incl. Code Generation Engine)
14 Builder Workspace UI
15 Network Core + Save/Load System
16 Game Genesis Engine + NLTL + Design Mentor

---

## CODING CONVENTIONS

1  Contracts before implementation — typed interfaces first
2  No layer bypass — never call across layers
3  Sorted structures everywhere — determinism requires it
4  Explicit fully-qualified paths — no implicit addressing
5  Atomic or nothing — mutations either fully succeed or fully roll back
6  Test determinism — same input same output always
7  Version everything crossing module boundaries
8  Asset references typed — never raw strings. Always AssetReference
9  Engine feedback only at tick boundaries — never mid-tick
10 Validate GCL on load before use

---

## SESSION START

Tell me: which phase/module today, decisions since last session, any test failures.
I read CLAUDE.md and MASTER_PLAN.md and continue from exactly where we left off.

# XACE MASTER BUILD PLAN
# Version: Post-Audit (Audits 1-7 incorporated)
# Status: [ ] Not Started | [~] In Progress | [x] Complete | [!] Blocked
# Update this file after every single session.

---

## AUDIT DECISIONS LOCKED (Reference Before Building Any File)

Audit 1 - Component Architecture: UCL=10 frozen, DCL=domain packages XACE-owned, GCL=developer-owned in game project
Audit 2 - Asset Pipeline: AssetReference typed struct not raw string, 4 states PLACEHOLDER/LINKED/MISSING/UNRESOLVED, auto-naming convention, Animation Contract generated from COMP_ANIMATION_V2
Audit 3 - Animation Depth: COMP_ANIMATION_V2 with layers dict + pending_events list, COMP_IK_V1, AnimationEventSystem in dcl/character/
Audit 4 - Zero-Experience User: Game Genesis Engine + Natural Language Translation Layer + Design Mentor, 30 genre templates, all Phase 16
Audit 5 - Multiplayer: Lockstep + rollback (auto-selected by game type), InputSynchroniser lockstep gate, cheat guard ALWAYS ON all modes, Phase 15
Audit 6 - Engine Feedback: Bidirectional XACE-Engine, 10 feedback message types, feedback enters XACE at tick boundaries only, visibility queries one-tick delayed
Audit 7 - Save/Load/Persistence: 3-layer save (game progress, player profile, schema version), 4 new DCL persistence components, schema migration on load, cloud sync abstraction

---

## PHASE OVERVIEW

Phase 0   - Project Skeleton (1-2 days)
Phase 1   - Core Types + DCL Stubs + GCL Loader (1 week)
Phase 2   - Runtime Core Foundation (1 week)
Phase 3   - Mutation Gate (3-4 days)
Phase 4   - System Executor + Phase Orchestrator (1 week)
Phase 5   - Snapshot Engine (3-5 days)
Phase 6   - Determinism Guard (3 days)
Phase 7   - Engine Adapter + Engine Feedback Protocol (1.5 weeks)
Phase 8   - Delta Sync (3-4 days)
Phase 9   - Minimal Example Game - MILESTONE 1 (3-5 days)
Phase 10  - System Graph Compiler (1-2 weeks)
Phase 11  - Schema Factory (1-2 weeks)
Phase 12  - Game Definition Engine (2 weeks)
Phase 13  - Prompt Intelligence Layer 13 submodules (4-5 weeks)
Phase 14  - Builder Workspace UI (3-4 weeks)
Phase 15  - Network Core Multiplayer (3-4 weeks)
Phase 16  - Zero-Experience Layer (4-5 weeks)

Milestone 1 Phase 9: hash test passes. Architecture proven real.
Milestone 2 Phase 12: full compilation pipeline.
Milestone 3 Phase 13: natural language to code to running game.
Milestone 4 Phase 16: zero-experience user builds complete game from one sentence.

---

## PHASE 0 - PROJECT SKELETON
Target: 1-2 days

- [ ] Run create_xace_project.sh
- [ ] Copy CLAUDE.md and MASTER_PLAN.md into xace/ root
- [ ] cargo check passes
- [ ] git init + first commit

Phase 0 Status: [ ] Complete
Notes:

---

## PHASE 1 - CANONICAL DATA MODELS + DCL + GCL LOADER
Target: 1 week

### 1.1 UCL Core - 10 Components Only (Rust, packages/core/src/)
Note: Only these 10. Everything else moved to DCL. This is locked per Audit 1.
- [ ] entity_id.rs - EntityID u64, NULL_ENTITY_ID, EntityIdGenerator atomic monotonic
- [ ] entity_state.rs - Active|Disabled|DestroyRequested|Destroyed|Archived
- [ ] entity_metadata.rs
- [ ] ucl/transform_component.rs - COMP_TRANSFORM_V1
- [ ] ucl/identity_component.rs - COMP_IDENTITY_V1
- [ ] ucl/render_component.rs - COMP_RENDER_V1 (asset_reference: AssetReference NOT String)
- [ ] ucl/collider_component.rs - COMP_COLLIDER_V1
- [ ] ucl/velocity_component.rs - COMP_VELOCITY_V1
- [ ] ucl/input_component.rs - COMP_INPUT_V1
- [ ] ucl/event_component.rs - COMP_EVENT_V1
- [ ] ucl/lifetime_component.rs - COMP_LIFETIME_V1
- [ ] ucl/game_state_component.rs - COMP_GAMESTATE_V1
- [ ] ucl/authority_component.rs - COMP_AUTHORITY_V1 with prediction_enabled, reconciliation_mode SNAP|INTERPOLATE, sync_rate_divisor, is_replicated
- [ ] ucl/ucl_registry.rs - 10 components only, frozen

### 1.2 Asset Reference Types (Rust, packages/core/src/assets/)
Per Audit 2 - AssetReference is a typed struct everywhere, never a raw String
- [ ] asset_reference.rs - AssetReference struct id+asset_type+status
- [ ] asset_type_enum.rs - MESH|TEXTURE|MATERIAL|ANIMATION_CONTROLLER|AUDIO_CLIP|AUDIO_MUSIC|SPRITE|PARTICLE|PREFAB|FONT
- [ ] asset_status_enum.rs - PLACEHOLDER|LINKED|MISSING|UNRESOLVED

### 1.3 Schema Types (Rust, packages/core/src/schema/)
- [ ] canonical_game_schema.rs
- [ ] game_mode.rs
- [ ] world_definition.rs
- [ ] actor_definition.rs
- [ ] system_definition.rs
- [ ] rule_definition.rs

### 1.4 Mutation Types (Rust, packages/core/src/mutation/)
- [ ] mutation_transaction.rs
- [ ] dsl_operation.rs
- [ ] schema_delta.rs
- [ ] usmc_categories.rs

### 1.5 Runtime Types (Rust, packages/core/src/runtime/)
- [ ] execution_plan.rs
- [ ] phase_enum.rs - Initialization|Input|Simulation|PostSimulation|Cleanup
- [ ] execution_group.rs
- [ ] world_snapshot.rs
- [ ] state_delta.rs

### 1.6 Event Types (Rust, packages/core/src/events/)
- [ ] event_type.rs - all domains including ANIMATION_EVENT_FIRED, PHYSICS_SETTLED, AUDIO_COMPLETE
- [ ] event_struct.rs

### 1.7 Wire Protocol Types (Rust, packages/core/src/wire/)
- [ ] wire_message.rs
- [ ] message_type.rs - SNAPSHOT|DELTA|INPUT|EVENT|CONTROL|FEEDBACK
- [ ] delta_payload.rs
- [ ] snapshot_payload.rs
- [ ] feedback_payload.rs - engine feedback message wrapper (new per Audit 6)

### 1.8 Error Types (Rust, packages/core/src/errors/)
- [ ] xace_error.rs - includes SaveMigrationRequired per Audit 7, NetworkDesyncError per Audit 5
- [ ] determinism_error.rs - D1-D15

### 1.9 Contracts (Rust, packages/core/src/contracts/)
- [ ] interfaces.rs - ISystem, IMutationGate, IEntityStore, IComponentTable, ISnapshotEngine, IEventBus, IDeterminismGuard, IEngineAdapter updated with receive_feedback_batch() and send_visibility_queries(), ISaveEngine

### 1.10 DCL Package (Python, packages/dcl/)
Registry and loader:
- [ ] dcl_registry.py - CompositeComponentRegistry: core + domains + GCL assembled at game load
- [ ] dcl_loader.py - loads domains from game_config.yaml
- [ ] domain_package.py
- [ ] gcl_loader.py - loads GCL from game project gcl/ folder
- [ ] gcl_validator.py - no name collision, valid field types, no engine-specific types

DCL combat/ domain:
- [ ] combat/health_component.py - COMP_HEALTH_V1
- [ ] combat/damage_component.py - COMP_DAMAGE_V1
- [ ] combat/hitbox_component.py - COMP_HITBOX_V1
- [ ] combat/shield_component.py - COMP_SHIELD_V1
- [ ] combat/status_effect_component.py - COMP_STATUS_EFFECT_V1

DCL character/ domain (Audit 3 - COMP_ANIMATION_V2 full spec):
- [ ] character/movement_intent_component.py - COMP_MOVEMENT_INTENT_V1
- [ ] character/animation_component.py - COMP_ANIMATION_V2 with layers dict, pending_events list, blend_parameters, ik_enabled, engine feedback fields
- [ ] character/ik_component.py - COMP_IK_V1 full spec with carry_ik_preset DRAG_BY_FEET|CARRY_OVER_SHOULDER|FIREMAN_CARRY|TWO_HAND_CARRY
- [ ] character/carry_component.py - COMP_CARRY_V1
- [ ] character/ragdoll_component.py - COMP_RAGDOLL_V1

DCL physics/ domain:
- [ ] physics/rigidbody_component.py - COMP_RIGIDBODY_V1
- [ ] physics/surface_properties_component.py - COMP_SURFACE_PROPERTIES_V1
- [ ] physics/buoyancy_component.py - COMP_BUOYANCY_V1
- [ ] physics/soft_body_component.py - COMP_SOFT_BODY_V1

DCL ai/ domain:
- [ ] ai/ai_component.py - COMP_AI_V1
- [ ] ai/patrol_component.py - COMP_PATROL_V1
- [ ] ai/perception_component.py - COMP_PERCEPTION_V1 with visibility_query_pending flag per Audit 6
- [ ] ai/crowd_agent_component.py - COMP_CROWD_AGENT_V1 lightweight Logic LOD for large crowds

DCL stealth/ domain:
- [ ] stealth/stealth_component.py - COMP_STEALTH_V1
- [ ] stealth/disguise_component.py - COMP_DISGUISE_V1
- [ ] stealth/detection_component.py - COMP_DETECTION_V1

DCL rpg/ domain:
- [ ] rpg/stats_component.py - COMP_STATS_V1
- [ ] rpg/inventory_component.py - COMP_INVENTORY_V1
- [ ] rpg/ability_component.py - COMP_ABILITY_V1
- [ ] rpg/progression_component.py - COMP_PROGRESSION_V1
- [ ] rpg/economy_component.py - COMP_ECONOMY_V1

DCL world/ domain:
- [ ] world/spawner_component.py - COMP_SPAWNER_V1
- [ ] world/triggerzone_component.py - COMP_TRIGGERZONE_V1
- [ ] world/persistence_component.py - COMP_PERSISTENCE_V1
- [ ] world/worldstreaming_component.py - COMP_WORLDSTREAMING_V1
- [ ] world/environment_component.py - COMP_ENVIRONMENT_V1
- [ ] world/destructible_component.py - COMP_DESTRUCTIBLE_V1

DCL interaction/ domain:
- [ ] interaction/interaction_component.py - COMP_INTERACTION_V1
- [ ] interaction/dialogue_component.py - COMP_DIALOGUE_V1
- [ ] interaction/puzzle_component.py - COMP_PUZZLE_V1
- [ ] interaction/usable_component.py - COMP_USABLE_V1

DCL camera/ domain:
- [ ] camera/camera_component.py - COMP_CAMERA_V1
- [ ] camera/camera_shake_component.py - COMP_CAMERA_SHAKE_V1
- [ ] camera/cinematic_component.py - COMP_CINEMATIC_V1

DCL audio/ domain:
- [ ] audio/audio_emitter_component.py - COMP_AUDIO_EMITTER_V1
- [ ] audio/audio_listener_component.py - COMP_AUDIO_LISTENER_V1
- [ ] audio/music_state_component.py - COMP_MUSIC_STATE_V1 intensity_value driven by distance
- [ ] audio/audio_zone_component.py - COMP_AUDIO_ZONE_V1

DCL network/ domain (per Audit 5):
- [ ] network/replication_component.py - COMP_REPLICATION_V1
- [ ] network/network_transform_component.py - COMP_NETWORK_TRANSFORM_V1
- [ ] network/player_session_component.py - COMP_PLAYER_SESSION_V1

DCL ui/ domain:
- [ ] ui/ui_element_component.py - COMP_UI_ELEMENT_V1
- [ ] ui/hud_binding_component.py - COMP_HUD_BINDING_V1
- [ ] ui/minimap_component.py - COMP_MINIMAP_V1

DCL persistence/ domain (per Audit 7):
- [ ] persistence/save_slot_component.py - COMP_SAVE_SLOT_V1 with schema_version field
- [ ] persistence/checkpoint_component.py - COMP_CHECKPOINT_V1 MANUAL|AUTO|STORY|RESPAWN
- [ ] persistence/player_profile_component.py - COMP_PLAYER_PROFILE_V1
- [ ] persistence/cloud_sync_component.py - COMP_CLOUD_SYNC_V1 STEAM|EPIC|PSN|XBOX|CUSTOM|NONE

DCL Tests:
- [ ] tests/test_dcl_registry.py - domain loading, composite assembly, GCL validation
- [ ] tests/test_gcl_loader.py - valid GCL loads, name collision rejection
- [ ] tests/test_domain_isolation.py - game using only dcl-combat cannot access dcl-rpg

Phase 1 Status: [ ] Complete
Notes:

---

## PHASE 2 - RUNTIME CORE FOUNDATION
Target: 1 week

### 2.1 Entity Store
- [ ] entity_store.rs - create_entity, destroy_entity, exists, get_all_alive sorted ASC for D3
- [ ] entity_id_generator.rs - atomic monotonic, never reuses
- [ ] entity_archive.rs - permanently reserved IDs
- [ ] tests/test_entity_store.rs

### 2.2 Component Tables
- [ ] component_table.rs - BTreeMap<EntityID,ComponentData> deterministic
- [ ] component_table_store.rs
- [ ] sorted_entity_map.rs - D3 core enforcement
- [ ] tests/test_component_tables.rs

### 2.3 Query Engine
- [ ] query_engine.rs - intersection queries always returns sorted EntityID
- [ ] query_cache.rs - invalidate on add/remove
- [ ] tests/test_query_engine.rs

Phase 2 Status: [ ] Complete
Notes:

---

## PHASE 3 - MUTATION GATE
Target: 3-4 days

- [ ] mutation_gate.rs - 4 deferred queues, apply_all in order spawn->add->modify->remove->destroy
- [ ] mutation_queue.rs
- [ ] mutation_validator.rs - validates against CompositeComponentRegistry not just UCL
- [ ] tests/test_mutation_gate.rs

Phase 3 Status: [ ] Complete
Notes:

---

## PHASE 4 - SYSTEM EXECUTOR + PHASE ORCHESTRATOR + EVENT BUS
Target: 1 week

### 4.1 Phase Orchestrator
- [ ] phase_orchestrator.rs - drain EngineFeedbackBuffer at tick START then run phases
- [ ] parallel_executor.rs - thread-local event buffers deterministic merge
- [ ] system_context.rs
- [ ] system_registry.rs
- [ ] tests/test_phase_orchestrator.rs

### 4.2 Time Controller
- [ ] time_controller.rs - NORMAL|REPLAY|SCRUB|SERVER_AUTH|MULTIPLAYER modes, fixed_input_delay field
- [ ] deterministic_rng.rs - seed=hash(world_seed, system_id, tick)
- [ ] tests/test_time_controller.rs

### 4.3 Event Bus
- [ ] event_bus.rs - deferred dispatch at phase END
- [ ] event_dispatcher.rs - sorted tick+phase+event_id
- [ ] event_subscription_registry.rs
- [ ] tests/test_event_bus.rs

### 4.4 DCL Character Animation Systems (Rust per Audit 3)
- [ ] dcl/character/animation_event_system.rs - reads pending_events, fires game events at tick boundary marks consumed
- [ ] dcl/character/animation_layer_manager.rs - multi-layer state
- [ ] dcl/character/animation_state_validator.rs
- [ ] dcl/character/tests/test_animation_event_system.rs
- [ ] dcl/character/tests/test_animation_layers.rs

Phase 4 Status: [ ] Complete
Notes:

---

## PHASE 5 - SNAPSHOT ENGINE
Target: 3-5 days

- [ ] snapshot_engine.rs - take_snapshot restore_snapshot deep copy initially
- [ ] snapshot_store.rs - Map<Tick,WorldSnapshot> retention policy
- [ ] snapshot_serializer.rs - deterministic stable key ordering fixed precision
- [ ] tests/test_snapshot_engine.rs

Phase 5 Status: [ ] Complete
Notes:

---

## PHASE 6 - DETERMINISM GUARD
Target: 3 days

- [ ] determinism_guard.rs - STRICT|DEV|SILENT modes 6 runtime hooks enforces D1-D15
- [ ] world_hasher.rs - hash entity_store + component_tables + tick
- [ ] replay_validator.rs - per-tick hash comparison
- [ ] rng_interceptor.rs - blocks OS/language RNG rule D6
- [ ] tests/test_determinism_guard.rs - each D1-D15 rule violation tested

Phase 6 Status: [ ] Complete
Notes:

---

## PHASE 7 - ENGINE ADAPTER + ENGINE FEEDBACK PROTOCOL
Target: 1.5 weeks

### 7.1 Transport
- [ ] tcp_transport.rs - multi-peer capable
- [ ] message_serializer.rs
- [ ] message_deserializer.rs
- [ ] protocol_handshake.rs
- [ ] sequence_tracker.rs

### 7.2 Adapter Contract
- [ ] engine_adapter_interface.rs - IEngineAdapter with spawn_entity, destroy_entity, apply_component_delta, collect_local_input(tick), send_event, receive_feedback_batch(), send_to_peer(peer_id,msg), send_visibility_queries()
- [ ] adapter_authority_enforcer.rs

### 7.3 Engine Feedback Package (packages/engine-feedback/) - per Audit 6
- [ ] feedback_message.rs
- [ ] feedback_type_enum.rs - 10 types
- [ ] feedback_buffer.rs - thread-safe append, deterministic drain sorted generated_frame ASC entity_id ASC at tick START
- [ ] feedback_router.rs
- [ ] handlers/animation_feedback_handler.rs
- [ ] handlers/physics_feedback_handler.rs - PHYSICS_SETTLED updates COMP_TRANSFORM_V1 via MutationGate
- [ ] handlers/visibility_feedback_handler.rs
- [ ] handlers/audio_feedback_handler.rs
- [ ] handlers/input_feedback_handler.rs
- [ ] handlers/performance_feedback_handler.rs - feeds PIL performance risk guard real data
- [ ] visibility_query/visibility_query.rs
- [ ] visibility_query/visibility_query_batcher.rs - collects COMP_PERCEPTION_V1.visibility_query_pending each tick
- [ ] visibility_query/visibility_result_store.rs - results expire after 1 tick
- [ ] feedback_log.rs - append-only for replay
- [ ] feedback_replay_loader.rs
- [ ] feedback_validator.rs
- [ ] tests/test_feedback_buffer.rs
- [ ] tests/test_visibility_queries.rs

### 7.4 Asset Registry (packages/asset-registry/) - per Audit 2
- [ ] asset_manifest.py
- [ ] asset_reference.py - Python-side AssetReference struct
- [ ] asset_type_enum.py
- [ ] asset_status_enum.py
- [ ] asset_naming_policy.py - auto-naming: entity_type_name_assettype_version
- [ ] placeholder_registry.py
- [ ] asset_linker.py - PLACEHOLDER->LINKED transition
- [ ] asset_validator.py - blocks UNRESOLVED from CGS commit enforces I11
- [ ] asset_cleanup_manager.py
- [ ] engine_sync_receiver.py - bulk PLACEHOLDER->LINKED from feedback
- [ ] animation_contract_generator.py - generates Animation Contract from COMP_ANIMATION_V2 data
- [ ] animation_contract.py - AnimationContract struct with states params IK events
- [ ] asset_report.py - status report for builder UI
- [ ] audio_manifest.py
- [ ] asset_registry_manager.py
- [ ] game_config_loader.py - loads game_config.yaml domain declarations
- [ ] tests/test_asset_manifest.py
- [ ] tests/test_asset_validation.py

### 7.5 Delta Sync
- [ ] delta_sync_engine.rs
- [ ] delta_builder.rs
- [ ] delta_compressor.rs
- [ ] snapshot_recovery.rs
- [ ] resync_detector.rs
- [ ] tests/test_transport.rs
- [ ] tests/test_delta_sync.rs
- [ ] tests/test_protocol_handshake.rs

### 7.6 Unity Adapter
- [ ] XaceTransport.cs - multi-peer sends resolved asset list on connect
- [ ] XaceDeltaApplicator.cs - collects animation and physics callbacks for feedback
- [ ] XaceInputCollector.cs - InputPackets with tick stamp
- [ ] XaceConsoleWidget.cs

Phase 7 Status: [ ] Complete
Notes:

---

## PHASE 8 - DELTA SYNC
Target: 3-4 days

- [ ] End-to-end delta sync test with Unity
- [ ] Sequence gap detection and SNAPSHOT recovery tested
- [ ] Performance test delta size at 100 entities

Phase 8 Status: [ ] Complete
Notes:

---

## PHASE 9 - MINIMAL EXAMPLE GAME - MILESTONE 1
Target: 3-5 days

Entities: Player UCL Core + dcl/combat, Zombie UCL Core + dcl/ai + dcl/combat
Systems all code-generated: InputSystem, MovementSystem, AISystem, DamageSystem, DeathSystem

Critical determinism test:
- [ ] Run from identical state 3 times
- [ ] world_hash at tick 1000 identical all 3 runs
- [ ] Engine shows zombie chase in Unity or Godot

MILESTONE 1: If hash test passes, architecture is proven real. Everything after is expansion.

Phase 9 Status: [ ] Complete
Notes:

---

## PHASE 10 - SYSTEM GRAPH COMPILER
Target: 1-2 weeks

7 compiler stages all in packages/system-graph-compiler/src/:
- [ ] graph_construction/ - graph_construction_layer.rs, system_node.rs, system_edge.rs EXPLICIT_DEPENDENCY|READ_AFTER_WRITE|WRITE_AFTER_WRITE|PHASE_ORDER, hazard_detector.rs WAW tie-break lexicographic
- [ ] phase_segmentation/ - phase_segmentation_layer.rs, phase_validator.rs
- [ ] dependency_resolution/ - dependency_resolution_engine.rs Kahns algorithm, topological_sorter.rs
- [ ] conflict_analyzer/ - conflict_analyzer.rs ConflictReport+SerializationGroups, serialization_group_builder.rs
- [ ] scheduler/ - deterministic_scheduler_builder.rs ExecutionPlan v1, parallel_group_analyzer.rs
- [ ] cycle_detection/ - cycle_detector.rs hard=CompilationError soft=suggestion, cycle_diagnostics.rs
- [ ] parallelization/ - parallelization_safety_model.rs
- [ ] sgc_pipeline.rs, compilation_error.rs
- [ ] tests/ - 5 test files

Phase 10 Status: [ ] Complete
Notes:

---

## PHASE 11 - SCHEMA FACTORY
Target: 1-2 weeks

- [ ] entity_blueprint/ - blueprint_compiler.py, entity_blueprint.py, blueprint_registry.py
- [ ] component_registry/component_definition_registry.py - validates against CompositeComponentRegistry not just UCL
- [ ] component_registry/component_definition.py
- [ ] system_registry/ - system_definition_registry.py, system_validator.py
- [ ] versioning/ - schema_version_manager.py, schema_snapshot.py
- [ ] diff_migration/ - schema_diff_engine.py, migration_rule_generator.py
- [ ] mode_composition/ - mode_composition_engine.py, mode_validator.py
- [ ] validation/schema_validation_contract.py - includes I11 no UNRESOLVED asset refs and I14 save schema version
- [ ] validation/invariant_checker.py - checks I1-I14
- [ ] schema_factory.py, compiled_schema_package.py
- [ ] tests/ - 3 files

Phase 11 Status: [ ] Complete
Notes:

---

## PHASE 12 - GAME DEFINITION ENGINE
Target: 2 weeks

- [ ] cgs/ - cgs_manager.py, mutation_target_resolver.py fully qualified paths only, cgs_serializer.py deterministic
- [ ] domain_dsl/ - usmc_classifier.py, path_parser.py, path_resolver.py, rule_expression_parser.py, rule_expression_validator.py, transaction_builder.py, transaction_executor.py, mutation_metadata_model.py
- [ ] prompt_interpretation/ - context_loader.py, intent_classifier.py, scope_resolver.py, slot_extractor.py, ambiguity_detector.py, intent_object.py
- [ ] question_engine/ - question_engine.py, question_types.py, question_session_manager.py
- [ ] consistency_validator/ - consistency_validator.py, type_checker.py, conflict_detector.py, invariant_enforcer.py
- [ ] mode_profiles/ - mode_profile_loader.py, mode_profile.py, profile_expander.py
- [ ] gde_orchestrator.py - checks if genesis session routes to GGE else normal mutation pipeline
- [ ] tests/ - 5 files

Phase 12 Status: [ ] Complete
Notes:

---

## PHASE 13 - PROMPT INTELLIGENCE LAYER (13 submodules)
Target: 4-5 weeks

### 13.1 Intent Intake
- [ ] intent_intake_layer.py, prompt_normalizer.py, intent_classifier.py 9 categories, risk_prescanner.py, intent_envelope.py

### 13.2 Context Assembler
- [ ] context_assembler.py, relevance_extractor.py, dependency_expander.py, constraint_aggregator.py, scope_builder.py, schema_simplifier.py, llm_context_packet.py

### 13.3 LLM Orchestrator 5-pass
- [ ] llm_orchestrator.py, pass1_planning.py, pass2_dsl_draft.py, pass3_self_critique.py, pass4_determinism_audit.py, pass5_final_output.py, retry_policy.py

### 13.4 Structured Output Parser
- [ ] structured_output_parser.py, schema_path_validator.py, operation_type_validator.py

### 13.5 Validation Loop
- [ ] validation_loop.py

### 13.6 Critique Engine
- [ ] critique_engine.py

### 13.7 Clarification Engine
- [ ] clarification_engine.py, clarification_session.py, question_generator.py

### 13.8 Mutation Planner
- [ ] mutation_planner.py, rollback_plan_builder.py

### 13.9 Safety and Scope Guard
- [ ] safety_scope_guard.py, scope_boundary_guard.py, destructive_change_guard.py, cascade_risk_guard.py
- [ ] performance_risk_guard.py - uses real engine metrics from Phase 7 feedback handler
- [ ] determinism_safety_guard.py

### 13.10 Memory Model (5 layers)
- [ ] memory_model.py, session_memory.py, design_memory.py, structural_memory.py, safety_memory.py, memory_lifecycle_manager.py

### 13.11 Mode Controller
- [ ] mode_controller.py - FULLY_ASSISTED|COLLABORATIVE|ADVANCED|ARCHITECT_MODE
- [ ] mode_profile.py

### 13.12 History Manager
- [ ] history_manager.py, session_store.py

### 13.13 Code Generation Engine - NEW
- [ ] code_generation/code_generation_engine.py - orchestrates SystemSpec -> Claude API -> validated Rust implementation
- [ ] code_generation/system_spec_builder.py - extracts complete spec from CGS
- [ ] code_generation/rust_code_generator.py - calls Claude API generates ISystem implementation
- [ ] code_generation/code_contract_validator.py - correct interface, correct components, writes via MutationGate
- [ ] code_generation/cargo_compiler.py - cargo check self-correction on error
- [ ] code_generation/determinism_code_checker.py - static: no OS RNG, no direct mutation, no unordered iteration
- [ ] tests/test_code_generation.py

### 13.14 Pipeline Entry Point
- [ ] pil_pipeline.py - orchestrates all 13 submodules

### 13.15 Tests
- [ ] tests/test_intent_intake.py, test_context_assembler.py, test_llm_orchestrator.py, test_safety_scope_guard.py, test_pil_pipeline.py

Phase 13 Status: [ ] Complete
Notes:

---

## PHASE 14 - BUILDER WORKSPACE UI
Target: 3-4 weeks

- [ ] Left sidebar: CGS Explorer entities/components/systems/rules/versions
- [ ] Builder canvas: prompt input, clarification cards CHOICE|CONFIRM|FILL|SCOPE_SELECT, diff viewer shows schema changes + generated code side by side, impact preview panel
- [ ] Right preview: engine viewport, entity inspector edit triggers prompt not direct mutation, runtime stats, tick debugger
- [ ] Bottom bar: version timeline, snapshot history, branch manager
- [ ] Command palette: Cmd+K search all schema nodes
- [ ] Schema graph visualization: execution dependency view
- [ ] Asset status panel: placeholder count, link options, game runs as grey boxes message
- [ ] Technical details toggle: behavior varies per mode FULLY_ASSISTED shows translated technical ARCHITECT shows raw
- [ ] In-game console inside engine adapters: Idle->PromptSubmitted->PreviewReceived->UserDecision state machine

Phase 14 Status: [ ] Complete
Notes:

---

## PHASE 15 - NETWORK CORE (MULTIPLAYER)
Target: 3-4 weeks

### 15.1 Session Management
- [ ] network_orchestrator.py, network_mode.py OFFLINE|HOST|CLIENT|DEDICATED_SERVER|PEER_TO_PEER
- [ ] session/peer_manager.rs, peer.rs, connection_state.rs CONNECTING|HANDSHAKING|SYNCING|LIVE|DESYNCED|RECONNECTING|DISCONNECTED, session_manager.rs

### 15.2 Input Synchronisation (the lockstep gate)
- [ ] input/input_packet.rs - peer_id, tick, sequence_id, actions, timestamp, signature
- [ ] input/input_synchroniser.rs - holds tick boundary until ALL peer inputs buffered then releases to PhaseOrchestrator
- [ ] input/input_buffer.rs - per-peer detects gaps handles late arrival
- [ ] input/input_delay_manager.rs - fixed delay from peer latencies
- [ ] input/input_broadcaster.rs - reliable delivery to all peers
- [ ] input/input_log.rs - append-only replay + cheat detection

### 15.3 Authority and Cheat Prevention
- [ ] authority/authority_resolver.rs
- [ ] authority/authority_transfer.rs
- [ ] authority/cheat_guard.rs - ALWAYS ON in ALL network modes including peer-to-peer. No exceptions.

### 15.4 Synchronisation and Desync Recovery
- [ ] synchronisation/tick_barrier.rs - all peers confirm ready before tick advances
- [ ] synchronisation/desync_detector.rs - world_hash comparison every 30 ticks
- [ ] synchronisation/resync_engine.rs - sends authoritative snapshot to desynced client
- [ ] synchronisation/late_join_handler.rs - snapshot + catch-up to live tick

### 15.5 Client Prediction and Rollback
- [ ] prediction/client_predictor.rs
- [ ] prediction/reconciliation_engine.rs - SNAP or INTERPOLATE per entity
- [ ] prediction/prediction_buffer.rs - circular buffer
- [ ] prediction/rollback_manager.rs - GGPO-style auto-selected for action|shooter|fighting|sports game types

### 15.6 Replication and Interest Management
- [ ] replication/relevance_filter.rs - by distance, team, relevance_radius
- [ ] replication/replication_manager.rs - per-peer entity delta state
- [ ] replication/interest_zone_manager.rs - area-of-interest zones

### 15.7 Tests
- [ ] tests/test_input_synchroniser.rs
- [ ] tests/test_desync_detection.rs
- [ ] tests/test_client_prediction.rs

Phase 15 Status: [ ] Complete
Notes:

---

## PHASE 16 - ZERO-EXPERIENCE LAYER
Target: 4-5 weeks

### 16.1 Game Genesis Engine (packages/game-genesis-engine/)
- [ ] gge_orchestrator.py
- [ ] creative_intent_capture.py
- [ ] genre_detector.py - detects from 30 genres
- [ ] genesis_question_engine.py - 3 questions max, always multiple choice
- [ ] genesis_answer_processor.py
- [ ] genre_template_loader.py
- [ ] template_customiser.py
- [ ] first_cgs_generator.py
- [ ] genesis_asset_seeder.py - pre-populates Asset Registry with PLACEHOLDERs
- [ ] genesis_completion_presenter.py - power signal message + sidebar tree reveal

Genre Templates 30 total. Build Core 8 first then Expanded then Niche:
Core 8:
- [ ] genre_templates/horror_stealth.py - Amnesia FNAF Outlast
- [ ] genre_templates/action_combat.py - God of War simple
- [ ] genre_templates/platformer.py - Mario Hollow Knight
- [ ] genre_templates/puzzle.py - Portal concept The Room
- [ ] genre_templates/racing.py - Mario Kart simple
- [ ] genre_templates/rpg_exploration.py - Zelda simple Stardew Valley
- [ ] genre_templates/survival.py - Don't Starve basic Minecraft
- [ ] genre_templates/tower_defense.py - Bloons Plants vs Zombies

Expanded 14:
- [ ] genre_templates/sandbox_builder.py - Minecraft full Terraria
- [ ] genre_templates/survival_horror.py - Resident Evil Silent Hill
- [ ] genre_templates/narrative_action.py - Last of Us Uncharted
- [ ] genre_templates/endless_runner.py - Temple Run Subway Surfers
- [ ] genre_templates/open_world_sandbox.py - GTA RDR simple
- [ ] genre_templates/stealth_action.py - Hitman Splinter Cell
- [ ] genre_templates/fighting.py - Street Fighter simple
- [ ] genre_templates/sports.py - FIFA basketball
- [ ] genre_templates/top_down_shooter.py - Hotline Miami Enter the Gungeon
- [ ] genre_templates/metroidvania.py - Hollow Knight full
- [ ] genre_templates/visual_novel.py - story dialogue games
- [ ] genre_templates/rhythm.py - Guitar Hero Beat Saber
- [ ] genre_templates/city_builder.py - Cities Skylines simple
- [ ] genre_templates/management_sim.py - Theme Hospital simple

Niche 8:
- [ ] genre_templates/turn_based_strategy.py - XCOM simple
- [ ] genre_templates/card_game.py - Slay the Spire Hearthstone
- [ ] genre_templates/roguelike.py - Binding of Isaac structure
- [ ] genre_templates/battle_royale.py - PUBG Fortnite structure shrinking zone
- [ ] genre_templates/moba_single.py - solo MOBA practice mode
- [ ] genre_templates/walking_simulator.py - Edith Finch type
- [ ] genre_templates/idle_clicker.py - Cookie Clicker
- [ ] genre_templates/social_deduction.py - Among Us structure

Tests:
- [ ] tests/test_genre_detection.py
- [ ] tests/test_template_customisation.py
- [ ] tests/test_first_cgs_validity.py

### 16.2 Natural Language Translation Layer (packages/natural-language-translation/)
- [ ] nltl_orchestrator.py
- [ ] feeling_classifier.py - speed/difficulty/atmosphere complaints
- [ ] feeling_to_design_mapper.py - too slow -> speed value range
- [ ] design_question_generator.py - always multiple choice max 3 options
- [ ] design_answer_to_intent.py - choice -> IntentObject for PIL
- [ ] schema_to_english_translator.py - zero technical vocabulary in output
- [ ] entity_namer.py - entity_4521 -> the ghost
- [ ] system_explainer.py - MovementSystem -> controls how things move
- [ ] component_explainer.py - COMP_STEALTH_V1.visibility_level:0.3 -> barely visible
- [ ] diff_summariser.py - SchemaDelta -> 2-3 sentence plain English
- [ ] vocabulary_filter.py - strips ECS/system/component/phase/tick from ALL user-facing text
- [ ] context_tracker.py - entity names within session
- [ ] tone_manager.py - encouraging calm game-world language always
- [ ] technical_detail_level_manager.py - tracks user growth pattern suggests mode upgrade
- [ ] tests/test_feeling_classifier.py
- [ ] tests/test_schema_to_english.py
- [ ] tests/test_vocabulary_filter.py

### 16.3 Design Mentor (packages/design-mentor/)
- [ ] mentor_orchestrator.py - runs after every schema change
- [ ] game_analyser.py - what is working, what is incomplete
- [ ] suggestion_generator.py - 2-3 suggestions, always optional
- [ ] suggestion_ranker.py - most impactful and easiest first
- [ ] suggestion_display_policy.py - full FULLY_ASSISTED, minimal ADVANCED, hidden ARCHITECT_MODE
- [ ] broken_moment_detector.py - common broken patterns from CGS
- [ ] symptom_tracer.py - symptom -> root cause in CGS in plain English
- [ ] fix_option_generator.py - always 2+ fix options with tradeoffs explained
- [ ] game_feel_advisor.py - genre-appropriate parameter ranges
- [ ] completeness_checker.py - win/lose condition, player control, at least one challenge
- [ ] pattern_library.py - known good design patterns with CGS signatures
- [ ] genre_standards.py - normal speed/health/detection values per genre
- [ ] mentor_memory.py - tracks shown/accepted/declined suggestions avoids repeating declined
- [ ] tests/test_suggestion_generator.py
- [ ] tests/test_symptom_tracer.py

### 16.4 Save Engine (packages/save-engine/) - per Audit 7
- [ ] save_engine_orchestrator.py
- [ ] save_serializer.py - deterministic JSON engine-agnostic
- [ ] save_deserializer.py - validates schema_version on load enforces I14
- [ ] save_migration_engine.py - applies CGS migration rules to old saves automatically
- [ ] save_slot_manager.py - list create delete rename slots
- [ ] autosave_trigger_system.rs - Rust runtime reads autosave rules from CGS
- [ ] checkpoint_system.rs - Rust runtime manages checkpoint state
- [ ] cloud_sync_adapter.py - abstract interface STEAM|PSN|EPIC|XBOX|CUSTOM|NONE
- [ ] cloud_sync_conflict_resolver.py - LOCAL_WINS|CLOUD_WINS|ASK_USER
- [ ] player_profile_manager.py - cross-session persistence
- [ ] save_encryption.py - optional
- [ ] save_compression.py - LZ4
- [ ] tests/test_save_roundtrip.py - save -> load -> identical world state
- [ ] tests/test_schema_migration.py - old save loads correctly in updated game
- [ ] tests/test_autosave_triggers.py
- [ ] tests/test_cloud_conflict.py

Phase 16 Status: [ ] Complete
Notes:

---

## DETERMINISM TEST SUITE (tests/determinism/ all Rust)

- [ ] test_vertical_slice_determinism.rs - THE KEY TEST: 3 runs tick 1000 hash identical
- [ ] test_snapshot_roundtrip.rs
- [ ] test_execution_order_stability.rs
- [ ] test_entity_iteration_order.rs - D3
- [ ] test_event_ordering.rs - D5
- [ ] test_mutation_gate_ordering.rs - D4
- [ ] test_rng_determinism.rs - D6
- [ ] test_schema_version_lock.rs - D10
- [ ] test_replay_validation.rs - D14
- [ ] test_parallel_execution_safety.rs
- [ ] test_mutation_transaction_atomicity.rs - I8
- [ ] test_world_hash_consistency.rs - D9
- [ ] test_feedback_determinism.rs - NEW same feedback sequence = same world hash
- [ ] test_multiplayer_lockstep.rs - NEW two simulations with identical inputs stay in sync

---

## CROSS-CUTTING

### Git Commit Convention
feat(module): description
fix(module): description
chore: description
test(module): description
refactor(module): description
docs: description
audit(N): description

### Documentation
- [ ] docs/00_philosophy.md
- [ ] docs/01_system_overview.md
- [ ] docs/02_canonical_data_models.md - UCL/DCL/GCL three-layer architecture
- [ ] docs/03_module_specs.md
- [ ] docs/04_contracts.md
- [ ] docs/05_mutation_lifecycle.md
- [ ] docs/06_determinism_guarantees.md
- [ ] docs/07_global_invariants.md - I1-I14
- [ ] docs/08_failure_classification.md
- [ ] docs/09_state_machines.md
- [ ] docs/10_versioning_and_build_order.md

---

## PROGRESS SUMMARY

| Phase | Name | Status | Started | Completed |
|---|---|---|---|---|
| 0 | Project Skeleton | [ ] | | |
| 1 | Core Types + DCL + GCL | [ ] | | |
| 2 | Runtime Core Foundation | [ ] | | |
| 3 | Mutation Gate | [ ] | | |
| 4 | System Executor + Event Bus | [ ] | | |
| 5 | Snapshot Engine | [ ] | | |
| 6 | Determinism Guard | [ ] | | |
| 7 | Engine Adapter + Feedback | [ ] | | |
| 8 | Delta Sync | [ ] | | |
| 9 | Minimal Example Game | [ ] | | |
| 10 | System Graph Compiler | [ ] | | |
| 11 | Schema Factory | [ ] | | |
| 12 | Game Definition Engine | [ ] | | |
| 13 | Prompt Intelligence Layer | [ ] | | |
| 14 | Builder Workspace | [ ] | | |
| 15 | Network Core | [ ] | | |
| 16 | Zero-Experience Layer | [ ] | | |

---

## LAST SESSION LOG

Date:
Phase worked on:
What was completed:
What is in-progress:
Blockers:
Audit decisions relevant to current phase:
Next session should start with:

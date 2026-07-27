# XACE Launch Readiness Map

This is the working map for moving current XACE from strong infrastructure to a launch-ready creator product. Keep it updated as slices land. The rule for every slice is:

1. Map the launch goal to files.
2. Name each touched file's single responsibility.
3. Build the smallest complete vertical behavior.
4. Add or run the closest test/smoke.
5. Update this map before moving on.

## Product Boundary

XACE owns:

- Canonical gameplay schemas, component contracts, semantic events, deterministic runtime state, mutation safety, saves, networking, replay, semantic asset bindings, AI-assisted authoring, and engine adapter contracts.

Engines own:

- Rendering, lighting, terrain editing, materials, animation playback graphs, audio playback, detailed physics solving, native editor workflows, and final platform packaging.

Guardrail:

- XACE may expose semantic/debug viewports and binding tools, but it must not become a weak renderer, terrain editor, material editor, lighting editor, or full animation editor.
- Historical slice entries record local proof at the time they were written; they are not public product claims by themselves.
- "Import" means wrap/link an existing engine project with XACE manifest, starter CGS, and adapter preparation. It does not mean automatic conversion of existing engine-native gameplay.
- "Export" means export/copy an adapter package for engine-owned integration. It does not mean a finished-game shipping pipeline.
- "Multiplayer" means network primitives and local smoke coverage until topology, security, chaos, soak, and installed-engine proof gates pass.
- "Portability" means gameplay-core portability through CGS/runtime/adapters. It does not mean finished-game portability for engine-native content, scenes, assets, builds, or platform services.
- "Prompt/AI" means guarded supported CGS mutation scenarios. It does not mean open-ended gameplay-system creation from prompts.

## Current Module Map

| Area | Status | Primary Files | Single Responsibility |
|---|---:|---|---|
| Root workspace | Partial | `Cargo.toml`, `package.json`, `Start XACE Builder.cmd` | Declare Rust/JS workspace scripts and provide the visible local Builder launch entry point. |
| Core shared model | Exists / Partial | `packages/core/src/**` | Own stable cross-package types: UCL, CGS schema, runtime snapshots/deltas, events, wire messages, mutations, errors, contracts. |
| Runtime core | Exists / Partial | `packages/runtime-core/src/lib.rs` | Public runtime-core module surface. |
| Runtime executable | Exists / Partial | `packages/runtime-core/src/bin/xace_runtime.rs` | CLI entry for loading CGS and starting runtime/control/engine bridge services. |
| CGS loading | Exists / Partial | `packages/runtime-core/src/cgs_loader.rs` | Load and validate Canonical Game Schema input from disk. |
| Runtime orchestration | Exists / Partial | `packages/runtime-core/src/runtime_orchestrator.rs` | Own authoritative tick lifecycle and runtime state progression. |
| Built-in systems | Partial | `packages/runtime-core/src/builtin_systems.rs` | Run bundled gameplay/runtime systems before pluginized systems exist. |
| Engine protocol | Exists / Partial | `packages/runtime-core/src/engine_protocol.rs` | Define runtime-to-engine and engine-to-runtime JSON protocol payloads. |
| TCP bridge | Exists / Partial | `packages/runtime-core/src/tcp_server.rs` | Stream snapshots/deltas and receive input/feedback over TCP. |
| Runtime control | Partial | `packages/runtime-core/src/control_protocol.rs`, `packages/runtime-core/src/control_server.rs` | Provide builder/runtime control commands such as health and lifecycle control. |
| Event bus | Exists / Partial | `packages/runtime-core/src/event_bus/**` | Queue, subscribe, and dispatch deterministic runtime events. |
| Determinism guard | Exists / Partial | `packages/runtime-core/src/determinism_guard/**` | Hash, replay, and validate deterministic runtime execution. |
| Component tables | Exists / Partial | `packages/runtime-core/src/component_tables/**` | Store deterministic component data by entity/archetype. |
| Snapshot engine | Exists / Partial | `packages/runtime-core/src/snapshot_engine/**` | Serialize, store, and recover world snapshots. |
| Mutation gate | Exists / Partial | `packages/runtime-core/src/mutation_gate/**` | Validate and queue schema/runtime mutations at safe tick boundaries. |
| Phase orchestrator | Exists / Partial | `packages/runtime-core/src/phase_orchestrator/**` | Run systems in deterministic phase order. |
| Query engine | Exists / Partial | `packages/runtime-core/src/query_engine/**` | Provide deterministic entity/component queries to systems. |
| Godot adapter | Live validated | `adapters/godot/*.gd`, `adapters/godot/*.tscn`, `adapters/godot/project.godot` | Connect Godot to runtime, collect input, apply deltas, render debug/game entities, expose HUD. Installed Godot validation now proves connection, snapshots, input, feedback, and clean protocol. |
| Unity adapter | Live validated | `adapters/unity/*.cs`, `adapters/unity/Editor/*.cs` | Unity-side transport, input collection, delta application, console UI, setup menu, and editor validation. Real Unity 6000 live validation now proves connection, snapshots, input, entity application, and feedback. |
| Unreal adapter | Live validated | `adapters/unreal/*.h`, `adapters/unreal/*.cpp` | Unreal-side transport, input collection, delta application, console UI, and commandlet validation. Real Unreal 5.7 validation now proves connection, snapshots, input, entity application, and feedback. |
| Engine adapter crate | Exists / Partial | `packages/engine-adapter/src/**` | Shared adapter protocol, transports, delta sync, FFI, and authority contracts. |
| Engine feedback | Exists / Partial | `packages/engine-feedback/src/**` | Validate, route, record, and replay engine feedback at deterministic boundaries. |
| Builder workspace | Partial | `packages/builder-workspace/src/**`, `packages/builder-workspace/server/**` | Creator UI, websocket bridge, project/session state, runtime controls, preview, panels. |
| Legacy builder workspace | Archived | `docs/WORKSPACE_BUILDER_ARCHIVE.md` | Placeholder TSX package archived; `packages/builder-workspace` is canonical. |
| Asset registry | Partial | `packages/asset-registry/**`, `packages/core/src/assets/**`, `packages/builder-workspace/src/panels/asset_*` | Track typed asset references, manifests, link/repair state, and builder asset UI. |
| DCL schemas | Partial | `packages/dcl/**`, `packages/core/src/ucl/**` | Domain component definitions and schema loading/validation surface. |
| GDE | Partial | `packages/gde/src/**` | Safely interpret and apply schema mutations through domain DSL/path addressing. |
| Prompt intelligence | Partial | `packages/prompt-intelligence/src/**` | Normalize prompts, assemble context, plan mutations, validate risk, and generate outputs. |
| Inference | Partial | `packages/inference/src/**`, `packages/inference/providers/**` | BYOK/provider routing, model selection, retry, budget, telemetry, local mode. |
| Network core | Partial | `packages/network-core/src/**` | Network primitives for lockstep-style input, prediction/reconciliation, replication concepts, authority, desync detection, and session lifecycle smokes. |
| Save engine | Partial | `packages/save-engine/src/**`, `packages/save-engine/*.py` | Save slots, checkpoints, serialization, migration, profile/cloud concepts. |
| Tooling | Partial | `tools/cgs_maker.py`, `tools/xace_builder_launch.py`, `tools/xace_godot_dev.py`, `tools/certify_launch.py`, `tools/runtime_bridge_smoke.py`, `tools/three_engine_runtime_smoke.py`, `tools/phase15_integration_check.py` | Local bootstrap, one-click Builder launch, CGS generation, Godot dev loop, bridge/network smoke checks, and launch certification. |
| Example project | Partial | `projects/zombie_chase/game.cgs.json`, `examples/zombie-chase/**` | Current playable/reference vertical slice and deterministic gameplay tests. |
| Certification tests | Partial | `tests/determinism/**`, package `tests/**` | Prove deterministic replay, networking, feedback, save, bridge, and schema behavior. |
| Docs | Partial | `README.md`, `docs/**`, `MASTER_PLAN.md`, `XACE_FILE_MANIFEST(LATEST).md` | Boundary, architecture, launch plan, user guides, troubleshooting. |

## Launch Build Order

| Step | Slice | Exit Criteria | Core Files |
|---:|---|---|---|
| 1 | Godot playability | Player input feels responsive, player stays in map, camera follows, smoke test passes. | `adapters/godot/*`, `runtime-core` protocol/systems, `tools/xace_godot_dev.py`, Godot smoke docs/tests. |
| 2 | Keybinding/action mapping | Runtime accepts semantic actions like `Jump`, `Attack`, `Pickup`, adapters remap device input, builder can edit mappings. | `core/ucl/input_component.rs`, `runtime-core/engine_protocol.rs`, adapters, builder input panel. |
| 3 | Interaction runtime | Proximity/focus/prompt/authority events work for general creator-defined interactions. | `core/ucl/interaction_component.rs`, `runtime-core/builtin_systems.rs`, `event_bus`, adapters, builder inspector. |
| 4 | Inventory/equipment | Generic pickup/drop/equip state persists and engine can attach items to sockets. | `core/ucl/inventory_component.rs`, `dcl/rpg`, runtime systems, save engine, adapter commands. |
| 5 | Semantic events | Registry, canonical names, binding metadata, timeline/persistence flags, and replay tests exist. | `core/events/**`, `runtime-core/event_bus/**`, builder timeline. |
| 6 | Animation/audio/VFX bindings | Semantic event bindings resolve to typed playback commands and show in builder UI. | `core/assets/**`, `runtime-core/engine_protocol.rs`, adapters, builder binding panels. |
| 7 | Asset import/link | Drag/drop or dialog imports/link assets, hashes them, repairs missing refs, resolves per engine. | `packages/asset-registry/**`, builder asset panels, adapters. |
| 8 | Project creation/templates | New/open/wrap-link project flows create manifest, starter CGS, adapter config, and playable templates. | builder project UI/server, `tools/cgs_maker.py`, `projects/**`, docs. |
| 9 | Godot package | Godot adapter ships as installable plugin with example project and smoke. | `adapters/godot/**`, package metadata, quickstart. |
| 10 | Unity validation | Unity package compiles and runs real smoke. | `adapters/unity/**`, engine-adapter contracts, smoke docs. |
| 11 | Unreal validation | Unreal plugin compiles and runs real smoke. | `adapters/unreal/**`, engine-adapter contracts, smoke docs. |
| 12 | Bidirectional edit loop | Engine selection/transform edits roundtrip safely through XACE authority and audit logs. | adapters, `runtime-core/control_*`, GDE/PIL mutation paths, builder inspector. |
| 13 | Save/load replay hash | Save/load includes CGS + asset hash and replay verifies same world hash. | save engine, runtime snapshots, determinism tests. |
| 14 | Network primitives smoke | Host/client flow, lockstep input, prediction/reconciliation, desync UI, smoke tests for primitives. | network-core, runtime bridge, builder network panel, adapters. |
| 15 | Certification command | One command runs runtime, builder bridge, adapters/smokes, replay, save, asset, edit, migration tests. | `tools/**`, package tests, root scripts. |
| 16 | Builder UX polish | Dashboard, controls, health, inspectors, asset browser, timelines, provider settings are coherent. | `packages/builder-workspace/src/**`. |
| 17 | Packaging/docs | Installer/dev bootstrap, adapter packages, examples, getting started, troubleshooting. | root scripts, docs, package manifests. |

## First Slice: Godot Playability

Status: complete for the first playable check. Runtime movement/input fixes are implemented and covered by Rust tests; user play-test confirmed the player moves, the zombie chases, and death occurs.

Goal:

- Make the existing Godot vertical slice feel like a real playable preview before building deeper creator systems.

Files to inspect before editing:

| File | Single Responsibility |
|---|---|
| `adapters/godot/xace_input_collector.gd` | Convert Godot keyboard/mouse/controller state into runtime input messages. |
| `adapters/godot/xace_delta_applicator.gd` | Apply runtime snapshots/deltas to Godot scene nodes. |
| `adapters/godot/xace_entity_manager.gd` | Own entity node creation, lookup, and transform updates in Godot. |
| `adapters/godot/xace_adapter.gd` | Coordinate transport, input, delta application, and adapter lifecycle. |
| `adapters/godot/xace_godot_main.gd` | Godot scene entry point and camera/viewport integration. |
| `adapters/godot/xace_debug_hud.gd` | Show runtime/adapter health and debug values. |
| `packages/runtime-core/src/engine_protocol.rs` | Runtime-side protocol types for input, snapshots, deltas, and adapter commands. |
| `packages/runtime-core/src/builtin_systems.rs` | Current movement/gameplay systems that consume input and mutate entity state. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime tick flow and snapshot production. |
| `projects/zombie_chase/game.cgs.json` | Current CGS used by the Godot/dev smoke flow. |
| `tools/xace_godot_dev.py` | One-command local Godot/runtime dev launcher. |
| `tools/runtime_bridge_smoke.py` | Bridge smoke coverage for runtime protocol health. |

Minimum build target:

- [x] Add or verify action-based input packet shape.
- [x] Clamp or enforce player world bounds deterministically when transform bounds are present.
- [x] Add camera-follow adapter behavior without moving rendering responsibility into XACE.
- [x] Add runtime tests that prove idle input stops velocity and bounded movement clamps.
- [x] Run Godot visual smoke after `godot` is available on PATH.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/runtime-core/src/builtin_systems.rs` | Built-in prototype gameplay systems. | Input now writes zero velocity for idle input, preserves velocity/transform metadata, and clamps X/Z movement to optional transform bounds. |
| `adapters/godot/xace_adapter.gd` | Coordinate Godot transport, input, delta application, and feedback. | Avoids resending identical actions for the same target runtime tick. |
| `adapters/godot/xace_entity_manager.gd` | Own Godot entity nodes and transform updates. | Adds transform interpolation for smoother runtime delta display. |
| `adapters/godot/xace_godot_main.gd` | Godot scene entry point and preview world. | Enables idle movement emission and camera follow for entity `1`. |
| `projects/zombie_chase/game.cgs.json` | Current Godot/dev zombie chase CGS. | Adds player transform bounds matching the 24x24 preview floor. |
| `game.cgs.json` | Root starter CGS. | Adds the same player transform bounds for root-level runtime/dev flows. |

Verification:

- `cargo test -p xace-runtime-core --lib` passes: 551 tests.
- `cargo test -p xace-runtime-core` currently fails only in pre-existing doctests where prose diagrams are treated as Rust code examples.
- User play-test confirmed: player moved, zombie chased, zombie killed player. Next balancing/polish can happen later.

## Second Slice: Keybinding / Action Mapping

Status: runtime/adapter foundation complete; builder keybinding editor still pending.

Goal:

- Move from hard-coded movement-only input toward semantic actions that gameplay systems and creator UI can reason about: `Move`, `Attack`, `Pickup`/`Interact`, `Dash`, and later `Jump`.

Minimum build target:

- [x] Runtime stores semantic button/axis state in the input component.
- [x] Godot adapter exposes a clear default action profile.
- [x] Runtime accepts both current lowercase wire actions and future PascalCase semantic actions.
- [x] Tests prove `attack`, `interact`/`pickup`, and `dash` survive engine input application.
- [x] Launch map records files and next UI follow-up.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/runtime-core/src/runtime_orchestrator.rs` | Convert engine packets into authoritative runtime input components. | Adds deterministic packet-to-input JSON mapping for movement plus `Attack`, `Interact`, `Pickup`, and `Dash`; accepts lowercase and PascalCase aliases. |
| `adapters/godot/xace_input_collector.gd` | Convert Godot input actions into runtime semantic action packets. | Adds `get_action_profile()` and sends button actions as creator-facing semantic names while preserving movement axes. |

Verification:

- `cargo test -p xace-runtime-core --lib runtime_orchestrator::tests --target-dir target-codex-input-map` passes: 2 tests.
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-input-map` passes: 553 tests.
- Default `target` test executable was locked by Windows during one run, so verification used a separate target directory.

Follow-up for builder UX:

- Add a keybinding/action mapping panel after interaction/inventory have enough actions to edit meaningfully. The runtime can now carry those semantic actions.

Files to inspect before editing:

| File | Single Responsibility |
|---|---|
| `adapters/godot/xace_input_collector.gd` | Convert Godot input actions into runtime semantic action packets. |
| `adapters/godot/xace_godot_main.gd` | Install the default Godot action map for the starter scene. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Convert engine packets into authoritative runtime input components. |
| `packages/runtime-core/src/engine_protocol.rs` | Define and validate engine input packet/action payloads. |
| `packages/network-core/src/input/input_packet.rs` | Shared validated input packet/action model. |

## Third Slice: General Interaction Runtime

Status: runtime foundation complete; adapter visual feedback and builder interaction editor still pending.

Goal:

- Add a general interaction layer for creator-defined actions such as open, activate, talk, pick up, inspect, use, custom prompts, and later game-specific behaviors. This slice must not hard-code sword/combat/single-template logic.

Minimum build target:

- [x] Runtime finds nearest interactable entity within range.
- [x] Runtime writes focus/prompt state onto the actor input component for adapters/builders to display.
- [x] Runtime accepts semantic interaction intents from the input component.
- [x] Runtime emits deterministic interaction domain events.
- [x] Runtime updates general interaction bookkeeping on the target entity.
- [x] CGS loader recognizes `COMP_INTERACTION_V1`.
- [x] Tests prove focus and accepted interaction behavior.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/runtime-core/src/builtin_systems.rs` | Built-in prototype gameplay/runtime systems. | Adds `InteractionSystem`: proximity focus, prompt state, intent acceptance, interaction count/tick bookkeeping, and domain events such as `interaction.focused`, `interaction.unfocused`, `interaction.interacted`, and `interaction.accepted`. |
| `packages/runtime-core/src/cgs_loader.rs` | Load and validate CGS into runtime component/system registrations. | Registers `COMP_INTERACTION_V1` and permits `InteractionSystem` as a built-in runtime system. |

Verification:

- `cargo test -p xace-runtime-core --lib builtin_systems::tests::interaction --target-dir target-codex-interaction` passes: 2 tests.
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-interaction` passes: 555 tests.
- Verification used a separate target directory because the default Windows build target was previously locked by another process.

Follow-up for builder/adapter UX:

- Show focused entity highlight/prompt in Godot.
- Add builder interaction inspector for interaction type, prompt, range, enabled state, and max-use rules.
- Route accepted interaction events into future inventory/equipment, dialogue, doors, triggers, quests, and custom creator systems.

Files to inspect before the next interaction UX pass:

| File | Single Responsibility |
|---|---|
| `packages/runtime-core/src/builtin_systems.rs` | Own current runtime focus/intent/acceptance logic. |
| `packages/runtime-core/src/cgs_loader.rs` | Register interaction components and built-in systems from CGS. |
| `adapters/godot/xace_entity_manager.gd` | Apply focus/highlight state to live Godot nodes. |
| `adapters/godot/xace_debug_hud.gd` | Surface current focus/prompt/debug state. |
| `packages/builder-workspace/src/**` | Later creator UI for editing interaction components and viewing prompts/events. |

## Fourth Slice: Generic Inventory / Equipment Runtime

Status: runtime foundation complete; Godot visual attach/hide behavior, save integration, and builder inventory inspector still pending.

Goal:

- Add a general inventory/equipment layer for creator-defined items such as keys, tools, weapons, consumables, quest items, resources, armor, props, or custom game objects. This slice must not hard-code sword, shooter, RPG, or single-template behavior.

Minimum build target:

- [x] Define/register a general item component outside the frozen UCL surface.
- [x] Runtime can pick up a focused item into an inventory.
- [x] Runtime enforces basic capacity and weight limits.
- [x] Runtime can equip an inventory slot.
- [x] Runtime can drop an equipped/selected item back into the world.
- [x] Runtime emits deterministic inventory domain events.
- [x] Tests prove pickup, equip, and drop behavior.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/runtime-core/src/builtin_systems.rs` | Built-in prototype gameplay/runtime systems. | Adds `InventorySystem`: generic pickup/equip/drop intent handling, inventory slot bookkeeping, item ownership/world-state updates, interaction enable/disable, drop transform placement, and events such as `inventory.pickup_accepted`, `inventory.equipped`, and `inventory.dropped`. |
| `packages/runtime-core/src/cgs_loader.rs` | Load and validate CGS into runtime component/system registrations. | Registers `COMP_INVENTORY_V1`, `COMP_ITEM_V1`, and permits `InventorySystem` as a built-in runtime system. |
| `packages/dcl/rpg/__init__.py` | Declare RPG-adjacent DCL components. | Adds general `COMP_ITEM_V1` with item identity, quantity, slot type, weight, owner, slot id, equipped flag, and world state. |

Verification:

- `cargo test -p xace-runtime-core --lib inventory_system --target-dir target-codex-inventory-2` passes: 3 tests.
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-inventory-2` passes: 558 tests.
- `python -c "from packages.dcl.rpg import get_domain_package; pkg=get_domain_package(); pkg.validate(); names=[c.type_name for c in pkg.components]; print(len(pkg.components)); print('COMP_ITEM_V1' in names)"` prints `6` and `True`.
- A first test attempt using `target-codex-inventory` hit a Windows linker file lock, so verification used `target-codex-inventory-2`.

Follow-up for creator/product UX:

- Add Godot adapter behavior for hiding held items, showing dropped items, and attaching equipped items to named sockets/bones.
- Add builder inventory/item inspector for capacity, weight, slot type, pickable state, and equipped state.
- Wire inventory state into save/load replay hash.
- Add template CGS examples once adapter visual behavior exists.

Files to inspect before the next inventory UX pass:

| File | Single Responsibility |
|---|---|
| `packages/runtime-core/src/builtin_systems.rs` | Own current runtime pickup/equip/drop authority logic. |
| `packages/runtime-core/src/cgs_loader.rs` | Register inventory/item components and built-in systems from CGS. |
| `packages/dcl/rpg/__init__.py` | Define inventory/item schemas exposed to creator tooling. |
| `adapters/godot/xace_entity_manager.gd` | Later hide/restore/attach item nodes based on runtime item state. |
| `packages/builder-workspace/src/sidebar/component_inspector.ts` | Later inspect/edit item and inventory fields. |

## Fifth Slice: Semantic Event Registry

Status: core registry foundation complete; builder event timeline, binding editor, event persistence policy UI, and adapter playback routing still pending.

Goal:

- Make semantic events first-class creator contracts instead of loose strings. Runtime can still emit `EventType::Domain(name)`, but builder/adapters can now discover canonical names, categories, required payload keys, binding targets, and replay/persistence intent from one shared registry.

Minimum build target:

- [x] Add canonical semantic event names for interaction and inventory events already emitted by runtime.
- [x] Add starter canonical names for combat, animation, audio, and VFX so future binding slices have stable targets.
- [x] Track event category/domain.
- [x] Track required payload keys for validation and builder inspection.
- [x] Track valid binding targets such as builder timeline, animation, audio, and VFX.
- [x] Track whether an event is persistent and replay-relevant.
- [x] Runtime systems use registry constants instead of scattered raw strings.
- [x] Tests prove registry uniqueness, lookup, domain matching, and binding discovery.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/core/src/events/semantic_event_registry.rs` | Own canonical semantic event definitions shared by runtime, builder, adapters, and binding workflows. | Adds semantic event constants, `SemanticEventDefinition`, categories, binding targets, built-in registry, lookup helpers, and tests. |
| `packages/core/src/events/mod.rs` | Expose event module surface. | Exports the semantic event registry module. |
| `packages/runtime-core/src/builtin_systems.rs` | Built-in gameplay/runtime systems. | Uses registry constants/helpers for interaction and inventory domain event emission. |

Verification:

- `cargo test -p xace-core semantic_event_registry --target-dir target-codex-semantic-events` passes: 4 tests.
- `cargo test -p xace-core --lib --target-dir target-codex-semantic-events` passes: 494 tests.
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-semantic-events` passes: 558 tests.

Follow-up for event productization:

- Add builder event timeline using registry categories and replay flags.
- Validate semantic event bindings against required payload keys.
- Route registry events into animation/audio/VFX binding tables.
- Add event persistence/replay policy tests once save/replay integration is wired.

Files to inspect before the next binding pass:

| File | Single Responsibility |
|---|---|
| `packages/core/src/events/semantic_event_registry.rs` | Canonical event names and binding metadata. |
| `packages/core/src/events/event_type.rs` | Domain event carrier type used by runtime systems. |
| `packages/runtime-core/src/event_bus/**` | Deterministic event queue, dispatch, subscription, and replay surface. |
| `packages/runtime-core/src/builtin_systems.rs` | Current interaction/inventory event emitters. |
| `packages/builder-workspace/src/preview/tick_debugger.ts` | Possible starting point for visible event timeline/debug UI. |

## Sixth Slice: Semantic Playback Bindings

Status: shared binding/protocol foundation complete; runtime event-bus integration, Godot playback implementation, and builder binding UI still pending.

Goal:

- Let creators bind semantic events to animation, audio, or VFX assets in a general way. The binding model must stay engine-agnostic and genre-neutral: no sword, gun, zombie, or single-template assumptions.

Minimum build target:

- [x] Add an `AnimationClip` asset type so bindings can distinguish animation controllers from individual clips.
- [x] Add a typed semantic binding model for animation/audio/VFX playback.
- [x] Validate event names against the semantic event registry.
- [x] Validate asset type matches playback kind.
- [x] Resolve target entity from source entity, target entity, fixed entity, or event payload entity key.
- [x] Convert matched event bindings into deterministic playback command requests.
- [x] Add runtime/adapter protocol structs for playback command batches.
- [x] Teach Godot protocol validation to accept future `playback_commands` messages.
- [x] Tests prove binding validation, command resolution, deterministic ordering, and protocol validation.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/core/src/assets/asset_type.rs` | Define typed asset categories for the asset pipeline and adapters. | Adds `AnimationClip` alongside `AnimationController`. |
| `packages/core/src/assets/semantic_binding.rs` | Own engine-agnostic semantic event to playback asset bindings. | Adds `SemanticAssetBinding`, `SemanticBindingTable`, entity selectors, playback kinds, validation, command resolution, and tests. |
| `packages/core/src/assets/mod.rs` | Expose asset module surface. | Exports semantic binding types. |
| `packages/core/src/lib.rs` | Expose shared core modules. | Exposes `assets`, which already existed on disk but was not part of the public core API. |
| `packages/runtime-core/src/engine_protocol.rs` | Runtime-side engine adapter protocol payloads. | Adds `EnginePlaybackCommand`, `EnginePlaybackCommandBatch`, `playback_commands` message type, validation, and tests. |
| `adapters/godot/xace_protocol.gd` | Godot-side wire protocol validation. | Accepts future `playback_commands` frames with a tick and command array. |

Verification:

- `cargo test -p xace-core assets::semantic_binding --target-dir target-codex-bindings` passes: 6 tests.
- `cargo test -p xace-core assets::asset_type --target-dir target-codex-bindings` passes: 11 tests.
- `cargo test -p xace-runtime-core --lib engine_protocol --target-dir target-codex-bindings` passes: 7 tests.
- `cargo test -p xace-core --lib --target-dir target-codex-bindings` passes: 529 tests.
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-bindings` passes: 560 tests.

Follow-up for actual playback:

- Wire a runtime binding table into CGS/project config.
- Have runtime collect emitted semantic events and resolve playback commands each tick.
- Send playback commands to adapters through snapshots or a command stream.
- Implement Godot playback handlers for animation/audio/VFX commands.
- Add builder binding editor: event picker, target selector, asset picker, preview/test button.

Files to inspect before wiring runtime playback:

| File | Single Responsibility |
|---|---|
| `packages/core/src/assets/semantic_binding.rs` | Shared binding and command-resolution model. |
| `packages/runtime-core/src/engine_protocol.rs` | Adapter-facing playback command payloads. |
| `packages/runtime-core/src/event_bus/**` | Source of emitted semantic events. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Likely place to expose per-tick events/commands to snapshots. |
| `adapters/godot/xace_protocol.gd` | Godot frame validation for future playback commands. |
| `adapters/godot/xace_delta_applicator.gd` | Likely place to route playback commands once included in tick snapshots. |

## Seventh Slice: Asset Import / Link Workflow

Status: shared asset import workflow foundation complete; builder drag/drop UI, engine-specific resolver previews, and project-manifest persistence still pending.

Goal:

- Give creators one general asset workflow for meshes, textures, materials, animation clips/controllers, audio, VFX, prefabs, sprites, and fonts. This slice must stay engine-neutral and genre-neutral: imported assets become deterministic typed references first, then adapters decide how to load them.

Minimum build target:

- [x] Add Python asset registry support for `ANIMATION_CLIP` to match the shared core asset type.
- [x] Infer asset type from file extension plus conservative filename hints.
- [x] Scan folders recursively in deterministic order.
- [x] Hash imported files with SHA-256.
- [x] Produce skipped-file reasons for unsupported files.
- [x] Link imported assets in place.
- [x] Copy imported assets into a project asset root when requested.
- [x] Generate deterministic asset IDs and version duplicates.
- [x] Suggest candidate repairs for missing same-type assets.
- [x] Tests prove scan/import/copy/repair behavior.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/asset-registry/asset_import_workflow.py` | Own deterministic folder scan, import policy, file hashing, manifest linking, copy-to-project behavior, and missing asset repair suggestions. | Adds `AssetImportWorkflow`, `AssetCopyPolicy`, `ImportPlan`, `ImportResult`, `ScannedAsset`, `ImportedAsset`, and `RepairSuggestion`. |
| `packages/asset-registry/asset_type_enum.py` | Define Python-side typed asset categories for asset registry workflows. | Adds `ANIMATION_CLIP`, placeholder behavior, and animation-related classification. |
| `packages/asset-registry/asset_naming_policy.py` | Generate and parse canonical asset IDs. | Adds the `anim_clip` suffix and validation support. |
| `packages/asset-registry/asset_linker.py` | Validate and audit asset link transitions. | Allows animation clip file extensions such as `.anim`, `.fbx`, `.glb`, `.uasset`, `.res`, and `.tres`. |
| `packages/asset-registry/tests/test_asset_import_workflow.py` | Verify deterministic asset import workflow behavior. | Covers type inference, deterministic scan order, SHA-256 hashing, link-in-place import, copy-to-project import, duplicate ID versioning, and repair suggestions. |
| `packages/asset-registry/tests/test_asset_validation.py` | Verify asset enum, naming, validation, and animation contract behavior. | Updates enum coverage from 10 to 11 types and checks animation clip classification. |
| `packages/asset-registry/tests/test_asset_manifest.py` | Verify manifest/linker/engine sync integration behavior. | Fixes a duplicate test setup registration so the asset registry suite can run cleanly. |

Verification:

- `python -m unittest "packages/asset-registry/tests/test_asset_import_workflow.py"` passes: 6 tests.
- `python -m unittest discover "packages/asset-registry/tests"` passes: 200 tests.

Follow-up for creator/product UX:

- Add builder drag/drop and file-picker UI using `AssetImportWorkflow.scan_folder()` preview data.
- Persist imported asset manifests in the project manifest once the project system exists.
- Add per-engine resolver previews for Godot `.tscn/.tres/.glb`, Unity prefabs/materials/controllers, and Unreal `.uasset` references.
- Add repair UI that shows missing assets and one-click candidate relinking.
- Feed imported asset IDs into semantic animation/audio/VFX binding editors.

Files to inspect before the builder asset UX pass:

| File | Single Responsibility |
|---|---|
| `packages/asset-registry/asset_import_workflow.py` | Shared import/link/repair workflow. |
| `packages/asset-registry/asset_manifest.py` | Authoritative in-memory asset reference store. |
| `packages/asset-registry/asset_linker.py` | Authoritative PLACEHOLDER/MISSING to LINKED transition path. |
| `packages/builder-workspace/src/panels/asset_status_panel.ts` | Existing builder asset status UI entry point. |
| `packages/builder-workspace/src/panels/asset_link_dialog.ts` | Existing builder manual link dialog entry point. |
| `packages/core/src/assets/semantic_binding.rs` | Future consumer of imported animation/audio/VFX asset IDs. |

## Eighth Slice: Project Creation / Templates Foundation

Status: shared project manifest, starter template catalog, CLI creation, builder server project endpoints, and visible New Project UI complete; full Open/Wrap-Link project UI still pending.

Goal:

- Make project creation a first-class XACE workflow instead of a loose `game.cgs.json` script. A new project now has a manifest, selected engine, starter CGS, asset root, save folders, adapter config, and model-provider defaults. Templates stay general and engine-neutral; they do not hard-code one game type as the platform path.

Minimum build target:

- [x] Define a project manifest contract: engine type, CGS path, asset root, adapter config, save slots, and model provider config.
- [x] Add supported engine targets: Godot, Unity, Unreal, and headless.
- [x] Add a starter template catalog: blank 3D, top-down adventure, FPS prototype, third-person, RPG, horror chase, action combat, multiplayer lobby.
- [x] Keep legacy template aliases working: `empty`, `zombie_chase`, `sword_combat`, etc.
- [x] Generate starter CGS from the template catalog with stable CGS hashes.
- [x] Create standard project folders: `assets/`, `saves/`, `.xace/snapshots/`, `.xace/adapter/`.
- [x] Write `xace.project.json` and `game.cgs.json` from one shared project creator.
- [x] Update `tools/cgs_maker.py` and `tools/xace_godot_dev.py` to use the project system.
- [x] Add builder server endpoints for project info, template list, create project, and import existing engine project.
- [x] Tests prove template catalog, stable hashes, manifest creation, overwrite safety, legacy project open behavior, and wrapping a nonempty engine project folder.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/project-system/project_manifest.py` | Own the serialized XACE project manifest contract. | Adds `XaceProjectManifest`, engine validation, default adapter capabilities, save slots, model provider defaults, load/save helpers. |
| `packages/project-system/project_templates.py` | Own starter template catalog and CGS generation. | Adds 8 launch starter templates, legacy aliases, stable CGS hashing, generic actor/component helpers, and runtime-system-ready template CGS generation. |
| `packages/project-system/project_creator.py` | Own create/open/wrap-link project filesystem workflows. | Creates manifest, CGS, asset/save/.xace folders, adapter config, safe overwrite behavior, legacy open fallback, and engine project wrap/link. |
| `packages/project-system/tests/test_project_system.py` | Verify the project system contract. | Covers catalog entries, aliases, stable hashes, project file creation, overwrite refusal, legacy CGS-only open, and existing engine project wrapping. |
| `tools/cgs_maker.py` | CLI for creating starter XACE projects. | Delegates to the shared project system and now writes both `xace.project.json` and `game.cgs.json`. |
| `tools/xace_godot_dev.py` | One-command Godot dev loop launcher. | Uses the shared project creator and expanded template list. |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server. | Adds `/api/project`, `/api/project/templates`, `/api/project/create`, and `/api/project/import-engine`. |

Verification:

- `python -m unittest discover "packages/project-system/tests"` passes: 6 tests.
- `python tools/cgs_maker.py --project .\target-codex-project-system-smoke --template rpg --engine godot --name "Codex Project Smoke" --force` creates manifest, CGS, assets, saves, and `.xace` folders.
- `python -m py_compile tools/cgs_maker.py tools/xace_godot_dev.py packages/builder-workspace/server/builder_server.py packages/project-system/project_manifest.py packages/project-system/project_templates.py packages/project-system/project_creator.py` passes.
- `python -c "import sys, tempfile; from pathlib import Path; sys.path.insert(0, 'packages/builder-workspace/server'); from builder_server import create_app; d=tempfile.mkdtemp(); app=create_app(project_path=d, dev_mode=True); print(app.title)"` prints `XACE Builder Server`.
- `target-codex-xace-godot-dev\debug\xace_runtime.exe --cgs target-codex-project-system-smoke\game.cgs.json --no-wait --no-control --ticks 2 --quiet` loads the generated RPG CGS: 2 actors, 2 entities, 2 runtime systems.
- `cargo test -p xace-runtime-core --lib cgs_loader --target-dir target-codex-bindings` passes: 1 loader test. A fresh `target-codex-project-system` run failed while compiling third-party dependency build scripts on Windows before XACE code ran, so the warmed target was used.

Follow-up for creator/product UX:

- Build the full Open/Wrap-Link Project screens on top of these endpoints.
- Persist recent projects and show clear missing-CGS/manifest repair actions.
- Make engine project import install/copy the adapter package for each engine.
- Add template preview metadata and screenshots once visual template projects exist.
- Add one command that creates a project, starts runtime, starts builder, and launches the selected adapter.

Files to inspect before the project UI pass:

| File | Single Responsibility |
|---|---|
| `packages/project-system/project_creator.py` | Shared create/open/wrap-link project workflow. |
| `packages/project-system/project_manifest.py` | Project manifest schema and defaults. |
| `packages/project-system/project_templates.py` | Starter template catalog and CGS generation. |
| `packages/builder-workspace/server/builder_server.py` | REST endpoints the builder UI should call. |
| `packages/builder-workspace/src/layout/main_layout.ts` | Current builder shell where project dashboard/actions can be added. |
| `tools/xace_godot_dev.py` | Current one-command Godot path to evolve into general engine launch. |

## Ninth Slice: Builder Project Dashboard / New Project UI

Status: visible project dashboard and New Project flow complete for the current builder shell. Open/Wrap-Link project screens landed in the next slice; adapter install actions remain pending.

Goal:

- Give non-technical creators a visible place in Builder to see the active project and create a new XACE project without using CLI commands.

Minimum build target:

- [x] Add a compact Project button to the existing Builder top bar.
- [x] Show active project name, engine, template, folder, CGS path, asset root, and project warnings/errors.
- [x] Load starter templates from `/api/project/templates`.
- [x] Let creators choose Godot, Unity, Unreal, or Headless.
- [x] Let creators choose a template, enter project name and folder, and optionally replace starter files.
- [x] Create projects through `/api/project/create`.
- [x] Show success and error messages clearly.
- [x] Keep the UI dense and practical rather than a marketing page.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/src/project/project_dashboard.ts` | Own the visible project dashboard modal and New Project form. | Adds active project summary, engine selector, template selector, name/path fields, replace-starter-files checkbox, create-project API call, and clear status messaging. |
| `packages/builder-workspace/src/layout/main_layout.ts` | Own the main builder shell and top-bar controls. | Adds a compact Project button that opens the dashboard from the existing top bar. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Project Dashboard / New Project UI slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.

Follow-up for creator/product UX:

- Make switching active projects a launcher-owned action so users do not see terminal restart commands.
- Add template preview thumbnails or generated preview metadata once visual template assets exist.
- Add adapter install/copy actions after project creation for Godot, Unity, and Unreal.

Files to inspect before the next project UX pass:

| File | Single Responsibility |
|---|---|
| `packages/builder-workspace/src/project/project_dashboard.ts` | Current dashboard/new-project UI and API payload handling. |
| `packages/builder-workspace/server/builder_server.py` | Project REST endpoints and active project lifecycle. |
| `packages/project-system/project_creator.py` | Shared create/open/wrap-link project workflow. |
| `packages/project-system/project_templates.py` | Starter template catalog and metadata. |

## Tenth Slice: Open / Import Existing Project UI

Status: visible Open Project and Import Existing Engine Project flows complete for the current builder shell. Project switching and native folder picker support landed in the next slice.

Goal:

- Let creators validate an existing XACE project folder or wrap an existing Godot/Unity/Unreal project from the Builder dashboard, without needing CLI project-system commands.

Minimum build target:

- [x] Add an `/api/project/open` endpoint that validates a project folder with the shared project system.
- [x] Return `active` and `restart_required` flags from create/open/wrap-link project responses.
- [x] Add dashboard modes for New, Open, and Import.
- [x] Open Project accepts an existing XACE folder and shows whether it is active or needs a dev-server restart.
- [x] Wrap/Link Project accepts engine type, template, project name, engine project folder, XACE wrapper folder, and overwrite option.
- [x] Store recent projects locally in the browser and let users select one into the Open flow.
- [x] Keep messages honest about the current dev-server limitation and the launch-ready launcher path.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and project endpoints. | Adds `/api/project/open`; returns active/restart-required flags from create/open/wrap-link responses. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Own the visible project dashboard and project workflow forms. | Reworks the modal into New/Open/Wrap-Link modes, adds recent projects, engine project wrap/link form, and clearer switch/restart messaging. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Open / Import Existing Project UI slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.

Follow-up for creator/product UX:

- Install/copy the selected engine adapter during project creation/import.
- Add project repair actions for missing CGS, missing manifest, or missing adapter config.

Files to inspect before the launcher/switch pass:

| File | Single Responsibility |
|---|---|
| `packages/builder-workspace/server/builder_server.py` | Current REST endpoint behavior and dev-server project lifecycle. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Current project workflow UI and restart-required messaging. |
| `tools/xace_godot_dev.py` | Current dev launcher path that can evolve toward launcher-managed project startup. |
| `packages/project-system/project_creator.py` | Shared project validation/import behavior. |

## Eleventh Slice: Project Switching / Native Folder Picker

Status: launch-style project switching is complete inside the current local Builder server. Users can browse for folders, open/switch projects, and let the UI reload/reconnect without manually restarting the backend and frontend terminals. A packaged desktop launcher can later wrap the same behavior with a native app shell.

Goal:

- Remove terminal restart steps from the creator-facing project workflow. Opening or importing a project should switch Builder to that project and refresh the UI automatically.

Minimum build target:

- [x] Make the active builder project mutable inside the local server.
- [x] Add `/api/project/switch` to validate a project folder, rebind CGS persistence, reload CGS state, and mark the project active.
- [x] Add `/api/system/pick-folder` as a local-only native folder picker endpoint.
- [x] Add Browse buttons to project path fields.
- [x] Make Open Project switch the active project and reload the UI automatically.
- [x] Make Create/Import switch to the created/imported project when it is not already active.
- [x] Keep text fields as a fallback when a native picker is unavailable.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and local project lifecycle. | Adds mutable active project state, `/api/project/switch`, local-only `/api/system/pick-folder`, and rebinding of CGS persistence for project switches. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Own the visible project dashboard and project workflow forms. | Adds Browse buttons, folder-picker calls, automatic switch/reload behavior for Open/Create/Import, and removes creator-facing restart instructions. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the project switching/native folder picker slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.

Follow-up for creator/product UX:

- Add repair flows for invalid project folders.
- Consider a packaged desktop shell so the folder picker and backend lifecycle feel fully native outside dev mode.

Files to inspect before adapter-install/repair work:

| File | Single Responsibility |
|---|---|
| `packages/builder-workspace/server/builder_server.py` | Active project switching, folder picker, and project endpoints. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and automatic switch/reload behavior. |
| `packages/project-system/project_creator.py` | Project creation/import validation and filesystem behavior. |
| `adapters/godot/**`, `adapters/unity/**`, `adapters/unreal/**` | Adapter source folders to copy/install into selected projects. |

## Twelfth Slice: Automatic Adapter Install / Copy

Status: automatic adapter preparation is complete for project creation/import in the Builder server. Godot, Unity, and Unreal projects now receive the selected XACE adapter files under `.xace/adapter/<engine>/`; headless projects correctly skip adapter copy.

Goal:

- When a creator chooses Godot, Unity, or Unreal while creating/importing a project, XACE should prepare the matching adapter files automatically instead of requiring manual export/copy steps.

Minimum build target:

- [x] Copy selected adapter source into the project during `/api/project/create`.
- [x] Copy selected adapter source into the project during `/api/project/import-engine`.
- [x] Skip adapter copy for headless projects with a clear reason.
- [x] Return adapter install status, target, file list, and install path in API responses.
- [x] Show adapter install success/warning text in the Project Dashboard status message.
- [x] Keep installed adapter files inside `.xace/adapter/<engine>/` so they remain part of the XACE project wrapper.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and local project lifecycle. | Adds `_install_project_adapter()`, installs adapters during create/import, writes `xace_adapter_manifest.json`, and returns adapter install status. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and status messaging. | Displays adapter install success/warning text after create/import before switching/reloading the project. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the automatic adapter install/copy slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- Backend smoke creates a temporary Godot XACE project and installs the adapter: output `True godot 12 True True`, confirming `.xace/adapter/godot/` exists and contains `xace_adapter.gd`.

Follow-up for creator/product UX:

- Add engine-specific install guidance for copying from `.xace/adapter/<engine>/` into native Godot/Unity/Unreal project folders.
- Later, install directly into engine project plugin/package locations once each engine package format is validated.

Files to inspect before adapter repair/reinstall work:

| File | Single Responsibility |
|---|---|
| `packages/builder-workspace/server/builder_server.py` | Current adapter install helper and create/import endpoint responses. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Current project creation/import status messaging. |
| `adapters/godot/**`, `adapters/unity/**`, `adapters/unreal/**` | Source adapter payloads being installed into XACE projects. |
| `packages/project-system/project_manifest.py` | Adapter config defaults and future adapter install metadata location. |

## Thirteenth Slice: Adapter Health / Repair / Reinstall

Status: adapter health and repair actions are complete for the active Builder project. The dashboard now shows whether the selected engine adapter is installed, missing files, or skipped for headless projects, and creators can repair/reinstall the adapter without using terminal commands.

Goal:

- Make adapter setup recoverable for existing projects so users are not stuck if `.xace/adapter/<engine>/` is missing, stale, or partially deleted.

Minimum build target:

- [x] Report adapter health from the active project API.
- [x] Add a dedicated adapter status endpoint for the active project.
- [x] Add a reinstall/repair endpoint that re-copies the selected engine adapter.
- [x] Show adapter health in the Project Dashboard active-project summary.
- [x] Add a one-click Repair/Reinstall Adapter action for Godot, Unity, and Unreal projects.
- [x] Keep headless projects clear: no adapter is needed.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and local project lifecycle. | Adds `_adapter_status()`, returns adapter health from `/api/project`, and adds `/api/project/adapter/status` plus `/api/project/adapter/reinstall`. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and active project controls. | Shows adapter health in the active project summary and adds Repair/Reinstall Adapter. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the adapter health/repair/reinstall slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- Backend repair smoke creates a temporary Godot XACE project, deletes one installed adapter file, verifies the adapter is unhealthy, reinstalls it, and verifies it is healthy: output `False 1 True True 0`.

Follow-up for creator/product UX:

- Later, install directly into native engine plugin/package folders once each engine package format is validated.

Files to inspect before engine-specific adapter install guidance:

| File | Single Responsibility |
|---|---|
| `packages/builder-workspace/server/builder_server.py` | Adapter status, reinstall, and future engine install endpoints. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Active project adapter health and repair UI. |
| `adapters/godot/**`, `adapters/unity/**`, `adapters/unreal/**` | Engine adapter payloads and native install targets. |
| `packages/project-system/project_manifest.py` | Project manifest adapter config defaults and future install metadata. |

## Fourteenth Slice: Engine Adapter Copy Guidance / UI

Status: engine-specific adapter copy guidance and UI are complete for the active project. The Project Dashboard now has an Adapter tab that shows the prepared XACE adapter folder, explains where it will be copied for Godot, Unity, or Unreal, lets the user browse to the engine project folder, and copies the prepared files.

Goal:

- Let creators move from "XACE prepared the adapter" to "my engine project has the adapter files" without opening terminal commands or hunting through folders.

Minimum build target:

- [x] Add an adapter install-plan endpoint with source path, destination hint, saved engine project path, and engine-specific steps.
- [x] Add an adapter copy endpoint that copies the prepared adapter into the selected engine project.
- [x] Persist the selected engine project folder and last install destination in the project manifest adapter config.
- [x] Add an Adapter tab to the Project Dashboard.
- [x] Let users browse to the engine project folder and copy the adapter from the UI.
- [x] Keep copying conservative by default: existing files are skipped unless overwrite is selected.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and local project lifecycle. | Adds `/api/project/adapter/install-plan`, `/api/project/adapter/install-engine`, engine-specific destination helpers, and manifest persistence for selected engine project/install paths. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and active project controls. | Adds an Adapter tab, engine project folder picker, copy action, overwrite option, and engine-specific install steps. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the engine adapter copy guidance/UI slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- Backend copy smoke creates a temporary Godot XACE project and fake Godot engine project, then copies the adapter into the engine folder: output `True godot 10 1 True True`, confirming files copied, existing `project.godot` skipped, `xace_adapter.gd` exists, and `xace_engine_install_manifest.json` exists.

Follow-up for creator/product UX:

- Validate the Unity and Unreal copied adapter folders inside real Unity/Unreal projects.
- Later, replace conservative source-copy with fully packaged native engine plugins once each package format is validated.

Files to inspect before engine validation/package work:

| File | Single Responsibility |
|---|---|
| `packages/builder-workspace/server/builder_server.py` | Adapter copy endpoints and engine-specific destination rules. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Adapter tab and creator-facing copy flow. |
| `adapters/godot/**` | Godot adapter scripts, scene, and current root-level path assumptions. |
| `adapters/unity/**` | Unity C# adapter scripts copied to `Assets/XACE`. |
| `adapters/unreal/**` | Unreal C++ adapter sources copied to `Source/XACE`. |

## Fifteenth Slice: Godot Addon-Style Adapter Install

Status: Godot adapter copying now installs into a cleaner addon-style layout. Existing Godot projects receive files under `addons/xace/` instead of loose root files, with a generated `plugin.cfg` and minimal editor plugin script. The standalone adapter smoke project still keeps its root-level `project.godot` and starter scene behavior.

Goal:

- Make the Godot adapter feel like a normal Godot project addition and avoid cluttering or overwriting existing project root files.

Minimum build target:

- [x] Make Godot adapter scripts load sibling adapter scripts dynamically instead of hardcoding `res://xace_*.gd`.
- [x] Install copied Godot adapters to `addons/xace`.
- [x] Generate `plugin.cfg` and a minimal Godot editor plugin script during install.
- [x] Rewrite the copied starter scene script path to `res://addons/xace/xace_godot_main.gd`.
- [x] Skip copying `project.godot` into existing Godot projects.
- [x] Keep root-level smoke project files working for local adapter smoke/dev flows.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `adapters/godot/xace_adapter.gd` | Coordinate Godot transport, input, delta application, and feedback. | Loads sibling adapter scripts from its own folder so it can run from project root or `addons/xace`. |
| `adapters/godot/xace_godot_main.gd` | Godot starter scene entry point and preview world. | Loads sibling adapter scripts from its own folder so the starter scene works from the addon folder. |
| `adapters/godot/xace_transport.gd`, `adapters/godot/xace_input_collector.gd`, `adapters/godot/xace_entity_manager.gd`, `adapters/godot/xace_delta_applicator.gd` | Godot protocol, input, entity, and delta helpers. | Remove root-only protocol preloads and load `xace_protocol.gd` from the script's own folder. |
| `packages/builder-workspace/server/builder_server.py` | Builder adapter copy endpoints and engine-specific destination rules. | Changes Godot destination to `addons/xace`, rewrites copied starter scene paths, skips `project.godot`, and generates Godot plugin metadata. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Adapter tab and creator-facing copy flow. | Updates Godot copy instructions to match the addon location and plugin enable step. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Godot addon-style adapter install slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `rg "res://xace_|preload\(" adapters/godot` now reports only the intentional root smoke scene/project references.
- `where.exe godot` did not find Godot on PATH, so a real editor import smoke could not be run in this shell.
- Backend addon smoke creates a temporary Godot XACE project and fake Godot engine project, then verifies addon install behavior: output `True godot True True True True True False`, confirming `addons/xace` exists, `plugin.cfg` exists, `xace_editor_plugin.gd` exists, the copied scene points to `res://addons/xace/xace_godot_main.gd`, copied `xace_adapter.gd` has no `preload(` calls, and the engine project root does not receive `xace_adapter.gd`.

Follow-up for creator/product UX:

- Run a real Godot editor import/load smoke once Godot is available on PATH.
- Validate Unity and Unreal adapter copy flows inside real engine projects.

Files to inspect before the Godot editor smoke/scene setup pass:

| File | Single Responsibility |
|---|---|
| `adapters/godot/xace_godot_main.tscn` | Starter Godot scene used by smoke/addon copy. |
| `adapters/godot/xace_godot_main.gd` | Builds the preview scene and XACE node graph. |
| `adapters/godot/xace_adapter.gd` | Coordinates Godot adapter runtime connection and child nodes. |
| `packages/builder-workspace/server/builder_server.py` | Godot addon install generation and destination rules. |

## Sixteenth Slice: Godot One-Click Runtime Scene Setup

Status: Godot scene setup is complete at the filesystem level. The Project Dashboard can now create a ready-to-run Godot scene that uses the installed XACE addon and can optionally set it as the Godot project's main scene.

Goal:

- After copying the Godot addon, let users create the basic XACE runtime scene without manually making scene files or editing `project.godot`.

Minimum build target:

- [x] Add a Godot scene setup endpoint.
- [x] Create `scenes/xace_runtime_scene.tscn` referencing `res://addons/xace/xace_godot_main.gd`.
- [x] Ensure the Godot addon is installed before creating the setup scene.
- [x] Optionally set `run/main_scene` in `project.godot`.
- [x] Add a Project Dashboard `Setup Godot Scene` action.
- [x] Keep setup conservative: existing setup scenes are kept unless overwrite is selected.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder adapter copy/setup endpoints and engine-specific install rules. | Adds `/api/project/adapter/setup-godot-scene`, creates `scenes/xace_runtime_scene.tscn`, can update `project.godot`, and persists Godot setup metadata in adapter config. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Adapter tab and creator-facing copy/setup flow. | Adds `Setup Godot Scene` action and optional "set as main scene" checkbox for Godot projects. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Godot runtime scene setup slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- Backend Godot setup smoke creates a temporary XACE project and fake Godot project, runs scene setup with `set_main_scene=True`, and verifies scene creation, addon creation, scene script path, and `project.godot` main-scene update: output `True True True True True True True`.

Follow-up for creator/product UX:

- Run a real Godot editor import/load smoke once Godot is available on PATH.
- Move focus to Unity and Unreal adapter validation so the non-Godot paths are not left as package-source-only.

Files to inspect before Unity/Unreal validation:

| File | Single Responsibility |
|---|---|
| `adapters/unity/**` | Unity C# adapter scripts copied to `Assets/XACE`; needs real Unity compile/import smoke. |
| `adapters/unreal/**` | Unreal C++ adapter sources copied to `Source/XACE`; needs real Unreal module/plugin compile smoke. |
| `packages/builder-workspace/server/builder_server.py` | Engine-specific adapter destination and setup logic. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Adapter tab UX for all engine targets. |

## Seventeenth Slice: Unity Adapter Package Polish

Status: Unity adapter packaging is improved, but real Unity editor validation is still pending. The copied Unity adapter now lands as a clearer `Assets/XACE` package with assembly definition files, a README, and an editor menu item for creating the XACE runtime scene object.

Goal:

- Give Unity projects a practical adapter install shape instead of loose C# files only, so the next real Unity import/compile smoke has a clear target.

Minimum build target:

- [x] Add a Unity runtime assembly definition.
- [x] Add a Unity editor assembly definition.
- [x] Add a Unity editor menu item: `Tools > XACE > Create Runtime Object`.
- [x] Make the menu create or reuse an `XACE Runtime` GameObject and attach `XaceTransport`, `XaceInputCollector`, `XaceDeltaApplicator`, and `XaceConsoleWidget`.
- [x] Add Unity adapter README instructions.
- [x] Update Builder adapter instructions for Unity.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `adapters/unity/XACE.Adapter.Unity.asmdef` | Unity runtime assembly definition. | Adds package assembly metadata for runtime adapter scripts. |
| `adapters/unity/Editor/XACE.Adapter.Unity.Editor.asmdef` | Unity editor assembly definition. | Adds editor-only assembly metadata referencing the runtime adapter assembly. |
| `adapters/unity/Editor/XaceUnitySetupMenu.cs` | Unity editor setup helper. | Adds `Tools > XACE > Create Runtime Object` for one-click scene object setup. |
| `adapters/unity/README.md` | Unity adapter package instructions. | Documents install location and runtime-object setup steps. |
| `packages/builder-workspace/server/builder_server.py` | Builder adapter copy/setup endpoints and engine-specific install rules. | Updates Unity install guidance to describe the package layout and editor menu. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Adapter tab and creator-facing copy/setup flow. | Updates Unity adapter copy instructions shown in Builder. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Unity adapter package polish slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `where.exe Unity` did not find Unity on PATH, so real Unity import/compile validation could not be run in this shell.
- Backend Unity copy smoke creates a temporary Unity-shaped project and verifies package files land in `Assets/XACE`: output `True unity True True True True True`, confirming destination exists, runtime asmdef exists, editor setup menu exists, editor asmdef exists, and README exists.

Follow-up for creator/product UX:

- Run real Unity editor import/compile smoke with Unity installed.
- Add Unity scene/prefab asset generation if the editor menu is not enough for first-run setup.
- Run real Unreal editor/module compile smoke with Unreal installed.

Files to inspect before Unreal adapter polish:

| File | Single Responsibility |
|---|---|
| `adapters/unreal/**` | Unreal C++ adapter sources; needs module/plugin packaging and compile smoke. |
| `packages/builder-workspace/server/builder_server.py` | Engine-specific adapter destination and setup logic. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Adapter tab UX for all engine targets. |

## Eighteenth Slice: Unreal Adapter Plugin Package Polish

Status: Unreal adapter packaging is improved. This historical slice originally stopped before real editor/module validation; the Thirty-Seventh Slice now proves the packaged Unreal adapter in a real Unreal 5.7 installed-editor live validation.

Goal:

- Move Unreal from loose C++ source copy toward a normal Unreal plugin/module layout so the next real Unreal compile smoke has a clear package target.

Minimum build target:

- [x] Change Unreal copy destination from loose `Source/XACE` to `Plugins/XACE`.
- [x] Generate `XACE.uplugin`.
- [x] Generate `Source/XACEAdapter/XACEAdapter.Build.cs`.
- [x] Generate minimal Unreal module files.
- [x] Split copied Unreal `.h` files into `Public` and `.cpp` files into `Private`.
- [x] Add Unreal adapter README instructions.
- [x] Update Builder adapter instructions for Unreal.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `adapters/unreal/README.md` | Unreal adapter package instructions. | Documents install location and component setup steps. |
| `packages/builder-workspace/server/builder_server.py` | Builder adapter copy/setup endpoints and engine-specific install rules. | Installs Unreal as `Plugins/XACE`, routes headers/sources into module folders, and generates `.uplugin`, `Build.cs`, and module files. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Adapter tab and creator-facing copy/setup flow. | Updates Unreal adapter copy instructions shown in Builder. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Unreal adapter plugin package polish slice. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `where.exe UnrealEditor` did not find Unreal on PATH, so real Unreal module/plugin compile validation could not be run in this shell.
- Backend Unreal copy smoke creates a temporary Unreal-shaped project and verifies plugin files land in `Plugins/XACE`: output `True unreal True True True True True True`, confirming plugin destination exists, `.uplugin` exists, `Build.cs` exists, a Public header exists, a Private source exists, and README exists.

Follow-up for creator/product UX:

- Run a real Unreal editor/plugin compile smoke with Unreal installed.
- Fix any Unreal API/module compile issues found by the real editor smoke.
- Then build the "one runtime, three engines" demo launcher that starts one XACE runtime and connects Godot, Unity, and Unreal adapters as simultaneous clients.

Files to inspect before the three-engine demo work:

| File | Single Responsibility |
|---|---|
| `packages/runtime-core/src/tcp_server.rs` | Runtime TCP bridge that must accept multiple engine adapter clients. |
| `packages/runtime-core/src/engine_protocol.rs` | Shared runtime-to-engine and engine-to-runtime protocol. |
| `adapters/godot/**` | Godot client adapter. |
| `adapters/unity/**` | Unity client adapter. |
| `adapters/unreal/**` | Unreal client adapter. |
| `tools/xace_godot_dev.py` | Current single-engine dev launcher to generalize for multi-engine demo orchestration. |

## Nineteenth Slice: Three-Engine Runtime Bridge Readiness

Status: runtime multi-client bridge readiness is complete at the editor-free smoke level. One XACE runtime can now accept multiple engine adapter clients, broadcast the same authoritative tick snapshot to each client, and report a combined adapter type such as `multi(godot,unity,unreal)`.

Goal:

- Prepare the runtime side of the "one runtime, three engine renderers, same hash" demo before launching real Godot, Unity, and Unreal editors.

Minimum build target:

- [x] Keep the existing one-engine runtime behavior working by default.
- [x] Add an explicit runtime option for multiple engine adapter clients.
- [x] Accept multiple TCP adapter connections on the same runtime port.
- [x] Handshake each connected adapter against the same CGS hash.
- [x] Broadcast each runtime tick snapshot to every connected adapter.
- [x] Aggregate engine bridge stats and runtime status across connected adapters.
- [x] Add an editor-free smoke tool that connects Godot, Unity, and Unreal-named clients and verifies the same CGS hash, tick, and deterministic state hash.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/runtime-core/src/tcp_server.rs` | Runtime TCP acceptor for local engine adapters. | Adds helpers to wait for or try multiple adapter connections on one port. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Own authoritative tick lifecycle and runtime state progression. | Replaces the single live bridge slot with multiple bridges, broadcasts ticks, collects inputs/feedback from all bridges, and reports multi-adapter status. |
| `packages/runtime-core/src/bin/xace_runtime.rs` | CLI entry for loading CGS and starting runtime/control/engine bridge services. | Adds `--engine-clients` for explicit multi-adapter startup. |
| `packages/runtime-core/src/engine_protocol.rs` | Shared runtime-to-engine and engine-to-runtime protocol. | Advertises `multi_engine_clients` in handshake acknowledgements. |
| `tools/three_engine_runtime_smoke.py` | Editor-free smoke proof for the three-engine demo contract. | Launches one runtime, connects Godot/Unity/Unreal-named clients, steps one tick, and verifies the same CGS hash, tick, and deterministic state hash. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the three-engine runtime bridge readiness slice. |

Verification:

- `python -m py_compile tools/three_engine_runtime_smoke.py` passes.
- `cargo fmt --package xace-runtime-core` passes.
- `cargo test -p xace-runtime-core --lib runtime_orchestrator::tests --target-dir target-codex-three-engine` passes: 2 tests.
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-three-engine` passes: 560 tests.
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-three-engine` passes.
- Historical `python tools/three_engine_runtime_smoke.py --runtime-bin target-codex-three-engine\debug\xace_runtime.exe --cgs game.cgs.json` output used a 16-character `cgs_hash` prefix; that prefix is now non-authoritative. Current canonical CGS/world/state hashes must be lowercase 64-character SHA-256 digests.

Follow-up for creator/product UX:

- Add a user-facing three-engine demo launcher/checklist that starts the runtime once and helps connect installed Godot, Unity, and Unreal projects.
- Run real Unity and Unreal editor import/compile smokes once those engines are installed.
- Keep the visible proof UI easy to read in all three engine windows during demo capture.

Files to inspect before the three-engine demo launcher:

| File | Single Responsibility |
|---|---|
| `tools/three_engine_runtime_smoke.py` | Current editor-free proof for same runtime/same hash. |
| `tools/xace_godot_dev.py` | Current one-engine launcher pattern to generalize. |
| `adapters/godot/xace_debug_hud.gd` | Godot-side visible runtime health/tick/hash display. |
| `adapters/unity/XaceConsoleWidget.cs` | Unity-side visible runtime health/tick/hash display. |
| `adapters/unreal/XaceConsoleWidget.*` | Unreal-side visible runtime health/tick/hash display. |

## Twentieth Slice: Three-Adapter Visible Tick / Hash Proof

Status: adapter-side proof display is complete at the source level. Godot, Unity, and Unreal adapters now surface runtime tick and hash information in their existing HUD/console widgets so a demo can show the same runtime connection proof in each engine window.

Goal:

- Make the "one runtime, three engine renderers" demo visually understandable without terminal output.

Minimum build target:

- [x] Show the latest runtime tick in Godot, Unity, and Unreal adapter UI.
- [x] Show the CGS hash from the runtime handshake in Godot, Unity, and Unreal adapter UI.
- [x] Show a short snapshot proof hash where the adapter can compute one safely.
- [x] Keep the UI general and game-agnostic.
- [x] Avoid creating a separate marketing/demo-only page.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `adapters/godot/xace_adapter.gd` | Coordinate Godot transport, input, delta application, and adapter lifecycle. | Stores runtime CGS hash and computes a short deterministic snapshot proof hash from received snapshots. |
| `adapters/godot/xace_debug_hud.gd` | Godot-side visible runtime health HUD. | Displays connection state, tick, CGS hash, snapshot hash, entity count, and transport stats. |
| `adapters/unity/XaceConsoleWidget.cs` | Unity-side runtime console/debug widget. | Displays tick, CGS hash, and snapshot hash in the console window and logs the handshake hash. |
| `adapters/unreal/XaceConsoleWidget.h`, `adapters/unreal/XaceConsoleWidget.cpp` | Unreal-side runtime console/debug widget. | Stores and displays tick, CGS hash, and snapshot hash in the bound state text. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the visible tick/hash proof slice. |

Verification:

- `git diff --check -- adapters/godot/xace_adapter.gd adapters/godot/xace_debug_hud.gd adapters/unity/XaceConsoleWidget.cs adapters/unreal/XaceConsoleWidget.h adapters/unreal/XaceConsoleWidget.cpp` passes with only CRLF warnings.
- `where.exe godot` did not find Godot on PATH, so a real Godot HUD smoke could not be run in this shell.
- `where.exe Unity` did not find Unity on PATH, so a real Unity console compile/import smoke could not be run in this shell.
- `where.exe UnrealEditor` did not find Unreal on PATH, so a real Unreal widget/plugin compile smoke could not be run in this shell.

Follow-up for creator/product UX:

- Build a user-facing three-engine demo launcher/checklist that starts one runtime and guides the user to connect Godot, Unity, and Unreal.
- Once engines are installed, run real editor validation and adjust any engine-specific UI layout or compile issues.

Files to inspect before the demo launcher/checklist:

| File | Single Responsibility |
|---|---|
| `tools/three_engine_runtime_smoke.py` | Editor-free proof that one runtime can feed three engine clients. |
| `tools/xace_godot_dev.py` | Existing launcher pattern for runtime plus one engine. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Builder project UI where a demo checklist can live. |
| `packages/builder-workspace/server/builder_server.py` | Backend endpoints that can detect installed engines and project adapter status. |

## Twenty-First Slice: Builder Three-Engine Demo Checklist

Status: Builder now has a Demo tab in the Project Dashboard for preparing the "one runtime, three engine renderers" video. It checks Godot, Unity, and Unreal project folders, shows whether adapters are installed in each engine project, and can run the editor-free proof from the UI.

Goal:

- Give users a visible, non-terminal path for preparing the three-engine demo.

Minimum build target:

- [x] Add a Demo tab to the Project Dashboard.
- [x] Let users choose Godot, Unity, and Unreal project folders.
- [x] Save those paths in the active XACE project manifest when requested.
- [x] Validate engine project folder shape for Godot, Unity, and Unreal.
- [x] Show adapter-installed status for all three engine projects.
- [x] Show the next simple step for each missing/unfinished engine.
- [x] Add a Builder action that runs the editor-free one-runtime/three-client proof.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and local project lifecycle. | Adds `/api/project/demo/three-engine/status` and `/api/project/demo/three-engine/smoke`, plus helpers for engine folder validation, adapter install checks, runtime binary detection, and smoke execution. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and active project controls. | Adds a Demo tab with Godot/Unity/Unreal folder fields, readiness checklist, path persistence, and `Run Editor-Free Proof`. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Builder three-engine demo checklist slice. |

Verification:

- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `python -m unittest discover packages/builder-workspace/server/tests` passes: 7 tests.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- Backend demo status helper smoke returns `True True 0 0 3 True`, confirming status generation, editor-free proof readiness, three engine rows, and runtime binary detection.
- Backend editor-free proof action passes with output `True 3 multi(godot,unity,unreal) 0`.

Follow-up for creator/product UX:

- Add real engine launch/detect buttons once Godot, Unity, and Unreal install locations are known on the user's machine.
- Run the full Demo tab with real engine project folders and adjust wording/layout from the first recording attempt.

Files to inspect before real engine launch/detect:

| File | Single Responsibility |
|---|---|
| `packages/builder-workspace/server/builder_server.py` | Demo readiness endpoints and future engine launch/detect actions. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Demo checklist UI. |
| `tools/xace_godot_dev.py` | Existing process-launch pattern for runtime and Godot. |
| `adapters/*` | Engine project adapter components that must connect to the shared runtime. |

## Twenty-Second Slice: Engine Detect / Launch Buttons

Status: Builder can now detect installed Godot, Unity, and Unreal editor executables and expose launch buttons from the Demo tab. Launching remains explicit: the user chooses a valid engine project folder and clicks the engine-specific launch button.

Goal:

- Reduce terminal use for the three-engine demo and move toward launch-ready engine project opening.

Minimum build target:

- [x] Add backend engine executable detection for Godot, Unity, and Unreal.
- [x] Detect common Windows install locations plus PATH/environment overrides.
- [x] Add optional executable path fields in the Demo tab for manual override.
- [x] Add launch buttons for Godot, Unity, and Unreal project folders.
- [x] Validate engine project folder shape before launching.
- [x] Keep launch actions explicit and user-triggered.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and local project lifecycle. | Adds `/api/project/demo/engine-tools` and `/api/project/demo/launch-engine`, executable detection helpers, engine project launch command generation, and demo readiness engine-tool reporting. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and active project controls. | Adds `Detect Engines`, optional executable path fields, detected executable status, and per-engine launch buttons to the Demo tab. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the engine detect/launch slice. |

Verification:

- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- Backend engine detection smoke returns three tool rows: `godot`, `unity`, and `unreal`; on this machine Unreal was detected and Godot/Unity were not found automatically.
- Backend demo status smoke includes three engine-tool rows in readiness output.

Follow-up for creator/product UX:

- Add a one-click runtime launcher from Builder for the three-engine demo.
- Add clearer per-engine connection instructions once a real engine project is launched.
- Validate actual launch behavior on a machine with Godot, Unity, and Unreal installed.

Files to inspect before one-click runtime launcher:

| File | Single Responsibility |
|---|---|
| `packages/builder-workspace/server/builder_server.py` | Runtime process launch/control endpoints and demo launch helpers. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Demo tab launch controls. |
| `tools/three_engine_runtime_smoke.py` | Existing proof command for runtime multi-client behavior. |
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime executable flags such as `--engine-clients`, `--port`, and control settings. |

## Twenty-Third Slice: Builder One-Click Runtime Launcher

Status: Builder can now start, check, and stop one live XACE runtime for the three-engine demo from the Demo tab. The runtime starts with three engine-client capacity and does not wait for editor clients, so users can start runtime first, then open Godot, Unity, and Unreal in any order.

Goal:

- Remove the terminal step from the "one runtime, three engines" demo path.

Minimum build target:

- [x] Add backend runtime status/start/stop endpoints.
- [x] Start `xace_runtime` with the active project CGS.
- [x] Use `--engine-clients 3` for the shared demo runtime.
- [x] Use `--no-wait` so Builder remains responsive while engines open later.
- [x] Show live runtime status in the Demo tab.
- [x] Add Start Runtime, Check Runtime, and Stop Runtime buttons.
- [x] Keep the editor-free proof as a separate verification action.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and local runtime/demo orchestration. | Adds `/api/project/demo/runtime`, `/api/project/demo/runtime/start`, and `/api/project/demo/runtime/stop`, runtime process tracking, control-socket status checks, and launch command generation for one runtime with three engine clients. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and Demo tab controls. | Adds live runtime status display plus Start Runtime, Check Runtime, and Stop Runtime actions. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Builder one-click runtime launcher slice. |

Verification:

- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- Backend runtime smoke starts `xace_runtime` on test ports, confirms the control socket reports `running=True` with `engine_clients=3`, then stops it cleanly: `start True True 29904`, `status True 3 9709`, `stop True True 0`.

Follow-up for creator/product UX:

- Add per-engine connection status rows so Builder can show whether Godot, Unity, and Unreal are actually connected to the live runtime.
- Add a single "Run Full Demo" flow that starts runtime, launches available engines, and keeps the checklist visible for recording.

## Twenty-Fourth Slice: Per-Engine Live Connection Proof

Status: Builder can now show live Godot, Unity, and Unreal connection rows for the shared demo runtime. The runtime launcher also uses explicit live engine acceptance so the runtime can start first and accept engine clients as they open.

Goal:

- Make the "one runtime, three engines" recording prove each engine is connected to the same live runtime without terminal output.

Minimum build target:

- [x] Add runtime support for live engine acceptance after startup.
- [x] Start Builder-launched demo runtime with `--live-engine-accept`.
- [x] Derive connected engine names from runtime adapter status.
- [x] Include snapshot tick and snapshot hash in Builder runtime status.
- [x] Show Godot, Unity, and Unreal live connection rows in the Demo tab.
- [x] Keep editor-free proof and real editor launch controls separate.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime executable CLI and process lifecycle. | Adds `--live-engine-accept`, starts a nonblocking live accept thread, and drains accepted engine clients during the runtime loop. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Own authoritative runtime state and engine bridge registration. | Adds a public method to handshake one accepted engine connection into the running runtime. |
| `packages/builder-workspace/server/builder_server.py` | Builder runtime/demo orchestration endpoints. | Starts demo runtime with live engine acceptance, computes a snapshot proof hash, and returns per-engine connection rows. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and Demo tab controls. | Displays live Godot, Unity, and Unreal connection status with shared tick/hash proof when connected. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the per-engine live connection proof slice. |

Verification:

- `cargo fmt --package xace-runtime-core` passes.
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-three-engine` passes with pre-existing warnings.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- Live accept smoke passes: runtime starts first with `--no-wait --live-engine-accept`, then `tools/three_engine_runtime_smoke.py --no-start-runtime` connects Godot/Unity/Unreal clients and reports `multi(godot,unity,unreal)`, 3 clients, tick 0, and shared state hash `b931b2b9f4637c275c0c847347940034db1c76a7899fcf3a54b5986434672d80`.
- Backend per-engine row parsing smoke returns all three connected rows for `multi(godot,unity,unreal)`.
- `cargo test -p xace-runtime-core --lib runtime_orchestrator::tests --target-dir target-codex-live-status` passes: 2 tests. The same test command against `target-codex-three-engine` hit a Windows linker lock on the test executable before rerunning in the fresh target.

Follow-up for creator/product UX:

- Add a single "Run Full Demo" button that starts runtime, detects engines, launches available projects, and keeps the checklist visible.
- Run a real recording pass with installed Godot, Unity, and Unreal projects.

## Twenty-Fifth Slice: Builder Start Session Workflow

Status: Builder now has a general Start Session action in the Demo tab. It starts the live runtime, detects engine tools, launches every ready engine project it can, skips missing or invalid engine projects with clear reasons, and refreshes the live checklist.

Goal:

- Move XACE toward launch-ready local preview sessions where users do not manually start runtime and editors from terminals.

Minimum build target:

- [x] Add a backend session-start endpoint that orchestrates runtime start plus engine project launches.
- [x] Reuse saved/entered Godot, Unity, and Unreal project paths.
- [x] Reuse detected or manually entered engine executable paths.
- [x] Launch only valid ready engine projects.
- [x] Report skipped and failed engine launches without failing the whole runtime session.
- [x] Add a Start Session button to Builder.
- [x] Refresh runtime/demo status after starting the session.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `packages/builder-workspace/server/builder_server.py` | Builder local project, runtime, and engine orchestration. | Adds `/api/project/demo/session/start`, executable-path parsing, and session launch aggregation for Godot, Unity, and Unreal. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project workflow UI and Demo tab controls. | Adds `Start Session`, posts project/executable paths, updates runtime status, engine tools, and checklist feedback. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the Builder Start Session workflow slice. |

Verification:

- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- Backend launch aggregation smoke returns three skipped rows for missing Godot/Unity/Unreal project folders: `3 [('godot', True, False), ('unity', True, False), ('unreal', True, False)]`.
- Endpoint-level session smoke with `TestClient` starts runtime on a test control port, reports runtime running, skips the three missing engine projects cleanly, then stops runtime: `start True True [('godot', True), ('unity', True), ('unreal', True)]`, `stop True True`.

Follow-up for launch readiness:

- Return to the main launch map priorities: real Unity validation, real Unreal validation, bidirectional edit loop, save/load replay hash, network primitives smoke, certification command, and packaging/docs.

## Twenty-Sixth Slice: Real Unity Adapter Validation

Status: Unity adapter package now imports and compiles in a real Unity project at `C:\Users\ankit\firstgame` using Unity `6000.4.9f1`. A generic editor validation method also instantiates the runtime adapter components without touching the user's scene.

Goal:

- Prove the Unity adapter is not just source-shaped, but actually accepted by a real Unity editor project.

Minimum build target:

- [x] Install the XACE Unity adapter package into a real Unity project under `Assets/XACE`.
- [x] Run Unity batchmode import/compile validation.
- [x] Fix compile errors found by Unity.
- [x] Remove Unity 6000 obsolete API warning from the adapter widget.
- [x] Add a generic Unity editor validation entry point.
- [x] Run the validation method in Unity batchmode.
- [x] Confirm Unity produced `XACE.Adapter.Unity.dll`.

Changes landed in this slice:

| File | Single Responsibility | Slice Change |
|---|---|---|
| `adapters/unity/XaceTransport.cs` | Unity TCP transport, protocol framing, handshake, JSON parsing/serialization, and runtime message dispatch. | Fixes a C# local variable shadowing compile error in the JSON writer found by Unity 6000. |
| `adapters/unity/XaceConsoleWidget.cs` | Unity runtime status/debug console display. | Replaces deprecated `FindObjectOfType<T>()` with `FindAnyObjectByType<T>()` for Unity 6000 compatibility. |
| `adapters/unity/Editor/XaceUnityValidation.cs` | Editor-only import validation entry point for Unity package smoke checks. | Adds `RunImportValidation`, which creates a hidden unsaved object, attaches `XaceTransport`, `XaceInputCollector`, `XaceDeltaApplicator`, and `XaceConsoleWidget`, then exits batchmode with pass/fail. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the real Unity validation slice and updates Unity adapter status. |

Verification:

- Unity project shape verified at `C:\Users\ankit\firstgame`: `Assets` and `ProjectSettings` exist.
- Unity editor found at `C:\Program Files\Unity\Hub\Editor\6000.4.9f1\Editor\Unity.exe`.
- Adapter package installed into `C:\Users\ankit\firstgame\Assets\XACE`.
- First Unity batchmode compile found a real error: `Assets\XACE\XaceTransport.cs(702,21): error CS0136`.
- After fixing, Unity batchmode import/compile passed with `ExitCode: 0`.
- Unity produced `Library\Bee\artifacts\1900b0aE.dag\XACE.Adapter.Unity.dll` and the post-processed DLL.
- Unity batchmode execute method `Xace.Adapter.Unity.Editor.XaceUnityValidation.RunImportValidation` logged `[XACE] Unity adapter import validation passed.`

Follow-up for launch readiness:

- Real Unreal adapter validation is recorded in the Twenty-Seventh Slice below.
- Later Unity work should validate an actual play-mode runtime connection against `xace_runtime`, but the package import/compile/component smoke is now real.

## Twenty-Seventh Slice: Real Unreal Adapter Validation

Status: Unreal adapter plugin source now compiles in a real Unreal install. The adapter was installed into `C:\Users\ankit\OneDrive\Documents\Unreal Projects\MyProject3\Plugins\XACE`, then validated with Unreal `5.7` BuildPlugin no-host runtime builds for Win64 Development and Shipping.

What This Slice Proves:

- The Unreal adapter is no longer source-shaped only; UnrealHeaderTool accepts its reflected component/struct API.
- The runtime plugin module compiles against Unreal 5.7 for Win64 Development and Shipping.
- Builder's Unreal plugin layout (`Plugins/XACE`, `.uplugin`, `Build.cs`, Public headers, Private sources) is viable.
- The adapter remains general: transport, input collection, delta application, feedback, and console proof UI are engine/runtime features, not game-specific code.

Checklist:

- [x] Detect a real Unreal install on this machine.
- [x] Install the XACE Unreal plugin into a real Unreal project.
- [x] Fix Unreal reflection issues found by UHT: Blueprint-safe signed ID/tick/counter fields and explicit property categories.
- [x] Fix Unreal 5.7 compile issues: `UWorld` includes, MD5 include path, and TCP no-delay socket setup.
- [x] Run Unreal BuildPlugin no-host validation for Win64 Development and Shipping.
- [x] Record the remaining editor-host/live-play caveat.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `adapters/unreal/XaceTransport.h`, `adapters/unreal/XaceTransport.cpp` | Unreal TCP transport, handshake, protocol framing, runtime snapshots, input packets, stats, and feedback payloads. | Uses Blueprint-safe signed numeric fields at the public API, adds explicit categories, and replaces builder-level `WithNoDelay()` with socket `SetNoDelay(true)`. |
| `adapters/unreal/XaceInputCollector.h`, `adapters/unreal/XaceInputCollector.cpp` | Convert Unreal player/controller input state into XACE input packets. | Uses Blueprint-safe signed identity/tick fields and includes `Engine/World.h` for UE 5.7 compile compatibility. |
| `adapters/unreal/XaceDeltaApplicator.h`, `adapters/unreal/XaceDeltaApplicator.cpp` | Apply runtime entity snapshots to Unreal actors and collect generic feedback. | Uses Blueprint-safe signed entity/tick IDs, explicit categories, and includes `Engine/World.h` for spawning actors. |
| `adapters/unreal/XaceConsoleWidget.h`, `adapters/unreal/XaceConsoleWidget.cpp` | Unreal-side runtime console/debug widget and tick/hash proof display. | Uses signed tick display, includes `Misc/SecureHash.h`, and keeps snapshot proof hashing buildable in UE 5.7. |
| `adapters/unreal/README.md` | Unreal adapter install and validation notes. | Updates status to reflect real BuildPlugin validation; latest live editor proof is recorded in the Thirty-Seventh Slice. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the real Unreal validation slice and updates Unreal adapter status. |

Verification:

- Unreal adapter install into real project succeeded: `Plugins/XACE` exists under `C:\Users\ankit\OneDrive\Documents\Unreal Projects\MyProject3`.
- Historical note: this slice originally stopped because Unreal's editor module chain required a missing `.NET Framework SDK 4.6+`. That prerequisite is now resolved on this machine and the Thirty-Seventh Slice records full Unreal live validation.
- Unreal no-host runtime BuildPlugin validation passed:
  `RunUAT.bat BuildPlugin -Plugin="...\MyProject3\Plugins\XACE\XACE.uplugin" -Package="...\target-codex-unreal-validation\XACEBuiltNoHost4" -TargetPlatforms=Win64 -NoHostPlatform -Rocket`
- Final output included `Result: Succeeded` for Win64 Development, `Result: Succeeded` for Win64 Shipping, and `BUILD SUCCESSFUL`.

Follow-up:

- Run a live Unreal editor/play smoke after the editor-host SDK dependency is installed or on a machine with the full Unreal editor build prerequisites.
- Return to launch map priorities: bidirectional edit loop, save/load replay hash, network primitives smoke, certification command, and packaging/docs.

## Twenty-Eighth Slice: Bidirectional Runtime Edit Loop Foundation

Status: Builder can now send live focus and field-edit requests into the running runtime, receive an accepted/rejected acknowledgement, and show a small audit trail in the inspector. This is a runtime-preview edit loop foundation; persisted CGS changes still go through the existing Prompt Apply / mutation path.

What This Slice Proves:

- Builder inspector actions can travel through Builder WebSocket -> runtime control socket -> runtime orchestrator.
- Runtime validates live edit authority before changing preview state: entity must exist, component type must exist, field path must be portable, and edited values must be primitive JSON values.
- Builder records and returns an audit entry for each edit acknowledgement.
- The UI makes the difference clear: live edits affect the running preview, while durable CGS edits remain a separate save/mutation workflow.

Checklist:

- [x] Add live Focus action for runtime entities from the Builder inspector.
- [x] Add guarded Live Edit actions for primitive component fields.
- [x] Route engine edit acknowledgements to Builder UI listeners.
- [x] Return audit metadata from Builder backend acknowledgements.
- [x] Tighten runtime control validation for `set_component_field`.
- [x] Add backend and runtime protocol tests.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/src/preview/entity_inspector.ts` | Inspect selected actor/component state and expose focused editing controls. | Adds runtime entity matching, Focus Live, primitive field Live Edit, success/error feedback, and recent audit display. |
| `packages/builder-workspace/src/api/builder_client.ts` | Own Builder WebSocket message dispatch and client-side subscriptions. | Adds engine-edit acknowledgement listeners so UI panels can react to accepted/rejected runtime edits. |
| `packages/builder-workspace/src/api/message_types.ts` | Define Builder WebSocket message contracts. | Adds `source` on engine edit requests and audit metadata on engine edit acknowledgements. |
| `packages/builder-workspace/src/canvas/builder_canvas.ts` | Wire canvas, inspector, stores, and Builder client together. | Passes the Builder client into the inspector for live edit commands. |
| `packages/builder-workspace/server/ws_message_router.py` | Route Builder WebSocket messages to project/session/runtime services. | Records structured audit entries and returns them with `engine_edit_ack`. |
| `packages/builder-workspace/server/tests/test_engine_edit_router.py` | Backend coverage for engine edit routing. | Verifies accepted edits include audit data and unknown edit kinds are rejected before runtime routing. |
| `packages/runtime-core/src/control_protocol.rs` | Validate runtime control and engine-edit wire messages. | Requires `set_component_field` to include component type, portable field path, and a primitive JSON value. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the bidirectional runtime edit loop foundation. |

Verification:

- `python -m unittest discover packages/builder-workspace/server/tests` passes: 2 tests.
- `python -m py_compile packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/tests/test_engine_edit_router.py` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `cargo test -p xace-runtime-core control_protocol --target-dir target-codex-bindings` passes with pre-existing warnings.

Follow-up:

- Durable "commit accepted live edit to CGS" is recorded in the Twenty-Ninth Slice below.
- Continue launch map priorities: save/load replay hash, network primitives smoke, certification command, builder polish, and packaging/docs.

## Twenty-Ninth Slice: Durable Live Edit Commit

Status: accepted Builder live edits can now be committed into `game.cgs.json` through the existing GDE-backed value mutation path. The user previews a value first with Live Edit, then clicks `commit` on the accepted audit row to save that exact value into the CGS with a snapshot.

What This Slice Proves:

- Runtime-preview edits are not silently persisted; the user chooses when to commit.
- Commit requests must match an accepted `set_component_field` audit entry from the current Builder session.
- Backend validates the current CGS target before building a value mutation transaction.
- The commit path uses `SessionManager.apply_via_gde`, persists the CGS, creates a snapshot, and emits `cgs_update`.

Checklist:

- [x] Add typed `engine_edit_commit` and `engine_edit_commit_ack` Builder messages.
- [x] Store CGS context on accepted live edit audit entries: mode, actor, component, field, value.
- [x] Add `commit` button for accepted primitive live-edit audit rows.
- [x] Validate commit requests against the accepted audit log and current CGS.
- [x] Convert the accepted live edit into a GDE value mutation path.
- [x] Persist the new CGS and snapshot after commit.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/src/api/message_types.ts` | Define Builder WebSocket message contracts. | Adds durable live edit commit request/ack types and message factory. |
| `packages/builder-workspace/src/preview/entity_inspector.ts` | Inspect selected actor/component state and expose focused editing controls. | Adds `commit` actions for accepted live-edit audit rows plus clear saving/committed/failure status text. |
| `packages/builder-workspace/server/ws_message_router.py` | Route Builder WebSocket messages to project/session/runtime services. | Adds `engine_edit_commit`, validates accepted audit + CGS target, builds a value mutation transaction, applies through GDE/session manager, persists, snapshots, and sends `cgs_update`. |
| `packages/builder-workspace/server/tests/test_engine_edit_router.py` | Backend coverage for engine edit routing. | Adds commit tests for successful GDE value mutation and rejection without a matching accepted audit entry. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records durable live edit commit as a completed bidirectional edit-loop slice. |

Verification:

- `python -m unittest discover packages/builder-workspace/server/tests` passes: 4 tests.
- `python -m py_compile packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/tests/test_engine_edit_router.py` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `git diff --check -- packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/tests/test_engine_edit_router.py packages/builder-workspace/src/api/message_types.ts packages/builder-workspace/src/preview/entity_inspector.ts docs/LAUNCH_READINESS_MAP.md` passes with only normal Windows line-ending warnings.

Follow-up:

- Save/load replay hash is recorded in the Thirtieth Slice below.

## Thirtieth Slice: Save / Load Replay Hash

Status: the Rust save engine now records both the CGS hash and a deterministic project asset hash in save-slot metadata, and the runtime checkpoint test proves save -> load -> restore -> replay preserves the final world hash.

What This Slice Proves:

- A saved session records the CGS hash from the authoritative runtime snapshot.
- A project save can compute and store a deterministic hash of the asset folder.
- Loading a saved runtime snapshot preserves tick, CGS hash, and world hash.
- Restoring that snapshot into a fresh runtime and replaying forward reaches the same final world hash as the original runtime.

Checklist:

- [x] Add deterministic asset-folder hashing to the Rust save engine.
- [x] Store `asset_hash` in save-slot metadata while keeping existing `save_session` callers compatible.
- [x] Add a project-session save path that computes asset hash from an asset root.
- [x] Add metadata loading for slot inspection/verification.
- [x] Extend save roundtrip tests for asset hash stability and asset-change detection.
- [x] Extend runtime checkpoint replay test to verify stored CGS hash, asset hash, loaded snapshot hash, and replay final world hash.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/save-engine/src/save_engine.rs` | File-backed save slots, session/progress/world layers, metadata, and atomic writes. | Adds deterministic asset tree hashing, `save_project_session`, `save_session_with_asset_hash`, and `load_metadata`. |
| `packages/save-engine/src/save_slot.rs` | Save layer and slot metadata contracts. | Adds `asset_hash` with backward-compatible deserialization default. |
| `packages/save-engine/src/lib.rs` | Public save-engine crate surface. | Exposes `compute_asset_tree_hash`. |
| `packages/save-engine/Cargo.toml` | Save-engine crate dependencies. | Adds `sha2` for deterministic asset hashing. |
| `packages/save-engine/tests/test_save_roundtrip.rs` | Rust save-engine roundtrip coverage. | Verifies project session metadata stores CGS hash and deterministic asset hash, and asset content changes alter the asset hash. |
| `packages/save-engine/tests/test_runtime_checkpoint.rs` | Runtime/save integration coverage. | Verifies save/load/restore/replay final world hash equality with stored CGS and asset hashes. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records save/load replay hash completion. |

Verification:

- `cargo fmt --package xace-save-engine` passes.
- `cargo test -p xace-save-engine --target-dir target-codex-save-runtime` passes: 11 tests total, including `runtime_checkpoint_save_load_replay_preserves_world_hash` and `project_session_records_deterministic_asset_hash`.

Follow-up:

- Network primitives smoke is recorded in the Thirty-First Slice below.

## Thirty-First Slice: Network Primitives Smoke

Status: the network primitives smoke is now visible from Builder and backed by the network-core proof for host/client lifecycle, lockstep input release, prediction/reconciliation, desync detection, and deterministic final digest.

What This Slice Proves:

- A host session can reach live state with two required peers.
- A client session can enter live state while waiting on the server peer for authoritative input.
- Lockstep release is independent of peer input arrival order.
- Prediction and reconciliation stay within tolerance for the smoke simulation.
- Desync detection reports an intentionally divergent peer hash.
- Normal and flipped input arrival orders produce the same final multiplayer digest.

Checklist:

- [x] Extend the networked runtime smoke to include explicit host/client session lifecycle checks.
- [x] Add a Builder backend endpoint for the network primitives smoke.
- [x] Add a Demo-tab button and checklist result block for non-terminal multiplayer verification.
- [x] Keep the proof general to network/runtime behavior, not one game-specific demo.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/network-core/tests/test_networked_runtime_smoke.rs` | Network primitives smoke coverage. | Adds host/client session lifecycle assertions before lockstep, prediction, reconciliation, desync, and final digest checks. |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP API and local workflow helpers. | Adds `/api/project/demo/multiplayer/smoke`, which runs the network-core primitives smoke and returns structured checklist rows. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Active project dashboard, project workflows, and demo controls. | Adds the Run Network Primitives Smoke button plus compact pass/fail rows in the Demo tab. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records network primitives smoke completion. |

Verification:

- `cargo fmt --package xace-network-core` passes.
- `cargo test -p xace-network-core --target-dir target-codex-network-smoke networked_runtime_smoke_is_deterministic_across_arrival_orders` passes: 1 targeted smoke test.
- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.

Follow-up:

- Certification command is recorded in the Thirty-Second Slice below.

## Thirty-Second Slice: Certification Command

Status: XACE now has one editor-free launch certification command that builds the runtime, verifies Builder, runs bridge/network/save/replay checks, and covers project, asset, edit-loop, feedback, and migration tests.

What This Slice Proves:

- A non-engine-editor certification path exists for the shared XACE runtime and Builder product surface.
- The command builds `xace_runtime` before running runtime bridge smoke.
- Project creation/templates, asset import/link, Builder backend edit loop, Builder production build, runtime protocol/control, feedback replay, network primitives smoke, save replay hash, and save migration are covered from one command.
- The old `phase15` runner remains as a wrapper so existing internal workflows still work.

Checklist:

- [x] Add a user-facing certification command: `python tools/certify_launch.py`.
- [x] Add a root package script: `npm run xace:certify`.
- [x] Keep `tools/phase15_integration_check.py` as a compatibility wrapper.
- [x] Include a quick smoke-focused subset via `--quick`.
- [x] Print simple pass/fail status rows and stop at the first failing check.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/certify_launch.py` | Run editor-free launch certification checks from one command. | Adds full and quick certification suites, shared Cargo target handling, concise pass/fail output, and first-failure reporting. |
| `tools/phase15_integration_check.py` | Keep the old internal integration-check entry point working. | Wraps the new certification runner while preserving the old target directory. |
| `package.json` | Root developer/user scripts. | Adds `xace:certify` for the launch certification command. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records certification command completion. |

Verification:

- `python -m py_compile tools/certify_launch.py tools/phase15_integration_check.py` passes.
- `python tools/certify_launch.py --quick` passes: 6 checks, including runtime build, Builder build, runtime bridge smoke, network primitives smoke, and save replay.
- `python tools/certify_launch.py` passes: 13 checks in the full editor-free suite.
- `npm run xace:certify -- --quick` passes, confirming the root package shortcut invokes the certification command.
- Full certification output ended with: `launch readiness PASSED (13 checks, 45.5s)`.

Follow-up:

- Builder launch health UX polish is recorded in the Thirty-Third Slice below.

## Thirty-Third Slice: Builder Launch Health UX

Status: the Project Dashboard now opens to a Health tab that summarizes active project readiness, adapter health, CGS path, and launch certification readiness, with a one-click quick certification action inside Builder.

What This Slice Proves:

- Builder has a restrained launch health surface instead of hiding readiness behind terminal commands.
- Non-technical users can see whether the active project, CGS, adapter, and certification command are ready.
- Builder can run the quick editor-free certification suite through a backend endpoint and display pass/fail rows.
- The existing New/Open/Wrap-Link/Adapter Package/Demo workflows remain available as focused tabs.

Checklist:

- [x] Add launch certification status and quick-run endpoints to the Builder backend.
- [x] Add a Health tab to the Project Dashboard.
- [x] Default the Project Dashboard to Health so readiness is the first thing users see.
- [x] Show compact pass/fail rows for project, CGS, adapter, certification command, and quick certification steps.
- [x] Keep the UI dense and practical; no marketing page or one-game-specific copy.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP API and local workflow helpers. | Adds certification status and quick certification endpoints, plus output parsing into checklist rows. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Active project dashboard, project workflows, demo controls, and launch health UI. | Adds the Health tab, launch health rows, quick certification button/result rows, and makes Health the default dashboard tab. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records Builder launch health UX completion. |

Verification:

- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `python -m unittest discover packages/builder-workspace/server/tests` passes: 4 tests.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.

Follow-up:

- Prompt pipeline hardening is recorded in the Thirty-Fourth Slice below.

## Thirty-Fourth Slice: Full Prompt Pipeline Hardening

Status: supported prompt categories now have an editor-free scenario proof that travels through the real Builder route, GDE validation, SGC execution-plan hook, CGS persistence/snapshots, and runtime CGS loading. Unsupported broad prompts are blocked without leaving a pending mutation to apply.

What This Slice Proves:

- Supported value mutations, structural component additions, and structural actor additions can move from `pil_process` to `pil_apply` without bypassing GDE.
- Structural prompt mutations trigger the SGC hook and persist an execution plan next to the CGS snapshot.
- Empty-operation or unsupported prompt results are treated as blocked, not as successful no-op mutations.
- If GDE is unavailable, Builder returns a clear apply error instead of using direct CGS mutation fallback logic.
- The final prompt-mutated CGS loads into `xace_runtime` and runs ticks in editor-free certification.

Checklist:

- [x] Add deterministic supported prompt contract scenarios for general value and structural prompt categories.
- [x] Exercise those scenarios through the real Builder WebSocket router and `SessionManager.apply_via_gde`.
- [x] Add unsupported prompt blocking coverage with no pending transaction left behind.
- [x] Add explicit no-GDE rejection coverage so certification cannot pass through direct CGS fallback logic.
- [x] Add a prompt pipeline contract/scenario smoke command and wire it into launch certification.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/session_manager.py` | Own Builder session state, PIL execution, GDE apply, and SGC invocation. | Blocks empty/invalid mutation transactions, clears stale pending mutations on non-mutation results, rejects GDE-unavailable applies by default, and supports SGC command args for test/certification hooks. |
| `packages/builder-workspace/server/tests/fixtures/prompt_pipeline_contract.py` | Define reusable deterministic prompt-pipeline contract scenarios as test fixtures. | Adds general supported scenarios for value mutation, structural component add, structural actor add, plus an unsupported broad-prompt block scenario. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Backend prompt pipeline scenario coverage. | Verifies supported prompts apply through GDE, persist snapshots, run SGC for structural changes, block unsupported prompts, and reject no-GDE fake success. |
| `tools/prompt_pipeline_smoke.py` | Editor-free prompt pipeline contract/scenario smoke. | Creates a starter CGS, runs the supported/blocked prompt contract through Builder/GDE and the real SGC binary path, then loads the final CGS in `xace_runtime`. |
| `tools/certify_launch.py` | Run editor-free launch certification checks from one command. | Adds prompt pipeline contract/scenario smoke to both full and quick certification, and compiles the new prompt pipeline Python modules. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records full prompt pipeline hardening. |

Verification:

- `python -m py_compile packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/tests/fixtures/prompt_pipeline_contract.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py tools/prompt_pipeline_smoke.py tools/certify_launch.py` passes.
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` passes: 3 tests.
- `python -m unittest discover packages/builder-workspace/server/tests` passes: 7 tests.
- `python tools/prompt_pipeline_smoke.py --skip-runtime` passes the contract/scenario smoke after running outside the sandbox because the normal runner hit the known spawn-refresh issue.
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-certify\debug\xace_runtime.exe --sgc-bin target-codex-certify\debug\xace-system-graph-compiler.exe` passes and the runtime returns code 0.
- `python tools/certify_launch.py --quick` passes: 7 checks, including prompt pipeline contract/scenario smoke.

Follow-up:

- Continue the remaining hardening plan: old-to-new compatibility coverage, broader template/category matrix, and real provider/user-facing prompt UX checks.

## Thirty-Fifth Slice: Asset / Audio / Animation Playback Path

Status: semantic asset bindings now load from CGS, validate during runtime load, resolve emitted semantic events into typed engine playback commands, travel in runtime tick/control snapshots, and are consumed by Godot, Unity, and Unreal adapters. An editor-free smoke proves real imported animation/audio/VFX files become linked asset references and runtime-loadable CGS bindings.

What This Slice Proves:

- Asset import/link workflow can register and link animation clips, audio clips, and particle/VFX files without engine-specific hardcoding.
- Top-level `semantic_bindings` in CGS are no longer ignored by the runtime loader.
- Bad playback bindings, such as an Audio binding pointing at a Mesh asset, fail CGS load clearly.
- Runtime-emitted semantic events are preserved from the phase loop so playback can be resolved deterministically.
- Resolved playback commands are typed and included in engine tick snapshots for all connected adapters.
- Godot, Unity, and Unreal adapters now record playback commands and attempt generic engine playback when a command includes a usable resource path.
- The new certification smoke creates a temporary project, imports real files, writes playback bindings, and verifies `xace_runtime` loads that CGS.

Checklist:

- [x] Load and validate CGS `semantic_bindings` in runtime CGS loading.
- [x] Store semantic bindings in the runtime spawn summary.
- [x] Return emitted events from the deterministic phase tick result.
- [x] Resolve semantic events into engine playback commands inside `RuntimeOrchestrator`.
- [x] Include playback commands in control snapshots and connected engine tick snapshots.
- [x] Add general adapter-side playback command consumption for Godot, Unity, and Unreal.
- [x] Add an editor-free asset playback smoke and wire it into launch certification.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/cgs_loader.rs` | Load and validate CGS into runtime state. | Adds top-level `semantic_bindings`, validates them on load, stores them in `SpawnSummary`, and tests valid/invalid playback bindings. |
| `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs` | Run systems in deterministic phase order. | Carries emitted events back in `TickResult` while still dispatching through the EventBus. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Own authoritative tick lifecycle and runtime snapshots. | Resolves emitted semantic events into `EnginePlaybackCommand`s and exposes the latest commands in control snapshots. |
| `packages/runtime-core/src/engine_bridge.rs` | Send authoritative runtime snapshots to engine adapters. | Adds playback commands to outgoing tick snapshots for connected engines. |
| `adapters/godot/xace_delta_applicator.gd` | Apply runtime state messages to Godot. | Routes standalone playback command messages to the entity manager. |
| `adapters/godot/xace_entity_manager.gd` | Own Godot entity nodes and transform/visual updates. | Records playback commands per entity and best-effort plays audio, animation, or VFX when a resource path is supplied. |
| `adapters/unity/XaceTransport.cs` | Unity transport and runtime protocol model. | Parses tick-snapshot playback commands into typed Unity adapter objects. |
| `adapters/unity/XaceDeltaApplicator.cs` | Mirror runtime snapshots into a Unity scene. | Records playback commands per entity and best-effort plays AudioSource, Animator/Animation, or ParticleSystem resources. |
| `adapters/unreal/XaceTransport.h`, `adapters/unreal/XaceTransport.cpp` | Unreal transport and runtime protocol model. | Parses asset references and playback commands from tick snapshots. |
| `adapters/unreal/XaceDeltaApplicator.h`, `adapters/unreal/XaceDeltaApplicator.cpp` | Mirror runtime snapshots into an Unreal scene. | Records playback commands per entity and best-effort plays SoundBase, AnimationAsset, or ParticleSystem assets from supplied paths. |
| `tools/asset_playback_smoke.py` | Editor-free asset playback certification smoke. | Imports sample animation/audio/VFX files through the real asset workflow, writes CGS semantic bindings, and loads them through `xace_runtime`. |
| `tools/certify_launch.py` | Run editor-free launch certification checks from one command. | Adds asset playback smoke to quick/full certification and Python compile checks. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records asset/audio/animation playback path completion. |

Verification:

- `cargo fmt -p xace-runtime-core` passes.
- `python -m py_compile tools/asset_playback_smoke.py tools/certify_launch.py` passes.
- `cargo test -p xace-runtime-core load_and_spawn_accepts_valid_semantic_playback_bindings --lib --target-dir target-codex-bindings` passes.
- `cargo test -p xace-runtime-core load_and_spawn_rejects_invalid_semantic_asset_type --lib --target-dir target-codex-bindings` passes.
- `cargo test -p xace-runtime-core tick_returns_emitted_events_for_runtime_playback_resolution --lib --target-dir target-codex-bindings` passes.
- `cargo test -p xace-runtime-core semantic_playback_bindings_resolve_into_engine_snapshot_commands --lib --target-dir target-codex-bindings` passes.
- `python tools/asset_playback_smoke.py --skip-runtime` passes after running outside the sandbox because the normal runner hit the known spawn-refresh issue.
- `python tools/asset_playback_smoke.py --runtime-bin target-codex-certify\debug\xace_runtime.exe` passes.
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-bindings` passes: 565 tests.
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-asset-playback` passes: 8 checks.

Follow-up:

- Real editor validation should play actual project assets in Godot, Unity, and Unreal using command `resource_path`/`asset_path` parameters.
- Builder UI should expose semantic binding authoring/status more clearly for imported assets.

## Thirty-Sixth Slice: Builder UX Beyond Health

Status: Builder now has a creator-facing workflow layer beyond the health dashboard. The top bar exposes Health, Project, Prompt, Assets, Preview, and Inspector entry points; prompt mutations show clear lifecycle status; review/failure states explain what will or will not be saved; assets, inspector edits, and model/provider settings use normal creator language.

What This Slice Proves:

- A non-technical creator can find the main Builder areas without knowing panel shortcuts or terminal commands.
- Prompt requests visibly move through proposed, validating, safe, applied, and failed states.
- Review makes the save boundary explicit: Apply writes to the project, Revise keeps editing, Discard leaves the project unchanged.
- Runtime preview edits are clearly separated from saved CGS/project edits in the Inspector.
- Asset UI distinguishes imported assets, slots that still need art, and missing paths, with a repair action.
- Model/provider settings show local model status, hosted API key status, and current model from the existing selector.
- Error and blocked-request screens now say plainly that nothing was saved.

Checklist:

- [x] Add a compact Builder workflow nav: Health, Project, Prompt, Assets, Preview, Inspector.
- [x] Wire workflow buttons to existing project dashboard, prompt focus, asset linker, preview tab, and inspector tab.
- [x] Add prompt mutation lifecycle chips for proposed, validating, safe, applied, and failed.
- [x] Clarify review/apply/discard copy in the prompt review surface.
- [x] Render normal-user blocked/error states instead of blank error panels.
- [x] Add a real Preview tab in the right panel and keep the Inspector tab focused on selected entities.
- [x] Polish Inspector copy for saved fields vs temporary live preview edits.
- [x] Polish asset panel copy and repair actions.
- [x] Polish model/provider settings status.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/src/layout/main_layout.ts` | Builder shell and top toolbar. | Adds workflow navigation, routes Project/Health into the dashboard, focuses Prompt/Assets/Preview/Inspector, and wires Settings to model/provider settings. |
| `packages/builder-workspace/src/canvas/builder_canvas.ts` | Compose Builder left/center/right panels. | Adds a real Preview tab and expands the viewport when Preview is selected. |
| `packages/builder-workspace/src/canvas/prompt_input.ts` | Natural-language prompt entry. | Adds lifecycle status chips and prompt-focus event handling. |
| `packages/builder-workspace/src/views/processing_view.ts` | Prompt processing, review, blocked, and diagnostic views. | Clarifies review/apply/discard language and renders plain blocked/error messages with no-save reassurance. |
| `packages/builder-workspace/src/preview/entity_inspector.ts` | Selected actor/component inspector. | Clarifies selected entity copy, saved project fields, live preview edits, and save-to-project actions. |
| `packages/builder-workspace/src/panels/asset_status_panel.ts` | Asset status and linker dialog. | Renames asset states to imported/needs art/missing, adds repair actions, sorts missing assets first, and listens to the workflow nav. |
| `packages/builder-workspace/src/canvas/model_selector.ts` | Model/provider selector. | Shows local model status, hosted API key status, and current model; Settings opens this selector. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Active project dashboard and project workflows. | Allows direct opening to a specific dashboard tab and reports backend request errors in plain language. |
| `packages/builder-workspace/src/console/decision_bar.ts` | Reusable prompt decision strip. | Aligns labels with the main review surface: Revise Prompt and Apply to Project. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records Builder UX Beyond Health completion. |

Verification:

- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `git diff --check -- packages/builder-workspace/src/layout/main_layout.ts packages/builder-workspace/src/canvas/builder_canvas.ts packages/builder-workspace/src/canvas/prompt_input.ts packages/builder-workspace/src/views/processing_view.ts packages/builder-workspace/src/panels/asset_status_panel.ts packages/builder-workspace/src/canvas/model_selector.ts packages/builder-workspace/src/project/project_dashboard.ts packages/builder-workspace/src/console/decision_bar.ts` passes with only normal Windows line-ending warnings.

Follow-up:

- Builder should still get a final docs/onboarding pass near the end, after remaining launch-readiness features settle.
- A browser screenshot/playthrough should be run when the local Builder server is open, to visually confirm the new workflow nav and panels.

## Thirty-Seventh Slice: Engine Live Validation Evidence Path

Status: Builder, runtime, and all three adapters now have a shared live-validation signal path. Real installed-editor validation on this machine proves Godot live end-to-end through Builder/runtime counters. Real Unity 6000.4.9f1 editor validation proves Unity connection, snapshot delivery, input return, entity/transform application, and feedback return. Real Unreal 5.7 commandlet validation now proves Unreal connection, handshake, snapshot delivery, input return, entity application, and feedback return.

What This Slice Proves:

- Runtime status now reports per-engine connection evidence instead of only generic "runtime is up" health.
- Builder can show a normal-user live validation checklist for Godot, Unity, Unreal, and Headless/demo runtime paths.
- Adapters send generic live-validation feedback after applying runtime state; the proof is not tied to a sword, zombie, or one-game demo.
- Builder blocks Unreal launch with a clear `.NET Framework SDK 4.6+` next step when the prerequisite is missing; after installing the Developer Pack on this machine, Unreal editor-host validation passes.
- The same status shape can prove: adapter connected, snapshot received, input sent back, feedback sent back, and entity/transform delta applied.

Checklist:

- [x] Add per-engine runtime bridge status counters.
- [x] Surface per-engine connection status through runtime control protocol and Builder client types.
- [x] Add adapter-side live-validation feedback pulses for Godot, Unity, and Unreal.
- [x] Add Builder backend `/api/project/demo/live-validation`.
- [x] Add Builder Demo tab "Check Live Validation" action and readable proof rows.
- [x] Detect and explain the Unreal `.NET Framework SDK 4.6+` prerequisite before Unreal live launch.
- [x] Run real installed-editor Godot live validation with the Builder checklist and shared runtime.
- [x] Run Unity installed-editor validation far enough to prove adapter connection, runtime snapshots, and input packets.
- [x] Finish Unity feedback/delta proof from the live editor apply path.
- [x] Run Unreal installed-editor live validation after installing `.NET Framework SDK 4.6+`.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/engine_bridge.rs` | Track engine bridge clients and packets. | Exposes defaultable bridge stats for live-validation reporting. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Own authoritative tick lifecycle and runtime status. | Adds per-engine connection status and aggregate snapshot/input/feedback counters. |
| `packages/runtime-core/src/control_protocol.rs` | Runtime control API payloads. | Adds engine connection status fields to control status responses. |
| `packages/runtime-core/src/control_server.rs` | Serve runtime control commands. | Returns empty live-validation fields when runtime is offline. |
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime executable and control status mapping. | Maps runtime live-validation counters into control API status. |
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime executable live acceptor. | Keeps accepting replacement editor connections so Unity/Godot script reloads do not exhaust the live listener. |
| `adapters/godot/xace_entity_manager.gd` | Own Godot entity nodes and transform/visual updates. | Fixes Godot 4.6 parser/typing issues found during real installed-editor validation. |
| `adapters/godot/xace_godot_main.gd` | Godot validation scene bootstrap. | Avoids a startup look-at warning by adding mesh nodes before orientation. |
| `adapters/godot/xace_delta_applicator.gd` | Apply runtime state messages in Godot. | Sends live-validation feedback after applying snapshots/deltas. |
| `adapters/unity/XaceRuntimeBootstrap.cs` | Unity runtime adapter bootstrap. | Creates or repairs the XACE runtime object automatically when Play mode starts. |
| `adapters/unity/Editor/XaceUnityPlayBootstrap.cs` | Unity editor Play-mode helper. | Ensures the full adapter stack exists when the editor enters Play mode. |
| `adapters/unity/Editor/XaceUnityLiveValidationCommand.cs` | Unity editor validation command. | Runs repeatable editor/batch live validation against a real XACE runtime and reports connection, snapshot, apply, feedback, and protocol-error proof. |
| `adapters/unity/XaceTransport.cs` | Unity transport and runtime protocol model. | Adds companion-component self-repair, stale outbound queue clearing, reconnect-safe immediate feedback sending, safe snapshot-listener dispatch, and transport-level validation feedback hooks. |
| `adapters/unity/XaceInputCollector.cs` | Unity input bridge. | Stops old `UnityEngine.Input` exceptions when projects use the newer Input System only and reacquires the transport after editor reloads. |
| `adapters/unity/XaceConsoleWidget.cs` | Unity in-game XACE console/status widget. | Stops old `UnityEngine.Input` exceptions when projects use the newer Input System only. |
| `adapters/unity/XaceDeltaApplicator.cs` | Apply runtime state messages in Unity. | Keeps its scene root under the persistent XACE object, binds/rebinds to the transport after editor reloads, applies flat and nested transform fields, and sends live-validation feedback after applying snapshots/deltas. |
| `adapters/unreal/XaceTransport.h`, `adapters/unreal/XaceTransport.cpp` | Unreal transport and runtime protocol model. | Adds reusable connection/pump hooks for commandlet/editor validation and sanitizes Unreal's engine version string for the portable handshake contract. |
| `adapters/unreal/XaceInputCollector.h`, `adapters/unreal/XaceInputCollector.cpp` | Send Unreal-side input packets back to the runtime. | Adds explicit transport binding and reflection-safe delegate handlers for commandlet and live editor validation. |
| `adapters/unreal/XaceDeltaApplicator.h`, `adapters/unreal/XaceDeltaApplicator.cpp` | Apply runtime state messages in Unreal. | Sends live-validation feedback after applying snapshots/deltas, self-repairs transport binding, supports flat transform fields, and uses reflection-safe delegate handlers. |
| `adapters/unreal/XaceLiveValidationCommandlet.h`, `adapters/unreal/XaceLiveValidationCommandlet.cpp` | Run repeatable Unreal editor-host validation. | Creates a temporary Unreal validation actor with the real transport/input/delta components, connects to `xace_runtime`, proves handshake/snapshot/apply/input/feedback, and writes JSON proof. |
| `tools/xace_godot_dev.py` | Local Godot/XACE dev helper. | Adds `--godot-project` so validation can launch an isolated adapter-installed Godot project instead of the source adapter project. |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP API and local workflow helpers. | Adds live-validation endpoint, per-engine proof rows, runtime counter parsing, and Unreal prerequisite detection. |
| `packages/builder-workspace/src/api/message_types.ts` | Shared Builder API message types. | Adds runtime bridge engine connection status fields. |
| `packages/builder-workspace/src/api/builder_client.ts` | Builder runtime/control client mapping. | Reads runtime live-validation counters from control status. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project dashboard, demo controls, and engine workflows. | Adds Check Live Validation UI, per-engine proof rows, and readable next steps. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records the engine live-validation evidence path and remaining installed-editor proof. |

Verification:

- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `cargo fmt -p xace-runtime-core` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-engine-live` passes with pre-existing warnings.
- `cargo test -p xace-runtime-core --lib runtime_orchestrator::tests --target-dir target-codex-engine-live` passes: 3 tests.
- `python tools/runtime_bridge_smoke.py --runtime-bin target-codex-engine-live\debug\xace_runtime.exe` passes after rerunning outside the sandbox because the normal runner hit the known spawn-refresh issue.
- `python -m unittest discover packages/builder-workspace/server/tests` passes: 7 tests.
- `cargo test -p xace-runtime-core --lib engine_bridge --target-dir target-codex-engine-live` passes.
- `python -m py_compile tools/xace_godot_dev.py` passes.
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-three-engine` passes after stopping the old runtime process that had locked the Windows executable.
- Real Godot 4.6.3 installed-editor validation passes against the shared Builder runtime: Godot connected, received snapshots, returned input packets, returned feedback messages, and had zero malformed messages. Latest observed Builder counters in the shared run: 3820 Godot snapshots, 3793 Godot input packets, 192 Godot feedback messages, 0 malformed.
- Real Unity 6000.4.9f1 editor validation now passes using `XaceUnityLiveValidationCommand.Run` against a live `xace_runtime`: validation JSON reports `ok=true`, `snapshots=7`, `applied_snapshots=8`, `applied_entities=1`, `feedback_ready=7`, and `protocol_errors=0`.
- During Unity validation, runtime status also observed Unity connected with snapshots/input/feedback accepted and no malformed messages: `snapshots_sent=9`, `input_packets_received=18`, `feedback_messages_received=1`, `malformed_messages=0`. The batch validation exits after proof, so Builder's live panel must be checked while the Unity editor/project is still running.
- Unreal prerequisite is resolved on this machine: `.NET Framework` reference assemblies include `v4.8`, satisfying the old `4.6+` Unreal BuildTool requirement.
- Unreal BuildPlugin passes with the live-validation commandlet: `RunUAT.bat BuildPlugin -Plugin="C:\Users\ankit\OneDrive\Documents\Unreal Projects\MyProject3\Plugins\XACE\XACE.uplugin" -Package="target-codex-unreal-validation\XACEBuiltLiveCommandlet4" -TargetPlatforms=Win64 -Rocket`. UHT, `UnrealEditor` Win64 Development, `UnrealGame` Win64 Development, and `UnrealGame` Win64 Shipping all succeed.
- Real Unreal 5.7 installed-editor validation passes using `UnrealEditor-Cmd.exe` against `C:\Users\ankit\OneDrive\Documents\Unreal Projects\MyProject3\MyProject3.uproject` and the live `xace_runtime` for `C:\Users\ankit\firstgame\game.cgs.json`. Saved report `target-codex-unreal-validation\unreal_live_validation.json` reports `ok=true`, `connected=true`, `handshake_accepted=true`, `applied_snapshots=2`, `applied_entities=1`, `feedback_ready=1`, `input_packets_built=3`, `frames_received=2`, `frames_sent=5`, and `protocol_errors=0`.
- Runtime log during Unreal validation observed: `Handshake from UnrealLiveValidation ...`, `Engine bridge handshake complete`, and `Engine disconnected cleanly`. The control socket is active after validation, but after Unreal disconnects it reports no active engine connection; the persisted proof is the commandlet JSON plus runtime handshake log.

Follow-up:

- Builder Unreal commandlet automation is now implemented in the Thirty-Eighth Slice below.
- Unreal BuildPlugin still prints `WARNING: Unable to find Visual Studio SDK. Editor integration will be disabled`; this did not block compile or live validation, but packaging docs should mention it separately from the resolved `.NET Framework SDK` prerequisite.

## Thirty-Eighth Slice: Builder Unreal Live Validation Automation

Status: Builder can now run the Unreal live-validation path from the Demo tab instead of asking a creator to run Unreal terminal commands. The live-validation endpoint prepares the Unreal adapter for the selected Unreal project, detects the real `.NET Framework SDK` install path, builds editor plugin binaries with RunUAT when needed, starts a temporary XACE runtime when the shared runtime is not already running, runs `UnrealEditor-Cmd.exe -run=XaceLiveValidation`, reads the JSON proof, and folds that proof into the existing live-validation checklist.

What This Slice Proves:

- Unreal live validation is now a Builder-owned workflow, not a manual terminal recipe.
- The three-engine dashboard can install/copy a named engine adapter independently of the active XACE project's default engine type.
- Builder detects `.NET Framework SDK 4.8` from `C:\Program Files (x86)\Windows Kits\NETFXSDK\4.8`, matching the Developer Pack install location on this machine.
- Builder can copy/update `Plugins/XACE`, build packaged Unreal editor binaries, copy `Binaries` back into the selected Unreal project, run the commandlet, and show clear pass/fail proof rows.
- The proof remains general: adapter connected, handshake accepted, snapshot applied, input returned, feedback returned, entity/transform applied, and protocol errors stayed at zero.

Checklist:

- [x] Refactor adapter copy logic so Builder can install a named Godot/Unity/Unreal adapter without changing the active project engine.
- [x] Add Unreal adapter drift detection and automatic reinstall/update for stale or missing plugin files.
- [x] Add Unreal editor binary preparation with RunUAT `BuildPlugin` and binary copy-back.
- [x] Add temporary-runtime orchestration for commandlet validation when Builder's shared demo runtime is not running.
- [x] Add Unreal commandlet execution and JSON report parsing to `/api/project/demo/live-validation`.
- [x] Count successful Unreal commandlet reports as live proof in the existing Builder checklist.
- [x] Send selected/detected executable paths from the Project Dashboard when checking live validation.
- [x] Fix `.NET Framework SDK` detection to include `Windows Kits\NETFXSDK`.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP API and local workflow helpers. | Adds named-engine adapter install, Unreal SDK path detection, Unreal adapter drift checks, RunUAT binary preparation, temporary runtime orchestration, commandlet execution/report parsing, and automatic proof folding for `/api/project/demo/live-validation`. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | Project dashboard, demo controls, and engine workflows. | Sends selected/detected engine executable paths during live validation and explains that Unreal may build the adapter on first run. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records Builder-owned Unreal live-validation automation and verification. |

Verification:

- `python -m py_compile packages/builder-workspace/server/builder_server.py` passes.
- `npm run build` in `packages/builder-workspace` passes: TypeScript strict check plus Vite production build.
- Direct detector check now returns `.NET Framework SDK 4.8` at `C:\Program Files (x86)\Windows Kits\NETFXSDK\4.8`.
- Direct Builder helper verification against active XACE project `C:\Users\ankit\firstgame` and Unreal project `C:\Users\ankit\OneDrive\Documents\Unreal Projects\MyProject3` passes.
- Builder helper copied/updated `C:\Users\ankit\OneDrive\Documents\Unreal Projects\MyProject3\Plugins\XACE`, rebuilt with:
  `RunUAT.bat BuildPlugin -Plugin="C:\Users\ankit\OneDrive\Documents\Unreal Projects\MyProject3\Plugins\XACE\XACE.uplugin" -Package="C:\Users\ankit\Downloads\xace\target-codex-unreal-validation\builder-live\XACEBuilt-1780636179" -TargetPlatforms=Win64 -Rocket`
- BuildPlugin succeeded and copied packaged binaries from `target-codex-unreal-validation\builder-live\XACEBuilt-1780636179\Binaries` back to `MyProject3\Plugins\XACE\Binaries`.
- Latest Builder-run Unreal commandlet report `target-codex-unreal-validation\builder-live\unreal_live_validation_*.json` reports `ok=true`, `connected=true`, `handshake_accepted=true`, `applied_snapshots=2`, `applied_entities=1`, `feedback_ready=1`, `input_packets_built=2`, `frames_received=2`, `frames_sent=4`, and `protocol_errors=0`.

Follow-up:

- Wire the same installed-editor validation checks into the launch certification command so one product check can report editor-free and installed-editor readiness separately.
- Add a browser/playthrough screenshot pass for the Project Dashboard once the local Builder server is open, to visually confirm the new status rows and first-run Unreal message.

## Thirty-Ninth Slice: Launch Certification Installed-Engine Gate

Status: the launch certification command now has an explicit installed-engine layer. By default it still runs the editor-free product checks. When called with `--installed-engines`, it can also validate real installed Godot, Unity, and Unreal editor paths against an XACE project and report the results in one certification summary.

What This Slice Proves:

- `tools/certify_launch.py` now separates editor-free launch readiness from installed-editor readiness instead of mixing them silently.
- The installed-engine layer can discover saved project paths from the XACE manifest or accept explicit `--godot-project`, `--unity-project`, and `--unreal-project` paths.
- The gate can require specific engines with `--require-installed-engines godot,unity,unreal`, so missing editor validation fails clearly.
- Godot validation uses a headless installed-editor runner that executes the real Godot adapter, writes JSON proof, and verifies connection, snapshot apply, input send, feedback send, and zero malformed frames.
- Unity validation runs the existing real Unity editor command path and parses its JSON proof.
- Unreal validation reuses Builder-owned commandlet automation, including adapter preparation and binary build/copy when needed.

Checklist:

- [x] Add installed-engine CLI options to `tools/certify_launch.py`.
- [x] Keep the default certification editor-free unless `--installed-engines` is passed.
- [x] Reuse Builder project/adapter helpers instead of duplicating engine-install logic.
- [x] Add Godot installed-editor certification using a generated validation runner and JSON report.
- [x] Add Godot adapter counters for input packets and feedback payloads.
- [x] Preserve Unity installed-editor validation through `XaceUnityLiveValidationCommand.Run`.
- [x] Preserve Unreal installed-editor validation through the Builder commandlet helper.
- [x] Write an installed-engine JSON summary under the certification target directory.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/certify_launch.py` | Product launch certification command. | Adds `--installed-engines`, project/executable path options, required-engine gating, per-engine installed validation, installed summary JSON, Godot validation-runner generation, and clear editor-free vs installed-engine output. |
| `adapters/godot/xace_adapter.gd` | Coordinate Godot transport, input, delta application, and feedback. | Exposes generic live-proof counters for input packets sent and feedback payloads sent. |
| `adapters/godot/xace_godot_main.gd` | Godot scene entry point and runtime argument parsing. | Reads Godot user command-line args after `--`, which installed-editor launches need for XACE host/port/hash arguments. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records installed-engine launch certification and updates Godot/tooling status. |

Verification:

- `python -m py_compile tools/certify_launch.py` passes.
- Editor-free launch certification passes: `python tools/certify_launch.py --quick --target-dir target-codex-certify-installed-smoke`.
- Godot-only installed certification passes: `python tools/certify_launch.py --quick --target-dir target-codex-certify-installed-smoke --installed-engines --xace-project C:\Users\ankit\firstgame --require-installed-engines godot --installed-engine-timeout 30`.
- Full strict installed certification passes:
  `python tools/certify_launch.py --quick --target-dir target-codex-certify-installed-smoke --installed-engines --xace-project C:\Users\ankit\firstgame --unity-project C:\Users\ankit\firstgame --unreal-project "C:\Users\ankit\OneDrive\Documents\Unreal Projects\MyProject3" --require-installed-engines godot,unity,unreal`.
- Full strict result: editor-free checks passed, Godot passed from `godot_report` with `connected=True`, `snapshots=1`, `inputs=2`, `feedback=1`, `malformed=0`; Unity passed with `connected=True`, `handshake=True`, `snapshots=2`, `applied=3`, `entities=1`, `feedback=2`, `protocol_errors=0`; Unreal passed with `2` snapshots, `1` applied entity, `5` input packets, `1` feedback message, and `0` protocol errors.

Follow-up:

- This finishes the major engine-validation automation gate. It does not by itself make the engine side fully user-ready; remaining user-ready work is the visual Builder playthrough, one-click packaged launcher/onboarding so users do not start server/UI manually, and final docs/troubleshooting after the UI flow settles.

## Fortieth Slice: One-Click Builder Launcher

Status: local one-click Builder launch is now implemented. A non-technical user can double-click `Start XACE Builder.cmd` on Windows, or a developer can run `npm run xace:builder`, and XACE starts the current Builder backend, serves the built Builder UI, opens the browser, remembers the active project, and optionally starts the live runtime.

What This Slice Proves:

- Builder startup no longer requires separate manual commands for backend and UI.
- The default launch path serves the built production UI from the Builder backend instead of requiring a Vite dev server.
- The Builder UI derives its WebSocket URL from the opened page when no explicit `VITE_WS_URL` is provided, so production launches work on any selected local port.
- The launcher remembers the last active project through a small local state file; when Builder switches projects in the UI, the next launcher start can reuse that project.
- The launcher can still run in developer mode with `--dev-ui` for hot reload.
- The launcher can start `xace_runtime` for the active project with live-engine accept enabled, while also supporting `--no-runtime` for server-only checks.
- The launcher now ignores the repository root as an automatic remembered/default project and validates the runtime binary before launch, so stale local builds cannot crash the double-click path with missing live-engine flags.
- Builder folder browsing now opens the native picker through a short-lived helper process, so a Windows folder picker failure cannot crash the local Builder server.

Checklist:

- [x] Add a general Builder launcher separate from the Godot-specific dev loop.
- [x] Add a Windows double-click wrapper.
- [x] Add a root npm script for the launcher.
- [x] Serve the built Builder UI through the backend by default.
- [x] Keep a Vite dev-server option for development.
- [x] Remember the last active project from Builder server startup/switch flows.
- [x] Add dry-run and log-folder support for verification and troubleshooting.
- [x] Guard one-click startup against stale runtime binaries and accidental repo-root project selection.
- [x] Isolate the local folder picker used by Open Project, Import Engine Project, and adapter-copy paths.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/xace_builder_launch.py` | Product-style local launcher for Builder, UI, and optional runtime. | Starts Builder from one command, chooses ports, builds missing UI/runtime artifacts when allowed, serves production UI, opens the browser, writes logs, remembers project state, supports dry-run and dev UI mode; validates launcher-required runtime flags and avoids using the repo root as an implicit project. |
| `Start XACE Builder.cmd` | Windows visible launch entry point. | Lets a user double-click XACE Builder without typing terminal commands. |
| `packages/builder-workspace/src/app.ts` | Builder browser app bootstrap. | Computes the default WebSocket URL from `window.location`, so the built UI works from the backend URL and selected port. |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server and active project lifecycle. | Writes launcher state on startup, active project creation, project switch, and active import; runs native folder picking in a helper process so UI Browse actions do not crash the server. |
| `package.json` | Root package scripts/workspace metadata. | Adds `packages/builder-workspace` as a workspace and `npm run xace:builder`. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records one-click Builder launcher completion and verification. |

Verification:

- `python -m py_compile tools/xace_builder_launch.py packages/builder-workspace/server/builder_server.py` passes.
- Launcher dry-run passes for the real active project:
  `python tools/xace_builder_launch.py --dry-run --project C:\Users\ankit\firstgame --no-runtime --no-open-browser --ui-build never --state-file target-codex-launcher-smoke\state.json --log-dir target-codex-launcher-smoke\logs`.
- `npm run build` in `packages/builder-workspace` passes and writes production UI to `packages/builder-server/dist`.
- Server smoke passes: `python tools/xace_builder_launch.py --project C:\Users\ankit\firstgame --no-runtime --no-open-browser --ui-build never --port 8899 --strict-port --state-file target-codex-launcher-smoke\state.json --log-dir target-codex-launcher-smoke\logs` starts Builder, and `curl.exe -s http://127.0.0.1:8899/api/project` returns `ok=true` for `C:\Users\ankit\firstgame`.
- Runtime-backed launcher smoke passes: `python tools/xace_builder_launch.py --project C:\Users\ankit\firstgame --no-open-browser --ui-build never --port 8899 --runtime-control-port 8900 --runtime-port 8901 --strict-port --state-file target-codex-launcher-smoke\state.json --log-dir target-codex-launcher-smoke\logs` starts the rebuilt launcher runtime and Builder, and `curl.exe -s http://127.0.0.1:8899/api/project` returns `ok=true` for `C:\Users\ankit\firstgame`.
- Import/adapter smoke passes through the local Builder server on port `8899`: `/api/project/adapter/reinstall` reports a healthy Godot adapter with `12/12` files, and `/api/project/import-engine` creates `target-codex-import-ui-smoke\xace-imported` with `xace.project.json`, `game.cgs.json`, and healthy prepared adapter files.
- After stopping the smoke launcher, the same test port no longer responds, confirming no background server was left running.

How A User Starts XACE:

- Double-click `Start XACE Builder.cmd`.
- If it opens a starter project, click `Project`, choose `Open Project`, browse to the desired XACE project folder, and open it. The launcher remembers that project for the next start.
- Close the launcher window to stop local XACE services.

Follow-up:

- Build the final visual Builder playthrough/screenshot pass: launch from the double-click wrapper, open a project, create or apply one prompt change, inspect assets/project/preview, and confirm all user-facing errors are understandable.
- Later packaging can wrap the same launcher behavior in a desktop shell/installer.

## Forty-First Slice: BYOK Provider Settings Batch 1

Status: the first mass-user provider-settings batch is implemented. Builder now exposes a visible local settings flow for Ollama, Anthropic Claude, OpenAI, Google Gemini, and Kimi/Moonshot. API keys are saved outside XACE project files in local machine settings, provider health can run a real test call, and missing/broken hosted configuration blocks clearly instead of returning mock success.

What This Slice Proves:

- A normal user can choose provider, model, and API key from the Builder UI instead of terminal environment variables.
- The server stores provider settings under `~/.xace/provider_settings.json`, not in the active project folder.
- Hosted provider testing checks key presence, model reachability, and a real minimal completion.
- The prompt path builds the real shared `InferenceAdapter` for hosted providers, then routes PIL calls through the existing inference layer.
- Unsupported or unconfigured hosted providers now fail clearly instead of silently falling back to a provider test double.
- Launcher/server CLI flags accept `anthropic`, `openai`, `google`, and `moonshot` for scripted local launches.

Checklist:

- [x] Add local provider settings storage outside project files.
- [x] Add hosted provider factories for Anthropic, OpenAI-compatible providers, Google Gemini, and Kimi/Moonshot.
- [x] Add provider settings and provider test HTTP endpoints.
- [x] Replace the old local-only model dropdown with provider, key, model, save, and test controls.
- [x] Preserve old `/api/models` compatibility while returning richer provider metadata.
- [x] Fix inference prompt payload handoff so real providers receive prepared payloads with system prompts.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/provider_settings.py` | Local provider settings, key handling, health checks, and adapter construction. | Adds provider definitions, local settings storage, obfuscated local key persistence, model discovery, real test calls, and hosted adapter construction. |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP/WebSocket server. | Adds `/api/provider-settings` get/save/test endpoints and hosted provider CLI support. |
| `packages/builder-workspace/server/session_manager.py` | Session lifecycle and PIL adapter ownership. | Loads saved provider settings, activates launch overrides, builds real adapters from local settings, and blocks unavailable providers clearly. |
| `packages/builder-workspace/server/ws_message_router.py` | WebSocket message routing. | Routes model changes through the provider settings store before hot-swapping the active session adapter. |
| `packages/builder-workspace/src/canvas/model_selector.ts` | Bottom-bar provider/model UI. | Adds provider selection, API key input, model select/manual entry, Save, Test, and health/status display. |
| `packages/inference/providers/openai_provider.py` | OpenAI-compatible provider client. | Adds a canonical importable provider module for OpenAI and compatible endpoints such as Moonshot. |
| `packages/inference/src/inference_adapter.py` | Provider-agnostic LLM dispatch. | Passes system prompts into prompt preparation, sends provider clients the prepared payload, and forwards tier/provider/model to retry policy. |
| `packages/inference/src/prompt_cache.py` | Provider-specific prompt preparation. | Renames the internal dataclass field away from `__format__` while preserving the wire payload key. |
| `tools/xace_builder_launch.py` | Product-style local launcher. | Accepts all supported provider IDs and generic hosted API keys. |

Verification:

- `python -m py_compile packages/builder-workspace/server/provider_settings.py packages/builder-workspace/server/builder_server.py packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/ws_message_router.py packages/inference/providers/openai_provider.py packages/inference/src/inference_adapter.py packages/inference/src/prompt_cache.py tools/xace_builder_launch.py` passes.
- `npm run build` in `packages/builder-workspace` passes.
- Hosted adapter construction check passes for OpenAI, Google, and Kimi/Moonshot with fake keys without making network calls.
- Launcher dry-run accepts hosted provider flags: `python tools/xace_builder_launch.py --dry-run --no-runtime --no-open-browser --ui-build never --model-provider google --model gemini-test`.

Follow-up:

- Run real provider health checks with actual BYOK keys for OpenAI, Gemini, Claude, and Kimi.
- Add the end-to-end proof prompt: provider test passed -> prompt -> PIL -> GDE -> schema validation -> CGS mutation -> snapshot -> runtime reload -> engine update.
- Consider replacing local obfuscation with an OS key vault before final installer packaging.

## Forty-Second Slice: Provider Readiness Prompt Gate

Status: provider readiness now gates prompt execution. XACE will not start the PIL prompt pipeline if the selected provider cannot actually run prompts. Local modes require reachable Ollama; hosted modes require a saved key and a successful health test for the exact provider, model, base URL, and key fingerprint. Changing the key, model, or base URL invalidates the old health proof.

What This Slice Proves:

- A hosted provider can no longer be selected and then used for prompts before a real health test has passed.
- A changed hosted model cannot reuse a stale health-test result from a previous model.
- Local Ollama offline state blocks clearly before the prompt enters PIL.
- The Builder UI receives explicit readiness metadata instead of inferring prompt readiness only from generic health.
- Blocked provider configuration uses the existing normal-user blocked view, so no CGS mutation or snapshot is presented as successful.

Checklist:

- [x] Add provider readiness records to local provider settings.
- [x] Invalidate saved health tests when provider model or base URL changes.
- [x] Store provider/model/base URL/key fingerprint with each successful test.
- [x] Add `/api/provider-settings/readiness`.
- [x] Gate `SessionManager.run_pil()` before PIL begins.
- [x] Update the provider UI to show prompt readiness separately from raw health.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/provider_settings.py` | Local provider settings, health checks, and readiness. | Adds exact-match readiness metadata and invalidates stale test proof on key/model/base URL changes. |
| `packages/builder-workspace/server/session_manager.py` | Session lifecycle and PIL execution. | Blocks prompt execution when the active provider is not ready, returning a normal blocked result. |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP API. | Adds `/api/provider-settings/readiness`. |
| `packages/builder-workspace/src/canvas/model_selector.ts` | Bottom-bar provider/model UI. | Displays prompt readiness and uses readiness for provider status dots. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records provider readiness gating. |

Verification:

- `python -m py_compile packages/builder-workspace/server/provider_settings.py packages/builder-workspace/server/builder_server.py packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/ws_message_router.py packages/inference/providers/openai_provider.py packages/inference/src/inference_adapter.py packages/inference/src/prompt_cache.py tools/xace_builder_launch.py` passes.
- `npm run build` in `packages/builder-workspace` passes.
- Local readiness smoke passes with a throwaway settings file: untested OpenAI blocks, matching health-test proof opens readiness, changing the model blocks again.

Follow-up:

- Once real keys are available, run provider tests from the UI and then run the full prompt-through-runtime proof for each supported hosted provider.
- Keep certification coverage aligned as the provider flow evolves.

## Forty-Third Slice: Provider Readiness Certification

Status: the one-command launch certification now covers the provider readiness gate. Quick and full editor-free certification run a dedicated provider-readiness smoke, and the deterministic prompt pipeline contract/scenario smoke now uses isolated throwaway provider settings so it proves the supported prompt contract with the readiness gate enabled instead of depending on the user's real local settings.

What This Slice Proves:

- Certification catches the mass-user failure case where a hosted provider has a saved key but no successful health test.
- Certification proves a matching health proof lets a supported prompt enter the PIL path.
- Certification proves changing the selected hosted model invalidates the old health proof and blocks prompts again.
- Prompt pipeline contract/scenario smoke no longer reads or modifies the user's real `~/.xace/provider_settings.json`.
- The launch check now reports provider readiness as a first-class editor-free product gate.

Checklist:

- [x] Add isolated provider settings path support for local smoke/certification runs.
- [x] Add a provider-readiness smoke that checks untested, ready, and stale-proof states.
- [x] Add the provider-readiness smoke to `tools/certify_launch.py` quick/full checks.
- [x] Update prompt pipeline contract/scenario smoke so provider readiness remains enabled during deterministic PIL/GDE certification.
- [x] Run quick certification with the new provider check included.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/provider_settings.py` | Local provider settings, health checks, and readiness. | Adds `XACE_PROVIDER_SETTINGS_PATH` so tests and certification can use isolated local settings without touching user settings. |
| `tools/provider_readiness_smoke.py` | Editor-free provider readiness certification. | Adds the dedicated smoke for untested hosted provider blocking, matching health-proof readiness, and stale-proof invalidation. |
| `tools/prompt_pipeline_smoke.py` | Editor-free prompt pipeline contract/scenario certification. | Seeds an isolated matching provider health proof before running deterministic supported/unsupported prompt scenarios through the real SGC binary path. |
| `tools/certify_launch.py` | Product launch certification command. | Adds provider readiness smoke to quick/full checks and compiles the provider settings module. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records provider readiness certification coverage. |

Verification:

- `python -m py_compile tools/prompt_pipeline_smoke.py tools/provider_readiness_smoke.py tools/certify_launch.py packages/builder-workspace/server/provider_settings.py packages/builder-workspace/server/session_manager.py` passes.
- `python tools/provider_readiness_smoke.py --settings-path target-codex-provider-readiness-cert\provider_settings.json` passes.
- `python tools/prompt_pipeline_smoke.py --skip-runtime --provider-settings-path target-codex-provider-readiness-cert\prompt_provider_settings.json` passes.
- Quick launch certification passes with 9 checks, including provider readiness smoke:
  `python tools/certify_launch.py --quick --target-dir target-codex-certify-provider-readiness`.

## Forty-Fourth Slice: Launch-Ready Builder Onboarding

Status: the Builder now gives a normal first-run user clearer project/provider/runtime readiness signals and blocks prompt submission with one obvious provider action when the selected provider is not ready. New/open/wrap-link project flows also reject the XACE source checkout as a game project target, so double-click launch is less likely to strand users in the repo root.

What This Slice Proves:

- The top bar shows first-run readiness for Project, Provider, and Runtime.
- Prompt submission is blocked before WebSocket/PIL work when provider readiness is missing.
- The blocked prompt state opens the Provider Settings panel and asks the user to choose a provider and run Test.
- Provider Test now saves the chosen provider/model/key first, then records readiness proof against the saved key fingerprint.
- New Project defaults to a sibling game-project folder instead of the active folder.
- Builder backend routes reject the XACE source checkout for create/open/switch/wrap-link project actions.
- Quick certification now includes an offline onboarding smoke for project-folder safety.

Checklist:

- [x] Add shared provider-readiness state to the Builder client.
- [x] Publish readiness from the provider/model settings UI.
- [x] Disable/block prompt submission when provider readiness is missing.
- [x] Add Project/Provider/Runtime readiness chips to the main top bar.
- [x] Harden New/Open/Wrap-Link project path validation in the UI.
- [x] Harden project routes against using the XACE source checkout as a game project.
- [x] Add onboarding smoke to launch certification.
- [x] Run launcher/API smoke without using hosted API credits.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/src/api/builder_client.ts` | Builder client state and subscriptions. | Adds shared provider readiness state for prompt and layout UI. |
| `packages/builder-workspace/src/canvas/model_selector.ts` | Provider/model settings UI. | Publishes readiness and saves provider settings before running Test. |
| `packages/builder-workspace/src/canvas/prompt_input.ts` | Prompt submission surface. | Blocks unready providers with a Provider Settings action before PIL/WebSocket work. |
| `packages/builder-workspace/src/layout/main_layout.ts` | Main Builder shell. | Adds Project/Provider/Runtime readiness chips to the top bar. |
| `packages/builder-workspace/src/project/project_dashboard.ts` | New/Open/Wrap-Link project flows. | Suggests safer new-project paths and blocks obvious source-root/broken folder choices. |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP API. | Rejects source checkout folders in project create/open/switch/import routes. |
| `tools/builder_onboarding_smoke.py` | Editor-free onboarding certification. | Proves source checkouts are rejected and a generated game project opens normally. |
| `tools/certify_launch.py` | Launch certification command. | Adds onboarding smoke to quick/full certification and module compilation. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records launch-ready Builder onboarding coverage. |

Verification:

- `python -m py_compile tools/builder_onboarding_smoke.py tools/certify_launch.py packages/builder-workspace/server/builder_server.py` passes.
- `npm run build` in `packages/builder-workspace` passes.
- `python tools/builder_onboarding_smoke.py --target-dir target-codex-onboarding-smoke` passes.
- Local launcher/API smoke passes without runtime, browser launch, or hosted API calls:
  - `/api/project` opens the generated game project.
  - `/api/provider-settings/readiness` reports an offline provider block instead of attempting a hosted call.
  - `/api/project/open` rejects `C:\Users\ankit\Downloads\xace` with a friendly source-checkout error.
- Quick launch certification passes with 10 checks, including provider readiness and onboarding smoke:
  `python tools/certify_launch.py --quick --target-dir target-codex-certify-onboarding`.

## Forty-Fifth Slice: Python Test Gate

Status: Task 10 now has a single Python-only command for production Python package tests and repository Python tools. The gate isolates provider settings and credential writes under the generated target output directory, runs each Python package test surface with the import path it needs, runs governance/security tool checks, and writes a JSON artifact.

What This Slice Proves:

- One root command covers project-system, asset-registry, Builder server, save-engine, schema-factory, GDE, inference, and prompt-intelligence Python tests.
- Pytest-style package tests can run even in environments where the external pytest package is absent.
- Prompt/provider tests use generated settings paths instead of `~/.xace/provider_settings.json`.
- Tool coverage includes commercial scope, source inventory, workspace membership, fake/skip register, production path rules, forbidden claims, source secret scan, and syntax checks.
- The result is retained as machine-readable JSON.

Command:

```powershell
python tools/python_test_gate.py --output target-codex-python/python_gate_report.json
```

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/python_test_gate.py` | Python package/tool readiness gate. | Adds isolated suite orchestration and JSON artifact output. |
| `package.json` | Root developer command manifest. | Adds `xace:python`. |
| `packages/inference/src/model_router.py` | Hybrid model routing. | Requires registered/healthy provider clients and keeps local TIER_M behind local-manager availability. |
| `packages/inference/src/prompt_cache.py` | Provider prompt normalization. | Preserves prompt format compatibility and normalizes prepared payloads before provider conversion. |
| `packages/inference/tests/test_model_router.py` | Inference routing tests. | Aligns expected default providers with hybrid routing. |
| `packages/inference/tests/test_prompt_cache.py` | Prompt cache tests. | Proves non-Anthropic prompt conversion strips Anthropic cache directives. |
| `packages/prompt-intelligence/src/context_assembler/__init__.py` | Prompt-intelligence package exports. | Exposes the context assembler package API used by tests and pipeline imports. |
| `packages/prompt-intelligence/src/llm_orchestrator/__init__.py` | Prompt-intelligence package exports. | Exposes the LLM orchestrator package API used by tests and pipeline imports. |
| `packages/prompt-intelligence/src/memory_model/__init__.py` | Prompt-intelligence package exports. | Exposes the memory model package API used by tests and pipeline imports. |
| `docs/fake_skip_register.json` | Machine fake/skip register. | Registers the Python gate's governance/accounting terminology. |
| `docs/XACE_FAKE_AND_SKIP_REGISTER.md` | Human fake/skip register. | Mirrors the Python gate register entry. |
| `docs/source_inventory.json` | Machine source inventory. | Classifies the new Python gate. |
| `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Human source inventory. | Documents the new gate in the tools inventory. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records Task 10 coverage. |

Verification:

- `python tools/python_test_gate.py --output target-codex-python/python_gate_report.json` passes.
- JSON artifact written to `target-codex-python/python_gate_report.json`.
- Artifact summary: 1,182 tests passed, 0 failures/errors, 0 not-run; 7 tool checks passed, 0 tool failures; 258 production Python files syntax-checked, 0 syntax failures.
- Provider settings and credential writes are isolated under `target-codex-python/python_gate_work/isolated_settings`.

## Forty-Sixth Slice: Builder Test Gate

Status: Task 11 now has a declared Builder test command that covers TypeScript lint-style checks, TypeScript typecheck, UI contract assertions, and the Builder server contract unittest suite. CI now runs both the Builder production build and the declared Builder test command.

What This Slice Proves:

- `npm run build` still typechecks and production-builds the Builder UI.
- `npm run lint` rejects unused TypeScript locals/parameters in the Builder UI source.
- `npm run test:ui` verifies the browser-side WebSocket, provider readiness, provider settings, and top-bar readiness contracts without adding a test framework dependency.
- `npm run test:server` runs the Builder server contract surface under `server/tests`.
- CI installs Builder dependencies, builds the Builder workspace, and runs the declared Builder test command.

Commands:

```powershell
npm run build
npm run test
```

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/package.json` | Builder workspace command manifest. | Adds `lint`, `test:ui`, `test:server`, and aggregate `test`. |
| `packages/builder-workspace/tools/builder_ui_contract_test.mjs` | No-dependency Builder UI contract test. | Proves browser contract wiring for WebSocket messages, provider readiness, provider testing, and readiness chips. |
| `package.json` | Root developer command manifest. | Adds `xace:builder-test`. |
| `.github/workflows/xace-scope.yml` | CI governance and Builder gates. | Adds Builder build/test job. |
| `packages/builder-workspace/src/canvas/model_selector.ts` | Provider/model settings UI. | Removes unused lint blocker. |
| `packages/builder-workspace/src/canvas/prompt_input.ts` | Prompt submission surface. | Removes unused lint blocker. |
| `packages/builder-workspace/src/graph/system_node_graph.ts` | System graph view. | Removes unused lint blocker. |
| `packages/builder-workspace/src/sidebar/component_inspector.ts` | Component inspector. | Removes unused lint blocker. |
| `packages/builder-workspace/src/sidebar/entity_tree.ts` | Entity tree view. | Removes unused lint blocker. |
| `packages/builder-workspace/src/views/processing_view.ts` | Processing/idle/review views. | Removes unused lint blockers. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records Task 11 coverage. |

Verification:

- `npm.cmd run test` in `packages/builder-workspace` passes: strict TypeScript lint, typecheck, UI contract test, and 30 Builder server tests.
- `npm.cmd run build` in `packages/builder-workspace` passes.
- Governance checks still pass after the new CI/test files:
  - `python tools/source_inventory_check.py`
  - `python tools/fake_skip_register_check.py`
  - `python tools/production_path_check.py`

## Forty-Seventh Slice: Certification Artifact Gate

Status: Task 12 makes launch certification artifact-backed in both quick and full modes. The launcher now writes a top-level JSON report for passed and failed runs, records quick-mode full-check omissions as explicit skipped checks, and writes an installed-engine summary even when Godot/Unity/Unreal validation is not requested.

What This Slice Proves:

- Certification no longer relies on console-only pass/fail state.
- Failed editor-free checks write `launch_certification_report.json` before the command exits.
- Quick mode records omitted full-mode checks under `editor_free.skipped_checks`.
- Runs without `--installed-engines` record Godot, Unity, and Unreal as skipped plus unsupported for that run.
- Full mode records zero editor-free skipped checks while still recording unsupported installed-engine proof gaps when installed editors are not run.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/certify_launch.py` | Launch certification command. | Adds JSON pass/fail reporting, quick skipped-check artifacts, installed-engine skip summaries, report path support, and captured failure output tails. |
| `docs/fake_skip_register.json` | Machine fake/skip register. | Updates FSR-004 to point at the new certification artifacts instead of the old console-only skip. |
| `docs/XACE_FAKE_AND_SKIP_REGISTER.md` | Human fake/skip register. | Mirrors the FSR-004 artifact-backed certification status. |
| `docs/XACE_BASELINE_FAILURE_LIST.md` | Historical Task 5 baseline. | Adds a Task 12 resolution note without rewriting the historical baseline. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records Task 12 coverage. |

Verification:

- `python -m py_compile tools/certify_launch.py` passes.
- Quick certification passes with 17 executed checks, 7 recorded quick-mode skipped checks, and unsupported Godot/Unity/Unreal entries:
  `python tools/certify_launch.py --quick --target-dir target-codex-certify-task12-quick`.
- Full certification passes with 24 executed checks, 0 editor-free skipped checks, and unsupported Godot/Unity/Unreal entries:
  `python tools/certify_launch.py --target-dir target-codex-certify-task12-full`.
- Intentional failure probe writes `target-codex-certify-task12-fail/launch_certification_report.json` with top-level `ok: false`, a failed check artifact, and installed-engine unsupported skip entries.
- Installed-engine fallback probe writes `target-codex-certify-task12-installed-fail/launch_certification_report.json` with `requested: true` and Godot/Unity/Unreal marked skipped plus unsupported when installed validation cannot produce its own summary.

## Forty-Eighth Slice: No Silent Success Gate

Status: Task 17 converts the audited silent-success paths into explicit blocked/unsupported responses and adds a certification guard that fails if those paths regress.

What This Slice Proves:

- Completed GDE clarification sessions no longer report success unless a CGS mutation was committed.
- Structural Builder prompt applies cannot persist or broadcast a CGS update when SGC proof is unavailable.
- Runtime animation transitions reject non-forced interruption attempts with a stable actionable error code.
- Headless adapter endpoints return explicit `not_applicable` metadata instead of ambiguous success-only payloads.
- Launch certification now runs the no-silent-success guard in quick and full modes.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/gde/src/gde_orchestrator.py` | GDE prompt/clarification orchestration. | Adds actionable code/action/unsupported metadata and blocks completed clarification sessions that have not committed CGS. |
| `packages/gde/src/tests/test_gde_orchestrator.py` | GDE integration coverage. | Verifies completed clarification requires a re-prompt and leaves the CGS hash unchanged. |
| `packages/builder-workspace/server/session_manager.py` | Prompt session and SGC compilation helpers. | Marks unconfigured/no-system SGC results with stable codes, categories, actions, and unsupported metadata. |
| `packages/builder-workspace/server/ws_message_router.py` | Builder WebSocket mutation apply routing. | Rejects structural apply when SGC returns an unsupported skipped status, records audit evidence, and sends `server_error`. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Builder prompt pipeline coverage. | Proves structural apply without SGC restores the pre-apply state, does not persist partial artifacts, does not emit `cgs_update`, and records recovered rollback audit evidence. |
| `packages/runtime-core/src/dcl/character/animation_layer_manager.rs` | Runtime animation layer transitions. | Returns `ANIMATION_TRANSITION_IN_PROGRESS` instead of accepting a no-op transition. |
| `packages/builder-workspace/server/builder_server.py` | Builder project/adapter API. | Marks headless adapter responses as `not_applicable` with code/action metadata. |
| `tools/silent_success_check.py` | Governance guard. | Adds the Task 17 no-silent-success regression check and JSON artifact output. |
| `tools/certify_launch.py` | Launch certification command. | Runs the no-silent-success guard in quick/full certification and py-compiles it. |
| `package.json` | Root developer command manifest. | Adds `xace:silent-success`. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory. | Classifies the new guard. |
| `docs/fake_skip_register.json`, `docs/XACE_FAKE_AND_SKIP_REGISTER.md`, `docs/production_path_rules.json` | Governance registers/rules. | Registers guard terminology and removes a stale allowed SGC log finding. |
| `docs/LAUNCH_READINESS_MAP.md` | Track launch-readiness slices and verification. | Records Task 17 coverage. |

Verification:

- `python tools/silent_success_check.py --output target-codex-silent-success/silent_success_report.json` passes.
- `python -m unittest discover -s packages/builder-workspace/server/tests -p "test_prompt_pipeline_e2e.py"` passes.
- `python tools/python_test_gate.py --output target-codex-task17-python/python_gate_report.json` passes.
- `cargo test -p xace-runtime-core dcl::character::animation_layer_manager --lib --target-dir target-codex-task17-runtime` passes.
- Governance checks pass:
  - `python tools/source_inventory_check.py`
  - `python tools/fake_skip_register_check.py`
  - `python tools/production_path_check.py`
  - `python tools/forbidden_claims_check.py`
- Quick certification passes with the no-silent-success guard included:
  `python tools/certify_launch.py --quick --target-dir target-codex-certify-task17-quick`.

## Forty-Ninth Slice: Real SGC Prompt Proof

Status: Task 18 removes the fake SGC helper from prompt/certification execution. The prompt pipeline smoke now requires a compiled `xace-system-graph-compiler` binary, certification passes the just-built SGC binary into that smoke, and structural accepted prompt scenarios must produce persisted SGC proof bundles before the Builder broadcasts a CGS update.

What This Slice Proves:

- Prompt certification cannot pass without an SGC binary on disk.
- Supported structural prompt scenarios use the real SGC CLI path and verify `.xace/proof/sgc/<hash>/input.json`, `plan.json`, and `metadata.json`.
- Builder production documentation now says structural prompt applies block when `--sgc-bin` is absent.
- The fake SGC helper remains only in the Builder server test suite, where it is labeled as wiring-test-only coverage.
- The no-silent-success guard now fails if prompt proof loses the real-SGC path.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/prompt_pipeline_smoke.py` | Editor-free prompt pipeline contract/scenario certification. | Removes the wiring-only SGC helper, requires `--sgc-bin`, uses `SessionManager` with the compiled SGC binary, and verifies real proof bundles for structural prompts. |
| `tools/certify_launch.py` | Launch certification command. | Passes the built SGC binary into prompt pipeline certification. |
| `packages/builder-workspace/server/builder_server.py` | Builder server entry point and CLI docs. | Documents that structural prompt applies block when SGC is not configured. |
| `tools/silent_success_check.py` | Governance guard. | Adds real-SGC prompt-proof regression checks. |
| `docs/fake_skip_register.json`, `docs/XACE_FAKE_AND_SKIP_REGISTER.md`, `docs/production_path_rules.json` | Governance registers/rules. | Isolates fake SGC to Builder tests and removes stale production allowed findings. |
| `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | Readiness and claims records. | Updates SGC/prompt reality to reflect real-binary prompt certification while keeping runtime `ExecutionPlan` loading scoped as pending. |

Verification:

- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-certify-task17-quick/debug/xace_runtime.exe --sgc-bin target-codex-certify-task17-quick/debug/xace-system-graph-compiler.exe` passes.
- Task 18 final verification runs the syntax, prompt smoke, guard, governance, Builder test, and quick-certification checks listed in the task report.

## Fiftieth Slice: Test Fixture Isolation

Status: Task 19 removes remaining prompt fake/fallback helpers from Builder production code and moves deterministic prompt contract scenarios under Builder test fixtures. Production prompt execution now either uses the real PIL/provider path or blocks with `PIL_UNAVAILABLE`; production-path scanning no longer carries `_MockAdapter` or `SimplePipeline` allowlist entries.

What This Slice Proves:

- `SessionManager` no longer defines or executes the old fallback prompt pipeline or provider test double.
- Missing `PILPipeline` produces an explicit blocked unsupported result instead of synthesizing a mutation transaction.
- The deterministic prompt contract lives under `packages/builder-workspace/server/tests/fixtures/`, and only tests/smoke tools import it.
- Production import scanning blocks test fixture, fake, mock, and smoke helper imports from production files.
- The no-silent-success guard now fails if the old prompt fallback or provider test double returns to production `SessionManager`.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/session_manager.py` | Builder prompt sessions, provider adapters, GDE apply, and SGC compile. | Removes the fallback prompt pipeline/provider test double and blocks missing PIL with `PIL_UNAVAILABLE`. |
| `packages/builder-workspace/server/tests/fixtures/prompt_pipeline_contract.py` | Test-only deterministic prompt contract fixture. | Moves supported/blocked prompt scenarios out of production server source. |
| `tools/prompt_pipeline_smoke.py`, `tools/provider_readiness_smoke.py` | Editor-free smoke/certification helpers. | Import the deterministic prompt fixture from the test-only fixture path. |
| `packages/builder-workspace/server/tests/test_session_manager_authority.py`, `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Builder server regression tests. | Cover PIL-unavailable blocking and use the moved test fixture. |
| `tools/silent_success_check.py`, `docs/production_path_rules.json` | Governance guards. | Add fallback-removal checks and remove old production allowlist entries. |
| `docs/fake_skip_register.json`, `docs/XACE_FAKE_AND_SKIP_REGISTER.md`, `docs/XACE_PRODUCTION_PATH_RULES.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/LAUNCH_READINESS_MAP.md` | Governance/readiness docs. | Record fake/helper isolation and update prompt fixture paths. |

Verification:

- `python -m py_compile packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/tests/fixtures/prompt_pipeline_contract.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py packages/builder-workspace/server/tests/test_session_manager_authority.py tools/prompt_pipeline_smoke.py tools/provider_readiness_smoke.py tools/certify_launch.py tools/silent_success_check.py tools/production_path_check.py` passes.
- `python -m unittest packages/builder-workspace/server/tests/test_session_manager_authority.py` passes: 3 tests.
- `python -m unittest discover -s packages/builder-workspace/server/tests -p "test_prompt_pipeline_e2e.py"` passes: 6 tests.
- `python tools/provider_readiness_smoke.py --settings-path target-codex-task19-fixtures\provider_settings.json` passes.
- `python tools/silent_success_check.py --output target-codex-task19-fixtures\silent_success_report.json` passes.
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-certify-task18-quick/debug/xace_runtime.exe --sgc-bin target-codex-certify-task18-quick/debug/xace-system-graph-compiler.exe` passes.
- Governance checks pass:
  - `python tools/source_inventory_check.py`
  - `python tools/fake_skip_register_check.py`
  - `python tools/production_path_check.py`
  - `python tools/forbidden_claims_check.py`
- Quick certification passes with 18 checks:
  `python tools/certify_launch.py --quick --target-dir target-codex-certify-task19-quick`.

## Fifty-First Slice: GDE-Only CGS Apply

Status: Task 20 removes the remaining direct Builder CGS mutation fallback from production apply code. `SessionManager.apply_via_gde()` now has no opt-in bypass and no local JSON mutation helper; when a session has no GDE instance, apply returns an actionable error and no persistable CGS result.

What This Slice Proves:

- Builder production apply cannot be configured back to a direct CGS mutation path.
- The old local apply/set helpers are removed from `SessionManager`.
- No-GDE prompt apply scenarios fail with `GDE_APPLY_FAILED`, keep the original CGS hash, and emit no `cgs_update`.
- Production path rules no longer allow any PPR003 direct-mutation findings.
- The no-silent-success guard now fails if the removed option, helper, setter, or router wording returns.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/session_manager.py` | Builder prompt sessions, GDE apply, and SGC compile. | Removes the old direct CGS apply option and helper functions; GDE-unavailable apply remains a hard failure with no new CGS. |
| `packages/builder-workspace/server/ws_message_router.py` | WebSocket routing and prompt apply orchestration. | Documents the GDE-only production apply route. |
| `packages/builder-workspace/server/tests/test_session_manager_authority.py`, `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Builder authority and prompt E2E regression tests. | Assert no-GDE rejection without constructing any fallback option. |
| `tools/prompt_pipeline_smoke.py`, `tools/silent_success_check.py` | Certification smoke and no-silent-success guard. | Remove obsolete fallback wiring and add guard coverage for the deleted direct-mutation path. |
| `docs/production_path_rules.json`, `docs/XACE_PRODUCTION_PATH_RULES.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/LAUNCH_READINESS_MAP.md` | Governance/readiness records. | Remove PPR003 allowlist debt and record Task 20 completion. |

Verification:

- `python -m py_compile packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/tests/test_session_manager_authority.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py tools/prompt_pipeline_smoke.py tools/silent_success_check.py tools/production_path_check.py tools/certify_launch.py`
- `python -m unittest packages/builder-workspace/server/tests/test_session_manager_authority.py`
- `python -m unittest discover -s packages/builder-workspace/server/tests -p "test_prompt_pipeline_e2e.py"`
- `python tools/silent_success_check.py --output target-codex-task20-naive-removal/silent_success_report.json`
- `python tools/production_path_check.py`
- `python tools/source_inventory_check.py`
- `python tools/fake_skip_register_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-certify-task19-quick/debug/xace_runtime.exe --sgc-bin target-codex-certify-task19-quick/debug/xace-system-graph-compiler.exe`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task20-quick`

## Fifty-Second Slice: SGC ExecutionPlan Contract

Status: Task 21 defines the authoritative persisted SGC `ExecutionPlan` contract. Builder now has a documented and schema-backed contract for `.xace/execution_plans/<cgs_hash>.plan.json`, and persistence refuses plan files that do not match the required CGS hash, filename, and schedule shape.

What This Slice Proves:

- Persisted execution plans have an explicit owner, path, identity tuple, and runtime loading policy.
- `compiled_from_cgs_hash` must match both the current CGS hash and the `.plan.json` filename stem.
- The contract records `schema_version`, `plan_version`, `created_tick`, `plan_hash`, phase schedules, sorted `all_system_ids`, migration policy, and strict runtime load refusal rules.
- Builder's persisted-plan validator is exercised by unit tests and feeds the existing runtime-load validation path.
- Runtime execution of persisted SGC plans was completed later by Task 23; current status is `strict_loader_ready`.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md` | Persisted SGC plan authority contract. | Defines storage path, ownership, hashes, compatibility checks, migration policy, and runtime load rules. |
| `docs/schemas/xace-sgc-execution-plan.schema.json` | Machine-readable persisted plan schema. | Specifies required `ExecutionPlan` fields and phase/group shape. |
| `packages/builder-workspace/server/sgc_plan_validator.py` | Builder SGC plan validation. | Adds persisted plan contract validation and invokes it from runtime-load validation. |
| `packages/builder-workspace/server/cgs_persistence.py` | Project-local CGS, snapshot, audit, and plan persistence. | Refuses invalid persisted execution-plan contracts before writing `.plan.json`. |
| `packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py` | Persisted plan contract regression tests. | Verifies schema presence, valid contract acceptance, hash/path rejection, and persistence enforcement. |
| `docs/SGC_CLI_CONTRACT.md`, `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Link the persisted-plan contract and keep runtime loading scoped as pending. |

Verification:

- `python -m py_compile packages/builder-workspace/server/sgc_plan_validator.py packages/builder-workspace/server/cgs_persistence.py packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py`
- `python -m unittest packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py`
- `python -m unittest discover -s packages/builder-workspace/server/tests -p "test_prompt_pipeline_e2e.py"`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-certify-task20-quick/debug/xace_runtime.exe --sgc-bin target-codex-certify-task20-quick/debug/xace-system-graph-compiler.exe`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task21-quick`

## Fifty-Third Slice: Persisted SGC Plan Writer

Status: Task 22 implements Builder's canonical persisted SGC plan writer. Structural prompt applies now write `.xace/execution_plans/<cgs_hash>.plan.json` as compact sorted-key JSON enriched with SGC `plan_hash`, `compiled_from_cgs_hash`, `schema_version`, `plan_version`, component access sets, system metadata, and a stable proof-bundle reference. Existing plan files for the same CGS hash are accepted only when the bytes match exactly.

What This Slice Proves:

- Builder no longer stores raw SGC stdout as the persisted plan artifact.
- The persisted plan schema now requires `component_access_sets`, `system_metadata`, and `proof_bundle`.
- The validator has a strict persisted-plan mode for disk writes while still allowing raw SGC output through the compile validation path before enrichment.
- Prompt pipeline proof checks now compare the persisted plan file with the proof bundle plan copy.
- Runtime execution of persisted SGC plans is completed by Task 23; current status is `strict_loader_ready` for SGC-authority runs.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/cgs_persistence.py` | Project-local CGS, snapshot, audit, proof, and plan persistence. | Canonicalizes persisted plans, derives component access sets/system metadata/proof references, writes exact bytes atomically, and rejects byte-different immutable rewrites. |
| `packages/builder-workspace/server/sgc_plan_validator.py` | Builder SGC plan validation. | Adds strict persisted metadata validation and reports access/system/proof counts. |
| `packages/builder-workspace/server/ws_message_router.py` | Builder prompt/apply route. | Passes CGS and SGC validation into the canonical plan writer and proof bundle writer. |
| `docs/schemas/xace-sgc-execution-plan.schema.json` | Machine-readable persisted plan schema. | Requires canonical Builder metadata fields in persisted plan files. |
| `packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py` | Persisted plan contract regression tests. | Proves strict metadata requirements and byte-for-byte reproducibility for unchanged inputs. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`, `tools/prompt_pipeline_smoke.py` | Prompt pipeline proof checks. | Assert canonical persisted plan files and proof plan copies match. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Document the canonical writer and keep runtime loading scoped as pending. |

Verification:

- `python -m py_compile packages/builder-workspace/server/cgs_persistence.py packages/builder-workspace/server/sgc_plan_validator.py packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py tools/prompt_pipeline_smoke.py`
- `python -m unittest packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py`
- `python -m unittest packages/builder-workspace/server/tests/test_cgs_persistence_authority.py`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-certify-task21-quick/debug/xace_runtime.exe --sgc-bin target-codex-certify-task21-quick/debug/xace-system-graph-compiler.exe`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task22-quick`

## Fifty-Fourth Slice: Strict Runtime SGC Plan Loader

Status: Task 23 implements the standalone runtime strict persisted-plan loader. Runtime now prefers a persisted `.xace/execution_plans/<cgs_hash>.plan.json` plan when present, and `--require-sgc-plan` or `--sgc-plan` makes missing, stale, malformed, or unregistered-system plans fail during initialization before tick zero. In strict mode, the runtime uses SGC phase groups directly instead of deriving a built-in-only CGS phase plan.

What This Slice Proves:

- Runtime can resolve the persisted plan path from the CGS hash and project root.
- Runtime validates plan identity before simulation: CGS hash, schema version, plan version, plan hash, sorted `all_system_ids`, phase/group shape, persisted Builder metadata, and proof reference.
- Runtime converts persisted SGC groups into its `RuntimePhasePlan` without built-in filtering.
- Runtime rejects a strict SGC-authority run before tick zero when the plan is missing or schedules an unregistered system.
- A dedicated strict-loader smoke proves a compatible persisted `MovementSystem` plan runs under `--require-sgc-plan`; at Task 23 time, the broader prompt pipeline smoke explicitly used compatibility-checked `--derive-cgs-plan` until generated-system registry/ABI support arrived.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/cgs_loader.rs` | Standalone runtime CGS and SGC plan loading. | Adds `SgcPlanPolicy`, persisted plan resolution, strict plan validation, and SGC-group-to-runtime-plan conversion. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime initialization and tick orchestration. | Wires strict plan policy into initialization, stores the loaded plan version/hash/source, and rejects unknown scheduled systems before tick zero. |
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime CLI. | Adds `--require-sgc-plan`, `--sgc-plan`, and the explicit `--derive-cgs-plan` compatibility override, and reports loaded plan source/version/hash on startup. |
| `tools/runtime_sgc_plan_loader_smoke.py` | Strict persisted-plan runtime smoke. | Creates a temporary compatible persisted SGC plan, verifies `xace_runtime --require-sgc-plan` accepts it, and verifies a missing required plan is refused. |
| `tools/prompt_pipeline_smoke.py` | Real-SGC prompt-to-runtime smoke. | Passes compatibility-checked `--derive-cgs-plan` for its broad prompt scenario runtime leg by default; optional strict mode remains available for later generated-system registry tasks. |
| `tools/certify_launch.py` | Launch certification command. | Adds the focused strict runtime SGC plan loader smoke to quick and full certification. |
| `packages/builder-workspace/server/sgc_plan_validator.py`, `packages/builder-workspace/server/cgs_persistence.py` | Builder plan validation/proof metadata. | Updates load status and proof wording for the strict runtime loader. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Records strict loader behavior while keeping generated-system execution breadth and retained end-to-end proof scoped to later tasks. |

Verification:

- `cargo test -p xace-runtime-core cgs_loader --target-dir target-codex-task23-runtime`
- `cargo test -p xace-runtime-core runtime_orchestrator --target-dir target-codex-task23-runtime`
- `python -m py_compile tools/prompt_pipeline_smoke.py tools/runtime_sgc_plan_loader_smoke.py tools/certify_launch.py packages/builder-workspace/server/sgc_plan_validator.py packages/builder-workspace/server/cgs_persistence.py packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python -m unittest packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python tools/sgc_cli_integration.py --sgc-bin target-codex-certify-task22-quick/debug/xace-system-graph-compiler.exe --benchmark-threshold-ms 1000 --json`
- `python tools/runtime_sgc_plan_loader_smoke.py --runtime-bin target-codex-task23-runtime/debug/xace_runtime.exe`
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-task23-runtime/debug/xace_runtime.exe --sgc-bin target-codex-certify-task22-quick/debug/xace-system-graph-compiler.exe`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task23-quick`

## Fifty-Fifth Slice: Runtime SGC Plan Compatibility Validation

Status: Task 24 completes strict persisted SGC plan compatibility validation for the standalone runtime. Required SGC authority runs now reject incompatible plans before tick zero when CGS hash, schema version, CGS execution-plan version, plan version, adapter protocol version, system IDs, component IDs, deterministic flags, migration status, or proof metadata do not match the loaded CGS/runtime contract.

What This Slice Proves:

- Runtime checks persisted plan compatibility against the loaded CGS metadata and system definitions before constructing the tick schedule.
- Builder-persisted plans carry `adapter_protocol_version: 1` and `migration_status: "current"` as required loadability metadata.
- Component access sets, system metadata, deterministic flags, phase/group compatibility, proof references, and CGS system IDs are checked against the loaded CGS instead of trusted as plan-only data.
- The focused runtime smoke now covers compatible load, missing required plan, adapter protocol mismatch, and migration status mismatch.
- Generated-system registry support and retained end-to-end SGC runtime proof remain separate gates.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/cgs_loader.rs` | Standalone runtime CGS and SGC plan loading. | Adds strict compatibility checks for CGS metadata, adapter protocol, migration status, tick origin, system IDs, component access sets, system metadata, deterministic flags, and group membership before tick zero. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime initialization and registry validation. | Updates strict SGC runtime fixtures so valid plans match their CGS exactly and unregistered generated systems are rejected after compatibility passes. |
| `packages/builder-workspace/server/cgs_persistence.py` | Canonical persisted plan writer. | Stamps current adapter protocol and migration status into Builder-persisted SGC plans. |
| `packages/builder-workspace/server/sgc_plan_validator.py` | Builder persisted-plan contract validation. | Validates adapter protocol and migration status for strict persisted plans and reports them in validation output. |
| `docs/schemas/xace-sgc-execution-plan.schema.json` | Machine-readable persisted plan schema. | Requires `adapter_protocol_version` and `migration_status`. |
| `packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py` | Persisted plan contract regression tests. | Covers required runtime compatibility metadata and incompatible adapter/migration values. |
| `tools/runtime_sgc_plan_loader_smoke.py`, `tools/prompt_pipeline_smoke.py` | Runtime and prompt certification smokes. | Prove strict runtime compatibility failures and assert Builder-persisted plans carry loadability metadata. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Move runtime compatibility validation from pending to complete while keeping generated-system execution breadth and retained end-to-end proof pending. |

Verification:

- `cargo test -p xace-runtime-core cgs_loader --target-dir target-codex-task24-runtime`
- `cargo test -p xace-runtime-core runtime_orchestrator --target-dir target-codex-task24-runtime`
- `python -m py_compile tools/prompt_pipeline_smoke.py tools/runtime_sgc_plan_loader_smoke.py tools/certify_launch.py packages/builder-workspace/server/sgc_plan_validator.py packages/builder-workspace/server/cgs_persistence.py packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python -m unittest packages/builder-workspace/server/tests/test_sgc_execution_plan_contract.py`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python tools/runtime_sgc_plan_loader_smoke.py --runtime-bin target-codex-task24-runtime/debug/xace_runtime.exe`
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-task24-runtime/debug/xace_runtime.exe --sgc-bin target-codex-certify-task23-quick/debug/xace-system-graph-compiler.exe`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task24-quick`

## Fifty-Sixth Slice: No Silent Built-In System Filtering

Status: Task 25 removes the remaining CGS-derived built-in-only system filtering path. Runtime no longer drops unsupported, unknown, duplicate, invalid, or non-deterministic declared CGS systems when deriving a compatibility schedule. It fails before tick zero and writes a runtime compatibility proof artifact instead.

What This Slice Proves:

- CGS-derived compatibility loading schedules every supported declared system or fails; there is no built-in-only filter and no default `MovementSystem` injection.
- Unsupported generated/plugin systems now fail with actionable diagnostics that name the system and explain registry support is required.
- Non-deterministic declared systems fail loudly instead of disappearing from the phase plan.
- Runtime writes `.xace/proof/runtime-compatibility/<cgs_hash>.json` with declared systems, scheduled systems, unsupported systems, legacy dropped system IDs, and the no-filter/no-injection rule.
- Certification runtime smoke covers the unsupported derived-system failure and verifies the proof artifact.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/cgs_loader.rs` | Standalone runtime CGS and SGC plan loading. | Replaces derived-plan built-in filtering/default injection with compatibility evaluation, hard unsupported-system errors, and proof artifact writing. |
| `tools/runtime_sgc_plan_loader_smoke.py` | Runtime SGC/compatibility smoke. | Adds a CGS-derived unsupported generated-system scenario and asserts the runtime compatibility proof is written. |
| `tools/runtime_bridge_smoke.py` | Runtime bridge/control smoke. | Uses an isolated supported CGS fixture plus explicit compatibility-checked `--derive-cgs-plan`, avoiding accidental dependence on broad unsupported root fixtures. |
| `packages/save-engine/tests/test_runtime_checkpoint.rs` | Runtime checkpoint save/load replay proof. | Uses an isolated supported CGS fixture so save replay proof does not depend on broad unsupported root fixtures. |
| `tools/prompt_pipeline_smoke.py` | Prompt pipeline runtime verification. | Treats compatibility-checked CGS-derived unsupported-system rejection as a passing proof state before generated-system registry/ABI support exists. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/LAUNCH_READINESS_MAP.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md` | SGC/readiness/governance docs. | Records no silent filtering, the runtime compatibility proof path, and keeps generated-system execution scoped to Task 26+. |

Verification:

- `cargo test -p xace-runtime-core cgs_loader --target-dir target-codex-task25-runtime`
- `cargo test -p xace-runtime-core runtime_orchestrator --target-dir target-codex-task25-runtime`
- `python -m py_compile tools/prompt_pipeline_smoke.py tools/runtime_sgc_plan_loader_smoke.py tools/runtime_bridge_smoke.py tools/certify_launch.py`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task25-runtime`
- `python tools/runtime_sgc_plan_loader_smoke.py --runtime-bin target-codex-task25-runtime/debug/xace_runtime.exe`
- `python tools/runtime_bridge_smoke.py --runtime-bin target-codex-task25-runtime/debug/xace_runtime.exe`
- `cargo test -p xace-save-engine --test test_runtime_checkpoint --target-dir target-codex-task25-runtime`
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-task25-runtime/debug/xace_runtime.exe --sgc-bin target-codex-certify-task24-quick/debug/xace-system-graph-compiler.exe`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task25-quick`

## Fifty-Seventh Slice: Extensible Runtime System Registry

Status: Task 26 adds the first generated-system execution path through the real
runtime registry. CGS systems can now declare a narrow
`runtime_executor.kind = "generated.increment_numeric_field"` contract; the
standalone runtime registers that generated executor before phase-plan
validation and executes it through `SystemContext`, `PhaseOrchestrator`, and
`MutationGate`.

What This Slice Proves:

- `SpawnSummary` carries loaded CGS system definitions so runtime initialization
  can register non-built-in executors before validating persisted or derived
  schedules.
- CGS-derived compatibility no longer treats every non-built-in system as
  unsupported; it accepts supported generated executor contracts and still
  fails loudly for generated/plugin/external systems without a supported
  executor.
- A non-built-in `GeneratedCounterSystem` is registered by ID, scheduled from
  CGS, ticked through the normal runtime path, and mutates component state via
  deferred mutation application.
- This Task 26 executor path was deliberately scoped. Task 27 extends it with a
  generated-system ABI; sandboxed compilation, artifact signing,
  plugin/external executors, unsupported-API rejection, and full SGC
  retained end-to-end SGC runtime proof remain later gates.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/cgs_loader.rs` | Standalone runtime CGS and SGC plan loading. | Adds `runtime_executor` to CGS systems, preserves runtime system definitions in `SpawnSummary`, defines the first generated executor contract, and lets derived compatibility accept supported generated systems. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime initialization, registry validation, and tick execution. | Registers supported generated executors alongside built-ins before phase-plan validation and proves `GeneratedCounterSystem` executes through the real registry. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Records the Task 26 narrow generated executor contract while keeping safe compilation/signing and replay proof out of launch claims. |

Verification:

- `cargo fmt`
- `cargo test -p xace-runtime-core cgs_loader --target-dir target-codex-task26-runtime`
- `cargo test -p xace-runtime-core runtime_orchestrator --target-dir target-codex-task26-runtime`
- `python -m py_compile tools/prompt_pipeline_smoke.py tools/runtime_sgc_plan_loader_smoke.py tools/runtime_bridge_smoke.py tools/certify_launch.py`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task26-runtime`
- `python tools/runtime_sgc_plan_loader_smoke.py --runtime-bin target-codex-task26-runtime/debug/xace_runtime.exe`
- `python tools/runtime_bridge_smoke.py --runtime-bin target-codex-task26-runtime/debug/xace_runtime.exe`
- `python tools/prompt_pipeline_smoke.py --runtime-bin target-codex-task26-runtime/debug/xace_runtime.exe --sgc-bin target-codex-certify-task25-quick/debug/xace-system-graph-compiler.exe`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task26-quick`

## Fifty-Eighth Slice: Generated System ABI

Status: Task 27 defines the local generated-system execution ABI. Supported
generated systems now normalize to a deterministic `GeneratedSystemAbiSpec`
before registry insertion, with explicit coverage for inputs, reads, writes,
events, RNG budget, errors, rollback hooks, and executor operation.

What This Slice Proves:

- `runtime_executor` objects normalize into ABI version 1 using schema
  `xace.generated_system_abi.v1`; explicit ABI blocks are rejected when their
  inputs, events, RNG budget, error policy, or rollback hooks do not match the
  executor operation.
- The supported generated executor set now covers both component mutation
  (`generated.increment_numeric_field`) and deterministic RNG-driven event
  emission (`generated.emit_event_on_rng_threshold`).
- Generated systems run only through `SystemContext`, so mutations are deferred
  through `MutationGate`, RNG is drawn through the runtime RNG window, and
  events are emitted through the phase-buffered event path.
- Runtime tests cover multiple generated systems in one CGS-derived plan:
  `GeneratedCounterSystem` mutates component state and
  `GeneratedLootRollSystem` emits a deterministic generated domain event.
- Task 27 completes the local ABI boundary for supported generated executors.
  Safe generated-code compilation/signing, unsupported generated-system
  rejection, plugin/external executor registration, and full SGC
  retained end-to-end SGC runtime proof remain later gates.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/generated_system_abi.rs` | Generated system ABI definition, validation, and executor construction. | Adds ABI schema/version constants, input/event/RNG/error/rollback structs, supported executor parsing, explicit ABI validation, and runtime execution through `SystemContext`. |
| `packages/runtime-core/src/cgs_loader.rs` | Standalone runtime CGS and SGC plan loading. | Delegates generated executor compatibility to the ABI normalizer and adds a CGS fixture covering the RNG event executor. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime initialization, registry validation, and tick execution. | Registers generated ABI specs through the runtime registry and proves multiple generated systems execute together. |
| `packages/runtime-core/src/lib.rs` | Runtime crate module surface. | Exposes the generated-system ABI module. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Moves local generated-system ABI from pending to complete while keeping safe compilation/signing and retained end-to-end proof out of launch claims. |

Verification:

- `cargo fmt`
- `cargo test -p xace-runtime-core generated_system_abi`
- `cargo test -p xace-runtime-core cgs_derived_plan_accepts_supported_generated`
- `cargo test -p xace-runtime-core runtime_executes_supported_generated_system_through_registry`
- `cargo test -p xace-runtime-core runtime_executes_multiple_generated_systems_through_abi`
- `cargo test -p xace-runtime-core --lib`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task27-runtime`
- `python tools/runtime_sgc_plan_loader_smoke.py --runtime-bin target-codex-task27-runtime/debug/xace_runtime.exe`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task27-quick`

## Fifty-Ninth Slice: Safe Generated System Compilation

Status: Task 28 routes accepted generated Rust gameplay systems through a
local safe compile/sign/register gate. Generated-code-backed executor metadata
now requires SystemSpec validation, runtime ABI validation, deterministic
static checks, Cargo sandbox checking, real SGC compilation, signed compile
artifacts, and runtime signature verification before registration.

What This Slice Proves:

- `GeneratedSystemSafeCompiler` rejects invalid SystemSpec/runtime ABI inputs
  before generated code can reach SGC or runtime registration.
- Nondeterministic generated Rust source is stopped by the static checker
  before SGC compilation; the Task 28 smoke injects `rand::random` and verifies
  the failure stage is `determinism_static_check`.
- Valid generated Rust source is cargo-checked in a temporary sandbox, compiled
  through the real SGC binary, signed as
  `xace.generated_system_compile_artifact.v1`, and attached to the
  `runtime_executor`.
- Runtime registration independently verifies the compile artifact's system ID,
  source hash, runtime-executor hash, ABI hash, SGC plan hash, sandbox hash,
  validation step order, signing key ID, and deterministic local signature.
- The generated system safe compile smoke writes a signed CGS and launches the
  real runtime, proving signed generated-code-backed metadata still flows
  through the Task 27 ABI and registry path.
- Task 28 completes the local safe compile/sign/register boundary for supported
  generated executor metadata. Unsupported generated API rejection,
  plugin/external executor registration, release-wide artifact signing, and full
  retained end-to-end SGC runtime proof remain later gates.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/prompt-intelligence/src/code_generation/generated_system_safe_compiler.py` | Generated Rust safe compile gate. | Adds SystemSpec/runtime ABI validation, deterministic code checks, Cargo sandbox checking, real SGC compilation, deterministic local compile-artifact signing, and signed runtime executor output. |
| `packages/prompt-intelligence/src/code_generation/code_generation_engine.py` | Prompt code-generation orchestration. | Routes CGS systems with `runtime_executor` through the safe compile/sign gate before returning successful generated-code results. |
| `packages/prompt-intelligence/src/tests/test_code_generation.py` | Prompt-intelligence code generation regression tests. | Covers compile-artifact signing, nondeterministic generated-code blocking before SGC, and explicit ABI requirements before SGC. |
| `packages/runtime-core/src/generated_system_abi.rs` | Generated system ABI and runtime artifact validation. | Validates `runtime_executor.compile_artifact` hashes, validation-step order, signing key, and signature; rejects tampered signed executors. |
| `tools/generated_system_safe_compile_smoke.py` | Editor-free safe generated-system proof. | Proves deterministic failure injection, safe compile/sign through the real SGC binary, signed CGS writing, and runtime registration validation. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds the generated-system safe compile smoke to quick/full editor-free certification. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new smoke helper as test-only evidence. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Moves local safe generated-code compile/sign/register from pending to complete while keeping unsupported generated-system rejection and retained end-to-end proof out of launch claims. |

Verification:

- `cargo fmt`
- `python -m py_compile packages/prompt-intelligence/src/code_generation/generated_system_safe_compiler.py tools/generated_system_safe_compile_smoke.py tools/certify_launch.py packages/prompt-intelligence/src/tests/test_code_generation.py`
- `python packages/prompt-intelligence/src/tests/test_code_generation.py`
- `cargo test -p xace-runtime-core generated_system_abi`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-safe-compile`
- `cargo build -p xace-system-graph-compiler --target-dir target-codex-task28-safe-compile`
- `python tools/generated_system_safe_compile_smoke.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe --sgc-bin target-codex-task28-safe-compile/debug/xace-system-graph-compiler.exe`
- `cargo test -p xace-runtime-core cgs_derived_plan_accepts_supported_generated`
- `cargo test -p xace-runtime-core runtime_executes_multiple_generated_systems_through_abi`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task28-quick`

## Sixtieth Slice: Unsupported Generated System Rejection

Status: Task 29 adds the local unsupported generated-system rejection policy to
the generated-code safe compile gate. Accepted generated Rust is now scanned
for unsupported APIs, nondeterministic constructs, filesystem/network/process
access, engine-only calls, unsafe/FFI/threading escapes, and missing rollback
hooks before SGC compilation or runtime registration.

What This Slice Proves:

- `unsupported_generated_system_guard.py` produces stable exact reason codes
  such as `nondeterministic.random_source`,
  `unsupported.filesystem_access`, `unsupported.network_access`, and
  `unsupported.engine_api_godot`.
- `GeneratedSystemSafeCompiler` runs this guard after SystemSpec/runtime ABI
  validation and before contract validation, Cargo sandbox checking, SGC
  compilation, artifact signing, or runtime registration.
- Missing rollback hooks still fail during runtime ABI validation before SGC,
  with exact `runtime_executor.abi.rollback.*` diagnostics.
- Signed compile artifacts now include the unsupported rejection policy hash
  `3306f82262ec3e951b9d8d7de53dac45f3e69fac8b6b00d0959c89877c5e47c5` and the
  `unsupported_api_rejection` validation step.
- Runtime registration independently verifies that policy hash, step order,
  executor hash, ABI hash, SGC plan hash, sandbox hash, signing key, and local
  signature before generated-code-backed executor metadata can register.
- The generated-system safe compile smoke now injects adversarial random,
  filesystem, network, engine-only API, and missing-rollback cases and verifies
  exact blocked reasons with no SGC result for rejected systems.
- Task 29 completes the local unsupported generated-system rejection boundary
  for supported generated executor metadata. Plugin/external executor
  registration, release-wide artifact signing, and full SGC schedule/replay
  proof remain later gates.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/prompt-intelligence/src/code_generation/unsupported_generated_system_guard.py` | Generated-system unsupported API policy. | Adds stable reason-code scanning for unsafe Rust, filesystem/network/process access, engine APIs, threading/async escapes, and nondeterministic constructs. |
| `packages/prompt-intelligence/src/code_generation/generated_system_safe_compiler.py` | Generated Rust safe compile gate. | Runs unsupported rejection before Cargo/SGC, exposes exact reports, signs the rejection policy hash, and records the new validation step. |
| `packages/prompt-intelligence/src/code_generation/code_generation_engine.py` | Prompt code-generation orchestration. | Continues routing `runtime_executor` systems through the safe compiler so unsupported generated systems cannot be returned as successful generated-code results. |
| `packages/runtime-core/src/generated_system_abi.rs` | Generated system ABI and runtime artifact validation. | Requires the unsupported policy hash and new validation step before accepting signed compile artifacts. |
| `packages/prompt-intelligence/src/tests/test_code_generation.py` | Prompt-intelligence code generation regression tests. | Covers exact unsupported reason codes, engine path rejection, filesystem rejection, random rejection, and missing rollback hook rejection. |
| `tools/generated_system_safe_compile_smoke.py` | Editor-free safe generated-system proof. | Adds adversarial generated-system rejection cases and records reason codes in the smoke summary. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles the unsupported guard and keeps the adversarial generated-system smoke in quick/full certification. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Moves local unsupported generated-system rejection from pending to complete while keeping retained end-to-end proof out of launch claims. |

Verification:

- `cargo fmt`
- `python -m py_compile packages/prompt-intelligence/src/code_generation/unsupported_generated_system_guard.py packages/prompt-intelligence/src/code_generation/generated_system_safe_compiler.py packages/prompt-intelligence/src/code_generation/code_generation_engine.py tools/generated_system_safe_compile_smoke.py tools/certify_launch.py packages/prompt-intelligence/src/tests/test_code_generation.py`
- `python packages/prompt-intelligence/src/tests/test_code_generation.py`
- `cargo test -p xace-runtime-core generated_system_abi --quiet`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-safe-compile`
- `python tools/generated_system_safe_compile_smoke.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe --sgc-bin target-codex-task28-safe-compile/debug/xace-system-graph-compiler.exe`

## Sixty-First Slice: Runtime SGC Schedule Snapshot Replay

Status: Task 30 wires runtime ticks to the loaded SGC schedule ABI. The
standalone runtime now preserves persisted SGC group IDs, phases, execution
indexes, `parallel` flags, system order, serialization constraints, component
read/write access, and dependency metadata after strict plan loading, uses that
schedule for every tick, records per-tick schedule snapshots, and compares
those snapshots during replay.

What This Slice Proves:

- `RuntimeSchedulePlan` keeps the rich SGC schedule ABI instead of flattening
  persisted plans down to phase/system/parallel tuples.
- Strict persisted-plan loading now rejects parallel component hazards in the
  runtime loader, so hostile or stale plans cannot rely on Builder-only hazard
  checks.
- `RuntimeOrchestrator::tick()` derives the executable phase list from the
  preserved schedule plan and records a schedule snapshot only after a
  successful tick.
- Replay validation compares recorded schedule snapshots and replay-run
  snapshots against the schedule derived from the loaded persisted plan.
- The runtime CLI exposes `--schedule-snapshot-out` to write a deterministic
  JSON schedule snapshot report for real-binary checks.
- The dedicated smoke runs the real runtime binary twice against a persisted
  SGC plan containing two generated systems in one parallel group and verifies
  every tick snapshot matches the persisted plan and the replay.
- Task 30 completes the local runtime schedule snapshot/replay boundary for
  persisted SGC plans. The retained end-to-end CGS-to-SGC-to-runtime proof
  command, release-wide signing, and plugin/external executor support remain
  later gates.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/cgs_loader.rs` | Standalone runtime CGS and SGC plan loading. | Adds `RuntimeSchedulePlan`, group/access/dependency snapshots, dependency-order validation, and runtime-side parallel hazard rejection. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime initialization, replay validation, and tick execution. | Stores the rich schedule plan, executes ticks from it, records per-tick schedule snapshots, and compares schedule snapshots during replay. |
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime CLI. | Adds `--schedule-snapshot-out` and writes deterministic schedule snapshot reports. |
| `tools/runtime_sgc_schedule_snapshot_smoke.py` | Editor-free runtime schedule proof. | Runs two real runtime replays against a persisted generated-system SGC plan and verifies snapshot/plan equality for every tick. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds the schedule snapshot smoke to quick/full certification and Python compilation. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the schedule snapshot smoke as test-only evidence. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Moves local runtime schedule snapshot/replay proof from pending to complete while keeping retained end-to-end proof out of launch claims. |

Verification:

- `cargo fmt`
- `python -m py_compile tools/runtime_sgc_schedule_snapshot_smoke.py tools/certify_launch.py`
- `cargo test -p xace-runtime-core persisted_sgc_schedule_snapshots_match_plan_for_generated_replay --lib --target-dir target-codex-task28-safe-compile`
- `cargo test -p xace-runtime-core persisted_sgc_plan_rejects_parallel_component_hazard --lib --target-dir target-codex-task28-safe-compile`
- `cargo test -p xace-runtime-core runtime_uses_persisted_sgc_plan_as_authoritative_schedule --lib --target-dir target-codex-task28-safe-compile`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-safe-compile`
- `python tools/runtime_sgc_schedule_snapshot_smoke.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe`
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-task28-safe-compile`

## Sixty-Second Slice: Deterministic Parallel-Group Execution Policy

Status: Task 31 defines the standalone runtime's current execution policy for
SGC groups marked `parallel=true`. These groups remain SGC-parallel-eligible
schedule metadata, but the runtime now reports and tests that it executes them
under `deterministic_sequential` with `parallel_group_worker_threads=false`.

What This Slice Proves:

- `ParallelGroupExecutionPolicy` is a typed runtime policy, with stable report
  string `deterministic_sequential` and `uses_worker_threads=false`.
- `ParallelExecutor::execute_parallel()` is documented as the
  SGC-parallel-eligible group path, not a worker-thread promise.
- A concurrency probe test verifies that systems in a SGC-parallel-eligible
  group are not concurrently active under the current policy.
- Runtime startup/status/schedule-snapshot reports expose the active policy, so
  launch artifacts cannot preserve `parallel=true` flags while hiding the fact
  that worker threads are disabled.
- Criterion includes a benchmark for the current policy:
  `parallel_policy/deterministic_sequential_sgc_parallel_group_32_systems`.
- Claims and SGC contracts now state that true thread-pool execution is a future
  policy change requiring updated docs, tests, benchmarks, and launch claims.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/phase_orchestrator/parallel_executor.rs` | Runtime system group executor. | Adds explicit deterministic sequential policy, exposes policy metadata, and tests no concurrent activity for SGC-parallel-eligible groups. |
| `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs`, `packages/runtime-core/src/runtime_orchestrator.rs` | Tick orchestration and runtime status. | Threads the policy upward for status and reporting. |
| `packages/runtime-core/src/bin/xace_runtime.rs`, `packages/runtime-core/src/control_protocol.rs`, `packages/runtime-core/src/control_server.rs` | Runtime CLI/control surfaces. | Reports `parallel_group_execution_policy` and `parallel_group_worker_threads` in startup, control status, and schedule snapshot reports. |
| `packages/runtime-core/benches.rs` | Runtime performance evidence. | Adds deterministic sequential SGC-parallel-eligible group benchmark. |
| `packages/core/src/runtime/*`, `packages/core/src/schema/system_definition.rs`, `packages/core/src/entity_id.rs`, `packages/runtime-core/src/entity_store/entity_id_generator.rs` | Core schedule/schema docs. | Rewords current-runtime docs from active parallelism to parallel eligibility. |
| `tools/runtime_sgc_schedule_snapshot_smoke.py` | Editor-free runtime schedule proof. | Asserts the real runtime reports deterministic sequential policy and no worker threads while preserving persisted `parallel=true` flags. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Documents the current policy and blocks active thread-pool claims until implementation/proof exists. |

Verification:

- `cargo fmt`
- `python -m py_compile tools/runtime_sgc_schedule_snapshot_smoke.py`
- `cargo test -p xace-runtime-core parallel_executor --lib --target-dir target-codex-task28-safe-compile`
- `cargo test -p xace-runtime-core guarded_parallel_system_rng_uses_interceptor_window --lib --target-dir target-codex-task28-safe-compile`
- `cargo test -p xace-runtime-core persisted_sgc_schedule_snapshots_match_plan_for_generated_replay --lib --target-dir target-codex-task28-safe-compile`
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-task28-safe-compile`
- `cargo test -p xace-core --lib --target-dir target-codex-task28-safe-compile`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-safe-compile`
- `python tools/runtime_sgc_schedule_snapshot_smoke.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe`
- `cargo bench -p xace-runtime-core --bench determinism_overheads --target-dir target-codex-task28-safe-compile -- parallel_policy --sample-size 10`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task28-quick`

## Sixty-Third Slice: SGC Plan Migration Invalidation Proof

Status: Task 32 defines the current SGC migration behavior for the standalone
runtime. XACE does not silently migrate, downgrade, mutate, or fall back from a
stale persisted SGC plan. Parsed stale plans are rejected before tick zero with
an explicit invalidation proof under `.xace/proof/sgc-migration/<cgs_hash>.json`.

What This Slice Proves:

- Parsed persisted plans that fail schema-version, plan-version,
  adapter-protocol, or migration-status checks now write
  `xace.sgc.plan_migration.v1` proof artifacts.
- The proof records `decision=reject_and_regenerate`,
  `migration_performed=false`, `fallback_to_cgs_derived=false`,
  `silent_downgrade_performed=false`, and `runtime_tick_started=false`.
- The proof captures both runtime expectations and stale plan identity so a
  support/debug path can explain which upgrade boundary invalidated the plan.
- Runtime errors include the migration proof path while preserving the original
  compatibility diagnostic.
- The strict SGC plan loader smoke now proves migration invalidation through the
  real runtime binary for adapter-protocol, schema-version, plan-version, and
  migration-status mismatches.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/cgs_loader.rs` | Standalone runtime CGS and SGC plan loading. | Writes `xace.sgc.plan_migration.v1` invalidation proofs when parsed persisted plans are stale or incompatible before tick zero. |
| `tools/runtime_sgc_plan_loader_smoke.py` | Editor-free strict SGC loader proof. | Adds real-binary checks for schema, plan-version, adapter-protocol, and migration-status proof artifacts. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Documents the current migration behavior as explicit invalidation/regeneration, not silent migration or downgrade. |

Verification:

- `cargo fmt`
- `python -m py_compile tools/runtime_sgc_plan_loader_smoke.py`
- `cargo test -p xace-runtime-core persisted_sgc_plan_rejects_ --lib --target-dir target-codex-task28-safe-compile`
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-task28-safe-compile`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-safe-compile`
- `python tools/runtime_sgc_plan_loader_smoke.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`

## Sixty-Fourth Slice: SGC Runtime Proof Command

Status: Task 33 adds a single retained command for the real CGS-to-SGC-to-runtime
path. `tools/sgc_runtime_proof.py` generates a small CGS with two supported
generated systems, invokes the real SGC executable, persists the emitted plan
with the strict runtime metadata envelope, launches the real runtime with
`--require-sgc-plan`, and runs the same project twice to compare schedule
snapshots and per-tick world hash logs. By default, every run is retained under
`.xace/proof/sgc-runtime/<run-id>/`.

What This Slice Proves:

- The command invokes the compiled SGC binary through stdin/stdout and rejects
  failure or malformed output before writing a runtime proof.
- The persisted `.xace/execution_plans/<cgs_hash>.plan.json` file keeps SGC's
  schedule semantics and adds only the runtime-required access, metadata,
  loadability, and proof-reference fields.
- The standalone runtime loads the persisted plan in strict `persisted_sgc`
  mode; it does not derive a fallback schedule.
- The runtime schedule report now records `hash_log` and `latest_world_hash`
  alongside schedule snapshots.
- The proof compares both schedule snapshots and tick hash logs across replay,
  and records `no_fake_wiring=true` only after the real SGC and runtime
  binaries both succeed.
- The retained local proof run
  `.xace/proof/sgc-runtime/20260628T051852Z/summary.json` passed with two
  generated executor kinds and three ticks.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/sgc_runtime_proof.py` | Retained SGC/runtime proof command. | Creates CGS input, invokes real SGC, persists the plan, runs the real runtime twice, compares tick hashes and schedule snapshots, and stores proof artifacts under `.xace/proof/sgc-runtime/<run-id>/`. |
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime CLI reports. | Adds `latest_world_hash` and per-tick `hash_log` to `--schedule-snapshot-out` reports. |
| `tools/runtime_sgc_schedule_snapshot_smoke.py` | Editor-free runtime schedule proof. | Asserts report hash logs and latest world hash in addition to schedule snapshot equality. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the SGC runtime proof command in quick/full certification using a scratch proof root. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md`, `docs/fake_skip_register.json` | Source inventory and fake/skip governance. | Classifies the retained proof command as test-only proof tooling and registers intentional SGC fallback-proof terminology. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md` | SGC/readiness/governance docs. | Marks the Task 33 local proof command complete and records the then-next Task 34 end-to-end proof gate. |

Verification:

- `cargo fmt`
- `python -m py_compile tools/sgc_runtime_proof.py tools/certify_launch.py tools/runtime_sgc_schedule_snapshot_smoke.py`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-safe-compile`
- `cargo build -p xace-system-graph-compiler --target-dir target-codex-task28-safe-compile`
- `python tools/sgc_runtime_proof.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe --sgc-bin target-codex-task28-safe-compile/debug/xace-system-graph-compiler.exe --ticks 3`
- `python tools/runtime_sgc_schedule_snapshot_smoke.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe`
- `cargo test -p xace-runtime-core --lib --target-dir target-codex-task28-safe-compile`
- `python tools/source_inventory_check.py`
- `python tools/fake_skip_register_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task33-quick`

## Sixty-Fifth Slice: End-To-End CGS Proof

Status: Task 34 adds a retained end-to-end generated CGS proof and wires it
into launch certification plus hosted CI artifact retention. The proof command
generates the CGS, invokes the real SGC binary, persists the emitted SGC plan,
loads that plan through the real runtime in strict mode, proves deterministic
tick/hash replay, runs the runtime's `replay_record` and `replay_validate`
control hooks, captures rollback-failure restoration evidence, and verifies a
live adapter tick snapshot in one path. The local retained run
`.xace/proof/cgs-e2e/20260628T054855Z/summary.json` passed with three ticks,
rollback byte-for-byte restoration, and a generated counter value of `1` in the
adapter snapshot.

What This Slice Proves:

- `tools/cgs_end_to_end_proof.py` creates a generated CGS with two explicit
  generated-system ABI blocks and records `xace.cgs_generation_proof.v1`.
- The proof invokes the compiled `xace-system-graph-compiler` executable and
  refuses malformed or failed SGC output before runtime launch.
- The persisted `.xace/execution_plans/<cgs_hash>.plan.json` plan is the
  strict runtime authority; the runtime reports `plan_source=persisted_sgc`.
- Two strict runtime runs produce identical schedule snapshots and identical
  per-tick world hash logs.
- A paused runtime is stepped through the real control socket, then
  `replay_record` and `replay_validate` compare the live hash/schedule record
  against a fresh runtime loaded from the same CGS.
- The rollback leg runs the five-operation op3-failure mutation proof under
  the same retained proof directory and verifies `hashes_equal=true` plus
  `byte_for_byte_equal=true`.
- The adapter leg performs a real length-prefixed JSON handshake, steps one
  deterministic tick, stores the `tick_snapshot`, and verifies that the
  generated counter component was incremented from `0` to `1`.
- `.github/workflows/xace-scope.yml` now has a `cgs-e2e-proof` job that builds
  the proof binaries, runs the proof, and retains `.xace/proof/cgs-e2e-ci/`
  artifacts for 30 days.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/cgs_end_to_end_proof.py` | Retained Task 34 proof command. | Chains generated CGS creation, real SGC compile, strict runtime replay/hash proof, control replay validation, rollback failure proof artifacts, and adapter snapshot validation. |
| `.github/workflows/xace-scope.yml` | Hosted governance/CI workflow. | Adds the `cgs-e2e-proof` job and uploads retained proof artifacts on every run. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the end-to-end CGS proof in quick/full certification using a scratch proof root. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new proof command as test-only proof tooling. |
| `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | SGC/readiness/governance docs. | Marks Task 34 complete locally, documents CI artifact retention, and narrows remaining SGC claims to future plugin/external/release-scale gates. |

Verification:

- `python -m py_compile tools/cgs_end_to_end_proof.py tools/certify_launch.py`
- `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-safe-compile`
- `cargo build -p xace-system-graph-compiler --target-dir target-codex-task28-safe-compile`
- `python tools/cgs_end_to_end_proof.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe --sgc-bin target-codex-task28-safe-compile/debug/xace-system-graph-compiler.exe --ticks 3 --target-dir target-codex-task28-safe-compile`
- `python tools/source_inventory_check.py`
- `python tools/fake_skip_register_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task34-quick`

## Sixty-Sixth Slice: Prompt Capability Matrix

Status: Task 35 defines the launch prompt capability matrix and makes it a
single shared artifact for docs and Builder. The canonical matrix lives at
`docs/prompt_capability_matrix.json` with schema
`xace.prompt_capability_matrix.v1`; the human-readable product wording is in
`docs/PROMPT_CAPABILITY_MATRIX.md`, and Builder exposes the same JSON through
`GET /api/prompt/capability-matrix`.

What This Slice Proves:

- The matrix defines exactly six Task 35 categories:
  `certified_supported`, `constrained`, `clarification_required`, `blocked`,
  `unsupported`, and `experimental`.
- Every category has product wording, Builder copy, a Builder decision,
  provider-call policy, mutation policy, and at least two examples.
- Certified supported examples include the existing deterministic prompt
  contract scenarios: player speed value mutation, inventory component add,
  and pickup actor add.
- The blocked category includes the current deterministic broad prompt fixture
  and preserves the no-pending-transaction behavior already covered by prompt
  pipeline tests.
- Builder server code loads the matrix from the docs JSON, validates the
  required category order, computes the canonical `matrix_hash`, and returns it
  through `/api/prompt/capability-matrix`.
- Builder TypeScript now has `PromptCapabilityMatrix` types and client access
  for the same API shape instead of defining a parallel category model.
- Builder boot fetches the shared matrix and stores it in UI state for prompt
  UX/classifier flows instead of hard-coding local prompt categories.
- `tools/prompt_capability_matrix_check.py` verifies the JSON, docs hash,
  Builder server route, Builder client route, and deterministic prompt
  contract alignment.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `docs/prompt_capability_matrix.json` | Prompt capability source of truth. | Defines the six Task 35 categories, examples, product wording, Builder decisions, and policies. |
| `docs/PROMPT_CAPABILITY_MATRIX.md` | Human-readable prompt capability doc. | Documents the matrix hash, category summary, examples, Builder contract, and verification command. |
| `packages/builder-workspace/server/prompt_capability_matrix.py` | Builder matrix loader. | Loads and validates the docs JSON, computes `matrix_hash`, and exposes category lookup. |
| `packages/builder-workspace/server/builder_server.py` | Builder HTTP API. | Adds `GET /api/prompt/capability-matrix` returning the shared matrix. |
| `packages/builder-workspace/src/api/builder_client.ts`, `packages/builder-workspace/src/app.ts`, `packages/builder-workspace/src/state/ui_store.ts` | Builder UI matrix wiring. | Adds prompt capability matrix interfaces, fetches the Builder endpoint at boot, and stores the returned matrix for prompt UX/classifier flows. |
| `packages/builder-workspace/server/tests/test_prompt_capability_matrix.py` | Builder matrix tests. | Verifies required categories, deterministic prompt-contract alignment, and endpoint/hash equality. |
| `tools/prompt_capability_matrix_check.py` | Governance validator. | Checks JSON/docs/Builder alignment and prompt fixture coverage. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds the prompt capability matrix checker to quick/full certification and Python compilation. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the prompt matrix docs and checker. |
| `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Readiness and claims docs. | Records Task 35 as locally complete while leaving Task 36 classifier enforcement and the 100-prompt corpus as future gates. |

Verification:

- `python -m py_compile tools/prompt_capability_matrix_check.py packages/builder-workspace/server/prompt_capability_matrix.py packages/builder-workspace/server/builder_server.py tools/certify_launch.py`
- `python tools/prompt_capability_matrix_check.py`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_capability_matrix.py`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `npm run build` from `packages/builder-workspace`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task35-quick` was attempted first and passed the new prompt capability matrix gate before the fresh Rust target compile exhausted local disk space (`os error 112`, `no space on device`); that generated artifact directory was removed after verification.
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task34-quick --report-path target-codex-certify-task35-quick\launch_certification_report_cache_rerun.json` passed all 24 editor-free checks with installed-engine skips recorded as unsupported.

## Sixty-Seventh Slice: Prompt Classifier Gate

Status: Task 36 adds a deterministic Builder prompt classifier gate backed by
the Task 35 capability matrix. Every `pil_process` request is classified before
`SessionManager.run_pil()`, mutation planning, or provider calls. Only
`certified_supported` and `constrained` categories may continue to PIL; ambiguous,
blocked, unsupported, and experimental routes return a classifier-bearing
`pil_result` immediately and clear pending prompt state.

What This Slice Proves:

- Easy certified prompts continue through PIL/provider readiness and include the
  classifier payload on the returned result.
- Ambiguous prompts route to `clarification_required` and return a bounded
  clarification result before mutation planning. Task 37 owns the recorded
  resolution loop that follows this classifier result.
- Unsupported and adversarial prompts route to `unsupported` or `blocked` before
  provider calls, generated-code paths, filesystem/network behavior, or CGS
  mutation planning.
- Non-accepted classifications clear any prior pending prompt transaction, so a
  later `pil_apply` cannot accidentally apply stale prompt work.
- `tools/prompt_classifier_gate_check.py` validates representative easy,
  ambiguous, unsupported, and adversarial routing and checks that
  `WSMessageRouter._handle_pil_process()` calls the classifier before `run_pil`.
- Quick launch certification now includes an explicit `prompt classifier gate`
  check in addition to the Task 35 matrix check.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/prompt_classifier_gate.py` | Prompt classifier gate. | Loads the Task 35 matrix, deterministically classifies prompts, and returns JSON-safe classifier/PIL-blocking payloads. |
| `packages/builder-workspace/server/ws_message_router.py` | Builder WebSocket routing. | Gates `pil_process` before `SessionManager.run_pil()`, clears pending state on non-accepted routes, and attaches classifier results to accepted PIL output. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Prompt route integration tests. | Verifies certified prompts still reach PIL, while ambiguous, unsupported, and adversarial prompts do not call the pipeline and leave no pending transaction. |
| `tools/prompt_classifier_gate_check.py` | Governance validator. | Checks Task 36 routing cases and static router ordering. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt classifier gate checker in quick/full certification. |
| `packages/builder-workspace/src/types/pil.ts` | Builder PIL result types. | Adds optional classifier payload typing for prompt results. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Readiness and claims docs. | Records the classifier gate as locally complete while leaving the recorded clarification loop, hosted-provider proof, and corpus benchmarking pending. |

Verification:

- `python -m py_compile packages/builder-workspace/server/prompt_classifier_gate.py packages/builder-workspace/server/ws_message_router.py tools/prompt_classifier_gate_check.py tools/certify_launch.py`
- `python tools/prompt_classifier_gate_check.py`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_capability_matrix.py`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `npm run build` from `packages/builder-workspace`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task34-quick --report-path target-codex-certify-task36-quick\launch_certification_report_cache_rerun.json` passed all 25 editor-free checks, including `prompt classifier gate`, with installed-engine skips recorded as unsupported.

## Sixty-Eighth Slice: Prompt Clarification Loop

Status: Task 37 adds the recorded classifier clarification loop. Ambiguous
`clarification_required` prompts now create a bounded prompt clarification
session before PIL/provider mutation generation. Builder records the selected
user resolution, blocks `pil_apply` while the classifier clarification is
pending, and clears the pending clarification only after a bounded answer is
accepted. The answer itself does not generate a mutation; the user must submit
a clarified supported prompt afterward.

What This Slice Proves:

- `WSMessageRouter._handle_pil_process()` still classifies before PIL and now
  starts a `xace.prompt_clarification_session.v1` record for
  `clarification_required` routes.
- `SessionManager` stores pending classifier clarification state separately
  from PIL mutation transactions and keeps a bounded
  `prompt_clarification_log` of `xace.prompt_clarification_resolution.v1`
  records.
- `pil_apply` returns `PROMPT_CLARIFICATION_REQUIRED` while an ambiguous prompt
  clarification is unresolved, so no stale or ambiguous prompt transaction can
  mutate CGS.
- `pil_answer` resolves classifier clarification sessions before delegating to
  PIL's own clarification handler, validates that answers are selected from the
  listed bounded options, and leaves no pending transaction after resolution.
- Builder protocol/UI types expose `requires_reprompt`, `resolved_prompt`, and
  `clarification_result`; classifier clarifications return the prompt input to
  an editable state instead of pretending a mutation is already processing.
- `tools/prompt_clarification_loop_check.py` verifies the dynamic loop and
  router hooks, and quick launch certification now includes the checker.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/session_manager.py` | Builder session state. | Adds pending prompt clarification sessions, bounded answer validation, resolution logging, and no-transaction resolution semantics. |
| `packages/builder-workspace/server/ws_message_router.py` | Builder WebSocket routing. | Starts classifier clarification sessions, resolves classifier answers before PIL answers, and blocks apply while clarification is pending. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Prompt route integration tests. | Proves ambiguous prompts do not call PIL, do not create pending transactions, cannot apply, and record a bounded resolution before later supported prompt mutation generation. |
| `packages/builder-workspace/src/api/message_types.ts`, `packages/builder-workspace/src/types/pil.ts`, `packages/builder-workspace/src/api/builder_client.ts`, `packages/builder-workspace/src/state/console_state_machine.ts` | Builder prompt protocol/UI state. | Adds clarification-resolution fields and returns classifier clarifications to an editable prompt state after the answer is recorded. |
| `tools/prompt_clarification_loop_check.py` | Governance validator. | Checks Task 37 loop behavior and router wiring. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt clarification loop checker in quick/full certification. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new checker. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Readiness and claims docs. | Records Task 37 as locally complete while leaving hosted-provider proof and the 100-prompt corpus as future gates. |

Verification:

- `python -m py_compile packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/ws_message_router.py tools/prompt_clarification_loop_check.py`
- `python tools/prompt_clarification_loop_check.py --json`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py -k clarification`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python tools/prompt_classifier_gate_check.py`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `npm run build` from `packages/builder-workspace`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task34-quick --report-path target-codex-certify-task37-quick\launch_certification_report_cache_rerun.json` passed all 26 editor-free checks, including `prompt clarification loop`, with installed-engine skips recorded as unsupported.

## Sixty-Ninth Slice: Prompt Diff Preview And Approval

Status: Task 42 adds the prompt diff preview and approval gate for accepted
prompt mutations. Builder now returns a deterministic
`xace.prompt_diff_preview.v1` preview before apply, covering CGS, system,
asset, SGC, runtime, and cost sections. `pil_apply` refuses to persist the
pending mutation unless the request includes the matching preview approval
token or an audited test-mode override with a reason.

What This Slice Proves:

- Accepted mutation results carry `approval_required=true` and a structured
  prompt diff preview with an approval token.
- The preview includes CGS operation rows plus system, asset, SGC, runtime, and
  cost sections so Builder can show the user what will change before apply.
- `pil_apply` rejects missing or mismatched approvals before GDE, SGC, or CGS
  persistence can run.
- Rejected unapproved applies leave the original CGS hash and on-disk CGS
  unchanged, and keep the pending transaction available for later approved
  apply.
- Test-mode override requires a reason, is marked as test-only in the approval
  record, and is included in the mutation audit dataset.
- Builder review surfaces and the console decision bar send the preview ID and
  approval token when applying a reviewed prompt mutation.
- `tools/prompt_diff_approval_check.py` verifies dynamic approval behavior and
  static Builder/server hooks, and quick launch certification now includes the
  checker.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/session_manager.py` | Builder session state, prompt mutation preparation, and apply preconditions. | Builds structured prompt diff previews, stores pending preview state, validates explicit preview approvals, and records approval audit rows. |
| `packages/builder-workspace/server/ws_message_router.py` | Builder WebSocket prompt apply route. | Blocks unapproved prompt applies before GDE/SGC/persistence and records rejected/approved approval metadata in mutation audit output. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Prompt route integration tests. | Proves approved apply succeeds, missing approval does not persist, and test-mode override is audited. |
| `packages/builder-workspace/src/api/message_types.ts`, `packages/builder-workspace/src/types/pil.ts` | Builder prompt protocol types. | Adds prompt preview approval payloads and structured preview typing. |
| `packages/builder-workspace/src/views/processing_view.ts`, `packages/builder-workspace/src/console/decision_bar.ts` | Builder prompt apply UI. | Sends matching preview approvals when the user applies a reviewed prompt mutation. |
| `packages/builder-workspace/src/canvas/diff_viewer.ts` | Builder prompt diff display. | Renders structured CGS, Systems, Assets, SGC/Runtime, Cost, and Code preview tabs. |
| `tools/prompt_pipeline_smoke.py` | Editor-free prompt pipeline contract/scenario smoke. | Sends the structured preview approval token before applying supported prompt scenarios and asserts the normal approval path was recorded. |
| `tools/prompt_diff_approval_check.py` | Governance validator. | Checks approval rejection, mismatch rejection, valid approval, audited test-mode override, and static UI/server hooks. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt diff approval gate checker in quick/full certification. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 42 as locally complete while leaving corpus benchmark, hosted-provider proof, validation feedback, rollback recovery, and broad prompt generation pending. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new approval checker as production governance tooling. |

Verification:

- `python -m py_compile packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/ws_message_router.py`
- `python -m py_compile tools/prompt_pipeline_smoke.py tools/prompt_diff_approval_check.py tools/certify_launch.py`
- `python tools/prompt_diff_approval_check.py --json`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `npm run build` from `packages/builder-workspace`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_classifier_gate_check.py`
- `python tools/prompt_clarification_loop_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task34-quick --report-path target-codex-certify-task42-quick\launch_certification_report_cache_rerun.json`

## Seventieth Slice: Prompt Rollback Recovery

Status: Task 44 adds covered prompt-apply rollback recovery for failures that
occur before or after prompt mutation apply. The prompt route now captures the
pre-apply CGS/session runtime state, restores it when snapshot, SGC
plan/proof, runtime reload, replay validation, adapter validation, or provider
readiness fails, removes failed post-apply snapshot/plan/proof artifacts, and
returns a structured `xace.prompt_apply_recovery.v1` rollback report instead of
sending a UI success update.

What This Slice Proves:

- Failed post-apply snapshot persistence restores `game.cgs.json`, in-memory
  CGS, GDE state, snapshot index, and UI state to the pre-apply hash.
- Failed SGC plan/proof persistence removes both `.xace/execution_plans/<hash>.plan.json`
  and `.xace/proof/sgc/<hash>/` for the failed hash.
- Runtime reload, replay validation, and adapter validation failures restore the
  pre-apply CGS and cached runtime status, then ask the runtime-control path to
  reload the pre-apply version IDs when a runtime had been connected.
- Provider readiness failure leaves no pending transaction, no partial snapshot,
  no execution plan, no proof bundle, and no `cgs_update`.
- Recovery failures are audited as `rejected_recovered` with
  `rollback_status=restored_pre_apply` and the rollback report embedded in the
  mutation audit dataset.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/cgs_persistence.py` | CGS persistence, snapshots, plans, proof bundles, and audit storage. | Adds `restore_prompt_apply_failure()` to restore the pre-apply CGS and remove failed-hash snapshot, snapshot-index, execution-plan, and SGC proof artifacts. |
| `packages/builder-workspace/server/ws_message_router.py` | Builder WebSocket prompt apply route. | Captures pre-apply recovery state, converts snapshot/plan/proof/runtime/replay/adapter validation failures into rollback errors, restores session/GDE/runtime state, emits `xace.prompt_apply_recovery.v1`, and blocks `cgs_update` on failure. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Prompt route integration tests. | Adds failure-injection tests for snapshot, plan/proof, runtime reload, replay validation, adapter validation, and provider readiness failures. |
| `packages/builder-workspace/src/api/message_types.ts` | Builder WebSocket protocol types. | Adds optional prompt apply validation requirements, `cgs_update.apply_validation`, and rollback metadata on `server_error`. |
| `tools/prompt_apply_recovery_check.py` | Governance validator. | Runs the rollback failure subset and checks static recovery/report/audit hooks. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt apply atomic recovery gate in quick/full certification. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 44 as locally complete while keeping hosted provider proof, corpus benchmarking, and full validation feedback as future gates. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new recovery checker as production governance tooling. |

Verification:

- `python -m py_compile packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/cgs_persistence.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py tools/prompt_apply_recovery_check.py tools/certify_launch.py`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py -k rolls_back`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python tools/prompt_apply_recovery_check.py --json`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/prompt_classifier_gate_check.py`
- `python tools/prompt_clarification_loop_check.py`
- `python tools/prompt_diff_approval_check.py`
- `npm run build` from `packages/builder-workspace`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task34-quick --report-path target-codex-certify-task44-quick\launch_certification_report_cache_rerun.json`

## Seventy-First Slice: Prompt Apply Validation Feedback

Task 45 adds a deterministic prompt-apply feedback envelope so every
`pil_apply` response reports the same validation surface: classifier result,
structured diff, SGC result, runtime load result, replay result, adapter result,
rollback status, cost, latency, proof links, approval metadata, authority
hashes, and error stage/code. Builder now waits in an `ApplyingMutation` state
after the user clicks Apply, completes only on `cgs_update`, and renders
feedback-bearing `server_error` responses without falling back to a generic
masked failure.

What This Slice Proves:

- Successful prompt applies return `xace.prompt_apply_feedback.v1` on
  `cgs_update` with classifier, diff, SGC, runtime, replay, adapter, rollback,
  cost, latency, and proof-link sections.
- SGC failures return the same feedback envelope on `server_error`, including
  the actionable compiler error, preserved classifier/diff, and
  `rollback.status=not_persisted`.
- Runtime validation failures preserve partial validation reports, restore
  pre-apply CGS/runtime state through Task 44 recovery, and return
  `rollback.status=restored_pre_apply`.
- Builder no longer marks prompt mutations applied before the backend response;
  it holds an apply-in-progress state and shows structured feedback rows for
  classifier, diff, SGC, runtime, replay, rollback, cost, latency, and proof
  paths when an apply fails.
- The launch certification quick/full sets include the new
  `tools/prompt_apply_validation_feedback_check.py` gate.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/session_manager.py` | Builder session and pending prompt state. | Preserves the pending serialized prompt result so apply feedback can include the real classifier and diff context. |
| `packages/builder-workspace/server/ws_message_router.py` | Builder WebSocket prompt apply route. | Adds `xace.prompt_apply_feedback.v1`, attaches it to prompt apply success/failure/recovery/handler-error responses, and carries partial runtime/replay/adapter validation reports through recovery errors. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Prompt route integration tests. | Adds feedback success, SGC failure, and runtime rollback tests covering the Task 45 ABI. |
| `packages/builder-workspace/src/types/pil.ts`, `packages/builder-workspace/src/api/message_types.ts` | Builder prompt and WebSocket protocol types. | Adds typed prompt apply feedback on `cgs_update` and `server_error`. |
| `packages/builder-workspace/src/state/console_state_machine.ts`, `packages/builder-workspace/src/api/builder_client.ts` | Builder client state and WebSocket dispatch. | Adds `ApplyingMutation`, backend-confirmed apply completion, and feedback-bearing server error handling. |
| `packages/builder-workspace/src/views/processing_view.ts`, `packages/builder-workspace/src/canvas/builder_canvas.ts`, `packages/builder-workspace/src/canvas/prompt_input.ts`, `packages/builder-workspace/src/console/ingame_console.ts` | Builder prompt/apply UX surfaces. | Shows apply validation progress, disables prompt input while apply is pending, and renders structured failure feedback. |
| `tools/prompt_apply_validation_feedback_check.py` | Governance validator. | Runs the Task 45 focused feedback tests and checks static server/UI contract hooks. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt apply validation feedback gate in quick/full certification. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 45 as locally complete while keeping hosted provider proof and the 100-prompt benchmark as future gates. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new feedback checker as production governance tooling. |

Verification:

- `python -m py_compile packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py tools/prompt_apply_validation_feedback_check.py tools/certify_launch.py`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py -k validation_feedback`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py -k rolls_back`
- `python tools/prompt_apply_validation_feedback_check.py --json`
- `npm run build` from `packages/builder-workspace`

## Seventy-Second Slice: Prompt Corpus

Task 46 adds the reviewed, versioned `xace.prompt_corpus_100.v1` JSONL
corpus that later benchmark tooling will execute. The corpus is static source
data, not hosted-provider proof and not benchmark results. It covers the
required prompt bands and genres while keeping every expected route tied to the
Task 35 prompt capability matrix.

What This Slice Proves:

- `docs/prompt_corpus_100.jsonl` contains exactly 100 reviewed JSONL cases
  with stable `pc001` through `pc100` identifiers.
- The corpus covers platformer, RPG, shooter, survival, puzzle, strategy,
  inventory, simulation, multiplayer combat, and hybrid prompts with ten cases
  per genre.
- The corpus covers easy, medium, advanced, ambiguous, unsupported, and
  adversarial bands, and certified supported, constrained,
  clarification-required, blocked, unsupported, and experimental categories.
- `docs/prompt_corpus_manifest.json` pins the corpus version, required counts,
  review metadata, source path, and SHA-256 hash.
- `tools/prompt_corpus_check.py` validates JSONL syntax, dense rows, sequential
  IDs, unique prompt text, manifest hash, category/matrix alignment,
  expected Builder routes, result kinds, review metadata, and coverage counts.
- Launch certification quick/full runs now include the prompt corpus gate.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `docs/prompt_corpus_100.jsonl` | Reviewed prompt corpus source artifact. | Adds 100 approved prompt cases across required difficulty bands, categories, and game genres. |
| `docs/prompt_corpus_manifest.json` | Corpus version and integrity manifest. | Records corpus id, version, source path, review metadata, required coverage, expected counts, and SHA-256. |
| `docs/PROMPT_CORPUS.md` | Human-readable corpus contract. | Documents the source of truth, row schema, coverage, hash, and validation command. |
| `tools/prompt_corpus_check.py` | Governance validator. | Checks manifest integrity, corpus syntax, stable IDs, route/category consistency, coverage counts, and review status. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt corpus gate in quick/full certification. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 46 as locally complete while keeping hosted-provider proof and the 100-prompt benchmark results/thresholds as future gates. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the prompt corpus docs, manifest, JSONL, and checker as production source artifacts. |

Verification:

- `python -m py_compile tools/prompt_corpus_check.py tools/certify_launch.py`
- `python tools/prompt_corpus_check.py --json`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task46-quick --report-path target-codex-certify-task46-quick\launch_certification_report.json`

## Seventy-Third Slice: Prompt Corpus Benchmark Tool

Task 47 adds `tools/prompt_corpus_benchmark.py`, a local classifier-only
benchmark report generator for the reviewed Task 46 corpus. The tool runs all
100 JSONL prompts through the real Builder prompt classifier/matrix gate and
writes machine and human reports. It records the required accepted, blocked,
clarified, compiled, runtime-passed, rollback-passed, cost, latency, provider,
model, and reproducibility columns while explicitly marking provider calls, SGC
compile, runtime execution, rollback execution, and launch thresholds as not
run in the default local mode.

What This Slice Proves:

- `tools/prompt_corpus_benchmark.py` loads `docs/prompt_corpus_100.jsonl`,
  checks the manifest SHA-256, classifies every prompt, and writes all reports
  before returning success.
- `summary.json` uses schema `xace.prompt_corpus_benchmark.v1` and contains
  summary counts, route/category/result-kind match counts, cost/latency
  totals, local execution-scope caveats, full per-case rows, and a stable run
  signature.
- `results.jsonl` emits one `xace.prompt_corpus_benchmark_case.v1` row per
  prompt with accepted, blocked, clarified, compiled, runtime-passed,
  rollback-passed, cost, latency, provider, model, and reproducibility fields.
- `report.md` provides a human-readable summary, category table, route
  mismatch table, and full 100-row result table.
- Launch certification quick/full now compiles the benchmark tool and runs the
  prompt corpus benchmark gate into the certification target directory.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/prompt_corpus_benchmark.py` | Local prompt corpus benchmark report generator. | Adds classifier-only benchmark execution plus `summary.json`, `results.jsonl`, and `report.md` artifact writing. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt corpus benchmark gate in quick/full certification. |
| `docs/PROMPT_CORPUS.md`, `docs/PROMPT_CAPABILITY_MATRIX.md` | Prompt corpus/capability docs. | Document the benchmark command, output files, required columns, and local classifier-only caveat. |
| `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Readiness and claims docs. | Records Task 47 as locally complete while keeping hosted provider proof and launch thresholds as future gates. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new benchmark helper as test-only evidence tooling. |

Verification:

- `python -m py_compile tools/prompt_corpus_benchmark.py tools/certify_launch.py`
- `python tools/prompt_corpus_benchmark.py --output target-production-prompt-corpus --json`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task47-quick --report-path target-codex-certify-task47-quick\launch_certification_report.json`

## Seventy-Fourth Slice: Prompt Launch Thresholds

Task 48 defines measurable prompt launch threshold profiles and wires them into
the prompt corpus benchmark. The default `local_classifier` profile gates the
metrics XACE can measure today: classification accuracy, route accuracy,
result-kind accuracy, unsupported no-mutation behavior, exact unsupported/block
routing, cost, latency, and reproducibility. The stricter
`launch_provider_runtime` profile records the future launch bar for hosted
provider reliability, compilation success, runtime success, rollback success,
cost, latency, and reproducibility, and intentionally fails against local
classifier-only reports.

What This Slice Proves:

- `docs/prompt_launch_thresholds.json` stores versioned threshold profiles with
  schema `xace.prompt_launch_thresholds.v1`.
- `tools/prompt_corpus_benchmark.py` evaluates the selected threshold profile,
  writes `xace.prompt_launch_threshold_evaluation.v1` into `summary.json`,
  renders the threshold table in `report.md`, and exits non-zero when selected
  thresholds fail.
- `tools/prompt_launch_threshold_check.py` runs the default local benchmark and
  verifies threshold pass, then creates an intentionally stricter threshold file
  and verifies that the benchmark fails below threshold.
- `docs/PROMPT_LAUNCH_THRESHOLDS.md` documents the local and future launch
  threshold profiles plus the verification commands.
- Launch certification quick/full now includes the prompt launch thresholds
  gate.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `docs/prompt_launch_thresholds.json` | Machine-readable prompt threshold profiles. | Adds local classifier and future launch provider/runtime threshold gates for classification, compile, runtime, rollback, unsupported blocking, cost, latency, reliability, and reproducibility. |
| `docs/PROMPT_LAUNCH_THRESHOLDS.md` | Human-readable threshold contract. | Documents threshold profiles, measured metrics, future launch caveats, and commands. |
| `tools/prompt_corpus_benchmark.py` | Prompt corpus benchmark report generator. | Evaluates thresholds, fails below profile, writes threshold status/checks/failures, and renders a threshold table in Markdown. |
| `tools/prompt_launch_threshold_check.py` | Governance validator. | Proves the default profile passes and a stricter threshold makes the benchmark fail. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt launch threshold gate in quick/full certification. |
| `docs/PROMPT_CORPUS.md`, `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 48 as locally complete while keeping hosted provider/runtime threshold execution as future proof. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies threshold docs, JSON, and checker. |

Verification:

- `python -m py_compile tools/prompt_corpus_benchmark.py tools/prompt_launch_threshold_check.py tools/certify_launch.py`
- `python tools/prompt_corpus_benchmark.py --output target-production-prompt-corpus --json`
- `python tools/prompt_launch_threshold_check.py --json`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task48-quick --report-path target-codex-certify-task48-quick\launch_certification_report.json`

## Seventy-Fifth Slice: Prompt Security Tests

Task 50 adds deterministic prompt-security attack cases and a proof-producing
gate. The checked cases cover prompt injection, adversarial instructions,
malformed model responses, unsafe mutations, hallucinated capabilities, schema
corruption, and secret exfiltration. Each case must either be blocked by the
real prompt classifier before provider/mutation execution or quarantined by a
payload validator with a recorded reason.

What This Slice Proves:

- `docs/prompt_security_cases.jsonl` stores the checked attack corpus with
  schema `xace.prompt_security_case.v1`.
- `tools/prompt_security_check.py` exercises the real Builder classifier for
  prompt-level attacks and deterministic quarantine validators for provider
  response, mutation, capability, and CGS-fragment payloads.
- The checker writes `xace.prompt_security_report.v1` plus per-case
  `xace.prompt_security_case_result.v1` rows under the requested artifact
  directory.
- The current local run covers 14 cases: 6 blocked and 8 quarantined, with zero
  provider calls and zero allowed mutations.
- Launch certification quick/full now includes the `prompt security gate`.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `docs/prompt_security_cases.jsonl` | Machine-readable prompt-security attack corpus. | Adds required Task 50 cases for injection, adversarial instruction, malformed response, unsafe mutation, hallucinated capability, schema corruption, and secret exfiltration. |
| `docs/PROMPT_SECURITY_TESTS.md` | Human-readable prompt-security test contract. | Documents case schema, guard behavior, artifact paths, command usage, and scope limits. |
| `tools/prompt_security_check.py` | Prompt security governance validator. | Blocks/quarantines every checked case, writes JSONL/JSON/Markdown artifacts, and fails on any unblocked or unquarantined attack. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the prompt security gate in quick/full certification. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 50 as locally complete while keeping hosted provider/runtime threshold execution and broader security review as future proof. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the prompt-security docs, JSONL corpus, and checker. |

Verification:

- `python -m py_compile tools/prompt_security_check.py tools/certify_launch.py`
- `python tools/prompt_security_check.py --artifact-dir target-prompt-security --json`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task50-quick --report-path target-codex-certify-task50-quick\launch_certification_report.json`

## Seventy-Sixth Slice: Inference Adapter Boundary

Task 51 enforces that Builder, PIL, GDE, and repository tools do not call LLM
providers directly. Provider SDK imports, hosted completion endpoints, local
Ollama completion HTTP, hosted model discovery, retry, budget, cache, and
telemetry paths are centralized under `packages/inference`.

What This Slice Proves:

- Builder's local Ollama path now uses
  `packages/builder-workspace/server/ollama_adapter.py` as a thin
  inference-backed wrapper around `LocalModelManager` and `InferenceAdapter`.
- Hosted provider model discovery moved into
  `packages/inference/src/provider_model_discovery.py`, so Builder settings no
  longer perform provider HTTP directly.
- `tools/inference_adapter_boundary_check.py` scans Builder, PIL, GDE, and
  tools for provider SDK imports or provider completion HTTP outside
  `packages/inference`.
- The scanner includes detector self-tests and fails CI if a representative
  direct provider call is no longer detected.
- `.github/workflows/xace-scope.yml` and quick/full launch certification now
  run the `inference adapter boundary` gate.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/inference/src/provider_model_discovery.py` | Inference-owned provider model discovery. | Adds hosted provider model-list HTTP under the inference package boundary. |
| `packages/builder-workspace/server/provider_settings.py` | Builder provider selection, credentials, and readiness state. | Calls inference-owned discovery and continues building `InferenceAdapter` for provider test calls. |
| `packages/builder-workspace/server/ollama_adapter.py` | Builder local-provider compatibility surface. | Replaces direct Ollama HTTP with an inference-backed wrapper over `LocalModelManager` and `InferenceAdapter`. |
| `packages/builder-workspace/ollama_adapter.py` | Legacy Builder import shim. | Re-exports the server implementation without provider HTTP. |
| `tools/inference_adapter_boundary_check.py` | Inference boundary governance validator. | Scans Builder/PIL/GDE/tools and writes `xace.inference_adapter_boundary_report.v1` artifacts. |
| `.github/workflows/xace-scope.yml` | Hosted governance CI. | Runs the boundary gate on pull requests and pushes to `main`. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the inference adapter boundary gate in quick/full certification. |
| `docs/INFERENCE_ADAPTER_BOUNDARY.md` | Human-readable boundary contract. | Documents allowed provider-call roots, blocked patterns, implementation notes, and commands. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 51 as locally complete while keeping hosted provider/runtime threshold reliability and broader security review as future proof. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the boundary doc and checker. |

Verification:

- `python -m py_compile tools/inference_adapter_boundary_check.py packages/inference/src/provider_model_discovery.py packages/builder-workspace/server/ollama_adapter.py packages/builder-workspace/ollama_adapter.py packages/builder-workspace/server/provider_settings.py tools/certify_launch.py`
- `python tools/inference_adapter_boundary_check.py --json`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task51-quick --report-path target-codex-certify-task51-quick\launch_certification_report.json`

## Seventy-Seventh Slice: Provider Timeout And Retry Policy

Task 52 defines and enforces the provider-call retry ABI under
`packages/inference`. Every live provider call through `InferenceAdapter` now
records timeout policy, actual attempts, retry count, rate-limit
classification, scheduled backoff, failure category, final outcome, and a
deterministic user-facing provider error code in telemetry.

What This Slice Proves:

- `InferenceRetryPolicy` emits `xace.inference_retry_attempt.v1` records for
  every provider attempt and one `xace.inference_retry_summary.v1` report for
  each provider call.
- `InferenceAdapter` emits failure telemetry for provider calls that exhaust
  retry policy before usable text is returned.
- `InferenceTelemetryEvent` now carries compact retry fields plus the full
  retry report, while session summaries aggregate attempts, retries, backoff,
  rate-limited calls, and failure categories.
- `tools/provider_timeout_retry_check.py` uses a local synthetic provider
  client with the real adapter to prove timeout recovery, exhausted timeout,
  exhausted rate limit, exhausted server error, exhausted schema error, and
  exhausted quality error behavior.
- `.github/workflows/xace-scope.yml` and quick/full launch certification now
  run the provider timeout/retry gate.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/inference/src/inference_retry_policy.py` | Provider retry policy. | Adds deterministic attempt/summary records, timeout policy fields, failure categorization, rate-limit backoff, injectable sleep for proof runs, and stable user-facing provider error payloads. |
| `packages/inference/src/inference_adapter.py` | Provider-agnostic LLM dispatch. | Captures retry reports, emits provider failure telemetry, and attaches retry summary fields to success/failure telemetry events. |
| `packages/inference/src/telemetry_pipeline.py` | Inference telemetry events and summaries. | Adds provider attempt, retry, timeout, rate-limit, backoff, failure-category, user-error, and retry-report fields plus summary aggregation. |
| `tools/provider_timeout_retry_check.py` | Provider timeout/retry governance validator. | Proves deterministic simulated timeout, rate-limit, server, schema, and quality failure outcomes through the real adapter. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the provider timeout/retry gate in quick/full certification. |
| `.github/workflows/xace-scope.yml` | Hosted governance CI. | Runs the provider timeout/retry gate on pull requests and pushes to `main`. |
| `docs/PROVIDER_TIMEOUT_RETRY_POLICY.md` | Human-readable provider retry contract. | Documents schemas, telemetry fields, failure categories, user error codes, and local proof command. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 52 as locally complete while keeping hosted provider reliability, token/cost accounting, and broader security review as future proof. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the provider retry policy doc and checker. |

Verification:

- `python -m py_compile packages/inference/src/inference_retry_policy.py packages/inference/src/inference_adapter.py packages/inference/src/telemetry_pipeline.py tools/provider_timeout_retry_check.py tools/certify_launch.py`
- `python tools/provider_timeout_retry_check.py --json`
- `python tools/inference_adapter_boundary_check.py --json`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/provider_readiness_smoke.py --settings-path target-codex-task52-focused\provider_settings.json`
- `python tools/security_secret_scan.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task52-quick --report-path target-codex-certify-task52-quick\launch_certification_report.json`

## Seventy-Eighth Slice: Provider Token And Cost Accounting

Task 53 defines a provider accounting ABI and emits redacted accounting
artifacts for prompt benchmark runs. The local classifier benchmark still makes
zero hosted provider calls, but every run now writes provider accounting JSONL,
summary JSON, and Markdown artifacts. A separate deterministic proof uses the
real `InferenceAdapter` with a local synthetic provider to prove exact
token/cost/accounting behavior on live success, response-cache hit,
deterministic Tier S shortcut, and provider failure paths.

What This Slice Proves:

- `packages/inference/src/provider_accounting.py` normalizes telemetry into
  `xace.provider_accounting_event.v1` rows and
  `xace.provider_accounting_summary.v1` summaries.
- `InferenceTelemetryEvent` redaction no longer depends on the Builder server
  import path; standalone inference telemetry has an inference-local fallback
  redactor.
- `InferenceAdapter` marks cache and deterministic telemetry with the correct
  provider kind for accounting summaries.
- `tools/prompt_corpus_benchmark.py` writes
  `provider_accounting.jsonl`, `provider_accounting_summary.json`, and
  `provider_accounting.md` beside the existing benchmark artifacts.
- `tools/provider_token_cost_accounting_check.py` proves exact prompt tokens,
  completion tokens, cache-read/write tokens, cost, model, tier, latency,
  request ID, cache-hit, deterministic-shortcut, failure, and redaction
  behavior through the real adapter.
- `.github/workflows/xace-scope.yml` and quick/full launch certification now
  run the provider token/cost accounting gate.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/inference/src/provider_accounting.py` | Provider accounting artifact ABI. | Adds redacted event/summary normalization and JSONL/JSON/Markdown artifact writing. |
| `packages/inference/src/telemetry_pipeline.py` | Inference telemetry events and summaries. | Adds inference-local redaction fallback for standalone telemetry exports. |
| `packages/inference/src/inference_adapter.py` | Provider-agnostic LLM dispatch. | Tags live, cache, and deterministic telemetry with correct provider kind. |
| `tools/provider_token_cost_accounting_check.py` | Provider accounting governance validator. | Proves token, cost, cache, model, tier, latency, request ID, failure, and redaction accounting through the real adapter. |
| `tools/prompt_corpus_benchmark.py` | Prompt corpus benchmark report generator. | Writes provider accounting artifacts for every prompt benchmark run. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the provider token/cost accounting gate in quick/full certification. |
| `.github/workflows/xace-scope.yml` | Hosted governance CI. | Runs the provider token/cost accounting gate on pull requests and pushes to `main`. |
| `docs/PROVIDER_TOKEN_COST_ACCOUNTING.md` | Human-readable accounting contract. | Documents schemas, redaction, prompt benchmark artifacts, and local proof command. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 53 as locally complete while keeping hosted provider/runtime threshold execution and broader security review as future proof. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the provider accounting policy doc and checker. |

Verification:

- `python -m py_compile packages/inference/src/inference_adapter.py packages/inference/src/telemetry_pipeline.py packages/inference/src/provider_accounting.py tools/prompt_corpus_benchmark.py tools/provider_token_cost_accounting_check.py tools/certify_launch.py`
- `python tools/provider_token_cost_accounting_check.py --json`
- `python tools/prompt_corpus_benchmark.py --output target-codex-task53-prompt-corpus --json`
- `python tools/prompt_launch_threshold_check.py --target-dir target-codex-task53-thresholds`
- `python tools/inference_adapter_boundary_check.py --json`
- `python tools/source_inventory_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/provider_timeout_retry_check.py --json`
- `python tools/provider_readiness_smoke.py --settings-path target-codex-task53-focused\provider_settings.json`
- `python tools/security_secret_scan.py --source`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task53-quick --report-path target-codex-certify-task53-quick\launch_certification_report.json`

## Seventy-Ninth Slice: Provider Health And Stale-Model Policy

Task 54 turns provider readiness into an exact ABI gate before PIL. Hosted
provider prompts now require a matching `xace.provider_health_proof.v1` for the
current provider, model, base URL, key fingerprint, and config hash. Missing
keys, unresolved models, invalid base URLs, untested tuples, malformed health
proofs, and stale model/base-url/key proofs all return deterministic
`PROVIDER_*` codes and block with `guard=provider_readiness`.

What This Slice Proves:

- `ProviderSettingsStore.active_readiness()` now exposes `code`,
  `proof_status`, `base_url`, `key_fingerprint`, and `config_hash` for the
  active provider.
- Hosted providers are ready only when `provider`, `model`, `base_url`,
  `key_fingerprint`, `config_hash`, `tested_at_epoch`, and all required health
  checks match the current tuple.
- Saving a new model, base URL, or key preserves the old proof for audit
  context but marks it stale until Test runs again.
- `SessionManager.run_pil()` includes the readiness `code`, `action`, and
  `guard=provider_readiness` in the blocked result before PIL starts.
- `tools/provider_readiness_smoke.py` writes
  `xace.provider_health_stale_policy_report.v1` artifacts covering missing key,
  untested tuple, exact ready tuple, stale model, stale base URL, stale key
  fingerprint, malformed proof, and invalid base URL.
- Quick/full launch certification stores the provider health/stale-policy
  report under `provider-health-stale-policy`.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/provider_settings.py` | Local provider settings, credential metadata, health tests, and readiness payloads. | Adds exact provider health proof schema, config hashing, strict proof validation, invalid/stale/missing/untested readiness codes, and stale-proof preservation. |
| `packages/builder-workspace/server/session_manager.py` | Builder prompt execution gate before PIL. | Propagates provider readiness code/action/guard in blocked prompt results. |
| `tools/provider_readiness_smoke.py` | Editor-free provider readiness policy proof. | Expands the readiness proof into an eight-case stale/missing/invalid/untested provider policy report. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Runs the provider readiness stale-policy gate and stores its JSON report in quick/full certification. |
| `docs/PROVIDER_HEALTH_STALE_POLICY.md` | Human-readable provider readiness policy. | Documents the provider health proof tuple, blocking codes, and proof command. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 54 as locally complete while keeping archived live BYOK reports and provider/runtime threshold execution as future proof. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md`, `docs/fake_skip_register.json` | Source inventory and fixture governance. | Classifies the provider health policy doc and keeps isolated certification-key evidence aligned with source line numbers. |

Verification:

- `python -m py_compile packages/builder-workspace/server/provider_settings.py packages/builder-workspace/server/session_manager.py tools/provider_readiness_smoke.py tools/certify_launch.py`
- `python tools/provider_readiness_smoke.py --settings-path target-codex-task54-focused-fast\provider_settings.json --output target-codex-task54-focused-fast\provider_health_stale_policy_report.json --json`
- `python tools/provider_timeout_retry_check.py --json`
- `python tools/provider_token_cost_accounting_check.py --json`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/source_inventory_check.py`
- `python tools/fake_skip_register_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/security_secret_scan.py --source`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task54-quick --report-path target-codex-certify-task54-quick\launch_certification_report.json`

## Eightieth Slice: Hosted Provider Proof Gate

Task 55 adds an opt-in BYOK proof gate for real hosted and local/self-hosted
provider checks. Normal certification runs the gate in no-network mode and
proves the redacted report contract. Live proof requires both `--live` and
`XACE_HOSTED_PROVIDER_PROOF_OPT_IN=1`; `--require-live` fails unless the selected
OpenAI-compatible, Anthropic, Google, and local/self-hosted routes actually run
health and prompt checks with exact model IDs.

What This Slice Proves:

- `tools/hosted_provider_proof_gate.py` writes
  `xace.hosted_provider_proof_report.v1` reports and refuses live calls unless
  the explicit opt-in environment variable is present.
- The gate supports OpenAI-compatible, Anthropic, Google, and local/self-hosted
  provider IDs with exact base URL, model, and BYOK environment inputs.
- Normal launch certification gets deterministic no-network evidence that the
  proof gate is wired and that generated reports contain no known keys or
  secret-shaped values.
- Live proof mode marks missing BYOK or model configuration as failed and keeps
  the user-visible failure code in the redacted report.
- Provider settings now pass exact Anthropic and Google base URLs into their
  inference clients so live provider checks use the configured endpoint.
- Quick/full launch certification and hosted governance CI run the no-network
  proof gate; release gates that claim hosted-provider reliability must archive
  live BYOK reports separately.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `tools/hosted_provider_proof_gate.py` | Opt-in hosted/local provider health and prompt proof gate. | Adds no-network certification mode, live opt-in/BYOK execution, provider-specific inputs, redacted report writing, and secret-shape self-checks. |
| `packages/builder-workspace/server/provider_settings.py` | Provider settings, health checks, and provider factory wiring. | Passes exact configured Anthropic and Google base URLs into the real inference providers. |
| `packages/inference/providers/google_provider.py` | Google provider HTTP client. | Accepts a configurable API base URL for exact endpoint proof. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the hosted provider proof gate in quick/full certification. |
| `.github/workflows/xace-scope.yml` | Hosted governance CI. | Runs the no-network hosted provider proof gate on pull requests and pushes to `main`. |
| `docs/HOSTED_PROVIDER_PROOF_GATE.md` | Human-readable Task 55 proof-gate contract. | Documents opt-in semantics, provider environment inputs, report schema, and redaction guarantees. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records the Task 55 gate as implemented locally while leaving archived live BYOK provider proof pending. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the hosted-provider proof-gate doc and checker. |

Verification:

- `python -m py_compile tools/hosted_provider_proof_gate.py tools/certify_launch.py packages/builder-workspace/server/provider_settings.py packages/inference/providers/google_provider.py`
- `python tools/hosted_provider_proof_gate.py --output target-codex-task55-focused\hosted_provider_proof_report.json --json`
- `python tools/security_secret_scan.py --path target-codex-task55-focused\hosted_provider_proof_report.json --json`
- `python tools/source_inventory_check.py`
- `python tools/fake_skip_register_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`

## Eighty-First Slice: Automatic Model Route Evidence Gate

Task 56 gates `ModelRouter` automatic provider/model choices on fresh benchmark
evidence for the exact provider, logical model, concrete model ID, and tier.
Missing route evidence blocks with `MODEL_ROUTE_EVIDENCE_MISSING`; expired
evidence blocks with `MODEL_ROUTE_EVIDENCE_STALE`; malformed or failed evidence
blocks with `MODEL_ROUTE_EVIDENCE_INVALID`. If a preferred route is missing or
stale but another healthy route has fresh evidence, the router can select the
benchmarked route and records the rejected route messages on the decision.

What This Slice Proves:

- `packages/inference/src/route_evidence.py` defines
  `xace.provider_route_evidence.v1` records and deterministic route IDs.
- `ModelRouter.route()`, `route_cheapest()`, and `route_best()` now require
  fresh benchmark evidence for automatic provider/model selection.
- Local routes validate the actual selected local model string rather than only
  the generic local descriptor.
- User-visible `MODEL_ROUTE_EVIDENCE_*` messages explain stale, missing, and
  invalid route evidence.
- `tools/provider_route_evidence_check.py` writes
  `xace.provider_route_evidence_report.v1` artifacts covering valid cloud
  routing, missing-evidence rejection, stale-evidence rejection, alternate
  benchmarked-route selection, and exact local-model routing.
- Quick/full launch certification and hosted governance CI run the route
  evidence gate.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/inference/src/route_evidence.py` | Automatic route benchmark-evidence policy. | Adds route evidence records, strict freshness validation, deterministic route IDs, and user-visible `MODEL_ROUTE_EVIDENCE_*` results. |
| `packages/inference/src/model_router.py` | Automatic provider/model routing. | Filters automatic route candidates through the evidence policy and rejects stale or unbenchmarked choices. |
| `packages/inference/tests/test_model_router.py`, `packages/inference/tests/test_hybrid_routing.py`, `packages/inference/__init__.py`, `packages/inference/tests/__init__.py` | Inference routing tests. | Adds route-evidence fixtures and focused missing/stale/valid automatic routing coverage. |
| `tools/provider_route_evidence_check.py` | Route-evidence governance validator. | Proves the route-evidence gate and writes the Task 56 report artifact. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles and runs the provider route-evidence gate in quick/full certification. |
| `.github/workflows/xace-scope.yml` | Hosted governance CI. | Runs the provider route-evidence gate. |
| `docs/PROVIDER_ROUTE_EVIDENCE_POLICY.md` | Human-readable Task 56 policy. | Documents evidence fields, blocking codes, and proof command. |
| `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Prompt/readiness/claims docs. | Records Task 56 as locally complete and keeps live hosted-provider/runtime thresholds pending. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the route-evidence policy doc and checker. |

Verification:

- `python -m py_compile packages/inference/src/route_evidence.py packages/inference/src/model_router.py packages/inference/tests/test_model_router.py packages/inference/tests/test_hybrid_routing.py tools/provider_route_evidence_check.py`
- `python tools/provider_route_evidence_check.py --output target-codex-task56-focused\provider_route_evidence_report.json --json`
- `pytest -c pyproject.toml packages/inference/tests/test_model_router.py packages/inference/tests/test_hybrid_routing.py`
- `python tools/source_inventory_check.py`
- `python tools/fake_skip_register_check.py`
- `python tools/forbidden_claims_check.py`
- `python tools/production_path_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/prompt_capability_matrix_check.py`

## Eighty-Second Slice: Provider BYOK UX States

Task 57 adds a deterministic Builder/provider UX state ABI on top of the
Task 54 health-proof readiness gate. Provider readiness, provider test results,
persisted health proofs, and pre-PIL blocked prompt responses now carry
`xace.provider_ux_state.v1` with a stable `state`, readiness `code`, label,
message, action, and severity. Builder consumes that object in the prompt box
and model/provider settings panel.

What This Slice Proves:

- No-key, invalid-key, stale-health-proof, quota-failure, rate-limit, and
  provider-outage states have deterministic server codes and Builder copy.
- Failed hosted health tests persist the failure state in `last_test`, so a
  later prompt block can explain the same state without rerunning a provider
  call.
- `SessionManager.run_pil()` includes `ux_state` in provider-readiness blocked
  results.
- `npm run test:ui` covers the prompt copy, provider-state publish path, and
  provider settings status row.
- Server tests cover all six required Task 57 states plus hosted failure
  classification.
- Quick/full launch certification now includes the Builder UI contract.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/provider_settings.py` | Local provider settings, health checks, readiness, and provider UX states. | Adds `xace.provider_ux_state.v1`, splits invalid key/quota/rate-limit/outage failures, persists failed health-test state, and returns UX state with readiness. |
| `packages/builder-workspace/server/session_manager.py` | Prompt execution guard and blocked response shaping. | Carries provider `ux_state` through pre-PIL blocked prompt responses. |
| `packages/builder-workspace/src/api/builder_client.ts` | Builder client state contracts. | Adds the shared `ProviderUxState` type and publishes it with prompt provider status. |
| `packages/builder-workspace/src/canvas/model_selector.ts` | Provider/model settings UI. | Renders the current provider state and publishes readiness UX state to the prompt box. |
| `packages/builder-workspace/src/canvas/prompt_input.ts` | Prompt input readiness guard. | Adds explicit no-key, invalid-key, stale-proof, quota, rate-limit, and outage messages before opening provider settings. |
| `packages/builder-workspace/server/tests/test_provider_ux_states.py` | Provider UX server tests. | Covers all six required Task 57 states and the hosted failure classifier. |
| `packages/builder-workspace/tools/builder_ui_contract_test.mjs` | Lightweight Builder UI contract test. | Covers provider UX-state copy and publish/render hooks. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds the Builder UI contract to quick/full certification. |
| `docs/PROVIDER_HEALTH_STALE_POLICY.md`, `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Provider/prompt readiness docs. | Records Task 57 as locally complete while keeping live hosted-provider reliability pending. |

Verification:

- `python -m py_compile packages/builder-workspace/server/provider_settings.py packages/builder-workspace/server/session_manager.py tools/certify_launch.py`
- `python -m unittest packages/builder-workspace/server/tests/test_provider_ux_states.py`
- `npm.cmd run test:ui` from `packages/builder-workspace`
- `npm.cmd run typecheck` from `packages/builder-workspace`

## Eighty-Third Slice: Deterministic No-LLM Simple Edits

Task 58 adds a narrow deterministic route for certified player-speed value
edits. Prompts like "Set the player movement speed to 6.5." now classify
locally, verify that the existing CGS target field is numeric, and emit the
same approval-gated GDE `SET` transaction used by the prompt apply path without
running provider readiness, PIL, an LLM, or hosted-provider execution.

What This Slice Proves:

- `SessionManager.run_pil()` checks the deterministic simple-edit planner before
  provider readiness and keeps all other prompts on the existing readiness/PIL
  path.
- The simple-edit result carries `xace.deterministic_simple_edit.v1`, zero
  token/cost metadata, and `provider=deterministic` / `model=gde-simple-edit-v1`.
- Prompt diff preview cost metadata records
  `deterministic_simple_edit_no_provider_call` so Builder does not present the
  zero-cost path as PIL/provider streaming evidence.
- Server tests prove the speed edit bypasses provider readiness and PIL while a
  structural certified prompt still calls the deterministic prompt contract
  pipeline.
- `tools/deterministic_simple_edit_benchmark.py` writes JSON, JSONL, Markdown,
  and provider-accounting artifacts and fails unless certified simple-edit cases
  record zero provider, provider-readiness, PIL, and LLM calls.
- Quick/full launch certification and governance CI run the deterministic
  simple-edit benchmark.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/session_manager.py` | Prompt execution, provider readiness, preview creation, and pending transaction state. | Adds the narrow pre-provider deterministic simple-edit planner and zero-cost preview source metadata. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Builder prompt contract E2E coverage. | Proves certified speed edits bypass provider readiness/PIL while structural certified prompts still use the prompt pipeline. |
| `tools/deterministic_simple_edit_benchmark.py` | Task 58 benchmark/proof tool. | Runs certified simple-edit prompts through `SessionManager.run_pil()` with sentinels and writes zero-call evidence artifacts. |
| `tools/prompt_classifier_gate_check.py` | Classifier gate validator. | Updates the certified speed prompt label so the classifier check does not imply Task 58 must enter PIL/provider execution. |
| `tools/prompt_pipeline_smoke.py` | Prompt contract/scenario smoke. | Clarifies that certified scenarios may start from either the deterministic simple-edit branch or the deterministic prompt contract pipeline before GDE apply. |
| `tools/provider_readiness_smoke.py` | Provider readiness/stale-policy smoke. | Moves provider-readiness blocking probes to a structural certified prompt so Task 58 simple edits can bypass provider readiness intentionally. |
| `tools/certify_launch.py`, `.github/workflows/xace-scope.yml` | Launch certification and governance CI. | Compile/run the deterministic simple-edit benchmark in quick/full/local and CI paths. |
| `docs/PROVIDER_HEALTH_STALE_POLICY.md`, `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | Provider/prompt/readiness/claims docs. | Records Task 58 as complete locally while keeping broad prompt generation and live provider/runtime thresholds scoped as pending. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new Task 58 benchmark helper. |

Verification:

- `python -m py_compile packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py tools/deterministic_simple_edit_benchmark.py tools/certify_launch.py`
- `python tools/deterministic_simple_edit_benchmark.py --output target-codex-task58-focused\deterministic-simple-edit-benchmark --json`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python tools/source_inventory_check.py`
- `python tools/prompt_capability_matrix_check.py`
- `python tools/provider_readiness_smoke.py --settings-path target-codex-task58-focused\provider-readiness\provider_settings.json --output target-codex-task58-focused\provider-readiness\provider_health_stale_policy_report.json --json`
- `python tools/forbidden_claims_check.py`
- `python tools/commercial_scope_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task58-quick --report-path target-codex-certify-task58-quick\launch_certification_report.json`

## Eighty-Fourth Slice: X10-011 Side-Channel Hash Policy

Task X10-011 turns side-channel hash authority into executable runtime policy.
`WorldHasher` now feeds `cgs_hash`, RNG snapshot state, pending event queue
state, pending mutation queue state, and clean-boundary status in addition to
tick/version/entity/component state. Feedback queues, pre-materialized network
input buffers, save metadata, and adapter playback side effects are explicitly
excluded only with replay-log, materialization, persisted-hash, or derived-output
proofs.

What This Slice Proves:

- RNG, event queue, mutation queue, and asset binding state are direct world-hash
  inputs.
- Network input packets are deterministic-log-authoritative before tick and
  world-hash-authoritative after runtime materializes them into the `INPUT`
  component.
- Feedback queues are transient but `FeedbackLog` payload divergence changes the
  feedback session hash.
- Save-state corruption changes the recomputed `WorldSnapshot` hash before live
  restore.
- Adapter playback command divergence is explicitly excluded as derived output,
  not hidden authoritative state.
- Launch certification now runs the focused side-channel policy tests.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/determinism_guard/world_hasher.rs` | Canonical world hash feed. | Adds `cgs_hash`, RNG state, event queue state, mutation queue state, and `is_clean` to SHA-256 input order plus divergence tests. |
| `packages/runtime-core/src/determinism_guard/side_channel_hash_policy.rs` | Executable X10-011 side-channel policy. | Defines required channels, dispositions, validation, and injected divergence tests. |
| `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs`, `packages/runtime-core/src/runtime_orchestrator.rs`, `packages/runtime-core/src/snapshot_engine/snapshot_engine.rs` | Runtime/snapshot hash call sites. | Recompute canonical hashes after attaching `cgs_hash` so live ticks, world snapshots, and restore validation use the same authority. |
| `docs/SIDE_CHANNEL_HASH_POLICY.md`, `docs/06_determinism_guarantees.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Determinism and X10 task docs. | Records X10-011 policy, tests, and remaining X10-012/X10-013 boundaries. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds `runtime side-channel hash policy` to full and quick certification. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new side-channel policy doc. |

Verification:

- `cargo test -p xace-runtime-core side_channel_hash_policy --lib`
- `cargo test -p xace-runtime-core world_hasher --lib`
- `cargo test -p xace-runtime-core --lib`

## X10-012 Snapshot Completeness Hardening

Status: Done on 2026-07-24.

Changes:

- Added an executable snapshot completeness policy covering entity records,
  component tables, archived entities, RNG stream positions, events, mutations,
  feedback, network sync buffers, save state, and adapter side effects.
- Runtime and snapshot restore now reject non-clean snapshots with pending
  events, pending mutations, or live RNG stream positions instead of silently
  restoring only partial side-channel state.
- `EntityStore::restore_from_snapshot` reconstructs permanent archived-ID
  reservations from archived entity records.
- `ComponentTableStore::restore_from_tables_snapshot` clears component rows
  absent from the snapshot while retaining registered empty tables.
- Snapshot capture now records component type names and omits empty tables so
  the hashed snapshot represents authoritative row state without schema-noise.
- Launch certification now runs the focused X10-012 snapshot-completeness tests.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/snapshot_engine/snapshot_completeness_policy.rs` | Executable X10-012 snapshot policy. | Defines required channels, inclusion/exclusion dispositions, restorable-snapshot validation, and policy tests. |
| `packages/runtime-core/src/snapshot_engine/snapshot_engine.rs` | WorldSnapshot capture and restore. | Enforces clean-boundary restore policy, captures component type names, omits empty tables, restores complete table snapshots, and rejects pending side channels. |
| `packages/runtime-core/src/component_tables/component_table_store.rs` | Component table ownership and restore. | Adds complete WorldSnapshot table restore that clears absent rows while preserving registrations. |
| `packages/runtime-core/src/entity_store/entity_store.rs` | Entity metadata and archive ownership. | Infers archived-ID reservations from archived entity records during restore. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Live runtime restore/replay boundary. | Validates X10-012 completeness before disconnecting engines or clearing transient buffers and adds rollback/replay hash proof. |
| `docs/SNAPSHOT_COMPLETENESS_POLICY.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Snapshot contract and X10 task docs. | Records include/exclude policy, restore behavior, and verification commands. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds `runtime snapshot completeness` to full and quick certification. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new snapshot completeness policy doc. |

Verification:

- `cargo test -p xace-runtime-core x10_012 --lib`
- `cargo test -p xace-runtime-core snapshot_engine --lib`
- `cargo test -p xace-runtime-core runtime_orchestrator --lib`

## X10-013 Full Snapshot Serialization

Status: Done on 2026-07-24.

Changes:

- Replaced the old `SnapshotSerializer::deserialize` minimal fallback with full
  `serde_json::from_str::<WorldSnapshot>` parsing and snapshot validation.
- `SnapshotSerializer::serialize` now writes the complete authoritative
  `WorldSnapshot` schema instead of the partial legacy projection.
- Serializer-level hashing clears `world_hash` before serializing so snapshots
  never hash their own stored digest.
- Added rich round-trip tests for tick, Fixed64 time, schema/plan versions,
  `cgs_hash`, entity records, component tables, archived records, RNG state,
  pending events, pending mutations, `world_hash`, and `is_clean`.
- Added a deterministic 32-case fuzz-style round-trip loop and an explicit
  legacy-minimal JSON rejection test.
- Launch certification now runs the focused snapshot serializer tests.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/snapshot_engine/snapshot_serializer.rs` | Full WorldSnapshot canonical JSON serialization. | Uses serde full-schema serialization/deserialization, rejects lossy legacy JSON, and adds X10-013 round-trip/fuzz tests. |
| `docs/SNAPSHOT_SERIALIZATION_CONTRACT.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Snapshot serialization contract and X10 task docs. | Records full-field requirements, enforcement, and verification evidence. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds `runtime snapshot serialization` to full and quick certification. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new snapshot serialization policy doc. |

Verification:

- `cargo test -p xace-runtime-core snapshot_serializer --lib`

## X10-014 Cross-Platform Replay Proof

Status: Implemented on 2026-07-24. The local machine can record its own
platform leg; the final release gate closes when the Windows/Linux/macOS CI
aggregate artifact is retained.

Changes:

- Added `tools/replay_cross_platform_proof.py` with `record`, `aggregate`, and
  `self-test` commands.
- The recorder runs the real CGS -> SGC -> runtime replay proof for one OS and
  writes `platform_report.json`.
- The aggregator requires Windows, Linux, and macOS reports and compares the
  canonical replay identity: CGS hash, compiled CGS hash, plan hash, generated
  systems, scheduled systems, pinned seed, input-log hash, schedule fingerprint,
  latest world hash, and per-tick hash log.
- `xace_runtime` now accepts `--world-seed` and includes `world_seed` in
  schedule snapshot reports, so proof runs do not rely on an implicit seed.
- `tools/sgc_runtime_proof.py` now records a canonical empty input log and
  per-tick hash log for cross-platform aggregation.
- `.github/workflows/xace-scope.yml` records platform reports on
  Windows/Linux/macOS and fails the aggregate job on any identity mismatch.
- Launch certification records the local OS replay leg.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime CLI and schedule report writer. | Adds `--world-seed` and emits `world_seed` in schedule snapshot reports. |
| `tools/sgc_runtime_proof.py` | Real CGS -> SGC -> runtime replay proof helper. | Records pinned seed, canonical input-log hash, full hash log, generated/scheduled system IDs, and schedule fingerprint. |
| `tools/replay_cross_platform_proof.py` | Cross-platform replay proof recorder and aggregator. | Writes per-platform reports and compares required Windows/Linux/macOS replay identities. |
| `.github/workflows/xace-scope.yml` | Hosted CI governance/proof workflow. | Adds the three-OS record matrix and aggregate proof job. |
| `docs/REPLAY_CROSS_PLATFORM_PROOF.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Replay proof contract and X10 task docs. | Defines the artifact schema, equality key, commands, CI behavior, and remaining global gate boundary. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Compiles the new proof tool and records the local OS replay leg in quick/full certification. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the replay proof contract and proof tool. |

Verification:

- `python -m py_compile tools/replay_cross_platform_proof.py tools/sgc_runtime_proof.py tools/cgs_end_to_end_proof.py`
- `python tools/replay_cross_platform_proof.py self-test --target-dir target-codex-replay-cross-platform-self-test --json`

## X10-015 Replay Divergence Diagnosis

Status: Implemented on 2026-07-24.

Changes:

- `RuntimeOrchestrator::tick` now records a compact per-tick
  `RuntimeTickReplayTrace` beside schedule snapshots.
- `RuntimeOrchestrator::validate_recorded_replay_from_cgs` attaches
  `RuntimeReplayDivergenceDiagnosis` to the first hash mismatch.
- Diagnosis reports include suspected SGC group, candidate systems, component
  changes, emitted events, RNG calls, mutation counts, input packets, expected
  trace, actual trace, and a readable summary.
- `RngInterceptor::accesses_for_tick` exposes deterministic RNG access records
  in stable system order for divergent tick reports.
- Launch certification runs the focused `runtime replay divergence diagnosis`
  gate.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime tick orchestration and replay validation. | Adds replay trace capture, first-mismatch diagnosis structures, input packet application traces, and injected-divergence tests. |
| `packages/runtime-core/src/determinism_guard/rng_interceptor.rs` | Deterministic RNG access audit. | Adds tick-addressed RNG access inspection plus focused coverage. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds the X10-015 focused runtime test to full and quick certification. |
| `docs/REPLAY_DIVERGENCE_DIAGNOSIS.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Replay diagnosis contract and X10 task docs. | Defines the report fields, runtime binding, and verification evidence. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the replay divergence diagnosis contract. |

Verification:

- `cargo test -p xace-runtime-core x10_015 --lib --target-dir target-codex-replay-diagnosis`

## X10-016 Crash-Safe Project Recovery

Status: Implemented on 2026-07-24.

Changes:

- `CGSPersistence.recover()` now validates persisted ExecutionPlan files,
  repairs interrupted plan writes from matching SGC proof bundles, removes
  incomplete proof bundles, and restores the latest snapshot that has a valid
  plan when the active structural CGS cannot run.
- Builder startup runs project recovery before accepting sessions and exposes
  the structured report in the WebSocket `session_init` payload.
- Project manifest and template writes now use temp-file, fsync, replace, and
  last-valid backup writes; manifest load repairs interrupted writes before
  parsing.
- `FileSaveEngine` now maintains last-valid backups, removes stale temp files,
  repairs invalid or missing save files, and restores session/metadata pairs to
  the last complete slot state after interrupted commits.
- Launch certification runs focused project/Builder and save recovery gates in
  quick and full modes.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/cgs_persistence.py` | Project CGS, snapshot, ExecutionPlan, and proof persistence. | Adds plan/proof validation recovery, stale-temp cleanup under plan/proof roots, valid-plan snapshot restore, and recovery report counters. |
| `packages/builder-workspace/server/builder_server.py` | Builder server startup and session handshake. | Runs recovery during app creation and sends the recovery report in `session_init`. |
| `packages/project-system/project_manifest.py`, `packages/project-system/project_creator.py` | Project manifest and starter project writes. | Adds last-valid backup recovery and routes project file creation through crash-safe writes. |
| `packages/save-engine/src/save_engine.rs`, `packages/save-engine/src/lib.rs` | Deterministic save/load engine. | Adds `SaveRecoveryReport`, backup-backed repair, stale-temp cleanup, slot consistency repair, and automatic recovery before reads/lists. |
| `packages/project-system/tests/test_project_system.py`, `packages/builder-workspace/server/tests/test_cgs_persistence_authority.py`, `packages/save-engine/tests/test_save_roundtrip.rs` | Corruption-injection coverage. | Proves manifest recovery, snapshot-index recovery, interrupted plan repair, valid-plan snapshot restore, corrupt-main runnable snapshot restore, corrupt save repair, and interrupted session/metadata commit repair. |
| `docs/CRASH_SAFE_PROJECT_RECOVERY.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Recovery contract and X10 task docs. | Defines the operational recovery scope, report fields, evidence, and verification commands. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds project crash recovery and save crash recovery gates to quick/full certification. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the recovery contract. |

Verification:

- `python -m unittest packages/project-system/tests/test_project_system.py packages/builder-workspace/server/tests/test_cgs_persistence_authority.py`
- `cargo test -p xace-save-engine x10_016 --target-dir target-codex-crash-recovery`
- `python -m py_compile packages/project-system/project_manifest.py packages/project-system/project_creator.py packages/builder-workspace/server/cgs_persistence.py packages/builder-workspace/server/builder_server.py tools/certify_launch.py`

## X10-017 MutationGate Single Apply Path

Status: Implemented on 2026-07-25.

Changes:

- `MutationGate::apply_all()` no longer hides the old direct-apply body behind
  `#[allow(unreachable_code)]`.
- `MutationGate::apply_all()` and
  `MutationGate::apply_all_with_runtime_state()` now both delegate to one
  private `apply_all_transaction()` implementation.
- The single implementation owns pre-batch rollback capture, ordered mutation
  application, queue restore, optional event/RNG restore, rollback hash
  verification, and `MutationApplyFailureDiagnostic` reporting.
- `tools/mutation_gate_apply_path_check.py` scans the Rust source shape and
  fails if unreachable apply code, disabled legacy bodies, queue-discard
  failure behavior, or multiple transaction implementations return.
- `docs/05_mutation_lifecycle.md` now documents the implemented runtime
  apply-time rollback contract and keeps later Phase 3 overclaim boundaries
  explicit.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/mutation_gate/mutation_gate.rs` | Runtime mutation gateway. | Removes the unreachable legacy apply body, adds the single private transaction implementation, and makes both public apply entrypoints delegate to it. |
| `packages/runtime-core/src/mutation_gate/tests/test_mutation_gate.rs` | MutationGate integration coverage. | Adds `x10_017_public_apply_uses_atomic_transaction_path` proving the public wrapper preserves rollback diagnostics and queue restore. |
| `tools/mutation_gate_apply_path_check.py` | MutationGate apply-path governance. | Scans for one transaction implementation, delegated public wrappers, no unreachable-code allowance, no disabled old body, and no apply-time queue discard path. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds `mutation gate apply path` and `mutation gate atomic wrapper` to quick/full certification. |
| `docs/05_mutation_lifecycle.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Mutation lifecycle and X10 task docs. | Records Task 17 completion, implemented runtime contract, verification evidence, and remaining Phase 3 boundaries. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new MutationGate apply-path scanner as production governance tooling. |

Verification:

- `cargo test -p xace-runtime-core x10_017 --lib --target-dir target-codex-task17-runtime`
- `cargo test -p xace-runtime-core mutation_gate --lib --target-dir target-codex-task17-runtime`
- `python tools/mutation_gate_apply_path_check.py --json`

## X10-018 Static Mutation Conflict Analysis

Status: Implemented on 2026-07-25.

Changes:

- GDE consistency validation now runs static conflict analysis before accepting a
  proposed CGS mutation.
- The analyzer blocks dependency cycles, unknown/self/later-phase dependencies,
  same-phase read/write and write/write hazards without an ordering path,
  undeclared component access, incompatible component removals/renames/field
  migrations, and generated/plugin/external runtime executor ABI mismatches.
- Builder direct asset-link persistence now runs the same pre-commit analyzer
  before writing the new CGS and returns `STATIC_MUTATION_CONFLICT` on rejection.
- `tools/mutation_conflict_analysis_check.py` provides the adversarial corpus
  gate for dependency cycles, state access hazards, component migration
  incompatibility, generated-system ABI mismatch, GDE precommit rejection, and
  Builder pre-persist rejection.
- Launch certification runs the static mutation conflict analysis gate in quick
  and full modes.
- Quick-certification test-only fixtures now match strict CGS schema loading and
  fixed-point generated counter encoding, keeping the launch gate green after
  the new task 18 check was added.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/gde/src/consistency_validator/static_mutation_conflict_analyzer.py` | Static CGS mutation verifier. | Adds deterministic pre-commit conflict analysis for graph dependencies, state access, component migrations, and generated executor ABI contracts. |
| `packages/gde/src/consistency_validator/consistency_validator.py` | GDE consistency gate. | Runs static mutation conflict analysis before accepting CGS-only or transaction-backed validation results. |
| `packages/gde/src/tests/test_consistency_validator.py`, `packages/gde/src/tests/test_gde_orchestrator.py` | GDE validation and commit coverage. | Proves adversarial mutations fail and GDE leaves the authoritative hash unchanged on rejection. |
| `packages/builder-workspace/server/ws_message_router.py` | Builder WebSocket mutation persistence. | Adds a pre-persist conflict helper for direct CGS writes and rejects invalid proposed CGS writes before `CGSPersistence.save()`. |
| `packages/builder-workspace/server/tests/test_engine_edit_router.py` | Builder router coverage. | Proves Builder rejects a static graph hazard before persistence. |
| `tools/mutation_conflict_analysis_check.py` | Task X10-018 governance gate. | Runs adversarial static conflict cases plus GDE and Builder precommit checks. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds `static mutation conflict analysis` to quick/full certification and module compilation. |
| `tools/asset_playback_smoke.py`, `tools/runtime_bridge_smoke.py`, `tools/runtime_sgc_plan_loader_smoke.py`, `tools/generated_system_safe_compile_smoke.py` | Editor-free smoke fixtures. | Updates test-only CGS launch paths and fixture fields so strict runtime schema validation can run the intended smoke behavior. |
| `tools/cgs_end_to_end_proof.py` | End-to-end CGS proof. | Interprets generated counter values through the fixed-point raw-unit encoding while preserving raw proof evidence. |
| `docs/05_mutation_lifecycle.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Mutation lifecycle, claims, and task docs. | Records implemented static conflict scope while keeping the remaining X10-020 through X10-023 boundaries explicit. |
| `docs/source_inventory.json`, `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md` | Source inventory governance. | Classifies the new static conflict analysis gate. |

Verification:

- `python tools/mutation_conflict_analysis_check.py --json`
- `python -m unittest packages.builder-workspace.server.tests.test_session_manager_authority packages.builder-workspace.server.tests.test_engine_edit_router`
- `python -m py_compile packages/gde/src/consistency_validator/static_mutation_conflict_analyzer.py packages/gde/src/consistency_validator/consistency_validator.py packages/builder-workspace/server/ws_message_router.py tools/mutation_conflict_analysis_check.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task18-quick --report-path target-codex-certify-task18-quick\launch_certification_report.json`

## X10-019: Prompt Apply Atomic Transaction

Status: Task X10-019 makes the Builder prompt apply path atomic across the
covered prompt, GDE, SGC, persistence, runtime validation, adapter validation,
and UI-completion layers. After GDE accepts a mutation, any later failure now
enters the same recovery path, restores the captured pre-apply state, and emits
a structured rollback report instead of leaving a partially advanced layer.

What This Slice Proves:

- SGC compile failures and unsupported/skipped SGC structural applies restore
  the pre-apply CGS, GDE current hash, pending prompt/UI state, and audit hash.
- CGS save, snapshot, execution-plan, and SGC proof persistence failures restore
  `game.cgs.json`, in-memory CGS, snapshot index, failed-hash artifacts, GDE
  state, pending prompt/UI state, and adapter-visible session edit log.
- Runtime reload, replay validation, and adapter validation failures restore
  cached runtime status and send a runtime-control reload for the pre-apply
  version IDs when a runtime was connected.
- No covered failure path emits `cgs_update`; all recovered failures audit as
  `rejected_recovered` with `rollback_status=restored_pre_apply`.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/builder-workspace/server/ws_message_router.py` | Builder WebSocket prompt apply route. | Routes SGC compile/skip, CGS save, snapshot, plan, proof, runtime, replay, and adapter failures through one recovery helper; captures/restores pending prompt state, GDE state, runtime state, UI status, and adapter-visible session edit log. |
| `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py` | Prompt route integration tests. | Adds/extends failure-injection coverage for SGC failure, SGC unconfigured, CGS save failure, snapshot, proof, runtime, replay, adapter, and provider rollback paths with GDE/UI/adapter restore assertions. |
| `tools/prompt_apply_recovery_check.py` | Governance validator. | Upgrades the recovery gate to validate the X10-019 atomic rollback matrix and static restore/report hooks. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Runs the prompt apply atomic recovery gate in quick/full certification. |
| `docs/05_mutation_lifecycle.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Mutation lifecycle, claims, readiness, and task docs. | Records the covered prompt-apply atomicity scope while keeping live hot-swap, runtime migrations, and engine-side side-effect rollback as X10-020 through X10-023. |

Verification:

- `python -m py_compile packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py tools/prompt_apply_recovery_check.py tools/certify_launch.py`
- `python tools/prompt_apply_recovery_check.py --json`
- `python tools/prompt_apply_validation_feedback_check.py --json`
- `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task19-quick --report-path target-codex-certify-task19-quick\launch_certification_report.json`

## X10-020: State-Preserving Runtime Schema Hot-Swap

Status: Task X10-020 makes runtime `reload_cgs` a real hot-swap operation for
compatible/additive CGS and SGC schedule changes. The runtime validates the
requested disk CGS hash, schema version, and execution-plan version, compiles
the incoming runtime view through scratch stores, and swaps the active registry,
schedule identity, phase plan, and guard locks at the current clean tick
boundary without rebuilding live entity/component state.

What This Slice Proves:

- Accepted hot-swaps preserve the live tick counter, entity IDs, component rows,
  engine bridge state, pending engine inputs, and existing deterministic hash
  log.
- The incoming CGS and persisted SGC plan are loaded into scratch
  `EntityStore`/`ComponentTableStore` instances before any live metadata swap.
- Component table changes are additive-only in this slice: existing type IDs
  must keep their registered names, and new tables are registered empty without
  default-row backfill.
- New systems from the swapped schedule execute on the expected next live tick.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime session authority. | Adds `RuntimeHotSwapReport`, scratch-load validation, additive table merge, registry/schedule/guard swap, and the X10-020 state-preservation test. |
| `packages/runtime-core/src/determinism_guard/determinism_guard.rs` | Determinism lock and hash log authority. | Adds `reconfigure_for_hot_swap()` so schema/plan/system locks can advance while preserving prior tick hashes. |
| `packages/runtime-core/src/bin/xace_runtime.rs` | Runtime lifecycle control path. | Splits `reset` from `reload_cgs`; reload now hot-swaps without disconnecting adapters or resetting to tick 0, and validates requested version IDs against disk artifacts. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds `runtime schema hot-swap` to quick/full certification. |
| `docs/05_mutation_lifecycle.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Mutation lifecycle, claims, readiness, and task docs. | Records the implemented state-preserving hot-swap scope while keeping follow-on compatibility classification, migrations, and engine side-effect rollback boundaries explicit. |

Verification:

- `cargo test -p xace-runtime-core x10_020 --lib --target-dir target-codex-task20-runtime`
- `cargo test -p xace-runtime-core --target-dir target-codex-task20-runtime`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task20-quick --report-path target-codex-certify-task20-quick\launch_certification_report.json`

## X10-021: Hot-Swap Compatibility Classes

Status: Task X10-021 makes runtime hot-swap eligibility explicit and enforced.
Every candidate CGS/SGC swap is classified before live mutation as `additive`,
`migratable`, `state_transforming`, or `reset_required`; only candidates whose
issues are all additive can proceed through `hot_swap_cgs_at_tick_boundary()`.

What This Slice Proves:

- Empty new component tables and newly scheduled systems are classified as
  additive and may hot-swap live.
- Actor component additions that need default-row backfill are classified as
  migratable and refused until deterministic migration hooks exist.
- Existing system executor, access, dependency, phase, or relative-order changes
  are classified as state-transforming and refused before live state mutation.
- Actor topology, mode changes, and component table removals are classified as
  reset-required and refused with explicit reset-required diagnostics.
- Refused candidates leave the runtime at the old live tick and old CGS hash.

Files touched:

| File | Single Responsibility | Slice Change |
| --- | --- | --- |
| `packages/runtime-core/src/runtime_orchestrator.rs` | Runtime session authority. | Adds compatibility class/report/issue types, public classify-before-swap API, shared scratch candidate loading, additive-only enforcement, stable refusal diagnostics, and X10-021 tests for additive/migratable/state-transforming/reset-required cases. |
| `tools/certify_launch.py` | Launch certification orchestrator. | Adds `runtime hot-swap compatibility classes` to quick/full certification. |
| `docs/05_mutation_lifecycle.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/LAUNCH_READINESS_MAP.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` | Mutation lifecycle, claims, readiness, and task docs. | Records implemented compatibility classification/enforcement while keeping deterministic migrations and engine side-effect rollback as X10-022 through X10-023 work. |

Verification:

- `cargo test -p xace-runtime-core x10_021 --lib --target-dir target-codex-task21-runtime`
- `cargo test -p xace-runtime-core --target-dir target-codex-task21-runtime`
- `python tools/certify_launch.py --quick --target-dir target-codex-certify-task21-quick --report-path target-codex-certify-task21-quick\launch_certification_report.json`

## Current Risks To Watch

- Prompt and asset hardening prove the supported categories listed above. Prompt mutations now require structured preview approval before persistence, covered rollback recovery for the covered scenarios, crash-safe project/save recovery for the covered corruption scenarios, structured apply feedback in Builder, a reviewed/versioned corpus source fixture, local classifier-only benchmark reports with provider accounting artifacts, local classifier threshold gates, covered prompt-security attack artifacts, inference-adapter provider-call boundary enforcement, provider timeout/retry telemetry proof, provider token/cost accounting proof, provider health/stale-policy proof, an opt-in hosted-provider proof gate, automatic route-evidence gating, provider UX-state coverage, deterministic zero-provider-call proof for certified player-speed value edits, state-preserving runtime hot-swap for compatible/additive schedule changes, and hot-swap compatibility classification/enforcement, but they do not yet prove arbitrary any-game prompts, automatic full art/audio/animation generation, deterministic runtime state migrations, engine-side side-effect rollback, hosted-provider reliability at corpus scale, hosted provider/compile/runtime/rollback benchmark threshold pass, broader security review, or every old/new feature combination.
- `workspace/builder` is archived; keep all active Builder work in `packages/builder-workspace`.
- `packages/asset-registry` is the canonical asset registry path.
- Full installed-editor live validation and launch certification are now green for Godot, Unity, and Unreal on this machine. One-click local Builder launch is also in place; the remaining engine-readiness risk is the final visual playthrough/onboarding pass, not engine protocol proof.
- Build artifacts and generated target directories are present in the worktree; do not use them as source of truth.
- Older roadmap docs are phase/scaffold oriented; this map is product-readiness oriented.

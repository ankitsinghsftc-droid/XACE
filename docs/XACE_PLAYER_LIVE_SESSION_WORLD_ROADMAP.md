# XACE Player, Live Sessions, and World Contract


Pre-XP-007 architecture gate (2026-09-28): **SAFE TO START XP-007**.
The owner-requested audit found closed world/profile and actor/arena authoring
assumptions despite package-local mechanic rules. See
`docs/XP007_PREFLIGHT_ARCHITECTURE_AUDIT.md`. The completion checkpoint below is
historical profile evidence; it is not a universal extensibility certification.
The correction is implemented and verified; see `docs/WORLD_EXTENSIBILITY_COMPLETION.md`.
XP-007 is complete for its Windows native headless package profile; see `docs/XP007_COMPLETION.md`.

Implementation checkpoint (2026-10-03): XP-001 through XP-009 are complete for their
declared profiles. XP-010 implementation and same-host verification are finished;
clean-machine acceptance remains pending by owner instruction. See
`docs/XP010_COMPLETION.md`. XP-011 is implemented and locally verified; see
`docs/XP011_COMPLETION.md` and `docs/evidence/xp011-baseline.json`. XP-012
is implemented and locally verified for two independently controlled players;
see `docs/XP012_COMPLETION.md` and `docs/evidence/xp012-baseline.json`.
XP-013 is implemented and locally verified for full-baseline synchronization, late
join, reconnect and recovery; see `docs/XP013_COMPLETION.md` and
`docs/evidence/xp013-baseline.json`. XP-014 is implemented and same-host verified for Play/Invite/Join; two-machine
acceptance remains pending by owner instruction. See `docs/XP014_COMPLETION.md`
and `docs/evidence/xp014-baseline.json`. XP-015 is implemented and locally verified with an actual TLS relay; public
deployment and two-network acceptance remain pending by owner instruction. See
`docs/XP015_COMPLETION.md` and `docs/evidence/xp015-baseline.json`. XP-016 is
implemented with installed Unity/Godot/Unreal contract proofs and exported Player
evidence; Unity passed after license activation and proof scene setup correction. The older standalone
missing-cosmetic startup regression is retained as an open limitation. See
`docs/XP016_COMPLETION.md` and `docs/evidence/xp016-baseline.json`. XP-017 is
locally certified with actual Player+Godot, Unity+Godot+Unreal and all-four sessions,
applied client digests, owned inputs, shared events, refusal and disconnect proofs.
See `docs/XP017_COMPLETION.md` and `docs/evidence/xp017-baseline.json`.
XP-018 through XP-022 have not started. XP-002 legacy schema/input-plan
migration requirements still apply. No remote live cross-engine
or clean-machine certification is implied; original audit text remains historical.

## Binding amendment: extensible semantic worlds (2026-09-28)

World Contract v3 separates project semantics from executable geometry profiles.
A project declares versioned schemas for its own nouns and typed properties,
capabilities, role-keyed relationships/assets, and actor-instance bindings. Multiple
semantic objects may describe one instance. Core does not enumerate game concepts.
New semantic definitions require package validation and a new content identity, not
a new XACE release. A new solver or importer still requires an implementation and
host support; declaring a name is not an implementation of behavior.

The AABB backend remains one optional required geometry profile. Its rotation,
scale, size and query limits apply to its members, not to all world objects. Every
later task must preserve the schemas and reject unsupported required execution
profiles. Do not flatten unknown semantic objects into boxes, discard extensions,
resolve gameplay from native physics, or add per-noun adapter dispatch.

- XP-007: package and verify the entire schema-bearing world, profile requirements,
  typed semantic asset bindings and executor contracts. Exercise both legacy and v3
  packages. Import executes no project code; host admission checks actual support.
- XP-008/009: render through declared presentation bindings and supported profiles.
  Generic gameplay input/events are the product; wall-running and its VFX are proofs.
- XP-011 through XP-017: negotiate explicit world/session versions and bind all
  semantics/profile identities to admission and baselines. Host presentation varies;
  authoritative schemas and data do not. Unsupported required profiles fail closed.
- XP-018/019: mutations may change project schemas, relationships, capabilities,
  package systems or state under the same validated staging/migration transaction.
  No third-jump-specific staging or activation path is permitted.
- XP-020/021: record exact schema/profile/package artifacts for each epoch; display
  generic object IDs, typed data, dependencies and events. No fixture-specific parser.
- XP-022: retain data-only arbitrary-noun/compound-instance fixtures alongside the
  existing gameplay proof. No additional game or physics backend is required.

Legacy v2 artifacts retain their interpretation. Migration is an explicit detached
source operation followed by full compilation and new hashes, never a reader guess.

## Binding amendment: mechanic-agnostic platform and reference proof

Owner-directed amendment, 2026-09-24. This boundary governs all XP tasks and
supersedes mechanic-specific interpretations of the historical audit below.
XACE is a general gameplay platform. Wall-running, wall-jumping and third-attempt
shockwave/reversal are a removable **reference proof fixture only**.

Core World Contract, geometry, CGS, SGC, networking, mutation and replay may reason
about entities, components, systems, state, inputs, events, capabilities/tags,
contacts, queries, dependencies, transforms, collision/query geometry and semantic
world objects. They must not require knowledge of wall-running, grappling, combat,
zombies, swimming, parkour or any other particular mechanic.

- Implement the reference through ordinary versioned gameplay-system, package and
  catalog mechanisms, with normal declared reads/writes, dependencies and MutationGate.
  Its configuration, counters, transitions and event effects belong to that package.
- No `wall_run`-specific branch in authoritative execution infrastructure, the World
  Contract compiler/reader, session/network stack or engine adapters. Adapters consume
  generic state and semantic presentation events, never fixture gameplay rules.
- `wall_runnable` is an ordinary namespaced semantic capability owned/declared by
  the fixture. The existing spelling `world.wall_runnable.v1` confers no core privilege;
  any namespace migration must be explicit and versioned. Other packages can declare
  arbitrary valid namespaced semantic capabilities through the same mechanism.
- Separate platform/protocol support requirements from gameplay semantic declarations.
  Core validates identifiers, declarations, references, versions and dependencies;
  package/catalog declarations supply gameplay meaning and compatible target roles.
  Preserve fail-closed validation for malformed, undeclared or unsatisfied requirements
  without hardcoding a closed list of gameplay names in core or host admission.
- Removing/replacing the reference package must require no changes to core architecture,
  geometry APIs, scheduling, wire protocols, adapters, mutation, replay or debugger.
  Inspect ordinary registration/removal and generic capability data handling to verify
  this boundary; do not implement another mechanic, marketplace or plugin framework.

**PRODUCT CAPABILITY:** XACE can stage and activate a validated gameplay-system
ruleset mutation at authoritative tick N.

**REFERENCE PROOF:** In the golden fixture, the third wall-jump attempt changes
from disabled to reversal + shockwave at tick N. This proves the product capability;
it does not define its API, acceptance contract or supported gameplay vocabulary.

### XP-003 / XP-004 review and prerequisite correction

Resolution (2026-09-25): XP-005 implements this correction with World Contract v2,
package-owned semantic declarations, generic role constraints and artifact-bound
admission. The reference package passes its proof without privileged core branches.
See the XP-005 report above. The following review records the gap as discovered;
its prerequisite is now satisfied. XP-006 is complete for the registered-host authoring profile.

The earlier completion reports remain source-bound historical evidence. Their
"ready for XP-005" recommendation is conditional on this newly required boundary:

- **XP-003 has a concrete gap.** `packages/schema-factory/src/world_contract.py`
  has a closed capability set, a `world.wall_runnable.v1` solid-box check and
  mechanic-bearing role lists. `packages/core/src/world/mod.rs` repeats the closed
  vocabulary and wall-runnable role checks. The shared
  `packages/core/src/wire/session_contract.rs::KNOWN_CAPABILITIES` also reserves
  that gameplay name and rejects arbitrary package semantic requirements. These
  restrictions do not yet satisfy the amendment; documentation cannot certify them away.
- **Required before XP-005 implementation:** correct the existing capability path
  in Python compilation, Rust reading and session compatibility to use generic
  namespaced package/catalog declarations and declared constraints. Keep generic
  geometry/role validation, deterministic serialization, hashes, versioning and
  explicit rejection of unsupported platform requirements. Remove mechanic-name
  branches; express any fixture solid-surface dependency as fixture-owned data.
  Update affected golden/malformed vectors and provenance deliberately. Verify
  arbitrary declared semantic IDs, rejected undeclared/invalid requirements,
  Python/Rust parity and generic admission without implementing another mechanic.
  This is a correction to XP-003's shared capability contract (including the
  XP-001 compatibility dependency), not a new task or expanded mechanics scope.
- **XP-004 passes the mechanic-boundary review:** `packages/core/src/geometry.rs`
  and `packages/runtime-core/src/geometry.rs` expose bounded boxes, sweeps, overlaps,
  axis probes, normals, filters, IDs and squared-distance targeting. They contain
  no wall-run, jump-counter or shockwave rules. A ground/side probe is a geometric
  query, and a radius query has no intrinsic shockwave meaning. Its identity-binding
  API reuses WorldContract validation, so its usable semantic vocabulary inherits
  the XP-003 gap until that correction lands; no special geometry API is needed.

- Amendment review: queries remain generic geometric operations; no traversal or shockwave semantics belong here. World identity bindings inherit the XP-003 capability-validator correction, without requiring a new mechanic-specific query API.
- Amendment gate: remove the closed gameplay vocabulary and mechanic-specific role checks identified above before XP-005. Semantic capability declarations/constraints are package data; core retains generic schema/geometry/provenance validation. Historical tests do not certify the amended capability boundary.
At amendment time this changed planning/documentation only; XP-005 was unstarted.
The subsequent resolution and current implementation status are recorded above.

Original design-audit status (before approval): proposed architecture; implementation had not started.
Audit date: 2026-09-23. Checkout HEAD: `aaa15fc22207aa188009f9f29006032a2db62c47`, plus the existing working tree. The checkout contains substantial pre-existing uncommitted work. This review treats that working tree, executable tests, and available proof artifacts as authority. It does not certify a clean release or supersede accepted product scope.

## 1. Executive verdict

Yes. These three additions fit XACE cleanly if they extend the existing Rust authority and network contracts. They should form one program, with one authoritative runtime per live session and multiple presentation/input clients.

Recommend an exported, Godot-backed XACE Player; a session coordinator that composes `network-core` with the actual runtime bridge; and a CGS-owned World Contract compiled into a small fixed-point gameplay geometry representation. Begin with boxes, kinematic characters, triggers, spawn points, and interaction anchors. Preserve richer native visual content outside the authoritative collision model.

This is more than packaging existing capabilities. Several strong library implementations are not connected to the shipped bridge. The principal engineering work is closing authority boundaries, connecting session admission and ownership to real sockets, introducing gameplay contact queries, staging atomic ruleset transitions, and replaying recorded inputs across those transitions.

The flagship must prove **one session, independently controlled players, shared authoritative ticks, and a real gameplay transition**. Existing cross-engine core-hash comparison does not establish that result.

## 2. What already exists: repository evidence

### Runtime, schema, compilation, and mutation

- **Already implemented:** strict persisted-plan loading and per-tick schedule identity validation. `packages/runtime-core/src/cgs_loader.rs` defines `RuntimeSchedulePlan` and `RuntimeScheduleIdentity`; `RuntimeConfig::default()` in `runtime_orchestrator.rs` requires a persisted SGC plan and strict determinism guard. `tick()` validates the schedule before running phases. Reuse these gates.
- **Already implemented:** fixed-point authority primitives. `packages/core/src/fixed_point.rs` provides `Fixed64` using integer micro-units. `phase_orchestrator/`, `mutation_gate/`, `determinism_guard/`, and `event_bus/` provide the authoritative execution machinery. This is not a reason to create another simulator inside Player.
- **Already implemented:** CGS serialization, GDE transactions, typed operations, static checks, and approved Builder apply paths. Relevant sources are `packages/gde/src/cgs/`, `gde_orchestrator.py`, `domain_dsl/typed_operations/typed_operation_executor.py`, and Builder `session_manager.py`, `cgs_persistence.py`, `ws_message_router.py`, and `state_authority.py`. Agent ingress remains proposal-only in `agent_host/proposal_ingress.py`.
- **Already implemented, with an integration mismatch:** `packages/schema-factory/src/schema_factory.py` compiles registries, blueprints, mode composition, and validation into `CompiledSchemaPackage`. However, Builder `SessionManager.compile_sgc_plan()` currently calls `_extract_systems_for_sgc(cgs)` and submits a direct CGS-derived systems envelope to SGC. The World Contract must not perpetuate this bypass: introduce one validated Schema Factory projection used by Builder, package creation, and SGC ingress.
- **Already implemented:** actual Rust SGC pipeline, plan hashes, access/dependency metadata, CLI and runtime compatibility tests in `packages/system-graph-compiler/`. Reuse the compiler and persisted-plan contract.
- **Partially implemented / reusable:** generated executor infrastructure in `runtime-core/src/generated_system_abi.rs` and PIL `code_generation/`. The runtime supports bounded operations such as increment, set, copy, and RNG-conditioned events; the inspected typed generated-system authoring path is narrower still, centered on a verified numeric increment behavior. This is not an existing arbitrary wall-running compiler. Ship a reviewed mechanic primitive through the existing catalog and typed pipeline; do not fake general code-generation capability.

### Hot-swap, migration, snapshots, replay, and debugger

- **Already implemented:** `RuntimeOrchestrator::hot_swap_cgs_at_tick_boundary()` loads a candidate, classifies compatibility, checks a clean boundary, preserves entity IDs and component rows, applies supported migration hooks, and replaces the plan/registry. It records old/new identities and applied tick. Existing hooks include component backfill from candidate defaults. Runtime control `reload_cgs` invokes this path.
- **Needs extension:** this is immediate local boundary activation, not a staged multi-client transaction at a negotiated future tick. No inspected production session path implements prepare/readiness/commit, a durable activation decision, or epoch fencing. Hot-swap also resets `feedback_log` and `replay_golden_log`. Merely retaining some old tick hashes does not preserve a replayable ruleset history.
- **Already implemented:** complete snapshot serialization/restore validation, retained rollback snapshots, corrected-input resimulation, delta-compressed timeline retention, and prediction/reconciliation APIs in `runtime_orchestrator.rs`, `snapshot_engine/`, and `network-core/src/prediction/`.
- **Needs extension:** `validate_recorded_replay_from_cgs()` initializes a fresh runtime and ticks it; the inspected path does not feed the original live input/feedback stream or activate historical rulesets. It cannot certify the proposed interactive, multi-ruleset session replay.
- **Partially implemented / reusable:** `builder-workspace/src/preview/tick_debugger.ts`, `conditional_breakpoints.ts`, `causality_graph.ts`, and `rng_seed_trace.ts`. These already provide useful timeline/navigation and diagnostic surfaces. UI history navigation is distinct from restoring an authoritative live multiplayer world. The runtime control enum has no general timeline-restore/session-epoch action. Extend the existing debugger with recorded-session inspection; do not replace it.
- **Partially implemented / reusable:** `packages/save-engine/` has Rust checkpoint/save code and Python save envelopes/migration. X10-068/069 save authority and migration hardening remain unchecked. Do not make durable campaign/world saving a hidden prerequisite for a session checkpoint or claim it complete.

### Networking and actual bridge behavior

- **Already implemented as library contracts:** `network-core/src/session/session_manager.rs` includes lobby, ready, join, leave, reconnect, late join, teardown, player identity, and lifecycle records. `session_compatibility.rs` compares schema, plan, adapter, assets, package set, metadata and template. `late_join_handler.rs` plans snapshot/catch-up batches. `input/`, `authority/`, `replication/`, and `synchronisation/` provide input timing, ownership, malicious-input guards, interest filtering, and resync building blocks.
- **Needs extension:** the shipped `runtime-core/src/bin/xace_runtime.rs` uses `RuntimeOrchestrator` and engine bridges; its CLI does not select a network session/required-peer profile. Default runtime input mode is direct. The inspected production orchestrator does not compose the Rust `SessionManager`, `SessionCompatibilityProfile`, `MaliciousInputGate`, or `AuthorityResolver` into bridge admission/input processing. These exist in tests and network harnesses, which is a weaker claim than real client integration.
- **Already implemented:** multiple local engine connections, including a live accept option, in `tcp_server.rs`, `engine_bridge.rs`, and `xace_runtime.rs`. This is a valuable transport foothold.
- **Needs extension:** actual bridge listener helpers bind loopback. `engine_protocol.rs` handshake checks protocol and optionally non-empty CGS hash; it does not carry full package/world/plan admission identity. Session IDs currently derive from process ID. `TickSnapshot` lacks ruleset epoch, world/plan identity, and authoritative hash. The handshake gives initial entities without a proper current-tick baseline; Godot currently interprets that acknowledgement as tick zero.
- **Needs extension:** there are two related protocol families: the standalone length-prefixed JSON engine bridge and `engine-adapter/src/transport/protocol_handshake.rs` / `core/src/wire/`. The latter already has world/schema/plan concepts and delta sequencing. Define a versioned extension of the actually used bridge with shared identity contracts and conformance fixtures. Do not introduce an unrelated third transport model or blindly replace working native adapters.
- **Missing:** user-facing invite credentials, authenticated remote admission, package acquisition/readiness, session-owned process lifecycle, and an end-to-end Play/Invite/Join flow.
- **Conflicts with the intended boundary:** `apply_pending_engine_inputs_from()` directly adds/updates input components after checking player existence; the live bridge is not bound to authenticated player ownership. `set_preview_component_field()` updates runtime component tables, and the CLI control path invokes it. Close these paths for sessions: input state flows through a scheduled Input phase and MutationGate, and preview edits use isolated preview state.

### Player, engine adapters, assets, and packages

- **Partially implemented / reusable:** `adapters/godot/` already contains a runnable `project.godot`, main scene, TCP transport, protocol parser, snapshot/delta entity mirror, normalized input collector, camera, HUD, audio/animation/VFX hooks, fallback bindings, and side-effect rollback handling.
- **Needs extension:** the Godot main scene constructs a fixed floor/camera arena and assigns player ID 1. It is a smoke/development host, not a generic package-driven Player with server-assigned ownership and canonical world rendering. `tools/xace_godot_dev.py` launches source projects and development services. `tools/xace_builder_launch.py` is a local launcher, not a finished Player distribution.
- **Partially implemented / reusable:** native Unity C# and Unreal C++ adapter implementations, reversible installation, reference-only native-project inventory, and manual migration planning. Reuse `project-system/adapter_installation.py`, `engine_project_inventory.py`, and `engine_migration_wizard.py`; native projects remain engine-owned.
- **Already implemented:** typed `AssetReference`, manifest validation/preflight, semantic events, semantic playback bindings, per-engine binding status, and deterministic fallback metadata. Sources include `core/src/assets/semantic_binding.rs`, `core/src/events/semantic_event_registry.rs`, `asset-registry/semantic_binding_status.py`, and `asset_reference_preflight.py`.
- **Partially implemented / reusable:** `project-system/project_manifest.py` defines a creator project manifest; `adapter_package_versioning.py` provides version/checksum/dependency/lifecycle manifests and `adapter_package_handoff_preflight.py` composes validation. An adapter handoff package and the in-memory `CompiledSchemaPackage` are neither a playable release archive. A native playable package contract is missing.

### World and physics

- **Partially implemented / reusable:** UCL transform/identity/collider components; DCL surface, trigger, interaction and kinematic-character definitions; the composite registry; and `dcl/gameplay_primitives.py` with schema/system/event/input/asset/save/network facets.
- **Missing:** a versioned portable world compilation contract with stable world-object bindings, authoritative geometry/query results, declared semantic surface capabilities, host conformance, and a world content digest.
- **Existing world configuration is not geometry:** `core/src/schema/world_definition.rs` explicitly covers the space/environment rules, excluding terrain layout. Actor definitions and components are the appropriate source for world objects; compile their geometry rather than adding a second editable scene database.
- **Existing movement is not collision:** `builtin_systems.rs` implements jump buffering, coyote time, gravity, jump counts, and position integration/bounds clamping. It does not query world walls or solve their contacts. `KinematicCharacterComponent` describes engine-provided grounded state as a possibility. That cannot be the cross-engine authority model.
- **Conflicts if used for this profile:** native engine feedback determining grounded state, wall normals, visibility-sensitive gameplay or settled gameplay transforms. `engine-feedback/src/handlers/physics_feedback_handler.rs` queues native settled-transform actions; buffering them deterministically does not make the originating engine physics engine-independent. Preserve the legacy feedback contract, but disallow such feedback from defining portable-profile contacts.
- **Should not be built:** another authoritative runtime, a complete physics engine, arbitrary scene converter, scene editor, native script loader, marketplace, public social platform, or competing general networking stack.

### Evidence and verification limits

Freshly run in this audit:

1. `cargo test -p xace-runtime-core -p xace-network-core -p xace-engine-adapter -p xace-system-graph-compiler --offline --quiet`: **1,346 passed**, no failures or ignored tests in the emitted results.
2. `tools/python_test_gate.py` selected schema-factory, GDE, project-system, asset-registry and DCL: **545 passed; DCL discovery failed** with `ModuleNotFoundError: No module named 'packages'`. Artifact: `tmp/xp-audit-python-report.json`.
3. Direct DCL plus six focused Builder authority/persistence/SGC/typed-operation/semantic-binding/multiplayer-diagnostics modules: **45 passed**. This distinguishes the DCL runner import defect from a failing gameplay primitive test.

Retained evidence actually inspected:

- `.xace/proof/sgc-runtime/20260724T031517Z/summary.json`: real compiler/runtime binaries, persisted plan and matching two-tick schedule/hash replay for its fixture.
- `.xace/proof/cgs-e2e/20260723T101645Z/summary.json`: three-tick replay, adapter snapshot, and rollback failure restoration evidence.
- `.xace/proof/replay-cross-platform/20260724T071240Z/summary.json`: passes its configured **Windows-only** requirement, with six ticks and zero input packets. It is not a Windows/Linux/macOS interactive replay certificate.
- `.xace/proof/network-chaos/x10-043-full-20260814-60hz/network_chaos_report.json`: 4/8/16-client simulated profiles, 216,000 accepted ticks each, injected loss/jitter/reordering/disconnect/rejoin and no permanent desync. `network-core/src/chaos.rs` is a network simulation harness, not installed native engines sharing live runtime sockets.
- X10-064 through X10-067 completion records and their proof tools exist. The referenced `target-codex-task64/65/66/67-*` directories are absent from this checkout. Therefore the historical installed-engine completion claims are documented, not freshly revalidated here. `tools/cross_engine_core_hash_compare.py` hashes a normalized CGS/manifest/input/assets projection and engine attestations; it does not compare live cross-engine tick streams.

No native editors, new hosted model calls, Internet sessions, full workspace suite, or cross-platform run were launched for this review. The checked-in tasklist marks X10-001 through X10-067 complete and X10-068 onward incomplete; some older master-plan/claims rows are stale. The latest AG-030 checkpoint records completion for its declared development/early-user configuration, not whole-XACE launch approval.

## 3. What is actually missing

The deliverable requires a playable package loader; generic Player shell and installer; CGS-derived world geometry/capability compilation; contact/sweep queries; a removable reviewed gameplay-system reference fixture; authenticated session identity and ownership; real runtime/network-core composition; current-tick baseline and reconnect; reachable invite transport; cross-engine world/admission conformance; staged ruleset activation with crash recovery; and replay records spanning package/ruleset epochs.

Also required are targeted repairs to the observed integration conflicts: Schema Factory bypass, direct live preview/input writes, optional session compatibility enforcement, missing real bridge input guards, and the DCL test-runner import path. These are scoped prerequisites, not a proposal to reopen every historical task.

## 4. Recommended architecture

```text
Creator / Builder / optional AI
             |
     typed proposal + isolated preview + explicit approval
             |
            GDE                     (CGS authority)
             |
       Schema Factory               (registries, blueprints, world projection)
             |
            SGC                     (versioned persisted execution plan)
             |
 validated immutable candidate + runtime/migration proof
             |
 Session coordinator -- stage/readiness/activation journal -- local control
             |                                               |
             +-------------- ONE Rust runtime <--------------+
                              tick/input gate
                              canonical contact queries
                              scheduled systems / MutationGate
                              snapshots / events / epoch replay
                                      |
                         versioned session/engine protocol
                                      |
                  +-------------------+--------------------+
                  |                   |                    |
             XACE Player          Unity / Godot          Unreal
            exported Godot        native adapters     native adapter
                  +-------------------+--------------------+
                           normalized timed inputs

Native meshes, animation, particles, audio and cosmetic physics:
client presentation only; never independent gameplay authority.
```

The coordinator is a control-plane owner of admission and lifecycle, not another gameplay layer. It cannot invent schema changes or write component tables. Rust `network-core` owns shared session/compatibility contracts. The existing runtime process hosts the live session controller. Builder's authoring `SessionManager` and the game session remain distinct identities, linked explicitly.

## 5. Key architectural decisions

### Player host and distribution

**Choose an exported Godot 4 application, reusing and generalizing the existing Godot adapter.** Pin an exact stable Godot build and matching export templates during the first packaging task; the historical 4.6.3 proof is a candidate, not an assumption that it is the current certified release.

The repository already supplies Godot presentation/input integration and a runnable shell. A custom Rust/wgpu/SDL-style renderer would add camera, input, audio, resource import and rendering work with no corresponding mature host in this checkout. Unity and Unreal remain supported client targets; their existing adapter code does not remove the additional host packaging/toolchain and licensing obligations of selecting them as the default distribution.

Godot's MIT distribution model and playable export tooling suit this choice. Include the Godot license and applicable third-party/asset notices; retain exact export-tool/template provenance. Godot exports require presets/templates, and a PCK alone is not a playable build. See [Godot license guidance](https://docs.godotengine.org/en/stable/about/complying_with_licenses.html) and [Godot export documentation](https://docs.godotengine.org/en/stable/tutorials/export/exporting_projects.html). Unity platform/service-provider rights require particular attention under its [current editor terms](https://unity.com/legal/editor-terms-of-service/software); Unreal carries its own [distribution terms](https://www.unrealengine.com/eula/unreal). No legal or size benchmark equivalence is assumed.

Ship Player with trusted presentation code and the pinned XACE runtime sidecar. Solo/creator-host launches the sidecar; remote join does not launch a second authority. Friends need neither an editor nor Rust/Python/Node build tools nor an AI-provider account. Native projects continue using native adapters. Do not load arbitrary PCK scripts, DLLs, GDScript, Unity projects or Unreal projects from an invited gameplay package.

### Topology and input timing

Retain `host_client_lockstep_v1`: one creator-host authority with a fixed input delay and explicit required-input membership. Thin presentation clients do not independently simulate the authoritative world. Lockstep refers to the host's input-release gate, not deterministic native-engine physics on every client. Do not relabel this as certified dedicated-server or P2P support.

Initial certified profile: four players, 60 Hz, no authoritative client prediction, no host migration. Preserve optional bounded presentation prediction as a future profile using the existing Rust predictor, not a gameplay rewrite in three engine languages. Start with interpolation and measure responsiveness.

The host assigns peer/player identities and grants an input schedule. Each client submits bounded inputs for requested ticks, including explicit idle input, independently of receiving the next snapshot. Otherwise snapshot-triggered input plus lockstep can deadlock. Record input quantization, timeout decisions, and membership changes; never use render FPS or wall-clock timeout nondeterministically inside replay.

Use existing framing for the local proof. Remote transport must authenticate, encrypt and bind a connection to its assigned peer; keep the Builder control socket local. For the flagship begin with LAN/private reachable endpoints, then add one bounded invitation relay for the ordinary remote-friend product path. The relay forwards authenticated session traffic, not gameplay computation. No NAT mesh, matchmaking platform, public accounts, or general hosting service is needed.

### Minimal World Contract

World Contract v1 is a versioned **compiled projection of CGS actors/components**, not another editable scene file. Source authority remains CGS. Suggested new source locations are `core/src/world/`, `schema-factory/src/world_contract/`, and `runtime-core/src/gameplay_geometry/`; names are proposals, not existing modules.

The contract pins world ID/version/hash, source CGS hash, mode, units, axes, numeric/query profile, stable object IDs, object-to-runtime-EntityID mapping, transforms, primitive geometry, static/kinematic role, trigger/volume category masks, spawn/anchor metadata and versioned semantic capabilities. Binding status and concrete engine paths live in host-specific presentation records, outside the gameplay world digest.

Reuse the frozen ten UCL components. Add any needed capability/contact/character-state types to the appropriate DCL package or validated GCL; do not add an eleventh universal component or duplicate collider/transform authority. The Rust `ucl/` directory contains some DCL type implementations, but the registry still distinguishes the ten UCL core entries: follow namespace/type-ID ownership, not directory names alone.

Source object IDs such as `surface_17` are stable across editing and packaging. Runtime EntityIDs remain monotonically allocated and archived. Define their mapping explicitly, retain it in snapshots, and keep a newly added object from renumbering live objects. Compilation sorts inputs and rejects duplicate IDs, malformed typed properties, dangling relationships, invalid instance bindings, undeclared capabilities and unresolved asset references. Geometry validators additionally reject dimensions/transforms unsupported by the selected profile. Gameplay capability names and role constraints come from ordinary package/catalog declarations; unsupported platform/protocol requirements still reject.

Legacy v1/v2 geometry vocabulary was **Box, Trigger, SpawnPoint, InteractionAnchor**. It is not the semantic vocabulary of v3. Project-defined structures, effects, zones and other concepts are schema declarations; an object selects a collision profile only when required. A floor is a thin finite box. No new infinite plane, cylinder, ramp, arbitrary mesh or general capsule solver is required for the flagship. Characters can render as capsules while using a declared box gameplay proxy. V1 rejects rotated/sheared collision boxes and unsupported moving solids visibly; it does not silently substitute native physics.

### Physics boundary

1. **Visual geometry:** arbitrary engine-owned meshes and materials bound to canonical object IDs. Different appearances are permitted.
2. **Native physics:** cosmetics such as particles/ragdolls; camera-only queries are presentation. Gameplay-critical native feedback is prohibited in this portable session profile.
3. **Canonical interaction geometry:** fixed-point AABB overlap, swept-box movement, ground support and side probes; stable contact normals/IDs and deterministic tie-breaking. Generic proximity targeting uses fixed-point squared-distance queries; the reference shockwave is one package-level consumer, not a new core primitive.
4. **Authoritative state:** transform, velocity, contact state and package-defined gameplay state/event effects committed by scheduled systems through MutationGate. Wall-jump counters belong only to the reference package.

Define limits and intermediate arithmetic, touching/penetration rules, contact ordering `(time_of_impact, object_id, face_id)`, iteration bounds, velocity clipping and zero-distance behavior. Rebuild derived spatial indexes deterministically on restore; snapshot any solver state that affects outcomes. Use existing fixed-point math and avoid float roundtrips through adapters.

This trades curved/rotated surfaces and complex rigid-body interaction for a small, testable, portable mechanic envelope. Gameplay-relevant visual mismatch must be visible in a collision overlay. Native visibility/animation/settled feedback can remain supported for other profiles; any accepted authoritative external input must have one named source and a replay record. Independent engine callbacks must never decide the same gameplay event three times.

### Package and session identities

Define three distinct artifacts: creator project, immutable playable package, and live session. Extend project/package utilities, without rebranding adapter handoff as a finished game.

A playable package manifest pins package ID/version/content hash, source CGS/hash, compiled schema/world digests, persisted SGC plan identity, runtime/executor ABI and build compatibility, input/event schemas, authoritative feature flags, asset semantic requirements, and per-host presentation manifests. Authoritative executable content is limited to the pinned runtime's supported reviewed executors in v1. Include proof references and checksums, with distribution signing addressed by the release task.

Session identity pins session UUID, authority incarnation, package identity, schema/CGS/plan/world digests, world seed, 60 Hz profile, input schema/delay, feature flags, current tick, ruleset epoch, membership/ownership, client type/version/capabilities, baseline ID, readiness, and reconnect generation. Mutable state is separate from immutable identity. Missing values reject admission.

Split the current compatibility profile into **exact gameplay compatibility** and **host presentation compatibility**. Comparing whole engine-specific asset manifests or all adapter version strings for equality would wrongly reject Unity/Godot/Unreal variants. Require equal semantic gameplay requirements and certified protocol capabilities, while allowing different native asset bytes and host-specific bindings. Missing required geometry blocks; missing permitted cosmetic assets selects a reported fallback.

A full `WorldSnapshot` is an authoritative restore artifact; a presentation baseline need only carry the approved client projection. Give both separate digests. A thin client can verify the received projection and report the authority's world hash, but cannot independently recompute a full world hash from omitted RNG/queues/private state.

### Cross-engine synchronization and mutation

Synchronize by authoritative `(session, incarnation, ruleset_epoch, tick, sequence)`, not simultaneous rendered wall-clock frames. Native interpolation may differ. Each client must reject stale epochs, acknowledge applied baselines, and prove its actual canonical mirror state at agreed checkpoints, alongside the host's full state hash. Echoing a server hash alone is insufficient proof of correct application.

Activation protocol: **Proposed → Validated → Approved → Prepared → Ready → Committed@N → Active**, or **Aborted** before commitment.

- Stage immutable candidate CGS, Schema Factory output, SGC plan, package/world state and deterministic migration against the current parent epoch. Bind approval to their exact digests and invalidate it if the candidate changes.
- Validate on an isolated snapshot/runtime, outside the live tick loop. A live default-field edit must explicitly distinguish changed configuration from state to preserve: existing hot-swap does not overwrite existing component rows merely because new defaults changed.
- Send prepare records to participating clients with candidate identities, required capabilities and readiness deadline. Select a future tick N with enough input lead. Record the readiness set and commit decision durably.
- At the clean boundary before simulation tick N, the single authority applies the approved migration/plan using the existing hot-swap path. Publish one activation record and new baseline/epoch, then simulate N. Clients render authoritative epoch-tagged results; they do not independently commit gameplay code.
- Before commitment, rejection or failed migration preparation leaves the old epoch running. If activation itself fails, publish no new-epoch output; restore verified old state and continue only if restoration is proven. Otherwise halt visibly.
- Once activation is published, do not erase committed history. A client that loses the commit is fenced into resync and cannot submit old-epoch inputs. If the host crashes, recovery follows the durable decision and a verified checkpoint, or ends the session visibly; it never guesses an epoch.
- Joins around N bind to one baseline/epoch. Keep them out of required-input membership until caught up, recheck admission after transition, and discard old-epoch prediction/playback state. Deduplicate effects by `(epoch, tick, event_id, entity_id)` and retain rollback revocations.

“Everyone at tick N” is an authoritative semantic guarantee. A disconnected screen cannot be forced to display at the same instant. For the flagship, require all intended demo clients ready before commitment; failure aborts the candidate or pauses at the barrier according to a recorded policy.

## 6. Ordered implementation roadmap

Every task below is proposed, not complete. Dependencies are explicit; later phase work may be researched early, but its acceptance gate cannot be skipped. New paths are labeled proposed. Tests are part of the task, not substitutes for exercising real production entrypoints.

### Phase 0 — Freeze contracts and close authority gaps

**XP-001 — Freeze the supported session contract and audit baseline**

- Purpose: turn this proposal into a narrow executable engineering contract.
- Reuse: `core/src/wire/`, `engine_protocol.rs`, `session_compatibility.rs`, `launch_topology.rs`, and existing CGS/SGC schemas.
- Implementation: ADR plus typed identity/envelope/epoch contracts and golden JSON fixtures; specify 4-player/60-Hz Windows-first profile, geometry limits, input lead/timeout policy, package trust, and proof taxonomy. Correct the DCL runner import configuration; index evidence as present, historical-only, or missing. No new simulator.
- Dependencies: roadmap freeze.
- Acceptance: all three host readers can be tested against the same documented vectors; missing identity and unknown required capability are explicit rejects; DCL passes through the supported runner; topology naming discrepancy in chaos versus launch profile is mapped explicitly.
- Tests/proof: contract serialization/mismatch tests; source-bound baseline results and evidence manifest.
- Failure/rollback: rejected drafts remain drafts; no public support claim changes.

**XP-002 — Close live authority and compiler boundary gaps**

- Purpose: prevent Player/session work from inheriting bypass paths.
- Reuse: `SessionManager.compile_sgc_plan()`, `SchemaFactory.compile()`, `RuntimeOrchestrator`, `MutationGate`, control preview routes.
- Implementation: one compiled-schema projection feeds SGC; scheduled Input-phase mutations replace direct structural input writes; preview edits use an isolated world; session mode rejects legacy live preview writes. Audit feedback acceptance for the declared profile.
- Dependencies: XP-001.
- Acceptance: invalid world/component registry is rejected before SGC; a client cannot create an input component outside MutationGate; preview changes leave live state/hash unchanged; no provider or engine can commit directly.
- Tests/proof: real Builder→GDE→Factory→SGC→runtime test, injected component/preview violations, retained pre/post hashes.
- Failure/rollback: failed validation preserves disk CGS, compiled artifacts and live runtime; no silent fallback to direct extraction or mutation.

### Phase 1 — World foundation and the actual mechanic

**XP-003 — Compile World Contract v1 from CGS**

- Purpose: give every host the same gameplay world without a second scene authority.
- Reuse: `world_definition.rs`, actor blueprints, UCL collider/transform/identity, DCL registry and strict CGS validator.
- Implementation: proposed `core/src/world/` types and Schema Factory world projection, canonical IDs/bindings, box/trigger/spawn/anchor vocabulary, capability catalog, hash/version and manifest provenance. Register additions in DCL/GCL only.
- Dependencies: XP-001, XP-002.
- Acceptance: reorder-equivalent source yields identical world bytes/hash; IDs remain stable; duplicate IDs, negative sizes, unsupported transforms and unresolved assets fail before commit; world hash is bound to source CGS and package.
- Tests/proof: compile golden arenas, malformed corpus, roundtrip and ID-preservation tests.
- Failure/rollback: a rejected arena or binding batch commits nothing.

**XP-004 — Add the minimal authoritative geometry query layer**

- Purpose: remove engine-specific contacts from portable mechanics.
- Reuse: `Fixed64`, `ISystemContext`, entity queries, SGC access declarations, snapshots and MutationGate.
- Implementation: proposed runtime geometry module with bounded swept-AABB, overlap, ground/side probes, stable normals and squared-distance targeting. Derive spatial caches from canonical state; expose reads through the scheduled system context.
- Dependencies: XP-003.
- Acceptance: identical query/contact results under shuffled object insertion, restore and supported OS builds; no tunneling within declared limits; deterministic handling of corners, initial overlap, zero motion and equal hits; unsupported geometry rejected.
- Tests/proof: numeric edge corpus, permutation tests, fixed-point overflow/boundary cases and replay hashes.
- Failure/rollback: invalid geometry/query bounds refuse the package or halt the tick transaction without partial movement.

**XP-005 — Reference Mechanic Proof**

- Purpose / product capability: prove that an ordinary removable gameplay-system package can consume canonical contacts, semantic requirements, timed inputs and deterministic state transitions through existing XACE mechanisms.
- Prerequisite: complete the capability-contract correction recorded in the XP-003/004 review above before mechanic implementation. No new mechanic-specific core branch is an acceptable shortcut.
- Reuse: existing gameplay-system registration, package/catalog mechanisms, compatible character components, semantic inputs/events, declared SGC dependencies and MutationGate. Reuse existing built-in system/catalog infrastructure as infrastructure, not as permission to privilege the fixture in runtime orchestration.
- Implementation: an ordinary versioned reference package owns mechanic configuration, state, counters, transitions and effects. It declares surface capabilities and dependencies as data and uses the generic query API. Schedule exactly one authoritative movement writer for its actor. Removal/replacement uses normal package/catalog registration and leaves core contracts unchanged.
- Dependencies: XP-003 (corrected capability contract), XP-004.
- Product acceptance: normal compile/registration/scheduling/access/rollback paths execute the package; arbitrary declared namespaced capabilities use the same path; no mechanic names control World Contract, execution, networking or adapter behavior; package removal requires no core changes.
- Reference proof: wall-running on fixture-declared surfaces, exactly two successful chained wall-jumps before landing, grounded reset and a configurable third-attempt action. Initial third attempt is disabled; the later approved candidate performs reversal + shockwave. Untagged surfaces, contact loss and airborne transitions must not grant extra jumps or duplicate effects.
- Tests/proof: recorded inputs, corners, landing and jump edges; headless state/event assertions and replay hashes; inspect package boundaries and ordinary removal, plus generic semantic-data tests. Do not build an additional mechanic to prove generality.
- Failure/rollback: unsupported package requirements or mechanic requests clarify/refuse; no arbitrary native/generated script fallback or privileged runtime branch.

**XP-006 — Generic capability/dependency-aware gameplay authoring**

Status: complete (2026-09-28), registered-host/no-provider proof profile. See `docs/XP006_COMPLETION.md`.

- Purpose / product capability: author any supported catalog gameplay package using its declared world capabilities, component/system dependencies and configuration requirements.
- Reuse: primitive facets, PIL context/composite planning, GDE typed operations, preview approval, package/catalog declarations and typed asset placeholders.
- Implementation: generic requirement discovery, missing-dependency explanation, object tagging and deterministic template proposals driven by declared package data. Route the complete proposal through the existing atomic approval/compile pipeline. No wall-running keyword branch in core validation or dependency resolution.
- Dependencies: XP-003 corrected capability declarations, XP-005 reference proof package.
- Product acceptance: the same authoring mechanism accepts arbitrary valid declared capabilities, reports missing/unsupported dependencies, preserves the project on cancellation or stale approval, and commits the approved dependency/system/configuration batch atomically. Native asset paths never become gameplay conditions.
- Reference proof: "Add wall running" is the golden authoring request. The reference package's requirements produce the choice to mark selected compatible surfaces or create its test arena. Its template and capability meaning remain fixture-owned catalog data.
- Tests/proof: no-provider typed fixtures, generic declaration/requirement cases and the wall-running golden request; verify compiled systems/runtime behavior, not wording alone. An actual provider demonstration remains explicitly opted in later. No additional mechanic implementation.
- Failure/rollback: cancellation, stale CGS or invalid dependencies preserves the project and running epoch.

### Phase 2 — Minimum Player and playable package

**XP-007 — Define and verify the native playable package**

Completed 2026-09-29 for the Windows headless profile; see `docs/XP007_COMPLETION.md`.

- Purpose: establish what Player can actually run.
- Reuse: project manifest, package checksums/versioning, asset preflight, persisted plans and Schema Factory output.
- Implementation: proposed playable manifest/archive loader with exact gameplay identity, world/input contracts, supported executor set, presentation variants and bounded verified extraction. Keep release runtime artifacts outside hidden editor/cache paths.
- Dependencies: XP-002, XP-003, XP-005.
- Acceptance: package runs from a relocated clean folder; no repo-relative absolute paths; tampered/missing plan/world/runtime or archive path traversal is rejected; different native visual variants retain the same gameplay identity; no user code is executed on import.
- Tests/proof: deterministic package construction, unpack/repack verification, corrupt/archive limits and relocation tests.
- Failure/rollback: staged package is activated only after all verification; interrupted installation retains the previous package.

**XP-008 — Generalize the Godot shell into XACE Player**

Completed 2026-09-29 for the Windows local keyboard/pre-admitted package profile; see `docs/XP008_COMPLETION.md`.

- Purpose: deliver the first editor-free local playable client.
- Reuse: `adapters/godot/project.godot`, `xace_godot_main.gd`, transport/protocol, entity manager, input collector and debug HUD.
- Implementation: proposed `apps/xace-player/` shell using shared adapter logic; load package/world; local runtime sidecar lifecycle; canonical box rendering, dynamic ownership/camera, input focus and basic status. Remove fixed arena/player assumptions.
- Host integration: compose a reviewed native host using ordinary package-system registration. Match actual executor contracts and executable digest to XP-007 admission; no traversal dispatch in core.
- Dependencies: XP-004, XP-005, XP-007.
- Acceptance: a supported package opens and executes its declared gameplay systems from real input without an editor (reference proof: movement, jumps and wall-running); Player cannot advance gameplay without the Rust authority; changing render FPS does not change authoritative results.
- Tests/proof: Proof A with real Player/runtime processes and recorded input; screenshots/video supplemented by host state/event logs.
- Failure/rollback: runtime loss freezes gameplay with a clear message; closing Player cleans up only its owned process.

**XP-009 — Complete Player semantic presentation and world readiness**

Status: complete for the declared local Player formats; see `XP009_COMPLETION.md`.
Generic event bindings and world object identities remain independent of game nouns.

- Purpose: make actions understandable without confusing assets with gameplay.
- XP-008 handoff: preserve generic typed transforms, ownership and arbitrary input actions. Replace presentation placeholders through declared supported bindings; do not infer rendering or behavior from game nouns.
- Reuse: semantic playback, typed assets, binding-status reports and rollback cleanup in all adapters.
- Implementation: explicit supported presentation formats and generic camera/audio/effect event bindings (reference proof: the package shockwave event); world binding registry; safe resource loading; collision overlay and permitted placeholders.
- Dependencies: XP-008.
- Acceptance: a missing cosmetic asset has a reported fallback; missing required geometry blocks readiness; effect deduplication/rollback leaves no ghost objects; replacing presentation assets cannot alter authoritative contact results; wall visuals are the reference case.
- Tests/proof: asset-missing, fallback, duplicate event, restore and binding mismatch scenarios in real Player.
- Failure/rollback: failed presentation preparation cannot partially activate a gameplay package.

### Phase 3 — Player distribution and Play UX

**XP-010 — Package Player and wire Builder Play**

Status: implemented; clean-machine acceptance pending by owner instruction (2026-09-30).
Same-host lifecycle and Builder Play proofs pass. See `XP010_COMPLETION.md`.

- Purpose: remove repository/toolchain knowledge from first play.
- Reuse: Builder runtime-control/viewport UI and launcher process lifecycle patterns; Godot export tooling.
- Implementation: pinned export presets/templates, runtime bundle, notices/checksums, local launch broker with owned processes and capability-bound local control; Builder validates/materializes package then launches Player. Show actionable progress and retry.
- Dependencies: XP-007 through XP-009.
- Acceptance: clean declared Windows machine, no engine editor/Cargo/Python/Node in PATH, Play produces the supported local game; port collision, denied install path, stale binary and repeated Play recover without orphan authorities.
- Tests/proof: clean-machine install/launch record and automated broker lifecycle tests; record actual startup time, size and hardware requirements.
- Failure/rollback: failed update/launch restores the prior verified install; no implicit build from source on the friend's machine.

### Phase 4 — Real live session admission and synchronization

**XP-011 — Bind complete session identity to the real bridge**

- Purpose: make library compatibility rules govern every actual client.
- Reuse: Rust `SessionManager`, `SessionCompatibilityProfile`, bridge handshake, shared wire types and launch topology.
- Implementation: session controller in the runtime process; UUID/incarnation/epoch identities, exact gameplay compatibility versus presentation capability negotiation, authenticated player assignment, append-only input/membership/session records from session start.
- Dependencies: XP-001, XP-002, XP-007.
- Acceptance: no session starts without mandatory identities and compatibility; stale CGS/plan/world/runtime/input profile rejected before input admission; Unity/Godot visual variants accepted when semantically compatible; authoring and game-session IDs cannot be confused.
- Tests/proof: real socket handshake matrix plus golden cross-language contracts.
- Failure/rollback: failed admission creates no player ownership or required-input membership.

**XP-012 — Integrate authenticated input admission and tick pacing**

- Purpose: make independently controlled players safe and deterministic.
- Reuse: `MaliciousInputGate`, `AuthorityResolver`, `CheatGuard`, `InputSynchroniser`, input schemas and runtime Input phase.
- Implementation: connection-bound ownership, sequence/replay/rate limits, normalized quantized inputs, requested-tick/idle input pacing, bounded nonblocking queues, and actual runtime lockstep configuration. Reject gameplay feedback from unauthorized presentation clients.
- Dependencies: XP-011.
- Acceptance: a peer cannot control another actor; duplicate/future/stale packets cannot change state; two players can drive different actors; a slow/incomplete handshake cannot stall simulation indefinitely; zero-input lockstep cannot deadlock awaiting a snapshot.
- Tests/proof: real socket malicious input and pacing tests, adversarial fragmentation, owner impersonation and scripted arrival-order permutations.
- Failure/rollback: reject traffic before mutation; disconnect/timeout changes use an explicit logged membership policy.

**XP-013 — Implement baseline, late join, reconnect and resync**

Status: implemented for the local Windows full-projection profile (2026-10-01).
See `docs/XP013_COMPLETION.md` for verified scenarios and latency limits.

- Purpose: turn lifecycle objects into actual synchronized clients.
- Reuse: session lifecycle, `LateJoinHandler`, snapshots, delta sequencing, resync and rollback utilities.
- Implementation: baseline IDs with tick/epoch, client projection digest, gap recovery, bounded catch-up buffers and reconnect generation; newly joined peers become required-input members only after acknowledgement. Start with full snapshots; introduce deltas only after baseline correctness.
- Dependencies: XP-011, XP-012.
- Acceptance: late join starts at the current authoritative tick, never assumed zero; stale baseline/connection generation cannot overwrite new state; disconnect/rejoin preserves assigned player identity under policy; dropped baseline or delta gap forces verified recovery.
- Tests/proof: real two-client join/disconnect/reconnect tests and restored projection/hash comparisons.
- Failure/rollback: clients remain syncing/fenced on failure; existing players never wait for an unready joiner.

### Phase 5 — Invite and remote-friend product path

**XP-014 — Deliver Play → Invite → Join on a reachable session**

- Status (2026-10-02): implemented; final exported two-Player same-host proof passes. Two-machine acceptance remains pending by owner instruction. See `docs/XP014_COMPLETION.md` and `docs/XP014_TWO_MACHINE_TEST.md`.
- Purpose: provide the creator/friend workflow over the integrated session stack.
- Reuse: packaged Player, runtime session controller, Builder project/prompt UI and package verifier.
- Implementation: expiring scoped invite, one-time redemption/reconnect policy, human-readable join progress, verified package acquisition from the host/session service, readiness view, leave/end actions and bounded asset download/cache handling.
- Dependencies: XP-010 through XP-013.
- Acceptance: two Player instances on two machines join one host with distinct players; no developer tools or AI subscription needed; expired invite/tampered package has a clear refusal; leave/end releases membership/process resources.
- Tests/proof: Proof C on LAN/private reachable transport, package-missing and readiness-failure walkthroughs.
- Failure/rollback: package/asset preparation never grants partial live membership; abandoned joins expire.

**XP-015 — Add the bounded Internet invitation transport**

- Status (2026-10-02): implemented and locally TLS-verified; public deployment and two-network acceptance pending by owner instruction (no hosting available). See `docs/XP015_COMPLETION.md` and `docs/XP015_DEPLOYMENT_AND_TWO_NETWORK_TEST.md`.
- Purpose: make the remote friend flow work without manual port forwarding.
- Reuse: identical session messages and lifecycle; introduce only a transport relay interface.
- Implementation: encrypted authenticated relay connection with short-lived session capabilities, bounded sessions/bandwidth/queues, reachability health and cancellation. Authority remains on the creator host; do not expose Builder or add matchmaking/social accounts.
- Dependencies: XP-014.
- Acceptance: two ordinary external networks connect through the same invite flow; relay loss fences/reconnects clients without a second authority; token replay and control-channel access rejected. Declare service/availability limits.
- Tests/proof: two-network capture, relay outage/expiry/replay tests and traffic/resource budgets.
- Failure/rollback: visible session interruption or supported reachable-endpoint fallback; never silently label a LAN-only demonstration as Internet invitation support.

### Phase 6 — Cross-engine canonical world and same-session proof

**XP-016 — Extend native adapters to world/session v1**

- Purpose: keep Unity, Godot, Unreal and Player on one gameplay contract.
- Reuse: native transports/applicators/input collectors, reversible adapter installation, semantic binding status and package versioning.
- Implementation: world primitive rendering and canonical-object bindings, scale/axis/handedness conversion, session admission, ownership, tick/epoch application, readiness, reconnect and local-only cosmetic physics. Preserve shared Godot adapter logic between native integration and Player.
- Dependencies: XP-009, XP-011 through XP-013.
- Acceptance: same object IDs, transforms, extents, surface tags and input meaning in all supported versions; intentionally different wall artwork does not change gameplay; native contact reports cannot alter authoritative state.
- Tests/proof: Proof B canonical marker/normal/coordinate scene and cross-language malformed-message suite in real installed hosts.
- Failure/rollback: unsupported capabilities reject admission; adapter update uses existing reversible installation.

**XP-017 — Certify mixed and three-engine live play**

- Purpose / product capability: certify engine-independent execution of ordinary gameplay packages under one shared authority, with consistent ownership, input, state and events.
- Reuse: canonical vertical-slice fixture, installed-engine proof tools, runtime logs and new session conformance harness.
- Implementation: use the removable XP-005 reference package and its arena with independent scripted player inputs; launch Player+one native host, then Unity+Godot+Unreal simultaneously, and finally include Player as fourth client.
- Dependencies: XP-005, XP-013, XP-016; XP-015 for a remote claim.
- Product acceptance: one authority/session/incarnation, distinct player ownership, generic cross-client state/event interaction and matching canonical mirror projections at agreed ticks; mismatched world rejected; disconnect one client while others remain coherent.
- Reference proof: wall-running/jumping exercises canonical contacts and shared interactions as package gameplay; neither protocol nor adapter knows this mechanic.
- Tests/proof: Proofs D and E with real socket transcripts, host per-tick hashes, client-applied projection digests, build/source identities, and gameplay recording. Static manifests/screenshots alone fail this gate.
- Failure/rollback: retain failures and refuse same-session claims until all intended clients pass.

### Phase 7 — Approved synchronized live mutation

**XP-018 — Stage and prove immutable live ruleset candidates**

- Purpose / product capability: stage and prove an immutable validated gameplay-system ruleset candidate without touching the running epoch.
- Reuse: typed proposal approval, GDE/Factory/SGC, hot-swap classification, snapshot replay and migration hooks.
- Implementation: candidate store keyed by digests; parent-epoch checks; isolated runtime proof; explicit config-versus-state migration mapping; generic package/world and declared capability diff. No mechanic-specific candidate schema or migration branch.
- Dependencies: XP-005, XP-006, XP-011, XP-017.
- Product acceptance: authoring proposal cannot activate; unsupported/state-transforming migration rejected unless supported by a proven hook; changing CGS defaults alone cannot falsely report changed live behavior; validation failure leaves live tick/state/history untouched.
- Reference proof: stage the approved fixture candidate changing the third wall-jump attempt from disabled to reversal + shockwave. Its configuration/state interpretation belongs to the package.
- Tests/proof: rejected proposal, stale parent, stale plan, denied migration, and positive isolated behavior proof through the same generic candidate path.
- Failure/rollback: discard staged candidate; retain prior live and durable active identities.

**XP-019 — Commit rulesets at a durable future activation tick**

- Purpose / product capability: activate a validated gameplay-system ruleset mutation at authoritative tick N as one durable atomic session transition.
- Reuse: existing hot-swap implementation, MutationGate rollback, session readiness and side-effect rollback messages.
- Implementation: prepare/readiness/commit journal, activation tick N, clean-boundary CAS against parent epoch, plan+migration+world installation, epoch-tagged publication, crash recovery and join fencing. Extend existing local control; no second mutation engine.
- Dependencies: XP-012, XP-013, XP-018.
- Product acceptance: N-1 uses the old ruleset and N uses the new ruleset on one preserved world; all ready clients apply the new epoch; duplicate commit is idempotent; rejected/migration-failed candidate yields zero partial new-epoch output; joins at N−1/N/N+1 see a complete compatible epoch.
- Reference proof: the fixture third wall-jump attempt is disabled before N and produces reversal + shockwave at/after N. This is evidence for generic activation, not a rule built into the activation coordinator.
- Tests/proof: Proof F with state/event traces and all real hosts; inject failure before decision, after decision, during migration and before broadcast; restart from durable evidence.
- Failure/rollback: precommit abort continues old epoch; verified activation failure restores old state; postpublication recovery resyncs or visibly ends the session without rewriting committed history.

### Phase 8 — Replay and debugger integration

**XP-020 — Replay sessions across ruleset epochs**

- Purpose / product capability: replay any recorded supported gameplay-system ruleset history deterministically across live changes.
- Reuse: snapshot serializer, input/feedback logs, schedule traces, migration log, rollback resimulation and divergence diagnosis.
- Implementation: immutable replay bundle containing initial snapshot, quantized accepted input stream, permitted external inputs, membership/timeout decisions, seed, epoch activation/migration records and exact artifacts; restore matching schedule/registry for each epoch. Record from XP-011 onward.
- Dependencies: XP-019.
- Product acceptance: replay before/at/after N reproduces host per-tick hashes and canonical gameplay state/events exactly; rollback crossing an epoch uses the historical schedule; missing old code/plan/world fails visibly; repeated playback does not duplicate presentation effects.
- Reference proof: recorded fixture inputs reproduce the third-attempt reversal/shockwave using the historical package rules, without a mechanic-specific replay branch.
- Tests/proof: Proof G hash-by-hash comparison, non-empty input stream, injected first-divergence diagnosis; run declared OS matrix, keeping Windows-only and three-OS claims separate.
- Failure/rollback: corrupt/incomplete replay never substitutes current rules; live authority is untouched by offline replay.

**XP-021 — Extend the existing debugger and creator flow**

- Purpose / product capability: explain generic session state, gameplay-system causality and ruleset changes to creators using declared component/event metadata.
- Reuse: tick debugger, causality/RNG panels, diff approval, runtime status and support export.
- Implementation: session/epoch markers, applying-at-N status, player/input/contact/capability traces, migration diagnostics and proof export; inspect a replay fork by default. Privileged pause/restore is session-wide and explicit; guests cannot control the host.
- Dependencies: XP-020.
- Product acceptance: creators can locate a recorded gameplay event, inspect its inputs, contacts, capabilities, component state and system dependencies, replay it and return to live view. Opening the debugger does not rewind friends; permissions, plain-language errors and technical-detail toggles are coherent. No fixture-specific debugger panel or event interpreter is required.
- Reference proof: locate the third-attempt event and inspect surface/contact/counter/velocity causes using generic traces and package-provided labels.
- Tests/proof: automated navigation/control permission tests and an actual creator walkthrough of the entire target sequence.
- Failure/rollback: failed diagnostics/export leaves session running; failed replay fork can be discarded independently.

### Phase 9 — Faults, compatibility, distribution and usability gate

**XP-022 — Certify the complete program under faults and clean installation**

- Purpose: make support and public demo claims match reproducible evidence.
- Reuse: chaos harness, proof storage, certification tools, distribution checksum/lifecycle and claim matrix.
- Implementation: real-process fault runner, declared version/platform matrix, retained source/artifact-bound proof bundles, release signing/notices, budgets, two-hour real four-client soak with mutations/rejoins, and cold-install usability trial. Broader eight-hour commercial soak remains the existing release program.
- Dependencies: XP-010, XP-015, XP-017, XP-019 through XP-021.
- Acceptance: all Proof H cases pass without silent divergence; reconnect bounded by declared timeout; queues/memory remain bounded; proposed 60-Hz arena budget has p95 authority tick under 16.7 ms on recorded reference hardware; zero orphan authority on normal cleanup; three first-time testers complete Play/Invite/Join/approve without terminal help. Record actual latency/render performance separately.
- Tests/proof: Proofs A–H rerun from pinned binaries and fixture; install on a clean supported machine; fault/soak transcript, compatibility matrix and claims mapped to artifacts. No universal platform or engine-version claim.
- Failure/rollback: failed profile stays unsupported; retain last known-good signed Player/package and preserve diagnostics. No public release certification inferred from source tests alone.

### Existing backlog relationship

XP tasks are integration scope, not replacement completion claims for X10. XP-020 uses save/checkpoint concepts but does not close X10-068/069 campaign save authority/migration. XP-007/010/022 should share release/package work with X10-070/071 and X10-080/081/082/087/089/097 where applicable, instead of implementing parallel manifests/installers. AG integration is an optional authoring provider path; friends and deterministic replay must not depend on it. No current task checkbox is changed by this proposal.

## 7. Proof ladder

- **A — Local Player:** XP-008/010. Supported package, actual exported Player + Rust runtime, real player input and contact-driven gameplay, editor/toolchain absent.
- **B — World Contract:** XP-016. Same canonical IDs/geometry/capabilities mapped across all hosts; expected visual variation, verified coordinate and collision interpretation.
- **C — Invite:** XP-014; XP-015 adds Internet reachability. Two machines/two Player instances, one authority, distinct owned actors and verified baseline.
- **D — Mixed client:** XP-017. Player plus a native engine, interacting through one real session.
- **E — Three-engine session:** XP-017. Unity, Godot and Unreal simultaneously; add Player as a fourth client. Record distinct control inputs, host hashes and applied client projections.
- **F — Live mutation:** XP-019. Generic approved ruleset candidate activates at N with preserved actor/world continuity, readiness and durable commit record. Reference proof: observable old/new third-jump behavior.
- **G — Replay/debug:** XP-020/021. Non-empty recorded input plus epoch history reproduces canonical state/events and matching hashes; generic debugger traces explain causes. Reference proof: the launch/shockwave event.
- **H — Fault matrix:** XP-022. Stale CGS, stale plan, wrong world, incompatible runtime/client/protocol, unauthorized owner, disconnect/rejoin, dropped/reordered/duplicate messages, rejected mutation, migration failure, incompatible client, missing binding, and joins around activation. Also crash before/after commit, missing replay artifact, token expiry, partial package transfer, and slow client/backpressure. Every case has an explicit old-epoch continuation, fencing/resync, rejection, or visible halt outcome.

For each proof retain manifest/source revision plus working-tree digest, executable hashes, exact commands, input stream, session/ruleset/world/plan identities, host tick hashes, client projection digests, expected failures and logs. Screenshots/video explain the result but cannot establish authority or determinism. Distinguish simulated packet chaos from real socket/relay faults and installed-headless checks from human playability.

## 8. Risks and traps

- **An engine by accident:** a scene editor, generic script loader and arbitrary importer would overwhelm the program. Keep Player a host for supported packages.
- **A physics engine by accident:** start with the bounded generic AABB/query profile; reject unsupported collision shapes and motion. Do not promise arbitrary terrain or rigid bodies.
- **A second runtime:** no gameplay implementations in Godot/C#/C++; optional prediction must be bounded and non-authoritative.
- **A cosmetic mutation demo:** changing a label, CGS default or VFX alone is insufficient. Assert state, impulses, counters and event effects before/after N.
- **A second networking stack:** compose existing session/input/ownership modules and extend the active wire path. A relay is a transport addition.
- **False atomicity:** durable authoring state, staged package, runtime epoch and published client state need a journal and recovery policy. Local rollback tests do not prove distributed activation.
- **False equivalence:** a shared manifest digest, echoed server hash, generated evidence PNG or three separate runs does not prove live shared gameplay.
- **Presentation equality mistaken for compatibility:** native art may differ; authoritative geometry/input/semantics may not.
- **Wait loops and hidden latency:** per-client blocking reads, snapshot-triggered inputs, unbounded catch-up and four required peers can make a correct simulation unplayable. Measure the actual path.
- **Unbounded memory:** current vectors/maps retaining traces and schedules need explicit session retention policies and disk replay storage; longer sessions cannot rely on unlimited RAM.
- **Units/version drift:** fixed-point raw units, JSON integer precision, Unity/Godot metres versus Unreal conversion, axes and normals require golden fixtures. Reject values beyond exact host decoding limits or version the encoding; do not assume all JSON readers preserve arbitrary 64-bit integers.
- **Scope leakage into launch:** Windows-first packaged proof is not a universal signed public release; source test success is not installed-engine or Internet certification.

## 9. Future hooks, without implementation

- **Mechanics Transplant:** versioned requirements/capabilities, namespaced component/system ownership, immutable mechanic dependencies and binding reports can later support validated transplantation.
- **Mechanic registry:** package IDs/content digests/provenance and requirements are enough preparation; no discovery/marketplace/account service now.
- **Fusion:** explicit dependency conflicts, namespace ownership and migration compatibility provide a future composition boundary; no automatic merge of arbitrary mechanics now.
- **Browser play:** keep schema/identity/input messages transport-independent and assets separately profiled. A future web presentation client can join a remote authority; no WebGL runtime, WASM simulation, browser network transport or web distribution promise in this program.

## 10. Historical initial task recommendation (superseded by checkpoint and amendment)

After approving this roadmap, start **XP-001: typed package/world/session identity contracts, epoch envelope fixtures, and the supported-profile ADR**. Its first engineering deliverable should be a conformance fixture linking one existing CGS and persisted SGC plan to one minimal canonical arena and a rejected-mismatch matrix. Include the small DCL runner fix so the baseline can be repeated through the supported command.

Do not begin with a Player skin or Internet lobby. XP-001 makes the next work concrete; XP-002 then closes the actual authority/compiler gaps before new gameplay or clients depend on them.

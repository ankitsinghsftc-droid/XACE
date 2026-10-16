> Current recovery reconciliation: [NEC001 recovery acceptance](recovery/NEC001_RECOVERY_ACCEPTANCE.md). This governs current baseline, verification, authorization and output paths.

> Reconstructed historical NEC001 document. Historical paths, test counts and completion statements below are not fresh recovery verification. Current recovery status is in AGENT_PROGRESS.md. Original sealed payloads remain missing; use the new persistent recovered baseline.

# XACE Native Engine Continuity Program

Status: NEC-001 through NEC-007 complete; NEC-008 through NEC-018 NOT STARTED.

Amended 2026-10-08 against the sealed local post-XP-022 implementation. Task IDs and ordering retained; section 1 amendments govern later task scopes.

Original design prepared 3 October 2026 against `d3ef383`; [NEC-001](NEC001_HANDOFF_AUDIT.md) supersedes its present-state assessment.

Scheduling constraint: **finish XP-019 through XP-022 first; run this program next; then undertake the major XACE UX/UI redesign.** This document neither replaces nor marks any XP task complete. Proposed task identifiers use `NEC-001` through `NEC-018` to avoid changing XP numbering.

## 1. Verified post-XP-022 handoff and reconciliation

The implementation is the local, uncommitted post-XP-022 tree in `target/xp016-work`:
revision `39ed07b8cd390619a479a3364dc903ee077a6d38` plus frozen working-tree inventory
`4d728ba9752124388cf451f7fd4492f2d87b4562fbdc965b19908dc389ac636a`.
The original design audit at `d3ef383` is historical. The owner supplied the sealed
folder and authorized NEC-001 while external release gates remain open.
[NEC-001 audit](NEC001_HANDOFF_AUDIT.md), [ownership ADR](adr/NEC-001-native-authoring-ownership.md)
and [evidence](recovery/evidence/nec001-20261015/summary.json) govern current claims.

### 1.1 Engineering versus release gate

Accept the sealed local XP-022 engineering profile for NEC-001. Do not rewrite its
historical seal/status fields. REL-01 through REL-05 in [the release ledger](XP022_RELEASE_GATES.md)
remain OPEN with original thresholds. This authorization permits engineering
continuation only; original combined public-release acceptance is not passed.
NEC-002 through NEC-007 were subsequently authorized and completed; NEC-008 through
NEC-018 remain NOT STARTED until further instruction. See
[NEC-002 completion](NEC002_AUTHORING_IDENTITIES.md) and
[NEC-003 completion](NEC003_NATIVE_AUTHORING_CONTRACTS.md) and
[NEC-004 completion](NEC004_UNITY_AUTHORING.md) and
[NEC-005 completion](NEC005_GODOT_AUTHORING.md) and
[NEC-006 completion](NEC006_UNREAL_AUTHORING.md) and
[NEC-007 completion](NEC007_NATIVE_ADOPTION.md).

Pinned Windows x64 versions: Unity 6000.4.9f1, Godot 4.6.3-stable official,
Unreal 5.7.4-51494982+++UE5+Release-5.7. Installed-host versions do not prove native
adoption or packaged native games. NEC-013/015 must select and prove their build
backend/configuration before shipping; broad manifest ranges are insufficient.

### 1.2 Current reusable source trace

- **E01 — Project adoption shell: implemented, conversion incomplete.** [project_creator.py](../packages/project-system/project_creator.py), `import_engine_project`, validates an engine inventory, calls template-based `create_project`, and stores `engine_project_path`. [engine_project_inventory.py](../packages/project-system/engine_project_inventory.py) detects all three engine roots and inventories references, with a default per-category limit of 500. This is not complete scene deserialization. [builder_server.py](../packages/builder-workspace/server/builder_server.py), `/api/project/import-engine`, additionally attempts adapter installation and reports that separately.
- **E02 — Migration preview: partial.** [engine_migration_wizard.py](../packages/project-system/engine_migration_wizard.py), `materialize_manual_migration_draft`, creates reversible preview records. Godot extraction reads node headers; Unity extraction reads `m_Name` lines; Unreal extraction reads textual actor markers or emits a map reference. `_starter_actor_parts` fabricates starter defaults rather than preserving original transforms/gameplay. Binding candidates use preset event associations. Scripts/plugins/input maps become manual-work items. The Builder `/api/project/migration/manual-plan` route is preview-only; no complete migration apply workflow was found. Tests verify records, unchanged source files and reversal, not original-game behavioral equivalence.
- **E03 — Adapter file lifecycle: implemented foundation.** [adapter_installation.py](../packages/project-system/adapter_installation.py) tracks owned file hashes, backups, install/update transactions, rollback and uninstall conflicts. This is reusable file ownership/recovery infrastructure, not an atomic CGS-plus-native-scene transaction. [adapter_package_versioning.py](../packages/project-system/adapter_package_versioning.py) supplies checksums, runtime dependencies and broad engine version ranges; those ranges are not installed-version certification.
- **E04 — Assets: useful but separate mechanisms.** [asset_import_workflow.py](../packages/asset-registry/asset_import_workflow.py) scans, copies or links supported files, hashes them and suggests repairs. Types are sometimes inferred from names/extensions. [file_watcher.rs](../packages/asset-runtime/src/hot_reload/file_watcher.rs) and [reload_coordinator.rs](../packages/asset-runtime/src/hot_reload/reload_coordinator.rs) provide watcher/reload primitives; the coordinator skips deleted and unregistered files. No general native authoring reconciliation pipeline was found. [engine_sync_receiver.py](../packages/asset-registry/engine_sync_receiver.py) updates asset-resolution records, not arbitrary CGS authoring.
- **E05 — Semantic presentation: implemented subsets.** [semantic_binding_status.py](../packages/asset-registry/semantic_binding_status.py), asset preflight, native applicators and [player_presentation.py](../packages/project-system/player_presentation.py) provide typed references, per-engine binding status, fallback/readiness rules and Player presentation validation. They are not native animation graph importers. Required gameplay geometry and cosmetic resource availability must remain distinct.
- **E06 — Native adapters: runtime presentation exists.** [Unity applicator](../adapters/unity/XaceDeltaApplicator.cs), [Unreal applicator](../adapters/unreal/XaceDeltaApplicator.cpp) and [Godot applicator](../adapters/godot/xace_delta_applicator.gd) mirror entities and supported playback and process rollback cleanup. [Unity runtime bootstrap](../adapters/unity/XaceRuntimeBootstrap.cs) and [editor Play bootstrap](../adapters/unity/Editor/XaceUnityPlayBootstrap.cs) create adapter components; this alone is not a pinned package/runtime launch-and-build pipeline. Native scene authoring and continuous reconciliation remain missing. The generated Godot editor plugin in `builder_server.py` has empty enter/exit hooks.
- **E07 — Explicit field edit-back: partial.** [entity_inspector.ts](../packages/builder-workspace/src/preview/entity_inspector.ts) sends Builder live preview edits and explicit saves. [state_authority.py](../packages/builder-workspace/server/state_authority.py) permits durable commits only for primitive `set_component_field` values. [ws_message_router.py](../packages/builder-workspace/server/ws_message_router.py), `_handle_engine_edit_commit`, checks accepted preview identity, hashes/schema and adapter sequence, then uses GDE. This does not capture normal native editor activity, and its newer-CGS primitive merge permission is not a three-way same-field conflict algorithm. [project_manifest.py](../packages/project-system/project_manifest.py) declares `bidirectional_editing: False`.
- **E08 — Mutation authority and recovery: reuse, extend narrowly.** [typed_operation_executor.py](../packages/gde/src/domain_dsl/typed_operations/typed_operation_executor.py) has a closed typed operation grammar and copy-based batch application. [package_authoring.py](../packages/prompt-intelligence/src/typed_operations/package_authoring.py) and [gameplay_catalog.py](../packages/gde/src/domain_dsl/typed_operations/gameplay_catalog.py) support package-driven authoring. [cgs_persistence.py](../packages/builder-workspace/server/cgs_persistence.py) provides locking, atomic writes, snapshots and recovery. Prompt apply in `ws_message_router.py` includes GDE, compilation, persistence, reload and recovery hooks. Optional adapter validation checks connectivity, not durable native-scene equality. The field-edit handler is not equivalent to the full prompt-apply recovery path.
- **E09 — World Contract: extensible semantics, bounded geometry.** [world_contract_v3.py](../packages/schema-factory/src/world_contract_v3.py) validates project-defined schemas, capabilities, relationships, typed asset roles and actor-instance bindings. It compiles from CGS; compiled `world.json` is not independently authoritative authoring. [profiles.json](../packages/core/src/world/profiles.json) currently registers `world.aabb.v1`. The compiler requires its authoritative boxes to have identity rotation/scale and no parent, with bounded fixed-point coordinates. It does not support arbitrary terrain, mesh collision or engine physics. Do not hide this limitation behind richer native artwork.
- **E10 — Playable packages: strong foundation.** [playable_package.py](../packages/project-system/playable_package.py) verifies Factory/SGC/world provenance, exact runtime support, bounded archive paths and checksums, and stages installation. The current profile is Windows x64 with a trusted `runtime/xace_runtime.exe`, World v2/v3 and declared executor contracts. Presentation variants are separated from gameplay identity. This is not an arbitrary native project importer or a runtime-independent export.
- **E11 — Player and local lifecycle: implemented profile.** [apps/xace-player/player.gd](../apps/xace-player/player.gd) loads verified package data and starts/connects to Rust authority; loss freezes gameplay. [player_launch.py](../packages/builder-workspace/server/player_launch.py) validates the installed release and saved-project/package match. [player-launcher](../packages/player-launcher/src/main.rs), [session.rs](../packages/player-launcher/src/session.rs), [distribution.rs](../packages/player-launcher/src/distribution.rs) and [job.rs](../packages/player-launcher/src/job.rs) provide process ownership, admission, installation and session primitives. The current Builder service rejects a stale packaged game and asks for an updated package; it is not yet universal project-specific native build preparation.
- **E12 — Live authority: preserve the stronger current boundary.** [engine_bridge.rs](../packages/runtime-core/src/engine_bridge.rs), `queue_feedback`, rejects gameplay feedback from admitted live presentation clients. [runtime_orchestrator.rs](../packages/runtime-core/src/runtime_orchestrator.rs) processes allowed feedback at tick start on the other path. Editor proposals must never be smuggled through presentation feedback or weaken live-client authority protections.
- **E13 — Shipping/exit: mixed maturity.** The Builder handoff route copies adapter sources and metadata. [xp008_player_build.py](../tools/xp008_player_build.py) exports a real Godot Windows Player with a bundled runtime. [CLI build](../packages/cli/src/commands/build.rs), `generate_artifact`, writes adapter configuration JSON; [CLI deploy](../packages/cli/src/commands/deploy.rs) returns not implemented. No complete native gameplay source exporter was found. Preserve the working Player packaging foundation instead of treating the older CLI comments as shipping implementation.
- **E14 — Actual installed-host evidence now exists.** [XP-022 certification](XP022_ENGINEERING_CERTIFICATION.md) and sealed `native-v2` / `hosts-final` reports prove all three pinned installed readers and mixed sessions, not merely named socket clients. Fifteen conformance vectors per engine and four-host applied projections/events are retained. These do not certify native editor authoring or engine-built shipping. Fresh checks are separately recorded in [NEC-001 evidence](recovery/evidence/nec001-20261015/summary.json).

### 1.3 Confirmed handoff and mandatory amendments

- XP-016/017 implement canonical world/session readers and actual installed
  mixed/four-host parity. Reuse them; native editor serializers remain future work.
- XP-018 implements host-owned approval, parent/artifact/proof identity and isolated
  deterministic candidate execution. Only host-registered, system-read-only
  configuration replacement is supported. World/capability/entity/state migration
  fails closed; there is no generic script or scene migration API to reuse.
- XP-019 implements future-tick prepare/readiness/durable decision/publication.
  Failure after decision ends the session; restart refuses its parent. It does
  not supply resumed play, editor undo or native authoring transaction recovery.
- XP-020/022 implement exact historical replay and bounded segmented archives,
  including the verified two-hour archive. Quota/completion metadata must survive
  export. Replay is neither save migration nor a complete source archive.
- XP-021 supplies isolated inspection, trusted creator control and a UI shell.
  Native authoring conflicts, proposal approval and recovery flows remain missing.
- XP-022 seals engineering evidence, the unchanged production host, installed native
  proofs, unsigned release and local faults. REL-01–05 remain open.

**NEC-007/009/010/011/012 amendment:** structural/world edits use durable authoring
followed by an explicit stopped-session rebuild and new admission. Only eligible
approved configuration changes use XP-018/019 live activation. Keep the old
immutable runtime/package until stop; never silently reset/migrate it. General
live world migration requires separately scoped prerequisite work, outside NEC-001.

**NEC-008/009 amendment:** add a minimal three-way review/recovery surface and a
separate native authoring journal. XP-021 inspection and XP-019 activation do not
supply these; preserve all existing guest/creator and live-feedback fences.

**NEC-016/018 amendment:** preserve replay segment/completion/quota metadata and
certify dependency-closed restore/rebuild, save compatibility and distribution/
continuing-use terms. Cargo MIT metadata and third-party notices do not establish
rights for every imported asset/plugin. REL gates retain their claim-specific
conditions; external release claims cannot inherit an unpassed gate.

### 1.4 Verification and future fixture contract

[NEC-001 audit](NEC001_HANDOFF_AUDIT.md) sections 4–7 and its evidence JSON distinguish
fresh conformance checks from retained editor/soak evidence. No production source
was changed. The source ZIP, sealed payloads and detailed certification files remain
unchanged. Only the live master plan has an addendum; NEC records have new identities.
The ownership ADR assigns every promised representation to an owner and proof task.
Required fixture assertions and unmeasured scale budgets are explicit; no proposed
editor API is described as implemented.

## 2. Exact product promise and bounded v1 scope

After all NEC gates pass, the promise is:

> For the certified engine versions and Windows x64 profile, you can adopt a supported portion of an existing native project without discarding its content, develop XACE gameplay alongside native engine content, review and reconcile supported changes, press Play in your engine, and ship a normal engine-built game with a pinned local XACE gameplay runtime. Your source and versioned project data remain accessible. Shipped local gameplay needs neither Builder nor XACE cloud services.

The public statement must link to a capability and loss matrix. Full completion requires **Unity, Godot and Unreal**, each with a pinned editor/build version and real engine-built release proof. Exact versions are selected from actual XP-022 certification at NEC-001; broad manifest ranges are insufficient. Windows x64 is the initial shipping platform, not an implied console/mobile/macOS/Linux claim.

V1 must support stable adopted entities, rename/delete/reparent, authored transforms, native asset replacement, semantic animation/audio bindings, supported inputs, presentation settings and declared World v3 metadata. Cosmetic meshes/materials/animations/audio remain native content. Physics-affecting changes require a supported canonical geometry representation and validation.

Existing gameplay is adopted incrementally using verified known mappings and reviewed package/configuration work. Arbitrary scripts/Blueprints are preserved and classified, never claimed as translated. An unmigrated gameplay-critical dependency blocks declaring that adopted slice playable/shippable. It does not force the rest of the native project to be deleted or restarted.

Runtime-independent native source export, universal code translation, arbitrary terrain/rigid-body simulation, all engine/plugin versions, marketplace features and the UX redesign are non-goals. A shipped developer game may require its own online service for its own features; it must not acquire an accidental XACE license/cloud dependency. XACE relay outage may interrupt relay multiplayer, but not local gameplay. Preserve reachable local/LAN behavior only where explicitly certified.

## 3. Ownership model

Ownership is declared per property/role, not assigned vaguely to an entire GameObject/Actor/Node.

- **XACE-owned:** CGS gameplay components/defaults, systems/rules, input action meaning, authoritative collision/query geometry, World semantic declarations/relationships, gameplay event contracts, required runtime executors and live state. GDE owns durable definition mutations; runtime and Mutation Gate own live mutations. Factory output is derived.
- **Engine-owned:** mesh/material resources, textures, native animation/audio content, lighting, cameras and UI presentation within declared constraints, decorative objects and their transforms, presentation-only hierarchy, native project/build settings and engine/plugin code not claiming authority over XACE state.
- **Synchronized projections, never dual authority:** canonical object identity mapped to native identity; gameplay spawn placement reflected in a native marker; a semantic event contract mapped to a native animation/audio locator; canonical input action mapped to an engine physical binding. Each field declares an owner, permitted proposal directions, materializer version and validation policy. A native change to a gameplay marker is a proposal, not a new authoritative value.
- **Opaque retained content:** unsupported scripts, graphs, assets or plugins, with explicit dependencies and manual-work disposition. Preservation is not execution permission or compatibility certification.

Separate canonical transform, authored initial placement, render interpolation and cosmetic child offsets. A decorative child's reparent changes only presentation; an authoritative collider's reparent may invalidate geometry and requires a proposal or refusal. Engine play-mode motion must never be mistaken for authored placement. A user may explicitly request capture of a supported play-mode value, which remains a proposal.

Semantic ownership is also split: event identity/payload/gameplay timing is XACE-owned; native clip/state/resource locator and cosmetic parameters are engine-owned binding data. Bindings selected from XACE are outbound proposals to that owner. Do not automatically rewrite a native controller graph. Keep native locators outside gameplay predicates and canonical gameplay hashes unless a declared gameplay dependency truly changes.

## 4. Import and migration architecture — Workflow B

1. **Read-only discovery:** reuse E01/E04, report exact engine version, file counts, truncation, plugin/script dependencies, unsupported formats and source hashes. No native project launch, script execution, package installation or source modification occurs during inventory.
2. **Trusted native extraction:** for data that cannot be safely interpreted offline, offer an explicit isolated-copy editor extraction step after the developer trusts opening that project. Only supported serialized properties become records. An engine may execute project/editor code while loading: do not label editor extraction a no-code sandbox. If unwanted execution cannot be disabled, refuse automatic extraction until the owner accepts that boundary; keep the offline inventory available.
3. **Choose adoption scope:** scene/subscene and entity subsets; classify each as XACE gameplay, native presentation, deferred/manual or excluded. Preserve full originals and dependency edges. Require a disposition for every gameplay-critical dependency.
4. **Build a typed migration plan:** source hashes, stable IDs, normalizations, proposed CGS/World/binding operations, package requirements, exact native writes, reversible before-images and loss report. Replace E02's fabricated defaults with extracted supported values. Never infer health/input/event behavior from an entity name.
5. **Validate and review:** GDE/Factory/SGC, asset readiness, geometry/profile limits, executable admission, source-digest freshness and dependency closure. Show unsupported behavior and which original components must be disabled or rewritten. Refuse cycles/dangling bindings and unresolved assets before commit.
6. **Apply through the shared authoring transaction:** stage both sides, commit/recover as in section 7, then establish a verified reconciliation baseline. If a live session exists, stage a candidate separately; XP-019 alone activates it.
7. **Prove the adopted slice:** compare defined behaviors against original-project assertions and expected canonical inputs/state/events. Human review establishes intended behavior where the old game is nondeterministic. Only then enable XACE-controlled Play for that slice.

Legacy gameplay outside the adopted slice may continue operating on its own unrelated native state. It cannot write XACE-owned entities or feed unvalidated engine physics into authoritative contacts. A cross-slice interaction needs an explicit supported input/event contract; if none exists, that dependency blocks migration. Arbitrary legacy code may be impossible to police exhaustively, so certification combines authority-path checks, ownership diagnostics and tested behavior, not a claim of sandboxing all native code.

## 5. Stable identity architecture

NEC-002 implements a versioned **authoring identity mapping** in project-system,
bound to the existing manifest and stored under `.xace/authoring/`, distinct from
runtime EntityID and package content hash. The typed contract includes namespace,
branch, canonical object ID, persistent native document/object locator, scene,
prefab definition/instance, optional World binding, generation, tombstone and
provenance. See [the implemented contract](NEC002_AUTHORING_IDENTITIES.md).
Unity, Godot and Unreal metadata/capture are complete in NEC-004/005/006
within their documented native profiles.

Assign opaque IDs once during an approved metadata transaction. Persist them in version-controlled sidecar/native metadata. They are authoring identities and must not introduce random runtime behavior. Runtime entity IDs remain governed by deterministic runtime allocation; resolve runtime instances through the existing world binding map.

Native persistent IDs are engine-specific locators, not canonical gameplay semantics. NEC-004/005/006 validate Unity serialized asset/object identities, Unreal package/actor GUID locators and Godot resource UIDs plus explicit node metadata against the pinned versions and their stated profiles. Node paths, display names and array positions alone are unacceptable.

Rules: rename/move/reparent preserves identity; duplicate creates a new ID with provenance; prefab definition and each instance remain distinguishable; delete creates a tombstone; undo may restore the same authored object without reusing a destroyed runtime EntityID; copy/paste collisions are detected before linking. Branch/clone conflicts require an explicit namespace/identity resolution. Missing metadata or ambiguous native identities yield an unresolved mapping, never name-based silent reassociation.

## 6. Engine-change capture — Workflow C

Each editor integration emits a bounded normalized **authoring snapshot/delta** after a supported saved edit or explicit capture. It contains schema/version, engine/plugin identity, baseline revision, object/property IDs, before/after hashes, native dependency locators, ownership classification and authoring transaction provenance. No arbitrary code or executable callback is serialized.

Editor notifications are hints. Use debouncing, save checkpoints and deterministic rescans to recover missed events, external asset edits and editor restarts. Compare source fingerprints before applying; unsaved/dirty scenes require Save, explicit draft capture, or cancellation. Exclude runtime-created mirrors and known generated outputs; suppress write echo using transaction IDs plus observed hashes, not an unbounded ignore timer.

Required operation behavior:

- **Add:** assign/adopt identity; decorative object can stay engine-owned; gameplay participation proposes actor/World/component additions.
- **Delete:** tombstone and dependency analysis; block dangling roles, active gameplay contracts and accidental cascade deletion. Offer explicit dependent removal/rebinding.
- **Rename/move:** preserve ID; update native locator/display metadata and references; never delete-and-recreate by name.
- **Reparent:** compare parent IDs and local/world transforms together; propose changes only if canonical representation supports them. Cosmetic hierarchy can remain native.
- **Transform:** distinguish decoration, spawn pose and authoritative geometry. Normalize units/axes/fixed precision; report quantization. Do not approximate unsupported rotated colliders silently.
- **Asset import/replace:** maintain logical AssetReference identity when explicitly replacing; record new content/dependency hashes. Detect type/semantic incompatibility and missing references. New file does not automatically become a new gameplay asset.
- **Animation/audio binding:** native locator change produces binding reconciliation; event timing or gameplay event meaning becomes a GDE proposal. Native graphs remain intact unless a specifically supported edit was reviewed.
- **World metadata:** validate declared World v3 schema/capability/relationships; geometry uses its separate supported profile.
- **Input:** native physical key/control changes update versioned presentation binding; action meaning, controllers, quantization or authority constraints require canonical proposal and session compatibility review.
- **Presentation settings:** permitted engine-owned edits reconcile with resource/build readiness; settings affecting gameplay/geometry are reclassified and reviewed.
- **C#/C++/GDScript/Blueprint changes:** detect dependency/hash drift where possible and flag the affected adoption contracts. Preserve source; do not execute it to infer behavior or silently modify CGS. A reviewed supported translator is an extension, not a default.

## 7. Reconciliation and recovery — Workflow D

### 7.1 Three-way comparison

Store the last jointly acknowledged baseline `B`, current canonical authoring view `X`, and normalized engine authoring view `E`, with per-field owner and source identity. The baseline includes actual values or immutable content-addressed references, not only opaque hashes.

- `X=B` and `E=B`: no operation.
- One side changed: construct the owner-appropriate change/proposal; apply only within its approval policy.
- Both sides converge to the same normalized value: one idempotent change.
- Disjoint property changes with no semantic dependency conflict: compose and validate.
- Same property differs, delete-versus-edit, duplicate identity, reparent-versus-move, competing asset replacement or cross-field constraints: explicit conflict. No timestamp winner and no blanket primitive-field overwrite.

Automatic safe merge means preparing an unambiguous result. Gameplay-affecting application still uses explicit approval or an already granted narrowly scoped policy through normal XACE validation. Cosmetic-only automatic application may be enabled per project with an audit trail. Conflict resolution records the human choice and both originals; approval is bound to exact baseline/X/E hashes and expires on new edits.

### 7.2 Transaction ownership and crash protocol

Extend project-system with a reconciliation coordinator around existing GDE/persistence and adapter transactions. Do not put gameplay logic in native adapters or create a second mutation executor. Proposed durable states:

`Captured -> Proposed -> Validated -> Approved -> Prepared -> CommitDecided -> Materialized -> Verified -> BaselineAdvanced`, with `Aborted`, `RecoveryRequired` and `Conflict` terminal/interruption states.

The journal records operation IDs, source CAS hashes, staged canonical/native artifacts, before-images, approval identity, checksums, per-participant receipts and active runtime epoch. Serialize participating authoring writes; acquire resource locks in stable order. Native editor integration blocks application while its target documents remain dirty or cannot be locked. External modifications are detected by a final fingerprint check; an engine lock is not assumed to lock external processes.

Before durable decision, failures discard staged artifacts and leave the old baseline. After decision, retry idempotent materialization or restore verified before-images according to the journal. Do not claim one filesystem rename makes multiple editor files and CGS globally atomic. If a newer independent edit prevents compensation, preserve all versions, block Play/build of the mixed revision, retain the prior verified playable package and require explicit recovery. Never overwrite a user's post-transaction work to fake successful rollback.

Baseline advances only after both canonical artifacts and native saved files have verified receipts. Crash recovery inspects the journal and actual bytes, not UI success flags. Disk-full, failed save, interrupted engine import/cook, reconnect, cancellation, permission denial and plugin crash must each have a tested outcome.

Authoring transaction IDs are distinct from session epoch IDs. Only eligible configuration changes to a running game pass through XP-018/019 candidates and activation; structural/world edits require explicit stop, rebuild and new admission. Until then the old runtime continues on its immutable package. Postpublication recovery follows XP-019 history/fencing rules, not authoring before-image restoration. This distinction prevents editing a scene from silently changing a live game.

## 8. Durable XACE-to-engine authoring — Workflow A

Extend the same engine-specific serializers with allowlisted writers. Write persistent native resources, scene markers, prefab/instance bindings, supported authored placement, input binding assets and semantic presentation mappings through native serialization/editor transactions. Never treat runtime mirror objects as the durable project representation.

XACE-owned canonical fields materialize into explicitly owned native fields/markers. Requests to change engine-owned fields are staged native authoring operations with source CAS and reviewed write sets. Preserve unknown properties, scripts, prefab overrides, metadata and engine-generated references. Do not rewrite whole scenes from incomplete dictionaries or patch binary Unreal assets as text.

New projects get an ordinary native project or an approved integration in an existing one, with visible generated/owned files, dependency manifest and meaningful defaults. Materialize supported World objects and bind native resources; preserve the freedom to replace artwork. Returning to XACE captures changes and runs section 7; returning to the engine applies the next verified materialization. Repeated no-op sync must produce no semantic or file churn within the declared deterministic serializer profile.

Supported geometry is a real scope gate: preserve terrain or complex meshes as native visuals but do not certify their contacts. Allow an explicit reviewed collision proxy only if the developer accepts its gameplay meaning. A game requiring unsupported canonical geometry needs a separately reviewed backend/profile, not hidden engine physics. Do not make broad geometry development an unbounded prerequisite of this focused program.

## 9. Native-engine Play — Workflow E

One shared native host lifecycle contract serves Unity, Unreal, Godot and Player. Reuse E10/E11 and XP session integration rather than creating three gameplay runtimes.

`Native Play -> verify saved revision/bindings -> select pinned trusted runtime + exact package -> launch owned local authority or explicitly join compatible authority -> admission/readiness -> bind canonical IDs to native content -> ticked input and presentation -> clean stop`.

Default v1 packaging is a **bundled local sidecar runtime** on Windows x64. It is part of the game's distribution, not a separately installed XACE service. In-process FFI is a later alternative where justified; it is not necessary to meet the runtime-embedded product promise. Target platforms that forbid sidecars are out of v1 scope.

Editor Play may use local build tools to prepare an explicit new package, but may never silently fall back to stale gameplay. Published builds execute prebuilt verified binaries only. The runtime's declared executor registry must match package system implementations; a data manifest cannot certify nonexistent native code. New generated/custom gameplay executors require a trusted reproducible build/admission step on the creator/build machine.

Separate persistent native content from runtime mirror roots. Prevent duplicate spawns, conflicting native physics writes and duplicate input collectors. Native interpolation/animation/audio follows canonical state/events. Test Play/Stop, scene changes, Unity reload configurations, Unreal PIE instances and Godot reruns without leaking runtime processes or reusing another session's credentials. A runtime crash visibly freezes/fails the game; no fallback to native gameplay authority. Builder can be entirely closed.

## 10. Native build and shipping — Workflow F

Creator/CI pipeline: **approved saved revision -> GDE/Factory/SGC/package verification -> admitted runtime build selection -> engine cook/build/export -> stage runtime/package/native resources -> verify installed layout -> sign/package release -> clean-machine proof**.

Extend existing package/distribution manifests with an engine build receipt that references, rather than duplicates, gameplay identity: package/World/plan/runtime digests, executor ABI/contracts, native engine version/build target, adapter digest, cooked resource/binding closure, build settings hash and notices. Native import GUIDs/paths remain in presentation provenance; never become gameplay conditions. Native compiled/cooked resource verification is distinct from source asset hashing.

Unity builds, Unreal packaged builds and Godot exports each include executable authority, native adapter, exact gameplay package, required cooked content and approved dependency notices. Resolve assets from deployed engine resources; resolve writable saves/logs from per-user storage. Test read-only install directories, Unicode/spaced paths, relocation, offline startup and no development machine paths. No player-side Cargo, Python, Node, Codex, provider account or engine editor; no JIT compilation of downloaded gameplay.

Pin runtime selection locally with publisher-controlled trust metadata outside untrusted package assertions. Hashes establish integrity against a trusted identity; a self-signed or self-hashed package is not automatically trusted. Release updates stage complete versions and retain previous verified versions. Define save/version compatibility before activation; incompatible saves prompt a documented migration or refusal without data loss. Reuse XP historical artifact retention and existing save migration infrastructure; do not claim that this program implements every campaign save feature.

Offline execution cannot require startup activation, cloud license checks, remote revocation fetches, package downloads or AI calls. Optional update/telemetry failures must not prevent valid installed local play. Network sessions retain their declared connectivity requirements. Runtime redistribution rights, notices and continuing-use terms must be explicitly settled for release; no top-level LICENSE/NOTICE file was found by this audit's file search, so current code presence alone is not distribution permission evidence.

## 11. Continuity and leaving XACE — Workflow G

Provide an offline, versioned **project continuity archive**, built on existing package/checksum/debug export and XP-020 artifact retention. It is a source/project archive, not a replacement playable format.

Mandatory contents: CGS and schemas; GCL and system/rule declarations; available system implementation source and generated source with provenance; World source plus compiled contract/manifests; semantic/native bindings and identity map; assets or explicit external-reference/dependency/license inventory; package/executor/runtime manifests; native project files or a verified portable project archive; migration plans, approvals, loss reports, baseline snapshots and version history; build recipes/tool versions; documented runtime requirements and redistribution notices. Include relevant saves/migrations only by explicit selection; exclude credentials, tokens and unrelated personal data. Missing externally licensed assets or unavailable implementation source are prominent blockers/limitations, never silently omitted.

The developer keeps:

- **Directly usable native work:** original/edited scenes, art, animation/audio content, scripts, project settings and supported binding metadata. Removing the adapter cannot erase unrelated work.
- **Portable, documented XACE work:** definitions, World/semantic data, sources and history that remain inspectable/rebuildable with the retained tools/runtime profile.
- **Continuing shipped gameplay:** admitted local runtime and package remain usable without Builder or XACE services, subject to explicit shipped licensing terms. A native editor build can still consume that pinned package without opening Builder.
- **Manual migration if removing runtime:** replace XACE systems, event scheduling, canonical geometry, input authority, saves and network behavior with equivalent native implementations. Keeping original native files does not magically convert newly authored XACE gameplay.

Provide detach modes: keep runtime and native integration; archive authoring but keep shipping; or remove adapter-owned integration with a loss report. Before removal, capture continuity archive and owned-file checksums. Modified adapter files or native references create conflicts, not destructive cleanup. Test restore on a clean developer workspace. A cache export alone is not adequate ownership continuity.

## 12. Runtime-free export assessment

Feasible for a deliberately restricted portable gameplay subset, but no matching native backend currently exists. Translating arbitrary generated Rust systems, engine plugins or unsupported native gameplay is not generically solvable by a format exporter. A native implementation must reproduce numeric precision, schedule, mutations, events, RNG, geometry, input, snapshots, save migration and any network behavior actually promised. Generating an interpreter that recreates XACE's runtime semantics under another name would not establish independent maintainable native gameplay.

Value: native debugging/customization and a stronger exit option. Cost/risk: three compiler backends, source mapping and editable-code conventions, semantic drift, parity certification, and a permanent compatibility burden; potential loss of determinism if replaced with native physics/timing.

**Planning estimate, not a measured commitment:** a bounded single-engine proof for a small closed executor set is roughly 8–12 engineer-weeks after an IR/semantics spike. A supported three-engine source exporter is plausibly 12–24 engineer-months, plus ongoing parity maintenance; arbitrary custom code has no credible fixed estimate. These estimates are architectural judgments, not vendor research or verified delivery dates. An eventual 2–3 week inventory/prototype would refine them.

Recommendation: **post-launch research program, not a blocker for NEC or private alpha.** The pre-alpha anti-lock-in commitment is local pinned runtime continuity, usable native content, complete versioned source/data archive and honest dependency disclosure. Do not market that as runtime-free export.

## 13. Security and trust boundaries

- Import data is untrusted. Enforce bounded parsing, canonical paths, no traversal/symlink escape, resource limits, no embedded executable launch and no automatic third-party plugin install.
- Native editor extraction is explicitly trusted code execution when the engine loads project/editor scripts. Separate it from safe inventory and perform it on a staged copy where practical. Do not promise an engine safe mode without proving it for that version.
- Authoring endpoints require local project/session capability and approved roots. A live game client never obtains GDE, file-writing, package-admission or debugger control privileges.
- Typed operations validate independently at GDE; LLMs and native plugins cannot bypass checks. Approval binds to immutable source/target identities and concrete writes.
- Reconciliation writes only declared owned properties/files. Script/source rewriting is opt-in manual work with a diff, not background synchronization.
- Trusted executors and runtime binaries come from verified build provenance. Arbitrary binaries in an imported project do not become trusted because their hash is in a manifest.
- Logs/continuity exports redact credentials and restrict absolute-path/personal metadata. Local offline capabilities must not depend on retained authoring/provider credentials.
- Keep I1–I15 and D1–D15. Runtime feedback, world geometry and input remain in their established deterministic boundaries; editor authoring is a distinct transaction channel.

## 14. Real-engine certification strategy

Create one non-trivial pre-existing project per engine **before adoption**, not a generated XACE demo relabeled as an import. Each should contain at least two scenes/maps, at least 50 authored objects, duplicate display names, prefab/instance relationships, nested decorative hierarchy, native materials/mesh content, animation/audio, physical input bindings, supported collider/spawn metadata, one known supported behavior mapping and one intentionally unsupported script/plugin dependency. Unreal's binary maps/assets must be real engine-saved files. Exact fixture bytes, licensing and expected behaviors are versioned.

For each engine certify this full chain: link/inventory -> select scope -> preview and reject once -> approve -> verify preserved files and meaningful CGS/World/bindings -> edit gameplay in XACE -> native Play with Builder closed -> modify native content -> reconcile -> rename/move/delete/duplicate/reparent -> explicit same-field conflict -> resolve -> native Play again -> native engine release build -> clean-machine install/run offline. Repeat a new-project Workflow A as well as adoption Workflow B.

Fault matrix includes crash before/after each journal transition, engine dirty document, independent edit during apply, CAS mismatch, disk-full/save failure, locked file, lost notification, duplicate event, interrupted import/cook, tampered runtime/package, wrong geometry profile, missing binding, input schema mismatch and failed migration. Validate actual post-recovery bytes, baseline IDs, authority hashes and no orphan process. Include the journal's irreconcilable newer-edit case and require visible recovery, not a false all-green rollback.

Reuse XP-020 canonical input traces to compare state/events and per-tick authority hashes between Player, native editor Play and exported game for the same admitted package. Compare normalized client-applied projections; echoed host hashes and screenshots alone fail. Record native collision overlay versus authoritative contacts to expose visual/geometry mismatch. Capture real keyboard/controller actions for usability as well as deterministic scripted input for parity.

Clean-machine proof uses an actual clean supported Windows VM/PC with no Builder, repo, editor, developer toolchains or provider account. Removing PATH entries on the development machine is not sufficient. Block network/DNS and verify successful local gameplay from the installed build; retain process and network observations. Repeat clean update/rollback and save compatibility tests. Internet features get separate service tests; offline proof must not claim Internet multiplayer.

Retain source commit and working-tree digest, engine/OS/tool versions, fixture hashes, runtime/package/cooked-content identities, exact commands, machine profile, journals, expected assertions, per-tick hashes, applied projections, failures and human walkthrough recordings. Tie every supported matrix cell to those artifacts. Set bounded scale/latency budgets in NEC-001 and measure them; start with 1,000 adopted objects, 100-operation edit batches and p95 capture-to-review under 2 seconds excluding engine import/compile on recorded hardware. Preserve XP-022 runtime budgets and declare smaller certified limits if measured evidence requires it.

## 15. Ordered implementation program

NEC-001 through NEC-006 are **complete** within their declared scopes; NEC-007 through
NEC-018 are **not started**. Dependencies refer to completed and verified outputs,
not merely merged code. Engine-specific tracks may be scheduled concurrently after
shared contracts stabilize; that is a future scheduling option, not delegation.

### NEC-001 — Freeze the post-XP-022 handoff and supported promise

- **Status:** COMPLETE. See [audit](NEC001_HANDOFF_AUDIT.md), [ADR](adr/NEC-001-native-authoring-ownership.md) and [evidence](recovery/evidence/nec001-20261015/summary.json). NEC-002 was subsequently authorized and completed as recorded below.
- **Purpose:** establish one honest start/release contract.
- **Problem solved:** the original design used an older checkout; the actual uncommitted XP-022 seal now anchors the handoff. Broad engine ranges still cannot certify a profile.
- **Reuse:** E01/E03/E09–E14; XP-018–022 contracts and proof matrix.
- **Scope:** audit actual XP-022 code; bind evidence; select one pinned version per engine, Windows x64, feature/geometry limits, scale budgets, ownership ADR and required fixture behaviors; assign gaps back to prerequisites.
- **Dependencies:** sealed XP-022 local engineering profile accepted by the owner instruction for NEC-001, with verified XP-018/019 restrictions. External REL-01–05 remain open.
- **Acceptance:** no assumed API remains an unverified dependency; each promised feature has owner, supported representation and proof target; geometry and code-translation limits visible.
- **Tests/proofs:** source-to-contract trace and rerun handoff conformance fixtures; inspect real XP proof artifacts.
- **Rollback/failure:** keep this program blocked at design stage for missing prerequisite profiles; preserve XP implementation priority.
- **Non-goals:** implement missing XP work inside NEC or claim universal engine/platform support.

### NEC-002 — Persist canonical authoring identities and baselines

- **Status:** COMPLETE. [Contract/completion](NEC002_AUTHORING_IDENTITIES.md) and
  [evidence](recovery/evidence/nec002-20261015/summary.json). Project-side metadata only;
  native capture/materialization and verified save receipts remain later tasks.
- **Purpose:** make edits durable across rename, move and restart.
- **Problem solved:** names/paths/runtime IDs cannot identify native authored objects reliably.
- **Reuse:** E01 project manifest, E09 World bindings, E03 ownership hashes, E08 persistence.
- **Scope:** versioned mapping/baseline records, project namespaces, prefab/instance distinctions, tombstones, metadata attachment plan, schema migration and journal references.
- **Dependencies:** NEC-001.
- **Acceptance:** rename/reparent preserves IDs; duplication creates distinct IDs; ambiguous/colliding metadata blocks association; old mappings migrate without reassigning objects.
- **Tests/proofs:** identity property tests, clone/branch conflicts, delete/undo, lost metadata and restore corpus.
- **Rollback/failure:** stage metadata changes; restore prior map on failure; never silently regenerate IDs.
- **Non-goals:** replace runtime EntityID allocation or encode native paths in gameplay.

### NEC-003 — Define normalized native authoring contracts

- **Purpose:** share reconciliation semantics across engines.
- **Problem solved:** raw editor objects and event callbacks lack comparable ownership/type/coordinate meaning.
- **Reuse:** E04 typed AssetReference, E05 binding contracts, E09 World schemas/profile, XP-016 conversions.
- **Scope:** bounded snapshot/delta and loss-report contracts, fixed-point/unit normalization, owned-field schema, allowlisted read/write capabilities, source versions, dependency edges and dirty-document handling.
- **Dependencies:** NEC-002.
- **Acceptance:** equivalent supported values normalize identically; lossy conversions are reported; unsupported geometry/hierarchy never becomes silently approximate canonical data.
- **Tests/proofs:** cross-language golden JSON, large integers, axes/normals, nonfinite/overflow values, nested hierarchy and malformed corpus.
- **Rollback/failure:** refuse snapshot admission and retain baseline without native writes.
- **Non-goals:** universal scene interchange format or new authoritative geometry engine.

Completed 2026-10-09: [implementation and boundaries](NEC003_NATIVE_AUTHORING_CONTRACTS.md),
[evidence](recovery/evidence/nec003-20261015/summary.json). 28 focused plus 191 existing
regression tests pass. No task renumbering/reordering or added task is needed.
NEC-004/005/006 must consume the capture/snapshot contracts, certify host-owned
field policies and document fingerprints, run the shared numeric golden corpus,
and implement staged native writes with inverse conversions. NEC-003 write-field
selection is not a materializer or save authorization. Dirty documents require
save and recapture; opaque critical dependencies block admission. Full native
reader/writer proofs and GDE adoption/reconciliation remain in their original tasks.

### NEC-004 — Unity editor reader, capture and staged writer

- **Purpose:** operate on real Unity-authored content.
- **Problem solved:** `m_Name` extraction and runtime bootstrap do not provide durable authoring.
- **Reuse:** E01/E03, Unity Editor assembly/bootstrap/validation, E06, NEC contracts.
- **Scope:** saved scene/prefab/instance identities, serialized allowlisted extraction, supported edit notifications/rescan, dirty-state checks and native staged writer; preserve unknown components/overrides.
- **Dependencies:** NEC-003.
- **Acceptance:** fixture entities/transforms/hierarchy/resources/input/bindings survive extract-save-extract; ordinary and duplicate names are distinct; play-mode changes are excluded.
- **Tests/proofs:** installed pinned Unity editor tests with actual scene/prefab files, missed notifications and reload settings.
- **Rollback/failure:** no write outside approved staged set; restore before-images or report conflicting newer edits.
- **Non-goals:** translate arbitrary MonoBehaviours or execute imported scripts during read-only inventory.

Completed 2026-10-09: [implementation and boundaries](NEC004_UNITY_AUTHORING.md),
[evidence](recovery/evidence/nec004-20261015/summary.json). 228 Python tests and 50 installed
Unity checks pass. Callable discovery/enrollment/capture and approved native
staging/recovery APIs consume NEC-002/003 contracts. Actual regular scenes,
prefabs/instances, resource/input/binding preservation, unknown-component retention,
missed notifications and both Play reload settings are covered. Unknown behavior
still blocks schema admission. These APIs do not commit CGS or advance baselines.
NEC-007/009/010 must integrate explicit enrollment, loss review, hash-bound writer
requests, retained recovery receipts and saved-source reopen requirements.
No task addition or reorder is needed. NEC-005 was subsequently authorized and
completed as recorded below.

### NEC-005 — Godot editor reader, capture and staged writer

- **Purpose:** support native Godot development alongside Player.
- **Problem solved:** node-header parsing and empty editor plugin do not capture persistent content semantics.
- **Reuse:** E03, existing Godot adapter/Player shared scripts and NEC-003 contracts.
- **Scope:** scene/resource/node identities and metadata, packed-scene instances, saved property/resource capture, editor undo grouping, staged resource serialization and rescan.
- **Dependencies:** NEC-003.
- **Acceptance:** nested scenes, renames/reparent and resource replacements retain correct instance identity; editor integration and Player use the same runtime protocol without sharing editor privileges.
- **Tests/proofs:** real Godot editor save/reopen/undo corpus, `.tscn` plus supported binary resource handling, duplicate node metadata.
- **Rollback/failure:** refuse ambiguous node identity; preserve last saved scene and mark required recovery on collision.
- **Non-goals:** GDScript translation or a separate Player-only authoring model.

Completed 2026-10-09: [implementation and boundaries](NEC005_GODOT_AUTHORING.md),
[evidence](recovery/evidence/nec005-20261016/summary.json). 239 Python tests and 74 installed
Godot checks pass. Actual text/binary PackedScene saves, external binary resources,
instance metadata, grouped editor undo, staged writes and fresh-process recovery
are covered. Capture/write requires selected saved scenes closed after explicit
save/discard; Godot 4.6.3 exposes no public unsaved-scene query. Unknown behavior
and native physics remain blocking, and inexact float materialization is refused.
The unchanged Player/runtime protocol grants no editor privileges. NEC-007/009/010
must integrate these boundaries, reviewed adoption and retained native receipts.
No added/reordered task is needed. NEC-006 was not started at NEC-005 closeout;
its subsequent completion is recorded below.

### NEC-006 — Unreal editor reader, capture and staged writer

- **Purpose:** adopt real Unreal maps/content.
- **Problem solved:** text actor markers cannot migrate native binary maps/assets.
- **Reuse:** E03, Unreal plugin/module/commandlet patterns, E06 and NEC-003 contracts.
- **Scope:** trusted staged-copy extraction, persistent actor/resource/instance mapping, allowlisted reflected properties, supported saved map edits, dependency and Blueprint drift inventory, native asset saves/undo transactions.
- **Dependencies:** NEC-003.
- **Acceptance:** real `.umap`/`.uasset` fixture produces meaningful entities/values, not MapReference stand-ins; unsupported partition/level/Blueprint features have explicit dispositions.
- **Tests/proofs:** pinned installed editor/commandlet plus interactive authoring, binary save/reopen and duplicate actor identity tests.
- **Rollback/failure:** never text-patch binary assets; preserve backup/copy and refuse untrusted execution or unsupported save.
- **Non-goals:** arbitrary Blueprint/C++ conversion or blanket World Partition certification.

**Completed 2026-10-10:** [NEC-006 implementation and profile](NEC006_UNREAL_AUTHORING.md),
[evidence](recovery/evidence/nec006-20261016/summary.json). 255 Python tests and 73 native
Unreal checks pass. The pinned editor captures actual saved actors and typed meshes,
with explicit identity/rekey, attachment continuity, Blueprint/dependency opacity,
trusted independent copies and native binary stage/reopen. Staging uses native
autosave semantics to retain package identity; publication binds source plus newly
referenced resource dependencies and retains before/displaced images. Actual editor
Undo/Redo and cold-process Python write requests are verified.

**Concrete NEC-007/009/010 handoff:** one clean persistent map; explicit trust,
enrollment and loss review; save/reload and unload-before-publication gates; exact
numeric refusals; replacement-resource stamps and conflict-preserving receipts.
Blueprint instances remain opaque native behavior, not translated prefab/gameplay
rules. C++ project builds, partition/streamed maps, general input/animation/geometry
translation and cross-store automation are outside this proven profile. These limits
must appear in adoption previews and synchronization policy. No tasks are added or
reordered. At this NEC-006 handoff, NEC-007 had not started; its completion follows.

### NEC-007 — Typed adoption plans and meaningful migration previews

- **Purpose:** turn discovery into a usable controlled migration.
- **Problem solved:** current drafts fabricate defaults and have no complete validated adoption workflow.
- **Reuse:** E01/E02 preview/manual-work reports, E08 typed grammar/catalog, E09 compiler, E04/E05 readiness.
- **Scope:** selected-slice import, known component/package mappings, World and binding construction, dependency closure, reviewed legacy behavior disablement plan, per-item loss report and exact native write preview. Extend GDE typed operations for missing create/remove/reparent/binding operations, with contract validation.
- **Dependencies:** NEC-004–006, NEC-003.
- **Acceptance:** all mapped values trace to source or explicit user choice; critical unknown dependencies block Play eligibility; rerunning import is idempotent.
- **Tests/proofs:** three non-trivial native fixtures, rejected unsupported behavior, stale source, no-op import and expected supported gameplay assertions.
- **Rollback/failure:** preview cannot commit; cancellation preserves originals and current CGS.
- **Non-goals:** invent gameplay from names or automatic arbitrary source conversion.

**NEC-007 completion (2026-10-10):** the opt-in
[native adoption API](../packages/project-system/native_adoption.py) and
[structural GDE grammar](../packages/gde/src/domain_dsl/typed_operations/native_adoption_operations.py)
provide source/choice-bound selected-slice previews, typed World/assets/playback,
component/system package mappings, closure/loss review and exact optional native
write requests. All work remains on copies; no commit, native write, baseline
advance or Play activation is performed. Repeat imports are no-ops and differing
existing records require reconciliation. The old Builder wizard remains unchanged.

276 Python tests and six fresh pinned-runtime runs pass over three actual certified
native fixture families. Unknown Unity/Godot/Unreal behavior remains blocking after
manual disablement review. Explicit damage choices execute once, native transforms
remain unchanged and replay hashes match. See [completion](NEC007_NATIVE_ADOPTION.md)
and [evidence](recovery/evidence/nec007-20261016/summary.json). All 2,140 protected XP-022
files and prior receipts are preserved. NEC-008 through NEC-018 are NOT STARTED.

**Mandatory handoff amendment:** NEC-008/009 must retain blocking losses and
revalidate source/map/CGS/choice/catalog identities before recovery-coordinated
publication. Native parent identity is not a runtime EntityID; parented proposals
remain blocked. The frozen MovementSystem uses flat transform fields, so systems
accessing component 1 are conservatively blocked pending structured-transform
executor certification. NEC-010/011/012 must prove instance binding, transform
compatibility, resource readiness and reviewed package capability mapping before
widening admission. Component/system packages are supported here; templates and
capability materialization are explicitly refused. No task additions or reorder
are needed. These limits amend later acceptance, not the sealed XP-022 baseline.

### NEC-008 — Three-way reconciliation and conflict proposals

- **Purpose:** permit continuous work without silent winners.
- **Problem solved:** primitive edit-back permission is not conflict-aware merging.
- **Reuse:** E07 preview/hash envelopes, E08 typed validation/approval, NEC-002 baselines.
- **Scope:** B/X/E comparison, per-field ownership, semantic dependency checks, typed merge proposals, user resolution and hash-bound approvals; minimal UI on XP-021 surfaces.
- **Dependencies:** NEC-007.
- **Acceptance:** same-value/disjoint safe cases merge; same-field disagreement/delete-versus-edit/reparent interactions require resolution; engine code edits never auto-write CGS.
- **Tests/proofs:** deterministic permutation/idempotence corpus, stale approval, concurrent users, branch identity collisions and dirty scenes.
- **Rollback/failure:** unresolved conflicts keep last verified baseline/package active; retain both competing versions.
- **Non-goals:** CRDT multiplayer editor or timestamp-based overwrite policy.

### NEC-009 — Recoverable authoring transaction coordinator

- **Purpose:** safely commit approved adoption/reconciliation across both stores.
- **Problem solved:** separate file writes and GDE commits cannot guarantee multi-store recovery.
- **Reuse:** E03 file transactions, E08 locks/snapshots/audit, XP-018/019 activation interfaces.
- **Scope:** journal, staged artifacts, before-images, CAS/locks, idempotent participant receipts, verification/baseline advance and blocked recovery state; wire migration apply through GDE. Record but do not own runtime activation.
- **Dependencies:** NEC-008.
- **Acceptance:** injected failures at every durable boundary yield old complete revision, new verified revision, or explicit recoverable conflict; never advertise mixed state as success.
- **Tests/proofs:** real filesystem fault injection, independent edits during rollback, disk full/permission denial and crash/restart at decision boundaries.
- **Rollback/failure:** compensating restores only when source hashes still match; preserve newer work and block mixed-revision Play/build otherwise.
- **Non-goals:** a second runtime mutation/epoch engine or impossible filesystem-wide atomicity claims.

### NEC-010 — Durable materialization and complete authoring loop

- **Purpose:** persist appropriate XACE changes in native projects.
- **Problem solved:** runtime mirroring disappears at stop and does not maintain native authored documents.
- **Reuse:** NEC-004–006 staged writers, NEC-009, E03 lifecycle and E09 bindings.
- **Scope:** new-project native setup, owned marker/resources/input/binding writes, scene/prefab preservation, engine-owned change proposals, echo suppression and minimal review/apply UX.
- **Dependencies:** NEC-009.
- **Acceptance:** Workflow A/B cycles survive closing/reopening both tools; no-op sync is stable; unknown native properties survive; all source modifications are previewable and audited.
- **Tests/proofs:** repeated materialize-capture-reconcile cycles in all editors, rename/delete/reparent and native undo/redo; file-diff ownership assertions.
- **Rollback/failure:** failed save leaves baseline unadvanced and uses NEC-009 recovery.
- **Non-goals:** replace native scene editors or materialize arbitrary runtime snapshots as authored scenes.

### NEC-011 — World, assets, bindings and input fidelity gates

- **Purpose:** ensure the native game means what CGS says.
- **Problem solved:** a linked file or visible object can still have wrong geometry, event binding or input semantics.
- **Reuse:** E04/E05/E09, XP-016 coordinate/readiness checks, NEC-003/010.
- **Scope:** role-bound native resources, declared input mapping, animation/audio binding compatibility, dependency fingerprints, authoritative-versus-cosmetic geometry overlay, rescan/hot-reload integration and cooked-resource readiness contract.
- **Dependencies:** NEC-010.
- **Acceptance:** cosmetic replacements preserve gameplay hashes; missing required bindings/profile mismatch block readiness; deletes/replacements produce proposals; no unapproved native timing/physics affects gameplay.
- **Tests/proofs:** actual native asset replacement and binding playback, wrong axes/scale, stale controller/input config, required resource absent and permitted cosmetic fallback.
- **Rollback/failure:** retain prior verified presentation revision; gameplay-affecting changes use normal candidate approval.
- **Non-goals:** translating entire animator graphs, terrain physics or trusting arbitrary engine feedback.

### NEC-012 — Shared production native-host lifecycle and build contract

- **Purpose:** make native Play/build independent of Builder.
- **Problem solved:** adapters alone do not select/verify/own an admitted runtime and game package.
- **Reuse:** E10/E11 verified package, distribution and process ownership; XP-016–022 admission/epoch contracts.
- **Scope:** reusable Rust lifecycle/verification service within existing launcher infrastructure, sidecar ownership, package/executor compatibility, local admission/readiness, common engine build receipt and offline policy. Build-time creator tooling may use existing Python; shipped paths may not.
- **Dependencies:** NEC-001 and NEC-011.
- **Acceptance:** packaged lifecycle starts only a pinned trusted executable with compatible package, works with Builder closed, kills only owned processes and rejects stale/unsupported executors. No dev control endpoint is exposed to game clients.
- **Tests/proofs:** native process lifecycle, incompatible identity, crash/EOF, port collision, repeated Play and no-network startup; parity with existing Player host.
- **Rollback/failure:** retain prior admitted package; visibly freeze/stop on authority loss, never native fallback.
- **Non-goals:** new runtime/session stack, in-process ABI mandate or player-side compilation.

### NEC-013 — Unity production Play and Windows build integration

- **Purpose:** ship the actual XACE-powered Unity game.
- **Problem solved:** adding adapter components does not ensure deployed runtime/resources or safe Editor lifecycle.
- **Reuse:** Unity bootstrap/applicator/input, NEC-012 verifier/lifecycle, NEC-011 binding receipt.
- **Scope:** Play preflight, native scene binding instead of duplicate mirrors, supported reload/scene transition handling, Unity build hooks and staged runtime/package/native resource inclusion.
- **Dependencies:** NEC-012, NEC-004, NEC-010/011.
- **Acceptance:** open project and press Play with Builder closed; normal Unity release build runs the same package offline on a clean Windows machine with no XACE/development installation.
- **Tests/proofs:** actual Unity editor and selected scripting backend build, Play/Stop stress, input/animation/audio/world parity and relocated read-only installation.
- **Rollback/failure:** cancel build on stale/cooked binding mismatch; preserve previous release and journal failed staging.
- **Non-goals:** every Unity backend/platform/version or MonoBehaviour gameplay translation.

### NEC-014 — Godot production Play and Windows export integration

- **Purpose:** support the developer's Godot game as well as XACE Player.
- **Problem solved:** exporting the reference Player does not integrate a user's native project.
- **Reuse:** shared Godot adapter, E11 and `xp008_player_build.py`, NEC-012 lifecycle, NEC-005 editor integration.
- **Scope:** ordinary native project Play, real native resources, export hooks/presets for supported target, package deployment and ownership cleanup; keep Player on the same shared host contract.
- **Dependencies:** NEC-012, NEC-005, NEC-010/011.
- **Acceptance:** both existing and new Godot projects export playable games without forcing the Player scene/UI; Player regressions remain green; installed game is independent of developer tools/cloud.
- **Tests/proofs:** real editor/exported executable, resource path relocation, packed resource lookup, offline input/world/event parity.
- **Rollback/failure:** reject partial resource/package export; preserve prior export and owned process boundary.
- **Non-goals:** replace the user's game with the reference Player or enable arbitrary downloaded scripts.

### NEC-015 — Unreal production Play and packaged-build integration

- **Purpose:** support real Unreal PIE and shipped games.
- **Problem solved:** plugin/commandlet success is not a usable packaged native game.
- **Reuse:** Unreal transport/applicator/plugin generation and validation, NEC-012 lifecycle and NEC-006 mapping.
- **Scope:** supported PIE lifecycle/instances, native actor and asset binding, cooker/staging integration, packaged runtime/plugin dependencies, local process/port ownership and packaged resource readiness.
- **Dependencies:** NEC-012, NEC-006, NEC-010/011.
- **Acceptance:** real project PIE and packaged Windows executable run authoritative gameplay with native content and no Builder; two PIE instances do not accidentally create competing authority for one session.
- **Tests/proofs:** real installed Unreal editor, cook/package logs, clean-machine launch, scene transitions, native event playback and canonical parity.
- **Rollback/failure:** fail cook/stage on missing dependencies, preserve prior build and clean only owned processes/artifacts.
- **Non-goals:** arbitrary Blueprint gameplay conversion, console support or all engine plugins.

### NEC-016 — Offline distribution, continuity archive and detach

- **Purpose:** make ownership and continued use concrete.
- **Problem solved:** an adapter handoff or cache backup does not preserve a whole maintainable project.
- **Reuse:** E03 uninstall/backups, E10 package verification, E11 distribution, XP-020 history, existing support export/save migration contracts.
- **Scope:** documented versioned archive and restore; source/data/native project/dependency closure; pinned redistributable runtime/notices; no-cloud launch policy; safe detach modes; update/rollback and explicit save compatibility policy.
- **Dependencies:** NEC-009 and NEC-013–015.
- **Acceptance:** independent developer workspace restores project/history and rebuilds using documented prerequisites; shipped game runs after Builder removal and network denial; every unavailable source/asset is listed; detach preserves user modifications.
- **Tests/proofs:** archive integrity/redaction/relocation, actual clean restore, modified adapter conflict, release update failure and save-version refusal/migration.
- **Rollback/failure:** missing essential material blocks a completeness claim; detach failure preserves native files and archive; old release remains launchable.
- **Non-goals:** runtime-free native source export or redistribution of unlicensed third-party content.

### NEC-017 — Installed-engine adoption, conflict and crash certification

- **Purpose:** prove all development workflows in real tools.
- **Problem solved:** fixtures and named socket clients cannot establish native editing correctness.
- **Reuse:** NEC fixtures, XP-017/020/022 proof harnesses, E14 attestation, NEC-009 journals.
- **Scope:** full A–E/G authoring/continuity loops per engine, both new and non-trivial existing projects, conflict matrix, every journal crash boundary, scale/performance measurement and human review.
- **Dependencies:** NEC-004–016.
- **Acceptance:** all required engine/version cells pass; no silent loss, dual gameplay authority, unresolved critical dependency or mixed-revision success; retain exact evidence.
- **Tests/proofs:** actual installed editors, real binary assets, authoritative state/event comparisons, native applied projections, file preservation and recovery receipts.
- **Rollback/failure:** failed profile remains unsupported; diagnostics and last known-good project/package retained; no marker-scan substitute.
- **Non-goals:** claim coverage for unspecified versions, bigger worlds or unsupported geometry.

### NEC-018 — Clean-machine shipping and private-alpha gate

- **Purpose:** substantiate the complete product promise before exposing it.
- **Problem solved:** development-machine Play does not prove deployability, offline continuity or usability.
- **Reuse:** NEC-013–017 release artifacts, XP-022 notices/proof retention/performance and the still-open REL-04 signing gate.
- **Scope:** clean-machine installation of all three native engine builds; Builder/toolchain/cloud absence; update/save compatibility and rollback; three external developer walkthroughs covering adoption/reconcile/Play/build/export continuity; publish exact support/loss matrix and honest exit wording.
- **Dependencies:** NEC-017 and prerequisite XP-022 evidence for claimed profiles.
- **Acceptance:** all three engine builds pass offline canonical behavior checks and owned-process cleanup; participants finish the supported workflow without terminal repair; no material authority/data-loss/ship-blocking issue; redistribution/continuing-use terms explicitly approved.
- **Tests/proofs:** clean VM/PC manifests, process/network capture, state/event hashes, signed release identities, walkthrough and failure logs; maintain separate online-session evidence.
- **Rollback/failure:** no three-engine alpha claim on partial results; retain prior release and publish blocked matrix cells. A separately authorized single-engine pilot must be labeled narrowly.
- **Non-goals:** the major UX redesign, every commercial release certification, or runtime-free export.

## 16. Sequence, gates and final recommendation

**Recommended program name:** XACE Native Engine Continuity (NEC).

**Total:** 18 focused implementation tasks. This count separates shared authority/recovery work from three real editor integrations and three real shipping integrations. It avoids both a monolithic importer task and three duplicated reconciliation stacks.

**Critical path:** verified XP-022 handoff -> NEC-001 -> NEC-002 -> NEC-003 -> NEC-004/005/006 (all required for the full promise) -> NEC-007 -> NEC-008 -> NEC-009 -> NEC-010 -> NEC-011 -> NEC-012 -> NEC-013/014/015 -> NEC-016 -> NEC-017 -> NEC-018. One-engine prototypes can exercise the shared path earlier, but cannot close the all-engine gates. Identity and recovery semantics are the highest architectural risks; Unreal native serialization and clean packaged builds are likely schedule risks, to be measured rather than assumed away.

**Mandatory before private alpha claiming the full workflow:** all 18 tasks for the stated Windows/engine matrix, prerequisite XP-022 evidence, real migration rather than starter-default substitution, preservation/loss reporting, stable identity, reviewed conflict handling, crash recovery, durable native authoring, native Play, all three engine-built distributions, offline runtime continuity, tested archive/restore/detach and honest support/exit disclosures. Do not defer data-loss or authority correctness to UX polish. If a limited single-engine pilot is later authorized, retain the same safety/continuity/clean-machine bars for that engine and explicitly withhold the three-engine claim.

**Safely later:** additional versions/platforms, in-process embedding, richer geometry backends, broader plugin translators, full native animation-graph conversion, advanced collaborative editing, convenience automation, the major UX/UI redesign, and runtime-free source export research. Broader commercial-scale soak/support/store certification follows the existing release program; do not confuse this bounded production-path proof with certification of every game or platform.

**Current stop point:** NEC-001 through NEC-007 are complete against the local
XP-022 engineering baseline. The remaining 11 tasks retain their order with
section 1's migration/recovery/release amendments and NEC-003/004/005/006/007's concrete
contract/native writer/adoption handoffs. NEC-008 is not started and requires the owner's
next instruction.
Full runtime-free native source export remains outside this program and needs
a separately approved compiler/parity effort.

The intended final claim is credible only with its certified scope attached: **You can adopt XACE without abandoning your engine, develop continuously across both, experience and ship the real game through Unity, Unreal or Godot, retain your project, and keep shipped local gameplay independent of Builder and XACE cloud availability.**

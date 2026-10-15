> Current recovery reconciliation: [NEC001 recovery acceptance](recovery/NEC001_RECOVERY_ACCEPTANCE.md). This governs current baseline, verification, authorization and output paths.

> Reconstructed historical NEC001 document. Historical paths, test counts and completion statements below are not fresh recovery verification. Current recovery status is in AGENT_PROGRESS.md. Original sealed payloads remain missing; use the new persistent recovered baseline.

# NEC-001 — verified post-XP-022 engineering handoff

Date: 2026-10-08. Scope: NEC-001 only; NEC-002 is not started.

This audit uses `C:/Users/ankit/Downloads/xace/target/xp016-work`, including its
uncommitted implementation. The earlier design audit of parent checkout
`d3ef383` is historical, not the present-state implementation assessment.
The owner's instruction to begin NEC-001 against this explicit sealed folder
authorizes this engineering handoff with external release gates still open.
It does not certify a release or authorize NEC-002, a commit or a push.

## 1. Baseline and preservation

- Git revision: `39ed07b8cd390619a479a3364dc903ee077a6d38`.
- Frozen working-tree inventory: `4d728ba9752124388cf451f7fd4492f2d87b4562fbdc965b19908dc389ac636a`.
- Production host: `09825d6ebcc914a84dd0f3fb8000f0f3fbee3ec5810cfb1cc388a1466773cbe6`.
- Gameplay: `6d04eed3166b195dace0324acd0543f028667de1e908f94594680f542fa3c352`.
- Historical sealed baseline (original payload missing),
  [certification](XP022_ENGINEERING_CERTIFICATION.md),
  historical verification directory (missing),
  [compact NEC evidence](recovery/evidence/nec001-20261015/summary.json).

Before NEC changes, all 1,372 source entries match the live tree and source ZIP;
all nine sealed payloads and 27 report hashes match. The unsigned distribution's
25 inventory files, ZIP contents, trust envelope, native assemblies and proof
executables are independently checked. The Git commit alone omits substantial
XP-016–022 source and is not an adequate recovery point.

`tools/nec001_handoff_verify.py` never reseals XP-022. Before/after reports hash
every file under the sealed baseline and final-certification trees and verify
all manifest-referenced reports. New outputs are under `target/nec001`.
The only permitted change to an existing source-manifest entry is the live
`MASTER_PLAN.md` NEC addendum. Its original bytes remain in the unchanged sealed
`source.zip`; every other frozen source entry remains exact. New NEC files and
the live documentation change mean the current tree has a new identity, not a
replacement claim to the frozen working-tree digest. Historical `nec_started:
false` and proposed-amendment fields in the seal are intentionally not rewritten.

## 2. What XP-019–022 actually delivered

| Foundation | Implementation and proof | Exact reusable boundary / NEC consequence |
| --- | --- | --- |
| XP-016/017 native readers | `adapters/{unity,unreal}/XaceNativeContract.*`, `adapters/godot/xace_native_contract.gd`, canonical entity readers; final `native-v2/{unity,godot,unreal}.json` and `hosts-final/proof.json` | Fifteen accept/drop/recover/reject vectors per installed engine, coordinates/geometry/authority fencing, actual Player/Godot and four-host applied projections/events/input. These are runtime readers, not native editor serializers. Reuse in NEC-004–006/012–015. |
| XP-018 isolated candidate | `packages/runtime-core/src/runtime_orchestrator/ruleset_candidate.rs`: `CandidateParent`, `CandidateArtifacts`, host-owned `CandidateApproval`, `CandidatePolicy`, `CandidateStore::stage`; `examples/reference-mechanic/tests/candidate.rs` | Immutable parent/artifact/proof identities, two isolated deterministic runs and explicit host-registered, system-read-only configuration replacement. World/capability differences, entity migration and unregistered/state-written replacements fail closed. No generic script/compiler or scene migration API is assumed. |
| XP-019 future-tick activation | `ruleset_activation.rs`, `live_session.rs`, `runtime_cli.rs`; final `hosts-final` and `process-faults-final` | Peer readiness/generation fencing, tick-N revalidation, isolated migration, durable decision then publication. Old epoch through 7/new at 8 and changed behavior at 9 in retained actual hosts. Before-decision failure leaves parent; after-decision failure ends session; restart refuses old parent. It does **not** resume a crashed session or implement native authoring rollback. |
| XP-020 replay, strengthened by XP-022 | `runtime_orchestrator/epoch_replay.rs`, `tools/xp022_archive_verify.py`; final host replay plus independent archive report | Exact historical artifacts, input/feedback/membership, migration, schedule, hashes/events/state; independent read-only forks. XP-022 adds bounded segments, 64 MiB segment bound and 32 GiB archive quota. Full two-hour recording was verified across 791 segments / 202,271 ticks. This is replay, not arbitrary authoring undo or save migration. |
| XP-021 inspection and creator control | `packages/builder-workspace/server/replay_debugger.py`, `ws_message_router.py`, `src/preview/replay_inspector.ts`; final `debugger/proof.json` | Recorded frame/entity/event/world/dependency inspection, import/export/live fork and trusted creator controls with session-wide confirmation. Legacy guest controls fenced. No native change inbox, three-way diff or authoring recovery UI exists. Reuse the shell and authority checks; NEC-008/009 must add those flows. |
| XP-022 engineering evidence | `tools/xp022_final_proofs.py`, `xp022_process_faults.py`, `xp022_certification.py`, `xp022_seal_engineering.py`; sealed reports | Actual production-host socket faults, black-box kills, rejected migration, slow consumers, real installed native hosts, exported Player, browser debugger, unsigned package integrity and local TLS. Precise internal kill points are supplemental fault-injection test builds. No clean-machine, two-machine, public-relay, signing or first-time-tester pass is implied. |

The older statement that available cross-engine evidence consisted only of named
socket clients is superseded. Conversely, runtime parity in actual editors does
not establish import, ordinary editor capture, durable scene writes, full engine
release builds or independent gameplay source export.

## 3. Present-state answers

### Import an existing Unity, Unreal or Godot game

**Implemented.** All three project roots can be inventoried and linked to an XACE
project. `project-system/project_creator.py::import_engine_project` validates the
inventory, creates a template project and records the native path. The Builder
`/api/project/import-engine` route can additionally install an adapter.
`adapter_installation.py` tracks owned files/backups, updates, rollback and
uninstall conflicts. `asset-registry/asset_import_workflow.py` scans and links or
copies assets. Existing native files can be retained.

**Partial.** `engine_migration_wizard.py` produces reversible **preview** mappings:
Godot node headers, Unity `m_Name` lines, and Unreal text markers/`MapReference`
fallback. `_starter_actor_parts` constructs starter values rather than faithfully
extracting gameplay, placement or dependencies. The route at
`builder_server.py` `/api/project/migration/manual-plan` returns `preview_only`.
The default inventory cap is 500 entries per category. Existing tests verify
read-only inventory, generated proposals and reversal, not behavioral migration.

**Missing.** Faithful selected-scene/map adoption, prefab/instance/override identity,
serialized property capture, dependency/loss closure, meaningful reviewed CGS
application and original-game parity. No general MonoBehaviour/C++/Blueprint/
GDScript conversion exists. A half-built game can be linked and manually adopted
in pieces; it cannot be imported wholesale and continued with equivalent XACE
gameplay today. Unreal binary maps are not parsed by the text fallback.

### Bidirectional editing

**Implemented.** Runtime authority sends canonical state to native adapters and
receives admitted inputs with tick/epoch/ownership checks. The final native
proofs certify that bounded session path. Asset resolution updates exist in
`asset-registry/engine_sync_receiver.py`; file-watcher/hot-reload primitives exist
under `asset-runtime/src/hot_reload`. These are not native project edit capture.
`engine_bridge.rs::queue_feedback` rejects gameplay feedback from admitted live
presentation clients; editor edits must not bypass this fence.

**Partial.** `state_authority.py` allows explicit primitive
`set_component_field` commit proposals. `ws_message_router.py::_handle_engine_edit_commit`
checks accepted preview and identity/envelope, then uses GDE/persistence. It is
not a watcher for normal editor actions. Its permission to merge primitive
defaults across newer CGS is not a base/XACE/engine same-field conflict algorithm.
Native adapters materialize runtime mirrors and supported presentation, not
general durable scene authoring. XP-019 live synchronization is configuration
activation only; unsupported world/state migration is intentionally refused.

**Missing.** Automatic authoring capture of ordinary code, create/delete/rename,
hierarchy, assets/bindings, animation graphs, input maps and world/map edits;
persisted authoring IDs and common baselines; reviewed three-way reconciliation;
atomic/recoverable CGS-plus-native saves; undo/redo and concurrency protection.
`project_manifest.py` explicitly reports `bidirectional_editing: False`.
Today this is runtime synchronization plus partial explicit/manual authoring
paths, **not true bidirectional native editing**.

### Export / stop using XACE

**Implemented.** CGS/data and adapter sources are available; adapter handoff and
conflict-aware uninstall preserve user files. `project-system/playable_package.py`
builds verified, relocatable gameplay packages with trusted runtime/executor,
Factory/SGC/world provenance and presentation inventory. `tools/xp008_player_build.py`
and the Rust `player-launcher` produce the real standalone Windows Player
distribution tested by XP-022. Runtime, notices and data are bundled; this is a
usable local gameplay distribution with a **XACE runtime dependency**.

**Partial.** Native adapters can consume the game in the installed-host fixtures.
Adapter source/config handoff is useful integration material, not full exported
native gameplay. `packages/cli/src/commands/build.rs::generate_artifact` generates
adapter configuration JSON; `deploy.rs` remains unimplemented. The older CLI path
does not supersede the working Player distribution. Source access alone does not
prove a complete dependency-closed, licensed and rebuildable project archive.

**Missing.** Whole-game Unity C#/Unreal C++ or Blueprint/Godot GDScript gameplay
export that preserves semantics without the XACE runtime; maintained equivalent
native source generation; full adopted native-project Play/build/cook/export
integration for all three engines; complete archive/restore/detach certification.
NEC v1 promises independence from Builder/cloud using a pinned local runtime,
**not runtime-free exit**. The latter remains a separately scoped compiler project.

## 4. Pinned support contract and limits

| Profile | Selected version | Proven today | Required future native proof |
| --- | --- | --- | --- |
| Unity | 6000.4.9f1 | Installed Windows reader/geometry/input/session/epoch fixture | NEC-004 extract/save/extract; NEC-013 native Play and Windows x64 build; NEC-017/018 complete adoption/offline clean install. Select and record scripting backend/build options in NEC-013 before certification. |
| Godot | 4.6.3-stable official | Installed reader/session plus real exported XACE Player | NEC-005 native authoring and NEC-014 ordinary developer-project export; Player export is not proof for arbitrary adopted projects. |
| Unreal | 5.7.4-51494982+++UE5+Release-5.7 | Installed commandlet/native reader and mixed session | NEC-006 real binary map/asset authoring; NEC-015 PIE/cook/packaged Windows x64 game. Record packaging configuration at that gate. |

The measured OS is Windows 11 x64 build 26200 on i7-12650HX, about 16 GiB RAM,
RTX 4050 Laptop/Intel UHD. Broader adapter version ranges are compatibility
metadata, not certification. No other OS/editor/backend is included by inference.

- Gameplay geometry: only registered `world.aabb.v1`, fixed64 Y-up/-Z-forward,
  scale 1,000,000 raw units per world unit; bounded coordinates ±8,192 units,
  BOX, unparented identity rotation/scale; box bounds must remain inside limits.
  Registry maximum 4,096 bodies is a format/profile bound, not a measured 4,096-body
  performance claim. See `core/src/world/profiles.json` and
  `schema-factory/src/world_contract{,_v3}.py`.
- World v3 semantic schemas/capabilities/relationships and actor-instance bindings
  are extensible; arbitrary terrain/mesh/native physics are not thereby supported.
  Rich native geometry may remain visual only. Explicit reviewed AABB proxies
  must not silently claim original collision equivalence.
- Live activation: registered read-only configuration replacement only, unchanged
  semantic world and geometry. Structural authoring requires stop/save/recompile/
  admit/start a new session. Keep the last verified package until new admission;
  never reset or migrate an active world implicitly. Live structural migration
  requires separate prerequisite work, outside NEC-001 and the bounded v1 promise.
- NEC certification target: 1,000 adopted objects, 100-operation batches,
  p95 capture-to-review <2 seconds excluding engine import/compile, at least 30
  measured warm batches per engine on recorded hardware. Measure memory, total
  cold time and each exclusion separately. These are **future acceptance budgets**,
  not present measured adoption support; failure requires an explicit published
  smaller limit or remediation, not silent truncation.
- Preserve XP-022 p95 authority-work <16.7 ms for the same fixture/profile. Recorded
  result: 12.0662 ms, 7,200.860 seconds, 202,271 ticks, peak sampled authority private
  memory 60.49 MiB. No sustained 60 wall-clock ticks/sec claim. Render-frame interval
  p95 33.401 ms at 30-FPS cap and input-send/applied-tick p95 35.106 ms are local
  short samples, not GPU time or Internet latency. No new soak is claimed here.
- No automatic code/plugin translation or animation-graph rewriting. Unsupported
  gameplay-critical dependencies block declaring an adopted slice playable.
- Offline continuity target: no Builder, Python/Node/Cargo, provider credentials,
  license-server or XACE cloud dependency in the shipped local path. Pinned XACE
  runtime remains required. Cargo workspace MIT metadata and bundled third-party
  notices do not alone settle all native engine/assets/plugins redistribution
  terms: NEC-016/018 must inventory and obtain the applicable distribution and
  continuing-use terms before claiming complete commercial continuity.

## 5. Ownership and required fixture behavior

The normative field ownership and proof matrix is
[ADR NEC-001](adr/NEC-001-native-authoring-ownership.md).
Every promised representation is either an implemented reusable contract or a
named future NEC output. Future editor APIs/serializers are not assumed present.

For NEC-004/005/006, create one independently authored pre-adoption fixture per
pinned engine: two scenes/maps, at least 50 objects, duplicate names, nested
decorative hierarchy, definition/instance relationships with overrides, meshes/
materials, animation/audio, input bindings, supported spawn/AABB metadata, one
known configuration behavior and one unsupported critical script/plugin.
Unreal must use real editor-saved `.umap`/`.uasset`. Record fixture license,
native editor version, exact original hashes, selected subset and expected values.
No new fixture implementation is part of NEC-001.

Required assertions, owned by NEC-007–018:

1. Read-only inventory changes zero bytes and executes no project code. Trusted
   editor extraction is a separate explicit operation on an isolated copy; do not
   describe editor loading of project scripts as a sandbox.
2. Preview/reject preserves originals; approve produces extracted transform/input/
   binding values, not guessed defaults. Unsupported critical behavior blocks
   adoption until explicitly replaced/excluded with dependency closure.
3. Reference behavior: use the package-owned disabled-third-attempt / configured
   reversal-and-shockwave trace from XP-018/019 as the supported known mapping.
   Denied attempt at tick 7, activation at 8 and shared effect at 9 are parity
   assertions only for that exact fixture. No mechanic name enters core or a
   generic importer. Native source scripts are not inferred to implement it.
4. Rename/move retains authoring identity; duplicate allocates a new identity;
   delete retains a tombstone; prefab definition and instance overrides remain
   distinct. Decorative reparent is preserved; invalid authoritative geometry
   reparent/rotation is rejected. Native Play-mode motion is not authored placement.
5. Baseline/XACE/engine comparisons show same-field conflicts and delete-versus-edit;
   disjoint changes can form a reviewed proposal. Same-name objects never alias.
   No-op capture/save/reopen is semantically stable and produces no owned-file churn.
6. Crash every authoring journal boundary, then verify actual bytes/IDs/receipts.
   New independent edits prevent compensation from overwriting user work; mixed
   revisions block Play/build. XP-019 post-decision halt is not called recovery
   of a native save transaction.
7. Compare canonical states/events and normalized client-applied projections in
   Player, native Play and engine-built executable using identical admitted input.
   Test ordinary keyboard/controller input, asset replacement, animation/audio
   event mappings, required-geometry refusal and cosmetic fallback separately.
8. Archive/restore/rebuild in a separate workspace; then test every native shipped
   build on a genuinely clean Windows machine with network denied and Builder/
   developer tools absent. Detach preserves modified user files. Update rollback
   and save-version refusal/migration have explicit expected outcomes.

## 6. Required roadmap amendments

The amended [NEC program](XACE_NATIVE_ENGINE_CONTINUITY_PROGRAM.md) retains all
18 task IDs and ordering. It changes these assumptions, not the seven layers:

1. NEC engineering entry accepts the sealed local XP-022 profile by the present
   owner instruction. REL-01 clean Windows, REL-02 two machines, REL-03 public
   relay/two networks, REL-04 signing and REL-05 three first-time testers all stay
   OPEN, with their original thresholds and claim gates. NEC-018 is not a shortcut
   around them. No XP-019–022 reimplementation is assigned to NEC-001.
2. Pin the above three versions and reuse the actual native reader/session proofs;
   do not certify native authoring/build cells from those runtime proofs.
3. NEC-007/009/010/011/012 must distinguish stopped-session rebuild from eligible
   XP-018/019 configuration activation. No generic live world migration dependency.
4. NEC-009 owns a separate native authoring journal. XP-019 guarantees a durable
   decision and halt/refusal after failure, not resumed play or cross-editor undo.
5. NEC-008 adds a minimal conflict/recovery flow to the XP-021 inspection shell;
   debugger controls are not an existing authoring approval/merge implementation.
6. NEC-016 carries exact XP-020 history plus XP-022 segmented archives, quota and
   completion/integrity metadata; a replay is not a complete project/save archive.
   Licensing, save compatibility and dependency-closed rebuild remain explicit gates.

For the original three capabilities, the minimum coherent delivery units are:
stable identity/contracts (002–003); three real editor readers/writers (004–006);
meaningful migration, conflicts and recoverable durable saves (007–010); fidelity
and shared host lifecycle (011–012); three actual native shipping integrations
(013–015); archive/restore/detach (016); installed-engine and clean-machine proof
(017–018). Runtime-free whole-game export additionally needs a separately approved
native gameplay compiler/semantic parity program; completing NEC alone cannot
honestly satisfy that stronger exit requirement.

## 7. Verification and closeout

Fresh logs and exact commands are in
`target/nec001/verification-20261008/runs.json`, with compact results and artifact
hashes in `docs/evidence/nec001-handoff-20261008.json`. Scope distinguishes fresh
tests from retained installed-editor/soak evidence. No native staging rebuild,
two-hour rerun, clean-machine run, public deployment or external tester is claimed.

Fresh results: **85 Python tests and 23 Rust reference/candidate/activation tests
passed**, plus the production-host session/input/recovery socket suites, all five
black-box process-fault scenarios, all five replay fault cases, and all five epoch
boundary/repeat/rewind checks. The Rust test build enables
`activation-fault-injection`; the process proofs use the unchanged production
host without that feature. Neither is substituted for the other.

The replay fault CLI intentionally returns 2 when `local_subset_ok` is true and
`certified` is false (`tools/xp022_certification.py::main`). Evaluate all five case
results as well as that explicit status; do not rewrite this exit to a release pass.
The first generic command summary treated any nonzero as failed; retained raw logs
are unchanged and the NEC aggregate records the correct expected result.

Recheck the seal after all edits with:

```powershell
python -m tools.nec001_handoff_verify --allow-master-update --compare target/nec001/verification-20261008/before.json --out target/nec001/verification-20261008/after.json
```

NEC-001 is complete for the engineering handoff: fresh conformance checks and the
final preservation check pass, with 2,140 protected files unchanged. The live
master plan and compact evidence record the final decision. NEC-002 remains
not started and requires a subsequent user instruction.

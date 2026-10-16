> NEC010 is now explicitly authorized and IN PROGRESS (2026-10-16). Current acceptance checklist: docs/NEC010_DURABLE_MATERIALIZATION.md. Earlier stop/not-started entries are historical. NEC011 has not started.

> Current recovery status (2026-10-16): XP016?XP022 and NEC001?NEC009 verified within documented local scope. NEC009 acceptance: docs/NEC009_AUTHORING_TRANSACTIONS.md. NEC010 NOT STARTED; awaiting explicit authorization. REL01?05 remain open; original sealed payloads missing; no off-device backup. Historical statements below are retained as history.

# Recovery status ? 2026-10-12

This is a reconstructed historical plan. Current verification and outstanding recovery work are tracked in [AGENT_PROGRESS.md](AGENT_PROGRESS.md). Historical passing claims below are not fresh verification. Original XP-022 sealed evidence is missing.

Fresh recovery: XP-017 local acceptance passed on 2026-10-12, with an unresolved initial four-client timeout retained. See `docs/recovery/evidence/xp017-20261012/summary.json`. XP-018 recovery is next; no off-device backup exists.

Fresh recovery: XP-018 preparation acceptance passes (857 Rust, 10 Builder, end-to-end isolation); evidence under `docs/recovery/evidence/xp018-20261012`. XP-019 recovery is next. No checkpoint is backed up off-device.

Fresh recovery: XP019 historical local gates pass; recurring Unreal missing-input timeout remains open for final recovery acceptance. See AGENT_PROGRESS.md and fresh XP019 recovery evidence. XP020 recovery is next.

Fresh recovery: XP020 passes864 Rust tests and new four-client epoch replay acceptance. XP021 is next; original evidence and recurring native timeout limitations remain in AGENT_PROGRESS.md.

Fresh recovery: XP021 passes883 tests, Builder build/UI and actual browser walkthrough. XP022 reconstruction is next. Original seal missing and native timeout unresolved; see AGENT_PROGRESS.md.

Fresh recovery: XP022 source reconstructed; release build, 23 reference/fault tests, 8 world tests and production socket proofs pass. Remaining local certification and two-hour soak are pending. Original seal missing; no off-device backup.

Fresh recovery update 2026-10-14: XP022 short gates pass; fresh two-hour soak was interrupted by documented Button/Lid system sleep and FAILED. Retry and sealing remain pending; see AGENT_PROGRESS.md.

Recovery update 2026-10-14: original XP022 engineering-candidate receipt recovered and historical SHA256 matched; original sealed payloads/detailed reports still missing. User authorized a background endurance retry; see AGENT_PROGRESS.md.

Recovery update 2026-10-15: prior diagnostic soak completed two hours and all182002 archived ticks verify, but performance failed18.8007ms p95. New durable ingress/validation batching candidate passes847 runtime tests and real socket/process/mixed-engine/replay checks. Short timing preflight and full endurance remain pending; earlier freeze remains unconfirmed. Original receipt recovered, sealed payloads missing, no off-device backup. See AGENT_PROGRESS.md.

# XACE MASTER BUILD PLAN
# Version: Post-Audit (Audits 1-9 incorporated)
# Status: [ ] Not Started | [~] In Progress | [x] Complete | [!] Blocked
# Update this file after every single session.

## NEC-008: COMPLETE - THREE-WAY RECONCILIATION REVIEW - 2026-10-10

Implemented deterministic baseline/XACE/engine comparison, field ownership,
semantic dependency checks, retained conflict versions and hash-bound choices.
The concrete root-transform profile emits typed GDE proposals and exact native
writer previews. Baseline receipts, map/branch identity and current source/CGS
hashes are revalidated; no saved baseline or active package is changed.

- [x] Safe same-value/disjoint merges, explicit same-field/delete-edit/reparent
  conflicts, graph validation and opaque native behavior preservation.
- [x] Principal-bound expiring review sessions and signed process-local approvals;
  concurrent review CAS and source drift invalidate stale decisions.
- [x] Opt-in XP-021 Builder review panel and guarded routes; no apply endpoint.
- [x] 308 Python tests in 17 suites, three real capture-derived engine proofs,
  and 20 real-browser/HTTP checks pass. Desktop/narrow screenshots inspected.
- [x] All 2,140 protected XP-022 files and 95 NEC-007 artifact records preserved.
- [ ] NEC-009 through NEC-018: NOT STARTED. Stop before NEC-009.

Root-transform proposals are certified; structural/identity changes and broader
asset/input/binding mappings remain explicitly gated. Review approval cannot
commit or start Play. NEC-009 must perform fresh publication-time verification,
CAS/locks, journal and receipt checks; NEC-010/011 extend durable mappings before
wider admission. No task additions or reorder. REL-01 through REL-05 remain OPEN.
No commit or push was performed.

See [completion](docs/NEC008_NATIVE_RECONCILIATION.md),
[evidence](docs/evidence/nec008-reconciliation-20261010.json), and
`target/nec008/verification-20261010/`. Earlier entries are historical;
pre-NEC-008 live plans are retained in `target/nec008/entry-documents/`.

## NEC-007: COMPLETE - TYPED NATIVE ADOPTION PREVIEWS - 2026-10-10

Implemented the opt-in source-bound adoption API and structural GDE extension.
Native transforms/resources are preserved; semantic roles, additional component
values and hash-pinned gameplay package choices are explicit. Dependency closure,
per-item losses, reviewed manual behavior disablement and exact optional native
write requests remain inspectable without publishing CGS or changing native files.

- [x] Typed creation/removal/reparent/binding operations validate on an isolated CGS
  copy; stale source/CGS/records and invalid Factory contracts fail closed.
- [x] Repeat import is a no-op; differing existing records require reconciliation.
- [x] 276 Python tests pass, including 21 adoption tests and 255 prior regressions.
- [x] Three certified native fixture families and six fresh pinned-runtime runs
  prove explicit damage behavior, unchanged transforms and matching replay hashes.
- [x] All 2,140 protected XP-022 files and historical NEC receipts preserved.
- [ ] NEC-008 through NEC-018: NOT STARTED. Stop before NEC-008.

Preview-only host API; legacy Builder migration routes are unchanged. Arbitrary
native code/input/animation conversion, commit, continuous sync and runtime-free
export remain unimplemented. Parented runtime objects and systems accessing
structured transforms stay blocked pending certified instance bindings/executor
contracts. Package capability materialization also requires a separately reviewed
World mapping. NEC-008/009 preserve these gates; NEC-010/011/012 must integrate and
prove them before wider Play admission. No tasks added or reordered. REL-01 through
REL-05 remain OPEN. No commit or push was performed.

See [completion](docs/NEC007_NATIVE_ADOPTION.md),
[evidence](docs/recovery/evidence/nec007-20261016/summary.json) and
`target/nec007/verification-20261010/`. Earlier entries remain historical;
pre-NEC-007 live plans are retained in `target/nec007/entry-documents/`.

## NEC-006: COMPLETE - UNREAL SAVED NATIVE AUTHORING - 2026-10-10

Implemented the pinned Unreal 5.7.4 editor authoring module in
`adapters/unreal/Authoring/`, trusted independent project staging and the NEC-002/003
bridge in `packages/project-system/unreal_authoring*.py`.

- [x] Real binary maps/meshes, explicit scene/actor identities, duplicate refusal
  and rekey, saved rename/reparent, typed mesh references and Blueprint drift inventory.
- [x] Native staged saves preserve package identity, reopen with exact readback and
  bind replacement-resource dependencies; approved publication requires map unload.
- [x] Editor Undo/Redo, native before-images, injected-failure rollback and recovery
  preserving newer edits; no gameplay authority or runtime transport changes.
- [x] 255 Python tests and 73 installed-Unreal checks pass, including independent
  trusted-copy extraction, cold Python/native round trip and real editor authoring.
- [x] All 2,140 protected XP-022 files and historical NEC receipts preserved.
- [ ] NEC-007 through NEC-018: NOT STARTED. Stop before NEC-007.

Scope is one clean saved persistent map and allowlisted StaticMeshActor edits.
Blueprint/native behavior is preserved as blocking opaque loss, not converted.
C++ project builds, World Partition/streaming, arbitrary bindings/animations and
full runtime-free export remain outside this profile. No automatic CGS commit or
continuous synchronization is claimed. No tasks added/reordered; NEC-007/009/010
must integrate trust/enrollment/loss review, save/reload/unload gates, replacement
resource stamps and conflict-preserving receipts. REL-01 through REL-05 stay OPEN.
No commit or push was performed.

See [completion](docs/NEC006_UNREAL_AUTHORING.md),
[evidence](docs/recovery/evidence/nec006-20261016/summary.json) and
`target/nec006/verification-20261010/`. Earlier entries remain historical;
pre-NEC-006 live plans are retained in `target/nec006/entry-documents/`.

## NEC-005: COMPLETE - GODOT SAVED NATIVE AUTHORING - 2026-10-09

Implemented the opt-in Godot 4.6.3 editor authoring plugin, native discovery/capture,
explicit persistent metadata and staged PackedScene writer under
`adapters/godot/authoring/`, with the NEC-002/003 bridge in
`packages/project-system/godot_authoring.py`.

- [x] Scene/resource UIDs and node identities; nested packed instances, rename/
  reparent continuity, grouped editor Undo/Redo and duplicate metadata refusal.
- [x] Real text/binary scene saves, binary resource replacement, typed bindings,
  saved dependency fingerprints, full rescan and retained native behavior losses.
- [x] Receipt-bound writes, exact numeric refusal, before-image restore, newer-edit
  conflicts and recovery in a fresh editor process; no gameplay authority added.
- [x] 239 Python tests and 74 installed-Godot checks pass. Actual Play and a separate
  non-editor process cannot acquire authoring privileges; runtime protocol unchanged.
- [x] All 2,140 protected XP-022 files and historical NEC receipts preserved.
- [ ] NEC-006 through NEC-018: NOT STARTED. Stop before NEC-006.

Saved capture/write requires selected scenes closed after explicit save/discard:
Godot 4.6.3 has no public unsaved-scene query. Unknown native behavior and physics
remain blocking; arbitrary scripts/graphs and general inherited-scene ecosystems
are not certified. No automatic CGS commit, baseline advance, synchronization or
runtime-free export is claimed. No tasks added/reordered; NEC-007/009/010 must
integrate this explicit boundary and the native receipts. REL-01 through REL-05
remain OPEN. No commit or push was performed.

See [completion](docs/NEC005_GODOT_AUTHORING.md),
[evidence](docs/recovery/evidence/nec005-20261016/summary.json) and
`target/nec005/verification-20261009/`. Earlier entries remain historical;
pre-NEC-005 live plans are retained in `target/nec005/entry-documents/`.

## NEC-004: COMPLETE - UNITY NATIVE AUTHORING - 2026-10-09

Implemented opt-in Unity 6000.4.9f1 saved-content discovery, explicit authoring
metadata, normalized capture and approved staged native writes in
`adapters/unity/Authoring/`, with the NEC-002/003 Python bridge in
`packages/project-system/unity_authoring.py`.

- [x] Persistent scene/prefab/instance identities, serialized allowlisted fields,
  dependency fingerprints, dirty/Play refusal and notification/full-rescan handling.
- [x] Native serialization and saved readback, unknown component/override retention,
  exact numeric inverse conversion, before-images and conflict-preserving recovery.
- [x] 228 Python tests and 50 installed-Unity checks pass, including actual saved
  scenes/prefabs, cold reopen, Python-generated writes and both Play reload settings.
- [x] All 2,140 protected XP-022 files and historical NEC receipts preserved.
- [ ] NEC-005 through NEC-018: NOT STARTED. Stop before NEC-005.

These are callable authoring APIs; no automatic CGS commit, baseline advance,
continuous synchronization or runtime-free export is claimed. Regular prefab
fixtures, legacy input declarations and explicit supported bindings are certified;
arbitrary scripts/graphs and broader Unity package compatibility remain outside
this proof. No roadmap tasks were added or reordered. NEC-007/009/010 consume
these primitives for adoption, coordinated recovery and synchronization.
REL-01 through REL-05 remain OPEN. No commit or push was performed.

See [completion](docs/NEC004_UNITY_AUTHORING.md),
[evidence](docs/recovery/evidence/nec004-20261015/summary.json) and
`target/nec004/verification-20261009/`. Earlier entries below are historical;
pre-NEC-004 live plans are retained in `target/nec004/entry-documents/`.

## NEC-003: COMPLETE - NORMALIZED NATIVE AUTHORING CONTRACTS - 2026-10-09

Implemented opt-in project-system capture, snapshot, loss-report and delta contracts
in `native_authoring_contract.py`, with exact fixed-point/axis normalization in
`native_authoring_values.py`. Reuses NEC-002 identity, typed AssetReference,
semantic playback compatibility and the frozen XP-022 World geometry profile.

- [x] Versioned, bounded canonical JSON; int64 decimal strings; fixed-point rounding
  review; independent Python/Node golden values and full-snapshot digest parity.
- [x] Host-pinned source versions and field ownership/read/write policies; stable
  document fingerprints; dirty/Play capture refusal; explicit dependency closure.
- [x] Loss reporting, retained opaque native content, unsupported geometry refusal,
  preserved nested hierarchy, hash-bound snapshots and transport delta preconditions.
- [x] 28 focused tests plus 191 existing regressions pass (219 unique tests).
  Includes 30 numeric goldens, a 1,500-object hierarchy and 300 malformed mutations.
- [ ] NEC-004 through NEC-018: NOT STARTED. Stop before NEC-004.

No native editor reader/writer, watcher, CGS commit, baseline advancement or runtime
change is added. Write capabilities default off. Snapshot admission is authoring
validation, not native save authenticity or Play/readiness certification. Installed
native proofs remain NEC-004/005/006; reconciliation/recovery remain NEC-008/009.
The roadmap needs no new tasks or reorder; its reader/writer handoff now references
these concrete contracts and golden cases. REL-01 through REL-05 remain OPEN.

All 2,140 protected XP-022 files remain byte-identical. NEC-001/002 receipts are
unchanged; pre-NEC-003 master/roadmap copies preserve NEC-002 hashes under
`target/nec003/entry-documents/`. No commit or push was performed.
See [completion](docs/NEC003_NATIVE_AUTHORING_CONTRACTS.md),
[evidence](docs/recovery/evidence/nec003-20261015/summary.json) and
`target/nec003/verification-20261009/` for exact scope and verification.

## NEC-002: COMPLETE - AUTHORING IDENTITIES AND BASELINES - 2026-10-08

Implemented the opt-in project-system identity contract and durable revision store
in `packages/project-system/authoring_identity.py` and
`packages/project-system/authoring_identity_store.py`. The store binds to the
existing project manifest without modifying CGS, runtime EntityID allocation,
native project files or engine capability claims.

- [x] Stable namespace/branch/object IDs; distinct prefab definitions/instances;
  native persistent locators separate from name/path hints; optional World bindings.
- [x] Copy-based preparation; rename/reparent continuity; distinct duplication;
  tombstones and explicit undo; collision/lost-metadata refusal; fork conflicts.
- [x] Versioned baseline and journal/receipt references; explicit retained-map
  migration preserving IDs; content-addressed immutable history, locked CAS head
  publication, idempotent retry and explicit missing/corrupt-head recovery.
- [x] 24 focused tests and 67 existing project/Player/authoring regressions pass.
  Focused proofs include 300 identity round trips, a real process exit before
  publication and two real competing writer processes.
- [ ] NEC-003 through NEC-018: NOT STARTED. Stop until the owner's next instruction.

Native metadata attachment is specified for NEC-004/005/006, not implemented by
this task. Normalized snapshots, three-way merge and multi-editor transaction
recovery remain in NEC-003/008/009. Baseline receipts are validated references;
the later coordinator must verify their actual native/canonical save content.
No installed-editor, native shipping, performance or runtime-free export claim
is added. The existing NEC ordering and XP-022 external release gates are unchanged.

XP-022 seal and detailed certification files remain byte-identical; existing
source-manifest entries are unchanged except the live master-plan addenda.
NEC-001 receipts remain historical and untouched; pre-NEC-002 master/roadmap copies
under `target/nec002/entry-documents/` match those original receipts.
No commit or push was performed.

See [NEC-002 contract and completion](docs/NEC002_AUTHORING_IDENTITIES.md),
[evidence](docs/evidence/nec002-identities-20261008.json) and the
[current NEC program](docs/XACE_NATIVE_ENGINE_CONTINUITY_PROGRAM.md).

## NEC-001: COMPLETE — ENGINEERING HANDOFF ONLY — 2026-10-08

The owner supplied `C:/Users/ankit/Downloads/xace/target/xp016-work` and explicitly
authorized NEC-001 against its sealed post-XP-022 implementation, including
uncommitted work. This supersedes the earlier wrong-checkout prerequisite block
and authorizes the engineering/release separation for this handoff. The historical
XP-022 entries below and the sealed certification/manifest are unchanged.

- [x] NEC-001: audited actual XP-018–022 APIs, retained native proofs and present
  import/edit/export limits; reconciled the roadmap; fixed pinned versions,
  geometry/scale scope, ownership and required fixture assertions.
- [ ] NEC-002 through NEC-018: NOT STARTED. Stop here until the owner's next instruction.
- XP-022 ENGINEERING COMPLETE — EXTERNAL RELEASE GATES OPEN. REL-01 clean Windows,
  REL-02 two-machine LAN, REL-03 public relay/two networks, REL-04 signing and
  REL-05 three first-time testers remain OPEN. No original full release pass,
  new commercial-use grant, commit or push is claimed.

Frozen identity: revision `39ed07b8cd390619a479a3364dc903ee077a6d38` plus source
inventory `4d728ba9752124388cf451f7fd4492f2d87b4562fbdc965b19908dc389ac636a`.
The source ZIP, nine sealed payloads, 27 referenced reports, native assemblies
and unsigned release remain intact. Before/after SHA-256 inventories verify all
2,140 files in the sealed baseline and final-certification trees. This live master
addendum is the only changed pre-existing source-manifest entry; the sealed master
copy remains exact. All other NEC outputs are new files, outside XP-022 evidence.

Fresh verification: 85 Python tests and 23 exact-source Rust reference tests pass;
production-host session/socket/recovery proofs, five process-fault scenarios,
five replay fault cases and five before/at/after/repeat/rewind verifications pass.
Replay subset exit code 2 means `local_subset_ok: true`, `certified: false`, by
design. Retained installed-native proofs and the two-hour soak were inspected and
hash-verified, not rerun or relabeled as native authoring/build certification.

Roadmap amendments: reuse actual installed Unity 6000.4.9f1, Godot 4.6.3 and
Unreal 5.7.4 reader/session foundations; restrict live activation to registered
read-only configuration replacement; structural/world edits require explicit
stop/rebuild/new admission. XP-019 post-decision failure ends the session, so
NEC-009 needs its own authoring recovery journal. XP-021 inspection is not a native
conflict UI. NEC-016 must preserve segmented replay metadata, dependencies and
continuing-use terms. Runtime-free native gameplay export remains outside NEC v1.

Canonical records: [audit](docs/NEC001_HANDOFF_AUDIT.md),
[ownership ADR](docs/adr/NEC-001-native-authoring-ownership.md),
[amended NEC program](docs/XACE_NATIVE_ENGINE_CONTINUITY_PROGRAM.md),
[evidence](docs/evidence/nec001-handoff-20261008.json).

---

## XP-022: LOCAL ENGINEERING GATES PASSED — EXTERNAL RELEASE ACCEPTANCE OPEN - 2026-10-08

Latest final-candidate follow-up: production-binary admission/input/recovery,
crash-before/after durable activation, rejected migration, slow consumer, partial
package transfer, token expiry and local TLS outage tests pass. Installed-host
A-H engineering proofs, actual browser debugger, FPS/input/presentation and normal
unsigned packaging/lifecycle pass. Reference regressions: 23 passed; generic world
extensions: 8 passed. Runtime/Player/adapter production source is unchanged from
the successful soak. Generated Godot import metadata was removed from packaging
without changing runtime or gameplay identity. See docs/XP022_ENGINEERING_CERTIFICATION.md.

The source/binary/evidence baseline is sealed for engineering review by
tools/xp022_seal_engineering.py; its manifest is
docs/evidence/xp022-engineering-candidate.json. No Git ref, commit or push is part
of this freeze. NEC is NOT STARTED. The proposed engineering/release separation
in docs/XP022_RELEASE_GATES.md awaits explicit owner approval: REL-01 clean Windows,
REL-02 two-machine LAN, REL-03 public/two-network relay, REL-04 signing and REL-05
three first-time testers remain OPEN. The original combined public-release
acceptance is not marked passed. Local engineering is eligible for handoff under
that explicit amendment; external acceptance remains mandatory for release claims.

Historical pre-final audit (the local gaps below are now superseded):

Latest follow-up (2026-10-08): input-log quadratic hashing, redundant timeline
reconstruction, session-log write overhead and unbounded live replay/diagnostic
retention have been fixed. Segmented replay verification passes. The independent
soak failed at tick 24,747 because its repeated short reference input drove an
actor beyond the portable world bounds; p95 was 15.0235 ms and peak private memory
51.39 MiB. Corrected endurance input uses closed, separated routes inside the
fixture arena. A 100,080-tick reference regression passes across both rulesets.
The replacement two-hour soak PASSED: 7,200.860 seconds, 202,271 ticks,
12.0662 ms authority p95, two mutations and one reconnect. All 791 archived
segments replayed successfully across 202,271 ticks. Final gate reconciliation
did NOT support COMPLETE: full real-process Proof H, final pinned A-H and
packaging certification, and external acceptance remain open. See
docs/XP022_CLOSEOUT.md and docs/evidence/xp022-closeout-20261008.json.
The verified soak checkpoint is preserved; no final release baseline is frozen.

Historical initial checkpoint (superseded for retention, performance and soak):
added source/artifact-bound real-process certification subset, four-socket memory
preflight and streamed authority tick timing. Fresh four-native-host activation
and replay/socket fault subsets pass. The 600-tick preflight found private memory
growth from 2.17 MB to 46.22 MB; replay remains limited to 100,000 in-memory ticks.
Bounded durable recording/diagnostic retention must be resolved before the two-hour
soak. Full faults, performance, packaging and A-H acceptance remain open.
User confirmed signing certificate and first-time testers are unavailable; mark
pending along with previously deferred clean-machine and separate-network trials.
See docs/XP022_STATUS.md. No commit, push or protected-ref change.

## XP-021: COMPLETE FOR CONFIGURED LOCAL WINDOWS DEBUGGER PROFILE - 2026-10-04

Existing TickDebugger defaults to isolated inspection; breakpoints no longer
pause the authority. Generic event/frame/object navigation, component/contact
state, capabilities, dependencies, epoch markers, replay verification and proof
export are integrated. Live-copy capture and saved-file import use bounded IDs.
Creator controls require a trusted credential and session-wide confirmation;
legacy WebSocket mutation controls and shared demo lifecycle routes are fenced.
842 runtime, 22 reference, 9 debugger and 10 authoring tests pass, as do Builder
build/UI gates. Actual browser walkthrough locates frame 9/epoch 1, verifies its
replay, exports, captures/verifies a live copy and returns to live while authority
advances from tick 109 to 320. Guest pause is refused; creator pause/resume passes.
See docs/XP021_COMPLETION.md and docs/evidence/xp021-baseline.json for trusted
host/catalog/key setup and explicit trace/platform limits. XP-022 is next.
Protected main/safety refs remain at d3ef383; no commit or push. Earlier gates remain pending.

## XP-020: COMPLETE FOR WINDOWS OFFLINE CONFIGURATION-EPOCH REPLAY - 2026-10-04

Versioned sealed bundles retain initial snapshot, historical artifacts, applied
inputs/permitted feedback, membership release decisions and durable activation
records. Offline forks use the historical schedule and registered migration path.
Actual Player+Unity+Godot+Unreal recording contains 140 applied packets over 40
ticks; before/at/after-N, repeated replay and backward seek match hashes, canonical
state, events and schedules. 842 runtime and 22 reference-package tests pass,
including two activations, first divergence, corrupt/missing history and live
state isolation. No engine effects are emitted by headless offline verification.
Windows-only evidence; three-OS and rendered replay UI are not claimed. Recorder
seals on successful shutdown, not crash recovery. See docs/XP020_COMPLETION.md
and docs/evidence/xp020-baseline.json. XP-021 is next, not started.
Protected main/safety refs remain at d3ef383; no commit or push. Earlier gates remain pending.

## XP-019: COMPLETE FOR LOCAL CONFIGURATION ACTIVATION PROFILE - 2026-10-04

Work remains isolated in target/xp016-work. Generic durable activation switches
the preserved world at tick N after candidate/parent/readiness validation.
Actual Player+Godot, Unity+Godot+Unreal and all-four proofs pass 40 ticks with
old epoch through 7 and new epoch from 8, matching state/events and owned inputs.
Join probes at 7/8/9, real restart refusal, four injected failure points and
idempotency pass. Ordinary snapshot restore cannot cross a committed epoch.
842 runtime and 21 reference-package tests pass; production build passes.
Recovery after durable decision deliberately ends the prior session. Migration
remains registered read-only configuration replacement; other hooks fail closed.
See docs/XP019_COMPLETION.md and docs/evidence/xp019-baseline.json.
XP-020 is next, not started. Earlier environment gates remain pending.
Protected local main/safety refs remain at d3ef383; no commit or push.

## XP-018: IMPLEMENTED - ISOLATED CONFIGURATION CANDIDATES VERIFIED - 2026-10-03

Generic digest-addressed candidates bind approval, parent epoch/snapshot and exact
CGS/plan/world artifacts. Isolated snapshot migration uses MutationGate and runs
twice with matching hashes/events. The reference package proves the third-attempt
configuration changes behavior from preserved state. Unsupported structural,
world and state-transforming migrations fail closed; activation remains XP-019.
Actual Builder/GDE/Factory/SGC approval and compilation proofs pass, along with
real session-controller snapshot/journal isolation. 857 runtime/reference Rust
tests and 10 Builder authoring tests pass. See docs/XP018_COMPLETION.md and
docs/evidence/xp018-baseline.json. No protected refs moved; no commit or push.
Earlier pending environment gates and missing-cosmetic limitation remain open.

## XP-017: COMPLETE FOR LOCAL MIXED-ENGINE PROFILE - 2026-10-03

Continuing in target/xp016-work, based on clean-main-candidate 39ed07b.
Generic proof clients and a four-controller reference package now exercise
Player+Godot, Unity+Godot+Unreal and the four-client combination under one authority.
All three combinations pass 40 authoritative ticks, with distinct owned players,
matching applied projections/events and recorded inputs verified against the host.
Each rejects a mismatched world and survives one client departing after tick 19.
The reference package proves a shared event changes another owner's state at tick 7.
Unity's JSON object reader now accepts whitespace after commas, uncovered by the
pretty-printed proof configuration. The exported Player proof sends recorded
input outside assertions, since release builds omit assertions.
Rendered Player recordings, host hashes, applied client digests and source/build
fingerprints are retained. Unity's 15-case contract regression also passes.
See docs/XP017_COMPLETION.md and docs/evidence/xp017-baseline.json.
XP-018 is next. Earlier clean-machine/two-machine/Internet gates remain pending;
this same-computer certification makes no remote-network or latency claim.
Protected main/safety refs remain untouched; no changes have been pushed.

## XP-016: IMPLEMENTED - NATIVE HOST CONTRACT GATE VERIFIED - 2026-10-02

Work is isolated on branch xp-016, based on clean-main-candidate 39ed07b.
Local main and safety/pre-clean-main-20261002 remain at d3ef383; GitHub main
and its dated archive remain at aaa15fc. No XP-016 changes have been pushed.
Generic native world/session readers, authority-requested input and canonical
coordinate/geometry presentation are implemented; Godot and Player share a reader.
Installed Godot 4.6.3 and Unreal 5.7.4 pass 15 transcript cases, native geometry
and input fencing, plus real eight-tick authority/reconnect proofs at generation 2.
Unreal Development/Shipping builds pass. Unity Personal is now active, and the
installed Unity 6000.4.9f1 editor passes all 15 contract cases, native geometry
and input fencing after fixing a missing applicator in the proof scene setup.
The license gate is closed; the retained evidence records the successful retry.
Exported Player input/lifecycle and selected presentation regressions pass.
The full older XP-009 missing-cosmetic standalone case fails unchanged authority
package admission before launch; it is recorded, not silently marked passing.
13 Rust contract, 35 project, 7 launch and 14 engine-routing tests pass, along with
reversible installation/handoff and real two-client synchronization regressions.
See docs/XP016_COMPLETION.md and docs/evidence/xp016-baseline.json.
XP-017 has not started. Earlier pending environment gates remain pending.

## XP-015: IMPLEMENTED - LOCAL TLS VERIFIED - INTERNET GATE PENDING - 2026-10-02

Configured Player invitations now use an operator-provisioned TLS 1.3 relay with
single-use grants, scoped leases, fixed package/game routes and bounded resources.
Exported Players share one creator authority; transient tunnel loss recovers through
verified baseline generation 2. Relay outage fences remote membership, preserves
local host play and reports interruption without silent plaintext fallback.
7 launcher and 2 relay unit tests pass, alongside exported relay/resource proofs,
Player UI and XP-014/XP-010 regressions. No core gameplay/world changes were needed.
Public deployment and two-network acceptance remain pending by explicit owner
instruction (no hosting available). XP-014 two-machine and XP-010 clean-machine
gates are also pending. XP-016 is next, not started. See docs/XP015_COMPLETION.md,
docs/XP015_DEPLOYMENT_AND_TWO_NETWORK_TEST.md and docs/evidence/xp015-baseline.json.
Earlier checkpoints below are historical.

## XP-014: IMPLEMENTED - SAME-HOST VERIFIED - TWO-MACHINE GATE PENDING - 2026-10-02

Native Play/Invite/Join now shares one authority through expiring single-use private
session invitations, bounded verified data acquisition and trusted installed Players.
Builder and Player expose progress, readiness and leave/end. Controllers come from
CGS; no mechanic-specific session concepts were added. Final exported two-Player,
refusal/cancellation/readiness and native lifecycle proofs pass. Journals survive end.
6 launcher, 705 runtime and 7 network tests pass, plus Builder/Godot UI checks.
Two-machine acceptance is pending by explicit owner instruction (no second machine);
XP-010 clean-machine acceptance is also still pending. XP-015 is next, not started.
See docs/XP014_COMPLETION.md and docs/evidence/xp014-baseline.json.
Earlier checkpoints below are historical, not current task recommendations.

## XP-013: IMPLEMENTED - LOCAL SYNCHRONIZATION PROFILE VERIFIED - 2026-10-01

Versioned full projections now carry tick/epoch, digest, baseline ID and connection
generation. Required-input membership follows exact current-baseline acknowledgement.
Late join, bounded full replacement, gap recovery, timeout fencing and rotated-token
reconnect preserve canonical player identity without adding gameplay concepts.
705 runtime, 7 network and 8 session-contract tests pass, as do the real two-client
XP-013 proofs, 13 admission regressions, 6 input regressions, client stale/gap checks
and a five-tick staged Godot run. See docs/XP013_COMPLETION.md and
docs/evidence/xp013-baseline.json. XP-014 is next; remote/cross-engine certification
and XP-010 clean-machine acceptance remain pending. Earlier sections are historical.

## XP-012: IMPLEMENTED - LOCAL TWO-PLAYER PROFILE VERIFIED - 2026-10-01

The live bridge admits up to four separately granted controllers and binds each
socket to its canonical player entity. Generic targeted actions require entity
authority. Existing malicious-input, cheat, rate and lockstep modules now guard
the authoritative Input phase; accepted values use a 1/1024 quantization grid.
A typed numbered tick request drives Player input, including empty idle packets.
Incremental bounded reads survive fragmented frames; handshakes have a 1.5-second
deadline, and an unresponsive required peer is disconnected and logged after
five seconds. Live presentation feedback cannot enter authoritative feedback.
Two-peer real-socket ownership, replay/future/rate, arrival-order, fragmentation,
idle, incomplete-handshake and timeout proofs pass. The Godot Player ran five
requested-input ticks; 704 runtime and 6 network library tests, plus all twelve
XP-011 socket regressions, pass. XP-013 baseline/reconnect and XP-017 actual
cross-engine play remain pending. XP-010 clean-machine acceptance remains
pending by owner instruction. See docs/XP012_COMPLETION.md and
docs/evidence/xp012-baseline.json.

## XP-011: IMPLEMENTED - LOCAL PROFILE VERIFIED - 2026-10-01

The real bridge now requires the typed gameplay/session identity and one-use local
player grant for live play. It creates fresh session/incarnation UUIDs, derives exact
CGS/SGC/world/package/input/runtime identities from verified loaded artifacts,
negotiates presentation separately, and records session start, admissions/rejections,
validated inputs and departure durably. Rejected sockets gain no player ownership or
required-input membership. Twelve real socket cases and an exported Godot Player
30-tick run pass; 704 runtime-core, 8 shared-contract and 6 network-core tests pass.
Unity-shaped wire/presentation negotiation is verified; running Unity play remains
XP-017. XP-010 clean-machine acceptance remains pending by owner instruction.
XP-012 current status is above. See docs/XP011_COMPLETION.md and
docs/evidence/xp011-baseline.json.

## XP-010: IMPLEMENTED - CLEAN-MACHINE GATE PENDING - 2026-09-30

Pinned Windows distribution, native verified install/broker and generic Builder
Play/Stop/progress/retry are implemented. Verified: 2 native tests, 366 broad Builder
backend tests, final 6 route/service tests, real-browser UI, native lifecycle and
no-argument desktop launch. First install to ready measured 10.641 seconds; package
ZIP 39,546,841 bytes. Port collision, denied install/retry, stale repair, repeat Play,
failed launch rollback and crash/EOF authority cleanup pass. Builder discovers the
verified per-user installation and rejects stale saved-project packages.
Owner explicitly requested clean-machine acceptance remain pending (no clean PC/VM).
Same-host restricted PATH is not that certification. XP-011 status is above.
See docs/XP010_COMPLETION.md and docs/evidence/xp010-baseline.json.

## XP-009: COMPLETE - 2026-09-29

Generic typed Player presentation catalog, data-only mesh/PNG/WAV/ring/camera
formats, canonical world binding readiness, collision overlays and reported
fallbacks are implemented. Native emitted-event projection remains mechanic-agnostic.
Verified: 704 runtime library + 35 targeted Rust tests, 35 Python tests, 27 Godot
assertions, six exported Player/native scenarios. Two cosmetic variants preserve
all 30 authoritative hashes. Duplicate/restore/expiration, missing assets, binding
mismatch and tamper proofs pass. Same 31 prior inventory findings. Scope remains
local pre-admitted Windows package and explicit formats; no universal format or
remote-session claim. Next: XP-010 (not started).
See docs/XP009_COMPLETION.md and docs/evidence/xp009-baseline.json.

## XP-008: COMPLETE - 2026-09-29

Exported Windows local Player verifies its admitted package and runs an owned Rust
sidecar. Typed canonical visuals, controller-based ownership, parent transforms,
keyboard/focus input and runtime-loss freeze replace fixed demo assumptions. Generic
native host registration admits the reference package without core mechanic branches.
Verified: 704 runtime library + 51 targeted Rust tests, 25 Python tests, 8 Godot
presentation assertions, and identical 30-tick hashes at 30/144 FPS in real exported
Player/native processes. Lifecycle/tamper/direct-launch proofs pass. Inventory has
only the same 31 existing findings. Single pre-admitted package, local keyboard
lockstep scope; no remote/clean-machine/rich-asset claim. Next: XP-009.
See docs/XP008_COMPLETION.md and docs/evidence/xp008-baseline.json.

## XP-007: COMPLETE - 2026-09-29

Generic playable package construction, Factory/SGC/world verification, explicit
trusted executor admission and staged installation are implemented. Native world
startup preserves v3 semantic bindings across snapshot restore. Relocated native
execution produced identical four-tick hashes with toolchains absent from child PATH.
Verification: 22 project-system tests, 703 runtime library tests and 48 targeted
Rust tests pass. Inventory retains exactly 31 prior findings. No graphical Player,
clean-machine installer or multiplayer claim. Next: XP-008, including ordinary
host registration of required package systems; no mechanic-specific core branches.
See docs/XP007_COMPLETION.md and docs/evidence/xp007-baseline.json.

## World extensibility correction: COMPLETE - 2026-09-28

Owner authorized concrete correction before XP-007, including project-defined
semantic nouns, schema-validated extension data, independent geometry profiles,
compound/instance bindings and generic authoring. Preserve legacy v2 bytes.
Gate passed: 1,135 broad Python tests; final 32 targeted Python and 48 Rust tests;
541 core and 701 runtime library tests. Eleven data-only semantic concepts round-trip
without core noun enums; both reference configurations retain tick hashes/events
after explicit migration. Later tasks amended. See WORLD_EXTENSIBILITY_COMPLETION.md.
XP-007 may now proceed; native host/package integration remains its own work.

## XP-007 preflight audit: FIX REQUIRED - 2026-09-28

Owner-requested audit of XP-002 through XP-006 overrides the earlier READY FOR
XP-007 recommendation. Wall-run/jump/shockwave rules remain package-local, but the
World Contract conflates universal binding with a closed AABB profile. XP-006
requires actors/World Contract v2/empty-world templates even when not required by
a package. Custom actor types and richer bindings lack an end-to-end extension
path. Fourteen non-mutating probes and nine passing reference tests substantiate
both the working fixture boundary and current limits. No production refactor or
XP-007 implementation started. Apply the minimal contract/profile and authoring
correction in docs/XP007_PREFLIGHT_ARCHITECTURE_AUDIT.md before XP-007.
Historical completion reports certify only their declared profiles.

## XP-006 complete: generic gameplay authoring - 2026-09-28

Catalog-backed typed package selection now uses Builder clarification, full CGS
preview, approval, GDE atomic mutation and real Factory/SGC compilation. Package
capabilities, templates and configuration are data; the host separately registers
supported system contracts. No runtime, World Contract, network or adapter gameplay
branch was added. The reference host has replayed both approved configurations.
Verification: 1,128 affected Python tests pass (including 10 new authoring tests),
9 reference Rust tests pass on newly approved artifacts, and Builder TypeScript/UI
checks pass. Source inventory retains exactly the same 31 prior omissions. Explicit
host registration is required; no default runtime enrollment or provider/live/native
certification is claimed. See docs/XP006_COMPLETION.md and
docs/adr/XP-006-gameplay-authoring.md. READY FOR XP-007; XP-007 has not started.

## XP-005 complete: Reference Mechanic Proof - 2026-09-25

The required capability correction is implemented: World Contract v2 carries
package-owned namespaced declarations and generic role constraints, with separate
platform/semantic admission and an artifact-bound compatibility check. Explicit
recompilation is required; historical v1 fixtures are preserved.

The removable examples/reference-mechanic package owns all wall-run/jump/counter/
reversal/shockwave rules in ordinary GCL state/config and an ISystem. Its real
Factory/SGC persisted plan has one movement writer. No authoritative infrastructure,
World Contract, network or adapter mechanic-name branch was added.

Verification: broad Rust 1,934 passed; final reference 9/9 and contract 14/14 passed
(overlapping counts); official Python 1,135 passed. Real compiler goldens, full
recorded event/hash replay, actual impulses, landing/corner/held-edge behavior,
rollback and normal package removal pass. No live/native/network/performance claim.
Source inventory retains 31 prior omissions. See docs/XP005_COMPLETION.md,
 docs/adr/XP-005-reference-mechanic.md and docs/evidence/xp005-baseline.json.
READY FOR XP-006; XP-006 has NOT started. The earlier amendment gate is resolved.

## Roadmap amendment: mechanic-agnostic core - 2026-09-24

Wall-run/wall-jump/third-attempt reversal + shockwave is a removable reference proof
fixture only. XP-005 is Reference Mechanic Proof through ordinary gameplay-system,
package/catalog paths; XP-006 delivers generic capability/dependency-aware authoring.
XP-017 through XP-021 now separate generic product acceptance from fixture evidence.
No extra mechanics or XP-005 implementation were started. Documentation only.

Review found XP-004 geometry/query APIs contain no mechanic-specific rules, but
XP-003 Python/Rust validation special-cases world.wall_runnable.v1 and uses a closed
semantic capability list inherited from XP-001 session contracts. Before XP-005,
correct that shared capability path to generic namespaced package declarations and
data-driven constraints, retaining validation/versioning and platform admission.
This is an existing-contract correction, not a new mechanics task. Historical
completion evidence is preserved; the prior READY FOR XP-005 recommendation is now
conditional on this correction. See the binding amendment and revised tasks in
 docs/XACE_PLAYER_LIVE_SESSION_WORLD_ROADMAP.md.

## XP-004 complete: authoritative geometry queries - 2026-09-24

Authorized task: XP-004 only. Scheduled context now exposes bounded swept AABB,
overlap, ground/side probes and squared-distance targeting from canonical runtime
components. Exact rational contacts use stable World Contract IDs when bound.
Invalid queries halt and roll back the scheduled tick, including earlier movement,
events and RNG audit state. Mutations remain exclusively through MutationGate.

Verification: 1,924 Rust tests pass, zero failures/ignored (34 result groups),
including 18 new geometry tests, 5,766 gap-oracle cases, XP-003 golden compatibility,
snapshot replay hashes and guarded transaction rollback. Windows x64 only; no
performance or additional native/network certification. Source inventory retains
31 prior omissions. Package identity activation wiring remains XP-007 work.
See docs/XP004_COMPLETION.md, docs/adr/XP-004-authoritative-geometry.md and
 docs/evidence/xp004-baseline.json. READY FOR XP-005; XP-005 has NOT started.

## XP-003 complete: World Contract v1 compiler - 2026-09-24

Authorized task: XP-003 only. Schema Factory now produces an opt-in immutable
world artifact from CGS actor blueprints, with stable IDs/bindings, bounded fixed
point boxes/triggers/spawns/anchors, capabilities and typed asset requirements.
Canonical bytes/hash have a separate manifest bound to source CGS and the compiled
schema package. Shared Rust types validate/read/hash the exact Python output.
No frozen component, runtime authority, engine adapter or legacy CGS was changed.

Verification: 1,906 selected Rust tests (including 23 malformed world vectors),
1,130 official Python tests (338 Builder, 233 inference) and 13 final focused
world tests pass. Real six-object golden compilation/reorder/provenance proof
passes. Rejected GDE edits restore state and preserve CGS/world/manifest files.
The source inventory's 31 prior omissions remain outside this task. XP-002 legacy
migration limitations remain; XP-003 does not opt legacy projects in silently.
See docs/XP003_COMPLETION.md, docs/adr/XP-003-world-contract.md and
 docs/evidence/xp003-baseline.json. READY FOR XP-004; XP-004 has NOT started.
Future package/authoring distributions must include the reused strict validator.
No geometry execution, native reader, live networking or launch claim is added.

Historical checkpoint follows.

## XP-002 complete: compiler and live authority boundaries - 2026-09-24

Authorized task: XP-002 only. Builder now validates candidates through the real
Schema Factory and uses its compiled projection for SGC. External runtime inputs
are staged and applied by an explicitly scheduled EngineInputSystem through
MutationGate. Preview edits use isolated stores. --live-session requires persisted
SGC ingress, rejects preview writes and blocks native physics/visibility feedback.

Verification: 1,901 broad Rust tests and 7 final focused boundary tests pass;
1,121 final official Python tests pass (329 Builder, 233 inference). Builder lint,
typecheck, UI contracts and build pass. Real Builder/GDE/Factory/SGC/runtime proof
retains equal repeated world reports, rejection artifact hashes and GDE rollback.
Old default templates and exports with undeclared DCL/noncanonical fields now
fail closed and require explicit migration; no production CGS was rewritten.
Approval/rollback integration fixtures were migrated to declared structured UCL.
Source inventory's 31 pre-existing omissions remain outside this task.
See docs/XP002_COMPLETION.md, docs/adr/XP-002-authority-boundaries.md and
docs/evidence/xp002-baseline.json. READY FOR XP-003 for the supported profile;
XP-003 has NOT started. No native engine, networking or product launch claim.

Historical checkpoint follows.

## XP-001 complete: supported session identity baseline - 2026-09-23

The owner approved the XP-001 through XP-022 roadmap and authorized XP-001 only.
XP-001 now provides opt-in shared typed contracts, deterministic compatibility
checks, provenance hooks, 50 golden vectors and the supported-profile ADR.
Existing CGS/SGC/runtime and legacy session workflows remain unchanged. DCL's
normal Python gate import configuration is repaired (14 tests, isolated mode).
Verification: 1,895 selected Rust tests; 1,107 official Python tests (315 Builder,
233 inference/API-BYOK); Builder lint/typecheck/UI/build all pass. Repository
source-inventory omissions outside XP-001 remain a pre-existing documentation
backlog. No Player/native/network/geometry implementation or authority wiring.
See docs/XP001_COMPLETION.md, docs/adr/XP-001-supported-session-contract.md and
docs/evidence/xp001-baseline.json for exact scope, commands, files and evidence.
XP-001 acceptance is satisfied; READY FOR XP-002. XP-002 has NOT started and
requires the user's next instruction. Historical design-only checkpoint follows.

## Proposed Player / Live Session / World Contract roadmap - 2026-09-23

Design-only repository audit completed at the user's request. No milestone
implementation was started and no existing completion checkbox was changed.
Review artifact: docs/XACE_PLAYER_LIVE_SESSION_WORLD_ROADMAP.md (XP-001 through
XP-022, all proposed). Recommended direction: exported Godot-backed Player,
one Rust session authority using existing network-core contracts, and a minimal
CGS-derived fixed-point world/contact layer. Freeze the roadmap before engineering.

Fresh verification: 1,346 selected Rust tests passed; 545 Python gate tests
passed, with DCL discovery failing on a missing packages import. Direct DCL and
focused Builder authority tests passed all 45 tests. The runner defect is recorded
for XP-001; it was not fixed during this design-only session. Existing uncommitted
work was preserved. Historical installed-engine artifacts were not rerun; retained
Windows-only replay and simulated network-chaos evidence have narrower scope than
the proposed simultaneous cross-engine live session. Next engineering task after
roadmap approval: XP-001 contract/fixture baseline, followed by XP-002 authority
and Schema Factory integration repairs.

## AG-030 complete for development/early users - 2026-09-23

Product owner explicitly accepted upstream dependency risk for development/early
users, subject to pinning, replaceability, fail-closed behavior, unchanged
API/BYOK fallback and re-evaluation before public production. Official docs and
actual launch/config/API surfaces are recorded in docs/CODEX_APP_SERVER_SURFACE.md.
Acceptance is saved in docs/evidence/codex-ag030-review.json. All six final gates
passed: implementation, full Builder regression, browser setup/support, build,
API/BYOK regression and documentation. Source-bound evidence validated; no
blockers. docs/evidence/codex-ag030-completion.json records
codex_integration_complete: true / complete_for_declared_configuration.
Zero Codex integration tasks remain in AG-022 through AG-030. This is not public
production or whole-XACE launch approval. No production implementation or
security checks were changed by this review.

## Historical AG-030 implementation checkpoint - 2026-09-23

Phase/module: Phase 14 Builder Codex integration only. AG-029 remains complete.
AG-030 engineering implementation and all six final gates pass; product-owner
acceptance of the upstream App Server support risk is still pending.

Implemented terminal-free local runtime provisioning in Builder: official
pinned archive download link, local path and explicit consent, verified copied
bytes/recipe, cancellable local Docker build, OS-held build lock, atomic image
pin, invalid-pin repair, prior selection preserved on failure. No model setup
tool, automatic binary redistribution, raw shell or credential access added.

The real protected setup endpoint passed authorization/consent/build/readiness
checks without provider calls. UI browser consent/fallback checks pass. A fresh
real-account run passed all AG-029 scenarios on selected image
sha256:8f98e06bc7f94a8edf11ca2d4ac3c6eef4b8e574fef1fdbd33364a6c0c38304e;
credential-free isolation passed on the same image. Login volume is retained.

The final completion gate now validates fixed source-bound live/isolation/setup
records and a dated, nonempty defect/risk review. All 93 Builder production
Python/TypeScript sources are bound to the review. Missing/stale/partial/changed
evidence, unresolved P0/P1 and unaccepted residual risk block completion.
The draft inference command was corrected to tools/python_test_gate.py --suite
inference: all 233 API/BYOK tests pass. Final aggregate run also passes the full
Builder regression (including the added completion case), browser setup/support,
production build, implementation/conformance checks and documentation gate.
The final Agent static boundary check reports no findings; diff check passes
with only existing line-ending notices. Canonical completion report:
docs/evidence/codex-ag030-completion.json. It records exactly one blocker:
risk_acceptance_pending_upstream_support. No final completion claim is made.

Remaining decision: official App Server documentation still describes the
command as experimental and unsupported for production workloads. The owner
was asked to accept that P2 risk only for the pinned limited integration, with
fail-closed admission, API/BYOK fallback and mandatory review before public
launch. No acceptance has been inferred from a request to continue.
See docs/CODEX_INTEGRATION_HANDOFF.md and docs/evidence/codex-ag030-review.json.
Do not mark codex_integration_complete true until the actual gate passes.
Whole-XACE launch, native Windows isolation, Local and Claude remain outside scope.

## AG-029 completed checkpoint - 2026-09-22

Phase/module: Phase 14 Builder Agent Mode. AG-029 complete for Windows x64,
Docker Desktop / WSL 2, pinned official Codex 0.155.1 and the opted-in account.
AG-030 is the only remaining Codex integration task; it is not complete.
Local/Claude and native Windows isolation remain deferred/non-blocking.

Implemented: backend-neutral execution contract; production-selected isolated
Codex adapter shared by registry/Builder/setup/status/auth; host-only MCP relay;
verified local image build and atomic pin; graceful missing-dependency fallback;
functional device-code setup and regression coverage. No API/BYOK default change.

Real-account certificate passes every required check: native auth/models/limits,
MCP, streamed history, typed preview, approval denial/handoff, actual GDE and SGC
on a disposable approved copy, rejection persistence, resume/fork, compaction,
cancellation and explicit outage recovery. Source CGS unchanged. New selected
local image: sha256:4acbbf9ebd8622f3785ea3d26f9cb642adae2990e3840345c3fc3a674df3c6b3.
Credential-free synthetic isolation also passes on this image. The existing
dedicated provider volume/login is retained, not copied or deleted.

Evidence and requirements: docs/CODEX_REAL_ACCOUNT_CERTIFICATION.md,
docs/evidence/codex-ag029-host.json, docs/evidence/codex-ag029-isolation.json,
docs/CODEX_DOCKER_BACKEND.md. Final verification: 304 Builder tests passed (217.455s), including the new
strict-certificate regression; native + isolated real-browser setup passed;
lint/typecheck, UI contracts, production build and static Agent boundary checks
passed. git diff --check passed (only existing LF/CRLF notices). No owned
agent-execution containers remain running; provider login volume is retained.

AG-030 must still assess the upstream App Server experimental support caveat,
aggregate integration risks/evidence and address/accept the initial operator
local-build step against its ordinary-user setup criterion. No public bundling,
automatic updates, every-platform or whole-XACE launch completion is claimed.

## AUDIT DECISIONS LOCKED (Reference Before Building Any File)

Audit 1 - Component Architecture: UCL=10 frozen, DCL=domain packages XACE-owned, GCL=developer-owned in game project
Audit 2 - Asset Pipeline: AssetReference typed struct not raw string, 4 states PLACEHOLDER/LINKED/MISSING/UNRESOLVED, auto-naming convention, Animation Contract generated from COMP_ANIMATION_V2
Audit 3 - Animation Depth: COMP_ANIMATION_V2 with layers dict + pending_events list, COMP_IK_V1, AnimationEventSystem in dcl/character/
Audit 4 - Zero-Experience User: Game Genesis Engine + Natural Language Translation Layer + Design Mentor, 30 genre templates, all Phase 16
Audit 5 - Multiplayer: Lockstep + rollback (auto-selected by game type), InputSynchroniser lockstep gate, cheat guard ALWAYS ON all modes, Phase 15
Audit 6 - Engine Feedback: Bidirectional XACE-Engine, 10 feedback message types, feedback enters XACE at tick boundaries only, visibility queries one-tick delayed
Audit 7 - Save/Load/Persistence: 3-layer save (game progress, player profile, schema version), 4 new DCL persistence components, schema migration on load, cloud sync abstraction
Audit 8 - AI Inference Pipeline: packages/inference/ built BEFORE Phase 13 starts. All LLM calls go through inference_adapter.py â€” NO direct HTTP/API calls anywhere in PIL. complexity_classifier routes TIER_S intents to deterministic Phase 12 path (no LLM). prompt_cache.py wraps Anthropic cache_control on static prefix. telemetry_pipeline.py emits per-call cost events from day one of PIL. code_generation retry loop hard-capped at 2; escalate to clarification on third failure. No BYOK before beta.
Audit 9 - Context Assembly: context_budgeter.py enforces 8K dynamic token hard cap per call â€” reject + telemetry on exceed. dependency_expander capped to 1-hop reads, 2-hop writes by default, configurable per mode. Static sections (determinism rules, constraints, stable memory layers) live in cached prefix via prompt_cache, NOT in per-prompt body. diagnostic_orchestrator.py handles explain/debug/replay-divergence prompts on a 2-pass explainâ†’suggest path, NOT through the 5-pass mutation pipeline. memory layers Design/Structural/Behavioral go in cached prefix; Session/Safety go in per-prompt body.

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
Phase 13  - Prompt Intelligence Layer + Inference Package (6-8 weeks)
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

Phase 9 Status: [x] Complete
Notes: hash@1000 = 0b1d495d59a76609fdd15511294f5e132c5b62b9b72fb22b0acf61fac2c3e178. Milestone 1 proven.

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

Phase 11 Status: [x] Complete
Notes: 127/127 tests passing.

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

Phase 12 Status: [x] Complete
Notes: All 187 tests passing (127 Phase 11 + 60 Phase 12 GDE).

---

## PHASE 13 - PROMPT INTELLIGENCE LAYER + INFERENCE PACKAGE
Target: 6-8 weeks
Note: Build 13.16 Inference Package FIRST before any other Phase 13 submodule. All PIL files import from packages/inference/ â€” never speak HTTP directly.

### 13.1 Intent Intake (packages/prompt-intelligence/src/)
- [ ] intent_intake_layer.py - entry point normalise + classify + risk pre-scan + envelope
- [ ] prompt_normalizer.py - trim, quote-normalise, control-char strip, language detect, token estimate
- [ ] intent_classifier.py - 9 categories: CreateFeature|ModifyFeature|RemoveFeature|QueryExplain|DebugIssue|BalanceAdjustment|StructuralChange|WorldDesign|Unknown
- [ ] risk_prescanner.py - blocks engine-internal mutation attempts, code injection, invalid scope â€” routes to Safety Guard
- [ ] intent_envelope.py - IntentEnvelope struct: intent_category, normalised_text, assistance_mode, risk_score, confidence_estimate

### 13.2 Context Assembler (packages/prompt-intelligence/src/)
Note: All output fed to context_budgeter.py before reaching LLMContextPacket. dependency_expander capped 1-hop reads / 2-hop writes per Audit 9.
- [ ] context_assembler.py - orchestrates assembly; calls context_budgeter to validate token count; FULL SCHEMA TRANSMISSION FORBIDDEN
- [ ] relevance_extractor.py - identifies relevant entities/components/systems/rules from intent; excludes irrelevant
- [ ] dependency_expander.py - expands to required dependencies; HARD CAP 1-hop reads 2-hop writes; feeds system_graph_pruner on overflow
- [ ] constraint_aggregator.py - injects architectural constraints (D1-D15, R/W contracts, phase rules); OUTPUT GOES IN CACHED PREFIX not per-prompt body
- [ ] scope_builder.py - builds AllowedMutationScope: allowed_paths, forbidden_paths, max_mutation_depth, structural_change_allowed per mode
- [ ] schema_simplifier.py - converts ECS structures to compact LLM-friendly format; TARGET 60% size reduction vs raw CGS slice
- [ ] llm_context_packet.py - LLMContextPacket struct: game_metadata, relevant entities/components/systems/rules, constraints, scope, simplified_schema

### 13.3 LLM Orchestrator 5-pass (packages/prompt-intelligence/src/)
Note: All passes call inference_adapter.py from packages/inference/ â€” NO direct HTTP. Passes 3 and 4 routed to TIER_M by model_router (validation-shaped not generation-shaped).
- [ ] llm_orchestrator.py - 5-pass pipeline orchestrator; consumes LLMContextPacket once; passes share cached context
- [ ] pass1_planning.py - PASS 1 Structured Planning: ReasoningPlan target_entities + intended_mutation_type + risk_assessment; no DSL yet
- [ ] pass2_dsl_draft.py - PASS 2 DSL Mutation Draft: DraftMutationTransaction with paths + operations + values
- [ ] pass3_self_critique.py - PASS 3 Self-Critique: validates draft against path validity + constraints + scope; triggers regen on failure
- [ ] pass4_determinism_audit.py - PASS 4 Determinism Audit: checks D-rules + hidden dependencies + flags required_execution_graph_recompile
- [ ] pass5_final_output.py - PASS 5 Final Output: MutationTransaction with confidence_score + risk_level + schema_delta_type + required_recompile
- [ ] pil_retry_policy.py - PIL-level retry: bounded max 3 total passes per re-attempt; escalate to ClarificationEngine on exhaustion; distinct from inference-level retry in packages/inference/

### 13.4 Structured Output Parser (packages/prompt-intelligence/src/)
- [ ] structured_output_parser.py - strict JSONâ†’CanonicalMutation parser; safety boundary between probabilistic LLM output and deterministic pipeline; any deviation = reject
- [ ] schema_path_validator.py - validates all paths in parsed mutation exist in current CGS; no hallucinated references
- [ ] operation_type_validator.py - validates op types against USMC + value types match component field definitions + no extra keys

### 13.5 Validation Loop (packages/prompt-intelligence/src/)
- [ ] validation_loop.py - multi-layer validation: structural + type + dependency + invariant; runs Phase 12 ConsistencyValidator before any commit attempt

### 13.6 Critique Engine (packages/prompt-intelligence/src/)
- [ ] critique_engine.py - pre-commit internal review: cross-system impact + version compatibility + mutation completeness + side-effect analysis

### 13.7 Clarification Engine (packages/prompt-intelligence/src/)
- [ ] clarification_engine.py - ambiguity resolution: detects ambiguous targets + generates CHOICE|CONFIRM|FILL|SCOPE_SELECT questions
- [ ] clarification_session.py - session state: pending question + user response + pipeline resume point + timeout
- [ ] question_generator.py - generates structured micro-form questions schema-aware validated against CGS

### 13.8 Mutation Planner (packages/prompt-intelligence/src/)
- [ ] mutation_planner.py - builds CommittedMutationPlan: operation ordering + dependency resolution + rollback plan
- [ ] rollback_plan_builder.py - prepares rollback plan for each mutation: inverse operations + previous-state capture + atomicity

### 13.9 Safety and Scope Guard (packages/prompt-intelligence/src/)
- [ ] safety_scope_guard.py - final governance gate: 5 risk dimensions + risk threshold system â†’ Approved|SoftWarning|Blocked
- [ ] scope_boundary_guard.py - enforces mutation stays within allowed scope; blocks forbidden domains (engine core, runtime scheduler)
- [ ] destructive_change_guard.py - prevents deletion of core components/systems; analyzes cascade impact; requires confirmation in ADVANCED mode
- [ ] cascade_risk_guard.py - simulates indirect mutation impact across dependent systems; warns when too many systems affected
- [ ] performance_risk_guard.py - estimates runtime cost of mutation using real engine metrics from Phase 7 feedback handler
- [ ] determinism_safety_guard.py - blocks mutations that violate determinism: nondeterministic rules + unseeded random + cross-phase state changes

### 13.10 Memory Model 5 layers (packages/prompt-intelligence/src/)
Note: Design + Structural + Behavioral layers loaded into CACHED PREFIX via prompt_cache. Session + Safety loaded per-prompt per Audit 9.
- [ ] memory_model.py - 5-layer architecture: Session|Design|Structural|Behavioral|Safety; memory influences reasoning ONLY never runtime
- [ ] session_memory.py - SHORT TERM: recent prompts + mutations + clarifications + failures; cleared on session end; IN PER-PROMPT BODY
- [ ] design_memory.py - PERSISTENT: game vision summary + difficulty philosophy + core constraints; flags contradictory drift; IN CACHED PREFIX
- [ ] structural_memory.py - tracks all components/systems/rules created; assists DSL path resolution + prevents duplicates; IN CACHED PREFIX
- [ ] behavioral_memory.py - tracks player-observable patterns + pacing concerns + known broken moments; IN CACHED PREFIX
- [ ] safety_memory.py - records blocked mutations and accepted risk confirmations; prevents redundant safety alerts; IN PER-PROMPT BODY
- [ ] memory_lifecycle_manager.py - load: cached layers assembled once + per-prompt layers assembled each call; update after commit only; versioned alongside CGS

### 13.11 Mode Controller (packages/prompt-intelligence/src/)
- [ ] mode_controller.py - cross-cutting policy layer: FULLY_ASSISTED|COLLABORATIVE|ADVANCED|ARCHITECT_MODE profiles + mode switching logic
- [ ] pil_mode_profile.py - PIL-specific ModeProfile: clarification_threshold + auto_assumption_level + risk_block_level + explanation_level + suggestion_policy

### 13.12 History Manager (packages/prompt-intelligence/src/)
- [ ] history_manager.py - manages prompt history + mutation success/failure log + session lifecycle + history retrieval for context
- [ ] session_store.py - session data: recent prompts + recent mutations + recent clarifications + recent validation failures

### 13.13 Code Generation Engine (packages/prompt-intelligence/src/code_generation/)
Note: rust_code_generator calls inference_adapter NOT direct Claude API. Retry loop hard-capped at 2 per Audit 8; third failure escalates to clarification.
- [ ] code_generation_engine.py - orchestrates SystemSpec â†’ inference_adapter â†’ validated Rust implementation or error
- [ ] system_spec_builder.py - extracts complete spec from CGS: component types + field names + phase + determinism constraints + performance targets + ISystem interface requirements
- [ ] rust_code_generator.py - calls inference_adapter with full SystemSpec context; generates Rust struct implementing ISystem trait; max 2 retries on compile failure
- [ ] code_contract_validator.py - validates generated code against XACE contracts: correct ISystem interface + only declared components accessed + all writes via MutationGate
- [ ] cargo_compiler.py - runs cargo check on generated code + captures precise compile errors + feeds error + original spec back to generator for self-correction; HARD CAP 2 retries
- [ ] determinism_code_checker.py - static analysis on generated Rust: detects rand::random + thread_rng + direct mutation bypassing MutationGate + unordered iteration
- [ ] tests/test_code_generation.py - valid SystemSpec compiles; contract violations rejected; determinism violations caught; cargo error triggers self-correction; user diff shown before commit

### 13.14 Pipeline Entry Point (packages/prompt-intelligence/src/)
- [ ] pil_pipeline.py - orchestrates all PIL submodules in sequence; returns MutationTransaction or ClarificationRequest or BlockedMutation

### 13.15 Tests (packages/prompt-intelligence/src/tests/)
- [ ] test_intent_intake.py - all 9 classifications + normalisation edge cases + risk detection + IntentEnvelope output
- [ ] test_context_assembler.py - relevance extraction accuracy + dependency expansion cap enforcement + constraint injection + no full-schema leak + token budget rejection
- [ ] test_llm_orchestrator.py - all 5 passes + self-critique regen + determinism audit flags + retry policy + escalation path
- [ ] test_safety_scope_guard.py - all 4 risk levels + each guard module independently + determinism violations blocked + cascade detection
- [ ] test_pil_pipeline.py - full integration: promptâ†’MutationTransaction + clarification triggers + blocking scenarios + mode behaviour

### 13.16 Inference Package â€” BUILD FIRST (packages/inference/src/)
Note: This entire submodule must be complete before any other Phase 13 file is written. Every PIL submodule imports from here. Zero direct HTTP/API calls permitted outside this package.

Core dispatch:
- [ ] inference_adapter.py - single provider-agnostic dispatch point for all LLM calls; accepts InferenceRequest returns InferenceResponse; every PIL submodule imports this only
- [ ] provider_registry.py - maps logical model names (premium_reasoning|standard_mutation|cheap_validation|local_dev) to concrete provider client instances; hot-reloadable config
- [ ] model_descriptor.py - per-model metadata struct: provider + model_id + context_window_tokens + price_per_1k_input + price_per_1k_output + supports_cache_control + max_output_tokens + capabilities[]

Routing and classification:
- [ ] model_router.py - given ComplexityTier + BudgetContext + FailureContext selects provider+model; routes TIER_S back to deterministic Phase 12 path with no LLM call
- [ ] complexity_classifier.py - classifies IntentObject + LLMContextPacket size â†’ TIER_S (deterministic shortcut no LLM)|TIER_M (cheap model)|TIER_L (standard model)|TIER_XL (premium + code generation); TIER_S must correctly classify all simple value-set mutations

Token and cost:
- [ ] token_estimator.py - pre-flight tokeniser wrapper; approximates prompt token count before inference call; used by cost_estimator and context_budgeter
- [ ] cost_estimator.py - pre-flight cost calculation: token_estimate Ã— price_per_1k â†’ cents; validates against inference_budget; emits telemetry on over-budget
- [ ] inference_budget.py - per-session + per-user + per-day token budget enforcement; default infinite; interface ready for hard-cutoff without restructure; emits telemetry on approach and breach

Reliability:
- [ ] fallback_policy.py - declarative provider chain definition and execution: try primary â†’ secondary â†’ tertiary â†’ refuse_with_clarification; configurable per model_router tier
- [ ] inference_retry_policy.py - tier-aware retry distinct from PIL's pil_retry_policy: transport errors (retry immediately) vs schema failures (retry with correction) vs model quality failures (escalate); max 2 per tier

Caching:
- [ ] prompt_cache.py - wraps Anthropic cache_control directive; marks static sections (architectural constraints from constraint_aggregator + stable memory layers) as cacheable prefix; transparent to callers
- [ ] response_cache.py - deterministic output cache keyed by (intent_class + structural_cgs_hash + mode_profile); avoids re-inference on identical prompts against unchanged CGS; TTL configurable
- [ ] cache_key_builder.py - stable cache key computation: structural_hash of CGS (excludes volatile metadata fields) + intent_classification + mode_name; ensures cache keys survive cosmetic CGS changes

Telemetry and BYOK:
- [ ] telemetry_pipeline.py - emits one InferenceTelemetryEvent per call: provider + model + prompt_tokens + completion_tokens + cache_read_tokens + cache_write_tokens + latency_ms + outcome + cost_cents + tier; append-only log
- [ ] byok_manager.py - user-supplied API key management; encrypted at rest; per-user dispatch override in inference_adapter; pre-beta placeholder with full interface; activates in beta without restructure

Context efficiency (per Audit 9):
- [ ] context_budgeter.py - per-call token budget enforcer; hard-rejects context_assembler output exceeding 8K dynamic tokens (configurable); emits telemetry + raises ContextBudgetExceeded on breach; consumed by context_assembler.py
- [ ] cgs_diff_packer.py - computes structural delta from last cached CGS for repeat-prompt optimisation; avoids re-sending unchanged component defaults; keys by structural_cgs_hash
- [ ] rule_compactor.py - summarises rule expressions for context efficiency: sends compact rule_id + condition_outline + effect_summary instead of full expression strings; full text fetched only when needed
- [ ] system_graph_pruner.py - caps dependency_expander output to 1-hop reads + 2-hop writes by default; configurable max_hops per mode; hard token-count fallback if hop budget still exceeds context budget

Providers sub-package:
- [ ] providers/anthropic_provider.py - concrete Anthropic API client implementing provider interface; handles cache_control headers + streaming + error normalisation
- [ ] providers/openai_provider.py - concrete OpenAI-compatible client implementing provider interface; for future GPT-4o + local vLLM OpenAI-shim routing
- [ ] providers/local_provider.py - Ollama adapter implementing provider interface; for local dev and enterprise self-hosted inference; strips cache_control directives unsupported by local models

Prompt templates:
- [ ] prompt_template_registry.py - named versioned prompt templates for all PIL passes; prevents string literals scattered across submodules; version-pinnable per model; loaded at startup

Tests:
- [ ] tests/test_model_router.py - all 4 tiers + TIER_S deterministic shortcut + budget enforcement + fallback chain execution + provider registry lookup
- [ ] tests/test_complexity_classifier.py - TIER_S correctly classifies simple SET mutations + TIER_M covers balance changes + TIER_XL triggers code generation flag + edge cases
- [ ] tests/test_inference_budget.py - per-session cap enforcement + per-user cap + day reset + hard cutoff behaviour + telemetry emission on approach
- [ ] tests/test_prompt_cache.py - cache_control directives correct + static prefix cache hit + dynamic body always uncached + cache key stability across cosmetic CGS changes
- [ ] tests/test_telemetry_pipeline.py - event emission on every call + cost calculation accuracy + cache token accounting + append-only guarantee

### 13.17 Diagnostic Orchestrator â€” NEW (packages/prompt-intelligence/src/)
Note: Explain/debug/replay-divergence prompts MUST NOT go through the 5-pass mutation pipeline. This 2-pass path returns explanation + optional suggested mutation, not a committed mutation.
- [ ] diagnostic_orchestrator.py - routes diagnostic intent types (QueryExplain|DebugIssue) through 2-pass explainâ†’suggest flow; PASS 1 analysis: reads relevant systems + hashes + runtime telemetry; PASS 2 suggest: optionally generates IntentObject for mutation pipeline if fix is clear; never commits directly

Phase 13 Status: [ ] Complete
Notes:

---

## PHASE 14 - BUILDER WORKSPACE UI
Target: 3-4 weeks

- [ ] Left sidebar: CGS Explorer entities/components/systems/rules/versions
- [ ] Builder canvas: prompt input, clarification cards CHOICE|CONFIRM|FILL|SCOPE_SELECT, diff viewer shows schema changes + generated code side by side, impact preview panel, inference cost indicator per mutation
- [ ] Right preview: engine viewport, entity inspector edit triggers prompt not direct mutation, runtime stats, tick debugger
- [ ] Bottom bar: version timeline, snapshot history, branch manager
- [ ] Command palette: Cmd+K search all schema nodes
- [ ] Schema graph visualization: execution dependency view
- [ ] Asset status panel: placeholder count, link options, game runs as grey boxes message
- [ ] Technical details toggle: behavior varies per mode FULLY_ASSISTED shows translated technical ARCHITECT shows raw
- [ ] In-game console inside engine adapters: Idle->PromptSubmitted->PreviewReceived->UserDecision state machine
- [ ] Inference telemetry panel: per-session token spend + cost + cache hit rate + tier distribution (ARCHITECT_MODE only)

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

## INFERENCE INVARIANTS (LAWS â€” NEVER BREAK)

II1  All LLM calls go through inference_adapter.py. No PIL submodule speaks HTTP directly.
II2  complexity_classifier routes TIER_S intents to deterministic Phase 12 path. No LLM call for trivial SET mutations.
II3  prompt_cache wraps all static prefix sections (constraints, stable memory, determinism rules). Never sends static text uncached.
II4  context_budgeter enforces 8K dynamic token hard cap. Context that exceeds this is rejected before any LLM call.
II5  dependency_expander runs behind system_graph_pruner. Max 1-hop reads, 2-hop writes. No unbounded graph traversal.
II6  code_generation retry loop hard-capped at 2. Third failure escalates to ClarificationEngine.
II7  diagnostic_orchestrator handles QueryExplain|DebugIssue. These prompts never enter the 5-pass mutation pipeline.
II8  telemetry_pipeline emits per-call event for every inference call. Zero silent calls.
II9  Design + Structural + Behavioral memory layers go in cached prefix. Session + Safety go in per-prompt body.
II10 BYOK interface exists at startup. byok_manager.py is a pre-beta placeholder with full interface ready to activate.

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
- [ ] docs/07_global_invariants.md - I1-I14 + II1-II10
- [ ] docs/08_failure_classification.md
- [ ] docs/09_state_machines.md
- [ ] docs/10_versioning_and_build_order.md
- [ ] docs/11_inference_architecture.md - provider abstraction + routing + caching + telemetry + BYOK

---

## PROGRESS SUMMARY

| Phase | Name | Status | Started | Completed |
|---|---|---|---|---|
| 0 | Project Skeleton | [x] | | |
| 1 | Core Types + DCL + GCL | [x] | | |
| 2 | Runtime Core Foundation | [x] | | |
| 3 | Mutation Gate | [x] | | |
| 4 | System Executor + Event Bus | [x] | | |
| 5 | Snapshot Engine | [x] | | |
| 6 | Determinism Guard | [x] | | |
| 7 | Engine Adapter + Feedback | [x] | | |
| 8 | Delta Sync | [x] | | |
| 9 | Minimal Example Game | [x] | | |
| 10 | System Graph Compiler | [x] | | |
| 11 | Schema Factory | [x] | | |
| 12 | Game Definition Engine | [x] | | |
| 13 | Prompt Intelligence Layer + Inference | [ ] | | |
| 14 | Builder Workspace | [ ] | | |
| 15 | Network Core | [ ] | | |
| 16 | Zero-Experience Layer | [ ] | | |

---

## LAST SESSION LOG

Date: 2026-09-21
Phase worked on: Phase 14 - Builder Workspace, AG-029 isolation investigation
Results: Official Windows 0.155.1 rejects restricted reads in unelevated mode; elevated mode requires root read access. A credential-free loopback model probe finds apply_patch still exposed despite disabled native feature switches. Hooks are not a complete enforcement boundary per official documentation; no hook or security relaxation installed.
Verification: Six isolation-probe tests and five certification-preflight tests pass. No live-account certification or runtime activation. Production/API/BYOK unchanged. Details: docs/CODEX_REAL_ACCOUNT_CERTIFICATION.md.
Next: Decide and verify a separate OS/container isolation backend before adapting native request fields or consuming account usage. AG-029 and AG-030 remain incomplete.

---

Date: 2026-09-21
Phase worked on: Phase 14 - Builder Workspace, AG-029 official-runtime preflight
Authority: User explicitly approved isolated official runtime installation and bounded Codex/ChatGPT account tests. Do not ask for blanket permission again; credentials remain provider-owned.
Completed: Installed official npm Codex 0.154.0 and 0.155.1 in separate tmp/ag029-runtime-* directories; generated stable schemas and diagnostic-only 0.155.1 experimental schemas. Added tools/codex_certification_preflight.py with five passing tests and docs/CODEX_REAL_ACCOUNT_CERTIFICATION.md. Four prior AG-030 draft tests and eleven compatibility/resilience tests also pass.
Blocker: Both official stable schemas reject consumed thread/turn requests and omit restricted-read access; the 0.155.1 experimental schema also omits the read boundary. 0.155.1 additionally falls outside current admission range. No live account/model call or runtime activation occurred. Zero real configurations are certified; AG-029 and AG-030 remain incomplete.
Next: Establish a supported native contract enforcing the existing boundary or propose an independently verified equivalent isolation design for approval if it changes the architecture. Do not relax security, widen admission without evidence, or equate fixture success with live certification. API/BYOK and VS Code remain unchanged.


Date: 2026-09-21
Phase worked on: Phase 14 - Builder Workspace, AG-029 preflight
User correction: AG-029 is the active task, not AG-030. The accidentally started AG-030 draft tool, test and handoff document remain unverified and unfinished; no readiness marker was advanced.
What was completed: Current official App Server documentation reviewed; actual XACE executable resolution and fresh no-auth schema generation performed. Evidence: tmp/ag029-preflight/evidence.json (305 documents, same executable/schema hashes as AG-027).
Blockers: Only editor-private 0.154.0-alpha.6.2 resolves; prerelease admission and consumed-schema checks fail. Need a compatible official runtime and explicit opt-in account/model-usage consent. No live authentication, account probe or model turn ran; no runtime was installed or activated and no security check was relaxed.
Next step: Obtain runtime direction and live-test opt-in, then continue AG-029 in disposable projects. AG-029 and AG-030 remain incomplete; API/BYOK behavior is unchanged.


Date: 2026-09-21
Phase worked on: Phase 14 - Builder Workspace, AG-028
What was completed: Local allowlisted Agent diagnostics across seven failure categories; separately consented complete support preview and immutable exact-byte download; bounded expiring previews and clear controls; privacy canary/route tests and browser consent checks. Retention, deletion, incident response and support ownership documented in docs/AGENT_PRIVACY_SUPPORT.md. API/BYOK defaults and proposal approval boundaries unchanged.
What is in-progress: Nothing in AG-028. Two Codex integration tasks remain: AG-029 and AG-030.
Verification: All 261 Builder server tests, 13 focused support/privacy tests, lint/typecheck/UI contracts, browser support workflow, production build, static Agent boundary checks and nine internal readiness gates pass.
Known limitations: No compatible real runtime/account configuration is certified. The previously inspected private alpha remains rejected. No live login, model turn, credential read, automatic runtime acquisition or whole-XACE launch certification was performed.
Next session should start with: AG-029 only when requested, using explicit opt-in accounts and disposable projects. AG-016 through AG-018 remain deferred and non-blocking; broader XACE launch work stays separate.


Date: 2026-09-20
Phase worked on: Phase 14 - Builder Workspace, AG-027
What was completed: Versioned App Server schema admission and generated evidence, version/deprecation/revocation policy, bounded process I/O/queues, correlated responses and stale-event rejection, bounded initialization-only retry, explicit same-thread resume, MCP health recovery and cancellation cleanup. API/BYOK defaults and proposal/approval authority remain unchanged.
What is in-progress: Nothing in AG-027. Implementation and verification are complete; three tasks remain, AG-028 through AG-030.
Blockers/limits: No real runtime/account configuration is certified. Generated schema from installed editor-private 0.154.0-alpha.6.2 lacks the required restricted-read access field and is rejected; no security relaxation or runtime activation occurred. AG-029 must establish a compatible real configuration. Current official App Server experimental/production-support wording requires AG-030 review.
Verification: Twenty new focused schema/fault/recovery tests pass, as do production build, setup browser checks, nine internal readiness checks and static Agent security across 20 files. First full run caught two new fixture argument omissions and one stale AG-025 stage assertion from AG-026; all are corrected. Final Builder lint/typecheck/UI contracts and all 248 server tests pass; the final Codex-specific suite passes 94 tests.
Next session should start with: AG-028 only when requested. AG-016 through AG-018 remain deferred; no whole-XACE launch work is included.

Previous session:

Date: 2026-09-20
Phase worked on: Phase 14 - Builder Workspace, AG-026
What was completed: Functional Agent setup/recovery UI and loopback-only runtime operator routes. Guided detection/configuration, consent-gated lifecycle actions, browser/device sign-in, sign-out, refresh, cancellation, account/limits, safe diagnostics and API fallback are wired to AG-024/025. Stable DOM preserves inputs and focus. Explicit Agent enable refreshes cached pre-login readiness.
What is in-progress: Nothing in AG-026. Four Codex-only tasks remain, AG-027 through AG-030.
Blockers/limits: Fresh installation is provider-guided under AG-024; no automated acquisition, publisher-signature certification, live account test or manual screen-reader certification is claimed. Real-account evidence remains AG-029.
Verification: Full Builder lint/typecheck/UI contracts and 227 server tests pass, plus the added settings-cache regression (six settings tests). Seven focused runtime setup tests, actual headless-browser UI smoke, production build and all nine Agent readiness checks pass. See docs/AGENT_SETUP_UX.md for accessibility test scope. API/BYOK remains default and mutation governance is unchanged.
Next session should start with: AG-027 only when requested. AG-016 through AG-018 remain deferred; whole-XACE launch work remains separate.

Previous session:

Date: 2026-09-20
Phase worked on: Phase 14 - Builder Workspace, AG-025
What was completed: Provider-native Codex authentication backend and operator controls. The adapter lazily owns a dedicated auth connection with browser/device-code login, correlated completion/cancel/retry, expiry, refresh, confirmed logout, safe identity/limits/optional usage, and actionable recovery states. Identity changes and logout close cached model connections. Local-only same-origin endpoints reject credentials and arbitrary provider methods.
What is in-progress: Nothing in AG-025. Five Codex-only integration tasks remain, AG-026 through AG-030. AG-026 owns the functional setup/recovery UI.
Blockers: None for the AG-025 implementation. Real-account/browser certification remains AG-029; no live login/logout or authenticated model turn was performed. Managed acquisition remains disabled under the AG-024 decision.
Audit decisions relevant to current phase: Official OpenAI App Server documentation and locally generated schemas informed provider-native auth mapping. Codex owns credentials/storage/refresh; XACE keeps only sanitized in-memory control state and returns login challenges once. Auth notifications never enter chat persistence, and auth-related turn errors are sanitized before SQLite/JSONL history. The endpoints are not agent tools. API/BYOK defaults and proposal/approval/GDE/SGC/runtime boundaries are unchanged.
Verification: 28 final focused auth tests pass, including credential canaries across payloads, logs/file access, SQLite and JSONL. The full Builder gate passed lint, typecheck, UI contracts and 218 server tests before the final two additional auth regression cases (included in the passing 28-test focused run). Production build, static Agent security across 18 files, all nine readiness checks including Mock/Codex conformance, forbidden claims and patch whitespace checks pass.
Next session should start with: AG-026 only when requested - functional Agent setup and recovery UX.

Previous session:

Date: 2026-09-19
Phase worked on: Phase 14 - Builder Workspace, AG-024
What was completed: The approved guided official Codex runtime lifecycle. An operator-only CLI verifies and selects a user-owned native executable using native platform/architecture checks, stable version, SHA-256, complete generated-schema fingerprint, and explicit official-source confirmation. Atomic metadata activation, last-known-good selection, exact-pin repair/rollback, non-destructive removal, OS-locked interrupted-operation recovery, revocation policy, and fail-closed resolution are implemented.
What is in-progress: Nothing in AG-024. Six Codex-only integration tasks remain, AG-025 through AG-030.
Blockers: Managed SDK acquisition remains disabled because a supported public runtime executable-location interface and certified package artifact/hash matrix were not established. This is the ADR-approved guided fallback, not an automatic installer or universal platform certificate. Functional setup UI remains AG-026 and real-account certification remains AG-029.
Audit decisions relevant to current phase: Local SHA-256 pins establish integrity, not publisher authenticity. Provenance is user-confirmed official installation; vendor_signature_verified is false. XACE never downloads, copies, updates, or deletes user-owned provider executables or reads credentials. Rollback needs the old exact artifact at its recorded path. API/BYOK defaults and the typed proposal/approval/GDE/SGC/runtime boundary remain unchanged. Whole-XACE launch work remains outside this sequence.
Verification: All 18 final focused lifecycle tests pass. The full Builder gate passed lint, typecheck, UI contracts and 189 server tests (before three final additional lifecycle cases, which pass separately). Production build, all nine Agent readiness checks including Mock/Codex conformance, and static Agent security across 16 files pass. Read-only schema generation against the installed private development runtime produced 305 documents and passed required-method verification; it was not activated and no authenticated model turn was run.
Next session should start with: AG-025 only when requested - provider-native Codex authentication lifecycle.

Previous session:

Date: 2026-09-18
Phase worked on: Phase 14 - Builder Workspace, AG-023
What was completed: The Codex runtime distribution, compliance, and integration decision. XACE will prefer managed acquisition of an exact certified stable `openai-codex` package and its upstream-pinned runtime, retain compatible official external Codex as fallback, and keep direct App Server JSON-RPC as the production integration. A dated ADR and fail-closed `xace.codex_distribution_policy.v1` contract record provenance, integrity, credential ownership, update SLA, rollback, revocation, and platform/launch-surface gates.
What is in-progress: Nothing. AG-023 is complete; AG-024 has not started.
Blockers: Seven Codex-only integration tasks remain, AG-024 through AG-030. Managed acquisition stays disabled until AG-024 verifies official artifacts, exact hashes, supported platforms, a supported pinned-runtime launch surface, atomic lifecycle operations, and recovery.
Audit decisions relevant to current phase: Raw binary bundling, repackaging, redistribution, mirroring, and private package-internal scraping are prohibited. Codex owns OS-keyring credentials and XACE never reads or copies `auth.json`. Compatible external detection and API/BYOK remain available. Whole-XACE installer/signing/launch work is outside this task sequence.
Verification: 24 focused tests and all 89 Agent tests pass. The Builder gate passes lint, typecheck, UI contracts, and 174 server tests; production build, 233 inference tests, static Agent security across 15 files, Mock + Codex conformance, forbidden claims, and the nine-check readiness gate pass.
Next session should start with: AG-024 only - implement the selected managed or guided pinned Codex runtime lifecycle without changing API/BYOK defaults or taking ownership of credentials.


Date: 2026-09-17
Phase worked on: Phase 14 - Builder Workspace, AG-021
What was completed: The post-AG-020 public-readiness audit, ordered AG-021 through AG-032 roadmap, and AG-021 stable protocol/runtime-provenance baseline. Stable clients no longer advertise experimental API access; unsupported thread history mode was removed; thread sandbox values were aligned to the installed generated schema; runtime provenance and public-distribution eligibility are explicit; failed probes cannot be labeled compatible; and the live smoke starts/deletes its own empty read-only thread without a model turn.
What is in-progress: Nothing. AG-021 is complete; AG-022 native XACE MCP transport is the next task and was not started in this work unit.
Blockers: Public release remains blocked by AG-022 through AG-032: native MCP, a verified Codex acquisition/redistribution decision, managed or officially guided runtime lifecycle, provider-native auth UX, protocol resilience, packaged XACE delivery, a declared clean-machine support matrix, real-account end-to-end certification, privacy/support operations, and the final public gate.
Audit decisions relevant to current phase: AG-020 means integration implementation certification only. `public_product_ready` remains false. Codex App Server stays the first and primary Agent path; API/BYOK is unchanged; Local and Claude remain deferred. The installed Codex 0.151.0-alpha.7.2 comes from a private VS Code extension directory and is development fallback only. The current dynamic-tool bridge is experimental until AG-022 moves production turns to native MCP.
Verification: 20 focused AG-021 tests, 80 Agent tests, 165 Builder server tests, Builder lint/typecheck/UI contracts, the production Vite build, 233 inference tests, Mock + Codex conformance, static Agent security, forbidden claims, default readiness, and live no-model-turn stable thread start/delete all pass.
Next session should start with: AG-022 only - implement native XACE MCP transport for Codex while preserving the existing provider-neutral tool contract, proposal boundary, and API/BYOK behavior.

Previous session:

Date: 2026-09-17
Phase worked on: Phase 14 - Builder Workspace, AG-020
What was completed: The Codex Agent Mode production-readiness gate. Nine required checks now cover reusable AG-019 conformance, fail-closed security, healthy/unavailable provider contracts, API/BYOK rollback, provider-managed billing labels, functional Agent UX, approval UX, distribution safety, and truthful claims. Provider settings expose a typed launch-status contract that separates release certification from per-machine runtime readiness, and quick/full launch certification both run the new gate.
What is in-progress: Nothing; the narrowed AG-001 through AG-015, AG-019, and AG-020 Codex Agent Mode implementation window is complete. AG-016 through AG-018 remain explicitly deferred and non-blocking.
Blockers: None within AG-020. The broader repository launch gate still has pre-existing source-inventory/fake-register debt and two older adapter-package TestClient production-path findings; no remaining finding is in the AG-020 surface.
Audit decisions relevant to current phase: Codex is release-certified and the preferred Agent path, but API/BYOK remains the unchanged default and fallback. Local installation/authentication health is runtime state rather than build-certification state. Current distribution detects externally installed Codex; managed/pinned bundling remains blocked pending redistribution, packaging, authentication-storage, update, and compatibility verification. Local and Claude are not shipment dependencies. The strict agent -> XACE tools -> typed proposal -> preview -> approval -> GDE -> SGC -> runtime boundary remains enforced.
Verification: The AG-020 command passes all nine required checks and records ship_codex_agent_mode. The focused 16-test readiness/settings/detection suite, full 78-test Agent suite, aggregate Builder lint/typecheck/UI/server gate with all 163 server tests, production Vite build, 233-test inference gate, static Agent security check, and forbidden-claims check pass. The optional installed Codex probe was not required or run.
Next session should start with: No further AG task is required in this implementation window. AG-016 through AG-018 remain deferred until a concrete dependency justifies them.

Previous session:

Date: 2026-09-17
Phase worked on: Phase 14 - Builder Workspace, AG-019
What was completed: A reusable provider-neutral AgentAdapter conformance suite and CI command. Nine mandatory checks cover contract shape, detection, safe capabilities, start/resume lifecycle, event ordering, MCP permissions, preview-only proposal ingress, cancellation, and recovery. Deterministic Mock and Codex fixtures certify independently; advertised optional capabilities require evidence, unsupported options carry reasons, and failing production adapters are identified for disablement.
What is in-progress: Nothing; AG-019 is complete. AG-016 through AG-018 remain explicitly deferred and non-blocking.
Blockers: None.
Audit decisions relevant to current phase: Codex App Server remains the first production adapter. Conformance certification is adapter correctness evidence, while AG-020 is the separate shipment/default readiness gate. Local and Claude absence cannot fail Codex certification. The strict agent -> XACE tools -> typed proposal -> preview -> approval -> GDE -> SGC -> runtime boundary remains enforced, and API/BYOK defaults are unchanged.
Verification: The conformance command reports PASS with Mock and Codex certified (2/2), four focused conformance tests pass, the full 74-test Agent suite passes, the aggregate Builder gate passes lint/typecheck/UI contracts and all 159 server tests, the production Vite build passes, and the established inference gate passes all 233 tests.
Next session should start with: AG-020 only when explicitly requested; AG-016 through AG-018 remain deferred.

Earlier session:

Date: 2026-09-17
Phase worked on: Phase 14 - Builder Workspace, AG-015
What was completed: Fail-closed Builder Agent security enforcement. A provider-neutral policy now certifies exact XACE tools and adapter capabilities, rejects credentials or privilege escalation in metadata, confines Codex to XACE-built context capsules with restricted read-only roots, intercepts provider shell/file/patch/approval requests, and validates adapter events before persistence or proposal ingestion. Only typed preview submission may cross the read-only boundary.
What is in-progress: Nothing; AG-015 is complete. AG-016 through AG-018 remain explicitly deferred.
Blockers: None.
Audit decisions relevant to current phase: Provider-native lifecycle/auth remains owned by the adapter, while XACE owns tool authority and mutation governance. The enforced path is agent -> XACE tools -> typed proposal -> preview -> user/XACE approval -> GDE -> SGC -> runtime. Credential-store access, raw shell/process APIs, real-project writes, direct GDE commits, and direct runtime mutation are unavailable in normal Builder Agent Mode. API/BYOK remains the unchanged default.
Verification: The 70-test Agent suite, static Agent security check, targeted production secret scan, full Builder gate (lint, typecheck, UI contract, 155 server tests), production Vite build, and all 233 inference tests pass. The broad source scan's 11 findings are known intentional redaction canaries/test fixtures outside the AG-015 production surface.
Next session should start with: AG-019 only when explicitly requested; AG-016 through AG-018 remain deferred.

Earlier session (continued):

Date: 2026-09-04
Phase worked on: Phase 14 - Builder Workspace, AG-014
What was completed: Billing and usage boundary hardening across Agent Mode and API/BYOK. The provider-neutral xace.billing_usage.v1 contract distinguishes XACE-estimated API/BYOK cost, provider-managed Codex account usage, local compute/resource cost, and unknown state. Codex maps optional App Server account usage and rate-limit reads; inference telemetry/accounting exports preserve explicit provenance; Builder cost surfaces no longer imply that zero-price local execution is free.
What is in-progress: Nothing; AG-014 is complete. AG-015 has not started.
Blockers: None.
Audit decisions relevant to current phase: API/BYOK remains the default and retains XACE token/cost estimation. Codex Agent Mode shows provider-managed account usage without manufacturing per-turn dollar estimates. Local descriptors state that provider API price may be zero while hardware, electricity, hosting, and operator cost remain unestimated. Unknown capability data degrades explicitly rather than blocking the mode.
Verification: Full Builder gate passed (lint, typecheck, UI contract, 147 server tests); production Vite build passed; repository inference gate passed all 233 tests. Focused billing serialization and API-key/subscription/local/unknown state tests pass.
Next session should start with: AG-015 only when explicitly requested.

Recovery verification2026-10-15: ingress batching candidate dd2741c passes870 Rust tests and production socket/process/mixed-engine/replay gates; strict short soak passes4.1323ms p95. Full endurance pending. See AGENT_PROGRESS.md; no off-device backup.

XP022 repaired-candidate full endurance PASSED:7200.844 seconds,188507 ticks,11.6411ms p95 against16.7ms, successful reconnect and clean authority exit. All737 replay segments/188507 ticks verified without divergence. Finished2026-10-15 06:50:54 UTC (12:20:54 IST). Fresh evidence: docs/recovery/evidence/xp022-ingress-batch-20261015/completed-soak/summary.json. No rerun required for this gate. This is new recovered-candidate evidence, not original sealed evidence or full release certification. Earlier intermittent failure root cause remains unconfirmed; recovery sealing and remaining acceptance audit are pending. NEC010 not started. NOT backed up off-device.

XP022 local engineering closeout passes; external REL01-05 remain open. Reproduced native evidence writer read-sharing defect: legacy append fails, repaired append succeeds with held reader; complete40-tick mixed activation passes with held reader. Historical missing-input claims corrected using authority journals. See docs/recovery/XP022_RECOVERY_CLOSEOUT.md. All final-host affected gates and unsigned ZIP inventory pass; runtime unchanged since successful soak. Fresh recovery baseline sealing/readback next, then NEC001-009 restoration. NOT backed up off-device.

XP022 recovered baseline SEALED and readback verified: C:/Users/ankit/XACE-Recovery/baselines/xp022-recovered-20261015/baseline.json, SHA25644b38aea2503731b455377221385821228916b5ea843b094e9cd01d4847a90fc, source13a3d9b6ddb68d155b51045d6ad7dcc297ed1df9,1575 source entries/54 sealed files. Fresh engineering baseline only; REL01-05 OPEN. Next NEC001 recovery/reconciliation against this baseline. NOT backed up off-device.

NEC001 RECOVERY VERIFIED:85 Python +23 Rust acceptance tests pass; all54 sealed files/1575 archived source entries preserved before/after; final XP022 proofs retained with hashes, not rerun/relabelled. Roadmap keeps original amendments plus persistent recovery paths/checkpoints. Evidence: docs/recovery/evidence/nec001-20261015/summary.json. Next NEC002 under sequential authorization. NEC010 prohibited; REL01-05 OPEN; NOT backed up off-device.

NEC002 RECOVERY VERIFIED:24 identity/store tests +67 project/Player/authoring regressions pass (91 total). Atomic store interruption/concurrent-writer, rename/reparent/duplicate/tombstone/fork and migration cases restored; no native capture claimed. All55 protected recovery-baseline files including manifest unchanged. Evidence: docs/recovery/evidence/nec002-20261015/summary.json. Next NEC003. NOT backed up off-device.

NEC003 RECOVERY VERIFIED:28 normalized authoring contract tests +191 regressions pass (219 total), including independent Node golden checks,1500-object hierarchy and300 malformed mutations. All55 protected recovery-baseline files unchanged. Evidence: docs/recovery/evidence/nec003-20261015/summary.json. Native capture remains subsequent work. Next NEC004. NOT backed up off-device.

NEC004 RECOVERY VERIFIED:228 Python tests and50 installed Unity6000.4.9f1 checks pass (40 run,4 cold reopen/Python write,6 Play). All50 cases match the historical acceptance count. Persistent .xace holds native transaction receipts/before-images and proof snapshots; recovery-evidence holds isolated project/output. All55 sealed baseline files unchanged. Evidence: docs/recovery/evidence/nec004-20261015/summary.json. Native APIs are callable; automatic CGS sync remains later work. Next NEC005. NOT backed up off-device.

NEC005 RECOVERY VERIFIED:239 Python tests and74 installed Godot4.6.3 checks pass (62 run,5 cold reopen/Python write,4 Play,3 runtime privilege). Final tested source matches recovered files; unknown native behavior admission refused. All55 sealed baseline files unchanged. Evidence: docs/recovery/evidence/nec005-20261016/summary.json. Historical mixed-call omissions corrected; failed/prior attempts preserved. Next NEC006; NEC010 prohibited until recovery acceptance. NOT backed up off-device.

NEC006 RECOVERY VERIFIED:255 Python tests and73 installed Unreal5.7.4 checks pass (57 commandlet,1 independent trusted copy,6 cold-process,9 real editor). Persistent .xace transaction stage uses scoped native mount for saved binary readback; this recovery repair is explicitly distinct from historical source. Failed a/b fixtures preserved. Unknown Blueprint behavior blocks admission. All55 sealed baseline files unchanged. Evidence: docs/recovery/evidence/nec006-20261016/summary.json. Next NEC007. NOT backed up off-device.

NEC007 RECOVERY VERIFIED:276 Python tests (21 adoption) and6 fresh runtime executions pass using the verified XP022 host and fresh native captures. Explicit damage behavior, native transforms, no-op repeat adoption and deterministic hashes verified. Preview only; no CGS publication or automatic sync. All55 sealed baseline files unchanged. Evidence: docs/recovery/evidence/nec007-20261016/summary.json. Next NEC008. NOT backed up off-device.


## NEC008 recovery verification ? 2026-10-16

NEC008 RECOVERY VERIFIED:308 Python tests in17 suites,3 fresh capture-derived reconciliation proofs and20 real Chrome/HTTP checks pass. Desktop/narrow screenshots inspected; JS syntax check passes. Root-transform review only, no publication or baseline advance. All55 protected sealed files unchanged. Evidence: docs/recovery/evidence/nec008-20261016/summary.json. Next NEC009; NEC010 prohibited. NOT backed up off-device.

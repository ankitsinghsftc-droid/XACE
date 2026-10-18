# NEC-010 ? durable native materialization (in progress)

Authorized2026-10-16 after recovery acceptance checkpoint `7cb2dfd`. This is new development, not reconstructed historical work. NEC011 has not started. The sealed XP022 recovered baseline remains immutable.

## Acceptance ledger

- [x] Reconcile roadmap with recovered NEC009 and preserve entry baseline.
- [x] Separate engine-owned opaque metadata refresh from canonical structural edits; retain critical behavior and actual structural refusal.
- [ ] Certify exact staged native readback and preservation of all unowned content across save serialization. Stored-property fingerprints replace whole-document fingerprints for admitted content; full preservation acceptance remains pending. Saved-pair equality stays mandatory.
- [ ] Connect a durable reviewed plan, explicit apply authorization, staged artifacts and NEC009 recovery to the native host and minimal review/apply UI.
- [ ] Implement new-project setup and explicit owned marker/resource/input/binding writes with previewable file changes.
- [x] Repeated bound-root-transform materialize/capture/reconcile cycles in Unity, Godot and Unreal, with fresh host/editor processes and stable no-op echo suppression. Full new-project and broader owned-field cycles remain under the setup acceptance item.
- [ ] Rename/delete/reparent, native undo/redo and file ownership proofs; preserve or explicitly block unsupported structural mappings.
- [ ] Integrate actual Play/build readiness checks, failed-save recovery and baseline advancement only after verified paired saves.
- [ ] Final regression, native proofs, master-plan update and completion checkpoint.

## First implementation increment

`native_reconciliation.py` now treats native-owned opaque metadata as retained inspection information instead of an implied CGS structural mutation. It still records native changes in the report; critical behavior remains blocking, canonical opaque writes remain blocking, and parent/dependency/deletion changes still require structural review. Neither native writer permission nor saved-pair equality is relaxed.

`test_native_materialization.py` tests this boundary across the three reader profiles. The NEC010 Godot boundary runner uses a fresh copied fixture and the normal `prepare_apply` path. The first run retained NEC009's strict post-save refusal and rollback. The later stored-property implementation passes Godot saved-pair recovery and two additional cold-editor cycles; full all-engine/setup acceptance is still required.

## Required next design constraint

The reviewed target must distinguish requested owned-field changes from native serialization effects. An acceptable stage must bind exact before/staged file hashes, target identity, dependency hashes and a native proof of preservation of unowned content. A fresh recapture must equal that reviewed staged target. Do not ignore opaque fingerprints globally, substitute whatever is read back as the expected result, or advance the baseline merely because a writer returned success. Native stage evidence must be established before the durable publication decision and survive process restart.

Evidence is under `evidence/nec010/20261016`; native fixtures and unique receipts remain outside disposable directories. All checkpoints remain NOT backed up off-device.

## Increment1 verification

Source4ddc048 passes343 Python tests in20 suites. The installed Godot boundary proof passes normal plan/prepare_apply integration and preserves strict saved-pair refusal, process-exit recovery and rollback. All55 protected baseline files are unchanged. Full NEC010 acceptance remains pending. See [increment receipt](evidence/nec010-increment1-20261016/completed-increment.json).

## Continuation verification2026-10-17


NEC010 continuation2026-10-17: Unity50 native checks pass (40 run,4 cold-reopen,6 Play). Godot saved-pair crash recovery and2 additional cold-editor materialization cycles pass;6 unknown-property preservation checks pass. Host persists the reviewed saved-pair contract and resumes it after restart without review memory;5 host tests pass. Authenticated recovery HTTP route passes3 focused tests. Regression run passes350 tests (before the third route test was added). Unreal semantic fingerprint build passed but first native run refused stale inventory at staged preparation; diagnostic native build is ongoing. Full NEC010 remains INCOMPLETE: all-engine loops, setup/owned writes and complete UX/readiness acceptance pending. Evidence: docs/evidence/nec010-continuation-20261017. All55 sealed XP022 files preserved. No checkpoint backed up off-device.


NEC010 preservation continuation2026-10-18:353 Python tests pass. Expanded staged readback passes Unity50 and Godot74 native checks; both pass saved-pair crash recovery and2 further cold-editor cycles. Unreal74 native checks pass (58 commandlet,6 cold reopen,1 trusted copy,9 editor undo/redo). A real Unreal stage failure was traced to the relocated WorldSettings.NavigationSystemConfig object reference; typed world-relative reference identity fixes it without rewriting user strings. A literal package-path tag is preserved. Diagnostic nested JSON encoding now rejects empty evidence. Current browser Apply passes14 desktop/narrow checks and screenshots inspected.55 protected XP022 files unchanged. Evidence: docs/evidence/nec010-preservation-20261018, with byte-matched native fixture source provenance. Fresh Unreal coordinator cycles are running; setup/owned writes and remaining NEC010 acceptance are still INCOMPLETE. No checkpoint backed up off-device.


NEC010 continuation2026-10-18 after f2e447c: current Unreal source passes saved-pair process-exit73 recovery, idempotent recovery and2 additional cold-editor materialization cycles. Thus expanded preservation source has passing root-transform cycle proofs in all3 engines. New NativeSetupFiles provides create-only reviewed file publication with nested directories, Windows alias rejection, existing/newer-file protection and journal-retained rollback bytes.7 focused tests plus14 coordinator regressions pass, including restart resume/rollback with the real coordinator. This is setup publication infrastructure ONLY: registered native project factories, setup preview/apply UI, and broader owned marker/resource/input/binding integration remain unfinished. NEC010 is INCOMPLETE; no post-NEC010 completion ref exists. Evidence: docs/evidence/nec010-setup-publication-20261018. No off-device backup.


NEC010 active continuation: all3 new native factories now pass CGS-driven stage generation, cold reopen, exact World-bound transforms and existing-content refusal (Godot setup-c, Unity setup-c, Unreal setup-a compiled ue/i). Shared native_setup_plan validates source CGS and explicit single-instance root World bindings. NativeSetupBundle supports bounded multi-batch create-only publication;15 setup-plan/files/bundle tests pass. Godot first assertion mismatch and Unity unsaved-empty startup scene failure were retained and corrected; no user buffers discarded. Native generators and publication remain to be connected to setup review/apply, verified baseline handoff and broader owned-field writes. NEC010 remains active/incomplete; continuing, not closing. Evidence: docs/evidence/nec010-native-generators-20261018. No off-device backup.


NEC010 setup handoff checkpoint2026-10-18: production native factories and explicit reviewed file publication pass in all3 installed engines, including cold reopen, exact capture, verified baseline and normal host readiness. Source-bound frozen stages reject changes before apply; setup journals remain recognizable/recoverable by the normal host. Native editor gateways pass capture/prepare/commit/rollback; Unreal latest factory compiled ue/k.235 project-system tests,12 native route tests,27 focused setup tests and14 measured-viewport browser checks pass (browser fixture is filesystem-only). Godot missing-entry first attempt retained and fixed; narrow browser proof corrected after screenshot inspection. All55 protected seal files unchanged. Evidence: docs/evidence/nec010-setup-handoff-20261018. NEC010 remains INCOMPLETE: broader owned resource/input/binding integration and full remaining acceptance closeout are pending. No off-device backup.


NEC010 continuation2026-10-19: Unity50 checks and Godot71 checks pass across native run and cold reload. Newly selected playback/resource dependencies are now pinned before staging and rechecked before native publication; changes refuse save and retain original scene bytes. Unity actual input/playback write/rollback checks pass. Godot first fixture reused transaction820 and was corrected to930 in a fresh run; failed evidence retained. Source follow-up to c520d8e; docs/evidence/nec010-owned-dependencies-20261019. Full owned-field CGS/native integration and final NEC010 acceptance remain INCOMPLETE. No off-device backup.

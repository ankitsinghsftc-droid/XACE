# NEC-010 ? durable native materialization (in progress)

Authorized2026-10-16 after recovery acceptance checkpoint `7cb2dfd`. This is new development, not reconstructed historical work. NEC011 has not started. The sealed XP022 recovered baseline remains immutable.

## Acceptance ledger

- [x] Reconcile roadmap with recovered NEC009 and preserve entry baseline.
- [x] Separate engine-owned opaque metadata refresh from canonical structural edits; retain critical behavior and actual structural refusal.
- [ ] Certify exact staged native readback and preservation of all unowned content across save serialization. Stored-property fingerprints replace whole-document fingerprints for admitted content; full preservation acceptance remains pending. Saved-pair equality stays mandatory.
- [ ] Connect a durable reviewed plan, explicit apply authorization, staged artifacts and NEC009 recovery to the native host and minimal review/apply UI.
- [ ] Implement new-project setup and explicit owned marker/resource/input/binding writes with previewable file changes.
- [ ] Repeated materialize/capture/reconcile cycles in Unity, Godot and Unreal, including closing/reopening both tools and stable no-op echo suppression.
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

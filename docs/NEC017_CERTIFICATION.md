# NEC-017 installed-engine adoption, conflict and crash certification

Started 2026-10-28 after NEC016 local engineering closeout at958162e. User explicitly deferred clean-machine/VM certification; public release gates remain mandatory and open. NEC018 is not started.

Acceptance is the existing roadmap, including the four approved amendments. Keep task order and the1,000-bound-object target. Raising admission limits alone is not certification.

Required cells: installed Unity/Godot/Unreal supported versions; new and non-trivial existing projects; saved native capture/adoption/reconcile/review/apply/reopen/Play/build/continuity; real binary assets; conflicts preserving both versions; journal crash/recovery boundaries; two independent developer branches, reviewed merge/rebase/recovery;1,000-object repeated edits, no-op suppression, rebuild latency, peak resources, retained history and recovery correctness; unusual-mechanic state/snapshot/replay and shipping update/save failure cases. Record each failed/blocked/unsupported cell explicitly. Do not infer a native editor pass from Python fixtures.

Initial audit: Python native adoption, setup and reconciliation each cap bound objects at128; all three native editor setup implementations independently cap at128. Identity inventory already allows10,000 records. String-length128 limits are unrelated and remain unchanged. First implementation raises the bound-object profile to1,000 consistently and exercises actual planning/reconciliation at that count; native certification remains pending until run.

Status: IN PROGRESS. No installed-engine scale, collaboration or full crash certification claimed yet. Preserve all existing source/evidence, no automatic cleanup. New evidence under evidence/nec017 and compact records under docs/evidence. Stop before NEC018.

NEC017 scale checkpoint2026-10-28: bound-object admission raised128->1000 across Python and all native setup factories; structural GDE budget512->4096,16MiB bound unchanged. Real1,000-object shared adoption/setup/no-op reconciliation passes for all engines;1,001 refused. Actual Godot and Unity1,000-object create/cold-reopen/in-place overwrite refusal pass.325 project-system regressions pass. Unreal fresh plugin build running. Full collaboration/crash/repeated-edit/resource certification remains pending; NEC017 not complete. Evidence: docs/evidence/nec017-scale-start-20261028.

NEC017 Unreal native1,000-object create/cold-reopen passed after a fresh source build (105.1s build,25.5s create,7.2s reopen). All3 engines now pass the initial scale setup/reopen/overwrite-refusal cell. Evidence docs/evidence/nec017-unreal-scale-20261028. Repeated production authoring proof is running in evidence/nec017/20261028/godot-repeat-a; full NEC017 certification remains incomplete.

NEC017 review-boundary checkpoint 2026-10-29:327 project-system regressions and28 focused review tests pass. Replaced redundant recaptures within each approval-validation boundary with one fresh trusted snapshot; original/resolved plans, principal/signature, expiry and inter-boundary refresh remain required. Added expiry-during-capture refusal test. Actual1000-object repeated-edit run-a expired safely during staging and is retained; lower-overhead runs b/c remain in progress, not passing evidence. Initial scale setup/reopen passes all3 engines, but repeated performance, full conflicts/crashes and independent developer collaboration remain incomplete. Evidence docs/evidence/nec017-review-boundary-20261029. No NEC018. Raw fixtures/binaries/seal local-only; checkpoint push pending.

## Collaboration reconciliation finding (2026-10-29)

A raw copy of an active authoring workspace is not an executable collaboration fork. Native host configuration and participant receipts bind absolute workspace roots. The coordinator correctly rejects mismatched roots. Do not rewrite existing journals or remove identity/history to bypass this guard.

The remaining branch certification needs an explicitly reviewed new-workspace baseline: preserve the ancestor source, mapping, baseline and journal history unchanged; retain namespace/object IDs; assign a distinct branch ID; freshly capture the new native workspace and verify its CGS projection; establish only the new active baseline through the coordinator. Pending recovery must be resolved or explicitly preserved before a fork can be admitted. A copied historical receipt is provenance, not permission to execute an old root-bound transaction.

This workflow remains unimplemented/unverified. Required negative cases include stale source/approval, pending recovery, foreign namespace, existing destination, interrupted initialization and preservation of both conflicting branch versions. The installed-editor branch/merge/rebase/recovery proof cannot be replaced by the existing Python identity-fork tests.

## Active native recovery proof

`tools/nec017_godot_crash.py` exercises actual child-process exit at all14 coordinator journal boundaries, with a fresh two-object native fixture per case and production NativeMaterializationHost recovery. Run: `evidence/nec017/20261029/godot-crash-a`. First intent-durable case passed; the full matrix is not yet verified. This small recovery fixture does not certify scale, binary-asset conflicts or two-developer collaboration. All prior failures and source identities remain retained.

NEC017 2026-10-29: all14 Godot process-death journal boundaries pass using production host on isolated2-object fixtures. Both1000-object repeated runs b/c completed1 cycle but FAILED later native capture timeout240s; full3-cycle requirement remains open. Godot console-wrapper-only memory figures are insufficient; corrected descendant sampler verified on32MiB child and actual Godot create/reopen, with100ms sampling limitations explicit. Evidence docs/evidence/nec017-process-tree-20261029. No all-engine recovery/scale completion claim. Checkpoint828e764 pushed and remote verified; new checkpoint push pending. Raw fixtures and seal local-only. NEC018 not started.

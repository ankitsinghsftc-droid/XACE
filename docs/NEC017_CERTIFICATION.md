# NEC-017 installed-engine adoption, conflict and crash certification

Started 2026-10-28 after NEC016 local engineering closeout at958162e. User explicitly deferred clean-machine/VM certification; public release gates remain mandatory and open. NEC018 is not started.

Acceptance is the existing roadmap, including the four approved amendments. Keep task order and the1,000-bound-object target. Raising admission limits alone is not certification.

Required cells: installed Unity/Godot/Unreal supported versions; new and non-trivial existing projects; saved native capture/adoption/reconcile/review/apply/reopen/Play/build/continuity; real binary assets; conflicts preserving both versions; journal crash/recovery boundaries; two independent developer branches, reviewed merge/rebase/recovery;1,000-object repeated edits, no-op suppression, rebuild latency, peak resources, retained history and recovery correctness; unusual-mechanic state/snapshot/replay and shipping update/save failure cases. Record each failed/blocked/unsupported cell explicitly. Do not infer a native editor pass from Python fixtures.

Initial audit: Python native adoption, setup and reconciliation each cap bound objects at128; all three native editor setup implementations independently cap at128. Identity inventory already allows10,000 records. String-length128 limits are unrelated and remain unchanged. First implementation raises the bound-object profile to1,000 consistently and exercises actual planning/reconciliation at that count; native certification remains pending until run.

Status: IN PROGRESS. No installed-engine scale, collaboration or full crash certification claimed yet. Preserve all existing source/evidence, no automatic cleanup. New evidence under evidence/nec017 and compact records under docs/evidence. Stop before NEC018.

NEC017 scale checkpoint2026-10-28: bound-object admission raised128->1000 across Python and all native setup factories; structural GDE budget512->4096,16MiB bound unchanged. Real1,000-object shared adoption/setup/no-op reconciliation passes for all engines;1,001 refused. Actual Godot and Unity1,000-object create/cold-reopen/in-place overwrite refusal pass.325 project-system regressions pass. Unreal fresh plugin build running. Full collaboration/crash/repeated-edit/resource certification remains pending; NEC017 not complete. Evidence: docs/evidence/nec017-scale-start-20261028.

NEC017 Unreal native1,000-object create/cold-reopen passed after a fresh source build (105.1s build,25.5s create,7.2s reopen). All3 engines now pass the initial scale setup/reopen/overwrite-refusal cell. Evidence docs/evidence/nec017-unreal-scale-20261028. Repeated production authoring proof is running in evidence/nec017/20261028/godot-repeat-a; full NEC017 certification remains incomplete.

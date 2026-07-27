# XACE State Authority Rules

This document defines the Phase 3 state-authority contract for XACE authoring
and live runtime flows.

## Authority Owners

| State | Authority | Allowed write path | Required guard |
| --- | --- | --- | --- |
| Durable authoring state | Disk `game.cgs.json` | `CGSPersistence.save()` | Project `.xace/cgs.write.lock`, atomic write, submitted `cgs_hash` check |
| Transactional authoring mutation | GDE | `SessionManager.apply_via_gde()` | Parent `cgs_hash`, monotonic transaction ID, GDE validation |
| Live simulation state | Runtime | Runtime tick/control loop | `runtime_world_hash`, `runtime_tick`, reload version handshake |
| Engine presentation/editor preview | Engine adapter | `engine_edit` preview only | Accepted preview audit row before commit |
| Engine-originated CGS commit | Builder/GDE | `engine_edit_commit` | Current CGS version check, merge rule, GDE commit |

## Version IDs

Every CGS mutation path must carry or derive:

- `cgs_hash`
- `schema_version`
- `execution_plan_version`
- `runtime_world_hash`
- `runtime_tick`
- `engine_adapter_sequence`

A submitted `cgs_hash` that differs from the current disk or in-memory authoring
hash is rejected before mutation. Missing runtime IDs are recorded as unresolved;
they are not treated as proof of synchronization.

## GDE Apply Contract

Production CGS mutations must go through GDE validation. If GDE is unavailable,
if GDE internals cannot build the transaction, or if the transaction targets a
stale parent `cgs_hash`, Builder refuses the mutation visibly. Direct/naive CGS
edits are not a production fallback path.

## Locking

All `game.cgs.json` writes and snapshot index updates must happen while holding
the project lock at `.xace/cgs.write.lock`. The lock is process-visible and is
paired with atomic JSON replacement.

## Runtime Reload Handshake

`reload_cgs` is not a blind reset. Builder sends the version IDs it believes are
current. Runtime compares them to the disk CGS/runtime plan and refuses reload if
any provided ID does not match. If Builder cannot resolve a runtime-compatible
execution plan version, it records that value as unresolved instead of pretending
to have proof.

## Engine Edit Merge Rules

Engine edits are preview-first. A commit is allowed only after an accepted audit
row from `engine_edit`.

If newer CGS mutations landed after the preview, the commit can merge only when
all of these are true:

- the target resolves to an existing component `defaults` field;
- the value is a primitive JSON value;
- the operation is a value mutation, not a structural edit.

Structural edits, component/table changes, systems, rules, metadata changes, and
collection replacements must go through PIL/GDE.

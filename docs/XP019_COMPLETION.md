> Reconstructed historical document. Fresh recovery verification is pending; original evidence is missing. See AGENT_PROGRESS.md. Historical disposable paths below must not hold new unique evidence.

# XP-019: durable ruleset activation

Implemented on 2026-10-04 in the isolated `xp-016` worktree. No commit or push;
protected local and GitHub main/backup refs remain unchanged.

## Product capability

An approved, isolated configuration candidate can activate at a future authority
tick on the preserved world. The existing local control protocol exposes
`preview`, `stage`, `prepare` and `current` operations. Requests contain content
digests and a tick; filesystem locations come only from the trusted host's
`--ruleset-root`. Unknown fields and path-bearing requests are rejected.

The coordinator in `runtime_orchestrator/ruleset_activation.rs` binds the
candidate/proof digest, parent session/incarnation/epoch and exact ready peer
generations. A hash-chained, flushed journal records preparation, readiness,
the decision checkpoint and publication. At N it rechecks parent identity,
membership and artifact bytes, performs the existing MutationGate configuration
migration in isolation, durably decides, installs the prepared runtime and
publishes the new contract. All prepared clients must acknowledge the new
baseline before tick N executes. Stale-epoch inputs are rejected.

The published package identity is the verified playable manifest's gameplay
hash. Its compiled schema, CGS, plan and world files must match the candidate;
runtime, executable profile, package identity and presentation stay compatible.
This allows fresh clients using the actual candidate package to match the epoch.
Duplicate preparation/commit requests return the recorded identity without
reapplying migration. Conflicting duplicate journal decisions/publications fail.

Godot/Player, Unity and Unreal validate prepare messages, acknowledge readiness,
switch contract identity on commit and require a fresh complete baseline.
Godot normalizes protocol integer fields before comparing contract dictionaries.
No mechanic names or reference rules enter these generic transition handlers.

## Failure and recovery

Before decision, failed validation or migration discards the isolated candidate
and continues the old epoch. After a durable decision, a failure ends the session;
it never rolls back a possibly observed committed epoch. On restart, a durable
decision or damaged journal prevents silently reopening the parent session.
Automatic resumed play after a crash is not claimed by this profile.

New admission is fenced throughout preparation. Once published, joins receive
the complete current epoch. Ordinary snapshot restore cannot cross a committed
epoch; old rollback snapshots are removed from the mutable rollback cache.
Durable decision checkpoints and immutable candidate artifacts remain available
for the explicit epoch-aware replay work in XP-020.

The optional `activation-fault-injection` Cargo feature exists only for tests.
Normal production host builds do not expose failure injection through the CLI,
socket protocol or gameplay package.

## Verification and reference proof

The retained evidence is `docs/evidence/xp019-baseline.json`. Generated native
logs, private tickets, binaries, journals and recordings remain under ignored
`target/xp019/`; they are not source artifacts.

- Actual Player+Godot, Unity+Godot+Unreal and all-four sessions execute 40 ticks.
  All clients agree on applied projections, events and authority-accepted inputs.
  Old epoch runs through tick 7; new epoch runs from tick 8. One client leaves
  after tick 19; survivors continue through tick 39.
- The package-owned fixture denies the attempt at tick 7 and produces the
  changed behavior and shared effect at tick 9, preserving entity continuity.
- Boundary probes reject admission at tick 7 during preparation and verify
  complete new-epoch projections after ticks 8 and 9. The latter probes do not
  acknowledge baselines or become required input participants.
- Restarting each completed authority against its journal refuses the old epoch.
- Deterministic failure tests cover discarded migrated scratch state, before
  decision, after decision and before broadcast. Post-decision cases emit no
  partial tick; pre-decision cases continue old behavior.
- Unit/integration gates cover stale parents, denied migrations, artifact and
  approval integrity, duplicate decisions, torn journals, path rejection and
  refusal to restore a prior-epoch snapshot after activation.

Final Rust results: 842 runtime tests and 21 reference-package tests pass with
zero failures. The latter command explicitly enables fault injection; the
subsequent production host build does not.

Reproduction gates (from the worktree, with the installed native tools):

```text
cargo test -p xace-runtime-core --lib --tests
cargo test -p xace-reference-mechanic --all-targets --features activation-fault-injection
cargo build -p xace-reference-mechanic --bin xace_reference_host
python -m tools.xp019_activation_proof --stage --scenario all --out target/xp019/fresh-proof
```

The proof uses the current host at `target/debug/xace_reference_host.exe`; when
using a shared Cargo target directory, copy the newly built host there first.
The native Unreal project is staged/built by `tools/xp016_native_proof.py` with
`--engine unreal --out target/xp019/native` before running the mixed matrix.

This certification is local to one Windows computer, with Unity 6000.4.9f1,
Godot 4.6.3 and Unreal 5.7.4. It makes no Internet, latency or multi-machine claim.
XP-010 clean-machine, XP-014 two-machine and XP-015 public/two-network gates,
plus the older missing-cosmetic startup limitation, remain open.

The supported live migration is still XP-018's registered, read-only configuration
replacement profile. Structural/state-transforming/world migrations require
future validated hooks and fail closed today. This does not restrict generic
World Contract nouns, semantic capabilities or package-defined mechanics.

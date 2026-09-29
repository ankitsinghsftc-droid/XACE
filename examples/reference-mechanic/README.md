# Reference Mechanic Proof (XP-005)

This removable example package demonstrates ordinary XACE gameplay systems. It is
not a traversal feature of XACE core. Only this package owns the wall-running,
jump-chain, reversal and shockwave rules. No core crate depends on this crate.

`catalog.json` declares GCL state/config components, a namespaced surface capability
and system access/dependency metadata. The config lives in CGS component rows.
`ReferenceSystem` implements the normal ISystem trait and is registered with the
existing SystemRegistry. The proof uses an actual Factory/SGC-generated persisted
plan and the standard PhaseOrchestrator, MutationGate, World Contract and snapshots.

Run from the repository root:

```powershell
cargo build -p xace-system-graph-compiler --offline
python tools/xp005_reference_proof.py
cargo test -p xace-reference-mechanic --offline -- --nocapture
```

The compiler proof checks committed fixture bytes. `--write-fixtures` explicitly
regenerates them after an intentional source/catalog change. No provider or engine
is needed. Tests supply a tick-indexed input recording through a scheduled Input
system; they do not certify network ingress or native play.

The initial third-attempt policy is `disabled`. The alternate CGS-owned config is
`reversal_shockwave`; tests load its separately compiled CGS/world/plan artifacts, then prove
its behavior and replay independently. Live multi-client ruleset activation is
XP-018/019 work and is not simulated by this proof.

Two wall-jump edges succeed before landing. Holding jump does not create new edges.
Contact loss preserves the count; canonical ground contact resets it. The optional
third attempt reverses tangential horizontal velocity, launches upward and emits
one shockwave per airborne chain. The wave applies bounded horizontal impulses to
other reference actors in radius; it is a deliberately simple fixture effect.
The package owns its three-pass swept-slide response and rejects initial penetration.
Geometry sampling is against tick-boundary state, not a two-body physics solver.

The default runtime executable does not auto-discover/link this example or add a
wall-run branch. This proof explicitly registers it through the normal registry.
Omitting the package and its plan entries leaves the runtime operational; a stale
plan referencing the absent system rejects. Generic authoring integration is XP-006,
and playable artifact verification/distribution remains XP-007 onward.

# XP-005: Reference package and generic semantic capabilities

Implemented 2026-09-25 under the owner's mechanic-agnostic amendment. Scope is the
capability-contract correction plus one removable Reference Mechanic Proof.

## Core boundary and capability correction

World Contract v2 replaces the closed gameplay-name vocabulary and special role
checks in both Python Schema Factory and the Rust reader. Package/catalog data
supplies `capability_declarations`: unique bounded namespaced versioned IDs with
explicit allowed object kinds. The compiler canonicalizes declaration/order data;
the Rust reader rejects unsorted, duplicate, malformed or undeclared capabilities
and disallowed roles. Generic shape/transform/asset/provenance validation remains.
No wall-runnable, platform, road or safe-zone name has privileged core meaning.

World `required_capabilities` now contains only `world.aabb.v1` and
`world.semantic_bindings.v1`. Gameplay tags are object/declaration data covered by
the world digest. `ISystemContext::world_capabilities_v1` reads immutable validated
world bindings without interpreting their meaning or mutating runtime state.
Runtime geometry retains the same generic sweep/overlap/probe/target operations.

Session `required_capabilities` remains a fail-closed platform/protocol set:
`input.timed.v1`, `world.aabb.v1`, `world.semantic_bindings.v1`. An additive optional
`semantic_capabilities` set records package semantics separately. It requires
World Contract v2, exact equality between peers and valid semantic IDs; clients
need not advertise gameplay tags as engine implementation capabilities.
`compare_session_with_world` verifies the world digest/mode/version and exact
used semantic set against validated content before invoking normal compatibility.
The original metadata-only predicate remains metadata-only, not artifact admission.
Future package loaders must still verify package/source provenance and signatures.

This deliberately changes the World Contract schema/version to 2, rather than
silently broadening v1 semantics. Old v1 worlds require explicit recompilation from
CGS with declarations; no automatic migration is claimed. WorldManifest's container
shape stays v1 and carries world contract_version 2. Session schema v1 gains an
optional field; old readers reject the new world version/unknown field, so there is
no silent mixed-reader downgrade. Historical platform-only v1 session metadata can
still be compared. Active updated conformance cases live in `session_contract_v2`
(the fixture revision, not a claim of a new transport protocol). Original v1 world
and session fixture bytes remain preserved; prior reports stay historical.

## Reference implementation

`examples/reference-mechanic` is a standalone workspace example crate. It depends
on xace-core; runtime-core is only a dev dependency of its proof harness. No runtime,
compiler, network or adapter depends on the example. `ReferenceSystem` implements
ISystem and uses the existing registry, scheduled context and MutationGate. Its
catalog supplies ordinary GCL components 10000/10001 for state/config in this example
project; those IDs are not reserved universal/DCL components. Other projects must
resolve their own GCL namespace/ID allocation through normal registry validation.

Configuration and state are CGS-owned component rows. The persisted SGC plan has
one authoritative transform/velocity writer. It declares transform, collider,
velocity, input, GCL state and config reads; it writes transform/velocity/state.
A proof-only Input system supplies recorded frames using the standard context.
No runtime orchestrator, World Contract or adapter dispatches on the mechanic name.

The package interprets its declared surface capability, computes canonical ground
and side contacts, and owns these fixture rules:

- Grounded, airborne and wall-running transitions use canonical query results.
- Jump inputs use rising edges retained in snapshot state. Exactly two wall jumps
  succeed per airborne chain. Contact loss does not reset the count; landing does.
- Initial third attempt is disabled. Optional reversal_shockwave reverses tangential
  horizontal velocity, launches upward and emits one wave per airborne chain.
- Shockwave proximity uses the generic squared-distance query. Horizontal impulses
  affect other reference actors and accumulate before one final write per actor.
  Equal-position direction has a deterministic EntityID tie; no rigid-body claim.
- Swept slide response is package code. Initial penetration fails instead of silently
  teleporting the actor. Limits, fixed 60-Hz integration and integer rounding are
  explicit. Canonical contacts are sampled state, not relative two-body physics.

Default config uses 5 m/s running, 8 m/s upward jump, 6 m/s away impulse, 0.1635 m/s
per-tick gravity decrement, 0.1 m side probe, 0.001 m ground probe, and a 5 m wave
radius with 3 m/s per-axis horizontal impulse. Config validates bounds/version.
These values belong to this example's catalog and are not platform defaults.

## Proof and limitations

The compiler proof uses real Schema Factory output as real SGC input, persists its
plan and validates the sole transform writer. Rust loads that plan through the
standard loader and verifies world content against its manifest/source identities.
It checks actual registered reads/writes against the persisted declarations.

Nine reference tests cover chained jumps, disabled/alternate third attempts,
held edges, untagged surfaces, actual target impulses, contact loss/landing,
full event + hash replay for both policies, invalid-config tick rollback, normal
package removal/stale-plan rejection, stable corner selection and an arbitrary
renamed semantic capability. The latter changes data only, not the core or another
mechanic. Generic Python/Rust capability and artifact-bound admission tests cover
declaration validity and cross-language fixtures.

No additional mechanic, package/plugin framework, authoring UX, native engine,
network session, live activation or maximum-size performance certification is added.
This is explicit example registration, not dynamic executable/package loading in
the default runtime CLI. Those integration gates remain later roadmap tasks.
See `../XP005_COMPLETION.md` and `../evidence/xp005-baseline.json` for exact evidence.

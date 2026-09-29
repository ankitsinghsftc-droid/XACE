# World extensibility correction - completion

The pre-XP-007 architectural gate is satisfied for generic semantic binding.
World Contract v3 carries project-defined types and validated properties independently
of its supported geometry backends. No space/strategy/horror noun was added to core.

## Changes

- F1: explicit v3 source/compiler/Rust reader, versioned schema declarations, full
  transform metadata, actor-instance and compound bindings, typed properties,
  capabilities, role-keyed relationships and multiple asset requirements.
- F2: AABB constraints apply only to profile members; query filtering precedes shape
  validation. Nearest no longer rejects rotation/scale. Parented targeting still
  requires resolved world coordinates; this correction does not add a hierarchy solver.
- F3: catalog v2 declares component target roles; actor/world requirements are conditional.
  Additive template fragments use collision checks and the normal atomic GDE path.
  Builder proves a no-actor/no-world global-system proposal reaches approval.
- F4: Factory accepts namespaced custom classifications and Rust's Custom object form.
- F5: v3 role-keyed typed asset requirements support registered custom categories.
  Native loaders/importers remain separately supported presentation implementations.

Legacy v2 world/session vectors retain their meaning. Migration is explicit source
conversion followed by recompile/rehash. A new session profile binds v3 requirements
and semantic capabilities to verified artifact bytes. Host support is trusted input.
The compiler/runtime share the supported geometry descriptor in profiles.json.

Implementation: `packages/schema-factory/src/world_contract_v3.py`,
`packages/core/src/world/v3.rs`, `packages/runtime-core/src/geometry.rs`,
`QueryEngine::bind_world_v3`, `ISystemContext::world_objects_v3`, catalog authoring
and existing Builder approval integration. Full paths/hashes are in the evidence.

## Verification

- Broad isolated Python gate: 1,135 passed (127 Factory, 200 GDE, 448 PIL, 360 Builder).
- Final targeted Python checks after finishing edits: 22 world tests and 10 authoring
  tests passed; includes 8 new extensibility tests. Counts overlap the broad gate.
- Final targeted Rust: 48 passed (legacy/session/v3/query/reference proofs).
- Core/runtime library regressions: 541 + 701 passed, no failures.
- Shared Python-to-Rust canonical vectors: eleven project concepts, twelve objects,
  compound and repeated instance bindings, two typed asset roles and custom category.
- Both reference configurations have identical per-tick hashes/events under legacy
  and explicitly migrated v3 bindings. Existing replay tests remain green.
- Source inventory has the same 31 pre-existing findings, no new omissions.

Final targeted checks cover the namespace/profile/Builder wording edits made while
the broad gate was running. No native engines, provider calls or new games were used.
These results certify representation, validation, binding and generic authoring;
they do not claim every geometry solver, effect renderer or asset format exists.

XP-007 and later task wording now requires complete schema/profile identity and
generic authoring/mutation/replay behavior. Wall-run/shockwave are reference proofs.

**SAFE TO START XP-007**

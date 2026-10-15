> Reconstructed historical NEC003 document. Fresh recovery verification pending; original evidence and output paths below are historical. See AGENT_PROGRESS.md.

# NEC-003 - Normalized native authoring contracts

Completed 2026-10-09 in the local, uncommitted `target/xp016-work` repository.
Scope: shared authoring contracts and their executable validation. NEC-004 has
not started. The XP-022 runtime, engine adapters, sealed release and certification
evidence are unchanged. REL-01 through REL-05 remain open.

## Implementation and verified reuse

- [native_authoring_values.py](../packages/project-system/native_authoring_values.py)
  implements exact numeric normalization, typed assets, the supported semantic
  playback tuple and the frozen AABB geometry admission subset.
- [native_authoring_contract.py](../packages/project-system/native_authoring_contract.py)
  implements host-owned field policies, capture inspection, immutable snapshot
  bytes, versioned loss reports, hash-guarded deltas and write-field selection.
- NEC-002 [authoring_identity.py](../packages/project-system/authoring_identity.py)
  supplies project/namespace/branch identities, generations, persistent locators,
  scene/prefab relationships and mapping digests. No identity/store code changed.
- [AssetReference](../packages/asset-registry/asset_reference.py) supplies the real
  asset representation and lifecycle validation. Semantic playback compatibility
  reuses `PLAYBACK_EXPECTED_TYPES` from
  [asset_reference_preflight.py](../packages/asset-registry/asset_reference_preflight.py).
  Runtime/handoff readiness still belongs to that preflight and
  [semantic_binding_status.py](../packages/asset-registry/semantic_binding_status.py).
- Geometry restrictions match
  [world_contract_v3.py](../packages/schema-factory/src/world_contract_v3.py) and
  [profiles.json](../packages/core/src/world/profiles.json). The authoring envelope
  does not replace the World compiler or its registered profiles/assets checks.
- Coordinates invert the existing XP-016 conversions in
  [Unity](../adapters/unity/XaceNativeContract.cs),
  [Unreal](../adapters/unreal/XaceNativeContract.cpp) and
  [Godot](../adapters/godot/xace_canonical_entities.gd).

## Versioned wire contracts

All schemas are version 1; unknown versions/keys fail closed. A capture uses
`xace.native_authoring_capture.v1` and contains exactly:

- `project_id`, `namespace_id`, `branch_id`, `mapping_digest`, matching the supplied
  validated NEC-002 map. New identities require that separate reviewed identity
  workflow; this contract never guesses IDs from names or allocates them on load.
- `source`: engine, exact engine/reader/materializer versions, `play_mode`, and
  documents with persistent `id`, SHA-256 `before`/`after` fingerprints and `dirty`.
  Host policy pins versions out of band. Payloads cannot grant capabilities.
- `scope`: sorted, unique active authoring IDs. All scoped objects must be present.
  Scene, prefab-definition, parent and explicit dependency closure must also be
  present. The document list must exactly cover those objects' persistent locators.
- `objects`: each row has `generation` (int64 text), `deleted` (bool), `parent_id`,
  `fields`, `dependencies`, and `opaque`. Explicit deletion is a proposal with no
  remaining fields/edges/parent; missing rows never mean deletion. Runtime EntityID
  is not an authoring address.

`inspect_capture(capture, mapping, policy)` returns immutable canonical inspection
bytes (`xace.native_authoring_inspection.v1`). These contain the original bounded
capture, normalized objects, numeric profile, policy digest and a loss report
tagged `xace.native_authoring_loss_report.v1`. Keeping the source representation
allows independent revalidation, diagnostics and preservation of opaque evidence.

`inspection.admit()` returns `xace.native_authoring_snapshot.v1` bytes only if
there are no blocking losses and any precision review is explicitly acknowledged.
The acknowledgement is the SHA-256 of the entire inspection, including source
fingerprints; it cannot be reused after a source change. This API is a mechanism
for a future reviewed flow, not an implemented user approval interface.

`load_snapshot(bytes, mapping, policy)` repeats capture validation and normalization
and verifies exact canonical bytes, policy, losses and acknowledgement. Consumers
must use this loader: constructing the Python `Snapshot`/`Inspection` dataclasses
directly is not a trust boundary. Tampering with normalized data or hiding losses
does not survive load.

`make_delta` and `apply_delta` use `xace.native_authoring_delta.v1`: base/target
snapshot digests, the complete target capture header, and changed object rows with
per-row before digests. Source-only changes are retained even with no changed
objects. Applying a delta validates both the base and reconstructed target before
returning new bytes. Scope or identity-map changes require a full snapshot.
This is transport differencing; B/X/E reconciliation remains NEC-008.

## Values, ownership and loss semantics

All wire numbers are strings, including generation and int64 custom fields.
JSON numeric tokens, floats, booleans used as numbers, NaN/infinity, exponent
notation and int64 overflow are refused. Native decimal inputs are bounded exact
decimal text. Readers must format their native typed values before crossing this
boundary; this code cannot restore precision already lost inside a native API.

Canonical fixed64 values use scale 1,000,000, metres, Y-up and negative-Z-forward.
Quantization uses exact rational arithmetic and round-to-nearest, ties-to-even.
Every discarded fraction produces a field/axis precision-review entry.
Unity mirrors Z for positions/normals and X/Y for quaternions. Unreal converts
centimetres to metres for positions, offsets and sizes; its canonical position is
`(native_y, native_z, -native_x)/100`. Normals use the axis mapping without unit
scaling; sizes/scales permute without a sign flip. Godot uses canonical axes.
Quaternion signs are canonicalized using the first nonzero component in W/X/Y/Z
order. Normals/quaternions must be unit length within 4,000,000 in squared fixed
units around 1,000,000 squared; no implicit engine-style renormalization occurs.

`FieldPolicy` declares a value type, canonical/native ownership, read/write
allowlists and a `review` conflict rule. Policies are trusted host inputs, hashed
into snapshots; a different policy invalidates prior snapshots. Built-in field
types/ownership cannot be redefined. Extensions must be declared by the host,
still fit the bounded type vocabulary and acquire no CGS authority by declaration.
All built-in writes default to disabled. Native-owned fields may be observed but
cannot be selected for XACE writes. Canonical-owned fields are only proposals:
canonical ownership never grants the engine permission to commit CGS changes.
Structural parent/deletion proposals likewise always require review and later GDE
operations. There is no timestamp winner or automatic field commit.

Built-in fields cover transform vectors/quaternion, AABB geometry, typed
presentation assets, a typed semantic playback binding, named input action and
animation state. `binding.playback` carries `binding_id`, `event_name`,
`playback_kind` and a real typed `AssetReference`; playback/type combinations use
existing Animation/Audio/Vfx compatibility. It does not interpret controller
graphs, timing, arbitrary parameters or input behavior. A valid PLACEHOLDER or
MISSING asset may appear in an authoring proposal; snapshot admission is not a
readiness certificate, and UNRESOLVED assets are refused. Paths are evidence, not
verified filesystem existence. Registry membership and role/readiness checks
remain mandatory at adoption and Play.

Loss entries carry code, object ID, field, severity and detail:

- **Blocking:** unreadable/unknown fields, invalid values, unsupported geometry,
  dirty/racing documents, Play-mode capture, or critical opaque dependencies.
  No acknowledgement can admit these.
- **Review:** exact-to-fixed-grid rounding, requiring an inspection-bound digest.
- **Info:** noncritical opaque content retained in the native project, with
  explicit identity, content digest and reason. The snapshot inventories that
  content; it does not copy or translate its bytes.

Dependency edges use authoring IDs and resource/binding/behavior kinds. Targets
must be live within the selected closed scope; duplicates fail. Resource graph
cycles are representable; parent cycles, cross-scene parenting and parenting a
scene/prefab definition are refused. Native readers are responsible for trustworthy
dependency discovery and criticality classification; claiming cosmetic status is
not an automatic analysis of native code.

Nested presentation hierarchies remain explicit local transforms and parent IDs.
They are never flattened into gameplay geometry. Authoritative geometry admits
only unparented BOX bodies with identity rotation/scale, positive even raw sizes,
exact half extents, a bool trigger and bounds within the frozen world.aabb.v1
profile. Rotated/scaled/parented bodies, meshes and terrain cannot be silently
approximated. Optional broader World properties need explicit future mappings.

## Bounds and failure boundary

Every capture, inspection, snapshot and delta is bounded to 16 MiB; an inspection
stores raw and normalized values together, so practical capture capacity is below
that byte limit. Hard limits: 10,000 objects/documents, 64 fields per object/policy,
40,000 dependency plus opaque entries, 40,000 losses, 4,096 geometry bodies, nesting
depth 24, 1,000,000 JSON values, keys 256 ASCII characters, text 4,096 characters,
numeric input 96 characters, int64 output at most 20 characters. Duplicate JSON
keys and unpaired Unicode surrogates are refused. Unicode values remain supported
with deterministic ASCII JSON escaping. These are admission bounds, not measured
editor performance guarantees.

Malformed framing raises `IdentityError`; semantic conversion losses produce an
inspectable report and block admission as specified above. Neither success nor
failure writes native files, CGS, the identity revision store or the last baseline.
`writable_fields` returns only validated, allowlisted canonical proposal values.
It does not denormalize, save, authorize a native transaction or prove current
editor state. Dirty documents must be saved by the user/editor and recaptured;
there is no autosave, discard or mutable in-memory editor merge here.

## Verification and evidence

[Tests](../packages/project-system/tests/test_native_authoring_contract.py):
28 focused tests, including 30 static numeric golden cases checked independently
in Python and [Node BigInt](../tools/nec003_golden_check.mjs), full snapshot
Unicode/int64 canonical-byte digest parity, a 1,500-object hierarchy, 300 seeded
malformed mutations, loss review binding, capability escalation refusal, source
and identity drift, explicit deletion/dependency closure, and delta preconditions.

191 existing regression tests passed: NEC-002 identities 24, project system 11,
playable package 11, Player presentation 9, asset validation 107, asset preflight 5,
semantic binding status 2, World extensibility 8 and engine edit router 14.
Total: **219 unique passing tests**. The initial focused run exposed a mistaken
mapping-digest method call; it was corrected and all affected tests rerun. Logs of
the initial failure and subsequent passing runs are retained.

Reproduce focused proof with:

```powershell
python -m unittest discover -s packages/project-system/tests -p test_native_authoring_contract.py -v
node tools/nec003_golden_check.mjs packages/project-system/tests/fixtures/native_authoring_golden.json
```

Node is required, not silently skipped. This cross-language proof covers shared
wire/numeric semantics; it is not evidence of an installed Unity/C#/Unreal/C++/
Godot/GDScript reader or materializer. Those proofs remain NEC-004/005/006.
Runtime Rust and engine binaries were unchanged; their sealed certification was
verified rather than represented as a fresh engine/build/soak run.

Evidence: [receipt](evidence/nec003-contracts-20261009.json) and
`target/nec003/verification-20261009/`. The final preservation check compares all
2,140 protected XP-022 files with entry, verifies every sealed source entry except
the permitted live master addenda, and preserves original NEC-001/002 receipts.
Pre-NEC-003 master/roadmap copies in `target/nec003/entry-documents/` match their
NEC-002 receipts, which remain historical rather than being rewritten.

## Remaining roadmap

No task needs renumbering, replacement or scope expansion. The roadmap now records
this concrete handoff: NEC-004/005/006 readers must produce the versioned capture,
declare and certify their supported fields, compute trustworthy stable document
fingerprints, retain unsupported dependencies and use the shared golden corpus.
Their writers must implement inverse conversions and staged native saves; none
are implemented by the write-field selector. NEC-007 still validates adoption
through GDE/World/asset readiness; NEC-008/009 own reconciliation, approval and
multi-store recovery. Baseline advancement belongs to that coordinator.

No automatic engine watching/import, native writing, runtime-free export or
production native-editor continuity is claimed by NEC-003. **Stop before NEC-004.**

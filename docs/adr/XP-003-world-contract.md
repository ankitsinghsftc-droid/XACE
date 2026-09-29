# XP-003: World Contract v1 from CGS

Accepted implementation decision, 2026-09-24. XP-003 only.

The opt-in `modes[].world.contract` extension declares a stable artifact ID/version,
contract_version=1, numeric_profile=fixed64_y_up_neg_z_v1, and an objects array.
Exactly one mode may opt in. Each object has id, actor_id, kind and capabilities;
target_id and a typed asset_reference are optional. All IDs are bounded ASCII
semantic tokens using the existing ContractId vocabulary. An object ID is authored
once and retained through reorder, insertion and display-name edits. It is not a
runtime EntityID or an array index. Duplicate IDs/actor bindings and dangling
targets reject. A bound actor must have exactly one spawn instance.

Geometry comes from compiled actor blueprints and their existing UCL transform,
collider and identity components. No component was added or renamed. Roles and
binding declarations live in CGS world metadata, not an engine scene or a new
component namespace. Existing DCL/GCL registry validation remains in front of this
projection. All colliders in the selected mode must be explicitly bound; none can
silently disappear. Existing native SemanticAssetBinding tables describe event
playback and remain separate from world object/actor/target bindings.

The supported kinds are static_box, kinematic_box, trigger, spawn and anchor.
Kinematic denotes an initial geometry role; this task adds no movement executor.
Spawn and anchor are points without colliders. Boxes use collider shape BOX,
positive full size with exactly representable integer half extents, offset and
is_trigger matching the role. Size/position/offset/gravity use Fixed64 integer
micro-units (1,000,000 per metre). Transform rotation must be (0,0,0,1000000),
scale (1000000,1000000,1000000), parent_entity_id=0. Source transforms must explicitly
contain these fields; no native transform inference or float quantization occurs.
WorldSize, Gravity, Fixed64 and AssetType are reused by the shared Rust reader.
Other collider fields/rotated boxes/meshes/scales/parenting require a future profile.

The profile limits all world objects, including points, to 4,096; this is a
conservative resource cap within XP-001's AABB limit. Each coordinate and world
size is bounded to 8,192 metres, and each box endpoint must stay within +/-8,192.
Day length is an unsigned 64-bit tick value. The existing WorldDefinition size,
gravity and day fields are projected; visual environment settings remain in CGS.
XP-004 must enforce the separate 16 metres-per-tick movement/query policy. This
compiler has no tick execution, contact solver, native raycast or query cache.

Capabilities reuse XP-001's world.*.v1 vocabulary. Content requires aabb and
semantic_bindings plus the exact sorted union of object requirements. Unknown,
duplicate or unsorted output capabilities reject. Solid/wall_runnable/platform/
road require solid boxes; trigger/safe_zone require trigger volumes; spawn requires
a spawn point. Anchor requires interactable. A capability declaration records
requirements, not proof that a runtime/client implements or is certified for them.

Typed asset references are checked against CGS assets, including references in
actor components. UNRESOLVED/unregistered/mismatched references reject; PLACEHOLDER,
LINKED and MISSING retain the existing lifecycle. The content records semantic
asset ID/type only. Native source paths, resolution status and display labels do
not enter the world hash, so presentation replacement does not redefine collision.
No files are resolved and no engine payload is executed by this compiler.

The Schema Factory returns `CompiledSchemaPackage.world_contract` as immutable
content_bytes and manifest_bytes; decoded accessors return detached copies. This
is the existing compiled schema package, not the future playable distribution
package. Legacy schemas without world.contract receive None and retain their
existing behavior (including XP-002's documented legacy registry restrictions).
Factory validation is reached from Builder on both SGC recompilation and value-only
GDE edits. Failure returns no candidate package; the XP-002 GDE rollback path
restores the prior candidate before persistence. Source world data must match the
normalized projection, and package version/hash must match manifest provenance.

The repository's existing strict CGS validator is reused in-process with draft and
legacy hash exemptions disabled. Its source must be included with any authoring
compiler distribution; the reader/runtime only needs compiled artifacts. There is
no duplicate CGS hashing algorithm or validator exemption for world fixtures.

Canonical content is compact UTF-8 JSON with recursively sorted object keys,
objects sorted by explicit ID, sorted capability arrays and integer numerics.
SHA-256 covers these bytes. Rust reproduces Python's bytes/hash exactly. Source CGS
hash is deliberately outside the content digest: list reordering changes the
existing CGS hash while preserving semantic world bytes. The separate manifest
reuses WorldIdentity/ArtifactIdentity/ContentHash/ContractId and binds the digest,
mode ID and source CGS hash to the compiled schema package hash/version. Verification
requires an expected package identity from the caller; trusting a manifest's own
hash assertion is insufficient. The future XP-007 playable manifest must pin this
WorldIdentity alongside SGC, input and runtime identities. It does not exist yet.

The shared Rust `WorldContract::from_bytes` rejects malformed/duplicate JSON fields,
unknown nested fields, invalid roles, geometry, IDs, capability catalogs and bounds.
`WorldManifest::verify` verifies bytes via content_hash and external package links.
Neither API authenticates a publisher or admits a network peer. Consumers must
validate before use; runtime activation/native reader wiring remains later work.

Fixtures: packages/core/tests/fixtures/world_contract_v1. The source is a six-object
arena with floor, wall, lift, zone, spawn and switch. The malformed reader corpus has
23 cases. `python tools/xp003_world_proof.py` verifies the retained golden bytes;
`--write-fixtures` is an explicit maintenance operation. No production project,
legacy template, public readiness claim or XP-001/002 evidence is rewritten.

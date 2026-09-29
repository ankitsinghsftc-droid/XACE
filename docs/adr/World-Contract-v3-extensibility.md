# World Contract v3: project semantics and separately supported geometry

Status: implemented; correction regression gate passed. Owner authorization 2026-09-28.

The v2 contract certified an AABB projection and could not serve as the universal
semantic binding layer. V3 is an explicit successor; v2 bytes/readers remain valid.
CGS is the only editable authority. Factory projects validated actor defaults into
immutable, canonical world bytes and a manifest bound to the original CGS hash.

## Contract

Project `schemas` register namespaced versioned IDs and data-only definitions.
The portable v3 schema language supports signed 64-bit integers (including fixed
micro-unit values), booleans, UTF-8 strings, arrays and nested closed objects.
Definitions and values are bounded and validated in Python and Rust. No dynamic
code, native path or per-game type enum is needed. Names have no built-in behavior.
Required fields and type changes require a new schema version/package identity.

Objects have stable IDs, actor/instance bindings, a semantic type and typed
properties, capabilities, role-keyed relationships and typed asset requirements.
Multiple semantic objects can bind one instance; geometry has one owner per
instance. Asset categories may be built-in categories or registered schema IDs.
Concrete paths/status/fallback/importers remain presentation concerns; unresolved
references block compilation. Changing visual bytes does not change semantics.

The transform projection preserves the complete canonical UCL transform, including
rotation, scale and parent ID. This does not add a hierarchy solver. Gameplay state
still lives in components and changes only through MutationGate. `world_objects_v3`
exposes immutable authored metadata, not a substitute for reading live transforms.

`geometry_profiles` are independent platform requirements. `world.aabb.v1` is the
currently implemented deterministic backend. The compiler and runtime share its
identity and limits through `core/src/world/profiles.json`; adding metadata alone
does not install a backend. Only its members must satisfy the
bounded unparented identity-rotation/scale BOX profile. Unbound/cosmetic colliders
are excluded when the v3 binding is installed. Nearest targeting permits arbitrary
rotation/scale, but requires a resolved unparented world position. Unsupported
required backends reject; inventing a noun does not require inventing a backend.

## Integration

Factory dispatches explicit v2/v3 source versions. Rust `WorldContractV3` validates,
hashes and verifies provenance. `QueryEngine::bind_world_v3` installs a detached
actor-instance mapping atomically; compound capabilities are unioned deterministically.
Restore retains immutable package bindings; new package activation must rebuild them.
The v3 session profile derives exact requirements from the world artifact, without
requiring AABB for a geometry-free world. Older session profiles keep old rejection
semantics. XP-007 must verify and install this boundary when loading a package.

Catalog authoring v2 declares component target roles; world requirements are
conditional. Global packages need neither actors nor a World Contract. Additive
fragments merge declarations with collision checks on the existing GDE copy and
approval path. Legacy empty-mode template behavior remains a v1 compatibility rule.
Package systems must still match separately registered host execution contracts.

`migrate_v2_source` is explicit and returns a new contract; callers rehash/recompile.
It translates old roles into ordinary schema IDs. It does not reinterpret artifacts.

## Evidence and limits

Data-only fixtures use eleven space/strategy/horror concepts through the same code,
including compound/repeated bindings, multiple assets and nonidentity transforms.
The existing traversal package remains the only implemented gameplay proof.
Its tick hashes/events are compared using old and migrated v3 bindings for both
configurations. This certifies extension seams, not every imaginable solver,
renderer, file format, native engine or whole-game generation path.

# XP-016: native World Contract and session readers

Status: implemented; installed Unity host acceptance pending its license.

Unity, Godot, Unreal and Player consume the same authoritative full-projection
session profile and World Contract v3. This extends presentation adapters, not
game rules or the World Contract compiler. No authoritative Rust implementation
changes are part of XP-016.

## Contract and extension boundary

Adapters pin the raw `world.json` SHA-256 to the session offer before connecting.
The authority already validates the package, schemas and world. Native readers
support the declared `world.aabb.v1` geometry profile and reject unsupported
required capabilities. That bounded geometry implementation does not restrict
project semantic nouns, properties, relationships, asset references or capability
names. Those remain opaque versioned project data on canonical-object bindings.
Several semantic objects may bind to one canonical entity; the mapping is not
assumed to be one-to-one. Unknown component objects remain separate typed
component envelopes. Their field names never override the transform component.

The marker proof uses `project.marker.v1`, `project.any_surface.v1`, an unknown
component and two semantic aliases for one entity. It adds no gameplay mechanic.
The existing reference package appears only in regression/live proof inputs.
There is no wall-running, jump-attempt or shockwave dispatch in the new readers.
More native asset formats and executable geometry profiles require explicit
adapter support; supporting arbitrary semantics is not a promise to render every
asset format or simulate an unsupported collision primitive automatically.

## Coordinates and canonical primitive presentation

Canonical transforms use fixed-point millionths, metres, Y up and right-handed
coordinates. Godot preserves axes; Unity reflects Z; Unreal maps `(x,y,z)` to
`(-z,x,y)` in centimetres. Quaternion conversion follows the same basis change.
Dimension/scale conversion never negates an extent. Transform parenting preserves
local transforms; presentation verifies resolved acyclic parents before applying.
Deleting a native parent cannot implicitly delete another canonical entity.

Box presentation uses collider size and offset, rather than a demo capsule or
flattened component fields. Absent collider `layer_mask` means 1, matching World
Contract v3 compilation. Trigger geometry remains available as semantic data.
Godot's shared canonical manager supplies both native integration and Player;
Player keeps its admitted presentation catalog and playback restrictions.

Native authoritative mirrors disable local collision/simulated rigid bodies.
Cosmetic rendering/animation can remain native. Live transport feedback routes
reject native contact/physics feedback so it cannot define gameplay outcomes.

## Admission, readiness and input

Configure transports with an issued session ticket and the exact admitted raw
world artifact before connecting. Unity exposes `ConfigureLiveSession`, Unreal
exposes `ConfigureLiveSession` to Blueprint, and Godot exposes
`configure_live_session`. Existing installation/package inventories include the
new readers. Unreal's generated module links its engine-provided OpenSSL for
SHA-256; it does not invoke an unimplemented generic platform hash function.

Readers verify session/incarnation/ruleset identities, CGS hash, owner/controller,
connection generation, sequence, next tick and the raw projection digest. They
reject duplicate/unsorted entity IDs, unsafe numeric identities, malformed typed
envelopes and unresolved/cyclic parents. JSON-number metadata is limited to exact
integers through 2^53-1; oversized values fail rather than silently round.
Godot converts integer protocol metadata back to integers when serializing its
offer, since its JSON parser otherwise emits floating-point numbers.

Only a verified, applied baseline is acknowledged for readiness. Gaps or damaged
updates fence input and request a full replacement; stale generations/sequences
drop. Reconnect preserves assigned player identity and uses the rotated grant.
Full replacement clears presentation side effects through existing restore paths.
The authority's current ruleset epoch remains pinned; staging/activation of a new
ruleset belongs to later tasks, not an adapter-side reinterpretation.

Collectors use arbitrary configured action names and authority-requested ticks.
They send owned idle packets as well as active input, with one packet per request.
Live input never uses a render timer or snapshot-plus-one guess. Axis/button kinds
share changed/started/performed/cancelled meaning, including button edge tracking
and reset on reconnect. Existing standalone paths retain their earlier behavior.

## Evidence and remaining gates

`tools/xp016_native_proof.py --generate` emits the shared fixture. Installed
Godot and Unreal execute its 15 transcript cases plus native marker, hierarchy,
normal, dimensions, semantic aliases and input fencing assertions. Their live
proofs connect to a real authority, advance eight ticks, reconnect at generation
2 and retain the assigned player. Unreal builds Development and Shipping.

Unity sources and the editor proof compile against installed Unity assemblies.
The actual editor exits 198 with no active license. Compilation does not count
as installed-host acceptance. Activate the license, then execute the retained
Unity proof before claiming XP-016's all-host gate or XP-017 mixed-engine play.

Player exported regressions compare full authoritative projection digests, not
exit-only schedule files or a replay world-hash proof. Test-only failure reporting
keeps the proof alive to assert state freezing after the production failure path.
The old standalone missing-cosmetic XP-009 scenario fails before session creation:
the unchanged authority requires every declared package file at startup. This is
recorded separately; subset runs explicitly set `full_suite: false`.

See `../XP016_COMPLETION.md` and `../evidence/xp016-baseline.json` for commands,
actual versions, retained results and limitations. XP-017 is not implemented here.

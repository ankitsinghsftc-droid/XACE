# XP-009 Player presentation contract

Status: implemented and verified, 2026-09-29.

Presentation catalog `xace.player.presentation.v1` pins a compiled world hash and
contains typed asset references, world-object visual bindings, arbitrary namespaced
event bindings, and camera/overlay preferences. Supported resource formats are
explicit and versioned; no script or PackedScene is loaded from a game package.

Authoritative snapshots carry generic `xace.presentation_event.v1` records in the
existing events envelope. Event keys use tick and deterministic emission index.
Handshake `xace.world_bindings.v1` maps verified stable object IDs to actual entities,
including compound objects. Neither mechanism interprets game nouns or effects.

Preparation validates the whole catalog before creating admission output. Runtime
Player preparation decodes resources off-tree, reports permitted cosmetic fallbacks,
and verifies required geometry/host bindings before submitting first input. Required
geometry and binding mismatches block activation. Optional absent cosmetics may fall
back; present but checksum-mismatched files always block.

Presentation side effects are deduplicated per binding/event occurrence, expire at
bounded tick lifetimes, and are detached/stopped on rollback. Restore clears the
occurrence ledger for the restored timeline and reapplies static bindings. Cosmetic
assets and collision overlays never alter canonical contacts or world hashes.

## Catalog and resource contract

`presentation/player/presentation.json` has exactly: `schema`, `world_hash`,
`assets`, `objects`, `events`, `camera_offset`, `collision_overlay`.
Each asset has `asset: {id, asset_type, status}`, `format`, nullable `path`,
`required`, and `fallback` (`canonical`, `marker`, or `silent`). Binding references
carry `{id, asset_type}`. Status is Linked, Missing, or Placeholder; Unresolved
rejects admission. Catalog references are presentation-local and do not create CGS
assets or mutate World Contract. World object IDs must already exist.

| Format | Asset type | Admitted data |
|---|---|---|
| `xace.mesh.v1` | Mesh | Indexed triangles, vertices, RGBA; no scripts/material code |
| `image.png.v1` | Sprite | PNG, at most 4096 per dimension and 4,194,304 pixels |
| `audio.pcm_wav.v1` | AudioClip | PCM8/16 mono/stereo, 8?96 kHz, at most 10 seconds |
| `xace.effect.ring.v1` | Particle | Radius, color, duration 1?600 ticks |
| `xace.camera.impulse.v1` | Project namespaced versioned type | Offset, duration 1?120 ticks |

Resources are capped at 16 MiB each; catalogs at 4096 entries per list. Mesh limits
are 65,536 vertices and 196,608 indices. The Player decodes only manifest-admitted
paths. An unlisted file that appears later cannot become an admitted resource.
PNG decoding is completed by Godot during preparation; required decode failure
blocks launch. Optional decode failure reports fallback.

Objects bind `{object_id, asset}` to canonical entity transforms. Multiple semantic
objects may bind the same entity. Event bindings contain `{binding_id, event_name,
entity_selector, asset}`; selector is source or target. Names are arbitrary
namespaced strings, not built-in gameplay enums. Ring/audio/camera are supported
presentation formats, not authoritative mechanics. Other resource formats require
an explicit versioned decoder; new game nouns do not require core changes.

## Bridge and lifecycle

`WorldGeometryBindings::object_entity_ids` exposes verified stable bindings.
`HandshakeAck.world_bindings` is additive with a serde default, advertised by
`xace.world_bindings.v1`. `EngineBridge::send_tick_with_events` retains the old
`send_tick` wrapper. `presentation_events` maps actual emitted events to the existing
GameEvent envelope and advertises `xace.presentation_event.v1`. Payload, source and
target survive; occurrence identity is creation tick plus deterministic emission
index because the emitted copy precedes EventBus ID assignment. No new EventType
variant or mechanic-specific authoritative branch was added.

The Player validates bindings and supported canonical geometry before input tick 0.
F3 toggles the canonical collision overlay. Legacy playback commands cannot load
package scenes through the Player; other engine adapters retain their existing path.
Restore suppresses transient playback from its baseline, detaches effects immediately,
stops audio, resets camera/ledger, and rebuilds static bindings. Same-timeline
duplicates are suppressed; replay after restore can create a new occurrence once.
At most 256 active effects and 8192 ledger entries are retained, with old ledger
entries pruned after 1200 ticks. This certifies ordered local TCP presentation, not
remote reconnect epochs or live package replacement.

See `../XP009_COMPLETION.md` for evidence and scope.

# XP-009 Player presentation contract

Status: implementation in progress, 2026-09-29.

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

# XP-008: local authoritative Player

Status: implemented 2026-09-29, Windows x64 local keyboard profile.

## Product contract

The exported Godot application starts an owned, admitted Rust sidecar. Only the
sidecar runs gameplay. The Player uses shared adapter/transport/protocol/entity
storage, with a typed canonical visual projection instead of the legacy demo scene.
It finds a controlled entity from COMP_INPUT controller identity, preserving ownership
metadata when timed input updates arrive. Camera and selection do not depend on
actor nouns, a fixed arena, or entity ID 1. Transform parenting is validated before
application; unresolved parents and cycles fail visibly.

`xace.player.controls.v1` declares arbitrary wire action names, keyboard keys and
axis/button kinds in presentation data. The runtime retains full action records for
package systems, alongside existing compatibility fields. Keyboard focus loss emits
neutral values. Button edges remain explicit. Every packet is tagged for a simulation
tick. Local lockstep waits without advancing authoritative time; 30/144 FPS recorded
input runs must produce identical hashes. Slow delivery can stall this local profile;
this is a determinism proof, not a 60 Hz throughput certification at every render rate.

## Package admission and native composition

XP-007's full verifier runs at preparation. A trusted distribution receipt pins the
exact verified manifest and native executable. The Player checks that receipt and
all manifest file hashes before launching anything. Package contents cannot provide
the receipt. This is a pre-admitted single-package distribution, not an unrestricted
archive browser or publisher-signature service. New package data can be prepared and
exported with unchanged Player/core code. XP-010 owns installer/catalog lifecycle.

`HostSystemRegistrar` is a trusted native initialization hook. It registers ordinary
ISystem implementations before plan validation, and their read/write declarations
must match persisted SGC access contracts. Registration survives cloned runtime
configuration and restore/replay initialization; packages cannot inject callbacks.
The standard CLI moved into a reusable runtime module. The ordinary runtime binary
passes no registrar; the reference host registers its gameplay package explicitly.
No runtime, network or adapter branch recognizes traversal mechanic names.

The reference package now uses the existing Fixed64 JSON convention for real decimal
input values as well as recorded integer microunits. Missing startup input means idle;
malformed present axes still fail. Its rules, capability and state remain package-local.

## Lifecycle and scope

Verification failure prevents sidecar launch. A lost, disconnected or unresponsive
runtime freezes Player state and reports a reason. Closing the Player disconnects and
stops only its created process. Tests keep an unrelated sentinel process alive.

Canonical boxes are a presentation of the supported geometry profile. Objects without
that representation use a small presentation placeholder; arbitrary semantic schemas
are retained in package/world data and are never interpreted as physics rules.
Rich assets, effects, presentation readiness and supported importer policy remain
XP-009. Remote sessions, universal installers and cross-engine certification remain
later tasks. No additional mechanic was implemented as a generality proof.

Official Windows export template source:
[Godot 4.6.3 archive](https://godotengine.org/download/archive/4.6.3-stable/).
Its ZIP entry was CRC-checked during extraction; exact SHA-256 and URL are retained
in XP-008 evidence. The executable proof uses the export runtime, not the editor.

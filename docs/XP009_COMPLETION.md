# XP-009 completion ? 2026-09-29

XP-009 is complete for the local Windows Player and the explicit presentation
formats below. XACE remains mechanic-agnostic. The reference package's existing
shockwave exercises a generic emitted-event path; no wall-run, shockwave or arena
branch was added to the runtime, compiler, World Contract or Player.

## Implementation

- `packages/project-system/player_presentation.py`: typed, versioned catalog
  validation, path/resource limits, world-hash binding and fallback/readiness report.
- `tools/xp008_player_build.py`: catalog admission before any output; trusted receipt
  records permitted absent cosmetic files. Present checksum mismatches still reject.
- `apps/xace-player/presentation.gd`: data-only mesh, PNG, PCM WAV, ring and camera
  decoders; stable object bindings, canonical collision overlay, generic event
  playback, deduplication, expiration and restore cleanup. Package scripts/scenes are
  never loaded. New nouns and event names use data; new renderer formats need decoders.
- `apps/xace-player/player.gd`: preparation before host launch, binding verification
  before input tick 0, reported placeholders, camera configuration and F3 overlay.
- `apps/xace-player/canonical_entities.gd`: admitted presentation integration,
  suppression of baseline transient events during restore, static fallback ownership.
- `packages/runtime-core/src/geometry.rs`: complete object/entity projection,
  including compound objects sharing an entity.
- `packages/runtime-core/src/engine_protocol.rs`: additive handshake map and generic
  versioned event projection, preserving arbitrary event names/source/target/payload.
- `packages/runtime-core/src/engine_bridge.rs` and `runtime_orchestrator.rs`: publish
  verified bindings and actual emitted events. Existing send_tick API remains usable.

The World Contract remains the canonical semantic/geometry source. Catalog visuals
cannot change colliders or contact queries. The bounded ring renderer is one supported
cosmetic primitive; it does not define an authoritative shockwave mechanic.

## Verification

- 704 runtime library tests, 20 geometry tests, 2 new event/compound-binding tests,
  and 13 reference package/host tests pass.
- 35 project-system Python tests pass, including arbitrary object/event names,
  missing/required resources, type/path/format rejection and no partial preparation.
- Real Godot: 19 presentation assertions and 8 canonical mirror assertions pass.
  Mesh/PNG/WAV decoding, static fallback, world mismatch and rejection of unadmitted
  resource bytes are covered.
- Real exported Player + native host: all six scenarios pass. Normal runs resolve
  mesh skins and trigger three bindings (ring, audio, camera) from the native fixture.
  Missing ring bytes report fallback. Invalid world binding, missing geometry, and
  tampered cosmetic bytes block play with zero inputs. Owned hosts stop after exit.
- Duplicate-event suppression, immediate detach/audio-stop/camera reset on restore,
  unchanged mirrored entity state, replay once and expiration are asserted in the
  exported Player. An arbitrary `project.docking_pulse.v1` event uses the same API
  in the test harness without implementing another gameplay mechanic.
- Two different cosmetic packages have identical gameplay identity and all 30
  authoritative tick hashes. The fixture's canonical contact/state results are
  therefore unchanged by the asset replacement.
- Screenshot inspected: live ring, meshes and canonical collision guides render.

Evidence: [baseline](evidence/xp009-baseline.json), [screenshot](evidence/xp009-player.png),
[contract](adr/XP-009-player-presentation.md). Detailed process reports and hash logs
are in `tmp/xp009-final/`. Production executable:
`tmp/xp009-final/0/exported/xace-player.exe` (keep its PCK and package directory).

## Reproduction and limits

Build the reference host using `cargo build -p xace-reference-mechanic --bin
xace_reference_host --offline`, then run `python tools/xp009_player_proof.py
--template tmp/xp008-export/windows_release_x86_64.exe`. The installed Godot 4.6.3
and official matching release template are required for export. Keyboard input is
automated through the production collector; this is not manual user testing.

This is one pre-admitted local package on this Windows machine. Supported canonical
collision profile remains AABB; arbitrary gameplay nouns are independent of that
solver profile. This does not certify every asset format, remote session epochs,
clean-machine installation, runtime package switching or live ruleset mutation.
Restore tests invoke the existing adapter rollback contract; remote session delivery
and mutation choreography remain later tasks. XP-010 is next and is not started.

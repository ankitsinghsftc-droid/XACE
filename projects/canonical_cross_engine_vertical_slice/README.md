# Canonical Cross-Engine Vertical Slice

This project fixture is the X10-063 canonical CGS-owned slice consumed by later
installed-engine proof tasks. It is not an engine-native project and does not
claim Godot, Unity, or Unreal editor certification by itself.

The fixture defines one portable gameplay slice covering movement, combat,
health, inventory, save/load, rollback, replay, semantic bindings, animation,
audio, VFX, and network-ready input.

Primary files:

- `game.cgs.json` - committed CGS export with matching canonical SHA-256 hash.
- `xace.vertical_slice_manifest.json` - versioned fixture manifest and coverage
  map used by `tools/canonical_vertical_slice_check.py`.
- `assets/` - tiny hash-stable placeholder files for linked animation/audio
  asset references. VFX is represented as a deterministic documented fallback
  because there is no single linked particle extension accepted by all three
  target-engine preflight matrices.

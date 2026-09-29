# XP-008 completion - 2026-09-29

XP-008 is complete for the exported Windows local keyboard Player profile.
World Contract remains generic: no new game-noun dispatch or traversal-specific
branch was added to core. Wall-running is executed by the separately composed
reference package host.

## Implementation

- `apps/xace-player/`: package verification, owned sidecar lifecycle, timed controls,
  status, canonical presentation, dynamic controller selection and camera.
- `adapters/godot/xace_adapter.gd`: accepts compatible adapter subclasses and explicit
  input tick zero. Default untimed convenience calls still choose the next tick.
- `packages/runtime-core/src/runtime_orchestrator.rs`: trusted host registrar with
  persisted access-contract validation; retains controller/project input metadata
  and complete arbitrary action records through the scheduled mutation gate.
- `packages/runtime-core/src/runtime_cli.rs`, `src/bin/xace_runtime.rs`, `src/lib.rs`:
  shared CLI and recoverable local lockstep waiting.
- `examples/reference-mechanic/src/bin/host.rs`: ordinary reference-system host
  composition. The package parses live input with shared Fixed64 conventions.
- `tools/xp008_player_build.py`: verified admission receipt and native export APIs.
- `tools/xp008_player_proof.py`: reproducible exported v3 package proof.
- Three Player preparation regressions, three host integration regressions, one
  arbitrary-action runtime regression, four persisted host fixture files, and
  `apps/xace-player/tests/canonical_entities_test.gd`.

## Verified results

- **704 runtime library tests** and **51 targeted Rust tests** passed.
- **25 project-system Python tests** passed.
- Installed Godot canonical presentation test: **8 assertions** passed, covering
  typed component isolation, arbitrary entity/controller IDs, parent transforms,
  collider size/offset and cycle rejection.
- Exported Player plus native host: **30 identical authoritative tick hashes at
  30 and 144 FPS**, with identical recorded inputs. The v3 reference fixture proves
  movement, canonical wall contacts, wall-running and two wall jumps through Rust.
- Focus loss releases input; runtime loss freezes state after six ticks; close stops
  only the owned sidecar; unrelated sentinel processes remain running.
- Tampered world rejected before process launch. Direct executable launch locates its
  package correctly even from a different working directory.
- Child PATH excluded editor/Python/Rust toolchains. Input proof used automated
  Godot InputEventKey events through the production key collector, not manual play.
- Source inventory retains **31 pre-existing findings**, with no additions.

Evidence: [source-bound report](evidence/xp008-baseline.json),
[actual exported viewport](evidence/xp008-player.png), and
[architecture contract](adr/XP-008-local-player.md). Detailed logs and exported
executable live in `tmp/xp008-final/`.

## Remaining scope

The current distribution admits one verified package using a trusted receipt. It
requires no new core code for another game, but admission/export is a build operation;
installer/catalog UI remains XP-010. The profile uses local lockstep and can stall
when input delivery is slow. No remote session, clean-machine certification,
additional solver/importer, or arbitrary rich-asset support is claimed.
XP-009 supplies semantic asset/effect presentation and readiness.

**READY FOR XP-009.**

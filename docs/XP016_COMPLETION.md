> Recovery note (2026-10-12): reconstructed historical text from Codex patches, not fresh certification. The referenced original evidence JSON is not recovered. See `../AGENT_PROGRESS.md`. Do not use the historical disposable evidence paths below for new recovery work.

# XP-016 implementation checkpoint

XP-016's native world/session implementation is present on isolated branch
`xp-016`, based on `clean-main-candidate` at `39ed07b`. **All-host acceptance is
pending**, because the installed Unity editor has no active license. No XP-016
changes have been pushed, and neither local nor GitHub `main` has been moved.

The [architecture decision](adr/XP-016-native-world-session-readers.md) explains
generic semantic bindings, canonical geometry/conversion, ownership/readiness,
input fencing, recovery and the presentation-only boundary.

## Implementation

- New readers: `adapters/unity/XaceNativeContract.cs`,
  `adapters/unreal/XaceNativeContract.{h,cpp}` and
  `adapters/godot/xace_native_contract.gd`.
- Existing native transports, applicators and input collectors integrate those
  readers with generic action bindings and authority-requested ticks.
- `adapters/godot/xace_canonical_entities.gd` shares typed canonical presentation
  with Player's thin `apps/xace-player/canonical_entities.gd` wrapper. Player
  configures the same verified reader instead of directly setting ticket fields.
- Packaging, reversible installation inventories and installed-engine staging
  include the new dependencies. Unreal's generated module links engine OpenSSL.
- A shared marker/transcript fixture and native host proof entry points verify
  typed transforms, hierarchy, normals, extents, aliases and malformed sessions.

No runtime, network authority, SGC or World Contract compiler implementation was
modified. Semantic names and capabilities remain opaque project data. The only
Rust addition is a test proving the shared world fixture is admitted by the real
World Contract v3 reader. This is not an additional gameplay mechanic.

## Verification

Godot 4.6.3 and Unreal 5.7.4 pass 15 shared transcript cases, canonical native
geometry and input fencing. Both real authority sessions pass eight ticks,
same-owner reconnect at generation 2 and clean authority shutdown. Unreal's
plugin builds Development and Shipping. Unity 6000.4.9f1 sources/editor proof
compile against installed assemblies; editor execution fails with license exit
198, so its native assertions remain unexecuted.

The exported Windows Player passes 30/144-FPS input and projection equivalence,
focus release, runtime loss/state freezing, close, direct launch, tampered-world
rejection and owned-process cleanup while retaining an unrelated process.
Canonical World Contract/session Rust regressions pass (13 tests), project-system
tests pass (35), Builder launch tests pass (7), engine edit routing passes (14),
adapter reversibility passes (3 checks), and handoff preflight passes (4 checks).
The actual two-client socket proof also passes late join, readiness, reconnect,
resync and timeout fencing.

The full older XP-009 presentation suite does **not** pass its standalone missing
resource scenario: authority startup requires all manifest files. This requirement
already exists in unchanged `packages/runtime-core/src/live_session.rs`.
Its normal/alternate-artwork, binding mismatch, tamper and missing-geometry
scenarios are run separately with an explicitly partial report. Do not describe
that subset as a full XP-009 pass or silently change package admission to hide it.

## Reproduce

Run from the `xp-016` worktree; generated projects, credentials, binaries and logs
remain under ignored `target/`. The runner currently uses this machine's installed
engine paths; use equivalent installed toolchains when relocating it.

```powershell
python tools/xp016_native_proof.py --generate --engine godot --out target/xp016/final-godot
python tools/xp016_native_proof.py --engine unity-compile --out target/xp016/final-unity
# After license activation:
python tools/xp016_native_proof.py --engine unity --out target/xp016/licensed-unity
python tools/xp016_native_proof.py --engine unreal --out target/xp016/final-readers
python tools/xp016_native_proof.py --live --engine unreal --out target/xp016/final-readers
python tools/xp016_native_proof.py --live --engine godot --out target/xp016/final-godot
cargo test -p xace-core --test test_native_world_fixture --test test_world_contract_v3 --test test_session_contract
python -m unittest discover -s packages/project-system/tests
python tools/adapter_reversibility_check.py --output target/xp016/reversibility.json --artifact-dir target/xp016/reversibility
python tools/adapter_package_handoff_preflight_check.py --output target/xp016/handoff.json --artifact-dir target/xp016/handoff
```

Live proofs require a verified staged package (default
`target/xp016/player/exported/package`) and a fresh per-engine output directory.
Stage/export Player with the existing XP-008/009 proof tools and a trusted export
template. Run exported Player suites sequentially: they use the same default
port. Their reports compare raw verified projection digests, not replay world
hashes; the distinction is intentional.

Retained summary: [xp016-baseline.json](evidence/xp016-baseline.json).
XP-017 mixed-engine certification has not started. Earlier clean-machine,
two-machine and public Internet gates remain pending under the owner's existing
instructions. No universal asset-format or engine-version claim is made here.

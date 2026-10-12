> Recovered historical document: original evidence JSON and recordings are not recovered. Fresh recovery verification is pending; see AGENT_PROGRESS.md. Historical disposable paths below must not be used for new unique evidence.

# XP-017: local mixed-engine live play certification

Completed 2026-10-03 for real installed hosts on one Windows computer, using
loopback sockets and one authoritative runtime per scenario. Work remains
uncommitted in the `xp-016` worktree based on clean candidate `39ed07b`.

## Product capability and reference proof

Ordinary gameplay packages can run in a shared session across Player, Unity,
Godot and Unreal. Each client submits tick-indexed inputs for its own canonical
player and mirrors authoritative components, transforms and events. World/session
identity verification, ownership and disconnect handling remain generic.

The existing traversal reference package supplies the proof's action recording
and shared-event assertion. Its third-attempt shockwave changes a different
owner's velocity at tick 7. That assertion lives in the reference harness;
native proof clients read arbitrary configured actions and generic components.
No wall-running branches were added to core, World Contract, networking or adapters.
No new mechanics were introduced.

## Acceptance evidence

| Actual clients | Result | Client departing after tick 19 | Survivors |
| --- | --- | --- | --- |
| Exported Player + Godot | PASS | Godot | Through tick 39 |
| Unity + Godot + Unreal | PASS | Unreal | Through tick 39 |
| Unity + Godot + Unreal + exported Player | PASS | Player | Through tick 39 |

Every scenario verifies distinct owned players, a common session/incarnation/epoch,
actual component application and canonical local transform conversion, matching
applied projection digests and JSON event values at every agreed tick, wrong-world
refusal, recorded inputs matching the authority's accepted packets, and the shared
event's change to another owner's state. Each retains 40 authoritative world hashes.
Client proof compares its actual mirror to the projection before reporting success;
it does not merely echo the server hash.

Installed versions: Unity 6000.4.9f1, Godot/Player 4.6.3-stable and Unreal
5.7.4-51494982+++UE5+Release-5.7. Unreal Development and Shipping plugin builds
passed. Unity's final regression passes all 15 native contract cases, geometry and
input fencing. Python compilation and `git diff --check` pass.

[Retained evidence](evidence/xp017-baseline.json) includes source/build SHA-256
fingerprints, package file fingerprints, session identities, every authoritative
hash, client tick/digest records, transcript hashes and regression results.
Raw credentials are excluded. Generated binaries, tickets, logs and recordings
remain under ignored `target/xp017/`.

Actual Player viewport recordings are `target/xp017/final/pair/gameplay.mp4`
(40 frames, 2 seconds) and `target/xp017/final/four/gameplay.mp4` (20 frames,
1 second), H.264 at 1100x720. One rendered frame per authority tick is encoded at
20 FPS for inspection. A captured four-client frame was visually checked.
These short recordings are not latency measurements or polished gameplay demos.

## Implementation

- `tools/xp017_mixed_session_proof.py`: verified four-controller reference package,
  real host orchestration, ownership/application/event/refusal/disconnect checks,
  authoritative journal validation and recording.
- `tools/xp017_player_proof.gd`: exported proof build using production Player paths;
  sends recorded actions and captures the actual viewport.
- `adapters/godot/tests/mixed_session_proof.gd`,
  `adapters/unity/Editor/XaceMixedSessionProof.cs`, and
  `adapters/unreal/XaceMixedSessionProof.h`: generic installed-host proof clients.
- Unreal's native contract commandlet dispatch and `tools/xp016_native_proof.py`
  staging include the mixed-session proof.
- `adapters/unity/XaceTransport.cs`: generic JSON object parser now skips whitespace
  before the next key after a comma. Pretty-printed proof configuration exposed
  this existing parser defect. No gameplay-specific production fix was needed.

The proof also corrected release-build assertion side effects in its Player input
sender and compares parsed JSON event values rather than numeric spelling (`1`
versus `1.0`). The final matrix was rerun after these corrections.

## Reproduction and scope

With installed engines and Godot export template paths configured as in the tools:

```powershell
python tools/xp016_native_proof.py --engine unreal --out target/xp017/native
python tools/xp017_mixed_session_proof.py --stage --scenario all --out target/xp017/new-run
python tools/xp016_native_proof.py --engine unity --out target/xp017/unity-contract-regression
```

The final acceptance run used `--scenario all --out target/xp017/final` after
staging. Use a fresh output directory for a subsequent run. Unity must be licensed.

Inputs are scripted; native editors run headless/null-renderer proof hosts while
the exported Player renders. This certifies synchronization and application,
not human playtesting, visual parity across engines or Internet performance.
XP-010 clean-machine, XP-014 two-machine and XP-015 public relay/two-network gates
remain pending by owner instruction. The earlier XP-009 missing-cosmetic startup
regression remains open as documented in XP-016; it is not marked passing here.

XP-018 is next. Protected local main/safety refs were not moved; no commit or push
was performed for XP-016/017.

# XP-010 implementation record ? 2026-09-30

**Implementation finished and verified on this host. Clean-machine acceptance is pending.**
The owner confirmed that no clean Windows PC/VM is available and explicitly requested
that this acceptance test remain pending. XP-010 is not marked fully certified.

## Delivered

- `packages/player-launcher`: native Rust Windows launcher/broker, immutable verified
  staging, atomic active-install pointer, stale binary repair and exclusive install
  locks. The recipient needs no editor, Cargo, Python or Node.
- `apps/xace-player/player.gd`: broker ownership gate and token-bound first-tick
  readiness. Windows Job Objects clean the Player/runtime tree on stop, EOF or crash.
- `tools/xp010_player_distribution.py`: pinned editor/template export, runtime bundle,
  notices, file checksums, trust receipt, recipient README and ZIP assembly.
- `packages/builder-workspace/server/player_launch.py` and `player_launch_routes.py`:
  local installation discovery, saved-project validation, capability/origin guards,
  serialized native process control and shutdown cleanup.
- `packages/builder-workspace/server/builder_server.py`: route/lifecycle registration.
- `packages/builder-workspace/src/preview/engine_viewport.ts`: real Play/Stop flow,
  progress, busy protection and actionable Retry. The game opens in the native Player.

All APIs are generic. The existing reference fixture supplies the proof package;
there are no wall-run, arena or shockwave branches in installation or launch code.

## Verification

- 2 native unit tests; 366 Builder backend regression tests pass.
- Final 6 Player route/service tests pass, including hostile origin/capability/body,
  missing release and tampered installation discovery.
- Real-browser Play, busy/repeated click, capability, retry and Stop checks pass.
  TypeScript lint/type checking and the existing Builder UI contract suite pass.
- Real native processes with only Windows System32 in child PATH: unauthorized
  capability rejected, occupied port recovered, repeated Play reused one Player,
  Stop/EOF/broker crash/Player crash cleaned owned authorities, failed launch preserved
  the previous active pointer, damaged binary repaired, actual denied ACL install
  failed visibly and retried successfully after access was restored. An unrelated
  sentinel process survived throughout.
- The final recipient executable launched with **no command-line arguments** from
  outside its release folder. Its native window reached the first authoritative tick.
  The next Builder launch discovered that installation without environment path
  configuration and ran the matching saved game.

Measured final first install to ready: **10.641 seconds**, including verification
and materialization. Player startup after verification: **2.644 seconds** in the
same run (not a latency guarantee). Distribution payload: **120,834,356 bytes**;
ZIP: **39,546,841 bytes**. These are local development native binaries, not a signed
public release. Godot uses its pinned Windows release template.

Test host: Windows 11 Home x64 build 26200, Intel i7-12650HX, approximately 16 GiB RAM,
Intel UHD / NVIDIA RTX 4050 Laptop graphics. Declared target: Windows 10/11 x86_64,
OpenGL 3.3-compatible graphics, writable per-user local storage and at least 350 MB
free for archive, extracted release and first installed version; retained updates
require more. This profile and the observed hardware are **not minimum-hardware or
clean-machine certification**. Re-test graphics/dependency availability on that gate.

Evidence: [baseline](evidence/xp010-baseline.json),
[contract](adr/XP-010-player-distribution.md),
[clean-machine procedure](XP010_CLEAN_MACHINE_TEST.md).
Native proof: `tools/xp010_launch_proof.py`. Detailed logs remain under
`tmp/xp010-delivery/` and `tmp/xp010-builder-tests.log`.

## Delivery and scope

Extract `tmp/xp010-delivery/release.zip`, keep the folder contents together, and open
`XACE Play.exe`. It installs in `%LOCALAPPDATA%/XACE/Player`. Builder can discover that
verified local installation. The package must match the saved project exactly.
For authoring automation, `tools/xp010_player_distribution.py --help` describes the
assembly inputs; those build tools run only on the publisher's machine.

Play consumes a published, admitted release. Changed gameplay needs a newly published
package; it does not silently play an old demo or compile on a recipient's computer.
Unsigned local checksum trust is explicit; publisher signing/download distribution,
remote session admission and live package replacement are not certified here.
The remaining clean-machine test is recorded separately and has not been fabricated.
XP-011 has not been started.

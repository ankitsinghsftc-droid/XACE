# XP-014 — Play, Invite and Join

Status: implemented and verified with two exported Windows Players on one computer, 2026-10-02. **Two-machine acceptance remains pending by explicit owner instruction: no second machine is available.**

The native launcher owns one authoritative runtime. Play starts the host Player; Invite issues a ten-minute, single-use code; Join acquires and verifies missing package data, redeems a distinct controller grant, then opens the installed trusted Player against that authority. Builder and standalone Player expose invite, join progress, readiness and leave/end controls. A joining Player does not start another runtime.

The flow uses generic CGS input controllers, typed session identities, package manifests and verified baselines. No wall-run, wall-jump, shockwave or arena rule was added to the session architecture. Current limits are one to four predeclared human controllers, the admitted data formats and an exact trusted-runtime match; this is not a claim of universal asset-format support.

Implementation:

- `packages/player-launcher/src/session.rs`: versioned invite/descriptor protocol, private endpoint service, bounded acquisition, exclusive cache leases, authority ownership and journal-backed readiness.
- `packages/player-launcher/src/main.rs`: native Play/Invite/Join lifecycle and token-bound local Player controls. `distribution.rs` and `tools/xp010_player_distribution.py` include the admission receipt in the trusted distribution.
- `packages/runtime-core/src/runtime_cli.rs`: explicit private engine bind and bounded pending connection queue; runtime control is disabled for hosted sessions.
- `apps/xace-player/player.gd`: external authority mode, ticket controller binding and native session controls.
- Builder `server/player_launch.py`, `server/player_launch_routes.py` and `src/preview/engine_viewport.ts`: guarded local broker calls and user-facing controls.
- `tools/xp014_session_proof.py`, `apps/xace-player/tests/session_ui_test.gd` and the Builder launch tests: native, UI and failure proofs.

Verification on the final distribution `tmp/xp014-release-final2`:

- Two exported Players share one session/authority, own different canonical entities and both reach Playing after baseline verification. The friend begins without the package and has development tools removed from its child PATH.
- Expired/spent invites, executable downloads, path escapes and tampered files are refused. Failed acquisition leaves no Player/cache. Closing during acquisition cancels it; a readiness failure never becomes required-input membership and the host keeps playing.
- Leave releases membership/cache; End stops owned processes and closes the invite service. Authoritative journals survive in `session-history/`. Native EOF/crash cleanup, repeated Play, port collision, install repair and retry regressions pass.
- 6 launcher, 705 runtime-core and 7 network-core tests pass. Seven Builder launch tests, TypeScript checking, real-browser Play/Invite/Join tests, Godot session controls and XP-013 real-socket regressions pass.

The final proof also covers the startup fix that waits for every peer ticket before reading it, and cleanup of failed startup directories. Evidence and source/artifact hashes are in [xp014-baseline.json](evidence/xp014-baseline.json).

This is a private IPv4 transport implementation with same-machine verification, not two-machine LAN or Internet certification. XP-015 owns encrypted authenticated relay transport and external-network acceptance. XP-010 clean-machine acceptance remains pending. The [two-machine procedure](XP014_TWO_MACHINE_TEST.md) records the remaining gate; the [architecture decision](adr/XP-014-private-session-invites.md) records trust and recovery limits.

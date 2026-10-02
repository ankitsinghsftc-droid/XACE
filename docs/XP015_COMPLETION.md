# XP-015 — Bounded Internet relay transport

Status: implemented and locally verified with an actual TLS relay and exported Windows Players. **Public deployment and two-network acceptance remain pending by explicit owner instruction (no hosting available).** This is not a claim of completed Internet acceptance.

Configured Players now use outbound, certificate-verified TLS 1.3 for package acquisition and gameplay forwarding. The relay issues expiring, single-use invitations and scoped session leases, routes only package/game channels, and enforces session, connection, frame, queue, bandwidth and lifetime bounds. It cannot expose Builder/control APIs or choose arbitrary host targets. The creator's runtime remains authoritative; joined Players acquire data only and launch no second runtime.

The existing Play / Invite / Join controls select the configured relay. Local host targets and guest proxies bind loopback. Player displays relay interruption status. Brief link loss reuses the session and player identity, with a new verified baseline before input membership returns. Complete relay loss visibly fences remote players; local host play survives, and restart of the stateful session requires a new hosted session. There is no silent downgrade to private plaintext transport.

Files and boundaries:

- `packages/session-relay/{Cargo.toml,src/lib.rs,src/server.rs,src/client.rs,src/main.rs}`: typed v1 protocol/configuration, verified TLS client, bounded relay service and owned native bridges.
- `packages/player-launcher/{Cargo.toml,src/session.rs,src/main.rs}`: v2 relay invites, descriptor-pinned acquisition through the package tunnel, owned gameplay tunnel, transport health and self-join protection. Failed invitation publication leaves gameplay slots available.
- `apps/xace-player/player.gd` and `tests/session_ui_test.gd`: visible transport health and UI coverage.
- `tools/xp015_relay_proof.py` and `packages/session-relay/examples/transport_probe.rs`: real TLS/authentication/resource/fault proofs and repeated native transfer checks.
- Workspace Cargo manifest/lockfile: relay membership and pinned TLS dependencies. Existing distribution assembly includes their license notices.

No runtime, World Contract, geometry, CGS, SGC, gameplay system or engine protocol changes were needed. The reference game uses the same generic controller/session/baseline machinery as any admitted game. This task does not add a mechanic or claim universal asset-format support.

Verification and source/artifact hashes are recorded in [xp015-baseline.json](evidence/xp015-baseline.json). The local proof checks exported package acquisition and gameplay, two distinct players with one authority, reused-invite refusal, transient tunnel recovery, outage fencing and cleanup. It also checks certificate/authentication failures, fixed routing, expiry, one-use channel tokens and resource limits. Native unit tests, Player UI and XP-014/XP-010 regressions accompany it.

The deployment uses a trusted operator and explicitly provisioned endpoint/CA/hosting credential. It has no hosted public service, availability SLA, persistent relay recovery or measured Internet capacity yet. TLS terminates at the trusted relay. See the [architecture decision](adr/XP-015-bounded-session-relay.md) for exact bounds and [deployment/acceptance procedure](XP015_DEPLOYMENT_AND_TWO_NETWORK_TEST.md) for the remaining gate. XP-014 two-machine and XP-010 clean-machine acceptance remain pending. XP-016 is next; cross-engine play is not certified here.

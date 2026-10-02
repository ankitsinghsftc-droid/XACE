# XP-013 — verified baselines, late join, reconnect and recovery

Status: implemented and verified for the local Windows live-session profile on 2026-10-01.

Live-session transport admission no longer grants input membership. A peer must acknowledge its exact current projection before joining the required-input set. The versioned stamp identifies the session, authority incarnation, ruleset epoch, connection generation, baseline UUID, per-connection sequence, next simulation tick and SHA-256 projection digest. `next_tick` means state before that tick; late join never assumes zero.

The authority sends full entity/component projections. The digest covers the exact UTF-8 `projection_json` bytes, not a client reserialization, rendering output, presentation events or the complete authoritative WorldSnapshot. `sync_json` preserves integer metadata through Godot JSON; the client verifies the received state and echoes that exact stamp. Missing `session.projection.v1` support is rejected during compatibility negotiation. Arbitrary world semantic capabilities remain separate from this protocol capability registry.

A syncing bridge retains one baseline, with no delta backlog. If a verified baseline is already behind the authority, the bridge replaces it with the current full projection and remains fenced. An acknowledgement with a mismatched digest, tick, epoch, ID or generation cannot activate it. `LateJoinHandler` certifies the zero-history catch-up case once the current full projection is acknowledged. A sequence gap or corrupt projection triggers explicit resync; the client discards stale updates and requests a full replacement. An unacknowledged baseline expires after five seconds. Clients unable to catch the current tick remain fenced; this checkpoint does not certify high-latency catch-up performance. Existing ready players continue while a joining/recovering peer is fenced. A session with no ready players pauses simulation.

Reconnect uses a rotated opaque credential returned by each accepted handshake and an increasing connection generation. The original ticket and previous reconnect token are spent. Only a disconnected peer may reconnect, and it must still map to the same canonical player entity. Disconnect clears that peer's buffered future inputs and sequence history; peer rate windows survive to prevent reconnect-based flood bypass. Same-connection resync clears buffered input while preserving anti-replay sequence history. Losing the newly rotated credential before receiving the ACK fails closed; durable redemption/recovery policy belongs to XP-014.

The Godot Player verifies state before applying it, restores full entity/component state (including removal of absent entities), and reconnects with the retained credential. It sends inputs only for the authority's verified-tick requests. Paused runtime sessions continue pumping network synchronization, and a requested single step survives an input-wait retry.

Files and boundaries:

- `packages/runtime-core/src/session_projection.rs`: typed versioned `ProjectionStamp` and `ProjectionControl` (`baseline_ack`, `resync_request`).
- `packages/runtime-core/src/engine_bridge.rs`: bounded projection/ack state, full-baseline messages, timeout and input fencing.
- `packages/runtime-core/src/live_session.rs`: credential rotation, generation and stable player binding.
- `packages/runtime-core/src/runtime_orchestrator.rs`, `runtime_cli.rs`: tick-boundary membership, empty-session pause, input cleanup and paused pumping.
- `packages/network-core/src/input/{input_buffer,input_synchroniser,malicious_input_gate}.rs`: peer-scoped buffered-input and sequence cleanup.
- `packages/core/src/wire/session_contract.rs`: negotiated `session.projection.v1` protocol capability; no mechanic-specific semantic vocabulary.
- `adapters/godot/{xace_transport,xace_protocol,xace_adapter,xace_entity_manager}.gd`, `apps/xace-player/player.gd`: validation, exact full restoration, recovery and reconnect presentation path.
- `tools/xp013_socket_proof.py`, `tools/xp013_projection_proof.gd`: real two-client acceptance and client-side stale/gap/corruption checks. XP-011/012 proof clients now acknowledge baselines.

Verification:

- 705 runtime-core library tests, 7 network-core library tests and 8 shared session-contract tests pass.
- Two real clients: join at tick 1, delay ACK while the existing player reaches tick 2, then activate from the current projection. Bad digest acknowledgement is rejected.
- Disconnect/reconnect: assigned entity is preserved; generation advances to 2 at tick 4. Spent credentials and old-generation acknowledgements are rejected.
- Recovery: a missing update is replaced by a full projection at next tick 6 with the authority's exact projection digest. A dropped baseline times out; the other player completes tick 6.
- Godot client proof: old generation/baseline, sequence gap and corrupt projection never overwrite verified state; valid replacement recovers.
- All 13 XP-011 admission scenarios and all 6 XP-012 input/ordering/flood/fragmentation/timeout scenarios pass.
- Freshly staged Godot Player: five ticks, five inputs, zero errors.

See [machine-readable evidence](evidence/xp013-baseline.json) and [protocol decision](adr/XP-013-session-projections.md). Full snapshots are intentional; live delta compression is not introduced. XP-014 owns invitation, acquisition and remote join product flow; XP-015 owns remote deployment/network conditions; XP-017 owns running cross-engine clients. XP-010 clean-machine acceptance remains pending by explicit owner instruction. No additional mechanic or privileged wall-run concept was introduced.

# XP-012 — authenticated input admission and tick pacing

Status: implemented and verified for the local Windows live-bridge profile on 2026-10-01.

The authority binds each one-use session grant to one distinct HUMAN controller and canonical player entity. Up to four controllers can be declared with matching lockstep peer IDs. The first ticket keeps the XP-011 path; later tickets use `<stem>.peerN.<extension>`. Admitted peers become required lockstep members only after verified handshake. A spent grant cannot rejoin; reconnect and current-tick baselines are XP-013 work.

Each live input must match its connection's peer and assigned player. Generic optional action target entities are checked against `AuthorityResolver`. `MaliciousInputGate` applies packet structure, sequence/replay, future-tick, action, prediction and per-peer rate policy before `InputSynchroniser` can release a packet. Live action values are quantized to the 1/1024 grid before admission, gameplay projection and durable `input_validation` recording. An empty action list is an explicit idle input. Invalid, duplicate, stale and future packets never reach mutation staging.

The authority sends a typed `input_tick_request` after admission and after each snapshot. The Player sends exactly one input packet per request, including idle ticks. The socket reader preserves fragmented frames across nonblocking reads, caps a frame at 4 MiB, and budgets 64 KiB and 64 parsed frames per pump. The handshake has a 1.5-second whole-frame deadline. The per-connection input queue is bounded and rejects overflow without evicting previously accepted packets. Live presentation-client feedback is rejected before the authoritative feedback buffer.

A required peer that provides no input for five seconds receives `input_timeout`; the authority records the membership removal and releases lockstep without fabricating that peer's input. Connection admission failure on the live acceptor is isolated to that socket. Feedback drains once at the start of a tick that is actually ready to execute, so lockstep retries do not reprocess the same feedback.

The wire and runtime additions are generic entity, controller, peer, input, tick and feedback mechanisms. They contain no reference-mechanic or genre branch. The existing reference arena supplied two human actor IDs only as proof data.

Verification on this workspace:

- `cargo test -p xace-network-core -p xace-runtime-core --lib --quiet`: 6 network-core and 704 runtime-core tests pass.
- `tools/xp012_socket_proof.py` against a freshly staged package: two players drive actor IDs 3 and 4 independently; reversed packet arrival and a 0.5003 quantization probe yield the same two-tick canonical entity digest; forged peer/player/action target, stale/duplicate and future inputs are rejected; a flood receives ten rate rejections without changing the first-tick digest; fragmented handshake/input frames pass; two empty-action input ticks advance; an incomplete handshake is rejected after the deadline and a valid client is then admitted; a silent input peer is disconnected and logged after 5.00 seconds. See [XP-012 evidence](evidence/xp012-baseline.json).
- Final XP-011 twelve-scenario real-socket admission regression passes. The staged Godot Player runs five requested-input ticks with five input packets and no errors.

This is a local Windows transport/profile result. XP-013 still owns current-tick baselines, late join, reconnect and resync. XP-017 owns running cross-engine play; XP-010 clean-machine launch remains pending by explicit owner instruction.

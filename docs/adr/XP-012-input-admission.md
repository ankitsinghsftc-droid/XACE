# XP-012 input admission decision

The live bridge remains an engine-neutral presentation transport. Each admitted socket has a peer grant and one canonical player entity. A packet carrying a different peer/player is dropped before ingress; a targeted action requires explicit authority for that entity. The authority cannot infer gameplay meaning from action names.

`InputTickRequest { msg_type: "input_tick_request", protocol_version: 1, tick }` is the authority's pacing signal. An empty action list is a valid response. The Player sends only on this signal. The authority asks for tick zero immediately after admission and the next tick after each published snapshot; a late admission asks for the authority's current tick, while XP-013 will add a proper current-tick baseline before supporting late join as a product path.

The live admission gate uses the existing network-core `MaliciousInputGate`, `CheatGuard`, `AuthorityResolver` and `InputSynchroniser`. Values are normalized to [-1, 1] by packet validation and quantized to increments of 1/1024 before the gate. This fixed grid is part of the current local profile's runtime semantics and accepted input log. Rejected packets are recorded separately from accepted quantized packets. A one-use grant stays spent after disconnect.

The transport reads frames incrementally with a 4 MiB maximum and per-pump byte/message budgets. A handshake must complete within 1.5 seconds total. The bounded input queue rejects new traffic at capacity. The host waits up to five seconds for a required peer's numbered input, then sends a disconnect, records a membership removal, and stops requiring that peer. It never inserts an invented idle packet. A sender can intentionally supply an empty idle packet to advance normally.

The local proof runs two sockets against one authority and one package, and includes malformed ownership, replay, future, rate, fragmentation, idle, and timeout cases. Cross-engine visual adapters, late-join baselines, reconnect generations and remote invites remain later tasks.

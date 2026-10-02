# XP-011 live session admission

Status: implemented and locally verified, 2026-10-01.

The authority constructs one canonical `SessionContract` from the verified package
manifest and actual loaded CGS, persisted SGC plan and compiled world. Its session
and authority-incarnation UUIDs change per launch; epoch begins at zero. A local
launch secret is generated before the runtime starts and is carried separately from
the presentation package. The client sends the canonical serialized `SessionOffer` and grant credential
in its first handshake. The offer travels as an opaque JSON string because Godot's
JSON parser otherwise converts integer version fields to floating-point values. The runtime compares with `compare_session`, using its own
trusted certified adapter set. CGS, SGC, world, playable package, input and runtime
identities are exact; the presentation manifest is negotiated, not part of gameplay
identity. A rejected offer never creates a bridge, player assignment or required
input member. The adapter and runtime share only the versioned wire data, no engine
specific gameplay noun.

The live controller maps a verified grant to one peer and canonical player entity.
Membership is recorded only after all checks succeed. Records are append-only,
ordered and persisted from launch; input record append occurs before input enters
authoritative ingress. File/log failure fails closed. The active connection, not
packet `peer_id`, decides ownership. XP-012 will add adversarial input pacing,
sequence/rate handling and reconnect policy.

Legacy authoring preview can still use the old handshake only when no gameplay
session was requested. XP-010 Player requests the strict gameplay session path.

The local Player launch writes a one-use grant ticket atomically outside the package.
It removes the ticket after reading it. The runtime records start before publishing
the ticket, then records admission/rejection, accepted input before ingress, and
departure. A disconnect removes the peer from the live `SessionManager` and the
required lockstep set. The current profile issues one grant to one controller; the
multi-player admission/pacing work is XP-012/XP-013.

The authority verifies every file listed by the playable manifest and compares the
loaded CGS, SGC plan and compiled world with package identities. The actual running
executable hash must match the packaged runtime digest. The session runtime artifact
hash is a semantic ABI/executor projection, while the executable hash is a separate
load-time gate. World semantic capability names come from ordinary v3 object data.

The real-socket matrix and exported Player proof are recorded in
`docs/XP011_COMPLETION.md` and `docs/evidence/xp011-baseline.json`. The socket
Unity case certifies compatibility negotiation for a Unity-shaped client identity
and different presentation manifest, not a running Unity build. XP-017 covers
cross-engine play.

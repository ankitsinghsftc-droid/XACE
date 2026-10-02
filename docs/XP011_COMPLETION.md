# XP-011 implementation record — 2026-10-01

**Implemented and verified for the local Windows Player/live bridge profile.** XP-010's clean-machine acceptance remains pending by owner instruction. XP-012 has not started.

The runtime now derives a typed `SessionContract` from the verified playable package and the CGS, persisted SGC plan, compiled World Contract v3, input proof, registered executor identity and actual packaged runtime executable. Every launch receives fresh session and authority-incarnation UUIDs at ruleset epoch zero. A one-use local grant binds a controller to exactly one canonical human player entity. The Player sends the canonical offer JSON and grant at the first bridge handshake; the authority applies the shared `compare_session` rules before creating a bridge, player membership or required lockstep peer.

The package gameplay identity is exact. The presentation manifest hash is negotiated separately, so changing native visuals does not alter the ruleset. A claimed adapter must be in the authority's certified set and match the outer bridge handshake. Inputs must match the admitted connection's peer and player IDs; a validated input is durably appended before entering authoritative ingress. Start, admitted/rejected membership, inputs and departure are append-only records. A record failure stops admission/input or fails the tick. The temporary grant ticket is atomically published outside the package and removed by the Player after reading it. Legacy authoring previews still use the separate non-live handshake identity.

No gameplay noun or reference mechanic branch was added. World capability names stay versioned data; the socket/runtime code only sees generic artifact, capability, player and input identities.

Verification:

- Runtime-core library: 704 tests passed. Shared core session vectors: 8 tests passed, including 50 compatibility cases. Network-core library: 6 tests passed.
- Twelve real TCP scenarios passed: accepted Godot and Unity-shaped visual variants; rejection of wrong grant, absent offer, adapter claim mismatch, and stale CGS, plan, world, input, runtime, epoch and authority incarnation. Rejected attempts had no admitted membership or input record. The accepted cases recorded one valid input and dropped a spoofed peer input.
- The exported Godot Player with a freshly packaged native host ran 30 ticks and sent 30 inputs under a restricted System32-only child PATH. Its log contains start, admission, 30 inputs and departure, with no grant ticket left on disk. See [XP-011 evidence](evidence/xp011-baseline.json).

The Unity acceptance case exercises its certified wire identity and a different presentation hash through a real TCP connection; it is not a claim of a running Unity build. Actual cross-engine play is XP-017. Multi-player adversarial pacing, reconnect, sequence/rate policy and unauthorized feedback handling remain XP-012/XP-013. The XP-010 clean Windows machine launch remains untested as requested.

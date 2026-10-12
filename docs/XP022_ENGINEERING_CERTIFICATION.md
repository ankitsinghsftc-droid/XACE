> Reconstructed historical document. The ORIGINAL XP022 SEAL AND EVIDENCE ARE MISSING. Historical passing claims below are not fresh recovery certification. See AGENT_PROGRESS.md. Never reuse disposable paths for new unique evidence.

# XP-022 final-candidate engineering certification — 2026-10-08

Scope: Windows 11 x64 on the recorded development machine; actual exported Player,
Unity 6000.4.9f1, Godot 4.6.3 and Unreal 5.7.4; loopback and local TLS relay.
This report supersedes the earlier missing-local-evidence list in XP022_CLOSEOUT.md.
External acceptance remains OPEN under the proposed `XP022_RELEASE_GATES.md`
amendment, which requires owner approval before declaring engineering completion.
NEC has not started. No commit, push or protected-ref change is authorized here.

## Candidate identity and packaging correction

Every new runtime process uses the soak-certified production host SHA-256
`09825d6ebcc914a84dd0f3fb8000f0f3fbee3ec5810cfb1cc388a1466773cbe6`.
All production runtime, Player and adapter source bytes were compared against the
2026-10-08 soak-closeout source inventory and are unchanged. Test tools and
packaging preparation changed; no mechanic or gameplay concept entered core.

The first normal distribution correctly failed admission because previous fixture
staging had included Godot-generated `sound.wav.import`. Staging now excludes
generated import metadata, and export copies only the sealed manifest inventory.
The corrected package retains the exact runtime and gameplay identity. The normal
Player resource pack and release launcher/relay have their own hashes; they are
not misrepresented as the instrumented soak Player's resource pack. Both failed
attempts and corrected results remain under `target/xp022/final-certification/`.

The launch collision fixture now reserves the same loopback address used by its
launcher. Cold-editor startup allowance is 300 seconds; gameplay/network timeouts
are unchanged. Unity's missing contract-test entrypoint was staged before the
final installed-host rerun. None of these changes weakens runtime validation.

## Proof ladder

| Proof | Current candidate evidence |
| --- | --- |
| A — Local Player | `player-input/proof.json`: real physical-key collector, 30/144-FPS identical input/projections, focus handling, visible freeze on runtime loss, direct launch, tamper refusal, owned cleanup. `launch-v3/proof.json`: normal release lifecycle with developer tools removed from child PATH. Clean machine remains REL-01. |
| B — World Contract | `native-v2/{godot,unity,unreal}.json`: all 15 shared accept/drop/recover/reject vectors in actual installed hosts, coordinate/geometry/normal and authority fencing checks. Eight world-extensibility tests pass arbitrary semantic nouns and capabilities. |
| C — Invite | `invite-v2/proof.json` and `relay/proof.json`: actual two-Player package acquisition, owned actors, verified membership, token expiry/replay, TLS refusals, tunnel reconnect/outage and cleanup. Two machines/public deployment remain REL-02/03. |
| D/E — Mixed and three-engine session | `hosts-final/proof.json`: Player/Godot pair and Unity/Godot/Unreal/Player together; distinct ownership, matching applied projections/events, cross-owner state change, wrong-world refusal and coherent survivors after a departure. |
| F — Live activation | Final host pair/four proofs bind old epoch through tick 7 and new epoch at 8; observable fixture change at 9; joins around 7/8/9; normal durable restart refusal. Production process tests add crash-before/crash-after decision, idempotent duplicate prepare, corrupt staged data and unsupported migration refusal. |
| G — Replay/debug | Final four-host recording independently verifies before/at/after activation, repeat and rewind. `debugger/proof.json` verifies the actual browser event/state/dependency view, export, live fork and guest/creator boundaries using the same host. Live capture at tick >256 also exercises the segmented recorder's current tail. Completed two-hour archive separately verifies all 202,271 ticks across 791 segments. |
| H — Fault matrix | Detailed mapping below; actual production processes/sockets plus native reader vectors. Precise internal failpoints are explicitly supplemental. |

## Fault matrix

| Case | Explicit outcome and evidence |
| --- | --- |
| Stale CGS/plan/world/input/runtime/epoch/incarnation | Rejected before membership/input: `admission-final/proof.json`. |
| Incompatible client/wire protocol; wrong adapter claim; missing required capability | Explicit admission rejection in the same final admission suite. |
| Unauthorized owner, duplicate/future/stale/flooded inputs | Rejected or bounded by production input gate: `sockets/xp012_socket_proof/proof.json`. |
| Dropped baseline/update, stale generation, arrival-order reversal | Verified recovery/fencing or unchanged canonical result: XP012/013 socket proofs; native sequence-gap/stale-message vectors. These are application-message faults over real TCP, not a claim that TCP delivers reordered bytes. |
| Disconnect/rejoin and slow handshake/input | Same owned identity on reconnect, incomplete clients fenced within configured deadlines; XP012/013 and exported-Player invite/relay proofs. |
| Rejected mutation or unsupported migration | Incorrect approval rejected without live change; valid changed-world candidate refused because no migration hook exists; `process-faults-final/proof.json`. |
| Staged data changes after validation | Activation aborts at N, old epoch continues without partial new output; same process proof. |
| Joins N-1/N/N+1 | Prepare fence or complete compatible new epoch; `hosts-final/pair/join-boundaries.json`. |
| Crash before commit | Production authority killed while prepared but undecided; fresh session credentials with retained journal reopen parent without activation. Same old session credentials are not reused. |
| Crash after commit | Production authority killed after published decision; restart with retained journal refuses parent and visibly halts. No automatic crash-session resume is claimed. |
| Missing/corrupt/truncated replay, invalid seek | Exact production verifier rejects; `replay-faults/report.json`. Its subset `certified:false` is intentional, not a failing replay case. |
| Missing binding/required geometry; optional cosmetic missing; tampered data | Explicit refusal or verified cosmetic fallback; `presentation/proof.json`. |
| Token expiry/replay | Actual elapsed relay capability expiry and host expiry, spent-token refusal and expired invite refusal; `relay/proof.json`, invite/recovery proofs. |
| Partial package transfer | Proxy closes a real file response mid-frame; join fails, no Player starts and cache is removed; `invite-v2/proof.json`. |
| Slow consumer/backpressure | Non-reading client requests 4,000 recovery frames; fenced, memory under budget, healthy second peer advances. Relay additionally enforces 16 sessions, two lease connections, frame bound and 8 MiB traffic cutoff. |
| Launcher/Player crash, normal shutdown | Owned process tree stops; unrelated sentinel stays alive; `launch-v3/proof.json` and Player proof. |

Supplemental exact-source test build: 23 reference-package tests pass, including
activation failpoints during isolated migration, before decision, after decision
and before broadcast. This build enables `activation-fault-injection`; it is not
the shipped binary. Black-box production kills certify observable pre/post durable
decision behavior, not sub-instruction kill timing. A world/state migration without
a proven hook remains deliberately unsupported and is tested as a rejection.

## Performance, retention and installation boundary

The completed independent soak uses the unchanged host: 7,200.860 seconds,
202,271 successful ticks, p95 authority work 12.0662 ms and peak sampled authority
private memory 60.49 MiB. It includes two activations and a reconnect. The full
archive is approximately 2.88 GB; recording uses bounded segments and a 32 GiB
quota rather than unbounded RAM. Quota exhaustion is not advertised as infinite
recording support. No new two-hour run is needed for test-tool/package-metadata
changes that leave production simulation bytes and gameplay identity unchanged.

Separate short rendered local measurement at a 30-FPS cap: frame-interval p95
33.401 ms (60 samples), input-send to applied-tick p95 35.106 ms (30 samples).
These include frame scheduling and are not GPU duration or Internet latency.
The soak does not demonstrate sustained 60 wall-clock ticks/sec. Hardware is an
i7-12650HX, approximately 16 GiB RAM, RTX 4050 Laptop/Intel UHD, Windows 11 build
26200; exact driver versions are in `hardware.json`.

Normal unsigned packaging includes verified runtime/package/Player inventory,
Godot and Rust notices, README, manifest/trust hashes and ZIP. All inventory bytes
must match at final evidence sealing. Signature authenticity, clean-machine
behavior and human usability are explicitly reserved for REL-01/04/05.

## Handoff decision

Local gates pass. Source, unsigned distribution and relay bytes are sealed for
engineering review in `target/xp022/engineering-baseline-20261008/`, bound by
`docs/evidence/xp022-engineering-candidate.json`. The immutable manifest contains
the source revision plus full working-tree digest; the Git revision alone does
not describe the uncommitted implementation. No protected Git ref is changed.
The engineering/release amendment remains proposed until the owner approves it.
With all local checks passing and that amendment approved, this sealed profile is
eligible for formal engineering handoff to NEC-001. Without approval, the
original combined XP-022 status remains open. Do not start NEC automatically.

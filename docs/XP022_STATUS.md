> Reconstructed historical document. The ORIGINAL XP022 SEAL AND EVIDENCE ARE MISSING. Historical passing claims below are not fresh recovery certification. See AGENT_PROGRESS.md. Never reuse disposable paths for new unique evidence.

# XP-022 — certification in progress, release not certified

Final-candidate update (2026-10-08): **local engineering gates PASS**. Read
`XP022_ENGINEERING_CERTIFICATION.md` and `evidence/xp022-engineering-candidate.json`
for the final production-binary fault, installed-host A-H, packaging and baseline
evidence. The original release acceptance remains open. The proposed REL-01 through
REL-05 separation in `XP022_RELEASE_GATES.md` awaits owner approval. NEC is not
started. The historical blocker sections below are retained, not current failures.

2026-10-04. Work remains in the isolated `target/xp016-work` worktree.
No protected branch update, commit or push is part of this task.

## Latest follow-up — 2026-10-08

Closeout review: **two-hour soak and full archived replay PASSED; XP-022 remains
IN PROGRESS**. The completed run contains 202,271 ticks in 7,200.860 seconds,
791 verified replay segments and 12.0662 ms p95 authority time. See
`XP022_CLOSEOUT.md` for the criterion-by-criterion decision and
`evidence/xp022-closeout-20261008.json` for the retained evidence fingerprints.

The initial blocker list below is historical. Implemented since then: ordered
input-log append avoids rebuilding the entire chain; live sessions avoid a
duplicate full-session input log in RAM; session JSON is serialized before writing;
timeline prefix pruning preserves the valid latest-snapshot cache. Live replay
rotates into durable 256-tick segments with chained index and completion marker.
Live diagnostic hashes/traces/schedules/feedback/action counters retain a bounded
window. The archive verifier checks every segment, replay and snapshot continuity.
The Player reconnect check now uses its validated current transport epoch.
Missing cosmetics explicitly declared optional by a verified descriptor are
accepted; required or tampered package data still fails. The full presentation
regression passed, including the formerly open missing-cosmetic case.

The independent run `target/xp022/independent-20261008-003743` **failed** at tick
24,747 after 971.6 seconds. The reference actor left portable world bounds because
the short golden input recording was repeated indefinitely with net displacement.
The explicit fatal halt preserved the runtime bounds invariant. Successful ticks
had p95 15.0235 ms and maximum sampled private memory 51.39 MiB.

The corrected soak uses nonempty, owned, 60-frame forward/back input routes with
distinct small speeds and no net displacement or overlapping paths. Reference
mechanic golden jump/effect proofs remain separate and unchanged. The new Rust
regression executes 50,040 ticks in each direction under the two reference rulesets
and checks bounded positions and zero accumulated horizontal displacement.

The standalone supervisor now verifies the entire archived replay after a passing
two-hour run and records a final result independently of this conversation. The
Player `.pck` is hashed as well as its executable. The replacement run
`target/xp022/independent-fixed-20261008-042759` passed, closing the local
headless four-Player endurance/replay gate. External acceptance deferrals remain
explicit. Full fault and final pinned packaging/A-H evidence are still incomplete.

## Implemented

`tools/xp022_certification.py` retains revision, working-tree file digest manifest,
binary and input hashes, exact commands, process output and explicit pending gates.
It runs real offline runtime processes for valid replay, corrupt digest, truncated
transfer, missing recording and out-of-range seek. Optional `--package` reruns the
existing actual TCP ownership/ordering/flood and reconnect/recovery probes.
Exit 2 means the subset passed but certification remains incomplete; exit 1 means
a subset failure. Neither result constitutes release approval.

`tools/xp022_session_probe.py` starts one real authority and four TCP protocol
clients. It checks every applied projection, samples Windows process private
memory/working set, retains hashes and checks normal authority exit. These clients
are protocol probes, not four native engine hosts. Its manually stepped duration
and empty inputs are explicitly recorded; it is not the two-hour realtime soak.

The optional runtime CLI `--tick-metrics-out PATH` creates a new JSONL file and
streams timing samples without accumulating them in memory. Each successful
`runtime.tick()` records its tick, duration and world hash. The duration includes
bridge sends and excludes CLI pacing, paused control handling and failed input-wait
attempts. Clock readings never enter state, scheduling decisions or replay hashes.
The preflight's `--tick-metrics` reports this separately from end-to-end step time.

## Retained local evidence

- `target/xp022/current-faults/report.json`: five replay process cases plus actual
  XP012/013 socket runners passed against the freshly staged package. Ownership
  forgery, duplicate flooding, input arrival order, slow handshake, late join,
  spent reconnect token, stale acknowledgement and dropped baseline are covered.
  This is not complete Proof H coverage; TCP packet-level reordering, all crashes,
  expiry and slow-consumer backpressure still require their distinct evidence.
- `target/xp022/four-host-result.json`: actual Unity 6000.4.9f1, Godot 4.6.3,
  Unreal 5.7.4 and exported Player share matching projections/events and activation
  at tick 8. Forty ticks, Player departure after 19, survivors through 39.
- `target/xp022/session-preflight/report.json`: 600 ticks, matching four-client
  projections and normal authority exit. Private bytes rose from 2,170,880 to
  46,219,264; end-to-end step p95 was 110 ms. This is a development binary and
  manually stepped measurement, not the authority-only production performance gate.
- `target/xp022/timed-preflight/report.json`: instrumented development build,
  600 ticks, authority `runtime.tick()` p95 **77.6461 ms** including bridge sends;
  the 16.7 ms target fails in this profile. End-to-end p95 125 ms. Private bytes
  rose from 1,822,720 to 45,756,416. All 600 projection digests match the run
  without instrumentation; authority exited normally. All 842 runtime tests pass.
  `docs/evidence/xp022-checkpoint.json` binds these retained reports by SHA-256.

Historical and newer instrumented binaries have different hashes. Preserve their
packages and pair each replay with the exact host that recorded it. Earlier passes
must not be silently attributed to a later executable.

## Historical initial blockers (superseded by XP022_CLOSEOUT.md)

1. Bound long-session storage before the full soak. `epoch_replay.rs` retains full
   state/events/schedule per tick in memory and stops at 100,000 ticks (27.8 minutes
   at 60 Hz). `runtime_orchestrator.rs` also appends schedule snapshots and replay
   traces; determinism guard retains its tick hash map. A larger tick limit alone
   is not a fix. Durable, bounded replay storage must preserve exact historical
   artifacts, activations, seek and debugging semantics; diagnostics need explicit
   retention. The measured growth means a two-hour certification claim is refused.
2. Complete the real-process fault matrix, including crash boundaries and slow
   clients; retain explicit rejects/fences and prove bounded queues and cleanup.
3. Run two actual wall-clock hours with four native clients, mutations and rejoins
   after retention is fixed. Record hardware, production build settings, authority
   p95 (<16.7 ms target), render/latency separately, and memory/queue budgets.
4. Rerun A–H from the final pinned binaries, packaging/notices/compatibility checks,
   including the earlier missing-cosmetic regression. No universal engine, OS or
   asset claim follows from the tested Windows profile.
5. Clean-machine, second-machine and public two-network tests remain pending per
   the user's earlier instructions. Signing certificate and three first-time
   testers are unavailable; user explicitly requested recording both as pending.
   No signed release or human usability trial is claimed.

Wall traversal remains a reference package assertion in the existing proof runner.
The certification, instrumentation and socket preflight contain no gameplay rules.

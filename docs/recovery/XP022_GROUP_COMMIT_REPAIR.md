# XP022 recovery performance repair

The original engineering receipt survives, but rebuilt recovery binaries require fresh evidence. The diagnostic recovery run completed 182,002 ticks in two hours with no stall warnings, but authority p95 was18.8007ms against16.7ms. Its entire711-segment archive independently verified. This does not convert its performance failure into a pass.

Median authority work was7.0361ms. Inbound processing averaged3.4892ms and input scheduling3.4789ms, versus simulation0.5002ms. Both input stages include per-record synchronous journal durability. These measurements identify a performance target; they do not prove the earlier intermittent freeze's cause.

The repair groups input-validation records from a single ingress pass into one ordered JSONL write and one sync_data barrier. The barrier remains before lockstep release and gameplay application. Raw-input admission, membership, activation decisions and replay-segment durability are unchanged. Every validation result is retained in the original order. Write or flush failure returns an error before release. No liveness or performance threshold is relaxed, and no nondeterministic value enters simulation.

This is a new recovery repair, not a claim that the original source contained group commit.845 runtime tests passed, including ordered-batch and injected write/flush-failure checks. Real-process and endurance results are recorded separately. The earlier missing-input/freeze issue remains unresolved until evidence supports a cause or fix.

The background supervisor now independently verifies any successfully completed full-duration recording, even if performance fails. Overall acceptance still requires both performance and archive verification.

Original repositories, recovered receipts, pinned historical reconstruction binaries and failed-run evidence remain untouched. All checkpoints are currently only on the laptop SSD.

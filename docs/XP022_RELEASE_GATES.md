> Reconstructed historical document. The ORIGINAL XP022 SEAL AND EVIDENCE ARE MISSING. Historical passing claims below are not fresh recovery certification. See AGENT_PROGRESS.md. Never reuse disposable paths for new unique evidence.

# Proposed XP-022 engineering/release separation — 2026-10-08

Status: **PROPOSED; awaiting owner approval.** No gate below has passed.
This amendment does not change test thresholds, runtime behavior or fault outcomes.
It separates an evidence-bound Windows engineering handoff from external release
acceptance. NEC-001 is not started by accepting or recording this proposal.

Proposed XP-022 engineering completion requires the final pinned production runtime,
normal unsigned distribution, installed native-host A-H profile, fault outcomes,
bounded two-hour soak, replay verification and packaging/lifecycle checks to pass.
Precise internal activation failure injection remains supplemental test-build
evidence; it is never relabeled as a production-executable injection. Unsupported
state/world migration must fail closed. The supported Windows profile is not a
claim of arbitrary engine versions, Internet deployment or clean-machine support.

The following gates remain OPEN in a separate release ledger. Existing XP010,
XP014 and XP015 external deferrals map here without being changed to passes.

| Gate | Required before | Evidence still required | Completed locally now |
| --- | --- | --- | --- |
| REL-01 — Clean Windows installation | External pre-alpha distribution claiming clean Windows support | Fresh supported Windows 10/11 x64 machine/VM without engine editors, Cargo, Python or Node; OS/GPU/driver identity; exact release/checksum; download/extract/Play/close; repeat launch, path/port failure recovery, uninstall/update behavior where supported; logs, screenshots and process-cleanup results. Record actual SmartScreen/AV behavior. No repository, SDK, preexisting install cache or trust shortcut. | Relocated distribution, tools removed from child PATH, integrity checks, port collision, access-denied recovery, stale-install repair and owned-process cleanup pass on the development machine. This is not a clean-machine test. |
| REL-02 — Two-machine LAN | External multi-user pre-alpha LAN claim | Two distinct Windows computers on a reachable LAN; exact host/friend distributions; ordinary Play/Invite/Join; distinct owned actors, matching session/epoch and projections, disconnect/rejoin, leave/end cleanup; packet/application timing, machine and network descriptions. | Two exported Players, one authority, actual loopback invite/acquisition/rejoin and cleanup. |
| REL-03 — Public relay and two networks | Internet pre-alpha multiplayer claim | Deployed relay with documented server/operator configuration and valid TLS chain; two separate ordinary Internet connections/NATs; exact relay/Player identities; invite/package/gameplay traffic, latency, loss/reconnect/outage, expiry/replay rejection and cleanup; deployment/security/availability limits. Do not expose operator tokens or private keys in evidence. | Actual local TLS1.3 relay, certificate refusals, capability expiry, replay refusal, connection/session/traffic limits, tunnel loss recovery and relay outage fencing. Test certificates are not deployment certificates. |
| REL-04 — Signed distribution | Public pre-release claiming publisher-authenticated Windows binaries | Authorized code-signing certificate/service; signing and timestamp transcript; valid Authenticode chain and publisher identity on all required shipped executables; post-sign package/runtime/distribution hashes and trust metadata regenerated consistently; repeat admission/launch/integrity tests and record SmartScreen outcome on clean Windows. Signing changes bytes: unsigned hashes cannot be reused as signed evidence. Keys/passwords stay outside the repository. | Unsigned release with complete Godot/Rust notices, README, sealed distribution inventory, content hashes, trusted-launcher checksum and package integrity tests. Hash integrity is not publisher authentication. |
| REL-05 — Three first-time testers | External pre-alpha usability acceptance | Three actual first-time people independently complete Play/Invite/Join/approve without terminal help; exact build, task script, consented observations, completion times, errors, assistance and outcome per person; record blockers and fixes, then rerun affected tasks. Automated agents and experienced developer walkthroughs do not substitute. | Automated exported-Player, native launcher and actual browser debugger/approval-boundary walkthroughs. |

Practical limits: the owner reports no clean machine, second machine, hosting/two
networks, code-signing certificate or first-time testers. The clean-machine trial
is explicitly deferred to later. No external resource is presumed available or
simulated to close these gates. No new account, certificate purchase, deployment
or invitation to others is authorized by this amendment.

If approved and local gates pass, use the precise status **XP-022 ENGINEERING
COMPLETE — EXTERNAL RELEASE GATES OPEN**. A handoff may reference that frozen
baseline; it must not say the original full public-release acceptance has passed.
Until approval, the original combined roadmap item remains open. A technical
baseline may be sealed for review, but is not declared a release-certified or
formally approved handoff baseline. The broad eight-hour commercial soak remains its separate
existing release-program obligation.

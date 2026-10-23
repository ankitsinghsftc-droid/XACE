# NEC-012 shared native host acceptance

Status: COMPLETE for the shared Windows host contract (2026-10-24); external release certification remains open. Entry: cec01a1be78fa00c084f881363f8fd44f1464444 (NEC-011).

The shipped implementation belongs to packages/player-launcher in Rust. Reuse the existing runtime protocol, process ownership job, package verification and install activation; do not create an alternative gameplay/session authority. Python is creator/proof tooling only. Native editor/build integrations remain NEC-013 through NEC-015.

Required closeout evidence:

- Trusted creator executor receipt and common engine release receipt pin executable, package, resources, capabilities, backend/numeric/state/replay identities. Reject stale or incompatible identity before spawning. Receipt trust is supplied out-of-band, never self-authorized by downloaded content.
- Shared owned-process lifecycle with local-only offline admission and readiness, no development control endpoint, repeated Play/Stop, collision, startup failure, crash and host EOF proofs. Existing Player lifecycle parity must pass. Authority loss stops/freezes; no native gameplay fallback.
- Relocated unusual-mechanic release executes, checkpoints and replays with no player compiler or Builder. Preserve exact declared profile boundaries.
- Stable per-user/per-game save location outside installs/cache; compatible restore or deterministic migration/non-destructive refusal. Never overwrite an incompatible original save.
- Validate release update before activation; failure retains working release and saves. Readiness failure cannot advance active identity.
- Focused Rust/Python, actual native process and affected Player regression evidence; source identities and recovered XP-022 seal integrity. External clean-machine/signing/tester/networking gates remain open.

Entry findings: existing Player session::Host already owns a runtime Job and disables the development control endpoint, but its launch construction is private and coupled to Player invitations. distribution::verified pins Player payload bytes and activation occurs after readiness. Neither is yet a common native release/executor/save contract. NEC-011 receipts and benchmarks are creator-side evidence, not proof of this new shipping service.


Closeout: docs/evidence/nec012-completion-20261024/summary.json and audit.json bind the tested checkout bytes, Git source blobs and preserved launcher binary. Source checkpoint b59b8b8. All required shared-service proofs pass:513 Python regressions,11 Rust tests,19 lifecycle checks, actual Player parity, three engine-protocol authoritative ticks, valid update/failed readiness/explicit rollback, and relocated custom graph checkpoint/replay. Exact supported behavior and downstream integration obligations are in NEC012_NATIVE_HOST_CONTRACT.md. No previous acceptance criterion or external release gate is removed. NEC013 is not started.

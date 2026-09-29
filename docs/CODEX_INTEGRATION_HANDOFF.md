# Codex integration completion gate (AG-030)

Status (2026-09-23): AG-030 complete for the declared development/early-user
configuration. All six final aggregate gates passed; source-bound evidence and
explicit product-owner risk acceptance validated, with no blockers.
`codex_integration_complete: true`; `decision: complete_for_declared_configuration`. No public-production
support or whole-XACE launch approval is implied. Exact transport, version,
experimental/config dependencies and failure impacts are documented in
[the App Server surface verification](CODEX_APP_SERVER_SURFACE.md).
[Saved completion report](evidence/codex-ag030-completion.json).

## Supported configuration and setup

The declared configuration is Windows x64, local Docker Desktop with WSL 2 /
Linux containers, official pinned Codex 0.155.1, and a ChatGPT account for which
Codex reports an entitlement. The actual opted-in account passed live tests.
No universal account/model, native Windows, macOS or Linux-host claim is made.
Claude/Local are deferred and not completion dependencies.

Follow [the current setup guide](CODEX_DOCKER_BACKEND.md). After installing the
documented Docker/WSL prerequisites, users can download the official pinned
archive from Builder, paste its absolute local path, confirm and click
**Build / repair isolated runtime**. No npm/global CLI or developer terminal
command is required. XACE verifies the copied bytes and fixed recipe, builds
locally from the pinned base, and atomically selects the immutable image.
There is no automatic public bundling, redistribution or silent version update.

Provider device-code authentication, model/account discovery and prompt entry
remain in Builder. Restart/resume, preview approval/rejection, cancellation,
outage recovery and provider-managed usage are supported. Dependencies missing,
an invalid runtime, account restrictions or quota exhaustion never trigger an
unsafe or silent alternate provider. Explicit API/BYOK fallback preserves settings.

## Evidence and final decision

Run `python tools/codex_integration_completion.py` from the repository.
It runs implementation/conformance/security checks, full Builder regression,
real-browser setup/support checks, production build and inference/API/BYOK tests.
It performs no login or model turn. Evidence is written under
`target-codex-agent-readiness/completion/`.

The gate validates the fixed repository records:
- [live account certificate](evidence/codex-ag029-host.json);
- [credential-free isolation proof](evidence/codex-ag029-isolation.json);
- [real protected setup route](evidence/codex-ag030-setup.json);
- [accountable defect/risk review](evidence/codex-ag030-review.json).

Every required scenario must pass. Agent source coverage must be exact; source
hashes, isolation artifacts, setup image identity and the review's hashes of all
Builder production Python/TypeScript must match. Missing, duplicate, stale,
partial or malformed evidence fails closed. Review expires after 30 days;
changed source requires renewed evidence/review. Local hashes establish
integrity, not a publisher signature or protection against malicious maintainers.

All engineering checks, live/isolation/setup evidence, a complete scoped
review, zero unresolved known P0/P1 issues and explicit acceptance of lesser
risks are required for `codex_integration_complete: true`.
No empty inventory or old AG-020 shipping verdict substitutes for these checks.
There is no force-complete flag. Unit-test positive records remain disposable
test fixtures and never replace the production certificates.

## Accepted upstream risk, not public-production approval

The product owner explicitly accepted the scoped dependency risk on 2026-09-23.
See [exact surfaces and official sources](CODEX_APP_SERVER_SURFACE.md) and
[the source-bound acceptance record](evidence/codex-ag030-review.json).
Default stdio and stable API opt-in semantics do not remove the command-level
experimental support caveat, beta config profiles, undocumented host flag, or
best-effort experimental cancellation cleanup. Before public production,
re-evaluate upstream maturity, compatibility, isolation and the launch decision.

## Boundaries and operational limitations

The unchanged path is agent -> XACE tools -> typed proposal -> preview ->
user/XACE approval -> GDE -> SGC -> runtime. Setup routes are local-operator-only,
consent protected, and not exposed to model tools. No raw model shell, arbitrary
project write, direct commit/runtime mutation or credential access is added.
The provider-owned login volume is retained; XACE does not inspect auth files.

A cancelled build cannot activate afterward; a completed activation is not
misreported as cancelled. Failed verification preserves the previous pin.
Cancellation may leave Docker build cache, not an activated runtime or deleted
credentials. Repair uses the same verified archive; newer versions require
recertification. Docker subscription terms and Windows/WSL requirements remain
external prerequisites. Full distribution/installer/signing/deployment and
whole-XACE launch certification stay outside this task.

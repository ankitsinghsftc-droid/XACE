# Codex compatibility and process resilience (AG-027)

AG-027 implements compatibility admission and failure recovery, not real-account certification or whole-XACE launch readiness. Codex App Server remains the primary adapter; API/BYOK remains the unchanged default/fallback. No Local or Claude execution is introduced.

## Compatibility decision

The versioned profile is `xace.codex_app_server_contract.v1`. The conservative candidate window is stable `>=0.143.0,<0.155.0`, reflecting the existing 0.143/0.144 lifecycle fixtures and the currently inspected 0.154 development family. This is a maintainer admission policy, NOT evidence that every version in that interval works. Every real process must additionally pass the consumed-request schema profile; prereleases, unknown versions, future minors, revoked hashes/versions and incompatible security fields fail closed. Expanding the window requires generated schema evidence and tests, not just changing a version number.

The profile verifies the shapes XACE relies on for initialization, authentication (including device code), model discovery, threads, resume/fork/compaction, turns/interruption and native MCP status. It resolves document-local references without fetching external resources, checks required fields/types/security enum values, and rejects unsupported validation constructs on consumed requests. Additive methods and optional fields are accepted. This is a conservative consumed-contract check, not a general JSON Schema equivalence solver. Runtime response and event checks independently reject malformed IDs, cross-thread/turn events and unknown terminal states.

Each pin stores its exact executable SHA-256, complete generated-schema fingerprint and compatibility profile. Activation persists the generated documents in `<runtime-state-dir>/schemas/<fingerprint>.json`. Repair and rollback still demand the original exact executable/schema identity; a compatible additive schema change is an explicit Update, not a silent Repair. Pins from before AG-027 require consented Repair/reverification. No provider executable or credential is changed.

Default real-process detection/start also checks compatibility, including external fallbacks. An in-memory cache covers at most eight exact executable hashes; version/revocation policy is checked before reuse. Test-injected clients remain deterministic fixtures and do not certify real binaries.

Normal deprecation changes require 30 days notice, recorded sunset dates in `DEPRECATED_VERSIONS`, an update/rollback path and tests. Sunset versions fail closed. Security revocations use the existing version/hash blocklist immediately, with no grace period. Nothing automatically updates or downloads a runtime.

## Evidence and honest limitations

Run `python tools/codex_schema_check.py --executable <absolute-native-executable> --output <evidence-directory>` to generate schemas, fingerprints and a machine-readable verdict without authentication, model turns or runtime activation. The command exits nonzero on incompatibility. Evidence must be generated for each future certified exact runtime; an empty certified-runtime list must never be treated as public-product certification.

The installed editor-private `0.154.0-alpha.6.2` was inspected only as development evidence. Its 305 generated documents hash to `90343540518664b9a0c398edce465b25707828babc920c43e12fd6d2370c2544`; its executable hash is `2271526227b06ca13ab2b975b88546460fc61b2a29225b6dda0fdc803024ccc9`. It is rejected: it is a prerelease/private distribution and its read-only sandbox schema does not declare XACE's required restricted-read `access` field. No security relaxation was made. Generated local evidence is in `tmp/ag027-evidence`; this document preserves the negative verdict, not a certification claim.

No real runtime/account combination is certified yet. AG-029 must find and prove a supported configuration that satisfies the security profile; AG-030 must block release if none exists. Existing fixture-based adapter certification is not a substitute. If a currently installed runtime stops being offered after this change, the remedy is a compatible verified runtime or API/BYOK, not bypassing schema validation.

The current [official App Server documentation](https://learn.chatgpt.com/docs/app-server) documents version-specific schema generation and JSON-RPC envelopes. It also currently labels the App Server command/remote-host path and WebSocket transport experimental and not supported for production workloads. XACE retains local stdio and its chosen architecture, but AG-030 must explicitly resolve/accept provider-support risk; passing XACE's internal engineering gates does not imply provider production support.

## Process and recovery policy

- Initialization may create at most two processes, with one 100 ms delay, only for classified transient transport failures before any thread/turn operation. Every failed process is closed. No turn, thread creation, compaction, tool call or proposal is automatically replayed.
- RPC reads and writes use the configured timeout (four seconds by default); blocked pipe writes are bounded. A response timeout invalidates the connection so a late response cannot be mistaken for a later request.
- Frames are capped at 256 Ki characters; both incoming and pending-notification queues are capped at 64. Overflow terminates the connection rather than dropping ordered events. Malformed JSON, duplicate keys, non-finite values, invalid envelopes and mismatched response IDs fail closed.
- Turns time out after 120 seconds without an event. Explicit resume creates a new connection to the same provider thread, reattaches required MCP, and never silently substitutes another thread or resends the old prompt. Missing/stale threads require the user to choose a new session.
- Required MCP health is checked before every turn and every five seconds during consumption. Missing/disconnected servers or a changed tool allowlist stop the session. Resume re-establishes and verifies the bridge; it never silently falls back to arbitrary tools.
- Cancellation waits for an already-started bounded worker before final cleanup, avoiding a late client being published after cancellation. Shutdown terminates/reaps the process before closing reader pipes to avoid an IO-lock deadlock. Transport and MCP resources are closed on both start and stream failures.
- Provider errors are categorized without copying raw error strings. Rate limits, account restrictions and network failures preserve API fallback. This does not implement AG-028's support bundle.

## Verification

Twenty new focused tests cover additive/breaking schemas, version exclusion, stale/malformed events, actual subprocess crashes/timeouts/blocked writes/overflow/cleanup, provider error canaries, startup retry bounds, no turn replay, idle recovery, stale resume, cancellation during startup, required MCP loss, persisted schema evidence and legacy pin revalidation. Final results: Builder lint/typecheck/UI contracts and all 248 server tests pass; all 94 Codex-specific tests pass after final schema refinements. Production build, setup browser smoke, nine internal Agent readiness checks and the 20-file static Agent security check pass. No live-account/model turn was run.

The security path remains agent → XACE tools → typed proposal → preview → user/XACE approval → GDE → SGC → runtime. No raw shell, arbitrary real-project write, direct commit/runtime mutation or credential-reading capability was added.


## AG-029 official artifact follow-up (2026-09-21)

With user approval, official stable 0.154.0 and 0.155.1 were installed in isolated certification directories. Both fail the consumed-schema profile; neither declares restricted-read access, even in 0.155.1 experimental schema output. Version 0.155.1 is also outside the existing admission range. See `docs/CODEX_REAL_ACCOUNT_CERTIFICATION.md` for hashes and complete preflight findings. This is no longer solely a private-extension artifact limitation. No production policy was relaxed and no account turn ran.

# Codex Agent Mode Integration Completion Roadmap

Status date: 2026-09-21

## Scope and outcome

This roadmap is limited to completing the Codex Agent Mode integration inside XACE. It does not certify the whole XACE product for public launch.

AG-020 certified the provider-neutral Agent Host, deterministic Mock and Codex adapter behavior, the security and proposal boundary, durable session history, functional Agent UI, and unchanged API/BYOK fallback. AG-021 established the stable App Server lifecycle and runtime-provenance baseline. AG-022 replaced the experimental production tool path with required native MCP. AG-023 selected managed acquisition of the official pinned Python Codex SDK/runtime, without approving raw binary redistribution.

The remaining work makes Codex setup, authentication, compatibility, recovery, diagnostics, and real-account operation complete as an XACE feature. Whole-product installer construction, XACE signing/notarization, general engine/platform certification, marketing launch gates, and unrelated XACE features belong to the later XACE launch program.

There are nine tasks from AG-022 through AG-030 in this scoped sequence. AG-022 through AG-030 are complete for the declared development/early-user scope. Zero tasks remain in this Codex integration sequence; public-production re-evaluation is mandatory before launch. The declared Windows x64 / Docker Desktop WSL 2 / pinned Codex 0.155.1 configuration now has real-account evidence. This is not every-platform or whole-XACE launch certification.

## Architecture retained

- Codex App Server remains the first and primary production Agent Mode integration.
- AgentAdapter owns provider detection, lifecycle, authentication orchestration, sessions, events, cancellation, resume, fork, and compaction.
- Native MCP is the preferred provider-neutral XACE tool transport.
- The security boundary remains agent -> XACE tools -> typed proposal -> preview -> user/XACE approval -> GDE -> SGC -> runtime.
- Normal Builder Agent Mode exposes no raw shell, arbitrary real-project writes, credential access, direct GDE commit, or direct runtime mutation.
- Context Capsules remain isolated while controlled read-only progressive retrieval supplies relevant XACE/project/system/world/binding/asset/adapter knowledge.
- SQLite remains authoritative for structured session/event/tool/proposal/lineage state; JSONL is optional audit/export only.
- API/BYOK remains independently usable and unchanged.
- Local Agent and Claude execution remain deferred and non-blocking.

## Non-regression rules for every task

- Existing XACE project, GDE, SGC, runtime, engine-adapter, validation, and rollback paths remain authoritative.
- New contracts are additive or versioned, and stored sessions remain readable.
- Provider-native capabilities are used where supported instead of reimplemented.
- Experimental provider capabilities are explicit fallbacks and cannot silently replace a failed production path.
- No credential value enters XACE logs, SQLite, WebSocket payloads, project files, support bundles, or command arguments.
- External-state operations have cancellation, truthful progress, recovery, and an API/BYOK fallback.
- Each task runs focused proof plus proportional Agent, Builder, inference, security, claims, and build regression gates.

Official references:

- https://developers.openai.com/codex/app-server
- https://developers.openai.com/codex/config-reference
- https://developers.openai.com/codex/auth
- https://developers.openai.com/codex/cli
- https://developers.openai.com/codex/sdk
- https://developers.openai.com/codex/open-source

## Completed baseline

### AG-021: Stable protocol and runtime provenance baseline

Status: complete (2026-09-17).

Objective: Establish an honest compatibility baseline before adding distribution or UX.

Likely modules: agent_host/codex_adapter.py, provider_settings.py, tools/agent_mode_production_readiness.py, focused Agent tests, architecture/readiness documents.

Dependencies: AG-020.

Implementation summary:

- Keep App Server initialization on the stable API unless an isolated compatibility fallback explicitly requires experimentation.
- Remove unsupported paginated thread creation.
- Align stable thread-start fields with the generated schema.
- Classify managed, external CLI, custom/test, and private host-extension runtime provenance.
- Report protocol compatibility separately from public distribution readiness.
- Upgrade the optional live probe to start and delete its own empty read-only thread without a model turn.
- Preserve current external runtime discovery and API/BYOK behavior.

Acceptance criteria:

- Stable detection and ordinary thread lifecycle omit experimentalApi.
- Thread start omits historyMode and uses the schema-valid read-only sandbox value.
- Dynamic tools opt in explicitly and are labeled experimental.
- A private extension binary is reported as development fallback only.
- Live start/delete passes on the installed runtime and leaves no smoke thread.
- Public distribution remains blocked in machine-readable readiness output.

Tests/proofs: focused provenance, initialization, lifecycle, bridge, and readiness tests; full Agent/Builder/inference/security gates; optional live Codex lifecycle report.

Rollback/failure behavior: revert to the AG-020 adapter while retaining API/BYOK; never reinterpret failed compatibility as public readiness.

Completion evidence: stable and failed protocol probes now have distinct machine-readable compatibility states; the installed host-extension runtime is classified as development fallback only; the AG-020 report remains implementation-certified but explicitly holds public release.

Verification: 20 focused tests, 80 Agent tests, 165 Builder server tests, Builder lint/typecheck/UI contracts, production Vite build, 233 inference tests, Mock + Codex conformance, static Agent security, forbidden claims, default readiness, and the live no-model-turn stable thread start/delete probe all pass.

### AG-022: Native XACE MCP transport for Codex

Status: complete (2026-09-18).

Objective: Remove App Server dynamicTools from the normal production path and serve the existing XACE tool contract through required native MCP.

Implementation:

- Added a fixed stdio MCP proxy launched per Codex App Server process.
- Added an authenticated loopback broker owned by XACE so the live XaceToolSurface, session store, proposal ingress, and runtime observations remain authoritative.
- Injected the MCP server through per-thread App Server config without changing the user's global Codex configuration.
- Passed the high-entropy session secret only through the child environment; it is absent from argv, thread config, session metadata, logs, and project state.
- Marked the server required and verified it after start/resume with mcpServerStatus/list and exact tool-catalog parity.
- Kept dynamicTools only behind an explicit development fallback flag. Native startup or status failure otherwise fails closed.
- Mapped provider-native mcpToolCall items through the existing AgentEvent and security contracts.
- Disabled App Server shell, unified exec, web search, and image tools per thread so XACE MCP remains the authoritative tool boundary.
- Made MCP responses JSON-RPC 2.0 compliant and retained preview-only proposal behavior.

Acceptance evidence:

- Standard sessions omit experimentalApi and dynamicTools.
- The proxy completes initialize, tools/list, and tools/call against the live XACE tool surface.
- Required-server failure closes the App Server client and broker without mutating project state.
- Native tool events are accepted only for the session's XACE allowlist.
- Legacy dynamic fallback tests opt in and deliberately fail native startup.
- Focused native/fallback/proposal/detection tests and the full Agent suite pass.

Rollback/failure behavior: Disable Codex Agent Mode for the affected runtime and offer API/BYOK. Never silently select experimental dynamic tools.

### AG-023: Codex distribution, compliance, and integration decision

Status: complete (2026-09-18).

Decision: Prefer XACE-managed acquisition of an exact certified `openai-codex` stable package in an isolated XACE Agent integration environment. OpenAI documents that the stable Python SDK includes and automatically uses a pinned Codex CLI runtime. Keep the direct App Server protocol as the production integration and keep compatible externally installed Codex as fallback.

Safety boundary: Raw binary bundling, repackaging, redistribution, mirroring, package-internal binary scraping, and automatic acquisition remain disabled. The reviewed official documentation does not establish an OpenAI-specific vendor signature/checksum program or a raw-binary redistribution grant, so the decision does not rely on either. AG-024 must verify exact package hashes, supported platform artifacts, a supported pinned-runtime launch surface, runtime/schema compatibility, and lifecycle recovery before enabling acquisition.

Authentication boundary: Codex remains the credential owner. The managed route requires the OS keyring and never reads, copies, persists, or exports provider credentials or `auth.json`; keyring failure offers guided external installation or API/BYOK.

Update/revocation: XACE Agent Integration maintainers own an exact certified manifest, review security releases within 7 days and ordinary stable releases within 30 days, require user consent, retain a last-known-good runtime, and maintain a machine-readable blocklist.

Evidence: `docs/adr/ADR-0023-CODEX-RUNTIME-DISTRIBUTION.md`, the versioned `xace.codex_distribution_policy.v1` payload, focused policy/settings/readiness tests, and official App Server, SDK, CLI, authentication, and open-source documentation.

Out of scope retained: General XACE desktop packaging/signing and AG-024 runtime lifecycle implementation.

Verification: 24 focused policy/settings/detection/readiness tests, the 89-test Agent suite, Builder lint/typecheck/UI contracts and all 174 server tests, the production build, 233 inference tests, static Agent security across 15 files, Mock + Codex conformance, forbidden claims, and the nine-check readiness gate pass.

## Remaining ordered implementation tasks


### AG-024: Managed or guided pinned Codex runtime lifecycle

Status: Complete (guided official external-install fallback).

Delivered: Operator CLI in `tools/codex_runtime.py`, native-platform and SHA-256 verification, generated App Server schema fingerprinting, atomic selection, exact-pin repair/rollback, last-known-good metadata, non-destructive deactivation, OS-locked interruption recovery, and revocation checks. Invalid or removed pins cannot silently fall through to PATH. See `docs/CODEX_RUNTIME_GUIDE.md`.

Decision: Managed SDK acquisition stays disabled because a public executable-location surface for direct App Server integration was not established. No package internals were scraped. Provenance is user-confirmed official installation, not publisher-signature verification. The fallback never copies or changes a provider executable; rollback requires the old artifact to remain available. Native header support is not cross-platform certification. Functional setup UI remains AG-026; real-account certification remains AG-029.

Verification: 18 deterministic lifecycle tests pass; generated-schema compatibility was exercised against the installed development CLI (305 documents), without activation or authentication. Builder production build and all nine Agent readiness checks pass, including conformance and API/BYOK fallback.

Objective: Implement the runtime lifecycle selected by AG-023.

Dependencies: AG-023.

Implementation:

- Resolve, verify, activate, inspect, update, repair, roll back, and remove a pinned Codex runtime in a XACE-owned integration directory when permitted.
- If managed acquisition is not permitted, implement an official guided install and deterministic external-runtime verification flow.
- Verify platform, architecture, digest/signature when available, version, provenance, and the expected App Server schema.
- Use atomic activation and retain a last-known-good runtime.
- Never modify another application's extension binary or a user-managed global CLI.

Acceptance criteria:

- Install/acquire or guided-detect, repair, update, rollback, removal, and interrupted-operation recovery are deterministic.
- Active version and provenance are machine-readable.
- Codex authentication remains provider-owned and outside project data.

Out of scope: Packaging or updating unrelated XACE components.

### AG-025: Provider-native Codex authentication lifecycle

Status: Complete (backend/operator controls; functional setup UI remains AG-026).

Delivered: Lazy adapter-owned auth connection, browser/device-code challenges, correlated completion/cancel/retry, local expiry, logout consent, account refresh, safe identity/limit/optional usage projections, and standardized recovery states. Local-only, same-origin protected endpoints never accept credentials or arbitrary provider methods. Provider-owned storage is untouched by XACE; account changes/logout close cached model connections. Auth notifications are excluded from chat history and authentication errors are sanitized before persistence.

Evidence: 28 deterministic auth/endpoint/privacy tests pass, including SQLite/JSONL and logging/file-access canaries. Generated provider auth schemas were inspected without signing in. Production build, Agent static security, and all nine readiness checks pass. Real-account certification remains AG-029. See `docs/CODEX_AUTH_LIFECYCLE.md`.

Objective: Make Codex sign-in, sign-out, account changes, entitlement failures, limits, and recovery usable from XACE without owning credentials.

Dependencies: AG-021; coordinate with AG-024.

Implementation:

- Map account/read, login start/completion/cancel, logout, account-updated, rate-limit, and usage capabilities where the certified App Server supports them.
- Support browser and device-code flows exposed by the provider.
- Let Codex enforce credential storage and surface only non-secret policy/state.
- Handle workspace restrictions, expired sessions, unavailable browser launch, cancellation, and retry.

Acceptance criteria:

- A signed-out user can start, cancel, complete, and retry login.
- Identity, entitlement, and provider-managed limits update without restarting XACE.
- Secret canaries prove credentials never enter XACE persistence, logs, UI payloads, or project files.

### AG-026: Functional Agent setup and recovery UX

Status: Complete for the AG-024 guided external-runtime model. See `docs/AGENT_SETUP_UX.md`. Fresh installation remains provider-guided, not terminal-free; automatic acquisition remains disabled. Real-account and manual assistive-technology certification are not claimed by deterministic browser checks.

Evidence: seven local runtime-control tests, real-browser configure/auth/cancel/prompt/fallback and accessibility-semantic checks, explicit readiness-cache regression, Builder regressions, production build and nine existing Agent readiness gates. The broader real-account certification remains AG-029.

Objective: Turn runtime and authentication states into a complete, clean functional workflow.

Dependencies: AG-024 and AG-025.

Implementation:

- Add install/configure or guided-detect, sign in/out, refresh, update, repair, rollback, retry, diagnostics, and switch-to-API actions.
- Show progress, cancellation, consent, version/provenance, account, limits, and precise recovery guidance.
- Keep the information architecture modest because the larger XACE Creation Experience redesign remains separate.

Acceptance criteria:

- A supported user can reach a usable Codex Agent prompt without terminal commands.
- Every setup state has a safe primary action and an API/BYOK fallback.
- Keyboard, focus, screen-reader, reduced-motion, and narrow-window checks pass.

### AG-027: App Server schema compatibility and process resilience

Status: Implementation complete. Twenty new fault/compatibility tests cover bounded subprocess I/O, schema admission, recovery and cancellation. See `docs/CODEX_COMPATIBILITY_RESILIENCE.md` for policy, generated negative evidence and verification. No real runtime is certified: the installed private alpha omits the restricted-read schema field XACE requires and is rejected. AG-029/030 must establish a compatible real configuration and resolve the official App Server production-support caveat before release.

Objective: Make supported Codex upgrades and App Server failures predictable.

Dependencies: AG-022 and AG-024.

Implementation:

- Generate and fingerprint schemas for every certified runtime version.
- Define supported version ranges, prerelease policy, blocklist, deprecation window, and compatibility checks.
- Add bounded startup/retry policy, crash recovery, cancellation-race handling, malformed-event rejection, stream backpressure, stale-session recovery, and required-MCP recovery.
- Keep provider capability and model discovery authoritative.

Acceptance criteria:

- Breaking schema changes fail closed with actionable update or rollback guidance.
- Additive changes remain compatible.
- Crash, timeout, malformed response, network loss, rate limit, and cancellation never mutate project state or leak a process.

### AG-028: Agent privacy, diagnostics, and support operations

Status: Complete. Local allowlisted diagnostics cover all seven failure categories. Separate preparation/download consent, full preview, immutable exact-byte export, bounded expiring previews and local clearing are implemented. No automatic upload, project/history export or credential access is added. See `docs/AGENT_PRIVACY_SUPPORT.md` for retention, deletion and incident/support ownership.

Evidence: 13 privacy/backend tests, real-browser preview/export consent checks, all 261 Builder server tests, lint/typecheck/UI contracts, production build, static Agent boundary checks and all nine internal readiness gates pass. Real-runtime/account certification remains AG-029.

Objective: Make the Codex integration supportable without leaking projects, prompts, or credentials.

Dependencies: AG-024 through AG-027.

Implementation:

- Add local structured diagnostics and an explicit-consent Agent support bundle.
- Include XACE Agent version, Codex provenance/version, schema fingerprints, lifecycle states, MCP health, and redacted error categories.
- Exclude prompts, project content, credentials, tokens, provider auth files, and proposal payloads by default.
- Document retention, deletion, redaction, incident response, and support ownership for Agent data.

Acceptance criteria:

- Diagnostics distinguish runtime, auth, compatibility, provider, MCP, persistence, and XACE validation failures.
- Users can inspect the bundle before export.
- Redaction canaries and privacy tests pass.

Out of scope: Whole-product telemetry or general XACE support operations.

### AG-029: Real-account Codex end-to-end certification

Status: Complete (2026-09-22), scoped to the declared Windows x64 / Docker Desktop WSL 2 / Codex 0.155.1 configuration and opted-in account. The production-selected Windows host adapter passed real auth/models, MCP, streaming, persistent chat/tools/proposals, preview/rejection, approval handoff, actual GDE/SGC, resume/fork/compaction, cancellation and outage recovery. Source CGS stayed unchanged. Backend abstraction, reproducible local setup, consistent setup/auth/status selection and graceful API/BYOK fallback are implemented. See docs/CODEX_REAL_ACCOUNT_CERTIFICATION.md and docs/CODEX_DOCKER_BACKEND.md. AG-030 subsequently implemented final provisioning UX and recorded scoped upstream support acceptance; see its current status below.

Objective: Prove the integration beyond deterministic fixtures on supported Codex runtime/account configurations.

Dependencies: AG-022, AG-025, AG-026, and AG-027.

Implementation:

- Exercise authentication state, model discovery, thread start/resume/fork, compaction, streaming, cancellation, native MCP retrieval, typed proposal, rejection, approval handoff, limits, outage, and recovery.
- Use disposable isolated XACE projects and explicit opt-in test accounts.
- Separate no-model-turn protocol smoke from provider-billed model-turn tests.
- Record runtime version/provenance, schema hash, redacted events, and XACE Agent build identity.

Acceptance criteria:

- Required scenarios pass for every Codex runtime/account configuration claimed by the integration.
- No scenario writes the real project or bypasses preview/approval.
- Failures are recoverable and usage is labeled provider-managed.

Out of scope: Certifying every operating system or the whole packaged XACE product.

### AG-030: Final Codex integration completion gate

Status (2026-09-23): Complete for the declared development/early-user configuration. Engineering implementation and all six aggregate checks pass. Terminal-free verified local archive build/repair is available in Builder; real protected setup, refreshed live-account and isolation proofs pass. Source-bound evidence admission and defect/risk review are implemented. Explicit upstream risk acceptance is recorded for development/early users only; final aggregate verification passed with no blockers. Public-production re-evaluation remains mandatory. See docs/CODEX_APP_SERVER_SURFACE.md. See docs/CODEX_INTEGRATION_HANDOFF.md.

Objective: Decide whether the Codex feature is complete enough to hand off to the broader XACE product and launch program.

Dependencies: AG-022 through AG-029. AG-016 through AG-018 remain deferred and non-blocking.

Implementation:

- Aggregate native MCP, runtime decision/lifecycle, authentication, functional setup UX, compatibility/resilience, privacy/support, real-account evidence, and non-regression results.
- Require zero unresolved Codex-integration P0/P1 defects and explicit risk acceptance for lesser findings.
- Publish Codex setup, supported runtime/account configurations, recovery, security boundary, limitations, and API/BYOK fallback documentation.
- Emit a machine-readable codex_integration_complete decision separate from whole-XACE launch readiness.

Acceptance criteria:

- A user in a declared supported Codex configuration can configure the runtime, authenticate, complete a safe Agent task, restart/resume, and recover from expected failure without developer commands.
- Existing API/BYOK and non-Agent workflows pass unchanged.
- The gate makes no claim that XACE itself is packaged, signed, generally platform-certified, deployed, or launch-ready.

Rollback/failure behavior: Keep Codex Agent Mode unavailable or limited for affected configurations while API/BYOK remains usable.

## Execution rule

Implement one task at a time in dependency order. Close a task only after its focused proof and proportional non-regression gates pass. AG-029 is complete with production-path real-account and isolation evidence; AG-030 is complete after all six final gates and scoped risk acceptance; public-production approval is not part of this closure. AG-029 must not substitute deterministic fixtures for real compatible-runtime evidence.

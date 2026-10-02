                        # AG-029 real-account certification

Status (2026-09-22): **Complete for the declared Windows x64 / Docker Desktop WSL 2 / Codex 0.155.1 configuration and opted-in ChatGPT account.** AG-030 remains unfinished.

## AG-030 revalidation (2026-09-23)

All mandatory live scenarios passed again after the terminal-free setup changes.
The protected Builder setup route selected image
`sha256:8f98e06bc7f94a8edf11ca2d4ac3c6eef4b8e574fef1fdbd33364a6c0c38304e`;
credential-free isolation passed on that image. The refreshed canonical JSON
records current source hashes and seven provider-discovered models (availability
is dynamic). The original AG-029 image/count below is historical evidence.
AG-030 final support-risk acceptance remains separate.

## Final production-path evidence

The user approved Docker/WSL as the first supported execution backend. Normal
Builder startup, registry, setup, status/auth and Agent sessions now select
`IsolatedCodexAdapter` through the backend-neutral `AgentExecutionBackend`
contract. This is no longer an injected candidate or a Builder running inside
a test container: Builder and its real GDE/SGC remain on Windows.

The final host run passed every mandatory live check:
authentication and five provider-discovered models; provider-managed usage and
rate-limit state; native MCP proposal/tool history; streamed completion;
SQLite chat/events/tools/proposals; visible Builder preview; missing approval
denial; valid approval-token handoff; actual GDE application and successful SGC
compilation on a disposable approved copy; preview rejection persistence;
resume, fork lineage, completed compaction, cancellation, subsequent successful
turn, owned-process outage and explicit resume. Source CGS stayed unchanged.
Quota state was inspected, not deliberately exhausted.

Evidence: [host live certificate](evidence/codex-ag029-host.json) and
[credential-free isolation preflight](evidence/codex-ag029-isolation.json).
The host runner fails unless every required check is literally true, models
exist and the error list is empty. Its negative regression prevents partial
passes from producing a certificate. These are measured account/runtime
results, not mocked provider execution or a universal-account assertion.

The production-selected image was built with the documented local setup tool:
`sha256:4acbbf9ebd8622f3785ea3d26f9cb642adae2990e3840345c3fc3a674df3c6b3`.
Official Linux Codex binary SHA-256:
`0753dfe1d8b87a52436deb13eb1c549661ef4c84fee2c5aa688385eebeccb761`.
Fresh stable schema fingerprint:
`63b9e241836428c98f456d57324be8dfa145d44e9960ab1a167ecc185ee60045`.
The worker verifies binary identity, stable schema, revocation policy and
isolation on each startup. The image is locally built from the verified
official npm archive and digest-pinned base, not redistributed or vendor-signed
by XACE. The retained provider-owned volume avoids credential copying.

Regression evidence: full Builder suite (304 tests, 217.455s, including the final
certificate regression); focused backend tests, lint/typecheck/UI contracts,
production build and static Agent boundary checks pass. Real-browser checks
caught and fixed detached-label lookup in the setup panel; both old setup and
the isolated setup path are tested. The final 304-test rerun passed; native and isolated real-browser setup,
UI contracts, production build and diff checks passed. No owned execution
containers remained running after verification.

The documented setup, recovery, credentials, dependency fallback and security
decision are in [Codex Docker backend](CODEX_DOCKER_BACKEND.md).
No raw shell, arbitrary project write, direct GDE commit, runtime mutation or
credential access was granted to the model. API/BYOK remains the default and
unchanged. Native Windows isolation is a later backend; Local/Claude are
non-blocking deferred work.

## Scope retained for AG-030

This closes empirical AG-029 certification, not the final feature or whole-XACE
launch gate. AG-030 must aggregate evidence, assess ordinary-user provisioning
(the initial local build still uses an operator command), and resolve/accept
the official App Server experimental production-support caveat. No automatic
public bundling, every-OS certification, universal account access, deliberate
quota exhaustion or automatic update guarantee is claimed.

Repeat live verification only with account-owner approval:
`python tools/codex_host_backend_probe.py --real-account --output <report.json>`.
Run the credential-free preflight separately with
`python tools/codex_container_preflight.py --docker <docker.exe> --image <full-image-sha256> --output <report.json>`.

## Historical investigation (superseded by the final decision above)

# Earlier AG-029 checkpoints

Status (2026-09-22): **In progress; isolated real-account checks now pass, production certification not yet declared.** AG-030 remains unfinished.

## Live Linux/container continuation (2026-09-22)

The earlier Windows findings below remain valid, but the statement that no account calls occurred is now historical. A user-local Docker Desktop installation was located without changing PATH or installing a new daemon. The user completed official device login into the dedicated `xace-ag029-provider` Docker volume. XACE never read, copied or exported its authentication file.

An explicit, non-default candidate maps XACE restricted-read intent to the pinned Linux runtime's native permission profile. The existing Windows/default admission gate remains intact. Image ID: `sha256:7b59fe353f2416fd2ef2b5088830b2168689a4b89bf93ffe8af973e49e9eb506`; official Codex 0.155.1 Linux binary SHA-256: `0753dfe1d8b87a52436deb13eb1c549661ef4c84fee2c5aa688385eebeccb761`; generated stable schema fingerprint: `63b9e241836428c98f456d57324be8dfa145d44e9960ab1a167ecc185ee60045`. This operator-built diagnostic image is not a public distribution or a bundled product.

Isolation uses non-root execution, read-only container root, dropped capabilities, no-new-privileges, a deny-by-default seccomp profile, and native capsule-only read access plus the fixed runtime/minimal platform files. Model native shell/image/browser/plugin capabilities are disabled. Native apply_patch remains exposed by the provider but measured filesystem enforcement denies private reads and writes; ignored JSON fields or hooks are not used as a boundary. The credential-free preflight has no network or auth volume. Live probes mount only XACE code read-only, provider storage and disposable tmpfs; no real game project or host credential directory is mounted.

The seccomp profile starts from Moby's default (`tmp/ag029-container-build/moby-default-seccomp.json`, SHA-256 `785b2429264afba4d594320337cb17f144f3c7d51585f9805eef72e28f4f9334`) and permits clone/unshare/mount/umount2/pivot_root/setns for nested unprivileged isolation. It grants no host capabilities or Docker socket. The policy hash is recorded with each proof. This profile still requires packaging/security review before production adoption.

Measured real-account passes: signed-in state, five discovered models, provider-managed billing and rate-limit state, native MCP diagnostics, streamed deltas, thread resume/fork with lineage, cancellation with owned-transport cleanup, a successful subsequent turn, completed native compaction, typed proposal persisted in SQLite, preview without source-CGS mutation, missing/wrong-token rejection, valid approval-gate handoff without a test override, preview discard, owned-provider-process failure and explicit resume. The recorded four-turn run uses provider-discovered `gpt-6-astra`; this is evidence for the tested account/configuration, not a universal account/model claim.

Two live-discovered lifecycle corrections are covered by focused tests: discard only previous-turn accounting snapshots on resume (never stale tool requests or cross-thread events), and give forked candidate sessions fresh transports/MCP authority instead of sharing notification queues. Full Builder regressions pass: 291 tests; lint/typecheck, UI contracts and static Agent security checks pass.

Repeatable evidence:
- `python tools/codex_container_preflight.py --docker <docker.exe> --output <preflight.json>` (no account usage).
- `python tools/codex_container_live_check.py --docker <docker.exe> --output <live-check.json> --real-account` (explicit, bounded account usage).
- Current redacted records: `tmp/ag029-container-build/preflight.json` and `live-check.json`. They retain source hashes, runtime/schema identity and booleans, not credentials or raw events.

The real Builder-router proof now also passes: actual registry, context-capsule builder, message router and event stream persist the turn/tool calls, deliver the native MCP proposal preview, acknowledge discard and persist its disposition, while CGS stays unchanged. The first run exposed missing native MCP preview parsing; that production parser is now fixed with structured/text-envelope and negative tests. Final post-fix verification passed all 179 Agent tests and 32 Codex tests (211 total), plus the static Agent security check. Evidence: `tmp/ag029-container-build/builder-check.json` (`candidate_scenarios_passed: true`, no missing checks). Its dependency-layer image is `sha256:a6a41c62440efcd715b09361b90c28cae4a13efe8d229f21db136ce013d1f2d2`; it adds Debian libsecret-tools 0.20.5-3, never an unsafe credential fallback. Synthetic isolation passed again for that image. Repeat with the live-check command plus `--builder-router`.

Remaining before AG-029 closure: resolve the distinction between this explicitly injected candidate and a selectable production configuration. Normal Builder startup/setup still selects the original adapter. Promoting the proven alternative means explicitly supporting Docker/WSL as a prerequisite for the initial Windows configuration and integrating profile selection consistently across setup, status/auth, sessions and updates. Keeping Docker test-only instead requires another verified native isolation route. This is a product/runtime-dependency decision, not missing account permission; no further login or credential sharing is required. No default adapter activation, public bundling, whole-XACE launch claim or AG-030 completion is authorized by these partial results. Account quota was read, not deliberately exhausted. The approved mutation boundary and existing API/BYOK defaults remain unchanged.

## Historical preflight record

## Work performed

Installed exact official npm packages `@openai/codex@0.154.0` and `@openai/codex@0.155.1` from `https://registry.npmjs.org` in separate repository-local test directories, using `--ignore-scripts`, no global install and no audit/funding requests. The npm lockfiles retain registry package integrity values. Neither runtime was activated in XACE, added to PATH, bundled or copied into the product. The user's VS Code installation and credentials were not changed.

Locations: `tmp/ag029-runtime-0154/` and `tmp/ag029-runtime-0155/`. These are operator test installations, not an implementation of automatic acquisition or a supported package-internal runtime-location API. Native executable discovery here is manual certification work only.

Generated public stable App Server schemas without account/session/model calls. Additional experimental schema generation for 0.155.1 was diagnostic-only; no experimental provider session was enabled.

### Official stable 0.154.0

- Version admission passes the existing policy; consumed-schema compatibility fails.
- Executable SHA-256: `be96b992178b1e467c225800da0d65f2c86d5eba1ef0b14632f65db381cbdfde`.
- 305 schema documents; fingerprint: `90343540518664b9a0c398edce465b25707828babc920c43e12fd6d2370c2544`.
- Local evidence: `tmp/ag029-official-0154-evidence/evidence.json` and `preflight.json`.

### Official stable 0.155.1

- Outside the current version window; consumed-schema compatibility also fails independently. Increasing the version ceiling alone would not fix it.
- Executable SHA-256: `eba0f32c976667cb9298efafd98513e823eeda7b576a03ec658bb8be8d336316`.
- 312 schema documents; fingerprint: `63b9e241836428c98f456d57324be8dfa145d44e9960ab1a167ecc185ee60045`.
- Local evidence: `tmp/ag029-official-0155-evidence/evidence.json` and `preflight.json`.

## Concrete blockers

Both generated stable contracts reject XACE's representative requests for `thread/start`, `thread/resume`, `thread/fork` and `turn/start`. For example, `allowProviderModelFallback` is absent from stable ThreadStartParams and present only in the experimental schema of 0.155.1. This is separate from the more fundamental sandbox issue.

Both runtime schemas expose a read-only sandbox with `type` and `networkAccess`, but no restricted-read `access` contract. The 0.155.1 experimental schema lacks it too. XACE requires explicit capsule-only readable roots; treating an undeclared field as accepted could silently leave full filesystem reads available. A read-only filesystem does not by itself prevent reading credentials or unrelated project content.

The [official App Server documentation](https://learn.chatgpt.com/docs/app-server) describes restricted-read access and recommends version-specific generated schemas. The tested artifacts do not expose that documented field. Their own generated contracts remain decisive for XACE admission; documentation alone cannot certify enforcement. These results concern the exact two tested artifacts, not every past/future Codex version or platform.

## Repeatable preflight

Run `python tools/codex_certification_preflight.py --executable <native-executable> --output <preflight.json>`.

The tool generates fresh schemas and reports every consumed-request mismatch plus a separate restricted-read diagnostic. It never logs in, starts a session, runs a model turn, activates a runtime or creates an account certificate. `schema_preflight_passed` is only a prerequisite, never end-to-end proof. Exit code 1 is expected for both artifacts above. The existing production gate remains unchanged.

Five focused tests verify complete mismatch reporting, ignored-extra-field rejection for restricted reads, version/schema failure, exclusion of extra raw error/auth fields, and separation of schema success from real-account certification. The four tests for the earlier AG-030 draft also pass; that draft still cannot certify the integration.

## Remaining work and boundaries

No live-account scenario has passed yet. Authentication, model discovery, native MCP, real turns, proposals/rejection/approval, resume/fork/compaction, cancellation and recovery still require real evidence through XACE after safe runtime admission. Existing mocks must not be relabeled as that evidence. No account usage was consumed during this preflight.

The next technical decision is to establish a supported provider contract that actually enforces the required read boundary, or approve and implement an independently verified equivalent isolation mechanism. Any request-field adjustment must preserve security and have native-schema regression evidence. Do not remove the restricted-read gate, accept ignored security fields, enable experimental execution silently or widen the version window just to obtain a green report.

The user has authorized continued work and account usage; further blanket permission is unnecessary. If an equivalent isolation approach changes the approved architecture, present its concrete boundary and tradeoffs for approval before implementing it. Until then Agent Mode remains unavailable for these configurations and API/BYOK behavior remains unchanged. The two isolated installations and generated evidence are retained for diagnosis; no files have been deleted.


## Isolation investigation follow-up (2026-09-21)

Credential-free probes use disposable synthetic files and a separate provider home; they neither copy credentials nor activate the runtime. The fixed sandbox probe is `tools/codex_isolation_probe.py`. On official Windows 0.155.1:

- Unelevated backend refuses restricted read-only access and requires the elevated backend.
- Elevated backend refuses the same profile because it requires effective `:root` read access.
- Neither refusal is proof of working isolation. Granting root read access would defeat the intended capsule-only boundary and was not done.

`tools/codex_capability_probe.py` uses a loopback fake Responses endpoint with the real App Server. No hosted model/account call is made. With shell, image, browser, plugins, hooks, multi-agent and related feature switches disabled, the captured native catalog still exposes `apply_patch` and `request_user_input`. This is not an MCP-only capability boundary. Strict config also rejects `tools.view_image`, a key currently supplied by XACE; configuration intent cannot substitute for measured runtime behavior.

Hooks were considered but not installed: the [official hook documentation](https://learn.chatgpt.com/docs/hooks) explicitly describes paths outside the hook boundary and error cases that continue execution. Hooks therefore cannot replace filesystem/process isolation. The inspected create-hook skill describes a different configuration layout; no such configuration was applied.

Local evidence is under `tmp/ag029-official-0155-evidence/` (`isolation.json`, `isolation-elevated.json`, `capabilities.json`). Six focused probe tests pass, alongside the five preflight tests. These unit tests cover evidence classification, missing evidence, environment filtering and non-certification; they are not live-account certification.

Production adapter, compatibility gates, API/BYOK behavior and user credentials remain unchanged by this investigation. AG-029 remains incomplete. A separate OS/container isolation backend is now a candidate requiring a concrete distribution and authentication design before adoption. Available local WSL inventory showed only docker-desktop; a usable Docker CLI was not found at the checked locations. No distro, container runtime or privileged sandbox setup was installed or reconfigured.

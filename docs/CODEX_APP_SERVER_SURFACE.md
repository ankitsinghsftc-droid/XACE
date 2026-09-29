# AG-030 App Server dependency verification

Verified 2026-09-23. Scope: development/early users on Windows x64 with Docker
Desktop WSL 2/Linux containers, not public-production or whole-XACE launch.

## Exact consumed surface

- `container_worker.py` launches the pinned executable with fixed `-c` settings,
  `app-server --strict-config`, stdin/stdout pipes and no `--listen` override.
  Thus App Server uses default **stdio JSONL**, bidirectional JSON-RPC 2.0 with
  the `jsonrpc` header omitted. No App Server WebSocket, Unix socket, remote
  endpoint, Codex daemon, or remote Code Mode host is selected. Docker's daemon
  is execution infrastructure, not a Codex protocol transport.
- Runtime: official Codex **0.155.1 Linux x64**. Binary SHA-256:
  `0753dfe1d8b87a52436deb13eb1c549661ef4c84fee2c5aa688385eebeccb761`.
  Selected image: `sha256:8f98e06bc7f94a8edf11ca2d4ac3c6eef4b8e574fef1fdbd33364a6c0c38304e`.
  The thread/turn/account API is the runtime's v2 schema family, not a REST
  `/v2` endpoint or negotiated semantic API version. Compatibility is checked
  against generated non-experimental schemas from that exact binary; recorded
  fingerprint: `63b9e241836428c98f456d57324be8dfa145d44e9960ab1a167ecc185ee60045`.
  XACE profile `xace.codex_linux_permissions.v1` and clientInfo version `0.1.0`
  are XACE identifiers, not OpenAI protocol versions.
- Initialization omits `capabilities.experimentalApi` (false semantics).
  `IsolatedCodexAdapter` rejects attempts to enable it. Required operations:
  initialize/initialized; account/read, account/login/start (managed ChatGPT
  browser/device-code), account/login/cancel, account/logout; model/list;
  thread/start, thread/resume, thread/fork, thread/compact/start; turn/start,
  turn/interrupt; mcpServerStatus/list; streamed thread/turn/item/account events.
  Rate-limit and usage reads are optional; unavailable usage is not invented.
- XACE supplies an **external MCP server** via Codex's MCP stdio client and a
  private worker relay. Its loopback broker is not App Server WebSocket. XACE
  does not run the removed `codex mcp-server` command. Experimental dynamicTools,
  externally supplied ChatGPT tokens, process APIs and paginated history APIs
  are not enabled. Provider-native permission/shell requests are denied.

## Maturity, specific dependencies, and failure impact

1. OpenAI recommends App Server for rich product integrations, but also explicitly
   labels the **app-server command itself** experimental and unsupported for
   production workloads. This is not merely a WebSocket warning. Stdio is the
   documented default; the separate experimental WebSocket transport is unused.
   Changes or service incompatibility can prevent login, sessions, turns or
   tools. Pinning the binary cannot pin OpenAI's remote service behavior.
2. `default_permissions` / `permissions.xace_capsule` are **beta permission
   profiles**, supplied through config rather than the experimental RPC
   `permissions` field. These enforce capsule-only read intent with command
   networking disabled. Changes could invalidate startup or isolation: require
   renewed schema/config and synthetic isolation proof before any upgrade.
   Container mounts and the host proposal boundary remain independent controls;
   do not weaken policy to recover availability. Native apply_patch remains
   provider-visible but tested filesystem restrictions deny prohibited access.
3. `features.code_mode_host=true` is explicitly set while `code_mode=false`.
   The current public config reference does not document that flag's stability.
   Treat it as a pinned implementation dependency, not a supported public API.
   No remote host URL is configured. Removal/behavior changes may break startup
   or native MCP tool availability; re-probe the tool catalog and isolation.
4. Cancellation attempts **experimental `thread/backgroundTerminals/clean`**
   best-effort after `turn/interrupt`. Without experimental opt-in, rejection is
   expected/permitted and suppressed; the client/execution channel is closed in
   `finally`. XACE does not depend on successful experimental cleanup and does
   not enable native shell terminals. A rejected call alone does not invalidate
   cancellation; no stronger terminal-cleanup guarantee is claimed.

## Acceptance and mandatory re-evaluation

The product owner's 2026-09-23 final-verification message explicitly accepts
experimental/unsupported dependencies for development/early users, conditional
on pinning, replaceability, fail-closed checks, API/BYOK fallback and mandatory
re-evaluation before public production launch. Record this as accepted residual
risk, not resolved upstream support. All four items above fall within that scope.

AgentAdapter and AgentExecutionBackend remain replaceable; no Docker assumptions
are added to core Agent/Builder APIs. API/BYOK remains unchanged and explicitly
user-selected, never a silent replay/fallback. Missing Docker/WSL, failed checks,
auth/quota problems or revoked runtime keep Agent Mode unavailable safely.
Before public production: recheck upstream command/API/config maturity and terms,
repeat exact-version auth/MCP/isolation/lifecycle tests, and obtain a new launch
decision. AG-030 completion does not grant that decision.

## Official sources

- [App Server protocol, default stdio, experimental opt-in and cleanup API](https://learn.chatgpt.com/docs/app-server)
- [MCP migration: App Server recommendation and command-level support caveat](https://learn.chatgpt.com/docs/mcp-server)
- [Config reference: beta permission profiles](https://learn.chatgpt.com/docs/config-file/config-reference)

Implementation anchors: `server/agent_host/container_worker.py`,
`codex_linux_profile.py`, `isolated_codex_adapter.py`, `codex_adapter.py`,
`codex_auth.py`, `docker_execution_backend.py` in `packages/builder-workspace/`.

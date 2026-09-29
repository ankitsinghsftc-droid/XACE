# Codex authentication control (AG-025)

AG-025 implements the backend/operator authentication lifecycle. AG-026 owns
the functional setup UI. This does not change API/BYOK defaults, authenticate
anyone automatically, or certify a real subscription/account.

## Ownership and protocol

The Codex adapter lazily owns a dedicated authentication connection. It starts
no project thread or model turn. Codex owns login callbacks, refresh, credential
storage, workspace policy, and entitlement enforcement. XACE neither reads auth
files nor accepts API keys, access tokens, refresh tokens, or external-token
login through these controls.

The implementation follows the provider's [App Server authentication contract](https://learn.chatgpt.com/docs/app-server):
account reads, browser/device-code login, completion/cancellation, logout, and
account/rate-limit notifications. Device-flow availability is determined by the
installed provider; unsupported requests return a safe recovery code. Plan names
are descriptive, never proof of entitlement. Optional usage data stays unknown
when unsupported rather than being represented as zero.

## Local control API

All requests require a loopback client/host and the header
`X-XACE-Agent-Auth: 1`. Browser origins must match Builder (or the explicit
Vite development origin). Responses use `Cache-Control: no-store`.
POST requests require JSON, reject unknown fields, and are bounded to 1 KiB.

- `GET /api/agent-auth`: poll notifications and return the versioned
  `xace.agent_auth_status.v1` snapshot. An untouched controller starts no process.
- `POST /api/agent-auth/refresh`, body `{}`: connect and ask Codex to refresh
  its own account state. No credential is returned.
- `POST /api/agent-auth/start`, body `{"flow":"browser"}` or
  `{"flow":"device_code"}`: return an ephemeral challenge once.
- `POST /api/agent-auth/cancel`, body `{}`: cancel the current provider login.
- `POST /api/agent-auth/logout`, body `{"confirm":true}`: close active model
  connections and request provider logout. This can affect the user's other
  Codex clients sharing the same provider credential store. The UI must explain
  that consequence before sending confirmation.

Clients must poll while setup is visible. Polling consumes a bounded number of
notifications and refreshes account metadata at most every two seconds.
A five-minute local pending-login timeout is enforced during polling. The
provider also owns its own login expiration. Process shutdown cancels a pending
login and closes connections without signing out an already authenticated user.

The browser-opening decision belongs to the client. Use the returned HTTPS link
manually if launching fails, or cancel and retry with the device flow. XACE
does not invoke a shell/browser automatically. Display the one-time device code
only in the dedicated setup surface; do not retain it in local storage,
telemetry, diagnostics, chat, or project files.

## State and recovery

Login state is independent of account state. A cancelled attempt can coexist
with a previously signed-in account. Duplicate starts preserve the pending
attempt; stale completion events cannot complete a newer attempt. Success is
confirmed by a new account read. Identity changes and logout invalidate active
Codex model connections; explicit resume/retry creates fresh provider connections.

Failure payloads contain stable recovery codes, not raw provider text:
`auth_expired`, `workspace_restricted`, `rate_limited`,
`flow_unsupported`, `browser_unavailable`, `runtime_missing`, or
`provider_unavailable`. Automatic cached account reads cannot clear observed
authorization failures. Explicit refresh/login can revalidate them.

Account emails are masked, plan names are allowlisted, and usage/limit fields
are numeric projections. Account notifications never become persisted chat
events. Authentication-related turn failures are sanitized before the normal
event store receives them. Login IDs stay internal; challenges are absent from
ordinary snapshots. No raw provider notification is logged by this controller.

The control API is for the local trusted operator, not remote hosting or agent
tools. No tools, shell, project writes, approvals, GDE commits, or runtime
authority are added. The native XACE tool and proposal boundary is unchanged.

## Verification boundary

Deterministic fake-provider tests cover both flows, cancellation/retry, stale
events, expiry, disconnects, workspace restrictions, limits, shutdown,
same-origin controls, URL safety, numeric usage, and credential canaries.
Canaries are checked through actual SQLite and JSONL event persistence.
Generated auth schemas were inspected locally without login or credential
inspection. Real-account/browser end-to-end certification remains AG-029.

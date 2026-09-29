# Current isolated setup (AG-030)

For the supported Windows/Docker/WSL backend, use the in-panel official archive download link, enter the downloaded .tgz path, explicitly approve and click **Build / repair isolated runtime**. Then use provider-managed device-code sign-in. Native executable controls remain hidden; missing dependencies preserve API/BYOK. See [current setup and recovery](CODEX_DOCKER_BACKEND.md). The remainder records the earlier native setup design where applicable.

# Codex setup and recovery (AG-026)

The Agent panel includes a small, replaceable setup section. The larger XACE UI redesign is not part of this task. API/BYOK remains the default and is always available as a fallback.

## Supported workflow

1. Install a supported official standalone Codex runtime using the linked provider guide. XACE does not download packages, execute installers, scrape SDK-private paths, or copy a provider binary.
2. Select **Find installed Codex**, or paste the absolute native executable path. A PATH result is only a candidate; shell launchers and editor-private runtimes are not accepted by verification. If PATH resolves a launcher, select the native executable from the official standalone installation instead.
3. Confirm the source and runtime-selection change, then verify. XACE checks the executable, version, digest and App Server schema before atomically recording its selection. Provenance is user-confirmed, not publisher-signature certification.
4. Check the account, then choose browser or device-code sign-in. Open the secure provider link and complete authentication there. Codex owns credentials; XACE never reads its auth files.
5. Refresh if needed, then select **Use Codex and focus prompt**. XACE checks readiness afresh. If model selection is required, use model settings and retry.

For an already-installed supported runtime, these Builder steps require no terminal commands. Fresh installation remains provider-guided and is NOT certified terminal-free. Managed acquisition remains disabled under AG-024. Real-account completion evidence remains AG-029, not this fixture-based UI test.

## Recovery and consent

Verify update, repair pin, rollback, remove selection and interrupted-state recovery require explicit consent. Runtime changes close active Codex connections. Removal only deactivates XACE metadata; no provider executable or credential is deleted. Rollback needs the recorded old artifact to remain available. Developer environment overrides take precedence and are displayed explicitly.

Verification runs off the request thread. Cancellation before the final activation check preserves the prior selection; it waits for bounded verification to return rather than forcibly killing it. Cancellation after activation does not undo an already-completed change. Tiny atomic remove/recover operations are not interruptible. Closing the panel cancels a login it owns, but a server-owned runtime job can finish safely; use Cancel before leaving when cancellation is intended.

Sign-out has a separate confirmation because other clients sharing Codex's credential store can be affected. Browser links and one-time device codes exist only in ephemeral panel DOM, are removed on cancellation/completion/unmount, and never enter shared UI state, browser storage or diagnostics.

The local runtime and authentication endpoints require loopback host/client checks, same-origin restrictions and a custom operator header. They are not XACE agent tools. This does not change the agent → XACE tools → typed proposal → preview → approval → GDE → SGC → runtime boundary.

## Verification and accessibility scope

- Seven backend tests cover consent, read-only discovery, lifecycle operations, overlap rejection, cancellation, safe errors, and route guards.
- The browser fixture exercises real DOM controls with fake local endpoints: configure, sign-in challenge, cancel, account refresh, usable-prompt transition, logout consent and API fallback. It also checks native keyboard targets, focus restoration, live-region semantics, narrow layout and reduced-motion styling.
- Inputs and focus survive status updates because the setup section is not rebuilt during Agent session rendering.
- Run `npm run test:agent-setup` from `packages/builder-workspace`. It uses an isolated Chromium profile and requires Chrome/Edge or `XACE_TEST_BROWSER`; no browser is downloaded.
- Automated semantic checks are not a manual screen-reader certification or an OS/browser support claim. A real-account and supported-configuration walkthrough remains required in AG-029/030.

Diagnostics show only allowlisted lifecycle states, versions and error categories. AG-028 adds a separate Agent privacy and support section with preparation consent, a complete JSON preview, separate download consent and local clearing. See `docs/AGENT_PRIVACY_SUPPORT.md`. No whole-XACE packaging, deployment or launch readiness is claimed.

# ADR-0023: Codex Runtime Distribution and Acquisition

Status: Accepted; AG-024 guided fallback implemented

Decision date: 2026-09-18

Owner: XACE Agent Integration maintainers

## Context

XACE needs a predictable Codex App Server runtime without permanently requiring every user to install and update a global Codex CLI. XACE must not take ownership of provider credentials, silently replace user software, copy a private editor-extension binary, or redistribute a runtime without a verified basis.

AG-023 decides the allowed acquisition model only. It does not download, install, bundle, update, or remove Codex; those lifecycle operations belong to AG-024.

## Evidence

Official OpenAI documentation establishes that:

- Codex App Server is the supported interface for rich product clients that need authentication, conversation history, approvals, and streamed agent events: https://developers.openai.com/codex/app-server
- The stable Python Codex SDK is installed as `openai-codex`, requires Python 3.10 or later, includes a pinned Codex CLI runtime dependency, and automatically uses that pinned runtime: https://developers.openai.com/codex/sdk
- The official CLI remains a supported user-installed channel and offers ChatGPT sign-in: https://developers.openai.com/codex/cli
- Codex owns cached credentials and can use the operating-system credential store; file storage contains access tokens and must be treated as secret: https://developers.openai.com/codex/auth
- Codex CLI, SDK, and App Server are developed as open-source components: https://developers.openai.com/codex/open-source

The reviewed official documentation does not establish an OpenAI-specific vendor signature/checksum program or grant that XACE may repackage and redistribute raw Codex binaries. XACE therefore does not rely on raw-binary redistribution.

## Decision

Choose **XACE-managed acquisition from the official stable `openai-codex` Python package** as the preferred production runtime source.

The package version must be an exact XACE-certified pin. AG-024 must install it into an isolated XACE Agent integration environment, verify package hashes, runtime version, App Server responsiveness, native MCP compatibility, and generated schema before activation. XACE must retain one last-known-good version and use atomic activation.

The existing direct stdio App Server JSON-RPC integration remains authoritative. The SDK is selected as the official pinned-runtime acquisition vehicle, not as permission to bypass `AgentAdapter`, XACE MCP, proposal review, or the security boundary.

No automatic acquisition is enabled by this ADR. AG-024 may enable it only after proving a supported SDK runtime launch surface, artifact availability for the declared platform/architecture, locked hashes, interruption recovery, update, rollback, and removal.

## Allowed provenance and priority

1. `official_pinned_python_sdk_runtime` — preferred production source after AG-024 certification.
2. `official_external_cli` — supported fallback after version, provenance, App Server, schema, and native MCP compatibility checks.
3. `custom_path` — development or test only.
4. `host_extension_private` — development fallback only; XACE must never copy, update, remove, or represent it as a public distribution source.

Unsupported or unverifiable sources fail closed for Agent Mode and leave API/BYOK available.

## Redistribution and packaging boundary

- Raw Codex binary bundling, repackaging, and redistribution are not approved.
- XACE does not mirror the package or binary.
- Acquisition must use the official package channel documented by OpenAI.
- The general XACE installer, application signing, notarization, and whole-product update system remain outside this AG sequence.
- Any future request to embed or mirror the runtime requires a new legal/compliance review and a superseding ADR.

## Integrity and platform policy

- Exact stable package version; prereleases are forbidden for public configurations.
- SHA-256 lock entries are required for every acquired artifact.
- Runtime version and App Server schema fingerprint must match the certified manifest.
- Platform and architecture are allowlisted only after the official package artifact is exercised on that target.
- A missing artifact, hash mismatch, unsupported architecture, undocumented launch surface, or schema mismatch blocks managed activation and offers guided official external installation or API/BYOK.
- Official OpenAI documentation currently does not document a vendor-signature mechanism; XACE must not claim signature verification until one is available and implemented.

## Authentication boundary

Codex owns sign-in, token refresh, sign-out, and credential storage. XACE may orchestrate provider-native App Server authentication methods and display non-secret account state, but it must never read, copy, persist, export, or log credential values or `auth.json`.

For the XACE-managed runtime, the required credential-storage policy is the operating-system keyring. If the keyring is unavailable, the managed route fails closed and offers guided external installation or API/BYOK. XACE does not silently fall back to plaintext file credentials.

AG-025 owns authentication UX and provider-native lifecycle mapping.

## Update ownership, SLA, rollback, and revocation

The XACE Agent Integration maintainers own the certified manifest and update decision.

- Review security-critical upstream releases within 7 calendar days.
- Review ordinary stable compatibility releases within 30 calendar days.
- Never auto-advance an unpinned version.
- Require user consent before changing the active runtime.
- Retain and health-check the last-known-good version before activation.
- Maintain a machine-readable version blocklist.
- A revoked or failed runtime is disabled; XACE rolls back when safe, otherwise offers compatible external Codex or API/BYOK.

These are review/compatibility SLAs, not a promise that every upstream version will be shipped.

## Remaining AG-024 verification

AG-024 must resolve these implementation constraints before managed acquisition is enabled:

- certified official package artifact matrix for each claimed OS/architecture;
- a supported way for XACE's direct App Server adapter to launch the SDK-pinned runtime without scraping private package internals;
- generated lock hashes for the chosen package artifacts;
- atomic install, activation, repair, rollback, removal, and interrupted-operation recovery.

If the SDK does not expose a supportable runtime launch surface for XACE's direct App Server integration, the approved fallback decision is guided official external CLI installation. Raw package-internal binary scraping is prohibited.

## User-facing claims

Until AG-024 is complete, XACE may say that the official pinned SDK runtime is the selected managed acquisition model and that compatible externally installed Codex is supported for development/recovery. It may not say that Codex is bundled, automatically installed, supported on every platform, or that any ChatGPT subscription universally includes access.

## Machine-readable policy

The executable policy is `xace.codex_distribution_policy.v1` in `packages/builder-workspace/server/agent_host/codex_distribution.py`. Provider settings and readiness reports expose only this non-secret decision metadata.

## Consequences

This decision avoids a permanent global-CLI requirement while preserving App Server as the primary integration, provider-owned authentication, external CLI recovery, and the existing API/BYOK fallback. It also makes AG-024 fail closed if the official package cannot satisfy XACE's platform, integrity, or launch-surface requirements.


## AG-024 implementation decision (2026-09-19)

The reviewed official SDK documentation establishes a bundled/pinned runtime used by the SDK, but not a supported public executable-location interface for this direct App Server integration. The documented standalone installer does not establish an exact-version acquisition contract. Therefore the approved guided external-install fallback is implemented; managed acquisition and raw redistribution remain disabled. No unsupported package layout is used.

`tools/codex_runtime.py` verifies a user-confirmed official native executable and records a machine-local version, SHA-256, native platform/CPU, and generated stable App Server schema fingerprint. This is trust-on-first-use with explicit provenance disclosure, not independently authenticated vendor supply-chain evidence. Repair/rollback must match the recorded pin and revocation policy. Activation/recovery use an OS lock and atomic metadata replacement. XACE keeps last-known-good metadata, never copies binaries, and refuses rollback if the original artifact is no longer available.

The policy's version/digest revocation lists ship with XACE updates; no automatic network updater is implied. Native platform parsing does not claim tested support on every platform. See `docs/CODEX_RUNTIME_GUIDE.md`. The managed acquisition prerequisites above remain prerequisites to any future change, not hidden work in the completed guided fallback.

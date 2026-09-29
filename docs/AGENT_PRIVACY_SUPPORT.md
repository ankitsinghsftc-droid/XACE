# Agent privacy, diagnostics and support (AG-028)

This policy covers XACE's Codex Agent integration only. It does not certify the whole XACE product, introduce general telemetry, change API/BYOK defaults or resolve AG-029/030's real-runtime certification requirements.

## Local workflow

Open **Agent → Set up Codex → Agent privacy and support**.

1. **View local diagnostics** reads a content-free snapshot. It does not start Codex, refresh authentication or call the provider.
2. Confirm collection and choose **Prepare support preview**. Inspect the complete JSON shown in the panel; it is not a summary hiding additional attachments.
3. Separately confirm that you reviewed the preview, then choose **Download reviewed support bundle**. The server returns the exact cached preview bytes; the browser checks equality before creating the download. Changed, missing, expired or consumed previews fail closed.
4. Share the downloaded file yourself through a trusted support channel if needed. There is no automatic upload, email, issue creation, remote collector or telemetry endpoint.
5. **Clear local support previews** clears this Builder server's pending preview cache and the panel display. It does not delete downloaded files, chat history, provider data or game changes.

These controls are local operator routes protected by the same loopback, same-origin and custom-header requirements as setup/authentication. They are not agent tools. Requests cannot supply arbitrary file paths, provider methods, extra attachments or options to include prompt content. Responses use `no-store`, and downloads have a fixed filename and `nosniff`.

## What is included

The versioned `xace.agent_diagnostics.v1` snapshot includes the XACE Agent build identifier; selected Codex version and categorical provenance; generated-schema fingerprint; runtime setup state; cached auth/login state (not identity); compatibility state; provider connection/turn counts; last observed MCP status; store schema availability and last store-operation failure flag; and the last XACE proposal-validation outcome/code. Error codes are drawn from a fixed allowlist; unknown codes become `unknown_error`.

There are seven separate diagnostic categories: runtime, auth, compatibility, provider, MCP, persistence, and validation. Unknown/not-observed states are explicit. Snapshots are point-in-time observations, not continuous monitoring or proof of current provider availability. MCP state/error categories may describe the last observed failure after a connection closed. Persistence checks read only SQLite schema metadata with a short read-only connection, not chat/events/proposals or audit files. They do not constitute a full database integrity audit.

`xace.agent_support_bundle.v1` wraps that snapshot. Each preview has an opaque ID and SHA-256 digest; no raw collector dictionaries are copied into the export.

## What is excluded

Support bundles exclude prompts, responses, chat/session history, project contents, CGS hashes, proposals, tool arguments/results, mutation payloads, account identity/email, credentials, tokens, login URLs/device codes, provider auth files, filesystem paths, environment variables, raw logs, session/thread IDs and stack traces. The exporter never invokes the existing full session-export feature. Collector exceptions produce fixed unavailable/error states rather than exception text.

This is data minimization by construction, not a promise that a regex can detect every secret. The existing durable chat-history feature can retain user-entered sensitive text; do not paste credentials into prompts. Support exports avoid that risk by excluding all free-form chat/project/log content.

## Retention and deletion

- **Live diagnostics:** collected on explicit request and returned to the local panel; no diagnostic log file, database row or remote telemetry is created. Counters/outcome flags are in-process only and reset on restart.
- **Support previews:** at most four, each at most 16 KiB, in server memory. Export authorization expires after five minutes. Expired entries are pruned on the next prepare/export operation; bounded expired bytes can remain in memory until then, Clear, or server shutdown. Export consumes its preview. The browser clears prepared content after export, Clear, expiry or unmount; it writes no local/session storage.
- **Downloaded support files:** retained by the user/browser wherever the browser saves them. Delete them through the OS/browser when no longer needed. Clearing XACE previews cannot delete downloaded copies or copies already shared with someone else.
- **Existing Agent chat/audit history:** remains in the selected project's `.xace/agent_sessions/` directory (SQLite, possible WAL/SHM sidecars and optional JSONL audit). It is retained until explicitly removed; AG-028 does not silently purge it. To remove it, first close XACE and related Agent sessions, verify the exact project directory, back up what you need, then remove only that project's Agent-history directory. Treat backups as equally sensitive. This loses XACE Agent history/resume/lineage records; it does not undo committed game changes or erase provider-side threads. Do not delete a live SQLite database or just one of its related files.
- **Context Capsules:** project-derived snapshots under `.xace/agent_capsules/` are separate from support data. With XACE/Agent sessions closed, verify the selected project and remove only those capsules if you intend to discard them. Existing provider resumes may require a newly generated capsule/session afterward.
- **Runtime metadata/generated schemas:** stored separately in the XACE runtime-state directory. They contain local runtime paths and software schema evidence, not credentials. Support includes only the selected version/provenance and schema fingerprint, never the paths or full schema documents.
- **Provider credentials/history:** remain provider-owned. XACE support Clear does not delete them; use provider-supported controls. Signing out should not be treated as a guarantee of history deletion.

If the Builder server cannot start because its existing history store is corrupt, the in-app exporter is unavailable. Preserve the affected directory and use the backup/recovery procedure; do not bypass store checks or attach the database by default.

## Ownership and incident response

The **XACE Agent integration maintainers** own the bundle schema, allowlist, local lifecycle, redaction tests and runtime/MCP/validation triage. Provider authentication, entitlement, limits and provider-side data remain the provider's responsibility. The user controls export and sharing. No staffed support channel or response-time guarantee is implied by this implementation.

For an Agent incident:

1. Stop the affected turn. Keep API/BYOK available and preserve the preview/approval boundary; never bypass runtime compatibility/security checks to reproduce a failure.
2. Prepare a fresh content-free bundle, inspect it and share only the minimal file with trusted maintainers. Identify the diagnostic category before asking for more evidence.
3. Reproduce in a disposable project with synthetic data. Do not request auth files, bearer tokens, raw project databases, prompts or full log archives as a default troubleshooting step.
4. If the user deliberately supplies additional sensitive evidence, agree on its purpose, access restrictions and deletion before receiving it. This bundle flow does not collect such attachments.
5. If a credential was exposed outside this bundle workflow, stop sharing, revoke/rotate it through its owner, restrict/remove shared copies and investigate. Removing a local preview is not credential revocation.
6. Maintainers should retain a shared bundle only for the active investigation and remove their working/shared copies within 30 days of closure unless the user expressly agrees otherwise. This is an operational requirement, not an automated retention promise: XACE has no control over recipient systems or their backups.

## Verification and remaining scope

Thirteen focused backend tests cover canaries, strict field projection, all seven categories, two consent gates, exact reviewed bytes, single-use exports, TTL/cache bounds, clearing, collector exceptions, no implicit file/provider access, metadata-only store health, validation privacy and local route/body guards. The real-browser fixture additionally verifies full preview display/focus, separate download consent, export consumption, clearing and absence of browser-storage persistence.

Real-account certification remains AG-029. The incompatible development runtime and App Server provider-support caveat from AG-027 are not waived by these diagnostics. AG-030 remains the Codex-only completion gate; whole-XACE launch readiness is separate.

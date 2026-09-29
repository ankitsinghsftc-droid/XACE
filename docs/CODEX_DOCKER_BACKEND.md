# Codex Agent Mode: first supported execution backend

Decision: AG-029, 2026-09-22, explicitly approved by the product owner.
The first supported configuration is Windows x64 with Docker Desktop's local
Linux/WSL 2 backend and the verified official Codex 0.155.1 Linux x64 runtime.
Native Windows isolation is deferred, not a prerequisite for Codex integration.
This is not certification of every OS, account, model, or the whole XACE product.

## Setup

1. Install/start Docker Desktop with WSL 2 and Linux containers. Use its local
   `desktop-linux` context; remote daemons and Windows containers are rejected.
   Follow [Docker's Windows prerequisites](https://docs.docker.com/desktop/setup/install/windows-install/)
   and [WSL guidance](https://docs.docker.com/desktop/features/wsl/), including
   virtualization and supported Windows/WSL versions. Check Docker's applicable
   subscription terms; it is not free for every organization or use case.
2. Recommended terminal-free path: in Builder Codex setup, click **Download official pinned Codex archive**, save it, use Windows **Copy as path**, paste into **Downloaded .tgz archive**, confirm the local build and click **Build / repair isolated runtime**. The server verifies the copied archive bytes and fixed recipe, builds locally, and selects the immutable image. You can cancel before activation; failures preserve the previous selection. Then continue with step 4.

   Optional operator alternative: obtain the official pinned package without installing a global CLI:
   `npm pack @openai/codex@0.155.1-linux-x64 --ignore-scripts`.
   This is the Linux package version of `@openai/codex`, not a separately named
   npm package. Keep the resulting archive outside game projects.
3. From the XACE checkout run:
   `python tools/codex_backend_setup.py --runtime-package <absolute-tgz-path> --confirm-local-build`.
   The explicit local build verifies the official archive SHA-512, uses a
   digest-pinned Python base, builds locally, and atomically selects the full
   image SHA-256 in `%LOCALAPPDATA%/XACE/agent-execution/backend.json`.
   It does not install Docker/WSL, copy credentials, or publish/bundle an image.
4. Open XACE Codex setup and refresh/recheck the execution backend. Choose
   **Sign in with device code**, complete the official provider page, and wait
   for signed-in status. Then choose **Use Codex and focus prompt**.
   Authentication, discovered models, subscription usage/limits and threads
   are provider-managed. Do not enter API keys, passwords or tokens into chat.

AG-030 adds terminal-free local provisioning to Builder and verifies both its
browser controls and the actual protected build route. Docker/WSL installation
remains an external prerequisite; whole-product distribution UX is not claimed.
No automatic runtime download, public redistribution or silent update is enabled.
The builder remains on Windows; only the provider process runs in isolation.

## Persistence, updates and recovery

The dedicated Docker volume `xace-ag029-provider` is retained deliberately to
preserve the existing provider-owned login and native thread history without
credential copying. The name is a compatibility identifier, not a test-only
authentication path. XACE never reads its auth files. Provider auth/session
state belongs to Codex; structured XACE chat, events, tools and proposal lineage
remain in the project's existing SQLite session store. Sign-out is explicit
and affects XACE clients sharing this volume, not the separate VS Code store.

If Docker/WSL is absent, stopped, unreachable, uses the wrong context, or the
image/policy/pin is missing or invalid, Codex stays unavailable with a setup
message. Start/repair that dependency and refresh. There is no automatic global
CLI, native Windows, API, or unsafe credential-store fallback. Switching to
API/BYOK is explicit and preserves existing provider settings; API/BYOK remains
the unchanged default. Failed operations are not automatically replayed.

Repair the same version by repeating the verified local build. Build failure
preserves the previous pin; metadata retains the previous image identity and
no old images or auth volumes are deleted. New Codex versions require explicit
package, binary, stable-schema and isolation recertification before changing
the source pin. Existing native CLI update/remove controls are hidden for this
backend; they must not modify an unrelated executable or delete provider state.
Restart/resume recovers persisted threads after owned process interruption.
Quota exhaustion is provider-reported: wait for reset or explicitly use API/BYOK.

## Architecture and security

`AgentExecutionBackend` owns execution health and client creation. The Codex
adapter owns auth, lifecycle, sessions, native events and cancellation; MCP
remains the reusable provider-neutral XACE tool contract. Docker commands,
paths, image identity and the private multiplexed transport stay below these
interfaces. A later native Windows backend can implement the same contract
without changing Agent requests, Builder APIs, proposals, GDE or runtime.

Normal Builder startup, registry, status/auth and setup all select the same
isolated adapter. Its container is non-root with read-only root, dropped
capabilities, no-new-privileges, resource limits and a pinned seccomp policy.
Only the generated capsule tree and trusted Builder server code are mounted
read-only; no real project root, host credential directory, Docker socket,
published port, privileged mode or host networking is exposed. Native
permission profiles restrict model tools to the current capsule and fixed
runtime/platform files. Native shell execution is disabled; measured native
patch attempts cannot write the capsule or read/write private provider files.

The trusted host MCP endpoint is bound by XACE, never selected by the container
or model. A bounded authenticated stdio relay avoids exposing host network
ports and keeps the host MCP token outside container arguments/environment.
Only the owned random-name provider container is stopped during cancellation;
the persistent provider volume is not deleted.

The boundary is unchanged:
agent -> XACE tools -> typed proposal -> preview -> user/XACE approval ->
GDE -> SGC -> runtime. No direct commit or runtime mutation is granted.

The seccomp asset derives from [Moby's default profile](https://github.com/moby/profiles/blob/main/seccomp/default.json)
(upstream Apache-2.0; retain its attribution when distributing). The inspected
upstream SHA-256 was `785b2429264afba4d594320337cb17f144f3c7d51585f9805eef72e28f4f9334`.
The modified asset SHA-256 is
`cb584107039743dbdfd16ca124b8813d21fc3b2ea9b3e8ca86c9233233dad859`.
It permits clone/unshare/mount/umount2/pivot_root/setns for nested unprivileged
isolation, without granting host capabilities; other default denials remain.
This is a measured isolation profile, not a formal proof against kernel flaws.

[Official App Server documentation](https://learn.chatgpt.com/docs/app-server)
describes the provider-native interface and its experimental support caveat.
AG-029 establishes empirical compatibility for the pinned configuration, not
an upstream production-support guarantee. AG-030 records product-owner acceptance
for development/early users only. See [exact dependency surfaces and risks](CODEX_APP_SERVER_SURFACE.md).
Public-production launch requires a new upstream maturity and isolation review.

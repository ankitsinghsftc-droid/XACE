# Codex runtime setup and lifecycle

AG-029 update: the first supported production-selected Agent backend is Windows
x64 with Docker Desktop / WSL 2 and a locally built pinned Codex Linux runtime.
Use [the current Docker backend setup and recovery guide](CODEX_DOCKER_BACKEND.md).
Builder setup/auth/status/sessions use that backend consistently. AG-030 adds
a consent-based **Build / repair isolated runtime** flow for the verified
official .tgz archive; first provisioning no longer requires developer commands. No global
Codex installation is required. Missing dependencies leave Agent unavailable;
API/BYOK remains the unchanged default. Native Windows isolation is deferred.

The instructions below are retained for explicit native CLI development and
historical AG-024 context, not the current Builder production setup path.

## Historical native runtime lifecycle (AG-024)

The earlier native runtime path uses an explicitly selected, user-owned official Codex executable.
Automatic SDK acquisition remains disabled: the reviewed public SDK documentation
describes its pinned runtime but does not document a supported executable-location
API for XACE's direct App Server client. XACE does not scrape package internals,
copy extension binaries, own credentials, or change API/BYOK defaults.

## Operator workflow

Run these commands from the XACE repository. They are operator commands, never
Builder Agent tools. AG-026 owns the later functional setup/recovery UI.

1. Run `python tools/codex_runtime.py guide install` for official provider
   installation instructions. Review and run the installer yourself outside your
   project. XACE does not download or execute installer scripts.
2. Find the actual native executable installed by that provider channel (not a
   shell wrapper or private editor-extension executable).
3. Run `python tools/codex_runtime.py install <absolute-executable-path> --confirm-official-install`.
   Optional `--expected-version` and `--expected-sha256` enforce independently
   obtained evidence before activation. Confirmation means you trust the source;
   it does not manufacture publisher-signature verification.
4. Run `python tools/codex_runtime.py inspect` to inspect the local pin.

The global `--state-dir <directory>` option precedes the subcommand. Builder
resolution uses `XACE_CODEX_RUNTIME_DIR` when configured; otherwise both use
`~/.xace/codex-runtime`. A CLI-only custom state directory must also be configured
for Builder to select it.

## Updates and recovery

- `guide update` describes provider-owned installation. Preserve the old
  installation at its original path if rollback is needed. Run `update <new-path>
  --confirm-official-install` only after installing the new version yourself.
- `repair <path> --confirm-official-install` requires the active pin's exact
  version, digest, and generated schema. Restore the exact original provider
  artifact yourself first. A different release requires explicit update.
- `rollback` revalidates the last-known-good path, version, digest, platform,
  schema, and revocation policy before selecting it. An overwritten or deleted
  old executable cannot be resurrected by metadata; obtain the original
  provider artifact or explicitly select a newly verified release.
- `remove` deactivates XACE's selection. It does not delete any executable,
  credential, project, or unrelated file. Audit history remains.
- `recover` discards incomplete operation metadata under an OS lock; it cannot
  steal a live operation. The last atomic state remains authoritative.

An invalid, revoked, or explicitly removed selection suppresses implicit PATH
fallback. Explicit `XACE_CODEX_APP_SERVER_BIN` / `XACE_CODEX_EXECUTABLE` overrides
remain development/operator paths, not verified lifecycle pins. Removing such
an override is necessary to use the managed selection metadata.

## What verification establishes

Native headers must match the current OS and CPU: Windows PE, Linux ELF64
little-endian, or macOS thin Mach-O64, on x86_64 or aarch64. Wrappers, universal
Mach-O, other architectures, and private editor-extension paths are rejected.
This is binary-format validation, not certification of all these platforms.

XACE verifies a stable version and SHA-256 before/after schema generation. It
generates stable App Server JSON schemas with the public command, checks required
method declarations, and fingerprints the complete sorted document bundle.
Repair and rollback require equality with the recorded schema. Normal adapter
health/native-MCP checks still determine whether Agent Mode can actually run;
schema availability alone is not authenticated end-to-end certification.

The pin is local integrity evidence. Provenance is explicitly
`user_confirmed_official_install`; `vendor_signature_verified` remains false.
The versioned distribution policy carries revoked version/digest lists (initially
empty), enforced during activation and each pinned executable resolution.
Activation replaces a flushed metadata file atomically. A persistent OS lock
serializes writers and recovery. No runtime is copied or deleted by XACE.

Provider sources: [SDK documentation](https://developers.openai.com/codex/sdk)
and [installer environment contract](https://developers.openai.com/codex/config-file/environment-variables).
The installed development CLI's schema-generation help and 305 generated schema
documents were checked locally; that private runtime was not activated.

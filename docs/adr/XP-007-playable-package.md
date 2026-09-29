# XP-007: verified native playable packages

Status: implemented, 2026-09-29. Windows x64, native headless runtime profile.

The package carries authoritative CGS, actual Schema Factory projection, persisted
SGC plan, compiled World Contract and provenance manifest, a pinned native runtime,
and separately indexed presentation variants. World v2 remains readable; v3 retains
project schemas, properties, capabilities, relationships, assets and instance bindings.
No game noun or reference mechanic receives privileged package/runtime dispatch.

## Contract and trust

`packages/project-system/playable_package.py` defines `RuntimeSupport`,
`compiled_artifacts`, `build_package`, `verify_archive`, `install_archive` and
`runtime_command`. Manifest version is `xace.playable_package.v1`. Trusted callers
register the executable digest, ABI, exact executor contracts and supported profiles;
package assertions cannot extend host support. Registration must describe an actual
reviewed host build. This is integrity/admission, not publisher signing.

Verification recompiles CGS through Factory and compares authoritative artifacts.
`sgc_identity.py` recomputes Rust SGC input, plan and validation identities, alongside
the existing persisted-plan validator. It does not schedule systems. Gameplay hash
pins schema/world/plan/runtime/executor/input/event identities. Presentation variant
content is separately indexed; changing only those bytes preserves gameplay hash.
Changing authoritative CGS still changes gameplay identity.

ZIP construction is deterministic. Import/verification execute no package code.
Archives have bounded count, per-file and expanded size; paths reject traversal,
absolute paths, Windows devices/ADS, normalization, duplicates and case collisions.
Links and special files are rejected. Asset locations must reference packaged
presentation resources. Installation verifies a staged tree, retains content-addressed
versions and replaces the active pointer only after verification. Interrupted staging
or pointer replacement retains the previous active package.

## Runtime integration

`world_loader.rs::bind_compiled_world` validates version, provenance and actual
spawned actor-instance bindings before installing semantic/query metadata. CLI
`--world` and `--world-manifest` must be paired and use a persisted SGC plan.
Snapshot restore preserves same-ruleset immutable bindings while invalidating query
caches. Direct CGS hot reload involving compiled worlds fails closed until XP-018
provides a staged world migration/activation transaction.

`runtime_command` verifies installed files and returns native launch arguments; it
does not launch code. The relocated execution proof explicitly launches the pinned
host. Stock runtime support remains its registered executors. Reference gameplay
requires a reviewed host build registering that ordinary package system, not a
wall-run branch in core. XP-008 owns that integration with real Player input.

## Limits

This release verifies a Windows headless package moved to another folder on the same
host, with Python/Rust toolchains removed from the child PATH. It is not clean-machine
installation or graphical Player certification. Player lifecycle, presentation format
readiness, distribution signing and live session activation remain later tasks.
Presentation metadata does not certify a native importer. New semantic nouns need
project schemas; new executable solvers/importers still need implementations and
explicit host support. No extra game mechanic was implemented to prove extensibility.

# XP-010 distribution and local launch contract

Status: implementation verified on this host, 2026-09-30. Clean-machine acceptance pending by owner instruction.

A trusted release distribution contains the exported Player, PCK, already admitted
package, notices and checksums. The authoring build pins Godot/template version and
SHA-256. The recipient never runs a source build or needs Python, Node, Cargo or an
engine editor. Checksums establish consistency with the explicitly trusted release;
unsigned local bundles do not establish publisher authenticity.

The native broker accepts bounded JSON commands over inherited private stdin/stdout
pipes, carrying a fresh launch capability. It has no public control socket. A Windows
kill-on-close Job Object owns the Player and its descendants. Player waits for a
broker gate before starting the authority so ownership precedes authority creation.
Repeated Play reuses a running child. Exit, failed readiness, Stop, EOF and broker
termination clean the owned tree. Other processes are never terminated by port/PID
search. A dynamic loopback port avoids default-port conflicts; readiness must come
from this launch's token-bound Player status, not a listening stranger.

Installation verifies every declared byte, rejects unsafe paths/symlinks, stages an
immutable content-addressed version and atomically replaces a small active pointer.
Failed preparation leaves the prior pointer. Launch rechecks bytes to reject stale
binaries. Retained versions permit rollback. Builder selects its verified local installation or an explicitly configured
trusted distribution and compares the admitted package CGS with the current saved
project before launch; stale authoring requires publishing a fresh package. Builder
materializes the verified distribution into its local install, without running an
engine export or compiling code during Play.

Builder control routes require the existing local-operator guard, JSON content type
and a per-process capability. UI shows preparing/starting/playing or actionable retry.
This is local distribution/launch, not authenticated multiplayer session admission.

A clean Windows-machine record is required before XP-010 is marked complete.
Same-host tests with restricted PATH are separately labeled and insufficient.

## Interfaces and trust placement

`xace.player.distribution.v1` declares platform, version, CGS/gameplay hashes and a
sorted file table of safe relative paths, SHA-256 and sizes. `distribution.trust.json`
is publisher-supplied local release metadata, not package-controlled executable trust.
Checksums do not replace a future code-signing or authenticated-download policy.

`XACE Play.exe` with no arguments stages the adjacent release under
`%LOCALAPPDATA%/XACE/Player`, launches its Player and waits for exit. A failure shows
a desktop error dialog. `--serve` exposes only inherited JSON stdin/stdout; each
request has schema `xace.player.broker_request.v1`, capability and action
`play|status|stop`. Ready replies use `xace.player.broker_ready.v1`. The optional
preferred port falls back to a fresh loopback port when occupied.

Player accepts an owner gate and writes `xace.player.launch_status.v1` containing the
fresh launch token. First authoritative tick establishes readiness. The broker then
atomically commits `active.json`; earlier failures retain its prior bytes. All
children inherit the Windows Job Object. Stale installs are quarantined and replaced
from verified release bytes. The install lock is a Windows exclusive file handle,
so a dead process cannot permanently own a stale lock file. No other PID is searched
for or killed. A prior *running* game is not hot-swapped by a new package.

Builder discovers only the dedicated local Player registry, validates its digest
and broker bytes, compares full saved CGS data and the UI's current hash, and uses
its own install cache. Explicit publisher configuration uses `XACE_PLAYER_RELEASE`,
`XACE_PLAYER_RELEASE_SHA256`, `XACE_PLAYER_BROKER_SHA256`. Project files and HTTP
requests never choose an executable. `/api/player` grants the local browser a
per-server capability; `/api/player/{play|stop|status}` requires it plus the local
operator/origin guard. Server shutdown closes the native broker's pipe.

## Boundaries

Play consumes an already published/admitted game release. It does not silently
compile changed gameplay or fall back to the reference demo. Stale saved games
receive an instruction to publish an updated package. The Builder preview remains
a separate view; Player input and rendering are in its native window. This release
does not add in-Player pause/step controls, remote control, package hot swap or
multiplayer admission. No gameplay nouns or mechanics appear in the launch APIs.

Pinned build: Godot 4.6.3 official `7d41c59c4`, Windows x86_64 release template
SHA-256 `91724f15024a3a545e28ccd83134403d31ce2323a38e51c95e4dfa282f732ab6`.
Assembly uses the explicit XP-008 export preset and includes runtime, engine notices,
Rust dependency license files, checksums and a recipient README. License export
uses the pinned engine's introspection APIs documented at
https://docs.godotengine.org/en/4.6/classes/class_engine.html.

See `../XP010_COMPLETION.md` for scoped evidence and the remaining clean-machine gate.

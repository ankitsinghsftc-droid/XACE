> Reconstructed historical document. Original evidence is missing; fresh recovery verification is pending. See AGENT_PROGRESS.md. Do not reuse historical disposable paths for new unique evidence.

# XP-021: generic creator replay inspection

Implemented and locally verified on 2026-10-04 in `target/xp016-work`. No commit,
push or protected-ref update was performed.

## Creator behavior

The existing `TickDebugger` opens the new `ReplayInspector` in recording mode by
default. Creators can select or open a saved recording, capture an isolated copy
of a running authority, find an event, select its frame and object, inspect the
recorded data, verify replay, export a support summary and return to live view.

The generic view shows session/ruleset markers, migration frames, input packets,
component fields (including contact/counter/velocity fields when recorded by the
package), semantic world objects/capabilities and declared system dependencies
and component access. Event labels come from optional package metadata
`metadata.event_labels`, falling back to the package's event identifier.
Technical data is collapsed behind a toggle; errors explain how to recover.

The existing live causality/RNG panels remain available in live view. The replay
inspector distinguishes recorded state and declared dependencies from exact query
or RNG-call traces that XP-020 did not record. It does not fabricate those traces
or infer mechanic-specific causes. The reference fixture's fields are inspected
through the same component-table view as arbitrary project component fields.

Inspection breakpoints now stop local timeline following only. They no longer
send an implicit pause to the authority. Ordinary old debugger control buttons
direct creators to the explicit session-control section. The runtime's new
read-only `ruleset.inspect` reports current contract/phase and the pending
activation tick, allowing an “applying at frame N” message.

## Isolation, permissions and retained evidence

`server/replay_debugger.py` exposes bounded recording IDs, inspection, offline
verification, capture, import and support export. Requests cannot select server
filesystem paths or executable paths. Imported filenames are ignored; the file's
SHA-256 determines its ID. Changed files and unsupported formats fail closed.
The inspector labels data as unverified until the separate historical verifier
has run; exported summaries include a retained verification report when available.

Verification uses only operator-configured historical hosts whose executable hash
matches the recording. XP-020 performs schema/digest/artifact/journal validation
and reconstruction in a fresh scratch fork. A single verification runs at a time,
with a bounded timeout; it opens no live control/engine connection. Failures leave
the authority running. Discarding inspection drops the UI selection; generated
fork artifacts are retained for operator inspection, not recursively deleted.

The runtime's `ruleset.export_replay` takes no paths. It seals a completed prefix
under the trusted ruleset root's `replays` directory and returns its content ID.
Hosts launched with `--ruleset-root` enable recording at startup. Export does not
rewind, pause or restore the world. Empty/incomplete captures fail visibly, and
the existing XP-020 size/tick limits apply; at most 64 exports occupy this catalog.

Creator pause/resume requires a server-configured creator key and explicit
session-wide confirmation. Client-supplied roles grant no authority. Missing or
wrong keys are refused by the server. The old WebSocket runtime-control route is
also gated in the Builder application, as are shared demo authority start/stop
routes. Status/snapshot inspection remains read-only. Live restore is deliberately
unavailable in the inspector; historical seeking uses isolated replay forks.

This is the local Builder control boundary, not a claim of repository-wide
multi-user authentication or Internet hosting certification.

## Trusted host configuration

The launcher/operator configures these process settings, never a gameplay package
or browser request:

- `XACE_REPLAY_ROOT`: recording catalog. Defaults to the opened Builder project's
  `.xace/replays`. For live capture it must identify `<host ruleset root>/replays`.
- `XACE_DEBUGGER_HOSTS`: trusted historical executable paths separated by the
  platform path separator (semicolon on Windows). Each is hash-checked before use.
- `XACE_CREATOR_CONTROL_TOKEN`: creator control credential. Without it, session
  controls fail closed. Creators enter the key in the session-control section;
  it stays in the mounted component's memory and is not included in support exports.

Saved recordings can be opened through the file picker. No original host binary
is executed merely by opening a recording; verification is a separate action.
Automatic installation/discovery of historical executable versions is not added
by this task. A missing host produces an actionable refusal.

## Verification

The real-browser harness uses the production inspector, real HTTP endpoints, the
actual archived XP-020 host for verification and a separate running authority.
It finds the reference event at frame 9/epoch 1, inspects its surface capability,
contact, counter and velocity fields, verifies replay, exports a proof summary,
returns to live, captures/verifies a fresh live copy and returns again. The
authority advances throughout; guest pause is refused and explicit creator
pause/resume succeeds. This is an automated creator walkthrough, not the
first-time human usability trial reserved for XP-022.

Results and fingerprints are retained in `docs/evidence/xp021-baseline.json`.
Generated browser profiles, screenshots, recordings and forks stay under ignored
`target/xp021/`.

| Gate | Result |
| --- | --- |
| Runtime regression | 842 passed |
| Reference package/replay/fault regression | 22 passed |
| Debugger navigation/import/export/permission tests | 9 passed |
| Existing gameplay authoring regression | 10 passed |
| TypeScript/Vite build and existing Builder UI contracts | Passed |
| Actual browser + historical verifier + running authority | Passed |

Reproduce with `python -m tools.xp021_debugger_proof --out target/xp021/new-proof`
after building the production reference host and retaining XP-020's certified
recording and archived host. Server tests run through unittest discovery using
`test_replay_debugger.py`; Builder build/UI gates use its existing npm scripts.

Certification is local Windows only. Earlier clean-machine, two-machine, public
relay/two-network and missing-cosmetic startup gates remain pending. XP-022 is next.

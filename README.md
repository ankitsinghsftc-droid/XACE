# XACE

XACE is an in-progress schema-driven gameplay-core platform. It helps a
developer describe, validate, version, compile, and run supported gameplay logic
through a Canonical Game Schema (CGS), a Rust runtime core, and engine adapters
for Godot, Unity, and Unreal.

XACE is not a game engine. Rendering, animation, art pipelines, physics scenes,
packaging, store builds, and engine-native content still belong to the engine
and the game team. XACE's current launch-readiness work is focused on the
portable gameplay core, adapter protocol, Builder workflow, and certification
smokes needed before real users should depend on it.

## Current Boundary

The current public claim is intentionally narrow:

- XACE can create local CGS-backed projects from supported templates.
- Builder can wrap or link an existing engine project by creating a XACE project
  manifest and preparing starter adapter files.
- The export flow copies an adapter package for engine-owned integration. It is
  not a finished-game shipping pipeline.
- The prompt path supports certified mutation scenarios and blocks unsupported
  broad requests.
- The System Graph Compiler CLI has been repaired and smoke-tested with a small
  fixture. Full prompt-to-SGC-to-runtime production proof is still pending.
- Runtime determinism, replay, mutation safety, and adapter bridges have
  foundations and targeted tests, but live end-to-end enforcement still has open
  proof gates.
- Network work is currently network primitives and local smokes: host/client
  lifecycle, lockstep input, prediction/reconciliation, desync detection, and
  digest checks. It is not a complete shipped multiplayer stack.
- Portability means gameplay-core portability through CGS and adapters. It does
  not mean automatic migration of every finished game asset, scene, script, or
  engine-native feature between engines.

The single execution contract is
[`docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`](docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md).
The frozen commercial launch model is
[`docs/XACE_COMMERCIAL_SCOPE.md`](docs/XACE_COMMERCIAL_SCOPE.md).
The source-of-truth path inventory is
[`docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md`](docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md).
The fake/skip/stub/smoke register is
[`docs/XACE_FAKE_AND_SKIP_REGISTER.md`](docs/XACE_FAKE_AND_SKIP_REGISTER.md).
The production/test/demo boundary rules are
[`docs/XACE_PRODUCTION_PATH_RULES.md`](docs/XACE_PRODUCTION_PATH_RULES.md).
The shorter claims checklist is
[`docs/XACE_PRODUCT_CLAIMS_MATRIX.md`](docs/XACE_PRODUCT_CLAIMS_MATRIX.md).

## Architecture

```text
User intent
  -> Prompt Intelligence Layer   [Python]
  -> Game Definition Engine       [Python]
  -> Schema Factory               [Python]
  -> System Graph Compiler        [Rust]
  -> Runtime Core                 [Rust]
  -> Engine Adapter Protocol      [Rust + engine language]
  -> Game Engine                  [Godot / Unity / Unreal]
```

## Core Pieces

**Prompt Intelligence Layer**

Receives natural-language requests and routes only supported scenarios through
guarded planning, validation, and review. It should not be described as
open-ended game or system creation.

**Game Definition Engine**

Owns CGS mutation application, path validation, consistency checks, and
clarification flow. Schema changes should pass through this layer instead of
direct ad hoc writes.

**Schema Factory and SGC**

Compile schema data into execution-plan inputs. The SGC library and CLI now have
working proof points, while the broader production path still needs the remaining
master-plan gates.

**Runtime Core**

Provides tick-driven runtime foundations, entity/component storage, mutation
gating, phase orchestration, snapshots, replay/hash utilities, and adapter
protocol payloads. Current claims should say "foundations" or "targeted proof"
unless the master plan marks the live proof complete.

**Engine Adapters**

Bridge runtime deltas and engine feedback for Godot, Unity, and Unreal. Adapter
packages are integration handoffs for engine projects; they are not complete
game exports.

## Import And Export

Import means "wrap/link an existing engine project." XACE creates or updates a
project manifest, starter CGS files, launcher state, and adapter preparation
where supported. It does not reverse-engineer an existing Unity, Godot, or Unreal
game into CGS automatically.

Export means "export/copy an adapter package." The receiving engine project
still owns build settings, scenes, assets, packaging, platform SDKs, QA, and
release.

## Multiplayer Scope

Use "network primitives" for the current multiplayer-related work. The network
core has local proof points for lockstep-style input release,
prediction/reconciliation, desync detection, session lifecycle, and deterministic
digests. Shipped game networking still needs topology, security, chaos, soak,
platform, and engine-installed proof.

## Portability Scope

Use "gameplay-core portability" for the current cross-engine claim. CGS,
runtime payloads, and adapters can make supported gameplay definitions portable
across adapter targets. Finished-game portability remains out of scope until
engine-native content, build pipelines, assets, input maps, scenes, physics
settings, and platform services are proven.

## Prompt And AI Scope

The prompt workflow is a guarded editing surface over supported CGS mutation
categories. It should ask clarifying questions, show diffs, block unsupported
requests, and preserve project state. It should not promise unsupported gameplay
systems from open-ended text.

## Verification

Useful local checks:

```powershell
python tools/forbidden_claims_check.py
python tools/sgc_cli_smoke.py --json
cargo test -p xace-system-graph-compiler
```

For launch-readiness sequencing, follow the master plan rather than this README.

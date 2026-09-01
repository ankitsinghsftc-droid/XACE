# XACE

XACE is an in-progress schema-driven gameplay-core platform. It helps a
developer describe, validate, version, compile, and run supported gameplay logic
through a Canonical Game Schema (CGS), a Rust runtime core, and engine adapters
for Godot, Unity, and Unreal.

# XACE

### Build gameplay as a system — not as a pile of engine-specific code.

**XACE is an AI-native, engine-independent gameplay platform for building, running, mutating, debugging, replaying, and networking game logic on top of a deterministic authoritative runtime.**

It is not another AI chatbot inside a game engine.

It is not a one-prompt game generator.

And it is not a replacement for Unreal, Unity, Godot, Blender, or your content pipeline.

XACE is the **gameplay layer beneath them**.

---

## Why XACE exists

Modern AI can write C++, C#, Blueprints, shaders, scripts, and entire gameplay systems astonishingly quickly.

That creates a new problem:

> **We can now generate game logic faster than humans can safely understand, maintain, debug, synchronize, and evolve it.**

XACE is built around a different model:

```text
Human intent
     ↓
AI / Agent
     ↓
Typed gameplay proposal
     ↓
XACE validation
     ↓
Canonical Game Schema
     ↓
System Graph Compiler
     ↓
Deterministic Runtime
     ↓
Unity / Unreal / Godot / XACE clients
```

The governing rule is simple:

> **AI proposes. XACE authorizes.**

AI can be incredibly powerful without becoming the authority over the game.

---

# What XACE actually is

Instead of allowing authoritative gameplay to become scattered across scripts, Blueprints, prefabs, scenes, server code, plugins, and generated files, XACE represents gameplay through a canonical semantic model.

That model is compiled into an explicit execution plan and executed by XACE's authoritative runtime.

The engine becomes primarily responsible for things engines are already excellent at:

* rendering
* animation
* audio
* editor tooling
* content
* platform integration
* engine-native presentation

XACE owns the **gameplay truth**.

That separation enables capabilities that become extremely difficult when gameplay authority lives inside one engine's scripting model.

---

# Core Architecture

### Canonical Game Schema — CGS

A versioned, canonical representation of gameplay containing concepts such as:

* entities and actors
* components and state
* gameplay systems
* events
* execution phases
* read/write relationships
* dependencies
* rules
* semantic asset bindings
* gameplay metadata

Gameplay becomes structured data with stable identity rather than an opaque collection of source files.

---

### System Graph Compiler — SGC

XACE converts declared gameplay systems into a persisted deterministic execution plan.

It understands:

* dependencies
* execution ordering
* read/write relationships
* conflicts
* system identity
* structural changes
* validation requirements

The execution model is explicit, inspectable, and reproducible.

---

### Deterministic Authoritative Runtime

The XACE runtime is responsible for authoritative gameplay execution.

It provides foundations for:

* fixed-tick simulation
* deterministic execution
* authoritative state
* deterministic RNG
* event windows
* entity/component storage
* world hashing
* snapshots
* replay
* rollback
* mutation boundaries

The goal is not merely to make gameplay run.

The goal is to make gameplay **explainable, reproducible, and trustworthy**.

---

# Safe AI-Native Development

XACE treats an AI model or coding agent as an **untrusted proposal source**, not as the project authority.

An AI-generated change moves through:

```text
Intent
  ↓
Structured proposal
  ↓
Typed operations
  ↓
Validation
  ↓
Preview / Diff
  ↓
Approval
  ↓
CGS mutation
  ↓
Compilation
  ↓
Runtime validation
  ↓
Replay / Proof
```

An AI should not need permission to silently rewrite hundreds of authoritative gameplay files and hope the project still works.

XACE gives powerful models a controlled environment in which to operate.

---

# Agent-Native

XACE is being designed around **bring-your-own-agent**, rather than being tied permanently to one model provider.

The architecture supports a provider-neutral Agent Host so tools such as Codex and future compatible agents can operate through XACE-owned capabilities.

The intelligence can change.

The game's contracts remain stable.

```text
Codex
Claude / future agents
Local agents
Other frontier models
        ↓
     XACE tools
        ↓
Typed gameplay proposals
        ↓
XACE authority
```

The model is replaceable.

The gameplay architecture is not.

---

# Engine Independent

XACE is designed so authoritative gameplay does not have to belong to a single engine.

Engine adapters connect the same underlying gameplay model and runtime to different presentation hosts.

Current architecture includes integration work across:

* **Unity**
* **Godot**
* **Unreal Engine**

The long-term principle is:

> **Your game logic should belong to your game — not to your engine.**

Portability is therefore an architectural property rather than a code-conversion trick.

---

# Gameplay Mutation

Gameplay represented through structured contracts can be changed transactionally.

XACE can:

* validate proposed changes
* detect incompatible mutations
* preview changes before commit
* regenerate affected execution plans
* preserve state where migration is valid
* reject unsafe mutations
* roll back failed changes
* record mutation history

The ambition is to make gameplay iteration feel immediate without sacrificing correctness.

---

# Replay, Rollback & Debugging Foundations

Because XACE controls authoritative state and execution, it can reason about gameplay at the level of simulation ticks rather than just source files.

The architecture includes foundations for:

* deterministic snapshots
* replay
* rollback
* world hashes
* state inspection
* mutation history
* validation proofs
* divergent-state detection

This is the foundation for a larger goal:

> **If a gameplay bug happened once, XACE should eventually be able to reproduce exactly what happened and explain why.**

---

# Multiplayer by Architecture

Networking is not intended to be something bolted onto gameplay after the game has already been written around single-player assumptions.

XACE's deterministic runtime, authoritative state, stable gameplay identities, snapshots, mutation rules, and engine-independent execution model are designed with networked gameplay in mind.

The goal is a world where multiplayer is a property of the gameplay architecture—not a second implementation of the game.

---

# Semantic Assets

Gameplay should not depend on arbitrary engine asset paths.

XACE separates gameplay meaning from presentation.

For example:

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
game shipping packages.

## Import And Adapter Package Handoff

Import means "wrap/link an existing engine project." XACE creates or updates a
project manifest, starter CGS files, launcher state, and adapter preparation
where supported. It does not reverse-engineer an existing Unity, Godot, or Unreal
game into CGS automatically.

Adapter package handoff means "validate, then copy a XACE adapter package into an engine-owned project." The preflight gate checks the target engine, CGS, persisted SGC plan, runtime compatibility proof, adapter protocol/version markers, asset references, semantic bindings, and local secret patterns before copy. The copied handoff package includes `xace_adapter_package_version_manifest.json` with version, compatibility matrix, dependency declarations, install/uninstall/rollback lifecycle script declarations, rollback support metadata, and SHA-256 file checksums. The receiving engine project still owns build settings, scenes, assets, packaging, platform SDKs, QA, and release.

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

The canonical cross-engine vertical-slice fixture lives at
`projects/canonical_cross_engine_vertical_slice`. It is a versioned CGS-owned
fixture covering movement, combat, health, inventory, save/load, rollback,
replay, semantic bindings, animation, audio, VFX fallback, and network-ready
input for Godot, Unity, and Unreal certification tasks. Godot and Unity now have
retained installed-engine proofs with validation JSON, PNG evidence, logs, and
hash reports under `target-codex-task64-godot-vertical-slice` and
`target-codex-task65-unity-vertical-slice`; Unreal, packaging/export, and
cross-engine hash equivalence remain separate gates.

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

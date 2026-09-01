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
Gameplay:
    event = player_wall_run_started

Unity:
    animation = WallRun_Unity.anim

Godot:
    animation = wall_run.tres

Unreal:
    montage = AM_WallRun
```

The gameplay concept remains stable while engines resolve their own presentation assets.

---

# What XACE is building toward

The current runtime/compiler architecture is the foundation for a much larger creation environment.

Upcoming work includes:

### XACE World Contract

A minimal canonical representation of gameplay-relevant world semantics—surfaces, triggers, spawn points, interaction volumes, capabilities, gameplay geometry, and other concepts that gameplay systems can depend on without becoming engine-specific.

### XACE Player

A lightweight first-party way to immediately run and play XACE-native gameplay without requiring a full external engine project for every iteration.

### XACE Live

Shared authoritative sessions where different clients—and eventually different engines—can participate in the same running game.

### XACE Black Box

A causal debugging system intended to turn:

> “Something broke after 47 minutes and I can't reproduce it.”

into:

> “The first incorrect state occurred at tick 284,191, here is the system that wrote it, here is the causal chain, and here is the exact replay.”

### Reality Fork

Branch a running game from an exact moment, try alternate gameplay rules, actually play each version, and promote the version that works.

Think:

> **Git branches for a running game universe.**

### Portable Gameplay Systems

Gameplay systems that carry their requirements, state contracts, events, networking behavior, tests, compatibility metadata, and world requirements with them—allowing developers to install and compose mechanics rather than repeatedly rebuilding them from scratch.

---

# The bigger idea

AI is making software generation cheap.

That does not make architecture, correctness, debugging, multiplayer, portability, compatibility, or maintainability disappear.

It makes them more important.

XACE is an attempt to build the infrastructure for that world:

> **AI-speed creation with deterministic, inspectable, portable gameplay underneath it.**

The eventual development loop should feel closer to:

```text
Imagine
   ↓
Build
   ↓
Play
   ↓
Change
   ↓
Fork
   ↓
Compare
   ↓
Debug
   ↓
Invite
   ↓
Ship
```

instead of spending most of a development cycle wiring infrastructure together.

---

## XACE in one sentence

> **XACE is an AI-native gameplay operating layer that turns game logic into deterministic, inspectable, mutable, network-capable, engine-independent software.**

---

**The model can change.
The engine can change.
The gameplay remains yours.**


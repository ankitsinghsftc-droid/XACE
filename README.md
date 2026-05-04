# XACE

**Deterministic, engine-agnostic, schema-driven game definition compiler.**

XACE is a deterministic, schema-driven game definition compiler and complete game creation platform. It sits between a game designer's intent and a game engine's execution — handling everything in between.

The simplest way to say it: **XACE is the layer between your game idea and your game engine.**
You describe what you want. XACE compiles it into validated, versioned game logic. That logic runs identically on Unity, Unreal, or Godot without rewriting anything.

XACE is not a game engine. It does not render, animate, or simulate physics. Those stay in the engine you already know. XACE is the logic layer — the rules, systems, entities, and behaviors that make your game work — compiled into a form that any engine can execute.

## The Core Architecture — 7 Layers
XACE is organized as a strict seven-layer pipeline. Every user input travels through these layers in order. No layer can be bypassed. No layer can reach across to another out of order.



**Layer 1 — Prompt Intelligence Layer (PIL)**

The entry point for natural language. When you type "make the zombie faster" or "add a health system to the player," this layer receives it. The PIL runs your prompt through a five-pass AI pipeline — planning, drafting, self-critique, determinism audit, and final output — before anything touches your game definition. It generates not just the schema mutation but also the Rust system implementation if new game logic is needed.



**Layer 2 — Game Definition Engine (GDE)**

The schema compiler. Takes validated mutations from the PIL and applies them to the Canonical Game Schema. Handles the domain-specific language, path addressing, transaction building, consistency validation, and the question engine when clarification is needed. Nothing modifies the game schema except through this layer.



**Layer 3 — Schema Factory**

Compiles the raw game schema into a structured package of entity blueprints, component registries, system definitions, and dependency graphs. Validates everything against the full component library before the runtime ever sees it.



**Layer 4 — System Graph Compiler (SGC)**

Takes the compiled schema and produces a deterministic execution plan — a complete schedule of which systems run in which order, which can run in parallel, and which must run sequentially. Seven compiler stages: graph construction, phase segmentation, dependency resolution, conflict analysis, scheduling, cycle detection, and parallelization safety validation.



**Layer 5 — Runtime Core**

The deterministic simulation engine. Tick-driven, not frame-driven. Runs your game's logic identically every time given identical inputs. Contains the entity store, component tables, query engine, mutation gate, phase orchestrator, time controller, snapshot engine, event bus, and determinism guard.



**Layer 6 — Engine Adapter**

Translates XACE's runtime output into engine-specific commands. Sends a minimal state delta to the engine every tick — only what changed. Receives input and feedback back from the engine. The adapter mirrors state only — it never modifies the authoritative simulation.



**Layer 7 — External Game Engine**

Unity, Unreal, or Godot. Handles rendering, animation, audio, physics, and input collection. Receives commands from XACE's adapter and sends back feedback. Never defines game rules. Never modifies simulation state.



---



## The Component Architecture — Three Layers



XACE organizes game components into three permanent layers.



**UCL Core — 10 components, frozen forever**

Transform, Identity, Render, Collider, Velocity, Input, Event, Lifetime, GameState, Authority. Every game uses all ten. These are universal across every genre — a horror game and a city builder both need entities with positions, identities, and lifecycle states.



**DCL — Domain Component Library, 13 domain packages, XACE-owned**

Combat, Character, Physics, AI, Stealth, RPG, World, Interaction, Camera, Audio, Network, UI, Persistence. Games declare which domains they need in their config file. A puzzle game might use only World and Interaction. A multiplayer RPG might use all thirteen. Each domain is versioned independently.



**GCL — Game Component Library, per-game, unlimited**

Developer-defined components specific to one game. The XACE validator ensures they don't collide with UCL or DCL names, use only valid field types, and follow naming rules. These are fully custom but validated by XACE before use.



---



## What XACE Is Capable Of



**Natural Language Game Design**

You describe your game in plain English. XACE's Prompt Intelligence Layer interprets your intent, classifies it into one of eight mutation categories (Create, Modify, Remove, Constrain, Compose, ProgressionDefine, EnvironmentDefine, Interaction), validates it against your current game schema, and applies it atomically. If your prompt is ambiguous, XACE asks a focused clarification question instead of guessing wrong.



**Automatic Code Generation**

When you add a new game system through natural language, XACE doesn't just update the schema — it writes the Rust implementation. It builds a complete system specification from your schema, calls its code generation engine, validates the generated code against XACE's interfaces, runs cargo check for compile errors, self-corrects if compilation fails, and shows you a diff before committing. You confirm. The system is live.



**Deterministic Simulation**

XACE enforces 15 determinism rules across every aspect of the runtime. The same game, started from the same initial state, with the same inputs, produces identical output on any machine, every time. This is not a feature — it is a proof. After Phase 9 you can run your game three times from identical state and verify the world hash at tick 1000 is byte-for-byte identical across all three runs.



**Full Replay System**

Record any game session. Replay it later from the initial snapshot plus the input stream. Every tick of the replay will match the original run exactly. This works because XACE's simulation is deterministic by design — replay is not a feature bolted on top, it is a natural consequence of the architecture.



**Instant Rollback**

XACE snapshots the complete world state at defined intervals. Roll back to any previous snapshot tick and the simulation resumes from that exact state — identical to the original run from that point. Used for debugging, testing, and network desync recovery.



**Schema Versioning and Migration**

Every change to your game definition is versioned, hashed, and stored as an immutable delta. Old save files carry the schema version they were created on. When a player loads an old save, XACE walks the delta chain and migrates their save data to the current schema automatically. If migration fails, the user is warned.



**Engine-Agnostic Portability**

Your game's logic lives in the schema, not in the engine. The same schema targets Unity, Unreal, or Godot through engine-specific adapters. Switching engines does not require rewriting game logic — only the adapter changes.



**Multiplayer Built In**

GGPO-style rollback netcode, lockstep synchronization, client-side prediction, server-authority mode, interest management, cheat prevention — all part of the platform. These are not things you add to XACE. They are things XACE provides so you don't have to build them.



**Save System**

Three-layer save architecture: session state (active game), progress (inventory, levels, achievements), and world state (doors opened, NPCs moved, terrain changed). Each layer persists independently. Cloud sync abstraction works with Steam, Epic, PlayStation, Xbox, or custom backends.



**Zero-Experience Game Creation**

30 genre templates covering horror, action, RPG, platformer, puzzle, survival, shooter, strategy, and more. A three-question guided flow generates a first playable game schema in 90 seconds. The Natural Language Translation Layer strips all technical vocabulary — no ECS terms, no component names, no phase references — from everything the user sees. The Design Mentor suggests improvements in plain English after every change.



---



## How It Works — End to End



A user types: *"add a double jump ability to the player."*



1. **PIL receives the prompt.** Normalizes it, classifies intent as CreateFeature, runs risk pre-scan. Assembles context from the current game schema — only the relevant parts, not the full schema. Runs five passes: planning identifies which entities and systems are affected. Draft generates the DSL mutation. Self-critique validates paths and constraints. Determinism audit checks D-rules. Final output produces a typed MutationTransaction with confidence score.



2. **Output parser validates.** Checks all schema paths exist. Validates operation types against component field definitions. Rejects any hallucinated references.



3. **Safety scope guard evaluates.** Five risk dimensions: scope boundary, destructive change, cascade impact, performance risk, determinism safety. Returns Approved, SoftWarning, or Blocked.



4. **GDE receives the transaction.** Path parser validates fully-qualified paths. Consistency validator checks type safety, component compatibility, and invariants. Transaction executor commits atomically — all operations succeed or none do.



5. **Schema Factory recompiles.** Entity blueprints updated. Component registry updated. Dependency graph updated.



6. **SGC produces new ExecutionPlan.** If the mutation added or changed systems, the SGC recompiles the execution schedule. New plan version assigned.



7. **Runtime validates and applies.** Confirms schema version matches execution plan version. Applies the new plan on the next tick boundary. New systems are live.



8. **Code Generation Engine activates** (if a new system was declared). Builds SystemSpec from schema. Calls Claude API with full spec. Validates generated Rust against ISystem interface. Runs cargo check. Self-corrects on error. Shows user a diff. User confirms. System compiles and runs.



All of this happens from one sentence.



---



## The Pains XACE Solves



**Engine lock-in.** The Unity runtime fee incident forced thousands of studios to consider switching engines. The rewrite cost stopped most of them. With XACE, your game logic lives in the schema — not in Unity-specific MonoBehaviours or Unreal Blueprints. Switching adapters is weeks, not months.



**Multiplayer complexity.** Building rollback netcode, lockstep synchronization, desync detection, and cheat prevention from scratch takes senior engineers six to twelve months. XACE provides all of it as infrastructure.



**Non-determinism bugs.** Games that should replay identically often don't. Random ordering of hash maps, frame-rate-dependent physics, untimed input — these produce subtle bugs that are nearly impossible to diagnose. XACE's 15 determinism rules and the DeterminismGuard enforce correctness at every execution boundary.

**Schema drift in live games.** Patching live games and breaking save files, replays, or multiplayer compatibility is a constant pain. XACE's versioned schema with migration rules makes schema evolution safe.

**The coding barrier for designers.** Game designers who understand design deeply but cannot write code have no good tools. Visual scripting inside engines is still engine-locked and doesn't scale. XACE's PIL lets designers express game mechanics in plain English and get working, production-grade implementations.

**No universal component standard.** Every game team reinvents the component architecture. XACE's three-layer UCL/DCL/GCL system provides a universal foundation that every game builds on consistently.

## Who XACE Is For

**Primary audience — technical indie developers and small studios (2-10 people)** who are actively building games and feel engine lock-in, multiplayer complexity, or determinism requirements as real costs. These developers have budget, they pay for infrastructure tools, and they understand the value of what XACE provides.


**Secondary audience — game designers and producers** who understand game design deeply but cannot write code. XACE removes the coding barrier — not the design-thinking barrier. You still need to understand what makes a good game. You no longer need to know Rust or C# to build one.


**Tertiary audience — zero-experience creators** who want to bring a game idea to life. The Game Genesis Engine, Natural Language Translation Layer, and Design Mentor are built for this audience. This is the Phase 16 promise.


## How XACE Is Different From Everything Existing

**From Unity, Unreal, Godot:**

XACE is not an engine. It sits above engines. Where engines solve rendering and physics, XACE solves game logic compilation, schema versioning, deterministic simulation, and cross-engine portability. These are orthogonal concerns. XACE works with any of these engines.


**From visual scripting (Unity Visual Scripting, Unreal Blueprints):**

Visual scripting is still engine-locked. It does not provide schema versioning, determinism guarantees, replay, rollback, or cross-engine portability. It solves "coding is hard" within one engine. XACE solves game logic definition across all engines.


**From middleware (Playfab, GameSparks, Photon):**

These are backend services — authentication, leaderboards, matchmaking, cloud infrastructure. They sit below the game engine handling server concerns. XACE sits above the game engine handling game logic concerns. They are complementary, not competing.


**From no-code game builders (GDevelop, GameMaker, RPG Maker):**

These are genre-locked, single-engine tools with low ceilings. They are designed to produce simple games. XACE is designed to produce production-grade games at any scale. The underlying architecture — deterministic ECS, schema compilation, SGC — is the same infrastructure AAA studios build internally.


**From AI game tools (Rosebud, Ludo):**

These generate game prototypes or assets from prompts. They have no determinism guarantees, no schema layer, no versioning, no cross-engine portability, and no production-grade runtime. They produce demos, not shippable games. XACE's PIL is just one layer of a complete platform.

## Why XACE Is Hard to Copy

**The deterministic ECS runtime is genuinely hard to build.** Getting 15 determinism rules to hold simultaneously across parallel execution, a mutation gate, an event bus, snapshot/restore, and replay validation is a multi-month engineering effort. The test suite that proves correctness — the vertical slice determinism test at Phase 9 — is the credibility signal.

**The three-layer component architecture is a design decision, not just code.** UCL/DCL/GCL took extensive design iteration to get right. The boundaries between what is universal, what is domain-specific, and what is game-specific — and the enforcement rules between them — are architectural choices that took time to think through.

**The 5-pass PIL with determinism audit is not a chatbot wrapper.** The planning → draft → self-critique → determinism audit → final output pipeline, combined with the safety scope guard, the clarification engine, the memory model, and the code generation engine, is a complete AI orchestration system. The self-correcting code generation loop alone — spec to Rust to cargo check to error to correction to validation — is substantial engineering.

**The cross-language boundary is genuinely complex.** Rust for the runtime, Python for the AI pipeline, TypeScript for the UI, C# for Unity — held together by a wire protocol, a delta sync engine, a feedback protocol, and a set of interfaces that must all agree. Getting this boundary right is a multi-phase engineering effort, not a weekend project.

**First-mover on this specific combination.** No one has shipped a deterministic ECS schema compiler with a natural language mutation pipeline and cross-engine adapter protocol. The individual pieces exist in various forms. The combination, at this level of rigor, does not.

## What the Final XACE Looks Like
A game studio opens the XACE Builder Workspace. On the left is the CGS Explorer — every entity, component, system, rule, and version of their game displayed as a navigable tree. In the center is a prompt input with a diff viewer — every schema change shows exactly what will change before it commits. On the right is a live engine viewport showing the game running.

A designer types: *"enemies should call for backup when their health drops below 30%."*
The PIL processes it. The clarification engine asks: *"Which enemies? All enemy types or just the Guard?"* The designer selects "All enemy types." The PIL generates a rule definition and a new system, shows a diff, asks for confirmation. The designer confirms. The SGC recompiles. The system is live in the next tick. The designer watches enemies call for backup in the running game viewport.

A game designer with no code knowledge has just added a complex behavior to a production-grade deterministic game simulation in under sixty seconds.

A technical director at a studio exports the same game schema and retargets it from Unity to Godot. The adapter is swapped. Game logic is unchanged. The schema version history, the save migration rules, the multiplayer synchronization — all intact.

A studio patches their live game. New rule added. CGS version incremented. Save migration rule generated automatically. Players who load old saves get their data migrated transparently. No broken saves. No support tickets.

A solo developer who has never written a line of code picks a "horror stealth" genre template. Answers three questions. Gets a first playable zombie-stalking game in 90 seconds. Spends the next month describing the mechanics they want in plain English. Ships a game.

That is the final XACE.

## The Single Sentence
**XACE is the operating system for game creation — the layer that sits between human intent and engine execution, handling everything in between.**

CurentStage: Building phase (see  master plan & recent commits)
## Architecture

```
User Intent
  → Prompt Intelligence Layer   [Python]
  → Game Definition Engine       [Python]
  → Schema Factory               [Python]
  → System Graph Compiler        [Rust]
  → Runtime Core                 [Rust]
  → Engine Adapter               [Rust]
  → Game Engine                  [C# / C++ / GDScript]
```

## Tech Stack

| Layer | Language |
|---|---|
| Runtime Core | Rust |
| System Graph Compiler | Rust |
| Engine Adapter Protocol | Rust |
| Shared Core Types | Rust |
| Schema Factory | Python |
| Game Definition Engine | Python |
| Prompt Intelligence Layer | Python |
| Builder Workspace UI | TypeScript + React |
| Unity Adapter | C# |
| Unreal Adapter | C++ |
| Godot Adapter | GDScript |

## Build Order

See MASTER_PLAN.md for the complete phase-by-phase build order.
See XACE_File_Manifest.docx for every file, its responsibility, and target line count.
See CLAUDE.md for full system context used by Claude Code.

## Setup

```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install Python dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Build Rust packages
cargo build

# Install Claude Code
npm install -g @anthropic-ai/claude-code
```

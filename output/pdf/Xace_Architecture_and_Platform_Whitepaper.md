---
title: XACE
subtitle: Deterministic Gameplay Infrastructure and AI-Assisted Authoring
edition: Architecture, Evidence, and Platform Blueprint
snapshot: After completion of X10-031
date: 2026-08-09
classification: Technical whitepaper and forward architecture
---

# Document Control

This document is an architecture and evidence snapshot of XACE after X10-031. It is not a released-product specification, a security certification, or a representation that the remaining launch gates have passed.

The source hierarchy used for this publication is:

1. `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` for the latest implementation sequence and task status.
2. `docs/XACE_COMMERCIAL_SCOPE.md` for the frozen first-commercial-release model.
3. `docs/XACE_PRODUCT_CLAIMS_MATRIX.md` for public wording constraints.
4. Current source code and the technical contracts classified as production sources in `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md`.
5. Retained proof artifacts for the exact scenarios they execute.

Historical audit material and archived design stubs are not treated as current product truth. Where the requested brief supplied founder or company history that the repository cannot verify, this paper labels it as founder-supplied context that requires editorial confirmation before external publication.

## Evidence Legend

| Label | Meaning | Publication rule |
| --- | --- | --- |
| Implemented and locally proven | Source exists and a retained or reproducible local proof covers the stated scenario. | State the exact scope, machine boundary, and proof limitations. |
| Implemented foundation; release proof open | The mechanism exists, but one or more global, cross-platform, installed-engine, security, scale, or soak gates remain open. | Use qualified language such as foundation, local proof, or supported scenario. |
| Approved product strategy | A deliberate commercial or architectural decision is recorded, but the complete product capability is not implemented. | Describe the target and required gates, not a shipped feature. |
| Long-term platform thesis | A proposed market or architecture direction is outside the current implementation or X10-100 roadmap. | Present as a blueprint with explicit dependencies and validation metrics. |

## Executive Definition

XACE is local-first deterministic gameplay infrastructure. It represents supported gameplay logic in a versioned Canonical Game Schema, compiles declared systems into a validated System Graph execution plan, executes that plan in a Rust runtime, and mirrors semantic state into host engines through adapters. AI is a constrained authoring input; it is never the runtime authority.

That definition is narrower than an AI game engine and more defensible. XACE does not replace a renderer, engine editor, physics scene, art pipeline, platform SDK, build system, or store submission workflow. Its intended responsibility is the gameplay core and the evidence that a supported change is structurally valid, deterministic under the covered model, executable, replayable, and recoverable.

[[DIAGRAM:architecture_stack]]

# 1. Executive Summary and Core Vision

## 1.1 What XACE Is

Most game development stacks interleave simulation rules with engine APIs, scene objects, animation callbacks, network transports, editor metadata, and rendering state. That coupling makes gameplay difficult to inspect as one coherent system. It also makes automated generation risky: a model can produce plausible C#, C++, GDScript, or JavaScript while silently violating ordering, authority, state, or recovery assumptions.

XACE introduces a gameplay-core boundary. The boundary is expressed through four primary artifacts:

- The Canonical Game Schema, or CGS, is a readable JSON definition of gameplay structure, identities, component defaults, systems, phases, read/write sets, dependencies, rules, and semantic bindings.
- The System Graph Compiler, or SGC, transforms declared systems into a deterministic persisted execution plan with stable identity and proof metadata.
- The runtime core owns fixed-tick simulation, entity and component state, guarded mutations, deterministic event and RNG windows, snapshots, replay hashes, and adapter-facing state deltas.
- Engine adapters translate the runtime protocol into engine-owned objects, presentation effects, input, and feedback while leaving rendering and native content in Godot, Unity, or Unreal.

The phrase logic brain and graphics skin is a useful intuition, but it is incomplete. Physics integration, input mapping, native assets, animation graphs, platform services, packaging, and presentation side effects are not merely skin. They are host-owned systems with explicit boundaries. XACE is strongest when it states those boundaries precisely.

## 1.2 The Paradigm Shift

The proposed shift is not from code to no code. It is from unbounded generated source as authority to constrained intent compiled through explicit contracts.

In the current production path, a supported authoring request is classified, clarified if needed, represented as a closed typed operation, shown as a preview, approved by the user, independently validated by the Game Definition Engine, compiled by the real SGC, loaded by the runtime, checked through replay and rollback hooks, and persisted only if the transaction completes. Provider output cannot choose arbitrary CGS paths or supply an executable runtime artifact.

This changes the role of AI. A model may propose a bounded definition, but local code derives identities, validates types, resolves dependencies, materializes supported behavior, and supplies execution metadata. The runtime trusts neither prose nor a provider response. It trusts a validated CGS, a compatible persisted plan, registered executors, and the state-authority handshake.

The result is not an immutable state graph. CGS is deliberately mutable through transactions. Each committed version is versioned, canonicalized, hash-addressed, and related to a verified parent. Immutability applies to identified artifacts such as a persisted plan for one CGS hash, not to the lifetime of the game definition.

## 1.3 Vision and Mission

The near-term mission is to make supported gameplay change safer and more inspectable:

- represent gameplay intent in portable contracts;
- reject invalid or stale mutations before they become durable;
- compile execution order instead of relying on incidental script order;
- run authoritative state through deterministic primitives;
- preserve snapshots and proof artifacts for diagnosis and recovery;
- mirror the same supported gameplay core into multiple host engines.

The long-term thesis is broader: a stable gameplay protocol could become a reusable substrate for interactive simulations, multiplayer games, and eventually adjacent deterministic simulation domains. Digital twins and general interactive simulation are not current repository capabilities. They are possible market extensions that would require new domain schemas, time and sensor models, validation rules, safety evidence, and integration programs.

## 1.4 The Honest Product Boundary

XACE currently should not be represented as:

- a full game engine;
- an arbitrary prompt-to-game generator;
- a finished-game exporter or automatic engine-project converter;
- a production multiplayer stack;
- a WebAssembly or WebGL game player;
- a public schema registry or hosted remix service;
- proof that every deterministic result is already bit-identical across all supported platforms;
- a zero-netcode system.

The strongest product sentence is therefore operational rather than magical: XACE lets AI and humans propose supported gameplay changes, then subjects those changes to schema, compiler, runtime, replay, rollback, and adapter checks before they are treated as applied.

# 2. Startup DNA and Global Platform Ambition

## 2.1 Origin and Positioning

The founding narrative supplied for this whitepaper positions XACE as India-originated deep-technology infrastructure led by a sole, non-traditional founder. The repository does not independently establish geography, founder count, biography, company formation, adoption, funding, or customer evidence. Those statements should be verified from signed founder and corporate sources before public distribution.

The technically supportable positioning is independent of biography: XACE is built at the schema, compiler, deterministic runtime, and adapter-protocol layers rather than as a regional workflow wrapper. That layer choice gives the project a plausible path to international relevance because the underlying problems - unsafe generated logic, simulation divergence, engine coupling, replayability, and change recovery - are not geography-specific.

The narrative should avoid claiming that lack of traditional computer-science constraints caused better architecture. XACE depends directly on established systems concepts: canonical serialization, content addressing, typed contracts, dependency graphs, topological sorting, fixed-point arithmetic, deterministic iteration, snapshots, transactional mutation, capability boundaries, and reproducible proof. The distinctive proposition is the way those concepts are assembled around AI-assisted gameplay authoring.

## 2.2 Infrastructure Ambition Without Category Inflation

Docker, WebAssembly, and Vercel are useful strategic analogies only at the level of abstraction:

- Docker illustrates the value of a portable contract between authored intent and execution environment.
- WebAssembly illustrates the value of a constrained, verifiable execution target with multiple hosts.
- Vercel illustrates the value of turning a complicated delivery pipeline into an opinionated developer workflow.

XACE is not equivalent to any of them in maturity, standardization, adoption, security model, or ecosystem. A publication-safe claim is that XACE aspires to become a portable gameplay-contract and verification layer. The evidence required for that status includes stable specifications, multiple independent implementations or consumers, compatibility governance, signed releases, broad cross-platform proof, third-party extensions, and sustained external use.

## 2.3 Protocol Layer Versus Application Layer

Application-layer AI tools compete primarily on model quality, prompt UX, content generation, and integration convenience. Those advantages can compress rapidly as general models improve. A protocol/runtime product can pursue a different source of value:

- the CGS defines what gameplay state and system contracts mean;
- the SGC defines how dependencies become an execution schedule;
- the runtime defines authority, mutation, time, snapshot, event, RNG, and hash behavior;
- proof artifacts make validation repeatable outside one UI session;
- adapters give engines a common semantic integration surface.

The moat is not that models cannot generate code. They can. The moat thesis is that generated changes still need a trusted authority that can reject invalid definitions, reproduce execution, diagnose divergence, recover state, and certify compatibility.

## 2.4 Local-First Commercial Posture

The frozen commercial strategy is local-first. Builder state, CGS, execution plans, runtime, adapters, saves, logs, and proof artifacts live on the user's machine by default. Hosted XACE services are not required for the first commercial release. Prompting is local-model or BYOK first; hosted providers require explicit configuration, exact model identity, health proof, credential protection, cost visibility, and user action.

This posture supports three strategic properties:

1. Project access does not depend on a hosted XACE runtime.
2. Users retain inspectable schema and proof artifacts.
3. Inference cost can be made visible and attributable rather than hidden in an unlimited platform subsidy.

It does not imply zero cost or zero liability. XACE may still bear costs for distribution, update infrastructure, compatibility work, support, registries, relays, abuse response, optional hosted services, and any future free tier.

## 2.5 Global Trust Requirements

Infrastructure ambition becomes credible through governance, not analogy. Before XACE can behave like a protocol-level platform, it needs:

- a versioned public specification for CGS, execution plans, runtime executor ABI, adapter messages, and proof artifacts;
- compatibility and deprecation policies with reference conformance suites;
- stable security and extension boundaries;
- a signed release and artifact-verification system;
- cross-platform and installed-engine matrices produced by hosted CI;
- third-party package provenance, license metadata, moderation, and revocation;
- public incident, privacy, support, and migration processes.

These requirements recur throughout the roadmap. They are part of the product, not administrative work after the product.

# 3. Technical Architecture and Deep Dive

## 3.1 System Context and Authority Boundaries

XACE separates authoring authority, simulation authority, and presentation authority.

| State | Authority | Durable or transient | Allowed write path |
| --- | --- | --- | --- |
| Authored game definition | Disk `game.cgs.json` plus GDE session state | Durable | GDE-validated transaction under the project lock and parent hash check |
| Compiled schedule | Persisted SGC execution plan for one CGS hash | Durable, immutable for that hash | Real SGC output validated and canonically persisted by Builder |
| Live gameplay world | Rust runtime | Transient with snapshots/save layers | Fixed-tick systems through guarded contexts and MutationGate |
| Engine presentation | Godot, Unity, or Unreal adapter | Transient, engine-owned | Runtime deltas, semantic playback commands, and approved feedback |
| Provider output | Inference boundary | Untrusted proposal | Closed schema parse, local normalization, preview, and downstream validation |

The central rule is that no layer may silently promote a weaker form of evidence into a stronger authority. A provider response is not CGS. A valid CGS is not an execution plan. An execution plan is not proof that the runtime can execute every declared system. A matching local replay is not cross-platform release proof. An editor-free adapter client is not installed-engine certification.

The current architecture can be summarized as:

```text
Natural-language or direct authoring intent
  -> capability classification and clarification
  -> closed typed CGS operation batch
  -> preview fingerprint and explicit approval
  -> GDE isolated apply plus whole-CGS validation
  -> canonical CGS commit and content hash
  -> SGC graph compilation and persisted plan
  -> runtime plan validation and executor registration
  -> fixed-tick simulation, snapshot, and world hash
  -> adapter snapshots/deltas and semantic playback
  -> engine-owned presentation and feedback
```

[[DIAGRAM:authority_flow]]

## 3.2 Canonical Game Schema

The correct expansion of CGS is Canonical Game Schema. The word game matters: the current contract is not a general graph format. It is a domain schema for gameplay modes, actors, component declarations and defaults, systems, rules, events, assets, and semantic bindings.

### 3.2.1 Top-Level Shape

A shareable CGS export is a UTF-8 JSON object. New exports identify `format = xace.cgs.export` and `format_version = 1.0.0`. The core shape includes:

- metadata with content and compatibility versions;
- global systems;
- optional top-level component schemas;
- one or more modes, exactly one of which is default;
- optional semantic bindings that remain parseable without engine-native files.

A system record carries a stable ID, phase, component read set, component write set, explicit dependencies, deterministic flag, optional parallel eligibility, and optional executor metadata. Component references use positive numeric type IDs. Mode, actor, system, and rule identities are stable strings with scoped uniqueness rules.

```json
{
  "format": "xace.cgs.export",
  "format_version": "1.0.0",
  "metadata": {
    "name": "Counter Example",
    "version": "0.2.0",
    "schema_version": "0.2.0",
    "cgs_hash": "<canonical-sha256>"
  },
  "component_schemas": [
    {
      "type_id": 10000,
      "name": "COMP_COUNTER_V1",
      "defaults": {"value": 0},
      "fields": [{"name": "value", "field_type": "fixed"}],
      "source": "generated"
    }
  ],
  "global_systems": [],
  "modes": [
    {
      "id": "mode_gameplay",
      "schema_version": "0.2.0",
      "is_default": true,
      "actors": [],
      "systems": [],
      "rules": []
    }
  ]
}
```

This example is explanatory. A committed file must contain the exact recomputed hash and pass the standalone validator.

### 3.2.2 Canonicalization and Identity

CGS identity is content-derived. The canonical hash algorithm removes `metadata.cgs_hash`, normalizes the parsed structure, recursively sorts object keys, serializes compact JSON with stable separators and ASCII escaping, and computes SHA-256 over the UTF-8 bytes.

The export contract currently specifies rounding JSON floats to six decimal places during canonicalization. Authoritative runtime state is stricter and uses fixed-point integers on covered surfaces. These are related but distinct rules: CGS canonicalization must tolerate legacy and non-authoritative JSON numbers, while runtime determinism must prevent raw floating-point values from becoming authoritative state.

The hash provides:

- a parent identity for optimistic concurrency;
- a filename key for persisted SGC plans;
- a runtime handshake field;
- a proof-bundle binding;
- a replay and snapshot compatibility marker.

It does not provide authenticity by itself. A SHA-256 digest proves content equality, not who published the content. Publisher authenticity requires a keyed signature or public-key signature and a trust policy.

### 3.2.3 Version and Mutation Semantics

CGS is versioned and transactionally updated, not globally immutable. A production mutation submits a parent CGS hash. GDE deep-copies the current document, applies the typed operations to the isolated copy, runs consistency validation, increments the appropriate semantic version, recomputes the canonical hash, and commits the new document once.

This model gives every accepted state a stable identity while preserving live authoring. Stale parent hashes fail before commit. Unknown fields and compatibility evolution are governed by format-version rules: new required fields require a major bump, additive optional fields a minor bump, and non-behavioral clarifications a patch bump.

### 3.2.4 Multiple Representations

XACE currently has layered representations rather than one fully unified statically typed CGS object:

- Rust core schema types define canonical gameplay contracts.
- The JSON export contract is designed for portability and independent validation.
- GDE operates on Python dictionaries under typed transaction and consistency validators.
- The runtime loader deserializes a richer JSON-facing model that includes component schemas, actors, systems, and executor metadata.

The layers are intentional at some boundaries, but they create schema-drift risk. Production maturity requires conformance tests that generate one corpus and validate it through every representation. Unknown optional fields must round-trip without accidental deletion, and each major schema version needs migration fixtures.

## 3.3 System Graph Compiler

The Rust System Graph Compiler turns system declarations into an execution plan. Its job is not to optimize arbitrary source code. It validates and schedules a domain graph whose nodes already declare their phase, dependencies, component reads, and component writes.

[[DIAGRAM:sgc_pipeline]]

### 3.3.1 Compiler Passes

The implemented SGC pipeline is:

1. Graph construction.
2. Early cycle detection for actionable diagnostics.
3. Phase segmentation.
4. Per-phase dependency resolution using Kahn's algorithm.
5. Conflict analysis and serialization grouping.
6. Deterministic schedule construction.
7. Independent parallel-safety verification.

Each pass consumes a more constrained representation. Deterministic containers such as `BTreeMap` and `BTreeSet` normalize iteration order so input declaration order does not accidentally become schedule authority.

### 3.3.2 Graph Construction

For systems `A` and `B`, the graph may contain four categories of edge:

| Edge | Direction | Purpose |
| --- | --- | --- |
| Explicit dependency | dependency -> dependent | Preserve authored `depends_on` order. |
| Read-after-write, RAW | writer -> reader | Ensure a reader observes the intended updated component. |
| Write-after-write, WAW | lexicographic first -> second | Serialize competing writes deterministically when no stronger order exists. |
| Phase order | earlier phase -> later phase | Preserve the global phase sequence. |

If several edge reasons apply to the same pair, the graph retains the highest-priority diagnostic reason: explicit dependency, then RAW, then WAW, then phase order.

A useful qualification is that read/write declarations are contracts. The compiler can only detect a hazard that the system declares. Runtime guarded contexts and executor validation therefore matter: they prevent a system from silently reading or writing outside its plan metadata.

### 3.3.3 Phase Segmentation

The canonical authoritative phases are:

1. Initialization
2. Input
3. Simulation
4. PostSimulation
5. Cleanup

SGC sorts each phase independently. Cross-phase order is already fixed by the phase sequence, so Kahn's algorithm operates only on the relevant phase-local subgraph. A dependency from an earlier phase to a later phase is compatible; a dependency that requires a later phase to precede an earlier phase is invalid.

### 3.3.4 Kahn Topological Ordering

Let `G = (V, E)` be one phase-local directed graph. For each node `v`, define:

```text
indegree(v) = |{(u, v) in E}|
```

The compiler seeds a sorted ready set with every zero-indegree node. It repeatedly removes the lexicographically smallest system ID, appends it to the output, decrements the indegree of each sorted successor, and inserts successors whose indegree becomes zero.

```text
ready = sorted_set(v for v in V if indegree(v) == 0)
ordered = []

while ready is not empty:
    v = pop_lexicographically_smallest(ready)
    ordered.append(v)
    for w in sorted(successors(v)):
        indegree(w) -= 1
        if indegree(w) == 0:
            ready.insert(w)

if len(ordered) != len(V):
    reject cycle
```

The usual complexity is `O(|V| + |E|)` apart from ordered-set factors. The `BTreeSet` tie break is not cosmetic: a queue whose order depends on hash iteration could emit different valid topological orders on different runs. XACE chooses one stable order.

An earlier deterministic DFS pass reports a concrete normalized cycle path and resolution suggestions. Kahn's residual-node check remains a defensive detection path.

### 3.3.5 Conflict Analysis and Parallel Eligibility

After ordering, the compiler records RAW hazards, WAW pairs, direct ordering constraints, and phase-local serialization groups. A deterministic greedy scan walks the topological order and accumulates a current window. A new system joins the window only if it has neither a component conflict nor a direct ordering edge with any existing member. Otherwise the window is flushed and a new one begins.

This is a stable greedy partition, not optimal graph coloring. Its purpose is safe, reproducible grouping rather than maximum theoretical parallelism.

Task X10-029 hardened one subtle rule: direct same-phase ordering edges are execution-window barriers. Two dependency-linked systems cannot be placed in the same parallel-eligible group even if their component sets appear disjoint. Independent siblings with a shared predecessor can still share a later window if they are conflict-free.

### 3.3.6 Persisted Execution Plan

A production plan is stored at:

```text
<project>/.xace/execution_plans/<cgs_hash>.plan.json
```

Its runtime identity tuple is:

```text
(schema_version,
 plan_version,
 adapter_protocol_version,
 compiled_from_cgs_hash,
 plan_hash)
```

The plan also records all scheduled system IDs, phase and group order, execution indexes, component access sets, system metadata, serialization constraints, and a proof-bundle reference. Builder may add validated metadata but may not rewrite SGC schedule semantics. Existing bytes for the same CGS hash must match exactly.

The runtime seals a schedule identity before tick zero and validates every schedule snapshot against it. In the strict authority path, a missing, stale, malformed, hash-mismatched, schema-mismatched, unsupported, or migration-pending plan is rejected before simulation; there is no silent fallback to a derived schedule.

### 3.3.7 Parallelism Reality

`parallel = true` currently means parallel-eligible. It does not mean the standalone runtime launches worker threads. The active policy is `deterministic_sequential`: systems in a parallel-eligible group execute one at a time in persisted order, and event merges retain system-ID ordering.

Future true parallel execution would need:

- isolated per-system read snapshots or safe shared reads;
- thread-local mutation and event buffers;
- deterministic merge order;
- bounded resource access and cancellation;
- race and stress testing;
- a policy/version change in schedule and replay evidence;
- performance proof that the added complexity is worthwhile.

## 3.4 Two Mutation Guardians, Not One

The requested phrase Mutation Gate Guardian combines two different trust boundaries. They should remain distinct because they protect different state at different times.

### 3.4.1 Design-Time GDE Validation

The Game Definition Engine protects authored CGS. A typed operation batch is reparsed at the trust boundary and applied to an isolated copy. The consistency pipeline checks paths, types, invariants, graph constraints, component migrations, and runtime executor ABI before one commit.

The static mutation conflict analyzer rejects covered classes including:

- empty, duplicate, or unknown system IDs;
- self-dependencies and dependency cycles;
- dependencies that violate phase direction or mode scope;
- reads or writes of undeclared component type IDs;
- same-phase read/write and write/write hazards without an ordering path;
- incompatible component-shape changes;
- generated-system ABI or compile-artifact mismatches.

This is schema and graph analysis over structured JSON, not arbitrary-language AST verification. It proves that defined invariants hold for the inspected model. It does not mathematically prevent code rot, future bugs, incorrect design intent, or undeclared behavior in an executor.

### 3.4.2 Runtime MutationGate

The Rust MutationGate protects the live gameplay world. Systems do not directly mutate entity or component storage. They submit deferred requests through guarded contexts. At each phase boundary, the gate drains five categories in fixed order:

```text
spawn -> add component -> modify component -> remove component -> destroy
```

Before applying a batch, the gate captures rollback images of entity state, component tables, queues, and optional event/RNG state. If an operation fails, it restores those images, restores the queued mutations rather than discarding them, recomputes a pre-batch hash where available, and reports the failed operation index, type, entity, component, path, source error, and rollback result.

Nested or concurrent apply transactions are rejected until a proven multi-transaction design exists. The store itself is intentionally not independently thread-safe; the phase orchestrator owns the mutation boundary.

[[DIAGRAM:mutation_transaction]]

### 3.4.3 Cross-Layer Prompt Atomicity

The Builder prompt apply path extends the transaction across authoring and runtime layers. The recovery image includes pre-apply CGS bytes and hash, GDE state, pending UI and approval state, persisted plan/proof/snapshot paths, runtime status, reload target, and adapter-visible session edit state.

If SGC, persistence, runtime reload, replay, adapter validation, or another covered downstream step fails after GDE commit, Builder restores the captured layers and does not emit a successful `cgs_update`. This is a high-value differentiator: the unit of success is not merely a valid JSON edit, but a validated end-to-end state transition for the covered path.

## 3.5 Deterministic Fixed-Point Numeric Model

XACE authoritative gameplay surfaces use `Fixed64`, integer ticks, integer IDs and counters, hashes, or domain-specific enums. `Fixed64` stores signed micro-units in an `i64`:

```text
S = 1,000,000
real_value = raw / S
1.0 is encoded as raw = 1,000,000
```

Serialization is a transparent JSON integer. There is no locale-sensitive decimal formatting and no binary floating-point state in the encoded value.

Implemented arithmetic includes:

```text
add(a, b) = saturating_i64(a.raw + b.raw)
sub(a, b) = saturating_i64(a.raw - b.raw)
mul(a, b) = saturating_i64((i128(a.raw) * i128(b.raw)) / S)
div(a, b) = saturating_i64((i128(a.raw) * S) / b.raw), b.raw != 0
sqrt(a)   = integer_sqrt(a.raw * S), a.raw > 0
```

Wider `i128` intermediates prevent ordinary intermediate overflow, final results saturate to the `i64` range, division returns no value for zero, and square root uses integer iteration. These semantics must be part of the compatibility contract because a different rounding or overflow rule can create divergence even when both implementations use integers.

The fixed-point gate covers spatial values, velocities, collider data, world size and gravity, actor statistics, elapsed gameplay time, interaction ranges, inventory weights, combat values, generated numeric behavior, and other named authoritative roots.

It does not remove all floating point from the codebase. Raw floats remain at non-authoritative boundaries such as wall-clock accumulation, engine feedback, visual reconciliation, and current network prediction structures. Fixed-point removes a major source of cross-platform divergence; it does not by itself prove full ARM, x86, or WebAssembly equivalence. The real three-operating-system replay artifact remains a global gate.

## 3.6 Authoritative State and Memory Model

### 3.6.1 EntityStore

The runtime EntityStore uses a `BTreeMap<EntityID, EntityMetadata>`. Entity IDs increase monotonically from 1, are never reused after destruction, and retain lifecycle history through archive state. Ascending map iteration gives deterministic entity order without sorting each query.

The lifecycle is explicit:

```text
Active <-> Disabled
Active or Disabled -> DestroyRequested -> Destroyed -> Archived
```

Destroy is deferred through MutationGate. An archived ID remains reserved, which prevents a replay from assigning an old identity to a later object.

### 3.6.2 ComponentTableStore

Component tables are keyed by numeric component type ID in a `BTreeMap`. Each table stores entity rows in ascending entity-ID order. The invariant is that a component row may not refer to an entity absent from EntityStore; MutationGate enforces the relationship.

The current component payload model includes canonical JSON strings in table rows. This is flexible and inspectable, but less compact than a generated binary struct layout. It also means canonical JSON production is part of deterministic correctness: the world hasher treats a row payload as an exact string.

### 3.6.3 Implications

The current memory model favors determinism, debuggability, and simple rollback over maximum cache locality. `BTreeMap` gives stable order and logarithmic updates but adds pointer chasing. JSON component rows make schema evolution and inspection easier but add parse and allocation overhead. Deep-copy snapshots multiply those costs.

Production performance work should measure before replacing these structures. Candidate future designs include generated packed tables for certified components, canonical binary row encoding, page-level copy-on-write snapshots, arena allocation, and stable sparse-set iteration. Every optimization must preserve externally visible ordering and hash semantics or explicitly version them.

## 3.7 Fixed-Tick Runtime Lifecycle

The time controller converts real elapsed time into discrete simulation ticks. Rendering frame rate does not define gameplay delta. A catch-up limit prevents an overloaded client from entering an unbounded spiral.

Within one tick, the runtime:

1. pumps engine messages;
2. collects and normalizes input;
3. processes engine feedback at the allowed boundary;
4. validates the sealed schedule identity;
5. enters each phase and runs its persisted groups;
6. applies deferred mutations at the phase boundary;
7. dispatches buffered events in deterministic order;
8. creates an authoritative end-of-tick snapshot;
9. computes and records the world hash;
10. advances the tick and emits adapter output.

[[DIAGRAM:runtime_tick]]

Events are buffered rather than dispatched mid-system. Their stable order is `(creation_tick, creation_phase, event_id)`. Payload maps use deterministic key ordering. This prevents callback timing from becoming an undeclared scheduling channel.

RNG is similarly bounded. A runtime interceptor opens a deterministic window for one system and tick. Seeds derive from world seed, system identity, and tick. Windowless, wrong-system, or OS-entropy access is a determinism violation under the active guard mode. Snapshot state records stream positions needed by the covered replay model.

## 3.8 Hash-Proven State Determinism

`world_hasher.rs` computes a lowercase SHA-256 digest from a fixed sequence of authoritative fields:

1. tick;
2. schema version;
3. execution plan version;
4. CGS hash;
5. RNG world seed and sorted stream positions;
6. pending event queue and next event ID;
7. pending mutation queues;
8. clean-boundary flag;
9. all entity lifecycle records and next entity ID;
10. all component tables and rows.

Fixed-width integers use big-endian bytes. Strings are length-prefixed so adjacent values cannot create ambiguous concatenations. Entity and component collections are already stored in sorted structures.

For snapshot `W`, the conceptual digest is:

```text
H(W) = SHA256(
  encode_tick(W) ||
  encode_identity(W) ||
  encode_rng(W) ||
  encode_queues(W) ||
  encode_entities(W) ||
  encode_components(W)
)
```

World hashes support three important operations:

- prove that two covered runs reached the same encoded state;
- find the first divergent tick during replay comparison;
- bind rollback restoration to the captured pre-failure state.

They do not synchronize peers. A network still needs authority, input delivery, ordering, loss handling, compatibility negotiation, rollback or resync, security, and lifecycle management. Hashes are evidence and detection, not zero-netcode synchronization.

Side channels outside WorldSnapshot require separate policy. Engine feedback buffers, adapter playback side effects, network inputs before materialization, save-slot metadata, and telemetry cannot be silently assumed to be covered by the world digest.

## 3.9 Snapshots, Replay, and Rollback

### 3.9.1 Complete Snapshot Contract

A `WorldSnapshot` contains tick and fixed-point time, schema and execution-plan versions, CGS hash, entity store state, component tables, RNG state, pending event and mutation queues, world hash, and clean-boundary status.

Serialization round-trips the complete structure. Missing legacy-minimal fields are rejected; deserialization may not fall back to a minimal snapshot that loses rollback authority. The serializer clears the stored world hash before computing the snapshot's canonical digest so the record does not hash its own digest.

### 3.9.2 Current Performance Model

The current SnapshotEngine is explicit: snapshot capture is a deep copy with `O(entities x components)` time and memory. Copy-on-write is future work. There is no repository proof for zero-copy buffers or a sub-millisecond latency budget.

That distinction matters for network design. A snapshot mechanism that is correct for local recovery may be too expensive at fighting-game rollback frequency or large-world scale. X10-074 and X10-075 are where scale benchmarks and budgets enter the hardening roadmap.

### 3.9.3 Restore Semantics

Restore validates schema compatibility and snapshot completeness, rebuilds entity and component stores, resets deterministic subsystems, restores tick and RNG/event/mutation state as covered, truncates later history, clears pending input and traces that would leak post-restore state, recomputes the hash, and notifies adapters to roll back presentation side effects.

This is a real local recovery foundation. It is not yet integrated rollback netcode.

### 3.9.4 Replay Proof

The cross-platform replay contract compares platform-independent identity fields: CGS and plan hashes, generated and scheduled system IDs, tick count, world seed, canonical input log, schedule fingerprint, latest world hash, and the per-tick hash log. Paths, command strings, and machine metadata are retained for audit but excluded from equality.

The tool can record one operating-system leg and aggregate Windows, Linux, and macOS reports. Local self-test proves comparison and injected-mismatch behavior. The top-level completion gate still requires the retained real three-platform aggregate.

### 3.9.5 Network Rollback Boundary

The network-core crate contains deterministic primitives for lockstep input gating, session and peer state, authority, prediction data, reconciliation plans, desync detection, interest management, and rollback bookkeeping. It intentionally does not open sockets.

Its RollbackManager stores snapshot metadata and computes a plan from the nearest stable snapshot at or before a target tick. The plan includes restore tick, replay ticks, target tick, live tick, reason, and optional hash. It does not own snapshot bytes and does not invoke runtime restore or resimulation.

Therefore the evidence-aligned status is:

- local snapshot/restore exists;
- deterministic rollback planning primitives exist;
- prediction and reconciliation primitives exist;
- local network smokes exist;
- runtime-integrated input synchronization, restore, resimulation, malicious-input hardening, diagnostics, chaos, and soak remain X10-036 through X10-044.

The phrase GGPO-style can describe a future design family, not the current implementation.

## 3.10 Live Schema Hot-Swap and Migration

Runtime `reload_cgs` is a versioned handshake, not a blind reset. Builder sends the CGS, schema, plan, world-hash, and tick identities it believes are current. Runtime compares them to disk and in-memory authority, loads the candidate CGS and plan into scratch structures, and accepts a swap only at a clean tick boundary.

Candidate changes are classified as:

| Class | Meaning | Current live action |
| --- | --- | --- |
| Additive | Existing state remains valid and new declarations can be initialized safely. | Eligible for live swap after validation. |
| Migratable | A deterministic registered migration can transform affected rows. | Eligible only for explicitly covered migration hooks. |
| State-transforming | Meaning or representation changes beyond a covered migration. | Reject before live mutation. |
| Reset-required | Compatibility cannot be preserved in the current world. | Reject live swap; require a controlled reset path. |

An accepted compatible swap preserves live tick, entity IDs, existing component rows, engine bridge state, pending inputs, and the existing tick-hash log while replacing the registry and schedule. Failed restore paths emit adapter side-effect rollback messages so host mirrors, playback commands, feedback queues, pending edit previews, and asset-binding caches can be cleared.

Installed-editor execution of every side-effect rollback path remains a global proof concern. The existence of adapter cleanup code is not equivalent to a release-wide engine guarantee.

## 3.11 Prompt Intelligence and Typed Operations

### 3.11.1 Capability Routing

Prompting is governed by a shared capability matrix. Routes are certified supported, constrained, clarification-required, blocked, unsupported, or experimental. Broad requests such as creating a complete online game, installing external services, writing arbitrary engine-native scripts, or packaging every store target are blocked or refused before mutation.

Ambiguous prompts enter a bounded clarification session. Accepted changes produce a structured preview and require explicit approval. Apply responses carry classifier, diff, SGC, runtime, replay, rollback, cost, latency, proof-link, and authority information rather than only a success string.

### 3.11.2 Provider Boundary

Builder, PIL, GDE, and repository tools may not call model providers directly. Provider execution, retry, cache, budget, model discovery, and telemetry live behind `packages/inference`. The production Builder path stores hosted credentials through the OS credential backend; a separate pre-beta BYOK placeholder module is not evidence for the production credential path.

Supported provider families may request native structured output:

- OpenAI-compatible providers receive a strict JSON Schema response format.
- Google receives response MIME type and response schema constraints.
- Anthropic receives a forced tool choice.
- Providers without a native equivalent receive stricter repair/quarantine instructions and local schema validation.

Structured syntax reduces malformed responses. It does not guarantee semantically correct gameplay and cannot support a zero-hallucination claim.

### 3.11.3 Closed Typed CGS Grammar

The current batch schema is `xace.typed_cgs_operation_batch.v1`. It is path-free and closed. The operation families are:

| Operation | Stable target | Scope |
| --- | --- | --- |
| `declare_component` | generated type ID and canonical name | Add a versioned schema with explicit typed fields/defaults. |
| `add_component` | mode, actor, component type | Attach a locally resolved complete default record. |
| `set_defaults` | mode, actor, component, fields | Change existing fields after exact type checks. |
| `add_system` | system ID and builtin reference | Select only a registered builtin with an exact contract. |
| `add_generated_system` | system ID and closed behavior | Request the narrow locally materialized generated behavior. |
| `add_event` | semantic event name | Add a versioned typed payload contract. |
| `add_rule` | mode and rule ID | Add deterministic declarative rule metadata. |
| `add_asset` | asset ID | Add a safe typed asset record. |

The provider schema contains no generic path, JSON Patch, arbitrary value envelope, source code, runtime executor, ABI, or compile artifact. Every operation has a stable ID and user-facing explanation. Unknown fields, duplicate targets, mixed legacy/typed envelopes, floats in the typed structural path, boolean-as-integer values, unsafe asset traversal, stale IDs, and numeric type drift fail closed.

### 3.11.4 Generated-System Trust Boundary

X10-031 adds one closed behavior: increment an exact field whose schema type is `fixed` by an integer number of whole units. Provider output specifies identities, phase, reads, writes, dependencies, version, explanation, and the behavior. It cannot provide generated Rust or executable metadata.

The local materializer:

1. validates the target against exact live component metadata;
2. stages an isolated CGS;
3. derives the ABI and rollback hooks;
4. generates Rust locally;
5. runs static unsupported-API and determinism checks;
6. runs a sandboxed Cargo type check against the approved contract;
7. invokes the real SGC and requires plan inclusion;
8. creates an integrity artifact bound to source, ABI, executor, policy, and plan hashes;
9. attaches only the locally materialized executor to the trusted batch.

GDE independently revalidates the executor envelope before commit. Runtime executes the closed declarative ABI behavior through guarded system context and MutationGate. The generated Rust compile is a safety and contract check; it is not arbitrary dynamic code loading.

The local artifact uses a deterministic integrity digest. It should not be described as publisher-authenticated release signing until a secret-key or public-key signing system and trust chain are implemented.

### 3.11.5 Current Proof

X10-030 retains 17 passing checks across all seven original operation families, strict provider schema compatibility, Builder/GDE atomicity, standalone CGS validation, real SGC persistence, two real runtime runs, matching replay, adversarial numeric rejection, and exact rollback.

X10-031 retains 25 passing checks, including provider executor exclusion, local materialization, code/ABI completeness, artifact integrity, real SGC/runtime execution, changing tick hashes, byte-stable replay, unsigned/tampered/provider-executor rejection, and exact rollback. Its retained report SHA-256 is `5dfd9f7395128b2709b2639ac2decf5ad2f692a0fb7f8c8391c16320ea0e03b1`.

The scope remains narrow. Composite prompt planning, prompt history with proof-linked undo/redo, and long-session degradation tests are X10-032 through X10-034.

## 3.12 Gameplay Primitive Library

X10-029 introduced ten versioned reusable primitives:

| Primitive | Genre focus |
| --- | --- |
| `platformer.kinematic_movement.v1` | Platformer movement and landing/jump semantics |
| `rpg.adventure_loop.v1` | RPG interaction, inventory, combat, and progression composition |
| `shooter.combat_loop.v1` | Shooter input, AI, damage, and death composition |
| `survival.gather_and_defend.v1` | Survival interaction, inventory, AI, and combat loop |
| `puzzle.interaction_loop.v1` | Puzzle state and semantic interaction |
| `strategy.unit_command.v1` | Strategy input, movement, AI, and unit state |
| `simulation.interactive_entity.v1` | Simulation entity, environment, and interaction state |
| `inventory.item_lifecycle.v1` | Pickup, equip, drop, and persistence composition |
| `combat.damage_resolution.v1` | Attack, damage, shield/status, and death composition |
| `multiplayer_combat.authoritative_loop.v1` | Authority and replication-policy composition for combat |

Every primitive declares seven facets: schema, system, event, input, asset, save, and network. Catalog systems refer to real runtime registry IDs with exact read/write contracts. The retained proof compiles and persists every SGC plan and launches each primitive twice for four ticks. Replay hashes match and each run changes state rather than passing on a static world.

The multiplayer-combat primitive proves local schema composition of authority and replication policy. It is not multiplayer runtime proof.

## 3.13 Engine Adapter Protocol

Host engines connect over a versioned framed message protocol. The runtime performs a handshake, sends authoritative snapshots or deltas and semantic playback commands, and receives normalized input and feedback. The shared Rust adapter package provides transport, sequence tracking, handshake validation, delta synchronization, snapshot recovery, and FFI surfaces; engine-specific adapters implement native object and editor integration.

The three targets are:

- Godot: GDScript transport, protocol, input collector, entity manager, delta applicator, and debug HUD/scene integration.
- Unity: C# transport, input collector, delta applicator, console widget, runtime bootstrap, and editor setup helpers.
- Unreal: C++ plugin components for transport, input collection, delta application, console UI, runtime setup, and commandlet validation.

Local installed-editor evidence exists on the current machine for Godot 4.6.3, Unity 6000.4.9f1, and Unreal 5.7. An editor-free smoke also proves that three named protocol clients receive the same tick and adapter-state digest from one runtime. The canonical cross-engine vertical slice, installed-engine CI lane, compatibility matrices, and direct cross-engine core-hash comparison remain later X10 tasks.

The adapter boundary deliberately excludes finished-game export. Import means wrap or link an existing engine project. Export means copy an adapter package for engine-owned integration. Scenes, assets, native scripts, physics setup, build settings, platform SDKs, packaging, QA, and release remain the game team's responsibility.

# 4. Current Development Status and Roadmap

## 4.1 Status After X10-031

The first 31 items in the ordered X10-001 through X10-100 completion backlog are marked complete. Sixty-nine remain open.

This count is useful for sequence tracking, but it is not a scientific product-readiness score. The tasks differ dramatically in size and risk, and the top-level completion gates remain open. A more accurate statement is: the authoritative core, deterministic-state foundation, mutation-safety foundation, and the first seven prompt-hardening tasks have locally completed evidence; integrated multiplayer, debugger, asset/import/export hardening, save/package/team hardening, scale, security, CI, usability, and release certification remain.

| Phase | Tasks | Checked | Open | Evidence-aligned status |
| --- | ---: | ---: | ---: | --- |
| Authoritative CGS, SGC, runtime contract | 001-008 | 8 | 0 | Complete locally; global release gates still apply. |
| Determinism, fixed point, snapshots, replay | 009-016 | 8 | 0 | Complete locally; real cross-platform aggregate remains a top-level gate. |
| Mutation safety and live hot-swap | 017-024 | 8 | 0 | Complete for covered paths; broader installed-engine and combination proof remains. |
| Prompt intelligence | 025-034 | 7 | 3 | Structured provider output, hard paths, packaging, benchmark, primitives, typed operations, and one generated behavior complete; composite planning/history/long sessions open. |
| Multiplayer integration | 035-044 | 0 | 10 | Primitive libraries and smokes exist; launch topology and runtime integration open. |
| Debugger and diagnostics | 045-052 | 0 | 8 | Time-travel product work open. |
| Engines, assets, import/export, cross-engine slice | 053-067 | 0 | 15 | Adapter foundations and local proof exist; this hardening/certification sequence is open. |
| Saves, migration, packages, extensions, teams | 068-073 | 0 | 6 | Foundations exist; authority, versioning, extension, and team workflow gates open. |
| Performance, security, CI, usability, release | 074-100 | 0 | 27 | Entire release proof program open. |

[[DIAGRAM:roadmap_status]]

## 4.2 What the First 31 Tasks Establish

### 4.2.1 Tasks 001-008: One Runtime Authority

This phase makes the persisted SGC plan the production schedule authority, removes hashless fallback, fixes plan identity ownership, requires complete CGS validation, registers authoritative component tables, broadens runtime executor registration, validates schedule identity per tick, and produces readiness inputs.

The important architectural result is fail-closed startup. A required plan that is missing, stale, unsupported, or incompatible cannot silently become a different derived schedule.

### 4.2.2 Tasks 009-016: Deterministic State and Recovery

This phase selects the `Fixed64` micro-unit model, migrates built-in authoritative math, defines side-channel hash policy, completes snapshot state, enforces complete serialization/restore, creates the cross-platform replay proof contract, adds divergence diagnosis, and hardens crash-safe project recovery.

The phase is locally complete, but the top-level gate still requires retained Windows, Linux, and macOS equality for the same real run.

### 4.2.3 Tasks 017-024: Mutation Safety and Hot-Swap

This phase consolidates runtime mutation apply code, adds GDE static conflict analysis, makes prompt apply recovery-backed across layers, implements compatible state-preserving reload, classifies compatibility, adds deterministic migration hooks, sends adapter side-effect rollback notices, and hardens bidirectional engine edit boundaries.

It is best described as covered transactional safety. It does not prove every schema combination, every native engine side effect, or arbitrary live migration.

### 4.2.4 Tasks 025-031: Constrained Prompt Authoring

This phase activates provider-native structured output where available, makes unknown paths hard failures, normalizes the prompt test command, runs the local launch provider/runtime benchmark profile, adds the ten-genre primitive catalog, introduces the path-free typed operation grammar, and locally materializes the first prompt-defined generated behavior.

Three retained proof milestones are especially concrete:

| Milestone | Result | Boundary |
| --- | --- | --- |
| X10-029 primitives | 10/10 genres, real SGC plans, two four-tick runtime replays per primitive | Reusable catalog, not arbitrary generation or multiplayer proof |
| X10-030 typed operations | 17/17 checks over seven operation families and exact rollback | Builtin systems only in `add_system`; generated behavior separate |
| X10-031 generated behavior | 25/25 checks, real SGC/runtime, replay, tamper rejection, rollback | One closed fixed-field increment behavior |

## 4.3 The Eleven Global Completion Gates

All top-level gates remain open. Completion of individual tasks does not waive them.

1. `cargo test --workspace` passes on Windows, Linux, and macOS.
2. Python production tests run through one documented command without ad hoc import-path surgery.
3. Builder TypeScript/server tests, build, typecheck, and lint pass in CI.
4. Cross-platform replay produces identical runtime-authoritative hashes on Windows, Linux, and macOS.
5. The prompt launch profile covers real provider, compile, runtime, rollback, and reproducibility dimensions.
6. Installed-engine proof exists for Godot, Unity, and Unreal on the same canonical vertical slice.
7. Multiplayer chaos proof passes for the selected supported topology.
8. An eight-hour product soak covers prompt edits, SGC, runtime, adapters, saves, rollback, and recovery.
9. Fuzz, security, secret-scan, supply-chain, and proof-artifact gates pass.
10. Every public claim maps to a reproducible proof artifact.
11. A signed release candidate installs on a fresh machine without repository knowledge.

## 4.4 The Remaining 69 Tasks

### 4.4.1 Immediate Prompt Work: X10-032 to X10-034

- Composite planning must turn a multi-system request into an ordered dependency graph of schema, system, asset, network, and save operations with one rollback plan.
- Undo/redo must link authoring history to CGS, plan, runtime, replay, and rollback proof identities.
- Long-session testing must exercise context growth, provider failures, stale state, edits, and undo without corruption or unbounded cost.

### 4.4.2 Multiplayer: X10-035 to X10-044

The first decision is topology. The frozen planning preference is a host-authoritative runtime, but the task must make the choice explicit and limit public claims to it. Runtime tick advancement must then consume synchronized inputs, SnapshotEngine must participate in restore and resimulation, and client prediction/reconciliation must operate against the selected authority.

Session lifecycle, compatibility negotiation, malicious-input limits, diagnostics, network chaos, and multi-user soak are not optional finishing touches. They determine whether rollback code can survive real packet loss, reordering, duplication, latency, disconnects, stale clients, and hostile data.

### 4.4.3 Debugger: X10-045 to X10-052

The debugger sequence starts with a minimum tick inspector and reverse navigation, then adds delta-compressed retention, conditional breakpoints, causality graphs, RNG traces, support bundles, and exportable reports. Time-travel scrubbing should not be advertised until these tasks provide a coherent user workflow and retention budget.

### 4.4.4 Engines and Assets: X10-053 to X10-067

Asset-reference validation, semantic binding UI, engine-specific binding status, and deterministic fallback behavior must precede broader portability claims. Import needs marker validation, inventory, and a manual migration wizard. Adapter install/uninstall and handoff need reversibility, preflight, and versioning.

The canonical cross-engine slice must then run in Godot, Unity, and Unreal with comparable core hashes. Existing local engine proofs reduce technical uncertainty, but they do not replace this common-slice program.

### 4.4.5 Saves, Packages, Extensions, Teams: X10-068 to X10-073

Save/load authority and schema migration must be explicit. Starter templates, packages, and extensions need semantic versions and compatibility rules. A third-party extension API needs capability restrictions, ABI stability, signing, and failure isolation. Team workflows need source-control guidance for CGS, plans, proof artifacts, conflicts, and migrations.

### 4.4.6 Release Engineering: X10-074 to X10-100

The final phase establishes scale benchmarks and budgets, fuzzing, an eight-hour soak, hosted and installed-engine CI, reproducible builds, signing, supply-chain review, secrets/privacy controls, opt-in telemetry, backup, external security review, fresh-user installation, tutorials, compatibility matrices, support, external usability tests, readiness scoring, independent verification, three public demos, claims alignment, private alpha, public beta, and commercial launch.

## 4.5 Capabilities Not Contained in X10-032 to X10-100

The attached brief requests several capabilities that are not implemented and are not explicitly delivered by the current 100-task roadmap:

- a WebAssembly browser player;
- WebGL or WebGPU rendering;
- `xace.app/play/<game-id>` hosted join links;
- a public content-addressed schema/package registry;
- one-click fork/remix lineage and hosted publishing;
- bundled royalty-free 3D assets and procedural level generation;
- low-latency cloud relay infrastructure.

X10-070 through X10-073 provide package, extension, and team-workflow foundations, but not a public service. Completing X10-100 would prove the governed commercial target described in the tasklist; it would not automatically prove the universal browser/social platform described in the brief. Section 7 defines a separate forward architecture and gate program for those ambitions.

## 4.6 Complete X10 Task Index

The following appendix table is generated directly from the current tasklist so checked state and titles cannot drift during PDF generation.

[[ROADMAP_TABLE]]

# 5. Target User Segmentation and Workflows

## 5.1 Segment Reality Matrix

| Segment | Current credible value | Missing before a public promise |
| --- | --- | --- |
| Technical indie developers | Local projects, templates, guarded prompt edits, typed previews, SGC/runtime proof, engine adapter handoff | Broader behaviors, onboarding, asset UX, debugger, release packaging, external usability proof |
| Engine and tools engineers | Protocol evaluation, deterministic-core experiments, adapter integration, schema and proof tooling | Stable extension API, compatibility guarantees, installed-engine CI, support lifecycle |
| Non-technical hobbyists | Future target; narrow guided scenarios may be demoed with assistance | Zero-experience onboarding, safe asset workflow, browser player or packaged local player, recovery UX, usability testing |
| Professional studios | Evaluation of deterministic validation, replay, rollback, and portable gameplay contracts | Scale budgets, security review, source-control/team workflows, SLA/support, migrations, long soak, external proof |
| Multiplayer teams | Network primitives and deterministic simulation concepts | Selected topology, runtime integration, resimulation, chaos, security, diagnostics, soak |
| Browser/social remix creators | Long-term thesis | WebRuntime, hosted sessions, registry, provenance, moderation, publishing, browser asset/runtime pipeline |

The best current fit is a technical creator willing to use a local Builder and understand that XACE is a gameplay-core layer. The easiest segment to imagine is not always the first one to serve. A zero-code browser creator requires substantially more product surface than a deterministic infrastructure evaluator.

## 5.2 Current Creator Workflow

The supported high-integrity workflow is:

```text
Create or link a local project
  -> load CGS and current authority IDs
  -> enter a supported prompt or direct edit
  -> classify and clarify
  -> produce typed preview and proof expectations
  -> user approves exact fingerprint
  -> GDE validates and commits atomically
  -> SGC compiles and persists plan
  -> runtime loads, ticks, replays, and validates rollback
  -> adapter mirrors the supported state into a host engine
```

The user sees an explanation of what will change, not only generated code. Unsupported broad requests fail visibly and do not leave a pending transaction.

### 5.2.1 Example: Add a Counter Behavior

For the X10-031 behavior, the user asks for a named system that increments a known counter. The prompt route identifies structural intent, the provider returns a closed behavior without executable metadata, and local code validates the fixed-point field. The materializer derives and verifies the executor, Builder shows a path-free preview, GDE commits the batch once, SGC schedules the system, and runtime proof shows the world changing each tick. Tampering or an unsigned batch leaves CGS unchanged.

The value is not that incrementing a counter is difficult. The value is that the complete trust boundary exists for a small behavior and can be extended deliberately.

## 5.3 Serious Indie Workflow

A serious indie team can use XACE as a logic laboratory:

1. Define mechanics using a starter template and reusable primitives.
2. Keep authoritative gameplay state in CGS-backed components.
3. Compile schedule changes and inspect hazards before integration.
4. Run deterministic headless proofs and retain tick hashes.
5. Bind semantic animation, audio, VFX, and input in the chosen engine.
6. Use snapshots and mutation rollback to recover from covered failed changes.
7. Commit schema and proof artifacts through source control under team policy.

The native engine remains the content and rendering environment. There is no one-click conversion of all engine state into XACE and no one-click finished-game export from XACE.

## 5.4 Professional Studio Workflow

The studio-grade target adds governance:

- schema review and code-owner rules for component/system contracts;
- signed extension and generated-executor policies;
- CI that compiles every supported platform and engine matrix;
- cross-platform replay artifacts for each gameplay release;
- migration rehearsals on real save corpora;
- performance and memory budgets by world scale;
- deterministic divergence triage and support bundles;
- threat modeling for prompt, package, network, and adapter boundaries;
- long-run soak and failure injection before release.

This target is credible only after X10-074 onward. Studios buy repeatability and support, not an architectural diagram.

## 5.5 Non-Technical Creator Target

The attached brief describes natural language to instant WebGL preview with no engine installation. That is a valuable future workflow but not a current capability.

A responsible zero-experience design would need:

1. a restricted catalog of proven mechanics and assets;
2. examples phrased in user language rather than ECS terminology;
3. immediate previews with clear unsupported boundaries;
4. automatic recovery and understandable diff explanations;
5. safe defaults for input, camera, save, and local multiplayer;
6. accessibility and mobile/browser controls;
7. a no-account local path or an explicit hosted trust model;
8. published limits for session size, network topology, and content.

The product should optimize for successful first play, not for the number of prompts accepted.

## 5.6 Time-Travel Debugging Target

Deterministic state provides the raw ingredients for time travel: tick-indexed snapshots, input logs, schedule identities, RNG state, mutation history, events, and hashes. The product experience remains future work.

The minimum credible debugger should answer:

- What changed at this tick?
- Which system wrote the field?
- Which input, event, RNG draw, or prior mutation caused it?
- What schedule and CGS version were active?
- Where did a replay first diverge?
- Can the user restore, branch, and reproduce the state?

Reverse navigation cannot simply decrement a counter. It must restore a compatible snapshot and replay the authoritative input/mutation log to the target tick, with retention and memory budgets made visible.

# 6. Game Creation Workflow, Assets, and Rendering Targets

## 6.1 Creation Lifecycle

The creation lifecycle has two feedback loops: authoring validation and live presentation.

[[DIAGRAM:creation_lifecycle]]

The authoring loop is:

```text
intent -> typed operation -> isolated validation -> CGS commit -> SGC plan -> runtime proof
```

The presentation loop is:

```text
engine input/feedback -> runtime tick -> snapshot/delta/playback -> engine presentation
```

The loops meet only through versioned contracts. Engine feedback is accepted at defined boundaries. Engine-originated durable edits are preview-first and currently restricted to audited primitive component-default changes; structural edits return to PIL/GDE.

## 6.2 Asset Strategy Today

XACE distinguishes gameplay identity from engine-native asset realization.

The Python asset registry manages typed references, statuses, manifests, placeholders, validation, import/link workflows, naming, animation contracts, audio manifests, and engine feedback. A reference can be:

- placeholder: gameplay can proceed with a known stand-in;
- linked: a semantic asset ID resolves to an engine path;
- missing: a previously linked target is unavailable;
- unresolved: the reference was not properly registered and blocks the relevant operation.

The CGS stores semantic asset identity rather than embedding binary meshes, textures, animation clips, or audio. The manifest and adapter binding layers resolve that identity into engine-owned content.

The Rust asset-runtime package contains foundations for streaming, local/CDN adapters, content hashing, and tick-boundary hot reload. These foundations and local smokes do not prove a production CDN service, a complete asset browser, or deterministic peer-wide hot reload under a shipped multiplayer topology.

## 6.3 Semantic Binding

A semantic binding answers: when gameplay emits event `E`, what presentation action should host engine `H` perform with asset `A`?

```text
binding_id
event_name
playback_kind: animation | audio | vfx | ui
asset_id
semantic_action
priority
engine-specific resolution status
```

This separates gameplay from concrete files. For example, `combat.hit_confirmed` can request a VFX action without the runtime knowing whether Unreal uses Niagara, Unity uses a prefab/VFX Graph, or Godot uses a particle scene.

The semantic contract is portable; the concrete binding is not automatically portable. Each engine must resolve a compatible asset and report status. X10-053 through X10-056 harden validation, UI, status, and fallback behavior.

## 6.4 Placeholder and Bundled Asset Policy

Placeholder visuals are valuable for early mechanics proof, but they must be labeled. The current repository register explicitly classifies grey-box and placeholder assets as test/demo support, not finished assets.

The attached proposal for royalty-free low-poly bundles and procedural level generation requires a separate product and legal program:

- asset provenance and license records;
- redistribution and generated-output rights;
- attribution requirements;
- platform and age-rating suitability;
- content moderation and malware scanning;
- versioned manifests and immutable content hashes;
- deterministic generation seeds and generator-version capture;
- performance tiers for mobile, browser, and native engines.

Until those controls exist, bundled asset packs are a platform thesis rather than a launch promise.

## 6.5 Current Rendering Targets

The implemented targets are host-engine adapters for Godot, Unity, and Unreal. The runtime sends state; the engine renders and owns native content. Headless runtime execution is also an important target for tests, servers, proofs, and tools.

| Target | Current role | Current evidence boundary |
| --- | --- | --- |
| Headless Rust runtime | Authoritative simulation, proof, replay, control API | Strong local targeted proof; global platform/scale gates open |
| Godot adapter | Engine presentation and feedback | Source plus current-machine installed validation |
| Unity adapter | Engine presentation and feedback | Source plus current-machine installed validation |
| Unreal adapter | Engine presentation and feedback | Source plus current-machine installed validation |
| Browser WebAssembly/WebGL/WebGPU | Proposed zero-download player | No implementation found; separate blueprint in Section 7 |

## 6.6 Native Engine Handoff

An adapter package handoff should include:

- adapter source/binaries and manifest;
- protocol and runtime compatibility versions;
- required engine/plugin version range;
- semantic binding inventory and unresolved items;
- setup steps and reversible installation record;
- preflight results;
- known limitations and support bundle command;
- package signature after release signing exists.

The receiving project remains responsible for scene construction, visual assets, animation state machines, engine physics, build profiles, platform services, packaging, and release.

## 6.7 Save and Persistence Layers

The save engine models three layers:

- session: authoritative `WorldSnapshot` state for the active run;
- progress: player/profile/story data that survives session rollback;
- world: durable world changes such as opened doors or defeated entities.

The Rust foundation writes snapshot and metadata files atomically, validates schema versions, records CGS and asset hashes, supports recovery, and sorts slot listings. Python modules add envelope, migration, cloud-conflict, profile, compression, and encryption concepts.

X10-068 and X10-069 remain open because the existence of these modules does not settle authority across duplicate implementations, prove long-term migration compatibility, or certify corruption, partial-write, cloud-conflict, and old-save behavior at release scale.

# 7. WebRuntime, Schema Reuse, Sharing, and Forking

## 7.1 Status of This Section

This section is a forward architecture. No WebAssembly player, WebGL/WebGPU renderer, public registry, `xace.app` join service, or one-click remix implementation was found in the current repository. These features are also not explicitly completed by X10-032 through X10-100.

The architecture below shows how they could be built without weakening the deterministic authority model. It should be approved as a new program after the existing commercial scope and release gates are reconciled.

## 7.2 WebRuntime Goals

A browser target should preserve five properties:

1. The same versioned CGS and compatible SGC plan identity govern execution.
2. Authoritative simulation runs outside rendering frame timing.
3. Browser APIs, assets, input, and networking are explicit non-authoritative boundaries until materialized.
4. Every loaded package is content-addressed and verified before tick zero.
5. A browser run can emit the same proof fields needed for replay and divergence diagnosis.

The goal is not merely to compile Rust to Wasm. It is to define a browser host whose clock, memory, networking, storage, and rendering constraints are compatible with XACE authority.

[[DIAGRAM:web_runtime]]

## 7.3 Proposed Browser Process Model

### 7.3.1 Main Thread

The main browser thread owns DOM, accessibility UI, input capture, page lifecycle, and the chosen renderer. It must not drive authoritative simulation directly from `requestAnimationFrame`.

### 7.3.2 Simulation Worker

A dedicated Web Worker loads the Wasm runtime and owns authoritative state. It receives normalized input packets and control messages, advances fixed ticks, and emits snapshots/deltas/playback commands. The worker isolates simulation from layout and rendering stalls.

The initial implementation should use deterministic single-threaded Wasm. Wasm threads and `SharedArrayBuffer` require cross-origin isolation headers, add memory-race risk, and should follow rather than precede a correct single-worker target.

### 7.3.3 Renderer

The renderer consumes adapter-facing state through a browser adapter contract. WebGL2 offers broad compatibility; WebGPU offers newer capabilities but a different support and security surface. Neither renderer should become state authority. Interpolation may use non-authoritative floats because the next authoritative snapshot can replace the visual result.

### 7.3.4 Audio, Storage, and Lifecycle

Browser audio requires a user gesture and may be suspended by the platform. IndexedDB can store packages, saves, and proof logs, but quota and eviction behavior are browser-controlled. Visibility changes, background throttling, mobile memory pressure, and service-worker updates must produce explicit runtime states rather than hidden time jumps.

## 7.4 Wasm Memory and Snapshot Strategy

The current native SnapshotEngine deep-copies logical state. A first Wasm port should preserve correctness before introducing a new memory design. It can serialize canonical snapshots into bounded buffers and measure cost.

Later optimization candidates include:

- page-granular copy-on-write inside a deterministic state arena;
- dirty-page tracking at tick boundaries;
- ring-buffer retention for recent snapshots;
- canonical binary component rows instead of JSON strings;
- delta snapshots against a verified base hash;
- compression in a separate worker after the authoritative snapshot is sealed.

An optimization cannot change state semantics merely because Wasm linear memory makes it convenient. Snapshot identity must include encoding version, base snapshot identity, schema/plan identity, and every authoritative queue. Restore must recompute the same world hash.

No latency target should be published before measuring representative worlds on desktop and mobile browsers. A useful budget matrix would include entity count, active component rows, snapshot interval, bytes per snapshot, capture time, restore time, and retained-history duration at p50, p95, and p99.

## 7.5 Browser Package Format

A deployable browser package should be an immutable manifest plus content-addressed blobs:

```json
{
  "schema": "xace.web_package.v1",
  "package_id": "sha256:<manifest-hash>",
  "cgs": {"hash": "...", "url": "blobs/..."},
  "execution_plan": {"hash": "...", "url": "blobs/..."},
  "runtime": {"abi": 1, "wasm_hash": "..."},
  "adapter": {"protocol": 1, "browser_adapter_hash": "..."},
  "assets": {"manifest_hash": "...", "required": []},
  "compatibility": {"min_host": "...", "max_host": "..."},
  "proof": {"bundle_hash": "..."},
  "license": {"spdx": "..."},
  "signature": {"algorithm": "...", "key_id": "...", "value": "..."}
}
```

The loader should verify the manifest signature, every blob hash, CGS hash, plan hash, ABI compatibility, asset policy, and proof metadata before creating the runtime worker. A service worker may cache immutable blobs by hash, but mutable aliases such as `latest` must resolve to a new immutable manifest.

## 7.6 Instant Play Link Architecture

A URL such as `xace.app/play/<game-id>` is a hosted routing feature, not an intrinsic property of Wasm. A safe resolution flow is:

1. The human-readable game ID resolves to an immutable published package ID.
2. The client downloads the signed package manifest.
3. The client verifies hashes, signature, revocation status, compatibility, and policy.
4. Immutable blobs are fetched from a content-addressed object store or cache.
5. The simulation worker starts paused and validates CGS plus plan before tick zero.
6. The browser adapter initializes input, renderer, accessibility, and audio.
7. For multiplayer, a separately authenticated session descriptor negotiates authority, topology, versions, and transport.

The play link must not embed credentials, private project content, provider keys, or mutable unsigned manifests. Revocation should block newly resolved launches while preserving an auditable record of what package was withdrawn and why.

## 7.7 Browser Multiplayer Transport

The transport choice should follow X10-035 topology, not precede it. Options include WebSocket for broad reliable support, WebRTC data channels for peer paths, and WebTransport where deployment and browser support justify it.

The session handshake must bind:

- package, CGS, plan, runtime, and protocol versions;
- selected topology and authority peer/server;
- world seed and start tick;
- input schema and allowed rate/size;
- snapshot and desync policy;
- authentication and reconnect token;
- feature flags that affect deterministic behavior.

Clients with mismatched authority identities must not enter live simulation. Hash comparison should trigger a bounded recovery policy, not an infinite resync loop. Host migration, relay fallback, NAT traversal, denial of service, cheating, and privacy need explicit product decisions.

## 7.8 Canonical Schema and Package Registry

The registry should be described as a verified package registry for gameplay contracts, not merely a search website.

### 7.8.1 Immutable Artifact Store

The artifact store is keyed by canonical content hash. It holds CGS exports, package manifests, dependency lockfiles, proof bundles, optional source material permitted by policy, and separately licensed asset manifests. Published version bytes never change.

### 7.8.2 Mutable Index

A search/index service stores mutable metadata:

- namespace and package name;
- semantic versions and tags;
- display text and categories;
- compatibility matrix;
- verification level;
- publisher identity;
- license and attribution summary;
- popularity and quality signals;
- deprecation or revocation state.

The index may be rebuilt from immutable records and signed publication events. Search rank is never part of deterministic runtime identity.

### 7.8.3 Proposed Package Manifest

```text
namespace/name@semver
content_hash
cgs_format_range
runtime_abi_range
sgc_plan_version_range
adapter_protocol_range
dependencies with exact lock hashes
declared component/system/event/input/asset/save/network facets
publisher and signing key
SPDX license and attribution
proof bundle and verification profile
security scan and moderation status
provenance parents
```

Dependencies should resolve into a lockfile of exact content hashes. Range resolution happens during authoring or publication; runtime should not pick a new compatible version at launch.

## 7.9 Publication Pipeline

A public package must be rebuilt and reverified by trusted infrastructure. The pipeline should:

1. authenticate namespace and publisher;
2. validate manifest and license metadata;
3. reject path traversal, credentials, secrets, unsafe URLs, and unsupported executors;
4. run standalone CGS validation;
5. resolve dependencies and write an exact lockfile;
6. rerun generated-system policy and safe compilation where applicable;
7. invoke the real SGC;
8. execute deterministic replay and rollback profiles;
9. scan assets and packages for malware and policy violations;
10. produce a signed registry proof and immutable artifact record;
11. update the mutable index only after artifacts are durable.

The registry must never trust a provider-supplied runtime executor merely because a local project accepted a preview. Publication is a separate trust domain.

## 7.10 Fork and Remix as a Provenance DAG

One-click remix should create a new identity rather than mutating the parent.

Let parent package `P` have content hash `h(P)`. A remix applies typed operation batch `T` to create child definition `C`:

```text
h(P) -> T -> validate -> compile -> replay -> h(C)
```

The child manifest records:

- parent package and content hash;
- exact typed operation batch hash;
- inherited dependency lockfile and any changes;
- attribution and license obligations;
- new CGS and plan hashes;
- new proof bundle;
- creator/publisher identity and timestamp outside runtime authority.

[[DIAGRAM:remix_dag]]

The provenance graph enables reproducibility, attribution, diff views, branch comparison, and security response. It also makes a remix honest: if the parent or dependency license forbids redistribution or derivative use, the UI cannot offer publication.

Natural-language remix should still show an exact preview and require approval. A lightning-bolt button may simplify discovery, but it must not bypass the same GDE, SGC, runtime, replay, and rollback gates.

## 7.11 Registry Security and Operations

A registry creates new attack and operational surfaces:

- namespace squatting and dependency confusion;
- malicious or compromised publisher keys;
- unsafe generated executors;
- denial-of-service packages designed to exhaust compile, memory, or replay budgets;
- malware or illegal assets;
- license laundering and missing attribution;
- private project leakage;
- moderation disputes and takedowns;
- revocation without destroying reproducibility;
- availability and regional compliance.

Required controls include organization namespaces, multi-factor authentication, key rotation, transparency logs, immutable audit events, sandboxed build workers, quotas, staged publication, dependency policy, malware scanning, moderation, appeal, takedown, revocation, backup, and incident response.

## 7.12 Relationship to Local-First Scope

The first commercial scope says hosted services are optional and must not be required for local project access. A public registry and hosted play-link service can coexist with that rule if:

- local projects and already downloaded packages remain usable offline;
- publishing and hosted matchmaking are explicit opt-in services;
- the registry does not become the only source of runtime dependencies;
- private content is not uploaded by default;
- telemetry and crash upload remain opt-in;
- exports remain readable and independently verifiable.

If product strategy makes hosted play or registry access mandatory, it requires a signed commercial-scope revision, privacy review, incident plan, and migration/exit guarantees.

## 7.13 Post-X10 Delivery Program

The universal platform vision requires a new staged program:

| Program | Minimum exit evidence |
| --- | --- |
| W1: Wasm conformance | Core compiles to Wasm, passes CGS/plan fixtures, and matches native tick hashes for a canonical corpus. |
| W2: Browser adapter | Worker-based fixed tick, input, snapshot/delta, playback, lifecycle, and IndexedDB recovery proofs. |
| W3: Browser renderer | WebGL2 reference renderer, accessibility/input controls, asset budgets, and visual regression suite. |
| W4: Browser multiplayer | Selected topology through browser transport with compatibility, rollback/resync, chaos, and abuse proof. |
| R1: Package specification | Versioned manifest, lockfile, license, provenance, signature, and conformance fixtures. |
| R2: Private registry | Authenticated immutable storage, index, trusted publication rebuild, revocation, and recovery. |
| R3: Public registry | Moderation, abuse, license, availability, privacy, support, and external security gates. |
| F1: Fork/remix | Provenance DAG, attribution, typed diff, atomic publication, and fork-to-play usability proof. |
| H1: Hosted play | Signed package resolver, CDN/cache, session service, regional operations, and exit/offline policy. |

These stages should be added only after scope, funding, security, and operating ownership are explicit.

## 7.14 Metrics for Platform Validation

Network effects should be measured rather than asserted. Useful metrics include:

- number of verified reusable packages, not raw uploads;
- dependency-resolution success rate;
- percentage of projects reusing at least one external package;
- median time from fork to first validated play;
- fork-to-publish and fork-to-retained-project conversion;
- replay proof pass rate by runtime/engine version;
- package vulnerability and revocation response time;
- creator support burden per published package;
- percentage of packages with complete license and provenance metadata.

The hypothesis is that verified reuse reduces marginal authoring and validation time. The data must demonstrate the magnitude.

# 8. Strategic Moats and Long-Term Defensibility

## 8.1 The Core Moat Thesis: Proof, Not Generation

General AI systems will continue to improve at producing scripts, gameplay prototypes, editor tools, network templates, and content. A moat based on prompt fluency alone will erode.

XACE's defensible thesis is the proof pipeline:

```text
structured intent
  -> typed contract
  -> dependency schedule
  -> guarded deterministic execution
  -> snapshot/hash/replay evidence
  -> rollback and recovery
  -> multi-engine semantic boundary
```

The compounding asset is not a pile of generated code. It is a growing compatibility and verification system: schemas, conformance cases, plan validators, executor policies, replay corpora, engine matrices, migration fixtures, security rules, and proof artifacts.

## 8.2 Compiler and Protocol Defensibility

The SGC and runtime contract can create defensibility through precision:

- stable scheduling semantics across versions;
- actionable dependency and hazard diagnostics;
- execution-plan identity and compatibility;
- runtime enforcement of declared access sets;
- deterministic artifact reproduction;
- extension ABI and package conformance.

This is not lock-in in the coercive sense. CGS is readable JSON, current licensing is MIT, and portability is part of the product promise. Deliberately making exit expensive would undermine trust.

A healthier moat is earned switching cost: users stay because XACE proof, tooling, compatibility data, and adapters are valuable, while open artifacts preserve a credible exit. The difficulty of replacing XACE should come from reproducing its assurance system, not from withholding user data.

## 8.3 Determinism and Replay Corpus

Every real engine/version/platform combination that passes a canonical replay contributes to a compatibility corpus. Over time, that corpus can expose regressions, migration hazards, and platform-specific behavior earlier than isolated tests.

Defensibility increases if XACE owns:

- well-designed canonical slices with real gameplay state change;
- public conformance fixtures and private adversarial corpora;
- first-divergence diagnosis across schedules, RNG, events, mutations, and state;
- reproducible cross-engine comparison;
- historical compatibility data tied to signed releases.

The corpus must avoid becoming a vanity count. Quality requires representative workloads, failure injection, false-positive controls, and external reproduction.

## 8.4 Adapter and Compatibility Moat

Writing one transport adapter is copyable. Maintaining an adapter across engine versions, packaging systems, editor lifecycles, input models, object ownership, hot reload, recovery, and platform builds is operationally difficult.

The moat becomes meaningful when XACE offers:

- certified engine/version/OS matrices;
- reversible installation and upgrades;
- semantic binding diagnostics;
- canonical cross-engine slices;
- support bundles and reproducible incident triage;
- stable protocol and deprecation policy;
- fast response to engine release changes.

That is a service and reliability moat layered on an open protocol.

## 8.5 Schema Registry Network Effects

A verified registry can create a reuse flywheel:

```text
more verified packages
  -> more proven starting points
  -> shorter validated build time
  -> more successful projects and remixes
  -> more publishers and evidence
```

The flywheel is not automatically exponential. Low-quality, incompatible, insecure, or poorly licensed packages can create negative network effects. Verification, curation, dependency hygiene, search quality, and maintenance determine whether supply is useful.

Registry defensibility may come from the graph of verified compatibility and provenance rather than from raw package count.

## 8.6 BYOK and Local-First Economics

Local models and BYOK reduce XACE's exposure to uncapped inference spending. Existing provider accounting can record prompt, completion, and cache tokens, cost, latency, model, tier, request ID, cache hit, failure, and deterministic-shortcut behavior. Health proofs bind provider, model, endpoint, and credential fingerprint before prompting.

This strategy can support sustainable unit economics:

- certified simple edits avoid provider calls entirely;
- local providers move compute to user-controlled hardware;
- BYOK assigns hosted inference billing to the user's provider relationship;
- budgets, caching, routing evidence, and previews reduce waste;
- paid value can center on signed builds, adapters, compatibility, updates, and support.

It does not ensure zero token liability. XACE may choose to subsidize onboarding, run hosted evaluations, operate a free tier, or pay for support and moderation. A registry, relay, CDN, crash service, or browser host has separate costs even if inference is BYOK.

## 8.7 Security and Trust as a Moat

Safety gates can become differentiated product value if they are real and usable:

- provider calls isolated behind one inference boundary;
- credentials stored in OS vaults on the production Builder path;
- structured output and quarantine;
- unsupported API rejection for generated systems;
- transaction recovery across authoring and runtime;
- immutable plans and proof bundles;
- secret scanning, supply-chain review, release signing, and external assessment;
- redacted support artifacts.

Security claims must wait for X10-081 through X10-086 and external review. The moat is built by repeatable process and response, not by declaring a safe architecture.

## 8.8 Strategic Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Models generate native engine code well enough | A generic generator can undercut chat-first value. | Own validation, proof, replay, rollback, and compatibility. |
| Schema/runtime complexity exceeds creator value | Users may prefer direct scripts for simple games. | Make proof visible, reduce ceremony for certified simple edits, target high-cost failures. |
| Determinism scope is overstated | One uncontrolled side channel breaks confidence. | Publish authority maps, conformance tests, and precise exclusions. |
| Adapter maintenance consumes the team | Three engines multiply compatibility work. | Limit supported versions, automate installed-engine CI, use semantic contracts. |
| Multiplayer becomes a multi-year distraction | Networking expands security and operational scope. | Choose one topology and one vertical slice; gate every broader claim. |
| Registry creates abuse and legal risk | Public uploads add moderation, malware, and licensing obligations. | Stage private registry first; fund operations and legal controls. |
| Founder concentration | A sole-founder project can have bus-factor and review risk. | Reproducible docs, external reviewers, release governance, community contribution path. |
| Open format reduces captive lock-in | Users can leave. | Treat openness as trust; monetize reliability, compatibility, support, and distribution. |

## 8.9 Evidence That Would Validate the Moat

The strongest near-term public demonstration is not a broad prompt showcase. It is a failed change caught and recovered before engine integration:

1. show the original CGS, plan, and world hash;
2. submit a mutation containing a real dependency, type, or determinism fault;
3. show the exact blocked invariant or first divergent tick;
4. show CGS/runtime/adapters restored with matching pre-change identity;
5. apply a corrected change;
6. run the same gameplay core through two or three installed engines;
7. publish the proof bundle and reproduction command.

That demonstration is difficult to fake with generated UI and directly supports the infrastructure thesis.

# 9. Public Launch Readiness

## 9.1 Two Different Launch Profiles

The whitepaper must distinguish:

- Profile A: the governed local-first commercial target represented by X10-001 through X10-100.
- Profile B: the universal browser, hosted play, registry, and remix platform proposed in Section 7.

Completing Profile A does not imply Profile B. Profile B requires a scope revision and a separate delivery program.

## 9.2 Profile A: X10 Commercial Readiness

### 9.2.1 Core Correctness

- All workspace Rust tests pass on Windows, Linux, and macOS.
- One Python command runs every production suite with explicit counts and artifacts.
- Builder server/UI test, build, typecheck, and lint run in CI.
- CGS, plan, executor ABI, adapter protocol, and proof schemas have conformance fixtures.
- No production path silently falls back to a fake, skip, filtered schedule, or partial snapshot.

### 9.2.2 Determinism and Recovery

- The same canonical input log produces identical runtime-authoritative hashes on three operating systems.
- Replay divergence diagnosis identifies the first mismatched identity or state field.
- Mutation, prompt apply, crash recovery, save restore, and adapter rollback survive failure injection.
- Snapshot capture/restore and retention meet published size and latency budgets.

### 9.2.3 Prompt and Provider

- Composite planning, proof-linked undo/redo, and long-session degradation tests pass.
- The launch provider/runtime profile uses opt-in real provider/model evidence for claimed routes.
- Structured output, repair/quarantine, cost, latency, retry, health, routing, and security metrics pass thresholds.
- Public language says certified supported scenarios, not arbitrary game generation or zero hallucination.

### 9.2.4 Multiplayer

- One topology is selected and documented.
- Runtime tick advancement consumes synchronized input.
- Rollback manager invokes complete snapshot restore and bounded resimulation.
- Prediction/reconciliation, lobby/session lifecycle, version checks, authority, resync, and malicious-input limits are integrated.
- Diagnostics expose wait, rollback, desync, resync, and compatibility state.
- Chaos and long multi-user soak pass with retained artifacts.

### 9.2.5 Engines and Assets

- Asset reference and semantic binding UX identifies unresolved and engine-specific states.
- Adapter install, uninstall, preflight, handoff, and versioning are reversible and documented.
- One canonical gameplay slice runs in installed Godot, Unity, and Unreal versions through CI or a controlled lab.
- Core schedule/world identities are compared across the same slice.
- Visual onboarding/playthrough evidence confirms the product workflow, not only commandlet protocol health.

### 9.2.6 Saves, Packages, Extensions, and Teams

- Save authority and schema migration pass real old-save corpora and corruption tests.
- Templates and packages have stable versions and dependency rules.
- Third-party extension capability and signing boundaries are defined.
- Team source-control guidance covers generated plans, proof artifacts, lockfiles, merges, and migrations.

### 9.2.7 Performance, Security, and Operations

- Representative scale benchmarks meet published CPU, memory, snapshot, tick, and adapter budgets.
- Fuzzing covers parsers, mutation boundaries, network packets, saves, and protocol frames.
- Eight-hour integrated soak passes.
- Reproducible builds and signed artifacts are verified on a fresh machine.
- Supply chain, secrets, privacy, telemetry opt-in, backup, disaster recovery, and external security review pass.
- Support diagnostics and incident processes are operational.

### 9.2.8 User and Release Gates

- Fresh-user installation and onboarding work without repository knowledge.
- External creators complete representative tasks and recover from errors.
- Compatibility matrices are generated from retained evidence.
- Three public demos map every visible claim to a proof artifact.
- Readiness scores receive independent review.
- X10-098 private alpha, X10-099 public beta, and X10-100 commercial launch receive signed gate approval.

[[DIAGRAM:launch_gates]]

## 9.3 Profile B: Universal Browser and Remix Readiness

In addition to every relevant Profile A gate:

- Native and Wasm runtimes pass a shared conformance and replay corpus.
- The Web Worker simulation host survives lifecycle, throttling, storage eviction, and mobile memory conditions.
- WebGL2 reference rendering and optional WebGPU meet browser/device matrices.
- Browser asset packages have signed provenance, licensing, and budgets.
- Hosted play resolution verifies signed immutable packages and supports offline/local exit.
- Browser multiplayer passes the selected topology's chaos, security, abuse, and reconnect tests.
- The registry provides immutable artifacts, exact lockfiles, publisher identity, transparency, moderation, revocation, backup, and incident response.
- Fork/remix preserves provenance, attribution, licensing, and atomic validation.
- Privacy, regional operations, service levels, cost model, and support are approved.
- External creator tests demonstrate safe fork-to-play and fork-to-publish flows.

## 9.4 Requested Four Claims Recast as Verifiable Gates

| Requested claim | Evidence-aligned launch gate |
| --- | --- |
| 100% automated rollback netcode | One selected topology passes integrated input, restore/resimulation, reconciliation, compatibility, chaos, malicious-input, diagnostics, and soak gates. Avoid 100% language. |
| Production WebAssembly browser engine with bundled 3D assets | Profile B Wasm, renderer, package, asset-license, device, performance, security, and operations program passes. |
| Full grammar-constrained decoding with zero hallucination | Supported providers enforce structured syntax or quarantine; semantic errors remain subject to local validation. Publish measured failure rates, never zero-hallucination. |
| Live registry with fork/remix | Signed immutable registry, provenance DAG, licensing, moderation, security, availability, and external usability gates pass. |

## 9.5 Launch Decision Rule

Public readiness is not the absence of known failing tests. It is a signed decision that:

- product scope is frozen and accurately described;
- every claim has reproducible evidence;
- known limitations are visible to users;
- recovery, support, privacy, and security operations exist;
- installation and upgrade work on clean machines;
- the team can maintain what it is launching.

If a required gate is not run, the result is unsupported for that release. A local smoke, test double, self-test, or current-machine success may inform engineering confidence but cannot be promoted into a broader claim.

# 10. Architectural Conclusions

XACE has a coherent and increasingly concrete core: versioned gameplay definitions, deterministic graph compilation, strict persisted schedule identity, guarded fixed-tick execution, fixed-point authoritative values, complete snapshot contracts, replay hashes, transactional mutation recovery, constrained prompt operations, reusable gameplay primitives, and host-engine adapters.

Its strongest opportunity is not to compete with general models at writing the most code. It is to become the authority that decides whether an AI- or human-proposed gameplay change is valid, deterministic under the supported model, reproducible, recoverable, and portable through declared adapter contracts.

The next engineering sequence should follow the tasklist: composite prompt planning, proof-linked authoring history, long-session prompt testing, then one deliberately selected multiplayer topology. Browser play, public registry, and social remix are significant separate products. They can amplify the protocol thesis, but only if their hosting, security, licensing, moderation, and operations are funded and governed explicitly.

The project should preserve three disciplines as it grows:

1. AI proposes; local contracts authorize.
2. Artifacts are identified, versioned, and reproducible.
3. Public claims never outrun retained evidence.

# Appendix A. Claim Correction Matrix

| Requested statement | Evidence-aligned formulation |
| --- | --- |
| AI-native game engine | Local-first deterministic gameplay infrastructure with AI-assisted authoring and host-engine adapters |
| Canonical Graph Schema | Canonical Game Schema |
| Type-safe immutable state graph | Closed typed operations update a versioned, canonical, hash-identified CGS transactionally |
| SGC parallelizes tick updates | SGC computes safe parallel-eligible groups; current standalone runtime executes them deterministically and sequentially |
| Mutation Guardian mathematically prevents code rot | GDE/SGC/runtime gates reject covered schema, dependency, access, ABI, and transaction faults |
| Fixed point eliminates all platform divergence | Fixed point removes a major authoritative numeric divergence source; full cross-platform proof remains gated |
| World hashes provide zero-netcode synchronization | World hashes prove or detect encoded state equality/divergence; networking is still required |
| Native GGPO rollback is built | Snapshot/restore and rollback-planning primitives exist; runtime-integrated network resimulation remains open |
| Snapshots are zero-copy and under 1 ms | Current snapshots are deep copies; performance budgets are not yet certified |
| Basic Wasm/WebGL player exists | Browser runtime is a forward architecture, not current implementation |
| PIL grammar integration is remaining | Provider structured output, hard paths, typed operations, and one generated behavior are complete; composite planning remains |
| Unity and Unreal adapters are remaining | Adapter code and current-machine validation exist; common-slice hardening and release-wide certification remain |
| Instant browser preview with no install | Future WebRuntime target; current product is local Builder/runtime plus host-engine adapters |
| One-click finished-game export | Current export is adapter package handoff for engine-owned integration |
| Time-travel debugger is available | Tick debugger and reverse navigation begin at X10-045 and remain open |
| Bundled royalty-free assets and procedural levels | Separate future content, licensing, provenance, and performance program |
| Public schema registry is part of the 100 tasks | Portable export and package foundations exist; public registry requires a separate roadmap |
| Compiler lock-in is the moat | Open portability plus hard-to-replicate proof, compatibility, tooling, and support is the healthier moat |
| Registry creates exponential acceleration | Verified reuse may reduce marginal authoring time; measure the effect |
| BYOK creates zero token liability | BYOK/local models reduce uncapped inference exposure; other product and service costs remain |
| Grammar constraints mean zero hallucination | Syntax can be constrained; semantic errors remain and require local validation |

# Appendix B. Core Data Structures and Invariants

## B.1 CGS System Definition

```text
SystemDefinition
  id: stable string
  phase: one of five authoritative phases
  reads: sorted set<ComponentTypeId>
  writes: sorted set<ComponentTypeId>
  depends_on: sorted set<SystemId>
  deterministic: boolean
  version: compatibility metadata
  description: user-facing metadata
  runtime_executor: optional validated executor envelope
```

Key invariant: runtime access must not exceed the persisted declared access set.

## B.2 Raw System Graph

```text
nodes: BTreeMap<SystemId, SystemNode>
edges: BTreeMap<(from, to), SystemEdge>
edge reason: explicit | RAW | WAW | phase order
```

Key invariant: the same validated system definitions produce the same graph and diagnostics independent of input order.

## B.3 Execution Plan

```text
identity:
  schema_version
  plan_version
  adapter_protocol_version
  compiled_from_cgs_hash
  plan_hash

schedule:
  phases[0..4]
  groups with group_id, execution_index, parallel eligibility
  ordered system IDs
  serialization constraints

metadata:
  component access sets
  system metadata and dependency map
  proof bundle reference
```

Key invariant: a plan for one CGS hash is byte-immutable and cannot silently migrate or downgrade.

## B.4 Authoritative World

```text
EntityStore
  BTreeMap<EntityId, EntityMetadata>
  monotonic next ID
  archive of never-reused IDs

ComponentTableStore
  BTreeMap<ComponentTypeId, ComponentTable>
  rows ordered by EntityId

Runtime side state
  fixed tick
  deterministic RNG windows and positions
  phase-buffered events
  deferred mutation queues
  sealed schedule identity
```

Key invariant: no component row exists for an unknown entity, and systems mutate structural state only through MutationGate.

## B.5 WorldSnapshot

```text
tick and Fixed64 time
schema and plan versions
CGS hash
entity records and next ID
component tables and rows
RNG world seed and stream positions
pending events and next event ID
pending spawn/add/modify/remove/destroy queues
world hash
clean boundary flag
```

Key invariant: serialize, deserialize, and restore must preserve every authoritative field and recompute the expected hash.

## B.6 Typed Operation Batch

```text
schema: xace.typed_cgs_operation_batch.v1
request_id
prompt_id
summary
operations[]:
  operation_id
  kind
  stable targets
  typed payload
  explanation
```

Key invariant: the provider-facing form is closed and path-free; executable metadata is local-only.

# Appendix C. Threat Model and Failure Modes

## C.1 Prompt and Provider Boundary

| Threat | Control | Open work |
| --- | --- | --- |
| Prompt injection or hallucinated capability | Capability classifier, security corpus, blocked routes | Broader external review and evolving attack corpus |
| Malformed model response | Native structured output or repair/quarantine plus schema validation | Live reliability at scale |
| Provider-supplied executable | Executor/source fields absent and rejected; local materializer owns ABI | Expand supported behaviors without widening authority accidentally |
| Secret leakage | Central inference boundary, redacted accounting, OS credential store in Builder | Complete security review and remove/archive placeholder credential paths |
| Cost explosion | Budgets, accounting, caching, routing evidence, deterministic shortcuts, BYOK/local | Product-level quotas and hosted-service economics |

## C.2 CGS and Compiler Boundary

| Threat | Control | Open work |
| --- | --- | --- |
| Stale overwrite | Parent CGS hash and project lock | Team merge workflow and distributed collaboration |
| Dependency cycle | GDE static DFS and SGC cycle detection | Fuzz/adversarial scale proof |
| Undeclared read/write | Static checks plus runtime guarded context | Third-party extension enforcement |
| Plan substitution | CGS/plan identity tuple, canonical path, immutable bytes | Release signatures and remote package trust |
| Schema drift across languages | Layered validation and conformance tools | Unified generated schema/conformance corpus |

## C.3 Runtime Boundary

| Threat | Control | Open work |
| --- | --- | --- |
| Mid-phase structural mutation | Deferred MutationGate | Concurrency/fuzz proof |
| Partial batch apply | Pre-batch rollback images and hash verification | Performance and hostile-scale testing |
| Nondeterministic time/RNG | Fixed tick and deterministic RNG windows | Broader instrumentation and platform proof |
| Incomplete snapshot | Required complete fields and validation | Copy-on-write/delta optimization with conformance |
| Engine side-effect leak after rollback | Adapter rollback notice and cleanup paths | Common installed-engine failure proof |

## C.4 Network Boundary

| Threat | Current foundation | Required integration |
| --- | --- | --- |
| Late, duplicate, stale, or missing input | Typed input buffers and lockstep decisions | Runtime tick gating and chaos proof |
| Desync | Hash comparison and reports | Bounded resync policy tied to complete snapshots |
| Malicious input | Validation primitives | X10-041 limits, authentication, rate controls, fuzzing |
| Rollback exhaustion | Replay-span and retention limits in planner | Runtime cost budgets and denial-of-service policy |
| Version mismatch | Identity fields and session concepts | Enforced session compatibility handshake |

## C.5 Registry and Hosted Boundary

This boundary is future work. It adds publisher compromise, dependency confusion, package denial of service, malware, illegal content, license disputes, account takeover, service outage, privacy, and regional compliance. A registry should not launch without funded operating ownership.

# Appendix D. Performance and Capacity Blueprint

No universal performance claim is justified until X10-074 and X10-075 define representative workloads. The benchmark matrix should include:

| Dimension | Suggested cases | Primary metrics |
| --- | --- | --- |
| Entity scale | 1k, 10k, 100k active entities where realistic | tick time, memory, iteration cost |
| Component density | sparse, typical, dense | table memory, query time, mutation cost |
| System graph | 10, 100, 1k systems with varied hazards | compile time, plan size, window quality |
| Mutation batch | 1, 100, 10k operations with injected failure | validate, apply, rollback time, memory |
| Snapshot | varied world sizes and queue states | bytes, capture, serialize, restore, hash time |
| Replay | 10k+ ticks and injected divergence | throughput, storage, first-difference latency |
| Adapter | snapshot and delta payload scales | bytes/tick, encode/decode, apply time, backlog |
| Network | peer count, latency, loss, reorder, duplication | wait, rollback rate, resim cost, desync recovery |
| Prompt | corpus size and long sessions | latency, cost, failure/repair rate, memory growth |
| Browser future | desktop/mobile devices | Wasm tick, snapshot, renderer frame, memory, startup |

Budgets must be percentile-based and tied to hardware classes. Average latency can hide catastrophic p99 behavior. Every benchmark should record CGS, plan, runtime build, compiler flags, hardware, OS, engine, world seed, input log, and artifact hash.

# Appendix E. Proof and Certification Hierarchy

From weakest to strongest:

1. Source exists.
2. Unit test covers a function.
3. Focused integration test covers package boundaries.
4. Smoke runs a named scenario.
5. Retained proof records real binaries, inputs, identities, hashes, and outputs.
6. Reproducible local certification orchestrates required proofs.
7. Hosted cross-platform CI retains the same proof across required environments.
8. Installed-engine proof runs real editors on a canonical slice.
9. Chaos, fuzz, security, and long soak cover adverse conditions.
10. External reproduction and independent review validate the evidence.
11. Signed release gates bind artifacts, claims, compatibility, and support.

A higher level does not make every lower-level scenario universal. Evidence remains scoped to the workload, versions, and failure conditions actually executed.

# Appendix F. Glossary

| Term | Definition |
| --- | --- |
| Adapter protocol | Versioned messages between runtime authority and a host engine or browser presentation layer. |
| Authoritative state | State whose exact value affects simulation correctness and replay identity. |
| CGS | Canonical Game Schema, the versioned gameplay definition. |
| Clean boundary | A point where phase mutations/events are drained and snapshot state is safe under the current contract. |
| Deterministic replay | Re-execution from the same authoritative inputs and identities with matching per-tick hashes. |
| Fixed64 | Signed `i64` fixed-point value with one million raw units per whole unit. |
| GDE | Game Definition Engine, owner of validated CGS transactions. |
| MutationGate | Runtime gateway for deferred spawn/add/modify/remove/destroy operations. |
| PIL | Prompt Intelligence Layer, the constrained authoring pipeline above GDE. |
| Plan hash | SGC-owned digest identifying the compiled schedule semantics. |
| Proof bundle | Retained inputs, identities, outputs, validation results, and hashes for a defined scenario. |
| SGC | System Graph Compiler, the Rust dependency and schedule compiler. |
| Snapshot | Complete captured authoritative world state under a versioned contract. |
| Typed operation | Closed, path-free structural CGS mutation with stable targets and exact field types. |
| World hash | SHA-256 digest of the ordered authoritative snapshot fields. |

# Appendix G. Primary Repository References

## G.1 Governance and Status

- `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md`
- `docs/XACE_COMMERCIAL_SCOPE.md`
- `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`
- `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md`
- `docs/XACE_FAKE_AND_SKIP_REGISTER.md`
- `docs/LAUNCH_READINESS_MAP.md`

## G.2 Core Contracts

- `docs/CGS_SCHEMA_EXPORT_FORMAT.md`
- `docs/SGC_EXECUTION_PLAN_CONTRACT.md`
- `docs/FIXED_POINT_NUMERIC_MODEL.md`
- `docs/SNAPSHOT_SERIALIZATION_CONTRACT.md`
- `docs/STATE_AUTHORITY_RULES.md`
- `docs/REPLAY_CROSS_PLATFORM_PROOF.md`
- `docs/05_mutation_lifecycle.md`
- `docs/TYPED_CGS_OPERATIONS.md`
- `docs/PROMPT_CAPABILITY_MATRIX.md`
- `docs/INFERENCE_ADAPTER_BOUNDARY.md`

## G.3 Principal Implementation Anchors

- `packages/core/src/fixed_point.rs`
- `packages/core/src/runtime/world_snapshot.rs`
- `packages/system-graph-compiler/src/sgc_pipeline.rs`
- `packages/system-graph-compiler/src/dependency_resolution/topological_sorter.rs`
- `packages/system-graph-compiler/src/graph_construction/hazard_detector.rs`
- `packages/system-graph-compiler/src/scheduler/parallel_group_analyzer.rs`
- `packages/runtime-core/src/cgs_loader.rs`
- `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs`
- `packages/runtime-core/src/mutation_gate/mutation_gate.rs`
- `packages/runtime-core/src/determinism_guard/world_hasher.rs`
- `packages/runtime-core/src/snapshot_engine/snapshot_engine.rs`
- `packages/runtime-core/src/runtime_orchestrator.rs`
- `packages/gde/src/consistency_validator/static_mutation_conflict_analyzer.py`
- `packages/gde/src/gde_orchestrator.py`
- `packages/prompt-intelligence/src/typed_operations/`
- `packages/prompt-intelligence/src/code_generation/generated_system_materializer.py`
- `packages/network-core/src/prediction/rollback_manager.rs`
- `packages/dcl/gameplay_primitives.py`
- `adapters/godot/`, `adapters/unity/`, `adapters/unreal/`

## G.4 Retained X10-029 to X10-031 Evidence

- `target-codex-task29-primitives/gameplay-primitives/report.json`
- `target-codex-task30-typed-operations/report.json`
- `target-codex-task31-generated-systems/report.json`

# End Note

This publication intentionally distinguishes present implementation from intended architecture. That distinction is not a weakness. It is the operating discipline required for XACE to become trusted infrastructure.


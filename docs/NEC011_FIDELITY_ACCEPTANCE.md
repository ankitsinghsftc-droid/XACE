# NEC-011 amended fidelity acceptance - active specification

Entry: post-NEC010 commit44cb7bf. This document defines acceptance; it is not implementation or certification evidence. NEC012 is not authorized to start. The frozen recovered XP022 seal remains untouched.

## Required proof cells

1. Structured transform reads/writes and parented instances retain stable World-to-runtime entity identity, deterministic coordinate composition, snapshot restoration and replay. Unsupported shear, numeric/backend modes or geometry must refuse explicitly. No removal of existing admission gates until corresponding proofs pass.
2. Role-bound resources, declared input actions/packet mapping and animation/audio events execute in the installed supported engines. Cosmetic replacements preserve gameplay hashes; missing required resources, wrong axes/scale, stale input/controller and invalid timing authority block readiness. Saved declarations alone do not pass.
3. Saved-change batching waits for a stable saved revision; repeated unchanged captures are no-ops. Changes during review invalidate approval; conflicts retain both versions. No silent overwrite or unattended approval.
4. Trusted custom executor contract binds source and build inputs, pinned creator toolchain, reproducible build identity, executable hash, required capabilities, system access/scheduling, numeric/backend profile, state/snapshot/replay versions and shipping dependencies. General custom code must execute through Runtime ISystem/SystemContext and Mutation Gate; engine adapters remain presentation/input/feedback only. The current generated executor enum is a fixed operation catalog, not this general extension path.

## Concrete benchmark: delayed echo graph

The player creates a directed graph of echo nodes. Each edge carries a delay and signed fixed-point gain. A pulse propagates through the graph in stable node/edge order; arrivals combine at a tick boundary, and a rewind action restores the graph and pending pulse queue to a retained checkpoint. A deterministic routing rule redirects pulses when a node threshold is crossed. This requires graph traversal, a bounded delayed queue and checkpointable gameplay state beyond set/copy/increment/RNG-threshold declarations.

Declare finite bounds for nodes, edges, pending pulses, delay, fixed-point overflow and rewind horizon. Store all gameplay state in snapshotted components/resources; no hidden executor mutable state. Inputs carry ticks. Simultaneous arrivals use a specified total order. Rewind/replay must reproduce every world hash and event, including duplicate inputs, queue exhaustion and overflow refusal.

Creator-side proof: compile the actual Rust mechanic from retained source using a pinned toolchain and dependency lock; demonstrate reproducible admitted identity and reject a changed executable/capability set. Build through Factory/SGC and execute the registered custom system. Record state/events, snapshot mid-queue, restore and replay, compare hashes, then package the pinned runtime/executor plus CGS/resources and run a relocated copy without compiling. No model-generated code or fixed-op substitute counts as execution evidence. Native engine build/clean-machine distribution remains required in NEC012-018; a creator-side package proof cannot certify those future cells.

## Prerequisite and impact accounting

Current adoption/reconciliation explicitly block parented instances and systems accessing component1. Current generated_system_abi.rs exposes four operations. Removing either refusal without a versioned runtime/executor proof would weaken acceptance. Implementation must identify whether existing runtime contracts can carry the required state and structured access; if a larger prerequisite cannot fit NEC011/012 responsibly, record concrete changed modules, proof impact and an estimate before expanding scope.

NEC011 is not complete. No benchmark execution, unrestricted mechanics, native shipping or Steam support is claimed by this specification.

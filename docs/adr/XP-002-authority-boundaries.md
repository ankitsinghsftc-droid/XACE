# XP-002: compiler, input, preview and feedback authority

Decision date: 2026-09-24. Scope: XP-002 only.

Builder submits candidate CGS to the real Schema Factory. Its compiled package's
`to_sgc_input()` is the only Builder projection into SGC. The portable adapter
normalizes display enums on a deep copy and builds a registry from shipped UCL/DCL
contracts and explicit project declarations. Actor values cannot invent registry
entries. All ten core identities remain frozen. Generated GDE declarations are
GCL (IDs >= 10000), with exact declared field metadata. Value-only GDE edits also
pass this validation before persistence. Rejection reloads the prior GDE candidate;
if restore fails, that session's GDE is disabled. No extraction fallback exists.

The adapter validates existing world coordinates and registry/value contracts;
it is not World Contract v1, geometry compilation or a second CGS authority.
Structured UCL field types and the shipped portable primitive vocabulary are
supported. Source CGS identity is retained, not replaced by a projection hash.

External packets are validated, sorted and staged at tick start. A declared
`EngineInputSystem` submits mutations through `ISystemContext` and MutationGate.
It has reads=[] and writes=[6], and must be the first singleton sequential Input
group in the ExecutionPlan. Later Input consumers depend on it. Runtime never
inserts a production plan entry. Missing ingress rejects packets with
`input_ingress_not_scheduled`; malformed ingress rejects plan loading. Direct
input mode rejects a packet whose tick differs from the current tick. Existing
lockstep/prediction admission policies still handle their own timing.

`--live-session` requires this ingress and persisted SGC policy at initialization
and hot swap. This flag enables restrictions only: it does not implement network
admission, peer ownership, Player packaging, epoch distribution or session sockets.
Those remain the later roadmap tasks. Legacy dev derived planning only splits an
already declared ingress; it never synthesizes an absent system.

Preview edits clone entity/table state, apply through a separate MutationGate and
retain isolated candidate tables. The live state, mutation queue and world hash
remain unchanged. `preview_component_json()` reads that isolated result. Each
preview starts from the current live state; it is not an accumulating branch or
an adapter-rendered preview world. Live-session mode rejects legacy preview writes
entirely. Approved edits must use the existing GDE transaction pipeline.

Feedback is still buffered, sorted and drained at tick boundaries. The live
profile rejects PhysicsSettled and VisibilityQueryResult before handler routing:
native contacts/raycasts cannot supply authoritative geometry. The other eight
feedback kinds retain existing typed validation and presentation/diagnostic
handlers; they do not receive authoritative component stores. Future gameplay
consumers must use declared runtime systems and MutationGate. This does not claim
native engine feedback certification or implement the planned geometry layer.

Migration is explicit. Add EngineInputSystem to CGS, declare its access and Input
consumer dependencies, then recompile through Factory/SGC. Do not hand-edit a
persisted plan. Old exports with undeclared DCL types, conflicting IDs/names,
noncanonical sources or unsupported fields must be migrated to canonical component
schemas before Builder can commit them. In particular, the root legacy game and
canonical_cross_engine_vertical_slice export are not automatically rewritten or
certified by this task. Previously persisted legacy plans can still run outside
live-session mode, but cannot admit external input without explicit ingress.

Evidence: `docs/XP002_COMPLETION.md`, `docs/evidence/xp002-baseline.json` and
`python tools/xp002_authority_proof.py`. The proof uses real Builder/GDE/Factory/
SGC/runtime on a disposable offline project. It does not invoke a provider or
native engine and does not certify multiplayer or whole-product readiness.

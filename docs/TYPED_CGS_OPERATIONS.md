# Typed CGS Operations

Status: production path for X10-030, the X10-031 generated-system extension,
the X10-032 composite prompt planning extension, and the X10-033 prompt
undo/redo history extension. Operation batch schema:
`xace.typed_cgs_operation_batch.v1`.

Structural prompt output is a closed, path-free operation batch. Provider output
cannot choose a CGS path or emit a generic JSON-patch operation. Existing scalar
`SET` and `SCALE` edits retain the legacy value-mutation path; new component
schemas, component attachments, registered systems, semantic events, rules,
assets, component defaults, and prompt-defined generated systems use the typed
path exclusively. Composite prompts do not add a second mutation language; they
derive an auditable `xace.composite_prompt_plan.v1` envelope from the same
canonical typed batch.

## Operation families

| Kind | Stable target | Authoritative effect |
| --- | --- | --- |
| `declare_component` | generated type ID and canonical name | Adds a versioned schema with typed fields and defaults. Generated IDs start at 10000. |
| `add_component` | mode ID, actor ID, component type ID | Resolves the schema locally and attaches a complete default record. |
| `set_defaults` | mode ID, actor ID, component type ID, field names | Updates existing attached fields after exact type validation. |
| `add_system` | system ID and implementation reference | Adds only a registered runtime builtin whose phase/read/write contract matches exactly. |
| `add_generated_system` | system ID and closed behavior | Describes a deterministic generated system without provider-authored code or runtime metadata. The initial behavior increments one exact `fixed` field by an integer whole-unit delta. |
| `add_event` | semantic event name | Adds a versioned, typed payload contract. |
| `add_rule` | mode ID and rule ID | Adds a deterministic declarative rule record. |
| `add_asset` | asset ID | Adds a placeholder, missing, or safe project-relative linked asset record. |

Each operation has a stable `operation_id` and a user-facing `explanation`.
The batch also binds `request_id`, `prompt_id`, and a summary. Unknown fields,
unknown operation kinds, duplicate targets, floats, bool-as-int values, unsafe
asset traversal, missing live IDs, type drift, and mixed typed/legacy envelopes
fail closed.

The provider-facing form stays within the native strict structured-output
subset: its root is an object, operation variants use nested `anyOf`, every
object is closed with `additionalProperties: false`, and every declared object
property is required. Optional wire fields are materialized by canonical
normalization. The provider schema contains no `oneOf`, `$id`, `uniqueItems`,
generic patch value, or CGS path field; uniqueness is rechecked by the parser.

An existing component can participate in typed attachment/default operations
only when its `component_schemas` record includes exact `fields[].field_type`
metadata matching its defaults. XACE does not infer whether an integer is
`fixed`, `int`, `uint`, or `entity_id`; missing metadata and numeric type
interchange fail closed at both the prompt preview and GDE boundaries.

## Production flow

1. Pass 1 classifies schema-creating intent.
2. Pass 2 requests the provider JSON Schema and parses the response into the
   closed typed model. Request and prompt IDs must match the inference request.
3. When Pass 1 selects `composite_feature_add`, Pass 2 must emit one ordered,
   self-contained typed batch. A local composite planner derives the operation
   order, dependency graph, schema/system/asset/save/network facet coverage,
   save/network facet plans, and rollback plan from that batch. Missing required
   facets or too few systems fail closed before preview.
4. When the batch contains `add_generated_system`, the local materializer
   validates the behavior against exact component metadata, stages an isolated
   CGS, derives the deterministic ABI and rollback hooks, generates source
   locally, and runs the safe compiler plus the real SGC. Only a matching,
   locally signed runtime executor may be attached to the trusted batch.
5. The trusted batch is reparsed with an explicit internal-only materialization
   flag. The provider-facing parser and structured-output schema never accept
   `runtime_executor`, ABI, compile artifact, generated source, or arbitrary
   executable code.
6. The structured parser normalizes the batch and validates it against a deep
   copy of the current CGS. No operation is lowered into a path mutation.
7. Builder stores the canonical batch and any derived composite plan in the
   approval preview, fingerprints them, and records path-free operation
   summaries, save/network facet previews, and batch provenance.
8. On approval, Builder revalidates the composite plan against the canonical
   batch when present. GDE then reparses the trust-boundary payload, resolves stable IDs,
   applies every operation to an isolated copy, runs whole-CGS consistency
   validation, and performs one minor-version commit.
9. Builder requires SGC for the typed batch, persists the exact plan/proof
   bundle, reloads and validates runtime state, and uses the existing full-state
   recovery path if any downstream step fails.
10. Successful prompt applies append a durable prompt-history entry bound to the
    pre/post CGS hashes, typed-operation provenance, optional composite-plan
    hash, snapshot path, persisted ExecutionPlan, and SGC proof bundle. Undo and
    redo restore only from that linear proof-linked history and reject stale
    current hashes or target states missing snapshot/plan/proof links.

A failure at any typed operation, consistency check, SGC step, persistence
step, runtime validation, or replay hook never exposes a partially authored
CGS. The pre-apply CGS and artifacts remain available for exact rollback.

## Composite prompt planning boundary

`composite_feature_add` is a planning route for prompts that need multiple
ordered structural families at once, such as adding gameplay behavior with
schema, several systems, asset declarations, save policy, and network policy.
It remains bound to the closed typed operation grammar above.

The locally derived composite envelope contains:

- the canonical typed-batch hash and operation order;
- an acyclic dependency graph with topological order and explicit edges for
  batch ordering, component schema/attachment dependencies, and system
  dependencies;
- facet membership for schema, system, event, rule, asset, defaults, save, and
  network operations;
- save and network facet plans derived from canonical component attachments or
  defaults for registered save/network component type IDs;
- a rollback plan bound to the pre-apply CGS hash, proposed CGS hash, and exact
  operation IDs.

Builder exposes the composite plan during preview and includes save/network
facet summaries so approval can see the cross-cutting effects before commit.
Apply provenance records the composite plan hash, schema, operation order, and
rollback pre-hash. Tampering with the stored plan, such as changing operation
order after preview, is rejected before apply.

## Executable-system boundary

X10-030 may select an existing registered builtin through
`implementation_ref = builtin.<SystemID>.v1`, with exact phase/read/write
metadata. X10-031 adds a separate `add_generated_system` grammar; it does not
weaken the builtin contract or let a provider invent a system executor.

Provider output for a generated system contains only stable IDs, phase,
sorted/unique reads and writes, dependencies, version/scope metadata, a
user-facing explanation, and a closed behavior object. The initial supported
behavior is `increment_numeric_field`; its component must be present in both
reads and writes, its target schema field must be exactly `fixed`, and its
amount must be an integer. Provider-supplied `runtime_executor` is rejected by
default and absent from the strict response schema.

The local materializer owns source generation, the full
`xace.generated_system_abi.v1` envelope, halt-and-rollback policy, mutation/event/RNG
rollback hooks, safe compilation, real-SGC validation, and compile-artifact
signing. Nondeterministic wall-clock compile timing is excluded from
authoritative CGS by storing the canonical artifact value `cargo.duration_ms =
0`. GDE independently requires the exact generated executor envelope and
complete system record before commit. This is a narrow generated behavior
contract, not a claim that arbitrary provider-authored gameplay code is safe.
Semantic events and assets are validated and persisted declarative contracts;
this task does not claim that every newly declared event or asset has runtime
behavior without a consuming system or binding.

## Prompt undo/redo boundary

Prompt undo/redo is a restore operation over already-committed prompt mutation
history, not a new mutation grammar. Builder persists
`.xace/audit/prompt_history.json` and appends restore events to
`.xace/audit/prompt_history_events.jsonl`. Each history entry binds the source
transaction, pre/post CGS hashes, version IDs, typed-operation provenance,
proof links, and the history cursor before and after the apply.

An undo or redo request must match the current CGS hash at the history cursor.
The restore plan is rejected unless the target CGS hash has a retained snapshot,
persisted ExecutionPlan, and SGC proof bundle. Accepted restore events include
the same proof links that justified the target state, so audit review can walk
from user prompt to CGS snapshot, SGC plan/proof bundle, runtime load, and replay
hash evidence without trusting transient UI state.

## Retained proof

Run:

```powershell
python tools/typed_cgs_operation_e2e_check.py `
  --runtime-bin <target>\debug\xace_runtime.exe `
  --sgc-bin <target>\debug\xace-system-graph-compiler.exe `
  --artifact-dir <output>\artifacts `
  --output <output>\report.json `
  --json
```

The proof produces all seven operation families, commits through the live
Builder/GDE boundary, validates the standalone CGS, invokes the real SGC,
loads its persisted plan in the real runtime twice, compares replay hashes and
schedules, proves a late-operation failure is atomic, and restores the exact
pre-commit CGS hash and bytes. It also statically validates all provider-schema
objects against the strict subset and proves mismatched numeric types and
negative unsigned assignments are rejected without changing authoritative CGS.

The X10-031 retained certification command is:

```powershell
python tools/generated_system_prompt_e2e_check.py `
  --runtime-bin <target>\debug\xace_runtime.exe `
  --sgc-bin <target>\debug\xace-system-graph-compiler.exe `
  --artifact-dir <output>\artifacts `
  --output <output>\report.json `
  --json
```

The retained report at
`target-codex-task31-generated-systems/report.json` passes all 25 checks. It
covers provider-schema exclusion of executable metadata, local
materialization/signing, the complete generated-system contract, atomic GDE
commit, real SGC and persisted runtime execution, deterministic replay, exact
rollback, and fail-closed unsigned/tampered/provider-executor rejection. Two
consecutive runs produced the same report SHA-256:
`5dfd9f7395128b2709b2639ac2decf5ad2f692a0fb7f8c8391c16320ea0e03b1`.

The X10-032 retained certification command is:

```powershell
python tools/composite_prompt_planning_e2e_check.py `
  --runtime-bin <target>\debug\xace_runtime.exe `
  --sgc-bin <target>\debug\xace-system-graph-compiler.exe `
  --artifact-dir <output>\artifacts `
  --output <output>\report.json `
  --json
```

The retained report at
`target-codex-task32-composite-planning/report.json` passes all 17 checks. It
covers required schema/system/asset/save/network facets, acyclic dependency
graph ordering, Builder preview preservation, save/network previews, atomic GDE
commit, standalone CGS validation, real SGC and persisted runtime execution,
schedule/tick replay matching, tampered-plan rejection, mid-batch failure
atomicity, and exact rollback. Its SHA-256 is
`2d382a49df1ce3cbc5f76c81fcc75907303b36b4f3eab440e90ba40b306f87db`.

The X10-033 retained certification command is:

```powershell
python tools/prompt_undo_redo_e2e_check.py `
  --runtime-bin <target>\debug\xace_runtime.exe `
  --sgc-bin <target>\debug\xace-system-graph-compiler.exe `
  --artifact-dir <output>\artifacts `
  --output <output>\report.json `
  --json
```

The retained report at
`target-codex-task33-prompt-history/report.json` passes all 14 checks. It
builds 50 chained closed typed prompt mutations, stores snapshots,
ExecutionPlans, and SGC proof bundles for every state, then performs 50 undos
and 50 redos. Every restored state matches the recorded CGS JSON hash, SGC plan
hash, runtime world hash, runtime hash-log hash, and schedule/replay
fingerprint. Its SHA-256 is
`3463436e16a817f668a24a5a88c534fce40797a37b6d2475fda66ee419ba999d`.

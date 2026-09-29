# XP-006: Generic capability/dependency-aware gameplay authoring

Status: implemented; final verification recorded in XP006_COMPLETION.md.

## Decision

A host may register immutable data-only GameplayCatalog packages and, separately,
its supported system contracts. Registration is explicit dependency injection
into SessionManager / GDEOrchestrator. Nothing scans project directories, executes
package source, admits an executor from a prompt, or treats package metadata as
proof that a native runtime contains an implementation. Stock hosts with no
registered catalog reject this operation. The native playable package admission
and distribution boundary remains XP-007.

`xace.gameplay_authoring_package.v1` contains ID/version, prompt aliases, GCL
schemas, system declarations, namespaced capability declarations, component/system/
capability requirements, deterministic templates and named configuration presets.
The content hash covers all of this data. The reference fixture owns its alias,
wall capability, arena and presets in `examples/reference-mechanic/authoring.json`.
Its existing catalog/fixture compilation remains unchanged. Tests compare authored
behavior inputs with the XP-005 fixture to detect drift.

`install_gameplay_package` extends the closed typed operation registry with
package ID/hash, mode ID, selected actor IDs, capability/object selections,
template ID and configuration ID. It carries no code, filesystem path or raw
replacement CGS. Older readers reject the unknown operation. Arbitrary valid
semantic capabilities use the same path, with no mechanic-name dispatch.

## Flow

1. Match a registered catalog alias in PIL planning; no provider is needed for this
   deterministic path. Otherwise existing prompt handling applies.
2. Discover missing requirements and compatible world objects. Builder's existing
   clarification cards choose an arena template or actors/objects, then a preset.
   Choices bind to the current CGS hash. Cancellation clears the pending selection.
3. Materialize on a detached copy through GDE's typed executor. Reject unsupported
   packages/runtime contracts, dependency failures, ID collisions and invalid
   selections. Template v1 requires an empty mode and cannot replace an existing
   populated world; surface marking preserves existing objects.
4. Validate the entire candidate through Schema Factory and real SGC before showing
   the preview. Existing CGS diff rows show schemas, actors, systems and world
   before/after values. The catalog identity and selections are in the typed batch.
5. The existing `pil_apply` route validates explicit preview approval and stale CGS,
   then performs GDE mutation, recompilation, persistence and its existing rollback
   protocol. Runtime mutation is not performed by the planner or catalog.

The operation is a typed aggregate: dependency validation/materialization happens
inside GDE on its batch copy. A failing later operation cannot leak a partly
installed package. Composite planning assigns schema/system/world/defaults facets.
The older fragment-only compiler explicitly rejects catalog operations because it
has no registered host catalog; it cannot silently omit or guess materialization.

## Boundaries and supported scope

- UCL is unchanged; package-owned state/configuration are GCL.
- World Contract v2 validates semantic declarations and geometry as before.
- Required systems must be present in the selected mode/global scope; package and
  template systems must exactly match the host-registered contracts. SGC validates
  the final graph, component access and cycles.
- Configuration v1 selects package-declared typed presets, not arbitrary scripts.
- The reference input dependency is a recorded-input fixture implementation. The
  proof registers it explicitly; the general runtime CLI does not acquire it.
- No provider run, native-engine activation, live tick mutation or package archive
  installation is claimed. Existing UI provider readiness policy is unchanged;
  no-provider certification uses the typed Builder server/proof-host flow.
- Asset placeholders remain available via the existing `add_asset` operation in
  atomic typed batches. Native asset paths are never capability conditions.

## Reproduction

From the repository root, run `python tools/xp006_authoring_proof.py` to author and
approve both reference variants through the real Builder router. It writes only
`tmp/xp006-authored` artifacts and `tmp/xp006-proof.json`, with isolated settings.
In PowerShell:

```powershell
$env:XACE_REFERENCE_FIXTURE_ROOT = (Resolve-Path tmp/xp006-authored).Path
cargo test -p xace-reference-mechanic --offline --quiet -- --nocapture
Remove-Item Env:XACE_REFERENCE_FIXTURE_ROOT
```

This environment variable is consumed only by the removable reference test host;
there is no new runtime loader path. With it unset, historical XP-005 fixtures are
still the default. Both sets use the real CGS loader, persisted plan, World Contract
verification, ordinary system registry and phase orchestrator.

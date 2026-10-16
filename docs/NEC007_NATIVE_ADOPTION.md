> Reconstructed historical NEC007 document. Fresh recovery verification passed:276 Python tests and6 runtime executions; historical paths/evidence below are not current results. See AGENT_PROGRESS.md.

# NEC-007 completion: typed native adoption previews

Completed 2026-10-10 in the local post-XP-022 `target/xp016-work` tree.
NEC-008 is not started. No commit or push was performed. REL-01 through REL-05
remain OPEN. This is engineering completion of the bounded preview task, not
certification of complete game migration, bidirectional editing or runtime-free exit.

## Implemented contract

[native_adoption.py](../packages/project-system/native_adoption.py) accepts an
explicitly trusted, pinned NEC-004/005/006 capture, its NEC-002 identity map,
current hash-valid CGS, selected live object IDs and explicit choices. It checks
the source SHA-256 and canonical full-CGS digest before planning. Selection is
bounded to 128 objects; dependency closure includes parents, scenes, prefab
definitions and declared dependency edges. All captured items receive an adopted,
required-native-dependency or excluded disposition. Excluded objects are retained
in the native source; a critical dependency inside the closure blocks the candidate.

The immutable `AdoptionPlan` contains the complete choices, source/map/version
identities, mapping profile, provenance, typed GDE batch, proposed CGS, compiled
World, per-item losses, non-executable legacy behavior review and exact optional
native writer request. Names are never classified into gameplay. Native transforms
and typed resources come from the capture; actor/control types, additional
components, semantic roles/properties and package selection are explicit choices.
The versioned mapping profile declares one actor/instance per selected authoring
object, identity construction and fixed-point normalization. Precision review is
bound to the entire source inspection; it cannot override blocking losses.

[native_adoption_operations.py](../packages/gde/src/domain_dsl/typed_operations/native_adoption_operations.py)
adds the opt-in `xace.native_adoption_operations.v1` grammar. It supports empty
mode/World construction, actor and World-object creation/removal, semantic
reparenting, typed World asset bindings and semantic playback binding edits.
Existing typed GDE operations handle asset/component/system/event/default and
host-registered package operations. Every batch runs on a copy, checks expected
record digests where replacing/removing records, checks final reference and parent
validity, recomputes the candidate hash and requires host Factory validation.
Errors cannot partially modify the supplied CGS.

Known component mappings use explicit validated component records. Registered
package components/configuration values and systems use the existing hash-pinned
catalog, with no catalog code loading or generated gameplay. This profile permits
component/system packages without templates or capability materialization.
Capability-bearing packages are refused explicitly: their World mapping needs
separate reviewed integration. Multiple independent packages repeat as a no-op;
different attached values are rejected rather than overwritten.

Captured playback metadata can become a typed semantic binding when the user
supplies action/selector/parameters/flags and the event is already declared.
Only SourceEntity/TargetEntity selectors and compatible Animation/Audio/Vfx asset
types are supported. The resource locator remains bound to the capture. This is
binding construction, not conversion of animation controllers or script events.

## Host API and review boundary

This is an opt-in Python host API. The sealed legacy migration wizard and Builder
routes are unchanged; they do not automatically call this planner. Minimal UI and
apply integration remain in NEC-008/009/010.

```python
plan = plan_adoption(
    native_inventory=capture_bytes, mapping=identity_map, current_cgs=cgs,
    selection=sorted(selected_ids), choices=explicit_choices,
    expected_source_digest=source_sha256, expected_cgs_digest=digest(cgs),
    trusted_project=True, gameplay_catalog=host_catalog,
)
report = plan.to_dict()
verify_plan(plan, **same_current_context)
compiled = compile_execution_preview(
    plan, sgc_executable=trusted_sgc_path, context=same_current_context,
)
```

The host must obtain a fresh saved native capture before review/use. An offline
capture cannot detect subsequent disk/editor changes by itself. `verify_plan`
recomputes the entire report against current inputs; SGC preview invokes it too.
Trust is a host decision, not something an imported file may grant itself.

`choices` has exactly `mode_id`, `new_mode`, `world_contract`, `objects`,
`packages`, `legacy_dispositions`. Each selected object's choice supplies
`actor_type`, `control_type`, `components`, `semantic_type`, `properties`,
`capabilities`, `geometry_profile`, `asset_role`, `playback`. The tests and retained
native proof plans provide complete executable examples. Invalid/stale input can
raise `ValueError`; valid inspections with unsupported content return blocked
reports with losses. Do not treat the presence of proposed CGS as approval.

`candidate_valid` means the proposal passed GDE/Factory and has no blocking loss.
It is not whole-game runtime certification. Every plan is `preview_only`,
`can_commit=False`, `play_eligible=False`; no CGS publication, version increment,
baseline advance, native write, runtime activation or automatic synchronization
occurs. Optional `native_target` produces the existing pinned writer's exact
request only, restricted by that writer's admission and structural edit limits.
Discarding a plan is cancellation and requires no rollback.

## Verified limits and roadmap amendments

- Critical native behavior remains opaque. `disable_before_play` records a
  hash-bound manual action, never edits code or claims successful disablement.
  Fresh native extraction must prove the blocking behavior is gone. Input/action
  and other unmapped behavior remains a blocking per-item loss.
- Native parent IDs are authoring identities, not runtime EntityIDs. Semantic
  parent relationships are retained, but parented candidates remain blocked until
  a durable instance-to-runtime binding and transform contract is proved. Local
  transforms in such a blocked proposal are not claimed to be world-space equivalents.
- The frozen `MovementSystem` reads flat transform fields; native World v3 uses
  structured position/rotation/scale. The planner conservatively blocks systems
  reading or writing component 1 until a structured-transform executor contract is
  certified. No frozen runtime source or binary was changed to hide this mismatch.
- World v3 geometry remains the existing bounded AABB profile. Mesh references
  are presentation references, not imported collision geometry. No arbitrary
  terrain, physics, code, Blueprint, input map or animation graph conversion exists.
- Referenced native assets are registered, not copied into a portable standalone
  game. Native packaging, readiness and runtime-free export remain later tasks.

No new tasks or ordering changes are required. NEC-008 must preserve these losses
and both sides of conflicts. NEC-009 must revalidate source/map/CGS/choices/catalog
and native receipts at commit and advance version/baseline only through the
recoverable coordinator. NEC-010/011/012 must prove parent binding, structured
transform executor compatibility, resource readiness and reviewed capability
mapping before widening admission or enabling Play. These are explicit handoff
amendments to existing scopes, not work silently marked complete here.

## Verification

- **276 Python tests in 15 suites pass**, including 21 adoption tests plus all
  255 NEC-006 regression tests. Coverage includes source/CGS staleness, trust,
  tampering, precision review, dependency closure, unknown behavior, dirty/Play
  refusal, no inferred defaults, no-op import, package data/conflicts, typed
  binding CAS, structural rollback and Factory rejection.
- **Three real native fixture families** are hash-identical copies of previously
  certified installed-editor captures: Unity has 5 objects, Godot 7, Unreal 3.
  Their additional actual unknown-component/script/Blueprint captures are also
  rejected by the new planner after a manual disablement review. Fixture origin
  hashes are in [provenance](../packages/project-system/tests/fixtures/nec007/provenance.json).
- **Six fresh pinned-runtime executions** prove the final selected compatible
  slices (Unity 1 object, Godot 1, Unreal 2), each twice through GDE, Factory and
  SGC. Explicitly chosen health 100 and damage 10 produce health 90 on tick one
  and remain 90 on tick two; damage is consumed once, all captured transforms
  remain exact, and repeated world hash logs match. These gameplay values are
  user choices in the proof, not inferred native game behavior. Full fixture
  adoption and arbitrary original-game equivalence are not claimed.
- New editor sessions were unnecessary: native extraction/writing is unchanged
  and its NEC-004/005/006 evidence is preserved. These are new planner/runtime
  proofs over exact real captures, not a new end-to-end editor apply certification.
- All **2,140 protected XP-022 files** and the NEC-001–006 evidence chain remain
  unchanged. Historical live plan versions are retained in
  `target/nec007/entry-documents/`.

Reproduce Python checks with
`python target/nec007/verification-20261010/run_tests.py` and runtime proof with
`python tools/nec007_adoption_proof.py --out target/nec007/<fresh-folder>`.
The proof runner refuses an existing output directory and verifies its pinned
runtime and native source captures. The first development proof attempt failed
because optional runtime `actor_id` was absent; final assertions compare the
complete transform multiset and entity count. That failed attempt is retained;
only the final run is certification evidence.

See [receipt](recovery/evidence/nec007-20261016/summary.json),
[tests](recovery/evidence/nec007-20261016/runs.json),
[runtime proof](recovery/evidence/nec007-20261016/native-runtime/proof.json) and
[closeout](recovery/evidence/nec007-20261016/summary.json).

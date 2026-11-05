# NEC-017 current profile boundaries

Status: incomplete. This is a live implementation addendum; historical NEC evidence and the recovered XP-022 seal are unchanged.

| Capability | Current boundary | Evidence / remaining verification |
| --- | --- | --- |
| 1,000 bound objects | Admitted in all three native authoring profiles; 1,001 refused | Actual setup, repeated edits and representative crash recovery pass |
| Journal recovery | All 14 boundaries in each installed engine | 42 native process-death cases pass; representative larger fixture is separate |
| Collaboration | Explicit local developer principals, real Git branches, reviewed transform contributions | Merge/conflict/rebase/recovery pass; not unrestricted code/asset merging or external human certification |
| Existing Godot project | Explicit 50-instance selected adoption after recorded removal of unsupported native authority in a copy | Saved pair, both transform-edit directions, resource preservation and cold no-op pass; full Play/build/continuity still open |
| Existing Unity project | Two scenes, 50 prefab instances, actual native assets, colliders and unsupported scripts; 64 identities enrolled | Whole fixture still blocked for unsupported parented physics and critical native behavior |
| Existing Unreal project | Independent native two-map fixture with 50 static objects, two Blueprint instances, real animation/audio, input and spawn content | Creation and separate cold native readback pass; enrollment compilation running; adoption and complete workflow still open |
| Collider adoption | Unity's already-supported unparented identity-rotation/unit-scale BOX profile, `world.aabb.v1` | Captured fields must equal explicitly supplied component-4 defaults and chosen profile; 50 actual native root boxes compile exactly. Native saved-pair publication, both transform-edit directions, preservation and cold no-op pass (20261105/unity-collider-publish-a) |
| Collider editing | Transform edits retain adopted geometry | Size/offset/trigger synchronization remains uncertified and refused; no new physics backend or parented-physics support |
| Material adoption | Optional explicit `material_role` in adoption object choices | Registers a captured LINKED MATERIAL separately from the mesh role; no inferred mapping. Static references are projected and preserved. Actual Godot 50-instance static-material adoption, saved pair, both transform-edit directions and cold no-op pass (20261105/godot-material-publish-a) |
| Material editing | Static reference only | Material-reference edits in either direction are refused; shader graphs, material properties and general material synchronization are not certified |
| Review latency | Target remains p95 under 2 seconds for 100-edit batches at 1,000 objects | Latest stable planner-only p95: Godot1.828s, Unity2.019s, Unreal1.804s. Fresh capture-to-review certification remains open |

`material_role` is optional for backward compatibility. A present material field without that explicit choice remains an itemized blocking loss. A role collision with the mesh role is rejected. Supported mesh replacement can update its own role while preserving the separate material role; other bindings are not dropped.

A selected CGS candidate can compile while excluded critical native behavior still prevents publication of the full saved pair. The preview now exposes `saved_pair_eligible` and `saved_pair_losses`; apply rejects before project writes if that full-capture gate fails. Excluding native code from translation does not disable it.

The collider choice must supply exactly matching BOX shape, fixed-point size/offset and trigger state in component4, with the existing required World profile. Mismatch, unsupported hierarchy and unsupported reader geometry are refused. Projection detects subsequent collider divergence; it does not silently leave CGS geometry stale.

Remaining NEC-017 closeout: complete all-engine existing-project Play/build/continuity loops; satisfy actual capture-to-review and repeated-build measurements; complete the compatibility/fault matrix and source/evidence acceptance audit. No acceptance criterion is waived. User-deferred clean-machine certification and other external release gates remain open. NEC-018 has not started.

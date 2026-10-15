> Current recovery reconciliation: [NEC001 recovery acceptance](../recovery/NEC001_RECOVERY_ACCEPTANCE.md). This governs current baseline, verification, authorization and output paths.

> Reconstructed historical NEC001 document. Historical paths, test counts and completion statements below are not fresh recovery verification. Current recovery status is in AGENT_PROGRESS.md. Original sealed payloads remain missing; use the new persistent recovered baseline.

# ADR NEC-001: native authoring is reviewed definition work, not runtime feedback

Date: 2026-10-08. Status: accepted for the bounded NEC design/handoff.
This decision implements no NEC-002 identities, serializers or reconciliation.
Scope and proof identity: [NEC-001 audit](../NEC001_HANDOFF_AUDIT.md).

CGS remains the gameplay definition authority. GDE validates and atomically
commits approved definition operations; Factory/SGC derive packages/plans;
Mutation Gate and runtime own live changes. Native adapters mirror and collect
admitted inputs. An ordinary engine edit is never direct runtime/CGS authority.

| Feature | Owner and supported representation | Present reuse | Remaining owner/task and proof target |
| --- | --- | --- | --- |
| Adopted identity, create/delete/rename, prefab definition/instance | Canonical authoring ID and native locator mapping, distinct from runtime EntityID; tombstones/override identity | Runtime actor-instance bindings are insufficient for authoring | Project-system NEC-002/003, editor teams 004–006; rename/duplicate/reopen/delete identity fixture |
| Gameplay fields, rules, systems and code | XACE CGS/package contracts, GDE typed operations, host-registered executor | GDE persistence; XP-018/019 only eligible configuration migration | NEC-007/010/012; extracted values and admitted behavior parity, critical unsupported script refusal. Arbitrary native code retained opaque, no translation claim |
| Initial placement and authoritative geometry | CGS transform/World v3/AABB; native marker is a proposal/projection | Factory geometry validation, shared native coordinate readers | NEC-003–007/011; exact normalized transforms, bounds and contact parity; stopped-session rebuild for changed world |
| Decorative hierarchy/transforms, meshes/materials, lighting/camera/UI | Native engine owns resources and cosmetic offsets; preserve opaque properties | Native runtime applicators and asset registry | NEC-004–006/010/011; extract/save/extract and unknown-property preservation; no full scene rewrite from a partial dictionary |
| Asset replacement and typed references | Native resource owner plus typed AssetReference and engine locator mapping; gameplay readiness distinct from cosmetic availability | Asset import, resolution, semantic status and presentation checks | NEC-011; missing required dependency blocks, optional cosmetic fallback explicit, content/hash/locator change capture |
| Input | CGS action meaning is XACE-owned; physical native binding is engine-owned projection | Admission/input schema, native collectors, Player controls | NEC-003–006/011; keyboard/controller binding round-trip and identical canonical input; no untimed input or owner bypass |
| Animation/audio/VFX bindings | XACE semantic event/payload/gameplay timing; engine clip/state/graph/resource and cosmetic parameters | Semantic bindings, native playback, feedback only where authority permits | NEC-004–006/011; event-to-resource parity, no arbitrary graph conversion and no live-client gameplay feedback bypass |
| World/map data and relationships | CGS World v3 semantic records; native map contains retained visual content and supported projected markers | Schemas/capabilities/relationships and compiled World contract | NEC-006/007/010/011; real binary-map extraction and preserved assets; unsupported terrain/physics critical dependency blocks |
| Capture/conflicts/approval | Project-system normalized records, B/X/E baselines and reviewed typed proposal; separate authenticated local authoring capability | Primitive explicit edit-back is only a foundation | NEC-003/008; same-field, delete/edit, duplicate events, lost notifications, Play-mode exclusion and stale-CAS tests |
| Durable saves/recovery | Separate authoring transaction journal with native/CGS receipts; no dual authority | CGS atomic persistence and adapter owned-file transactions; XP-019 runtime journal is separate | NEC-009/010; every crash boundary, dirty document, locked file, concurrent edit, compensation conflict; block mixed revision |
| Native Play/build | Engine presents; admitted pinned runtime owns simulation; generated package and build receipt derived from approved source | Player launcher/package verifier, native readers and XP-019 session protocol | NEC-012–015; all three real Play/build workflows, process ownership and Builder-closed operation |
| Exit/archive/detach | Developer owns project sources/data; versioned dependency inventory and pinned redistributable runtime | Package ZIP, owned adapter uninstall, epoch replay/segmented archive | NEC-016/018; independent restore/rebuild, continuing-use terms, clean offline launch and preserve modified files. Runtime-free exporter outside NEC v1 |

For each synchronized field, NEC-003 must encode one owner, proposal directions,
normalization, schema/materializer version and conflict policy. Baseline advances
only after canonical and native saved receipts verify. No timestamp wins rule.
Engine-native save/undo support does not prove multi-file atomicity; staged writes,
source CAS, before-images and a journal are required. On irreconcilable newer edits,
retain all versions and require recovery instead of overwriting user work.

Authoring IDs, native IDs and runtime EntityIDs must remain separate. Cosmetic
child transforms, authored placement and interpolation are different values.
No automatic capture of Play-mode movement into definitions. Imported scripts and
plugins remain opaque unless a supported mapping is explicitly selected and
verified; loading an editor can execute them and requires separate trust.

Changes to world/entities/state while running do not fit XP-018's registered
read-only configuration migration. The bounded NEC path commits durable authoring
while preserving the old immutable session, then requires an explicit stop and new
admitted start. It may use XP-018/019 only after eligibility validation and explicit
activation approval. A committed runtime epoch is never rolled back with native
file before-images. Durable-decision failure ends the session under XP-019.

Rejected alternatives: engine feedback as an authoring channel; names as stable
IDs; treating runtime mirrors as native saved scenes; unreviewed default guessing;
last-writer-wins over user code; implicit world reset; calling bundled-runtime
distribution runtime-independent source export. Each would violate authority,
preservation or the supported promise.

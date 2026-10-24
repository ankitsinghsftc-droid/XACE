# NEC-013 Unity production Play and Windows build integration

Status: ACTIVE, not verified. Entry fd44458bbd7eb197fa31d594f0c4e6ade75d806b, NEC-012 complete for its declared common service.

Declared initial target: installed Unity6000.4.9f1, Windows x86_64 standalone, Mono scripting backend. Verify the actual installed backend during build; do not infer IL2CPP support. Other backends/platforms remain unclaimed.

Required acceptance (no criteria removed):

- Approved configuration pins launcher and NEC012 native release identities. Editor Play and shipped player own the shared Rust host, select its local ticket and connect the existing adapter. Builder, Python and player compilation are absent from shipped paths.
- Explicit native scene object bindings prevent duplicate mirrors. Preserve native hierarchy and presentation; runtime remains sole gameplay authority. Missing/stale bindings/resources block Play/build. No name-based inference.
- Stop, Play/Stop stress, supported domain reload and scene transitions clean up only owned processes. Authority loss visibly freezes/stops; no native fallback.
- Unity build hooks stage runtime/package/native resource closure, pin cooked binding/configuration identity, and cancel stale/mismatched builds while retaining prior release and failure records.
- Actual editor and normal Windows standalone build prove input/animation/audio/World parity, relocated read-only installation, stable per-game user saves and incompatible-save/update refusal/rollback through the NEC012 contract.
- A clean Windows machine without XACE/development tools must run the same package offline. Same-machine restricted-PATH tests do not fulfill this requirement. Signing, first-time tester, external networking and Steam gates remain explicit and open until evidenced.
- Retain source/binary identities, fresh native and focused regression evidence, and immutable XP022 baseline. Stop before NEC014.

Entry findings: existing Unity BeforeSceneLoad bootstrap creates an auto-connecting transport without owned host/package admission. Existing applicator spawns mirrors and reparents live entities. Existing native authoring metadata is separate from adapter assembly and has no shipping Play/build integration. NEC012 supplies the owned Rust service, release admission, per-game save identity and readiness-gated activation/rollback. Clean-machine access is not currently evidenced.


Local verification update 2026-10-24: see docs/evidence/nec013-local-acceptance-20261024/summary.json and NEC013_UNITY_STATUS.md. Local declared-profile checks pass; the mandatory clean-machine test remains blocked. This does not mark NEC013 complete or change the criteria above.

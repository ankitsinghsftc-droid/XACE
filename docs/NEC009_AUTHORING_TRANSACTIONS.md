# NEC-009 recovered authoring transactions

Fresh recovery acceptance passed on 2026-10-16 against source checkpoint `5052000`. This report is new evidence. Historical completion call4055 was rejected and was not replayed. The last historical test launch had no retained final result; its pass is not assumed.

## Implemented and verified

`authoring_transaction_contract.py`, `authoring_transaction_files.py` and `authoring_transaction.py` implement staged participant tokens, durable decisions, before-images, source hash checks, shared CGS locking, receipts, restart inspection, compensating rollback and explicit recovery conflicts. Windows replacement retains the actual displaced bytes so a racing edit is preserved. Recovery verifies actual before-images instead of trusting a native restore claim. Baseline advancement requires saved-pair verification; incomplete or corrupt transactions block readiness.

`authoring_apply.py` prepares adoption/reconciliation through typed GDE operations and Factory validation. It rechecks the saved mapping and full proposal immediately before publication and after staging. `authoring_saved_pair.py` binds baseline receipts to the durable decision, recaptured native snapshot, CGS hash and canonical projection. `authoring_native_participant.py` is a host-supplied gateway contract; it rejects conflicting source state before invoking publication or restoration. Runtime activation is recorded as not performed.

338 Python tests in19 suites pass. The25 retained filesystem cases cover14 durable boundaries,3 actual process deaths/fresh restarts,2 independent-edit conflicts and6 adoption/reconciliation profiles using fixture gateways. Tests also cover disk-full/permission fault injection, replacement races, corrupt stages, identity drift, verifier changes on restart and locked readiness checks.

The installed Godot4.6.3 proof makes a real native save in a copied fixture, terminates the coordinator with exit73, rejects a mismatching opaque serialization revision, keeps the baseline unadvanced and then restores both stores. Repeated recovery is idempotent. This verifies refusal and rollback, not successful production Godot apply admission.

## Explicit boundaries and roadmap amendments

This is an opt-in host coordinator. The host must supply a trusted native gateway, fresh source/context and publication authorization. NEC008 browser approval alone cannot write. The default Builder has no new apply endpoint, automatic watcher or automatic integration with this readiness gate. Hosts must hold `publication_gate()` around their Play/build publication. Simultaneous arbitrary native editors are not certified; Unity/Unreal coordinator flows use fixture gateways, not fresh native commit proofs.

The real Godot case exposes opaque serialization fingerprint changes that remain blocked. NEC010 must implement and certify the complete saved/recaptured native materialization loop, distinguish expected serialization effects without weakening unrelated-content checks, integrate readiness in actual Play/build entry points and certify each engine. Structural/entity/asset/script conversion and runtime-free exit remain later tasks. No task is added or reordered; these limits amend the next handoff. NEC010 has not started.

Persistent `.xace` journals retain recovery images; fresh proofs live under `recovery-evidence/20261016/nec009`. All55 protected XP022 files remain unchanged. Original sealed payloads remain missing. Every checkpoint is NOT backed up off-device.

Evidence: [summary](recovery/evidence/nec009-20261016/summary.json), [tests](recovery/evidence/nec009-20261016/runs.json), [native proof](recovery/evidence/nec009-20261016/godot-proof/proof.json), [source ledger](recovery/nec009-reconstruction-ledger.json).

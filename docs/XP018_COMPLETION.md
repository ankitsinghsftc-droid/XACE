> Reconstructed historical document. Original retained evidence is missing; fresh acceptance is pending. See AGENT_PROGRESS.md. Historical disposable paths must not be reused for unique recovery evidence.

# XP-018: immutable ruleset preparation

Implemented 2026-10-03 in the isolated `xp-016` worktree. This task prepares and
proves a candidate; it does not activate it. Durable activation at tick N remains
XP-019. No commit or push was performed.

## Product capability

The runtime exposes a generic preparation API in
`packages/runtime-core/src/runtime_orchestrator/ruleset_candidate.rs`:

- `CandidateParent` pins session/incarnation/epoch and gameplay identity when a
  session exists, plus CGS, plan, world, tick and snapshot identities.
- `CandidateArtifacts` captures exact CGS, persisted SGC plan, compiled world and
  world-manifest bytes. Artifact names and sizes are bounded; caller paths do not
  remain mutable references to the approved proposal.
- `CandidateProposal` binds the parent, artifacts and explicit configuration
  replacement mapping. `CandidateApproval` is a non-deserializable host-owned
  approval bound to the complete proposal digest. Package/provider JSON cannot
  supply an approval object. Trusted host code creates it after explicit review.
- `CandidatePolicy` declares configuration component IDs at host composition.
  A candidate cannot register its own executable code or migration privilege.
- `CandidateStore::stage` borrows the active runtime immutably, validates the
  existing hot-swap compatibility classification, constructs isolated runtimes,
  transfers the captured snapshot, applies configuration through MutationGate,
  and executes twice. Tick hashes, events and host-owned behavior assertions must
  agree. A successful proof includes the actual host executable digest.
- `CandidateStore::read_proof` verifies proposal/artifact identities and requires
  the expected proof digest from the trusted preparation decision. Modified
  artifacts or proof results are refused. Failed staging publishes no proof.

The candidate store is digest-addressed and refuses overwrites with different
bytes. Generated scratch artifacts from a rejected candidate may remain, but are
unproved and carry no activation authority. The active durable journal is never
used as candidate scratch storage. The API exposes no activation operation and
does not call the existing direct hot-swap method.

## Supported migration profile

The first migration operation explicitly replaces host-declared, system-read-only
configuration tables from candidate defaults while preserving all other snapshot
rows. Both old and candidate plans must declare no writes to those tables.
An empty mapping, unregistered mapping or migration which changes no runtime
state is rejected. Changing CGS defaults alone cannot certify changed behavior.

Component/system topology, state transformation, geometry and semantic-world
changes require a proven migration hook and currently fail closed. Existing
classification is reused; no fallback resets the world. The proof reports changed
CGS/plan/manifest artifacts and unchanged world/capabilities. This is a bounded
live-migration profile, not a restriction on which nouns, capabilities or mechanics
World Contract can represent. General World Contract extensibility is unchanged.

## Reference proof and tests

`tools/xp018_candidate_proof.py` reuses the actual Builder approval flow from
XP-006, including missing/wrong approval rejection, then GDE, Factory and SGC.
It works in disposable authoring projects, not the active project. The generated
disabled and reversal/shockwave artifacts feed the same generic staging API.

The package-owned test captures the parent after two executed ticks, preserving
its existing traversal state. The staged configuration produces the third-attempt
behavior, shockwave and cross-entity hit through the ordinary reference system.
Both isolated runs agree on all eight subsequent hashes and event traces.
The parent tick, snapshot identity and hash history stay unchanged. All mechanic
names and assertions remain under the reference package or its proof tools.

A second proof recompiles those configurations for the ordinary live
`EngineInputSystem` host profile and World Contract v3. It initializes a real
session controller with the actual proof executable pinned by package admission,
stages the candidate, and checks the active epoch, full snapshot and durable
journal remain unchanged. This checks preparation at the admitted session's
initial boundary; it is not a connected-client or activation test.

| Gate | Result |
| --- | --- |
| Candidate rejection, integrity and behavior tests | 6 passed |
| Full runtime/reference regression command | 857 passed, zero failed/ignored |
| Existing Builder gameplay authoring tests | 10 passed |
| Final approved-authoring + live-controller isolation proof | Passed |

The six candidate tests are included in the 857 count. They cover stale parent,
changed approval, stale plan, absent configuration migration, unregistered and
system-owned state mapping, unsupported world change, stored artifact/proof
integrity and positive behavior. The final focused proof was rerun after adding
retained event traces; the earlier broad regression did not need to be repeated
for that reporting-only change.

The first live-proof attempts correctly rejected incomplete fixture setup:
an unregistered recorded-input system, the wrong executable identity and missing
Player presentation identity. The final fixture uses the production admission
requirements without weakening any check.

## Reproduction and evidence

```powershell
python -m tools.xp018_candidate_proof --out target/xp018/new-proof
cargo test -p xace-runtime-core -p xace-reference-mechanic --offline --quiet
python -m unittest discover -s packages/builder-workspace/server/tests -p test_gameplay_package_authoring.py -q
```

Use a fresh output directory: the session journal deliberately uses create-new
semantics. The existing SGC executable must be available at `target/debug/`.
Cargo's configured target directory is respected for the proof-host executable.

Compact retained evidence: [xp018-baseline.json](evidence/xp018-baseline.json).
Generated packages, tickets, candidate stores and logs stay under ignored
`target/xp018/`; raw session credentials are excluded from retained evidence.

XP-019 must revalidate the parent at a clean activation boundary, verify the
expected candidate/proof identities and implement readiness, durable decision,
atomic installation, epoch publication and crash recovery. Staging approval is
not activation approval. No new Builder activation button, mutation network
protocol or cross-engine activation claim is introduced by XP-018.

Earlier clean-machine, two-machine and public-network gates remain pending by
owner instruction. The older missing-cosmetic startup limitation remains open.

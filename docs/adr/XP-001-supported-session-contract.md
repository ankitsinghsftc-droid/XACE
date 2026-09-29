# XP-001: Supported session identity contract

Status: accepted for contract implementation, 2026-09-23. Applies to XP-001 only.
The program roadmap is approved. This ADR freezes a target integration profile;
it does not certify a shipping Player, native host, World Contract compiler or live
session. Production admission remains unchanged until the later integration tasks.

## Decision and ownership

Use `xace_core::wire::session_contract` for shared serializable identity records and
a pure compatibility predicate. These are metadata, not a third transport. Keep
`WireMessage` v1, local `EngineHandshake`/`TickSnapshot` protocol v1, persisted SGC
plans and `network-core::SessionCompatibilityProfile` unchanged. New readers opt
into `xace.session_contract.v1`; no silent downgrade or automatic legacy conversion.
The future coordinator must require both verified artifacts and this predicate.
A successful predicate is not authentication, package verification or permission
to mutate. No module in XP-001 reads engine state or writes CGS/runtime state.

The existing legacy profile compares adapter/asset/package strings exactly. It is
still valid for its existing callers. It lacks world, epoch and semantic input
identities, so it cannot be upgraded by filling missing fields with empty hashes.
Later admission must explicitly obtain all fields and trusted certification data.
The shared type lives in core to avoid making native readers depend on network-core
or creating runtime/core dependency cycles; legacy network decisions remain intact.

## Supported profile

`host_client_lockstep_4p_60hz_windows_v1` means one creator-host Rust authority,
up to four total players including the host, 60 fixed simulation ticks/second,
Windows x64 first, and `host_client_lockstep_v1` topology. Player uses a Godot host;
Unity/Godot/Unreal are presentation clients. This is a future conformance target,
not an assertion that any current adapter has earned certification. Dedicated
server, peer-to-peer authority, host migration and other platforms need a new
reviewed profile. An authority restart always changes its incarnation UUID.

Historical chaos evidence calls its topology
`host_client_authoritative_lockstep_v1`. Map that label to
`host_client_lockstep_v1` only when indexing the existing simulated chaos report;
do not accept it as a wire/profile alias or infer real network conformance from it.

Initial input lead is 3 ticks, maximum accepted future lead 12 ticks. Clients submit
explicit idle inputs on their own clock schedule, not in response to snapshots.
A missing required peer stalls the authority; after 5,000 ms the future coordinator
must persist an explicit pause/membership decision before any tick can advance.
No implicit neutral-input substitution or wall-clock decision during replay.
Replay consumes the recorded decision. Membership resumes only at an authoritative
tick boundary with a verified baseline. Input packet schema v1 is retained; the
input artifact hash must cover action semantics, normalization/quantization,
limits and lead/timeout policy before real admission is wired. XP-001 implements
none of this scheduling or timeout behavior. Constants freeze the policy for later
implementation and drift tests bind existing packet/protocol/tick identities.

World v1 target limits: one selected CGS mode, at most 4,096 canonical static or
kinematic AABBs, right-handed Y-up coordinates with forward -Z, metres expressed
through existing Fixed64 micro-units (1,000,000 per unit), each coordinate bounded
to +/-8,192 units, positive box extents and at most 16 units movement per tick.
Queries use stable object-ID tie breaking and checked/widened arithmetic. Rotated
collision boxes, triangle meshes, slopes, arbitrary rigid bodies and deformation
are unsupported authoritative geometry in this profile. Native visual meshes are
unrestricted by this collision vocabulary. These bounds are design limits for
XP-003/004 validation, not a geometry implementation or performance claim.

## Identity and provenance

- CGS: existing `metadata.cgs_hash` plus existing `CgsVersion`. Exact equality for
  a session, not the general major-version migration rule.
- SGC: projection of existing `ExecutionPlan` fields: schema_version, plan_version,
  plan_hash, compiled_from_cgs_hash and adapter_protocol_version. The typed
  conversion calls existing plan validation. It does not independently recompute
  plan hashes or replace the loader's content/integrity validation.
- World: stable artifact ID, artifact version/content hash, World Contract version
  (1), source CGS hash and mode ID. Future compiler digest covers canonical object
  IDs, numeric/query profile, geometry and semantic requirements, not native paths.
- Playable package: the common gameplay package identity. Future package manifest
  binds exact CGS/SGC/world/input/runtime requirements. Engine-specific handoff
  packages remain separate; do not repurpose their existing distribution hashes.
- Input: semantic artifact identity plus the existing packet schema version (1).
- Runtime: semantic ABI/system-set artifact identity plus wire and engine protocol
  versions (both 1). Executable byte hashes belong in proof/trust manifests, not
  cross-engine gameplay equality; ABI compatibility must be certified, not inferred
  from a binary name. No new executable loader exists here.
- Ruleset/session: session UUID, authority-incarnation UUID, monotonic ruleset epoch
  (zero initially), and the gameplay tuple above form the full ruleset identity.
  No redundant aggregate ruleset hash is introduced. Exact incarnation and epoch
  equality is required; a numerically larger epoch is not automatically accepted.
- Host: engine, adapter version, client version, Windows x64 platform, protocol,
  offered capabilities and native presentation-manifest hash. Adapter and client
  versions must appear in the authority-supplied trusted certification allowlist.
  There is no default allow-all list or peer-supplied certification. The fixture
  list is synthetic and must never be used as a production trust store.
- `SessionProvenance` carries the complete session contract, adapter, integer tick,
  and optional paired mutation/activation UUIDs. A missing activation means no
  activation correlation is asserted for that record, not implicit epoch zero.
  No causal tracing, log transport or activation state machine is implemented.

Hash text must be exactly 64 lowercase SHA-256 hex digits. Semantic IDs/versions
are bounded ASCII tokens (alphanumeric, dot, underscore, hyphen; 1..128 bytes).
Native paths such as `res://`, `Assets/` or `/Game/` cannot become artifact IDs.
Session, authority, mutation and activation UUIDs cannot be nil when present.
Existing CgsVersion serialization is reused unchanged. New records reject unknown
fields; the existing CgsVersion reader retains its prior behavior.

Reserved versioned capability names include solid, wall_runnable, interactable,
trigger, spawn, safe_zone, road and platform under `world.<name>.v1`.
`input.timed.v1`, `world.aabb.v1`, `world.semantic_bindings.v1` are mandatory for this
profile. A recognized word is only a vocabulary reservation. It does not mean the
runtime or a host implements it. Unknown required capabilities reject; extra
optional host capabilities do not change gameplay compatibility. Known required
sets must match exactly and the certified client must offer all of them.

## Deterministic decision and serialization

`compare_session` is read-only and returns the first stable rejection code.
Validate authority, then candidate: schema/profile; nonzero identities/plan;
CGS-to-plan/world links; world version; input version; protocols; unknown required
capabilities; missing mandatory profile capabilities. Then compare session,
incarnation, epoch, CGS, SGC, world, package, input, runtime, required capability
sets; check platform, client protocol, certification allowlist and offered
capabilities. JSON decoding failure is `malformed_contract`. The rejection order
is intentional and frozen by multi-failure vectors.

New records serialize in their Rust declaration order, compact UTF-8 JSON; sets
serialize sorted by ASCII token. `authority.canonical.json` contains exact bytes
(with one file-ending newline excluded from comparison). JSON object input order
is immaterial. No float or unordered map is present in these contracts. Preserve
unsigned 64-bit ticks/epochs exactly in native readers; do not round through a
JavaScript double. This serialization rule is not a replacement CGS/SGC hash
algorithm and does not mint a new gameplay identity digest.

Golden corpus: `packages/core/tests/fixtures/session_contract_v1/golden_vectors.json`.
Each case contains a complete candidate offer and nullable expected_rejection;
null means accept. Load the shared authority and synthetic certified_adapters,
validate/decode the candidate, then compare as above. Unity, Godot and Unreal
reader conformance in XP-016 must consume these same vectors. XP-001 tests the
shared Rust reader and host identity variants; it does not implement native readers.

The corpus copies a real retained CGS and persisted plan from the SGC runtime
proof. World/package/input/runtime artifact hashes are explicitly identity-only
fixture values: SHA-256 of `XP-001 identity-only fixture: <name>` for world,
playable-package, input and runtime-abi. They are not compiled/verified artifacts.
This keeps the contract test independent of unimplemented XP-003/007 compilers.
No invented arena is represented as authoritative or certified playable content.

## Trust, evidence and later integration

The future package loader verifies content digests, canonical links, capabilities,
resource bounds and trust before launch/join. Invited gameplay packages contain
validated data, not arbitrary PCK scripts, native DLLs, Unity/Unreal projects or
executable code. Trusted host/runtime updates use separately reviewed pinned
artifacts. Hash equality alone is not trust. Presentation differences are allowed
only outside the common gameplay tuple; missing authoritative geometry cannot
be treated as a cosmetic fallback. Cosmetic fallback must be reported.

Proof taxonomy stays the roadmap's A local Player, B World Contract, C invite,
D mixed client, E simultaneous three-engine, F live mutation, G replay/debug,
H fault matrix. XP-001 proves contract vectors only, none of A-H. Index historical
artifacts as present (with byte digest and scope), historical-only (documented
claim, missing retained run), or missing (no proof yet). Windows-only replay and
simulated chaos are not multi-OS or live socket evidence.

No roadmap task is merged into this one. XP-002 must still close Builder-to-SGC
Schema Factory bypass and live runtime input/control mutation paths. XP-003/007
must replace fixture-only world/package descriptors with validated compiler output;
XP-011/016 must wire strict admission and real host certification; XP-018/019 must
persist epoch activation and incarnation fencing. Do not weaken admission to make
legacy profiles or missing artifacts appear compatible.

## DCL runner repair

The official runner starts a child with tools as its script directory. DCL imports
`packages.dcl`, so its SuiteSpec now declares the repository root in the existing
import_roots mechanism. Other suites retain their discovery behavior. No test is
skipped and no shell PYTHONPATH is required. Verify with
`python -I tools/python_test_gate.py --suite dcl --output tmp/xp001-dcl-isolated.json`.

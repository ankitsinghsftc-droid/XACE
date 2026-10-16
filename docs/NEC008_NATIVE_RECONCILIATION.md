> Reconstructed historical NEC008 document. Fresh recovery verification pending; historical paths and evidence below are not current results. See AGENT_PROGRESS.md.

# NEC-008 completion: three-way reconciliation and review

Completed 2026-10-10 in the local post-XP-022 `target/xp016-work` repository.
NEC-009 is not started. No commit or push was performed; REL-01 through REL-05
remain OPEN. This task creates and reviews proposals. It does not implement the
recoverable publication coordinator or claim automatic bidirectional editing.

## Implemented

[native_reconciliation.py](../packages/project-system/native_reconciliation.py)
implements deterministic comparison of **B** (last verified saved baseline),
**X** (current canonical projection) and **E** (current saved native extraction).
It retains all three versions and the proposed result. No timestamp chooses a
winner. Same-value changes and independent edits merge; position/scale axes can
merge independently, while quaternion and typed reference values remain atomic.
The 64-case deterministic corpus and inventory permutations exercise repeatability.

Same-field disagreement, delete-versus-edit, dependency changes and interacting
hierarchy edits require an explicit XACE/engine choice. Parent changes also check
transitive dependents: an edit to a child is not assumed independent of reparenting
its ancestor. The combined dependency/parent graph is checked for deleted targets,
cycles and unsupported geometry. Conflict IDs bind the complete B/X/E/policy
identity; a choice cannot be reused after another edit.

Field ownership comes from the existing host-owned NEC-003 policy. Native-owned
values and opaque code stay in the engine; XACE cannot select an overwrite of a
native-owned field. Critical native behavior remains blocking. Missing objects
are never interpreted as deletion: explicit normalized tombstones are required,
and a scope/generation/branch/identity mismatch is refused. The kernel can explain
structural conflicts, but it cannot publish structural changes.

[native_reconciliation_plan.py](../packages/project-system/native_reconciliation_plan.py)
connects this kernel to real NEC-002 maps, NEC-003 snapshots, NEC-004/005/006 readers,
CGS and Factory validation. The host must verify the baseline's canonical/native
receipt references out of band; this module does not invent a verified baseline.
The baseline's mapping, CGS and snapshot digests must match, and its mapped native
transforms must agree with its canonical projection. Current full-CGS/source
digests and current map/branch/baseline identity are checked before planning.

The certified executable proposal profile is **structured root position, rotation
and scale of explicitly bound single actor instances**. Independent CGS work is
preserved in the candidate. Native edits become
[typed GDE operations](../packages/gde/src/domain_dsl/typed_operations/native_reconciliation_operations.py)
with full-CGS and per-actor preconditions, isolated-copy execution and mandatory
Factory validation. Native-bound output uses exact decimal coordinate inversion,
recapture/readback validation and the existing pinned native writer request API.
No writer is invoked. World changes outside this projection are explicitly blocked.

The report includes complete B/X/E values, decisions, conflicts, resolutions,
losses, typed CGS operations, candidate CGS and exact optional native write request.
`reviewable` means the supported proposal passed these checks, not that it can be
applied or played. Every plan has `preview_only=True`, `can_commit=False`, and
`play_eligible=False`. No schema version or baseline is advanced.

## Review approval and Builder surface

[native_reconciliation_review.py](../packages/project-system/native_reconciliation_review.py)
owns bounded, expiring review sessions. A host callback rereads the authoritative
context on open, resolve, approve and approval verification. Proposal digests act
as compare-and-swap conditions on concurrent review changes. Approvals are signed
with a process-local host key and bind the principal, session, full proposal and
source identities. Another browser/principal cannot use the session. Source, CGS,
baseline, branch, policy or resolution drift invalidates approval. Cancellation
only removes review state, including after source drift.

Approval is evidence of review, **not a native-write/CGS-commit capability**. Its
receipt says `can_commit=False` and `requires_coordinator=True`. Restart invalidates
the process-local signature/session; this intentionally avoids a durable approval
claim before NEC-009. Two users may review the same unchanged inputs; only the
future coordinator can serialize publication and recheck its store preconditions.

[native_reconciliation_routes.py](../packages/builder-workspace/server/native_reconciliation_routes.py)
provides an opt-in extension to the actual XP-021 Builder host. It reuses local
operator/origin guards, binds sessions to an HttpOnly same-site browser cookie,
limits/validates JSON bodies and exposes only open, resolve, approve and cancel.
There is no apply endpoint and no browser-supplied project path, CGS or baseline.
The existing sealed default Builder entry point is unchanged.

```python
from native_reconciliation_routes import create_reconciliation_app

app = create_reconciliation_app(
    fresh_trusted_context_provider,
    project_path=project_path,
    static_dir=builder_dist,
)
# Run this app with the existing local Builder server hosting configuration.
# Open /native-review on that same host.
```

Alternatively, a configured host calls `install_reconciliation_routes(app,
fresh_trusted_context_provider)`. The callback supplies the keyword arguments of
`plan_reconciliation`, including its out-of-band `verify_baseline` function. It must
obtain saved native data afresh; comparing an old file supplied twice cannot detect
editor/disk activity. No automatic watcher or baseline-enrollment shortcut exists.

The [review panel](../packages/builder-workspace/server/native_reconciliation_review.html)
shows last verified/XACE/engine values, readable position units, explicit choices,
blocking requirements and expandable exact technical records. It disables approval
until choices are re-reviewed, handles stale responses, and makes cancellation and
the absence of publication explicit. Native text uses text nodes, not HTML parsing.
The panel is accessible at `/native-review` only after installing the extension;
it is not silently enabled in the ordinary Builder launcher.

## Boundaries and remaining roadmap

- Entity enrollment, locator relocation and branch reconciliation are not silently
  merged. This task detects/refuses identity conflicts. A changed mapping requires
  an explicit reviewed identity workflow before a new comparable baseline.
- Native readers currently provide complete inventories without deleted-object
  records. The kernel tests explicit tombstones, but omission from a native
  inventory remains a scope error. There is no inferred native deletion.
- Structural conflicts retain both versions and can record a user choice, but
  structural materialization stays blocked for NEC-009/010. No create/delete or
  hierarchy write is authorized by a field writer.
- Native parent-to-runtime identity binding and systems accessing component 1
  remain gated by NEC-007's unproved structured-transform runtime contract.
  Unbound native hierarchy can remain in the preserved native content.
- The generic kernel compares declared typed fields, but the concrete CGS/native
  integration certifies transforms only. Asset, playback, input, code, arbitrary
  component/World and geometry conversions are not smuggled through transform
  operations; unsupported mappings produce blocking losses. NEC-010/011 must
  supply and certify those mappings before widening admission.
- Neither review nor native writer preview saves files, reloads runtime, advances
  baseline/version, translates scripts, or implements runtime-free export.
  Unresolved conflicts leave both stores and the last active package untouched.

No tasks are added or reordered. NEC-009 must consume/revalidate the exact reviewed
proposal under its own fresh source checks, locks/CAS, journal and participant
receipts; it must not equate this process-local review with commit authorization.
NEC-010/011 retain responsibility for broader durable mappings, explicit structural
and identity changes, resource readiness and recapture. NEC-012 retains Play
admission. These are concrete handoff amendments, not completed functionality.

## Verification and preservation

- **308 Python tests in 17 suites pass:** all 276 prior NEC tests plus 25 new
  reconciliation tests and 7 HTTP/Builder integration tests. The new coverage
  includes a 64-case deterministic corpus, ordering permutations, no-op repeat,
  ownership, atomic GDE failure, semantic dependency conflicts, baseline and
  source checks, dirty/Play refusal, stale approvals and concurrent users/reviews.
- **Three real native capture-derived proofs pass.** Exact NEC-007 fixture copies
  (Unity 5 captured objects / 1 bound, Godot 7 / 1, Unreal 3 / 2) prove disjoint
  canonical/native edits, exact writer previews, preserved competing versions,
  explicit resolution and stale approval refusal. New edits are controlled
  modifications of capture data; no editor was launched or project saved. Proof
  baseline receipts are isolated fixture receipts, not NEC-009 transaction evidence.
- **20 real Chrome/HTTP UI checks pass**, 10 each at desktop and narrow widths
  (1280 and 600). Screenshots were inspected. The tests exercise unresolved and
  stale approval refusal, three-version display, explicit review, cancellation,
  hostile native text rendered literally, refresh and no horizontal overflow.
  A 390-wide development capture was visually cropped by the headless host; it
  is retained but excluded from final UI certification. An initial runner UTF-8
  decoding failure was fixed before the passing runs.
- The actual `create_reconciliation_app` wrapper was exercised alongside the
  existing Builder capability route; no runtime or external model work was started.
- All **2,140 protected XP-022 files**, all **95 NEC-007 deliverable/artifact
  records**, and the historical NEC-001–007 receipt chain remain unchanged.
  The only prior live source exception is the permitted master-plan addendum;
  pre-task live plans are preserved in `target/nec008/entry-documents/`.

Evidence: [receipt](evidence/nec008-reconciliation-20261010.json),
[tests](../target/nec008/verification-20261010/tests.json),
[three-engine proof](../target/nec008/native-proof-20261010/proof.json),
[desktop UI](../target/nec008/browser-desktop-final-20261010/proof.json),
[narrow UI](../target/nec008/browser-narrow-final-20261010/proof.json), and
[closeout](../target/nec008/verification-20261010/closeout.json).

Reproduce with `python target/nec008/verification-20261010/run_tests.py`;
`python tools/nec008_reconciliation_proof.py --out target/nec008/<fresh-folder>`;
and `python tools/nec008_review_browser_proof.py --out target/nec008/<fresh-folder>
--width 600`. Proof runners require fresh output directories and preserve prior evidence.

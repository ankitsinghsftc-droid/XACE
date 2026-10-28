# NEC-016 continuity workflow and collaboration boundary

Use `python tools/continuity.py --help`. All output destinations must be new and persistent. Archive/restore do not run payload code, publish CGS, start Play, repair identities, or apply journals.

## Archive and restore

`create REQUEST.json OUTPUT.zip` takes explicit project identity, typed roots with role/key/path, dependencies, protected checkpoints, prerequisites, omissions and a reviewed_declared_closure flag. Relative source roots resolve against the request file. Required roles are project-source, native-project, executor-source, runtime, history and notices. Preserve native source/assets, executor sources plus Cargo.lock and build inputs, CGS, project manifest, immutable authoring revisions, reconciliation baselines and transaction journals. Preserve replay segment/completion/quota metadata and all referenced checkpoints; do not prune history. External toolchains and licensed inputs must be itemized. Essential unavailable material prevents complete-closure claims. `--allow-incomplete` creates a diagnostic archive explicitly labeled incomplete.

Record the returned archive SHA-256 outside the archive. `verify ARCHIVE --sha256 PIN` verifies every member and the manifest. A hash pin is integrity, not publisher authentication. Review all source roots for credentials and third-party permissions: filename checks are a guardrail, not exhaustive secret detection. Explicit omissions are recorded; original files remain unchanged. Git working-tree metadata is not portable history: omit `.git` explicitly and supply a durable Git bundle/checkpoint plus the full authoring/journal history when Git history is part of the declared closure.

`restore ARCHIVE --sha256 PIN NEW_DESTINATION` validates before writing, uses exclusive creation, and writes the success receipt last. Failed partial directories are retained and cannot be reused automatically. Windows long paths are addressed using the extended-length namespace. Restore is not proof that tools, dependencies, licenses, engine support or rebuilt binaries are valid. Perform a separate reviewed rebuild and pin resulting executables.

## Detach modes and approval

`review-detach ARCHIVE --sha256 PIN NEW_DESTINATION` returns a digest-bound review. Save that JSON outside the new destination; `apply-detach ARCHIVE REVIEW.json --approve REVIEW_SHA256` requires the exact current digest. CLI invocation is the operator's explicit approval; it is not a substitute for authenticated Builder approval when integrated into a service.

Default retain-runtime mode produces a standalone copy with native code, assets, adapters and pinned runtime retained. It does not modify the original link or silently disable synchronization in the original workspace. The copied project remains independent until a developer deliberately re-adopts it. Bundled XACE gameplay runtime remains necessary; this is not runtime-free source conversion.

Optional remove-adapter mode requires `--native-root KEY --engine godot|unity|unreal`. It removes only hashed manifest-owned integration in the independent copy. Modified ownership produces a conflict and preserves all installed siblings, the archive, the source and backup history. It does not remove arbitrary native gameplay references or promise the copied game remains runnable after integration removal. Missing/legacy/corrupt ownership cannot authorize deletion. Successful removal preserves before-images; failures restore absent files without overwriting concurrent creator changes. A hard process/power failure can leave the disposable *operation result* partial, but the unique independent archive and original native project remain intact; retry into another new destination. Do not store this destination under a disposable directory.

## Two-developer identity and review contract

- Clone: restore exact namespace/object identities, baseline references and immutable revisions. Do not create two concurrent writers with the same branch identity. Before independent editing, use `IdentityDraft.fork(new_branch_id)` and `AuthoringIdentityStore.prepare(..., operation="fork", expected_revision=...)` / commit. The project identity is retained; the branch is explicit.
- Fork: retain object identities and namespace so the common ancestor remains meaningful. A new unrelated game identity requires a separately reviewed adoption; do not rewrite IDs across archived history. Fork is metadata, not an engine/CGS mutation.
- Branch editing: saved native capture and the existing reconciliation pipeline (`native_reconciliation.py`, `native_reconciliation_review.py`, `authoring_apply.py`) remain mandatory. Every process rechecks its baseline, mapping, source and CGS identities at publication. A copied approval is never fresh approval.
- Merge: preserve both branch snapshots/archives and common baseline. `branch_conflicts` identifies branch/object divergence; `reconcile_records` retains both conflict values. Resolve through existing principal-bound reviews and the NEC009 transaction coordinator. Never resolve an identity head, CGS, opaque binary asset or transaction journal by last-writer-wins Git merge. Unsupported structural/opaque conflicts remain blocked for manual native resolution and fresh capture.
- Rebase: replay intended edits against a newly captured baseline as new reviewed transactions. Preserve old revisions, source snapshots and journals. Do not rewrite immutable revision records or reuse approvals from the previous base. There is no automatic general Git-rebase-to-CGS converter.
- Recovery: use existing journal recovery and `AuthoringIdentityStore.recover_head` with explicit expected-head digest, namespace and branch. Replay history is data, not executable restoration instructions. If source differs, preserve both versions and request review; never regenerate identities to conceal a missing/corrupt head.

NEC016 defines and tests shared preservation/identity primitives. Full real two-developer installed-editor branch/merge/crash certification and the 1,000-object scale target remain NEC017; this document does not claim those proofs.

## Shipping and save limits

A standalone native package contains no Builder and does not require cloud contact. It still needs its pinned runtime and platform redistributables. Network denial must be verified separately from PATH isolation; preserve loopback IPC required by the native host. A development-laptop test is not clean-machine certification.

Existing native save admission is exact-compatibility and refuses incompatible saves unchanged; it does not automatically migrate or restore arbitrary gameplay state. Migration must be an explicit validated conversion producing a new artifact while retaining the original save. Failed/unready updates must not advance active release; explicit rollback selects a retained release. The continuity archive alone is not an updater.

Original XP022 evidence and recovered sealed baselines are never rewritten. Public redistribution requires complete notices/licensing review; missing notices must remain an essential unavailable dependency. External clean-machine, signing, tester, networking and Steam gates remain unchanged.

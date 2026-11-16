# NEC-018 external test and evidence protocol

Every cell starts NOT RUN. Owner supplies an independently trusted candidate/archive digest and approves the exact distribution scope. The current unsigned kit is private local engineering material; it must not be sent externally before those approvals/signing prerequisites. Do not disable security, overwrite saves or patch source to turn a failed step green.

## Clean player-machine trial (REL-01)

Use an actually fresh supported Windows x64 PC/VM with recorded provisioning/image identity and no XACE Builder, repository, game-engine editor, Cargo, Python or Node. Do not convert the development laptop by hiding PATH entries. Preserve OS/CPU/RAM/GPU/driver, account token, security controls and SmartScreen/AV observations. External Windows prerequisites must be explicitly declared; a missing runtime is a failed dependency test, not permission to install development tools.

Independently compare the archive SHA256 before extraction and candidate SHA256 afterward. Extract to a new persistent test folder; keep the transferred archive intact. Run the included self-contained tools using an existing Windows PowerShell session, for example:

    & .\Run-NativeChecks.ps1 -CandidateRoot C:\XACE-Certification\candidate -ExpectedCandidateSha256 OWNER_PIN -EvidenceRoot C:\XACE-Certification\run-01

Use the actual64hexadecimal owner pin. Default is3launches per engine. Launches1 is only a smoke rehearsal. If execution policy or security controls prevent running it, record that fact and stop that cell; do not use a bypass. The runner uses only its pinned native payloads; no Python/engine SDK is needed. Environment/probe/installation/process/TCP/Authenticode records are collected. Automated callbacks are not physical keyboard/controller tests, fresh-OS proof or human usability evidence. Packet capture is separate; TCP polling cannot establish absence of all traffic.

For offline proof the owner arranges an approved isolated guest/network environment, retaining local IPC. Capture adapter/firewall/network policy and actual packet/connection evidence with positive controls. The runner observes networking and changes no adapter/firewall/system policy. It never calls a remote service to declare isolation. Repeat exact native canonical projection/state/event checks, not only screenshots. Preserve every failure and the original install file inventory. Verify launcher/runtime ownership cleanup after normal close, repeat launch and the prescribed fault cases.

## Update/save/install/uninstall independence (all three engines)

Owner supplies two byte-pinned, genuinely distinct native versions of the same stable game ID and an independently pinned second game; copying one build to two paths is relocation, not a distinct-version update. Confirm both payloads are admitted and their per-game namespaces/compatibility declared. No automatic migration is inferred.

1. Install/extract into new owned test paths. Establish a working versionA, compatible save envelope and immutable save sentinel. Record actual activation and save paths/hashes, which must be per-user and outside install/Builder directories.
2. Launch the independent second game. Show its save namespace/activation cannot overwrite the first game. Preserve both sentinels and all application state before each operation.
3. Admit and run versionB; show the intended active revision and unchanged compatible saves. Use an incompatible save/executor/schema candidate: require exact structured refusal before inappropriate state use, and byte-identical original saves. A valid migration, if later implemented, must be a separately tested new artifact with original bytes retained.
4. Test corrupt, missing-resource, interrupted-before-readiness and failed update cases. A process exit alone is insufficient, especially Unreal's graceful zero exit. Require the expected refusal/absence of authority, retained prior activation, unchanged original saves and a still-launchable versionA.
5. Explicitly roll back toA and prove its gameplay/ownership checks. Preserve both installed versions, receipts and history; do not clean them as part of recovery.
6. Exercise the actual declared uninstall method on a dedicated copied installation. The project has portable artifacts, not a certified general installer. A reversible test can quarantine that owned installation after resolved-path checks and before-image preservation; label this as portable removal, not MSI/uninstaller certification. Prove saves and the other game remain unchanged, and Builder removal/absence does not delete game source or progress. Never delete the original candidate, source, evidence, user folders or unrelated installations.

The current Run-NativeChecks tool does not execute this update/uninstall matrix. Prior same-laptop update/rollback/save receipts are contextual and do not close clean-machine cells.

## Three independent developer walkthroughs (REL-05 and NEC-018)

Recruit three actual first-time independent people, with consented observation; automation or an experienced operator does not substitute. Cover each declared engine with at least one independent developer and record exact per-person/engine coverage. Owner provides licensed creator prerequisites and a preconfigured supported workspace/launch shortcut; these belong on creator machines, separately from the tool-free player PC. If a normal configured authoring host cannot be supplied, the walkthrough is blocked, not repaired by the participant.

The existing opt-in review page is /native-review, installed only in an explicitly configured Builder host. Do not assume the default sealed app automatically configures native paths, context or a materialization host. Owner records the actual launch URL and source/package IDs; never expose operator secrets. Give each participant a fresh branch/project copy and supported-profile description.

Record each step: inventory/link existing original; select supported scope; inspect losses and reject once without writes; explicitly approve adoption; author a supported gameplay/transform change; native Play with Builder closed; save a native edit and review/reconcile; exercise rename and known refused structural cases; encounter/resolve a same-field conflict; Play again; native release build; archive/independent restore/exit continuity. Show untouched original files, meaningful CGS/World/bindings and no duplicate authority. Unsupported original behavior must be disclosed; a newly selected reference mechanic does not convert that behavior.

Record task time, errors, assistance, prompts, source/asset/identity preservation, exact installed artifacts, assertions and observations per person. No terminal/source repair to complete a task. A failed or assisted cell remains blocked until the problem is fixed and that affected real workflow rerun. Keep participant identity/consent private; publish pseudonymous compact results only with approval.

## Other release gates

REL-02 requires two distinct reachable Windows computers, ordinary invite/join/rejoin and matching authority/projections. REL-03 requires a real approved deployed relay with a valid TLS chain and two separate ordinary networks, outage/reconnect/expiry/replay rejection and cleanup. Local loopback/test TLS is not that proof. No deployment or invitations are authorized automatically.

REL-04 requires actual approved publisher signing, post-sign identities/admission/native checks and clean-Windows security observations; see NEC018_SIGNING_PREREQUISITE.md. Public redistribution/continuing-use approval is tied to exact dependencies/assets and the final candidate, separately from technical notice completeness. Actual Steam installation/update/client-lifecycle evidence is a separate unpassed gate for any Steam claim.

Evidence envelope schema and required per-gate check names are in release_handoff.py. A caller must independently review attachments and pin their exact envelope digest/reviewer identity. The tool can validate eligibility for owner review; a self-authored PASS JSON never proves a real human, fresh OS, valid signer or full release. Keep untested/failed/unknown cells visible.

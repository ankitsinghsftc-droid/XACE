# NEC-017 remaining acceptance

Current status: incomplete. This live list narrows execution to the approved supported profiles; it does not add tasks or waive acceptance criteria. NEC-018 is not started.

| Required closeout | Verified so far | Still needed |
| --- | --- | --- |
| Existing-project development workflows | Independent original fixtures in all three engines; real enrollment; Godot static-material and Unity root-collider adoption/edit loops; Unreal static adoption and both transform-edit directions pass | Full original-derived Unity supported-profile loop; connect supported adoption to gameplay mapping, native Play with Builder closed, native release build and continuity checks |
| Scale and performance | 1,000-object setup, repeated bidirectional editing, actual 100-operation batches, local Git merge/rebase/recovery, 42 native journal-crash cells and representative larger recovery | Fresh 30-batch capture-to-review measurements per engine, meet unchanged p95 <2s budget excluding import/compile, repeated native builds and resource/history measurements. Planner-only timings do not close this gate |
| Final evidence and compatibility audit | 363 project-system and 127 schema-factory tests pass; fresh structured replay proof; recovered XP022 seal unchanged | Tie each required supported workflow/fault/shipping/update/save cell to exact current or valid carried-forward source/artifact identities; repair uncovered failures; final checkpoint |

Not new NEC-017 blockers: unrestricted Blueprint/script translation, broader physics/terrain backends, general material/shader editing, additional engine versions, visual polish or the major UX redesign. Unsupported behavior must remain visible and refused; explicit test-copy disposition is not automatic gameplay conversion.

Already deferred external gates remain open: clean Windows machine/VM, signing, external first-time testers, external networking and actual Steam certification. Their unavailability need not block local NEC-017 work, but NEC-018/full release cannot claim those proofs.

Schedule: remaining work is substantive engineering plus native certification, not merely documentation. A reliable hour-level ETA is not established. Plan for multiple working sessions/days, with the full capture-to-review path the largest uncertainty. Current closed-editor startup costs must be measured rather than silently excluded or a planner-only result substituted. Any larger architectural prerequisite must be called out explicitly before expanding scope.

See [profile boundaries](NEC017_PROFILE_BOUNDARIES.md), [certification record](NEC017_CERTIFICATION.md), and the unchanged acceptance in section14/NEC-017 of [the program](XACE_NATIVE_ENGINE_CONTINUITY_PROGRAM.md).

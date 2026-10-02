# XP-010 clean Windows acceptance ? PENDING

Owner disposition, 2026-09-30: no clean PC or VM is available; retain this test as
pending. Same-host restricted-PATH tests passed but do not satisfy this gate.

On an independently clean Windows 10/11 x86_64 installation:

1. Record OS/build, CPU, RAM, GPU/driver, free space and whether the user is standard
   or administrator. Do not install any editor, Cargo, Python or Node for this test.
2. Transfer the trusted `release.zip` with its independently recorded release digest
   from `docs/evidence/xp010-baseline.json`. Extract the whole folder.
3. Open `XACE Play.exe` without arguments. Record elapsed time from opening it to
   visible controllable gameplay, installed size, graphics output and any dependency
   or SmartScreen prompts. Do not disable security controls to force a pass.
4. Move and trigger the fixture's input. Close the game; confirm its Player and runtime
   processes exit. Reopen twice in sequence and verify no previous authority survives.
5. Test a writable alternate install and a denied install path through the broker
   harness on a test account. Restore access and retry. Confirm a failed update leaves
   the previous verified active version intact. Preserve logs and exact file digests.
6. Record PASS/FAIL with evidence, not only a screenshot. A failure remains open until
   fixed and rerun. Update XP-010's roadmap state only when this gate actually passes.

The developer machine's measured 10.641-second install-to-ready time is contextual
baseline evidence, not this machine's result. No remote or cross-engine certification
is implied by this procedure.

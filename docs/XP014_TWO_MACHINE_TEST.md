# XP-014 — Pending two-machine acceptance

Status: **pending**, by owner instruction on 2026-10-02: no second Windows machine is available. The passing same-machine automated proof does not satisfy this gate. XP-010 clean-machine acceptance is a separate pending gate.

Use two Windows computers on a mutually reachable private IPv4 network, each with the same trusted XP-014 distribution. No Rust, Python, Godot editor, Builder development server or AI account is needed on the recipient. Record the distribution digest and both OS versions. Keep invite codes and ticket credentials out of shared evidence.

1. Open `XACE Play.exe` on the creator computer. Select Invite friend and copy the code.
2. Open `XACE Play.exe` on the friend computer, paste the code and select Join game. Its temporary local game should close after acquisition succeeds. Check visible download/verification progress and that both Players report Playing.
3. Move each Player independently. Confirm distinct canonical player entities, matching session/incarnation and verified baseline records in the host journal. Confirm only the creator owns the session authority after the join.
4. Leave on the friend. Confirm the creator continues and membership/cache are released. End on the creator; confirm the Player/runtime and invite listener stop while its journal remains.
5. Repeat from a missing recipient package. Exercise an expired code and controlled package-byte tampering; expect clear refusals with no partial live membership. Reusing a redeemed code must fail without closing a healthy Player.
6. Close a recipient during acquisition; confirm cleanup. Exercise a controlled readiness failure using the proof harness on a development host if necessary; the existing player must continue and the failed player must never enter required-input membership.

Collect redacted Player status, process ownership, host journal identity/baseline/departure records and refusal messages. Record the selected interface, reachability/firewall conditions and any manual setup. Do not label loopback, two windows on one computer or a manually forwarded public endpoint as this acceptance. XP-015 separately requires external-network relay acceptance without manual port forwarding.

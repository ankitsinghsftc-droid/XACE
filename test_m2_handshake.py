"""
test_m2_handshake.py — M2 handshake verification script

Run xace_runtime in one terminal, this script in another.
Verifies the full protocol: connect → handshake → ack → tick snapshots.

Usage:
    python test_m2_handshake.py [--port 7777] [--ticks 5]
"""

import socket
import json
import struct
import argparse
import sys
import time

# ── Wire protocol helpers ─────────────────────────────────────────────────────

def send_msg(sock: socket.socket, msg: dict) -> None:
    """Sends a length-prefixed JSON message (4-byte LE uint32 + JSON bytes)."""
    payload = json.dumps(msg).encode("utf-8")
    header  = struct.pack("<I", len(payload))
    sock.sendall(header + payload)

def recv_msg(sock: socket.socket) -> dict | None:
    """Reads one length-prefixed message. Returns None on clean close."""
    raw_len = _recv_exact(sock, 4)
    if raw_len is None:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    if msg_len > 4 * 1024 * 1024:
        raise ValueError(f"Message too large: {msg_len} bytes")
    payload = _recv_exact(sock, msg_len)
    if payload is None:
        return None
    return json.loads(payload.decode("utf-8"))

def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    """Reads exactly n bytes. Returns None on clean EOF."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="M2 Handshake Test")
    parser.add_argument("--port",  type=int, default=7777)
    parser.add_argument("--ticks", type=int, default=5,
                        help="Number of TickSnapshots to receive before exiting")
    parser.add_argument("--host",  default="127.0.0.1")
    args = parser.parse_args()

    print("=" * 60)
    print("  XACE M2 Handshake Test")
    print(f"  Connecting to {args.host}:{args.port}")
    print("=" * 60)

    # ── Connect ───────────────────────────────────────────────────────────
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((args.host, args.port))
        print(f"[OK]  Connected to {args.host}:{args.port}")
    except ConnectionRefusedError:
        print(f"[ERR] Connection refused — is xace_runtime running?")
        print(f"      Run: xace_runtime.exe --cgs game.cgs.json --port {args.port}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERR] Cannot connect: {e}")
        sys.exit(1)

    # ── Send Handshake ────────────────────────────────────────────────────
    handshake = {
        "msg_type":         "handshake",
        "protocol_version": 1,
        "engine_name":      "PythonTestClient",
        "engine_version":   "1.0.0",
        "adapter_version":  "0.1.0-test",
        "cgs_hash":         "0b1d495d59a76609",
    }
    send_msg(sock, handshake)
    print(f"[OK]  Sent Handshake (protocol_version=1, engine=PythonTestClient)")

    # ── Receive HandshakeAck ──────────────────────────────────────────────
    sock.settimeout(5.0)
    ack = recv_msg(sock)
    if ack is None:
        print("[ERR] Connection closed before HandshakeAck")
        sys.exit(1)

    print()
    print("── HandshakeAck ─────────────────────────────────────────────")
    print(f"  accepted:        {ack.get('accepted')}")
    print(f"  session_id:      {ack.get('session_id', '?')}")
    print(f"  tick_rate:       {ack.get('tick_rate')} fps")
    print(f"  cgs_hash:        {ack.get('cgs_hash', '?')}")
    print(f"  schema_version:  {ack.get('schema_version', '?')}")

    initial = ack.get("initial_entities", [])
    print(f"  initial_entities: {len(initial)}")
    for ent in initial:
        comps = list(ent.get("components", {}).keys())
        print(f"    entity #{ent['id']} '{ent['actor_id']}'  components={comps}")

    if not ack.get("accepted"):
        print(f"\n[ERR] Handshake rejected: {ack.get('reject_reason')}")
        sys.exit(1)

    print()
    print(f"[OK]  Handshake accepted — waiting for {args.ticks} TickSnapshots")
    print()

    # ── Receive TickSnapshots ─────────────────────────────────────────────
    sock.settimeout(2.0)
    received = 0

    while received < args.ticks:
        try:
            msg = recv_msg(sock)
        except socket.timeout:
            print("[WARN] Timeout waiting for TickSnapshot — is the runtime ticking?")
            break
        if msg is None:
            print("[INFO] Connection closed by runtime")
            break

        msg_type = msg.get("msg_type", "?")

        if msg_type == "tick_snapshot":
            tick      = msg.get("tick", "?")
            entities  = msg.get("entities", [])
            spawned   = msg.get("spawned_ids", [])
            destroyed = msg.get("destroyed_ids", [])
            ts        = msg.get("timestamp_ms", 0)

            print(f"  Tick {tick:>6}  entities={len(entities)}  "
                  f"spawned={len(spawned)}  destroyed={len(destroyed)}  "
                  f"t={ts}ms")

            # Show entity positions from first tick only
            if received == 0:
                for ent in entities:
                    comps = ent.get("components", {})
                    transform_json = comps.get("1") or comps.get(1)
                    if transform_json:
                        try:
                            t = json.loads(transform_json)
                            px = t.get("position_x", t.get("x", "?"))
                            py = t.get("position_y", t.get("y", "?"))
                            pz = t.get("position_z", t.get("z", "?"))
                            print(f"    #{ent['id']} '{ent['actor_id']}'  "
                                  f"pos=({px:.2f}, {py:.2f}, {pz:.2f})")
                        except Exception:
                            pass
            received += 1

        elif msg_type == "disconnect":
            print(f"[INFO] Runtime disconnected: {msg.get('reason', '?')}")
            break
        else:
            print(f"[INFO] Unexpected message: {msg_type}")

    print()
    if received == args.ticks:
        print(f"[PASS] ✓ M2 HANDSHAKE VERIFIED — received {received} TickSnapshots")
        print( "       The wire protocol is working. Godot can now connect.")
    else:
        print(f"[WARN] Received {received}/{args.ticks} snapshots before stopping")

    sock.close()
    print("=" * 60)

if __name__ == "__main__":
    main()
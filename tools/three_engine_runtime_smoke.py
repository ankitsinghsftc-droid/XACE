"""
Three-engine runtime bridge smoke harness.

This editor-free check launches one xace_runtime process, connects three tiny
adapter clients named Godot, Unity, and Unreal, steps one deterministic tick,
and verifies every client receives the same CGS hash, tick, and state hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server"
sys.path.insert(0, str(BUILDER_SERVER))

from runtime_control_client import RuntimeControlClient, RuntimeControlConfig  # noqa: E402


ENGINE_NAMES = ("Godot", "Unity", "Unreal")


def main() -> int:
    args = parse_args()
    cgs_path = Path(args.cgs).resolve()
    runtime_bin = Path(args.runtime_bin).resolve()
    engine_port = args.engine_port or find_free_port()
    control_port = args.control_port or find_free_port()
    cgs_hash = load_cgs_hash(cgs_path)

    process: subprocess.Popen[str] | None = None
    clients: list[socket.socket] = []
    try:
        if args.start_runtime:
            process = subprocess.Popen(
                [
                    str(runtime_bin),
                    "--cgs",
                    str(cgs_path),
                    "--quiet",
                    "--start-paused",
                    "--engine-clients",
                    str(len(ENGINE_NAMES)),
                    "--port",
                    str(engine_port),
                    "--control-port",
                    str(control_port),
                ],
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

        wait_for_port("127.0.0.1", control_port, args.timeout)
        for _ in ENGINE_NAMES:
            client = connect_with_retry("127.0.0.1", engine_port, args.timeout)
            client.settimeout(args.timeout)
            clients.append(client)

        for name, client in zip(ENGINE_NAMES, clients):
            write_frame(client, handshake_payload(name, cgs_hash))

        acks = [read_frame(client) for client in clients]
        for name, ack in zip(ENGINE_NAMES, acks):
            require(ack.get("accepted") is True, f"{name} handshake rejected: {ack}")
            require(ack.get("cgs_hash") == cgs_hash, f"{name} CGS hash mismatch: {ack}")
            require("multi_engine_clients" in ack.get("runtime_capabilities", []), f"{name} missing multi-client capability")

        control = RuntimeControlClient(RuntimeControlConfig(port=control_port, timeout_seconds=args.timeout))
        step_ack = control.send_control("step", session_id="three-engine-smoke")
        require(step_ack.get("accepted") is True, f"step rejected: {step_ack}")

        snapshots = [read_frame(client) for client in clients]
        for name, snapshot in zip(ENGINE_NAMES, snapshots):
            require(snapshot.get("msg_type") == "tick_snapshot", f"{name} expected tick_snapshot, got {snapshot}")

        ticks = [snapshot.get("tick") for snapshot in snapshots]
        hashes = [snapshot_state_hash(snapshot) for snapshot in snapshots]
        require(len(set(ticks)) == 1, f"engine ticks differ: {ticks}")
        require(len(set(hashes)) == 1, f"engine state hashes differ: {hashes}")

        status = control.status(session_id="three-engine-smoke").get("status", {})
        require(status.get("engine_connected") is True, f"runtime did not report engine connected: {status}")
        require("multi(" in str(status.get("adapter_type", "")), f"runtime did not report multi adapter type: {status}")

        shutdown = control.send_control("shutdown", session_id="three-engine-smoke")
        require(shutdown.get("accepted") is True, f"shutdown rejected: {shutdown}")
        if process is not None:
            process.wait(timeout=args.timeout)
            require(process.returncode == 0, f"runtime exited with {process.returncode}")

        print(json.dumps({
            "ok": True,
            "clients": len(clients),
            "engines": list(ENGINE_NAMES),
            "engine_port": engine_port,
            "control_port": control_port,
            "tick": ticks[0],
            "cgs_hash": cgs_hash,
            "state_hash": hashes[0],
            "adapter_type": status.get("adapter_type"),
        }, sort_keys=True))
        return 0
    except Exception as exc:
        if process is not None:
            try:
                RuntimeControlClient(RuntimeControlConfig(port=control_port, timeout_seconds=0.5)).send_control(
                    "shutdown",
                    session_id="three-engine-smoke-cleanup",
                )
            except Exception:
                process.terminate()
        print(f"three-engine runtime smoke failed: {exc}", file=sys.stderr)
        if process is not None and process.stdout is not None:
            try:
                output = process.communicate(timeout=1)[0]
            except Exception:
                output = ""
            if output:
                print(output[-4000:], file=sys.stderr)
        return 1
    finally:
        for client in clients:
            client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test one runtime feeding Godot, Unity, and Unreal clients.")
    parser.add_argument("--runtime-bin", default=str(REPO_ROOT / "target-codex-three-engine" / "debug" / "xace_runtime.exe"))
    parser.add_argument("--cgs", default=str(REPO_ROOT / "game.cgs.json"))
    parser.add_argument("--engine-port", type=int, default=0)
    parser.add_argument("--control-port", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--start-runtime", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def handshake_payload(engine_name: str, cgs_hash: str) -> dict[str, Any]:
    return {
        "msg_type": "handshake",
        "protocol_version": 1,
        "engine_name": engine_name,
        "engine_version": "smoke",
        "adapter_version": "0.1.0",
        "cgs_hash": cgs_hash,
        "capabilities": ["length_prefixed_json", "tick_snapshot_v1"],
    }


def load_cgs_hash(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return str(data.get("metadata", {}).get("cgs_hash", ""))


def snapshot_state_hash(snapshot: dict[str, Any]) -> str:
    deterministic_state = {
        "tick": snapshot.get("tick"),
        "entities": snapshot.get("entities", []),
        "spawned_ids": snapshot.get("spawned_ids", []),
        "destroyed_ids": snapshot.get("destroyed_ids", []),
        "events": snapshot.get("events", []),
        "playback_commands": snapshot.get("playback_commands", []),
    }
    raw = json.dumps(deterministic_state, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sock.sendall(struct.pack("<I", len(raw)))
    sock.sendall(raw)


def read_frame(sock: socket.socket) -> dict[str, Any]:
    header = read_exact(sock, 4)
    size = struct.unpack("<I", header)[0]
    require(0 < size <= 4 * 1024 * 1024, f"invalid frame size {size}")
    raw = read_exact(sock, size)
    value = json.loads(raw.decode("utf-8"))
    require(isinstance(value, dict), "frame was not a JSON object")
    return value


def read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    while sum(len(chunk) for chunk in chunks) < size:
        needed = size - sum(len(chunk) for chunk in chunks)
        chunk = sock.recv(needed)
        if not chunk:
            raise RuntimeError("socket closed early")
        chunks.append(chunk)
    return b"".join(chunks)


def wait_for_port(host: str, port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"{host}:{port} did not open: {last_error}")


def connect_with_retry(host: str, port: int, timeout: float) -> socket.socket:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection((host, port), timeout=0.2)
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"{host}:{port} did not accept connection: {last_error}")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())

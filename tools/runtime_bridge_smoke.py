"""
Runtime bridge smoke harness.

This is an editor-free integration check for the Phase 15 live bridge:
it launches xace_runtime, acts as a tiny engine adapter, sends a feedback
payload, steps one paused tick through the control socket, verifies runtime
feedback counters, then shuts the runtime down.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server"
sys.path.insert(0, str(BUILDER_SERVER))

from runtime_control_client import RuntimeControlClient, RuntimeControlConfig  # noqa: E402


def main() -> int:
    args = parse_args()
    cleanup: tempfile.TemporaryDirectory[str] | None = None
    if args.cgs:
        cgs_path = Path(args.cgs).resolve()
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="xace-runtime-bridge-cgs-")
        cgs_path = Path(cleanup.name) / "game.cgs.json"
        write_supported_bridge_cgs(cgs_path)
    runtime_bin = Path(args.runtime_bin).resolve()
    engine_port = args.engine_port or find_free_port()
    control_port = args.control_port or find_free_port()
    cgs_hash = load_cgs_hash(cgs_path)

    process: subprocess.Popen[str] | None = None
    engine: socket.socket | None = None
    try:
        if args.start_runtime:
            process = subprocess.Popen(
                [
                    str(runtime_bin),
                    "--cgs",
                    str(cgs_path),
                    "--derive-cgs-plan",
                    "--quiet",
                    "--start-paused",
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

        engine = connect_with_retry("127.0.0.1", engine_port, args.timeout)
        engine.settimeout(args.timeout)
        write_frame(engine, {
            "msg_type": "handshake",
            "protocol_version": 1,
            "engine_name": "SmokeEngine",
            "engine_version": "0.0",
            "adapter_version": "0.1.0",
            "cgs_hash": cgs_hash,
            "capabilities": ["length_prefixed_json", "tick_snapshot_v1", "feedback_payload_v1"],
        })
        ack = read_frame(engine)
        require(ack.get("accepted") is True, f"handshake rejected: {ack}")
        require(len(ack.get("initial_entities", [])) > 0, "handshake returned no entities")

        write_frame(engine, feedback_payload())
        control = RuntimeControlClient(RuntimeControlConfig(port=control_port, timeout_seconds=args.timeout))
        step_ack = control.send_control("step", session_id="runtime-smoke")
        require(step_ack.get("accepted") is True, f"step rejected: {step_ack}")

        snapshot = read_frame(engine)
        require(snapshot.get("msg_type") == "tick_snapshot", f"expected tick_snapshot, got {snapshot}")
        status = control.status(session_id="runtime-smoke").get("status", {})
        require(status.get("last_engine_feedback_processed") == 1, f"feedback not processed: {status}")
        require(status.get("last_engine_feedback_invalid") == 0, f"feedback invalid: {status}")
        require(status.get("last_engine_feedback_errors") == 0, f"feedback handler errors: {status}")
        require(status.get("adapter_type") == "smokeengine", f"adapter type missing: {status}")

        control_snapshot = control.send_control("snapshot", session_id="runtime-smoke")
        require(control_snapshot.get("accepted") is True, f"snapshot rejected: {control_snapshot}")
        require(
            len(control_snapshot.get("snapshot", {}).get("entities", [])) == len(snapshot.get("entities", [])),
            f"control snapshot entity mismatch: {control_snapshot}",
        )

        edit = control.send_engine_edit(
            "set_component_field",
            session_id="runtime-smoke",
            entity_id=1,
            component_type_id=1,
            field_path="position_x",
            value=3.5,
        )
        require(edit.get("accepted") is True, f"engine edit rejected: {edit}")
        edited_snapshot = control.send_control("snapshot", session_id="runtime-smoke")
        require(snapshot_has_position_x(edited_snapshot.get("snapshot", {}), 1, 3.5), "edit not visible in control snapshot")

        shutdown = control.send_control("shutdown", session_id="runtime-smoke")
        require(shutdown.get("accepted") is True, f"shutdown rejected: {shutdown}")
        if process is not None:
            process.wait(timeout=args.timeout)
            require(process.returncode == 0, f"runtime exited with {process.returncode}")

        print(json.dumps({
            "ok": True,
            "engine_port": engine_port,
            "control_port": control_port,
            "tick": snapshot.get("tick"),
            "entities": len(snapshot.get("entities", [])),
            "feedback_processed": status.get("last_engine_feedback_processed"),
            "control_snapshot_entities": len(control_snapshot.get("snapshot", {}).get("entities", [])),
        }, sort_keys=True))
        return 0
    except Exception as exc:
        if process is not None:
            try:
                RuntimeControlClient(RuntimeControlConfig(port=control_port, timeout_seconds=0.5)).send_control(
                    "shutdown",
                    session_id="runtime-smoke-cleanup",
                )
            except Exception:
                process.terminate()
        print(f"runtime bridge smoke failed: {exc}", file=sys.stderr)
        if process is not None and process.stdout is not None:
            try:
                output = process.communicate(timeout=1)[0]
            except Exception:
                output = ""
            if output:
                print(output[-4000:], file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.close()
        if cleanup is not None:
            cleanup.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test xace_runtime bridge/control/feedback.")
    parser.add_argument("--runtime-bin", default=str(REPO_ROOT / "target-codex-runtime-feedback" / "debug" / "xace_runtime.exe"))
    parser.add_argument("--cgs", default="")
    parser.add_argument("--engine-port", type=int, default=0)
    parser.add_argument("--control-port", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--start-runtime", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def write_supported_bridge_cgs(path: Path) -> None:
    payload = {
        "metadata": {
            "name": "Runtime Bridge Smoke",
            "schema_version": "0.1.0",
            "version": "0.1.0",
            "cgs_hash": "9" * 64,
        },
        "global_systems": [
            {
                "id": "MovementSystem",
                "phase": "Simulation",
                "reads": [1, 5],
                "writes": [1],
                "depends_on": [],
                "deterministic": True,
            }
        ],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [
                    {
                        "id": "player",
                        "spawn_count": 1,
                        "components": [
                            {
                                "type_id": 1,
                                "name": "COMP_TRANSFORM_V1",
                                "defaults": {
                                    "position_x": 0.0,
                                    "position_y": 0.0,
                                    "position_z": 0.0,
                                },
                            },
                            {
                                "type_id": 2,
                                "name": "COMP_IDENTITY_V1",
                                "defaults": {"name": "player"},
                            },
                            {
                                "type_id": 5,
                                "name": "COMP_VELOCITY_V1",
                                "defaults": {"vx": 1.0, "vy": 0.0, "vz": 0.0},
                            },
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def load_cgs_hash(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return str(data.get("metadata", {}).get("cgs_hash", ""))


def feedback_payload() -> dict[str, Any]:
    payload = {
        "engine_delta_apply_ms": 1.25,
        "draw_calls": 12,
        "physics_contacts": 0,
        "engine_entity_count": 2,
        "generated_frame": 1,
    }
    return {
        "msg_type": "feedback_payload",
        "tick": 0,
        "messages": [{
            "feedback_type": "PerformanceMetrics",
            "entity_id": 0,
            "generated_frame": 1,
            "payload_json": json.dumps(payload, separators=(",", ":"), sort_keys=True),
        }],
    }


def snapshot_has_position_x(snapshot: dict[str, Any], entity_id: int, expected: float) -> bool:
    for entity in snapshot.get("entities", []):
        if not isinstance(entity, dict) or int(entity.get("id", 0)) != entity_id:
            continue
        components = entity.get("components", {})
        if not isinstance(components, dict):
            return False
        raw_transform = components.get("1")
        if not isinstance(raw_transform, str):
            return False
        transform = json.loads(raw_transform)
        return abs(float(transform.get("position_x", 0.0)) - expected) < 0.0001
    return False


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

"""
Retained end-to-end proof for generated CGS gameplay systems.

The proof exercises one path through CGS generation, real SGC compilation,
strict runtime loading, deterministic ticking, runtime replay validation,
rollback failure restoration evidence, and live adapter snapshot output.
Artifacts are written under .xace/proof/cgs-e2e/<run-id>/ by default.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import sgc_runtime_proof as sgc_proof


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server"
if str(BUILDER_SERVER) not in sys.path:
    sys.path.insert(0, str(BUILDER_SERVER))

from runtime_control_client import RuntimeControlClient, RuntimeControlConfig  # noqa: E402


DEFAULT_TARGET_DIR = REPO_ROOT / "target-codex-certify"
RUNTIME_EXE = "xace_runtime.exe" if os.name == "nt" else "xace_runtime"
SGC_EXE = "xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler"
DEFAULT_RUNTIME_BIN = DEFAULT_TARGET_DIR / "debug" / RUNTIME_EXE
DEFAULT_SGC_BIN = DEFAULT_TARGET_DIR / "debug" / SGC_EXE
DEFAULT_PROOF_ROOT = REPO_ROOT / ".xace" / "proof" / "cgs-e2e"
DEFAULT_ROLLBACK_TARGET_DIR = REPO_ROOT / "target-codex-cgs-e2e-proof"
COUNTER_COMPONENT_TYPE_ID = 300
FIXED_POINT_SCALE = 1_000_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the retained end-to-end CGS proof.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--proof-root", default=str(DEFAULT_PROOF_ROOT))
    parser.add_argument("--run-id", default="", help="Optional retained proof run id.")
    parser.add_argument("--ticks", type=int, default=3)
    parser.add_argument("--target-dir", default=str(DEFAULT_ROLLBACK_TARGET_DIR))
    parser.add_argument("--timeout", type=float, default=8.0, help="Runtime socket timeout in seconds.")
    parser.add_argument("--rollback-timeout", type=float, default=180.0, help="Cargo rollback proof timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print only the proof summary JSON.")
    args = parser.parse_args(argv)

    try:
        summary = run_proof(
            runtime_bin=Path(args.runtime_bin).resolve(),
            sgc_bin=Path(args.sgc_bin).resolve(),
            proof_root=Path(args.proof_root).resolve(),
            run_id=args.run_id.strip() or None,
            ticks=args.ticks,
            target_dir=Path(args.target_dir).resolve(),
            runtime_timeout=float(args.timeout),
            rollback_timeout=float(args.rollback_timeout),
        )
    except Exception as exc:  # noqa: BLE001 - proof tools should print the actionable failure.
        print(f"CGS end-to-end proof failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
        print("CGS end-to-end proof PASSED")
    return 0


def run_proof(
    *,
    runtime_bin: Path,
    sgc_bin: Path,
    proof_root: Path,
    run_id: str | None,
    ticks: int,
    target_dir: Path,
    runtime_timeout: float,
    rollback_timeout: float,
) -> dict[str, Any]:
    sgc_proof.require(runtime_bin.is_file(), f"runtime binary not found: {runtime_bin}")
    sgc_proof.require(sgc_bin.is_file(), f"SGC binary not found: {sgc_bin}")
    sgc_proof.require(ticks > 0, "--ticks must be greater than zero")
    sgc_proof.require(runtime_timeout > 0, "--timeout must be greater than zero")
    sgc_proof.require(rollback_timeout > 0, "--rollback-timeout must be greater than zero")

    proof_dir = sgc_proof.allocate_proof_dir(proof_root, run_id)
    project_root = proof_dir / "project"

    cgs = sgc_proof.generated_system_cgs()
    cgs_hash = str(cgs["metadata"]["cgs_hash"])
    cgs_path = project_root / "game.cgs.json"
    sgc_proof.write_json(cgs_path, cgs)
    cgs_generation = {
        "schema": "xace.cgs_generation_proof.v1",
        "ok": True,
        "generated_by": "tools/cgs_end_to_end_proof.py",
        "cgs_hash": cgs_hash,
        "system_ids": [system["id"] for system in cgs["global_systems"]],
        "component_type_ids": sorted(
            {
                int(component["type_id"])
                for mode in cgs["modes"]
                for actor in mode["actors"]
                for component in actor["components"]
            }
        ),
    }
    sgc_proof.write_json(proof_dir / "cgs_generation.json", cgs_generation)

    sgc_input = sgc_proof.sgc_input_from_cgs(cgs)
    sgc_proof.write_json(proof_dir / "sgc_input.json", sgc_input)
    sgc_result = sgc_proof.run_sgc(sgc_bin, sgc_input)
    sgc_plan = sgc_result["plan"]
    sgc_proof.validate_sgc_plan(sgc_plan, cgs_hash, sgc_input)
    sgc_proof.write_json(proof_dir / "sgc_stdout_plan.json", sgc_plan)

    persisted_plan, sgc_proof_metadata = sgc_proof.persist_sgc_plan(
        project_root=project_root,
        sgc_input=sgc_input,
        sgc_plan=sgc_plan,
    )
    persisted_plan_path = project_root / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json"
    sgc_proof.write_json(proof_dir / "persisted_plan.json", persisted_plan)

    first_run = sgc_proof.run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        report_path=proof_dir / "first.schedule_report.json",
        stdout_path=proof_dir / "first.runtime.stdout.txt",
        stderr_path=proof_dir / "first.runtime.stderr.txt",
        ticks=ticks,
        world_seed=sgc_proof.DEFAULT_WORLD_SEED,
    )
    second_run = sgc_proof.run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        report_path=proof_dir / "second.schedule_report.json",
        stdout_path=proof_dir / "second.runtime.stdout.txt",
        stderr_path=proof_dir / "second.runtime.stderr.txt",
        ticks=ticks,
        world_seed=sgc_proof.DEFAULT_WORLD_SEED,
    )
    first_report = sgc_proof.read_runtime_report(
        first_run["report_path"],
        persisted_plan,
        ticks,
        sgc_proof.DEFAULT_WORLD_SEED,
    )
    second_report = sgc_proof.read_runtime_report(
        second_run["report_path"],
        persisted_plan,
        ticks,
        sgc_proof.DEFAULT_WORLD_SEED,
    )
    replay_checks = sgc_proof.compare_replay_reports(first_report, second_report)

    control_replay = run_control_replay_validation(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        proof_dir=proof_dir,
        ticks=ticks,
        timeout=runtime_timeout,
    )
    adapter_snapshot = run_adapter_snapshot_proof(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        cgs_hash=cgs_hash,
        proof_dir=proof_dir,
        timeout=runtime_timeout,
    )
    rollback_failure = run_rollback_failure_proof(
        proof_dir=proof_dir,
        target_dir=target_dir,
        timeout=rollback_timeout,
    )

    summary = {
        "schema": "xace.cgs_end_to_end_proof.v1",
        "ok": True,
        "run_id": proof_dir.name,
        "proof_dir": str(proof_dir),
        "project_dir": str(project_root),
        "cgs_path": str(cgs_path),
        "persisted_plan_path": str(persisted_plan_path),
        "ticks": ticks,
        "cgs_hash": cgs_hash,
        "plan_hash": persisted_plan["plan_hash"],
        "checks": {
            "cgs_generation": True,
            "real_sgc_compile": True,
            "strict_runtime_load": first_report["plan_source"] == "persisted_sgc",
            "deterministic_tick_hash_replay": replay_checks["tick_hash_replay_match"],
            "deterministic_schedule_replay": replay_checks["schedule_replay_match"],
            "runtime_replay_validation": bool(control_replay["accepted"]),
            "rollback_failure_restored": bool(rollback_failure["restored"]),
            "adapter_snapshot_output": bool(adapter_snapshot["ok"]),
            "no_fake_wiring": True,
        },
        "sgc": {
            "binary": str(sgc_bin),
            "returncode": sgc_result["returncode"],
            "stdout_plan_hash": sgc_plan["plan_hash"],
            "stderr_tail": sgc_result["stderr_tail"],
        },
        "runtime": {
            "binary": str(runtime_bin),
            "first_run": first_run,
            "second_run": second_run,
            "latest_world_hash": first_report["latest_world_hash"],
            "hash_log_count": len(first_report["hash_log"]),
            "control_replay": control_replay,
            "adapter_snapshot": adapter_snapshot,
        },
        "rollback_failure": rollback_failure,
        "sgc_proof_metadata": sgc_proof_metadata,
        "artifacts": {
            "cgs_generation": str(proof_dir / "cgs_generation.json"),
            "generated_cgs": str(cgs_path),
            "sgc_input": str(proof_dir / "sgc_input.json"),
            "sgc_stdout_plan": str(proof_dir / "sgc_stdout_plan.json"),
            "persisted_plan_copy": str(proof_dir / "persisted_plan.json"),
            "first_schedule_report": str(first_run["report_path"]),
            "second_schedule_report": str(second_run["report_path"]),
            "control_replay_validation": control_replay["artifact"],
            "rollback_failure": rollback_failure["artifact_dir"],
            "adapter_snapshot": adapter_snapshot["artifact"],
        },
    }
    sgc_proof.write_json(proof_dir / "summary.json", summary)
    return summary


def run_control_replay_validation(
    *,
    runtime_bin: Path,
    cgs_path: Path,
    proof_dir: Path,
    ticks: int,
    timeout: float,
) -> dict[str, Any]:
    control_port = find_free_port()
    stdout_path = proof_dir / "control_replay.runtime.stdout.txt"
    stderr_path = proof_dir / "control_replay.runtime.stderr.txt"
    process: subprocess.Popen[str] | None = None
    session_id = "cgs-e2e-replay"
    try:
        process = subprocess.Popen(
            [
                str(runtime_bin),
                "--cgs",
                str(cgs_path),
                "--require-sgc-plan",
                "--no-wait",
                "--quiet",
                "--start-paused",
                "--control-port",
                str(control_port),
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        wait_for_port("127.0.0.1", control_port, timeout)
        control = RuntimeControlClient(RuntimeControlConfig(port=control_port, timeout_seconds=timeout))
        steps = []
        final_status = {}
        for index in range(ticks):
            step_ack = control.send_control("step", session_id=session_id)
            sgc_proof.require(step_ack.get("accepted") is True, f"step rejected: {step_ack}")
            status_ack = wait_for_status_tick(control, index + 1, timeout, session_id=session_id)
            steps.append({"step": step_ack, "status_after_tick": status_ack})
            final_status = status_ack.get("status", {})

        record_ack = control.send_control("replay_record", session_id=session_id)
        sgc_proof.require(record_ack.get("accepted") is True, f"replay_record rejected: {record_ack}")
        validate_ack = control.send_control("replay_validate", session_id=session_id)
        sgc_proof.require(validate_ack.get("accepted") is True, f"replay_validate rejected: {validate_ack}")
        shutdown_ack = control.send_control("shutdown", session_id=session_id)
        sgc_proof.require(shutdown_ack.get("accepted") is True, f"shutdown rejected: {shutdown_ack}")
        stdout, stderr = communicate_process(process, timeout)
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        sgc_proof.require(process.returncode == 0, f"runtime replay process exited {process.returncode}: {stderr[-2000:]}")

        hash_log = final_status.get("hash_log") if isinstance(final_status, dict) else []
        sgc_proof.require(isinstance(hash_log, list) and len(hash_log) == ticks, "control replay hash_log length mismatch")
        artifact = {
            "schema": "xace.cgs_e2e.control_replay_validation.v1",
            "ok": True,
            "control_port": control_port,
            "steps": steps,
            "record": record_ack,
            "validate": validate_ack,
            "hash_log": hash_log,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
        artifact_path = proof_dir / "control_replay_validation.json"
        sgc_proof.write_json(artifact_path, artifact)
        return {
            "accepted": True,
            "compared_ticks": ticks,
            "record_reason": record_ack.get("reason", ""),
            "validate_reason": validate_ack.get("reason", ""),
            "hash_log_count": len(hash_log),
            "artifact": str(artifact_path),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    finally:
        cleanup_process(process, control_port, timeout, session_id)


def run_adapter_snapshot_proof(
    *,
    runtime_bin: Path,
    cgs_path: Path,
    cgs_hash: str,
    proof_dir: Path,
    timeout: float,
) -> dict[str, Any]:
    engine_port = find_free_port()
    control_port = find_free_port()
    stdout_path = proof_dir / "adapter.runtime.stdout.txt"
    stderr_path = proof_dir / "adapter.runtime.stderr.txt"
    process: subprocess.Popen[str] | None = None
    engine: socket.socket | None = None
    session_id = "cgs-e2e-adapter"
    try:
        process = subprocess.Popen(
            [
                str(runtime_bin),
                "--cgs",
                str(cgs_path),
                "--require-sgc-plan",
                "--quiet",
                "--start-paused",
                "--port",
                str(engine_port),
                "--control-port",
                str(control_port),
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        wait_for_port("127.0.0.1", control_port, timeout)
        engine = connect_with_retry("127.0.0.1", engine_port, timeout)
        engine.settimeout(timeout)
        write_frame(
            engine,
            {
                "msg_type": "handshake",
                "protocol_version": 1,
                "engine_name": "Task34ProofAdapter",
                "engine_version": "0.0",
                "adapter_version": "0.1.0",
                "cgs_hash": cgs_hash,
                "capabilities": ["length_prefixed_json", "tick_snapshot_v1"],
            },
        )
        ack = read_frame(engine)
        sgc_proof.write_json(proof_dir / "adapter_handshake_ack.json", ack)
        sgc_proof.require(ack.get("accepted") is True, f"adapter handshake rejected: {ack}")
        sgc_proof.require(len(ack.get("initial_entities", [])) > 0, "adapter handshake returned no entities")

        control = RuntimeControlClient(RuntimeControlConfig(port=control_port, timeout_seconds=timeout))
        step_ack = control.send_control("step", session_id=session_id)
        sgc_proof.require(step_ack.get("accepted") is True, f"adapter step rejected: {step_ack}")
        snapshot = read_frame(engine)
        sgc_proof.write_json(proof_dir / "adapter_tick_snapshot.json", snapshot)
        sgc_proof.require(snapshot.get("msg_type") == "tick_snapshot", f"expected tick_snapshot, got {snapshot}")
        sgc_proof.require(snapshot.get("tick") == 0, f"expected first adapter snapshot at tick 0, got {snapshot.get('tick')}")
        counter = find_counter_component(snapshot)
        sgc_proof.require(
            counter["count_units"] == 1,
            f"generated counter component was not incremented by one fixed-point unit: {counter}",
        )
        status_ack = wait_for_status_tick(control, 1, timeout, session_id=session_id)
        status = status_ack.get("status", {})
        sgc_proof.require(status.get("engine_snapshots_sent", 0) >= 1, f"runtime did not report adapter snapshots: {status}")
        sgc_proof.require(str(status.get("adapter_type", "")).lower() == "task34proofadapter", f"adapter type mismatch: {status}")

        snapshot_hash = snapshot_state_hash(snapshot)
        proof = {
            "schema": "xace.cgs_e2e.adapter_snapshot_proof.v1",
            "ok": True,
            "engine_port": engine_port,
            "control_port": control_port,
            "snapshot_tick": snapshot.get("tick"),
            "snapshot_hash": snapshot_hash,
            "entity_count": len(snapshot.get("entities", [])),
            "counter_entity_id": counter["entity_id"],
            "counter_component_type_id": COUNTER_COMPONENT_TYPE_ID,
            "counter_count_after_tick": counter["count_units"],
            "counter_count_raw_after_tick": counter["count_raw"],
            "status": status,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
        artifact_path = proof_dir / "adapter_snapshot_proof.json"
        sgc_proof.write_json(artifact_path, proof)

        shutdown_ack = control.send_control("shutdown", session_id=session_id)
        sgc_proof.require(shutdown_ack.get("accepted") is True, f"adapter shutdown rejected: {shutdown_ack}")
        stdout, stderr = communicate_process(process, timeout)
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        sgc_proof.require(process.returncode == 0, f"adapter runtime process exited {process.returncode}: {stderr[-2000:]}")
        return {
            "ok": True,
            "artifact": str(artifact_path),
            "handshake_ack": str(proof_dir / "adapter_handshake_ack.json"),
            "tick_snapshot": str(proof_dir / "adapter_tick_snapshot.json"),
            "snapshot_hash": snapshot_hash,
            "counter_count_after_tick": counter["count_units"],
            "counter_count_raw_after_tick": counter["count_raw"],
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    finally:
        if engine is not None:
            engine.close()
        cleanup_process(process, control_port, timeout, session_id)


def run_rollback_failure_proof(*, proof_dir: Path, target_dir: Path, timeout: float) -> dict[str, Any]:
    rollback_dir = proof_dir / "rollback_failure"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["XACE_MUTATION_PROOF_DIR"] = str(rollback_dir)
    cmd = [
        "cargo",
        "test",
        "-p",
        "xace-runtime-core",
        "mutation_atomicity_five_operation_batch_op3_failure_restores_byte_for_byte_state",
        "--lib",
        "--target-dir",
        str(target_dir),
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    (rollback_dir / "cargo_test_command.json").write_text(
        json.dumps({"command": cmd, "cwd": str(REPO_ROOT), "returncode": completed.returncode}, indent=2),
        encoding="utf-8",
    )
    (rollback_dir / "cargo_test.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (rollback_dir / "cargo_test.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            "rollback failure cargo test failed with "
            f"{completed.returncode}.\nstderr:\n{completed.stderr[-4000:]}"
        )

    hash_report_path = rollback_dir / "pre_post_hash_report.json"
    zero_diff_path = rollback_dir / "zero_diff_state_report.json"
    sgc_proof.require(hash_report_path.exists(), f"rollback hash report missing: {hash_report_path}")
    sgc_proof.require(zero_diff_path.exists(), f"rollback zero-diff report missing: {zero_diff_path}")
    hash_report = json.loads(hash_report_path.read_text(encoding="utf-8"))
    zero_diff_report = json.loads(zero_diff_path.read_text(encoding="utf-8"))
    sgc_proof.require(hash_report.get("hashes_equal") is True, f"rollback hashes diverged: {hash_report}")
    sgc_proof.require(zero_diff_report.get("byte_for_byte_equal") is True, f"rollback byte diff detected: {zero_diff_report}")
    sgc_proof.require(zero_diff_report.get("failing_operation_index") == 2, f"unexpected rollback failure index: {zero_diff_report}")
    sgc_proof.require(zero_diff_report.get("operation_type") == "modify_component", f"unexpected rollback operation: {zero_diff_report}")
    return {
        "restored": True,
        "artifact_dir": str(rollback_dir),
        "hash_report": str(hash_report_path),
        "zero_diff_report": str(zero_diff_path),
        "hashes_equal": hash_report.get("hashes_equal"),
        "byte_for_byte_equal": zero_diff_report.get("byte_for_byte_equal"),
        "failing_operation_index": zero_diff_report.get("failing_operation_index"),
        "operation_type": zero_diff_report.get("operation_type"),
        "cargo_returncode": completed.returncode,
    }


def wait_for_status_tick(
    control: RuntimeControlClient,
    expected_hash_records: int,
    timeout: float,
    *,
    session_id: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_ack: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_ack = control.status(session_id=session_id)
        status = last_ack.get("status", {})
        hash_log = status.get("hash_log") if isinstance(status, dict) else []
        if isinstance(hash_log, list) and len(hash_log) >= expected_hash_records:
            return last_ack
        time.sleep(0.05)
    raise RuntimeError(f"runtime did not reach {expected_hash_records} hash record(s): {last_ack}")


def find_counter_component(snapshot: dict[str, Any]) -> dict[str, int]:
    for entity in snapshot.get("entities", []):
        if not isinstance(entity, dict):
            continue
        components = entity.get("components")
        if not isinstance(components, dict):
            continue
        raw_component = components.get(str(COUNTER_COMPONENT_TYPE_ID), components.get(COUNTER_COMPONENT_TYPE_ID))
        if raw_component is None:
            continue
        if isinstance(raw_component, str):
            component = json.loads(raw_component)
        elif isinstance(raw_component, dict):
            component = raw_component
        else:
            continue
        count_raw = int(component.get("count", -1))
        return {
            "entity_id": int(entity.get("id", 0)),
            "count_raw": count_raw,
            "count_units": fixed_raw_to_units(count_raw),
        }
    raise RuntimeError(f"snapshot did not include component {COUNTER_COMPONENT_TYPE_ID}")


def fixed_raw_to_units(raw_value: int) -> int:
    if raw_value < 0 or raw_value % FIXED_POINT_SCALE != 0:
        return -1
    return raw_value // FIXED_POINT_SCALE


def snapshot_state_hash(snapshot: dict[str, Any]) -> str:
    stable = {
        "tick": snapshot.get("tick"),
        "entities": snapshot.get("entities", []),
        "spawned_ids": snapshot.get("spawned_ids", []),
        "destroyed_ids": snapshot.get("destroyed_ids", []),
        "playback_commands": snapshot.get("playback_commands", []),
    }
    return sgc_proof.sha256_json(stable)


def write_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sock.sendall(struct.pack("<I", len(raw)))
    sock.sendall(raw)


def read_frame(sock: socket.socket) -> dict[str, Any]:
    header = read_exact(sock, 4)
    size = struct.unpack("<I", header)[0]
    sgc_proof.require(0 < size <= 4 * 1024 * 1024, f"invalid frame size {size}")
    raw = read_exact(sock, size)
    value = json.loads(raw.decode("utf-8"))
    sgc_proof.require(isinstance(value, dict), "frame was not a JSON object")
    return value


def read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("socket closed early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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
    raise RuntimeError(f"timed out waiting for {host}:{port}: {last_error}")


def connect_with_retry(host: str, port: int, timeout: float) -> socket.socket:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection((host, port), timeout=0.5)
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"timed out connecting to {host}:{port}: {last_error}")


def cleanup_process(
    process: subprocess.Popen[str] | None,
    control_port: int,
    timeout: float,
    session_id: str,
) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        RuntimeControlClient(RuntimeControlConfig(port=control_port, timeout_seconds=0.5)).send_control(
            "shutdown",
            session_id=f"{session_id}-cleanup",
        )
        process.wait(timeout=timeout)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=1.0)
        except Exception:
            process.kill()


def communicate_process(process: subprocess.Popen[str], timeout: float) -> tuple[str, str]:
    try:
        return process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            return process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.communicate(timeout=1.0)


if __name__ == "__main__":
    raise SystemExit(main())

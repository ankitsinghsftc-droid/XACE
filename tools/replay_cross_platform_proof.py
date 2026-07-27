#!/usr/bin/env python3
"""Record and aggregate XACE cross-platform replay proof artifacts.

The per-platform command records a real CGS -> SGC -> runtime replay report for
one operating system. The aggregate command compares reports from Windows,
Linux, and macOS and fails unless the canonical replay identity matches across
all required platforms.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sgc_runtime_proof as sgc_proof


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROOF_ROOT = REPO_ROOT / ".xace" / "proof" / "replay-cross-platform"
DEFAULT_TARGET_DIR = REPO_ROOT / "target-codex-certify"
DEFAULT_TICKS = 6
DEFAULT_WORLD_SEED = 424242
REQUIRED_PLATFORM_KEYS = ("windows", "linux", "macos")
PLATFORM_REPORT_SCHEMA = "xace.replay_cross_platform.platform_report.v1"
SUMMARY_SCHEMA = "xace.replay_cross_platform.summary.v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record or aggregate XACE cross-platform replay proof artifacts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record", help="Record this platform's replay proof.")
    record_parser.add_argument("--runtime-bin", default="")
    record_parser.add_argument("--sgc-bin", default="")
    record_parser.add_argument("--target-dir", default=str(DEFAULT_TARGET_DIR))
    record_parser.add_argument("--proof-root", default=str(DEFAULT_PROOF_ROOT))
    record_parser.add_argument("--run-id", default="", help="Shared cross-platform run id.")
    record_parser.add_argument("--platform-key", default="", help="Override platform key.")
    record_parser.add_argument("--ticks", type=int, default=DEFAULT_TICKS)
    record_parser.add_argument("--world-seed", type=int, default=DEFAULT_WORLD_SEED)
    record_parser.add_argument("--json", action="store_true")

    aggregate_parser = subparsers.add_parser(
        "aggregate",
        help="Compare platform reports and write the cross-platform summary.",
    )
    aggregate_parser.add_argument("--proof-root", default=str(DEFAULT_PROOF_ROOT))
    aggregate_parser.add_argument("--run-id", default="")
    aggregate_parser.add_argument(
        "--reports",
        nargs="*",
        default=[],
        help="Explicit platform_report.json paths. Defaults to a recursive scan.",
    )
    aggregate_parser.add_argument(
        "--platforms",
        default=",".join(REQUIRED_PLATFORM_KEYS),
        help="Comma-separated required platform keys.",
    )
    aggregate_parser.add_argument("--output", default="")
    aggregate_parser.add_argument("--json", action="store_true")

    self_test_parser = subparsers.add_parser(
        "self-test",
        help="Exercise aggregation with deterministic fixture reports.",
    )
    self_test_parser.add_argument(
        "--target-dir",
        default=str(REPO_ROOT / "target-codex-replay-cross-platform-self-test"),
    )
    self_test_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            result = record_platform(args)
        elif args.command == "aggregate":
            result = aggregate_platforms(args)
        else:
            result = self_test(args)
    except Exception as exc:  # noqa: BLE001 - proof tools should surface the first actionable failure.
        print(f"cross-platform replay proof failed: {exc}", file=sys.stderr)
        return 1

    if bool(getattr(args, "json", False)):
        print(json.dumps(result, sort_keys=True))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


def record_platform(args: argparse.Namespace) -> dict[str, Any]:
    proof_root = Path(args.proof_root).resolve()
    run_id = str(args.run_id or timestamp_run_id()).strip()
    platform_key = normalize_platform_key(args.platform_key or platform.system())
    target_dir = Path(args.target_dir).resolve()
    runtime_bin = resolve_bin(args.runtime_bin, target_dir, runtime_exe_name())
    sgc_bin = resolve_bin(args.sgc_bin, target_dir, sgc_exe_name())
    ticks = int(args.ticks)
    world_seed = int(args.world_seed)

    sgc_proof.require(ticks > 0, "--ticks must be greater than zero")
    sgc_proof.require(0 <= world_seed <= 0xFFFFFFFFFFFFFFFF, "--world-seed must fit in u64")

    run_root = proof_root / run_id
    platform_dir = run_root / platform_key
    sgc_proof.require(
        not platform_dir.exists(),
        f"platform proof directory already exists: {platform_dir}",
    )
    platform_dir.mkdir(parents=True)

    sgc_summary = sgc_proof.run_proof(
        runtime_bin=runtime_bin,
        sgc_bin=sgc_bin,
        proof_root=platform_dir,
        run_id="sgc-runtime",
        ticks=ticks,
        world_seed=world_seed,
    )
    report = platform_report_from_sgc_summary(
        sgc_summary=sgc_summary,
        run_id=run_id,
        platform_key=platform_key,
        platform_dir=platform_dir,
    )
    report_path = platform_dir / "platform_report.json"
    write_json(report_path, report)
    report["artifacts"]["platform_report"] = str(report_path)
    write_json(report_path, report)
    return report


def aggregate_platforms(args: argparse.Namespace) -> dict[str, Any]:
    proof_root = Path(args.proof_root).resolve()
    run_id = str(args.run_id or "").strip()
    required_platforms = parse_platforms(args.platforms)
    report_paths = [Path(path).resolve() for path in getattr(args, "reports", [])]
    if not report_paths:
        report_paths = find_platform_reports(proof_root, run_id)
    summary = compare_platform_reports(
        reports=[read_json(path) for path in report_paths],
        report_paths=report_paths,
        required_platforms=required_platforms,
        run_id=run_id or infer_run_id(report_paths),
        proof_root=proof_root,
    )
    output = Path(args.output).resolve() if str(args.output or "").strip() else default_summary_path(
        proof_root,
        summary["run_id"],
    )
    write_json(output, summary)
    summary["artifacts"]["summary"] = str(output)
    write_json(output, summary)
    return summary


def platform_report_from_sgc_summary(
    *,
    sgc_summary: dict[str, Any],
    run_id: str,
    platform_key: str,
    platform_dir: Path,
) -> dict[str, Any]:
    sgc_proof.require(sgc_summary.get("schema") == "xace.sgc_runtime_proof.v1", "bad SGC summary schema")
    sgc_proof.require(sgc_summary.get("ok") is True, "SGC runtime proof did not pass")
    runtime = sgc_summary.get("runtime")
    sgc_proof.require(isinstance(runtime, dict), "SGC summary runtime block missing")

    identity = replay_identity(sgc_summary)
    return {
        "schema": PLATFORM_REPORT_SCHEMA,
        "ok": True,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform_key": platform_key,
        "platform": platform_metadata(),
        "replay_identity": identity,
        "semantic_hash": sgc_proof.sha256_json(identity),
        "checks": {
            "real_sgc_binary_invoked": bool((sgc_summary.get("checks") or {}).get("real_sgc_binary_invoked")),
            "real_runtime_binary_invoked": bool((sgc_summary.get("checks") or {}).get("real_runtime_binary_invoked")),
            "persisted_sgc_plan_loaded": bool((sgc_summary.get("checks") or {}).get("persisted_sgc_plan_loaded")),
            "world_seed_pinned": bool((sgc_summary.get("checks") or {}).get("world_seed_pinned")),
            "input_log_pinned": bool((sgc_summary.get("checks") or {}).get("input_log_pinned")),
            "local_replay_match": bool((sgc_summary.get("checks") or {}).get("tick_hash_replay_match")),
            "local_schedule_match": bool((sgc_summary.get("checks") or {}).get("schedule_replay_match")),
        },
        "artifacts": {
            "platform_dir": str(platform_dir),
            "sgc_runtime_summary": str(Path(str(sgc_summary["proof_dir"])) / "summary.json"),
            "input_log": str((sgc_summary.get("artifacts") or {}).get("input_log") or ""),
            "first_schedule_report": str((sgc_summary.get("artifacts") or {}).get("first_schedule_report") or ""),
            "second_schedule_report": str((sgc_summary.get("artifacts") or {}).get("second_schedule_report") or ""),
        },
    }


def replay_identity(sgc_summary: dict[str, Any]) -> dict[str, Any]:
    runtime = sgc_summary.get("runtime") or {}
    input_log = sgc_summary.get("input_log") or {}
    return {
        "schema": "xace.replay_cross_platform.identity.v1",
        "cgs_hash": sgc_summary.get("cgs_hash"),
        "compiled_from_cgs_hash": sgc_summary.get("compiled_from_cgs_hash"),
        "plan_hash": sgc_summary.get("plan_hash"),
        "generated_system_ids": sgc_summary.get("generated_system_ids"),
        "scheduled_system_ids": runtime.get("scheduled_system_ids"),
        "ticks": sgc_summary.get("ticks"),
        "world_seed": sgc_summary.get("world_seed"),
        "input_log_schema": input_log.get("schema"),
        "input_log_hash": sgc_summary.get("input_log_hash"),
        "input_packet_count": input_log.get("packet_count"),
        "schedule_fingerprint": runtime.get("schedule_fingerprint"),
        "latest_world_hash": runtime.get("latest_world_hash"),
        "hash_log": runtime.get("hash_log"),
    }


def compare_platform_reports(
    *,
    reports: list[dict[str, Any]],
    report_paths: list[Path],
    required_platforms: tuple[str, ...],
    run_id: str,
    proof_root: Path,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    reports_by_platform: dict[str, dict[str, Any]] = {}
    paths_by_platform: dict[str, str] = {}

    for index, report in enumerate(reports):
        path = report_paths[index] if index < len(report_paths) else Path("<memory>")
        if report.get("schema") != PLATFORM_REPORT_SCHEMA:
            issues.append(issue("bad_schema", str(path), PLATFORM_REPORT_SCHEMA, report.get("schema")))
            continue
        platform_key = normalize_platform_key(str(report.get("platform_key") or ""))
        if not platform_key:
            issues.append(issue("missing_platform_key", str(path), "non-empty platform_key", ""))
            continue
        if platform_key in reports_by_platform:
            issues.append(issue("duplicate_platform", platform_key, "one report", "multiple reports"))
            continue
        reports_by_platform[platform_key] = report
        paths_by_platform[platform_key] = str(path)
        if report.get("ok") is not True:
            issues.append(issue("platform_failed", platform_key, True, report.get("ok")))

    for platform_key in required_platforms:
        if platform_key not in reports_by_platform:
            issues.append(issue("missing_required_platform", platform_key, "present", "missing"))

    reference_platform = ""
    reference_identity: dict[str, Any] = {}
    reference_semantic_hash = ""
    if not issues:
        reference_platform = required_platforms[0]
        reference_report = reports_by_platform[reference_platform]
        reference_identity = reference_report.get("replay_identity") or {}
        reference_semantic_hash = str(reference_report.get("semantic_hash") or "")
        for platform_key in required_platforms[1:]:
            report = reports_by_platform[platform_key]
            actual_identity = report.get("replay_identity") or {}
            actual_semantic_hash = str(report.get("semantic_hash") or "")
            if actual_semantic_hash != reference_semantic_hash:
                issues.append(
                    issue(
                        "semantic_hash_mismatch",
                        platform_key,
                        reference_semantic_hash,
                        actual_semantic_hash,
                    )
                )
            for field, expected_value in reference_identity.items():
                actual_value = actual_identity.get(field)
                if actual_value != expected_value:
                    issues.append(issue(f"identity_{field}_mismatch", platform_key, expected_value, actual_value))

    ok = not issues
    return {
        "schema": SUMMARY_SCHEMA,
        "ok": ok,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "proof_root": str(proof_root),
        "required_platforms": list(required_platforms),
        "platforms_seen": sorted(reports_by_platform.keys()),
        "reference_platform": reference_platform,
        "checks": {
            "required_platforms_present": all(key in reports_by_platform for key in required_platforms),
            "unique_platform_reports": len(reports_by_platform) == len(reports),
            "all_platform_runs_ok": all(report.get("ok") is True for report in reports_by_platform.values()),
            "semantic_hash_match": not any(item["code"] == "semantic_hash_mismatch" for item in issues),
            "replay_identity_match": not any(item["code"].startswith("identity_") for item in issues),
        },
        "replay_identity": reference_identity,
        "semantic_hash": reference_semantic_hash,
        "mismatches": issues,
        "artifacts": {
            "platform_reports": paths_by_platform,
        },
    }


def self_test(args: argparse.Namespace) -> dict[str, Any]:
    target_dir = Path(args.target_dir).resolve()
    run_id = "self-test-" + timestamp_run_id()
    proof_root = target_dir / "proof"
    good_run_root = proof_root / run_id
    identity = self_test_identity()
    for platform_key in REQUIRED_PLATFORM_KEYS:
        write_json(
            good_run_root / platform_key / "platform_report.json",
            self_test_platform_report(run_id, platform_key, identity),
        )
    good_summary = compare_platform_reports(
        reports=[read_json(path) for path in find_platform_reports(proof_root, run_id)],
        report_paths=find_platform_reports(proof_root, run_id),
        required_platforms=REQUIRED_PLATFORM_KEYS,
        run_id=run_id,
        proof_root=proof_root,
    )

    mismatch_run_id = run_id + "-mismatch"
    for platform_key in REQUIRED_PLATFORM_KEYS:
        platform_identity = dict(identity)
        if platform_key == "macos":
            platform_identity["latest_world_hash"] = "b" * sgc_proof.HASH_HEX_LENGTH
        write_json(
            proof_root / mismatch_run_id / platform_key / "platform_report.json",
            self_test_platform_report(mismatch_run_id, platform_key, platform_identity),
        )
    mismatch_summary = compare_platform_reports(
        reports=[read_json(path) for path in find_platform_reports(proof_root, mismatch_run_id)],
        report_paths=find_platform_reports(proof_root, mismatch_run_id),
        required_platforms=REQUIRED_PLATFORM_KEYS,
        run_id=mismatch_run_id,
        proof_root=proof_root,
    )

    ok = bool(good_summary["ok"]) and not bool(mismatch_summary["ok"])
    result = {
        "schema": "xace.replay_cross_platform.self_test.v1",
        "ok": ok,
        "good_summary_ok": good_summary["ok"],
        "mismatch_summary_ok": mismatch_summary["ok"],
        "target_dir": str(target_dir),
    }
    write_json(target_dir / "self_test_summary.json", result)
    return result


def self_test_identity() -> dict[str, Any]:
    return {
        "schema": "xace.replay_cross_platform.identity.v1",
        "cgs_hash": "1" * sgc_proof.HASH_HEX_LENGTH,
        "compiled_from_cgs_hash": "1" * sgc_proof.HASH_HEX_LENGTH,
        "plan_hash": "2" * sgc_proof.HASH_HEX_LENGTH,
        "generated_system_ids": ["GeneratedCounterSystem", "GeneratedLootRollSystem"],
        "scheduled_system_ids": ["GeneratedCounterSystem", "GeneratedLootRollSystem"],
        "ticks": 2,
        "world_seed": DEFAULT_WORLD_SEED,
        "input_log_schema": "xace.replay.input_log.v1",
        "input_log_hash": "3" * sgc_proof.HASH_HEX_LENGTH,
        "input_packet_count": 0,
        "schedule_fingerprint": "4" * sgc_proof.HASH_HEX_LENGTH,
        "latest_world_hash": "5" * sgc_proof.HASH_HEX_LENGTH,
        "hash_log": [
            {"tick": 0, "world_hash": "6" * sgc_proof.HASH_HEX_LENGTH},
            {"tick": 1, "world_hash": "5" * sgc_proof.HASH_HEX_LENGTH},
        ],
    }


def self_test_platform_report(run_id: str, platform_key: str, identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": PLATFORM_REPORT_SCHEMA,
        "ok": True,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform_key": platform_key,
        "platform": {"system": platform_key},
        "replay_identity": identity,
        "semantic_hash": sgc_proof.sha256_json(identity),
        "checks": {
            "real_sgc_binary_invoked": True,
            "real_runtime_binary_invoked": True,
            "persisted_sgc_plan_loaded": True,
            "world_seed_pinned": True,
            "input_log_pinned": True,
            "local_replay_match": True,
            "local_schedule_match": True,
        },
        "artifacts": {},
    }


def find_platform_reports(proof_root: Path, run_id: str) -> list[Path]:
    search_root = proof_root / run_id if run_id else proof_root
    return sorted(search_root.glob("**/platform_report.json"))


def default_summary_path(proof_root: Path, run_id: str) -> Path:
    return proof_root / run_id / "summary.json" if run_id else proof_root / "summary.json"


def infer_run_id(report_paths: list[Path]) -> str:
    if not report_paths:
        return ""
    for parent in report_paths[0].parents:
        if parent.name in REQUIRED_PLATFORM_KEYS:
            return parent.parent.name
    return report_paths[0].parent.name


def parse_platforms(raw: str) -> tuple[str, ...]:
    values = tuple(normalize_platform_key(item) for item in raw.split(",") if item.strip())
    sgc_proof.require(bool(values), "--platforms must name at least one platform")
    return values


def normalize_platform_key(raw: str) -> str:
    value = raw.strip().lower()
    if value in {"windows", "win32", "win"}:
        return "windows"
    if value in {"linux"}:
        return "linux"
    if value in {"darwin", "mac", "macos", "osx"}:
        return "macos"
    return value


def platform_metadata() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python": sys.version,
        "runner_os": os.environ.get("RUNNER_OS", ""),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
        "rustc": capture_optional(["rustc", "-Vv"]),
    }


def capture_optional(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return completed.stdout.strip()


def resolve_bin(raw: str, target_dir: Path, exe_name: str) -> Path:
    if str(raw or "").strip():
        return Path(raw).resolve()
    return (target_dir / "debug" / exe_name).resolve()


def runtime_exe_name() -> str:
    return "xace_runtime.exe" if os.name == "nt" else "xace_runtime"


def sgc_exe_name() -> str:
    return "xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler"


def timestamp_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def issue(code: str, subject: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "code": code,
        "subject": subject,
        "expected": expected,
        "actual": actual,
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

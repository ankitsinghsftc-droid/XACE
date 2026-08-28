#!/usr/bin/env python3
"""Retained X10-064 proof for the canonical vertical slice in installed Godot.

This proof is intentionally stronger than an editor-free adapter smoke:

- it first reruns the X10-063 canonical fixture gate;
- it stages the canonical CGS slice into a disposable Godot project;
- it copies the current Godot adapter scripts into that staged project;
- it runs an installed Godot executable in headless mode;
- Godot itself writes the validation JSON and PNG evidence image;
- the wrapper captures logs and writes a hash report over every proof artifact.

The generated PNG is a deterministic Godot-created evidence image, not a
human-operated gameplay video. It exists so the installed-engine proof has a
retained visual artifact even when the certification runner is executed on a
headless machine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
FIXTURE_ROOT = REPO_ROOT / "projects" / "canonical_cross_engine_vertical_slice"
GODOT_ADAPTER_ROOT = REPO_ROOT / "adapters" / "godot"
DEFAULT_TARGET_ROOT = REPO_ROOT / "target-codex-task64-godot-vertical-slice"
DEFAULT_GODOT_DOWNLOAD = (
    Path.home()
    / "Downloads"
    / "Godot_v4.6.3-stable_win64.exe"
    / "Godot_v4.6.3-stable_win64_console.exe"
)

sys.path.insert(0, str(TOOLS_ROOT))
import canonical_vertical_slice_check  # noqa: E402


REPORT_SCHEMA = "xace.godot_vertical_slice_certification_report.v1"
VALIDATION_SCHEMA = "xace.godot_vertical_slice_validation.v1"
HASH_REPORT_SCHEMA = "xace.godot_vertical_slice_hash_report.v1"
TASK_ID = "X10-064"
REQUIRED_FEATURES = tuple(canonical_vertical_slice_check.REQUIRED_FEATURES)
EXPECTED_CGS_HASH = "a5856b8c95068a27ce47885c32c7d3e2729c4ff988a47f2dee840bfd13ff0a8a"
EXPECTED_FIXTURE_VERSION = "0.1.0"
ADAPTER_SCRIPT_NAMES = (
    "xace_adapter.gd",
    "xace_console_widget.gd",
    "xace_debug_hud.gd",
    "xace_delta_applicator.gd",
    "xace_entity_manager.gd",
    "xace_godot_main.gd",
    "xace_input_collector.gd",
    "xace_protocol.gd",
    "xace_transport.gd",
)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    evidence: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
        }
        if self.evidence is not None:
            payload["evidence"] = dict(self.evidence)
        return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the X10-064 installed-Godot vertical slice proof.")
    parser.add_argument("--godot-bin", default="", help="Path to an installed Godot executable.")
    parser.add_argument("--fixture-root", type=Path, default=FIXTURE_ROOT)
    parser.add_argument("--adapter-root", type=Path, default=GODOT_ADAPTER_ROOT)
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_TARGET_ROOT / "report.json",
        help="Final Task 64 report path.",
    )
    parser.add_argument("--timeout", type=float, default=45.0, help="Installed Godot runner timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print the final report JSON.")
    args = parser.parse_args(argv)

    try:
        report = run_certification(
            godot_bin=args.godot_bin,
            fixture_root=args.fixture_root.resolve(),
            adapter_root=args.adapter_root.resolve(),
            target_dir=args.target_dir.resolve(),
            output_path=args.output.resolve(),
            timeout_seconds=max(5.0, float(args.timeout)),
        )
    except Exception as exc:  # noqa: BLE001 - proof tools should surface one actionable failure.
        print(f"Godot vertical slice certification failed: {exc}", file=sys.stderr)
        return 1

    rendered = canonical_json(report, indent=2)
    if args.json:
        print(rendered)
    else:
        status = "PASSED" if report["ok"] else "FAILED"
        print(
            f"Godot vertical slice certification {status}: "
            f"{report['checks_passed']}/{report['checks_total']} checks"
        )
        print(f"report: {report['report_path']}")
    return 0 if report["ok"] else 1


def run_certification(
    *,
    godot_bin: str,
    fixture_root: Path,
    adapter_root: Path,
    target_dir: Path,
    output_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    require_under_repo(target_dir)
    require_under_repo(output_path)

    artifact_dir = target_dir / "artifacts"
    reports_dir = artifact_dir / "reports"
    logs_dir = artifact_dir / "logs"
    screenshots_dir = artifact_dir / "screenshots"
    hashes_dir = artifact_dir / "hashes"
    godot_project_dir = artifact_dir / "godot_project"
    for path in (reports_dir, logs_dir, screenshots_dir, hashes_dir):
        path.mkdir(parents=True, exist_ok=True)

    reset_generated_dir(godot_project_dir)
    for path in (reports_dir, logs_dir, screenshots_dir, hashes_dir):
        path.mkdir(parents=True, exist_ok=True)

    canonical_report_path = reports_dir / "canonical_vertical_slice_report.json"
    validation_path = reports_dir / "godot_vertical_slice_validation.json"
    screenshot_path = screenshots_dir / "godot_vertical_slice_screenshot.png"
    hash_report_path = hashes_dir / "godot_vertical_slice_hash_report.json"
    command_path = logs_dir / "godot_command.json"
    stdout_path = logs_dir / "godot_stdout.log"
    stderr_path = logs_dir / "godot_stderr.log"

    godot_executable = find_godot(godot_bin)
    canonical_report = canonical_vertical_slice_check.run_check(
        fixture_root=fixture_root,
        output_path=canonical_report_path,
    )
    staged = stage_godot_project(
        godot_project_dir=godot_project_dir,
        fixture_root=fixture_root,
        adapter_root=adapter_root,
        validation_path=validation_path,
        screenshot_path=screenshot_path,
    )

    version_report = probe_godot_version(godot_executable)
    command = [
        str(godot_executable),
        "--headless",
        "--path",
        str(godot_project_dir),
        "--script",
        str(staged["runner_path"]),
    ]
    command_payload = {
        "schema": "xace.godot_vertical_slice_command.v1",
        "task": TASK_ID,
        "cwd": str(godot_project_dir),
        "command": command,
        "timeout_seconds": timeout_seconds,
        "godot_version_probe": version_report,
    }
    command_path.write_text(canonical_json(command_payload, indent=2) + "\n", encoding="utf-8")

    started = time.perf_counter()
    completed = run_godot_command(command, godot_project_dir, timeout_seconds)
    elapsed = time.perf_counter() - started
    stdout_path.write_text(completed["stdout"], encoding="utf-8")
    stderr_path.write_text(completed["stderr"], encoding="utf-8")

    validation = read_json(validation_path)
    screenshot_sha = sha256_file(screenshot_path) if screenshot_path.exists() else ""
    hash_report = build_hash_report(
        godot_executable=godot_executable,
        godot_version_probe=version_report,
        fixture_root=fixture_root,
        adapter_root=adapter_root,
        artifacts=[
            canonical_report_path,
            validation_path,
            screenshot_path,
            command_path,
            stdout_path,
            stderr_path,
            staged["runner_path"],
            godot_project_dir / "project.godot",
            fixture_root / "game.cgs.json",
            fixture_root / "xace.vertical_slice_manifest.json",
        ],
        adapter_scripts=[adapter_root / name for name in ADAPTER_SCRIPT_NAMES],
        completed=completed,
        elapsed_seconds=elapsed,
    )
    hash_report_path.write_text(canonical_json(hash_report, indent=2) + "\n", encoding="utf-8")

    checks = [
        Check(
            "installed_godot_executable",
            godot_executable.exists() and godot_executable.is_file() and version_report.get("ok", False),
            "Installed Godot executable exists and returns a version.",
            {
                "path": str(godot_executable),
                "version": version_report.get("version", ""),
                "probe_returncode": version_report.get("returncode"),
            },
        ),
        Check(
            "canonical_vertical_slice_fixture_gate",
            bool(canonical_report.get("ok")),
            "X10-063 canonical slice gate passed before engine certification.",
            {
                "report_path": rel(canonical_report_path),
                "checks_passed": canonical_report.get("checks_passed"),
                "checks_total": canonical_report.get("checks_total"),
            },
        ),
        Check(
            "godot_project_staged",
            bool(staged.get("ok")),
            "Disposable Godot project contains the canonical fixture and current adapter scripts.",
            {
                "project_path": rel(godot_project_dir),
                "fixture_path": rel(staged["fixture_path"]),
                "adapter_script_count": len(staged["adapter_scripts"]),
            },
        ),
        Check(
            "installed_godot_validation_json",
            completed["returncode"] == 0
            and bool(validation.get("ok"))
            and validation.get("schema") == VALIDATION_SCHEMA,
            "Installed Godot wrote a passing validation JSON for the staged canonical slice.",
            {
                "path": rel(validation_path),
                "returncode": completed["returncode"],
                "schema": validation.get("schema", ""),
                "godot_engine_version": validation.get("godot", {}).get("version_string", ""),
                "cgs_hash": validation.get("cgs", {}).get("declared_hash", ""),
            },
        ),
        Check(
            "godot_png_evidence",
            screenshot_path.exists()
            and screenshot_path.stat().st_size > 0
            and bool(validation.get("screenshot", {}).get("ok"))
            and bool(screenshot_sha),
            "Installed Godot wrote a deterministic PNG evidence image.",
            {
                "path": rel(screenshot_path),
                "sha256": screenshot_sha,
                "bytes": screenshot_path.stat().st_size if screenshot_path.exists() else 0,
                "source": validation.get("screenshot", {}).get("source", ""),
            },
        ),
        Check(
            "logs_retained",
            command_path.exists() and stdout_path.exists() and stderr_path.exists(),
            "Godot command, stdout, and stderr logs were retained.",
            {
                "command": rel(command_path),
                "stdout": rel(stdout_path),
                "stderr": rel(stderr_path),
                "stdout_tail": tail_text(completed["stdout"]),
                "stderr_tail": tail_text(completed["stderr"]),
            },
        ),
        Check(
            "hash_report_retained",
            hash_report_path.exists()
            and hash_report.get("schema") == HASH_REPORT_SCHEMA
            and bool(hash_report.get("artifacts")),
            "Hash report covers fixture files, Godot outputs, logs, runner, and adapter scripts.",
            {
                "path": rel(hash_report_path),
                "sha256": sha256_file(hash_report_path),
                "artifact_count": len(hash_report.get("artifacts", [])),
            },
        ),
    ]
    ok = all(check.ok for check in checks)
    report = {
        "schema": REPORT_SCHEMA,
        "task": TASK_ID,
        "ok": ok,
        "x10_064_complete": ok,
        "generated_at_utc": utc_now(),
        "report_path": rel(output_path),
        "artifact_dir": rel(artifact_dir),
        "installed_engine_proof_path": rel(target_dir),
        "engine": "godot",
        "godot_executable": str(godot_executable),
        "godot_version": version_report.get("version", ""),
        "canonical_fixture": {
            "path": rel(fixture_root),
            "version": EXPECTED_FIXTURE_VERSION,
            "cgs_hash": EXPECTED_CGS_HASH,
            "gate_report": rel(canonical_report_path),
            "gate_report_sha256": sha256_file(canonical_report_path),
        },
        "evidence": {
            "validation_json": rel(validation_path),
            "screenshot_png": rel(screenshot_path),
            "stdout_log": rel(stdout_path),
            "stderr_log": rel(stderr_path),
            "command_log": rel(command_path),
            "hash_report": rel(hash_report_path),
            "hash_report_sha256": sha256_file(hash_report_path),
        },
        "godot_runner": {
            "returncode": completed["returncode"],
            "elapsed_seconds": round(elapsed, 3),
            "timed_out": bool(completed["timed_out"]),
        },
        "validation": validation,
        "checks_passed": sum(1 for check in checks if check.ok),
        "checks_total": len(checks),
        "checks": [check.to_dict() for check in checks],
        "boundary": {
            "proves": (
                "Installed Godot can load a staged project containing the canonical CGS-owned slice, "
                "parse/load current Godot adapter scripts, validate fixture identity/assets/features, "
                "and emit retained JSON, PNG, log, and hash evidence."
            ),
            "does_not_prove": (
                "This headless proof is not a finished-game package, human-recorded gameplay video, "
                "platform export, or cross-engine hash-equivalence result; those remain later gates."
            ),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(report, indent=2) + "\n", encoding="utf-8")
    if not ok:
        failed = ", ".join(check.name for check in checks if not check.ok)
        raise ValueError(f"checks failed: {failed}")
    return report


def find_godot(explicit: str) -> Path:
    candidates: list[Path] = []
    if explicit.strip():
        candidates.append(Path(explicit).expanduser())
    env_bin = os.environ.get("GODOT_BIN", "").strip()
    if env_bin:
        candidates.append(Path(env_bin).expanduser())
    candidates.append(DEFAULT_GODOT_DOWNLOAD)
    for name in ("godot", "godot4", "Godot"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        candidates.extend(path for path in downloads.glob("Godot*_console.exe") if path.is_file())
        candidates.extend(path for path in downloads.glob("Godot*/Godot*_console.exe") if path.is_file())
        candidates.extend(path for path in downloads.glob("Godot*.exe") if path.is_file())
        candidates.extend(path for path in downloads.glob("Godot*/Godot*.exe") if path.is_file())
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    rendered = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(f"Godot executable not found. Checked:\n{rendered}")


def probe_godot_version(godot_executable: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(godot_executable), "--version"],
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15.0,
        )
    except Exception as exc:  # noqa: BLE001 - version probe should be reported, not crash the proof.
        return {
            "ok": False,
            "error": str(exc),
            "version": "",
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
        }
    version = (completed.stdout or completed.stderr or "").strip().splitlines()
    return {
        "ok": completed.returncode == 0 and bool(version),
        "version": version[0] if version else "",
        "returncode": completed.returncode,
        "stdout_tail": tail_text(completed.stdout),
        "stderr_tail": tail_text(completed.stderr),
    }


def stage_godot_project(
    *,
    godot_project_dir: Path,
    fixture_root: Path,
    adapter_root: Path,
    validation_path: Path,
    screenshot_path: Path,
) -> dict[str, Any]:
    require_under_repo(godot_project_dir)
    godot_project_dir.mkdir(parents=True, exist_ok=True)
    (godot_project_dir / "project.godot").write_text(
        "\n".join(
            [
                "; Generated X10-064 Godot vertical-slice certification project.",
                "config_version=5",
                "",
                "[application]",
                'config/name="XACE Task64 Godot Vertical Slice"',
                'config/features=PackedStringArray("4.0")',
                "",
                "[debug]",
                "file_logging/enable_file_logging=false",
                "",
                "[rendering]",
                'renderer/rendering_method="gl_compatibility"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    fixture_dest = godot_project_dir / "fixtures" / "canonical_slice"
    reset_generated_dir(fixture_dest)
    fixture_dest.rmdir()
    shutil.copytree(fixture_root, fixture_dest)

    addons_dir = godot_project_dir / "addons" / "xace"
    addons_dir.mkdir(parents=True, exist_ok=True)
    copied_scripts: list[str] = []
    missing_scripts: list[str] = []
    for name in ADAPTER_SCRIPT_NAMES:
        source = adapter_root / name
        if not source.exists():
            missing_scripts.append(name)
            continue
        shutil.copy2(source, addons_dir / name)
        copied_scripts.append(rel(addons_dir / name))

    runner_path = godot_project_dir / "certify_vertical_slice.gd"
    runner_path.write_text(
        godot_runner_text(validation_path=validation_path, screenshot_path=screenshot_path),
        encoding="utf-8",
    )
    if missing_scripts:
        raise FileNotFoundError(f"Missing Godot adapter script(s): {', '.join(missing_scripts)}")
    return {
        "ok": True,
        "project_path": godot_project_dir,
        "fixture_path": fixture_dest,
        "runner_path": runner_path,
        "adapter_scripts": copied_scripts,
    }


def godot_runner_text(*, validation_path: Path, screenshot_path: Path) -> str:
    runner = r'''
extends SceneTree

const VALIDATION_OUTPUT := "__VALIDATION_OUTPUT__"
const SCREENSHOT_OUTPUT := "__SCREENSHOT_OUTPUT__"
const VALIDATION_SCHEMA := "__VALIDATION_SCHEMA__"
const EXPECTED_CGS_HASH := "__EXPECTED_CGS_HASH__"
const EXPECTED_FIXTURE_VERSION := "__EXPECTED_FIXTURE_VERSION__"
const CGS_PATH := "res://fixtures/canonical_slice/game.cgs.json"
const MANIFEST_PATH := "res://fixtures/canonical_slice/xace.vertical_slice_manifest.json"
const REQUIRED_FEATURES := __REQUIRED_FEATURES__
const ADAPTER_SCRIPT_PATHS := __ADAPTER_SCRIPT_PATHS__

var _started := false


func _init() -> void:
	call_deferred("_run")


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	if _started:
		return
	_started = true
	print("[XACE] X10-064 Godot vertical slice certification starting")
	var validation := _build_validation()
	var screenshot := _write_screenshot()
	validation["screenshot"] = screenshot
	validation["ok"] = _validation_ok(validation)
	_write_json(VALIDATION_OUTPUT, validation)
	if bool(validation.get("ok", false)):
		print("[XACE] X10-064 Godot vertical slice certification passed")
		quit(0)
	else:
		push_error("[XACE] X10-064 Godot vertical slice certification failed")
		quit(1)


func _build_validation() -> Dictionary:
	var cgs := _read_json(CGS_PATH)
	var manifest := _read_json(MANIFEST_PATH)
	var vertical_slice := _dict(cgs.get("vertical_slice", {}))
	var feature_coverage := _dict(vertical_slice.get("feature_coverage", {}))
	var manifest_feature_map := _dict(manifest.get("feature_map", {}))
	var metadata := _dict(cgs.get("metadata", {}))
	var manifest_cgs := _dict(manifest.get("cgs", {}))
	var target_engines := _array(manifest.get("target_engines", []))
	var semantic_bindings := _dict(cgs.get("semantic_bindings", {}))

	var cgs_declared_hash := str(metadata.get("cgs_hash", ""))
	var cgs_file_sha := _sha256_file(CGS_PATH)
	var manifest_file_sha := _sha256_file(MANIFEST_PATH)
	var checks: Array[Dictionary] = []
	checks.append(_check("cgs_json_parsed", not cgs.is_empty(), "CGS JSON parsed in installed Godot.", {"path": CGS_PATH}))
	checks.append(_check("manifest_json_parsed", not manifest.is_empty(), "Vertical-slice manifest JSON parsed in installed Godot.", {"path": MANIFEST_PATH}))
	checks.append(_check("fixture_identity", cgs_declared_hash == EXPECTED_CGS_HASH and str(manifest.get("version", "")) == EXPECTED_FIXTURE_VERSION, "Fixture hash/version match the canonical Task 63 slice.", {"cgs_hash": cgs_declared_hash, "version": manifest.get("version", "")}))
	checks.append(_check("manifest_targets_godot", target_engines.has("godot"), "Manifest includes Godot as a target engine.", {"target_engines": target_engines}))
	checks.append(_check("manifest_cgs_sha_matches", str(manifest_cgs.get("file_sha256", "")) == cgs_file_sha, "Manifest CGS file SHA-256 matches the staged CGS file.", {"manifest_sha256": manifest_cgs.get("file_sha256", ""), "computed_sha256": cgs_file_sha}))

	var missing_cgs_features: Array[String] = []
	var missing_manifest_features: Array[String] = []
	for feature in REQUIRED_FEATURES:
		if not feature_coverage.has(str(feature)):
			missing_cgs_features.append(str(feature))
		if not manifest_feature_map.has(str(feature)):
			missing_manifest_features.append(str(feature))
	checks.append(_check("required_features_present", missing_cgs_features.is_empty() and missing_manifest_features.is_empty(), "All required gameplay features are present in CGS and manifest coverage maps.", {"missing_cgs_features": missing_cgs_features, "missing_manifest_features": missing_manifest_features, "required_count": REQUIRED_FEATURES.size()}))

	var binding_records := _array(semantic_bindings.get("bindings", []))
	checks.append(_check("semantic_bindings_available", binding_records.size() >= 3, "Godot parsed semantic animation/audio/VFX binding records from CGS.", {"binding_count": binding_records.size()}))

	var adapter_results: Array[Dictionary] = []
	var missing_adapter_scripts: Array[String] = []
	for path in ADAPTER_SCRIPT_PATHS:
		var loaded: Variant = load(str(path))
		var loaded_ok := loaded != null
		adapter_results.append({"path": str(path), "loaded": loaded_ok})
		if not loaded_ok:
			missing_adapter_scripts.append(str(path))
	checks.append(_check("godot_adapter_scripts_load", missing_adapter_scripts.is_empty(), "Current Godot adapter scripts load in the staged installed-engine project.", {"scripts": adapter_results, "missing": missing_adapter_scripts}))

	var asset_results: Array[Dictionary] = []
	var missing_assets: Array[String] = []
	var mismatched_assets: Array[String] = []
	for asset in _array(manifest.get("asset_artifacts", [])):
		var asset_dict := _dict(asset)
		var relative_path := str(asset_dict.get("path", ""))
		var expected_sha := str(asset_dict.get("sha256", ""))
		var asset_path := "res://fixtures/canonical_slice/" + relative_path
		var exists := FileAccess.file_exists(asset_path)
		var actual_sha := _sha256_file(asset_path) if exists else ""
		var matches := exists and expected_sha == actual_sha
		asset_results.append({"id": str(asset_dict.get("id", "")), "path": asset_path, "exists": exists, "expected_sha256": expected_sha, "actual_sha256": actual_sha, "matches": matches})
		if not exists:
			missing_assets.append(relative_path)
		elif not matches:
			mismatched_assets.append(relative_path)
	checks.append(_check("asset_artifacts_present", missing_assets.is_empty() and mismatched_assets.is_empty(), "Godot can access the canonical slice asset files with expected SHA-256 values.", {"assets": asset_results, "missing": missing_assets, "mismatched": mismatched_assets}))

	var scenarios := _array(manifest.get("input_scenarios", []))
	var scenario_ok := false
	var scenario_summary := {}
	if not scenarios.is_empty():
		var first_scenario := _dict(scenarios[0])
		scenario_summary = {
			"id": str(first_scenario.get("id", "")),
			"ticks": int(first_scenario.get("ticks", 0)),
			"network_topology": str(first_scenario.get("network_topology", "")),
			"event_count": _array(first_scenario.get("events", [])).size(),
		}
		scenario_ok = scenario_summary["id"] == "canonical_host_client_attack_pickup" and scenario_summary["ticks"] == 8 and scenario_summary["network_topology"] == "host_client_lockstep" and scenario_summary["event_count"] >= 4
	checks.append(_check("input_scenario_available", scenario_ok, "Manifest contains the canonical host/client attack-pickup input scenario.", scenario_summary))

	var godot_version := Engine.get_version_info()
	return {
		"schema": VALIDATION_SCHEMA,
		"task": "X10-064",
		"engine": "godot",
		"ok": false,
		"generated_by": "installed Godot headless certification runner",
		"godot": {
			"name": Engine.get_architecture_name(),
			"version": godot_version,
			"version_string": str(godot_version.get("string", "")),
			"os_name": OS.get_name(),
			"display_server": DisplayServer.get_name(),
		},
		"project": {
			"path": ProjectSettings.globalize_path("res://"),
			"validation_output": VALIDATION_OUTPUT,
			"screenshot_output": SCREENSHOT_OUTPUT,
		},
		"cgs": {
			"path": CGS_PATH,
			"declared_hash": cgs_declared_hash,
			"file_sha256": cgs_file_sha,
			"manifest_file_sha256": manifest_file_sha,
			"system_count": _array(cgs.get("global_systems", [])).size(),
			"asset_count": _array(cgs.get("assets", [])).size(),
			"semantic_binding_count": binding_records.size(),
		},
		"manifest": {
			"path": MANIFEST_PATH,
			"schema": manifest.get("schema", ""),
			"slice_id": manifest.get("slice_id", ""),
			"version": manifest.get("version", ""),
			"target_engines": target_engines,
			"required_features": REQUIRED_FEATURES,
		},
		"checks_passed": _count_passed(checks),
		"checks_total": checks.size(),
		"checks": checks,
	}


func _validation_ok(report: Dictionary) -> bool:
	for check in _array(report.get("checks", [])):
		if not bool(_dict(check).get("ok", false)):
			return false
	if not bool(_dict(report.get("screenshot", {})).get("ok", false)):
		return false
	return true


func _write_screenshot() -> Dictionary:
	var image := Image.create(640, 360, false, Image.FORMAT_RGBA8)
	if image == null:
		return {"ok": false, "path": SCREENSHOT_OUTPUT, "source": "Godot Image.create", "error": "image_create_failed"}
	image.fill(Color(0.035, 0.045, 0.06, 1.0))
	_fill_rect(image, 28, 28, 584, 304, Color(0.075, 0.105, 0.145, 1.0))
	_fill_rect(image, 44, 58, 552, 30, Color(0.11, 0.18, 0.28, 1.0))
	_fill_rect(image, 64, 118, 160, 170, Color(0.12, 0.44, 0.76, 1.0))
	_fill_rect(image, 248, 118, 144, 170, Color(0.70, 0.23, 0.19, 1.0))
	_fill_rect(image, 416, 118, 160, 170, Color(0.20, 0.66, 0.38, 1.0))
	for x in range(64, 576, 32):
		_fill_rect(image, x, 306, 18, 10, Color(0.88, 0.72, 0.22, 1.0))
	var err := image.save_png(SCREENSHOT_OUTPUT)
	return {
		"ok": err == OK,
		"path": SCREENSHOT_OUTPUT,
		"width": image.get_width(),
		"height": image.get_height(),
		"source": "installed Godot Image.save_png deterministic evidence image",
		"error_code": int(err),
	}


func _fill_rect(image: Image, x0: int, y0: int, width: int, height: int, color: Color) -> void:
	for y in range(y0, y0 + height):
		for x in range(x0, x0 + width):
			image.set_pixel(x, y, color)


func _read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var text := FileAccess.get_file_as_string(path)
	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		return {}
	return parsed as Dictionary


func _sha256_file(path: String) -> String:
	if not FileAccess.file_exists(path):
		return ""
	var bytes := FileAccess.get_file_as_bytes(path)
	var context := HashingContext.new()
	var err := context.start(HashingContext.HASH_SHA256)
	if err != OK:
		return ""
	context.update(bytes)
	return context.finish().hex_encode()


func _check(name: String, ok: bool, detail: String, evidence: Dictionary = {}) -> Dictionary:
	return {
		"name": name,
		"ok": ok,
		"detail": detail,
		"evidence": evidence,
	}


func _count_passed(checks: Array) -> int:
	var passed := 0
	for check in checks:
		if bool(_dict(check).get("ok", false)):
			passed += 1
	return passed


func _dict(value: Variant) -> Dictionary:
	if typeof(value) == TYPE_DICTIONARY:
		return value as Dictionary
	return {}


func _array(value: Variant) -> Array:
	if typeof(value) == TYPE_ARRAY:
		return value as Array
	return []


func _write_json(path: String, payload: Dictionary) -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("[XACE] Could not write validation JSON: %s" % path)
		return
	file.store_string(JSON.stringify(payload, "\t", true))
	file.close()
'''
    replacements = {
        "__VALIDATION_OUTPUT__": gd_string(validation_path),
        "__SCREENSHOT_OUTPUT__": gd_string(screenshot_path),
        "__VALIDATION_SCHEMA__": VALIDATION_SCHEMA,
        "__EXPECTED_CGS_HASH__": EXPECTED_CGS_HASH,
        "__EXPECTED_FIXTURE_VERSION__": EXPECTED_FIXTURE_VERSION,
        "__REQUIRED_FEATURES__": json.dumps(list(REQUIRED_FEATURES)),
        "__ADAPTER_SCRIPT_PATHS__": json.dumps([f"res://addons/xace/{name}" for name in ADAPTER_SCRIPT_NAMES]),
    }
    for old, new in replacements.items():
        runner = runner.replace(old, new)
    return runner.lstrip()


def gd_string(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def run_godot_command(command: list[str], cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(timeout_seconds, 5.0),
        )
        return {
            "returncode": completed.returncode,
            "timed_out": False,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "returncode": 124,
            "timed_out": True,
            "stdout": stdout,
            "stderr": stderr,
        }


def build_hash_report(
    *,
    godot_executable: Path,
    godot_version_probe: Mapping[str, Any],
    fixture_root: Path,
    adapter_root: Path,
    artifacts: Iterable[Path],
    adapter_scripts: Iterable[Path],
    completed: Mapping[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    artifact_records = []
    for path in artifacts:
        artifact_records.append(file_record(path))
    adapter_records = []
    for path in adapter_scripts:
        adapter_records.append(file_record(path))
    return {
        "schema": HASH_REPORT_SCHEMA,
        "task": TASK_ID,
        "generated_at_utc": utc_now(),
        "engine": "godot",
        "godot_executable": str(godot_executable),
        "godot_executable_sha256": sha256_file(godot_executable),
        "godot_version_probe": dict(godot_version_probe),
        "fixture_root": rel(fixture_root),
        "adapter_root": rel(adapter_root),
        "expected_cgs_hash": EXPECTED_CGS_HASH,
        "godot_runner": {
            "returncode": completed.get("returncode"),
            "timed_out": bool(completed.get("timed_out")),
            "elapsed_seconds": round(elapsed_seconds, 3),
        },
        "artifacts": artifact_records,
        "adapter_scripts": adapter_records,
    }


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    exists = resolved.exists() and resolved.is_file()
    return {
        "path": rel(resolved) if is_under_repo(resolved) else str(resolved),
        "exists": exists,
        "bytes": resolved.stat().st_size if exists else 0,
        "sha256": sha256_file(resolved) if exists else "",
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def reset_generated_dir(path: Path) -> None:
    resolved = path.resolve()
    require_under_repo(resolved)
    if "target-codex-task64-godot-vertical-slice" not in resolved.parts:
        raise ValueError(f"Refusing to remove non-Task64 generated directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def require_under_repo(path: Path) -> None:
    resolved = path.resolve()
    if not is_under_repo(resolved):
        raise ValueError(f"Path is outside repository workspace: {resolved}")


def is_under_repo(path: Path) -> bool:
    repo = REPO_ROOT.resolve()
    resolved = path.resolve()
    return resolved == repo or repo in resolved.parents


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent, sort_keys=True, separators=(",", ": ") if indent else (",", ":"))


def rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT)).replace("/", "\\")
    except ValueError:
        return str(resolved)


def tail_text(value: str, *, max_chars: int = 1600) -> str:
    if not value:
        return ""
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n")
    return cleaned[-max_chars:]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

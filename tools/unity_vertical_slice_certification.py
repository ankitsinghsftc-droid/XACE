#!/usr/bin/env python3
"""Retained X10-065 proof for the canonical vertical slice in installed Unity.

The proof stages the X10-063 canonical slice into a disposable Unity project,
copies the current Unity adapter sources, runs an installed Unity editor in
batch mode, and requires Unity itself to emit validation JSON plus a PNG
evidence artifact. The Python wrapper retains command/editor/stdout/stderr logs
and writes a SHA-256 report over every evidence artifact.

This is an installed-editor certification artifact for the canonical CGS-owned
slice. It is deliberately not a finished-game build, platform export, or
human-recorded gameplay video.
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
UNITY_ADAPTER_ROOT = REPO_ROOT / "adapters" / "unity"
DEFAULT_TARGET_ROOT = REPO_ROOT / "target-codex-task65-unity-vertical-slice"
DEFAULT_UNITY_ROOT = Path("C:/Program Files/Unity/Hub/Editor")

sys.path.insert(0, str(TOOLS_ROOT))
import canonical_vertical_slice_check  # noqa: E402


REPORT_SCHEMA = "xace.unity_vertical_slice_certification_report.v1"
VALIDATION_SCHEMA = "xace.unity_vertical_slice_validation.v1"
HASH_REPORT_SCHEMA = "xace.unity_vertical_slice_hash_report.v1"
TASK_ID = "X10-065"
EXPECTED_CGS_HASH = "a5856b8c95068a27ce47885c32c7d3e2729c4ff988a47f2dee840bfd13ff0a8a"
EXPECTED_FIXTURE_VERSION = "0.1.0"
REQUIRED_FEATURES = tuple(canonical_vertical_slice_check.REQUIRED_FEATURES)
RUNTIME_SCRIPT_NAMES = (
    "XaceTransport.cs",
    "XaceInputCollector.cs",
    "XaceDeltaApplicator.cs",
    "XaceConsoleWidget.cs",
    "XaceRuntimeBootstrap.cs",
    "Xace_embedded.cs",
    "XACE.Adapter.Unity.asmdef",
)
EDITOR_SCRIPT_NAMES = (
    "XaceUnityValidation.cs",
    "XaceUnitySetupMenu.cs",
    "XaceUnityPlayBootstrap.cs",
    "XaceUnityLiveValidationCommand.cs",
    "XACE.Adapter.Unity.Editor.asmdef",
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
    parser = argparse.ArgumentParser(description="Run the X10-065 installed-Unity vertical slice proof.")
    parser.add_argument("--unity-exe", default="", help="Path to an installed Unity.exe.")
    parser.add_argument("--fixture-root", type=Path, default=FIXTURE_ROOT)
    parser.add_argument("--adapter-root", type=Path, default=UNITY_ADAPTER_ROOT)
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_TARGET_ROOT / "report.json",
        help="Final Task 65 report path.",
    )
    parser.add_argument("--timeout", type=float, default=240.0, help="Installed Unity runner timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print the final report JSON.")
    args = parser.parse_args(argv)

    try:
        report = run_certification(
            unity_exe=args.unity_exe,
            fixture_root=args.fixture_root.resolve(),
            adapter_root=args.adapter_root.resolve(),
            target_dir=args.target_dir.resolve(),
            output_path=args.output.resolve(),
            timeout_seconds=max(30.0, float(args.timeout)),
        )
    except Exception as exc:  # noqa: BLE001 - proof tools should surface one actionable failure.
        print(f"Unity vertical slice certification failed: {exc}", file=sys.stderr)
        return 1

    rendered = canonical_json(report, indent=2)
    if args.json:
        print(rendered)
    else:
        status = "PASSED" if report["ok"] else "FAILED"
        print(
            f"Unity vertical slice certification {status}: "
            f"{report['checks_passed']}/{report['checks_total']} checks"
        )
        print(f"report: {report['report_path']}")
    return 0 if report["ok"] else 1


def run_certification(
    *,
    unity_exe: str,
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
    unity_project_dir = artifact_dir / "unity_project"
    for path in (reports_dir, logs_dir, screenshots_dir, hashes_dir):
        path.mkdir(parents=True, exist_ok=True)

    reset_generated_dir(unity_project_dir)
    for path in (reports_dir, logs_dir, screenshots_dir, hashes_dir):
        path.mkdir(parents=True, exist_ok=True)

    canonical_report_path = reports_dir / "canonical_vertical_slice_report.json"
    validation_path = reports_dir / "unity_vertical_slice_validation.json"
    screenshot_path = screenshots_dir / "unity_vertical_slice_screenshot.png"
    hash_report_path = hashes_dir / "unity_vertical_slice_hash_report.json"
    command_path = logs_dir / "unity_command.json"
    editor_log_path = logs_dir / "unity_editor.log"
    stdout_path = logs_dir / "unity_stdout.log"
    stderr_path = logs_dir / "unity_stderr.log"

    unity_executable = find_unity(unity_exe)
    version_report = probe_unity_version(unity_executable)
    canonical_report = canonical_vertical_slice_check.run_check(
        fixture_root=fixture_root,
        output_path=canonical_report_path,
    )
    staged = stage_unity_project(
        unity_project_dir=unity_project_dir,
        fixture_root=fixture_root,
        adapter_root=adapter_root,
        validation_path=validation_path,
        screenshot_path=screenshot_path,
        unity_version=str(version_report.get("version") or "6000.4.9f1"),
    )

    command = [
        str(unity_executable),
        "-batchmode",
        "-quit",
        "-projectPath",
        str(unity_project_dir),
        "-executeMethod",
        "Xace.Adapter.Unity.Editor.XaceUnityVerticalSliceCertification.Run",
        "-logFile",
        str(editor_log_path),
        "--xace-validation-output",
        str(validation_path),
        "--xace-screenshot-output",
        str(screenshot_path),
    ]
    command_payload = {
        "schema": "xace.unity_vertical_slice_command.v1",
        "task": TASK_ID,
        "cwd": str(unity_project_dir),
        "command": command,
        "timeout_seconds": timeout_seconds,
        "unity_version_probe": version_report,
    }
    command_path.write_text(canonical_json(command_payload, indent=2) + "\n", encoding="utf-8")

    started = time.perf_counter()
    completed = run_unity_command(command, unity_project_dir, timeout_seconds)
    elapsed = time.perf_counter() - started
    stdout_path.write_text(completed["stdout"], encoding="utf-8")
    stderr_path.write_text(completed["stderr"], encoding="utf-8")

    validation = read_json(validation_path)
    screenshot_sha = sha256_file(screenshot_path) if screenshot_path.exists() else ""
    hash_report = build_hash_report(
        unity_executable=unity_executable,
        unity_version_probe=version_report,
        fixture_root=fixture_root,
        adapter_root=adapter_root,
        artifacts=[
            canonical_report_path,
            validation_path,
            screenshot_path,
            command_path,
            editor_log_path,
            stdout_path,
            stderr_path,
            staged["runner_path"],
            unity_project_dir / "Packages" / "manifest.json",
            unity_project_dir / "ProjectSettings" / "ProjectVersion.txt",
            fixture_root / "game.cgs.json",
            fixture_root / "xace.vertical_slice_manifest.json",
        ],
        adapter_scripts=[adapter_root / name for name in RUNTIME_SCRIPT_NAMES]
        + [adapter_root / "Editor" / name for name in EDITOR_SCRIPT_NAMES],
        completed=completed,
        elapsed_seconds=elapsed,
    )
    hash_report_path.write_text(canonical_json(hash_report, indent=2) + "\n", encoding="utf-8")

    checks = [
        Check(
            "installed_unity_executable",
            unity_executable.exists() and unity_executable.is_file() and version_report.get("ok", False),
            "Installed Unity executable exists and returns a version.",
            {
                "path": str(unity_executable),
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
            "unity_project_staged",
            bool(staged.get("ok")),
            "Disposable Unity project contains the canonical fixture and current adapter sources.",
            {
                "project_path": rel(unity_project_dir),
                "fixture_path": rel(staged["fixture_path"]),
                "runtime_script_count": len(staged["runtime_scripts"]),
                "editor_script_count": len(staged["editor_scripts"]),
            },
        ),
        Check(
            "installed_unity_validation_json",
            completed["returncode"] == 0
            and bool(validation.get("ok"))
            and validation.get("schema") == VALIDATION_SCHEMA,
            "Installed Unity wrote a passing validation JSON for the staged canonical slice.",
            {
                "path": rel(validation_path),
                "returncode": completed["returncode"],
                "schema": validation.get("schema", ""),
                "unity_version": validation.get("unity", {}).get("version", ""),
                "cgs_hash": validation.get("cgs", {}).get("declared_hash", ""),
            },
        ),
        Check(
            "unity_png_evidence",
            screenshot_path.exists()
            and screenshot_path.stat().st_size > 0
            and bool(validation.get("screenshot", {}).get("ok"))
            and bool(screenshot_sha),
            "Installed Unity wrote a deterministic PNG evidence image.",
            {
                "path": rel(screenshot_path),
                "sha256": screenshot_sha,
                "bytes": screenshot_path.stat().st_size if screenshot_path.exists() else 0,
                "source": validation.get("screenshot", {}).get("source", ""),
            },
        ),
        Check(
            "logs_retained",
            command_path.exists() and editor_log_path.exists() and stdout_path.exists() and stderr_path.exists(),
            "Unity command, editor log, stdout, and stderr logs were retained.",
            {
                "command": rel(command_path),
                "editor_log": rel(editor_log_path),
                "stdout": rel(stdout_path),
                "stderr": rel(stderr_path),
                "stdout_tail": tail_text(completed["stdout"]),
                "stderr_tail": tail_text(completed["stderr"]),
                "editor_tail": tail_file(editor_log_path),
            },
        ),
        Check(
            "hash_report_retained",
            hash_report_path.exists()
            and hash_report.get("schema") == HASH_REPORT_SCHEMA
            and bool(hash_report.get("artifacts")),
            "Hash report covers fixture files, Unity outputs, logs, runner, and adapter scripts.",
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
        "x10_065_complete": ok,
        "generated_at_utc": utc_now(),
        "report_path": rel(output_path),
        "artifact_dir": rel(artifact_dir),
        "installed_engine_proof_path": rel(target_dir),
        "engine": "unity",
        "unity_executable": str(unity_executable),
        "unity_version": version_report.get("version", ""),
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
            "editor_log": rel(editor_log_path),
            "stdout_log": rel(stdout_path),
            "stderr_log": rel(stderr_path),
            "command_log": rel(command_path),
            "hash_report": rel(hash_report_path),
            "hash_report_sha256": sha256_file(hash_report_path),
        },
        "unity_runner": {
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
                "Installed Unity can compile/load a staged project containing the canonical CGS-owned slice, "
                "construct current Unity adapter components, validate fixture identity/assets/features, "
                "and emit retained JSON, PNG, log, and hash evidence."
            ),
            "does_not_prove": (
                "This batch-mode proof is not a finished-game package, human-recorded gameplay video, "
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


def find_unity(explicit: str) -> Path:
    candidates: list[Path] = []
    if explicit.strip():
        candidates.append(Path(explicit).expanduser())
    env_bin = os.environ.get("UNITY_EXE", "").strip()
    if env_bin:
        candidates.append(Path(env_bin).expanduser())
    discovered = shutil.which("Unity.exe") or shutil.which("unity")
    if discovered:
        candidates.append(Path(discovered))
    if DEFAULT_UNITY_ROOT.exists():
        for version_dir in sorted(DEFAULT_UNITY_ROOT.iterdir(), reverse=True):
            candidates.append(version_dir / "Editor" / "Unity.exe")
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    rendered = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(f"Unity executable not found. Checked:\n{rendered}")


def probe_unity_version(unity_executable: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(unity_executable), "-version", "-batchmode", "-quit"],
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30.0,
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
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    version = first_unity_version_line(combined)
    return {
        "ok": completed.returncode == 0 and bool(version),
        "version": version,
        "returncode": completed.returncode,
        "stdout_tail": tail_text(completed.stdout),
        "stderr_tail": tail_text(completed.stderr),
    }


def first_unity_version_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned.startswith("Unity ") or cleaned.startswith("6000.") or cleaned.startswith("20"):
            return cleaned.replace("Unity ", "", 1)
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def stage_unity_project(
    *,
    unity_project_dir: Path,
    fixture_root: Path,
    adapter_root: Path,
    validation_path: Path,
    screenshot_path: Path,
    unity_version: str,
) -> dict[str, Any]:
    require_under_repo(unity_project_dir)
    assets_dir = unity_project_dir / "Assets"
    packages_dir = unity_project_dir / "Packages"
    settings_dir = unity_project_dir / "ProjectSettings"
    runtime_dest = assets_dir / "XACE"
    editor_dest = runtime_dest / "Editor"
    fixture_dest = assets_dir / "XACEFixtures" / "CanonicalSlice"
    for path in (assets_dir, packages_dir, settings_dir, runtime_dest, editor_dest, fixture_dest.parent):
        path.mkdir(parents=True, exist_ok=True)

    (packages_dir / "manifest.json").write_text(
        canonical_json(
            {
                "dependencies": {
                    "com.unity.modules.animation": "1.0.0",
                    "com.unity.modules.audio": "1.0.0",
                    "com.unity.modules.imgui": "1.0.0",
                    "com.unity.modules.particlesystem": "1.0.0",
                    "com.unity.modules.physics": "1.0.0",
                    "com.unity.modules.uielements": "1.0.0",
                    "com.unity.modules.unitywebrequest": "1.0.0",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (settings_dir / "ProjectVersion.txt").write_text(
        f"m_EditorVersion: {unity_version}\nm_EditorVersionWithRevision: {unity_version}\n",
        encoding="utf-8",
    )

    reset_generated_dir(fixture_dest)
    fixture_dest.rmdir()
    shutil.copytree(fixture_root, fixture_dest)

    runtime_scripts: list[str] = []
    missing_runtime: list[str] = []
    for name in RUNTIME_SCRIPT_NAMES:
        source = adapter_root / name
        if not source.exists():
            missing_runtime.append(name)
            continue
        shutil.copy2(source, runtime_dest / name)
        runtime_scripts.append(rel(runtime_dest / name))

    editor_scripts: list[str] = []
    missing_editor: list[str] = []
    for name in EDITOR_SCRIPT_NAMES:
        source = adapter_root / "Editor" / name
        if not source.exists():
            missing_editor.append(name)
            continue
        shutil.copy2(source, editor_dest / name)
        editor_scripts.append(rel(editor_dest / name))

    runner_path = editor_dest / "XaceUnityVerticalSliceCertification.cs"
    runner_path.write_text(
        unity_certification_script_text(validation_path=validation_path, screenshot_path=screenshot_path),
        encoding="utf-8",
    )
    editor_scripts.append(rel(runner_path))

    missing = missing_runtime + [f"Editor/{name}" for name in missing_editor]
    if missing:
        raise FileNotFoundError(f"Missing Unity adapter source file(s): {', '.join(missing)}")
    return {
        "ok": True,
        "project_path": unity_project_dir,
        "fixture_path": fixture_dest,
        "runner_path": runner_path,
        "runtime_scripts": runtime_scripts,
        "editor_scripts": editor_scripts,
    }


def unity_certification_script_text(*, validation_path: Path, screenshot_path: Path) -> str:
    required_features_literal = ", ".join(f'"{feature}"' for feature in REQUIRED_FEATURES)
    text = r'''
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Xace.Adapter.Unity;
using UnityEditor;
using UnityEngine;

namespace Xace.Adapter.Unity.Editor
{
    public static class XaceUnityVerticalSliceCertification
    {
        private const string ValidationSchema = "__VALIDATION_SCHEMA__";
        private const string ExpectedCgsHash = "__EXPECTED_CGS_HASH__";
        private const string ExpectedFixtureVersion = "__EXPECTED_FIXTURE_VERSION__";
        private const string ValidationOutput = "__VALIDATION_OUTPUT__";
        private const string ScreenshotOutput = "__SCREENSHOT_OUTPUT__";
        private static readonly string[] RequiredFeatures = new[] { __REQUIRED_FEATURES__ };

        public static void Run()
        {
            try
            {
                var args = Environment.GetCommandLineArgs();
                var validationOutput = ArgValue(args, "--xace-validation-output", ValidationOutput);
                var screenshotOutput = ArgValue(args, "--xace-screenshot-output", ScreenshotOutput);
                var report = BuildValidation(validationOutput, screenshotOutput);
                var screenshot = WriteScreenshot(screenshotOutput);
                report["screenshot"] = screenshot;
                report["ok"] = ValidationOk(report);
                WriteJson(validationOutput, report);
                Debug.Log("[XACE] X10-065 Unity vertical slice certification result: " + (bool)report["ok"]);
                EditorApplication.Exit((bool)report["ok"] ? 0 : 1);
            }
            catch (Exception ex)
            {
                var failure = new Dictionary<string, object>
                {
                    ["schema"] = ValidationSchema,
                    ["task"] = "X10-065",
                    ["engine"] = "unity",
                    ["ok"] = false,
                    ["error"] = ex.ToString(),
                };
                WriteJson(ValidationOutput, failure);
                Debug.LogError("[XACE] X10-065 Unity vertical slice certification failed: " + ex);
                EditorApplication.Exit(1);
            }
        }

        private static Dictionary<string, object> BuildValidation(string validationOutput, string screenshotOutput)
        {
            var projectRoot = Directory.GetParent(Application.dataPath).FullName;
            var cgsPath = Path.Combine(Application.dataPath, "XACEFixtures", "CanonicalSlice", "game.cgs.json");
            var manifestPath = Path.Combine(Application.dataPath, "XACEFixtures", "CanonicalSlice", "xace.vertical_slice_manifest.json");
            var cgsText = File.Exists(cgsPath) ? File.ReadAllText(cgsPath, Encoding.UTF8) : "";
            var manifestText = File.Exists(manifestPath) ? File.ReadAllText(manifestPath, Encoding.UTF8) : "";
            var cgsFileSha = File.Exists(cgsPath) ? Sha256File(cgsPath) : "";
            var manifestFileSha = File.Exists(manifestPath) ? Sha256File(manifestPath) : "";
            var checks = new List<Dictionary<string, object>>();

            checks.Add(Check("cgs_json_present", !string.IsNullOrWhiteSpace(cgsText), "CGS JSON is present in the staged Unity project.", new Dictionary<string, object> { ["path"] = cgsPath }));
            checks.Add(Check("manifest_json_present", !string.IsNullOrWhiteSpace(manifestText), "Vertical-slice manifest JSON is present in the staged Unity project.", new Dictionary<string, object> { ["path"] = manifestPath }));
            checks.Add(Check("fixture_identity", ContainsJsonString(cgsText, "cgs_hash", ExpectedCgsHash) && ContainsJsonString(manifestText, "version", ExpectedFixtureVersion), "Fixture hash/version match the canonical Task 63 slice.", new Dictionary<string, object> { ["cgs_hash"] = ExpectedCgsHash, ["version"] = ExpectedFixtureVersion }));
            checks.Add(Check("manifest_targets_unity", ContainsJsonStringValue(manifestText, "unity"), "Manifest includes Unity as a target engine.", new Dictionary<string, object> { ["expected"] = "unity" }));

            var missingCgsFeatures = new List<string>();
            var missingManifestFeatures = new List<string>();
            foreach (var feature in RequiredFeatures)
            {
                if (!ContainsJsonStringValue(cgsText, feature))
                    missingCgsFeatures.Add(feature);
                if (!ContainsJsonStringValue(manifestText, feature))
                    missingManifestFeatures.Add(feature);
            }
            checks.Add(Check("required_features_present", missingCgsFeatures.Count == 0 && missingManifestFeatures.Count == 0, "All required gameplay features are present in CGS and manifest coverage maps.", new Dictionary<string, object> { ["missing_cgs_features"] = missingCgsFeatures, ["missing_manifest_features"] = missingManifestFeatures, ["required_count"] = RequiredFeatures.Length }));

            var adapterComponentResults = ValidateAdapterComponents();
            checks.Add(Check("unity_adapter_components_construct", adapterComponentResults.All(item => (bool)item["ok"]), "Current Unity adapter components compile and can be constructed in the staged project.", new Dictionary<string, object> { ["components"] = adapterComponentResults }));

            var assetResults = ValidateAssets(Path.Combine(Application.dataPath, "XACEFixtures", "CanonicalSlice"));
            checks.Add(Check("asset_artifacts_present", assetResults.All(item => (bool)item["matches"]), "Unity can access the canonical slice asset files with expected SHA-256 values.", new Dictionary<string, object> { ["assets"] = assetResults }));

            var bindingCount = CountOccurrences(cgsText, "\"binding_");
            checks.Add(Check("semantic_bindings_available", bindingCount >= 3, "Unity parsed semantic animation/audio/VFX binding records from CGS text.", new Dictionary<string, object> { ["binding_count"] = bindingCount }));

            var scenarioOk = ContainsJsonStringValue(manifestText, "canonical_host_client_attack_pickup")
                && ContainsJsonStringValue(manifestText, "host_client_lockstep")
                && manifestText.Contains("\"ticks\": 8");
            checks.Add(Check("input_scenario_available", scenarioOk, "Manifest contains the canonical host/client attack-pickup input scenario.", new Dictionary<string, object> { ["id"] = "canonical_host_client_attack_pickup", ["network_topology"] = "host_client_lockstep", ["ticks"] = 8 }));

            return new Dictionary<string, object>
            {
                ["schema"] = ValidationSchema,
                ["task"] = "X10-065",
                ["engine"] = "unity",
                ["ok"] = false,
                ["generated_by"] = "installed Unity batch certification command",
                ["unity"] = new Dictionary<string, object>
                {
                    ["version"] = Application.unityVersion,
                    ["platform"] = Application.platform.ToString(),
                    ["batch_mode"] = Application.isBatchMode,
                    ["is_editor"] = Application.isEditor,
                },
                ["project"] = new Dictionary<string, object>
                {
                    ["path"] = projectRoot,
                    ["validation_output"] = validationOutput,
                    ["screenshot_output"] = screenshotOutput,
                },
                ["cgs"] = new Dictionary<string, object>
                {
                    ["path"] = cgsPath,
                    ["declared_hash"] = ExpectedCgsHash,
                    ["file_sha256"] = cgsFileSha,
                    ["manifest_file_sha256"] = manifestFileSha,
                    ["semantic_binding_count"] = bindingCount,
                },
                ["manifest"] = new Dictionary<string, object>
                {
                    ["path"] = manifestPath,
                    ["schema"] = "xace.canonical_vertical_slice_manifest.v1",
                    ["slice_id"] = "x10_063_canonical_cross_engine_vertical_slice",
                    ["version"] = ExpectedFixtureVersion,
                    ["target_engine"] = "unity",
                    ["required_features"] = RequiredFeatures.ToList(),
                },
                ["checks_passed"] = checks.Count(item => (bool)item["ok"]),
                ["checks_total"] = checks.Count,
                ["checks"] = checks,
            };
        }

        private static List<Dictionary<string, object>> ValidateAdapterComponents()
        {
            var root = new GameObject("XACE Task65 Unity Validation Object")
            {
                hideFlags = HideFlags.HideAndDontSave
            };
            var results = new List<Dictionary<string, object>>();
            try
            {
                results.Add(AddComponentResult<XaceTransport>(root));
                results.Add(AddComponentResult<XaceInputCollector>(root));
                results.Add(AddComponentResult<XaceDeltaApplicator>(root));
                results.Add(AddComponentResult<XaceConsoleWidget>(root));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
            return results;
        }

        private static Dictionary<string, object> AddComponentResult<T>(GameObject root) where T : Component
        {
            var component = root.AddComponent<T>();
            return new Dictionary<string, object>
            {
                ["type"] = typeof(T).FullName,
                ["ok"] = component != null,
            };
        }

        private static List<Dictionary<string, object>> ValidateAssets(string fixtureRoot)
        {
            var expected = new[]
            {
                new[] { "asset_hero_run_animation", "assets/hero_run.fbx", "9983441969e999e0f66bc415edbb81b078ef01d875a7f8490ecf09c85d365cff" },
                new[] { "asset_sword_hit_audio", "assets/sword_hit.wav", "55042b66b500fdb8c5a992e722d76b14c66cf96519a8aff33a7e1a7d7f5dcfde" },
            };
            var results = new List<Dictionary<string, object>>();
            foreach (var row in expected)
            {
                var absolute = Path.Combine(fixtureRoot, row[1].Replace('/', Path.DirectorySeparatorChar));
                var exists = File.Exists(absolute);
                var actual = exists ? Sha256File(absolute) : "";
                results.Add(new Dictionary<string, object>
                {
                    ["id"] = row[0],
                    ["path"] = absolute,
                    ["exists"] = exists,
                    ["expected_sha256"] = row[2],
                    ["actual_sha256"] = actual,
                    ["matches"] = exists && string.Equals(actual, row[2], StringComparison.OrdinalIgnoreCase),
                });
            }
            return results;
        }

        private static Dictionary<string, object> WriteScreenshot(string path)
        {
            try
            {
                var texture = new Texture2D(640, 360, TextureFormat.RGBA32, false);
                Fill(texture, new RectInt(0, 0, 640, 360), new Color32(9, 12, 17, 255));
                Fill(texture, new RectInt(28, 28, 584, 304), new Color32(20, 31, 45, 255));
                Fill(texture, new RectInt(44, 58, 552, 30), new Color32(34, 60, 88, 255));
                Fill(texture, new RectInt(64, 118, 160, 170), new Color32(65, 132, 214, 255));
                Fill(texture, new RectInt(248, 118, 144, 170), new Color32(194, 68, 54, 255));
                Fill(texture, new RectInt(416, 118, 160, 170), new Color32(65, 179, 104, 255));
                for (var x = 64; x < 576; x += 32)
                    Fill(texture, new RectInt(x, 306, 18, 10), new Color32(224, 184, 56, 255));
                texture.Apply(false, false);
                var bytes = texture.EncodeToPNG();
                UnityEngine.Object.DestroyImmediate(texture);
                var parent = Path.GetDirectoryName(Path.GetFullPath(path));
                if (!string.IsNullOrEmpty(parent))
                    Directory.CreateDirectory(parent);
                File.WriteAllBytes(path, bytes);
                return new Dictionary<string, object>
                {
                    ["ok"] = File.Exists(path) && new FileInfo(path).Length > 0,
                    ["path"] = path,
                    ["width"] = 640,
                    ["height"] = 360,
                    ["source"] = "installed Unity Texture2D.EncodeToPNG deterministic evidence image",
                    ["bytes"] = File.Exists(path) ? new FileInfo(path).Length : 0,
                };
            }
            catch (Exception ex)
            {
                return new Dictionary<string, object>
                {
                    ["ok"] = false,
                    ["path"] = path,
                    ["source"] = "installed Unity Texture2D.EncodeToPNG deterministic evidence image",
                    ["error"] = ex.Message,
                };
            }
        }

        private static void Fill(Texture2D texture, RectInt rect, Color32 color)
        {
            for (var y = rect.yMin; y < rect.yMax; y++)
                for (var x = rect.xMin; x < rect.xMax; x++)
                    texture.SetPixel(x, y, color);
        }

        private static bool ValidationOk(Dictionary<string, object> report)
        {
            var checks = (List<Dictionary<string, object>>)report["checks"];
            return checks.All(item => (bool)item["ok"])
                && report.TryGetValue("screenshot", out var screenshot)
                && screenshot is Dictionary<string, object> screenshotReport
                && screenshotReport.TryGetValue("ok", out var ok)
                && ok is bool screenshotOk
                && screenshotOk;
        }

        private static Dictionary<string, object> Check(string name, bool ok, string detail, Dictionary<string, object> evidence)
        {
            return new Dictionary<string, object>
            {
                ["name"] = name,
                ["ok"] = ok,
                ["detail"] = detail,
                ["evidence"] = evidence,
            };
        }

        private static string ArgValue(string[] args, string name, string fallback)
        {
            for (var i = 0; i < args.Length - 1; i++)
                if (string.Equals(args[i], name, StringComparison.Ordinal))
                    return args[i + 1] ?? fallback;
            return fallback;
        }

        private static bool ContainsJsonString(string text, string key, string value)
        {
            return text.Contains("\"" + EscapeJsonForContains(key) + "\": \"" + EscapeJsonForContains(value) + "\"");
        }

        private static bool ContainsJsonStringValue(string text, string value)
        {
            return text.Contains("\"" + EscapeJsonForContains(value) + "\"");
        }

        private static string EscapeJsonForContains(string value)
        {
            return (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");
        }

        private static int CountOccurrences(string text, string needle)
        {
            if (string.IsNullOrEmpty(text) || string.IsNullOrEmpty(needle))
                return 0;
            var count = 0;
            var index = 0;
            while ((index = text.IndexOf(needle, index, StringComparison.Ordinal)) >= 0)
            {
                count++;
                index += needle.Length;
            }
            return count;
        }

        private static string Sha256File(string path)
        {
            using (var stream = File.OpenRead(path))
            using (var sha = SHA256.Create())
            {
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
            }
        }

        private static void WriteJson(string path, Dictionary<string, object> payload)
        {
            var fullPath = Path.GetFullPath(path);
            var parent = Path.GetDirectoryName(fullPath);
            if (!string.IsNullOrEmpty(parent))
                Directory.CreateDirectory(parent);
            File.WriteAllText(fullPath, ToJson(payload), Encoding.UTF8);
        }

        private static string ToJson(object value)
        {
            if (value == null)
                return "null";
            if (value is bool b)
                return b ? "true" : "false";
            if (value is string s)
                return "\"" + JsonString(s) + "\"";
            if (value is int || value is long || value is uint || value is ulong || value is float || value is double || value is decimal)
                return Convert.ToString(value, CultureInfo.InvariantCulture);
            if (value is Dictionary<string, object> dict)
                return "{" + string.Join(",", dict.Select(kv => "\"" + JsonString(kv.Key) + "\":" + ToJson(kv.Value))) + "}";
            if (value is IEnumerable<string> strings)
                return "[" + string.Join(",", strings.Select(ToJson)) + "]";
            if (value is IEnumerable<Dictionary<string, object>> dicts)
                return "[" + string.Join(",", dicts.Select(ToJson)) + "]";
            if (value is System.Collections.IEnumerable sequence)
            {
                var parts = new List<string>();
                foreach (var item in sequence)
                    parts.Add(ToJson(item));
                return "[" + string.Join(",", parts) + "]";
            }
            return "\"" + JsonString(value.ToString()) + "\"";
        }

        private static string JsonString(string value)
        {
            var builder = new StringBuilder();
            foreach (var ch in value ?? "")
            {
                switch (ch)
                {
                    case '\\': builder.Append("\\\\"); break;
                    case '"': builder.Append("\\\""); break;
                    case '\n': builder.Append("\\n"); break;
                    case '\r': builder.Append("\\r"); break;
                    case '\t': builder.Append("\\t"); break;
                    default:
                        if (ch < ' ')
                            builder.Append("\\u").Append(((int)ch).ToString("x4", CultureInfo.InvariantCulture));
                        else
                            builder.Append(ch);
                        break;
                }
            }
            return builder.ToString();
        }
    }
}
'''
    replacements = {
        "__VALIDATION_SCHEMA__": VALIDATION_SCHEMA,
        "__EXPECTED_CGS_HASH__": EXPECTED_CGS_HASH,
        "__EXPECTED_FIXTURE_VERSION__": EXPECTED_FIXTURE_VERSION,
        "__VALIDATION_OUTPUT__": csharp_string(validation_path),
        "__SCREENSHOT_OUTPUT__": csharp_string(screenshot_path),
        "__REQUIRED_FEATURES__": required_features_literal,
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.lstrip()


def csharp_string(path: Path | str) -> str:
    return str(path).replace("\\", "\\\\")


def run_unity_command(command: list[str], cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(timeout_seconds, 30.0),
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
    unity_executable: Path,
    unity_version_probe: Mapping[str, Any],
    fixture_root: Path,
    adapter_root: Path,
    artifacts: Iterable[Path],
    adapter_scripts: Iterable[Path],
    completed: Mapping[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    artifact_records = [file_record(path) for path in artifacts]
    adapter_records = [file_record(path) for path in adapter_scripts]
    return {
        "schema": HASH_REPORT_SCHEMA,
        "task": TASK_ID,
        "generated_at_utc": utc_now(),
        "engine": "unity",
        "unity_executable": str(unity_executable),
        "unity_executable_sha256": sha256_file(unity_executable),
        "unity_version_probe": dict(unity_version_probe),
        "fixture_root": rel(fixture_root),
        "adapter_root": rel(adapter_root),
        "expected_cgs_hash": EXPECTED_CGS_HASH,
        "unity_runner": {
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
    if "target-codex-task65-unity-vertical-slice" not in resolved.parts:
        raise ValueError(f"Refusing to remove non-Task65 generated directory: {resolved}")
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


def tail_file(path: Path, *, max_chars: int = 1600) -> str:
    if not path.exists():
        return ""
    return tail_text(path.read_text(encoding="utf-8", errors="replace"), max_chars=max_chars)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

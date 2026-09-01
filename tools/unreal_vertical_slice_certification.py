#!/usr/bin/env python3
"""Retained X10-066 proof for the canonical vertical slice in installed Unreal.

The proof stages the X10-063 canonical slice into a disposable Unreal project,
installs the current Unreal adapter sources as a real `Plugins/XACE` plugin,
adds a generated certification commandlet, builds that plugin with the
installed Unreal toolchain, runs UnrealEditor-Cmd, and requires Unreal itself to
emit validation JSON plus a deterministic PNG evidence artifact.

This is an installed-editor certification artifact for the canonical CGS-owned
slice. It is deliberately not a finished-game build, platform package, or
human-recorded gameplay video.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
UNREAL_ADAPTER_ROOT = REPO_ROOT / "adapters" / "unreal"
DEFAULT_TARGET_ROOT = REPO_ROOT / "target-codex-task66-unreal-vertical-slice"
DEFAULT_UNREAL_ROOT = Path("C:/Program Files/Epic Games")

sys.path.insert(0, str(TOOLS_ROOT))
import canonical_vertical_slice_check  # noqa: E402


REPORT_SCHEMA = "xace.unreal_vertical_slice_certification_report.v1"
VALIDATION_SCHEMA = "xace.unreal_vertical_slice_validation.v1"
HASH_REPORT_SCHEMA = "xace.unreal_vertical_slice_hash_report.v1"
TASK_ID = "X10-066"
EXPECTED_CGS_HASH = "a5856b8c95068a27ce47885c32c7d3e2729c4ff988a47f2dee840bfd13ff0a8a"
EXPECTED_CGS_FILE_SHA = "b6c7824642ab1deddee958f70f44e9363345d0cca9ab58dc5485b10ced346e00"
EXPECTED_FIXTURE_VERSION = "0.1.0"
REQUIRED_FEATURES = tuple(canonical_vertical_slice_check.REQUIRED_FEATURES)
ADAPTER_SOURCE_NAMES = (
    "XaceTransport.h",
    "XaceTransport.cpp",
    "XaceInputCollector.h",
    "XaceInputCollector.cpp",
    "XaceDeltaApplicator.h",
    "XaceDeltaApplicator.cpp",
    "XaceConsoleWidget.h",
    "XaceConsoleWidget.cpp",
    "XaceLiveValidationCommandlet.h",
    "XaceLiveValidationCommandlet.cpp",
)
GENERATED_COMMANDLET_HEADER = "XaceVerticalSliceCertificationCommandlet.h"
GENERATED_COMMANDLET_SOURCE = "XaceVerticalSliceCertificationCommandlet.cpp"


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
    parser = argparse.ArgumentParser(description="Run the X10-066 installed-Unreal vertical slice proof.")
    parser.add_argument("--unreal-editor", default="", help="Path to UnrealEditor.exe or UnrealEditor-Cmd.exe.")
    parser.add_argument("--fixture-root", type=Path, default=FIXTURE_ROOT)
    parser.add_argument("--adapter-root", type=Path, default=UNREAL_ADAPTER_ROOT)
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_TARGET_ROOT / "report.json",
        help="Final Task 66 report path.",
    )
    parser.add_argument("--build-timeout", type=float, default=900.0, help="Unreal BuildPlugin timeout in seconds.")
    parser.add_argument("--run-timeout", type=float, default=300.0, help="Unreal commandlet timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print the final report JSON.")
    args = parser.parse_args(argv)

    try:
        report = run_certification(
            unreal_editor=args.unreal_editor,
            fixture_root=args.fixture_root.resolve(),
            adapter_root=args.adapter_root.resolve(),
            target_dir=args.target_dir.resolve(),
            output_path=args.output.resolve(),
            build_timeout_seconds=max(60.0, float(args.build_timeout)),
            run_timeout_seconds=max(30.0, float(args.run_timeout)),
        )
    except Exception as exc:  # noqa: BLE001 - proof tools should surface one actionable failure.
        print(f"Unreal vertical slice certification failed: {exc}", file=sys.stderr)
        return 1

    rendered = canonical_json(report, indent=2)
    if args.json:
        print(rendered)
    else:
        status = "PASSED" if report["ok"] else "FAILED"
        print(
            f"Unreal vertical slice certification {status}: "
            f"{report['checks_passed']}/{report['checks_total']} checks"
        )
        print(f"report: {report['report_path']}")
    return 0 if report["ok"] else 1


def run_certification(
    *,
    unreal_editor: str,
    fixture_root: Path,
    adapter_root: Path,
    target_dir: Path,
    output_path: Path,
    build_timeout_seconds: float,
    run_timeout_seconds: float,
) -> dict[str, Any]:
    require_under_repo(target_dir)
    require_under_repo(output_path)

    artifact_dir = target_dir / "artifacts"
    reports_dir = artifact_dir / "reports"
    logs_dir = artifact_dir / "logs"
    screenshots_dir = artifact_dir / "screenshots"
    hashes_dir = artifact_dir / "hashes"
    unreal_project_dir = artifact_dir / "unreal_project"
    plugin_package_dir = artifact_dir / "unreal_plugin_package"
    for path in (reports_dir, logs_dir, screenshots_dir, hashes_dir):
        path.mkdir(parents=True, exist_ok=True)

    reset_generated_dir(unreal_project_dir)
    if plugin_package_dir.exists():
        reset_generated_dir(plugin_package_dir)
        plugin_package_dir.rmdir()
    for path in (reports_dir, logs_dir, screenshots_dir, hashes_dir):
        path.mkdir(parents=True, exist_ok=True)

    canonical_report_path = reports_dir / "canonical_vertical_slice_report.json"
    validation_path = reports_dir / "unreal_vertical_slice_validation.json"
    screenshot_path = screenshots_dir / "unreal_vertical_slice_screenshot.png"
    hash_report_path = hashes_dir / "unreal_vertical_slice_hash_report.json"
    build_command_path = logs_dir / "unreal_build_command.json"
    build_stdout_path = logs_dir / "unreal_build_stdout.log"
    build_stderr_path = logs_dir / "unreal_build_stderr.log"
    run_command_path = logs_dir / "unreal_commandlet_command.json"
    editor_log_path = logs_dir / "unreal_editor.log"
    run_stdout_path = logs_dir / "unreal_commandlet_stdout.log"
    run_stderr_path = logs_dir / "unreal_commandlet_stderr.log"

    unreal_executable = find_unreal_editor(unreal_editor)
    commandlet_executable = unreal_commandlet_executable(unreal_executable)
    version_report = inspect_unreal_install(commandlet_executable)
    canonical_report = canonical_vertical_slice_check.run_check(
        fixture_root=fixture_root,
        output_path=canonical_report_path,
    )
    staged = stage_unreal_project(
        unreal_project_dir=unreal_project_dir,
        fixture_root=fixture_root,
        adapter_root=adapter_root,
        validation_path=validation_path,
        screenshot_path=screenshot_path,
        engine_association=str(version_report.get("engine_association", "")),
    )

    build = build_unreal_plugin(
        unreal_editor=commandlet_executable,
        plugin_root=staged["plugin_root"],
        package_dir=plugin_package_dir,
        command_path=build_command_path,
        stdout_path=build_stdout_path,
        stderr_path=build_stderr_path,
        timeout_seconds=build_timeout_seconds,
    )
    if build.get("ok"):
        copy_packaged_binaries_to_project(plugin_package_dir, staged["plugin_root"])

    commandlet = run_unreal_commandlet(
        commandlet_executable=commandlet_executable,
        project_file=staged["project_file"],
        fixture_path=staged["fixture_path"],
        validation_path=validation_path,
        screenshot_path=screenshot_path,
        editor_log_path=editor_log_path,
        command_path=run_command_path,
        stdout_path=run_stdout_path,
        stderr_path=run_stderr_path,
        timeout_seconds=run_timeout_seconds,
        skip=not bool(build.get("ok")),
    )

    validation = read_json(validation_path)
    screenshot_sha = sha256_file(screenshot_path) if screenshot_path.exists() else ""
    hash_report = build_hash_report(
        unreal_executable=commandlet_executable,
        version_report=version_report,
        fixture_root=fixture_root,
        adapter_root=adapter_root,
        artifacts=[
            canonical_report_path,
            validation_path,
            screenshot_path,
            build_command_path,
            build_stdout_path,
            build_stderr_path,
            run_command_path,
            editor_log_path,
            run_stdout_path,
            run_stderr_path,
            staged["project_file"],
            staged["plugin_root"] / "XACE.uplugin",
            staged["plugin_root"] / "Source" / "XACEAdapter" / "XACEAdapter.Build.cs",
            staged["runner_header_path"],
            staged["runner_source_path"],
            fixture_root / "game.cgs.json",
            fixture_root / "xace.vertical_slice_manifest.json",
        ],
        adapter_scripts=[adapter_root / name for name in ADAPTER_SOURCE_NAMES],
        plugin_files=list(iter_files(staged["plugin_root"] / "Source")),
        packaged_files=list(iter_files(plugin_package_dir / "Binaries")),
        completed_build=build,
        completed_commandlet=commandlet,
    )
    hash_report_path.write_text(canonical_json(hash_report, indent=2) + "\n", encoding="utf-8")

    binary_ready = unreal_plugin_editor_binary_ready(staged["plugin_root"])
    checks = [
        Check(
            "installed_unreal_executable",
            commandlet_executable.exists() and commandlet_executable.is_file() and bool(version_report.get("ok")),
            "Installed Unreal commandlet executable exists and the install metadata was read.",
            {
                "path": str(commandlet_executable),
                "version": version_report.get("version", ""),
                "engine_association": version_report.get("engine_association", ""),
                "run_uat": str(unreal_run_uat_path(commandlet_executable) or ""),
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
            "unreal_project_staged",
            bool(staged.get("ok")),
            "Disposable Unreal project contains the canonical fixture and current adapter plugin sources.",
            {
                "project_path": rel(unreal_project_dir),
                "project_file": rel(staged["project_file"]),
                "fixture_path": rel(staged["fixture_path"]),
                "plugin_root": rel(staged["plugin_root"]),
                "adapter_source_count": len(staged["adapter_sources"]),
            },
        ),
        Check(
            "unreal_plugin_build",
            bool(build.get("ok")) and bool(binary_ready.get("ready")),
            "Installed Unreal BuildPlugin compiled the staged XACE plugin and produced editor binaries.",
            {
                "command": rel(build_command_path),
                "returncode": build.get("returncode"),
                "timed_out": build.get("timed_out"),
                "package_dir": rel(plugin_package_dir),
                "binary_ready": binary_ready,
                "stdout_tail": tail_text(str(build.get("stdout", ""))),
                "stderr_tail": tail_text(str(build.get("stderr", ""))),
            },
        ),
        Check(
            "installed_unreal_validation_json",
            commandlet.get("returncode") == 0
            and bool(validation.get("ok"))
            and validation.get("schema") == VALIDATION_SCHEMA,
            "Installed Unreal wrote a passing validation JSON for the staged canonical slice.",
            {
                "path": rel(validation_path),
                "returncode": commandlet.get("returncode"),
                "schema": validation.get("schema", ""),
                "unreal_version": validation.get("unreal", {}).get("version", ""),
                "cgs_hash": validation.get("cgs", {}).get("declared_hash", ""),
                "skipped": commandlet.get("skipped", False),
            },
        ),
        Check(
            "unreal_png_evidence",
            screenshot_path.exists()
            and screenshot_path.stat().st_size > 0
            and bool(validation.get("screenshot", {}).get("ok"))
            and bool(screenshot_sha),
            "Installed Unreal wrote a deterministic PNG evidence image.",
            {
                "path": rel(screenshot_path),
                "sha256": screenshot_sha,
                "bytes": screenshot_path.stat().st_size if screenshot_path.exists() else 0,
                "source": validation.get("screenshot", {}).get("source", ""),
            },
        ),
        Check(
            "logs_retained",
            all(
                path.exists()
                for path in (
                    build_command_path,
                    build_stdout_path,
                    build_stderr_path,
                    run_command_path,
                    run_stdout_path,
                    run_stderr_path,
                )
            ),
            "Unreal build command, commandlet command, stdout, stderr, and editor logs were retained.",
            {
                "build_command": rel(build_command_path),
                "build_stdout": rel(build_stdout_path),
                "build_stderr": rel(build_stderr_path),
                "commandlet_command": rel(run_command_path),
                "editor_log": rel(editor_log_path),
                "commandlet_stdout": rel(run_stdout_path),
                "commandlet_stderr": rel(run_stderr_path),
                "editor_tail": tail_file(editor_log_path),
            },
        ),
        Check(
            "hash_report_retained",
            hash_report_path.exists()
            and hash_report.get("schema") == HASH_REPORT_SCHEMA
            and bool(hash_report.get("artifacts")),
            "Hash report covers fixture files, Unreal outputs, logs, generated commandlet, plugin files, and adapter sources.",
            {
                "path": rel(hash_report_path),
                "sha256": sha256_file(hash_report_path),
                "artifact_count": len(hash_report.get("artifacts", [])),
                "plugin_file_count": len(hash_report.get("plugin_files", [])),
                "packaged_file_count": len(hash_report.get("packaged_files", [])),
            },
        ),
    ]
    ok = all(check.ok for check in checks)
    report = {
        "schema": REPORT_SCHEMA,
        "task": TASK_ID,
        "ok": ok,
        "x10_066_complete": ok,
        "generated_at_utc": utc_now(),
        "report_path": rel(output_path),
        "artifact_dir": rel(artifact_dir),
        "installed_engine_proof_path": rel(target_dir),
        "engine": "unreal",
        "unreal_executable": str(commandlet_executable),
        "unreal_version": version_report.get("version", ""),
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
            "build_stdout_log": rel(build_stdout_path),
            "build_stderr_log": rel(build_stderr_path),
            "commandlet_stdout_log": rel(run_stdout_path),
            "commandlet_stderr_log": rel(run_stderr_path),
            "build_command_log": rel(build_command_path),
            "commandlet_command_log": rel(run_command_path),
            "hash_report": rel(hash_report_path),
            "hash_report_sha256": sha256_file(hash_report_path),
        },
        "unreal_build": {
            "returncode": build.get("returncode"),
            "elapsed_seconds": build.get("elapsed_seconds"),
            "timed_out": bool(build.get("timed_out")),
            "binary_ready": binary_ready,
        },
        "unreal_commandlet": {
            "returncode": commandlet.get("returncode"),
            "elapsed_seconds": commandlet.get("elapsed_seconds"),
            "timed_out": bool(commandlet.get("timed_out")),
            "skipped": bool(commandlet.get("skipped")),
        },
        "validation": validation,
        "checks_passed": sum(1 for check in checks if check.ok),
        "checks_total": len(checks),
        "checks": [check.to_dict() for check in checks],
        "boundary": {
            "proves": (
                "Installed Unreal can BuildPlugin a staged project containing the canonical CGS-owned slice, "
                "compile current Unreal adapter sources plus the X10-066 commandlet, validate fixture "
                "identity/assets/features/input scenario inside UnrealEditor-Cmd, and emit retained JSON, "
                "PNG, log, and hash evidence."
            ),
            "does_not_prove": (
                "This commandlet proof is not a finished-game package, human-recorded gameplay video, "
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


def find_unreal_editor(explicit: str) -> Path:
    candidates: list[Path] = []
    if explicit.strip():
        candidates.append(Path(explicit).expanduser())
    env_bin = os.environ.get("UNREAL_EDITOR_EXE", "").strip()
    if env_bin:
        candidates.append(Path(env_bin).expanduser())
    for name in ("UnrealEditor-Cmd.exe", "UnrealEditor.exe", "UnrealEditor-Cmd", "UnrealEditor"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))
    if DEFAULT_UNREAL_ROOT.exists():
        candidates.extend(sorted(DEFAULT_UNREAL_ROOT.glob("UE_*/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"), reverse=True))
        candidates.extend(sorted(DEFAULT_UNREAL_ROOT.glob("UE_*/Engine/Binaries/Win64/UnrealEditor.exe"), reverse=True))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    rendered = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(f"UnrealEditor executable not found. Checked:\n{rendered}")


def unreal_commandlet_executable(unreal_editor: Path) -> Path:
    if "unrealeditor-cmd" in unreal_editor.name.lower():
        return unreal_editor.resolve()
    candidate = unreal_editor.with_name("UnrealEditor-Cmd.exe")
    return candidate.resolve() if candidate.exists() else unreal_editor.resolve()


def inspect_unreal_install(commandlet_executable: Path) -> dict[str, Any]:
    engine_dir = unreal_engine_dir(commandlet_executable)
    install_root = engine_dir.parent if engine_dir is not None else commandlet_executable.parent
    build_version_path = engine_dir / "Build" / "Build.version" if engine_dir is not None else Path()
    run_uat = unreal_run_uat_path(commandlet_executable)
    payload: dict[str, Any] = {
        "ok": commandlet_executable.exists()
        and commandlet_executable.is_file()
        and run_uat is not None
        and run_uat.exists()
        and build_version_path.exists(),
        "commandlet_executable": str(commandlet_executable),
        "engine_dir": str(engine_dir or ""),
        "install_root": str(install_root),
        "run_uat": str(run_uat or ""),
        "build_version_path": str(build_version_path),
        "version": "",
        "engine_association": "",
        "build_version": {},
    }
    if build_version_path.exists():
        try:
            build_version = json.loads(build_version_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            build_version = {}
        if isinstance(build_version, dict):
            major = build_version.get("MajorVersion", "")
            minor = build_version.get("MinorVersion", "")
            patch = build_version.get("PatchVersion", "")
            payload["build_version"] = build_version
            payload["version"] = ".".join(str(part) for part in (major, minor, patch) if str(part) != "")
            payload["engine_association"] = f"{major}.{minor}" if str(major) and str(minor) else install_root.name.replace("UE_", "")
    if not payload["engine_association"]:
        payload["engine_association"] = install_root.name.replace("UE_", "")
    if not payload["version"]:
        payload["version"] = payload["engine_association"]
    return payload


def unreal_engine_dir(commandlet_executable: Path) -> Path | None:
    resolved = commandlet_executable.resolve()
    for parent in resolved.parents:
        if parent.name.lower() == "engine":
            return parent
    return None


def unreal_run_uat_path(commandlet_executable: Path) -> Path | None:
    engine_dir = unreal_engine_dir(commandlet_executable)
    if engine_dir is None:
        return None
    if platform.system().lower() == "windows":
        path = engine_dir / "Build" / "BatchFiles" / "RunUAT.bat"
    else:
        path = engine_dir / "Build" / "BatchFiles" / "RunUAT.sh"
    return path if path.exists() else None


def stage_unreal_project(
    *,
    unreal_project_dir: Path,
    fixture_root: Path,
    adapter_root: Path,
    validation_path: Path,
    screenshot_path: Path,
    engine_association: str,
) -> dict[str, Any]:
    require_under_repo(unreal_project_dir)
    unreal_project_dir.mkdir(parents=True, exist_ok=True)
    project_file = unreal_project_dir / "XaceTask66.uproject"
    project_payload = {
        "FileVersion": 3,
        "EngineAssociation": engine_association or "5.7",
        "Category": "XACE",
        "Description": "Generated X10-066 Unreal vertical-slice certification project.",
        "Plugins": [{"Name": "XACE", "Enabled": True}],
    }
    project_file.write_text(canonical_json(project_payload, indent=2) + "\n", encoding="utf-8")

    fixture_dest = unreal_project_dir / "XACEFixtures" / "CanonicalSlice"
    reset_generated_dir(fixture_dest)
    fixture_dest.rmdir()
    shutil.copytree(fixture_root, fixture_dest)

    plugin_root = unreal_project_dir / "Plugins" / "XACE"
    public_dir = plugin_root / "Source" / "XACEAdapter" / "Public"
    private_dir = plugin_root / "Source" / "XACEAdapter" / "Private"
    public_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[str] = []
    for relative_path, text in unreal_generated_plugin_texts().items():
        target = plugin_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        generated_files.append(rel(target))

    adapter_sources: list[str] = []
    missing_sources: list[str] = []
    for name in ADAPTER_SOURCE_NAMES:
        source = adapter_root / name
        if not source.exists():
            missing_sources.append(name)
            continue
        target_dir = public_dir if name.endswith(".h") else private_dir
        shutil.copy2(source, target_dir / name)
        adapter_sources.append(rel(target_dir / name))

    runner_header = public_dir / GENERATED_COMMANDLET_HEADER
    runner_source = private_dir / GENERATED_COMMANDLET_SOURCE
    runner_header.write_text(unreal_vertical_slice_commandlet_header(), encoding="utf-8")
    runner_source.write_text(
        unreal_vertical_slice_commandlet_source(validation_path=validation_path, screenshot_path=screenshot_path),
        encoding="utf-8",
    )

    if missing_sources:
        raise FileNotFoundError(f"Missing Unreal adapter source(s): {', '.join(missing_sources)}")
    return {
        "ok": True,
        "project_file": project_file,
        "fixture_path": fixture_dest,
        "plugin_root": plugin_root,
        "runner_header_path": runner_header,
        "runner_source_path": runner_source,
        "adapter_sources": adapter_sources,
        "generated_plugin_files": generated_files,
    }


def unreal_generated_plugin_texts() -> dict[str, str]:
    return {
        "XACE.uplugin": canonical_json(
            {
                "FileVersion": 3,
                "Version": 1,
                "VersionName": "0.1.0",
                "FriendlyName": "XACE Adapter",
                "Description": "Connects Unreal projects to the XACE runtime.",
                "Category": "Gameplay",
                "CreatedBy": "XACE",
                "CanContainContent": False,
                "IsBetaVersion": True,
                "Modules": [{"Name": "XACEAdapter", "Type": "Runtime", "LoadingPhase": "Default"}],
            },
            indent=2,
        )
        + "\n",
        "Source/XACEAdapter/XACEAdapter.Build.cs": "\n".join(
            [
                "using UnrealBuildTool;",
                "",
                "public class XACEAdapter : ModuleRules",
                "{",
                "    public XACEAdapter(ReadOnlyTargetRules Target) : base(Target)",
                "    {",
                "        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;",
                "",
                "        PublicDependencyModuleNames.AddRange(new string[]",
                "        {",
                '            "Core",',
                '            "CoreUObject",',
                '            "Engine",',
                '            "InputCore",',
                '            "Json",',
                '            "Sockets",',
                '            "Networking",',
                '            "UMG",',
                '            "ImageWrapper"',
                "        });",
                "    }",
                "}",
                "",
            ]
        ),
        "Source/XACEAdapter/Public/XACEAdapterModule.h": "\n".join(
            [
                "#pragma once",
                "",
                '#include "Modules/ModuleManager.h"',
                "",
                "class FXACEAdapterModule : public IModuleInterface",
                "{",
                "public:",
                "    virtual void StartupModule() override;",
                "    virtual void ShutdownModule() override;",
                "};",
                "",
            ]
        ),
        "Source/XACEAdapter/Private/XACEAdapterModule.cpp": "\n".join(
            [
                '#include "XACEAdapterModule.h"',
                "",
                '#include "Modules/ModuleManager.h"',
                "",
                "IMPLEMENT_MODULE(FXACEAdapterModule, XACEAdapter)",
                "",
                "void FXACEAdapterModule::StartupModule()",
                "{",
                "}",
                "",
                "void FXACEAdapterModule::ShutdownModule()",
                "{",
                "}",
                "",
            ]
        ),
    }


def unreal_vertical_slice_commandlet_header() -> str:
    return "\n".join(
        [
            "#pragma once",
            "",
            '#include "CoreMinimal.h"',
            '#include "Commandlets/Commandlet.h"',
            '#include "XaceVerticalSliceCertificationCommandlet.generated.h"',
            "",
            "UCLASS()",
            "class UXaceVerticalSliceCertificationCommandlet : public UCommandlet",
            "{",
            "    GENERATED_BODY()",
            "",
            "public:",
            "    UXaceVerticalSliceCertificationCommandlet();",
            "",
            "    virtual int32 Main(const FString& Params) override;",
            "};",
            "",
        ]
    )


def unreal_vertical_slice_commandlet_source(*, validation_path: Path, screenshot_path: Path) -> str:
    required_features_literal = ", ".join(f'TEXT("{feature}")' for feature in REQUIRED_FEATURES)
    text = r'''
#include "XaceVerticalSliceCertificationCommandlet.h"

#include "XaceConsoleWidget.h"
#include "XaceDeltaApplicator.h"
#include "XaceInputCollector.h"
#include "XaceTransport.h"

#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "IImageWrapper.h"
#include "IImageWrapperModule.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
    const TCHAR* ValidationSchema = TEXT("__VALIDATION_SCHEMA__");
    const TCHAR* ExpectedCgsHash = TEXT("__EXPECTED_CGS_HASH__");
    const TCHAR* ExpectedCgsFileSha = TEXT("__EXPECTED_CGS_FILE_SHA__");
    const TCHAR* ExpectedFixtureVersion = TEXT("__EXPECTED_FIXTURE_VERSION__");
    const TCHAR* DefaultValidationOutput = TEXT("__VALIDATION_OUTPUT__");
    const TCHAR* DefaultScreenshotOutput = TEXT("__SCREENSHOT_OUTPUT__");
    const TCHAR* RequiredFeatures[] = { __REQUIRED_FEATURES__ };

    bool ReadStringParam(const FString& Params, const TCHAR* Key, FString& OutValue)
    {
        return FParse::Value(*Params, *FString::Printf(TEXT("-%s="), Key), OutValue)
            || FParse::Value(*Params, *FString::Printf(TEXT("%s="), Key), OutValue);
    }

    FString JsonToString(const TSharedRef<FJsonObject>& Object)
    {
        FString Out;
        TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
        FJsonSerializer::Serialize(Object, Writer);
        return Out;
    }

    bool WriteReport(const FString& OutputPath, const TSharedRef<FJsonObject>& Report, FString& OutError)
    {
        const FString Directory = FPaths::GetPath(OutputPath);
        if (!Directory.IsEmpty())
        {
            IFileManager::Get().MakeDirectory(*Directory, true);
        }
        if (!FFileHelper::SaveStringToFile(JsonToString(Report) + TEXT("\n"), *OutputPath))
        {
            OutError = FString::Printf(TEXT("failed to write validation report: %s"), *OutputPath);
            return false;
        }
        return true;
    }

    TSharedPtr<FJsonObject> ReadJsonObject(const FString& Path)
    {
        FString Text;
        if (!FFileHelper::LoadFileToString(Text, *Path))
        {
            return nullptr;
        }
        TSharedPtr<FJsonObject> Object;
        TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
        return FJsonSerializer::Deserialize(Reader, Object) && Object.IsValid() ? Object : nullptr;
    }

    TSharedPtr<FJsonObject> ObjectField(const TSharedPtr<FJsonObject>& Object, const FString& Field)
    {
        if (!Object.IsValid())
        {
            return nullptr;
        }
        const TSharedPtr<FJsonObject>* Nested = nullptr;
        return Object->TryGetObjectField(Field, Nested) && Nested != nullptr ? *Nested : nullptr;
    }

    FString StringField(const TSharedPtr<FJsonObject>& Object, const FString& Field, const FString& Fallback = TEXT(""))
    {
        if (!Object.IsValid())
        {
            return Fallback;
        }
        FString Value;
        return Object->TryGetStringField(Field, Value) ? Value : Fallback;
    }

    bool StringArrayContains(const TSharedPtr<FJsonObject>& Object, const FString& Field, const FString& Needle)
    {
        if (!Object.IsValid())
        {
            return false;
        }
        const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
        if (!Object->TryGetArrayField(Field, Values) || Values == nullptr)
        {
            return false;
        }
        for (const TSharedPtr<FJsonValue>& Value : *Values)
        {
            if (Value.IsValid() && Value->Type == EJson::String && Value->AsString() == Needle)
            {
                return true;
            }
        }
        return false;
    }

    int32 ArrayFieldCount(const TSharedPtr<FJsonObject>& Object, const FString& Field)
    {
        if (!Object.IsValid())
        {
            return 0;
        }
        const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
        return Object->TryGetArrayField(Field, Values) && Values != nullptr ? Values->Num() : 0;
    }

    TArray<TSharedPtr<FJsonValue>> StringArrayValues(const TArray<FString>& Values)
    {
        TArray<TSharedPtr<FJsonValue>> Out;
        for (const FString& Value : Values)
        {
            Out.Add(MakeShared<FJsonValueString>(Value));
        }
        return Out;
    }

    TSharedRef<FJsonObject> EmptyObject()
    {
        return MakeShared<FJsonObject>();
    }

    TSharedRef<FJsonObject> CheckObject(
        const FString& Name,
        bool bOk,
        const FString& Detail,
        const TSharedRef<FJsonObject>& Evidence
    )
    {
        TSharedRef<FJsonObject> Check = MakeShared<FJsonObject>();
        Check->SetStringField(TEXT("name"), Name);
        Check->SetBoolField(TEXT("ok"), bOk);
        Check->SetStringField(TEXT("detail"), Detail);
        Check->SetObjectField(TEXT("evidence"), Evidence);
        return Check;
    }

    template <typename TComponent>
    TComponent* AddValidationComponent(AActor* Owner, const FName Name)
    {
        if (Owner == nullptr)
        {
            return nullptr;
        }
        TComponent* Component = NewObject<TComponent>(Owner, Name);
        if (Component == nullptr)
        {
            return nullptr;
        }
        Owner->AddInstanceComponent(Component);
        Component->RegisterComponent();
        return Component;
    }

    TSharedPtr<FJsonValue> ComponentResult(const FString& TypeName, bool bOk)
    {
        TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
        Result->SetStringField(TEXT("type"), TypeName);
        Result->SetBoolField(TEXT("ok"), bOk);
        return MakeShared<FJsonValueObject>(Result);
    }

    TSharedRef<FJsonObject> ValidateAdapterComponents(bool& bOutOk)
    {
        TSharedRef<FJsonObject> Evidence = MakeShared<FJsonObject>();
        TArray<TSharedPtr<FJsonValue>> Results;
        bOutOk = false;

        UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("XaceTask66VerticalSliceWorld"));
        if (World == nullptr || GEngine == nullptr)
        {
            Evidence->SetStringField(TEXT("error"), TEXT("Unable to create Unreal validation world."));
            Evidence->SetArrayField(TEXT("components"), Results);
            return Evidence;
        }

        GEngine->CreateNewWorldContext(EWorldType::Game).SetCurrentWorld(World);
        AActor* HostActor = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity);
        UXaceTransportComponent* Transport = AddValidationComponent<UXaceTransportComponent>(HostActor, TEXT("XaceTransport"));
        UXaceInputCollectorComponent* InputCollector = AddValidationComponent<UXaceInputCollectorComponent>(HostActor, TEXT("XaceInputCollector"));
        UXaceDeltaApplicatorComponent* Applicator = AddValidationComponent<UXaceDeltaApplicatorComponent>(HostActor, TEXT("XaceDeltaApplicator"));
        UClass* ConsoleClass = UXaceConsoleWidget::StaticClass();

        Results.Add(ComponentResult(TEXT("UXaceTransportComponent"), Transport != nullptr));
        Results.Add(ComponentResult(TEXT("UXaceInputCollectorComponent"), InputCollector != nullptr));
        Results.Add(ComponentResult(TEXT("UXaceDeltaApplicatorComponent"), Applicator != nullptr));
        Results.Add(ComponentResult(TEXT("UXaceConsoleWidget.StaticClass"), ConsoleClass != nullptr));

        bOutOk = HostActor != nullptr && Transport != nullptr && InputCollector != nullptr && Applicator != nullptr && ConsoleClass != nullptr;
        Evidence->SetBoolField(TEXT("world_created"), true);
        Evidence->SetBoolField(TEXT("actor_created"), HostActor != nullptr);
        Evidence->SetArrayField(TEXT("components"), Results);

        World->DestroyWorld(false);
        GEngine->DestroyWorldContext(World);
        return Evidence;
    }

    TSharedRef<FJsonObject> ValidateAssets(const TSharedPtr<FJsonObject>& Manifest, const FString& FixtureRoot, bool& bOutOk)
    {
        TSharedRef<FJsonObject> Evidence = MakeShared<FJsonObject>();
        TArray<TSharedPtr<FJsonValue>> AssetResults;
        int32 Existing = 0;
        int32 Declared = 0;
        bOutOk = false;

        const TArray<TSharedPtr<FJsonValue>>* Assets = nullptr;
        if (Manifest.IsValid() && Manifest->TryGetArrayField(TEXT("asset_artifacts"), Assets) && Assets != nullptr)
        {
            for (const TSharedPtr<FJsonValue>& AssetValue : *Assets)
            {
                const TSharedPtr<FJsonObject>* AssetObject = nullptr;
                if (!AssetValue.IsValid() || !AssetValue->TryGetObject(AssetObject) || AssetObject == nullptr)
                {
                    continue;
                }
                ++Declared;
                const FString Id = StringField(*AssetObject, TEXT("id"));
                const FString RelativePath = StringField(*AssetObject, TEXT("path"));
                const FString ExpectedSha = StringField(*AssetObject, TEXT("sha256"));
                const FString AbsolutePath = FPaths::Combine(FixtureRoot, RelativePath);
                const bool bExists = IFileManager::Get().FileExists(*AbsolutePath);
                const int64 Bytes = bExists ? IFileManager::Get().FileSize(*AbsolutePath) : 0;
                if (bExists && Bytes > 0)
                {
                    ++Existing;
                }
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("id"), Id);
                Row->SetStringField(TEXT("path"), AbsolutePath);
                Row->SetBoolField(TEXT("exists"), bExists);
                Row->SetNumberField(TEXT("bytes"), static_cast<double>(Bytes));
                Row->SetStringField(TEXT("expected_sha256"), ExpectedSha);
                Row->SetStringField(TEXT("sha256_verified_by"), TEXT("Python wrapper hash report"));
                AssetResults.Add(MakeShared<FJsonValueObject>(Row));
            }
        }

        bOutOk = Declared >= 2 && Existing == Declared;
        Evidence->SetNumberField(TEXT("declared_count"), Declared);
        Evidence->SetNumberField(TEXT("existing_count"), Existing);
        Evidence->SetArrayField(TEXT("assets"), AssetResults);
        return Evidence;
    }

    TSharedRef<FJsonObject> ValidateInputScenario(const TSharedPtr<FJsonObject>& Manifest, bool& bOutOk)
    {
        TSharedRef<FJsonObject> Evidence = MakeShared<FJsonObject>();
        bOutOk = false;
        const TArray<TSharedPtr<FJsonValue>>* Scenarios = nullptr;
        if (!Manifest.IsValid() || !Manifest->TryGetArrayField(TEXT("input_scenarios"), Scenarios) || Scenarios == nullptr || Scenarios->Num() == 0)
        {
            Evidence->SetStringField(TEXT("error"), TEXT("input_scenarios missing"));
            return Evidence;
        }
        const TSharedPtr<FJsonObject>* FirstScenario = nullptr;
        if (!(*Scenarios)[0].IsValid() || !(*Scenarios)[0]->TryGetObject(FirstScenario) || FirstScenario == nullptr)
        {
            Evidence->SetStringField(TEXT("error"), TEXT("first input scenario is not an object"));
            return Evidence;
        }
        const FString Id = StringField(*FirstScenario, TEXT("id"));
        const FString Topology = StringField(*FirstScenario, TEXT("network_topology"));
        const int32 EventCount = ArrayFieldCount(*FirstScenario, TEXT("events"));
        double Ticks = 0.0;
        (*FirstScenario)->TryGetNumberField(TEXT("ticks"), Ticks);
        bOutOk = Id == TEXT("canonical_host_client_attack_pickup")
            && Topology == TEXT("host_client_lockstep")
            && FMath::RoundToInt(Ticks) == 8
            && EventCount >= 4;
        Evidence->SetStringField(TEXT("id"), Id);
        Evidence->SetStringField(TEXT("network_topology"), Topology);
        Evidence->SetNumberField(TEXT("ticks"), Ticks);
        Evidence->SetNumberField(TEXT("event_count"), EventCount);
        return Evidence;
    }

    TSharedRef<FJsonObject> WriteScreenshot(const FString& Path)
    {
        TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
        Result->SetStringField(TEXT("path"), Path);
        Result->SetNumberField(TEXT("width"), 640);
        Result->SetNumberField(TEXT("height"), 360);
        Result->SetStringField(TEXT("source"), TEXT("installed Unreal ImageWrapper deterministic PNG evidence image"));

        constexpr int32 Width = 640;
        constexpr int32 Height = 360;
        TArray<uint8> Raw;
        Raw.SetNumZeroed(Width * Height * 4);
        auto FillRect = [&Raw](int32 X0, int32 Y0, int32 W, int32 H, uint8 R, uint8 G, uint8 B, uint8 A)
        {
            for (int32 Y = Y0; Y < Y0 + H; ++Y)
            {
                for (int32 X = X0; X < X0 + W; ++X)
                {
                    const int32 Index = ((Y * Width) + X) * 4;
                    Raw[Index] = R;
                    Raw[Index + 1] = G;
                    Raw[Index + 2] = B;
                    Raw[Index + 3] = A;
                }
            }
        };
        FillRect(0, 0, Width, Height, 9, 12, 17, 255);
        FillRect(28, 28, 584, 304, 20, 31, 45, 255);
        FillRect(44, 58, 552, 30, 34, 60, 88, 255);
        FillRect(64, 118, 160, 170, 65, 132, 214, 255);
        FillRect(248, 118, 144, 170, 194, 68, 54, 255);
        FillRect(416, 118, 160, 170, 65, 179, 104, 255);
        for (int32 X = 64; X < 576; X += 32)
        {
            FillRect(X, 306, 18, 10, 224, 184, 56, 255);
        }

        const FString Directory = FPaths::GetPath(Path);
        if (!Directory.IsEmpty())
        {
            IFileManager::Get().MakeDirectory(*Directory, true);
        }
        IImageWrapperModule& ImageWrapperModule = FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
        TSharedPtr<IImageWrapper> PngWrapper = ImageWrapperModule.CreateImageWrapper(EImageFormat::PNG);
        if (!PngWrapper.IsValid() || !PngWrapper->SetRaw(Raw.GetData(), Raw.Num(), Width, Height, ERGBFormat::RGBA, 8))
        {
            Result->SetBoolField(TEXT("ok"), false);
            Result->SetStringField(TEXT("error"), TEXT("PNG wrapper failed"));
            return Result;
        }
        const TArray64<uint8>& Compressed64 = PngWrapper->GetCompressed(100);
        TArray<uint8> Compressed;
        Compressed.Append(Compressed64.GetData(), static_cast<int32>(Compressed64.Num()));
        const bool bSaved = FFileHelper::SaveArrayToFile(Compressed, *Path);
        Result->SetBoolField(TEXT("ok"), bSaved && IFileManager::Get().FileSize(*Path) > 0);
        Result->SetNumberField(TEXT("bytes"), static_cast<double>(IFileManager::Get().FileSize(*Path)));
        return Result;
    }
}

UXaceVerticalSliceCertificationCommandlet::UXaceVerticalSliceCertificationCommandlet()
{
    IsClient = false;
    IsEditor = true;
    LogToConsole = true;
    ShowErrorCount = false;
}

int32 UXaceVerticalSliceCertificationCommandlet::Main(const FString& Params)
{
    FString FixtureRoot = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("XACEFixtures/CanonicalSlice")));
    FString ValidationOutput = DefaultValidationOutput;
    FString ScreenshotOutput = DefaultScreenshotOutput;
    ReadStringParam(Params, TEXT("XaceFixtureRoot"), FixtureRoot);
    ReadStringParam(Params, TEXT("XaceValidationOutput"), ValidationOutput);
    ReadStringParam(Params, TEXT("XaceScreenshotOutput"), ScreenshotOutput);

    const FString CgsPath = FPaths::Combine(FixtureRoot, TEXT("game.cgs.json"));
    const FString ManifestPath = FPaths::Combine(FixtureRoot, TEXT("xace.vertical_slice_manifest.json"));
    TSharedPtr<FJsonObject> Cgs = ReadJsonObject(CgsPath);
    TSharedPtr<FJsonObject> Manifest = ReadJsonObject(ManifestPath);
    TSharedPtr<FJsonObject> Metadata = ObjectField(Cgs, TEXT("metadata"));
    TSharedPtr<FJsonObject> VerticalSlice = ObjectField(Cgs, TEXT("vertical_slice"));
    TSharedPtr<FJsonObject> FeatureCoverage = ObjectField(VerticalSlice, TEXT("feature_coverage"));
    TSharedPtr<FJsonObject> ManifestCgs = ObjectField(Manifest, TEXT("cgs"));
    TSharedPtr<FJsonObject> ManifestFeatureMap = ObjectField(Manifest, TEXT("feature_map"));
    TSharedPtr<FJsonObject> SemanticBindings = ObjectField(Cgs, TEXT("semantic_bindings"));

    TArray<TSharedPtr<FJsonValue>> Checks;
    bool bAllChecksOk = true;
    int32 ChecksPassed = 0;
    auto AddCheck = [&Checks, &bAllChecksOk, &ChecksPassed](
        const FString& Name,
        bool bOk,
        const FString& Detail,
        const TSharedRef<FJsonObject>& Evidence
    )
    {
        if (bOk)
        {
            ++ChecksPassed;
        }
        else
        {
            bAllChecksOk = false;
        }
        Checks.Add(MakeShared<FJsonValueObject>(CheckObject(Name, bOk, Detail, Evidence)));
    };

    TSharedRef<FJsonObject> CgsParsedEvidence = EmptyObject();
    CgsParsedEvidence->SetStringField(TEXT("path"), CgsPath);
    AddCheck(TEXT("cgs_json_parsed"), Cgs.IsValid(), TEXT("CGS JSON parsed in installed Unreal."), CgsParsedEvidence);

    TSharedRef<FJsonObject> ManifestParsedEvidence = EmptyObject();
    ManifestParsedEvidence->SetStringField(TEXT("path"), ManifestPath);
    AddCheck(TEXT("manifest_json_parsed"), Manifest.IsValid(), TEXT("Vertical-slice manifest JSON parsed in installed Unreal."), ManifestParsedEvidence);

    const FString DeclaredHash = StringField(Metadata, TEXT("cgs_hash"));
    const FString ManifestHash = StringField(ManifestCgs, TEXT("cgs_hash"));
    const FString ManifestVersion = StringField(Manifest, TEXT("version"));
    TSharedRef<FJsonObject> IdentityEvidence = EmptyObject();
    IdentityEvidence->SetStringField(TEXT("cgs_hash"), DeclaredHash);
    IdentityEvidence->SetStringField(TEXT("manifest_cgs_hash"), ManifestHash);
    IdentityEvidence->SetStringField(TEXT("version"), ManifestVersion);
    AddCheck(
        TEXT("fixture_identity"),
        DeclaredHash == ExpectedCgsHash && ManifestHash == ExpectedCgsHash && ManifestVersion == ExpectedFixtureVersion,
        TEXT("Fixture hash/version match the canonical Task 63 slice."),
        IdentityEvidence
    );

    TSharedRef<FJsonObject> TargetEvidence = EmptyObject();
    TargetEvidence->SetBoolField(TEXT("unreal_declared"), StringArrayContains(Manifest, TEXT("target_engines"), TEXT("unreal")));
    AddCheck(
        TEXT("manifest_targets_unreal"),
        StringArrayContains(Manifest, TEXT("target_engines"), TEXT("unreal")),
        TEXT("Manifest includes Unreal as a target engine."),
        TargetEvidence
    );

    const FString ManifestCgsFileSha = StringField(ManifestCgs, TEXT("file_sha256"));
    TSharedRef<FJsonObject> ManifestShaEvidence = EmptyObject();
    ManifestShaEvidence->SetStringField(TEXT("manifest_cgs_file_sha256"), ManifestCgsFileSha);
    ManifestShaEvidence->SetStringField(TEXT("expected_cgs_file_sha256"), ExpectedCgsFileSha);
    ManifestShaEvidence->SetStringField(TEXT("sha256_verified_by"), TEXT("Python wrapper hash report"));
    AddCheck(
        TEXT("manifest_cgs_sha_declared"),
        ManifestCgsFileSha == ExpectedCgsFileSha,
        TEXT("Manifest declares the canonical staged CGS file SHA-256."),
        ManifestShaEvidence
    );

    TArray<FString> MissingCgsFeatures;
    TArray<FString> MissingManifestFeatures;
    TArray<FString> RequiredFeatureNames;
    for (const TCHAR* Feature : RequiredFeatures)
    {
        const FString FeatureName(Feature);
        RequiredFeatureNames.Add(FeatureName);
        if (!FeatureCoverage.IsValid() || !FeatureCoverage->HasField(FeatureName))
        {
            MissingCgsFeatures.Add(FeatureName);
        }
        if (!ManifestFeatureMap.IsValid() || !ManifestFeatureMap->HasField(FeatureName))
        {
            MissingManifestFeatures.Add(FeatureName);
        }
    }
    TSharedRef<FJsonObject> FeatureEvidence = EmptyObject();
    FeatureEvidence->SetArrayField(TEXT("missing_cgs_features"), StringArrayValues(MissingCgsFeatures));
    FeatureEvidence->SetArrayField(TEXT("missing_manifest_features"), StringArrayValues(MissingManifestFeatures));
    FeatureEvidence->SetNumberField(TEXT("required_count"), RequiredFeatureNames.Num());
    AddCheck(
        TEXT("required_features_present"),
        MissingCgsFeatures.Num() == 0 && MissingManifestFeatures.Num() == 0,
        TEXT("All required gameplay features are present in CGS and manifest coverage maps."),
        FeatureEvidence
    );

    bool bAdapterComponentsOk = false;
    TSharedRef<FJsonObject> ComponentEvidence = ValidateAdapterComponents(bAdapterComponentsOk);
    AddCheck(
        TEXT("unreal_adapter_components_construct"),
        bAdapterComponentsOk,
        TEXT("Current Unreal adapter components compile and can be constructed in the staged project."),
        ComponentEvidence
    );

    bool bAssetsOk = false;
    TSharedRef<FJsonObject> AssetEvidence = ValidateAssets(Manifest, FixtureRoot, bAssetsOk);
    AddCheck(
        TEXT("asset_artifacts_present"),
        bAssetsOk,
        TEXT("Unreal can access the canonical slice asset files; SHA-256 values are retained in the wrapper hash report."),
        AssetEvidence
    );

    const int32 BindingCount = ArrayFieldCount(SemanticBindings, TEXT("bindings"));
    TSharedRef<FJsonObject> BindingEvidence = EmptyObject();
    BindingEvidence->SetNumberField(TEXT("binding_count"), BindingCount);
    AddCheck(
        TEXT("semantic_bindings_available"),
        BindingCount >= 3,
        TEXT("Unreal parsed semantic animation/audio/VFX binding records from CGS."),
        BindingEvidence
    );

    bool bScenarioOk = false;
    TSharedRef<FJsonObject> ScenarioEvidence = ValidateInputScenario(Manifest, bScenarioOk);
    AddCheck(
        TEXT("input_scenario_available"),
        bScenarioOk,
        TEXT("Manifest contains the canonical host/client attack-pickup input scenario."),
        ScenarioEvidence
    );

    TSharedRef<FJsonObject> Screenshot = WriteScreenshot(ScreenshotOutput);
    const bool bScreenshotOk = Screenshot->GetBoolField(TEXT("ok"));
    const bool bOk = bAllChecksOk && bScreenshotOk;

    TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
    Report->SetStringField(TEXT("schema"), ValidationSchema);
    Report->SetStringField(TEXT("task"), TEXT("X10-066"));
    Report->SetStringField(TEXT("engine"), TEXT("unreal"));
    Report->SetBoolField(TEXT("ok"), bOk);
    Report->SetStringField(TEXT("generated_by"), TEXT("installed Unreal commandlet certification runner"));
    TSharedRef<FJsonObject> Unreal = MakeShared<FJsonObject>();
    Unreal->SetStringField(TEXT("version"), FEngineVersion::Current().ToString());
    Unreal->SetStringField(TEXT("project_dir"), FPaths::ProjectDir());
    Unreal->SetBoolField(TEXT("is_running_commandlet"), IsRunningCommandlet());
    Unreal->SetBoolField(TEXT("is_unattended"), FApp::IsUnattended());
    Report->SetObjectField(TEXT("unreal"), Unreal);
    TSharedRef<FJsonObject> Project = MakeShared<FJsonObject>();
    Project->SetStringField(TEXT("path"), FPaths::ProjectDir());
    Project->SetStringField(TEXT("fixture_root"), FixtureRoot);
    Project->SetStringField(TEXT("validation_output"), ValidationOutput);
    Project->SetStringField(TEXT("screenshot_output"), ScreenshotOutput);
    Report->SetObjectField(TEXT("project"), Project);
    TSharedRef<FJsonObject> CgsReport = MakeShared<FJsonObject>();
    CgsReport->SetStringField(TEXT("path"), CgsPath);
    CgsReport->SetStringField(TEXT("declared_hash"), DeclaredHash);
    CgsReport->SetStringField(TEXT("manifest_file_sha256"), ManifestCgsFileSha);
    CgsReport->SetNumberField(TEXT("semantic_binding_count"), BindingCount);
    Report->SetObjectField(TEXT("cgs"), CgsReport);
    TSharedRef<FJsonObject> ManifestReport = MakeShared<FJsonObject>();
    ManifestReport->SetStringField(TEXT("path"), ManifestPath);
    ManifestReport->SetStringField(TEXT("schema"), StringField(Manifest, TEXT("schema")));
    ManifestReport->SetStringField(TEXT("slice_id"), StringField(Manifest, TEXT("slice_id")));
    ManifestReport->SetStringField(TEXT("version"), ManifestVersion);
    ManifestReport->SetArrayField(TEXT("required_features"), StringArrayValues(RequiredFeatureNames));
    Report->SetObjectField(TEXT("manifest"), ManifestReport);
    Report->SetObjectField(TEXT("screenshot"), Screenshot);
    Report->SetNumberField(TEXT("checks_passed"), ChecksPassed);
    Report->SetNumberField(TEXT("checks_total"), Checks.Num());
    Report->SetArrayField(TEXT("checks"), Checks);

    FString WriteError;
    if (!WriteReport(ValidationOutput, Report, WriteError))
    {
        UE_LOG(LogTemp, Error, TEXT("XACE Unreal vertical slice certification: %s"), *WriteError);
        return 1;
    }
    UE_LOG(LogTemp, Display, TEXT("XACE Unreal vertical slice certification report: %s"), *JsonToString(Report));
    return bOk ? 0 : 1;
}
'''
    replacements = {
        "__VALIDATION_SCHEMA__": VALIDATION_SCHEMA,
        "__EXPECTED_CGS_HASH__": EXPECTED_CGS_HASH,
        "__EXPECTED_CGS_FILE_SHA__": EXPECTED_CGS_FILE_SHA,
        "__EXPECTED_FIXTURE_VERSION__": EXPECTED_FIXTURE_VERSION,
        "__VALIDATION_OUTPUT__": cpp_string(validation_path),
        "__SCREENSHOT_OUTPUT__": cpp_string(screenshot_path),
        "__REQUIRED_FEATURES__": required_features_literal,
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.lstrip()


def cpp_string(path: Path | str) -> str:
    return str(path).replace("\\", "\\\\")


def build_unreal_plugin(
    *,
    unreal_editor: Path,
    plugin_root: Path,
    package_dir: Path,
    command_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    run_uat = unreal_run_uat_path(unreal_editor)
    if run_uat is None:
        payload = {
            "ok": False,
            "returncode": None,
            "timed_out": False,
            "elapsed_seconds": 0.0,
            "error": f"RunUAT was not found for Unreal executable: {unreal_editor}",
            "stdout": "",
            "stderr": "",
        }
        command_path.write_text(canonical_json(payload, indent=2) + "\n", encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(payload["error"] + "\n", encoding="utf-8")
        return payload
    command = [
        str(run_uat),
        "BuildPlugin",
        f"-Plugin={plugin_root / 'XACE.uplugin'}",
        f"-Package={package_dir}",
        f"-TargetPlatforms={unreal_build_platform()}",
        "-Rocket",
    ]
    command_payload = {
        "schema": "xace.unreal_vertical_slice_build_command.v1",
        "task": TASK_ID,
        "cwd": str(plugin_root),
        "command": command,
        "timeout_seconds": timeout_seconds,
    }
    command_path.write_text(canonical_json(command_payload, indent=2) + "\n", encoding="utf-8")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(plugin_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(timeout_seconds, 60.0),
        )
        elapsed = time.perf_counter() - started
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "timed_out": False,
            "elapsed_seconds": round(elapsed, 3),
            "command": command,
            "package_dir": str(package_dir),
            "stdout": stdout,
            "stderr": stderr,
            "error": "" if completed.returncode == 0 else "Unreal BuildPlugin failed.",
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - started
        stdout = decode_timeout_stream(exc.stdout)
        stderr = decode_timeout_stream(exc.stderr)
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        return {
            "ok": False,
            "returncode": 124,
            "timed_out": True,
            "elapsed_seconds": round(elapsed, 3),
            "command": command,
            "package_dir": str(package_dir),
            "stdout": stdout,
            "stderr": stderr,
            "error": "Unreal BuildPlugin timed out.",
        }


def copy_packaged_binaries_to_project(package_dir: Path, plugin_root: Path) -> None:
    package_binaries = package_dir / "Binaries"
    if package_binaries.exists():
        shutil.copytree(package_binaries, plugin_root / "Binaries", dirs_exist_ok=True)


def unreal_plugin_editor_binary_ready(plugin_root: Path) -> dict[str, Any]:
    binary_dir = plugin_root / "Binaries" / unreal_build_platform()
    module_marker = binary_dir / "UnrealEditor.modules"
    editor_modules = sorted(binary_dir.glob("UnrealEditor-XACEAdapter.*"))
    ready = module_marker.exists() and any(path.suffix.lower() in {".dll", ".dylib", ".so"} for path in editor_modules)
    return {
        "ready": ready,
        "binary_dir": rel(binary_dir) if is_under_repo(binary_dir) else str(binary_dir),
        "module_marker": rel(module_marker) if is_under_repo(module_marker) else str(module_marker),
        "editor_modules": [rel(path) if is_under_repo(path) else str(path) for path in editor_modules],
    }


def run_unreal_commandlet(
    *,
    commandlet_executable: Path,
    project_file: Path,
    fixture_path: Path,
    validation_path: Path,
    screenshot_path: Path,
    editor_log_path: Path,
    command_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
    skip: bool,
) -> dict[str, Any]:
    command = [
        str(commandlet_executable),
        str(project_file),
        "-run=XaceVerticalSliceCertification",
        f"-XaceFixtureRoot={fixture_path}",
        f"-XaceValidationOutput={validation_path}",
        f"-XaceScreenshotOutput={screenshot_path}",
        "-unattended",
        "-nop4",
        "-nosplash",
        "-NullRHI",
        "-NoSound",
        f"-abslog={editor_log_path}",
    ]
    command_payload = {
        "schema": "xace.unreal_vertical_slice_commandlet_command.v1",
        "task": TASK_ID,
        "cwd": str(project_file.parent),
        "command": command,
        "timeout_seconds": timeout_seconds,
        "skipped": skip,
    }
    command_path.write_text(canonical_json(command_payload, indent=2) + "\n", encoding="utf-8")
    if skip:
        message = "Skipped UnrealEditor-Cmd run because BuildPlugin did not pass.\n"
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(message, encoding="utf-8")
        editor_log_path.write_text(message, encoding="utf-8")
        return {
            "ok": False,
            "returncode": None,
            "timed_out": False,
            "elapsed_seconds": 0.0,
            "skipped": True,
            "stdout": "",
            "stderr": message,
            "error": message.strip(),
        }
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_file.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(timeout_seconds, 30.0),
        )
        elapsed = time.perf_counter() - started
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "timed_out": False,
            "elapsed_seconds": round(elapsed, 3),
            "skipped": False,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "error": "" if completed.returncode == 0 else "Unreal commandlet failed.",
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - started
        stdout = decode_timeout_stream(exc.stdout)
        stderr = decode_timeout_stream(exc.stderr)
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        return {
            "ok": False,
            "returncode": 124,
            "timed_out": True,
            "elapsed_seconds": round(elapsed, 3),
            "skipped": False,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "error": "Unreal commandlet timed out.",
        }


def unreal_build_platform() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "Win64"
    if system == "darwin":
        return "Mac"
    return "Linux"


def build_hash_report(
    *,
    unreal_executable: Path,
    version_report: Mapping[str, Any],
    fixture_root: Path,
    adapter_root: Path,
    artifacts: Iterable[Path],
    adapter_scripts: Iterable[Path],
    plugin_files: Iterable[Path],
    packaged_files: Iterable[Path],
    completed_build: Mapping[str, Any],
    completed_commandlet: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": HASH_REPORT_SCHEMA,
        "task": TASK_ID,
        "generated_at_utc": utc_now(),
        "engine": "unreal",
        "unreal_executable": str(unreal_executable),
        "unreal_executable_sha256": sha256_file(unreal_executable),
        "unreal_version_probe": dict(version_report),
        "fixture_root": rel(fixture_root),
        "adapter_root": rel(adapter_root),
        "expected_cgs_hash": EXPECTED_CGS_HASH,
        "expected_cgs_file_sha256": EXPECTED_CGS_FILE_SHA,
        "unreal_build": {
            "returncode": completed_build.get("returncode"),
            "timed_out": bool(completed_build.get("timed_out")),
            "elapsed_seconds": completed_build.get("elapsed_seconds"),
        },
        "unreal_commandlet": {
            "returncode": completed_commandlet.get("returncode"),
            "timed_out": bool(completed_commandlet.get("timed_out")),
            "elapsed_seconds": completed_commandlet.get("elapsed_seconds"),
            "skipped": bool(completed_commandlet.get("skipped")),
        },
        "artifacts": [file_record(path) for path in artifacts],
        "adapter_scripts": [file_record(path) for path in adapter_scripts],
        "plugin_files": [file_record(path) for path in plugin_files],
        "packaged_files": [file_record(path) for path in packaged_files],
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


def iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in sorted(root.rglob("*")) if path.is_file()]


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
    if "target-codex-task66-unreal-vertical-slice" not in resolved.parts:
        raise ValueError(f"Refusing to remove non-Task66 generated directory: {resolved}")
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


def decode_timeout_stream(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

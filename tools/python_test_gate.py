"""
Run the XACE production Python test gate and write a JSON artifact.

This command is intentionally Python-only. It covers production Python package
tests plus lightweight repository tools, while forcing provider settings and
credential writes into a generated target directory instead of user settings.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import io
import json
import os
import re
import subprocess
import sys
import time
import traceback
import types
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "target-codex-python" / "python_gate_report.json"


@dataclass(frozen=True)
class SuiteSpec:
    id: str
    label: str
    runner: str
    start_dir: str = ""
    top_level_dir: str = ""
    import_roots: tuple[str, ...] = ()
    module_prefix: str = ""
    alias_modules: dict[str, str] = field(default_factory=dict)


UNITTEST_SUITES = (
    SuiteSpec(
        id="project-system",
        label="Project system unit tests",
        runner="unittest",
        start_dir="packages/project-system/tests",
        top_level_dir="packages/project-system",
    ),
    SuiteSpec(
        id="asset-registry",
        label="Asset registry unit tests",
        runner="unittest",
        start_dir="packages/asset-registry/tests",
        top_level_dir="packages/asset-registry",
    ),
    SuiteSpec(
        id="builder-server",
        label="Builder server unit tests",
        runner="unittest",
        start_dir="packages/builder-workspace/server/tests",
        top_level_dir="packages/builder-workspace/server",
        import_roots=("packages/project-system",),
    ),
    SuiteSpec(
        id="save-engine",
        label="Save engine Python tests",
        runner="unittest",
        start_dir="packages/save-engine/tests",
        top_level_dir="packages/save-engine",
    ),
)


PYTEST_STYLE_SUITES = (
    SuiteSpec(
        id="schema-factory",
        label="Schema factory Python tests",
        runner="pytest_style",
        start_dir="packages/schema-factory/src/tests",
        import_roots=("packages/schema-factory",),
        module_prefix="src.tests",
    ),
    SuiteSpec(
        id="gde",
        label="GDE Python tests",
        runner="pytest_style",
        start_dir="packages/gde/src/tests",
        import_roots=("packages/gde", "packages/schema-factory"),
        module_prefix="src.tests",
    ),
    SuiteSpec(
        id="inference",
        label="Inference Python tests",
        runner="pytest_style",
        start_dir="packages/inference/tests",
        import_roots=("packages", "packages/inference/src"),
        module_prefix="inference.tests",
        alias_modules={
            "inference.credit_system": "inference.src.credit_system",
            "inference.local_model_manager": "inference.src.local_model_manager",
            "inference.inference_retry_policy": "inference.src.inference_retry_policy",
        },
    ),
    SuiteSpec(
        id="prompt-intelligence",
        label="Prompt intelligence Python tests",
        runner="pytest_style",
        start_dir="packages/prompt-intelligence/src/tests",
        import_roots=(
            "packages/prompt-intelligence/src/clarification_engine",
            "packages/prompt-intelligence/src/code_generation",
            "packages/prompt-intelligence/src/context_assembler",
            "packages/prompt-intelligence/src/critique_engine",
            "packages/prompt-intelligence/src/history_manager",
            "packages/prompt-intelligence/src/intent_intake",
            "packages/prompt-intelligence/src/llm_orchestrator",
            "packages/prompt-intelligence/src/memory",
            "packages/prompt-intelligence/src/memory_model",
            "packages/prompt-intelligence/src/mode_controller",
            "packages/prompt-intelligence/src/mutation_planner",
            "packages/prompt-intelligence/src/output_parser",
            "packages/prompt-intelligence/src/safety_scope_guard",
            "packages/prompt-intelligence/src/validation_loop",
            "packages/prompt-intelligence/src",
            "packages/gde/src",
            "packages/inference/src",
        ),
        module_prefix="file",
        alias_modules={
            "pil_retry_policy": "retry_policy",
        },
    ),
)


ALL_SUITES = UNITTEST_SUITES + PYTEST_STYLE_SUITES


TOOL_COMMANDS = (
    ("commercial-scope", "Commercial scope check", [sys.executable, "tools/commercial_scope_check.py"]),
    ("source-inventory", "Source inventory check", [sys.executable, "tools/source_inventory_check.py"]),
    ("workspace-membership", "Workspace membership check", [sys.executable, "tools/workspace_membership_check.py"]),
    ("fake-skip-register", "Fake/skip register check", [sys.executable, "tools/fake_skip_register_check.py"]),
    ("production-path", "Production path rule check", [sys.executable, "tools/production_path_check.py"]),
    ("forbidden-claims", "Forbidden claims check", [sys.executable, "tools/forbidden_claims_check.py"]),
    ("secret-scan-source", "Source secret scan", [sys.executable, "tools/security_secret_scan.py", "--source"]),
)


class RaisesContext:
    def __init__(self, expected: type[BaseException] | tuple[type[BaseException], ...], match: str | None = None):
        self.expected = expected
        self.match = match
        self.value: BaseException | None = None
        self.type: type[BaseException] | None = None
        self.traceback: types.TracebackType | None = None

    def __enter__(self) -> "RaisesContext":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: types.TracebackType | None,
    ) -> bool:
        if exc_type is None or exc is None:
            raise AssertionError(f"expected exception {self.expected!r}")
        if not issubclass(exc_type, self.expected):
            return False
        if self.match and re.search(self.match, str(exc)) is None:
            raise AssertionError(f"exception text did not match {self.match!r}: {exc}")
        self.value = exc
        self.type = exc_type
        self.traceback = tb
        return True


def _install_pytest_raises_module() -> None:
    module = types.ModuleType("pytest")
    module.raises = lambda expected, match=None: RaisesContext(expected, match=match)  # type: ignore[attr-defined]
    sys.modules.setdefault("pytest", module)


def _suite_by_id(suite_id: str) -> SuiteSpec:
    for suite in ALL_SUITES:
        if suite.id == suite_id:
            return suite
    raise SystemExit(f"unknown suite: {suite_id}")


def _isolation_env(isolation_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["XACE_PROVIDER_SETTINGS_PATH"] = str(isolation_dir / "provider_settings.json")
    env["XACE_CREDENTIAL_BACKEND"] = "unsafe-file"
    env["XACE_DEV_UNSAFE_CREDENTIAL_FALLBACK"] = "1"
    env["XACE_UNSAFE_CREDENTIAL_STORE_PATH"] = str(isolation_dir / "unsafe_credentials.json")
    return env


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _tail(text: str, limit: int = 6000) -> str:
    return text[-limit:] if len(text) > limit else text


def _test_files(start_dir: Path) -> list[Path]:
    return sorted(path for path in start_dir.glob("test*.py") if path.is_file())


def _module_name_for(spec: SuiteSpec, path: Path) -> str:
    stem = path.with_suffix("").relative_to(REPO_ROOT / spec.start_dir).as_posix().replace("/", ".")
    if spec.module_prefix == "file":
        return f"xace_gate_{spec.id.replace('-', '_')}_{stem.replace('.', '_')}"
    return f"{spec.module_prefix}.{stem}" if stem else spec.module_prefix


def _prepare_imports(spec: SuiteSpec) -> None:
    for root in reversed(spec.import_roots):
        path = str((REPO_ROOT / root).resolve())
        if path not in sys.path:
            sys.path.insert(0, path)
    for alias, target in spec.alias_modules.items():
        sys.modules[alias] = importlib.import_module(target)


class _CountingTextResult(unittest.TextTestResult):
    pass


def _run_unittest_suite(spec: SuiteSpec, *, verbose: bool) -> dict[str, Any]:
    _prepare_imports(spec)
    start = time.perf_counter()
    buffer = io.StringIO()
    loader = unittest.defaultTestLoader
    suite = loader.discover(
        str(REPO_ROOT / spec.start_dir),
        top_level_dir=None,
    )
    runner = unittest.TextTestRunner(
        stream=buffer,
        verbosity=2 if verbose else 1,
        resultclass=_CountingTextResult,
    )
    result = runner.run(suite)
    elapsed = time.perf_counter() - start
    failures = [
        {"test": str(test), "traceback": trace}
        for test, trace in result.failures
    ]
    errors = [
        {"test": str(test), "traceback": trace}
        for test, trace in result.errors
    ]
    not_run = [
        {"test": str(test), "reason": reason}
        for test, reason in result.skipped
    ]
    return {
        "id": spec.id,
        "label": spec.label,
        "runner": spec.runner,
        "ok": result.wasSuccessful(),
        "tests": result.testsRun,
        "passed": result.testsRun - len(failures) - len(errors) - len(not_run),
        "failed": len(failures),
        "errors": len(errors),
        "not_run": len(not_run),
        "elapsed_seconds": round(elapsed, 3),
        "failures": failures,
        "error_details": errors,
        "not_run_details": not_run,
        "output_tail": _tail(buffer.getvalue()),
    }


def _run_pytest_style_suite(spec: SuiteSpec, *, verbose: bool) -> dict[str, Any]:
    _install_pytest_raises_module()
    _prepare_imports(spec)
    start = time.perf_counter()
    failures: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    passed = 0
    tests = 0

    for path in _test_files(REPO_ROOT / spec.start_dir):
        module_name = _module_name_for(spec, path)
        try:
            module = _import_test_module(spec, path, module_name)
        except Exception:
            tests += 1
            errors.append({
                "test": module_name,
                "traceback": traceback.format_exc(),
            })
            continue

        for cls_name, cls in sorted(inspect.getmembers(module, inspect.isclass)):
            if not cls_name.startswith("Test") or cls.__module__ != module.__name__:
                continue
            for method_name, method in sorted(inspect.getmembers(cls, inspect.isfunction)):
                if not method_name.startswith("test_"):
                    continue
                tests += 1
                test_id = f"{module_name}.{cls_name}.{method_name}"
                outcome = _run_pytest_style_method(cls, method_name)
                if outcome is None:
                    passed += 1
                    if verbose:
                        print(f"PASS {test_id}", file=sys.stderr)
                elif outcome["kind"] == "failure":
                    failures.append({"test": test_id, "traceback": outcome["traceback"]})
                else:
                    errors.append({"test": test_id, "traceback": outcome["traceback"]})

    elapsed = time.perf_counter() - start
    return {
        "id": spec.id,
        "label": spec.label,
        "runner": spec.runner,
        "ok": not failures and not errors,
        "tests": tests,
        "passed": passed,
        "failed": len(failures),
        "errors": len(errors),
        "not_run": 0,
        "elapsed_seconds": round(elapsed, 3),
        "failures": failures,
        "error_details": errors,
        "not_run_details": [],
        "output_tail": "",
    }


def _import_test_module(spec: SuiteSpec, path: Path, module_name: str) -> types.ModuleType:
    if spec.module_prefix == "file":
        module_spec = importlib.util.spec_from_file_location(module_name, path)
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"cannot load test module {path}")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        return module
    return importlib.import_module(module_name)


def _run_pytest_style_method(cls: type[Any], method_name: str) -> dict[str, str] | None:
    instance = cls()
    setup = getattr(instance, "setup_method", None)
    teardown = getattr(instance, "teardown_method", None)
    method = getattr(instance, method_name)
    try:
        if callable(setup):
            _call_setup_or_teardown(setup, method)
        method()
        if callable(teardown):
            _call_setup_or_teardown(teardown, method)
    except AssertionError:
        return {"kind": "failure", "traceback": traceback.format_exc()}
    except Exception:
        return {"kind": "error", "traceback": traceback.format_exc()}
    return None


def _call_setup_or_teardown(callback: Any, method: Any) -> None:
    try:
        callback()
    except TypeError as exc:
        try:
            callback(method)
        except TypeError:
            raise exc


def _child_run_suite(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    spec = _suite_by_id(args.suite)
    if spec.runner == "unittest":
        result = _run_unittest_suite(spec, verbose=args.verbose)
    else:
        result = _run_pytest_style_suite(spec, verbose=args.verbose)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


def _run_suite_subprocess(spec: SuiteSpec, env: dict[str, str], output_dir: Path, *, verbose: bool) -> dict[str, Any]:
    child_output = output_dir / f"{spec.id}.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_child-suite",
        "--suite",
        spec.id,
        "--output",
        str(child_output),
    ]
    if verbose:
        command.append("--verbose")
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if child_output.exists():
        result = json.loads(child_output.read_text(encoding="utf-8"))
    else:
        result = {
            "id": spec.id,
            "label": spec.label,
            "runner": spec.runner,
            "ok": False,
            "tests": 0,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "not_run": 0,
            "elapsed_seconds": round(elapsed, 3),
            "failures": [],
            "error_details": [{"test": spec.id, "traceback": "suite runner did not write a result"}],
            "not_run_details": [],
            "output_tail": _tail(completed.stdout or ""),
        }
    result["returncode"] = completed.returncode
    result["command"] = command
    result["stdout_tail"] = _tail(completed.stdout or "")
    return result


def _run_tool_command(command_id: str, label: str, command: list[str], env: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = time.perf_counter() - started
    return {
        "id": command_id,
        "label": label,
        "runner": "command",
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "elapsed_seconds": round(elapsed, 3),
        "stdout_tail": _tail(completed.stdout or ""),
    }


def _syntax_check_python_files() -> dict[str, Any]:
    started = time.perf_counter()
    failures: list[dict[str, str]] = []
    files = _production_python_files()
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except Exception:
            failures.append({
                "path": _rel(path),
                "traceback": traceback.format_exc(),
            })
    elapsed = time.perf_counter() - started
    return {
        "id": "python-syntax",
        "label": "Production Python syntax check",
        "runner": "compile",
        "ok": not failures,
        "files": len(files),
        "failed": len(failures),
        "elapsed_seconds": round(elapsed, 3),
        "failures": failures,
    }


def _production_python_files() -> list[Path]:
    files: set[Path] = set()
    for root in ("tools", "packages"):
        for path in (REPO_ROOT / root).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(part in {"__pycache__", "node_modules", "dist", "build"} for part in rel.split("/")):
                continue
            if "/tests/" in rel or rel.endswith("/tests.py"):
                continue
            files.add(path)
    return sorted(files)


def _summarize(suites: list[dict[str, Any]], tools: list[dict[str, Any]], syntax: dict[str, Any]) -> dict[str, Any]:
    total_tests = sum(int(suite.get("tests", 0)) for suite in suites)
    failed = sum(int(suite.get("failed", 0)) + int(suite.get("errors", 0)) for suite in suites)
    not_run = sum(int(suite.get("not_run", 0)) for suite in suites)
    return {
        "suites": len(suites),
        "tests": total_tests,
        "passed": sum(int(suite.get("passed", 0)) for suite in suites),
        "failed_or_error": failed,
        "not_run": not_run,
        "tools": len(tools),
        "tool_failures": sum(1 for tool in tools if not tool.get("ok")),
        "syntax_files": int(syntax.get("files", 0)),
        "syntax_failures": int(syntax.get("failed", 0)),
    }


def _write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_gate(output_path: Path, *, fail_fast: bool, verbose: bool) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    output_path = output_path.resolve()
    work_dir = output_path.parent / "python_gate_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    isolation_dir = work_dir / "isolated_settings"
    isolation_dir.mkdir(parents=True, exist_ok=True)
    env = _isolation_env(isolation_dir)

    suites: list[dict[str, Any]] = []
    for spec in ALL_SUITES:
        result = _run_suite_subprocess(spec, env, work_dir, verbose=verbose)
        suites.append(result)
        status = "PASS" if result.get("ok") else "FAIL"
        print(f"[python-gate] {status} {spec.label} ({result.get('tests', 0)} tests, {result.get('elapsed_seconds')}s)")
        if fail_fast and not result.get("ok"):
            break

    tools: list[dict[str, Any]] = []
    if not fail_fast or all(suite.get("ok") for suite in suites):
        for command_id, label, command in TOOL_COMMANDS:
            result = _run_tool_command(command_id, label, command, env)
            tools.append(result)
            status = "PASS" if result.get("ok") else "FAIL"
            print(f"[python-gate] {status} {label} ({result.get('elapsed_seconds')}s)")
            if fail_fast and not result.get("ok"):
                break

    syntax = _syntax_check_python_files()
    print(
        f"[python-gate] {'PASS' if syntax.get('ok') else 'FAIL'} "
        f"{syntax['label']} ({syntax.get('files', 0)} files, {syntax.get('elapsed_seconds')}s)"
    )

    elapsed = time.perf_counter() - start
    summary = _summarize(suites, tools, syntax)
    ok = (
        all(suite.get("ok") for suite in suites)
        and all(tool.get("ok") for tool in tools)
        and bool(syntax.get("ok"))
        and len(suites) == len(ALL_SUITES)
        and len(tools) == len(TOOL_COMMANDS)
    )
    report = {
        "schema": "xace.python_test_gate.v1",
        "ok": ok,
        "started_at_utc": started_at.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "repo_root": str(REPO_ROOT),
        "command": [sys.executable, "tools/python_test_gate.py", "--output", str(output_path)],
        "isolation": {
            "settings_path": env["XACE_PROVIDER_SETTINGS_PATH"],
            "credential_store_path": env["XACE_UNSAFE_CREDENTIAL_STORE_PATH"],
            "work_dir": str(work_dir),
        },
        "summary": summary,
        "suites": suites,
        "tools": tools,
        "syntax": syntax,
    }
    _write_report(report, output_path)
    print(f"[python-gate] JSON artifact: {output_path}")
    print(f"[python-gate] {'PASSED' if ok else 'FAILED'}")
    return report


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if argv and argv[0] == "--_child-suite":
        return _child_run_suite(argv[1:])

    parser = argparse.ArgumentParser(description="Run all production Python package tests and Python tool checks.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Path for the JSON artifact. Default: target-codex-python/python_gate_report.json",
    )
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failing suite or tool.")
    parser.add_argument("--verbose", action="store_true", help="Use verbose suite output in child runners.")
    args = parser.parse_args(argv)

    report = run_gate(Path(args.output), fail_fast=bool(args.fail_fast), verbose=bool(args.verbose))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

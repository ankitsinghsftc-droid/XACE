"""Static AG-015 guardrails for XACE Builder Agent Mode.

This complements runtime denial tests. It rejects credential-store imports and
direct provider calls to shell, process, filesystem-write, approval, or patch
methods from the Agent host implementation.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_HOST = REPO_ROOT / "packages" / "builder-workspace" / "server" / "agent_host"

FORBIDDEN_PROVIDER_METHOD_PREFIXES = ("command/", "process/", "fs/")
FORBIDDEN_PROVIDER_METHODS = {
    "applyPatch",
    "fileChange",
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
}


def _credential_imports(tree: ast.AST) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [str(node.module or "")]
        else:
            continue
        findings.extend(name for name in names if "credential_store" in name)
    return findings


def _provider_method_literals(tree: ast.AST) -> list[tuple[int, str]]:
    methods: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"request", "optional_request", "notify"} or not node.args:
            continue
        method = node.args[0]
        if isinstance(method, ast.Constant) and isinstance(method.value, str):
            methods.append((node.lineno, method.value))
    return methods


def run_check() -> dict[str, object]:
    findings: list[dict[str, object]] = []
    scanned = 0
    for path in sorted(AGENT_HOST.glob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        relative = path.relative_to(REPO_ROOT).as_posix()
        for imported in _credential_imports(tree):
            findings.append(
                {
                    "path": relative,
                    "line": 0,
                    "rule": "no-agent-credential-store-import",
                    "detail": imported,
                }
            )
        for line, method in _provider_method_literals(tree):
            forbidden = method in FORBIDDEN_PROVIDER_METHODS or method.startswith(
                FORBIDDEN_PROVIDER_METHOD_PREFIXES
            )
            if forbidden:
                findings.append(
                    {
                        "path": relative,
                        "line": line,
                        "rule": "no-agent-provider-mutation-method",
                        "detail": method,
                    }
                )

    required = {
        "security_policy.py": AGENT_HOST / "security_policy.py",
        "context_capsule.py": AGENT_HOST / "context_capsule.py",
        "proposal_ingress.py": AGENT_HOST / "proposal_ingress.py",
    }
    for label, path in required.items():
        if not path.is_file():
            findings.append(
                {
                    "path": path.relative_to(REPO_ROOT).as_posix(),
                    "line": 0,
                    "rule": "required-agent-security-module",
                    "detail": label,
                }
            )

    return {
        "schema": "xace.agent_security_check.v1",
        "ok": not findings,
        "files_scanned": scanned,
        "findings": findings,
    }


def main() -> int:
    report = run_check()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

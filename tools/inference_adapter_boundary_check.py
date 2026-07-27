"""
Enforce Task 51: model provider calls must go through packages/inference.

The check scans Builder, PIL, GDE, and tools for provider SDK imports or direct
provider completion HTTP outside packages/inference. It intentionally permits
provider endpoint configuration strings when there is no HTTP dispatch in that
file; the boundary being enforced is provider execution, not static metadata.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "xace.inference_adapter_boundary_report.v1"
DEFAULT_OUTPUT = REPO_ROOT / "target-inference-adapter-boundary" / "inference_adapter_boundary_report.json"
SCAN_ROOTS = (
    "packages/builder-workspace",
    "packages/prompt-intelligence",
    "packages/gde",
    "tools",
)
ALLOWED_PREFIXES = (
    "packages/inference/",
)
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
}
SELF_PATH = "tools/inference_adapter_boundary_check.py"

SDK_IMPORT_PATTERNS = (
    re.compile(r"^\s*(?:import|from)\s+openai\b", re.MULTILINE),
    re.compile(r"^\s*(?:import|from)\s+anthropic\b", re.MULTILINE),
    re.compile(r"^\s*(?:import|from)\s+google\.(?:generativeai|genai)\b", re.MULTILINE),
    re.compile(r"^\s*(?:import|from)\s+(?:cohere|groq|mistralai)\b", re.MULTILINE),
)
HTTP_CLIENT_PATTERNS = (
    re.compile(r"\brequests\.(?:delete|get|post|put|request)\s*\("),
    re.compile(r"\burllib\.request\.urlopen\s*\("),
    re.compile(r"\burlopen\s*\("),
    re.compile(r"\bhttpx\."),
    re.compile(r"\baiohttp\.ClientSession\b"),
    re.compile(r"\bfetch\s*\("),
)
PROVIDER_ENDPOINT_PATTERNS = (
    re.compile(r"https://api\.openai\.com\b"),
    re.compile(r"https://api\.anthropic\.com\b"),
    re.compile(r"https://generativelanguage\.googleapis\.com\b"),
    re.compile(r"https://api\.moonshot\.ai\b"),
    re.compile(r"[/\\]v1[/\\]chat[/\\]completions\b"),
    re.compile(r"[/\\]v1[/\\]messages\b"),
    re.compile(r":generateContent\b"),
    re.compile(r"[/\\]api[/\\](?:chat|generate)\b"),
)


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    line: int
    message: str
    text: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the inference adapter provider-call boundary.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON report path.")
    parser.add_argument("--json", action="store_true", help="Print the report JSON.")
    args = parser.parse_args(argv)

    report = run(Path(args.output))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(f"inference adapter boundary check PASSED ({report['scanned_files']} files scanned)")
    else:
        print("inference adapter boundary check failed:", file=sys.stderr)
        for finding in report["findings"]:
            print(
                f"- {finding['path']}:{finding['line']}: {finding['rule']}: "
                f"{finding['message']}",
                file=sys.stderr,
            )
    return 0 if report["ok"] else 1


def run(output: Path) -> dict[str, object]:
    output = _resolve(output)
    findings: list[Finding] = []
    self_test_findings = _self_test_findings()
    findings.extend(self_test_findings)

    files = list(_scan_files())
    for path in files:
        rel_path = _display(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(Finding(rel_path, "read_error", 0, str(exc), ""))
            continue
        findings.extend(_detect_text(text, rel_path))

    report = {
        "schema": REPORT_SCHEMA,
        "ok": not findings,
        "scanned_files": len(files),
        "allowed_provider_call_root": "packages/inference",
        "detector_self_test": "pass" if not self_test_findings else "fail",
        "rules": [
            "provider_sdk_import_outside_inference",
            "provider_http_dispatch_outside_inference",
        ],
        "findings": [asdict(finding) for finding in findings],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _self_test_findings() -> list[Finding]:
    cases = (
        (
            "synthetic/provider_sdk.py",
            "import openai\nclient = openai.OpenAI()\n",
            True,
        ),
        (
            "synthetic/provider_http.py",
            "import urllib.request\nurllib.request.urlopen('https://api.openai.com/v1/chat/completions')\n",
            True,
        ),
        (
            "synthetic/provider_fetch.ts",
            "fetch('https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent')\n",
            True,
        ),
        (
            "packages/inference/providers/openai_provider.py",
            "import urllib.request\nurllib.request.urlopen('https://api.openai.com/v1/chat/completions')\n",
            False,
        ),
        (
            "synthetic/provider_config_only.py",
            "CHAT_URL = 'https://api.openai.com/v1/chat/completions'\n",
            False,
        ),
        (
            "synthetic/local_builder_api.py",
            "import urllib.request\nurllib.request.urlopen('http://127.0.0.1:8899/api/project')\n",
            False,
        ),
    )
    findings: list[Finding] = []
    for path, text, should_find in cases:
        detected = _detect_text(text, path)
        if should_find and not detected:
            findings.append(Finding(path, "self_test", 0, "detector missed a direct provider call", ""))
        if not should_find and detected:
            findings.append(Finding(path, "self_test", 0, "detector flagged an allowed pattern", detected[0].text))
    return findings


def _detect_text(text: str, rel_path: str) -> list[Finding]:
    if _is_allowed_path(rel_path):
        return []
    findings: list[Finding] = []
    for pattern in SDK_IMPORT_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(Finding(
                rel_path,
                "provider_sdk_import_outside_inference",
                _line_number(text, match.start()),
                "Provider SDK imports are allowed only inside packages/inference.",
                _line_text(text, match.start()),
            ))

    has_http_dispatch = any(pattern.search(text) for pattern in HTTP_CLIENT_PATTERNS)
    if not has_http_dispatch:
        return findings
    for pattern in PROVIDER_ENDPOINT_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(Finding(
                rel_path,
                "provider_http_dispatch_outside_inference",
                _line_number(text, match.start()),
                "Provider completion HTTP/API dispatch must be routed through packages/inference.",
                _line_text(text, match.start()),
            ))
    return findings


def _scan_files() -> Iterable[Path]:
    for root_name in SCAN_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        if root.is_file():
            if _should_scan(root):
                yield root
            continue
        for path in sorted(root.rglob("*")):
            if _should_scan(path):
                yield path


def _should_scan(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    rel = _display(path)
    if rel == SELF_PATH:
        return False
    if _is_allowed_path(rel):
        return False
    if rel.startswith("target") or any(part in IGNORED_PARTS or part.startswith("target-") for part in path.parts):
        return False
    return True


def _is_allowed_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _line_text(text: str, offset: int) -> str:
    lines = text.splitlines()
    line = _line_number(text, offset)
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()
    return ""


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())

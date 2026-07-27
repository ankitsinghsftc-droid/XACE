"""
Validate that authoritative XACE state code does not use raw float math.

This is the Task X10-009/X10-010 guard. It scans authoritative state/runtime roots
after masking Rust comments and string literals, so docs, examples embedded in
strings, and JSON fixture text do not count as executable authority.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "xace.fixed_point_authority_report.v1"

AUTHORITATIVE_TARGETS = (
    "packages/core/src/fixed_point.rs",
    "packages/core/src/ucl",
    "packages/core/src/schema",
    "packages/core/src/runtime",
    "packages/core/src/events/event_struct.rs",
    "packages/runtime-core/src/fixed_json.rs",
    "packages/runtime-core/src/builtin_systems.rs",
    "packages/runtime-core/src/generated_system_abi.rs",
    "packages/runtime-core/src/phase_orchestrator/system_context.rs",
    "examples/zombie-chase/src",
)

NON_AUTHORITATIVE_FLOAT_ZONES = (
    {
        "path": "packages/core/src/wire/feedback_payload.rs",
        "reason": "Engine feedback/telemetry boundary; consumed at tick boundary before authoritative mutation.",
    },
    {
        "path": "packages/core/src/contracts/interfaces.rs",
        "reason": "Cross-module/adapter interface surface; X10-011 covers visibility distance migration and side-channel policy.",
    },
    {
        "path": "packages/runtime-core/src/time_controller",
        "reason": "Wall-clock frame accumulator boundary; ticks remain authoritative.",
    },
    {
        "path": "packages/network-core/src/prediction",
        "reason": "Client prediction/reconciliation is not authoritative state until X10-035..X10-038 integration.",
    },
    {
        "path": "packages/engine-feedback/src",
        "reason": "Engine feedback adapter layer; feedback is sorted and converted before committed runtime mutation.",
    },
)

NEXT_TASK_FLOAT_DEBT: tuple[dict[str, str], ...] = ()

FLOAT_TYPE_RE = re.compile(r"\b(?:f32|f64)\b")
FLOAT_LITERAL_RE = re.compile(
    r"(?<![\w.])(?:\d+\.\d+|\d+\.(?!\.))(?:[eE][+-]?\d+)?(?:f32|f64)?"
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    token: str
    snippet: str

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "kind": self.kind,
            "token": self.token,
            "snippet": self.snippet,
        }


def _mask_preserve_newlines(value: str) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in value)


def _raw_string_end(text: str, index: int) -> int | None:
    prefix_len = 0
    if text.startswith("br", index):
        prefix_len = 2
    elif text.startswith("r", index):
        prefix_len = 1
    else:
        return None

    hash_start = index + prefix_len
    cursor = hash_start
    while cursor < len(text) and text[cursor] == "#":
        cursor += 1
    if cursor >= len(text) or text[cursor] != '"':
        return None

    hashes = text[hash_start:cursor]
    terminator = '"' + hashes
    end = text.find(terminator, cursor + 1)
    if end == -1:
        return len(text)
    return end + len(terminator)


def strip_rust_comments_and_literals(text: str) -> str:
    out: list[str] = []
    i = 0
    block_depth = 0

    while i < len(text):
        if block_depth:
            if text.startswith("/*", i):
                out.extend("  ")
                block_depth += 1
                i += 2
            elif text.startswith("*/", i):
                out.extend("  ")
                block_depth -= 1
                i += 2
            else:
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue

        raw_end = _raw_string_end(text, i)
        if raw_end is not None:
            out.append(_mask_preserve_newlines(text[i:raw_end]))
            i = raw_end
            continue

        if text.startswith("//", i):
            end = text.find("\n", i)
            if end == -1:
                out.append(" " * (len(text) - i))
                break
            out.append(" " * (end - i))
            out.append("\n")
            i = end + 1
            continue

        if text.startswith("/*", i):
            out.extend("  ")
            block_depth = 1
            i += 2
            continue

        if text[i] == '"':
            start = i
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            out.append(_mask_preserve_newlines(text[start:i]))
            continue

        if text[i] == "'":
            start = i
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == "'":
                    i += 1
                    break
                if text[i] == "\n":
                    break
                i += 1
            out.append(_mask_preserve_newlines(text[start:i]))
            continue

        out.append(text[i])
        i += 1

    return "".join(out)


def _rust_files(root: Path, target: str) -> list[Path]:
    path = root / target
    if path.is_file():
        return [path] if path.suffix == ".rs" else []
    if path.is_dir():
        return sorted(path.rglob("*.rs"))
    return []


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _snippet(original: str, line: int) -> str:
    lines = original.splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()[:220]
    return ""


def scan_file(root: Path, path: Path) -> list[Finding]:
    original = path.read_text(encoding="utf-8")
    code = strip_rust_comments_and_literals(original)
    rel = path.relative_to(root).as_posix()
    findings: list[Finding] = []

    for regex, kind in ((FLOAT_TYPE_RE, "raw_float_type"), (FLOAT_LITERAL_RE, "float_literal")):
        for match in regex.finditer(code):
            line = _line_for_offset(code, match.start())
            findings.append(
                Finding(
                    path=rel,
                    line=line,
                    kind=kind,
                    token=match.group(0),
                    snippet=_snippet(original, line),
                )
            )
    return findings


def scan_targets(root: Path, targets: tuple[str, ...]) -> tuple[list[str], list[Finding]]:
    files: list[Path] = []
    for target in targets:
        files.extend(_rust_files(root, target))
    unique_files = sorted({path.resolve() for path in files})
    findings: list[Finding] = []
    for path in unique_files:
        findings.extend(scan_file(root, path))
    rel_files = [path.relative_to(root).as_posix() for path in unique_files]
    return rel_files, findings


def summarize_debt(root: Path) -> list[dict[str, Any]]:
    debt: list[dict[str, Any]] = []
    for item in NEXT_TASK_FLOAT_DEBT:
        files, findings = scan_targets(root, (str(item["path"]),))
        samples = [finding.to_json() for finding in findings[:12]]
        debt.append(
            {
                **item,
                "files_scanned": len(files),
                "finding_count": len(findings),
                "sample_findings": samples,
            }
        )
    return debt


def build_report(root: Path) -> dict[str, Any]:
    files, findings = scan_targets(root, AUTHORITATIVE_TARGETS)
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ok": not findings,
        "fixed_point_contract": {
            "rust_type": "xace_core::fixed_point::Fixed64",
            "storage": "i64 raw micro-units",
            "scale": 1_000_000,
            "serde": "transparent integer; no JSON float encoding",
        },
        "authoritative_scan": {
            "targets": list(AUTHORITATIVE_TARGETS),
            "files_scanned": len(files),
            "banned_patterns": ["f32", "f64", "executable float literals"],
            "findings": [finding.to_json() for finding in findings],
        },
        "allowed_non_authoritative_float_zones": list(NON_AUTHORITATIVE_FLOAT_ZONES),
        "next_task_float_debt": summarize_debt(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate XACE authoritative fixed-point state.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root to scan.")
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report path. Defaults to stdout only.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report = build_report(root)

    output = str(args.output or "").strip()
    if output:
        output_path = Path(output)
        if not output_path.is_absolute():
            output_path = root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    elif report["ok"]:
        scan = report["authoritative_scan"]
        print(
            "fixed-point authority check PASSED "
            f"({scan['files_scanned']} files, {len(scan['findings'])} findings)"
        )
    else:
        print("fixed-point authority check FAILED", file=sys.stderr)
        for finding in report["authoritative_scan"]["findings"]:
            print(
                f"{finding['path']}:{finding['line']}: {finding['kind']} {finding['token']} "
                f"in {finding['snippet']}",
                file=sys.stderr,
            )

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

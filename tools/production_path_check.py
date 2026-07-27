from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = REPO_ROOT / "docs" / "production_path_rules.json"
REGISTER_PATH = REPO_ROOT / "docs" / "fake_skip_register.json"

TEXT_SUFFIXES = {
    ".cs",
    ".cpp",
    ".gd",
    ".h",
    ".py",
    ".rs",
    ".ts",
}

IMPORT_LINE = re.compile(
    r"^\s*(?:from\s+[\w.]+\s+import|import\s+[\w., ]+|use\s+[\w:]+|mod\s+\w+|"
    r".*?\bfrom\s+[\"'][^\"']+[\"']|.*?\brequire\([\"'][^\"']+[\"']\))"
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule_id: str
    message: str
    text: str


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _matches(pattern: str, rel_path: str) -> bool:
    pattern = pattern.replace("\\", "/")
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if "*" in prefix or "?" in prefix:
            return fnmatch(rel_path, pattern) or fnmatch(rel_path, prefix)
        return rel_path == prefix or rel_path.startswith(prefix + "/")
    return rel_path == pattern or fnmatch(rel_path, pattern)


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(_matches(pattern, rel_path) for pattern in patterns)


def _iter_production_files(rules: dict[str, Any]) -> list[Path]:
    production_globs = list(rules.get("production_globs") or [])
    nonproduction_globs = list(rules.get("nonproduction_globs") or [])
    files: set[Path] = set()
    for pattern in production_globs:
        files.update(path for path in REPO_ROOT.glob(pattern) if path.is_file())
    out: list[Path] = []
    for path in sorted(files):
        rel_path = _rel(path)
        if path.suffix not in TEXT_SUFFIXES:
            continue
        if _matches_any(rel_path, nonproduction_globs):
            continue
        if rel_path.startswith("target") or "node_modules/" in rel_path or "/dist/" in rel_path:
            continue
        out.append(path)
    return out


def _allowed_key(allowed: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(allowed.get("rule_id") or ""),
        str(allowed.get("path") or "").replace("\\", "/"),
        str(allowed.get("contains") or ""),
    )


def _is_allowed(finding: Finding, allowed: list[dict[str, Any]]) -> bool:
    for item in allowed:
        rule_id, path, contains = _allowed_key(item)
        if rule_id == finding.rule_id and path == finding.path and contains and contains in finding.text:
            return True
    return False


def _validate_config(rules: dict[str, Any], register: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if rules.get("schema") != "xace.production_path_rules.v1":
        findings.append(Finding(str(RULES_PATH), 0, "CONFIG", "schema must be xace.production_path_rules.v1", ""))
    register_ids = {
        str(entry.get("id"))
        for entry in register.get("entries", [])
        if isinstance(entry, dict) and entry.get("id")
    }
    rule_ids = {
        str(rule.get("id"))
        for rule in rules.get("forbidden_patterns", [])
        if isinstance(rule, dict) and rule.get("id")
    }
    for item in rules.get("allowed_findings", []):
        if not isinstance(item, dict):
            findings.append(Finding(str(RULES_PATH), 0, "CONFIG", "allowed_findings entries must be objects", ""))
            continue
        for field in ("rule_id", "path", "contains", "fsr_id", "owner_task"):
            if not str(item.get(field) or "").strip():
                findings.append(Finding(str(RULES_PATH), 0, "CONFIG", f"allowed finding missing {field}", json.dumps(item)))
        if str(item.get("rule_id")) not in rule_ids:
            findings.append(Finding(str(RULES_PATH), 0, "CONFIG", f"allowed finding references unknown rule {item.get('rule_id')}", json.dumps(item)))
        if str(item.get("fsr_id")) not in register_ids:
            findings.append(Finding(str(RULES_PATH), 0, "CONFIG", f"allowed finding references unknown FSR {item.get('fsr_id')}", json.dumps(item)))
        rel_path = str(item.get("path") or "").replace("\\", "/")
        if rel_path and not (REPO_ROOT / rel_path).exists():
            findings.append(Finding(rel_path, 0, "CONFIG", "allowed finding path does not exist", json.dumps(item)))
    return findings


def _scan_imports(path: Path, rel_path: str, text: str, rules: dict[str, Any]) -> list[Finding]:
    blocked = [str(item) for item in rules.get("blocked_import_fragments", [])]
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not IMPORT_LINE.search(line):
            continue
        lowered = line.lower()
        for fragment in blocked:
            if fragment.lower() in lowered:
                findings.append(Finding(
                    rel_path,
                    lineno,
                    "PPR_IMPORT",
                    f"production import references non-production fragment {fragment!r}",
                    line.strip(),
                ))
    return findings


def _scan_forbidden_patterns(path: Path, rel_path: str, text: str, rules: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    patterns = rules.get("forbidden_patterns", [])
    for rule in patterns:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id") or "")
        name = str(rule.get("name") or rule_id)
        regex = str(rule.get("regex") or "")
        if not rule_id or not regex:
            continue
        compiled = re.compile(regex, re.IGNORECASE)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                findings.append(Finding(
                    rel_path,
                    lineno,
                    rule_id,
                    name,
                    line.strip(),
                ))
    return findings


def validate(rules: dict[str, Any], register: dict[str, Any]) -> list[Finding]:
    findings = _validate_config(rules, register)
    allowed = list(rules.get("allowed_findings") or [])
    observed_allowed: set[tuple[str, str, str]] = set()

    for path in _iter_production_files(rules):
        rel_path = _rel(path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        for finding in _scan_imports(path, rel_path, text, rules):
            findings.append(finding)
        for finding in _scan_forbidden_patterns(path, rel_path, text, rules):
            if _is_allowed(finding, allowed):
                for item in allowed:
                    if (
                        str(item.get("rule_id")) == finding.rule_id
                        and str(item.get("path")).replace("\\", "/") == finding.path
                        and str(item.get("contains") or "") in finding.text
                    ):
                        observed_allowed.add(_allowed_key(item))
                continue
            findings.append(finding)

    for item in allowed:
        key = _allowed_key(item)
        if key not in observed_allowed:
            findings.append(Finding(
                str(item.get("path") or RULES_PATH),
                0,
                "STALE_ALLOW",
                f"allowed finding is stale or no longer matched: {item.get('contains')!r}",
                json.dumps(item, sort_keys=True),
            ))
    return findings


def main() -> int:
    findings = validate(_load_json(RULES_PATH), _load_json(REGISTER_PATH))
    if findings:
        print("XACE production path check failed:", file=sys.stderr)
        for finding in findings:
            location = finding.path if finding.line == 0 else f"{finding.path}:{finding.line}"
            print(f"{location}: {finding.rule_id}: {finding.message}: {finding.text}", file=sys.stderr)
        return 1
    print("production path check PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Validate the Task 46 reviewed 100-prompt corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "docs" / "prompt_corpus_manifest.json"
MATRIX_PATH = REPO_ROOT / "docs" / "prompt_capability_matrix.json"

CASE_SCHEMA = "xace.prompt_corpus_case.v1"
MANIFEST_SCHEMA = "xace.prompt_corpus_manifest.v1"

ROUTES_BY_CATEGORY = {
    "certified_supported": {"mutation_preview", "mutation_preview_with_sgc"},
    "constrained": {"mutation_or_clarification"},
    "clarification_required": {"clarification"},
    "blocked": {"blocked"},
    "unsupported": {"unsupported"},
    "experimental": {"experimental"},
}

RESULT_KIND_BY_CATEGORY = {
    "certified_supported": {"mutation"},
    "constrained": {"mutation_or_clarification"},
    "clarification_required": {"clarification"},
    "blocked": {"blocked"},
    "unsupported": {"blocked"},
    "experimental": {"blocked_or_clarification"},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Task 46 prompt corpus.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args(argv)

    findings = run()
    report = {
        "schema": "xace.prompt_corpus_check.v1",
        "ok": not findings,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        print("prompt corpus check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
    else:
        print("prompt corpus check PASSED")
    return 1 if findings else 0


def run() -> list[str]:
    findings: list[str] = []
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"cannot load prompt corpus manifest: {exc}"]
    if manifest.get("schema") != MANIFEST_SCHEMA:
        findings.append(f"manifest schema must be {MANIFEST_SCHEMA}")

    corpus_path = REPO_ROOT / str(manifest.get("source_of_truth") or "")
    if not corpus_path.exists():
        return findings + [f"missing corpus file: {corpus_path.relative_to(REPO_ROOT)}"]
    actual_hash = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    if manifest.get("corpus_sha256") != actual_hash:
        findings.append("manifest corpus_sha256 does not match docs/prompt_corpus_100.jsonl")

    try:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return findings + [f"cannot load prompt capability matrix: {exc}"]
    matrix_categories = {
        str(category.get("id"))
        for category in matrix.get("categories", [])
        if isinstance(category, dict)
    }

    rows, parse_findings = _load_jsonl(corpus_path)
    findings.extend(parse_findings)
    expected_count = int(manifest.get("case_count") or 0)
    if len(rows) != expected_count:
        findings.append(f"corpus has {len(rows)} cases, expected {expected_count}")

    findings.extend(_validate_rows(rows, manifest, matrix_categories))
    findings.extend(_validate_counts(rows, manifest))
    return findings


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    findings: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            findings.append(f"line {line_number} is blank; JSONL corpus must be dense")
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(f"line {line_number} invalid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            findings.append(f"line {line_number} must be a JSON object")
            continue
        rows.append(row)
    return rows, findings


def _validate_rows(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    matrix_categories: set[str],
) -> list[str]:
    findings: list[str] = []
    seen_ids: set[str] = set()
    seen_prompts: set[str] = set()
    required_genres = set(manifest.get("required_genres") or [])
    required_bands = set(manifest.get("required_difficulty_bands") or [])
    required_categories = set(manifest.get("required_category_ids") or [])
    expected_version = int(manifest.get("version") or 0)
    expected_corpus_id = str(manifest.get("corpus_id") or "")

    for index, row in enumerate(rows, start=1):
        prefix = f"case {index}"
        prompt_id = str(row.get("prompt_id") or "")
        expected_id = f"pc{index:03d}"
        if prompt_id != expected_id:
            findings.append(f"{prefix} prompt_id must be {expected_id}, got {prompt_id!r}")
        if prompt_id in seen_ids:
            findings.append(f"{prefix} duplicate prompt_id {prompt_id!r}")
        seen_ids.add(prompt_id)

        if row.get("schema") != CASE_SCHEMA:
            findings.append(f"{prompt_id} schema must be {CASE_SCHEMA}")
        if row.get("corpus_id") != expected_corpus_id:
            findings.append(f"{prompt_id} corpus_id mismatch")
        if int(row.get("corpus_version") or 0) != expected_version:
            findings.append(f"{prompt_id} corpus_version mismatch")

        prompt = str(row.get("prompt") or "").strip()
        if len(prompt) < 12:
            findings.append(f"{prompt_id} prompt is too short")
        normalized_prompt = " ".join(prompt.lower().split())
        if normalized_prompt in seen_prompts:
            findings.append(f"{prompt_id} duplicate prompt text")
        seen_prompts.add(normalized_prompt)

        genre = str(row.get("genre") or "")
        if genre not in required_genres:
            findings.append(f"{prompt_id} genre {genre!r} is not in manifest required_genres")
        band = str(row.get("difficulty_band") or "")
        if band not in required_bands:
            findings.append(f"{prompt_id} difficulty_band {band!r} is not in manifest required_difficulty_bands")
        category = str(row.get("category_id") or "")
        if category not in required_categories:
            findings.append(f"{prompt_id} category_id {category!r} is not in manifest required_category_ids")
        if category not in matrix_categories:
            findings.append(f"{prompt_id} category_id {category!r} is not in prompt capability matrix")

        route = str(row.get("expected_builder_route") or "")
        if route not in ROUTES_BY_CATEGORY.get(category, set()):
            findings.append(f"{prompt_id} route {route!r} does not match category {category!r}")
        result_kind = str(row.get("expected_result_kind") or "")
        if result_kind not in RESULT_KIND_BY_CATEGORY.get(category, set()):
            findings.append(f"{prompt_id} result kind {result_kind!r} does not match category {category!r}")

        review = row.get("review")
        if not isinstance(review, dict):
            findings.append(f"{prompt_id} review must be an object")
        else:
            if review.get("reviewed") is not True:
                findings.append(f"{prompt_id} review.reviewed must be true")
            if review.get("status") != "approved":
                findings.append(f"{prompt_id} review.status must be approved")
            if str(review.get("reviewer") or "") != "xace-task-46":
                findings.append(f"{prompt_id} review.reviewer must be xace-task-46")
            if str(review.get("reviewed_at") or "") != str(manifest.get("updated") or ""):
                findings.append(f"{prompt_id} review.reviewed_at must match manifest updated date")

    return findings


def _validate_counts(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    expected_counts = manifest.get("expected_counts")
    if not isinstance(expected_counts, dict):
        return ["manifest expected_counts must be an object"]
    counter_specs = {
        "genres": Counter(str(row.get("genre") or "") for row in rows),
        "difficulty_bands": Counter(str(row.get("difficulty_band") or "") for row in rows),
        "category_ids": Counter(str(row.get("category_id") or "") for row in rows),
    }
    for key, actual in counter_specs.items():
        expected = expected_counts.get(key)
        if not isinstance(expected, dict):
            findings.append(f"manifest expected_counts.{key} must be an object")
            continue
        expected_counter = Counter({str(k): int(v) for k, v in expected.items()})
        if actual != expected_counter:
            findings.append(f"{key} counts differ: actual={dict(actual)} expected={dict(expected_counter)}")
    return findings


if __name__ == "__main__":
    raise SystemExit(main())

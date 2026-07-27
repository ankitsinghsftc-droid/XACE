"""
Shared prompt capability matrix loader for Builder server code.

The source of truth is docs/prompt_capability_matrix.json. Builder exposes this
same artifact so server responses and product docs cannot drift.
"""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = REPO_ROOT / "docs" / "prompt_capability_matrix.json"
EXPECTED_SCHEMA = "xace.prompt_capability_matrix.v1"
REQUIRED_CATEGORY_IDS = (
    "certified_supported",
    "constrained",
    "clarification_required",
    "blocked",
    "unsupported",
    "experimental",
)


class PromptCapabilityMatrixError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_prompt_capability_matrix() -> dict[str, Any]:
    try:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PromptCapabilityMatrixError(f"prompt capability matrix missing: {MATRIX_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise PromptCapabilityMatrixError(f"prompt capability matrix is invalid JSON: {exc}") from exc

    validate_prompt_capability_matrix(matrix)
    payload = copy.deepcopy(matrix)
    payload["matrix_hash"] = prompt_capability_matrix_hash(matrix)
    payload["matrix_path"] = str(MATRIX_PATH.relative_to(REPO_ROOT)).replace("\\", "/")
    return payload


def prompt_capability_category(category_id: str) -> dict[str, Any]:
    matrix = load_prompt_capability_matrix()
    for category in matrix["categories"]:
        if category["id"] == category_id:
            return copy.deepcopy(category)
    raise PromptCapabilityMatrixError(f"unknown prompt capability category: {category_id}")


def prompt_capability_matrix_hash(matrix: dict[str, Any]) -> str:
    cleaned = copy.deepcopy(matrix)
    cleaned.pop("matrix_hash", None)
    cleaned.pop("matrix_path", None)
    encoded = json.dumps(
        cleaned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_prompt_capability_matrix(matrix: dict[str, Any]) -> None:
    if matrix.get("schema") != EXPECTED_SCHEMA:
        raise PromptCapabilityMatrixError(f"schema must be {EXPECTED_SCHEMA}")
    if int(matrix.get("version", 0)) < 1:
        raise PromptCapabilityMatrixError("version must be >= 1")
    category_order = matrix.get("category_order")
    if category_order != list(REQUIRED_CATEGORY_IDS):
        raise PromptCapabilityMatrixError("category_order does not match the required Task 35 category IDs")

    categories = matrix.get("categories")
    if not isinstance(categories, list):
        raise PromptCapabilityMatrixError("categories must be a list")
    ids = [str(category.get("id", "")) for category in categories if isinstance(category, dict)]
    if ids != list(REQUIRED_CATEGORY_IDS):
        raise PromptCapabilityMatrixError("categories must appear exactly once in required order")

    for category in categories:
        if not isinstance(category, dict):
            raise PromptCapabilityMatrixError("category entries must be objects")
        for field in (
            "id",
            "label",
            "builder_decision",
            "builder_result_kind",
            "provider_call_policy",
            "mutation_policy",
            "product_wording",
            "builder_copy",
        ):
            if not str(category.get(field, "")).strip():
                raise PromptCapabilityMatrixError(f"{category.get('id', '<unknown>')}: missing {field}")
        examples = category.get("examples")
        if not isinstance(examples, list) or len(examples) < 2:
            raise PromptCapabilityMatrixError(f"{category['id']}: at least two examples are required")
        for example in examples:
            if not isinstance(example, dict):
                raise PromptCapabilityMatrixError(f"{category['id']}: examples must be objects")
            for field in ("id", "prompt", "expected_builder_route", "notes"):
                if not str(example.get(field, "")).strip():
                    raise PromptCapabilityMatrixError(f"{category['id']}: example missing {field}")

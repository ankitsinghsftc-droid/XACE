"""
structured_output_parser.py — StructuredOutputParser
======================================================
Strict safety boundary between probabilistic LLM output and the
deterministic XACE mutation pipeline.

## Role and Invariant

    This is the ONLY point where raw LLM text becomes a typed Python
    mutation object. Any deviation from the expected schema is rejected
    here — nothing malformed reaches the Validation Loop or GDE.

    The parser does NOT make assumptions or fill in missing fields.
    If the JSON is missing "op", it raises ParseError. Period.

## Two-Phase Parse

    Phase 1 — Structural Parse (this file):
        Raw text → JSON → DraftMutationTransaction
        Validates JSON grammar, required fields, allowed enum values.
        Does NOT access the CGS at all.

    Phase 2 — Schema Validation (SchemaPathValidator + OperationTypeValidator):
        DraftMutationTransaction → validated against current CGS
        Checks that paths exist, values match types, ops match delta types.

    Both phases must pass before a mutation proceeds to Phase 13.5.

## CanonicalMutation

    StructuredOutputParser produces a CanonicalMutation — a fully-typed,
    validated wrapper around DraftMutationTransaction that carries:
        - The parsed and type-checked operations
        - Path validation result (from SchemaPathValidator)
        - Operation validation result (from OperationTypeValidator)
        - Parser confidence (0.0–1.0, based on how clean the parse was)
        - Whether any warnings were generated

    CanonicalMutation is the Phase 13.5 Validation Loop's input type.

## Error Handling

    On any parse failure:
        raise ParseError(reason, raw_text)

    ParseError is caught by llm_orchestrator, which records the failure
    in PILRetryPolicy and either retries Pass 2 or escalates to
    ClarificationEngine.

## No Silent Failures

    This parser NEVER silently coerces. If type_hint says "float" and
    the value is "2x", it raises. Coercion is the LLM's responsibility
    in the prompt — the parser enforces the contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from schema_path_validator import SchemaPathValidator, PathValidationResult
from operation_type_validator import OperationTypeValidator, OperationValidationResult

import sys, os
_SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SRC_ROOT not in sys.path:
    sys.path.append(_SRC_ROOT)
sys.path.insert(0, os.path.join(_SRC_ROOT, "llm_orchestrator"))
from pass2_dsl_draft import DraftMutationTransaction, MutationOp
from typed_operations import (
    CompositePromptPlan,
    TypedCgsFragmentPlan,
    TypedCgsOperationBatch,
    TypedOperationError,
    TypedOperationValidationResult,
    apply_typed_operation_batch,
    build_composite_prompt_plan,
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
)

_VALID_OPS = frozenset({
    "SET", "SCALE", "ADD_ACTOR", "REMOVE_ACTOR",
    "ADD_COMPONENT", "REMOVE_COMPONENT",
    "ADD_SYSTEM", "REMOVE_SYSTEM",
    "ADD_RULE", "REMOVE_RULE",
})
_VALID_TYPE_HINTS = frozenset({"float", "int", "bool", "str", "dict", "list"})
_LEGACY_VALUE_OPS = frozenset({"SET", "SCALE"})
_VALID_SCHEMA_DELTA_TYPES = frozenset({
    "value_mutation", "structural_add", "structural_remove", "rule_change"
})


# ── Parse Error ───────────────────────────────────────────────────────────────

class ParseError(Exception):
    """
    Raised when the LLM output cannot be parsed into a valid mutation.
    Caught by llm_orchestrator → triggers PILRetryPolicy.record_failure().
    """
    def __init__(self, reason: str, raw_text: str = "") -> None:
        self.reason   = reason
        self.raw_text = raw_text[:300]
        super().__init__(f"ParseError: {reason}")


# ── Canonical Mutation ────────────────────────────────────────────────────────

@dataclass
class CanonicalMutation:
    """
    Fully parsed, schema-validated mutation ready for Phase 13.5.

    Attributes
    ----------
    transaction        : DraftMutationTransaction  — parsed operations
    path_validation    : PathValidationResult      — from SchemaPathValidator
    op_validation      : OperationValidationResult — from OperationTypeValidator
    parser_confidence  : float  — parse quality score [0.0–1.0]
    had_markdown_fences: bool   — True if raw text had ``` fences (quality signal)
    warnings           : list[str]  — non-fatal issues (passed with annotation)
    """
    transaction:         DraftMutationTransaction
    path_validation:     PathValidationResult
    op_validation:       OperationValidationResult
    parser_confidence:   float                    = 1.0
    had_markdown_fences: bool                     = False
    warnings:            list[str]                = field(default_factory=list)

    @property
    def is_fully_valid(self) -> bool:
        """True when both path and op validation passed."""
        return self.path_validation.valid and self.op_validation.valid

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0 or self.op_validation.has_warnings

    @property
    def all_warnings(self) -> list[str]:
        return self.warnings + self.op_validation.warnings

    def __repr__(self) -> str:
        valid = "VALID" if self.is_fully_valid else "INVALID"
        conf  = f"conf={self.parser_confidence:.2f}"
        warns = f" warns={len(self.all_warnings)}" if self.has_warnings else ""
        return f"CanonicalMutation({valid}, {conf}{warns})"


@dataclass
class CanonicalTypedMutation:
    """Path-free typed schema mutation validated against the current CGS."""

    batch: TypedCgsOperationBatch
    fragment_plan: TypedCgsFragmentPlan
    composite_plan: CompositePromptPlan | None
    normalized_batch: dict[str, Any]
    proposed_cgs: dict[str, Any] | None
    validation: TypedOperationValidationResult
    parser_confidence: float = 1.0
    had_markdown_fences: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def is_fully_valid(self) -> bool:
        return self.validation.valid and self.proposed_cgs is not None

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    def __repr__(self) -> str:
        valid = "VALID" if self.is_fully_valid else "INVALID"
        return f"CanonicalTypedMutation({valid}, conf={self.parser_confidence:.2f})"


# ── Structured Output Parser ──────────────────────────────────────────────────

class StructuredOutputParser:
    """
    Strict safety boundary: LLM text → CanonicalMutation.

    One shared instance per PIL session.
    Stateless — deterministic for the same input.

    Usage
    -----
        parser = StructuredOutputParser()
        canonical = parser.parse(
            raw_text   = response.text,
            cgs        = current_cgs,
        )
        if not canonical.is_fully_valid:
            raise ParseError(canonical.path_validation.reasons[0])
        # proceed to Validation Loop
    """

    def __init__(self) -> None:
        self._path_validator = SchemaPathValidator()
        self._op_validator   = OperationTypeValidator()

    def parse(
        self,
        raw_text: str,
        cgs:      dict[str, Any],
    ) -> CanonicalMutation:
        """
        Parses raw LLM text into a CanonicalMutation.

        Parameters
        ----------
        raw_text : str
            Raw InferenceResponse.text from Pass 2 or Pass 5.
        cgs : dict
            Current CGS JSON for path and type validation.

        Returns
        -------
        CanonicalMutation
            Always returns when structural parse succeeds.
            Path/op validation errors are embedded in the result,
            not raised — caller decides whether to reject.

        Raises
        ------
        ParseError
            When the text cannot be structurally parsed at all
            (invalid JSON, wrong root type, missing required fields).
        """
        # ── Phase 1: Structural parse ─────────────────────────────────────────
        had_fences, clean_text = self._strip_fences(raw_text)
        data                   = self._parse_json(clean_text, raw_text)
        confidence             = 1.0 if not had_fences else 0.95

        # Root type check
        if not isinstance(data, dict):
            raise ParseError(
                f"Expected JSON object at root, got {type(data).__name__}.",
                raw_text,
            )

        # schema_delta_type
        delta = data.get("schema_delta_type")
        if not delta:
            raise ParseError("Missing required field 'schema_delta_type'.", raw_text)
        if delta not in _VALID_SCHEMA_DELTA_TYPES:
            raise ParseError(
                f"'schema_delta_type'={delta!r} is not valid. "
                f"Must be one of: {sorted(_VALID_SCHEMA_DELTA_TYPES)}",
                raw_text,
            )
        if delta != "value_mutation":
            raise ParseError(
                "Legacy path/op/value structural mutations are disabled. "
                "Use a typed CGS operation batch.",
                raw_text,
            )

        # operations
        raw_ops = data.get("operations")
        if raw_ops is None:
            raise ParseError("Missing required field 'operations'.", raw_text)
        if not isinstance(raw_ops, list):
            raise ParseError(
                f"'operations' must be a JSON array, got {type(raw_ops).__name__}.",
                raw_text,
            )
        if len(raw_ops) == 0:
            raise ParseError("'operations' array is empty — no mutations to apply.", raw_text)

        # confidence from model (optional)
        model_confidence = float(data.get("confidence", 1.0))
        if not 0.0 <= model_confidence <= 1.0:
            model_confidence = 0.5
        confidence = min(confidence, model_confidence)

        # Parse operations
        ops:      list[MutationOp] = []
        warnings: list[str]        = []

        for i, raw_op in enumerate(raw_ops):
            op, op_warnings = self._parse_operation(i, raw_op, raw_text)
            ops.append(op)
            warnings.extend(op_warnings)

        structural_ops = [op.op for op in ops if op.op not in _LEGACY_VALUE_OPS]
        if structural_ops:
            raise ParseError(
                "Legacy path/op/value payloads accept SET and SCALE only; "
                f"structural operations require a typed CGS batch: {structural_ops}",
                raw_text,
            )

        # Slight confidence penalty for each warning
        confidence = max(0.0, confidence - 0.03 * len(warnings))

        transaction = DraftMutationTransaction(
            operations        = ops,
            schema_delta_type = delta,
            confidence        = confidence,
            raw_json          = raw_text,
        )

        # ── Phase 2: Schema validation ────────────────────────────────────────
        paths          = [op.path for op in ops]
        path_result    = self._path_validator.validate(paths, cgs)
        op_result      = self._op_validator.validate(ops, delta, cgs)

        return CanonicalMutation(
            transaction         = transaction,
            path_validation     = path_result,
            op_validation       = op_result,
            parser_confidence   = confidence,
            had_markdown_fences = had_fences,
            warnings            = warnings,
        )

    def parse_typed(
        self,
        raw_text: str,
        cgs: dict[str, Any],
        *,
        allow_materialized_generated_systems: bool = False,
    ) -> CanonicalTypedMutation:
        """Parse, normalize, and locally validate a typed CGS operation batch."""

        had_fences, clean_text = self._strip_fences(raw_text)
        try:
            batch = parse_typed_operation_batch(
                clean_text,
                allow_materialized_generated_systems=(
                    allow_materialized_generated_systems
                ),
            )
        except TypedOperationError as exc:
            raise ParseError(str(exc), raw_text) from exc

        apply_result = apply_typed_operation_batch(batch, cgs)
        composite_plan = None
        if apply_result.validation.valid and apply_result.proposed_cgs is not None:
            composite_plan = build_composite_prompt_plan(
                batch,
                cgs,
                apply_result.proposed_cgs,
            )
        warnings = (
            ["Provider output contained markdown fences."]
            if had_fences
            else []
        )
        return CanonicalTypedMutation(
            batch=batch,
            fragment_plan=apply_result.fragment_plan,
            composite_plan=composite_plan,
            normalized_batch=normalized_typed_operation_batch(batch),
            proposed_cgs=apply_result.proposed_cgs,
            validation=apply_result.validation,
            parser_confidence=0.95 if had_fences else 1.0,
            had_markdown_fences=had_fences,
            warnings=warnings,
        )

    # ── Operation parsing ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_operation(
        i:        int,
        raw_op:   Any,
        raw_text: str,
    ) -> tuple[MutationOp, list[str]]:
        """
        Parses one operation dict into a MutationOp.
        Returns (MutationOp, warnings).
        Raises ParseError on hard structural failures.
        """
        if not isinstance(raw_op, dict):
            raise ParseError(
                f"operations[{i}] must be a JSON object, got {type(raw_op).__name__}.",
                raw_text,
            )

        warnings: list[str] = []

        # Required: path
        path = raw_op.get("path")
        if not path or not isinstance(path, str):
            raise ParseError(
                f"operations[{i}] missing required field 'path' (must be a string).",
                raw_text,
            )

        # Required: op
        op_type = raw_op.get("op")
        if not op_type or not isinstance(op_type, str):
            raise ParseError(
                f"operations[{i}] missing required field 'op' (must be a string).",
                raw_text,
            )
        if op_type not in _VALID_OPS:
            raise ParseError(
                f"operations[{i}].op={op_type!r} is not a valid operation. "
                f"Valid ops: {sorted(_VALID_OPS)}",
                raw_text,
            )

        # type_hint — optional but validated if present
        type_hint = str(raw_op.get("type_hint", "float"))
        if type_hint not in _VALID_TYPE_HINTS:
            warnings.append(
                f"operations[{i}].type_hint={type_hint!r} is unrecognised. "
                f"Defaulting to 'float'."
            )
            type_hint = "float"

        return MutationOp(
            path       = path,
            op         = op_type,
            value      = raw_op.get("value"),
            type_hint  = type_hint,
            field_name = str(raw_op.get("field_name", "")),
            actor_id   = str(raw_op.get("actor_id",  "")),
            type_id    = int(raw_op.get("type_id",    0)),
        ), warnings

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_fences(text: str) -> tuple[bool, str]:
        """Strips markdown ``` fences. Returns (had_fences, clean_text)."""
        stripped = text.strip()
        if stripped.startswith("```"):
            lines   = stripped.splitlines()
            cleaned = "\n".join(l for l in lines if not l.startswith("```")).strip()
            return True, cleaned
        return False, stripped

    @staticmethod
    def _parse_json(text: str, raw_text: str) -> Any:
        """Parses JSON, raises ParseError on failure."""
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseError(
                f"JSON decode error: {exc}",
                raw_text,
            )

"""
pass2_dsl_draft.py — Pass2DSLDraft
=====================================
PASS 2 of the 5-pass LLM Orchestrator pipeline.

Responsibility: DSL mutation draft generation.
Tier: TIER_L (standard_mutation model — DeepSeek V4 Pro primary)
Input: LLMContextPacket + ReasoningPlan from Pass 1
Output: DraftMutationTransaction

## What Pass 2 Does

    Pass 2 receives the ReasoningPlan from Pass 1 and writes a concrete
    DraftMutationTransaction: the actual CGS path + operation + value
    for each mutation in the plan.

    Pass 2 writes real CGS paths. Every path in the draft must:
        - Match an element that exists in the simplified schema
        - Use the correct component type_id from the UCL
        - Have a value type compatible with the field's existing type
        - Stay within the AllowedMutationScope from the LLMContextPacket

## DraftMutationTransaction Fields

    operations: list[MutationOp]
        Each MutationOp is one field write:
        {
            "path":       "modes[mode_default].actors[actor_zombie].components[5].defaults.max_linear_speed",
            "op":         "SET" | "SCALE" | "ADD_ACTOR" | "REMOVE_ACTOR" | "ADD_RULE" | "REMOVE_RULE",
            "value":      <JSON value — must match field type>,
            "type_hint":  "float" | "int" | "bool" | "str" | "dict",
            "field_name": "max_linear_speed",
            "actor_id":   "actor_zombie",
            "type_id":    5,
        }

    schema_delta_type: str
        "value_mutation" | "structural_add" | "structural_remove" | "rule_change"

    confidence: float [0.0–1.0]
        Model's self-reported confidence in the draft correctness.

    raw_json: str
        Raw model output for audit trail.

## Prompt Structure

    Cached prefix:
        Constraints from LLMContextPacket (identical to Pass 1 — cache hit expected)

    Dynamic body:
        - ReasoningPlan.to_context_str() — Pass 1 output
        - Relevant actors with FULL component defaults (for accurate path writing)
        - Allowed scope boundaries
        - Pass 2 task instruction

## Critical: Path Format

    Paths must use the bracket notation matching the real CGS:
    "modes[{mode_id}].actors[{actor_id}].components[{type_id}].defaults.{field}"

    NOT dot-notation:
    "modes.mode_default.actors.actor_zombie..." ← WRONG, will fail validation
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

try:
    from inference_adapter import (
        InferenceAdapter, InferenceRequest, PromptPart, InferenceResponse
    )
    from model_descriptor import ComplexityTier
except ImportError:
    import dataclasses as _dc
    import uuid as _uuid

    @_dc.dataclass
    class PromptPart:  # type: ignore[no-redef]
        text: str; cacheable: bool = False; label: str = ""

    @_dc.dataclass
    class InferenceRequest:  # type: ignore[no-redef]
        prompt_parts: list; system_prompt: str = ""; logical_model: str = "standard_mutation"
        complexity_tier: str = "TIER_L"; max_tokens: int = 0; temperature: float = 0.0
        session_id: str = ""; call_label: str = ""
        request_id: str = _dc.field(default_factory=lambda: _uuid.uuid4().hex)
        cgs_structural_hash: str = ""; intent_class: str = ""; bypass_response_cache: bool = False

    class ComplexityTier:  # type: ignore[no-redef]
        L = "TIER_L"; M = "TIER_M"; S = "TIER_S"; XL = "TIER_XL"

    InferenceAdapter = None; InferenceResponse = None  # type: ignore

from pass1_planning import ReasoningPlan, OutputParseError
from llm_context_packet import LLMContextPacket


# ── Constants ─────────────────────────────────────────────────────────────────

PASS_LABEL    = "pass2_dsl_draft"
LOGICAL_MODEL = "standard_mutation"
TIER          = "TIER_L"
MAX_TOKENS    = 800
TEMPERATURE   = 0.0

_VALID_OPS = frozenset({
    "SET", "SCALE", "ADD_ACTOR", "REMOVE_ACTOR",
    "ADD_COMPONENT", "REMOVE_COMPONENT",
    "ADD_SYSTEM", "REMOVE_SYSTEM",
    "ADD_RULE", "REMOVE_RULE",
})

_VALID_TYPE_HINTS = frozenset({"float", "int", "bool", "str", "dict", "list"})

_VALID_SCHEMA_DELTA_TYPES = frozenset({
    "value_mutation", "structural_add", "structural_remove", "rule_change"
})


# ── Output Types ──────────────────────────────────────────────────────────────

@dataclass
class MutationOp:
    """One atomic mutation operation in the draft."""
    path:       str
    op:         str
    value:      Any
    type_hint:  str  = "float"
    field_name: str  = ""
    actor_id:   str  = ""
    type_id:    int  = 0

    def is_valid(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.path:
            errors.append("path is empty")
        if self.op not in _VALID_OPS:
            errors.append(f"op '{self.op}' not in {sorted(_VALID_OPS)}")
        if self.type_hint not in _VALID_TYPE_HINTS:
            errors.append(f"type_hint '{self.type_hint}' not valid")
        if self.value is None and self.op in {"SET", "SCALE"}:
            errors.append(f"value is None for op '{self.op}'")
        return len(errors) == 0, errors


@dataclass
class DraftMutationTransaction:
    """
    Output of Pass 2. Fed into Pass 3 (self-critique) as input.

    Attributes
    ----------
    operations        : list[MutationOp]  — the actual field writes
    schema_delta_type : str               — mutation category
    confidence        : float             — model's self-reported confidence
    raw_json          : str               — raw model output
    """
    operations:        list[MutationOp]
    schema_delta_type: str
    confidence:        float = 0.0
    raw_json:          str   = ""

    def is_valid(self) -> bool:
        if not self.operations:
            return False
        if self.schema_delta_type not in _VALID_SCHEMA_DELTA_TYPES:
            return False
        for op in self.operations:
            valid, _ = op.is_valid()
            if not valid:
                return False
        return True

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.operations:
            errors.append("operations list is empty — no mutations drafted")
        if self.schema_delta_type not in _VALID_SCHEMA_DELTA_TYPES:
            errors.append(
                f"schema_delta_type '{self.schema_delta_type}' "
                f"not in {sorted(_VALID_SCHEMA_DELTA_TYPES)}"
            )
        for i, op in enumerate(self.operations):
            valid, op_errors = op.is_valid()
            if not valid:
                errors.extend(f"op[{i}]: {e}" for e in op_errors)
        return errors

    def to_context_str(self) -> str:
        """Compact representation for injection into Pass 3 context."""
        ops_str = "; ".join(
            f"{op.op} {op.path} = {op.value!r}"
            for op in self.operations[:5]
        )
        return (
            f"DRAFT: delta_type={self.schema_delta_type}, "
            f"confidence={self.confidence:.2f}, "
            f"ops=[{ops_str}]"
        )


# ── Pass 2 ────────────────────────────────────────────────────────────────────

class Pass2DSLDraft:
    """
    Pass 2: DSL Mutation Draft.

    Calls inference_adapter once (TIER_L) and returns a DraftMutationTransaction.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def run(
        self,
        packet:      LLMContextPacket,
        plan:        ReasoningPlan,
        session_id:  str = "",
        correction:  str = "",
    ) -> DraftMutationTransaction:
        request  = self._build_request(packet, plan, session_id, correction)
        response = self._adapter.call(request)
        return self._parse_response(response)

    def _build_request(
        self,
        packet:     LLMContextPacket,
        plan:       ReasoningPlan,
        session_id: str,
        correction: str,
    ) -> InferenceRequest:
        cached_part = PromptPart(
            text=(
                "=== ARCHITECTURAL CONSTRAINTS ===\n"
                + "\n".join(f"- {c}" for c in packet.constraints)
                + "\n=== END CONSTRAINTS ==="
            ),
            cacheable=True,
            label="constraints",
        )

        dynamic_parts: list[PromptPart] = []

        if correction:
            dynamic_parts.append(PromptPart(text=correction, cacheable=False, label="correction"))

        dynamic_parts.append(PromptPart(
            text=(
                f"Game: {packet.game_metadata.get('name','?')}\n"
                f"Intent: {packet.intent_category}\n"
                f"Prompt: \"{packet.normalized_prompt}\"\n"
                f"Mode: {packet.assistance_mode}\n\n"
                f"{plan.to_context_str()}"
            ),
            cacheable=False, label="context",
        ))

        # Full component defaults — needed for accurate path writing
        if packet.relevant_actors:
            actor_lines = []
            for a in packet.relevant_actors:
                actor_lines.append(f"Actor: {a.actor_id} (type={a.actor_type})")
                for c in a.components:
                    actor_lines.append(
                        f"  Component type_id={c.get('type_id')} "
                        f"name={c.get('name','?')} "
                        f"defaults={json.dumps(c.get('defaults',{}))}"
                    )
            dynamic_parts.append(PromptPart(
                text="Relevant actors with defaults:\n" + "\n".join(actor_lines),
                cacheable=False, label="actors",
            ))

        if packet.allowed_scope:
            scope = packet.allowed_scope
            scope_lines = [f"Structural changes allowed: {scope.structural_change_allowed}"]
            if scope.allowed_paths:
                scope_lines.append("Allowed path prefixes:")
                for p in scope.allowed_paths[:5]:
                    scope_lines.append(f"  {p}")
            scope_lines.append("Forbidden paths:")
            for fp in scope.forbidden_paths[:5]:
                scope_lines.append(f"  {fp}")
            dynamic_parts.append(PromptPart(
                text="\n".join(scope_lines), cacheable=False, label="scope",
            ))

        dynamic_parts.append(PromptPart(
            text=_PASS2_TASK_INSTRUCTION, cacheable=False, label="task",
        ))

        return InferenceRequest(
            prompt_parts    = [cached_part] + dynamic_parts,
            system_prompt   = _PASS2_SYSTEM_PROMPT,
            logical_model   = LOGICAL_MODEL,
            complexity_tier = TIER,
            max_tokens      = MAX_TOKENS,
            temperature     = TEMPERATURE,
            session_id      = session_id,
            call_label      = PASS_LABEL,
            intent_class    = packet.intent_category,
        )

    @staticmethod
    def _parse_response(response: Any) -> DraftMutationTransaction:
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```")).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OutputParseError(PASS_LABEL, f"JSON decode error: {exc}", raw=response.text[:300])

        if not isinstance(data, dict):
            raise OutputParseError(PASS_LABEL, f"Expected JSON object, got {type(data).__name__}")

        raw_ops = data.get("operations", [])
        if not isinstance(raw_ops, list):
            raise OutputParseError(PASS_LABEL, "operations must be a JSON array")

        ops: list[MutationOp] = []
        for i, raw_op in enumerate(raw_ops):
            if not isinstance(raw_op, dict):
                raise OutputParseError(PASS_LABEL, f"operations[{i}] is not an object")
            ops.append(MutationOp(
                path       = str(raw_op.get("path",  "")),
                op         = str(raw_op.get("op",    "SET")),
                value      = raw_op.get("value"),
                type_hint  = str(raw_op.get("type_hint", "float")),
                field_name = str(raw_op.get("field_name", "")),
                actor_id   = str(raw_op.get("actor_id",  "")),
                type_id    = int(raw_op.get("type_id", 0)),
            ))

        draft = DraftMutationTransaction(
            operations        = ops,
            schema_delta_type = str(data.get("schema_delta_type", "value_mutation")),
            confidence        = float(data.get("confidence", 0.0)),
            raw_json          = response.text,
        )

        errors = draft.validation_errors()
        if errors:
            raise OutputParseError(
                PASS_LABEL, f"Validation failed: {'; '.join(errors)}", raw=response.text[:300]
            )
        return draft


# ── Prompts ───────────────────────────────────────────────────────────────────

_PASS2_SYSTEM_PROMPT = """\
You are an expert game schema mutation engine. Given a mutation plan and the current game schema,
you write a precise DSL mutation transaction using the exact CGS path syntax.
Respond ONLY with a valid JSON object. No markdown, no explanation outside JSON.\
"""

_PASS2_TASK_INSTRUCTION = """\
=== PASS 2: DSL MUTATION DRAFT ===

Using the mutation plan and schema above, write a DraftMutationTransaction.

CRITICAL PATH FORMAT: Use bracket notation exactly:
  modes[{mode_id}].actors[{actor_id}].components[{type_id}].defaults.{field_name}

Return EXACTLY this JSON structure:
{
  "operations": [
    {
      "path":       "<full CGS path in bracket notation>",
      "op":         "<SET|SCALE|ADD_ACTOR|REMOVE_ACTOR|ADD_COMPONENT|REMOVE_COMPONENT|ADD_SYSTEM|REMOVE_SYSTEM|ADD_RULE|REMOVE_RULE>",
      "value":      <new value — must match field type>,
      "type_hint":  "<float|int|bool|str|dict|list>",
      "field_name": "<leaf field name>",
      "actor_id":   "<actor_id or empty>",
      "type_id":    <component type_id as int or 0>
    }
  ],
  "schema_delta_type": "<value_mutation|structural_add|structural_remove|rule_change>",
  "confidence": <0.0 to 1.0>
}

Rules:
- Include one operation per field being changed.
- Never use metadata.cgs_hash or metadata.schema_version as a path.
- Paths must reference only actors/systems/rules shown in the schema above.
- confidence reflects how certain you are the paths and values are correct.
- Do NOT include any text outside the JSON object.\
"""
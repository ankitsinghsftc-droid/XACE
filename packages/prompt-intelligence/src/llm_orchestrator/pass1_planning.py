"""
pass1_planning.py — Pass1Planning
===================================
PASS 1 of the 5-pass LLM Orchestrator pipeline.

Responsibility: Structured intent planning.
Tier: TIER_L (standard_mutation model — DeepSeek V4 Pro primary)
Output: ReasoningPlan

## What Pass 1 Does

    Pass 1 receives the assembled LLMContextPacket and produces a
    structured ReasoningPlan: a pre-commit analysis of what the mutation
    will target, what type of change it is, and what risks it carries.

    Pass 1 does NOT write DSL. No CGS paths are mutated in this pass.
    The ReasoningPlan feeds Pass 2, which uses it to write a concrete
    DraftMutationTransaction.

## ReasoningPlan Fields

    target_entities:      list[str]
        CGS entity IDs that will be touched (actor_zombie, AISystem, etc.)

    intended_mutation_type: str
        High-level mutation category:
        "field_value_set" | "field_value_scale" | "actor_add" |
        "actor_remove" | "component_add" | "component_remove" |
        "system_add" | "system_remove" | "rule_add" | "rule_modify" |
        "rule_remove" | "multi_field_set"

    component_targets:    list[dict]
        Which components are touched, with specific field names:
        [{"actor_id": "actor_zombie", "type_id": 100, "field": "current"}]

    risk_assessment:      str
        "low" | "medium" | "high"
        Pass 1's estimate of mutation risk before seeing the DSL.

    reasoning:            str
        Brief (≤200 chars) explanation of the plan. Human-readable.

    requires_recompile:   bool
        True when the planned mutation requires system graph recompilation.
        Set conservatively (prefer True over False when uncertain).

## Prompt Structure

    Cached prefix:
        - Architectural constraints from LLMContextPacket.constraints
        (marked cacheable=True → prompt_cache applies cache_control)

    Dynamic body:
        - Current normalized prompt
        - Relevant actors, systems, rules (simplified)
        - Allowed mutation scope
        - Pass 1 task instruction (JSON schema to fill)

## Output Format

    The model is prompted to return ONLY a JSON object matching the
    ReasoningPlan schema. structured_output_parser.py (Phase 13.4)
    validates and parses this JSON. Pass 1 itself does minimal parsing —
    it returns the raw InferenceResponse text and a parsed ReasoningPlan
    if parsing succeeds, or raises OutputParseError if JSON is malformed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# inference_adapter lives in packages/inference — imported via sys.path
# in production. For PIL tests we use a mock adapter (see test file).
try:
    from inference_adapter import (
        InferenceAdapter, InferenceRequest, PromptPart, InferenceResponse
    )
    from model_descriptor import ComplexityTier
except ImportError:
    # Test shim — lightweight stand-ins used when packages/inference not on sys.path
    import dataclasses as _dc
    import uuid as _uuid

    @_dc.dataclass
    class PromptPart:  # type: ignore[no-redef]
        text:      str
        cacheable: bool = False
        label:     str  = ""

    @_dc.dataclass
    class InferenceRequest:  # type: ignore[no-redef]
        prompt_parts:          list
        system_prompt:         str   = ""
        logical_model:         str   = "standard_mutation"
        complexity_tier:       str   = "TIER_L"
        max_tokens:            int   = 0
        temperature:           float = 0.0
        session_id:            str   = ""
        call_label:            str   = ""
        request_id:            str   = _dc.field(default_factory=lambda: _uuid.uuid4().hex)
        cgs_structural_hash:   str   = ""
        intent_class:          str   = ""
        bypass_response_cache: bool  = False

    class ComplexityTier:  # type: ignore[no-redef]
        L = "TIER_L"
        M = "TIER_M"
        S = "TIER_S"
        XL = "TIER_XL"

    InferenceAdapter  = None   # type: ignore[assignment]
    InferenceResponse = None   # type: ignore[assignment]

from llm_context_packet import LLMContextPacket


# ── Constants ─────────────────────────────────────────────────────────────────

PASS_LABEL    = "pass1_planning"
LOGICAL_MODEL = "standard_mutation"   # TIER_L
TIER          = "TIER_L"
MAX_TOKENS    = 512    # Planning pass needs only a compact JSON object
TEMPERATURE   = 0.0    # Deterministic planning


# ── Output Types ──────────────────────────────────────────────────────────────

_VALID_MUTATION_TYPES = frozenset({
    "field_value_set", "field_value_scale",
    "actor_add", "actor_remove",
    "component_add", "component_remove",
    "system_add", "system_remove",
    "rule_add", "rule_modify", "rule_remove",
    "multi_field_set",
})

_VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})


@dataclass
class ReasoningPlan:
    """
    Output of Pass 1. Fed directly into Pass 2 as context.

    Attributes
    ----------
    target_entities       : list[str]   — actor/system/rule IDs to touch
    intended_mutation_type: str         — mutation category (see module docstring)
    component_targets     : list[dict]  — {actor_id, type_id, field} per target
    risk_assessment       : str         — "low" | "medium" | "high"
    reasoning             : str         — brief human-readable explanation (≤200 chars)
    requires_recompile    : bool        — system graph recompile needed?
    raw_json              : str         — raw model output for audit
    """
    target_entities:        list[str]
    intended_mutation_type: str
    component_targets:      list[dict]      = field(default_factory=list)
    risk_assessment:        str             = "low"
    reasoning:              str             = ""
    requires_recompile:     bool            = False
    raw_json:               str             = ""

    def is_valid(self) -> bool:
        return (
            bool(self.target_entities)
            and self.intended_mutation_type in _VALID_MUTATION_TYPES
            and self.risk_assessment in _VALID_RISK_LEVELS
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.target_entities:
            errors.append("target_entities is empty — no entity to mutate")
        if self.intended_mutation_type not in _VALID_MUTATION_TYPES:
            errors.append(
                f"intended_mutation_type '{self.intended_mutation_type}' "
                f"not in allowed set: {sorted(_VALID_MUTATION_TYPES)}"
            )
        if self.risk_assessment not in _VALID_RISK_LEVELS:
            errors.append(
                f"risk_assessment '{self.risk_assessment}' "
                f"must be one of: {sorted(_VALID_RISK_LEVELS)}"
            )
        return errors

    def to_context_str(self) -> str:
        """Compact string representation for injection into Pass 2 context."""
        comps = ", ".join(
            f"{c.get('actor_id','?')}.comp[{c.get('type_id','?')}].{c.get('field','?')}"
            for c in self.component_targets
        )
        return (
            f"PLAN: mutation_type={self.intended_mutation_type}, "
            f"targets={self.target_entities}, "
            f"components=[{comps}], "
            f"risk={self.risk_assessment}, "
            f"recompile={self.requires_recompile}. "
            f"Reasoning: {self.reasoning[:150]}"
        )


# ── Output Parse Error ────────────────────────────────────────────────────────

class OutputParseError(Exception):
    """Raised when the model response cannot be parsed into the expected type."""
    def __init__(self, pass_label: str, reason: str, raw: str = "") -> None:
        self.pass_label = pass_label
        self.reason     = reason
        self.raw        = raw
        super().__init__(f"[{pass_label}] OutputParseError: {reason}")


# ── Pass 1 ────────────────────────────────────────────────────────────────────

class Pass1Planning:
    """
    Pass 1: Structured Intent Planning.

    Calls inference_adapter once (TIER_L) and returns a ReasoningPlan.
    Raises OutputParseError on malformed JSON or schema mismatch.

    Usage (from llm_orchestrator)
    -----
        pass1 = Pass1Planning(adapter)
        plan  = pass1.run(packet, session_id="s1", correction="")
    """

    def __init__(self, adapter: Any) -> None:
        """
        Parameters
        ----------
        adapter : InferenceAdapter
            The shared InferenceAdapter instance from packages/inference.
            Type is Any to allow test mocks without importing the real class.
        """
        self._adapter = adapter

    def run(
        self,
        packet:      LLMContextPacket,
        session_id:  str = "",
        correction:  str = "",   # injected by PILRetryPolicy on retry
    ) -> ReasoningPlan:
        """
        Runs Pass 1 and returns a ReasoningPlan.

        Parameters
        ----------
        packet : LLMContextPacket
            Assembled context from Phase 13.2 ContextAssembler.
        session_id : str
            For telemetry grouping.
        correction : str
            Non-empty on retry — prepended to dynamic section.

        Returns
        -------
        ReasoningPlan
            Parsed and validated planning output.

        Raises
        ------
        OutputParseError
            When the model returns malformed JSON or fails schema validation.
        """
        request = self._build_request(packet, session_id, correction)
        response: InferenceResponse = self._adapter.call(request)
        return self._parse_response(response)

    # ── Prompt construction ───────────────────────────────────────────────────

    def _build_request(
        self,
        packet:     LLMContextPacket,
        session_id: str,
        correction: str,
    ) -> InferenceRequest:
        """Builds the InferenceRequest for Pass 1."""

        # ── Cached prefix — architectural constraints ──────────────────────
        constraints_text = "\n".join(f"- {c}" for c in packet.constraints)
        cached_part = PromptPart(
            text=(
                "=== ARCHITECTURAL CONSTRAINTS (always apply) ===\n"
                f"{constraints_text}\n"
                "=== END CONSTRAINTS ==="
            ),
            cacheable=True,
            label="constraints",
        )

        # ── Dynamic body ──────────────────────────────────────────────────
        dynamic_parts: list[PromptPart] = []

        # Correction injection (retry only)
        if correction:
            dynamic_parts.append(PromptPart(
                text=correction,
                cacheable=False,
                label="correction",
            ))

        # Game context
        game_ctx = (
            f"Game: {packet.game_metadata.get('name','?')} "
            f"(schema_version={packet.game_metadata.get('schema_version','?')})\n"
            f"Intent: {packet.intent_category}\n"
            f"Prompt: \"{packet.normalized_prompt}\"\n"
            f"Mode: {packet.assistance_mode}"
        )
        dynamic_parts.append(PromptPart(
            text=game_ctx,
            cacheable=False,
            label="game_context",
        ))

        # Relevant schema slice
        if packet.relevant_actors:
            actor_lines = []
            for a in packet.relevant_actors:
                comps = ", ".join(
                    f"{c.get('name','?')}(type_id={c.get('type_id','?')})"
                    for c in a.components
                )
                actor_lines.append(f"  - {a.actor_id} ({a.actor_type}): [{comps}]")
            dynamic_parts.append(PromptPart(
                text="Relevant actors:\n" + "\n".join(actor_lines),
                cacheable=False,
                label="actors",
            ))

        if packet.relevant_systems:
            sys_lines = [
                f"  - {s.system_id} reads={list(s.reads)} writes={list(s.writes)}"
                for s in packet.relevant_systems
            ]
            dynamic_parts.append(PromptPart(
                text="Relevant systems:\n" + "\n".join(sys_lines),
                cacheable=False,
                label="systems",
            ))

        # Allowed scope
        if packet.allowed_scope:
            scope = packet.allowed_scope
            dynamic_parts.append(PromptPart(
                text=(
                    f"Structural changes allowed: {scope.structural_change_allowed}\n"
                    f"Max mutation depth: {scope.max_mutation_depth}"
                ),
                cacheable=False,
                label="scope",
            ))

        # Task instruction + JSON schema
        dynamic_parts.append(PromptPart(
            text=_PASS1_TASK_INSTRUCTION,
            cacheable=False,
            label="task",
        ))

        return InferenceRequest(
            prompt_parts    = [cached_part] + dynamic_parts,
            system_prompt   = _PASS1_SYSTEM_PROMPT,
            logical_model   = LOGICAL_MODEL,
            complexity_tier = TIER,
            max_tokens      = MAX_TOKENS,
            temperature     = TEMPERATURE,
            session_id      = session_id,
            call_label      = PASS_LABEL,
            intent_class    = packet.intent_category,
        )

    # ── Response parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(response: InferenceResponse) -> ReasoningPlan:
        """
        Parses the model's JSON response into a ReasoningPlan.
        Raises OutputParseError on any parsing or validation failure.
        """
        raw = response.text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw   = "\n".join(
                l for l in lines if not l.startswith("```")
            ).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OutputParseError(
                PASS_LABEL,
                f"JSON decode error: {exc}",
                raw=response.text[:300],
            )

        if not isinstance(data, dict):
            raise OutputParseError(
                PASS_LABEL,
                f"Expected JSON object, got {type(data).__name__}",
                raw=response.text[:300],
            )

        # Extract required fields
        try:
            plan = ReasoningPlan(
                target_entities        = data.get("target_entities", []),
                intended_mutation_type = data.get("intended_mutation_type", ""),
                component_targets      = data.get("component_targets", []),
                risk_assessment        = data.get("risk_assessment", "low"),
                reasoning              = str(data.get("reasoning", ""))[:200],
                requires_recompile     = bool(data.get("requires_recompile", False)),
                raw_json               = response.text,
            )
        except (TypeError, KeyError) as exc:
            raise OutputParseError(
                PASS_LABEL,
                f"Schema extraction error: {exc}",
                raw=response.text[:300],
            )

        errors = plan.validation_errors()
        if errors:
            raise OutputParseError(
                PASS_LABEL,
                f"Validation failed: {'; '.join(errors)}",
                raw=response.text[:300],
            )

        return plan


# ── Prompts ───────────────────────────────────────────────────────────────────

_PASS1_SYSTEM_PROMPT = """\
You are an expert game design assistant helping a designer modify a game schema.
You analyze the designer's intent and produce a structured mutation plan.
You must respond ONLY with a valid JSON object — no markdown, no explanation outside JSON.
The JSON must strictly match the schema provided in the task instruction.\
"""

_PASS1_TASK_INSTRUCTION = """\
=== PASS 1: STRUCTURED PLANNING ===

Analyze the designer's prompt and the game context above.
Produce a mutation plan as a single JSON object with EXACTLY these fields:

{
  "target_entities": ["<actor_id or system_id or rule_id>"],
  "intended_mutation_type": "<one of: field_value_set|field_value_scale|actor_add|actor_remove|component_add|component_remove|system_add|system_remove|rule_add|rule_modify|rule_remove|multi_field_set>",
  "component_targets": [
    {"actor_id": "<id>", "type_id": <int>, "field": "<field_name>"}
  ],
  "risk_assessment": "<low|medium|high>",
  "reasoning": "<brief explanation, max 200 chars>",
  "requires_recompile": <true|false>
}

Rules:
- target_entities must contain at least one ID from the relevant actors/systems/rules shown above.
- intended_mutation_type must be exactly one of the listed values.
- component_targets: include one entry per component field that will be changed.
- requires_recompile: set true if adding/removing systems, changing system phase, or adding/removing rules.
- Do NOT include any text outside the JSON object.\
"""
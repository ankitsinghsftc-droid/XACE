"""
pass5_final_output.py — Pass5FinalOutput
==========================================
PASS 5 of the 5-pass LLM Orchestrator pipeline.

Responsibility: Final structured mutation output assembly.
Tier: TIER_M (cheap_validation) — locked per II13
Input: LLMContextPacket + DraftMutationTransaction + DeterminismAuditResult
Output: MutationTransaction

## What Pass 5 Does

    Pass 5 assembles the final, commit-ready MutationTransaction from
    the approved draft and the determinism audit result.

    Pass 5 does NOT make additional mutations. It:
        1. Copies approved operations from the draft verbatim
        2. Attaches a final confidence_score (weighted from all passes)
        3. Sets risk_level based on Pass 3 critique + Pass 4 determinism risk
        4. Confirms schema_delta_type and required_recompile
        5. Adds a human-readable mutation_summary for the UI

    The output MutationTransaction is the handoff object from PIL to the
    Validation Loop (Phase 13.5) and ultimately to GDE.

## MutationTransaction Fields

    operations:         list[MutationOp]   — from approved draft (verbatim)
    schema_delta_type:  str                — "value_mutation" | "structural_*" | "rule_change"
    confidence_score:   float              — weighted confidence [0.0–1.0]
    risk_level:         str                — "low" | "medium" | "high"
    required_recompile: bool               — from DeterminismAuditResult
    affected_systems:   list[str]          — from DeterminismAuditResult
    mutation_summary:   str                — human-readable ≤200 chars for builder UI
    raw_json:           str                — raw model output

## II13 — Pass 5 is TIER_M (Never Break)

    Pass 5 is TIER_M. This was debated but is now LOCKED.
    The reasoning: Pass 5 is assembly + formatting, not reasoning.
    The expensive reasoning happens in Passes 1-2 (TIER_L).
    Pass 5 synthesizes what's already been produced — cheap model is sufficient.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

try:
    from inference_adapter import InferenceRequest, PromptPart
    from model_descriptor import ComplexityTier
    from structured_output import mutation_transaction_contract
except ImportError:
    import dataclasses as _dc, uuid as _uuid

    @_dc.dataclass
    class PromptPart:  # type: ignore[no-redef]
        text: str; cacheable: bool = False; label: str = ""

    @_dc.dataclass
    class InferenceRequest:  # type: ignore[no-redef]
        prompt_parts: list; system_prompt: str = ""; logical_model: str = "cheap_validation"
        complexity_tier: str = "TIER_M"; max_tokens: int = 0; temperature: float = 0.0
        session_id: str = ""; call_label: str = ""
        request_id: str = _dc.field(default_factory=lambda: _uuid.uuid4().hex)
        cgs_structural_hash: str = ""; intent_class: str = ""; bypass_response_cache: bool = False
        structured_output: Any | None = None

    class ComplexityTier:  # type: ignore[no-redef]
        L = "TIER_L"; M = "TIER_M"; S = "TIER_S"; XL = "TIER_XL"

    @dataclass(frozen=True)
    class _FallbackStructuredOutputContract:
        schema_id: str = "xace.mutation_transaction.v1"
        name: str = "xace_mutation_transaction_v1"
        schema: dict[str, Any] = field(default_factory=dict)
        description: str = "Final XACE mutation transaction envelope."
        strict: bool = True

        @property
        def schema_hash(self) -> str:
            return "sha256:fallback"

    def mutation_transaction_contract() -> _FallbackStructuredOutputContract:
        return _FallbackStructuredOutputContract(schema={
            "type": "object",
            "required": [
                "schema_delta_type", "confidence_score", "risk_level",
                "required_recompile", "mutation_summary",
            ],
        })



from pass1_planning import OutputParseError
from pass2_dsl_draft import DraftMutationTransaction, MutationOp
from pass4_determinism_audit import DeterminismAuditResult
from llm_context_packet import LLMContextPacket


PASS_LABEL    = "pass5_final_output"
LOGICAL_MODEL = "cheap_validation"   # II13: LOCKED — TIER_M
TIER          = "TIER_M"
MAX_TOKENS    = 600
TEMPERATURE   = 0.0

_VALID_RISK_LEVELS       = frozenset({"low", "medium", "high"})
_VALID_SCHEMA_DELTA_TYPES = frozenset({
    "value_mutation", "structural_add", "structural_remove", "rule_change"
})


@dataclass
class MutationTransaction:
    """
    Final output of the 5-pass pipeline.

    This is the PIL → Validation Loop handoff object.
    Validation Loop (13.5) and Safety Guard (13.9) consume this before
    handing it to MutationPlanner (13.8) → GDE.

    Attributes
    ----------
    operations         : list[MutationOp] — verbatim from approved draft
    schema_delta_type  : str
    confidence_score   : float            — weighted [0.0–1.0]
    risk_level         : str              — "low" | "medium" | "high"
    required_recompile : bool
    affected_systems   : list[str]
    mutation_summary   : str              — ≤200 chars, for builder UI
    raw_json           : str
    """
    operations:         list[MutationOp]
    schema_delta_type:  str
    confidence_score:   float             = 0.0
    risk_level:         str               = "low"
    required_recompile: bool              = False
    affected_systems:   list[str]         = field(default_factory=list)
    mutation_summary:   str               = ""
    raw_json:           str               = ""

    def is_valid(self) -> bool:
        return (
            bool(self.operations)
            and self.schema_delta_type in _VALID_SCHEMA_DELTA_TYPES
            and self.risk_level in _VALID_RISK_LEVELS
            and 0.0 <= self.confidence_score <= 1.0
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.operations:
            errors.append("operations is empty")
        if self.schema_delta_type not in _VALID_SCHEMA_DELTA_TYPES:
            errors.append(f"invalid schema_delta_type: {self.schema_delta_type!r}")
        if self.risk_level not in _VALID_RISK_LEVELS:
            errors.append(f"invalid risk_level: {self.risk_level!r}")
        if not (0.0 <= self.confidence_score <= 1.0):
            errors.append(f"confidence_score {self.confidence_score} out of [0,1]")
        return errors

    def __repr__(self) -> str:
        return (
            f"MutationTransaction({self.schema_delta_type!r}, "
            f"ops={len(self.operations)}, "
            f"conf={self.confidence_score:.2f}, "
            f"risk={self.risk_level}, "
            f"recompile={self.required_recompile})"
        )


class Pass5FinalOutput:
    """
    Pass 5: Final output assembly. TIER_M (II13 — locked).

    Assembles MutationTransaction from the approved draft + audit result.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def run(
        self,
        packet:     LLMContextPacket,
        draft:      DraftMutationTransaction,
        audit:      DeterminismAuditResult,
        session_id: str = "",
    ) -> MutationTransaction:
        request  = self._build_request(packet, draft, audit, session_id)
        response = self._adapter.call(request)
        return self._parse_response(response, draft, audit)

    def _build_request(
        self,
        packet:     LLMContextPacket,
        draft:      DraftMutationTransaction,
        audit:      DeterminismAuditResult,
        session_id: str,
    ) -> InferenceRequest:
        cached_part = PromptPart(
            text=(
                "=== ARCHITECTURAL CONSTRAINTS ===\n"
                + "\n".join(f"- {c}" for c in packet.constraints)
                + "\n=== END ==="
            ),
            cacheable=True, label="constraints",
        )

        ops_text = json.dumps(
            [{"path": op.path, "op": op.op, "value": op.value, "type_hint": op.type_hint}
             for op in draft.operations], indent=2,
        )

        dynamic_text = (
            f"=== APPROVED DRAFT ===\n"
            f"schema_delta_type: {draft.schema_delta_type}\n"
            f"draft_confidence: {draft.confidence:.2f}\n"
            f"operations:\n{ops_text}\n\n"
            f"=== DETERMINISM AUDIT ===\n"
            f"{audit.to_context_str()}\n\n"
            f"Intent: {packet.intent_category}\n"
            f"Prompt: \"{packet.normalized_prompt}\"\n"
            f"Mode: {packet.assistance_mode}"
        )

        return InferenceRequest(
            prompt_parts=[
                cached_part,
                PromptPart(text=dynamic_text, cacheable=False, label="draft_and_audit"),
                PromptPart(text=_PASS5_TASK_INSTRUCTION, cacheable=False, label="task"),
            ],
            system_prompt=_PASS5_SYSTEM_PROMPT,
            logical_model=LOGICAL_MODEL,
            complexity_tier=TIER,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            session_id=session_id,
            call_label=PASS_LABEL,
            intent_class=packet.intent_category,
            structured_output=mutation_transaction_contract(),
        )

    def _parse_response(
        self,
        response: Any,
        draft:    DraftMutationTransaction,
        audit:    DeterminismAuditResult,
    ) -> MutationTransaction:
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```")).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OutputParseError(
                PASS_LABEL, f"JSON decode error: {exc}", raw=response.text[:300]
            )

        risk = str(data.get("risk_level", "low"))
        if risk not in _VALID_RISK_LEVELS:
            risk = "low"

        delta = str(data.get("schema_delta_type", draft.schema_delta_type))
        if delta not in _VALID_SCHEMA_DELTA_TYPES:
            delta = draft.schema_delta_type

        txn = MutationTransaction(
            operations         = list(draft.operations),   # verbatim from draft
            schema_delta_type  = delta,
            confidence_score   = float(data.get("confidence_score", draft.confidence)),
            risk_level         = risk,
            required_recompile = bool(data.get("required_recompile", audit.required_recompile)),
            affected_systems   = list(audit.affected_systems),
            mutation_summary   = str(data.get("mutation_summary", ""))[:200],
            raw_json           = response.text,
        )

        errors = txn.validation_errors()
        if errors:
            raise OutputParseError(
                PASS_LABEL,
                f"MutationTransaction validation failed: {'; '.join(errors)}",
                raw=response.text[:300],
            )
        return txn


_PASS5_SYSTEM_PROMPT = """\
You are the final output stage of a game mutation pipeline.
Synthesize the approved draft and determinism audit into the final MutationTransaction.
Respond ONLY with a valid JSON object.\
"""

_PASS5_TASK_INSTRUCTION = """\
=== PASS 5: FINAL STRUCTURED OUTPUT ===

Using the APPROVED DRAFT and DETERMINISM AUDIT above, produce the final MutationTransaction.

Rules:
- Do NOT invent new operations — use the approved draft's operations verbatim.
- confidence_score = weighted average of draft confidence and audit result (penalize for risk).
- risk_level: "low" if determinism_risk=none/low and no violations; "medium" if hidden_deps exist; "high" if violations.
- mutation_summary: one sentence ≤200 chars describing what this mutation does for the designer.
- required_recompile: copy from audit result (true if audit flagged it OR structural changes).

Return EXACTLY this JSON:
{
  "schema_delta_type": "<value_mutation|structural_add|structural_remove|rule_change>",
  "confidence_score": <0.0 to 1.0>,
  "risk_level": "<low|medium|high>",
  "required_recompile": <true|false>,
  "mutation_summary": "<one sentence, ≤200 chars>"
}

Do NOT include operations in the output — they are taken verbatim from the draft.
Do NOT include any text outside the JSON.\
"""
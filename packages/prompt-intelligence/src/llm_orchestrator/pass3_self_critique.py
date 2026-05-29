"""
pass3_self_critique.py — Pass3SelfCritique
============================================
PASS 3 of the 5-pass LLM Orchestrator pipeline.

Responsibility: Self-critique of the DSL draft from Pass 2.
Tier: TIER_M (cheap_validation model — Ollama local first, DeepSeek Flash fallback)
Input: LLMContextPacket + DraftMutationTransaction from Pass 2
Output: CritiqueResult

## What Pass 3 Does

    Pass 3 acts as an internal reviewer. It reads the DraftMutationTransaction
    and checks for correctness issues before Pass 4 (determinism audit):

    Check 1 — Path Validity
        Are all paths in the draft reachable in the schema?
        Does the path use the correct bracket notation?
        Does the type_id in the path match a component that exists on that actor?

    Check 2 — Value Type Correctness
        Does the drafted value's Python type match the type_hint?
        E.g. if type_hint="float" and value="fast", that's a type mismatch.
        E.g. if type_hint="int" and value=10.5, that's a precision issue.

    Check 3 — Scope Compliance
        Does every operation path start with an allowed prefix?
        Does any path touch a forbidden domain (metadata.cgs_hash, etc.)?

    Check 4 — Unintended Modifications
        Is the draft touching actors or components not in the plan?
        E.g. if the plan targeted actor_zombie and the draft also touches
        actor_player, this is an unintended modification.

    Check 5 — Constraint Compliance
        Does the draft violate any architectural constraint?
        E.g. setting deterministic: false on a system.

## CritiqueResult Fields

    passed:            bool          — True if all checks passed
    issues:            list[str]     — Human-readable issue descriptions
    check_scores:      dict[str,bool] — Per-check pass/fail
    corrected_draft:   DraftMutationTransaction | None
        When passed=False and the model suggests a correction,
        a corrected draft may be provided. If None, Pass 2 is re-run
        with a correction prompt.
    confidence:        float         — Model's confidence in critique accuracy

## On Failure

    If passed=False:
        llm_orchestrator calls PILRetryPolicy.record_failure("pass2_dsl_draft")
        and re-runs Pass 2 with the correction prompt from the critique.
        Pass 3 itself is NOT retried — it runs once per Pass 2 draft.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

try:
    from inference_adapter import InferenceRequest, PromptPart
    from model_descriptor import ComplexityTier
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

    class ComplexityTier:  # type: ignore[no-redef]
        L = "TIER_L"; M = "TIER_M"; S = "TIER_S"; XL = "TIER_XL"

from pass1_planning import OutputParseError
from pass2_dsl_draft import DraftMutationTransaction, MutationOp
from llm_context_packet import LLMContextPacket


# ── Constants ─────────────────────────────────────────────────────────────────

PASS_LABEL    = "pass3_self_critique"
LOGICAL_MODEL = "cheap_validation"
TIER          = "TIER_M"
MAX_TOKENS    = 600
TEMPERATURE   = 0.0

_CHECK_NAMES = (
    "path_validity",
    "value_type_correctness",
    "scope_compliance",
    "unintended_modifications",
    "constraint_compliance",
)


# ── Output Types ──────────────────────────────────────────────────────────────

@dataclass
class CritiqueResult:
    """
    Output of Pass 3.

    Attributes
    ----------
    passed          : bool               — True if all checks passed
    issues          : list[str]          — Issue descriptions (empty when passed)
    check_scores    : dict[str,bool]     — Per-check results
    confidence      : float              — Model's confidence in critique
    correction_hint : str                — Targeted correction instruction for Pass 2 retry
    raw_json        : str                — Raw model output
    """
    passed:          bool
    issues:          list[str]           = field(default_factory=list)
    check_scores:    dict[str, bool]     = field(default_factory=dict)
    confidence:      float               = 0.0
    correction_hint: str                 = ""
    raw_json:        str                 = ""

    @property
    def failed_checks(self) -> list[str]:
        return [k for k, v in self.check_scores.items() if not v]

    def to_correction_prompt(self) -> str:
        """Generates a correction instruction for PILRetryPolicy injection."""
        if self.passed:
            return ""
        issues_text = "\n".join(f"  - {issue}" for issue in self.issues)
        hint = f"\n  Hint: {self.correction_hint}" if self.correction_hint else ""
        return (
            f"CORRECTION REQUIRED: The previous draft failed self-critique "
            f"with these issues:\n{issues_text}{hint}\n"
            f"Rewrite the draft to fix all issues above."
        )


# ── Pass 3 ────────────────────────────────────────────────────────────────────

class Pass3SelfCritique:
    """
    Pass 3: Self-Critique of the DSL draft.

    Runs TIER_M (cheap_validation). One call per Pass 2 draft.
    Does NOT retry itself — failure triggers Pass 2 retry via llm_orchestrator.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def run(
        self,
        packet:     LLMContextPacket,
        draft:      DraftMutationTransaction,
        session_id: str = "",
    ) -> CritiqueResult:
        request  = self._build_request(packet, draft, session_id)
        response = self._adapter.call(request)
        return self._parse_response(response)

    def _build_request(
        self,
        packet:     LLMContextPacket,
        draft:      DraftMutationTransaction,
        session_id: str,
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

        # Draft summary for critique
        ops_text = json.dumps(
            [{"path": op.path, "op": op.op, "value": op.value,
              "type_hint": op.type_hint} for op in draft.operations],
            indent=2,
        )

        # Allowed scope context
        scope_text = ""
        if packet.allowed_scope:
            scope = packet.allowed_scope
            allowed = list(scope.allowed_paths)[:5] if scope.allowed_paths else ["(unrestricted)"]
            forbidden = list(scope.forbidden_paths)[:5]
            scope_text = (
                f"\nAllowed path prefixes: {allowed}"
                f"\nForbidden paths: {forbidden}"
                f"\nStructural changes allowed: {scope.structural_change_allowed}"
            )

        # Actor context for path validation
        actor_ids = [a.actor_id for a in packet.relevant_actors]
        comp_map = {}
        for a in packet.relevant_actors:
            comp_map[a.actor_id] = [c.get("type_id") for c in a.components]

        dynamic_text = (
            f"=== DRAFT TO CRITIQUE ===\n"
            f"schema_delta_type: {draft.schema_delta_type}\n"
            f"confidence: {draft.confidence}\n"
            f"operations:\n{ops_text}\n\n"
            f"=== CONTEXT ===\n"
            f"Intent: {packet.intent_category}\n"
            f"Prompt: \"{packet.normalized_prompt}\"\n"
            f"Relevant actors: {actor_ids}\n"
            f"Actor→component_type_ids: {json.dumps(comp_map)}"
            f"{scope_text}"
        )

        return InferenceRequest(
            prompt_parts=[
                cached_part,
                PromptPart(text=dynamic_text, cacheable=False, label="draft_context"),
                PromptPart(text=_PASS3_TASK_INSTRUCTION, cacheable=False, label="task"),
            ],
            system_prompt   = _PASS3_SYSTEM_PROMPT,
            logical_model   = LOGICAL_MODEL,
            complexity_tier = TIER,
            max_tokens      = MAX_TOKENS,
            temperature     = TEMPERATURE,
            session_id      = session_id,
            call_label      = PASS_LABEL,
            intent_class    = packet.intent_category,
        )

    @staticmethod
    def _parse_response(response: Any) -> CritiqueResult:
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```")).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Parse failure in the critique pass itself — return a safe "failed" result
            # rather than raising, so llm_orchestrator can handle it gracefully.
            return CritiqueResult(
                passed=False,
                issues=[f"Pass 3 parse error: {exc}"],
                check_scores={k: False for k in _CHECK_NAMES},
                confidence=0.0,
                correction_hint="Rewrite the draft with correct JSON format.",
                raw_json=response.text,
            )

        passed      = bool(data.get("passed", False))
        issues      = [str(i) for i in data.get("issues", [])]
        check_scores = {k: bool(data.get("check_scores", {}).get(k, passed))
                        for k in _CHECK_NAMES}
        confidence  = float(data.get("confidence", 0.0))
        hint        = str(data.get("correction_hint", ""))

        return CritiqueResult(
            passed          = passed,
            issues          = issues,
            check_scores    = check_scores,
            confidence      = confidence,
            correction_hint = hint,
            raw_json        = response.text,
        )


# ── Prompts ───────────────────────────────────────────────────────────────────

_PASS3_SYSTEM_PROMPT = """\
You are a strict DSL mutation reviewer. Your job is to find errors in mutation drafts
before they are applied to a game schema. Be conservative: if you are unsure, flag it.
Respond ONLY with a valid JSON object.\
"""

_PASS3_TASK_INSTRUCTION = """\
=== PASS 3: SELF-CRITIQUE ===

Review the DRAFT above against the CONTEXT and CONSTRAINTS.
Check ALL of the following:

1. path_validity: Every path uses correct bracket notation (modes[id].actors[id].components[type_id].defaults.field). The actor_id and type_id in the path exist in the relevant actors list.
2. value_type_correctness: The value's type matches type_hint (float→number, int→integer, bool→true/false, str→string).
3. scope_compliance: Every path starts with an allowed prefix. No path touches forbidden paths.
4. unintended_modifications: The draft only modifies entities mentioned in the intent/prompt. No extra actors/systems modified.
5. constraint_compliance: No operation sets deterministic to false. No path uses metadata.cgs_hash or metadata.schema_version.

Return EXACTLY this JSON:
{
  "passed": <true|false>,
  "issues": ["<issue description>"],
  "check_scores": {
    "path_validity": <true|false>,
    "value_type_correctness": <true|false>,
    "scope_compliance": <true|false>,
    "unintended_modifications": <true|false>,
    "constraint_compliance": <true|false>
  },
  "confidence": <0.0 to 1.0>,
  "correction_hint": "<specific instruction for fixing the draft, or empty string if passed>"
}

passed must be true only if ALL five checks are true.
issues must be empty when passed is true.
Do NOT include any text outside the JSON object.\
"""
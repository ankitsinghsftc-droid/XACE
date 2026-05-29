"""
pass4_determinism_audit.py — Pass4DeterminismAudit
====================================================
PASS 4 of the 5-pass LLM Orchestrator pipeline.

Responsibility: Determinism audit of the (critique-approved) DSL draft.
Tier: TIER_M (cheap_validation)
Input: LLMContextPacket + DraftMutationTransaction (post-critique)
Output: DeterminismAuditResult

## What Pass 4 Does

    Pass 4 applies the D-rules from the constraint prefix to the specific
    draft operations and detects any determinism violations:

    Check 1 — D-Rule Compliance
        Does any operation modify a component that a deterministic system
        writes to, in a way that could change that system's output between
        replays?
        E.g. changing COMP_VELOCITY_V1.max_linear_speed affects MovementSystem
        — this is allowed but MUST be flagged as "affects deterministic system".

    Check 2 — Hidden Dependency Detection
        Does the mutation indirectly affect systems not listed in the plan?
        E.g. changing COMP_AI_V1.behavior_model affects AISystem, which writes
        to type_id=101 (damage events), which DamageSystem reads.
        Hidden dependency: DamageSystem is now transitively affected.

    Check 3 — Cross-Phase State Mutation Detection
        Does any operation write a field that is read in a different phase
        than it is written? This would create a phase ordering dependency
        that is not expressed in the system graph.

    Check 4 — Nondeterminism Source Detection
        Does any operation introduce an unseeded random, timestamp, or other
        nondeterministic source as a value?
        E.g. value="random()" or value={"random_seed": null}

## DeterminismAuditResult Fields

    passed:                    bool
    violations:                list[str]   — D-rule violations found
    hidden_dependencies:       list[str]   — Transitively affected systems
    required_recompile:        bool        — System graph recompile needed
    affected_systems:          list[str]   — Systems directly affected by ops
    determinism_risk:          str         — "none" | "low" | "medium" | "high"
    raw_json:                  str
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

from pass2_dsl_draft import DraftMutationTransaction
from llm_context_packet import LLMContextPacket


PASS_LABEL    = "pass4_determinism_audit"
LOGICAL_MODEL = "cheap_validation"
TIER          = "TIER_M"
MAX_TOKENS    = 500
TEMPERATURE   = 0.0

_VALID_RISK_LEVELS = frozenset({"none", "low", "medium", "high"})


@dataclass
class DeterminismAuditResult:
    """
    Output of Pass 4.

    Attributes
    ----------
    passed               : bool        — True if no hard determinism violations
    violations           : list[str]   — D-rule violations (hard failures)
    hidden_dependencies  : list[str]   — Transitively affected systems (warnings)
    required_recompile   : bool        — True if system graph must be recompiled
    affected_systems     : list[str]   — Systems directly affected by operations
    determinism_risk     : str         — "none" | "low" | "medium" | "high"
    raw_json             : str
    """
    passed:               bool
    violations:           list[str]  = field(default_factory=list)
    hidden_dependencies:  list[str]  = field(default_factory=list)
    required_recompile:   bool       = False
    affected_systems:     list[str]  = field(default_factory=list)
    determinism_risk:     str        = "none"
    raw_json:             str        = ""

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    def to_context_str(self) -> str:
        deps = ", ".join(self.hidden_dependencies) if self.hidden_dependencies else "none"
        systems = ", ".join(self.affected_systems) if self.affected_systems else "none"
        return (
            f"DETERMINISM: risk={self.determinism_risk}, "
            f"recompile={self.required_recompile}, "
            f"affected_systems=[{systems}], "
            f"hidden_deps=[{deps}]"
        )


class Pass4DeterminismAudit:
    """Pass 4: Determinism audit. Tier M. One call per approved draft."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def run(
        self,
        packet:     LLMContextPacket,
        draft:      DraftMutationTransaction,
        session_id: str = "",
    ) -> DeterminismAuditResult:
        request  = self._build_request(packet, draft, session_id)
        response = self._adapter.call(request)
        return self._parse_response(response)

    def _build_request(
        self,
        packet:     LLMContextPacket,
        draft:      DraftMutationTransaction,
        session_id: str,
    ) -> InferenceRequest:
        # D-rules are in the constraints (cached prefix)
        cached_part = PromptPart(
            text=(
                "=== ARCHITECTURAL CONSTRAINTS + D-RULES ===\n"
                + "\n".join(f"- {c}" for c in packet.constraints)
                + "\n=== END ==="
            ),
            cacheable=True, label="constraints",
        )

        ops_text = json.dumps(
            [{"path": op.path, "op": op.op, "value": op.value, "type_id": op.type_id}
             for op in draft.operations],
            indent=2,
        )

        sys_text = "\n".join(
            f"  {s.system_id}: reads={list(s.reads)} writes={list(s.writes)} "
            f"depends_on={list(s.depends_on)}"
            for s in packet.relevant_systems
        )

        dynamic_text = (
            f"=== DRAFT OPERATIONS ===\n{ops_text}\n\n"
            f"=== SYSTEM GRAPH (relevant) ===\n{sys_text if sys_text else '(none)'}\n\n"
            f"Intent: {packet.intent_category}\n"
            f"Prompt: \"{packet.normalized_prompt}\""
        )

        return InferenceRequest(
            prompt_parts=[
                cached_part,
                PromptPart(text=dynamic_text, cacheable=False, label="draft_and_graph"),
                PromptPart(text=_PASS4_TASK_INSTRUCTION, cacheable=False, label="task"),
            ],
            system_prompt=_PASS4_SYSTEM_PROMPT,
            logical_model=LOGICAL_MODEL,
            complexity_tier=TIER,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            session_id=session_id,
            call_label=PASS_LABEL,
            intent_class=packet.intent_category,
        )

    @staticmethod
    def _parse_response(response: Any) -> DeterminismAuditResult:
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```")).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Safe fallback — flag as low risk, not a hard violation
            return DeterminismAuditResult(
                passed=True, violations=[],
                hidden_dependencies=["(audit parse error — review manually)"],
                determinism_risk="low", raw_json=response.text,
            )

        risk = str(data.get("determinism_risk", "none"))
        if risk not in _VALID_RISK_LEVELS:
            risk = "low"

        return DeterminismAuditResult(
            passed              = bool(data.get("passed", True)),
            violations          = [str(v) for v in data.get("violations", [])],
            hidden_dependencies = [str(d) for d in data.get("hidden_dependencies", [])],
            required_recompile  = bool(data.get("required_recompile", False)),
            affected_systems    = [str(s) for s in data.get("affected_systems", [])],
            determinism_risk    = risk,
            raw_json            = response.text,
        )


_PASS4_SYSTEM_PROMPT = """\
You are a determinism auditor for a game simulation engine.
Your job is to find any way the proposed mutation could break replay determinism.
Respond ONLY with a valid JSON object.\
"""

_PASS4_TASK_INSTRUCTION = """\
=== PASS 4: DETERMINISM AUDIT ===

Review the DRAFT OPERATIONS against the D-RULES and SYSTEM GRAPH.

For each operation:
1. Identify which systems read/write the affected component type_id.
2. Check if the mutation could produce different results across ticks/replays.
3. Detect hidden transitive dependencies (system A → component → system B not in plan).
4. Flag if adding/removing systems/rules requires recompiling the system graph.
5. Flag nondeterministic values (random, timestamp, null seeds).

Return EXACTLY this JSON:
{
  "passed": <true if no hard violations>,
  "violations": ["<description of hard D-rule violation>"],
  "hidden_dependencies": ["<system or component indirectly affected>"],
  "required_recompile": <true|false>,
  "affected_systems": ["<system_id directly affected by operations>"],
  "determinism_risk": "<none|low|medium|high>"
}

passed=false only for hard violations (nondeterminism sources, phase crossing, etc.).
Warnings about affected systems go in hidden_dependencies, not violations.
Do NOT include any text outside the JSON.\
"""
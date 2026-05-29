"""
diagnostic_orchestrator.py — DiagnosticOrchestrator
=====================================================
Routes QueryExplain and DebugIssue intents through a 2-pass
explain→suggest flow. Never commits mutations directly.

## II7 Compliance

    This is the ONLY path for diagnostic intents. The 5-pass mutation
    pipeline (LLMOrchestrator) raises DiagnosticIntentError if a
    QueryExplain or DebugIssue intent reaches it. PILPipeline catches
    that and routes here instead.

## Two-Pass Flow

    PASS 1 — Analysis (TIER_M: cheap_validation)
        Reads:
            - Relevant systems from CGS (matched to the query topic)
            - CGS structural hash (to identify the schema version)
            - Memory: design vision + known behavioral patterns
            - Runtime telemetry if provided (tick timing, error logs)
        Produces:
            - Structured explanation of the queried system/issue
            - Root cause analysis for DebugIssue intents
            - Key facts relevant to the question

    PASS 2 — Suggest (TIER_M: cheap_validation, conditional)
        Only runs when:
            - Pass 1 identified a clear actionable fix
            - The fix can be expressed as a single mutation (not a redesign)
            - The intent_category is DebugIssue (not QueryExplain)
        Produces:
            - Optional IntentObject (prompt that the mutation pipeline
              would process to implement the fix)
            - NOT a committed MutationTransaction — just a suggestion

    This 2-pass approach is dramatically cheaper than the 5-pass mutation
    pipeline and appropriate for read-only queries.

## DiagnosticResult

    explanation           : str   — human-readable explanation
    root_cause            : str   — for DebugIssue: identified root cause
    affected_systems      : list[str]
    suggested_transaction : MutationTransaction | None  — optional fix
    suggested_prompt      : str   — natural language version of the fix
    confidence            : float
    pass1_raw             : str   — raw Pass 1 output for audit
    pass2_raw             : str   — raw Pass 2 output for audit
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import sys, os

_dir = os.path.dirname(__file__)
for sub in (
    "intent_intake", "context_assembler", "llm_orchestrator",
    "output_parser", "validation_loop",
):
    sys.path.insert(0, os.path.join(_dir, sub))

from intent_envelope import IntentEnvelope, PILIntentCategory

try:
    from inference_adapter import InferenceRequest, PromptPart
    from model_descriptor import ComplexityTier
except ImportError:
    import dataclasses as _dc, uuid as _uuid

    @_dc.dataclass
    class PromptPart:                                  # type: ignore[no-redef]
        text: str; cacheable: bool = False; label: str = ""

    @_dc.dataclass
    class InferenceRequest:                            # type: ignore[no-redef]
        prompt_parts: list; system_prompt: str = ""
        logical_model: str = "cheap_validation"
        complexity_tier: str = "TIER_M"; max_tokens: int = 0
        temperature: float = 0.0; session_id: str = ""
        call_label: str = ""
        request_id: str = _dc.field(default_factory=lambda: _uuid.uuid4().hex)
        cgs_structural_hash: str = ""; intent_class: str = ""
        bypass_response_cache: bool = False

    class ComplexityTier:                              # type: ignore[no-redef]
        M = "TIER_M"; L = "TIER_L"; S = "TIER_S"; XL = "TIER_XL"


# ── Constants ─────────────────────────────────────────────────────────────────

PASS1_LABEL    = "diagnostic_analysis"
PASS2_LABEL    = "diagnostic_suggest"
LOGICAL_MODEL  = "cheap_validation"   # TIER_M — diagnostic is read-only
TIER           = "TIER_M"
PASS1_TOKENS   = 800
PASS2_TOKENS   = 400
TEMPERATURE    = 0.0


# ── Diagnostic Result ─────────────────────────────────────────────────────────

@dataclass
class DiagnosticResult:
    """
    Output of DiagnosticOrchestrator.run().

    Attributes
    ----------
    explanation           : str   — human-readable explanation or analysis
    root_cause            : str   — DebugIssue: identified root cause
    affected_systems      : list[str]
    suggested_transaction : Any | None  — optional MutationTransaction
    suggested_prompt      : str   — natural language mutation suggestion
    confidence            : float
    intent_category       : str
    pass1_raw             : str
    pass2_raw             : str
    """
    explanation:           str
    root_cause:            str               = ""
    affected_systems:      list[str]         = field(default_factory=list)
    suggested_transaction: Any | None        = None
    suggested_prompt:      str               = ""
    confidence:            float             = 0.0
    intent_category:       str               = ""
    pass1_raw:             str               = ""
    pass2_raw:             str               = ""

    @property
    def has_suggestion(self) -> bool:
        return bool(self.suggested_prompt or self.suggested_transaction)

    def __repr__(self) -> str:
        sug = " [+suggestion]" if self.has_suggestion else ""
        return (
            f"DiagnosticResult({self.intent_category!r}, "
            f"conf={self.confidence:.2f}{sug})"
        )


# ── Diagnostic Orchestrator ───────────────────────────────────────────────────

class DiagnosticOrchestrator:
    """
    Runs the 2-pass diagnostic pipeline for explain/debug intents.

    One instance per PIL session (or shared — it is stateless).

    Usage
    -----
        orch   = DiagnosticOrchestrator(adapter)
        result = orch.run(envelope, cgs, mode="COLLABORATIVE")
        print(result.explanation)
        if result.has_suggestion:
            show_suggestion(result.suggested_prompt)
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def run(
        self,
        envelope:   IntentEnvelope,
        cgs:        dict[str, Any],
        mode:       str            = "COLLABORATIVE",
        session_id: str            = "",
        telemetry:  dict | None    = None,
    ) -> DiagnosticResult:
        """
        Runs the 2-pass diagnostic flow.

        Parameters
        ----------
        envelope   : IntentEnvelope — classified diagnostic intent
        cgs        : dict           — current CGS for system lookup
        mode       : str            — assistance mode
        session_id : str            — telemetry
        telemetry  : dict | None    — optional engine runtime metrics

        Returns
        -------
        DiagnosticResult
        """
        is_debug = envelope.intent_category == PILIntentCategory.DEBUG_ISSUE

        # ── Pass 1: Analysis ──────────────────────────────────────────────────
        p1_request  = self._build_pass1(envelope, cgs, telemetry, session_id)
        p1_response = self._adapter.call(p1_request)
        p1_data     = self._parse_pass1(p1_response.text)

        explanation    = p1_data.get("explanation", p1_response.text[:500])
        root_cause     = p1_data.get("root_cause", "")
        affected_sys   = p1_data.get("affected_systems", [])
        is_actionable  = bool(p1_data.get("is_actionable", False))
        p1_confidence  = float(p1_data.get("confidence", 0.7))

        # ── Pass 2: Suggest (conditional) ────────────────────────────────────
        suggested_prompt = ""
        p2_raw           = ""

        if is_debug and is_actionable:
            p2_request   = self._build_pass2(envelope, p1_data, cgs, session_id)
            p2_response  = self._adapter.call(p2_request)
            p2_data      = self._parse_pass2(p2_response.text)
            suggested_prompt = p2_data.get("suggested_prompt", "")
            p2_raw           = p2_response.text

        return DiagnosticResult(
            explanation       = explanation,
            root_cause        = root_cause,
            affected_systems  = affected_sys,
            suggested_prompt  = suggested_prompt,
            confidence        = p1_confidence,
            intent_category   = envelope.intent_category,
            pass1_raw         = p1_response.text,
            pass2_raw         = p2_raw,
        )

    # ── Pass 1 construction ───────────────────────────────────────────────────

    @staticmethod
    def _build_pass1(
        envelope:  IntentEnvelope,
        cgs:       dict[str, Any],
        telemetry: dict | None,
        session_id: str,
    ) -> InferenceRequest:
        """Builds the Pass 1 analysis request."""

        # Cached: game name + system overview (stable across calls for same game)
        game_name  = cgs.get("metadata", {}).get("name", "Unknown Game")
        cgs_hash   = cgs.get("metadata", {}).get("cgs_hash", "")
        system_ids = _collect_system_ids(cgs)

        cached_part = PromptPart(
            text=(
                f"=== GAME CONTEXT ===\n"
                f"Game: {game_name} (cgs_hash={cgs_hash[:8]})\n"
                f"All systems: {', '.join(system_ids)}\n"
                f"=== END CONTEXT ==="
            ),
            cacheable=True,
            label="game_context",
        )

        # Dynamic: the actual query + relevant schema excerpt
        relevant_sys = _relevant_systems(envelope.normalized_text, cgs)
        sys_text = "\n".join(
            f"  {s['id']}: reads={s.get('reads',[])} writes={s.get('writes',[])} "
            f"phase={s.get('phase','?')} deterministic={s.get('deterministic',True)}"
            for s in relevant_sys[:5]
        )

        tel_text = ""
        if telemetry:
            tel_text = f"\nRuntime metrics: {json.dumps(telemetry)[:200]}"

        task = (
            "=== DIAGNOSTIC ANALYSIS TASK ===\n\n"
            f"Intent: {envelope.intent_category}\n"
            f"Query: \"{envelope.normalized_text}\"\n\n"
            f"Relevant systems:\n{sys_text or '(none identified)'}"
            f"{tel_text}\n\n"
            "Respond with a JSON object:\n"
            "{\n"
            '  "explanation": "<clear explanation of the system/issue, ≤400 chars>",\n'
            '  "root_cause": "<for debug: identified root cause or empty string>",\n'
            '  "affected_systems": ["<system_id>"],\n'
            '  "is_actionable": <true if a single mutation could fix it>,\n'
            '  "confidence": <0.0 to 1.0>,\n'
            '  "action_hint": "<brief description of fix if actionable>"\n'
            "}\n"
            "Return ONLY the JSON object."
        )

        return InferenceRequest(
            prompt_parts    = [cached_part, PromptPart(text=task, cacheable=False, label="task")],
            system_prompt   = _DIAG_SYSTEM_PROMPT,
            logical_model   = LOGICAL_MODEL,
            complexity_tier = TIER,
            max_tokens      = PASS1_TOKENS,
            temperature     = TEMPERATURE,
            session_id      = session_id,
            call_label      = PASS1_LABEL,
            intent_class    = envelope.intent_category,
        )

    @staticmethod
    def _build_pass2(
        envelope:  IntentEnvelope,
        p1_data:   dict,
        cgs:       dict[str, Any],
        session_id: str,
    ) -> InferenceRequest:
        """Builds the Pass 2 suggestion request (DebugIssue only)."""
        action_hint = p1_data.get("action_hint", "")

        task = (
            "=== DIAGNOSTIC SUGGEST TASK ===\n\n"
            f"Original query: \"{envelope.normalized_text}\"\n"
            f"Root cause identified: {p1_data.get('root_cause','')}\n"
            f"Action hint: {action_hint}\n\n"
            "Generate a natural language mutation prompt that would fix this issue.\n"
            "The prompt must be specific enough for the mutation pipeline to process.\n\n"
            "Respond with a JSON object:\n"
            "{\n"
            '  "suggested_prompt": "<specific mutation prompt, ≤200 chars>",\n'
            '  "confidence": <0.0 to 1.0>\n'
            "}\n"
            "Return ONLY the JSON object."
        )

        return InferenceRequest(
            prompt_parts    = [PromptPart(text=task, cacheable=False, label="suggest_task")],
            system_prompt   = _DIAG_SYSTEM_PROMPT,
            logical_model   = LOGICAL_MODEL,
            complexity_tier = TIER,
            max_tokens      = PASS2_TOKENS,
            temperature     = TEMPERATURE,
            session_id      = session_id,
            call_label      = PASS2_LABEL,
            intent_class    = envelope.intent_category,
        )

    # ── Response parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_pass1(raw: str) -> dict:
        """Parses Pass 1 JSON response. Returns empty dict on parse failure."""
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.splitlines()
                             if not l.startswith("```")).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Graceful fallback — return the raw text as explanation
            return {"explanation": text[:400], "confidence": 0.5}

    @staticmethod
    def _parse_pass2(raw: str) -> dict:
        """Parses Pass 2 JSON response."""
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.splitlines()
                             if not l.startswith("```")).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"suggested_prompt": text[:200]}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_system_ids(cgs: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for gs in cgs.get("global_systems", []):
        ids.append(gs.get("id", ""))
    for mode in cgs.get("modes", []):
        for sys in mode.get("systems", []):
            ids.append(sys.get("id", ""))
    return [i for i in ids if i]


def _relevant_systems(query: str, cgs: dict[str, Any]) -> list[dict]:
    """Returns systems whose ID or phase appears in the query."""
    query_lower = query.lower()
    all_systems: list[dict] = list(cgs.get("global_systems", []))
    for mode in cgs.get("modes", []):
        all_systems.extend(mode.get("systems", []))

    # Exact ID match first
    matched = [s for s in all_systems
               if s.get("id", "").lower() in query_lower]
    if not matched:
        # Phase match
        matched = [s for s in all_systems
                   if s.get("phase", "").lower() in query_lower]
    if not matched:
        # Return all systems (up to 5) for generic queries
        matched = all_systems[:5]

    return matched[:5]


_DIAG_SYSTEM_PROMPT = """\
You are a game engine diagnostic expert analysing an XACE ECS game schema.
Your job is to explain system behaviour, identify bugs, and suggest fixes.
Be precise and concise. Respond ONLY with valid JSON as instructed.\
"""
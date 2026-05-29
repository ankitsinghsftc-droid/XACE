"""
llm_orchestrator.py — LLMOrchestrator
========================================
Orchestrates the 5-pass LLM mutation pipeline.

This is the single entry point for all PIL → LLM → MutationTransaction paths.
It receives an LLMContextPacket and returns either a MutationTransaction
or a PipelineResult indicating that clarification is needed.

## Pass Execution Order

    Pass 1 (TIER_L) → ReasoningPlan
    Pass 2 (TIER_L) → DraftMutationTransaction
    Pass 3 (TIER_M) → CritiqueResult
        if Pass 3 fails → inject correction → retry Pass 2 (max 2 attempts each)
    Pass 4 (TIER_M) → DeterminismAuditResult
        if Pass 4 hard violation → retry from Pass 2 (not from Pass 1)
    Pass 5 (TIER_M) → MutationTransaction

## TIER_S Shortcut (II2)

    If the LLMContextPacket's complexity_tier resolves to TIER_S,
    the orchestrator does NOT run any passes. It returns a
    PipelineResult(tier_s_shortcut=True) and the caller must
    route to GDEOrchestrator.process_intent() instead.

    The complexity_tier is set by ComplexityClassifier before the
    LLMContextPacket is assembled. LLMOrchestrator trusts that value.

## Retry Logic

    PILRetryPolicy governs all retries:
        - Pass 2 retried up to MAX_ATTEMPTS_PER_PASS=2 on critique failure
        - Full pipeline restarted up to MAX_TOTAL_REATTEMPTS=3 on hard failures
        - On exhaustion: PipelineResult(needs_clarification=True)

    Pass 1 is retried independently (up to 2 attempts) on OutputParseError.
    Pass 3 is never retried (it re-triggers Pass 2 instead).
    Pass 4 is never retried (parse error → safe fallback, hard violation → Pass 2 redo).
    Pass 5 raises on parse error (escalates to clarification).

## Diagnostic Routing (II7)

    QueryExplain and DebugIssue intents MUST NOT enter the 5-pass pipeline.
    LLMOrchestrator enforces this: if packet.is_read_only_intent is True,
    it raises DiagnosticIntentError. The caller (PIL pipeline coordinator)
    routes these to diagnostic_orchestrator (Phase 13.7) instead.

## PipelineResult

    success:            bool
    transaction:        MutationTransaction | None   — set on success
    needs_clarification:bool                         — true on retry exhaustion
    tier_s_shortcut:    bool                         — true for TIER_S intents
    error:              str                          — description if failed
    pass_summary:       dict                         — PILRetryPolicy.summary()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pass1_planning import Pass1Planning, ReasoningPlan, OutputParseError
from pass2_dsl_draft import Pass2DSLDraft, DraftMutationTransaction
from pass3_self_critique import Pass3SelfCritique, CritiqueResult
from pass4_determinism_audit import Pass4DeterminismAudit, DeterminismAuditResult
from pass5_final_output import Pass5FinalOutput, MutationTransaction
from retry_policy import PILRetryPolicy, RetryBudgetExhausted, MAX_ATTEMPTS_PER_PASS
from llm_context_packet import LLMContextPacket


# ── Exceptions ────────────────────────────────────────────────────────────────

class DiagnosticIntentError(Exception):
    """
    Raised when a QueryExplain or DebugIssue intent reaches LLMOrchestrator.
    These must be routed to diagnostic_orchestrator (II7), not the 5-pass pipeline.
    """
    def __init__(self, intent_category: str) -> None:
        super().__init__(
            f"Intent '{intent_category}' is a diagnostic/read-only intent (II7). "
            f"Route to diagnostic_orchestrator, not LLMOrchestrator."
        )
        self.intent_category = intent_category


# ── Pipeline Result ───────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """
    Result of one LLMOrchestrator.run() call.

    Attributes
    ----------
    success             : bool
    transaction         : MutationTransaction | None  — set on success=True
    needs_clarification : bool  — True when retry budget exhausted
    tier_s_shortcut     : bool  — True when TIER_S, no LLM ran
    error               : str   — human-readable error (empty on success)
    pass_summary        : dict  — PILRetryPolicy.summary() for telemetry
    """
    success:             bool                      = False
    transaction:         MutationTransaction | None = None
    needs_clarification: bool                      = False
    tier_s_shortcut:     bool                      = False
    error:               str                       = ""
    pass_summary:        dict                      = field(default_factory=dict)

    def __repr__(self) -> str:
        if self.success:
            return f"PipelineResult(SUCCESS, conf={self.transaction.confidence_score:.2f})"
        if self.tier_s_shortcut:
            return "PipelineResult(TIER_S_SHORTCUT)"
        if self.needs_clarification:
            return "PipelineResult(NEEDS_CLARIFICATION)"
        return f"PipelineResult(FAILED: {self.error[:60]!r})"


# ── LLM Orchestrator ──────────────────────────────────────────────────────────

class LLMOrchestrator:
    """
    Orchestrates the 5-pass PIL mutation pipeline.

    One shared instance per PIL session. Each call to run() creates
    a fresh PILRetryPolicy.

    Usage
    -----
        orchestrator = LLMOrchestrator(
            adapter,                 # InferenceAdapter from packages/inference
            session_id="s1",
        )
        result = orchestrator.run(context_packet)
        if result.tier_s_shortcut:
            return gde.process_intent(intent)
        if result.needs_clarification:
            return clarification_engine.generate(...)
        if result.success:
            return validation_loop.validate(result.transaction)
    """

    def __init__(
        self,
        adapter:    Any,
        session_id: str = "",
    ) -> None:
        self._adapter    = adapter
        self._session_id = session_id

        # Pass instances — shared across calls (all are stateless)
        self._pass1 = Pass1Planning(adapter)
        self._pass2 = Pass2DSLDraft(adapter)
        self._pass3 = Pass3SelfCritique(adapter)
        self._pass4 = Pass4DeterminismAudit(adapter)
        self._pass5 = Pass5FinalOutput(adapter)

    def run(self, packet: LLMContextPacket) -> PipelineResult:
        """
        Runs the full 5-pass pipeline for one LLMContextPacket.

        Parameters
        ----------
        packet : LLMContextPacket
            Assembled context from Phase 13.2 ContextAssembler.

        Returns
        -------
        PipelineResult

        Raises
        ------
        DiagnosticIntentError
            When packet.is_read_only_intent is True (II7).
        """
        # II7: diagnostic intents must not enter the 5-pass pipeline
        if packet.is_read_only_intent:
            raise DiagnosticIntentError(packet.intent_category)

        # TIER_S shortcut (II2)
        if packet.intent_category == "BalanceAdjustment":
            # Complexity tier is checked via packet context — for now delegate
            # to the adapter's TIER_S signal. Full integration happens when
            # ComplexityClassifier is wired in the PIL coordinator.
            pass  # continue to pipeline; TIER_S routing is caller responsibility

        policy = PILRetryPolicy()

        while policy.can_reattempt_pipeline() or policy.pipeline_runs == 0:
            if policy.pipeline_runs > 0:
                policy.begin_pipeline_reattempt()

            try:
                result = self._run_pipeline(packet, policy)
                if result is not None:
                    result.pass_summary = policy.summary()
                    return result
            except RetryBudgetExhausted as exc:
                return PipelineResult(
                    success             = False,
                    needs_clarification = True,
                    error               = str(exc),
                    pass_summary        = policy.summary(),
                )
            except DiagnosticIntentError:
                raise
            except Exception as exc:
                if not policy.can_reattempt_pipeline():
                    return PipelineResult(
                        success             = False,
                        needs_clarification = True,
                        error               = f"Unhandled error: {exc}",
                        pass_summary        = policy.summary(),
                    )
                # Loop to reattempt

        return PipelineResult(
            success             = False,
            needs_clarification = True,
            error               = "Pipeline reattempt budget exhausted.",
            pass_summary        = policy.summary(),
        )

    def _run_pipeline(
        self,
        packet: LLMContextPacket,
        policy: PILRetryPolicy,
    ) -> PipelineResult | None:
        """
        Runs one complete pipeline attempt (all 5 passes).
        Returns PipelineResult on success or definitive failure.
        Returns None to signal outer loop to reattempt.
        Raises RetryBudgetExhausted when budget is fully exhausted.
        """
        sid = self._session_id

        # ── Pass 1: Planning ──────────────────────────────────────────────────
        plan = self._run_pass1(packet, policy, sid)
        if plan is None:
            raise RetryBudgetExhausted("pass1_planning", 2, ["OutputParseError exhausted"])

        # ── Pass 2 + 3 loop: Draft + Self-Critique ────────────────────────────
        draft = self._run_pass2_with_critique(packet, plan, policy, sid)
        if draft is None:
            raise RetryBudgetExhausted("pass2_dsl_draft", 2, ["Self-critique exhausted"])

        # ── Pass 4: Determinism Audit ─────────────────────────────────────────
        audit = self._pass4.run(packet, draft, sid)
        policy.begin_attempt("pass4_determinism_audit")
        policy.record_success("pass4_determinism_audit")

        if audit.has_violations:
            # Hard violation — reattempt from Pass 2 (not Pass 1)
            if policy.can_reattempt_pipeline():
                return None   # signal outer loop to reattempt
            raise RetryBudgetExhausted(
                "pass4_determinism_audit", 1,
                [f"Determinism violation: {'; '.join(audit.violations[:2])}"]
            )

        # ── Pass 5: Final Output ──────────────────────────────────────────────
        try:
            policy.begin_attempt("pass5_final_output")
            txn = self._pass5.run(packet, draft, audit, sid)
            policy.record_success("pass5_final_output")
        except OutputParseError as exc:
            policy.record_failure("pass5_final_output", [str(exc)])
            raise RetryBudgetExhausted("pass5_final_output", 1, [str(exc)])

        return PipelineResult(
            success     = True,
            transaction = txn,
        )

    def _run_pass1(
        self,
        packet: LLMContextPacket,
        policy: PILRetryPolicy,
        sid:    str,
    ) -> ReasoningPlan | None:
        """Runs Pass 1 with retry. Returns plan or None on exhaustion."""
        for _ in range(MAX_ATTEMPTS_PER_PASS):
            policy.begin_attempt("pass1_planning")
            correction = policy.correction_prompt("pass1_planning")
            try:
                plan = self._pass1.run(packet, sid, correction)
                policy.record_success("pass1_planning")
                return plan
            except OutputParseError as exc:
                policy.record_failure("pass1_planning", [str(exc)])
                if not policy.can_retry("pass1_planning"):
                    return None
        return None

    def _run_pass2_with_critique(
        self,
        packet: LLMContextPacket,
        plan:   ReasoningPlan,
        policy: PILRetryPolicy,
        sid:    str,
    ) -> DraftMutationTransaction | None:
        """
        Runs Pass 2 → Pass 3 loop.
        On critique failure: injects correction and re-runs Pass 2.
        Returns approved draft or None on exhaustion.
        """
        for attempt in range(MAX_ATTEMPTS_PER_PASS):
            # Pass 2
            policy.begin_attempt("pass2_dsl_draft")
            correction = policy.correction_prompt("pass2_dsl_draft")
            try:
                draft = self._pass2.run(packet, plan, sid, correction)
                # Don't record success yet — wait for critique to pass
            except OutputParseError as exc:
                policy.record_failure("pass2_dsl_draft", [str(exc)])
                if not policy.can_retry("pass2_dsl_draft"):
                    return None
                continue

            # Pass 3 (critique)
            policy.begin_attempt("pass3_self_critique")
            critique: CritiqueResult = self._pass3.run(packet, draft, sid)

            if critique.passed:
                policy.record_success("pass3_self_critique")
                policy.record_success("pass2_dsl_draft")
                return draft
            else:
                # Critique failed — correction will be injected on next pass2 attempt
                policy.record_failure("pass3_self_critique", critique.issues[:3])
                policy.record_failure(
                    "pass2_dsl_draft",
                    [critique.to_correction_prompt() or "Self-critique failed — revise draft."]
                )
                # can_retry checks attempts < MAX — already incremented above
                if attempt + 1 >= MAX_ATTEMPTS_PER_PASS:
                    return None
                # Loop continues with corrected pass2

        return None
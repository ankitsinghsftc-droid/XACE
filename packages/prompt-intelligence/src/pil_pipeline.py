"""
pil_pipeline.py — PILPipeline
================================
PIL entry point — orchestrates all 13 submodules in sequence.

This is the SINGLE callable surface for the Builder Workspace UI and
any external system that wants the PIL to process a designer's prompt.

## Call Contract

    result = pipeline.process(
        prompt     = "make the zombie faster",
        cgs        = current_cgs,
        cgs_hash   = "0b1d495d00000000000000000000000000000000000000000000000000000000",
        mode       = "COLLABORATIVE",
        session_id = "s1",
    )

    result is one of:
        PILResult(kind="mutation",      transaction=MutationTransaction, ...)
        PILResult(kind="clarification", questions=[...], session_id="...")
        PILResult(kind="blocked",       reason="...", guard="...")
        PILResult(kind="diagnostic",    explanation="...", suggestion=None)
        PILResult(kind="tier_s",        ...)  → route to GDE directly

## Pipeline Sequence (mutation path)

    1.  IntentIntakeLayer.process()        → IntentEnvelope
    2.  [II7] Diagnostic routing check     → DiagnosticOrchestrator if QueryExplain|DebugIssue
    3.  ModeController.classify()          → ComplexityTier + forced_llm flag
    4.  [TIER_S shortcut]                  → PILResult(kind="tier_s") if TIER_S
    5.  MemoryLifecycleManager.assemble()  → MemoryAssembly (cached prefix + per-prompt)
    6.  ContextAssembler.assemble()        → LLMContextPacket
    7.  LLMOrchestrator.run()              → PipelineResult
        → PILResult(kind="clarification") if needs_clarification
    8.  StructuredOutputParser.parse()     → CanonicalMutation
    9.  ValidationLoop.validate()          → ValidationResult
        → PILResult(kind="blocked")       if not passed
    10. CritiqueEngine.review()            → CritiqueReport
        → PILResult(kind="blocked")       if not approved
    11. MutationPlanner.plan()             → CommittedMutationPlan
    12. SafetyScopeGuard.evaluate()        → SafetyOutcome
        → PILResult(kind="blocked")       if Blocked
    13. PILModeProfile policy check        → auto-commit or confirmation gate
    14. HistoryManager.on_commit()         → session history updated
    15. MemoryLifecycleManager.on_commit() → memory model updated
    16. PILResult(kind="mutation",         transaction=MutationTransaction)

## Error Handling

    All exceptions are caught at this level. Unknown exceptions produce
    PILResult(kind="blocked", reason=str(exc)) rather than propagating.

## Thread Safety

    PILPipeline is NOT thread-safe. One instance per builder session.
    The session_id is used for telemetry grouping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import sys, os

_src = os.path.dirname(__file__)
sys.path.insert(0, _src)  # pil_pipeline.py lives directly in src/
for sub in (
    "intent_intake", "context_assembler", "llm_orchestrator",
    "output_parser", "validation_loop", "critique_engine",
    "clarification_engine", "mutation_planner", "safety_scope_guard",
    "memory_model", "history_manager", "memory",
    "code_generation",
):
    sys.path.insert(0, os.path.join(_src, sub))
sys.path.insert(0, os.path.join(_src, 'mode_controller'))  # pil_mode_profile.py

# ── Submodule imports ─────────────────────────────────────────────────────────

from intent_intake_layer import IntentIntakeLayer
from intent_envelope import PILIntentCategory
from context_assembler import ContextAssembler
from llm_orchestrator import LLMOrchestrator, DiagnosticIntentError
from structured_output_parser import (
    CanonicalTypedMutation,
    StructuredOutputParser,
    ParseError,
)
from validation_loop import ValidationLoop
from critique_engine import CritiqueEngine
from mutation_planner import MutationPlanner
from safety_scope_guard import SafetyScopeGuard, Verdict
from clarification_engine import ClarificationEngine, NothingToClarifyError
from memory_lifecycle_manager import MemoryLifecycleManager
from session_memory import MutationRecord, FailureRecord
from history_manager import HistoryManager
from mode_controller import ModeController
from mode_profile import get_pil_profile
from pass5_final_output import MutationTransaction
from typed_operations import serialize_typed_operation_batch
from generated_system_materializer import (
    GeneratedSystemMaterializationError,
    GeneratedSystemMaterializer,
)


# ── PIL Result ────────────────────────────────────────────────────────────────

@dataclass
class PILResult:
    """
    Output of PILPipeline.process(). Always one kind per call.

    Attributes
    ----------
    kind : str
        "mutation"      — mutation transaction ready for GDE commit
        "clarification" — questions generated, awaiting user answers
        "blocked"       — safety/validation hard block
        "diagnostic"    — explanation returned (QueryExplain/DebugIssue)
        "tier_s"        — TIER_S: route to GDE deterministic path
        "error"         — unexpected error (should not happen in prod)

    transaction      : MutationTransaction | None
    questions        : list[dict]        — for clarification kind
    clarification_session_id : str       — for clarification kind
    explanation      : str               — for diagnostic kind
    suggestion       : MutationTransaction | None  — optional for diagnostic
    reason           : str               — for blocked/error kind
    guard            : str               — which guard blocked (if blocked)
    auto_committed   : bool              — True if committed without confirmation
    mode_profile_warnings : list[str]    — non-blocking mode-profile observations
    turn_index       : int               — session turn when this result was produced
    intent_category  : str               — classified intent
    confidence       : float             — intent classification confidence
    diff_text        : str               — unified diff (for mutation kind)
    """
    kind:                     str
    transaction:              MutationTransaction | None = None
    questions:                list[dict]                 = field(default_factory=list)
    clarification_session_id: str                        = ""
    explanation:              str                        = ""
    suggestion:               MutationTransaction | None = None
    reason:                   str                        = ""
    guard:                    str                        = ""
    auto_committed:           bool                       = False
    mode_profile_warnings:    list[str]                  = field(default_factory=list)
    turn_index:               int                        = 0
    intent_category:          str                        = ""
    confidence:               float                      = 0.0
    diff_text:                str                        = ""
    typed_mutation:           CanonicalTypedMutation | None = None

    @property
    def succeeded(self) -> bool:
        return self.kind == "mutation"

    @property
    def needs_user_input(self) -> bool:
        return self.kind == "clarification"

    @property
    def is_blocked(self) -> bool:
        return self.kind == "blocked"

    def __repr__(self) -> str:
        if self.kind == "mutation":
            conf = f", conf={self.confidence:.2f}" if self.confidence else ""
            return f"PILResult(mutation{conf})"
        if self.kind == "clarification":
            return f"PILResult(clarification, {len(self.questions)} questions)"
        if self.kind == "blocked":
            return f"PILResult(blocked: {self.reason[:60]!r})"
        return f"PILResult({self.kind})"


# ── PIL Pipeline ──────────────────────────────────────────────────────────────

class PILPipeline:
    """
    PIL entry point — orchestrates all submodules for one builder session.

    Usage
    -----
        pipeline = PILPipeline(
            inference_adapter = adapter,
            session_id        = "s1",
        )
        result = pipeline.process(
            prompt     = "make the zombie faster",
            cgs        = current_cgs,
            cgs_hash   = "0b1d495d00000000000000000000000000000000000000000000000000000000",
            mode       = "COLLABORATIVE",
        )
    """

    def __init__(
        self,
        inference_adapter: Any,
        session_id:        str = "",
        enable_code_gen:   bool = False,
        sgc_bin_path:      str = "",
        generated_system_materializer: Any = None,
        code_generation_engine: Any = None,
    ) -> None:
        self._adapter     = inference_adapter
        self._session_id  = session_id

        # Submodule instances (one per session)
        self._intake          = IntentIntakeLayer()
        self._context_asm     = ContextAssembler()
        self._llm_orch        = LLMOrchestrator(inference_adapter, session_id)
        self._output_parser   = StructuredOutputParser()
        self._validation      = ValidationLoop()
        self._critique        = CritiqueEngine()
        self._planner         = MutationPlanner()
        self._safety          = SafetyScopeGuard()
        self._clarification   = ClarificationEngine()
        self._memory          = MemoryLifecycleManager(session_id=session_id)
        self._history         = HistoryManager(session_id=session_id)
        # ModeController is instantiated per-call with the request's mode (see _run_pipeline)

        # Optional code generation (Phase 13.13)
        self._enable_code_gen = enable_code_gen
        self._code_gen = code_generation_engine
        if enable_code_gen:
            if self._code_gen is None:
                from code_generation_engine import CodeGenerationEngine
                self._code_gen = CodeGenerationEngine(
                    inference_adapter,
                    sgc_bin=sgc_bin_path,
                )
        self._generated_system_materializer = (
            generated_system_materializer
            if generated_system_materializer is not None
            else GeneratedSystemMaterializer(
                enabled=enable_code_gen,
                sgc_bin_path=sgc_bin_path,
                code_generation_engine=self._code_gen,
            )
        )

    # ── Main Entry Point ──────────────────────────────────────────────────────

    def process(
        self,
        prompt:         str,
        cgs:            dict[str, Any],
        cgs_hash:       str             = "",
        mode:           str             = "COLLABORATIVE",
        engine_metrics: dict | None     = None,
    ) -> PILResult:
        """
        Processes one designer prompt through the full PIL pipeline.

        Parameters
        ----------
        prompt         : str   — the raw designer prompt
        cgs            : dict  — current CGS JSON
        cgs_hash       : str   — CGS hash for memory memoization
        mode           : str   — assistance mode (COLLABORATIVE etc.)
        engine_metrics : dict  — optional Phase 7 performance data

        Returns
        -------
        PILResult
        """
        # Advance session turn
        self._memory.on_prompt(prompt)
        self._history.on_prompt(prompt)
        turn = self._history.current_turn

        try:
            return self._run_pipeline(prompt, cgs, cgs_hash, mode,
                                       engine_metrics, turn)
        except Exception as exc:
            self._history.on_failure(
                prompt, "unexpected_error", str(exc)[:200]
            )
            return PILResult(
                kind           = "error",
                reason         = f"Unexpected pipeline error: {exc}",
                turn_index     = turn,
                intent_category = "",
            )

    def _run_pipeline(
        self,
        prompt:         str,
        cgs:            dict[str, Any],
        cgs_hash:       str,
        mode:           str,
        engine_metrics: dict | None,
        turn:           int,
    ) -> PILResult:

        profile   = get_pil_profile(mode)
        mode_ctrl = ModeController(initial_mode=mode)

        # ── Step 1: Intent intake ─────────────────────────────────────────────
        intake_result = self._intake.process(prompt, mode)
        envelope      = intake_result.envelope

        # If intake blocked (Category A risk), return immediately
        if intake_result.was_blocked:
            return PILResult(
                kind            = "blocked",
                reason          = f"Intent blocked at intake: risk level too high.",
                guard           = "intake",
                turn_index      = turn,
                intent_category = envelope.intent_category,
            )

        # ── Step 2: Diagnostic routing (II7) ─────────────────────────────────
        if envelope.intent_category in {
            PILIntentCategory.QUERY_EXPLAIN,
            PILIntentCategory.DEBUG_ISSUE,
        }:
            return self._run_diagnostic(envelope, cgs, cgs_hash, mode, turn)

        # ── Step 3/4: Mode profile ────────────────────────────────────────────
        # TIER_S routing handled by LLMOrchestrator (returns tier_s_shortcut=True)

        # ── Step 5: Memory assembly ───────────────────────────────────────────
        memory_assembly = self._memory.assemble(cgs, cgs_hash)

        # ── Step 6: Context assembly ──────────────────────────────────────────
        packet = self._context_asm.assemble(
            envelope   = envelope,
            cgs        = cgs,
            session_id = self._session_id,
        )

        # ── Step 7: LLM Orchestrator (5-pass) ────────────────────────────────
        try:
            pipeline_result = self._llm_orch.run(packet)
        except DiagnosticIntentError:
            return self._run_diagnostic(envelope, cgs, cgs_hash, mode, turn)

        if pipeline_result.needs_clarification:
            return self._handle_clarification(
                envelope, cgs, pipeline_result.error, mode, turn, profile
            )

        if pipeline_result.tier_s_shortcut:
            return PILResult(
                kind            = "tier_s",
                intent_category = envelope.intent_category,
                confidence      = envelope.confidence,
                turn_index      = turn,
            )

        if pipeline_result.typed_operation_batch is not None:
            return self._finish_typed_mutation(
                prompt=prompt,
                envelope=envelope,
                batch=pipeline_result.typed_operation_batch,
                cgs=cgs,
                cgs_hash=cgs_hash,
                turn=turn,
            )

        # Unpack the MutationTransaction from PipelineResult
        transaction = pipeline_result.transaction

        # ── Step 8: Structured output parse ──────────────────────────────────
        # Build CanonicalMutation from the transaction's operations + draft JSON.
        # The draft JSON (from Pass 2) contains the operations; Pass 5 only
        # has schema_delta_type / risk_level metadata.  Use _transaction_to_json
        # to reconstruct a parseable JSON from the transaction itself.
        try:
            raw_json = _transaction_to_json(transaction)
            canonical = self._output_parser.parse(raw_json, cgs)
        except ParseError as exc:
            self._history.on_failure(prompt, "parse_error", str(exc))
            return self._handle_clarification(
                envelope, cgs, str(exc), mode, turn, profile
            )

        if not canonical.is_fully_valid:
            # Path validation failures are non-blocking warnings if the
            # transaction already passed LLMOrchestrator validation.
            # Only block on hard type mismatches.
            if not canonical.op_validation.valid:
                errors = canonical.op_validation.errors
                reason = "; ".join(list(errors)[:3])
                self._history.on_failure(prompt, "parse_error", reason)
                return PILResult(
                    kind            = "blocked",
                    reason          = f"Output type validation failed: {reason}",
                    guard           = "output_parser",
                    turn_index      = turn,
                    intent_category = envelope.intent_category,
                )

        # ── Step 9: Validation loop ───────────────────────────────────────────
        val_result = self._validation.validate(canonical, cgs)
        if not val_result.passed:
            reason = "; ".join(val_result.blocking_errors[:2])
            self._history.on_failure(prompt, "validation", reason)
            return PILResult(
                kind            = "blocked",
                reason          = f"Validation failed: {reason}",
                guard           = "validation_loop",
                turn_index      = turn,
                intent_category = envelope.intent_category,
            )

        # ── Step 10: Critique engine ──────────────────────────────────────────
        critique_report = self._critique.review(
            canonical   = canonical,
            validation  = val_result,
            transaction = transaction,
            current_cgs = cgs,
        )
        if not critique_report.approved:
            blocking = critique_report.concerns[:2]
            reason   = "; ".join(c for c in blocking if c.startswith("CRITICAL"))
            self._history.on_failure(prompt, "critique_block", reason)
            return PILResult(
                kind            = "blocked",
                reason          = f"Critique blocked: {reason}",
                guard           = "critique_engine",
                turn_index      = turn,
                intent_category = envelope.intent_category,
            )

        # ── Step 11: Mutation planner ─────────────────────────────────────────
        plan = self._planner.plan(
            transaction  = transaction,
            critique     = critique_report,
            current_cgs  = cgs,
            cgs_hash     = cgs_hash,
        )

        # ── Step 12: Safety scope guard ───────────────────────────────────────
        scope   = packet.allowed_scope if hasattr(packet, "allowed_scope") else None
        outcome = self._safety.evaluate(
            plan           = plan,
            current_cgs    = cgs,
            mode           = mode,
            scope          = scope,
            engine_metrics = engine_metrics,
        )

        if outcome.is_blocked:
            # Record blocked attempt in safety memory
            for guard, findings in zip(
                outcome.blocking_guards,
                [outcome.blocking_findings[:1]] * len(outcome.blocking_guards),
            ):
                self._memory.on_safety_block(
                    guard, "", findings[0] if findings else "blocked"
                )
            reason = "; ".join(outcome.blocking_findings[:2])
            self._history.on_failure(prompt, "safety_block", reason)
            return PILResult(
                kind            = "blocked",
                reason          = reason,
                guard           = ", ".join(outcome.blocking_guards),
                turn_index      = turn,
                intent_category = envelope.intent_category,
            )

        # Soft warnings — note but don't block
        mode_warnings: list[str] = []
        if outcome.is_soft_warning:
            mode_warnings = outcome.warning_findings[:3]

        # ── Step 13: Mode profile auto-commit gate ────────────────────────────
        should_auto = profile.should_auto_commit(transaction.risk_level)

        # ── Step 14 & 15: Record commit in history and memory ─────────────────
        new_cgs_hash = cgs_hash  # GDE will update this; we record what we know
        self._history.on_commit(
            summary          = transaction.mutation_summary or plan.mutation_description,
            schema_delta     = transaction.schema_delta_type,
            risk_level       = transaction.risk_level,
            confidence       = transaction.confidence_score,
            version_bump     = plan.version_bump,
            cgs_hash_before  = cgs_hash,
            cgs_hash_after   = new_cgs_hash,
            affected_systems = plan.affected_systems,
        )
        self._memory.on_commit(
            mutation     = MutationRecord(
                summary      = transaction.mutation_summary or plan.mutation_description,
                schema_delta = transaction.schema_delta_type,
                risk_level   = transaction.risk_level,
                turn_index   = turn,
            ),
            new_cgs      = cgs,
            new_cgs_hash = new_cgs_hash,
        )

        # ── Step 16: Return mutation result ───────────────────────────────────
        return PILResult(
            kind                  = "mutation",
            transaction           = transaction,
            auto_committed        = should_auto,
            mode_profile_warnings = mode_warnings,
            turn_index            = turn,
            intent_category       = envelope.intent_category,
            confidence            = envelope.confidence,
            diff_text             = "",
        )

    def _finish_typed_mutation(
        self,
        *,
        prompt: str,
        envelope: Any,
        batch: Any,
        cgs: dict[str, Any],
        cgs_hash: str,
        turn: int,
    ) -> PILResult:
        """Validate and carry a typed mutation without lowering it to paths."""

        try:
            provider_batch = json.loads(serialize_typed_operation_batch(batch))
            materialized = self._generated_system_materializer.materialize(
                provider_batch,
                cgs,
                session_id=self._session_id,
            )
            canonical = self._output_parser.parse_typed(
                json.dumps(
                    materialized.normalized_batch,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                cgs,
                allow_materialized_generated_systems=materialized.materialized,
            )
        except GeneratedSystemMaterializationError as exc:
            self._history.on_failure(
                prompt,
                "generated_system_materialization",
                f"{exc.code}: {exc}",
            )
            return PILResult(
                kind="blocked",
                reason=f"Generated system materialization failed [{exc.code}]: {exc}",
                guard=f"generated_system_materialization:{exc.stage}",
                turn_index=turn,
                intent_category=envelope.intent_category,
            )
        except ParseError as exc:
            self._history.on_failure(prompt, "typed_parse_error", str(exc))
            return PILResult(
                kind="blocked",
                reason=f"Typed output parse failed: {exc}",
                guard="typed_output_parser",
                turn_index=turn,
                intent_category=envelope.intent_category,
            )

        if not canonical.is_fully_valid:
            reason = "; ".join(canonical.validation.errors[:3])
            self._history.on_failure(prompt, "typed_validation", reason)
            return PILResult(
                kind="blocked",
                reason=f"Typed operation validation failed: {reason}",
                guard="typed_operation_validation",
                turn_index=turn,
                intent_category=envelope.intent_category,
            )

        operation_kinds = {
            operation.kind.value for operation in canonical.batch.operations
        }
        structural = operation_kinds != {"set_defaults"}
        schema_delta = "structural_add" if structural else "value_mutation"
        risk_level = "medium" if structural else "low"
        version_bump = "minor" if structural else "patch"
        affected_systems = [
            system["id"] for system in canonical.fragment_plan.global_systems
        ] + [
            system["id"]
            for _, system in canonical.fragment_plan.mode_systems
        ]

        self._history.on_commit(
            summary=canonical.batch.summary,
            schema_delta=schema_delta,
            risk_level=risk_level,
            confidence=envelope.confidence,
            version_bump=version_bump,
            cgs_hash_before=cgs_hash,
            cgs_hash_after=cgs_hash,
            affected_systems=affected_systems,
        )
        self._memory.on_commit(
            mutation=MutationRecord(
                summary=canonical.batch.summary,
                schema_delta=schema_delta,
                risk_level=risk_level,
                turn_index=turn,
            ),
            new_cgs=cgs,
            new_cgs_hash=cgs_hash,
        )

        return PILResult(
            kind="mutation",
            transaction=None,
            typed_mutation=canonical,
            auto_committed=False,
            turn_index=turn,
            intent_category=envelope.intent_category,
            confidence=envelope.confidence,
            diff_text=materialized.diff_text,
        )

    # ── Diagnostic path (QueryExplain | DebugIssue) ───────────────────────────

    def _run_diagnostic(
        self,
        envelope:   Any,
        cgs:        dict[str, Any],
        cgs_hash:   str,
        mode:       str,
        turn:       int,
    ) -> PILResult:
        """Routes to DiagnosticOrchestrator for explain/debug intents."""
        try:
            sys.path.insert(0, os.path.join(_src, "."))
            from diagnostic_orchestrator import DiagnosticOrchestrator
            orch = DiagnosticOrchestrator(self._adapter)
            diag_result = orch.run(envelope, cgs, mode)
            return PILResult(
                kind            = "diagnostic",
                explanation     = diag_result.explanation,
                suggestion      = diag_result.suggested_transaction,
                turn_index      = turn,
                intent_category = envelope.intent_category,
                confidence      = envelope.confidence,
            )
        except ImportError:
            # DiagnosticOrchestrator not yet built — return stub explanation
            return PILResult(
                kind            = "diagnostic",
                explanation     = (
                    f"[Diagnostic] Intent: {envelope.intent_category}. "
                    f"Prompt: '{envelope.normalized_text[:100]}'. "
                    f"Full diagnostic analysis requires DiagnosticOrchestrator."
                ),
                turn_index      = turn,
                intent_category = envelope.intent_category,
                confidence      = envelope.confidence,
            )
        except Exception as exc:
            return PILResult(
                kind            = "diagnostic",
                explanation     = f"Diagnostic error: {exc}",
                turn_index      = turn,
                intent_category = envelope.intent_category,
            )

    # ── Clarification path ────────────────────────────────────────────────────

    def _handle_clarification(
        self,
        envelope: Any,
        cgs:      dict[str, Any],
        error:    str,
        mode:     str,
        turn:     int,
        profile:  Any,
    ) -> PILResult:
        """Creates a clarification session and returns the first question."""
        if profile.max_clarification_questions == 0:
            # ARCHITECT_MODE — never asks
            return PILResult(
                kind            = "blocked",
                reason          = f"Cannot proceed: {error[:200]}",
                guard           = "pipeline",
                turn_index      = turn,
                intent_category = envelope.intent_category,
            )

        try:
            retry_ctx = {"pass_label": "pipeline", "reasons": [error[:200]]}
            session = self._clarification.create_session(
                envelope      = envelope,
                cgs           = cgs,
                resume_point  = "pass2_dsl_draft",
                retry_context = retry_ctx,
            )

            # Get first question formatted for the UI
            q = session.current_question
            questions = []
            if q:
                questions.append({
                    "question_id":   q.question_id,
                    "question_type": q.question_type,
                    "prompt":        q.prompt,
                    "options":       list(q.options),
                    "hint":          q.hint,
                    "parameter_key": q.parameter_key,
                })

            return PILResult(
                kind                     = "clarification",
                questions                = questions,
                clarification_session_id = session.session_id,
                reason                   = error[:200],
                turn_index               = turn,
                intent_category          = envelope.intent_category,
                confidence               = envelope.confidence,
            )
        except NothingToClarifyError:
            return PILResult(
                kind            = "blocked",
                reason          = f"Cannot clarify intent: {error[:200]}",
                guard           = "pipeline",
                turn_index      = turn,
                intent_category = envelope.intent_category,
            )

    # ── Clarification answer submission ───────────────────────────────────────

    def submit_clarification_answer(
        self,
        session_id: str,
        answer:     str,
    ) -> dict[str, Any]:
        """
        Submits an answer to a clarification question.

        Returns:
            {"accepted": bool, "error": str, "complete": bool, "next_question": dict|None}
        """
        ok = self._clarification.submit_answer(session_id, answer)
        if not ok:
            return {
                "accepted":      False,
                "error":         self._clarification.get_last_error(session_id),
                "complete":      False,
                "next_question": None,
            }

        is_complete = self._clarification.is_session_complete(session_id)
        next_q_dict = None

        if not is_complete:
            next_q = self._clarification.get_current_question(session_id)
            if next_q:
                next_q_dict = {
                    "question_id":   next_q.question_id,
                    "question_type": next_q.question_type,
                    "prompt":        next_q.prompt,
                    "options":       list(next_q.options),
                    "hint":          next_q.hint,
                    "parameter_key": next_q.parameter_key,
                }

        return {
            "accepted":      True,
            "error":         "",
            "complete":      is_complete,
            "next_question": next_q_dict,
        }

    def apply_clarification_answers(
        self,
        session_id: str,
        prompt:     str,
        cgs:        dict[str, Any],
        cgs_hash:   str       = "",
        mode:       str       = "COLLABORATIVE",
    ) -> PILResult:
        """
        After all clarification questions are answered, re-runs the pipeline
        with the resolved parameters merged into the prompt context.
        """
        try:
            outcome = self._clarification.apply_answers(session_id)
            self._clarification.close_session(session_id)
        except Exception as exc:
            return PILResult(
                kind   = "error",
                reason = f"Failed to apply clarification answers: {exc}",
            )

        # Build enriched prompt from clarification outcome
        enriched_prompt = prompt
        if outcome.rephrased_prompt:
            enriched_prompt = outcome.rephrased_prompt
        elif outcome.target_actor_id:
            enriched_prompt = f"{prompt} [actor: {outcome.target_actor_id}]"
        if outcome.numeric_value is not None:
            enriched_prompt = f"{enriched_prompt} [value: {outcome.numeric_value}]"

        return self.process(
            prompt   = enriched_prompt,
            cgs      = cgs,
            cgs_hash = cgs_hash,
            mode     = mode,
        )

    # ── Session management ────────────────────────────────────────────────────

    def close_session(self) -> dict[str, Any]:
        """
        Closes the PIL session and returns a summary dict.
        Call when the designer closes the builder window.
        """
        summary = self._history.close_session(
            final_turn=self._history.current_turn
        )
        self._memory.on_session_end()
        return {
            "session_id":      self._session_id,
            "total_mutations": summary.total_mutations,
            "total_failures":  summary.total_failures,
            "failure_rate":    summary.failure_rate,
            "version_bumps":   summary.version_bumps,
        }

    def __repr__(self) -> str:
        return (
            f"PILPipeline(session={self._session_id!r}, "
            f"turn={self._history.current_turn})"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _transaction_to_json(txn: MutationTransaction) -> str:
    """Reconstructs a minimal JSON from a MutationTransaction for re-parsing."""
    import json
    ops = [
        {
            "path":       op.path,
            "op":         op.op,
            "value":      op.value,
            "type_hint":  op.type_hint,
            "field_name": op.field_name,
            "actor_id":   op.actor_id,
            "type_id":    op.type_id,
        }
        for op in txn.operations
    ]
    return json.dumps({
        "operations":        ops,
        "schema_delta_type": txn.schema_delta_type,
        "confidence":        txn.confidence_score,
    })

"""
gde_orchestrator.py — GDEOrchestrator
========================================
The Game Definition Engine entry point.

Routes all inputs through the correct submodule pipeline and returns
either a committed CGS update or a ClarificationRequest for the UI.

## Input Types
    str (prompt)       — natural language from the designer
    IntentObject       — pre-classified intent (from PIL or builder internal)
    DSLTransaction     — explicit programmatic transaction (developer mode)

## Pipeline for Prompt Input
    1. IntentClassifier.classify(prompt)
    2. ContextLoader.load(intent, cgs)
    3. ScopeResolver.resolve(intent, cgs)
    4. SlotExtractor.extract(intent, cgs_slice)
    5. AmbiguityDetector.detect(intent, cgs_slice)
       → If ambiguous and mode asks: return ClarificationRequest
    6. TransactionBuilder assembles DSLTransaction from intent
    7. TransactionExecutor.execute(txn, cgs)    → proposed_cgs
    8. ConsistencyValidator.validate(proposed_cgs, txn)
       → If invalid: return validation errors
    9. CGSManager.commit(proposed_cgs, metadata)   → snapshot
    10. Return GDEResult(success)

## Genesis Routing
If CGSManager is uninitialised (no CGS loaded yet) AND the intent is
a genesis intent (first game creation), the orchestrator routes to
GGE (Game Genesis Engine, Phase 16). This is the check_if_genesis_session
routing described in CLAUDE.md.

## Thread Safety
GDEOrchestrator is NOT thread-safe. One instance per builder session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .cgs.cgs_manager import CGSManager, CGSManagerError
from .cgs.cgs_serializer import CGSSerializer
from .domain_dsl.mutation_metadata.mutation_metadata_model import MutationMetadata
from .domain_dsl.transaction_model.transaction_builder import (
    DSLTransaction, TransactionBuildError,
)
from .domain_dsl.transaction_model.transaction_executor import (
    TransactionExecutor, TransactionExecutionError,
)
from .prompt_interpretation.intent_object import IntentObject, GDEIntentType
from .prompt_interpretation.intent_classifier import IntentClassifier
from .prompt_interpretation.context_loader import ContextLoader
from .prompt_interpretation.scope_resolver import ScopeResolver
from .prompt_interpretation.slot_extractor import SlotExtractor
from .prompt_interpretation.ambiguity_detector import (
    AmbiguityDetector, ClarificationRequest,
)
from .question_engine.question_engine import QuestionEngine
from .question_engine.question_session_manager import QuestionSessionManager
from .mode_profiles.mode_profile import ModeProfile, get_profile, AssistanceMode
from .consistency_validator.consistency_validator import ConsistencyValidator, ConsistencyReport


# ── GDE Result ────────────────────────────────────────────────────────────────

@dataclass
class GDEResult:
    """
    Result of one GDE pipeline run.

    Attributes
    ----------
    success : bool
        True if the CGS was successfully mutated and committed.
    snapshot : dict[str, Any] | None
        The commit snapshot record if success=True.
    clarification_request : ClarificationRequest | None
        Set when the intent is ambiguous and the mode requires clarification.
    consistency_report : ConsistencyReport | None
        Set when validation failed.
    error : str
        Human-readable error description if success=False.
    code : str
        Stable actionable code for blocked or failed outcomes.
    action : str
        User/developer action that can resolve a blocked or failed outcome.
    unsupported : bool
        True when the requested behavior is unsupported for this run.
    intent : IntentObject | None
        The classified intent for this run.
    new_cgs_hash : str
        Hash of the committed CGS (empty if not committed).
    """

    success:               bool                      = False
    snapshot:              dict[str, Any] | None     = None
    clarification_request: ClarificationRequest | None = None
    consistency_report:    ConsistencyReport | None  = None
    error:                 str                       = ""
    code:                  str                       = ""
    action:                str                       = ""
    unsupported:           bool                      = False
    intent:                IntentObject | None        = None
    new_cgs_hash:          str                       = ""

    @property
    def needs_clarification(self) -> bool:
        return self.clarification_request is not None and \
               not self.clarification_request.is_empty()

    @property
    def is_query(self) -> bool:
        return self.intent is not None and self.intent.is_query

    def __repr__(self) -> str:
        if self.success:
            return f"GDEResult(SUCCESS, hash={self.new_cgs_hash[:8]}…)"
        if self.needs_clarification:
            return f"GDEResult(CLARIFICATION_NEEDED)"
        return f"GDEResult(FAILED: {self.error[:60]!r})"


# ── GDE Orchestrator ──────────────────────────────────────────────────────────

class GDEOrchestrator:
    """
    Game Definition Engine entry point.

    Owns one CGSManager per game session. Routes all designer inputs
    through the correct sub-pipeline.

    Usage
    -----
        orchestrator = GDEOrchestrator(mode="COLLABORATIVE", session_id="s1")
        orchestrator.load_cgs(initial_cgs)

        # From a natural-language prompt
        result = orchestrator.process_prompt("make the zombie faster")

        # From a pre-built transaction (developer mode)
        result = orchestrator.process_transaction(txn)

        # Resume after clarification
        session_id = result.clarification_request.session_id
        result2    = orchestrator.resume_clarification(session_id, "Zombie")
    """

    def __init__(
        self,
        mode:       str        = AssistanceMode.COLLABORATIVE,
        session_id: str | None = None,
    ) -> None:
        self._mode_name  = mode
        self._mode       = get_profile(mode)
        self._session_id = session_id or uuid.uuid4().hex
        self._cgs_manager: CGSManager | None = None

        # Sub-modules
        self._classifier    = IntentClassifier()
        self._ctx_loader    = ContextLoader()
        self._scope_resolver = ScopeResolver()
        self._slot_extractor = SlotExtractor()
        self._ambiguity_det  = AmbiguityDetector()
        self._q_engine       = QuestionEngine()
        self._q_sessions     = QuestionSessionManager()
        self._executor       = TransactionExecutor()
        self._validator      = ConsistencyValidator()

    # ── Initialisation ────────────────────────────────────────────────────────

    def load_cgs(
        self,
        cgs:        dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        """Loads an existing CGS into the manager. Call before processing."""
        self._cgs_manager = CGSManager.initialise(
            cgs, session_id=session_id or self._session_id
        )

    @property
    def is_initialised(self) -> bool:
        return self._cgs_manager is not None

    @property
    def current_cgs(self) -> dict[str, Any] | None:
        return self._cgs_manager.current_cgs if self._cgs_manager else None

    @property
    def current_hash(self) -> str:
        return self._cgs_manager.current_hash if self._cgs_manager else ""

    def set_mode(self, mode: str) -> None:
        """Switches the assistance mode for subsequent pipeline runs."""
        self._mode_name = mode
        self._mode      = get_profile(mode)

    # ── Prompt Pipeline ───────────────────────────────────────────────────────

    def process_prompt(
        self,
        prompt:             str,
        transaction_builder = None,   # optional pre-built TransactionBuilder
    ) -> GDEResult:
        """
        Full prompt → CGS pipeline.

        Returns GDEResult with success=True on commit, or
        clarification_request set if user input is needed.
        """
        if not self.is_initialised:
            return GDEResult(
                error=(
                    "No CGS is loaded. Call load_cgs() before processing prompts. "
                    "If this is a new game, start with the Game Genesis Engine."
                )
            )

        cgs = self._cgs_manager.current_cgs

        # ── Step 1: Classify intent ───────────────────────────────────────────
        intent = self._classifier.classify(prompt, session_id=self._session_id)

        # Query intents don't mutate — short circuit
        if intent.is_query:
            return GDEResult(success=True, intent=intent)

        # ── Step 2: Load context slice ────────────────────────────────────────
        cgs_slice = self._ctx_loader.load(intent, cgs)

        # ── Step 3: Resolve scope ─────────────────────────────────────────────
        self._scope_resolver.resolve(intent, cgs)

        # ── Step 4: Extract slots ─────────────────────────────────────────────
        self._slot_extractor.extract(intent, cgs_slice)

        # ── Step 5: Ambiguity detection ───────────────────────────────────────
        clarification = self._ambiguity_det.detect(
            intent,
            cgs_slice,
            confidence_threshold=self._mode.clarification_threshold,
        )

        if not clarification.is_empty() and self._mode.asks_for_clarification:
            # Build typed questions and create a session
            questions = self._q_engine.build(
                clarification, cgs_slice, intent, self._mode_name
            )
            if questions:
                session = self._q_sessions.create_session(
                    questions=questions,
                    resume_point="transaction_build",
                    intent_snapshot=intent.scope,
                )
                return GDEResult(
                    success=False,
                    clarification_request=clarification,
                    intent=intent,
                )

        # ── Steps 6-9: Build → Execute → Validate → Commit ───────────────────
        return self._build_and_commit(intent, cgs, transaction_builder)

    def process_intent(self, intent: IntentObject) -> GDEResult:
        """
        Processes a pre-classified IntentObject (from PIL).
        Skips classification; starts from scope resolution.
        """
        if not self.is_initialised:
            return GDEResult(error="No CGS loaded.")

        cgs       = self._cgs_manager.current_cgs
        cgs_slice = self._ctx_loader.load(intent, cgs)
        self._scope_resolver.resolve(intent, cgs)
        self._slot_extractor.extract(intent, cgs_slice)

        return self._build_and_commit(intent, cgs)

    def process_transaction(
        self,
        transaction: DSLTransaction,
    ) -> GDEResult:
        """
        Applies a pre-built DSLTransaction directly.
        Used by ADVANCED/ARCHITECT mode and by the Code Generation Engine.
        """
        if not self.is_initialised:
            return GDEResult(error="No CGS loaded.")

        cgs = self._cgs_manager.current_cgs
        return self._execute_and_commit(transaction, cgs)

    # ── Clarification Resume ──────────────────────────────────────────────────

    def resume_clarification(
        self,
        session_id: str,
        response:   str,
    ) -> GDEResult:
        """
        Submits a user answer to a clarification question.
        Returns the next question or proceeds to execution if all answered.
        """
        from .question_engine.question_session_manager import SessionError

        try:
            outcome = self._q_sessions.submit_answer(session_id, response)
        except SessionError as exc:
            return GDEResult(error=str(exc))

        if not outcome.is_valid:
            return GDEResult(
                error=f"Invalid answer: {outcome.error}",
                success=False,
            )

        if self._q_sessions.is_complete(session_id):
            # Merge resolved parameters back and proceed
            self._q_sessions.close_session(session_id)
            # Reconstruct a minimal intent from resolved params
            return GDEResult(
                success=False,
                error="Clarification session is complete, but no CGS mutation was committed.",
                code="GDE_CLARIFICATION_REPROMPT_REQUIRED",
                action="Re-submit the original prompt with the resolved clarification details.",
                unsupported=True,
            )

        # More questions pending
        return GDEResult(success=False, error="")

    # ── Internal Pipeline ─────────────────────────────────────────────────────

    def _build_and_commit(
        self,
        intent:              IntentObject,
        cgs:                 dict[str, Any],
        transaction_builder  = None,
    ) -> GDEResult:
        """
        Translates an IntentObject → DSLTransaction → executes → commits.
        For Phase 12, builds a minimal transaction from intent parameters.
        Full LLM-backed transaction building is in PIL Phase 13.
        """
        # Build a minimal transaction from extracted slots
        txn = self._intent_to_transaction(intent, cgs)
        if txn is None:
            return GDEResult(
                success=False,
                intent=intent,
                error=(
                    "Could not build a transaction from this intent. "
                    "The intent may lack sufficient parameter slots. "
                    "Try rephrasing with more specific values, "
                    "e.g. 'set zombie speed to 5'."
                ),
            )
        return self._execute_and_commit(txn, cgs, intent)

    def _execute_and_commit(
        self,
        txn:    DSLTransaction,
        cgs:    dict[str, Any],
        intent: IntentObject | None = None,
    ) -> GDEResult:
        """Executes → validates → commits a DSLTransaction."""

        # Execute: apply to copy
        try:
            proposed_cgs = self._executor.execute(txn, cgs)
        except TransactionExecutionError as exc:
            return GDEResult(
                success=False,
                intent=intent,
                error=str(exc),
            )

        # Validate: check consistency
        report = self._validator.validate(proposed_cgs, txn, cgs)
        if not report.is_valid:
            return GDEResult(
                success=False,
                intent=intent,
                consistency_report=report,
                error="; ".join(report.errors[:3]),  # first 3 errors in summary
            )

        # Commit
        try:
            snapshot = self._cgs_manager.commit(
                new_cgs=proposed_cgs,
                metadata=txn.metadata,
                bump=_version_bump_for(txn),
            )
        except CGSManagerError as exc:
            return GDEResult(
                success=False,
                intent=intent,
                error=str(exc),
            )

        return GDEResult(
            success=True,
            snapshot=snapshot,
            intent=intent,
            consistency_report=report,
            new_cgs_hash=snapshot.get("cgs_hash", ""),
        )

    def _intent_to_transaction(
        self,
        intent: IntentObject,
        cgs:    dict[str, Any],
    ) -> DSLTransaction | None:
        """
        Builds a minimal DSLTransaction from an IntentObject's extracted slots.
        This is the Phase 12 bridge — PIL (Phase 13) replaces this with full
        LLM-backed transaction generation.
        """
        from .domain_dsl.transaction_model.transaction_builder import (
            TransactionBuilder, OpType,
        )

        paths     = intent.path_hints
        field_val = intent.get_parameter("target_field")
        num_val   = (
            intent.get_parameter("numeric_value_0")
            or intent.get_parameter("value_0")
        )

        if not paths or not field_val or num_val is None:
            return None

        metadata = MutationMetadata.for_manual_edit(
            parent_cgs_hash       = self._cgs_manager.current_hash,
            schema_version_target = self._cgs_manager.current_version,
            description           = intent.raw_prompt[:100],
            session_id            = self._session_id,
        )

        try:
            builder = TransactionBuilder(metadata)
            for path in paths[:1]:  # one path for Phase 12; PIL handles multi-path
                # If a field was extracted, append it to reach the leaf value
                target = f"{path}.defaults.{field_val}" if field_val else path
                builder.set(target, num_val, type_hint="float")
            return builder.build()
        except TransactionBuildError:
            return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _version_bump_for(txn: DSLTransaction) -> str:
    """Returns the appropriate version bump type for a transaction."""
    if txn.has_structural_changes():
        return "minor"
    return "patch"

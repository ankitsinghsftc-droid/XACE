"""
mode_controller.py — ModeController
=====================================
Manages the assistance mode for one PIL session.

The assistance mode controls PIL-layer routing behaviour:
    - Whether the 5-pass LLM pipeline is forced regardless of
      ComplexityClassifier's TIER_S / TIER_M result.
    - How ClassificationInput is enriched before tier routing.
    - Whether the session tracks user-triggered force_llm overrides.

Four modes (increasing assumed user expertise):

    FULLY_ASSISTED
        The system proceeds confidently, making smart guesses for the user.
        Ambiguity is handled by proceeding with best-confidence result.
        TIER_S is allowed. force_llm=False always.
        Clarification threshold is LOW (system only blocks on genuine
        confusion — confidence < 0.45 — so beginners are not interrupted).

    COLLABORATIVE  [default]
        Balanced. System asks when unsure (confidence < 0.70).
        TIER_S allowed. force_llm=False unless explicitly set.
        Design suggestions shown on significant changes.

    ADVANCED
        User knows the domain. Clarification threshold is high (0.85).
        TIER_S allowed.
        User may call set_force_llm(True) to invoke the full 5-pass pipeline
        for a single call. force_llm resets to False after that call
        (one-shot semantics).

    ARCHITECT_MODE
        Expert mode. force_llm is always True — TIER_S is never used.
        System never asks for clarification (threshold = 1.0).
        Suggestions completely hidden unless explicitly requested.
        force_llm cannot be overridden to False while in this mode.

## force_llm Semantics
    FULLY_ASSISTED / COLLABORATIVE:
        force_llm is always False. set_force_llm() is a no-op.

    ADVANCED:
        set_force_llm(True) arms a one-shot override.
        After enrich_classification_input() consumes it, it resets to False.

    ARCHITECT_MODE:
        force_llm is structurally always True. set_force_llm(False) is a no-op.

## ClassificationInput Integration
    Call enrich_classification_input(inp) to attach mode context before
    dispatching to ComplexityClassifier:

        enriched = mode_controller.enrich_classification_input(inp)
        result   = classifier.classify(enriched)

## Thread Safety
    ModeController is NOT thread-safe. One instance per builder session.
    GDEOrchestrator and PIL each own their own instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# AssistanceMode constants live in GDE — PIL is Layer 1, GDE is Layer 2.
# PIL → GDE imports are correct and do not create a circular dependency.
# inference/ mirrors intent constants to avoid importing from PIL or GDE
# (see complexity_classifier.py), but mode constants do not flow there.
try:
    from mode_profiles.mode_profile import AssistanceMode
except ImportError:
    # Fallback: define inline when gde package is not on sys.path during
    # isolated PIL tests. These values MUST stay in sync with GDE's
    # AssistanceMode. If GDE renames a constant, update here immediately.
    class AssistanceMode:  # type: ignore[no-redef]
        FULLY_ASSISTED  = "FULLY_ASSISTED"
        COLLABORATIVE   = "COLLABORATIVE"
        ADVANCED        = "ADVANCED"
        ARCHITECT_MODE  = "ARCHITECT_MODE"

        @classmethod
        def all_modes(cls) -> frozenset[str]:
            return frozenset({
                cls.FULLY_ASSISTED,
                cls.COLLABORATIVE,
                cls.ADVANCED,
                cls.ARCHITECT_MODE,
            })


# ── Mode Profile ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModeProfile:
    """
    Immutable configuration for one assistance mode.

    Attributes
    ----------
    mode : str
        The AssistanceMode constant this profile describes.
    clarification_threshold : float
        Minimum confidence below which the AmbiguityDetector may trigger
        clarification. Range [0.0, 1.0].
        Lower = system asks less (auto-proceeds).
        Higher = system asks more (blocks on ambiguity).
    asks_for_clarification : bool
        Whether this mode ever blocks to request user clarification.
        ARCHITECT_MODE: False. All others: True.
    force_llm_structural : bool
        If True, force_llm is always True regardless of user signals.
        ARCHITECT_MODE only.
    suggestion_frequency : str
        One of: "always" | "significant" | "collapsed" | "hidden".
        Used by the Design Mentor (Phase 16); stored here for completeness.
    tier_s_allowed : bool
        Whether TIER_S shortcuts are permitted in this mode.
        ARCHITECT_MODE overrides to False (full pipeline always).
    """
    mode:                    str
    clarification_threshold: float
    asks_for_clarification:  bool
    force_llm_structural:    bool
    suggestion_frequency:    str
    tier_s_allowed:          bool


# ── Mode Profile Registry ─────────────────────────────────────────────────────

_PROFILES: dict[str, ModeProfile] = {
    AssistanceMode.FULLY_ASSISTED: ModeProfile(
        mode                    = AssistanceMode.FULLY_ASSISTED,
        clarification_threshold = 0.45,   # only block at very low confidence
        asks_for_clarification  = True,   # still asks, but rarely
        force_llm_structural    = False,
        suggestion_frequency    = "always",
        tier_s_allowed          = True,
    ),
    AssistanceMode.COLLABORATIVE: ModeProfile(
        mode                    = AssistanceMode.COLLABORATIVE,
        clarification_threshold = 0.70,   # balanced
        asks_for_clarification  = True,
        force_llm_structural    = False,
        suggestion_frequency    = "significant",
        tier_s_allowed          = True,
    ),
    AssistanceMode.ADVANCED: ModeProfile(
        mode                    = AssistanceMode.ADVANCED,
        clarification_threshold = 0.85,   # expert: rarely interrupted
        asks_for_clarification  = False,
        force_llm_structural    = False,
        suggestion_frequency    = "collapsed",
        tier_s_allowed          = True,
    ),
    AssistanceMode.ARCHITECT_MODE: ModeProfile(
        mode                    = AssistanceMode.ARCHITECT_MODE,
        clarification_threshold = 1.0,    # never blocks (threshold unreachable)
        asks_for_clarification  = False,
        force_llm_structural    = True,   # ALWAYS forces full pipeline
        suggestion_frequency    = "hidden",
        tier_s_allowed          = False,  # TIER_S never used
    ),
}


def get_mode_profile(mode: str) -> ModeProfile:
    """Returns the ModeProfile for the given mode string."""
    try:
        return _PROFILES[mode]
    except KeyError:
        raise ValueError(
            f"Unknown assistance mode: {mode!r}. "
            f"Valid modes: {sorted(_PROFILES.keys())}"
        )


# ── Mode Transition Record ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModeTransition:
    """
    Record of one mode switch within a session.
    Stored for telemetry; not used for routing logic.
    """
    from_mode:  str
    to_mode:    str
    trigger:    str   = "user"   # "user" | "system" | "test"


# ── Mode Controller ───────────────────────────────────────────────────────────

class ModeController:
    """
    Manages assistance mode state for one PIL session.

    Owns the mode-dependent routing flags that are injected into
    ClassificationInput before ComplexityClassifier runs.

    Usage
    -----
        mc = ModeController(initial_mode=AssistanceMode.COLLABORATIVE)

        # Before dispatching to ComplexityClassifier:
        enriched = mc.enrich_classification_input(raw_inp)
        result   = classifier.classify(enriched)

        # Expert user forces full pipeline for this call only:
        mc.set_force_llm(True)
        enriched = mc.enrich_classification_input(raw_inp)
        # enriched.force_llm == True for ADVANCED mode
        # After the call, force_llm resets to False automatically.

        # Switch modes:
        mc.set_mode(AssistanceMode.ARCHITECT_MODE)
    """

    def __init__(
        self,
        initial_mode: str    = AssistanceMode.COLLABORATIVE,
        session_id:   str | None = None,
    ) -> None:
        if initial_mode not in _PROFILES:
            raise ValueError(
                f"Unknown initial_mode: {initial_mode!r}. "
                f"Valid: {sorted(_PROFILES.keys())}"
            )
        self._mode:          str  = initial_mode
        self._profile:       ModeProfile = _PROFILES[initial_mode]
        self._force_llm_arm: bool = False   # one-shot arm for ADVANCED
        self._session_id:    str | None = session_id
        self._transitions:   list[ModeTransition] = []

    # ── Mode Access ───────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        """Current assistance mode string."""
        return self._mode

    @property
    def profile(self) -> ModeProfile:
        """Current ModeProfile (immutable)."""
        return self._profile

    @property
    def clarification_threshold(self) -> float:
        """Minimum confidence below which AmbiguityDetector may trigger."""
        return self._profile.clarification_threshold

    @property
    def asks_for_clarification(self) -> bool:
        """Whether this mode ever blocks to request user clarification."""
        return self._profile.asks_for_clarification

    @property
    def tier_s_allowed(self) -> bool:
        """Whether ComplexityClassifier may route to TIER_S in this mode."""
        return self._profile.tier_s_allowed

    # ── Mode Switching ────────────────────────────────────────────────────────

    def set_mode(
        self,
        new_mode: str,
        trigger:  str = "user",
    ) -> None:
        """
        Switches to a new assistance mode.

        Any pending one-shot force_llm arm is cleared on mode change
        (the new mode's structural force_llm takes over).

        Parameters
        ----------
        new_mode : str
            Target mode. Must be one of AssistanceMode constants.
        trigger : str
            Reason for transition: "user" | "system" | "test".
        """
        if new_mode not in _PROFILES:
            raise ValueError(
                f"Unknown mode: {new_mode!r}. Valid: {sorted(_PROFILES.keys())}"
            )
        if new_mode == self._mode:
            return  # no-op, no transition record

        transition = ModeTransition(
            from_mode=self._mode,
            to_mode=new_mode,
            trigger=trigger,
        )
        self._transitions.append(transition)
        self._mode    = new_mode
        self._profile = _PROFILES[new_mode]
        self._force_llm_arm = False   # clear one-shot arm on mode change

    # ── force_llm Control ─────────────────────────────────────────────────────

    def set_force_llm(self, armed: bool) -> None:
        """
        Arms or disarms the one-shot force_llm override.

        Mode rules:
            FULLY_ASSISTED / COLLABORATIVE:
                set_force_llm() is a no-op. force_llm stays False.
            ADVANCED:
                set_force_llm(True) arms for the next call.
                Automatically disarmed after enrich_classification_input().
            ARCHITECT_MODE:
                set_force_llm(False) is a no-op. force_llm is always True.
        """
        if self._mode == AssistanceMode.ARCHITECT_MODE:
            # ARCHITECT_MODE: structurally always True; override not possible
            return
        if self._mode in {AssistanceMode.FULLY_ASSISTED, AssistanceMode.COLLABORATIVE}:
            # These modes do not support user-triggered force_llm
            return
        # ADVANCED: honour the arm request
        self._force_llm_arm = armed

    @property
    def force_llm(self) -> bool:
        """
        Whether force_llm should be True for the current call.

        ARCHITECT_MODE: always True.
        ADVANCED + armed: True.
        All others: False.
        """
        if self._profile.force_llm_structural:
            return True
        return self._force_llm_arm

    def _consume_force_llm(self) -> bool:
        """
        Returns force_llm value AND resets one-shot arm if applicable.
        Called by enrich_classification_input().
        """
        if self._profile.force_llm_structural:
            return True   # ARCHITECT_MODE: always True, never resets

        value = self._force_llm_arm
        self._force_llm_arm = False   # reset one-shot
        return value

    # ── ClassificationInput Enrichment ────────────────────────────────────────

    def enrich_classification_input(self, inp: object) -> object:
        """
        Returns a new ClassificationInput with mode-derived fields set.

        Sets:
            assistance_mode : str  — current mode
            force_llm       : bool — whether to bypass TIER_S

        If the incoming ClassificationInput was built with force_llm=True
        by the caller for a reason unrelated to mode (e.g. a test), that
        value is OR'd with the mode-derived value — it is never downgraded.

        Parameters
        ----------
        inp : ClassificationInput
            Input from PIL before tier classification.
            Must have `assistance_mode` and `force_llm` dataclass fields.

        Returns
        -------
        ClassificationInput
            A new instance (frozen dataclass) with mode fields applied.
        """
        mode_force_llm = self._consume_force_llm()
        # Merge: if either the caller or the mode says force_llm, honour it.
        merged_force_llm = mode_force_llm or getattr(inp, "force_llm", False)

        # Use dataclasses.replace to produce a new frozen instance.
        import dataclasses
        return dataclasses.replace(
            inp,
            assistance_mode=self._mode,
            force_llm=merged_force_llm,
        )

    # ── Transition History ────────────────────────────────────────────────────

    @property
    def transitions(self) -> list[ModeTransition]:
        """Read-only view of all mode transitions in this session."""
        return list(self._transitions)

    @property
    def transition_count(self) -> int:
        return len(self._transitions)

    # ── Introspection ─────────────────────────────────────────────────────────

    def describe(self) -> dict:
        """Returns a plain dict snapshot of current controller state."""
        return {
            "mode":                     self._mode,
            "clarification_threshold":  self._profile.clarification_threshold,
            "asks_for_clarification":   self._profile.asks_for_clarification,
            "tier_s_allowed":           self._profile.tier_s_allowed,
            "force_llm":                self.force_llm,
            "force_llm_armed":          self._force_llm_arm,
            "suggestion_frequency":     self._profile.suggestion_frequency,
            "transition_count":         self.transition_count,
            "session_id":               self._session_id,
        }

    def __repr__(self) -> str:
        force = " force_llm=True" if self.force_llm else ""
        return f"ModeController({self._mode!r}{force})"
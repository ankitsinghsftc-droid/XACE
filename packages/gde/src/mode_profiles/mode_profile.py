"""
mode_profile.py — ModeProfile
================================
Defines the four GDE assistance mode profiles that control how much
the engine asks, assumes, explains, and suggests.

## The Four Modes

    FULLY_ASSISTED  — for zero-experience designers
        Asks everything. Never assumes. Explains all changes in plain English.
        Suggests improvements after every mutation. Blocks risky changes.
        Blocks all technical vocabulary.

    COLLABORATIVE   — default for most designers
        Asks when confidence < 0.65. Makes safe assumptions for low-risk cases.
        Explains significant changes. Suggests periodically.
        Allows one-word technical terms in explanations.

    ADVANCED        — for developers and experienced designers
        Asks only when essential data is missing (A5 / UNKNOWN).
        Makes most assumptions automatically. Brief explanations on request.
        Suggestions collapsed by default, available on demand.
        Technical vocabulary allowed.

    ARCHITECT_MODE  — for expert users who know exactly what they want
        Never asks. Always proceeds with best-guess assumptions.
        No explanations unless explicitly requested.
        No suggestions unless explicitly requested.
        Full technical vocabulary (ECS, component, system, phase).

## Switching Modes
The mode is set globally for a builder session by the designer in the
settings panel. The GDE orchestrator reads it at the start of each pipeline
run. Mode switches take effect on the next prompt — not mid-pipeline.

The NLTL (Natural Language Translation Layer) checks
technical_detail_level_manager.py for whether a user has grown beyond
their current mode and surfaces a suggestion to upgrade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Mode Names ────────────────────────────────────────────────────────────────

class AssistanceMode:
    FULLY_ASSISTED = "FULLY_ASSISTED"
    COLLABORATIVE  = "COLLABORATIVE"
    ADVANCED       = "ADVANCED"
    ARCHITECT_MODE = "ARCHITECT_MODE"

    ALL: tuple[str, ...] = (
        FULLY_ASSISTED, COLLABORATIVE, ADVANCED, ARCHITECT_MODE
    )

    @classmethod
    def is_valid(cls, mode: str) -> bool:
        return mode in cls.ALL

    @classmethod
    def is_more_assisted(cls, a: str, b: str) -> bool:
        """Returns True if mode a is more assisted than mode b."""
        order = {m: i for i, m in enumerate(cls.ALL)}
        return order.get(a, 99) < order.get(b, 99)


# ── Mode Profile ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModeProfile:
    """
    Configuration record controlling the GDE's behaviour for one mode.

    Attributes
    ----------
    mode : str
        The assistance mode name (one of AssistanceMode constants).

    clarification_threshold : float
        Intent confidence below which the GDE asks for clarification.
        Range: [0.0, 1.0]. Higher = more questions asked.
        FULLY_ASSISTED: 0.70, COLLABORATIVE: 0.60, ADVANCED: 0.0 (never),
        ARCHITECT_MODE: 0.0 (never)

    auto_assumption_level : str
        How aggressively the GDE fills in missing slots without asking:
        "never"   — always ask (FULLY_ASSISTED)
        "safe"    — assume only for demonstrably low-risk slots (COLLABORATIVE)
        "liberal" — assume for most slots (ADVANCED)
        "always"  — always assume, never ask (ARCHITECT_MODE)

    risk_block_level : str
        Which risk levels trigger a hard block:
        "all"     — block medium and high risk (FULLY_ASSISTED)
        "high"    — block only high risk (COLLABORATIVE, ADVANCED)
        "none"    — never block, always warn (ARCHITECT_MODE)

    explanation_level : str
        How much plain-English explanation to add to each mutation:
        "full"    — full explanation of every field changed (FULLY_ASSISTED)
        "summary" — one-sentence summary of significant changes (COLLABORATIVE)
        "minimal" — brief label only (ADVANCED)
        "none"    — no explanation (ARCHITECT_MODE)

    auto_commit_policy : str
        Whether mutations are committed immediately or require confirmation:
        "always_confirm"  — show diff and ask "apply?" (FULLY_ASSISTED)
        "confirm_if_risk" — auto-commit low-risk, confirm medium+ (COLLABORATIVE)
        "auto_commit"     — auto-commit, show diff after (ADVANCED)
        "silent"          — commit silently, no diff shown (ARCHITECT_MODE)

    suggestion_policy : str
        When to show Design Mentor suggestions:
        "always"   — after every mutation (FULLY_ASSISTED)
        "periodic" — after significant changes (COLLABORATIVE)
        "on_demand"— collapsed by default, expandable (ADVANCED)
        "hidden"   — never shown (ARCHITECT_MODE)

    show_technical_details : bool
        Whether ECS/component/system/phase vocabulary is shown in explanations.
        False for FULLY_ASSISTED and COLLABORATIVE (vocabulary filter active).
        True for ADVANCED and ARCHITECT_MODE.

    max_questions_per_clarification : int
        Cap on how many questions to ask per ambiguity resolution.
        FULLY_ASSISTED: 5, COLLABORATIVE: 3, ADVANCED: 1, ARCHITECT_MODE: 0

    diff_viewer_auto_open : bool
        Whether the schema diff panel opens automatically after a mutation.
    """

    mode:                             str
    clarification_threshold:          float
    auto_assumption_level:            str
    risk_block_level:                 str
    explanation_level:                str
    auto_commit_policy:               str
    suggestion_policy:                str
    show_technical_details:           bool
    max_questions_per_clarification:  int
    diff_viewer_auto_open:            bool

    # ── Derived Properties ────────────────────────────────────────────────────

    @property
    def asks_for_clarification(self) -> bool:
        """True if this mode ever asks clarification questions."""
        return self.clarification_threshold > 0.0

    @property
    def auto_commits(self) -> bool:
        return self.auto_commit_policy in ("auto_commit", "silent")

    @property
    def shows_suggestions(self) -> bool:
        return self.suggestion_policy != "hidden"

    def should_clarify(self, confidence: float) -> bool:
        """Returns True if the given confidence warrants a clarification prompt."""
        return confidence < self.clarification_threshold

    def should_block(self, risk_level: str) -> bool:
        """Returns True if the given risk level should block the mutation."""
        match self.risk_block_level:
            case "all":
                return risk_level in ("medium", "high")
            case "high":
                return risk_level == "high"
            case "none":
                return False
            case _:
                return risk_level == "high"

    def explanation_for_mutation(self, description: str, technical: str) -> str:
        """
        Returns the appropriate explanation string based on explanation_level.

        Parameters
        ----------
        description : str
            Plain-English description of the mutation.
        technical : str
            Technical (ECS) description for ADVANCED/ARCHITECT users.
        """
        match self.explanation_level:
            case "full" | "summary":
                return description
            case "minimal":
                return technical if self.show_technical_details else description
            case "none":
                return ""
            case _:
                return description

    def __repr__(self) -> str:
        return f"ModeProfile({self.mode})"


# ── Pre-Built Mode Profiles ───────────────────────────────────────────────────

FULLY_ASSISTED_PROFILE = ModeProfile(
    mode                            = AssistanceMode.FULLY_ASSISTED,
    clarification_threshold         = 0.70,
    auto_assumption_level           = "never",
    risk_block_level                = "all",
    explanation_level               = "full",
    auto_commit_policy              = "always_confirm",
    suggestion_policy               = "always",
    show_technical_details          = False,
    max_questions_per_clarification = 5,
    diff_viewer_auto_open           = True,
)

COLLABORATIVE_PROFILE = ModeProfile(
    mode                            = AssistanceMode.COLLABORATIVE,
    clarification_threshold         = 0.60,
    auto_assumption_level           = "safe",
    risk_block_level                = "high",
    explanation_level               = "summary",
    auto_commit_policy              = "confirm_if_risk",
    suggestion_policy               = "periodic",
    show_technical_details          = False,
    max_questions_per_clarification = 3,
    diff_viewer_auto_open           = True,
)

ADVANCED_PROFILE = ModeProfile(
    mode                            = AssistanceMode.ADVANCED,
    clarification_threshold         = 0.0,
    auto_assumption_level           = "liberal",
    risk_block_level                = "high",
    explanation_level               = "minimal",
    auto_commit_policy              = "auto_commit",
    suggestion_policy               = "on_demand",
    show_technical_details          = True,
    max_questions_per_clarification = 1,
    diff_viewer_auto_open           = False,
)

ARCHITECT_PROFILE = ModeProfile(
    mode                            = AssistanceMode.ARCHITECT_MODE,
    clarification_threshold         = 0.0,
    auto_assumption_level           = "always",
    risk_block_level                = "none",
    explanation_level               = "none",
    auto_commit_policy              = "silent",
    suggestion_policy               = "hidden",
    show_technical_details          = True,
    max_questions_per_clarification = 0,
    diff_viewer_auto_open           = False,
)

# ── Registry ──────────────────────────────────────────────────────────────────

_PROFILES: dict[str, ModeProfile] = {
    AssistanceMode.FULLY_ASSISTED: FULLY_ASSISTED_PROFILE,
    AssistanceMode.COLLABORATIVE:  COLLABORATIVE_PROFILE,
    AssistanceMode.ADVANCED:       ADVANCED_PROFILE,
    AssistanceMode.ARCHITECT_MODE: ARCHITECT_PROFILE,
}


def get_profile(mode: str) -> ModeProfile:
    """
    Returns the ModeProfile for the given mode name.

    Raises
    ------
    ValueError
        If the mode name is not recognised.
    """
    profile = _PROFILES.get(mode)
    if profile is None:
        raise ValueError(
            f"Unknown assistance mode '{mode}'. "
            f"Valid modes: {list(_PROFILES.keys())}"
        )
    return profile


def all_profiles() -> list[ModeProfile]:
    """Returns all mode profiles in order from most to least assisted."""
    return [_PROFILES[m] for m in AssistanceMode.ALL]
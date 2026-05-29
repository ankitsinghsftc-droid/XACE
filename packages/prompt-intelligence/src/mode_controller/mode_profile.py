"""
pil_mode_profile.py — PILModeProfile
======================================
Extended mode profile for PIL-layer behaviours beyond routing.

ModeController (mode_controller.py) carries the minimal profile needed
for inference routing: clarification_threshold, force_llm, tier_s_allowed.

PILModeProfile carries the extended configuration that governs how PIL
communicates results to the designer:
    - How aggressively to auto-assume missing parameters
    - Whether to auto-commit low-risk mutations without confirmation
    - How much explanation to include with mutation results
    - How quickly to escalate risk warnings to blocks
    - Whether to show proactive design suggestions

## Four Profiles

    FULLY_ASSISTED
        Designed for non-technical users who just want results.
        High auto-assumption (fills in sensible defaults).
        Auto-commit safe mutations (no confirmation required for low risk).
        Full explanation (every action explained in plain language).
        Aggressive suggestion (proactively proposes improvements).
        Risk block level is LOW (err on the side of safety).

    COLLABORATIVE  [default]
        Balanced. Assumes some things, asks when genuinely unsure.
        Auto-commit only very-low-risk mutations.
        Standard explanation (result + reason, not full tutorial).
        Moderate suggestion (offer suggestions on significant changes).
        Risk block level is MEDIUM.

    ADVANCED
        Expert user. Minimal assumptions — asks for explicit values.
        Does not auto-commit — always shows what will happen.
        Terse explanation (one line, no tutorial).
        Collapsed suggestion (available on request, not pushed).
        Risk block level is HIGH (expert decides what risks are acceptable).

    ARCHITECT_MODE
        No auto-assumption, no auto-commit.
        No proactive explanation unless asked.
        No suggestions unless requested.
        Risk block level is MAXIMUM (only hard invariant violations block —
        everything else is permitted, with the expert taking responsibility).

## Usage

    profile = PILModeProfile.for_mode("COLLABORATIVE")
    profile.should_auto_commit(risk_level="low")   # True
    profile.explain(result_text, verbosity="standard")
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Policy Enums ──────────────────────────────────────────────────────────────

class AutoAssumptionLevel:
    """How aggressively PIL fills in missing parameters without asking."""
    HIGH     = "HIGH"     # fill in sensible defaults for most missing values
    MODERATE = "MODERATE" # fill in obvious defaults, ask for ambiguous ones
    LOW      = "LOW"      # ask for explicit value when anything is unclear
    NONE     = "NONE"     # never assume — always ask or fail gracefully


class RiskBlockLevel:
    """At what risk severity PIL blocks a mutation (rather than warning)."""
    LOW      = "LOW"      # block on any non-zero risk
    MEDIUM   = "MEDIUM"   # block on MODERATE or HIGH risk
    HIGH     = "HIGH"     # block only on HIGH risk
    MAXIMUM  = "MAXIMUM"  # block only on hard invariant violations


class ExplanationLevel:
    """How much explanation PIL attaches to mutation results."""
    FULL      = "FULL"      # plain-language summary, what changed, why, what to watch
    STANDARD  = "STANDARD"  # one paragraph: what changed and immediate implications
    TERSE     = "TERSE"     # one sentence maximum
    NONE      = "NONE"      # no explanation — just the result


class SuggestionPolicy:
    """When PIL offers proactive design suggestions."""
    ALWAYS    = "ALWAYS"    # suggest on every mutation
    SIGNIFICANT = "SIGNIFICANT"  # suggest on structural or high-impact mutations
    COLLAPSED = "COLLAPSED" # suggestions available on request, not pushed
    HIDDEN    = "HIDDEN"    # no suggestions


class AutoCommitPolicy:
    """When PIL auto-commits without requesting confirmation."""
    ALWAYS    = "ALWAYS"    # auto-commit everything (caution: destructive too)
    LOW_RISK  = "LOW_RISK"  # auto-commit when risk_level="low"
    NEVER     = "NEVER"     # always show commit confirmation


# ── PIL Mode Profile ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PILModeProfile:
    """
    Extended PIL-layer mode profile.

    Governs communication behaviour beyond inference routing.
    One profile per assistance mode — built at module load time.

    Attributes
    ----------
    mode                  : str — AssistanceMode constant
    auto_assumption_level : str — AutoAssumptionLevel
    risk_block_level      : str — RiskBlockLevel
    explanation_level     : str — ExplanationLevel
    suggestion_policy     : str — SuggestionPolicy
    auto_commit_policy    : str — AutoCommitPolicy
    max_clarification_questions : int
        Maximum number of clarification questions per session.
        FULLY_ASSISTED: 2 (don't overwhelm beginners)
        COLLABORATIVE: 3
        ADVANCED: 1 (experts don't like being asked)
        ARCHITECT_MODE: 0 (never asks)
    show_critique_concerns : bool
        Whether to surface CritiqueEngine concerns to the designer.
        FULLY_ASSISTED: False (concerns converted to safe auto-choices)
        All others: True
    show_validation_detail : bool
        Whether to show detailed ValidationLoop layer results.
        ADVANCED + ARCHITECT_MODE: True
        Others: False (summary only)
    """
    mode:                       str
    auto_assumption_level:      str
    risk_block_level:           str
    explanation_level:          str
    suggestion_policy:          str
    auto_commit_policy:         str
    max_clarification_questions: int
    show_critique_concerns:     bool
    show_validation_detail:     bool

    # ── Convenience methods ───────────────────────────────────────────────────

    def should_auto_commit(self, risk_level: str) -> bool:
        """
        Returns True if PIL should auto-commit a mutation at this risk level.

        Parameters
        ----------
        risk_level : str — "low" | "medium" | "high"
        """
        if self.auto_commit_policy == AutoCommitPolicy.ALWAYS:
            return True
        if self.auto_commit_policy == AutoCommitPolicy.NEVER:
            return False
        # LOW_RISK: auto-commit only when risk is low
        return risk_level == "low"

    def should_block_on_risk(self, severity: str) -> bool:
        """
        Returns True if the given guard severity should block in this mode.

        Parameters
        ----------
        severity : str — "none" | "warning" | "block"
        """
        if severity == "none":
            return False
        if severity == "block":
            return True  # always block on hard block regardless of mode

        # severity == "warning": depends on risk_block_level
        if self.risk_block_level == RiskBlockLevel.LOW:
            return True    # block on any non-zero severity
        if self.risk_block_level in {RiskBlockLevel.MEDIUM, RiskBlockLevel.HIGH,
                                      RiskBlockLevel.MAXIMUM}:
            return False   # warnings are not blocks in these modes
        return False

    def should_suggest(self, is_structural: bool, impact_level: str) -> bool:
        """
        Returns True if PIL should show a proactive design suggestion.

        Parameters
        ----------
        is_structural : bool — whether the mutation is structural
        impact_level  : str  — "none" | "low" | "medium" | "high"
        """
        if self.suggestion_policy == SuggestionPolicy.HIDDEN:
            return False
        if self.suggestion_policy == SuggestionPolicy.ALWAYS:
            return True
        if self.suggestion_policy == SuggestionPolicy.COLLAPSED:
            return False   # available on request
        # SIGNIFICANT: suggest on structural or medium/high impact
        return is_structural or impact_level in {"medium", "high"}

    def format_explanation(self, result_text: str) -> str:
        """
        Formats a result explanation according to this mode's verbosity.

        Parameters
        ----------
        result_text : str — the full explanation text

        Returns
        -------
        str — truncated/formatted per explanation_level
        """
        if self.explanation_level == ExplanationLevel.NONE:
            return ""
        if self.explanation_level == ExplanationLevel.TERSE:
            # First sentence only
            first_sentence = result_text.split(".")[0]
            return (first_sentence + ".").strip() if first_sentence else ""
        if self.explanation_level == ExplanationLevel.STANDARD:
            # First paragraph (up to first double newline), capped at 300 chars
            first_para = result_text.split("\n\n")[0]
            return first_para[:300] if len(first_para) > 300 else first_para
        # FULL: return as-is (capped at 800 chars for UI)
        return result_text[:800]

    def to_dict(self) -> dict:
        return {
            "mode":                        self.mode,
            "auto_assumption_level":       self.auto_assumption_level,
            "risk_block_level":            self.risk_block_level,
            "explanation_level":           self.explanation_level,
            "suggestion_policy":           self.suggestion_policy,
            "auto_commit_policy":          self.auto_commit_policy,
            "max_clarification_questions": self.max_clarification_questions,
            "show_critique_concerns":      self.show_critique_concerns,
            "show_validation_detail":      self.show_validation_detail,
        }

    def __repr__(self) -> str:
        return (
            f"PILModeProfile({self.mode}, "
            f"assumption={self.auto_assumption_level}, "
            f"block={self.risk_block_level}, "
            f"explain={self.explanation_level})"
        )


# ── Profile Registry ──────────────────────────────────────────────────────────

_PROFILES: dict[str, PILModeProfile] = {
    "FULLY_ASSISTED": PILModeProfile(
        mode                        = "FULLY_ASSISTED",
        auto_assumption_level       = AutoAssumptionLevel.HIGH,
        risk_block_level            = RiskBlockLevel.LOW,
        explanation_level           = ExplanationLevel.FULL,
        suggestion_policy           = SuggestionPolicy.ALWAYS,
        auto_commit_policy          = AutoCommitPolicy.LOW_RISK,
        max_clarification_questions = 2,
        show_critique_concerns      = False,
        show_validation_detail      = False,
    ),
    "COLLABORATIVE": PILModeProfile(
        mode                        = "COLLABORATIVE",
        auto_assumption_level       = AutoAssumptionLevel.MODERATE,
        risk_block_level            = RiskBlockLevel.MEDIUM,
        explanation_level           = ExplanationLevel.STANDARD,
        suggestion_policy           = SuggestionPolicy.SIGNIFICANT,
        auto_commit_policy          = AutoCommitPolicy.LOW_RISK,
        max_clarification_questions = 3,
        show_critique_concerns      = True,
        show_validation_detail      = False,
    ),
    "ADVANCED": PILModeProfile(
        mode                        = "ADVANCED",
        auto_assumption_level       = AutoAssumptionLevel.LOW,
        risk_block_level            = RiskBlockLevel.HIGH,
        explanation_level           = ExplanationLevel.TERSE,
        suggestion_policy           = SuggestionPolicy.COLLAPSED,
        auto_commit_policy          = AutoCommitPolicy.NEVER,
        max_clarification_questions = 1,
        show_critique_concerns      = True,
        show_validation_detail      = True,
    ),
    "ARCHITECT_MODE": PILModeProfile(
        mode                        = "ARCHITECT_MODE",
        auto_assumption_level       = AutoAssumptionLevel.NONE,
        risk_block_level            = RiskBlockLevel.MAXIMUM,
        explanation_level           = ExplanationLevel.NONE,
        suggestion_policy           = SuggestionPolicy.HIDDEN,
        auto_commit_policy          = AutoCommitPolicy.NEVER,
        max_clarification_questions = 0,
        show_critique_concerns      = True,
        show_validation_detail      = True,
    ),
}


def get_pil_profile(mode: str) -> PILModeProfile:
    """
    Returns the PILModeProfile for the given mode string.

    Raises ValueError for unknown modes.
    """
    try:
        return _PROFILES[mode]
    except KeyError:
        raise ValueError(
            f"Unknown assistance mode: {mode!r}. "
            f"Valid: {sorted(_PROFILES.keys())}"
        )


def all_modes() -> list[str]:
    """Returns all valid mode strings."""
    return list(_PROFILES.keys())
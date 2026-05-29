"""
pil_retry_policy.py — PILRetryPolicy
======================================
PIL-level quality failure retry. Distinct from InferenceRetryPolicy.

## Two Retry Layers — Do Not Confuse

    InferenceRetryPolicy (packages/inference/src/inference_retry_policy.py)
        → Transport-level: network errors, provider 5xx, timeouts
        → Retries the SAME call to a different provider
        → Transparent to PIL passes

    PILRetryPolicy (this file)
        → Quality-level: malformed JSON, failed self-critique, invalid paths
        → Re-runs the PASS with corrective context injected
        → Visible to PIL passes and llm_orchestrator

## Retry Budget (Locked)

    MAX_ATTEMPTS_PER_PASS = 2
        Pass 1 gets up to 2 attempts.
        Pass 2 gets up to 2 attempts.
        Passes 3-5 get up to 2 attempts.

    MAX_TOTAL_REATTEMPTS = 3
        The entire 5-pass pipeline may restart at most 3 times total
        (i.e. 3 full pipeline runs). If the 3rd run still fails Pass 3
        (self-critique), the pipeline escalates to ClarificationEngine.

    These limits are HARD. No configuration overrides them.

## Escalation

    When retry budget is exhausted, PILRetryPolicy raises
    RetryBudgetExhausted. llm_orchestrator catches this and:
        1. Returns a PipelineResult with needs_clarification=True
        2. llm_orchestrator signals ClarificationEngine to generate
           a targeted question about the failing intent.

## Corrective Context

    On each retry, PILRetryPolicy prepends a correction instruction
    to the next attempt's prompt:
        "Your previous response had the following issues: {reasons}.
         Correct these and try again."
    This is injected as a non-cacheable PromptPart at the front of the
    dynamic section. The cached prefix (constraints) is never modified.

## Usage

    policy = PILRetryPolicy()

    # Check before attempting a pass
    policy.begin_pass("pass2_dsl_draft")

    # Record a failure
    policy.record_failure("pass2_dsl_draft", reasons=["invalid JSON", "missing path"])

    # Check if can retry
    if policy.can_retry("pass2_dsl_draft"):
        correction = policy.correction_prompt("pass2_dsl_draft")
        # inject correction into next attempt
    else:
        raise RetryBudgetExhausted(...)

    # Record a success
    policy.record_success("pass2_dsl_draft")
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Limits ────────────────────────────────────────────────────────────────────

MAX_ATTEMPTS_PER_PASS  = 2
MAX_TOTAL_REATTEMPTS   = 3

# All known PIL pass labels in execution order
PASS_LABELS: tuple[str, ...] = (
    "pass1_planning",
    "pass2_dsl_draft",
    "pass3_self_critique",
    "pass4_determinism_audit",
    "pass5_final_output",
)


# ── Exceptions ────────────────────────────────────────────────────────────────

class RetryBudgetExhausted(Exception):
    """
    Raised when PIL retry budget is exhausted.
    llm_orchestrator catches this and routes to ClarificationEngine.
    """
    def __init__(self, pass_label: str, attempts: int, reasons: list[str]) -> None:
        self.pass_label = pass_label
        self.attempts   = attempts
        self.reasons    = reasons
        super().__init__(
            f"PIL retry budget exhausted for '{pass_label}' "
            f"after {attempts} attempt(s). "
            f"Last failures: {reasons}. "
            f"Escalating to ClarificationEngine."
        )


# ── Pass State ────────────────────────────────────────────────────────────────

@dataclass
class PassState:
    """Tracks retry state for one pass label within one pipeline run."""
    label:         str
    attempts:      int       = 0
    failures:      int       = 0
    succeeded:     bool      = False
    failure_log:   list[list[str]] = field(default_factory=list)  # per-attempt reasons

    @property
    def last_failure_reasons(self) -> list[str]:
        return self.failure_log[-1] if self.failure_log else []

    @property
    def can_retry(self) -> bool:
        return not self.succeeded and self.attempts < MAX_ATTEMPTS_PER_PASS


# ── PIL Retry Policy ──────────────────────────────────────────────────────────

class PILRetryPolicy:
    """
    Tracks and enforces PIL-level quality retry budget.

    One instance per pipeline run. NOT shared across pipeline runs.
    llm_orchestrator creates a fresh instance for each prompt.

    Usage
    -----
        policy = PILRetryPolicy()

        for attempt in range(MAX_ATTEMPTS_PER_PASS):
            policy.begin_attempt("pass2_dsl_draft")
            try:
                result = run_pass2(...)
                policy.record_success("pass2_dsl_draft")
                break
            except OutputParseError as e:
                policy.record_failure("pass2_dsl_draft", reasons=[str(e)])
                if not policy.can_retry("pass2_dsl_draft"):
                    raise RetryBudgetExhausted(...)
                # inject correction and loop
    """

    def __init__(self) -> None:
        self._states:          dict[str, PassState] = {}
        self._pipeline_runs:   int = 0   # full pipeline reattempts (max 3)

    # ── Pass tracking ─────────────────────────────────────────────────────────

    def begin_attempt(self, pass_label: str) -> None:
        """
        Registers the start of one attempt at a pass.
        Must be called before each attempt.
        """
        if pass_label not in self._states:
            self._states[pass_label] = PassState(label=pass_label)
        self._states[pass_label].attempts += 1

    def record_success(self, pass_label: str) -> None:
        """Records that a pass attempt succeeded."""
        state = self._states.get(pass_label)
        if state:
            state.succeeded = True

    def record_failure(
        self,
        pass_label: str,
        reasons:    list[str],
    ) -> None:
        """
        Records that a pass attempt failed with the given reasons.
        Increments failure count and stores reasons for correction prompt.
        """
        if pass_label not in self._states:
            self._states[pass_label] = PassState(label=pass_label)
        state = self._states[pass_label]
        state.failures += 1
        state.failure_log.append(list(reasons))

    def can_retry(self, pass_label: str) -> bool:
        """
        Returns True if this pass may be attempted again.
        False when at MAX_ATTEMPTS_PER_PASS or already succeeded.
        """
        state = self._states.get(pass_label)
        if state is None:
            return True   # not yet attempted
        return state.can_retry

    def correction_prompt(self, pass_label: str) -> str:
        """
        Returns a correction instruction to inject into the next attempt.
        Empty string if no failures recorded for this pass.
        """
        state = self._states.get(pass_label)
        if not state or not state.last_failure_reasons:
            return ""
        reasons_text = "; ".join(state.last_failure_reasons)
        return (
            f"CORRECTION REQUIRED: Your previous response had the following "
            f"issues that must be fixed in this attempt:\n{reasons_text}\n"
            f"Carefully address each issue before generating your response."
        )

    # ── Pipeline reattempt tracking ───────────────────────────────────────────

    def begin_pipeline_reattempt(self) -> None:
        """
        Records one full pipeline reattempt.
        Call when restarting all 5 passes from Pass 1.
        """
        self._pipeline_runs += 1
        # Reset per-pass state for the new run
        self._states.clear()

    def can_reattempt_pipeline(self) -> bool:
        """Returns True if the full pipeline may be restarted."""
        return self._pipeline_runs < MAX_TOTAL_REATTEMPTS

    @property
    def pipeline_runs(self) -> int:
        return self._pipeline_runs

    # ── Inspection ────────────────────────────────────────────────────────────

    def pass_state(self, pass_label: str) -> PassState | None:
        return self._states.get(pass_label)

    def attempts_for(self, pass_label: str) -> int:
        state = self._states.get(pass_label)
        return state.attempts if state else 0

    def failures_for(self, pass_label: str) -> int:
        state = self._states.get(pass_label)
        return state.failures if state else 0

    def all_passed(self) -> bool:
        """True if all 5 passes have succeeded in the current run."""
        return all(
            self._states.get(label, PassState(label=label)).succeeded
            for label in PASS_LABELS
        )

    def summary(self) -> dict:
        return {
            "pipeline_runs": self._pipeline_runs,
            "passes": {
                label: {
                    "attempts":  self.attempts_for(label),
                    "failures":  self.failures_for(label),
                    "succeeded": (self._states[label].succeeded
                                  if label in self._states else False),
                }
                for label in PASS_LABELS
            },
        }

    def __repr__(self) -> str:
        succeeded = sum(
            1 for s in self._states.values() if s.succeeded
        )
        return (
            f"PILRetryPolicy(runs={self._pipeline_runs}, "
            f"passes_done={succeeded}/{len(PASS_LABELS)})"
        )
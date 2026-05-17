"""
intent_intake_layer.py — IntentIntakeLayer
============================================
Entry point for the PIL Intent Intake pipeline.

Orchestrates the four intake submodules in sequence and produces
an IntentEnvelope ready for the ContextAssembler.

## Pipeline

    raw prompt (str)
        ↓
    PromptNormalizer.normalize()
        → NormalizedPrompt (trimmed, quote-normalized, token-estimated)
        ↓
    RiskPreScanner.scan()
        → ScanResult (risk_score, risk_flags, is_blocked)
        ↓
    [if is_blocked] → return blocked IntentEnvelope immediately
        ↓
    PILIntentClassifier.classify_normalized()
        → PILClassificationResult (category, confidence, layer)
        ↓
    IntentEnvelope (assembled here)

## Short-Circuit on Block

    If RiskPreScanner returns is_blocked=True, the pipeline returns
    an IntentEnvelope.blocked() immediately. The PILIntentClassifier
    is NOT called. No LLM inference is triggered.
    The blocked envelope carries risk_score=1.0 and the fired risk_flags.

## requires_clarification Assembly

    requires_clarification is set to True when ANY of:
        - classifier result has requires_clarification=True
        - confidence < mode-appropriate threshold
        - The category is UNKNOWN regardless of confidence

    Mode thresholds for requires_clarification:
        FULLY_ASSISTED   confidence < 0.65 → ask
        COLLABORATIVE    confidence < 0.65 → ask
        ADVANCED         confidence < 0.45 → ask (expert: fewer interrupts)
        ARCHITECT_MODE   never → always proceed

## Thread Safety

    IntentIntakeLayer is stateless — safe to share across sessions.
    All submodule instances are shared (they are stateless too).
"""

from __future__ import annotations

from dataclasses import dataclass

from intent_envelope import IntentEnvelope, PILIntentCategory, RiskLevel
from prompt_normalizer import PromptNormalizer, NormalizedPrompt
from risk_prescanner import RiskPreScanner, ScanResult
from intent_classifier import PILIntentClassifier, PILClassificationResult


# ── Mode-specific clarification thresholds ────────────────────────────────────

_CLARIFICATION_THRESHOLDS: dict[str, float] = {
    "FULLY_ASSISTED":  0.65,
    "COLLABORATIVE":   0.65,
    "ADVANCED":        0.45,
    "ARCHITECT_MODE":  0.0,   # never requires clarification from intake
}

_DEFAULT_THRESHOLD = 0.65


# ── Intake Result ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IntakeResult:
    """
    Full output of IntentIntakeLayer.process().

    Attributes
    ----------
    envelope : IntentEnvelope
        The assembled intent envelope for downstream PIL modules.
    normalized : NormalizedPrompt
        The normalized prompt (kept for debugging / telemetry).
    scan : ScanResult
        The raw risk scan result.
    classification : PILClassificationResult | None
        The raw classification result. None when blocked before classification.
    """
    envelope:       IntentEnvelope
    normalized:     NormalizedPrompt
    scan:           ScanResult
    classification: PILClassificationResult | None = None

    @property
    def was_blocked(self) -> bool:
        return self.envelope.is_blocked

    @property
    def needs_clarification(self) -> bool:
        return self.envelope.requires_clarification

    def __repr__(self) -> str:
        return (
            f"IntakeResult({self.envelope.intent_category!r}, "
            f"conf={self.envelope.confidence:.2f}, "
            f"risk={self.envelope.risk_level})"
        )


# ── Intent Intake Layer ───────────────────────────────────────────────────────

class IntentIntakeLayer:
    """
    PIL Intent Intake pipeline orchestrator.

    Stateless — one instance may be shared across all builder sessions.

    Usage
    -----
        intake = IntentIntakeLayer()
        result = intake.process("make the zombie faster", session_id="s1")

        if result.was_blocked:
            # surface risk_flags to user
            ...
        elif result.needs_clarification:
            # route to ClarificationEngine
            ...
        else:
            # pass result.envelope to ContextAssembler
            ...
    """

    def __init__(self) -> None:
        self._normalizer  = PromptNormalizer()
        self._scanner     = RiskPreScanner()
        self._classifier  = PILIntentClassifier()

    def process(
        self,
        raw_prompt:      str,
        assistance_mode: str        = "COLLABORATIVE",
        session_id:      str | None = None,
    ) -> IntakeResult:
        """
        Runs the full intake pipeline on a raw prompt.

        Parameters
        ----------
        raw_prompt : str
            Unprocessed text from the builder UI.
        assistance_mode : str
            Current ModeController mode — affects clarification threshold.
        session_id : str | None
            Session identifier for provenance.

        Returns
        -------
        IntakeResult
            Always returns. Never raises.
        """
        # ── Step 1: Normalize ─────────────────────────────────────────────────
        normalized = self._normalizer.normalize(raw_prompt)

        if normalized.is_empty:
            envelope = IntentEnvelope.unknown(
                raw_text        = raw_prompt,
                assistance_mode = assistance_mode,
                session_id      = session_id,
            )
            return IntakeResult(
                envelope       = envelope,
                normalized     = normalized,
                scan           = ScanResult(risk_score=0.0, risk_flags=(), is_blocked=False),
                classification = None,
            )

        # ── Step 2: Risk pre-scan ─────────────────────────────────────────────
        scan = self._scanner.scan(normalized.text)

        if scan.is_blocked:
            envelope = IntentEnvelope.blocked(
                raw_text   = raw_prompt,
                risk_flags = scan.risk_flags,
                session_id = session_id,
            )
            # Patch assistance_mode onto the frozen dataclass via replace
            import dataclasses
            envelope = dataclasses.replace(envelope, assistance_mode=assistance_mode)
            return IntakeResult(
                envelope       = envelope,
                normalized     = normalized,
                scan           = scan,
                classification = None,
            )

        # ── Step 3: Classify ──────────────────────────────────────────────────
        classification = self._classifier.classify_normalized(normalized.text)

        # ── Step 4: Determine requires_clarification ──────────────────────────
        threshold = _CLARIFICATION_THRESHOLDS.get(assistance_mode, _DEFAULT_THRESHOLD)
        requires_clarification = (
            classification.requires_clarification
            or classification.confidence < threshold
            or classification.category == PILIntentCategory.UNKNOWN
        )

        # ── Step 5: Assemble envelope ─────────────────────────────────────────
        envelope = IntentEnvelope(
            intent_category        = classification.category,
            normalized_text        = normalized.text,
            raw_text               = raw_prompt,
            assistance_mode        = assistance_mode,
            confidence             = classification.confidence,
            requires_clarification = requires_clarification,
            risk_score             = scan.risk_score,
            risk_flags             = scan.risk_flags,
            estimated_tokens       = normalized.estimated_tokens,
            detected_language      = normalized.detected_language,
            session_id             = session_id,
        )

        return IntakeResult(
            envelope       = envelope,
            normalized     = normalized,
            scan           = scan,
            classification = classification,
        )

    def process_batch(
        self,
        prompts:         list[str],
        assistance_mode: str        = "COLLABORATIVE",
        session_id:      str | None = None,
    ) -> list[IntakeResult]:
        """Processes a list of prompts. Each is independent."""
        return [self.process(p, assistance_mode, session_id) for p in prompts]
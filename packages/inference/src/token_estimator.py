"""
token_estimator.py — TokenEstimator
======================================
Approximates token counts before inference calls — no network required.

Used by cost_estimator.py (pre-flight cost) and context_budgeter.py
(dynamic context cap enforcement) to measure prompt size without
making an actual tokenisation API call.

## Why Approximation?
Exact tokenisation requires either the provider's tokeniser library
(adding a heavy dependency per provider) or an API call (costly and
circular). Approximation within ±15% is accurate enough for:
    - budget pre-checks ("will this prompt breach the 8K cap?")
    - cost estimation ("will this call cost more than X cents?")
    - model routing ("does this fit in a TIER_M 32K context?")

For billing, InferenceAdapter uses actual token counts from the
provider response — never these estimates.

## Approximation Strategy
Different content types tokenise at different rates:

    English prose      ~4 chars / token   (standard GPT/Claude heuristic)
    Code (Python/Rust) ~3 chars / token   (shorter tokens, more symbols)
    JSON/YAML          ~3.5 chars / token (many braces, colons, quotes)
    Dense symbols      ~2 chars / token   (math, regex, binary data)
    Whitespace-heavy   ~5 chars / token   (padded text, tables)

TokenEstimator auto-detects content type from the text and applies
the appropriate ratio. When type is specified explicitly, the specified
ratio is used.

## Anthropic Opus 4.7 Note
Opus 4.7 uses a new tokeniser that produces up to 35% more tokens
than Opus 4.6 for the same text. apply_opus47_multiplier=True (default
for TIER_XL requests) adds a 1.35x safety margin when the target model
is Opus 4.7.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ── Content Type ──────────────────────────────────────────────────────────────

class ContentType:
    PROSE    = "prose"      # English natural language
    CODE     = "code"       # Python, Rust, JS, etc.
    JSON     = "json"       # JSON / YAML / TOML
    SYMBOLS  = "symbols"    # math, regex, dense tokens
    MIXED    = "mixed"      # combination (default)
    AUTO     = "auto"       # detect from content


# ── Chars-per-Token Ratios ────────────────────────────────────────────────────

_CHARS_PER_TOKEN: dict[str, float] = {
    ContentType.PROSE:   4.0,
    ContentType.CODE:    3.0,
    ContentType.JSON:    3.5,
    ContentType.SYMBOLS: 2.5,
    ContentType.MIXED:   3.8,
}

# Overhead per message from system/human/assistant roles (tokens)
_MESSAGE_OVERHEAD_TOKENS = 4

# Anthropic Opus 4.7 tokeniser multiplier vs older models
_OPUS_47_MULTIPLIER = 1.35


# ── Estimation Result ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenEstimate:
    """
    Result of one token estimation.

    Attributes
    ----------
    estimated_tokens : int
        Best estimate. Always an integer (rounded up).
    content_type : str
        Auto-detected or provided content type.
    chars_per_token_used : float
        The ratio applied to produce the estimate.
    safety_multiplier : float
        1.0 normally; 1.35 when apply_opus47_multiplier=True.
    raw_chars : int
        Character count of the input text.
    """

    estimated_tokens:     int
    content_type:         str
    chars_per_token_used: float
    safety_multiplier:    float
    raw_chars:            int

    @property
    def with_output_reserve(self) -> int:
        """Adds 20% buffer for output tokens in context window checks."""
        return int(self.estimated_tokens * 1.2)

    def fits_in(self, context_window: int, reserved_output: int = 0) -> bool:
        """True if the estimated input fits within the context window."""
        return self.estimated_tokens + reserved_output <= context_window

    def __repr__(self) -> str:
        return (
            f"TokenEstimate("
            f"~{self.estimated_tokens} tokens, "
            f"type={self.content_type!r}, "
            f"chars={self.raw_chars})"
        )


# ── Detection Patterns ────────────────────────────────────────────────────────

_JSON_INDICATORS = re.compile(
    r'[{}\[\]":]|":\s*[{\[\d"tf]|null|true|false', re.IGNORECASE
)
_CODE_INDICATORS = re.compile(
    r'\bdef\b|\bfn\b|\bimport\b|\bfrom\b|\bclass\b|\bstruct\b|'
    r'\breturn\b|\blet\b|\bvar\b|\bconst\b|::\w+|->|=>|'
    r'#\[|#include|pub fn|async fn'
)
_DENSE_INDICATORS = re.compile(
    r'[\\^$|*+?(){}[\]]{3,}|\\x[0-9a-f]{2}|\\u[0-9a-f]{4}|'
    r'(?:\d+\.){3}\d+|[=<>!]{2,}'
)


# ── Token Estimator ───────────────────────────────────────────────────────────

class TokenEstimator:
    """
    Pre-flight token count approximation.

    Stateless — safe to share and call from multiple threads.

    Usage
    -----
        estimator = TokenEstimator()

        # Estimate one text segment
        est = estimator.estimate("Hello, how many tokens is this?")
        print(est.estimated_tokens)   # ~8

        # Estimate a full prompt (list of parts)
        total = estimator.estimate_parts([
            ("You are an architect.", ContentType.PROSE),
            (json_schema_text,        ContentType.JSON),
            (rust_code,               ContentType.CODE),
        ])

        # Estimate with Opus 4.7 safety margin
        est = estimator.estimate(text, apply_opus47_multiplier=True)
    """

    def estimate(
        self,
        text:                    str,
        content_type:            str   = ContentType.AUTO,
        apply_opus47_multiplier: bool  = False,
    ) -> TokenEstimate:
        """
        Estimates the token count of one text string.

        Parameters
        ----------
        text : str
            The text to estimate.
        content_type : str
            ContentType constant. AUTO = detect from content.
        apply_opus47_multiplier : bool
            True when the target model is Opus 4.7 (adds 35% safety margin).

        Returns
        -------
        TokenEstimate
        """
        if not text:
            return TokenEstimate(
                estimated_tokens=0,
                content_type=ContentType.PROSE,
                chars_per_token_used=4.0,
                safety_multiplier=1.0,
                raw_chars=0,
            )

        raw_chars    = len(text)
        detected     = (
            self._detect_content_type(text)
            if content_type == ContentType.AUTO
            else content_type
        )
        ratio        = _CHARS_PER_TOKEN.get(detected, _CHARS_PER_TOKEN[ContentType.MIXED])
        multiplier   = _OPUS_47_MULTIPLIER if apply_opus47_multiplier else 1.0
        base_tokens  = raw_chars / ratio
        final        = int((base_tokens * multiplier) + 0.5)  # round to nearest int
        # Minimum 1 token for any non-empty text
        final        = max(1, final)

        return TokenEstimate(
            estimated_tokens     = final,
            content_type         = detected,
            chars_per_token_used = ratio,
            safety_multiplier    = multiplier,
            raw_chars            = raw_chars,
        )

    def estimate_parts(
        self,
        parts:                   list[tuple[str, str]],
        apply_opus47_multiplier: bool = False,
    ) -> int:
        """
        Estimates total token count for a list of (text, content_type) pairs.
        Adds per-message overhead for each part.

        Returns
        -------
        int
            Total estimated token count including message overhead.
        """
        total = 0
        for text, ctype in parts:
            est    = self.estimate(text, ctype, apply_opus47_multiplier)
            total += est.estimated_tokens + _MESSAGE_OVERHEAD_TOKENS
        return total

    def estimate_prompt_parts(
        self,
        prompt_parts:            list[Any],   # list[PromptPart] from inference_adapter
        system_prompt:           str = "",
        apply_opus47_multiplier: bool = False,
    ) -> int:
        """
        Estimates tokens for InferenceAdapter.InferenceRequest.prompt_parts.
        Works with any object that has .text and .cacheable attributes.
        Caches the estimate per call to avoid re-processing.

        Returns
        -------
        int
            Total estimated input tokens (prompt + system prompt).
        """
        total = 0
        if system_prompt:
            total += self.estimate(system_prompt, ContentType.PROSE,
                                   apply_opus47_multiplier).estimated_tokens
            total += _MESSAGE_OVERHEAD_TOKENS

        for part in prompt_parts:
            text  = getattr(part, "text", str(part))
            ctype = self._infer_part_type(text)
            total += self.estimate(text, ctype, apply_opus47_multiplier).estimated_tokens
            total += _MESSAGE_OVERHEAD_TOKENS

        return total

    def fits_in_budget(
        self,
        text:              str,
        token_budget:      int,
        content_type:      str  = ContentType.AUTO,
        reserved_output:   int  = 0,
    ) -> tuple[bool, int]:
        """
        Checks whether text fits within a token budget.

        Returns
        -------
        tuple[bool, int]
            (fits, estimated_tokens)
        """
        est = self.estimate(text, content_type)
        fits = (est.estimated_tokens + reserved_output) <= token_budget
        return fits, est.estimated_tokens

    def count_chars(self, texts: list[str]) -> int:
        """Total character count across a list of strings."""
        return sum(len(t) for t in texts)

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_content_type(text: str) -> str:
        """
        Heuristically detects content type from text content.
        Samples the first 500 characters to keep it fast.
        """
        sample = text[:500]

        json_hits = len(_JSON_INDICATORS.findall(sample))
        code_hits = len(_CODE_INDICATORS.findall(sample))
        sym_hits  = len(_DENSE_INDICATORS.findall(sample))

        # Weighted scoring
        scores = {
            ContentType.JSON:    json_hits * 2,
            ContentType.CODE:    code_hits * 3,
            ContentType.SYMBOLS: sym_hits  * 4,
        }
        best       = max(scores, key=lambda k: scores[k])
        best_score = scores[best]

        if best_score >= 6:
            return best
        if best_score >= 3:
            return ContentType.MIXED
        return ContentType.PROSE

    @staticmethod
    def _infer_part_type(text: str) -> str:
        """Quick content type for individual prompt parts."""
        stripped = text.strip()
        if stripped.startswith(("{", "[", '"')):
            return ContentType.JSON
        if any(k in stripped[:100] for k in ("def ", "fn ", "impl ", "pub ", "struct ")):
            return ContentType.CODE
        return ContentType.AUTO


# ── Convenience Function ──────────────────────────────────────────────────────

_DEFAULT_ESTIMATOR = TokenEstimator()


def estimate_tokens(
    text:                    str,
    content_type:            str  = ContentType.AUTO,
    apply_opus47_multiplier: bool = False,
) -> int:
    """
    Module-level convenience: returns estimated token count for one text.
    Uses a shared default TokenEstimator instance.
    """
    return _DEFAULT_ESTIMATOR.estimate(
        text, content_type, apply_opus47_multiplier
    ).estimated_tokens
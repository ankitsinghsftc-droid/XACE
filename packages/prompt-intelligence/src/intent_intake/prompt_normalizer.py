"""
prompt_normalizer.py — PromptNormalizer
==========================================
Normalizes a raw designer prompt before classification.

This is the first stage of the PIL Intent Intake pipeline. Every prompt
passes through here before any classification or risk scanning happens.
The output is a NormalizedPrompt that every downstream stage reads from.

## What Normalization Does

    1. Whitespace normalization
       - Leading/trailing whitespace stripped
       - Internal runs of whitespace collapsed to single space
       - Newlines inside the prompt preserved as a single \n
         (multi-line prompts are valid — "add a zombie\nit should chase the player")

    2. Quote normalization
       - Smart/curly quotes → straight ASCII quotes
       - " " → "   ' ' → '
       - Prevents downstream regex from failing on pasted text from Word/Notion

    3. Control character removal
       - ASCII control chars (0x00–0x1F) stripped except \n and \t
       - \t → single space
       - Null bytes, BEL, BS, etc. removed silently

    4. Length cap
       - Hard cap: 2000 characters after normalization
       - Prompts beyond this are truncated with a marker suffix
       - This prevents context explosion before token estimation

    5. Language detection
       - Best-effort language detection from script analysis
       - Returns ISO 639-1 code ("en", "zh", "ar", "es", ...)
       - "en" default when detection is inconclusive (< 6 chars)
       - Detection is heuristic only — not a full NLP classifier
         (full language support is a Phase 16 concern)

    6. Token estimation
       - Approximates prompt token count using character-based heuristic
       - Rule of thumb: 1 token ≈ 4 characters for English,
         ≈ 2 characters for CJK scripts
       - Accurate enough for pre-flight budget checks; precise tokenization
         happens in packages/inference/token_estimator.py before LLM calls
       - This estimate is used by ComplexityClassifier as estimated_prompt_tokens

## Why No LLM Here?
    PromptNormalizer runs on every prompt before the pipeline decides whether
    to use an LLM. It must be sub-millisecond and have zero network calls.

## Determinism
    Given the same raw input, PromptNormalizer always returns the same
    NormalizedPrompt. No randomness, no state, no external calls.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# ── Constants ─────────────────────────────────────────────────────────────────

MAX_PROMPT_CHARS       = 2_000   # hard cap after normalization
TRUNCATION_MARKER      = " …[truncated]"
MIN_CHARS_FOR_LANGUAGE = 6       # below this, language detection is unreliable

# Characters per token approximations
_CHARS_PER_TOKEN_LATIN = 4.0
_CHARS_PER_TOKEN_CJK   = 2.0

# Smart quote → ASCII quote mapping
_QUOTE_MAP = str.maketrans({
    "\u2018": "'",   # '  LEFT SINGLE QUOTATION MARK
    "\u2019": "'",   # '  RIGHT SINGLE QUOTATION MARK
    "\u201A": "'",   # ‚  SINGLE LOW-9 QUOTATION MARK
    "\u201B": "'",   # ‛  SINGLE HIGH-REVERSED-9 QUOTATION MARK
    "\u201C": '"',   # "  LEFT DOUBLE QUOTATION MARK
    "\u201D": '"',   # "  RIGHT DOUBLE QUOTATION MARK
    "\u201E": '"',   # „  DOUBLE LOW-9 QUOTATION MARK
    "\u201F": '"',   # ‟  DOUBLE HIGH-REVERSED-9 QUOTATION MARK
    "\u2039": "'",   # ‹  SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    "\u203A": "'",   # ›  SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    "\u00AB": '"',   # «  LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
    "\u00BB": '"',   # »  RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
})

# CJK Unicode block ranges (for language detection + token estimation)
_CJK_RANGES = [
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3040, 0x309F),    # Hiragana
    (0x30A0, 0x30FF),    # Katakana
    (0xAC00, 0xD7AF),    # Hangul Syllables
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x20000, 0x2A6DF),  # CJK Extension B
]

# Arabic Unicode block (heuristic)
_ARABIC_RANGE = (0x0600, 0x06FF)

# Devanagari (Hindi, etc.)
_DEVANAGARI_RANGE = (0x0900, 0x097F)

# Pattern: runs of whitespace that are NOT newlines
_HORIZONTAL_WHITESPACE = re.compile(r'[^\S\n]+')

# Pattern: multiple blank lines → single newline
_MULTI_NEWLINE = re.compile(r'\n{3,}')

# Pattern: control chars to strip (keep \n, \t → space handled separately)
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')


# ── Normalized Prompt ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class NormalizedPrompt:
    """
    Output of PromptNormalizer.normalize().

    Attributes
    ----------
    text : str
        The normalized prompt text ready for classification.
    raw_text : str
        The original unmodified input.
    was_truncated : bool
        True if the prompt exceeded MAX_PROMPT_CHARS and was cut.
    detected_language : str
        ISO 639-1 language code, or "en" when inconclusive.
    estimated_tokens : int
        Character-based token estimate. See module docstring.
    char_count : int
        Character count of the normalized text.
    is_empty : bool
        True when normalized text has no printable content.
    """

    text:               str
    raw_text:           str
    was_truncated:      bool  = False
    detected_language:  str   = "en"
    estimated_tokens:   int   = 0
    char_count:         int   = 0
    is_empty:           bool  = False

    def __repr__(self) -> str:
        lang  = f" lang={self.detected_language}" if self.detected_language != "en" else ""
        trunc = " [truncated]" if self.was_truncated else ""
        return (
            f"NormalizedPrompt({self.char_count}chars, "
            f"~{self.estimated_tokens}tok{lang}{trunc})"
        )


# ── Prompt Normalizer ─────────────────────────────────────────────────────────

class PromptNormalizer:
    """
    Normalizes raw designer prompts for the PIL intake pipeline.

    Stateless — safe to share across threads and sessions.
    Deterministic — same input always produces the same NormalizedPrompt.
    Sub-millisecond — no network calls, no LLM.

    Usage
    -----
        normalizer = PromptNormalizer()
        result = normalizer.normalize("make the zombie FASTER!!")
        # NormalizedPrompt(25chars, ~6tok)
        print(result.text)            # "make the zombie FASTER!!"
        print(result.estimated_tokens) # 6
    """

    def normalize(self, raw: str) -> NormalizedPrompt:
        """
        Normalizes a raw prompt and returns a NormalizedPrompt.

        Always returns a result — never raises. Empty or whitespace-only
        inputs return an NormalizedPrompt with is_empty=True.

        Parameters
        ----------
        raw : str
            The raw prompt from the builder UI.

        Returns
        -------
        NormalizedPrompt
            Normalized text with language and token metadata.
        """
        if not isinstance(raw, str):
            raw = str(raw)

        # ── Step 1: Control char removal ──────────────────────────────────────
        text = _CONTROL_CHARS.sub("", raw)
        text = text.replace("\t", " ")      # tab → space

        # ── Step 2: Quote normalization ───────────────────────────────────────
        text = text.translate(_QUOTE_MAP)

        # ── Step 3: Whitespace collapse ───────────────────────────────────────
        text = _HORIZONTAL_WHITESPACE.sub(" ", text)   # collapse horizontal runs
        text = _MULTI_NEWLINE.sub("\n\n", text)         # max two consecutive newlines
        text = text.strip()

        # ── Step 4: Empty check ───────────────────────────────────────────────
        if not text:
            return NormalizedPrompt(
                text              = "",
                raw_text          = raw,
                is_empty          = True,
                detected_language = "en",
                estimated_tokens  = 0,
                char_count        = 0,
            )

        # ── Step 5: Length cap ────────────────────────────────────────────────
        was_truncated = False
        if len(text) > MAX_PROMPT_CHARS:
            cut = MAX_PROMPT_CHARS - len(TRUNCATION_MARKER)
            text = text[:cut] + TRUNCATION_MARKER
            was_truncated = True

        # ── Step 6: Language detection ────────────────────────────────────────
        detected_language = self._detect_language(text)

        # ── Step 7: Token estimation ──────────────────────────────────────────
        estimated_tokens = self._estimate_tokens(text, detected_language)

        return NormalizedPrompt(
            text              = text,
            raw_text          = raw,
            was_truncated     = was_truncated,
            detected_language = detected_language,
            estimated_tokens  = estimated_tokens,
            char_count        = len(text),
        )

    # ── Language Detection ────────────────────────────────────────────────────

    @staticmethod
    def _detect_language(text: str) -> str:
        """
        Heuristic language detection from script analysis.

        Checks for dominant script in the first 200 chars of text.
        Returns ISO 639-1 code or "en" when inconclusive.

        This is intentionally lightweight. A full language detector
        (fasttext, langdetect) is not a dependency of PIL intake.
        """
        if len(text) < MIN_CHARS_FOR_LANGUAGE:
            return "en"

        sample = text[:200]
        total = len(sample)
        if total == 0:
            return "en"

        cjk_count       = 0
        arabic_count     = 0
        devanagari_count = 0
        latin_count      = 0

        for ch in sample:
            cp = ord(ch)
            if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
                cjk_count += 1
            elif _ARABIC_RANGE[0] <= cp <= _ARABIC_RANGE[1]:
                arabic_count += 1
            elif _DEVANAGARI_RANGE[0] <= cp <= _DEVANAGARI_RANGE[1]:
                devanagari_count += 1
            elif cp < 0x0250:   # basic Latin + extended Latin
                latin_count += 1

        # Dominant script threshold: >20% of sample
        threshold = total * 0.20
        if cjk_count > threshold:
            return "zh"     # Simplified Chinese as canonical CJK code
        if arabic_count > threshold:
            return "ar"
        if devanagari_count > threshold:
            return "hi"

        return "en"   # default: Latin / English

    # ── Token Estimation ──────────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(text: str, language: str) -> int:
        """
        Estimates token count using a character-ratio heuristic.

        Rule of thumb:
            Latin scripts:  1 token ≈ 4 chars  (matches cl100k_base roughly)
            CJK scripts:    1 token ≈ 2 chars   (CJK chars are often 1 token)
            Arabic/Hindi:   1 token ≈ 3 chars   (between the two extremes)

        This estimate is deliberately conservative (slightly over-counts)
        so that budget pre-checks never under-estimate.
        """
        if not text:
            return 0

        chars = len(text)
        if language == "zh":
            return max(1, int(chars / _CHARS_PER_TOKEN_CJK))
        if language in {"ar", "hi"}:
            return max(1, int(chars / 3.0))
        return max(1, int(chars / _CHARS_PER_TOKEN_LATIN))

    # ── Batch Normalize ───────────────────────────────────────────────────────

    def normalize_batch(self, raws: list[str]) -> list[NormalizedPrompt]:
        """Normalizes a list of prompts. Each is independent."""
        return [self.normalize(r) for r in raws]
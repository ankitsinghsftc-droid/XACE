"""
risk_prescanner.py — RiskPreScanner
=====================================
Safety pre-scan that runs on every normalized prompt before the PIL
classification pipeline commits to any path.

## Purpose

    The RiskPreScanner is a fast, deterministic, LLM-free guard layer.
    It does NOT block prompts — that is SafetyScopeGuard's job (Phase 13.9).
    It SCORES prompts and flags risk signals so that:

        - Downstream modules know to proceed with caution
        - The 5-pass LLM pipeline receives the risk context up front
        - Blocked intents are surfaced immediately without wasting inference

## What It Detects

    Category A — BLOCK (risk_score = 1.0, routed away from LLM):
        engine_internal_mutation
            Attempts to directly edit runtime, scheduler, physics engine,
            memory addresses, or other engine internals that XACE owns.
            Examples: "modify the ECS storage directly", "change the tick rate"

        code_injection_attempt
            Prompts that include executable code, script tags, eval(),
            shell commands, file system paths, or prompt injection patterns.
            Examples: "run this code: import os; os.system(...)",
                      "ignore previous instructions and..."

        forbidden_scope
            Attempts to modify UCL frozen components, determinism invariants,
            or core XACE architectural contracts.
            Examples: "change the entity ID format", "disable the mutation gate"

    Category B — HIGH (risk_score = 0.80–0.95):
        mass_destruction
            Deleting many things at once without specific targets.
            Examples: "delete all actors", "remove everything", "wipe the game"

        core_system_modification
            Modifying core systems that underpin all gameplay.
            Examples: "change how the movement system works fundamentally"

    Category C — MODERATE (risk_score = 0.55–0.79):
        destructive_without_target
            Removal intent without naming a specific target.
            Examples: "remove the actor", "delete the system"

        irreversible_global_change
            Changes that affect all entities globally.
            Examples: "change all health to 0", "set every actor's speed"

    Category D — LOW (risk_score = 0.20–0.54):
        vague_destructive_language
            Destruction-adjacent vocabulary without clear target.
            Examples: "kill it", "destroy the thing"

## Risk Score Composition

    Multiple signals accumulate. Final score = max(individual_scores)
    capped at 1.0. The BLOCK categories set score directly to 1.0.
    Risk score does NOT combine additively to avoid false positives from
    vocabulary overlap.

## Output

    ScanResult:
        risk_score : float [0.0–1.0]
        risk_flags : tuple[str, ...] — specific signal names detected
        is_blocked : bool — True only for Category A signals
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Risk Signal Definition ────────────────────────────────────────────────────

@dataclass(frozen=True)
class _RiskSignal:
    name:  str
    score: float
    patterns: tuple[re.Pattern, ...]


def _p(*exprs: str) -> tuple[re.Pattern, ...]:
    """Compiles patterns with IGNORECASE."""
    return tuple(re.compile(e, re.I) for e in exprs)


# ── Signal Registry ───────────────────────────────────────────────────────────
# Ordered by severity descending — first match at 1.0 short-circuits.

_SIGNALS: list[_RiskSignal] = [

    # ── Category A: BLOCK (score 1.0) ─────────────────────────────────────────

    _RiskSignal(
        name="code_injection_attempt",
        score=1.0,
        patterns=_p(
            r'\bimport\s+(?:os|sys|subprocess|shutil|socket)\b',
            r'\bos\s*\.\s*(?:system|popen|exec|remove|rmdir|listdir)\b',
            r'\bsubprocess\s*\.\s*(?:run|Popen|call|check_output)\b',
            r'\beval\s*\(',
            r'\bexec\s*\(',
            r'<script[^>]*>',
            r'\bignore (?:previous|above|all|your) instructions\b',
            r'\bforget (?:everything|all|your instructions)\b',
            r'\bprompt injection\b',
            r'\byou are now\b.{0,30}\b(?:an? |the )?(?:different|new|unrestricted|jailbreak)',
            r'\bsystem\s*\(\s*["\']',
            r'\.\./',          # path traversal
            r'\b/etc/passwd\b',
            r'\b(?:chmod|chown|sudo|rm -rf)\b',
        ),
    ),

    _RiskSignal(
        name="engine_internal_mutation",
        score=1.0,
        patterns=_p(
            r'\b(?:tick rate|tick_rate|ticks per second|simulation speed|physics timestep)\b',
            r'\b(?:ecs|entity component system)\s+(?:storage|internals?|core|memory)\b',
            r'\b(?:mutation gate|mutationgate)\b.{0,40}\b(?:disable|bypass|skip|remove|modify)\b',
            r'\b(?:disable|bypass|skip|remove|modify)\b.{0,40}\b(?:mutation gate|mutationgate)\b',
            r'\b(?:world hash|determinism guard|determinismguard)\b.{0,30}\b(?:disable|bypass|modify)\b',
            r'\b(?:raw memory|memory address|pointer|unsafe rust|unsafe block)\b',
            r'\bphase orchestrator\b.{0,30}\b(?:modify|change|bypass|disable)\b',
            r'\bsnapshot engine\b.{0,30}\b(?:disable|bypass|modify the format)\b',
        ),
    ),

    _RiskSignal(
        name="forbidden_scope",
        score=1.0,
        patterns=_p(
            r'\b(?:entity id|entity_id) (?:format|type|generation|counter)\b',
            r'\b(?:ucl|universal component library) (?:add|change|modify|extend|remove)\b',
            r'\badd (?:an? )?(?:11th|eleventh) (?:ucl )?component\b',
            r'\b(?:d[1-9]|d1[0-5]) (?:determinism )?rule\b.{0,30}\b(?:disable|remove|bypass|modify)\b',
            r'\b(?:global invariant|invariant i[1-9]|invariant i1[0-4])\b.{0,30}\b(?:disable|bypass|remove)\b',
        ),
    ),

    # ── Category B: HIGH (score 0.85–0.90) ────────────────────────────────────

    _RiskSignal(
        name="mass_destruction",
        score=0.90,
        patterns=_p(
            r'\b(?:delete|remove|destroy|wipe|clear)\b.{0,20}\b(?:all|every|everything|all actors|all systems|all rules|entire)\b',
            r'\b(?:all actors|all systems|all components|all rules|all entities)\b.{0,20}\b(?:delete|remove|destroy|wipe)\b',
            r'\bwipe (?:the )?(?:game|schema|cgs|world)\b',
            r'\bstart (?:from )?(?:scratch|over|fresh|blank)\b',
            r'\breset (?:everything|all|the (?:game|world|schema))\b',
        ),
    ),

    _RiskSignal(
        name="core_system_modification",
        score=0.85,
        patterns=_p(
            r'\b(?:fundamentally|completely|entirely) (?:change|rewrite|replace|redesign)\b.{0,30}\b(?:movement|physics|input|rendering|collision)\b',
            r'\breplace (?:the )?(?:movement system|physics system|input system)\b',
        ),
    ),

    # ── Category C: MODERATE (score 0.60–0.75) ────────────────────────────────

    _RiskSignal(
        name="destructive_without_target",
        score=0.65,
        patterns=_p(
            r'^(?:remove|delete|destroy) (?:the|an?) (?:actor|system|rule|component)$',
            r'\b(?:remove|delete|destroy) (?:the|an?) (?:actor|system|rule|component)\b(?!.{3,20}\b\w{3,})',
        ),
    ),

    _RiskSignal(
        name="irreversible_global_change",
        score=0.70,
        patterns=_p(
            r'\b(?:set|change)\b.{0,20}\b(?:all|every|each)\b.{0,30}\b(?:actors?|entities|components?)\b',
            r'\b(?:all|every) (?:actor|entity|player|zombie|enemy|npc)\'?s? (?:health|speed|damage)\b',
        ),
    ),

    # ── Category D: LOW (score 0.25–0.40) ────────────────────────────────────

    _RiskSignal(
        name="vague_destructive_language",
        score=0.30,
        patterns=_p(
            r'\b(?:kill|nuke|blow up|annihilate|obliterate)\b',
            r'\bget rid of (?:it|them|everything|all of it)\b',
            r'\bpermanently (?:delete|remove|destroy)\b',
        ),
    ),
]


# ── Scan Result ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScanResult:
    """
    Output of RiskPreScanner.scan().

    Attributes
    ----------
    risk_score : float
        Highest individual signal score [0.0–1.0].
        This is max(), NOT sum() — vocabulary overlap should not compound.
    risk_flags : tuple[str, ...]
        All signal names that fired, in detection order.
    is_blocked : bool
        True when any Category A signal (score=1.0) fired.
    """
    risk_score:  float
    risk_flags:  tuple[str, ...]
    is_blocked:  bool

    @property
    def is_clean(self) -> bool:
        return len(self.risk_flags) == 0

    def __repr__(self) -> str:
        if self.is_clean:
            return "ScanResult(CLEAN)"
        flags = ", ".join(self.risk_flags)
        blocked = " BLOCKED" if self.is_blocked else ""
        return f"ScanResult(score={self.risk_score:.2f}{blocked}, flags=[{flags}])"


# ── Risk Pre-Scanner ──────────────────────────────────────────────────────────

class RiskPreScanner:
    """
    Fast, deterministic, LLM-free safety pre-scan.

    Stateless — safe to share across threads and sessions.
    Evaluates all signals; returns max score with all fired flags.

    Usage
    -----
        scanner = RiskPreScanner()
        result = scanner.scan("delete all actors")
        # ScanResult(score=0.90 flags=[mass_destruction])

        result2 = scanner.scan("import os; os.system('rm -rf /')")
        # ScanResult(score=1.00 BLOCKED flags=[code_injection_attempt])
    """

    def scan(self, normalized_text: str) -> ScanResult:
        """
        Scans a normalized prompt for risk signals.

        Parameters
        ----------
        normalized_text : str
            Output of PromptNormalizer — already trimmed and cleaned.

        Returns
        -------
        ScanResult
            risk_score = max individual signal score detected.
            risk_flags = all fired signal names (may be multiple).
            is_blocked = True if any score=1.0 signal fired.
        """
        if not normalized_text:
            return ScanResult(risk_score=0.0, risk_flags=(), is_blocked=False)

        fired_flags: list[str] = []
        max_score:   float     = 0.0
        is_blocked:  bool      = False

        for signal in _SIGNALS:
            for pattern in signal.patterns:
                if pattern.search(normalized_text):
                    fired_flags.append(signal.name)
                    max_score   = max(max_score, signal.score)
                    if signal.score >= 1.0:
                        is_blocked = True
                    break   # one pattern match is enough to fire this signal

        return ScanResult(
            risk_score = min(max_score, 1.0),
            risk_flags = tuple(fired_flags),
            is_blocked = is_blocked,
        )

    def is_clean(self, normalized_text: str) -> bool:
        """Returns True if no risk signals fire for this prompt."""
        return self.scan(normalized_text).is_clean
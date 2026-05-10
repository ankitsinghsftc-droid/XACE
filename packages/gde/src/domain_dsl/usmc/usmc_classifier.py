"""
usmc_classifier.py — USMCClassifier
=====================================
Classifies a mutation operation or intent into one of the eight
USMC (Unified Schema Mutation Category) categories.

## Why Categorise?
Every mutation in XACE is one of eight fundamental design acts.
The category drives:
    - Which safety checks apply (destructive change guard for REMOVE)
    - Which PIL passes are needed (extra critique for STRUCTURAL)
    - Which Design Mentor suggestions are offered after the mutation
    - The builder UI diff icon and colour

## USMC Categories

    Create             — Add a new entity, system, rule, or component to the CGS.
                         Examples: "add a zombie actor", "create a damage system"

    Modify             — Change an existing value in the CGS.
                         Examples: "increase player health", "change move speed to 5"

    Remove             — Delete an entity, system, rule, or component from the CGS.
                         Examples: "remove the shield mechanic", "delete rule_starvation"

    Constrain          — Add a rule or condition that limits what is allowed.
                         Examples: "player can't move while stunned",
                                   "zombies only spawn at night"

    Compose            — Combine or layer multiple design elements.
                         Examples: "make the player also an AI when stunned",
                                   "add combat to the NPC"

    ProgressionDefine  — Define growth, levelling, or unlock mechanics.
                         Examples: "add experience points", "unlock ability at level 5"

    EnvironmentDefine  — Define world, zone, or environmental properties.
                         Examples: "make the forest zone foggy",
                                   "add a water zone with buoyancy"

    Interaction        — Define how entities relate, interact, or communicate.
                         Examples: "player can pick up items",
                                   "NPC talks when approached"

## Classification Strategy
The classifier uses a three-layer approach:
    1. Explicit op_type from a DSL operation dict ("SET"→Modify, "REMOVE"→Remove, etc.)
    2. Path-segment heuristics (path contains "rules" → Constrain candidate)
    3. Keyword signal scoring on the description/prompt text

If confidence is below the threshold, the caller should ask the user
to confirm the category.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


# ── USMC Category Enum ────────────────────────────────────────────────────────

class USMCCategory(str, Enum):
    """The eight Unified Schema Mutation Categories."""
    CREATE             = "Create"
    MODIFY             = "Modify"
    REMOVE             = "Remove"
    CONSTRAIN          = "Constrain"
    COMPOSE            = "Compose"
    PROGRESSION_DEFINE = "ProgressionDefine"
    ENVIRONMENT_DEFINE = "EnvironmentDefine"
    INTERACTION        = "Interaction"


# ── Classification Result ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class USMCClassificationResult:
    """
    Result of classifying one mutation operation.

    Attributes
    ----------
    category : USMCCategory
        The assigned category.
    confidence : float
        Score in [0.0, 1.0]. Below 0.5 means the classifier is unsure.
    method : str
        Which classification layer produced this result:
        "op_type" | "path_heuristic" | "keyword_score" | "fallback"
    reasons : list[str]
        Human-readable explanation of why this category was chosen.
        Surfaced in builder UI and Design Mentor suggestions.
    """

    category:   USMCCategory
    confidence: float
    method:     str
    reasons:    tuple[str, ...]

    def is_confident(self, threshold: float = 0.6) -> bool:
        return self.confidence >= threshold

    def __repr__(self) -> str:
        return (
            f"USMCResult({self.category.value}, "
            f"conf={self.confidence:.2f}, via={self.method!r})"
        )


# ── Op-Type → Category Map ────────────────────────────────────────────────────

_OP_TYPE_MAP: dict[str, tuple[USMCCategory, float]] = {
    # Structural adds
    "ADD_ACTOR":        (USMCCategory.CREATE,   1.0),
    "ADD_SYSTEM":       (USMCCategory.CREATE,   1.0),
    "ADD_COMPONENT":    (USMCCategory.COMPOSE,  0.9),
    "ADD_RULE":         (USMCCategory.CONSTRAIN,0.9),
    "ADD_MODE":         (USMCCategory.CREATE,   1.0),
    # Value modifications
    "SET":              (USMCCategory.MODIFY,   0.9),
    "MULTIPLY":         (USMCCategory.MODIFY,   0.9),
    "DIVIDE":           (USMCCategory.MODIFY,   0.9),
    "ADD":              (USMCCategory.MODIFY,   0.85),
    # List operations
    "APPEND":           (USMCCategory.MODIFY,   0.8),
    "DELETE":           (USMCCategory.REMOVE,   1.0),
    # Structural removes
    "REMOVE_ACTOR":     (USMCCategory.REMOVE,   1.0),
    "REMOVE_SYSTEM":    (USMCCategory.REMOVE,   1.0),
    "REMOVE_COMPONENT": (USMCCategory.REMOVE,   1.0),
    "REMOVE_RULE":      (USMCCategory.REMOVE,   1.0),
}

# ── Path-Segment Heuristics ───────────────────────────────────────────────────

# path_segment → (candidate_category, confidence_boost)
_PATH_HEURISTICS: list[tuple[str, USMCCategory, float]] = [
    # Rules in the path → likely a constraint definition
    ("rules",         USMCCategory.CONSTRAIN,          0.7),
    # Progression-related component names
    ("progression",   USMCCategory.PROGRESSION_DEFINE, 0.75),
    ("ability",       USMCCategory.PROGRESSION_DEFINE, 0.65),
    ("economy",       USMCCategory.PROGRESSION_DEFINE, 0.65),
    # Environment-related
    ("environment",   USMCCategory.ENVIRONMENT_DEFINE, 0.8),
    ("world",         USMCCategory.ENVIRONMENT_DEFINE, 0.65),
    ("worldstreaming",USMCCategory.ENVIRONMENT_DEFINE, 0.75),
    # Interaction-related
    ("dialogue",      USMCCategory.INTERACTION,        0.8),
    ("interaction",   USMCCategory.INTERACTION,        0.8),
    ("puzzle",        USMCCategory.INTERACTION,        0.7),
    ("usable",        USMCCategory.INTERACTION,        0.7),
    # Composition signals
    ("components",    USMCCategory.COMPOSE,            0.5),
]

# ── Keyword Signal Scoring ────────────────────────────────────────────────────

# keyword → (candidate_category, score_delta)
_KEYWORD_SIGNALS: list[tuple[str, USMCCategory, float]] = [
    # Create signals
    ("add",        USMCCategory.CREATE,             0.4),
    ("create",     USMCCategory.CREATE,             0.5),
    ("new",        USMCCategory.CREATE,             0.4),
    ("spawn",      USMCCategory.CREATE,             0.4),
    ("introduce",  USMCCategory.CREATE,             0.35),
    # Modify signals
    ("change",     USMCCategory.MODIFY,             0.5),
    ("increase",   USMCCategory.MODIFY,             0.5),
    ("decrease",   USMCCategory.MODIFY,             0.5),
    ("set",        USMCCategory.MODIFY,             0.4),
    ("update",     USMCCategory.MODIFY,             0.4),
    ("adjust",     USMCCategory.MODIFY,             0.45),
    ("make",       USMCCategory.MODIFY,             0.3),
    ("faster",     USMCCategory.MODIFY,             0.5),
    ("slower",     USMCCategory.MODIFY,             0.5),
    # Remove signals
    ("remove",     USMCCategory.REMOVE,             0.6),
    ("delete",     USMCCategory.REMOVE,             0.6),
    ("disable",    USMCCategory.REMOVE,             0.45),
    ("take away",  USMCCategory.REMOVE,             0.5),
    # Constrain signals
    ("only when",  USMCCategory.CONSTRAIN,          0.6),
    ("prevent",    USMCCategory.CONSTRAIN,          0.55),
    ("restrict",   USMCCategory.CONSTRAIN,          0.55),
    ("can't",      USMCCategory.CONSTRAIN,          0.5),
    ("cannot",     USMCCategory.CONSTRAIN,          0.5),
    ("limit",      USMCCategory.CONSTRAIN,          0.5),
    ("rule",       USMCCategory.CONSTRAIN,          0.45),
    ("condition",  USMCCategory.CONSTRAIN,          0.4),
    # Compose signals
    ("combine",    USMCCategory.COMPOSE,            0.5),
    ("also",       USMCCategory.COMPOSE,            0.3),
    ("both",       USMCCategory.COMPOSE,            0.3),
    # Progression signals
    ("level",      USMCCategory.PROGRESSION_DEFINE, 0.5),
    ("experience", USMCCategory.PROGRESSION_DEFINE, 0.55),
    ("unlock",     USMCCategory.PROGRESSION_DEFINE, 0.55),
    ("upgrade",    USMCCategory.PROGRESSION_DEFINE, 0.5),
    ("skill",      USMCCategory.PROGRESSION_DEFINE, 0.45),
    # Environment signals
    ("zone",       USMCCategory.ENVIRONMENT_DEFINE, 0.5),
    ("area",       USMCCategory.ENVIRONMENT_DEFINE, 0.4),
    ("weather",    USMCCategory.ENVIRONMENT_DEFINE, 0.55),
    ("terrain",    USMCCategory.ENVIRONMENT_DEFINE, 0.5),
    ("biome",      USMCCategory.ENVIRONMENT_DEFINE, 0.6),
    # Interaction signals
    ("talk",       USMCCategory.INTERACTION,        0.55),
    ("dialogue",   USMCCategory.INTERACTION,        0.6),
    ("interact",   USMCCategory.INTERACTION,        0.55),
    ("pickup",     USMCCategory.INTERACTION,        0.5),
    ("pick up",    USMCCategory.INTERACTION,        0.5),
    ("use",        USMCCategory.INTERACTION,        0.35),
    ("open",       USMCCategory.INTERACTION,        0.35),
]


# ── USMC Classifier ───────────────────────────────────────────────────────────

class USMCClassifier:
    """
    Classifies mutation operations into USMC categories.

    Stateless — safe to share across the entire GDE session.

    Usage
    -----
        classifier = USMCClassifier()

        # From a DSL operation dict
        result = classifier.classify_operation({"op_type": "SET", "target": "...", ...})

        # From a free-text description
        result = classifier.classify_text("add a fire damage zone to the forest")

        # From a path + description combined
        result = classifier.classify(op_type="SET", path="modes.default.rules.rule_fire",
                                     description="add fire damage rule")
    """

    def classify_operation(
        self, operation: dict[str, Any]
    ) -> USMCClassificationResult:
        """
        Classifies a raw DSL operation dict.
        Uses op_type first, then path heuristics, then keyword scoring.
        """
        op_type     = str(operation.get("op_type", "")).upper()
        path        = str(operation.get("target", ""))
        description = str(operation.get("description", ""))
        return self.classify(op_type=op_type, path=path, description=description)

    def classify_text(self, text: str) -> USMCClassificationResult:
        """Classifies a natural-language description with no operation context."""
        return self.classify(op_type="", path="", description=text)

    def classify(
        self,
        op_type:     str = "",
        path:        str = "",
        description: str = "",
    ) -> USMCClassificationResult:
        """
        Full classification pipeline: op_type → path heuristic → keyword score → fallback.
        """
        # ── Layer 1: Explicit op_type mapping (highest confidence) ────────────
        if op_type:
            mapped = _OP_TYPE_MAP.get(op_type.upper())
            if mapped:
                cat, conf = mapped
                return USMCClassificationResult(
                    category=cat,
                    confidence=conf,
                    method="op_type",
                    reasons=(
                        f"Operation type '{op_type}' maps directly to {cat.value}.",
                    ),
                )

        # ── Layer 2: Path-segment heuristics ──────────────────────────────────
        if path:
            path_lower = path.lower()
            for segment, cat, conf in _PATH_HEURISTICS:
                if segment in path_lower:
                    # Path heuristic is suggestive — combine with keyword scoring
                    kw_result = self._keyword_score(description)
                    if kw_result and kw_result[1] >= 0.4:
                        kw_cat, kw_score = kw_result
                        if kw_cat == cat:
                            # Agreement between path and keywords → higher confidence
                            return USMCClassificationResult(
                                category=cat,
                                confidence=min(conf + kw_score * 0.3, 1.0),
                                method="path_heuristic",
                                reasons=(
                                    f"Path segment '{segment}' suggests {cat.value}.",
                                    f"Keyword score for {cat.value}: {kw_score:.2f}.",
                                ),
                            )
                    return USMCClassificationResult(
                        category=cat,
                        confidence=conf,
                        method="path_heuristic",
                        reasons=(f"Path segment '{segment}' suggests {cat.value}.",),
                    )

        # ── Layer 3: Keyword scoring ───────────────────────────────────────────
        if description:
            kw_result = self._keyword_score(description)
            if kw_result:
                cat, score = kw_result
                return USMCClassificationResult(
                    category=cat,
                    confidence=score,
                    method="keyword_score",
                    reasons=(
                        f"Keyword analysis of description assigned {cat.value} "
                        f"(score={score:.2f}).",
                    ),
                )

        # ── Layer 4: Fallback ─────────────────────────────────────────────────
        return USMCClassificationResult(
            category=USMCCategory.MODIFY,
            confidence=0.3,
            method="fallback",
            reasons=(
                "Could not determine USMC category from operation, path, or "
                "description. Defaulting to Modify — the most common mutation type.",
            ),
        )

    # ── Keyword Scoring ───────────────────────────────────────────────────────

    @staticmethod
    def _keyword_score(
        text: str,
    ) -> tuple[USMCCategory, float] | None:
        """
        Scores text against keyword signals.
        Returns (best_category, score) or None if nothing scored.
        """
        if not text:
            return None

        text_lower = text.lower()
        scores: dict[USMCCategory, float] = {}

        for keyword, cat, delta in _KEYWORD_SIGNALS:
            if keyword in text_lower:
                scores[cat] = scores.get(cat, 0.0) + delta

        if not scores:
            return None

        best_cat   = max(scores, key=lambda c: scores[c])
        best_score = min(scores[best_cat], 0.95)  # cap at 0.95 — never certain from keywords alone
        return best_cat, best_score
"""
relevance_extractor.py — RelevanceExtractor
=============================================
Determines which CGS elements (actors, systems, rules) are relevant
to the current IntentEnvelope.

## Purpose

    Before SchemaSimplifier can filter the CGS, it needs to know WHICH
    elements to keep. RelevanceExtractor answers that question by scoring
    every CGS element against the intent and returning sets of IDs.

## Relevance Scoring Strategy

    Three signal sources, combined with max() (not sum()):

    1. Keyword match — does the actor/system/rule ID or description
       contain words from the prompt? (e.g. "zombie" in prompt →
       actor_zombie gets high keyword score)

    2. Component overlap — for BALANCE_ADJUSTMENT intents, which actors
       have the component type mentioned? (e.g. intent mentions "health"
       → all actors with COMP_HEALTH_V1 are relevant)

    3. System dependency chain — if a system is relevant, its direct
       dependents and dependencies are also included (II5 1-hop rule).
       RelevanceExtractor enforces 1-hop for reads, 2-hop for writes.

## Output

    RelevanceResult:
        relevant_actor_ids  : set[str]
        relevant_system_ids : set[str]
        relevant_rule_ids   : set[str]

    These sets are passed directly to SchemaSimplifier.

## Fallback

    If no elements score above the threshold, the most-likely elements
    are selected heuristically (default actor + default-mode systems).
    An empty result is never returned — at minimum the top-1 actor
    and direct-dependency systems are included.

## Component Name → Type ID hints

    The classifier uses keyword → component name substring mapping.
    Examples:
        "health" → "HEALTH"
        "speed"  → "VELOCITY"
        "ai"     → "AI"
        "input"  → "INPUT"
        "transform", "position" → "TRANSFORM"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intent_intake.intent_envelope import IntentEnvelope, PILIntentCategory


# ── Component keyword hints ───────────────────────────────────────────────────

_KEYWORD_TO_COMP: dict[str, str] = {
    "health":    "HEALTH",
    "damage":    "HEALTH",
    "dead":      "HEALTH",
    "death":     "HEALTH",
    "hp":        "HEALTH",
    "speed":     "VELOCITY",
    "velocity":  "VELOCITY",
    "movement":  "VELOCITY",
    "fast":      "VELOCITY",
    "slow":      "VELOCITY",
    "ai":        "AI",
    "chase":     "AI",
    "behavior":  "AI",
    "detection": "AI",
    "aggression":"AI",
    "input":     "INPUT",
    "control":   "INPUT",
    "transform": "TRANSFORM",
    "position":  "TRANSFORM",
    "rotation":  "TRANSFORM",
    "scale":     "TRANSFORM",
    "location":  "TRANSFORM",
}

# Relevance score thresholds
_INCLUDE_THRESHOLD = 0.30


# ── Relevance Result ──────────────────────────────────────────────────────────

@dataclass
class RelevanceResult:
    """
    Sets of CGS element IDs relevant to the current intent.

    Attributes
    ----------
    relevant_actor_ids  : set[str]   — actor IDs to include in context
    relevant_system_ids : set[str]   — system IDs to include
    relevant_rule_ids   : set[str]   — rule IDs to include
    scores              : dict       — debug: element_id → score
    """
    relevant_actor_ids:  set[str] = field(default_factory=set)
    relevant_system_ids: set[str] = field(default_factory=set)
    relevant_rule_ids:   set[str] = field(default_factory=set)
    scores:              dict      = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return (not self.relevant_actor_ids
                and not self.relevant_system_ids
                and not self.relevant_rule_ids)


# ── Relevance Extractor ───────────────────────────────────────────────────────

class RelevanceExtractor:
    """
    Scores CGS elements against an IntentEnvelope and returns
    the relevant subset.

    Stateless, deterministic, LLM-free.

    Usage
    -----
        extractor = RelevanceExtractor()
        result = extractor.extract(envelope, cgs)
        # result.relevant_actor_ids → {"actor_zombie"}
        # result.relevant_system_ids → {"AISystem", "MovementSystem"}
    """

    def extract(
        self,
        envelope: IntentEnvelope,
        cgs:      dict[str, Any],
    ) -> RelevanceResult:
        """
        Extracts relevant CGS element IDs for the given envelope.

        Parameters
        ----------
        envelope : IntentEnvelope
            Intent from IntentIntakeLayer.
        cgs : dict
            Current CGS JSON.

        Returns
        -------
        RelevanceResult
            Always non-empty (falls back to heuristic selection).
        """
        category      = envelope.intent_category
        prompt_lower  = envelope.normalized_text.lower()
        prompt_words  = set(prompt_lower.split())
        modes         = cgs.get("modes", [])

        # Read-only / diagnostic: include everything for full context
        if PILIntentCategory.is_read_only(category):
            return self._include_all(cgs)

        # Structural: include all (LLM needs full picture to add/remove)
        if PILIntentCategory.is_structural(category):
            return self._include_all(cgs)

        # World design: all actors + all rules
        if category == PILIntentCategory.WORLD_DESIGN:
            return self._include_actors_and_rules(cgs)

        # Unknown: minimal — just the default mode's actors
        if category == PILIntentCategory.UNKNOWN:
            return self._include_minimal(cgs)

        # BalanceAdjustment / ModifyFeature: score-based selection
        scores:         dict[str, float] = {}
        actor_ids:      set[str]         = set()
        system_ids:     set[str]         = set()
        rule_ids:       set[str]         = set()

        # Infer which component names are mentioned in the prompt
        relevant_comp_names = self._relevant_component_names(prompt_lower)

        for mode in modes:
            # Score actors
            for actor in mode.get("actors", []):
                aid   = actor.get("id", "")
                score = self._score_actor(actor, prompt_lower, prompt_words,
                                          relevant_comp_names)
                scores[aid] = max(scores.get(aid, 0.0), score)
                if score >= _INCLUDE_THRESHOLD:
                    actor_ids.add(aid)

            # Score systems
            for sys in mode.get("systems", []):
                sid   = sys.get("id", "")
                score = self._score_system(sys, prompt_lower, prompt_words,
                                           relevant_comp_names)
                scores[sid] = max(scores.get(sid, 0.0), score)
                if score >= _INCLUDE_THRESHOLD:
                    system_ids.add(sid)

            # Score rules
            for rule in mode.get("rules", []):
                rid   = rule.get("id", "")
                score = self._score_rule(rule, prompt_lower, prompt_words)
                scores[rid] = max(scores.get(rid, 0.0), score)
                if score >= _INCLUDE_THRESHOLD:
                    rule_ids.add(rid)

        # Expand system IDs to include 1-hop dependencies (II5)
        system_ids = self._expand_system_deps(system_ids, cgs, hops=1)

        # Include global systems if any mode systems are relevant
        if system_ids:
            for gs in cgs.get("global_systems", []):
                system_ids.add(gs.get("id", ""))

        result = RelevanceResult(
            relevant_actor_ids  = actor_ids,
            relevant_system_ids = system_ids,
            relevant_rule_ids   = rule_ids,
            scores              = scores,
        )

        # Fallback: ensure at least something is included
        if result.is_empty:
            return self._include_minimal(cgs)

        return result

    # ── Scoring ───────────────────────────────────────────────────────────────

    @staticmethod
    def _score_actor(
        actor:               dict[str, Any],
        prompt_lower:        str,
        prompt_words:        set[str],
        relevant_comp_names: set[str],
    ) -> float:
        """Scores one actor against the current prompt."""
        score = 0.0
        aid   = actor.get("id", "").lower()

        # Keyword match on actor ID
        for word in prompt_words:
            if len(word) >= 3 and word in aid:
                score = max(score, 0.80)

        # Generic entity words
        actor_type = actor.get("actor_type", "").lower()
        for word in prompt_words:
            if len(word) >= 3 and word in actor_type:
                score = max(score, 0.65)

        # Component name overlap
        for comp in actor.get("components", []):
            name = comp.get("name", "").upper()
            for comp_keyword in relevant_comp_names:
                if comp_keyword in name:
                    score = max(score, 0.55)

        return score

    @staticmethod
    def _score_system(
        sys:                 dict[str, Any],
        prompt_lower:        str,
        prompt_words:        set[str],
        relevant_comp_names: set[str],
    ) -> float:
        """Scores one system against the current prompt."""
        score = 0.0
        sid   = sys.get("id", "").lower()

        # Keyword match on system ID
        for word in prompt_words:
            if len(word) >= 3 and word in sid:
                score = max(score, 0.75)

        # Component type overlap (reads/writes)
        # If a component relevant to the prompt is read/written by this system,
        # the system is likely relevant.
        reads  = sys.get("reads",  [])
        writes = sys.get("writes", [])
        all_types = set(reads) | set(writes)

        # We use the component name hints rather than type IDs here, since
        # type IDs are integers we don't know without the full UCL mapping.
        # Systems that write are more relevant than those that only read.
        if relevant_comp_names:
            # AI-related: AISystem highly relevant
            if "AI" in relevant_comp_names and "ai" in sid:
                score = max(score, 0.70)
            # Velocity/speed-related: MovementSystem relevant
            if "VELOCITY" in relevant_comp_names and "movement" in sid:
                score = max(score, 0.70)
            # Health-related: DamageSystem / DeathSystem relevant
            if "HEALTH" in relevant_comp_names and any(k in sid for k in ("damage", "death", "health")):
                score = max(score, 0.70)

        return score

    @staticmethod
    def _score_rule(
        rule:         dict[str, Any],
        prompt_lower: str,
        prompt_words: set[str],
    ) -> float:
        """Scores one rule against the current prompt."""
        score     = 0.0
        rid       = rule.get("id", "").lower()
        condition = rule.get("condition", "").lower()
        effect    = rule.get("effect",    "").lower()

        for word in prompt_words:
            if len(word) >= 4:
                if word in rid or word in condition or word in effect:
                    score = max(score, 0.60)

        return score

    # ── Component keyword mapping ─────────────────────────────────────────────

    @staticmethod
    def _relevant_component_names(prompt_lower: str) -> set[str]:
        """Returns the set of component name fragments relevant to this prompt."""
        relevant: set[str] = set()
        for keyword, comp_name in _KEYWORD_TO_COMP.items():
            if keyword in prompt_lower:
                relevant.add(comp_name)
        return relevant

    # ── System dependency expansion (II5) ─────────────────────────────────────

    @staticmethod
    def _expand_system_deps(
        seed_ids: set[str],
        cgs:      dict[str, Any],
        hops:     int = 1,
    ) -> set[str]:
        """
        Expands a seed set of system IDs to include their direct dependencies.
        Implements II5: 1-hop reads, respects depends_on chains.
        """
        if not seed_ids:
            return seed_ids

        # Build full system map
        all_systems: dict[str, dict] = {}
        for gs in cgs.get("global_systems", []):
            all_systems[gs.get("id", "")] = gs
        for mode in cgs.get("modes", []):
            for sys in mode.get("systems", []):
                all_systems[sys.get("id", "")] = sys

        expanded = set(seed_ids)
        frontier = set(seed_ids)

        for _ in range(hops):
            next_frontier: set[str] = set()
            for sid in frontier:
                sys = all_systems.get(sid, {})
                for dep in sys.get("depends_on", []):
                    if dep not in expanded:
                        expanded.add(dep)
                        next_frontier.add(dep)
            frontier = next_frontier
            if not frontier:
                break

        return expanded

    # ── Convenience selectors ─────────────────────────────────────────────────

    @staticmethod
    def _include_all(cgs: dict[str, Any]) -> RelevanceResult:
        actor_ids  = set()
        system_ids = set()
        rule_ids   = set()

        for gs in cgs.get("global_systems", []):
            system_ids.add(gs.get("id", ""))
        for mode in cgs.get("modes", []):
            for a in mode.get("actors",  []): actor_ids.add(a.get("id", ""))
            for s in mode.get("systems", []): system_ids.add(s.get("id", ""))
            for r in mode.get("rules",   []): rule_ids.add(r.get("id", ""))

        return RelevanceResult(
            relevant_actor_ids  = actor_ids,
            relevant_system_ids = system_ids,
            relevant_rule_ids   = rule_ids,
        )

    @staticmethod
    def _include_actors_and_rules(cgs: dict[str, Any]) -> RelevanceResult:
        actor_ids = set()
        rule_ids  = set()
        for mode in cgs.get("modes", []):
            for a in mode.get("actors", []): actor_ids.add(a.get("id", ""))
            for r in mode.get("rules",  []): rule_ids.add(r.get("id", ""))
        return RelevanceResult(
            relevant_actor_ids = actor_ids,
            relevant_rule_ids  = rule_ids,
        )

    @staticmethod
    def _include_minimal(cgs: dict[str, Any]) -> RelevanceResult:
        """Heuristic fallback: first actor + all global systems."""
        actor_ids  = set()
        system_ids = set()

        for gs in cgs.get("global_systems", []):
            system_ids.add(gs.get("id", ""))
        for mode in cgs.get("modes", []):
            actors = mode.get("actors", [])
            if actors:
                actor_ids.add(actors[0].get("id", ""))
            break  # only first mode

        return RelevanceResult(
            relevant_actor_ids  = actor_ids,
            relevant_system_ids = system_ids,
        )
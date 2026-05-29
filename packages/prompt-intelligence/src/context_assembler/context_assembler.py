"""
context_assembler.py — ContextAssembler
==========================================
Orchestrates all Phase 13.2 submodules to produce one LLMContextPacket.

This is the single entry point for context assembly. It receives an
IntentEnvelope + current CGS and returns a fully assembled
LLMContextPacket ready for the 5-pass LLM pipeline.

## Pipeline

    IntentEnvelope + CGS
        ↓
    ScopeBuilder.build()
        → AllowedMutationScope
        ↓
    ConstraintAggregator.aggregate()
        → ConstraintSet (cached prefix content)
        ↓
    RelevanceExtractor.extract()
        → RelevanceResult (which elements to include)
        ↓
    DependencyExpander.expand()
        → ExpansionResult (system deps expanded per II5)
        ↓
    SchemaSimplifier.simplify()
        → simplified_schema dict
        ↓
    Token count estimation
        ↓
    Budget enforcement (raises ContextBudgetExceeded if > 8K dynamic)
        ↓
    LLMContextPacket (assembled here)

## Budget Enforcement (II4)

    dynamic_token_count is estimated across:
        - game_metadata
        - relevant_actors, relevant_systems, relevant_rules (simplified)
        - simplified_schema
        - allowed_scope

    If dynamic_token_count > 8192:
        1. First attempt: trim relevance to only the highest-scoring elements
        2. Second attempt: reduce to minimal (fallback actors + global systems)
        3. If still over: raise ContextBudgetExceeded
            (inference_adapter catches this and routes to a smaller tier)

    static_token_count (constraints) is NOT counted against the 8K cap.

## SimplifiedActor Construction

    ContextAssembler converts raw CGS actor dicts to SimplifiedActor
    frozen dataclasses that LLMContextPacket holds. Same for
    SimplifiedSystem and SimplifiedRule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from intent_envelope import IntentEnvelope, PILIntentCategory
from llm_context_packet import (
    LLMContextPacket, AllowedMutationScope,
    SimplifiedActor, SimplifiedSystem, SimplifiedRule,
)
from scope_builder import ScopeBuilder
from constraint_aggregator import ConstraintAggregator, ConstraintSet
from relevance_extractor import RelevanceExtractor, RelevanceResult
from dependency_expander import DependencyExpander, ExpansionResult
from schema_simplifier import SchemaSimplifier


# ── Budget limit ──────────────────────────────────────────────────────────────

DYNAMIC_TOKEN_HARD_CAP = 8_192   # II4


# ── Budget Exceeded ───────────────────────────────────────────────────────────

class ContextBudgetExceeded(Exception):
    """
    Raised when dynamic token count cannot be reduced below 8K (II4).
    Caught by InferenceAdapter, which may route to a lower-tier model.
    """
    def __init__(self, token_count: int) -> None:
        super().__init__(
            f"Dynamic context budget exceeded: {token_count} tokens > "
            f"{DYNAMIC_TOKEN_HARD_CAP} cap (II4). "
            f"Reduce scope or split into multiple calls."
        )
        self.token_count = token_count


# ── Context Assembler ─────────────────────────────────────────────────────────

class ContextAssembler:
    """
    Orchestrates context assembly for one PIL call.

    One instance may be shared across sessions (all submodules are stateless).
    The assembled LLMContextPacket is always immutable (frozen dataclass).

    Usage
    -----
        assembler = ContextAssembler()
        packet = assembler.assemble(envelope, cgs, session_id="s1")
        # packet.relevant_actors → (SimplifiedActor(...), ...)
        # packet.dynamic_token_count → 340
        # packet.constraints → ("Entity IDs are u64...", ...)
    """

    def __init__(self) -> None:
        self._scope_builder    = ScopeBuilder()
        self._constraint_agg   = ConstraintAggregator()
        self._relevance_ext    = RelevanceExtractor()
        self._dep_expander     = DependencyExpander()
        self._simplifier       = SchemaSimplifier()

    def assemble(
        self,
        envelope:   IntentEnvelope,
        cgs:        dict[str, Any],
        session_id: str | None = None,
    ) -> LLMContextPacket:
        """
        Assembles a complete LLMContextPacket.

        Parameters
        ----------
        envelope : IntentEnvelope
            Output of IntentIntakeLayer.
        cgs : dict
            Current CGS JSON.
        session_id : str | None
            For provenance.

        Returns
        -------
        LLMContextPacket
            Immutable context packet for the 5-pass pipeline.

        Raises
        ------
        ContextBudgetExceeded
            When dynamic token count cannot be kept under 8K (II4).
        """
        # ── Step 1: Scope ─────────────────────────────────────────────────────
        scope = self._scope_builder.build(envelope, cgs)

        # ── Step 2: Constraints (cached prefix — static) ──────────────────────
        constraints = self._constraint_agg.aggregate(cgs)

        # ── Step 3: Relevance selection ───────────────────────────────────────
        relevance = self._relevance_ext.extract(envelope, cgs)

        # ── Step 4: Dependency expansion (II5) ────────────────────────────────
        expanded = self._dep_expander.expand(relevance, cgs)

        # ── Step 5: Schema simplification ─────────────────────────────────────
        include_all = envelope.assistance_mode == "ARCHITECT_MODE"
        simplified_schema = self._simplifier.simplify(
            cgs,
            relevant_actor_ids  = expanded.actor_ids  if not include_all else None,
            relevant_system_ids = expanded.system_ids if not include_all else None,
            relevant_rule_ids   = expanded.rule_ids   if not include_all else None,
            include_all         = include_all,
        )

        # ── Step 6: Build typed dataclass collections ─────────────────────────
        rel_actors  = self._build_actors(simplified_schema,  expanded.actor_ids,  include_all)
        rel_systems = self._build_systems(simplified_schema, expanded.system_ids, include_all)
        rel_rules   = self._build_rules(simplified_schema,   expanded.rule_ids,   include_all)

        # ── Step 7: Game metadata (compact) ───────────────────────────────────
        game_metadata = self._extract_metadata(cgs)

        # ── Step 8: Token counting ────────────────────────────────────────────
        dynamic_tokens = self._estimate_dynamic_tokens(
            game_metadata, rel_actors, rel_systems, rel_rules,
            scope, simplified_schema,
        )
        static_tokens = constraints.estimated_tokens

        # ── Step 9: Budget enforcement (II4) ──────────────────────────────────
        if dynamic_tokens > DYNAMIC_TOKEN_HARD_CAP:
            # Attempt 1: trim to only directly-named actors
            dynamic_tokens, rel_actors, rel_systems, rel_rules, simplified_schema = \
                self._trim_to_budget(
                    envelope, cgs, constraints, scope,
                    game_metadata, expanded,
                )
            if dynamic_tokens > DYNAMIC_TOKEN_HARD_CAP:
                raise ContextBudgetExceeded(dynamic_tokens)

        # ── Step 10: Assemble packet ──────────────────────────────────────────
        return LLMContextPacket(
            intent_category      = envelope.intent_category,
            normalized_prompt    = envelope.normalized_text,
            assistance_mode      = envelope.assistance_mode,
            game_metadata        = game_metadata,
            relevant_actors      = rel_actors,
            relevant_systems     = rel_systems,
            relevant_rules       = rel_rules,
            constraints          = constraints.all_constraints,
            allowed_scope        = scope,
            simplified_schema    = simplified_schema,
            dynamic_token_count  = dynamic_tokens,
            static_token_count   = static_tokens,
            session_id           = session_id,
        )

    # ── Builders ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_actors(
        slim_schema: dict[str, Any],
        actor_ids:   set[str],
        include_all: bool,
    ) -> tuple[SimplifiedActor, ...]:
        actors: list[SimplifiedActor] = []
        for mode in slim_schema.get("modes", []):
            mid = mode.get("id")
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                if not include_all and aid not in actor_ids:
                    continue
                components = tuple(
                    {"type_id": c.get("type_id"), "name": c.get("name", ""),
                     "defaults": c.get("defaults", {})}
                    for c in actor.get("components", [])
                )
                actors.append(SimplifiedActor(
                    actor_id     = aid,
                    actor_type   = actor.get("actor_type", ""),
                    control_type = actor.get("control_type", ""),
                    components   = components,
                    mode_id      = mid,
                ))
        return tuple(actors)

    @staticmethod
    def _build_systems(
        slim_schema: dict[str, Any],
        system_ids:  set[str],
        include_all: bool,
    ) -> tuple[SimplifiedSystem, ...]:
        systems: list[SimplifiedSystem] = []

        def _add(sys_list: list[dict], mid: str | None) -> None:
            for sys in sys_list:
                sid = sys.get("id", "")
                if not include_all and sid not in system_ids:
                    continue
                systems.append(SimplifiedSystem(
                    system_id     = sid,
                    phase         = sys.get("phase", ""),
                    reads         = tuple(sys.get("reads",  [])),
                    writes        = tuple(sys.get("writes", [])),
                    depends_on    = tuple(sys.get("depends_on", [])),
                    deterministic = sys.get("deterministic", True),
                    mode_id       = mid,
                ))

        _add(slim_schema.get("global_systems", []), None)
        for mode in slim_schema.get("modes", []):
            _add(mode.get("systems", []), mode.get("id"))

        return tuple(systems)

    @staticmethod
    def _build_rules(
        slim_schema: dict[str, Any],
        rule_ids:    set[str],
        include_all: bool,
    ) -> tuple[SimplifiedRule, ...]:
        rules: list[SimplifiedRule] = []
        for mode in slim_schema.get("modes", []):
            mid = mode.get("id")
            for rule in mode.get("rules", []):
                rid = rule.get("id", "")
                if not include_all and rid not in rule_ids:
                    continue
                rules.append(SimplifiedRule(
                    rule_id   = rid,
                    condition = rule.get("condition", ""),
                    effect    = rule.get("effect", ""),
                    priority  = rule.get("priority", 0),
                    is_active = rule.get("is_active", True),
                    mode_id   = mid,
                ))
        return tuple(rules)

    @staticmethod
    def _extract_metadata(cgs: dict[str, Any]) -> dict:
        meta = cgs.get("metadata", {})
        return {
            "name":           meta.get("name", ""),
            "version":        meta.get("version", ""),
            "schema_version": meta.get("schema_version", ""),
        }

    @staticmethod
    def _estimate_dynamic_tokens(
        game_metadata:  dict,
        rel_actors:     tuple,
        rel_systems:    tuple,
        rel_rules:      tuple,
        scope:          AllowedMutationScope,
        simplified_schema: dict,
    ) -> int:
        """Character-based token estimate for all dynamic content."""
        text = (
            json.dumps(game_metadata)
            + json.dumps([a.to_dict() for a in rel_actors])
            + json.dumps([s.to_dict() for s in rel_systems])
            + json.dumps([r.to_dict() for r in rel_rules])
            + json.dumps(scope.to_dict() if scope else {})
            + json.dumps(simplified_schema)
        )
        return max(1, len(text) // 4)

    def _trim_to_budget(
        self,
        envelope:     IntentEnvelope,
        cgs:          dict[str, Any],
        constraints:  ConstraintSet,
        scope:        AllowedMutationScope,
        game_metadata: dict,
        expanded:     ExpansionResult,
    ) -> tuple[int, tuple, tuple, tuple, dict]:
        """
        Trims context to fit within the 8K dynamic token cap.
        Returns (token_count, actors, systems, rules, simplified_schema).
        """
        # Minimal: just global systems + first relevant actor
        min_actor_ids  = set(list(expanded.actor_ids)[:1])
        min_system_ids = {gs.get("id", "")
                          for gs in cgs.get("global_systems", [])}

        slim = self._simplifier.simplify(
            cgs,
            relevant_actor_ids  = min_actor_ids,
            relevant_system_ids = min_system_ids,
            relevant_rule_ids   = set(),
        )
        actors  = self._build_actors(slim,  min_actor_ids,  False)
        systems = self._build_systems(slim, min_system_ids, False)
        rules:  tuple = ()

        tokens = self._estimate_dynamic_tokens(
            game_metadata, actors, systems, rules, scope, slim
        )
        return tokens, actors, systems, rules, slim
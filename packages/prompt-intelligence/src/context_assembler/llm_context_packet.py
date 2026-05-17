"""
llm_context_packet.py — LLMContextPacket + supporting types
==============================================================
The assembled context packet that ContextAssembler produces and the
5-pass LLM Orchestrator consumes.

## Role in the Pipeline

    IntentEnvelope
        → ContextAssembler (orchestrates all 13.2 submodules)
        → LLMContextPacket  ← this file
        → LLMOrchestrator (5-pass pipeline, all passes read from ONE packet)

## Token Budget Split

    LLMContextPacket carries TWO token counts:

        static_token_count   — content destined for the CACHED PREFIX
                               (constraints, stable memory layers per II9)
                               This is sent once and reused across calls
                               with the same CGS hash + mode.

        dynamic_token_count  — content in the per-prompt body
                               Context Budgeter enforces this ≤ 8K (II4).
                               Exceeding this raises ContextBudgetExceeded.

    The static content is never counted against the 8K dynamic cap.
    constraint_aggregator.py places its output in static; everything
    from relevance_extractor and schema_simplifier goes into dynamic.

## What Goes Where

    Cached prefix (static):
        - constraints (D-rules, R/W contracts, phase rules)
        - stable memory layers (Design, Structural, Behavioral — Phase 13.10)

    Per-prompt body (dynamic):
        - game_metadata (name, hash, version)
        - relevant_actors, relevant_systems, relevant_rules
        - simplified_schema
        - allowed_scope
        - session_memory, safety_memory (Phase 13.10)

## Immutability

    LLMContextPacket is frozen after assembly. The 5 passes read from it
    but never mutate it. Pass state is managed by LLMOrchestrator.

## Full Schema Transmission Prohibition

    FULL CGS TRANSMISSION IS FORBIDDEN. The packet must contain only
    the CGS slice relevant to the current intent (per Audit 9).
    schema_simplifier enforces the 60% size reduction target.
    ContextAssembler enforces the 8K dynamic token hard cap via
    context_budgeter.py from packages/inference/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Simplified Actor ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SimplifiedActor:
    """
    Compact representation of one actor for LLM context.

    Contains only the components relevant to the current intent.
    Full component defaults are further simplified by schema_simplifier.
    """
    actor_id:    str
    actor_type:  str
    control_type: str
    components:  tuple[dict, ...]    # simplified component dicts
    mode_id:     str | None = None

    def to_dict(self) -> dict:
        return {
            "actor_id":    self.actor_id,
            "actor_type":  self.actor_type,
            "control_type": self.control_type,
            "components":  list(self.components),
            "mode_id":     self.mode_id,
        }


# ── Simplified System ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SimplifiedSystem:
    """Compact representation of one system for LLM context."""
    system_id:    str
    phase:        str
    reads:        tuple[int, ...]
    writes:       tuple[int, ...]
    depends_on:   tuple[str, ...]
    deterministic: bool
    mode_id:      str | None = None

    def to_dict(self) -> dict:
        return {
            "system_id":    self.system_id,
            "phase":        self.phase,
            "reads":        list(self.reads),
            "writes":       list(self.writes),
            "depends_on":   list(self.depends_on),
            "deterministic": self.deterministic,
            "mode_id":      self.mode_id,
        }


# ── Simplified Rule ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SimplifiedRule:
    """Compact representation of one rule for LLM context."""
    rule_id:   str
    condition: str
    effect:    str
    priority:  int
    is_active: bool
    mode_id:   str | None = None

    def to_dict(self) -> dict:
        return {
            "rule_id":   self.rule_id,
            "condition": self.condition,
            "effect":    self.effect,
            "priority":  self.priority,
            "is_active": self.is_active,
            "mode_id":   self.mode_id,
        }


# ── Allowed Mutation Scope (imported from scope_builder, redefined here for clarity) ──
# scope_builder.py imports from this module to avoid circular deps.

@dataclass(frozen=True)
class AllowedMutationScope:
    """
    Defines which CGS paths are permitted for the current intent + mode.

    Built by ScopeBuilder. Consumed by LLMOrchestrator and SafetyScopeGuard.

    Attributes
    ----------
    allowed_paths : tuple[str, ...]
        CGS paths the LLM may propose mutations for.
        Empty tuple = no path restriction (mode is ARCHITECT_MODE).
    forbidden_paths : tuple[str, ...]
        CGS paths that must never be mutated in any mode.
        Always includes: metadata.cgs_hash, metadata.schema_version,
        entity_id internals, UCL frozen fields.
    structural_change_allowed : bool
        Whether this intent+mode combination permits adding/removing
        schema nodes (actors, systems, rules).
    max_mutation_depth : int
        How many nested levels into a component's defaults may be mutated.
        Default 3. ARCHITECT_MODE allows deeper paths.
    mode : str
        The assistance mode in effect when this scope was built.
    """
    allowed_paths:            tuple[str, ...]
    forbidden_paths:          tuple[str, ...]
    structural_change_allowed: bool
    max_mutation_depth:       int
    mode:                     str

    @property
    def is_unrestricted(self) -> bool:
        """True when no path allow-list is in effect (ARCHITECT_MODE)."""
        return len(self.allowed_paths) == 0

    def path_is_allowed(self, path: str) -> bool:
        """Returns True if path is permitted for mutation."""
        if path in self.forbidden_paths:
            return False
        if self.is_unrestricted:
            return True
        return any(path.startswith(a) for a in self.allowed_paths)

    def path_is_forbidden(self, path: str) -> bool:
        return any(path.startswith(f) for f in self.forbidden_paths)

    def to_dict(self) -> dict:
        return {
            "allowed_paths":             list(self.allowed_paths),
            "forbidden_paths":           list(self.forbidden_paths),
            "structural_change_allowed": self.structural_change_allowed,
            "max_mutation_depth":        self.max_mutation_depth,
            "mode":                      self.mode,
            "is_unrestricted":           self.is_unrestricted,
        }


# ── LLM Context Packet ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LLMContextPacket:
    """
    Assembled context handed from ContextAssembler to LLMOrchestrator.

    The 5-pass pipeline reads from exactly ONE packet per prompt.
    All passes share this packet — it is never re-assembled mid-pipeline.

    Attributes
    ----------
    intent_category : str
        PIL intent category from IntentEnvelope. Tells the 5-pass pipeline
        which template family to use.
    normalized_prompt : str
        The normalized prompt text from PromptNormalizer.
    assistance_mode : str
        Mode at context assembly time.

    game_metadata : dict
        Compact game info: name, cgs_hash, version, schema_version.
        Always in per-prompt body (changes with each CGS commit).

    relevant_actors : tuple[SimplifiedActor, ...]
        Only actors relevant to this intent.
    relevant_systems : tuple[SimplifiedSystem, ...]
        Only systems relevant to this intent.
    relevant_rules : tuple[SimplifiedRule, ...]
        Only rules relevant to this intent.

    constraints : tuple[str, ...]
        Architectural constraints from constraint_aggregator.
        These go in the CACHED PREFIX — not counted in dynamic_token_count.

    allowed_scope : AllowedMutationScope
        Which CGS paths are allowed for this call.

    simplified_schema : dict
        Compact CGS slice from schema_simplifier.
        Contains only elements relevant to the intent.

    dynamic_token_count : int
        Estimated tokens for per-prompt content.
        context_budgeter enforces this ≤ 8192 (II4).

    static_token_count : int
        Estimated tokens for cached prefix content (constraints).
        Not counted against the 8K dynamic cap.

    session_id : str | None
        For provenance and telemetry.
    """

    # Routing and prompt
    intent_category:   str
    normalized_prompt: str
    assistance_mode:   str

    # Game identity (per-prompt)
    game_metadata:     dict

    # Relevant CGS elements (per-prompt)
    relevant_actors:   tuple[SimplifiedActor, ...]   = field(default_factory=tuple)
    relevant_systems:  tuple[SimplifiedSystem, ...]  = field(default_factory=tuple)
    relevant_rules:    tuple[SimplifiedRule, ...]     = field(default_factory=tuple)

    # Architectural constraints (cached prefix — static)
    constraints:       tuple[str, ...]               = field(default_factory=tuple)

    # Mutation scope and simplified view
    allowed_scope:     AllowedMutationScope | None   = None
    simplified_schema: dict                          = field(default_factory=dict)

    # Token accounting
    dynamic_token_count: int  = 0
    static_token_count:  int  = 0

    # Provenance
    session_id:         str | None = None

    # ── Convenience Properties ────────────────────────────────────────────────

    @property
    def total_token_count(self) -> int:
        return self.dynamic_token_count + self.static_token_count

    @property
    def actor_count(self) -> int:
        return len(self.relevant_actors)

    @property
    def system_count(self) -> int:
        return len(self.relevant_systems)

    @property
    def rule_count(self) -> int:
        return len(self.relevant_rules)

    @property
    def constraint_count(self) -> int:
        return len(self.constraints)

    @property
    def is_within_budget(self) -> bool:
        """True if dynamic token count is within the 8K hard cap (II4)."""
        return self.dynamic_token_count <= 8_192

    @property
    def is_read_only_intent(self) -> bool:
        """True for QueryExplain / DebugIssue — no mutation expected."""
        return self.intent_category in {"QueryExplain", "DebugIssue"}

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """JSON-serializable representation for telemetry and debugging."""
        return {
            "intent_category":    self.intent_category,
            "normalized_prompt":  self.normalized_prompt[:200],
            "assistance_mode":    self.assistance_mode,
            "game_metadata":      self.game_metadata,
            "actor_count":        self.actor_count,
            "system_count":       self.system_count,
            "rule_count":         self.rule_count,
            "constraint_count":   self.constraint_count,
            "dynamic_token_count": self.dynamic_token_count,
            "static_token_count":  self.static_token_count,
            "total_token_count":   self.total_token_count,
            "is_within_budget":   self.is_within_budget,
            "session_id":         self.session_id,
        }

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"LLMContextPacket({self.intent_category!r}, "
            f"{self.actor_count}actors/{self.system_count}sys/{self.rule_count}rules, "
            f"dyn={self.dynamic_token_count}tok, static={self.static_token_count}tok)"
        )

    def __repr__(self) -> str:
        return self.summary()
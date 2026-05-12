"""
prompt_template_registry.py — PromptTemplateRegistry
======================================================
Named, versioned prompt templates for all PIL passes and utility calls.

## Why a Template Registry?
Without this, prompt strings live scattered across 13 PIL submodules —
embedded as string literals in pass1_planning.py, pass2_dsl_draft.py, etc.
Problems with that approach:
    - A/B testing prompts requires editing source files
    - Model-specific prompt tuning requires branching the code
    - Prompt versioning is invisible (what changed, when, why?)
    - Reviewing prompt quality requires reading Python code

With the registry:
    - All prompts live in one place with names and versions
    - PIL submodules call get("pass1_planning") — never embed strings
    - Model-specific overrides exist without touching PIL logic
    - Version history is explicit (v1 → v2 → v3 per template)
    - Testing prompts against new models is a config change

## Template Types
    SYSTEM  — system-level instruction (usually cacheable prefix)
    USER    — per-call user message body (dynamic, not cached)
    PREFIX  — static text prepended to dynamic content (cacheable)
    SUFFIX  — appended after dynamic content

## Model-Specific Overrides
A template can have a base version plus model-specific overrides:
    registry.set_override(
        name     = "pass3_self_critique",
        model_id = "claude-haiku-4-5-20251001",
        template = "..more concise critique prompt for Haiku..",
    )

## Variable Substitution
Templates support {variable} placeholders filled at render time:
    template = "Critique this mutation:\n{mutation_json}\n\nCurrent CGS:\n{cgs_summary}"
    rendered = registry.render("pass3_self_critique", mutation_json=..., cgs_summary=...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Template Type ─────────────────────────────────────────────────────────────

class TemplateType:
    SYSTEM = "system"
    USER   = "user"
    PREFIX = "prefix"
    SUFFIX = "suffix"


# ── Template Record ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PromptTemplate:
    """
    One named, versioned prompt template.

    Attributes
    ----------
    name : str
        Unique template identifier. Example: "pass1_planning"
    version : str
        Semantic version string. Example: "1.0.0"
    template_type : str
        TemplateType constant.
    text : str
        The template text with optional {variable} placeholders.
    description : str
        What this template is for and when to use it.
    cacheable : bool
        True if this section should be marked cacheable in PromptCache.
        System prompts and static prefixes are cacheable.
        Per-call dynamic content is not.
    """

    name:          str
    version:       str
    template_type: str
    text:          str
    description:   str  = ""
    cacheable:     bool = False

    def render(self, **variables: Any) -> str:
        """Substitutes {variable} placeholders with provided values."""
        try:
            return self.text.format(**variables)
        except KeyError as exc:
            raise TemplateRenderError(
                f"Template '{self.name}' v{self.version} missing variable: {exc}. "
                f"Available variables: {sorted(variables.keys())}"
            ) from exc

    def __repr__(self) -> str:
        return f"PromptTemplate({self.name!r} v{self.version}, {self.template_type})"


class TemplateRenderError(Exception):
    """Raised when a template variable is missing during render."""


# ── Built-in Templates ────────────────────────────────────────────────────────

_BUILTIN_TEMPLATES: list[PromptTemplate] = [

    # ── Architectural Constraint Prefix (CACHED) ───────────────────────────
    PromptTemplate(
        name          = "architectural_constraints",
        version       = "1.0.0",
        template_type = TemplateType.PREFIX,
        cacheable     = True,
        description   = "Static XACE architectural rules injected by constraint_aggregator. "
                        "Cached — never changes for a given schema version.",
        text          = """\
# XACE ARCHITECTURAL CONSTRAINTS (READ BEFORE RESPONDING)

## Determinism Rules (D1-D15)
D1  System order = ExecutionPlan only. Never self-schedule.
D2  EntityID never reused. Destroyed = archived.
D3  Entity iteration sorted by EntityID ASC.
D4  Mutations only after phase completion, via Mutation Gate.
D5  Events sorted by (creation_tick, creation_phase, event_id).
D6  DeterministicRNG only. seed=hash(world_seed,system_id,tick). No OS/language RNG.
D7  Fixed timestep only. delta_time=1/simulation_rate.
D8  Consistent float precision. No frame-dependent accumulation.
D9  world_hash computed after each tick. Replay hashes must match.
D10 runtime.schema_version == execution_plan.schema_version always.
D11 Stable key ordering in serialisation. Fixed decimal precision.
D12 External input applied at tick boundaries only.
D13 Adapters never modify authoritative simulation state.
D14 Replay = initial snapshot + deterministic input stream + identical schema version.
D15 Determinism Guard hooks at every execution boundary.

## Global Invariants (I1-I15)
I2  ALL structural changes through Mutation Gate. Direct mutation FORBIDDEN.
I3  CGS is single source of truth. No runtime system modifies schema directly.
I6  No module may introduce nondeterministic behaviour.
I8  Schema mutations applied atomically. Partial commits FORBIDDEN.
I9  Events never modify state directly. All mutation through Mutation Gate.
I12 UNRESOLVED asset references never enter committed CGS.

## DSL Path Rules
- All paths must start with a known root: metadata, global_systems, or modes.
- Paths are always fully qualified. No implicit or partial paths.
- Target leaf must exist (for SET/ADD/MULTIPLY/DIVIDE/DELETE operations).
- Structural operations (ADD_ACTOR, ADD_RULE, etc.) target container lists.

## Operation Types
Value mutations: SET, ADD, REMOVE, MULTIPLY, DIVIDE, APPEND, DELETE
Structural adds: ADD_ACTOR, ADD_SYSTEM, ADD_RULE, ADD_COMPONENT, ADD_MODE
Structural removes: REMOVE_ACTOR, REMOVE_SYSTEM, REMOVE_RULE, REMOVE_COMPONENT, REMOVE_MODE
""",
    ),

    # ── Pass 1: Planning ───────────────────────────────────────────────────
    PromptTemplate(
        name          = "pass1_planning",
        version       = "1.0.0",
        template_type = TemplateType.USER,
        cacheable     = False,
        description   = "PASS 1: structured planning. Produces ReasoningPlan. No DSL yet.",
        text          = """\
## TASK: PASS 1 — STRUCTURED PLANNING

Analyse the following designer intent and produce a structured reasoning plan.
Do NOT generate any DSL operations yet. Plan only.

### Designer Intent
{intent_description}

### Current CGS Context
{cgs_context}

### Allowed Mutation Scope
{allowed_scope}

Produce a ReasoningPlan as JSON with this exact schema:
{{
    "target_entities": ["list of entity IDs affected"],
    "target_components": ["list of component type_ids as integers"],
    "target_fields": ["list of field names"],
    "intended_mutation_type": "one of: SetValue|ScaleValue|CreateActor|DefineRule|...",
    "risk_assessment": "low|medium|high",
    "requires_code_generation": false,
    "requires_sgc_recompile": false,
    "reasoning": "1-3 sentences explaining the plan"
}}

Respond with JSON only. No preamble or explanation outside the JSON block.
""",
    ),

    # ── Pass 2: DSL Draft ──────────────────────────────────────────────────
    PromptTemplate(
        name          = "pass2_dsl_draft",
        version       = "1.0.0",
        template_type = TemplateType.USER,
        cacheable     = False,
        description   = "PASS 2: generates DSL mutation transaction draft.",
        text          = """\
## TASK: PASS 2 — DSL MUTATION DRAFT

Based on the reasoning plan below, generate a DSL mutation transaction.
All paths must be fully qualified from a known CGS root (metadata, global_systems, modes).

### Reasoning Plan
{reasoning_plan}

### CGS Context
{cgs_context}

Produce a DraftMutationTransaction as JSON:
{{
    "operations": [
        {{
            "op_type": "SET|ADD|MULTIPLY|ADD_ACTOR|ADD_RULE|...",
            "target": "fully.qualified.cgs.path",
            "value": <typed value matching field type>,
            "type_hint": "float|int|str|bool|dict",
            "description": "what this operation does"
        }}
    ],
    "confidence": 0.0-1.0,
    "risk_level": "low|medium|high"
}}

Rules:
- Use EXACTLY the component type_ids from the CGS context (integers, not names).
- All numeric values must match the declared field type (no strings for float fields).
- Structural operations (ADD_ACTOR etc.) require a complete dict as value.
- Never target metadata.cgs_hash or metadata.version directly.

Respond with JSON only.
""",
    ),

    # ── Pass 3: Self-Critique ──────────────────────────────────────────────
    PromptTemplate(
        name          = "pass3_self_critique",
        version       = "1.0.0",
        template_type = TemplateType.USER,
        cacheable     = False,
        description   = "PASS 3: validates draft against path validity and scope. TIER_M.",
        text          = """\
## TASK: PASS 3 — SELF-CRITIQUE

Review the mutation draft below for errors. Check:
1. All paths are fully qualified and use correct CGS structure.
2. All op_types match their target (SET for values, ADD_ACTOR for actors, etc.).
3. No duplicate target paths in value mutations.
4. No paths target forbidden fields (metadata.cgs_hash, metadata.version).
5. The mutation stays within the allowed scope.
6. Values match their declared type_hint.

### Mutation Draft
{mutation_draft}

### Allowed Scope
{allowed_scope}

Respond with JSON:
{{
    "is_valid": true|false,
    "errors": ["list of errors if any"],
    "warnings": ["list of warnings"],
    "corrected_draft": null  // or corrected DraftMutationTransaction if errors found
}}

If no errors found, is_valid=true and corrected_draft=null.
Respond with JSON only.
""",
    ),

    # ── Pass 4: Determinism Audit ──────────────────────────────────────────
    PromptTemplate(
        name          = "pass4_determinism_audit",
        version       = "1.0.0",
        template_type = TemplateType.USER,
        cacheable     = False,
        description   = "PASS 4: checks D-rules compliance. TIER_M model.",
        text          = """\
## TASK: PASS 4 — DETERMINISM AUDIT

Audit the mutation draft for determinism violations.

### Rules to Check
- D4: Does any operation mutate state outside the Mutation Gate? (forbidden)
- D6: Does any new system definition reference random functions? (forbidden)
- D11: Are all new objects (actors, systems, rules) given stable, unique IDs?
- D10: Does this mutation require SGC recompilation? (if systems/phases change)

### Mutation Draft
{mutation_draft}

Respond with JSON:
{{
    "determinism_safe": true|false,
    "violations": ["list of D-rule violations if any"],
    "required_execution_graph_recompile": false,
    "notes": "brief note if any D-rule concerns exist"
}}

Respond with JSON only.
""",
    ),

    # ── Pass 5: Final Output ───────────────────────────────────────────────
    PromptTemplate(
        name          = "pass5_final_output",
        version       = "1.0.0",
        template_type = TemplateType.USER,
        cacheable     = False,
        description   = "PASS 5: final structured output — CommittedMutationTransaction.",
        text          = """\
## TASK: PASS 5 — FINAL STRUCTURED OUTPUT

Produce the final validated mutation transaction ready for commit.

### Validated Draft
{validated_draft}

### Determinism Audit Result
{determinism_result}

Produce a CommittedMutationTransaction as JSON:
{{
    "operations": [...],   // from validated draft
    "confidence_score": 0.0-1.0,
    "risk_level": "low|medium|high",
    "schema_delta_type": "patch|minor|major",
    "required_recompile": false,
    "summary": "one sentence plain English description for the designer"
}}

- schema_delta_type: patch=value change, minor=structural add, major=structural remove
- required_recompile: true only if system phases or dependencies changed
- summary: use plain English. No ECS vocabulary (no 'component', 'system', 'phase').

Respond with JSON only.
""",
    ),

    # ── Diagnostic: Explain ────────────────────────────────────────────────
    PromptTemplate(
        name          = "diagnostic_explain",
        version       = "1.0.0",
        template_type = TemplateType.USER,
        cacheable     = False,
        description   = "Diagnostic pass 1: explains what is happening in a game system.",
        text          = """\
## TASK: EXPLAIN

The designer asked: {designer_question}

Relevant context from the game schema:
{cgs_context}

Explain in plain English, as if speaking to a game designer with no technical background.
Do NOT use any of these words: component, system, phase, ECS, entity, schema, tick, DSL.
Instead say: character, behaviour, rule, game piece, moment, pattern.

Keep the explanation under 150 words. Offer 1-2 suggestions if you see room for improvement.
""",
    ),

    # ── Code Generation: Rust System ──────────────────────────────────────
    PromptTemplate(
        name          = "codegen_rust_system",
        version       = "1.0.0",
        template_type = TemplateType.USER,
        cacheable     = False,
        description   = "Code generation: generates Rust ISystem implementation from SystemSpec.",
        text          = """\
## TASK: GENERATE RUST SYSTEM IMPLEMENTATION

Generate a Rust struct implementing the ISystem trait for the following specification.

### System Specification
{system_spec_json}

### ISystem Trait Requirements
- Implement `fn execute(&self, ctx: &mut SystemContext) -> Result<(), XaceError>`
- Read components via `ctx.query::<(ComponentA, ComponentB)>()`
- ALL writes via `ctx.mutation_gate().request_*(...)` — NEVER mutate directly
- Use ONLY `ctx.rng()` for any randomness — NEVER use rand::random or thread_rng
- Iterate entities in EntityID sorted order (ctx.query returns sorted)
- Mark `deterministic: true` in the SystemDefinition

### XACE Determinism Rules
{determinism_rules_summary}

Generate:
1. The Rust struct implementing ISystem
2. The `#[derive(Debug)]` attribute
3. Proper error handling with `?` propagation

Return ONLY valid Rust code. No markdown fences. No explanation text.
Code must compile with: `cargo check --edition 2021`
""",
    ),
]


# ── Template Registry ─────────────────────────────────────────────────────────

class PromptTemplateRegistry:
    """
    Manages named, versioned prompt templates for all PIL passes.

    One instance shared across all PIL submodules.

    Usage
    -----
        registry = PromptTemplateRegistry()

        # Get a template
        template = registry.get("pass2_dsl_draft")
        text = template.render(
            reasoning_plan=json.dumps(plan),
            cgs_context=cgs_summary,
        )

        # Check if cacheable (for PromptPart construction)
        if template.cacheable:
            parts.append(PromptCache.mark_cacheable(text, template.name))
        else:
            parts.append(PromptCache.mark_dynamic(text, template.name))
    """

    def __init__(self) -> None:
        # name → {version → PromptTemplate}
        self._templates: dict[str, dict[str, PromptTemplate]] = {}
        # model-specific overrides: (name, model_id) → PromptTemplate
        self._overrides: dict[tuple[str, str], PromptTemplate] = {}
        self._load_builtins()

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get(
        self,
        name:     str,
        model_id: str = "",
        version:  str = "",
    ) -> PromptTemplate:
        """
        Returns the best matching template for name + model_id.
        Priority: model-specific override > version-pinned > latest.

        Raises
        ------
        TemplateNotFoundError
            If no template with the given name exists.
        """
        # Check model-specific override first
        if model_id:
            override = self._overrides.get((name, model_id))
            if override:
                return override

        versions = self._templates.get(name)
        if not versions:
            raise TemplateNotFoundError(
                f"No prompt template found for '{name}'. "
                f"Available: {sorted(self._templates.keys())}"
            )

        if version and version in versions:
            return versions[version]

        # Return latest version (highest semver string)
        return versions[max(versions.keys())]

    def render(
        self,
        name:     str,
        model_id: str = "",
        version:  str = "",
        **variables: Any,
    ) -> str:
        """Gets the template and renders it with variables in one call."""
        return self.get(name, model_id, version).render(**variables)

    def is_cacheable(self, name: str, model_id: str = "") -> bool:
        """Returns True if the template is marked cacheable."""
        try:
            return self.get(name, model_id).cacheable
        except TemplateNotFoundError:
            return False

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, template: PromptTemplate) -> None:
        """Registers a template. If name+version exists, replaces it."""
        self._templates.setdefault(template.name, {})[template.version] = template

    def set_override(
        self,
        name:     str,
        model_id: str,
        template: PromptTemplate,
    ) -> None:
        """
        Registers a model-specific template override.
        When model_id matches, this takes priority over the base template.
        """
        self._overrides[(name, model_id)] = template

    def remove_override(self, name: str, model_id: str) -> bool:
        return self._overrides.pop((name, model_id), None) is not None

    # ── Introspection ─────────────────────────────────────────────────────────

    def all_names(self) -> list[str]:
        return sorted(self._templates.keys())

    def versions_for(self, name: str) -> list[str]:
        return sorted(self._templates.get(name, {}).keys())

    def overrides_for_model(self, model_id: str) -> list[str]:
        return [n for (n, m) in self._overrides if m == model_id]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_builtins(self) -> None:
        for template in _BUILTIN_TEMPLATES:
            self.register(template)


class TemplateNotFoundError(Exception):
    """Raised when a requested template name has no registered entry."""
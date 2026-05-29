"""
rust_code_generator.py — RustCodeGenerator
============================================
Calls inference_adapter (II1) to generate a Rust ISystem implementation
from a SystemSpec. Bounded retry hard-capped at 2 per Audit 8.

## II1 Compliance

    This module calls inference_adapter.py via adapter.call(InferenceRequest).
    It NEVER imports anthropic, openai, requests, or any HTTP library directly.
    All LLM calls go through InferenceAdapter.call().

## Tier Routing

    Code generation uses TIER_XL (Anthropic Opus 4.x primary).
    Code gen is not balance-adjustment or simple mutation — it requires
    deep reasoning about Rust types, lifetimes, trait contracts, and
    the XACE runtime model. TIER_M and TIER_L are insufficient.

## Retry Policy (Audit 8 — HARD CAP)

    MAX_ATTEMPTS = 2 (first attempt + 1 correction attempt)

    On first failure (contract violation or compile error):
        - Inject precise error feedback into next attempt
        - Re-run with correction context

    On second failure:
        - Raise CodeGenerationError
        - cargo_compiler.py / code_generation_engine.py escalates
          to ClarificationEngine

    This cap is NON-NEGOTIABLE. No configuration override. No exception.

## Prompt Structure

    Cached prefix (cacheable=True):
        - XACE ISystem trait definition (stable across calls)
        - MutationGate API (stable)
        - SystemContext API (stable)
        - Determinism rules (stable)

    Dynamic body (cacheable=False):
        - SystemSpec.to_prompt_context() — full spec
        - Correction context (empty on first attempt, populated on retry)
        - Code generation task instruction

## Output

    Returns GeneratedCode:
        rust_source  : str    — the full Rust source
        attempt      : int    — which attempt produced this (1 or 2)
        raw_response : str    — raw LLM output for audit
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

try:
    from inference_adapter import InferenceRequest, PromptPart, InferenceResponse
    from model_descriptor import ComplexityTier
except ImportError:
    import dataclasses as _dc, uuid as _uuid

    @_dc.dataclass
    class PromptPart:                                    # type: ignore[no-redef]
        text: str; cacheable: bool = False; label: str = ""

    @_dc.dataclass
    class InferenceRequest:                             # type: ignore[no-redef]
        prompt_parts: list; system_prompt: str = ""
        logical_model: str = "architect_codegen"
        complexity_tier: str = "TIER_XL"; max_tokens: int = 0
        temperature: float = 0.0; session_id: str = ""
        call_label: str = ""
        request_id: str = _dc.field(default_factory=lambda: _uuid.uuid4().hex)
        cgs_structural_hash: str = ""; intent_class: str = ""
        bypass_response_cache: bool = False

    class ComplexityTier:                               # type: ignore[no-redef]
        XL = "TIER_XL"; L = "TIER_L"; M = "TIER_M"; S = "TIER_S"

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from system_spec_builder import SystemSpec

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_ATTEMPTS    = 2        # Audit 8 hard cap — never change
PASS_LABEL      = "rust_code_generation"
LOGICAL_MODEL   = "architect_codegen"   # maps to TIER_XL in model_router
TIER            = "TIER_XL"
MAX_TOKENS      = 2048     # Rust systems are ~150-300 lines
TEMPERATURE     = 0.0      # Deterministic generation


# ── Generated Code ────────────────────────────────────────────────────────────

@dataclass
class GeneratedCode:
    """Output of RustCodeGenerator.generate()."""
    rust_source:  str
    attempt:      int    # 1 = first attempt, 2 = after correction
    raw_response: str    # raw LLM output for audit trail
    system_id:    str    # echoed from spec

    def __repr__(self) -> str:
        lines = len(self.rust_source.splitlines())
        return (
            f"GeneratedCode(system={self.system_id!r}, "
            f"attempt={self.attempt}, lines={lines})"
        )


# ── Code Generation Error ─────────────────────────────────────────────────────

class CodeGenerationError(Exception):
    """
    Raised when both generation attempts fail.
    code_generation_engine.py escalates to ClarificationEngine.
    """
    def __init__(
        self,
        system_id: str,
        attempts:  int,
        last_error: str,
    ) -> None:
        self.system_id  = system_id
        self.attempts   = attempts
        self.last_error = last_error
        super().__init__(
            f"Code generation failed for '{system_id}' after {attempts} "
            f"attempt(s). Last error: {last_error[:200]}. "
            f"Escalating to ClarificationEngine."
        )


# ── Rust Code Generator ───────────────────────────────────────────────────────

class RustCodeGenerator:
    """
    Generates Rust ISystem implementations via InferenceAdapter (TIER_XL).

    One instance per PIL session. Stateless between calls.

    Usage
    -----
        generator = RustCodeGenerator(adapter)
        code = generator.generate(
            spec        = system_spec,
            session_id  = "s1",
            correction  = "",           # "" on first attempt
        )
        # code.rust_source → full Rust source
    """

    def __init__(self, adapter: Any) -> None:
        """
        Parameters
        ----------
        adapter : InferenceAdapter
            The shared InferenceAdapter from packages/inference (II1).
        """
        self._adapter = adapter

    def generate(
        self,
        spec:       SystemSpec,
        session_id: str = "",
        correction: str = "",  # injected by engine on retry
        attempt:    int = 1,
    ) -> GeneratedCode:
        """
        Generates a Rust ISystem implementation for the given spec.

        Parameters
        ----------
        spec       : SystemSpec  — complete system specification
        session_id : str         — for telemetry
        correction : str         — error feedback from previous attempt
        attempt    : int         — current attempt number (1 or 2)

        Returns
        -------
        GeneratedCode

        Raises
        ------
        CodeGenerationError
            When attempt > MAX_ATTEMPTS.
        ValueError
            When spec is invalid (caller should validate first).
        """
        if not spec.is_valid:
            raise ValueError(
                f"SystemSpec for '{spec.system_id}' is invalid: "
                f"{spec.validation_errors}"
            )

        if attempt > MAX_ATTEMPTS:
            raise CodeGenerationError(
                spec.system_id, attempt - 1,
                correction or "Max attempts reached"
            )

        request  = self._build_request(spec, session_id, correction, attempt)
        response = self._adapter.call(request)
        rust_src = self._extract_rust(response.text, spec)

        return GeneratedCode(
            rust_source  = rust_src,
            attempt      = attempt,
            raw_response = response.text,
            system_id    = spec.system_id,
        )

    # ── Request construction ──────────────────────────────────────────────────

    def _build_request(
        self,
        spec:       SystemSpec,
        session_id: str,
        correction: str,
        attempt:    int,
    ) -> InferenceRequest:
        """Builds the InferenceRequest for code generation."""

        # ── Cached prefix — XACE trait definitions (stable) ──────────────────
        cached_part = PromptPart(
            text      = _XACE_TRAIT_DEFINITIONS,
            cacheable = True,
            label     = "xace_trait_defs",
        )

        # ── Dynamic body — spec + correction + task ───────────────────────────
        dynamic_parts: list[PromptPart] = []

        # Correction from previous attempt (non-empty on retry)
        if correction:
            dynamic_parts.append(PromptPart(
                text      = (
                    f"=== CORRECTION REQUIRED ===\n"
                    f"Your previous attempt had these errors:\n"
                    f"{correction}\n"
                    f"Fix ALL errors above in this attempt.\n"
                    f"=== END CORRECTION ==="
                ),
                cacheable = False,
                label     = "correction",
            ))

        # System specification
        dynamic_parts.append(PromptPart(
            text      = spec.to_prompt_context(),
            cacheable = False,
            label     = "system_spec",
        ))

        # Task instruction
        dynamic_parts.append(PromptPart(
            text      = _CODEGEN_TASK_INSTRUCTION,
            cacheable = False,
            label     = "task",
        ))

        return InferenceRequest(
            prompt_parts     = [cached_part] + dynamic_parts,
            system_prompt    = _CODEGEN_SYSTEM_PROMPT,
            logical_model    = LOGICAL_MODEL,
            complexity_tier  = TIER,
            max_tokens       = MAX_TOKENS,
            temperature      = TEMPERATURE,
            session_id       = session_id,
            call_label       = f"{PASS_LABEL}_attempt{attempt}",
            intent_class     = "CodeGeneration",
        )

    # ── Rust source extraction ────────────────────────────────────────────────

    @staticmethod
    def _extract_rust(raw_response: str, spec: SystemSpec) -> str:
        """
        Extracts Rust source from the LLM response.

        Handles:
        - Raw Rust code (no fences)
        - ```rust ... ``` fenced blocks
        - ``` ... ``` generic fenced blocks

        Validates that the extracted code is non-empty and contains
        the expected struct name.
        """
        text = raw_response.strip()

        # Try to extract fenced block
        fence_match = re.search(
            r'```(?:rust)?\s*\n(.*?)```',
            text,
            re.DOTALL,
        )
        if fence_match:
            extracted = fence_match.group(1).strip()
        else:
            extracted = text

        # Minimal sanity: must contain the struct name
        if spec.rust_struct_name not in extracted:
            # Fallback: return full text (validator will catch the issue)
            return text

        return extracted


# ── XACE Trait Definitions (cached prefix) ────────────────────────────────────

_XACE_TRAIT_DEFINITIONS = """\
=== XACE ENGINE CONTRACTS (always apply) ===

/// Core system trait. Every game system implements this.
pub trait ISystem: Send + Sync {
    /// Called once when the system is first registered.
    fn init(&mut self, ctx: &mut SystemContext);

    /// Called every simulation tick. Must be deterministic.
    fn execute(&mut self, ctx: &mut SystemContext);
}

/// SystemContext provides read/write access to the ECS.
/// Read access: ctx.read_component::<TypeId>(entity_id)
/// Write access: ctx.mutation_gate().apply(mutation)
/// Iteration:    ctx.entities_with::<TypeId>() → sorted Vec<EntityId>
/// RNG:          ctx.deterministic_rng() → &mut DeterministicRng
impl SystemContext {
    pub fn read_component<C: Component>(&self, entity: EntityId) -> Option<&C>;
    pub fn entities_with<C: Component>(&self) -> Vec<EntityId>; // always sorted
    pub fn mutation_gate(&mut self) -> &mut MutationGate;
    pub fn deterministic_rng(&mut self) -> &mut DeterministicRng;
    pub fn current_tick(&self) -> u64;
}

/// MutationGate: the ONLY way to write component data.
/// Never mutate component fields directly.
impl MutationGate {
    pub fn apply<C: Component>(&mut self, entity: EntityId, mutation: C) -> Result<(), MutationError>;
    pub fn apply_partial<C: Component, F>(&mut self, entity: EntityId, f: F) -> Result<(), MutationError>
    where F: FnOnce(&mut C);
}

/// DeterministicRng: seeded per system+tick, never uses OS entropy.
impl DeterministicRng {
    pub fn next_u32(&mut self) -> u32;
    pub fn next_f32(&mut self) -> f32;  // range [0.0, 1.0)
    pub fn next_range(&mut self, low: i32, high: i32) -> i32;
}

DETERMINISM RULES (all must be satisfied):
1. fn execute() must produce identical output for identical input on every run.
2. Never call rand::random(), thread_rng(), OsRng, or any OS entropy source.
3. Use ctx.deterministic_rng() if you need randomness (seeded per tick+system).
4. Never read Instant::now(), SystemTime::now(), or wall-clock time.
5. Entity iteration via ctx.entities_with() returns a SORTED Vec — always iterate in order.
6. Use BTreeMap/BTreeSet for any internal sorted collections, never HashMap/HashSet.
7. All writes go through ctx.mutation_gate().apply() — never mutate fields directly.
8. No static mut, thread_local!, or lazy_static! inside execute().
=== END XACE ENGINE CONTRACTS ===\
"""

# ── System Prompt ─────────────────────────────────────────────────────────────

_CODEGEN_SYSTEM_PROMPT = """\
You are an expert Rust game engine programmer specialising in Entity-Component-System (ECS) architecture.
You generate production-quality, deterministic Rust code implementing XACE game systems.
You strictly follow the XACE ISystem trait contract and all determinism rules.
Respond with ONLY the Rust source code — no explanation, no markdown prose outside the code block.\
"""

# ── Task Instruction ──────────────────────────────────────────────────────────

_CODEGEN_TASK_INSTRUCTION = """\
=== CODE GENERATION TASK ===

Using the SYSTEM SPEC above and the XACE ENGINE CONTRACTS, generate a complete Rust implementation.

Requirements:
1. Define a pub struct matching the system name exactly (e.g. pub struct MovementSystem { ... })
2. impl ISystem for <StructName> with BOTH fn init() and fn execute()
3. In execute(): iterate ctx.entities_with() (already sorted), read declared components, apply writes via mutation_gate()
4. Use ctx.deterministic_rng() if randomness is needed — NEVER rand::random() or thread_rng()
5. Use BTreeMap/BTreeSet for internal collections — NEVER HashMap/HashSet
6. All field types must match the spec's Rust types exactly
7. Include use statements for all needed XACE types
8. Add a brief doc comment on the struct explaining what the system does

Output format:
```rust
// your generated Rust code here
```

Do NOT include any text outside the ```rust ... ``` block.\
"""
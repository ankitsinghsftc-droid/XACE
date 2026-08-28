"""
model_descriptor.py — ModelDescriptor
========================================
Per-model metadata record: provider, model ID, pricing, context window,
capability flags, and complexity tier.

Prices last verified: May 2026. Update before any production billing decisions.
Pricing sources: platform.claude.com/docs/pricing, openai.com/api/pricing,
api-docs.deepseek.com/quick_start/pricing, openrouter.ai (GLM-5.1, MiniMax M2.7),
docs.z.ai.

## How to Add a New Model (3 steps — read before adding)

STEP 1 — Add a ModelDescriptor instance in this file:

    MY_MODEL = ModelDescriptor(
        logical_name             = "my_logical_name",
        provider                 = "myprovider",          # must match registered client
        model_id                 = "my-model-id",         # exact string sent to API
        context_window_tokens    = 200_000,
        max_output_tokens        = 32_768,
        input_price_per_1k       = 0.001,                 # USD per 1K input tokens
        output_price_per_1k      = 0.004,                 # USD per 1K output tokens
        cache_write_price_per_1k = 0.00125,               # 0.0 if automatic / none
        cache_read_price_per_1k  = 0.0001,                # 0.0 if unsupported
        supports_cache_control   = False,                 # True only for Anthropic API
        default_tier             = ComplexityTier.M,
        capabilities             = frozenset({ModelCapability.GENERATION, ...}),
        notes                    = "My model. Pricing: Month Year.",
    )

STEP 2 — Add the instance to BUILTIN_DESCRIPTORS at the bottom of this file:

    BUILTIN_DESCRIPTORS["my_logical_name"] = MY_MODEL

    # or just add it to the list in the dict comprehension — both work

STEP 3 — Create or reuse a provider client:
    - OpenAI-compatible API (DeepSeek, GLM, MiniMax, etc.):
        Subclass or instantiate openai_provider.py with your base_url + api_key.
        Register: registry.register_client("myprovider", OpenAIProvider(base_url=...))
    - Anthropic-compatible API (some GLM endpoints):
        Use anthropic_provider.py with a different base_url.
    - Entirely new protocol: implement IProviderClient from provider_registry.py.

That is all. model_router.py reads BUILTIN_DESCRIPTORS automatically.

## Pricing field notes
    cache_write_price_per_1k: Anthropic = 1.25× input price.
                              Other providers: 0.0 (caching is automatic — no write cost).
    cache_read_price_per_1k:  Anthropic = 0.1× input price (90% savings).
                              OpenAI = 75% discount (auto). DeepSeek = ~98% (auto).
    supports_cache_control:   True ONLY for Anthropic API models. Enables prompt_cache.py
                              to set cache_control headers on PromptPart(cacheable=True).
                              All other providers cache automatically — no directive needed.

## Tier guidance
    TIER_S  — no LLM call; Phase 12 GDE deterministic path handles it
    TIER_M  — cheap: validation, self-critique, simple queries
    TIER_L  — standard: mutation drafting, balance changes
    TIER_XL — premium: structural surgery, code generation, deep reasoning
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Complexity Tiers ──────────────────────────────────────────────────────────

class ComplexityTier:
    S  = "TIER_S"
    M  = "TIER_M"
    L  = "TIER_L"
    XL = "TIER_XL"
    ALL: tuple[str, ...] = (S, M, L, XL)

    @classmethod
    def is_valid(cls, tier: str) -> bool:
        return tier in cls.ALL

    @classmethod
    def requires_llm(cls, tier: str) -> bool:
        return tier != cls.S

    @classmethod
    def rank(cls, tier: str) -> int:
        return {cls.S: 0, cls.M: 1, cls.L: 2, cls.XL: 3}.get(tier, -1)


# ── Capability Flags ──────────────────────────────────────────────────────────

class ModelCapability:
    GENERATION    = "generation"
    CODE_GEN      = "code_gen"
    CRITIQUE      = "critique"
    REASONING     = "reasoning"
    FUNCTION_CALL = "function_call"
    STREAMING     = "streaming"
    VISION        = "vision"
    STRUCTURED_OUTPUT = "structured_output"


# ── Model Descriptor ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelDescriptor:
    """
    Immutable description of one AI model accessible from XACE.
    See module docstring for how to add a new model in 3 steps.
    """

    logical_name:              str
    provider:                  str
    model_id:                  str
    context_window_tokens:     int
    max_output_tokens:         int
    input_price_per_1k:        float
    output_price_per_1k:       float
    cache_write_price_per_1k:  float
    cache_read_price_per_1k:   float
    supports_cache_control:    bool
    default_tier:              str
    capabilities:              frozenset[str]   = field(default_factory=frozenset)
    notes:                     str              = ""

    def can(self, capability: str) -> bool:
        return capability in self.capabilities

    def cost_estimate_cents(
        self,
        input_tokens:       int,
        output_tokens:      int,
        cache_read_tokens:  int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Estimated cost in USD cents for one call."""
        input_cost  = (input_tokens  / 1000.0) * self.input_price_per_1k
        output_cost = (output_tokens / 1000.0) * self.output_price_per_1k
        read_cost   = (cache_read_tokens  / 1000.0) * self.cache_read_price_per_1k
        write_cost  = (cache_write_tokens / 1000.0) * self.cache_write_price_per_1k
        return (input_cost + output_cost + read_cost + write_cost) * 100.0

    def dynamic_token_budget(self, static_prefix_tokens: int) -> int:
        """Tokens remaining for dynamic context after prefix + max output reservation."""
        return max(0, self.context_window_tokens - static_prefix_tokens - self.max_output_tokens)

    def is_tier(self, tier: str) -> bool:
        return self.default_tier == tier

    def __repr__(self) -> str:
        return (
            f"ModelDescriptor({self.logical_name!r} "
            f"→ {self.provider}/{self.model_id!r}, tier={self.default_tier})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ANTHROPIC MODELS
# Pricing: platform.claude.com/docs/pricing — May 2026
# Cache: supports_cache_control=True
# Cache write = 1.25× input; cache read = 0.10× input (90% savings)
# ─────────────────────────────────────────────────────────────────────────────

_ANTHROPIC_FULL = frozenset({
    ModelCapability.GENERATION, ModelCapability.CODE_GEN, ModelCapability.CRITIQUE,
    ModelCapability.REASONING,  ModelCapability.FUNCTION_CALL, ModelCapability.STREAMING,
    ModelCapability.VISION, ModelCapability.STRUCTURED_OUTPUT,
})

ANTHROPIC_OPUS_4_7 = ModelDescriptor(
    logical_name             = "premium_reasoning",
    provider                 = "anthropic",
    model_id                 = "claude-opus-4-7",
    context_window_tokens    = 1_000_000,
    max_output_tokens        = 128_000,
    input_price_per_1k       = 0.005,       # $5.00 / MTok
    output_price_per_1k      = 0.025,       # $25.00 / MTok
    cache_write_price_per_1k = 0.00625,     # $6.25 / MTok  (1.25× input)
    cache_read_price_per_1k  = 0.0005,      # $0.50 / MTok  (0.10× input)
    supports_cache_control   = True,
    default_tier             = ComplexityTier.XL,
    capabilities             = _ANTHROPIC_FULL,
    notes                    = (
        "TIER_XL. Use for structural changes and code generation only. "
        "New tokenizer produces up to 35% more tokens than Opus 4.6 for same text — "
        "benchmark before migrating. Released April 16, 2026."
    ),
)

ANTHROPIC_SONNET_4_6 = ModelDescriptor(
    logical_name             = "standard_mutation",
    provider                 = "anthropic",
    model_id                 = "claude-sonnet-4-6",
    context_window_tokens    = 1_000_000,
    max_output_tokens        = 64_000,
    input_price_per_1k       = 0.003,       # $3.00 / MTok
    output_price_per_1k      = 0.015,       # $15.00 / MTok
    cache_write_price_per_1k = 0.00375,     # $3.75 / MTok
    cache_read_price_per_1k  = 0.0003,      # $0.30 / MTok
    supports_cache_control   = True,
    default_tier             = ComplexityTier.L,
    capabilities             = _ANTHROPIC_FULL,
    notes                    = (
        "Default TIER_L. 1M context at flat rate, no long-context surcharge. "
        "Current Claude Code default model. Pricing: May 2026."
    ),
)

ANTHROPIC_HAIKU_4_5 = ModelDescriptor(
    logical_name             = "cheap_validation",
    provider                 = "anthropic",
    model_id                 = "claude-haiku-4-5-20251001",
    context_window_tokens    = 200_000,
    max_output_tokens        = 8_192,
    input_price_per_1k       = 0.001,       # $1.00 / MTok
    output_price_per_1k      = 0.005,       # $5.00 / MTok
    cache_write_price_per_1k = 0.00125,     # $1.25 / MTok
    cache_read_price_per_1k  = 0.0001,      # $0.10 / MTok
    supports_cache_control   = True,
    default_tier             = ComplexityTier.M,
    capabilities             = frozenset({
        ModelCapability.GENERATION, ModelCapability.CRITIQUE,
        ModelCapability.FUNCTION_CALL, ModelCapability.STREAMING, ModelCapability.VISION,
        ModelCapability.STRUCTURED_OUTPUT,
    }),
    notes                    = (
        "TIER_M. Validation passes (pass3/pass4), simple queries. "
        "Do NOT route code generation here. Pricing: May 2026."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# OPENAI MODELS
# Pricing: openai.com/api/pricing — May 2026
# Cache: automatic (no cache_control header). Cached input = 75% discount.
# WARNING: prompts >272K input tokens billed at 2× input + 1.5× output.
# ─────────────────────────────────────────────────────────────────────────────

OPENAI_GPT5_5 = ModelDescriptor(
    logical_name             = "openai_premium",
    provider                 = "openai",
    model_id                 = "gpt-5.5",
    context_window_tokens    = 1_050_000,   # 922K input + 128K output
    max_output_tokens        = 128_000,
    input_price_per_1k       = 0.005,       # $5.00 / MTok
    output_price_per_1k      = 0.030,       # $30.00 / MTok
    cache_write_price_per_1k = 0.0,         # automatic — no explicit write cost
    cache_read_price_per_1k  = 0.00125,     # $1.25 / MTok auto cached (75% discount)
    supports_cache_control   = False,
    default_tier             = ComplexityTier.XL,
    capabilities             = frozenset({
        ModelCapability.GENERATION, ModelCapability.CODE_GEN, ModelCapability.CRITIQUE,
        ModelCapability.REASONING,  ModelCapability.FUNCTION_CALL, ModelCapability.STREAMING,
        ModelCapability.VISION, ModelCapability.STRUCTURED_OUTPUT,
    }),
    notes                    = (
        "TIER_XL OpenAI fallback. Released April 24, 2026. "
        "Keep prompt under 272K tokens to avoid long-context surcharge (2×/1.5×). "
        "Output is $30/MTok — significantly more expensive than Opus 4.7 output. "
        "Use only when Anthropic is unavailable."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# DEEPSEEK V4 MODELS
# Pricing: api-docs.deepseek.com/quick_start/pricing — May 2026
# V4 Pro: 75% discount active until 2026-05-31 15:59 UTC. List: $1.74/$3.48.
# Cache: automatic (98% discount). No directive needed.
# Both models: OpenAI-compatible AND Anthropic-compatible endpoints.
# Use openai_provider.py with base_url="https://api.deepseek.com"
# ─────────────────────────────────────────────────────────────────────────────

_DEEPSEEK_CAPS = frozenset({
    ModelCapability.GENERATION, ModelCapability.CODE_GEN, ModelCapability.CRITIQUE,
    ModelCapability.REASONING,  ModelCapability.FUNCTION_CALL, ModelCapability.STREAMING,
})

DEEPSEEK_V4_FLASH = ModelDescriptor(
    logical_name             = "deepseek_standard",
    provider                 = "deepseek",
    model_id                 = "deepseek-v4-flash",
    context_window_tokens    = 1_000_000,
    max_output_tokens        = 384_000,
    input_price_per_1k       = 0.00014,     # $0.14 / MTok
    output_price_per_1k      = 0.00028,     # $0.28 / MTok
    cache_write_price_per_1k = 0.0,         # automatic
    cache_read_price_per_1k  = 0.0000028,   # $0.0028 / MTok (98% auto-discount)
    supports_cache_control   = False,
    default_tier             = ComplexityTier.M,
    capabilities             = _DEEPSEEK_CAPS,
    notes                    = (
        "Ultra-cheap TIER_M. ~36× cheaper than Opus 4.7 on input. "
        "Ideal for high-volume validation and classification. 1M context. "
        "OpenAI-compatible: api.deepseek.com. MIT license (open weights). "
        "Legacy alias deepseek-chat deprecated 2026-07-24 — use this ID now. "
        "Pricing: $0.14/$0.28 per MTok. May 2026."
    ),
)

DEEPSEEK_V4_PRO = ModelDescriptor(
    logical_name             = "deepseek_premium",
    provider                 = "deepseek",
    model_id                 = "deepseek-v4-pro",
    context_window_tokens    = 1_000_000,
    max_output_tokens        = 384_000,
    input_price_per_1k       = 0.000435,    # $0.435/MTok (75% off; list $1.74)
    output_price_per_1k      = 0.00087,     # $0.87/MTok  (75% off; list $3.48)
    cache_write_price_per_1k = 0.0,
    cache_read_price_per_1k  = 0.000003625, # $0.003625 / MTok
    supports_cache_control   = False,
    default_tier             = ComplexityTier.L,
    capabilities             = _DEEPSEEK_CAPS,
    notes                    = (
        "Cost-effective TIER_L. 75% discount until 2026-05-31 15:59 UTC. "
        "After discount expires, list price $1.74/$3.48/MTok — re-evaluate routing. "
        "80.6%% SWE-bench Verified (highest May 2026). 1.6T params, 49B active MoE. "
        "MIT license, open weights. OpenAI-compatible: api.deepseek.com."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# GLM-5.1 (Z.ai / Zhipu AI)
# Pricing: openrouter.ai/z-ai/glm-5.1 — April/May 2026
# Context: 202,752 tokens. Max output: 65,535 tokens.
# Cache: $0.26/MTok read (vs $1.05 standard — 75% discount). Automatic.
# API: OpenAI-compatible  → api.z.ai/api/openai/v1
#      Anthropic-compatible → api.z.ai/api/anthropic (drop-in for Claude Code)
# Use openai_provider.py with base_url="https://api.z.ai/api/openai/v1"
# Peak hours 14:00-18:00 UTC+8 billed at 3× standard rate.
# ─────────────────────────────────────────────────────────────────────────────

GLM_5_1 = ModelDescriptor(
    logical_name             = "zai_standard",
    provider                 = "zai",
    model_id                 = "glm-5.1",
    context_window_tokens    = 202_752,
    max_output_tokens        = 65_535,
    input_price_per_1k       = 0.00105,     # $1.05 / MTok (OpenRouter)
    output_price_per_1k      = 0.0035,      # $3.50 / MTok
    cache_write_price_per_1k = 0.0,
    cache_read_price_per_1k  = 0.00026,     # $0.26 / MTok (auto, ~75% off)
    supports_cache_control   = False,
    default_tier             = ComplexityTier.L,
    capabilities             = frozenset({
        ModelCapability.GENERATION, ModelCapability.CODE_GEN, ModelCapability.CRITIQUE,
        ModelCapability.REASONING,  ModelCapability.FUNCTION_CALL, ModelCapability.STREAMING,
    }),
    notes                    = (
        "Z.ai GLM-5.1. Released April 7, 2026. MIT license, open weights. "
        "#1 SWE-Bench Pro (58.4%%) as of April 2026. 754B MoE, 40B active. "
        "Designed for long-horizon agentic coding (autonomous up to 8 hours). "
        "PEAK HOURS WARNING: 14:00-18:00 UTC+8 billed at 3× standard — "
        "schedule heavy batches off-peak (UTC+8 early morning = US daytime). "
        "Anthropic-compatible endpoint for Claude Code: api.z.ai/api/anthropic. "
        "Pricing: $1.05/$3.50 per MTok (OpenRouter). May 2026."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# MINIMAX MODELS
# Pricing: openrouter.ai/minimax/minimax-m2.7 — May 2026
# Context: 196,608 tokens. Max output: 131,072 tokens.
# Cache: $0.059/MTok read (vs $0.299 standard — ~80% discount). Automatic.
# API: OpenAI-compatible → api.minimax.io/v1
# Use openai_provider.py with base_url="https://api.minimax.io/v1"
# ─────────────────────────────────────────────────────────────────────────────

MINIMAX_M2_7 = ModelDescriptor(
    logical_name             = "minimax_standard",
    provider                 = "minimax",
    model_id                 = "minimax-m2.7",
    context_window_tokens    = 196_608,
    max_output_tokens        = 131_072,
    input_price_per_1k       = 0.000299,    # $0.299 / MTok
    output_price_per_1k      = 0.0012,      # $1.20 / MTok
    cache_write_price_per_1k = 0.0,
    cache_read_price_per_1k  = 0.000059,    # $0.059 / MTok (auto, ~80% off)
    supports_cache_control   = False,
    default_tier             = ComplexityTier.M,
    capabilities             = frozenset({
        ModelCapability.GENERATION, ModelCapability.CODE_GEN, ModelCapability.CRITIQUE,
        ModelCapability.REASONING,  ModelCapability.FUNCTION_CALL, ModelCapability.STREAMING,
    }),
    notes                    = (
        "MiniMax M2.7. Released March 18, 2026. "
        "56.2%% SWE-Pro, strong multi-agent and office workflow performance. "
        "Automatic caching — no configuration needed. "
        "OpenAI-compatible: api.minimax.io/v1. "
        "Pricing: $0.299/$1.20 per MTok. May 2026."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE GEMINI MODELS
# Pricing: ai.google.dev/gemini-api/docs/pricing — verified May 10, 2026
# Gemini 3.1 Pro released February 19, 2026. Model ID: gemini-3.1-pro-preview
# Context-tiered pricing: ≤200K tokens: $2/$12; >200K tokens: $4/$18 per MTok
# Context caching: IMPLICIT (automatic, zero config) — cache hits at $0.20/MTok
#                  EXPLICIT (32K+ minimum, hourly storage fee $4.50/MTok/hr)
# Caching discount: 90% off input tokens on cache hits
# API: Google AI Developer API (NOT OpenAI-compatible)
#      Endpoint: generativelanguage.googleapis.com/v1beta
#      Use google_provider.py — NOT openai_provider.py
# Supports: text, vision, audio, video, function_calling, structured_output
# supports_cache_control = False: uses Google's implicit/explicit caching,
#   NOT Anthropic cache_control blocks. prompt_cache.py will use openai format.
# ─────────────────────────────────────────────────────────────────────────────

GOOGLE_GEMINI_31_PRO = ModelDescriptor(
    logical_name             = "google_flagship",
    provider                 = "google",
    model_id                 = "gemini-3.1-pro-preview",
    context_window_tokens    = 2_000_000,  # 2M token context window
    max_output_tokens        = 65_536,     # 64K output max
    input_price_per_1k       = 0.002,      # $2.00/MTok (≤200K context)
    output_price_per_1k      = 0.012,      # $12.00/MTok
    cache_write_price_per_1k = 0.0,        # explicit caching: storage-based not per-write
    cache_read_price_per_1k  = 0.0002,     # $0.20/MTok implicit cache hits (90% off)
    supports_cache_control   = False,      # uses Google caching, NOT cache_control blocks
    default_tier             = ComplexityTier.L,
    capabilities             = frozenset({
        ModelCapability.GENERATION, ModelCapability.CODE_GEN,
        ModelCapability.CRITIQUE, ModelCapability.REASONING,
        ModelCapability.FUNCTION_CALL, ModelCapability.STREAMING,
        ModelCapability.STRUCTURED_OUTPUT,
    }),
    notes                    = (
        "Gemini 3.1 Pro Preview. Released February 19, 2026. "
        "2M context window — largest Tier-1 production context. "
        "CONTEXT TIER WARNING: >200K tokens billed at $4/$18/MTok (2× standard). "
        "Cache hits (implicit, automatic): $0.20/MTok — 90%% off input. "
        "ARC-AGI-2: 77.1%%. Still in preview — not GA. "
        "Beats Claude Opus 4.7 on price at standard context ($2 vs $5/MTok). "
        "Use google_provider.py — API format is NOT OpenAI-compatible. "
        "Pricing verified May 10, 2026 from ai.google.dev/gemini-api/docs/pricing."
    ),
)

GOOGLE_GEMINI_3_FLASH = ModelDescriptor(
    logical_name             = "google_standard",
    provider                 = "google",
    model_id                 = "gemini-3-flash-preview",
    context_window_tokens    = 1_000_000,
    max_output_tokens        = 32_768,
    input_price_per_1k       = 0.0005,     # $0.50/MTok
    output_price_per_1k      = 0.003,      # $3.00/MTok
    cache_write_price_per_1k = 0.0,
    cache_read_price_per_1k  = 0.0000625,  # $0.0625/MTok (implicit cache hit, ~87.5% off)
    supports_cache_control   = False,
    default_tier             = ComplexityTier.M,
    capabilities             = frozenset({
        ModelCapability.GENERATION, ModelCapability.CRITIQUE,
        ModelCapability.FUNCTION_CALL, ModelCapability.STREAMING,
        ModelCapability.STRUCTURED_OUTPUT,
    }),
    notes                    = (
        "Gemini 3 Flash. $0.50/$3.00/MTok. 1M context. Free tier available. "
        "Good TIER_M option when DeepSeek is slow or unavailable. "
        "Use google_provider.py."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL DEVELOPMENT
# Zero cost. Requires Ollama running at localhost:11434.
# Use local_provider.py which wraps Ollama's OpenAI-compatible endpoint.
# ─────────────────────────────────────────────────────────────────────────────

LOCAL_LLAMA3_70B = ModelDescriptor(
    logical_name             = "local_dev",
    provider                 = "local",
    model_id                 = "llama-3.1-70b-instruct",
    context_window_tokens    = 32_768,
    max_output_tokens        = 4_096,
    input_price_per_1k       = 0.0,
    output_price_per_1k      = 0.0,
    cache_write_price_per_1k = 0.0,
    cache_read_price_per_1k  = 0.0,
    supports_cache_control   = False,
    default_tier             = ComplexityTier.M,
    capabilities             = frozenset({
        ModelCapability.GENERATION, ModelCapability.CRITIQUE, ModelCapability.STREAMING,
    }),
    notes                    = (
        "Local dev via Ollama (localhost:11434). Zero cost. No code_gen. "
        "Replace model_id with whatever model you have pulled (ollama pull ...)."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# BUILTIN DESCRIPTOR REGISTRY
# Add your new ModelDescriptor instance to this dict via STEP 2 (see module doc).
# ─────────────────────────────────────────────────────────────────────────────

BUILTIN_DESCRIPTORS: dict[str, ModelDescriptor] = {
    d.logical_name: d for d in [
        # ── Anthropic (primary provider) ─────────────────────────
        ANTHROPIC_HAIKU_4_5,     # TIER_M  cheap_validation
        ANTHROPIC_SONNET_4_6,    # TIER_L  standard_mutation   ← default
        ANTHROPIC_OPUS_4_7,      # TIER_XL premium_reasoning
        # ── OpenAI (XL fallback) ─────────────────────────────────
        OPENAI_GPT5_5,           # TIER_XL openai_premium
        # ── DeepSeek (ultra-cheap alternatives) ──────────────────
        DEEPSEEK_V4_FLASH,       # TIER_M  deepseek_standard
        DEEPSEEK_V4_PRO,         # TIER_L  deepseek_premium (discounted)
        # ── Z.ai GLM (agentic coding specialist) ─────────────────
        GLM_5_1,                 # TIER_L  zai_standard
        # ── MiniMax (multi-agent workflows) ──────────────────────
        MINIMAX_M2_7,            # TIER_M  minimax_standard
        # ── Google Gemini ─────────────────────────────────────────
        GOOGLE_GEMINI_31_PRO,    # TIER_L  google_flagship   (2M ctx, $2/$12)
        GOOGLE_GEMINI_3_FLASH,   # TIER_M  google_standard   ($0.50/$3)
        # ── Local development ─────────────────────────────────────
        LOCAL_LLAMA3_70B,        # TIER_M  local_dev
    ]
}


# ── Convenience helpers ───────────────────────────────────────────────────────

def descriptors_for_tier(tier: str) -> list[ModelDescriptor]:
    """All registered descriptors for a tier, sorted cheapest first."""
    return sorted(
        [d for d in BUILTIN_DESCRIPTORS.values() if d.default_tier == tier],
        key=lambda d: d.input_price_per_1k,
    )


def cheapest_for_tier(tier: str) -> ModelDescriptor | None:
    """The cheapest descriptor for a given tier, or None."""
    candidates = descriptors_for_tier(tier)
    return candidates[0] if candidates else None
"""
prompt_cache.py — PromptCache
================================
Applies Anthropic cache_control directives to cacheable prompt sections
and builds provider-specific prepared prompt structures.

## What This Does
PromptCache is the single place where PromptPart objects are converted
into provider-specific wire formats. It serves two purposes:

    1. Cache directive injection
       For Anthropic: adds {"type": "ephemeral"} cache_control blocks
       to segments marked cacheable=True in InferenceRequest.prompt_parts.
       For all other providers: no directive added (they handle caching
       automatically via prefix matching — no configuration required).

    2. Prompt format translation
       Converts XACE's canonical PromptPart list into the wire format
       each provider expects:
           Anthropic    → {"messages": [...], "system": [...]}
                          where each block is {"type": "text", "text": ...,
                                              "cache_control": {...} | absent}
           OpenAI-compat → {"messages": [{"role": "system", ...},
                                         {"role": "user", ...}]}

## Cache Strategy (Audit 9)
Only static sections get cache_control:
    ✅ constraint_aggregator output (determinism rules, R/W contracts)
    ✅ stable memory layers (Design, Structural, Behavioral)
    ✅ schema_simplifier base output (when CGS hasn't changed)
    ❌ dynamic context (per-prompt CGS slice, slot extractions)
    ❌ session memory (changes every call)
    ❌ current intent and clarification history

## Cache TTL
Anthropic's default prompt cache TTL is 5 minutes.
For extended TTL (experimental), set use_extended_ttl=True in config.
This is useful when the same project stays open for a long session.

## The Prepared Prompt Dict
The return value of prepare() is an opaque dict consumed by provider
clients (anthropic_provider.py, openai_provider.py). Each provider
client knows how to unpack its own format key.

Anthropic format:
    {
        "__format__": "anthropic",
        "system": [
            {"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "..."}  # dynamic — no cache_control
        ],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "..."}]}
        ]
    }

OpenAI-compatible format:
    {
        "__format__": "openai",
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user",   "content": "..."}
        ]
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .model_descriptor import ModelDescriptor

if TYPE_CHECKING:
    from .inference_adapter import PromptPart


# ── Cache Config ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CacheConfig:
    """
    Configuration for prompt cache behaviour.

    Attributes
    ----------
    use_extended_ttl : bool
        When True, uses extended cache TTL (beta, Anthropic only).
        Default TTL is 5 minutes. Extended TTL is ~1 hour.
        Use for long sessions where the same project is open for >5 min.
    min_cacheable_tokens : int
        Minimum tokens a section must have to be worth caching.
        Anthropic caches sections above a minimum size automatically;
        below this threshold the cache_control directive is added but
        may not actually cache (provider-side decision).
    cache_system_prompt : bool
        Whether to apply cache_control to the system prompt.
        Almost always True — system prompts rarely change per call.
    split_at_cacheable : bool
        When True, the prompt is split at the boundary between cached
        and uncached sections for maximum cache efficiency.
        When False, all cacheable blocks get cache_control individually.
    """

    use_extended_ttl:       bool = False
    min_cacheable_tokens:   int  = 100     # ~400 chars — below this don't bother
    cache_system_prompt:    bool = True
    split_at_cacheable:     bool = True


DEFAULT_CACHE_CONFIG = CacheConfig()


# ── Prepared Prompt ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PreparedPrompt:
    """
    Provider-specific prompt structure ready for wire dispatch.

    The inner dict structure varies by provider format.
    Provider clients in providers/ unpack this via the __format__ key.
    """

    __format__:          str
    payload:             dict[str, Any]

    # Stats for telemetry
    cacheable_tokens:    int   = 0
    dynamic_tokens:      int   = 0
    system_tokens:       int   = 0

    def __repr__(self) -> str:
        return (
            f"PreparedPrompt({self.__format__!r}, "
            f"cache={self.cacheable_tokens}tok, "
            f"dynamic={self.dynamic_tokens}tok)"
        )


# ── Prompt Cache ──────────────────────────────────────────────────────────────

class PromptCache:
    """
    Converts XACE PromptPart lists into provider wire formats,
    injecting Anthropic cache_control directives on cacheable sections.

    One instance is shared across InferenceAdapter calls.
    Stateless — safe for concurrent use.

    Usage
    -----
        cache   = PromptCache()
        prompt  = cache.prepare(request.prompt_parts, descriptor,
                                system_prompt=request.system_prompt)
        # prompt.__format__ == "anthropic" or "openai"
        # Provider client reads prompt.payload
    """

    def __init__(self, config: CacheConfig = DEFAULT_CACHE_CONFIG) -> None:
        self._config = config

    def prepare(
        self,
        prompt_parts:  list["PromptPart"],
        descriptor:    ModelDescriptor,
        system_prompt: str = "",
    ) -> PreparedPrompt:
        """
        Converts PromptParts to a provider-specific wire format.

        Parameters
        ----------
        prompt_parts : list[PromptPart]
            Ordered prompt segments from InferenceRequest.
        descriptor : ModelDescriptor
            Determines which wire format to produce.
        system_prompt : str
            Optional system-level instruction.

        Returns
        -------
        PreparedPrompt
            Provider-specific payload ready for the provider client.
        """
        if descriptor.provider == "anthropic":
            return self._prepare_anthropic(prompt_parts, descriptor, system_prompt)
        else:
            return self._prepare_openai_compat(prompt_parts, descriptor, system_prompt)

    # ── Anthropic Format ──────────────────────────────────────────────────────

    def _prepare_anthropic(
        self,
        parts:         list["PromptPart"],
        descriptor:    ModelDescriptor,
        system_prompt: str,
    ) -> PreparedPrompt:
        """
        Builds Anthropic Messages API format with cache_control on cacheable blocks.

        Anthropic caches up to the LAST cache_control marker in the request.
        Strategy: put all cacheable parts first, then dynamic parts.
        Add cache_control to the last cacheable block only (most efficient).
        """
        system_blocks: list[dict[str, Any]] = []
        user_blocks:   list[dict[str, Any]] = []
        cacheable_tok  = 0
        dynamic_tok    = 0
        system_tok     = 0

        # ── System prompt ──────────────────────────────────────────────────────
        if system_prompt and self._config.cache_system_prompt:
            sys_block: dict[str, Any] = {"type": "text", "text": system_prompt}
            if descriptor.supports_cache_control:
                sys_block["cache_control"] = self._cache_directive()
            system_blocks.append(sys_block)
            system_tok = len(system_prompt) // 4   # rough estimate

        # ── Separate cacheable vs dynamic parts ───────────────────────────────
        cacheable_parts = [p for p in parts if p.cacheable]
        dynamic_parts   = [p for p in parts if not p.cacheable]

        # Build cacheable blocks (put first in message for cache efficiency)
        for i, part in enumerate(cacheable_parts):
            block: dict[str, Any] = {"type": "text", "text": part.text}
            # Add cache_control only to the LAST cacheable block
            # (Anthropic caches everything up to the marker)
            if descriptor.supports_cache_control and i == len(cacheable_parts) - 1:
                block["cache_control"] = self._cache_directive()
            user_blocks.append(block)
            cacheable_tok += len(part.text) // 4

        # Build dynamic blocks (never cached)
        for part in dynamic_parts:
            user_blocks.append({"type": "text", "text": part.text})
            dynamic_tok += len(part.text) // 4

        payload = {
            "__format__":  "anthropic",
            "system":      system_blocks,
            "messages":    [
                {"role": "user", "content": user_blocks}
            ],
        }

        return PreparedPrompt(
            __format__       = "anthropic",
            payload          = payload,
            cacheable_tokens = cacheable_tok,
            dynamic_tokens   = dynamic_tok,
            system_tokens    = system_tok,
        )

    # ── OpenAI-Compatible Format ──────────────────────────────────────────────

    def _prepare_openai_compat(
        self,
        parts:         list["PromptPart"],
        descriptor:    ModelDescriptor,
        system_prompt: str,
    ) -> PreparedPrompt:
        """
        Builds OpenAI Chat Completions format.
        Used for DeepSeek, GLM, MiniMax, OpenAI, and local providers.
        No cache_control — these providers use automatic prefix matching.
        """
        messages: list[dict[str, Any]] = []
        cacheable_tok = 0
        dynamic_tok   = 0

        # System message (all cacheable content prepended here for prefix efficiency)
        system_parts = [p for p in parts if p.cacheable]
        system_text  = system_prompt
        if system_parts:
            prefix = "\n\n".join(p.text for p in system_parts)
            system_text = f"{system_prompt}\n\n{prefix}" if system_prompt else prefix
            cacheable_tok = len(system_text) // 4

        if system_text:
            messages.append({"role": "system", "content": system_text})

        # User message (dynamic parts only)
        dynamic_parts = [p for p in parts if not p.cacheable]
        user_text     = "\n\n".join(p.text for p in dynamic_parts)
        dynamic_tok   = len(user_text) // 4

        if user_text:
            messages.append({"role": "user", "content": user_text})
        elif not system_text:
            # Safety: always have at least one message
            messages.append({"role": "user", "content": "Continue."})

        payload = {
            "__format__": "openai",
            "messages":   messages,
        }

        return PreparedPrompt(
            __format__       = "openai",
            payload          = payload,
            cacheable_tokens = cacheable_tok,
            dynamic_tokens   = dynamic_tok,
            system_tokens    = 0,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cache_directive(self) -> dict[str, str]:
        """Returns the cache_control dict for Anthropic's API."""
        if self._config.use_extended_ttl:
            # Extended TTL is a beta feature as of May 2026
            return {"type": "ephemeral", "ttl": "extended"}
        return {"type": "ephemeral"}

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def mark_cacheable(text: str, label: str = "") -> "PromptPart":
        """
        Convenience factory for creating cacheable PromptParts.

        Used by context_assembler.py and memory_lifecycle_manager.py
        when injecting static sections:
            constraints = PromptCache.mark_cacheable(constraints_text, "constraints")
        """
        # Import here to avoid circular import at module level
        from .inference_adapter import PromptPart
        return PromptPart(text=text, cacheable=True, label=label)

    @staticmethod
    def mark_dynamic(text: str, label: str = "") -> "PromptPart":
        """Convenience factory for non-cacheable PromptParts."""
        from .inference_adapter import PromptPart
        return PromptPart(text=text, cacheable=False, label=label)

    def split_for_cache(
        self,
        text:          str,
        static_prefix: str,
    ) -> tuple[str, str]:
        """
        Splits a combined prompt into (static_prefix, dynamic_suffix).
        Used when the caller has a pre-assembled prompt string but wants
        to mark the static portion as cacheable.

        Returns
        -------
        tuple[str, str]
            (static_text, dynamic_text) — split at the first occurrence
            of the static_prefix boundary. If not found, treats all as dynamic.
        """
        if static_prefix and text.startswith(static_prefix):
            return static_prefix, text[len(static_prefix):]
        return "", text

    def update_config(self, config: CacheConfig) -> None:
        """Replaces the cache config. Takes effect on next prepare() call."""
        self._config = config

    def __repr__(self) -> str:
        return (
            f"PromptCache("
            f"extended_ttl={self._config.use_extended_ttl}, "
            f"cache_system={self._config.cache_system_prompt})"
        )
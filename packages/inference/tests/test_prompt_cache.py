"""
tests/test_prompt_cache.py
===========================
Tests for PromptCache, CacheKeyBuilder, and ResponseCache.
"""

from __future__ import annotations

import time
import pytest
from typing import Any

from ..src.prompt_cache import PromptCache, CacheConfig, PreparedPrompt
from ..src.cache_key_builder import CacheKeyBuilder
from ..src.response_cache import (
    ResponseCache, InMemoryResponseCache, CacheStats,
)
from ..src.model_descriptor import ANTHROPIC_SONNET_4_6, DEEPSEEK_V4_FLASH, ModelDescriptor
from ..src.inference_adapter import PromptPart


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _parts(
    cacheable_texts: list[str] = None,
    dynamic_texts:  list[str] = None,
) -> list[PromptPart]:
    parts = []
    for t in (cacheable_texts or []):
        parts.append(PromptPart(text=t, cacheable=True, label="cache"))
    for t in (dynamic_texts or []):
        parts.append(PromptPart(text=t, cacheable=False, label="dynamic"))
    return parts


def _anthropic_desc() -> ModelDescriptor:
    return ANTHROPIC_SONNET_4_6


def _openai_desc() -> ModelDescriptor:
    return DEEPSEEK_V4_FLASH


# ── PromptCache: Anthropic Format ─────────────────────────────────────────────

class TestPromptCacheAnthropicFormat:

    def setup_method(self) -> None:
        self.cache = PromptCache()
        self.desc  = _anthropic_desc()

    def test_produces_anthropic_format(self) -> None:
        parts  = _parts(dynamic_texts=["hello"])
        result = self.cache.prepare(parts, self.desc, system_prompt="You are X")
        assert result.__format__ == "anthropic"

    def test_system_prompt_in_system_block(self) -> None:
        parts  = _parts(dynamic_texts=["hello"])
        result = self.cache.prepare(parts, self.desc, system_prompt="System instruction")
        payload = result.payload
        assert "system" in payload
        assert len(payload["system"]) > 0
        assert payload["system"][0]["text"] == "System instruction"

    def test_system_prompt_gets_cache_control(self) -> None:
        parts  = _parts(dynamic_texts=["hello"])
        result = self.cache.prepare(parts, self.desc, system_prompt="Instructions")
        sys_block = result.payload["system"][0]
        assert "cache_control" in sys_block

    def test_cacheable_part_in_user_message(self) -> None:
        parts  = _parts(cacheable_texts=["static prefix"])
        result = self.cache.prepare(parts, self.desc)
        user_content = result.payload["messages"][0]["content"]
        assert any(b["text"] == "static prefix" for b in user_content)

    def test_cache_control_only_on_last_cacheable_block(self) -> None:
        parts = _parts(
            cacheable_texts=["first static", "second static"],
            dynamic_texts=["dynamic content"],
        )
        result       = self.cache.prepare(parts, self.desc)
        user_content = result.payload["messages"][0]["content"]

        cached_blocks = [b for b in user_content if b.get("text") in
                         ("first static", "second static")]
        assert len(cached_blocks) == 2

        # Only LAST cacheable block should have cache_control
        last_cached = cached_blocks[-1]
        first_cached = cached_blocks[0]
        assert "cache_control" in last_cached
        assert "cache_control" not in first_cached

    def test_dynamic_parts_never_get_cache_control(self) -> None:
        parts = _parts(
            cacheable_texts=["static"],
            dynamic_texts=["dynamic A", "dynamic B"],
        )
        result       = self.cache.prepare(parts, self.desc)
        user_content = result.payload["messages"][0]["content"]
        dynamic_blocks = [b for b in user_content
                          if b.get("text") in ("dynamic A", "dynamic B")]
        for block in dynamic_blocks:
            assert "cache_control" not in block

    def test_cache_control_type_is_ephemeral(self) -> None:
        parts  = _parts(cacheable_texts=["static"])
        result = self.cache.prepare(parts, self.desc)
        user_content = result.payload["messages"][0]["content"]
        cached = [b for b in user_content if "cache_control" in b]
        assert len(cached) > 0
        assert cached[0]["cache_control"]["type"] == "ephemeral"

    def test_cacheable_token_count_populated(self) -> None:
        parts  = _parts(cacheable_texts=["a" * 400])  # ~100 tokens
        result = self.cache.prepare(parts, self.desc)
        assert result.cacheable_tokens > 0

    def test_dynamic_token_count_populated(self) -> None:
        parts  = _parts(dynamic_texts=["b" * 800])
        result = self.cache.prepare(parts, self.desc)
        assert result.dynamic_tokens > 0


# ── PromptCache: OpenAI Format ────────────────────────────────────────────────

class TestPromptCacheOpenAIFormat:

    def setup_method(self) -> None:
        self.cache = PromptCache()
        self.desc  = _openai_desc()

    def test_produces_openai_format(self) -> None:
        parts  = _parts(dynamic_texts=["hello"])
        result = self.cache.prepare(parts, self.desc, system_prompt="Sys")
        assert result.__format__ == "openai"

    def test_system_message_in_messages(self) -> None:
        parts  = _parts(dynamic_texts=["hello"])
        result = self.cache.prepare(parts, self.desc, system_prompt="Sys")
        messages = result.payload["messages"]
        sys_msgs = [m for m in messages if m["role"] == "system"]
        assert len(sys_msgs) == 1
        assert "Sys" in sys_msgs[0]["content"]

    def test_cacheable_content_prepended_to_system(self) -> None:
        parts  = _parts(cacheable_texts=["Static prefix"], dynamic_texts=["query"])
        result = self.cache.prepare(parts, self.desc, system_prompt="Instructions")
        messages = result.payload["messages"]
        sys_msg  = next(m for m in messages if m["role"] == "system")
        assert "Static prefix" in sys_msg["content"]

    def test_no_cache_control_in_openai_format(self) -> None:
        parts  = _parts(cacheable_texts=["static"], dynamic_texts=["dynamic"])
        result = self.cache.prepare(parts, self.desc)
        for msg in result.payload["messages"]:
            assert "cache_control" not in msg

    def test_user_message_contains_dynamic_text(self) -> None:
        parts  = _parts(dynamic_texts=["my question"])
        result = self.cache.prepare(parts, self.desc)
        user_msgs = [m for m in result.payload["messages"] if m["role"] == "user"]
        assert len(user_msgs) > 0
        assert "my question" in user_msgs[0]["content"]

    def test_non_anthropic_provider_strips_cache_directives(self) -> None:
        # If somehow an anthropic-format prompt is passed to a non-anthropic provider
        anthropic_prompt = {
            "__format__": "anthropic",
            "system":     [{"type": "text", "text": "Sys", "cache_control": {"type": "ephemeral"}}],
            "messages":   [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}],
        }
        result = self.cache.prepare(anthropic_prompt, self.desc)
        # Should produce openai format without cache_control
        assert result.__format__ == "openai"
        assert "cache_control" not in str(result.payload)


# ── CacheKeyBuilder ───────────────────────────────────────────────────────────

def _cgs(name: str = "Test", actors: list = None) -> dict[str, Any]:
    return {
        "metadata": {
            "name":     name,
            "version":  "0.1.0",
            "cgs_hash": "volatile_hash_changes_every_commit",
        },
        "global_systems": [
            {"id": "sys_input", "phase": "Input", "reads": [6], "writes": [5],
             "depends_on": [], "deterministic": True}
        ],
        "modes": [
            {
                "id":      "mode_default",
                "is_default": True,
                "actors":  actors or [
                    {"id": "actor_player", "actor_type": "PLAYER",
                     "components": [{"type_id": 100, "defaults": {"current": 80.0}}]}
                ],
                "systems": [],
                "rules":   [],
            }
        ],
    }


class TestCacheKeyBuilder:

    def setup_method(self) -> None:
        self.builder = CacheKeyBuilder()

    def test_structural_hash_is_64_chars(self) -> None:
        h = self.builder.structural_hash(_cgs())
        assert len(h) == 64

    def test_structural_hash_stable_across_name_change(self) -> None:
        h1 = self.builder.structural_hash(_cgs(name="Game A"))
        h2 = self.builder.structural_hash(_cgs(name="Game B"))
        # Name is metadata — excluded from structural hash
        assert h1 == h2

    def test_structural_hash_stable_across_cgs_hash_change(self) -> None:
        cgs1 = _cgs()
        cgs2 = _cgs()
        cgs2["metadata"]["cgs_hash"] = "totally_different_hash"
        h1 = self.builder.structural_hash(cgs1)
        h2 = self.builder.structural_hash(cgs2)
        assert h1 == h2

    def test_structural_hash_changes_on_actor_add(self) -> None:
        cgs1 = _cgs()
        cgs2 = _cgs(actors=[
            {"id": "actor_player", "actor_type": "PLAYER",
             "components": [{"type_id": 100, "defaults": {"current": 80.0}}]},
            {"id": "actor_zombie", "actor_type": "ENEMY", "components": []},
        ])
        h1 = self.builder.structural_hash(cgs1)
        h2 = self.builder.structural_hash(cgs2)
        assert h1 != h2

    def test_structural_hash_changes_on_field_value_change(self) -> None:
        cgs1 = _cgs(actors=[
            {"id": "actor_player", "actor_type": "PLAYER",
             "components": [{"type_id": 100, "defaults": {"current": 80.0}}]}
        ])
        cgs2 = _cgs(actors=[
            {"id": "actor_player", "actor_type": "PLAYER",
             "components": [{"type_id": 100, "defaults": {"current": 50.0}}]}  # changed
        ])
        h1 = self.builder.structural_hash(cgs1)
        h2 = self.builder.structural_hash(cgs2)
        assert h1 != h2

    def test_asset_reference_stripped_from_hash(self) -> None:
        cgs1 = _cgs(actors=[{"id": "actor_player", "actor_type": "PLAYER",
            "components": [{"type_id": 1, "defaults": {
                "render_ref": {"id": "r1", "asset_type": "MESH", "status": "PLACEHOLDER"}
            }}]
        }])
        cgs2 = _cgs(actors=[{"id": "actor_player", "actor_type": "PLAYER",
            "components": [{"type_id": 1, "defaults": {
                "render_ref": {"id": "r2", "asset_type": "MESH", "status": "LINKED"}  # different
            }}]
        }])
        h1 = self.builder.structural_hash(cgs1)
        h2 = self.builder.structural_hash(cgs2)
        # Asset ref changes are cosmetic → same hash
        assert h1 == h2

    def test_build_key_format(self) -> None:
        key = self.builder.build("SetValue", "a" * 64, "standard_mutation")
        parts = key.split(":")
        assert len(parts) == 3
        assert parts[0] == "SetValue"
        assert parts[1] == "standard_mutation"
        assert len(parts[2]) == 16

    def test_is_valid_key(self) -> None:
        key = self.builder.build("SetValue", "a" * 64, "model")
        assert self.builder.is_valid_key(key)
        assert not self.builder.is_valid_key("bad_key")
        assert not self.builder.is_valid_key("a:b")   # only 2 parts

    def test_parse_key_roundtrip(self) -> None:
        key    = self.builder.build("SetValue", "a" * 64, "standard_mutation")
        parsed = self.builder.parse_key(key)
        assert parsed is not None
        assert parsed["intent_class"]  == "SetValue"
        assert parsed["logical_model"] == "standard_mutation"
        assert len(parsed["hash_prefix"]) == 16

    def test_build_from_cgs_matches_build(self) -> None:
        cgs = _cgs()
        sh  = self.builder.structural_hash(cgs)
        k1  = self.builder.build("SetValue", sh, "model")
        k2  = self.builder.build_from_cgs("SetValue", cgs, "model")
        assert k1 == k2


# ── ResponseCache ─────────────────────────────────────────────────────────────

class TestResponseCache:

    def setup_method(self) -> None:
        self.cache = ResponseCache(InMemoryResponseCache(max_entries=10))

    def test_get_returns_none_on_miss(self) -> None:
        assert self.cache.get("nonexistent_key") is None

    def test_put_then_get_returns_value(self) -> None:
        self.cache.put("SetValue:model:abc123", '{"ops": []}')
        result = self.cache.get("SetValue:model:abc123")
        assert result == '{"ops": []}'

    def test_empty_value_not_stored(self) -> None:
        self.cache.put("key", "")
        assert self.cache.get("key") is None

    def test_whitespace_only_value_not_stored(self) -> None:
        self.cache.put("key", "   ")
        assert self.cache.get("key") is None

    def test_debug_issue_intent_never_cached(self) -> None:
        self.cache.put("DebugIssue:model:abc123", "some_response")
        assert self.cache.get("DebugIssue:model:abc123") is None

    def test_unknown_intent_never_cached(self) -> None:
        self.cache.put("Unknown:model:abc123", "some_response")
        assert self.cache.get("Unknown:model:abc123") is None

    def test_query_explain_never_cached(self) -> None:
        self.cache.put("QueryExplain:model:abc123", "explanation")
        assert self.cache.get("QueryExplain:model:abc123") is None

    def test_set_value_is_cached(self) -> None:
        self.cache.put("SetValue:model:abc123", '{"ops": []}')
        assert self.cache.get("SetValue:model:abc123") is not None

    def test_invalidate_removes_entry(self) -> None:
        self.cache.put("SetValue:model:xyz", '{"x": 1}')
        existed = self.cache.invalidate("SetValue:model:xyz")
        assert existed
        assert self.cache.get("SetValue:model:xyz") is None

    def test_stats_track_hits_and_misses(self) -> None:
        self.cache.put("SetValue:model:k1", "response")
        self.cache.get("SetValue:model:k1")  # hit
        self.cache.get("SetValue:model:k2")  # miss
        stats = self.cache.stats()
        assert stats.hits   >= 1
        assert stats.misses >= 1


class TestInMemoryResponseCacheLRU:

    def test_lru_eviction_at_max_entries(self) -> None:
        cache = InMemoryResponseCache(max_entries=3)
        for i in range(5):
            cache.put(f"SetValue:m:{i:016d}", f"response_{i}")
        # Should have at most 3 entries
        assert cache.entry_count() <= 3

    def test_lru_oldest_evicted_first(self) -> None:
        cache = InMemoryResponseCache(max_entries=2)
        cache.put("SetValue:m:0000000000000001", "r1")
        cache.put("SetValue:m:0000000000000002", "r2")
        # Touch k1 to make it recently used
        cache.get("SetValue:m:0000000000000001")
        # Add k3 — should evict k2 (LRU)
        cache.put("SetValue:m:0000000000000003", "r3")
        assert cache.get("SetValue:m:0000000000000001") == "r1"
        assert cache.get("SetValue:m:0000000000000003") == "r3"

    def test_ttl_expiry_returns_none(self) -> None:
        cache = InMemoryResponseCache(max_entries=10, default_ttl=0.01)
        cache.put("SetValue:m:exp", "response")
        time.sleep(0.02)   # let TTL expire
        assert cache.get("SetValue:m:exp") is None
        assert cache.stats().expirations >= 1

    def test_immortal_entry_with_zero_ttl_never_expires(self) -> None:
        cache = InMemoryResponseCache(max_entries=10, default_ttl=0)
        cache.put("SetValue:m:perm", "permanent")
        time.sleep(0.01)
        assert cache.get("SetValue:m:perm") == "permanent"

    def test_invalidate_prefix_removes_matching_entries(self) -> None:
        cache = InMemoryResponseCache(max_entries=20)
        cache.put("SetValue:m:aaaa0000bbbb1111", "r1")
        cache.put("SetValue:m:aaaa0000bbbb2222", "r2")
        cache.put("ScaleValue:m:cccc0000dddd1111", "r3")
        # Remove all SetValue entries
        cache.invalidate_prefix("SetValue:")
        assert cache.get("SetValue:m:aaaa0000bbbb1111") is None
        assert cache.get("SetValue:m:aaaa0000bbbb2222") is None
        assert cache.get("ScaleValue:m:cccc0000dddd1111") is not None

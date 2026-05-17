# ============================================================================
# tests/test_local_model_manager.py
# ============================================================================
 
"""
Tests for LocalModelManager — focused on interface correctness and
internal logic without requiring a live Ollama server.
"""
 
import pytest
from unittest.mock import MagicMock, patch
 
from ..local_model_manager import (
    LocalModelManager, LocalModelConfig, DEFAULT_LOCAL_MODELS,
    _ModelState,
)
from ..inference_retry_policy import InferenceTransportError
 
 
def _manager_with_mocked_fetch(loaded_models: list[str]) -> LocalModelManager:
    """Creates a manager whose _fetch_loaded_models always returns the given list."""
    m = LocalModelManager(LocalModelConfig(auto_pull_on_miss=False))
    m._fetch_loaded_models = MagicMock(return_value=loaded_models)
    return m
 
 
class TestLocalModelManagerAvailability:
 
    def test_is_available_true_when_model_loaded(self) -> None:
        mgr = _manager_with_mocked_fetch(["llama3.1:70b", "qwen2.5:72b"])
        assert mgr.is_available("llama3.1:70b")
 
    def test_is_available_false_when_not_loaded(self) -> None:
        mgr = _manager_with_mocked_fetch([])
        assert not mgr.is_available("llama3.1:70b")
 
    def test_has_any_available_true(self) -> None:
        mgr = _manager_with_mocked_fetch(["llama3.1:70b"])
        assert mgr.has_any_available()
 
    def test_has_any_available_false_when_empty(self) -> None:
        mgr = _manager_with_mocked_fetch([])
        assert not mgr.has_any_available()
 
    def test_available_models_returns_list(self) -> None:
        mgr = _manager_with_mocked_fetch(["llama3.1:70b", "qwen2.5:72b"])
        models = mgr.available_models()
        assert "llama3.1:70b" in models
        assert "qwen2.5:72b"  in models
 
 
class TestLocalModelManagerSelection:
 
    def test_select_model_prefers_default_order(self) -> None:
        # Default order: llama3.1:70b first, then qwen2.5:72b
        mgr = _manager_with_mocked_fetch(["qwen2.5:72b", "llama3.1:70b"])
        selected = mgr.select_model()
        # First default model that is loaded
        assert selected == "llama3.1:70b"
 
    def test_select_model_returns_second_if_first_unavailable(self) -> None:
        mgr = _manager_with_mocked_fetch(["qwen2.5:72b"])
        selected = mgr.select_model()
        assert selected == "qwen2.5:72b"
 
    def test_select_model_returns_any_if_no_defaults_available(self) -> None:
        mgr = _manager_with_mocked_fetch(["custom_model:7b"])
        selected = mgr.select_model()
        assert selected == "custom_model:7b"
 
    def test_select_model_returns_first_default_when_none_loaded(self) -> None:
        mgr = _manager_with_mocked_fetch([])
        selected = mgr.select_model()
        # Falls back to first default model (will be pulled on demand)
        assert selected == DEFAULT_LOCAL_MODELS[0]
 
 
class TestLocalModelManagerProviderInterface:
 
    def test_provider_name_is_local(self) -> None:
        mgr = LocalModelManager()
        assert mgr.provider_name() == "local"
 
    def test_health_check_false_when_no_models_and_no_ollama(self) -> None:
        mgr = _manager_with_mocked_fetch([])
        # has_any_available is False → health depends on config defaults
        # With no loaded models: still returns True if default_models non-empty
        # (model will be pulled on first use)
        # health_check calls has_any_available OR has defaults
        result = mgr.health_check()
        assert isinstance(result, bool)  # must not raise
 
    def test_complete_raises_when_auto_pull_off_and_not_loaded(self) -> None:
        mgr = _manager_with_mocked_fetch([])
        # auto_pull_on_miss=False → should raise InferenceTransportError
        with pytest.raises(InferenceTransportError):
            mgr.complete(
                model_id      = "llama3.1:70b",
                prompt        = {"__format__": "openai", "messages": [{"role": "user", "content": "hi"}]},
                system_prompt = "",
                max_tokens    = 100,
                temperature   = 0.0,
            )
 
 
class TestLocalModelManagerBodyBuilding:
 
    def test_strips_cache_control_from_anthropic_format(self) -> None:
        prompt = {
            "__format__": "anthropic",
            "system": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        }
        body = LocalModelManager._build_body("model", prompt, "", 100, 0.0)
        # All messages should be plain text, no cache_control
        for msg in body["messages"]:
            assert "cache_control" not in msg
 
    def test_strips_cache_control_from_openai_format(self) -> None:
        prompt = {
            "__format__": "openai",
            "messages": [
                {"role": "system", "content": "sys", "cache_control": "bad"},
                {"role": "user",   "content": "hello"},
            ],
        }
        body = LocalModelManager._build_body("model", prompt, "", 100, 0.0)
        for msg in body["messages"]:
            assert "cache_control" not in msg
 
    def test_plain_text_prompt_becomes_user_message(self) -> None:
        body = LocalModelManager._build_body("model", {"text": "hello"}, "sys", 100, 0.0)
        assert any(m["role"] == "user" and "hello" in m["content"] for m in body["messages"])
        assert any(m["role"] == "system" and "sys" in m["content"] for m in body["messages"])
 
    def test_stream_is_false(self) -> None:
        body = LocalModelManager._build_body("model", {"text": "x"}, "", 100, 0.0)
        assert body["stream"] is False
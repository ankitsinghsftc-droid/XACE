"""
Compatibility shim for the Builder local model adapter.

The implementation lives in server/ollama_adapter.py and dispatches through
packages/inference. This file exists only for older local imports.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_server_module() -> ModuleType:
    path = Path(__file__).resolve().parent / "server" / "ollama_adapter.py"
    spec = importlib.util.spec_from_file_location("_xace_builder_server_ollama_adapter", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Builder Ollama adapter from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SERVER_MODULE = _load_server_module()

OllamaAdapter: Any = _SERVER_MODULE.OllamaAdapter
create_ollama_adapter: Any = _SERVER_MODULE.create_ollama_adapter
preferred_model_list: Any = _SERVER_MODULE.preferred_model_list

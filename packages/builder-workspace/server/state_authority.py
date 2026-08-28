"""
state_authority.py - Builder-side state authority contract.

These rules are intentionally small and explicit. They describe which runtime
surface owns each state class and which engine-originated edits can be merged
after newer CGS authoring mutations.
"""

from __future__ import annotations

from typing import Any


AUTHORITY_RULES: tuple[dict[str, str], ...] = (
    {
        "state": "durable_authoring",
        "authority": "disk_cgs",
        "write_path": "CGSPersistence.save",
        "guard": "project cgs.write.lock and submitted cgs_hash check",
    },
    {
        "state": "transactional_authoring",
        "authority": "GDE",
        "write_path": "SessionManager.apply_via_gde",
        "guard": "parent_cgs_hash and monotonic transaction_id",
    },
    {
        "state": "live_simulation",
        "authority": "runtime",
        "write_path": "runtime control and tick loop",
        "guard": "runtime_world_hash, runtime_tick, and reload version handshake",
    },
    {
        "state": "engine_presentation",
        "authority": "engine_adapter",
        "write_path": "engine edit preview only",
        "guard": "preview audit row; commit must merge through CGS",
    },
)

SUPPORTED_ENGINE_EDIT_KINDS = frozenset({
    "select_entity",
    "focus_entity",
    "set_component_field",
})
SUPPORTED_ENGINE_EDIT_COMMIT_KINDS = frozenset({"set_component_field"})

PRIMITIVE_JSON_TYPES = (str, int, float, bool)


def is_primitive_json_value(value: Any) -> bool:
    return value is None or isinstance(value, PRIMITIVE_JSON_TYPES)


def is_component_default_path(path: str) -> bool:
    parts = [part for part in path.split(".") if part]
    return "actors" in parts and "components" in parts and "defaults" in parts


def can_merge_engine_default_edit(path: str, value: Any) -> bool:
    """
    Engine commits may merge across a newer CGS only for primitive component
    default field edits. Structural edits, component/table changes, systems,
    rules, metadata, and collection edits must go through GDE/PIL.
    """
    return is_component_default_path(path) and is_primitive_json_value(value)


def engine_edit_commit_class(kind: str, path: str = "", value: Any = None) -> str:
    if kind == "select_entity":
        return "selection"
    if kind == "focus_entity":
        return "focus"
    if kind == "set_component_field" and is_primitive_json_value(value):
        return "primitive_component_default"
    if kind == "set_component_field":
        return "unsupported_component_value"
    return "unsupported"


def can_commit_engine_edit_kind(kind: str) -> bool:
    return kind in SUPPORTED_ENGINE_EDIT_COMMIT_KINDS


def authority_rules_for_docs() -> list[dict[str, str]]:
    return [dict(rule) for rule in AUTHORITY_RULES]

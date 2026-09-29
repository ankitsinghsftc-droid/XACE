"""Portable CGS -> validated Factory package -> SGC input. No I/O or mutation.

Portable exports use flat runtime fields and display-style actor/control enums.
This adapter normalizes that representation on a copy while retaining source
CGS identity. Component declarations, never actor values, define the registry.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from dcl.dcl_registry import _build_ucl_core_definitions
from dcl.gameplay_primitives import CANONICAL_COMPONENT_CONTRACTS, GAMEPLAY_PRIMITIVES
from .component_registry.component_definition import ComponentDefinition, FieldDefinition
from .component_registry.component_definition_registry import ComponentDefinitionRegistry, ComponentDefinitionRegistryError
from .schema_factory import SchemaFactory, SchemaFactoryError


def compile_portable_cgs(cgs: dict[str, Any]):
    source = copy.deepcopy(cgs)
    errors: list[str] = []
    registry = ComponentDefinitionRegistry()
    canonical = {d.type_id: (d.type_name, "ucl") for d in _build_ucl_core_definitions()}
    canonical.update(CANONICAL_COMPONENT_CONTRACTS)
    names = {name for name, _ in canonical.values()}
    # Project declarations cannot extend frozen UCL/DCL field vocabularies.
    # Reuse the shipped portable primitive catalog alongside structured UCL names.
    core_types = {d.type_id: {f.field_name: f.field_type for f in d.fields} for d in _build_ucl_core_definitions()}
    allowed_fields = {d.type_id: set(d.field_names()) for d in _build_ucl_core_definitions()}
    trusted_types: dict[int, dict[str, set[str]]] = {}
    for primitive in GAMEPLAY_PRIMITIVES:
        for component in primitive.components:
            allowed_fields.setdefault(component.type_id, set()).update(component.defaults)
            for key, value in component.defaults.items():
                trusted_types.setdefault(component.type_id, {}).setdefault(key, set()).add(_field_type(value))

    schemas = source.get("component_schemas", [])
    if not isinstance(schemas, list):
        raise SchemaFactoryError(["component_schemas must be a list"], "component_registry")
    for schema in schemas:
        if not isinstance(schema, dict):
            errors.append("component_schemas entries must be objects")
            continue
        tid, name, domain = schema.get("type_id"), schema.get("name"), schema.get("source")
        if type(tid) is not int or tid < 1 or not isinstance(name, str) or not name:
            errors.append("component schema requires a positive integer type_id and name")
            continue
        if tid in canonical:
            if (name, domain) != canonical[tid]:
                errors.append(f"component {tid} must retain canonical name/source {canonical[tid]}")
                continue
        elif tid < 10000 or domain not in {"gcl", "generated"} or name in names:
            errors.append(f"component {tid} is not a canonical UCL/DCL type or valid GCL declaration")
            continue
        defaults = schema.get("defaults", {})
        if not isinstance(defaults, dict):
            errors.append(f"component {tid} defaults must be an object")
            continue
        if tid in canonical and set(defaults) - allowed_fields.get(tid, set()):
            errors.append(f"component {tid} declares fields outside the shipped UCL/DCL contract: {sorted(set(defaults) - allowed_fields.get(tid, set()))}")
            continue
        if not _finite_json(defaults):
            errors.append(f"component {tid} defaults must contain finite JSON values")
        for key, value in defaults.items():
            expected = trusted_types.get(tid, {}).get(key)
            canonical_type = core_types.get(tid, {}).get(key)
            if not expected and canonical_type and not _matches_type(value, canonical_type):
                errors.append(f"component {tid}.{key} requires canonical type {canonical_type}")
            if expected and _field_type(value) not in expected:
                errors.append(f"component {tid}.{key} changes the shipped field type")
        if registry.get_by_name(name) is not None:
            errors.append(f"duplicate component name {name}")
        declared_types = {}
        if domain == "generated":
            raw_fields = schema.get("fields")
            if not isinstance(raw_fields, list) or not raw_fields:
                errors.append(f"generated component {tid} requires typed fields")
                continue
            for field in raw_fields:
                if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                    errors.append(f"component {tid} has invalid field metadata")
                    continue
                key, kind = field["name"], field.get("field_type")
                if key in declared_types or kind not in {"fixed", "int", "uint", "entity_id", "bool", "string", "string_list", "int_list", "object"}:
                    errors.append(f"component {tid} has invalid or duplicate field type")
                    continue
                declared_types[key] = kind
                if key not in defaults or field.get("default") != defaults[key] or not _matches_type(defaults[key], kind):
                    errors.append(f"component {tid}.{key} default conflicts with its field metadata")
            if set(declared_types) != set(defaults):
                errors.append(f"component {tid} fields/defaults differ")
        fields = tuple(FieldDefinition(k, declared_types.get(k, _field_type(v)), required=False, default=copy.deepcopy(v))
                       for k, v in sorted(defaults.items()))
        try:
            registry.register(ComponentDefinition(tid, name, "gcl" if domain == "generated" else domain.replace(".", "/"),
                                                 field_definitions=fields, is_ucl_core=tid <= 10))
        except ComponentDefinitionRegistryError as exc:
            errors.append(str(exc))
        names.add(name)
    # All ten frozen core identities exist, even if a portable export omits them.
    for definition in _build_ucl_core_definitions():
        if not registry.has_component(definition.type_id):
            registry.register(ComponentDefinition(
                definition.type_id, definition.type_name, "ucl", is_ucl_core=True,
                field_definitions=tuple(FieldDefinition(f.field_name, f.field_type, required=False)
                                        for f in definition.fields)))
    actor_types = {"PlayerCharacter": "PLAYER", "EnemyCharacter": "ENEMY",
                   "NonPlayerCharacter": "NPC", "WorldObject": "WORLD_OBJECT",
                   "Projectile": "PROJECTILE", "Pickup": "PICKUP", "Trigger": "TRIGGER",
                   "Camera": "CAMERA", "Manager": "MANAGER"}
    controls = {"Human": "HUMAN", "AI": "AI_PROXY", "AIProxy": "AI_PROXY",
                "NetworkRemote": "NETWORK_REMOTE", "None": "NONE"}
    for mode in source.get("modes", []):
        world = mode.get("world", {})
        if not isinstance(world, dict):
            errors.append(f"mode {mode.get('id')} world must be an object")
        else:
            for field in ("size", "gravity"):
                if field in world:
                    value = world[field]
                    axes = ("width", "height", "depth") if field == "size" else ("x", "y", "z")
                    if not isinstance(value, dict) or any(
                        type(value.get(axis)) not in (int, float) or not math.isfinite(value[axis])
                        or (field == "size" and value[axis] < 0) for axis in axes
                    ):
                        errors.append(f"world.{field} requires finite canonical coordinates")
            if "day_length_ticks" in world and (type(world["day_length_ticks"]) is not int or world["day_length_ticks"] < 0):
                errors.append("world.day_length_ticks must be an unsigned integer")
        for actor in mode.get("actors", []):
            actor_type = actor.get("actor_type", "UNKNOWN")
            if isinstance(actor_type, dict) and set(actor_type) == {"Custom"}:
                actor_type = actor_type["Custom"]
            actor["actor_type"] = actor_types.get(actor_type, actor_type) if isinstance(actor_type, str) else actor_type
            actor["control_type"] = controls.get(actor.get("control_type"), actor.get("control_type", "NONE"))
            for component in actor.get("components", []):
                tid = component.get("type_id")
                if tid in canonical and component.get("name", canonical[tid][0]) != canonical[tid][0]:
                    errors.append(f"component {tid} name conflicts with canonical registry")
                defaults = component.get("defaults", {})
                if not isinstance(defaults, dict) or not _finite_json(defaults):
                    errors.append(f"component {tid} values must be a finite JSON object")
                    continue
                definition = registry.get(tid)
                if definition:
                    if component.get("name", definition.name) != definition.name:
                        errors.append(f"component {tid} name conflicts with declared registry")
                    if set(defaults) - definition.field_names():
                        errors.append(f"component {tid} has undeclared fields {sorted(set(defaults) - definition.field_names())}")
                    for field in definition.field_definitions:
                        if field.name in defaults and not _matches_type(defaults[field.name], field.field_type):
                            errors.append(f"component {tid}.{field.name} requires {field.field_type}")
    for system in source.get("global_systems", []) + [s for m in source.get("modes", []) for s in m.get("systems", [])]:
        if system.get("phase") not in {"Initialization", "Input", "Simulation", "PostSimulation", "Cleanup"}:
            errors.append(f"system {system.get('id')} has invalid phase")
        if system.get("deterministic", True) is not True:
            errors.append(f"system {system.get('id')} must be deterministic")
    if errors:
        raise SchemaFactoryError(errors, "portable_projection")
    return SchemaFactory(registry).compile(source, schema_version=source.get("metadata", {}).get("schema_version"), source_cgs=cgs)


def _field_type(value: Any) -> str:
    return {bool: "bool", int: "int", float: "float", str: "str", dict: "dict", list: "list"}.get(type(value), "optional")


def _matches_type(value: Any, expected: str) -> bool:
    if expected in {"fixed", "uint", "entity_id"}:
        return type(value) is int and (expected == "fixed" or value >= 0)
    if expected in {"string_list", "int_list"}:
        item_type = str if expected == "string_list" else int
        return isinstance(value, list) and all(type(item) is item_type for item in value)
    if expected in {"string", "object"}:
        return type(value) is (str if expected == "string" else dict)
    if expected == "optional":
        return value is None
    if expected in {"u8", "u32", "u64", "i32", "i64"}:
        bits = int(expected[1:])
        lower, upper = (0, 2 ** bits) if expected[0] == "u" else (-2 ** (bits - 1), 2 ** (bits - 1))
        return type(value) is int and lower <= value < upper
    if expected in {"struct", "enum"}:
        return type(value) is (dict if expected == "struct" else str)
    if expected in {"float", "f32", "f64"}:
        return type(value) in (int, float)
    return _field_type(value) == expected


def _finite_json(value: Any) -> bool:
    if isinstance(value, dict):
        return all(isinstance(k, str) and _finite_json(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_finite_json(v) for v in value)
    return value is None or type(value) in (str, bool, int) or (type(value) is float and math.isfinite(value))

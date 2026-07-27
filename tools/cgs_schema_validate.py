#!/usr/bin/env python3
"""Validate a standalone XACE CGS export file.

This validator intentionally has no repo-local imports and no third-party
dependencies. It is the executable companion to:

    docs/CGS_SCHEMA_EXPORT_FORMAT.md

It validates the portable CGS export contract, including cross-field checks
that a plain JSON Schema cannot express.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
FORMAT_NAME = "xace.cgs.export"
FORMAT_VERSION = "1.0.0"

RESERVED_COMPONENT_TYPE_IDS = {
    1: "COMP_TRANSFORM_V1",
    2: "COMP_IDENTITY_V1",
    5: "COMP_VELOCITY_V1",
    6: "COMP_INPUT_V1",
    100: "COMP_HEALTH_V1",
    101: "COMP_DAMAGE_V1",
    160: "COMP_AI_V1",
    201: "COMP_INVENTORY_V1",
    205: "COMP_ITEM_V1",
    260: "COMP_INTERACTION_V1",
}

CANONICAL_PHASES = {
    "Initialization",
    "Input",
    "Simulation",
    "PostSimulation",
    "Cleanup",
    "Render",
}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    computed_hash: str = ""
    declared_hash: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a standalone XACE CGS export file.")
    parser.add_argument("path", help="Path to a .cgs.json file.")
    parser.add_argument(
        "--allow-legacy-hash",
        action="store_true",
        help="Warn instead of fail for non-authoritative legacy short hashes.",
    )
    parser.add_argument(
        "--allow-draft-hash",
        action="store_true",
        help="Warn instead of fail for empty/unresolved/zero draft hashes.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable validation output.",
    )
    args = parser.parse_args()

    path = Path(args.path)
    result = validate_file(
        path,
        allow_legacy_hash=args.allow_legacy_hash,
        allow_draft_hash=args.allow_draft_hash,
    )
    emit_result(path, result, as_json=args.json)
    return 0 if result.ok else 1


def validate_file(
    path: Path,
    *,
    allow_legacy_hash: bool = False,
    allow_draft_hash: bool = False,
) -> ValidationResult:
    result = ValidationResult()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        result.error(f"cannot read file: {exc}")
        return result

    try:
        cgs = json.loads(text)
    except json.JSONDecodeError as exc:
        result.error(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return result

    validate_cgs(
        cgs,
        result,
        allow_legacy_hash=allow_legacy_hash,
        allow_draft_hash=allow_draft_hash,
    )
    return result


def validate_cgs(
    cgs: Any,
    result: ValidationResult,
    *,
    allow_legacy_hash: bool,
    allow_draft_hash: bool,
) -> None:
    if not isinstance(cgs, dict):
        result.error("top-level JSON value must be an object")
        return

    check_top_level(cgs, result)
    metadata = check_metadata(cgs, result)
    modes = check_array(cgs, "modes", result)
    global_systems = check_array(cgs, "global_systems", result)
    component_schemas = check_optional_array(cgs, "component_schemas", result)

    declared_components = collect_declared_components(component_schemas, modes, result)
    all_system_ids = collect_system_ids(global_systems, modes, result)
    check_modes(modes, result)
    check_systems(global_systems, modes, all_system_ids, declared_components, result)
    check_hash(
        cgs,
        metadata,
        result,
        allow_legacy_hash=allow_legacy_hash,
        allow_draft_hash=allow_draft_hash,
    )


def check_top_level(cgs: dict[str, Any], result: ValidationResult) -> None:
    required = {"metadata", "global_systems", "modes"}
    missing = sorted(required - set(cgs))
    if missing:
        result.error(f"missing top-level fields: {missing}")

    fmt = cgs.get("format")
    fmt_version = cgs.get("format_version")
    if fmt is None or fmt_version is None:
        result.warn(
            "missing format/format_version; treating file as legacy project CGS JSON, not canonical export v1"
        )
    else:
        if fmt != FORMAT_NAME:
            result.error(f"format must be {FORMAT_NAME!r}, got {fmt!r}")
        if not isinstance(fmt_version, str) or not SEMVER_RE.fullmatch(fmt_version):
            result.error("format_version must be a MAJOR.MINOR.PATCH string")
        elif fmt_version != FORMAT_VERSION:
            result.warn(
                f"validator targets format_version {FORMAT_VERSION}; file declares {fmt_version}"
            )


def check_metadata(cgs: dict[str, Any], result: ValidationResult) -> dict[str, Any]:
    metadata = cgs.get("metadata")
    if not isinstance(metadata, dict):
        result.error("metadata must be an object")
        return {}

    for field_name in ["name", "version", "schema_version", "cgs_hash"]:
        if field_name not in metadata:
            result.error(f"metadata.{field_name} is required")

    name = metadata.get("name")
    if not isinstance(name, str) or not name.strip():
        result.error("metadata.name must be a non-empty string")

    for field_name in ["version", "schema_version"]:
        value = metadata.get(field_name)
        if not isinstance(value, str) or not SEMVER_RE.fullmatch(value):
            result.error(f"metadata.{field_name} must be a MAJOR.MINOR.PATCH string")

    return metadata


def check_array(parent: dict[str, Any], field_name: str, result: ValidationResult) -> list[Any]:
    value = parent.get(field_name)
    if not isinstance(value, list):
        result.error(f"{field_name} must be an array")
        return []
    return value


def check_optional_array(parent: dict[str, Any], field_name: str, result: ValidationResult) -> list[Any]:
    value = parent.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list):
        result.error(f"{field_name} must be an array when present")
        return []
    return value


def collect_declared_components(
    component_schemas: list[Any],
    modes: list[Any],
    result: ValidationResult,
) -> dict[int, str]:
    declared: dict[int, str] = dict(RESERVED_COMPONENT_TYPE_IDS)
    actor_ids: dict[str, str] = {}
    seen_schema_type_ids: set[int] = set()

    for schema_index, schema in enumerate(objects(component_schemas, "component_schemas", result)):
        schema_path = f"component_schemas[{schema_index}]"
        type_id = schema.get("type_id")
        if not isinstance(type_id, int) or type_id <= 0:
            result.error(f"{schema_path}.type_id must be a positive component type ID")
            continue
        if type_id in seen_schema_type_ids:
            result.error(f"component_schemas declares duplicate component type_id {type_id}")
        seen_schema_type_ids.add(type_id)

        name = schema.get("name")
        if not isinstance(name, str) or not name.strip():
            result.error(f"{schema_path}.name must be a non-empty string")
        elif type_id in declared and declared[type_id] != name:
            result.error(
                f"{schema_path} component type_id {type_id} name {name!r} conflicts with {declared[type_id]!r}"
            )
        else:
            declared[type_id] = name

        defaults = schema.get("defaults")
        if not isinstance(defaults, dict):
            result.error(f"{schema_path}.defaults must be an object")

        source = schema.get("source")
        if source is not None and (not isinstance(source, str) or not source.strip()):
            result.error(f"{schema_path}.source must be a non-empty string when present")

    for mode in objects(modes, "modes", result):
        mode_id = require_id(mode, "mode", result)
        actors = check_array_field(mode, "actors", f"mode {mode_id}", result)
        for actor in objects(actors, f"mode {mode_id}.actors", result):
            actor_id = require_id(actor, f"actor in mode {mode_id}", result)
            if actor_id:
                previous_mode = actor_ids.setdefault(actor_id, mode_id)
                if previous_mode != mode_id:
                    result.error(
                        f"duplicate actor id {actor_id!r} in modes {previous_mode!r} and {mode_id!r}"
                    )

            spawn_count = actor.get("spawn_count", 1)
            if not isinstance(spawn_count, int) or spawn_count < 1:
                result.error(f"actor {actor_id!r} spawn_count must be an integer >= 1")

            components = check_array_field(actor, "components", f"actor {actor_id}", result)
            seen_type_ids: set[int] = set()
            for component in objects(components, f"actor {actor_id}.components", result):
                type_id = component.get("type_id")
                if not isinstance(type_id, int) or type_id <= 0:
                    result.error(f"actor {actor_id!r} has component with invalid positive type_id")
                    continue
                if type_id in seen_type_ids:
                    result.error(f"actor {actor_id!r} declares duplicate component type_id {type_id}")
                seen_type_ids.add(type_id)

                name = component.get("name")
                if not isinstance(name, str) or not name.strip():
                    result.error(f"component type_id {type_id} must have a non-empty name")
                elif type_id in declared and declared[type_id] != name:
                    result.warn(
                        f"component type_id {type_id} appears with name {name!r}; earlier/reserved name is {declared[type_id]!r}"
                    )
                else:
                    declared[type_id] = name

                defaults = component.get("defaults")
                if not isinstance(defaults, dict):
                    result.error(f"component type_id {type_id} defaults must be an object")

    return declared


def collect_system_ids(
    global_systems: list[Any],
    modes: list[Any],
    result: ValidationResult,
) -> set[str]:
    ids: set[str] = set()
    non_global_seen: dict[str, str] = {}

    for system in objects(global_systems, "global_systems", result):
        system_id = require_id(system, "global system", result)
        if system_id in ids:
            result.error(f"duplicate global system id {system_id!r}")
        ids.add(system_id)

    for mode in objects(modes, "modes", result):
        mode_id = require_id(mode, "mode", result)
        systems = check_array_field(mode, "systems", f"mode {mode_id}", result)
        for system in objects(systems, f"mode {mode_id}.systems", result):
            system_id = require_id(system, f"system in mode {mode_id}", result)
            if not system_id:
                continue
            if system_id in non_global_seen:
                result.error(
                    f"duplicate non-global system id {system_id!r} in modes {non_global_seen[system_id]!r} and {mode_id!r}"
                )
            if system_id in ids:
                result.warn(f"mode {mode_id!r} system {system_id!r} overrides a global system")
            non_global_seen[system_id] = mode_id
            ids.add(system_id)

    return ids


def check_modes(modes: list[Any], result: ValidationResult) -> None:
    if not modes:
        result.error("modes must contain at least one mode")
        return

    mode_ids: set[str] = set()
    default_count = 0
    for mode in objects(modes, "modes", result):
        mode_id = require_id(mode, "mode", result)
        if mode_id in mode_ids:
            result.error(f"duplicate mode id {mode_id!r}")
        mode_ids.add(mode_id)

        schema_version = mode.get("schema_version")
        if not isinstance(schema_version, str) or not SEMVER_RE.fullmatch(schema_version):
            result.error(f"mode {mode_id!r} schema_version must be a MAJOR.MINOR.PATCH string")

        is_default = mode.get("is_default")
        if not isinstance(is_default, bool):
            result.error(f"mode {mode_id!r} is_default must be boolean")
        elif is_default:
            default_count += 1

        check_array_field(mode, "actors", f"mode {mode_id}", result)
        check_array_field(mode, "systems", f"mode {mode_id}", result)
        rules = check_array_field(mode, "rules", f"mode {mode_id}", result)
        check_rules(rules, mode_id, result)

    if default_count != 1:
        result.error(f"exactly one mode must have is_default=true; found {default_count}")


def check_rules(rules: list[Any], mode_id: str, result: ValidationResult) -> None:
    seen: set[str] = set()
    for rule in objects(rules, f"mode {mode_id}.rules", result):
        rule_id = require_id(rule, f"rule in mode {mode_id}", result)
        if rule_id in seen:
            result.error(f"duplicate rule id {rule_id!r} in mode {mode_id!r}")
        seen.add(rule_id)
        for field_name in ["condition", "effect"]:
            if not isinstance(rule.get(field_name), str):
                result.error(f"rule {rule_id!r} {field_name} must be a string")
        if not isinstance(rule.get("priority"), int):
            result.error(f"rule {rule_id!r} priority must be an integer")
        if not isinstance(rule.get("is_active"), bool):
            result.error(f"rule {rule_id!r} is_active must be boolean")


def check_systems(
    global_systems: list[Any],
    modes: list[Any],
    all_system_ids: set[str],
    declared_components: dict[int, str],
    result: ValidationResult,
) -> None:
    for system in objects(global_systems, "global_systems", result):
        check_system(system, "global_systems", all_system_ids, declared_components, result)
    for mode in objects(modes, "modes", result):
        mode_id = str(mode.get("id", "?"))
        systems = mode.get("systems", [])
        if isinstance(systems, list):
            for system in objects(systems, f"mode {mode_id}.systems", result):
                check_system(system, f"mode {mode_id}", all_system_ids, declared_components, result)


def check_system(
    system: dict[str, Any],
    context: str,
    all_system_ids: set[str],
    declared_components: dict[int, str],
    result: ValidationResult,
) -> None:
    system_id = require_id(system, f"system in {context}", result)
    phase = system.get("phase")
    if not isinstance(phase, str) or phase not in CANONICAL_PHASES:
        result.error(f"system {system_id!r} phase must be one of {sorted(CANONICAL_PHASES)}")
    elif phase == "Render":
        result.warn(f"system {system_id!r} uses Render phase; authoritative gameplay mutation should not run there")

    for field_name in ["reads", "writes"]:
        values = system.get(field_name)
        if not isinstance(values, list):
            result.error(f"system {system_id!r} {field_name} must be an array")
            continue
        for type_id in values:
            if not isinstance(type_id, int) or type_id <= 0:
                result.error(f"system {system_id!r} {field_name} contains invalid type_id {type_id!r}")
            elif type_id not in declared_components:
                result.error(
                    f"system {system_id!r} {field_name} references undeclared component type_id {type_id}"
                )

    deps = system.get("depends_on")
    if not isinstance(deps, list):
        result.error(f"system {system_id!r} depends_on must be an array")
    else:
        for dep in deps:
            if not isinstance(dep, str) or not dep.strip():
                result.error(f"system {system_id!r} depends_on contains invalid dependency {dep!r}")
            elif dep == system_id:
                result.error(f"system {system_id!r} depends_on itself")
            elif dep not in all_system_ids:
                result.error(f"system {system_id!r} depends_on unknown system {dep!r}")

    if not isinstance(system.get("deterministic"), bool):
        result.error(f"system {system_id!r} deterministic must be boolean")
    if "parallel" in system and not isinstance(system.get("parallel"), bool):
        result.error(f"system {system_id!r} parallel must be boolean when present")
    if "runtime_executor" in system and not isinstance(system.get("runtime_executor"), dict):
        result.error(f"system {system_id!r} runtime_executor must be an object when present")


def check_hash(
    cgs: dict[str, Any],
    metadata: dict[str, Any],
    result: ValidationResult,
    *,
    allow_legacy_hash: bool,
    allow_draft_hash: bool,
) -> None:
    declared = metadata.get("cgs_hash", "")
    result.declared_hash = str(declared)
    result.computed_hash = compute_cgs_hash(cgs)

    draft_values = {"", "unresolved", "0" * 64}
    if declared in draft_values:
        message = "metadata.cgs_hash is a draft/unresolved value; committed exports require a matching SHA-256 hash"
        if allow_draft_hash:
            result.warn(message)
        else:
            result.error(message)
        return

    if not isinstance(declared, str) or not HASH_RE.fullmatch(declared):
        message = "metadata.cgs_hash must be a lowercase 64-character SHA-256 hex digest"
        if allow_legacy_hash and isinstance(declared, str) and len(declared) in {8, 16}:
            result.warn(message + "; accepted only because --allow-legacy-hash was used")
        else:
            result.error(message)
        return

    if declared != result.computed_hash:
        result.error(
            f"metadata.cgs_hash mismatch: declared {declared}, computed {result.computed_hash}"
        )


def compute_cgs_hash(cgs: dict[str, Any]) -> str:
    stripped = copy.deepcopy(cgs)
    metadata = stripped.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("cgs_hash", None)
    canonical = canonical_json(normalise_floats(stripped)).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def normalise_floats(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: normalise_floats(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalise_floats(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def require_id(obj: dict[str, Any], context: str, result: ValidationResult) -> str:
    value = obj.get("id")
    if not isinstance(value, str) or not value.strip():
        result.error(f"{context} id must be a non-empty string")
        return ""
    return value


def check_array_field(
    obj: dict[str, Any],
    field_name: str,
    context: str,
    result: ValidationResult,
) -> list[Any]:
    value = obj.get(field_name)
    if not isinstance(value, list):
        result.error(f"{context}.{field_name} must be an array")
        return []
    return value


def objects(values: list[Any], context: str, result: ValidationResult) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if isinstance(value, dict):
            output.append(value)
        else:
            result.error(f"{context}[{index}] must be an object")
    return output


def emit_result(path: Path, result: ValidationResult, *, as_json: bool) -> None:
    payload = {
        "path": str(path),
        "valid": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "declared_hash": result.declared_hash,
        "computed_hash": result.computed_hash,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    status = "PASS" if result.ok else "FAIL"
    print(f"{status}: {path}")
    if result.declared_hash or result.computed_hash:
        print(f"declared_hash: {result.declared_hash}")
        print(f"computed_hash: {result.computed_hash}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Provider-free planning from registered gameplay package declarations.

Aliases are catalog data. This planner returns proposals, never changes CGS.
"""
from __future__ import annotations
import copy
import hashlib
import json
from .operation_registry import parse_typed_operation_batch, normalized_typed_operation_batch
from .composite_plan import build_composite_prompt_plan


def discover_packages(prompt, descriptors, cgs, mode_id):
    matches = [p for p in descriptors if prompt.strip().casefold() in {a.strip().casefold() for a in p["aliases"]}]
    if not matches:
        return None
    if len(matches) != 1:
        return {"kind": "clarification", "message": "Choose a gameplay package.", "package_ids": sorted(p["id"] for p in matches)}
    package = matches[0]
    mode = next((m for m in cgs.get("modes", []) if m["id"] == mode_id), {})
    objects = mode.get("world", {}).get("contract", {}).get("objects", [])
    compatible = {cap["id"]: sorted(obj["id"] for obj in objects if not cap.get("allowed_types", cap.get("allowed_kinds")) or obj.get("semantic_type", obj.get("kind")) in cap.get("allowed_types", cap.get("allowed_kinds", [])))
                  for cap in package["capability_declarations"] if cap["id"] in package["requirements"]["capability_ids"]}
    present = {cap for obj in objects for cap in obj.get("capabilities", [])}
    systems = {s["id"] for s in cgs.get("global_systems", []) + mode.get("systems", [])}
    required = set(package["requirements"]["component_type_ids"])
    return {"kind": "clarification", "schema": "xace.gameplay_requirements.v1",
        "message": "Select package targets or a package template, then review the complete proposal.",
        "requires_actors": bool(package["component_schemas"]),
        "package_id": package["id"], "package_hash": package["package_hash"], "mode_id": mode_id,
        "missing_capabilities": sorted(set(package["requirements"]["capability_ids"]) - present),
        "missing_systems": sorted(set(package["requirements"]["system_ids"]) - systems),
        "actor_dependencies": {a["id"]: sorted(required - {c["type_id"] for c in a.get("components", [])}) for a in mode.get("actors", [])},
        "compatible_objects": compatible,
        "templates": sorted(t["id"] for t in package["templates"]),
        "configurations": sorted(c["id"] for c in package["configurations"])}


def package_proposal(*, package, cgs, mode_id, actor_ids=(), capability_targets=(),
                     template_id="", configuration_id):
    operation = {"operation_id": "install_package", "kind": "install_gameplay_package",
        "explanation": "Install the selected package and its declared world requirements.",
        "package_id": package["id"], "package_hash": package["package_hash"], "mode_id": mode_id,
        "actor_ids": sorted(actor_ids), "capability_targets": sorted(copy.deepcopy(list(capability_targets)), key=lambda x: x["capability_id"]),
        "template_id": template_id, "configuration_id": configuration_id}
    identity = hashlib.sha256(json.dumps(operation, sort_keys=True).encode()).hexdigest()[:24]
    batch = parse_typed_operation_batch({"schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "package_" + identity, "prompt_id": "package_" + identity,
        "operations": [operation], "summary": "Install selected gameplay package"})
    normalized = normalized_typed_operation_batch(batch)
    return {"kind": "mutation", "turn_index": 0, "intent_category": "GameplayPackage", "confidence": 1.0,
        "mode_profile_warnings": [], "auto_committed": False,
        "diff_text": "Install the selected package, world requirements and configuration.",
        "transaction": {"operation_format": "typed_cgs_v1", "schema_delta_type": "structural",
        "required_recompile": True, "risk_level": "medium", "affected_systems": [s["id"] for s in package["systems"]],
        "typed_operation_batch": normalized, "operations": [],
        "mutation_summary": normalized["summary"], "confidence_score": 1.0,
        "composite_prompt_plan": build_composite_prompt_plan(batch, cgs).to_dict()}}

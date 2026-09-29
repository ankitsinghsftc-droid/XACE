"""Trusted, data-only gameplay authoring catalogs. No runtime code loading.

The host registers catalogs and its supported system contracts separately.
A prompt supplies only a pinned catalog identity and bounded selections.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from typing import Any


class CatalogError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _require(ok, message):
    if not ok:
        raise CatalogError(message)


def _index(items, key, label):
    _require(isinstance(items, list) and all(isinstance(x, dict) and key in x for x in items),
             f"{label} must be records with {key}")
    result = {x[key]: x for x in items}
    _require(len(result) == len(items), f"duplicate {label}")
    return result


class GameplayCatalog:
    """Immutable registration snapshot; returned descriptors are detached copies."""
    def __init__(self, packages=(), *, supported_systems=()):
        self._systems = copy.deepcopy(_index(list(supported_systems), "id", "host systems"))
        self._packages = {}
        for source in packages:
            package = copy.deepcopy(source)
            _require(package.get("schema") in {"xace.gameplay_authoring_package.v1", "xace.gameplay_authoring_package.v2"}, "unsupported catalog schema")
            v2 = package["schema"].endswith(".v2")
            _require(set(package) == ({"schema", "id", "version", "aliases", "component_schemas",
                "systems", "capability_declarations", "requirements", "templates", "configurations"} | ({"target_roles"} if v2 else set())),
                "unknown or missing catalog fields")
            _require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", package["id"]) is not None, "invalid package ID")
            _require(package["id"] not in self._packages, "duplicate package ID")
            declarations = _index(package["capability_declarations"], "id", "capabilities")
            for cap in declarations.values():
                role_key = "allowed_types" if v2 else "allowed_kinds"
                _require(set(cap) == {"id", role_key}, "invalid capability declaration")
                _require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)+\.v[1-9][0-9]*", cap["id"]) is not None,
                         "invalid namespaced capability")
                _require(cap["id"] not in {"input.timed.v1", "world.aabb.v1", "world.semantic_bindings.v1", "world.semantic_bindings.v3"}, "reserved capability")
                _require(isinstance(cap[role_key], list) and cap[role_key] == sorted(set(cap[role_key])), "invalid capability roles")
            req = package["requirements"]
            _require(set(req) == {"component_type_ids", "system_ids", "capability_ids"}, "invalid requirements")
            _require(set(req["capability_ids"]) <= set(declarations), "undeclared capability requirement")
            _index(package["component_schemas"], "type_id", "component schemas")
            _index(package["systems"], "id", "package systems")
            _index(package["templates"], "id", "templates")
            _index(package["configurations"], "id", "configurations")
            for schema in package["component_schemas"]:
                _require(type(schema["type_id"]) is int and schema["type_id"] >= 10000 and schema.get("source") == "gcl", "package components must be GCL")
            _require(package["aliases"] and all(isinstance(x, str) and x.strip() for x in package["aliases"]), "aliases must be nonempty strings")
            if v2:
                roles = _index(package["target_roles"], "id", "target roles")
                package_tids = {x["type_id"] for x in package["component_schemas"]}
                assigned = []
                for role in roles.values():
                    _require(set(role) == {"id", "component_type_ids", "requires_component_type_ids", "actor_types", "min_count"}, "invalid target role")
                    _require(type(role["min_count"]) is int and role["min_count"] >= 0, "invalid role count")
                    _require(set(role["component_type_ids"]) <= package_tids, "role references non-package component")
                    assigned.extend(role["component_type_ids"])
                _require(len(assigned) == len(set(assigned)) and set(assigned) == package_tids, "each package component needs exactly one target role")
            self._packages[package["id"]] = package

    def descriptors(self):
        return [dict(copy.deepcopy(p), package_hash=digest(p)) for _, p in sorted(self._packages.items())]

    def resolve(self, package_id, package_hash):
        package = self._packages.get(package_id)
        _require(package is not None, "unsupported gameplay package")
        _require(digest(package) == package_hash, "stale catalog identity; regenerate preview")
        return copy.deepcopy(package)

    def apply(self, current, operation):
        """Materialize on a copy; GDE/Factory/SGC still validate before activation."""
        package = self.resolve(operation["package_id"], operation["package_hash"])
        proposed = copy.deepcopy(current)
        modes = _index(proposed.get("modes", []), "id", "modes")
        _require(operation["mode_id"] in modes, "selected mode does not exist")
        mode = modes[operation["mode_id"]]
        templates = _index(package["templates"], "id", "templates")
        configurations = _index(package["configurations"], "id", "configurations")
        _require(operation["configuration_id"] in configurations, "unsupported configuration")
        template_systems = []
        actor_ids = operation["actor_ids"]
        if operation["template_id"]:
            _require(operation["template_id"] in templates, "unsupported template")
            _require(not actor_ids and not operation["capability_targets"], "template and explicit selections cannot be mixed")
            template = copy.deepcopy(templates[operation["template_id"]])
            _require(set(template) in ({"id", "actors", "world", "systems", "actor_ids"}, {"id", "actors", "world", "systems", "actor_ids", "policy"}), "invalid template fields")
            existing = _index(mode.get("actors", []), "id", "actors")
            _require(not set(existing) & set(_index(template["actors"], "id", "template actors")), "template actor ID collision")
            policy = template.get("policy", "empty_mode")
            _require(policy in {"empty_mode", "additive"}, "unknown template policy")
            if policy == "empty_mode":
                _require(not mode.get("actors") and not mode.get("world", {}).get("contract", {}).get("objects"), "template needs an empty mode")
                mode["actors"] = template["actors"]
                mode["world"] = template["world"]
            else:
                mode.setdefault("actors", []).extend(template["actors"])
                fragment = template["world"]
                _require(set(fragment) <= {"contract"}, "additive world templates contain contract fragments only")
                if "contract" in fragment:
                    contract = mode.get("world", {}).get("contract")
                    _require(contract is not None and contract.get("contract_version") == 3, "additive semantic fragments require world v3")
                    _require(set(fragment["contract"]) <= {"schemas", "objects", "capability_declarations", "geometry_profiles"}, "invalid additive contract fragment")
                    for key, records in fragment["contract"].items():
                        existing_records = _index(contract[key], "id", key)
                        for rid, record in _index(records, "id", key).items():
                            _require(rid not in existing_records or (key != "objects" and existing_records[rid] == record), "template declaration collision")
                            existing_records[rid] = record
                        contract[key] = [existing_records[k] for k in sorted(existing_records)]
            actor_ids = template["actor_ids"]
            template_systems = template["systems"]
        _require(actor_ids == sorted(set(actor_ids)), "select unique sorted actor IDs")
        if package["schema"].endswith(".v1") and package["component_schemas"]:
            _require(bool(actor_ids), "package requires actor targets")
        actors = _index(mode.get("actors", []), "id", "actors")
        _require(set(actor_ids) <= set(actors), "selected actor does not exist")
        contract = mode.get("world", {}).get("contract", {})
        needs_world = bool(package["capability_declarations"] or package["requirements"]["capability_ids"] or operation["capability_targets"])
        if needs_world:
            _require(contract.get("contract_version") in {2, 3}, "declared package requirements need a World Contract")
        role_key = "allowed_types" if contract.get("contract_version") == 3 else "allowed_kinds"
        object_key = "semantic_type" if contract.get("contract_version") == 3 else "kind"
        objects = _index(contract.get("objects", []), "id", "world objects")
        declarations = _index(contract.setdefault("capability_declarations", []), "id", "world capabilities")
        for cap in package["capability_declarations"]:
            _require(role_key in cap, "package capability contract version differs from world; migrate explicitly")
            _require(cap["id"] not in declarations or declarations[cap["id"]] == cap, "conflicting capability declaration")
            declarations[cap["id"]] = cap
        contract["capability_declarations"] = [declarations[k] for k in sorted(declarations)]
        targets = _index(operation["capability_targets"], "capability_id", "capability targets")
        allowed = {c["id"] for c in package["capability_declarations"]}
        for cap_id, target in sorted(targets.items()):
            _require(cap_id in allowed, "capability is not declared by package")
            _require(target["object_ids"] and target["object_ids"] == sorted(set(target["object_ids"])), "select unique sorted world object IDs")
            for object_id in target["object_ids"]:
                _require(object_id in objects, "selected world object does not exist")
                obj = objects[object_id]
                _require((not declarations[cap_id][role_key] or obj[object_key] in declarations[cap_id][role_key]), "selected object has incompatible role")
                obj["capabilities"] = sorted(set(obj.get("capabilities", [])) | {cap_id})
        for cap_id in package["requirements"]["capability_ids"]:
            _require(any(cap_id in obj.get("capabilities", []) and (not declarations[cap_id][role_key] or obj[object_key] in declarations[cap_id][role_key]) for obj in objects.values()),
                     f"missing world capability: {cap_id}; select compatible objects or a catalog template")
        schemas = _index(proposed.setdefault("component_schemas", []), "type_id", "component schemas")
        for schema in package["component_schemas"]:
            _require(schema["type_id"] not in schemas or schemas[schema["type_id"]] == schema, "component schema ID collision")
            _require(not any(s["name"] == schema["name"] and s["type_id"] != schema["type_id"] for s in schemas.values()), "component schema name collision")
            schemas[schema["type_id"]] = schema
        proposed["component_schemas"] = [schemas[k] for k in sorted(schemas)]
        config = configurations[operation["configuration_id"]]
        _require(set(config) == {"id", "defaults"}, "invalid configuration fields")
        package_ids = {s["type_id"] for s in package["component_schemas"]}
        _require(set(config["defaults"]) <= {str(i) for i in package_ids}, "configuration references non-package component")
        assignments = {aid: package["component_schemas"] for aid in actor_ids}
        if package["schema"].endswith(".v2"):
            assignments = {aid: [] for aid in actor_ids}
            for role in package["target_roles"]:
                matching = [aid for aid in actor_ids if (not role["actor_types"] or (actors[aid].get("actor_type", {}).get("Custom") if isinstance(actors[aid].get("actor_type"), dict) else actors[aid].get("actor_type")) in role["actor_types"])
                    and set(role["requires_component_type_ids"]) <= {c["type_id"] for c in actors[aid].get("components", [])}]
                _require(len(matching) >= role["min_count"], "missing target role: " + role["id"])
                for aid in matching:
                    assignments[aid].extend(s for s in package["component_schemas"] if s["type_id"] in role["component_type_ids"])
            _require(all(assignments.values()), "selected actor matches no package role")
        for actor_id in actor_ids:
            actor = actors[actor_id]
            components = _index(actor.get("components", []), "type_id", "actor components")
            missing = sorted(set(package["requirements"]["component_type_ids"]) - set(components))
            _require(not missing, f"actor {actor_id} missing component dependencies: {missing}")
            _require(not package_ids & set(components), "package component already attached")
            for schema in assignments[actor_id]:
                defaults = copy.deepcopy(schema["defaults"])
                updates = config["defaults"].get(str(schema["type_id"]), {})
                _require(set(updates) <= set(defaults), "unknown configuration field")
                for name, value in updates.items():
                    _require(type(value) is type(defaults[name]), "configuration type mismatch")
                defaults.update(updates)
                actor.setdefault("components", []).append({"type_id": schema["type_id"], "name": schema["name"], "defaults": defaults})
        existing_systems = list(proposed.get("global_systems", [])) + list(mode.get("systems", []))
        system_map = _index(existing_systems, "id", "systems")
        for system in template_systems + package["systems"]:
            host = self._systems.get(system["id"])
            _require(host == system, f"unsupported runtime system contract: {system['id']}")
            _require(system["id"] not in system_map, "system ID collision")
            system_map[system["id"]] = system
            mode.setdefault("systems", []).append(copy.deepcopy(system))
        for system in list(system_map.values()):
            _require(set(system.get("depends_on", [])) <= set(system_map), f"missing system dependency for {system['id']}")
        _require(set(package["requirements"]["system_ids"]) <= set(system_map), "missing package system dependencies")
        return proposed

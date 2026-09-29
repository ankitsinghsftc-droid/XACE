"""Offline World Contract compiler proof and golden-fixture generator (no runtime)."""
from __future__ import annotations
import argparse
import copy
import importlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "packages"))
from tools.cgs_schema_validate import compute_cgs_hash
factory = importlib.import_module("schema-factory.src.portable_compilation")
SCALE = 1_000_000
FIXTURES = ROOT / "packages/core/tests/fixtures/world_contract_v2"

def arena():
    actors, objects = [], []
    for index, (name, kind, caps) in enumerate([
        ("floor", "static_box", ["world.solid.v1", "world.platform.v1"]),
        ("wall", "static_box", ["world.solid.v1", "world.wall_runnable.v1"]),
        ("lift", "kinematic_box", ["world.solid.v1"]),
        ("zone", "trigger", ["world.trigger.v1", "world.safe_zone.v1"]),
        ("spawn", "spawn", ["world.spawn.v1"]),
        ("switch", "anchor", ["world.interactable.v1"]),
    ]):
        components = [
            {"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {
                "position": {"x": index * 4 * SCALE, "y": 0, "z": 0},
                "rotation": {"x": 0, "y": 0, "z": 0, "w": SCALE},
                "scale": {"x": SCALE, "y": SCALE, "z": SCALE}, "parent_entity_id": 0}},
            {"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {"entity_name": name}},
        ]
        if kind in {"static_box", "kinematic_box", "trigger"}:
            components.append({"type_id": 4, "name": "COMP_COLLIDER_V1", "defaults": {
                "shape": "BOX", "size": {"x": 2*SCALE, "y": 2*SCALE, "z": 2*SCALE},
                "offset": {"x": 0, "y": 0, "z": 0}, "is_trigger": kind == "trigger"}})
        actors.append({"id": "actor_" + name, "actor_type": "WORLD_OBJECT", "control_type": "NONE", "spawn_count": 1, "components": components})
        objects.append({"id": name, "actor_id": "actor_" + name, "kind": kind, "capabilities": caps})
    objects[-1]["target_id"] = "lift"
    objects[1]["asset_reference"] = {"id": "wall_mesh_v1", "asset_type": "MESH", "status": "PLACEHOLDER"}
    cgs = {"metadata": {"name": "XP003Arena", "version": "0.1.0", "schema_version": "0.1.0", "cgs_hash": ""},
        "global_systems": [{"id": "EngineInputSystem", "phase": "Input", "reads": [], "writes": [6], "depends_on": [], "deterministic": True}],
        "assets": [{"id": "wall_mesh_v1", "asset_type": "MESH", "status": "PLACEHOLDER"}],
        "modes": [{"id": "mode_arena", "schema_version": "0.1.0", "is_default": True, "actors": actors, "systems": [], "rules": [], "ui": {},
            "world": {"size": {"width": 100*SCALE, "height": 100*SCALE, "depth": 100*SCALE},
                "gravity": {"x": 0, "y": -9810000, "z": 0}, "day_length_ticks": 3600,
                "contract": {"contract_version": 2, "id": "arena_v1", "version": "1.0.0",
                             "numeric_profile": "fixed64_y_up_neg_z_v1", "objects": objects}}}]}
    role_sets = {}
    for obj in objects:
        for cap in obj["capabilities"]:
            role_sets.setdefault(cap, set()).add(obj["kind"])
    cgs["modes"][0]["world"]["contract"]["capability_declarations"] = [
        {"id": cap, "allowed_kinds": sorted(kinds)} for cap, kinds in sorted(role_sets.items())]
    cgs["metadata"]["cgs_hash"] = compute_cgs_hash(cgs)
    return cgs

def run(output: Path, write_fixtures: bool = False):
    cgs = arena()
    package = factory.compile_portable_cgs(cgs)
    world = package.world_contract
    assert world is not None
    shuffled = copy.deepcopy(cgs)
    shuffled["modes"][0]["actors"].reverse()
    shuffled["modes"][0]["world"]["contract"]["objects"].reverse()
    for actor in shuffled["modes"][0]["actors"]: actor["components"].reverse()
    shuffled["metadata"]["cgs_hash"] = compute_cgs_hash(shuffled)
    other = factory.compile_portable_cgs(shuffled).world_contract
    assert other.content_bytes == world.content_bytes
    assert other.manifest()["world"]["compiled_from_cgs_hash"] != world.manifest()["world"]["compiled_from_cgs_hash"]
    if not write_fixtures:
        assert (FIXTURES / "world.canonical.json").read_bytes() == world.content_bytes
        assert (FIXTURES / "manifest.json").read_bytes() == world.manifest_bytes
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "xace.xp003.world_proof.v1", "ok": True,
              "objects": len(world.content()["objects"]), "identity": world.manifest(),
              "reordered_source_identical_world_bytes": True,
              "scope": "offline real Factory compilation; Rust reader tested separately; no geometry execution, native engine or live session"}
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if write_fixtures:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / "source.cgs.json").write_text(json.dumps(cgs, indent=2) + "\n", encoding="utf-8")
        (FIXTURES / "world.canonical.json").write_bytes(world.content_bytes)
        (FIXTURES / "manifest.json").write_bytes(world.manifest_bytes)
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/xp003-proof")
    parser.add_argument("--write-fixtures", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.write_fixtures), indent=2))

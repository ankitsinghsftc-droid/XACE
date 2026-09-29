"""Offline XP-002 proof through real Builder, GDE, Factory, SGC and runtime.

Writes only a disposable project under the requested output directory. Does not
invoke a provider, native editor or network session, and does not edit a user's CGS.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "builder-workspace" / "server"))
from session_manager import SessionManager, _GDEOrchestrator
from cgs_persistence import CGSPersistence
from dcl.gameplay_primitives import build_primitive_cgs, committed_cgs_hash, PLATFORMER_KINEMATIC_MOVEMENT_V1


def run(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    project = output / "project"
    project.mkdir(exist_ok=True)
    cgs = build_primitive_cgs(PLATFORMER_KINEMATIC_MOVEMENT_V1)
    systems = cgs["global_systems"] + [s for m in cgs["modes"] for s in m["systems"]]
    cgs["global_systems"].append({"id": "EngineInputSystem", "phase": "Input", "reads": [], "writes": [6], "depends_on": [], "deterministic": True})
    for system in systems:
        if system["phase"] == "Input": system["depends_on"].append("EngineInputSystem")
    cgs["metadata"]["cgs_hash"] = committed_cgs_hash(cgs)
    persist = CGSPersistence(project)
    persist.save(cgs)
    manager = object.__new__(SessionManager)
    manager._sgc_bin = str(ROOT / "target" / "debug" / ("xace-system-graph-compiler.exe" if sys.platform == "win32" else "xace-system-graph-compiler"))
    manager._sgc_args = []
    assert _GDEOrchestrator is not None
    gde = _GDEOrchestrator(mode="COLLABORATIVE", session_id="xp002-proof")
    manager._sessions = {"xp002-proof": SimpleNamespace(gde=gde)}
    mode = cgs["modes"][0]
    actor = mode["actors"][0]
    path = f"modes.{mode['id']}.actors.{actor['id']}.components.5.defaults.max_linear_speed"
    # Model the already-approved typed operation handoff; no provider is involved.
    result = manager.apply_via_gde("xp002-proof", {
        "parent_cgs_hash": cgs["metadata"]["cgs_hash"],
        "operations": [{"op": "SET", "path": path, "value": 7000000, "type_hint": "int"}],
        "mutation_summary": "XP-002 disposable authority proof",
    }, cgs)
    if not result.success: raise RuntimeError(result.error)
    compiled = manager.compile_sgc_plan(result.new_cgs)
    if not compiled.ok: raise RuntimeError(compiled.error)
    persist.save(result.new_cgs)
    plan = persist.save_execution_plan(result.new_hash, compiled.plan_json, cgs=result.new_cgs)
    persist.save_sgc_proof_bundle(result.new_cgs, plan, validation=compiled.validation)
    before_disk = hashlib.sha256((project / "game.cgs.json").read_bytes()).hexdigest()
    before_artifacts = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob("*") if p.is_file()}
    invalid = copy.deepcopy(result.new_cgs)
    invalid["modes"][0]["world"] = "native-engine-world"
    rejected = manager.compile_sgc_plan(invalid)
    assert rejected.failed and rejected.error["code"] == "SCHEMA_FACTORY_VALIDATION_FAILED"
    rejected_edit = manager.apply_via_gde("xp002-proof", {
        "parent_cgs_hash": result.new_hash,
        "operations": [{"op": "SET", "path": path, "value": "invalid-speed", "type_hint": "str"}],
        "mutation_summary": "XP-002 invalid typed value",
    }, result.new_cgs)
    assert not rejected_edit.success, "invalid value edit was committed"
    assert gde.current_hash == result.new_hash, "GDE candidate was not restored"
    assert gde.current_cgs == result.new_cgs, "GDE state differs after rejection"
    after_artifacts = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob("*") if p.is_file()}
    assert before_artifacts == after_artifacts
    runtime = ROOT / "target" / "debug" / ("xace_runtime.exe" if sys.platform == "win32" else "xace_runtime")
    reports = []
    for label in ("first", "second"):
        report_path = output / f"{label}.schedule.json"
        command = [str(runtime), "--cgs", str(project / "game.cgs.json"), "--require-sgc-plan", "--live-session", "--no-wait", "--no-control", "--ticks", "3", "--quiet", "--schedule-snapshot-out", str(report_path)]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=30)
        (output / f"{label}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (output / f"{label}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        if proc.returncode: raise RuntimeError(proc.stderr)
        reports.append(json.loads(report_path.read_text(encoding="utf-8")))
    assert reports[0] == reports[1], "repeated runtime schedules/hashes differ"
    summary = {"schema": "xace.xp002.authority_proof.v1", "ok": True,
        "cgs_hash": result.new_hash, "plan_hash": json.loads(plan)["plan_hash"],
        "disk_sha256_before_rejected_compile": before_disk,
        "disk_sha256_after_rejected_compile": hashlib.sha256((project / "game.cgs.json").read_bytes()).hexdigest(),
        "all_project_artifacts_unchanged_on_rejection": before_artifacts == after_artifacts,
        "repeated_runtime_reports_identical": True, "ticks": 3,
        "rejected_gde_edit_restored_previous_state": True, "rejected_edit_reason": rejected_edit.error,
        "rejected_code": rejected.error["code"], "runtime_binary_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        "sgc_binary_sha256": hashlib.sha256(Path(manager._sgc_bin).read_bytes()).hexdigest(),
        "scope": "real offline compiler/runtime chain; control/input/preview injection invariants tested separately in Rust and Builder regressions; not live networking"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "xp002-proof")
    print(json.dumps(run(parser.parse_args().output.resolve()), indent=2))

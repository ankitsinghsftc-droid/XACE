"""No-provider Builder approval -> GDE -> Factory/SGC -> reference host artifacts."""
from __future__ import annotations
import asyncio
import importlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages"), str(ROOT / "packages/builder-workspace/server"), str(ROOT / "packages/project-system")]
from session_manager import SessionManager, BuilderSession, _GDEOrchestrator
from src.domain_dsl.typed_operations.gameplay_catalog import GameplayCatalog
from cgs_persistence import CGSPersistence
from ws_message_router import WSMessageRouter
from tools.cgs_schema_validate import compute_cgs_hash
from tools.xp005_reference_proof import fixture


async def run(output):
    output.mkdir(parents=True, exist_ok=True)
    previous_settings = os.environ.get("XACE_PROVIDER_SETTINGS_PATH")
    os.environ["XACE_PROVIDER_SETTINGS_PATH"] = str(output / "provider-settings.json")
    package = json.loads((ROOT / "examples/reference-mechanic/authoring.json").read_text(encoding="utf-8"))
    catalog = GameplayCatalog([package], supported_systems=package["systems"] + package["templates"][0]["systems"])
    manager = SessionManager(sgc_bin_path=str(ROOT / "target/debug/xace-system-graph-compiler.exe"), gameplay_catalog=catalog)
    router = WSMessageRouter(manager)
    evidence = {}
    try:
        for policy, configuration in [("disabled", "default"), ("reversal_shockwave", "third_attempt")]:
            root = output if policy == "disabled" else output / policy
            root.mkdir(parents=True, exist_ok=True)
            cgs = fixture()
            cgs["component_schemas"] = []
            cgs["global_systems"] = []
            mode = cgs["modes"][0]
            mode["actors"] = []
            mode["systems"] = []
            mode["world"]["contract"]["objects"] = []
            mode["world"]["contract"]["capability_declarations"] = []
            cgs["metadata"]["cgs_hash"] = compute_cgs_hash(cgs)
            persist = CGSPersistence(root)
            persist.save(cgs)
            gde = _GDEOrchestrator(gameplay_catalog=catalog)
            manager._sessions[policy] = BuilderSession(session_id=policy, pipeline=None, gde=gde, project_path=str(root))
            sent = []
            async def send(message):
                sent.append(message)
            await router.route(policy, {"type": "pil_process", "prompt": "Add wall running", "cgs_hash": cgs["metadata"]["cgs_hash"]}, send, persist, cgs)
            result = sent[-1]["result"]
            assert result["kind"] == "clarification", result
            for answer in ["Create reference.test_arena.v1", configuration]:
                await router.route(policy, {"type": "pil_answer", "clarification_id": result["clarification_session_id"], "answer": answer}, send, persist, cgs)
                assert "result" in sent[-1], sent[-1]
                result = sent[-1]["result"]
            assert result["kind"] == "mutation", result
            assert persist.load() == cgs
            preview = result["preview"]
            assert any(row["path"].endswith("world") for row in preview["cgs_diff"]["operations"])
            # Approval failures must not persist any part of the package.
            before_rejection = json.dumps(persist.load(), sort_keys=True)
            await router.route(policy, {"type": "pil_apply"}, send, persist, cgs)
            assert not [m for m in sent if m.get("type") == "cgs_update"]
            assert json.dumps(persist.load(), sort_keys=True) == before_rejection
            await router.route(policy, {"type": "pil_apply", "approval": {"preview_id": preview["preview_id"], "approval_token": "wrong"}}, send, persist, cgs)
            assert not [m for m in sent if m.get("type") == "cgs_update"]
            assert json.dumps(persist.load(), sort_keys=True) == before_rejection
            await router.route(policy, {"type": "pil_apply", "approval": {"preview_id": preview["preview_id"], "approval_token": preview["approval_token"]}}, send, persist, cgs)
            updates = [m for m in sent if m.get("type") == "cgs_update"]
            assert updates, sent[-2:]
            assert persist.load() == cgs
            compiled = importlib.import_module("schema-factory.src.portable_compilation").compile_portable_cgs(cgs)
            plan = manager.compile_sgc_plan(cgs)
            assert plan.ok, plan
            (root / "game.cgs.json").write_text(json.dumps(cgs, indent=2) + "\n", encoding="utf-8")
            (root / "execution_plan.json").write_text(plan.plan_json, encoding="utf-8")
            (root / "world.json").write_bytes(compiled.world_contract.content_bytes)
            (root / "world.manifest.json").write_bytes(compiled.world_contract.manifest_bytes)
            evidence[policy] = {"cgs_hash": compiled.cgs_hash, "approval": updates[-1]["approval"], "world_hash": compiled.world_contract.manifest()["world"]["artifact"]["content_hash"]}
    finally:
        manager._executor.shutdown()
        if previous_settings is None:
            os.environ.pop("XACE_PROVIDER_SETTINGS_PATH", None)
        else:
            os.environ["XACE_PROVIDER_SETTINGS_PATH"] = previous_settings
    return {"schema": "xace.xp006.authoring_proof.v1", "ok": True, "variants": evidence}


if __name__ == "__main__":
    result = asyncio.run(run(ROOT / "tmp/xp006-authored"))
    (ROOT / "tmp/xp006-proof.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))

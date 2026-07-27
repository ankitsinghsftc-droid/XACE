"""
Editor-free prompt pipeline contract/scenario smoke.

Proves the launch path for certified supported prompt scenarios:

    deterministic simple-edit or PIL contract result -> Builder pil_apply
    -> GDE -> SGC hook -> CGS save -> runtime loads the resulting CGS

This is not an AI capability proof or LLM quality benchmark. It is a
contract/scenario smoke that checks supported prompt categories do not bypass
validation or fake success.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
PROMPT_FIXTURE_DIR = SERVER_DIR / "tests" / "fixtures"
PROJECT_SYSTEM_DIR = REPO_ROOT / "packages" / "project-system"
DEFAULT_RUNTIME_BIN = (
    REPO_ROOT
    / "target-codex-certify"
    / "debug"
    / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
)
DEFAULT_SGC_BIN = (
    REPO_ROOT
    / "target-codex-certify"
    / "debug"
    / ("xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler")
)

for path in (PROMPT_FIXTURE_DIR, SERVER_DIR, PROJECT_SYSTEM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cgs_persistence import CGSPersistence  # noqa: E402
from prompt_pipeline_contract import (  # noqa: E402
    DeterministicPromptPipeline,
    all_prompt_pipeline_scenarios,
    blocked_prompt_pipeline_scenario,
    supported_prompt_pipeline_scenarios,
)
from project_templates import make_template  # noqa: E402
from credential_store import BACKEND_ENV, UNSAFE_FALLBACK_ENV, UNSAFE_STORE_PATH_ENV  # noqa: E402
from provider_settings import ProviderSettingsStore, _fingerprint  # noqa: E402
from session_manager import SessionManager  # noqa: E402
from ws_message_router import WSMessageRouter  # noqa: E402


PROMPT_CONTRACT_PROVIDER = "openai"
PROMPT_CONTRACT_MODEL = "xace-prompt-contract-scenario-model"
PROMPT_CONTRACT_FAKE_KEY = "sk-" + "xace-prompt-contract-scenario"


async def run_prompt_pipeline(project_root: Path, provider_settings_path: Path, sgc_bin: Path) -> dict[str, Any]:
    _require(sgc_bin.exists(), f"SGC binary not found: {sgc_bin}")
    previous_env = _prepare_ready_prompt_provider(provider_settings_path)
    try:
        persist = _create_project(project_root)
        cgs_state = persist.load()
        sent: list[dict[str, Any]] = []

        async def send_fn(message: dict[str, Any]) -> None:
            sent.append(message)

        sm = SessionManager(
            sgc_bin_path=str(sgc_bin),
            sgc_args=[],
        )
        router = WSMessageRouter(sm)
        session = await sm.get_or_create("prompt-contract-scenario-smoke", send_fn, project_path=str(project_root))
        session.pipeline = DeterministicPromptPipeline(all_prompt_pipeline_scenarios())

        applied: list[dict[str, Any]] = []
        for scenario in supported_prompt_pipeline_scenarios():
            sent.clear()
            await _route_prompt(router, persist, cgs_state, sent, scenario.prompt)
            pil_result = _last(sent, "pil_result")["result"]
            _require(pil_result["kind"] == "mutation", f"{scenario.scenario_id}: PIL did not return mutation")
            _require(session.pending_txn is not None, f"{scenario.scenario_id}: no pending transaction")
            _require(len(session.pending_txn["operations"]) > 0, f"{scenario.scenario_id}: empty transaction")

            await _route_apply(router, persist, cgs_state, sent)
            update = _last(sent, "cgs_update")
            _require(update.get("gde_used") is True, f"{scenario.scenario_id}: GDE was not used")
            approval = update.get("approval") or {}
            _require(
                approval.get("approved") is True,
                f"{scenario.scenario_id}: prompt preview approval was not recorded",
            )
            _require(
                approval.get("test_mode_override") is not True,
                f"{scenario.scenario_id}: prompt smoke used test-mode approval override",
            )
            if scenario.expects_execution_plan:
                _require(
                    update.get("execution_plan_available") is True,
                    f"{scenario.scenario_id}: SGC execution plan was not produced",
                )
                _require(
                    persist.has_execution_plan(update["hash"]),
                    f"{scenario.scenario_id}: execution plan was not persisted",
                )
                validation = update.get("sgc_validation") or {}
                _require(
                    validation.get("ok") is True,
                    f"{scenario.scenario_id}: SGC plan validation did not pass",
                )
                _assert_real_sgc_proof_bundle(project_root, update["hash"])
            _assert_expected_state(cgs_state, scenario)
            applied.append({
                "scenario_id": scenario.scenario_id,
                "category": scenario.category,
                "hash": update["hash"],
                "gde_used": update.get("gde_used") is True,
                "execution_plan_available": update.get("execution_plan_available") is True,
            })

        blocked = blocked_prompt_pipeline_scenario()
        sent.clear()
        await _route_prompt(router, persist, cgs_state, sent, blocked.prompt)
        blocked_result = _last(sent, "pil_result")["result"]
        _require(blocked_result["kind"] == "blocked", "unsupported prompt was not blocked")
        _require(session.pending_txn is None, "blocked prompt left a pending transaction")
        await _route_apply(router, persist, cgs_state, sent)
        no_pending = _last(sent, "server_error")
        _require(no_pending.get("code") == "NO_PENDING_TXN", "blocked prompt was still applyable")

        return {
            "project": str(project_root),
            "provider_settings_path": str(provider_settings_path),
            "sgc_bin": str(sgc_bin),
            "final_cgs": str(project_root / "game.cgs.json"),
            "final_hash": cgs_state["metadata"]["cgs_hash"],
            "proof_scope": "contract/scenario smoke with real SGC binary",
            "sgc_scope": "real SGC binary",
            "applied": applied,
            "blocked_prompt": blocked.scenario_id,
            "snapshot_count": len(persist.list_snapshots()),
        }
    finally:
        _restore_provider_settings_env(previous_env)


def run_runtime(runtime_bin: Path, cgs_path: Path, *, require_sgc_plan: bool = False) -> dict[str, Any]:
    _require(runtime_bin.exists(), f"runtime binary not found: {runtime_bin}")
    command = [
        str(runtime_bin),
        "--cgs",
        str(cgs_path),
        "--no-wait",
        "--no-control",
        "--ticks",
        "2",
        "--quiet",
    ]
    if require_sgc_plan:
        command.insert(3, "--require-sgc-plan")
    else:
        command.insert(3, "--derive-cgs-plan")
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = completed.stdout + completed.stderr
    compatibility_proof = ""
    compatibility_status = "loaded"
    if completed.returncode != 0 and not require_sgc_plan:
        _require(
            "CGS-derived runtime compatibility failed before tick zero" in output,
            "runtime failed to load prompt-mutated CGS:\n" + output[-4000:],
        )
        cgs = json.loads(cgs_path.read_text(encoding="utf-8"))
        cgs_hash = str(cgs.get("metadata", {}).get("cgs_hash") or "")
        proof_path = (
            cgs_path.parent
            / ".xace"
            / "proof"
            / "runtime-compatibility"
            / f"{cgs_hash}.json"
        )
        _require(proof_path.exists(), f"runtime compatibility proof missing: {proof_path}")
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        _require(proof.get("ok") is False, "runtime compatibility proof did not record failure")
        _require(
            proof.get("unsupported_systems"),
            "runtime compatibility proof did not record unsupported systems",
        )
        compatibility_proof = str(proof_path)
        compatibility_status = "unsupported_systems_blocked"
    else:
        _require(
            completed.returncode == 0,
            "runtime failed to load prompt-mutated CGS:\n" + output[-4000:],
        )
    return {
        "runtime_bin": str(runtime_bin),
        "require_sgc_plan": require_sgc_plan,
        "derive_cgs_plan": not require_sgc_plan,
        "compatibility_status": compatibility_status,
        "compatibility_proof": compatibility_proof,
        "returncode": completed.returncode,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Builder prompt pipeline contract/scenario smoke.")
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--project-dir", default="")
    parser.add_argument("--provider-settings-path", default="")
    parser.add_argument("--keep-project", action="store_true")
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument(
        "--require-runtime-sgc-plan",
        action="store_true",
        help=(
            "Launch the final prompt-mutated CGS with xace_runtime --require-sgc-plan. "
            "Default runtime verification uses CGS-derived compatibility loading, which rejects "
            "unsupported declared systems until generated-system runtime registry coverage is complete."
        ),
    )
    args = parser.parse_args(argv)
    sgc_bin = Path(args.sgc_bin).resolve()

    provider_cleanup = None
    if args.provider_settings_path:
        provider_settings_path = Path(args.provider_settings_path).resolve()
    else:
        provider_cleanup = tempfile.TemporaryDirectory(prefix="xace-prompt-provider-")
        provider_settings_path = Path(provider_cleanup.name) / "provider_settings.json"

    if args.project_dir:
        project_root = Path(args.project_dir).resolve()
        project_root.mkdir(parents=True, exist_ok=True)
        summary = asyncio.run(run_prompt_pipeline(project_root, provider_settings_path, sgc_bin))
        cleanup = None
    else:
        tmp = tempfile.TemporaryDirectory(prefix="xace-prompt-pipeline-")
        cleanup = tmp
        project_root = Path(tmp.name)
        summary = asyncio.run(run_prompt_pipeline(project_root, provider_settings_path, sgc_bin))

    if not args.skip_runtime:
        summary["runtime"] = run_runtime(
            Path(args.runtime_bin).resolve(),
            Path(summary["final_cgs"]),
            require_sgc_plan=args.require_runtime_sgc_plan,
        )

    print(json.dumps(summary, indent=2, sort_keys=True))
    print("prompt pipeline contract/scenario smoke PASSED")

    if cleanup is not None and not args.keep_project:
        cleanup.cleanup()
    if provider_cleanup is not None:
        provider_cleanup.cleanup()
    return 0


async def _route_prompt(
    router: WSMessageRouter,
    persist: CGSPersistence,
    cgs_state: dict[str, Any],
    sent: list[dict[str, Any]],
    prompt: str,
) -> None:
    async def send_fn(message: dict[str, Any]) -> None:
        sent.append(message)

    await router.route(
        "prompt-contract-scenario-smoke",
        {
            "type": "pil_process",
            "prompt": prompt,
            "cgs_hash": cgs_state["metadata"]["cgs_hash"],
            "mode": "COLLABORATIVE",
        },
        send_fn,
        persist,
        cgs_state,
    )


async def _route_apply(
    router: WSMessageRouter,
    persist: CGSPersistence,
    cgs_state: dict[str, Any],
    sent: list[dict[str, Any]],
) -> None:
    async def send_fn(message: dict[str, Any]) -> None:
        sent.append(message)

    message: dict[str, Any] = {"type": "pil_apply"}
    approval = _approval_from_last_preview(sent)
    if approval is not None:
        message["approval"] = approval
    await router.route("prompt-contract-scenario-smoke", message, send_fn, persist, cgs_state)


def _create_project(project_root: Path) -> CGSPersistence:
    project_root.mkdir(parents=True, exist_ok=True)
    cgs = make_template("blank_3d", "Prompt Pipeline Contract Scenario Smoke")
    persist = CGSPersistence(project_root)
    persist.save(cgs)
    return persist


def _assert_expected_state(cgs: dict[str, Any], scenario) -> None:
    if scenario.expected_path:
        actual = _resolve_cgs_path(cgs, scenario.expected_path)
        _require(actual == scenario.expected_value, f"{scenario.scenario_id}: expected {actual!r}")
    if scenario.expected_actor_id == "actor_player":
        _require(_component(cgs, "actor_player", 201) is not None, "player inventory component missing")
    elif scenario.expected_actor_id:
        _require(_actor(cgs, scenario.expected_actor_id) is not None, f"{scenario.expected_actor_id} missing")


def _resolve_cgs_path(cgs: dict[str, Any], path: str) -> Any:
    current: Any = cgs
    previous = ""
    for segment in path.split("."):
        if isinstance(current, list):
            if previous == "components":
                current = next(item for item in current if str(item.get("type_id")) == segment)
            else:
                current = next(item for item in current if str(item.get("id")) == segment)
        else:
            current = current[segment]
        previous = segment
    return current


def _actor(cgs: dict[str, Any], actor_id: str) -> dict[str, Any] | None:
    for mode in cgs.get("modes", []):
        for actor in mode.get("actors", []):
            if actor.get("id") == actor_id:
                return actor
    return None


def _component(cgs: dict[str, Any], actor_id: str, type_id: int) -> dict[str, Any] | None:
    actor = _actor(cgs, actor_id)
    if actor is None:
        return None
    for component in actor.get("components", []):
        if component.get("type_id") == type_id:
            return component
    return None


def _assert_real_sgc_proof_bundle(project_root: Path, cgs_hash: str) -> None:
    persisted_plan_path = project_root / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json"
    proof_dir = project_root / ".xace" / "proof" / "sgc" / cgs_hash
    input_path = proof_dir / "input.json"
    plan_path = proof_dir / "plan.json"
    metadata_path = proof_dir / "metadata.json"
    _require(persisted_plan_path.exists(), f"missing persisted SGC plan: {persisted_plan_path}")
    _require(input_path.exists(), f"missing SGC proof input: {input_path}")
    _require(plan_path.exists(), f"missing SGC proof plan: {plan_path}")
    _require(metadata_path.exists(), f"missing SGC proof metadata: {metadata_path}")

    persisted_text = persisted_plan_path.read_text(encoding="utf-8")
    persisted_plan = json.loads(persisted_text)
    proof_input = json.loads(input_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _require(
        persisted_text == json.dumps(persisted_plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "persisted SGC plan is not canonical JSON",
    )
    _require(plan == persisted_plan, "SGC proof plan does not match persisted canonical plan")
    _require(proof_input.get("schema") == "xace.sgc.cli.input.v1", "SGC proof input schema mismatch")
    _require(proof_input.get("cgs_hash") == cgs_hash, "SGC proof input hash mismatch")
    _require(persisted_plan.get("compiled_from_cgs_hash") == cgs_hash, "SGC plan was not compiled from the current CGS hash")
    _require(persisted_plan.get("adapter_protocol_version") == 1, "persisted SGC plan adapter protocol mismatch")
    _require(persisted_plan.get("migration_status") == "current", "persisted SGC plan migration status is not current")
    _require(isinstance(persisted_plan.get("plan_hash"), str) and len(persisted_plan["plan_hash"]) == 64, "SGC plan hash missing")
    _require(
        persisted_plan.get("component_access_sets", {}).get("schema") == "xace.sgc.component_access_sets.v1",
        "persisted SGC plan component access sets missing",
    )
    _require(
        persisted_plan.get("system_metadata", {}).get("schema") == "xace.sgc.system_metadata.v1",
        "persisted SGC plan system metadata missing",
    )
    _require(
        persisted_plan.get("proof_bundle", {}).get("path") == f".xace/proof/sgc/{cgs_hash}",
        "persisted SGC plan proof bundle reference mismatch",
    )
    _require(metadata.get("schema") == "xace.sgc.proof.v1", "SGC proof metadata schema mismatch")
    _require(metadata.get("cgs_hash") == cgs_hash, "SGC proof metadata hash mismatch")
    validation = metadata.get("validation") if isinstance(metadata.get("validation"), dict) else {}
    _require(validation.get("ok") is True, "SGC proof validation did not pass")
    _require(validation.get("load_ready") is True, "SGC proof is not load-ready")


def _prepare_ready_prompt_provider(settings_path: Path) -> str | None:
    previous_env = os.environ.get("XACE_PROVIDER_SETTINGS_PATH")
    previous_backend_env = os.environ.get(BACKEND_ENV)
    previous_unsafe_env = os.environ.get(UNSAFE_FALLBACK_ENV)
    previous_unsafe_path_env = os.environ.get(UNSAFE_STORE_PATH_ENV)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        settings_path.unlink()
    os.environ["XACE_PROVIDER_SETTINGS_PATH"] = str(settings_path)
    os.environ[BACKEND_ENV] = "unsafe-file"
    os.environ[UNSAFE_FALLBACK_ENV] = "1"
    os.environ[UNSAFE_STORE_PATH_ENV] = str(settings_path.with_suffix(".unsafe_credentials.json"))
    store = ProviderSettingsStore(settings_path)
    store.configure(provider=PROMPT_CONTRACT_PROVIDER, model=PROMPT_CONTRACT_MODEL, api_key=PROMPT_CONTRACT_FAKE_KEY)
    store._record_test(PROMPT_CONTRACT_PROVIDER, {
        "ok": True,
        "provider": PROMPT_CONTRACT_PROVIDER,
        "model": PROMPT_CONTRACT_MODEL,
        "base_url": "https://api.openai.com/v1",
        "key_fingerprint": _fingerprint(PROMPT_CONTRACT_FAKE_KEY),
        "checks": {
            "key_present": True,
            "key_valid": True,
            "model_reachable": True,
            "test_call": True,
        },
        "message": "OpenAI responded with xace-prompt-contract-scenario-model.",
        "latency_ms": 1,
    })
    _require(store.active_readiness().get("ok"), "prompt contract/scenario provider readiness proof was not accepted")
    return json.dumps({
        "provider": previous_env,
        "backend": previous_backend_env,
        "unsafe": previous_unsafe_env,
        "unsafe_path": previous_unsafe_path_env,
    })


def _restore_provider_settings_env(previous_env: str | None) -> None:
    if previous_env and previous_env.startswith("{"):
        values = json.loads(previous_env)
        _restore_env("XACE_PROVIDER_SETTINGS_PATH", values.get("provider"))
        _restore_env(BACKEND_ENV, values.get("backend"))
        _restore_env(UNSAFE_FALLBACK_ENV, values.get("unsafe"))
        _restore_env(UNSAFE_STORE_PATH_ENV, values.get("unsafe_path"))
        return
    _restore_env("XACE_PROVIDER_SETTINGS_PATH", previous_env)


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def _last(messages: list[dict[str, Any]], message_type: str) -> dict[str, Any]:
    matches = [message for message in messages if message.get("type") == message_type]
    _require(bool(matches), f"missing message type {message_type}: {messages}")
    return matches[-1]


def _approval_from_last_preview(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("type") != "pil_result":
            continue
        result = message.get("result") if isinstance(message.get("result"), dict) else {}
        preview = result.get("preview") if isinstance(result.get("preview"), dict) else None
        if not preview:
            return None
        preview_id = preview.get("preview_id")
        approval_token = preview.get("approval_token")
        if not isinstance(preview_id, str) or not isinstance(approval_token, str):
            return None
        return {
            "schema": "xace.prompt_preview_approval.v1",
            "preview_id": preview_id,
            "approval_token": approval_token,
            "approval_source": "prompt_pipeline_smoke",
            "approved_by": "prompt-contract-scenario-smoke",
        }
    return None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())

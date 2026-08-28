"""
builder_server.py — XACE Builder WebSocket Server
==================================================
FastAPI application that bridges the TypeScript builder UI
and the Python PIL backend.

## Endpoints

    GET  /            → serves built TypeScript UI (index.html)
    GET  /assets/*    → serves built TypeScript static assets
    WS   /ws/{session_id}  → WebSocket connection per designer session

## Request Flow

    Browser connects to /ws/{session_id}
    ↓ SessionManager.get_or_create(session_id)
    ↓ CGSPersistence.load() → sends session_init to browser
    ↓ Browser sends pil_process
    ↓ WSMessageRouter.route() → SessionManager.run_pil()
    ↓ PIL runs in thread pool, streaming pass updates via WebSocket
    ↓ PIL result sent as pil_result
    ↓ Browser sends pil_apply → GDE validates → CGS updated → cgs_update broadcast

## Running

    python builder_server.py --project /path/to/project [--port 8765] [--dev]
                             [--api-key sk-ant-...]

    --dev     flag enables CORS for the Vite dev server (localhost:5173).
    --api-key saves a hosted provider key for real LLM calls via InferenceAdapter.
              If prompt dependencies or provider readiness are missing, prompts block visibly.

## Phase 14.5 additions
    --api-key  wires the real InferenceAdapter into PIL
    --sgc-bin  path to compiled SGC binary; structural prompt applies block if absent
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from session_manager import SessionManager
from cgs_persistence import CGSPersistence, CGSLoadError
from prompt_capability_matrix import load_prompt_capability_matrix
from ws_message_router import WSMessageRouter
from runtime_control_client import RuntimeControlClient, RuntimeControlConfig, RuntimeControlError

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt = "%H:%M:%S",
)
log = logging.getLogger("xace.server")

EXPORT_TARGETS = {
    "unity":  {"source": "adapters/unity",  "label": "Unity C#"},
    "unreal": {"source": "adapters/unreal", "label": "Unreal C++"},
    "godot":  {"source": "adapters/godot",  "label": "Godot GDScript"},
}

_PROJECT_SYSTEM = Path(__file__).resolve().parents[2] / "project-system"
sys.path.insert(0, str(_PROJECT_SYSTEM))
from project_creator import CreateProjectRequest, ProjectCreator  # noqa: E402
from adapter_installation import (  # noqa: E402
    AdapterInstallationError,
    install_or_update_adapter,
    rollback_latest_adapter_transaction,
    uninstall_adapter,
)
from adapter_package_handoff_preflight import (  # noqa: E402
    validate_adapter_package_handoff,
    write_adapter_package_handoff_preflight_report,
)
from adapter_package_versioning import (  # noqa: E402
    ADAPTER_PACKAGE_MANIFEST,
    build_adapter_package_manifest,
    verify_adapter_package,
    write_adapter_package_manifest,
    write_adapter_package_verification_report,
)
from engine_migration_wizard import build_manual_migration_plan, materialize_manual_migration_draft  # noqa: E402
from project_manifest import ProjectManifestError, save_manifest  # noqa: E402
from project_templates import list_templates  # noqa: E402

LAUNCHER_STATE_ENV = "XACE_LAUNCHER_STATE"

# ── App factory ───────────────────────────────────────────────────────────────

def create_app(
    project_path:   str  = "./project",
    static_dir:     str  = "./dist",
    dev_mode:       bool = False,
    sgc_bin:        str  = "",
    model_provider: str  = "auto",
    model_name:     str  = "",
    ollama_url:     str  = "http://localhost:11434",
    api_key:        str  = "",
    runtime_host:   str  = "127.0.0.1",
    runtime_control_port: int = 7778,
    runtime_control_timeout: float = 2.0,
) -> FastAPI:
    """
    Creates the FastAPI application.

    Parameters
    ----------
    project_path   : str   — path to the XACE project directory
    static_dir     : str   — path to the built Vite output directory
    dev_mode       : bool  — enables CORS for Vite dev server
    sgc_bin        : str   — path to compiled SGC binary
    model_provider : str   — "auto" | "ollama" | hosted provider id
    model_name     : str   — explicit model id; empty leaves hosted providers unresolved until selected
    ollama_url     : str   — Ollama server URL
    """
    app = FastAPI(title="XACE Builder Server")

    # ── CORS (dev mode only) ──────────────────────────────────────────────────
    if dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins     = ["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_origin_regex = r"^http://(localhost|127\.0\.0\.1):[0-9]+$",
            allow_credentials = True,
            allow_methods     = ["*"],
            allow_headers     = ["*"],
        )

    # ── Shared state ──────────────────────────────────────────────────────────
    project_path  = str(Path(project_path).resolve())
    _remember_launcher_project(project_path)
    persist       = CGSPersistence(project_path)
    recovery_report = persist.recover().to_dict()
    session_mgr   = SessionManager(
        sgc_bin_path   = sgc_bin,
        model_provider = model_provider,
        model_name     = model_name,
        ollama_url     = ollama_url,
        api_key        = api_key,
    )
    runtime_control = RuntimeControlClient(RuntimeControlConfig(
        host=runtime_host,
        port=runtime_control_port,
        timeout_seconds=runtime_control_timeout,
    ))
    router        = WSMessageRouter(session_mgr, runtime_control)
    cgs_state: dict = {}
    app.state.persist = persist
    app.state.session_manager = session_mgr
    app.state.router = router
    app.state.cgs_state = cgs_state
    app.state.recovery_report = recovery_report
    app.state.demo_runtime_process = None

    # ── Static file serving ───────────────────────────────────────────────────
    dist_path = Path(static_dir)
    if dist_path.exists():
        app.mount("/assets", StaticFiles(directory=str(dist_path / "assets")), name="assets")

    @app.get("/", response_model=None)
    async def serve_index():
        index = dist_path / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return HTMLResponse(
            "<html><body><h2>XACE Builder</h2>"
            "<p>Run <code>npm run build</code> in builder-workspace, "
            "or start the Vite dev server with <code>npm run dev</code>.</p>"
            "</body></html>"
        )

    # ── WebSocket endpoint ────────────────────────────────────────────────────
    @app.websocket("/ws/{session_id}")
    async def ws_endpoint(ws: WebSocket, session_id: str) -> None:
        nonlocal persist, project_path
        await ws.accept()
        log.info("WebSocket connected: session=%s", session_id[:12])

        async def send_fn(msg: dict) -> None:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                pass

        try:
            # Create or resume session
            await session_mgr.get_or_create(
                session_id   = session_id,
                send_fn      = send_fn,
                project_path = project_path,
            )

            # Load CGS and send session_init
            try:
                loaded = persist.load()
                cgs_state.clear()
                cgs_state.update(loaded)
            except CGSLoadError:
                log.warning("No CGS found at %s — starting empty", project_path)
                cgs_state.update(_empty_cgs())

            snapshots = persist.list_snapshots(limit=50)
            await send_fn({
                "type":       "session_init",
                "session_id": session_id,
                "cgs":        cgs_state,
                "hash":       cgs_state.get("metadata", {}).get("cgs_hash", ""),
                "snapshots":  [s.to_dict() for s in snapshots],
                "recovery":   app.state.recovery_report,
                "version":    cgs_state.get("metadata", {}).get("schema_version", "0.0.0"),
            })

            # Message loop
            while True:
                raw = await ws.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await send_fn({"type": "server_error", "code": "INVALID_JSON",
                                   "message": "Message is not valid JSON."})
                    continue

                await router.route(
                    session_id = session_id,
                    message    = message,
                    send_fn    = send_fn,
                    persist    = persist,
                    cgs_state  = cgs_state,
                )

        except WebSocketDisconnect:
            log.info("WebSocket disconnected: session=%s", session_id[:12])
            session_mgr.mark_disconnected(session_id)
        except Exception as exc:
            log.exception("Unexpected WebSocket error for session %s", session_id[:12])
            try:
                await ws.close()
            except Exception:
                pass

    # ── Terminal WebSocket endpoint ───────────────────────────────────────────
    @app.websocket("/ws/terminal/{session_id}")
    async def terminal_endpoint(ws: WebSocket, session_id: str) -> None:
        nonlocal project_path
        """
        Spawns a bash subprocess and bridges its I/O to the WebSocket.
        Used by the XACE embedded terminal for running Ollama commands.
        The builder is a local developer tool, so this endpoint only accepts
        loopback clients and runs from the active project directory.
        """
        if not _is_loopback_ws(ws):
            await ws.close(code=1008, reason="Terminal is restricted to loopback clients.")
            return

        await ws.accept()

        shell = _default_shell()
        log.info("Terminal session opened: %s shell=%s", session_id[:12], shell)

        proc = await asyncio.create_subprocess_exec(
            shell,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=project_path,
            env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"},
        )

        async def _read_output():
            """Forward process stdout → WebSocket."""
            try:
                while True:
                    chunk = await proc.stdout.read(1024)  # type: ignore[union-attr]
                    if not chunk:
                        break
                    try:
                        await ws.send_text(chunk.decode(errors="replace"))
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                try:
                    await ws.close()
                except Exception:
                    pass

        async def _read_input():
            """Forward WebSocket keystrokes → process stdin."""
            try:
                while True:
                    data = await ws.receive_text()
                    if proc.stdin:
                        proc.stdin.write(data.encode())
                        await proc.stdin.drain()
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                if proc.stdin:
                    proc.stdin.close()

        try:
            await asyncio.gather(_read_output(), _read_input())
        except Exception:
            pass
        finally:
            try:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
            except Exception:
                pass
            log.info("Terminal session closed: %s", session_id[:12])

    @app.get("/health")
    async def health():
        return {
            "status":        "ok",
            "sessions":      session_mgr.session_count,
            "project":       project_path,
            "sgc_available": bool(sgc_bin and Path(sgc_bin).exists()),
            "provider":      model_provider,
            "runtime_control": runtime_control.endpoint,
        }

    # ── Model list (for UI model selector) ────────────────────────────────────
    @app.get("/api/models")
    async def list_models():
        """
        Returns available models for the current provider.
        Called by the TypeScript model selector on load and refresh.
        """
        return session_mgr.get_available_models()

    @app.get("/api/provider-settings")
    async def get_provider_settings():
        """
        Returns local provider settings metadata without exposing API keys.
        """
        return session_mgr.get_provider_settings()

    @app.get("/api/provider-settings/readiness")
    async def get_provider_readiness():
        """
        Returns whether the active provider is ready for prompt execution.
        """
        return session_mgr.provider_readiness()

    @app.get("/api/prompt/capability-matrix")
    async def get_prompt_capability_matrix():
        """
        Returns the shared Task 35 prompt capability matrix used by Builder and docs.
        """
        return load_prompt_capability_matrix()

    @app.post("/api/provider-settings")
    async def save_provider_settings(request: Request):
        """
        Saves provider/model selection and optional API key to local settings.
        """
        if not _is_loopback_http(request):
            return {"ok": False, "error": "Provider settings are restricted to local Builder clients."}
        payload = await request.json()
        provider = str(payload.get("provider") or "auto")
        model = str(payload.get("model") or "")
        api_key = payload.get("api_key")
        base_url = str(payload.get("base_url") or payload.get("ollama_url") or "")
        clear_key = bool(payload.get("clear_key", False))
        return session_mgr.configure_provider(
            provider=provider,
            model_name=model,
            api_key=str(api_key) if api_key is not None else None,
            base_url=base_url,
            clear_key=clear_key,
        )

    @app.post("/api/provider-settings/test")
    async def test_provider_settings(request: Request):
        """
        Runs a real provider health check: key present, model reachable, test call.
        """
        if not _is_loopback_http(request):
            return {"ok": False, "error": "Provider tests are restricted to local Builder clients."}
        payload = await request.json()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: session_mgr.test_provider_config(payload),
        )

    @app.get("/api/project")
    async def get_project():
        nonlocal project_path
        """
        Returns the active project manifest and current CGS path.
        """
        creator = ProjectCreator()
        try:
            rejected = _reject_source_checkout_project(project_path)
            if rejected:
                return {
                    "ok": False,
                    "project_dir": str(Path(project_path).resolve()),
                    "error": rejected,
                }
            opened = creator.open_project(project_path)
            return {
                "ok": True,
                **opened.to_dict(),
                "adapter_status": _adapter_status(
                    opened.project_dir,
                    opened.manifest.engine_type,
                ),
                "adapter_install_plan": _adapter_install_plan(opened.project_dir, opened.manifest),
            }
        except ProjectManifestError as exc:
            return {
                "ok": False,
                "project_dir": str(Path(project_path).resolve()),
                "error": str(exc),
            }

    @app.get("/api/project/templates")
    async def get_project_templates():
        """Returns starter templates for the New Project flow."""
        return {
            "ok": True,
            "templates": [template.to_dict() for template in list_templates()],
        }

    @app.post("/api/project/create")
    async def create_project(payload: dict):
        nonlocal persist, project_path
        """
        Creates a XACE project folder with xace.project.json and game.cgs.json.

        If project_path is omitted, this creates/repairs the server's active
        project folder. Creating another folder does not switch this running
        server to that folder; restart the server with --project for that.
        """
        target_project = str(payload.get("project_path") or project_path)
        rejected = _reject_source_checkout_project(target_project)
        if rejected:
            return {"ok": False, "project_dir": str(Path(target_project).resolve()), "error": rejected}
        creator = ProjectCreator()
        try:
            result = creator.create_project(CreateProjectRequest(
                project_dir=target_project,
                name=str(payload.get("name") or "XACE Project"),
                engine_type=str(payload.get("engine_type") or "godot"),
                template_id=str(payload.get("template_id") or "blank_3d"),
                force=bool(payload.get("force", False)),
            ))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        is_active = Path(target_project).resolve() == Path(project_path).resolve()
        adapter_install = _install_project_adapter(
            project_dir=result.project_dir,
            engine_type=result.manifest.engine_type,
        )
        if is_active:
            try:
                loaded = persist.load()
                cgs_state.clear()
                cgs_state.update(loaded)
            except CGSLoadError:
                pass
            _remember_launcher_project(result.project_dir)

        return {
            "ok": True,
            **result.to_dict(),
            "active": is_active,
            "restart_required": not is_active,
            "adapter_install": adapter_install,
            "adapter_status": _adapter_status(result.project_dir, result.manifest.engine_type),
        }

    @app.get("/api/project/adapter/status")
    async def get_project_adapter_status():
        nonlocal project_path
        """
        Returns adapter health for the active project.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "adapter_status": _adapter_status(
                opened.project_dir,
                opened.manifest.engine_type,
            ),
        }

    @app.post("/api/project/adapter/reinstall")
    async def reinstall_project_adapter():
        nonlocal project_path
        """
        Reinstalls the selected adapter payload into the active project.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        adapter_install = _install_project_adapter(
            project_dir=opened.project_dir,
            engine_type=opened.manifest.engine_type,
        )
        adapter_status = _adapter_status(opened.project_dir, opened.manifest.engine_type)
        return {
            "ok": bool(adapter_install.get("ok")),
            "adapter_install": adapter_install,
            "adapter_status": adapter_status,
        }

    @app.get("/api/project/adapter/install-plan")
    async def get_project_adapter_install_plan():
        nonlocal project_path
        """
        Returns engine-specific guidance for copying the adapter into the engine project.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "adapter_install_plan": _adapter_install_plan(opened.project_dir, opened.manifest),
        }

    @app.post("/api/project/adapter/install-engine")
    async def install_project_adapter_to_engine(payload: dict):
        nonlocal project_path
        """
        Installs or updates the prepared XACE adapter payload in the selected engine project folder.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            result = _copy_adapter_to_engine_project(
                project_dir=opened.project_dir,
                manifest=opened.manifest,
                engine_project_path=str(payload.get("engine_project_path") or ""),
                overwrite=bool(payload.get("overwrite", False)),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": bool(result.get("ok")),
            "adapter_engine_install": result,
            "adapter_install_plan": _adapter_install_plan(opened.project_dir, opened.manifest),
            "adapter_status": _adapter_status(opened.project_dir, opened.manifest.engine_type),
        }

    @app.post("/api/project/adapter/rollback-engine")
    async def rollback_project_adapter_in_engine(payload: dict):
        nonlocal project_path
        """
        Rolls back the latest XACE-owned adapter install/update transaction.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            result = _rollback_adapter_in_engine_project(
                project_dir=opened.project_dir,
                manifest=opened.manifest,
                engine_project_path=str(payload.get("engine_project_path") or ""),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": bool(result.get("ok")),
            "adapter_engine_rollback": result,
            "adapter_install_plan": _adapter_install_plan(opened.project_dir, opened.manifest),
            "adapter_status": _adapter_status(opened.project_dir, opened.manifest.engine_type),
        }

    @app.post("/api/project/adapter/uninstall-engine")
    async def uninstall_project_adapter_from_engine(payload: dict):
        nonlocal project_path
        """
        Uninstalls XACE-owned adapter files without deleting user engine data.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            result = _uninstall_adapter_from_engine_project(
                project_dir=opened.project_dir,
                manifest=opened.manifest,
                engine_project_path=str(payload.get("engine_project_path") or ""),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": bool(result.get("ok")),
            "adapter_engine_uninstall": result,
            "adapter_install_plan": _adapter_install_plan(opened.project_dir, opened.manifest),
            "adapter_status": _adapter_status(opened.project_dir, opened.manifest.engine_type),
        }

    @app.post("/api/project/adapter/setup-godot-scene")
    async def setup_godot_adapter_scene(payload: dict):
        nonlocal project_path
        """
        Creates a ready-to-run Godot scene that uses the installed XACE addon.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            result = _setup_godot_scene(
                project_dir=opened.project_dir,
                manifest=opened.manifest,
                engine_project_path=str(payload.get("engine_project_path") or ""),
                overwrite=bool(payload.get("overwrite", False)),
                set_main_scene=bool(payload.get("set_main_scene", False)),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": bool(result.get("ok")),
            "godot_scene_setup": result,
            "adapter_install_plan": _adapter_install_plan(opened.project_dir, opened.manifest),
            "adapter_status": _adapter_status(opened.project_dir, opened.manifest.engine_type),
        }

    @app.post("/api/project/demo/three-engine/status")
    async def three_engine_demo_status(payload: dict):
        nonlocal project_path
        """
        Checks readiness for the one-runtime / three-engine demo.

        This does not launch heavyweight engine editors. It validates the saved
        engine project folders and returns a safe command/status shape that the
        Builder UI can present to non-technical users.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            engine_paths = _demo_engine_paths_from_payload(payload, opened.manifest)
            if bool(payload.get("save_paths", False)):
                opened.manifest.adapter_config["demo_engine_projects"] = engine_paths
                save_manifest(opened.project_dir, opened.manifest)
            return {
                "ok": True,
                "demo": _three_engine_demo_status(
                    opened.project_dir,
                    opened.manifest,
                    engine_paths,
                    runtime_control=runtime_control,
                    runtime_process=app.state.demo_runtime_process,
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/project/demo/three-engine/smoke")
    async def run_three_engine_demo_smoke(payload: dict):
        nonlocal project_path
        """
        Runs the editor-free proof: one runtime, three adapter clients, same hash.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            engine_paths = _demo_engine_paths_from_payload(payload, opened.manifest)
            if bool(payload.get("save_paths", False)):
                opened.manifest.adapter_config["demo_engine_projects"] = engine_paths
                save_manifest(opened.project_dir, opened.manifest)
            status = _three_engine_demo_status(
                opened.project_dir,
                opened.manifest,
                engine_paths,
                runtime_control=runtime_control,
                runtime_process=app.state.demo_runtime_process,
            )
            smoke = await asyncio.to_thread(_run_three_engine_smoke, Path(opened.project_dir).resolve(), opened.manifest)
            return {
                "ok": bool(smoke.get("ok")),
                "demo": status,
                "smoke": smoke,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/project/demo/multiplayer/smoke")
    async def run_multiplayer_product_smoke():
        """
        Runs the editor-free network-primitives smoke:
        host/client lifecycle, lockstep input, prediction/reconciliation, desync detection.
        """
        smoke = await asyncio.to_thread(_run_multiplayer_product_smoke)
        return {
            "ok": bool(smoke.get("ok")),
            "smoke": smoke,
        }

    @app.get("/api/project/demo/multiplayer/diagnostics")
    async def get_multiplayer_diagnostics_panel():
        """
        Returns the Builder multiplayer diagnostics panel payload for the
        supported host/client lockstep topology.
        """
        try:
            diagnostics = await asyncio.to_thread(_build_multiplayer_diagnostics_panel)
            return {
                "ok": True,
                "diagnostics": diagnostics,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.get("/api/project/certify/status")
    async def get_launch_certification_status():
        """
        Returns launch certification command readiness without running it.
        """
        return {
            "ok": True,
            "certification": _launch_certification_status(),
        }

    @app.post("/api/project/certify/quick")
    async def run_launch_certification_quick():
        """
        Runs the quick editor-free launch certification suite.
        """
        result = await asyncio.to_thread(_run_launch_certification_quick)
        return {
            "ok": bool(result.get("ok")),
            "certification": result,
        }

    @app.get("/api/project/demo/runtime")
    async def get_demo_runtime_status():
        """Returns the current runtime process/control status for the demo."""
        return {
            "ok": True,
            "runtime": _demo_runtime_status(runtime_control, app.state.demo_runtime_process),
        }

    @app.post("/api/project/demo/live-validation")
    async def check_demo_live_validation(payload: dict):
        """
        Reports the live editor validation checklist for Godot, Unity, and Unreal.

        The check is intentionally evidence-based: an engine is only marked live
        when the runtime has seen its adapter connect, receive snapshots, send
        input/feedback, and report a state application pulse.
        """
        nonlocal project_path
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            engine_paths = _demo_engine_paths_from_payload(payload, opened.manifest)
            if bool(payload.get("save_paths", False)):
                opened.manifest.adapter_config["demo_engine_projects"] = engine_paths
                save_manifest(opened.project_dir, opened.manifest)
            executable_paths = _demo_executable_paths_from_payload(payload)
            unreal_validation = await asyncio.to_thread(
                _run_unreal_live_validation_from_builder,
                Path(opened.project_dir).resolve(),
                opened.manifest,
                engine_paths.get("unreal", ""),
                executable_paths.get("unreal", ""),
                runtime_control,
                app.state.demo_runtime_process,
            )
            demo = _three_engine_demo_status(
                opened.project_dir,
                opened.manifest,
                engine_paths,
                runtime_control=runtime_control,
                runtime_process=app.state.demo_runtime_process,
            )
            live_validation = _demo_live_validation_status(
                demo,
                automation={"unreal": unreal_validation},
            )
            return {
                "ok": True,
                "demo": demo,
                "live_validation": live_validation,
                "automation": {
                    "unreal": unreal_validation,
                },
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/project/demo/runtime/start")
    async def start_demo_runtime():
        """
        Starts one XACE runtime for three engine adapter clients.

        The runtime starts without waiting for editor clients so Builder remains
        responsive while users open Godot, Unity, and Unreal in any order.
        """
        nonlocal project_path
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            result, process = _start_demo_runtime(
                Path(opened.project_dir).resolve(),
                opened.manifest,
                runtime_control,
                app.state.demo_runtime_process,
            )
            app.state.demo_runtime_process = process
            return {"ok": bool(result.get("ok")), "runtime": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/project/demo/session/start")
    async def start_demo_session(payload: dict):
        """
        Starts the local runtime session and launches any ready engine projects.

        This is a product workflow helper, not a certification shortcut: each
        engine launch is reported independently so missing installs or folders
        do not hide the runtime state.
        """
        nonlocal project_path
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            engine_paths = _demo_engine_paths_from_payload(payload, opened.manifest)
            if bool(payload.get("save_paths", False)):
                opened.manifest.adapter_config["demo_engine_projects"] = engine_paths
                save_manifest(opened.project_dir, opened.manifest)

            runtime_result, process = _start_demo_runtime(
                Path(opened.project_dir).resolve(),
                opened.manifest,
                runtime_control,
                app.state.demo_runtime_process,
            )
            app.state.demo_runtime_process = process
            executable_paths = _demo_executable_paths_from_payload(payload)
            launches = _start_demo_engine_projects(engine_paths, executable_paths)
            status = _three_engine_demo_status(
                opened.project_dir,
                opened.manifest,
                engine_paths,
                runtime_control=runtime_control,
                runtime_process=app.state.demo_runtime_process,
            )
            return {
                "ok": bool(runtime_result.get("ok")),
                "runtime": runtime_result,
                "launches": launches,
                "demo": status,
                "engine_tools": status.get("engine_tools", []),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/project/demo/runtime/stop")
    async def stop_demo_runtime():
        """Stops the runtime listening on Builder's configured control port."""
        result = _stop_demo_runtime(runtime_control, app.state.demo_runtime_process)
        if bool(result.get("stopped")):
            app.state.demo_runtime_process = None
        return {"ok": bool(result.get("ok")), "runtime": result}

    @app.get("/api/project/demo/engine-tools")
    async def detect_demo_engine_tools():
        """Detects installed Godot, Unity, and Unreal editor executables."""
        return {
            "ok": True,
            "engine_tools": _detect_engine_tools(),
        }

    @app.post("/api/project/demo/launch-engine")
    async def launch_demo_engine(payload: dict):
        """
        Launches one selected engine project for the three-engine demo.
        """
        engine = str(payload.get("engine") or "").strip().lower()
        engine_project_path = str(payload.get("engine_project_path") or "").strip()
        executable_path = str(payload.get("executable_path") or "").strip()
        try:
            result = _launch_engine_project(engine, engine_project_path, executable_path)
            return {"ok": bool(result.get("ok")), "launch": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/project/open")
    async def open_project(payload: dict):
        nonlocal project_path
        """
        Validates an existing XACE project folder for the Open Project flow.

        The current dev server is bound to the --project folder it started
        with, so opening another folder reports restart_required. The packaged
        launcher can use the same response to restart/switch Builder for users.
        """
        target_project = str(payload.get("project_path") or "").strip()
        if not target_project:
            return {"ok": False, "error": "Choose a project folder to open."}
        rejected = _reject_source_checkout_project(target_project)
        if rejected:
            return {
                "ok": False,
                "project_dir": str(Path(target_project).resolve()),
                "error": rejected,
            }

        creator = ProjectCreator()
        try:
            opened = creator.open_project(target_project)
        except Exception as exc:
            return {
                "ok": False,
                "project_dir": str(Path(target_project).resolve()),
                "error": str(exc),
            }

        is_active = Path(target_project).resolve() == Path(project_path).resolve()
        return {
            "ok": True,
            **opened.to_dict(),
            "active": is_active,
            "restart_required": not is_active,
        }

    @app.post("/api/project/switch")
    async def switch_project(payload: dict):
        """
        Switches the active Builder project in-process.

        This is the dev-server stand-in for launch-ready launcher behavior:
        validate the target folder, rebind persistence, clear loaded CGS state,
        and let the browser reconnect to receive a fresh session_init.
        """
        nonlocal persist, project_path
        target_project = str(payload.get("project_path") or "").strip()
        if not target_project:
            return {"ok": False, "error": "Choose a project folder to open."}
        rejected = _reject_source_checkout_project(target_project)
        if rejected:
            return {
                "ok": False,
                "project_dir": str(Path(target_project).resolve()),
                "error": rejected,
            }

        creator = ProjectCreator()
        try:
            opened = creator.open_project(target_project)
        except Exception as exc:
            return {
                "ok": False,
                "project_dir": str(Path(target_project).resolve()),
                "error": str(exc),
            }

        project_path = str(Path(opened.project_dir).resolve())
        _remember_launcher_project(project_path)
        persist = CGSPersistence(project_path)
        app.state.persist = persist

        try:
            loaded = persist.load()
            cgs_state.clear()
            cgs_state.update(loaded)
        except CGSLoadError:
            cgs_state.clear()
            cgs_state.update(_empty_cgs())

        log.info("Active Builder project switched to: %s", project_path)
        return {
            "ok": True,
            **opened.to_dict(),
            "active": True,
            "restart_required": False,
            "reload_required": True,
            "adapter_status": _adapter_status(opened.project_dir, opened.manifest.engine_type),
        }

    @app.post("/api/project/import-engine")
    async def import_engine_project(payload: dict):
        nonlocal project_path
        """
        Wraps/links an existing engine project with a new XACE project manifest.
        """
        creator = ProjectCreator()
        target_project = str(payload.get("project_path") or project_path)
        rejected = _reject_source_checkout_project(target_project)
        if rejected:
            return {"ok": False, "project_dir": str(Path(target_project).resolve()), "error": rejected}
        try:
            result = creator.import_engine_project(
                engine_project_dir=str(payload.get("engine_project_path") or ""),
                xace_project_dir=target_project,
                name=str(payload.get("name") or "Imported XACE Project"),
                engine_type=str(payload.get("engine_type") or "godot"),
                template_id=str(payload.get("template_id") or "blank_3d"),
                force=bool(payload.get("force", False)),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        is_active = Path(result.project_dir).resolve() == Path(project_path).resolve()
        adapter_install = _install_project_adapter(
            project_dir=result.project_dir,
            engine_type=result.manifest.engine_type,
        )
        if is_active:
            _remember_launcher_project(result.project_dir)
        return {
            "ok": True,
            **result.to_dict(),
            "active": is_active,
            "restart_required": not is_active,
            "adapter_install": adapter_install,
            "adapter_status": _adapter_status(result.project_dir, result.manifest.engine_type),
        }

    @app.post("/api/project/migration/manual-plan")
    async def build_project_manual_migration_plan(payload: dict):
        nonlocal project_path
        """
        Builds a read-only manual migration plan for a linked engine project.

        The response is a wizard preview only: it maps engine scenes, entity
        candidates, and asset references to reversible CGS-shaped records, but
        it does not write CGS, adapter, or engine-owned files.
        """
        creator = ProjectCreator()
        try:
            opened = creator.open_project(project_path)
            engine_project_path = str(
                payload.get("engine_project_path")
                or opened.manifest.adapter_config.get("engine_project_path")
                or ""
            ).strip()
            if not engine_project_path:
                return {
                    "ok": False,
                    "error": "No linked engine project path is available. Import/link an engine project first.",
                }
            cgs: dict[str, Any] | None = None
            cgs_path = Path(opened.cgs_path)
            if cgs_path.exists():
                cgs = json.loads(cgs_path.read_text(encoding="utf-8"))
            plan = build_manual_migration_plan(
                engine_project_path,
                expected_engine_type=str(payload.get("engine_type") or opened.manifest.engine_type),
                base_cgs=cgs,
            )
            response: dict[str, Any] = {
                "ok": bool(plan.get("ok")),
                "manual_migration_plan": plan,
                "preview_only": True,
            }
            if bool(payload.get("include_preview_cgs", False)) and cgs is not None and plan.get("ok"):
                response["manual_migration_preview"] = materialize_manual_migration_draft(cgs, plan)
            return response
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/system/pick-folder")
    async def pick_folder(payload: dict, request: Request):
        """
        Opens a native folder picker on the local Builder machine.

        Browsers intentionally do not expose absolute local folder paths, so
        this local-only endpoint supplies the launch-style native picker while
        the text field remains as a fallback for dev/headless environments.
        """
        if not _is_loopback_http(request):
            return {"ok": False, "error": "Folder picker is restricted to this computer."}

        title = str(payload.get("title") or "Choose folder")
        initial_path = str(payload.get("initial_path") or project_path)
        try:
            selected = await asyncio.to_thread(_pick_folder_dialog, title, initial_path)
        except Exception as exc:
            return {"ok": False, "error": f"Folder picker is unavailable: {exc}"}
        if not selected:
            return {"ok": False, "cancelled": True, "error": "No folder selected."}
        return {"ok": True, "path": selected}

    @app.post("/api/adapter-package/handoff/{target}")
    async def handoff_adapter_package(target: str):
        """
        Copies an adapter package into the active project's
        .xace/adapter_package_handoffs/<target>/ directory.

        This is an engine-integration handoff. The receiving engine project owns
        shipping packages, platform builds, and release validation.
        """
        key = target.lower()
        repo_root = Path(__file__).resolve().parents[3]
        preflight = validate_adapter_package_handoff(project_path, key, repo_root=repo_root)
        preflight_path = write_adapter_package_handoff_preflight_report(project_path, key, preflight)
        if not preflight.get("ok"):
            return {
                "ok": False,
                "error": "Adapter package handoff preflight failed.",
                "preflight_report_path": str(preflight_path),
                "preflight": preflight,
                "targets": sorted(EXPORT_TARGETS),
            }

        if key not in EXPORT_TARGETS:
            return {
                "ok": False,
                "error": f"Unknown adapter package handoff target: {target}",
                "preflight_report_path": str(preflight_path),
                "preflight": preflight,
                "targets": sorted(EXPORT_TARGETS),
            }

        src_dir = repo_root / EXPORT_TARGETS[key]["source"]
        if not src_dir.exists():
            return {
                "ok": False,
                "error": f"Adapter source missing: {src_dir}",
                "preflight_report_path": str(preflight_path),
                "preflight": preflight,
                "targets": sorted(EXPORT_TARGETS),
            }

        source_package_manifest = build_adapter_package_manifest(src_dir, key)
        source_package_report = verify_adapter_package(
            src_dir,
            key,
            manifest=source_package_manifest,
            require_manifest_file=False,
        )
        source_package_report_path = write_adapter_package_verification_report(project_path, key, source_package_report)
        if not source_package_report.get("ok"):
            return {
                "ok": False,
                "error": "Adapter package version verification failed.",
                "preflight_report_path": str(preflight_path),
                "preflight": preflight,
                "package_version_report_path": str(source_package_report_path),
                "package_version_report": source_package_report,
                "targets": sorted(EXPORT_TARGETS),
            }

        handoff_root = Path(project_path).resolve() / ".xace" / "adapter_package_handoffs" / key
        if handoff_root.exists():
            shutil.rmtree(handoff_root)
        shutil.copytree(src_dir, handoff_root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        export_root = handoff_root  # Internal compatibility alias for the file-list loop below.

        package_manifest_path, package_manifest = write_adapter_package_manifest(handoff_root, key)
        package_version_report = verify_adapter_package(handoff_root, key)
        package_version_report_path = write_adapter_package_verification_report(project_path, key, package_version_report)
        if not package_version_report.get("ok"):
            return {
                "ok": False,
                "error": "Adapter package checksum verification failed after handoff copy.",
                "preflight_report_path": str(preflight_path),
                "preflight": preflight,
                "package_version_report_path": str(package_version_report_path),
                "package_version_report": package_version_report,
                "targets": sorted(EXPORT_TARGETS),
            }

        files = [
            str(path.relative_to(export_root)).replace("\\", "/")
            for path in sorted(export_root.rglob("*"))
            if path.is_file()
        ]
        manifest = {
            "schema": "xace.adapter_package_handoff_manifest.v1",
            "target": key,
            "label": EXPORT_TARGETS[key]["label"],
            "package_role": "adapter_package_handoff",
            "shipping_boundary": "engine_project_owns_shipping_package",
            "adapter_package_manifest": ADAPTER_PACKAGE_MANIFEST,
            "adapter_package_id": package_manifest["package_id"],
            "adapter_package_version": package_manifest["version"],
            "adapter_protocol_version": package_manifest["adapter_protocol_version"],
            "package_content_sha256": package_manifest["checksums"]["package_content_sha256"],
            "package_checksum_algorithm": package_manifest["checksums"]["algorithm"],
            "compatibility_matrix": package_manifest["compatibility_matrix"],
            "dependencies": package_manifest["dependencies"],
            "lifecycle_scripts": package_manifest["lifecycle_scripts"],
            "rollback_support": package_manifest["rollback_support"],
            "file_count": len(files),
            "files": files,
        }
        (handoff_root / "xace_adapter_package_handoff_manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

        return {
            "ok": True,
            "target": key,
            "label": EXPORT_TARGETS[key]["label"],
            "path": str(handoff_root),
            "files": files,
            "manifest": manifest,
            "preflight_report_path": str(preflight_path),
            "preflight": preflight,
            "package_version_manifest_path": str(package_manifest_path),
            "package_version_manifest": package_manifest,
            "package_version_report_path": str(package_version_report_path),
            "package_version_report": package_version_report,
        }

    @app.post("/api/run-smoke")
    async def run_smoke():
        """
        Runs the strongest local smoke action available today.

        This is intentionally not a real engine launch: Unity/Unreal/Godot live
        bridges are later-phase work. For the current repo, the best immediate
        signal is the deterministic zombie-chase runner test.
        """
        repo_root = Path(__file__).resolve().parents[3]
        manifest = repo_root / "Cargo.toml"
        zombie_example = repo_root / "examples" / "zombie-chase" / "Cargo.toml"

        if not manifest.exists() or not zombie_example.exists():
            return {
                "ok": False,
                "kind": "unavailable",
                "error": "No local cargo zombie-chase smoke target was found.",
                "engine_bridge": "not_connected",
            }

        command = [
            "cargo",
            "test",
            "-p",
            "xace-zombie-chase",
            "three_runs_seed_42_tick_1000_hash_identical",
            "--",
            "--nocapture",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
        except FileNotFoundError:
            return {
                "ok": False,
                "kind": "cargo_smoke",
                "command": command,
                "error": "cargo was not found on PATH.",
                "engine_bridge": "not_connected",
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[possibly-undefined]
                await proc.wait()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return {
                "ok": False,
                "kind": "cargo_smoke",
                "command": command,
                "error": "Smoke run timed out after 45 seconds.",
                "engine_bridge": "not_connected",
            }

        out_text = stdout.decode(errors="replace")
        err_text = stderr.decode(errors="replace")
        return {
            "ok": proc.returncode == 0,
            "kind": "cargo_smoke",
            "command": command,
            "exit_code": proc.returncode,
            "stdout_tail": out_text[-4000:],
            "stderr_tail": err_text[-4000:],
            "engine_bridge": "not_connected",
        }

    return app


def _install_project_adapter(project_dir: str | Path, engine_type: str) -> dict:
    """
    Copies the selected engine adapter into the project's .xace/adapter folder.

    The engine project still owns native packaging/import. This prepares the
    correct XACE-side adapter payload so the next step can install it into
    Godot/Unity/Unreal projects without asking the creator to hunt for files.
    """
    key = engine_type.strip().lower()
    if key == "headless":
        return {
            "ok": True,
            "status": "not_applicable",
            "code": "ADAPTER_NOT_APPLICABLE",
            "target": key,
            "skipped": True,
            "unsupported": False,
            "reason": "Headless projects do not need an engine adapter.",
            "action": "Choose Godot, Unity, or Unreal as the project engine before installing an adapter.",
        }
    if key not in EXPORT_TARGETS:
        return {
            "ok": False,
            "target": key,
            "error": f"Unknown adapter target: {engine_type}",
            "targets": sorted(EXPORT_TARGETS),
        }

    repo_root = Path(__file__).resolve().parents[3]
    src_dir = repo_root / EXPORT_TARGETS[key]["source"]
    if not src_dir.exists():
        return {
            "ok": False,
            "target": key,
            "error": f"Adapter source missing: {src_dir}",
            "targets": sorted(EXPORT_TARGETS),
        }

    project_root = Path(project_dir).resolve()
    adapter_root = project_root / ".xace" / "adapter" / key
    if not _is_within(project_root, adapter_root):
        return {
            "ok": False,
            "target": key,
            "error": f"Refusing to install adapter outside project: {adapter_root}",
        }

    if adapter_root.exists():
        shutil.rmtree(adapter_root)
    shutil.copytree(src_dir, adapter_root)

    files = [
        str(path.relative_to(adapter_root)).replace("\\", "/")
        for path in sorted(adapter_root.rglob("*"))
        if path.is_file()
    ]
    manifest = {
        "target": key,
        "label": EXPORT_TARGETS[key]["label"],
        "source": EXPORT_TARGETS[key]["source"],
        "file_count": len(files),
        "files": files,
    }
    (adapter_root / "xace_adapter_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    files.append("xace_adapter_manifest.json")

    return {
        "ok": True,
        "target": key,
        "label": EXPORT_TARGETS[key]["label"],
        "path": str(adapter_root),
        "files": files,
    }


def _adapter_status(project_dir: str | Path, engine_type: str) -> dict:
    """
    Reports whether the selected project adapter payload is present.
    """
    key = engine_type.strip().lower()
    if key == "headless":
        return {
            "ok": True,
            "status": "not_applicable",
            "code": "ADAPTER_NOT_APPLICABLE",
            "target": key,
            "skipped": True,
            "unsupported": False,
            "healthy": True,
            "installed": False,
            "reason": "Headless projects do not need an engine adapter.",
            "action": "Choose Godot, Unity, or Unreal as the project engine before checking adapter status.",
        }
    if key not in EXPORT_TARGETS:
        return {
            "ok": False,
            "target": key,
            "healthy": False,
            "installed": False,
            "error": f"Unknown adapter target: {engine_type}",
            "targets": sorted(EXPORT_TARGETS),
        }

    repo_root = Path(__file__).resolve().parents[3]
    src_dir = repo_root / EXPORT_TARGETS[key]["source"]
    project_root = Path(project_dir).resolve()
    adapter_root = project_root / ".xace" / "adapter" / key

    if not src_dir.exists():
        return {
            "ok": False,
            "target": key,
            "label": EXPORT_TARGETS[key]["label"],
            "healthy": False,
            "installed": adapter_root.exists(),
            "path": str(adapter_root),
            "error": f"Adapter source missing: {src_dir}",
            "targets": sorted(EXPORT_TARGETS),
        }

    source_files = [
        str(path.relative_to(src_dir)).replace("\\", "/")
        for path in sorted(src_dir.rglob("*"))
        if path.is_file()
    ]
    expected_files = source_files + ["xace_adapter_manifest.json"]
    installed = adapter_root.exists()
    installed_files = [
        str(path.relative_to(adapter_root)).replace("\\", "/")
        for path in sorted(adapter_root.rglob("*"))
        if path.is_file()
    ] if installed else []
    missing_files = [
        relative_path
        for relative_path in expected_files
        if not (adapter_root / relative_path).exists()
    ]
    healthy = installed and not missing_files

    return {
        "ok": True,
        "target": key,
        "label": EXPORT_TARGETS[key]["label"],
        "healthy": healthy,
        "installed": installed,
        "path": str(adapter_root),
        "file_count": len(installed_files),
        "expected_count": len(expected_files),
        "missing_files": missing_files,
    }


def _adapter_install_plan(project_dir: str | Path, manifest: Any) -> dict:
    key = str(manifest.engine_type).strip().lower()
    status = _adapter_status(project_dir, key)
    if key == "headless":
        return {
            "ok": True,
            "status": "not_applicable",
            "code": "ADAPTER_NOT_APPLICABLE",
            "target": key,
            "skipped": True,
            "unsupported": False,
            "reason": "Headless projects do not need an engine adapter.",
            "action": "Choose Godot, Unity, or Unreal as the project engine before planning adapter install.",
        }
    if key not in EXPORT_TARGETS:
        return {
            "ok": False,
            "target": key,
            "error": f"Unknown adapter target: {manifest.engine_type}",
            "targets": sorted(EXPORT_TARGETS),
        }

    adapter_config = dict(getattr(manifest, "adapter_config", {}) or {})
    engine_project_path = str(adapter_config.get("engine_project_path") or "")
    destination = ""
    if engine_project_path:
        destination = str(_engine_adapter_destination(Path(engine_project_path).resolve(), key))

    return {
        "ok": bool(status.get("ok")),
        "target": key,
        "label": EXPORT_TARGETS[key]["label"],
        "prepared_path": status.get("path", ""),
        "prepared_healthy": bool(status.get("healthy")),
        "engine_project_path": engine_project_path,
        "destination_path": destination,
        "default_destination": _engine_adapter_destination_label(key),
        "steps": _engine_adapter_steps(key),
    }


def _copy_adapter_to_engine_project(
    project_dir: str | Path,
    manifest: Any,
    engine_project_path: str,
    *,
    overwrite: bool,
) -> dict:
    return _copy_named_adapter_to_engine_project(
        project_dir=project_dir,
        manifest=manifest,
        engine_type=str(manifest.engine_type),
        engine_project_path=engine_project_path,
        overwrite=overwrite,
        save_primary_config=True,
    )


def _legacy_copy_named_adapter_to_engine_project(
    project_dir: str | Path,
    manifest: Any,
    engine_type: str,
    engine_project_path: str,
    *,
    overwrite: bool,
    save_primary_config: bool = False,
) -> dict:
    key = engine_type.strip().lower()
    if key == "headless":
        return {
            "ok": True,
            "status": "not_applicable",
            "code": "ADAPTER_NOT_APPLICABLE",
            "target": key,
            "skipped": True,
            "unsupported": False,
            "reason": "Headless projects do not need an engine adapter.",
            "action": "Choose Godot, Unity, or Unreal as the project engine before copying an adapter.",
        }
    if key not in EXPORT_TARGETS:
        return {
            "ok": False,
            "target": key,
            "error": f"Unknown adapter target: {engine_type}",
            "targets": sorted(EXPORT_TARGETS),
        }

    engine_root = Path(engine_project_path).resolve()
    if not engine_root.exists() or not engine_root.is_dir():
        return {"ok": False, "target": key, "error": f"Engine project folder not found: {engine_root}"}
    marker_ok, marker_reason = _engine_project_marker_ok(engine_root, key)
    if not marker_ok:
        return {"ok": False, "target": key, "error": marker_reason}

    status = _adapter_status(project_dir, key)
    if not status.get("healthy"):
        _install_project_adapter(project_dir, key)
        status = _adapter_status(project_dir, key)
    if not status.get("healthy"):
        return {
            "ok": False,
            "target": key,
            "error": "Prepared adapter is missing files. Use Repair Adapter first.",
            "adapter_status": status,
        }

    adapter_root = Path(str(status["path"])).resolve()
    destination = _engine_adapter_destination(engine_root, key)
    if not _is_within(engine_root, destination):
        return {
            "ok": False,
            "target": key,
            "error": f"Refusing to install adapter outside engine project: {destination}",
        }

    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []
    for source_path in sorted(adapter_root.rglob("*")):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(adapter_root)
        relative_text = str(relative_path).replace("\\", "/")
        if relative_text == "xace_adapter_manifest.json":
            continue
        if key == "godot" and relative_text == "project.godot":
            skipped.append(relative_text)
            continue
        target_path = _engine_adapter_target_path(destination, key, relative_text)
        if not _should_copy_engine_adapter_file(key, relative_text, target_path, overwrite):
            skipped.append(relative_text)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if key == "godot" and relative_text == "xace_godot_main.tscn":
            _write_godot_addon_scene(source_path, target_path)
        else:
            shutil.copy2(source_path, target_path)
        copied.append(relative_text)

    if key == "godot":
        if _write_godot_plugin_files(destination, overwrite):
            copied.extend(["plugin.cfg", "xace_editor_plugin.gd"])
        else:
            skipped.extend(["plugin.cfg", "xace_editor_plugin.gd"])
    elif key == "unreal":
        generated = _write_unreal_plugin_files(destination, overwrite)
        copied.extend(generated["copied"])
        skipped.extend(generated["skipped"])

    manifest_path = destination / "xace_engine_install_manifest.json"
    install_manifest = {
        "target": key,
        "label": EXPORT_TARGETS[key]["label"],
        "source": str(adapter_root),
        "engine_project_path": str(engine_root),
        "destination_path": str(destination),
        "copied": copied,
        "skipped": skipped,
        "overwrite": overwrite,
    }
    manifest_path.write_text(json.dumps(install_manifest, indent=2), encoding="utf-8")

    demo_projects = dict(manifest.adapter_config.get("demo_engine_projects", {}) or {})
    demo_projects[key] = str(engine_root)
    manifest.adapter_config["demo_engine_projects"] = demo_projects
    demo_install_paths = dict(manifest.adapter_config.get("demo_engine_adapter_install_paths", {}) or {})
    demo_install_paths[key] = str(destination)
    manifest.adapter_config["demo_engine_adapter_install_paths"] = demo_install_paths
    if save_primary_config:
        manifest.adapter_config["engine_project_path"] = str(engine_root)
        manifest.adapter_config["engine_adapter_install_path"] = str(destination)
    save_manifest(project_dir, manifest)

    return {
        "ok": True,
        "target": key,
        "label": EXPORT_TARGETS[key]["label"],
        "engine_project_path": str(engine_root),
        "destination_path": str(destination),
        "copied": copied,
        "skipped": skipped,
        "manifest_path": str(manifest_path),
        "steps": _engine_adapter_steps(key),
    }


def _setup_godot_scene(
    project_dir: str | Path,
    manifest: Any,
    engine_project_path: str,
    *,
    overwrite: bool,
    set_main_scene: bool,
) -> dict:
    key = str(manifest.engine_type).strip().lower()
    if key != "godot":
        return {
            "ok": False,
            "target": key,
            "error": "Scene setup is currently available for Godot projects only.",
        }

    engine_root = Path(engine_project_path).resolve()
    if not engine_root.exists() or not engine_root.is_dir():
        return {"ok": False, "target": key, "error": f"Godot project folder not found: {engine_root}"}
    project_file = engine_root / "project.godot"
    if not project_file.exists():
        return {"ok": False, "target": key, "error": f"Godot project.godot not found: {project_file}"}

    addon_root = _engine_adapter_destination(engine_root, key)
    if not (addon_root / "xace_godot_main.gd").exists():
        install = _copy_adapter_to_engine_project(
            project_dir=project_dir,
            manifest=manifest,
            engine_project_path=str(engine_root),
            overwrite=overwrite,
        )
        if not install.get("ok"):
            return {
                "ok": False,
                "target": key,
                "error": install.get("error", "Godot addon install failed."),
                "adapter_engine_install": install,
            }

    scenes_dir = engine_root / "scenes"
    scene_path = scenes_dir / "xace_runtime_scene.tscn"
    scene_relative = "scenes/xace_runtime_scene.tscn"
    scene_resource = f"res://{scene_relative}"
    scene_created = False
    scene_skipped = False

    if scene_path.exists() and not overwrite:
        scene_skipped = True
    else:
        scenes_dir.mkdir(parents=True, exist_ok=True)
        scene_path.write_text(_godot_runtime_scene_text(), encoding="utf-8")
        scene_created = True

    main_scene_changed = False
    if set_main_scene:
        main_scene_changed = _set_godot_main_scene(project_file, scene_resource)

    manifest.adapter_config["engine_project_path"] = str(engine_root)
    manifest.adapter_config["godot_setup_scene"] = scene_relative
    if main_scene_changed:
        manifest.adapter_config["godot_main_scene"] = scene_relative
    save_manifest(project_dir, manifest)

    return {
        "ok": True,
        "target": key,
        "engine_project_path": str(engine_root),
        "scene_path": str(scene_path),
        "scene_resource": scene_resource,
        "scene_created": scene_created,
        "scene_skipped": scene_skipped,
        "main_scene_changed": main_scene_changed,
        "addon_path": str(addon_root),
    }


def _demo_engine_paths_from_payload(payload: dict, manifest: Any) -> dict[str, str]:
    saved = dict(getattr(manifest, "adapter_config", {}) or {}).get("demo_engine_projects")
    saved_paths = saved if isinstance(saved, dict) else {}
    raw_paths = payload.get("engine_paths")
    requested = raw_paths if isinstance(raw_paths, dict) else {}
    out: dict[str, str] = {}
    for engine in ("godot", "unity", "unreal"):
        value = requested.get(engine, saved_paths.get(engine, ""))
        out[engine] = str(value or "").strip()
    return out


def _demo_executable_paths_from_payload(payload: dict) -> dict[str, str]:
    raw_paths = payload.get("executable_paths")
    requested = raw_paths if isinstance(raw_paths, dict) else {}
    return {
        "godot": str(requested.get("godot") or "").strip(),
        "unity": str(requested.get("unity") or "").strip(),
        "unreal": str(requested.get("unreal") or "").strip(),
    }


def _run_unreal_live_validation_from_builder(
    project_dir: Path,
    manifest: Any,
    engine_project_path: str,
    executable_path: str,
    runtime_control: RuntimeControlClient,
    runtime_process: subprocess.Popen | None = None,
) -> dict:
    label = _engine_label("unreal")
    result: dict[str, Any] = {
        "ok": False,
        "attempted": False,
        "engine": "unreal",
        "label": label,
        "summary": "",
        "reason": "",
        "next_step": "",
    }

    if not str(engine_project_path or "").strip():
        result.update({
            "skipped": True,
            "reason": "Choose the Unreal project folder before running automatic Unreal validation.",
            "next_step": "Click Browse beside Unreal Project and choose the folder that contains the .uproject file.",
        })
        return result

    engine_root = Path(engine_project_path).resolve()
    result["engine_project_path"] = str(engine_root)
    if not engine_root.exists() or not engine_root.is_dir():
        result.update({
            "reason": f"Unreal project folder was not found: {engine_root}",
            "next_step": "Choose the correct Unreal project folder.",
        })
        return result

    marker_ok, marker_reason = _engine_project_marker_ok(engine_root, "unreal")
    if not marker_ok:
        result.update({
            "reason": marker_reason,
            "next_step": "Choose the root folder that contains the Unreal .uproject file.",
        })
        return result

    prerequisite = _detect_unreal_netfxsdk()
    result["prerequisite"] = prerequisite
    if not prerequisite.get("ok"):
        result.update({
            "reason": prerequisite.get("reason", "Unreal prerequisite is missing."),
            "next_step": prerequisite.get("next_step", "Install the Unreal prerequisite, then run this check again."),
        })
        return result

    executable = _resolve_engine_executable("unreal", executable_path)
    if executable is None:
        result.update({
            "reason": "Unreal executable was not found.",
            "next_step": "Install Unreal Engine, then click Detect Engines or paste the UnrealEditor.exe path.",
        })
        return result
    result["executable_path"] = str(executable)

    adapter = _ensure_unreal_adapter_for_validation(project_dir, manifest, engine_root, executable)
    result["adapter_prepare"] = adapter
    if not adapter.get("ok"):
        result.update({
            "reason": adapter.get("error", "Unreal adapter preparation failed."),
            "next_step": adapter.get("next_step", "Repair or reinstall the Unreal adapter, then run this check again."),
        })
        return result

    runtime_public: dict[str, Any] = {}
    validation_control: RuntimeControlClient | None = None
    validation_process: subprocess.Popen | None = None
    stop_validation_runtime = False
    try:
        runtime_public, validation_control, validation_process, stop_validation_runtime = (
            _prepare_unreal_validation_runtime(project_dir, manifest, runtime_control, runtime_process)
        )
        result["runtime"] = runtime_public
        if not runtime_public.get("ok"):
            result.update({
                "reason": runtime_public.get("error", "Unable to start an XACE runtime for Unreal validation."),
                "next_step": "Build the XACE runtime, then run live validation again.",
            })
            return result

        result["attempted"] = True
        commandlet = _run_unreal_live_validation_commandlet(
            engine_root=engine_root,
            unreal_editor=executable,
            engine_port=_as_int(runtime_public.get("engine_port"), 7777),
        )
        result["commandlet"] = commandlet
        report = commandlet.get("report") if isinstance(commandlet.get("report"), dict) else {}
        result["report"] = report
        result["ok"] = bool(commandlet.get("ok"))
        if result["ok"]:
            result["summary"] = _unreal_live_report_summary(report)
            result["reason"] = "Unreal live validation passed."
            result["next_step"] = ""
        else:
            result["summary"] = commandlet.get("error", "Unreal live validation did not complete.")
            result["reason"] = result["summary"]
            result["next_step"] = "Close any stuck Unreal editor process, then run live validation again."
        return result
    finally:
        if stop_validation_runtime and validation_control is not None:
            result["runtime_stop"] = _stop_demo_runtime(validation_control, validation_process)


def _ensure_unreal_adapter_for_validation(
    project_dir: Path,
    manifest: Any,
    engine_root: Path,
    unreal_editor: Path,
) -> dict:
    plugin_root = _engine_adapter_destination(engine_root, "unreal")
    drift = _unreal_adapter_drift(plugin_root)
    installed = _engine_adapter_installed(plugin_root, "unreal")
    copied = False
    install: dict[str, Any] | None = None
    if not installed or drift["missing_files"] or drift["stale_files"]:
        install = _copy_named_adapter_to_engine_project(
            project_dir=project_dir,
            manifest=manifest,
            engine_type="unreal",
            engine_project_path=str(engine_root),
            overwrite=True,
            save_primary_config=False,
        )
        if not install.get("ok"):
            return {
                "ok": False,
                "error": install.get("error", "Unable to copy the Unreal adapter into the project."),
                "adapter_engine_install": install,
            }
        copied = True
        drift = _unreal_adapter_drift(plugin_root)

    if drift["missing_files"] or drift["stale_files"]:
        return {
            "ok": False,
            "error": "Unreal adapter files are still incomplete after reinstall.",
            "missing_files": drift["missing_files"],
            "stale_files": drift["stale_files"],
            "next_step": "Repair the XACE Unreal adapter files, then run this check again.",
        }

    binaries = _ensure_unreal_editor_binaries(
        plugin_root=plugin_root,
        unreal_editor=unreal_editor,
        force_rebuild=copied or not _unreal_plugin_editor_binary_ready(plugin_root).get("ready"),
    )
    if not binaries.get("ok"):
        return {
            "ok": False,
            "error": binaries.get("error", "Unable to build Unreal adapter binaries."),
            "adapter_engine_install": install,
            "binary_prepare": binaries,
            "next_step": "Make sure Unreal and Visual Studio build tools are installed, then run this check again.",
        }

    return {
        "ok": True,
        "plugin_path": str(plugin_root),
        "adapter_engine_install": install,
        "copied_or_updated": copied,
        "drift": drift,
        "binary_prepare": binaries,
    }


def _unreal_adapter_drift(plugin_root: Path) -> dict:
    missing: list[str] = []
    stale: list[str] = []
    repo_root = Path(__file__).resolve().parents[3]
    source_root = repo_root / EXPORT_TARGETS["unreal"]["source"]
    if not source_root.exists():
        return {
            "missing_files": ["adapters/unreal"],
            "stale_files": [],
        }

    for source_path in sorted(source_root.rglob("*")):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(source_root)
        relative_text = str(relative_path).replace("\\", "/")
        target_path = _engine_adapter_target_path(plugin_root, "unreal", relative_text)
        if not target_path.exists():
            missing.append(relative_text)
            continue
        try:
            if source_path.read_bytes() != target_path.read_bytes():
                stale.append(relative_text)
        except OSError:
            stale.append(relative_text)

    for relative_text, expected_text in _unreal_generated_plugin_texts().items():
        target_path = plugin_root / relative_text
        if not target_path.exists():
            missing.append(relative_text)
            continue
        try:
            if target_path.read_text(encoding="utf-8") != expected_text:
                stale.append(relative_text)
        except OSError:
            stale.append(relative_text)

    return {
        "missing_files": missing,
        "stale_files": stale,
    }


def _unreal_generated_plugin_texts() -> dict[str, str]:
    return {
        "XACE.uplugin": _unreal_uplugin_text(),
        "Source/XACEAdapter/XACEAdapter.Build.cs": _unreal_build_cs_text(),
        "Source/XACEAdapter/Public/XACEAdapterModule.h": _unreal_module_h_text(),
        "Source/XACEAdapter/Private/XACEAdapterModule.cpp": _unreal_module_cpp_text(),
    }


def _ensure_unreal_editor_binaries(
    plugin_root: Path,
    unreal_editor: Path,
    *,
    force_rebuild: bool,
) -> dict:
    current = _unreal_plugin_editor_binary_ready(plugin_root)
    if current.get("ready") and not force_rebuild:
        return {
            "ok": True,
            "rebuilt": False,
            "reason": "Unreal adapter editor binaries are already present.",
            **current,
        }

    build = _build_unreal_plugin_for_editor(plugin_root, unreal_editor)
    if not build.get("ok"):
        return build

    package_dir = Path(str(build["package_dir"]))
    package_binaries = package_dir / "Binaries"
    if not package_binaries.exists():
        return {
            "ok": False,
            "rebuilt": True,
            "build": build,
            "error": f"Unreal BuildPlugin finished, but no Binaries folder was produced at {package_binaries}.",
        }
    plugin_binaries = plugin_root / "Binaries"
    shutil.copytree(package_binaries, plugin_binaries, dirs_exist_ok=True)
    refreshed = _unreal_plugin_editor_binary_ready(plugin_root)
    return {
        "ok": bool(refreshed.get("ready")),
        "rebuilt": True,
        "build": build,
        "copied_binaries_from": str(package_binaries),
        "copied_binaries_to": str(plugin_binaries),
        **refreshed,
    }


def _unreal_plugin_editor_binary_ready(plugin_root: Path) -> dict:
    binary_dir = plugin_root / "Binaries" / _unreal_binary_platform_dir()
    module_marker = binary_dir / "UnrealEditor.modules"
    editor_modules = sorted(binary_dir.glob("UnrealEditor-XACEAdapter.*"))
    ready = module_marker.exists() and any(path.suffix.lower() in {".dll", ".dylib", ".so"} for path in editor_modules)
    return {
        "ready": ready,
        "binary_dir": str(binary_dir),
        "module_marker": str(module_marker),
        "editor_modules": [str(path) for path in editor_modules],
    }


def _build_unreal_plugin_for_editor(plugin_root: Path, unreal_editor: Path) -> dict:
    plugin_file = plugin_root / "XACE.uplugin"
    if not plugin_file.exists():
        return {"ok": False, "error": f"Unreal plugin file not found: {plugin_file}"}

    run_uat = _unreal_run_uat_path(unreal_editor)
    if run_uat is None:
        return {
            "ok": False,
            "error": f"RunUAT was not found for Unreal executable: {unreal_editor}",
        }

    repo_root = Path(__file__).resolve().parents[3]
    package_dir = repo_root / "target-codex-unreal-validation" / "builder-live" / f"XACEBuilt-{int(time.time())}"
    package_dir.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(run_uat),
        "BuildPlugin",
        f"-Plugin={plugin_file}",
        f"-Package={package_dir}",
        f"-TargetPlatforms={_unreal_build_platform()}",
        "-Rocket",
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=str(plugin_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": command,
            "package_dir": str(package_dir),
            "error": "Unreal BuildPlugin timed out after 15 minutes.",
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr),
        }

    return {
        "ok": proc.returncode == 0,
        "command": command,
        "package_dir": str(package_dir),
        "exit_code": proc.returncode,
        "stdout_tail": _tail_text(proc.stdout),
        "stderr_tail": _tail_text(proc.stderr),
        "error": "" if proc.returncode == 0 else "Unreal BuildPlugin failed.",
    }


def _prepare_unreal_validation_runtime(
    project_dir: Path,
    manifest: Any,
    runtime_control: RuntimeControlClient,
    runtime_process: subprocess.Popen | None,
) -> tuple[dict, RuntimeControlClient, subprocess.Popen | None, bool]:
    current = _demo_runtime_status(runtime_control, runtime_process)
    if current.get("running"):
        current.update({
            "ok": True,
            "reused": True,
            "temporary": False,
            "engine_port": 7777,
        })
        return current, runtime_control, runtime_process, False

    repo_root = Path(__file__).resolve().parents[3]
    runtime_bin = _find_runtime_binary(repo_root)
    cgs_path = _project_cgs_path(project_dir, manifest)
    if runtime_bin is None:
        return {"ok": False, "error": "xace_runtime.exe was not found. Build the runtime first."}, runtime_control, None, False
    if not cgs_path.exists():
        return {"ok": False, "error": f"CGS file not found: {cgs_path}"}, runtime_control, None, False

    engine_port = _find_free_tcp_port()
    control_port = _find_free_tcp_port(avoid={engine_port})
    temp_control = RuntimeControlClient(RuntimeControlConfig(
        host="127.0.0.1",
        port=control_port,
        timeout_seconds=2.0,
    ))
    command = _demo_runtime_launch_command(runtime_bin, cgs_path, engine_port, control_port)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        command,
        cwd=str(repo_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    status = _wait_for_runtime_status(temp_control, process, engine_port, timeout_seconds=8.0)
    status.update({
        "ok": bool(status.get("running")),
        "reused": False,
        "temporary": True,
        "runtime_bin": str(runtime_bin),
        "cgs_path": str(cgs_path),
        "command": command,
        "engine_port": engine_port,
        "control_endpoint": temp_control.endpoint,
    })
    if not status.get("running") and not status.get("error"):
        status["error"] = status.get("reason", "Temporary runtime did not answer in time.")
    return status, temp_control, process, True


def _wait_for_runtime_status(
    runtime_control: RuntimeControlClient,
    process: subprocess.Popen | None,
    engine_port: int,
    *,
    timeout_seconds: float,
) -> dict:
    deadline = time.time() + timeout_seconds
    status: dict[str, Any] = {}
    while time.time() < deadline:
        status = _demo_runtime_status(runtime_control, process)
        status["engine_port"] = engine_port
        if status.get("running"):
            return status
        if process is not None and process.poll() is not None:
            status["error"] = f"Runtime exited early with code {process.poll()}."
            return status
        time.sleep(0.25)
    return status


def _run_unreal_live_validation_commandlet(
    engine_root: Path,
    unreal_editor: Path,
    engine_port: int,
) -> dict:
    project_file = _unreal_project_file(engine_root)
    if project_file is None:
        return {"ok": False, "error": f"No .uproject file found in {engine_root}"}

    commandlet_exe = _unreal_commandlet_executable(unreal_editor)
    repo_root = Path(__file__).resolve().parents[3]
    report_dir = repo_root / "target-codex-unreal-validation" / "builder-live"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"unreal_live_validation_{int(time.time())}.json"
    command = [
        str(commandlet_exe),
        str(project_file),
        "-run=XaceLiveValidation",
        f"-XacePort={engine_port}",
        "-XaceSeconds=25",
        f"-XaceOutput={report_path}",
        "-unattended",
        "-nop4",
        "-nosplash",
        "-NullRHI",
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=str(engine_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=240,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": command,
            "report_path": str(report_path),
            "error": "Unreal live validation timed out after 4 minutes.",
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr),
        }

    report: dict[str, Any] = {}
    report_error = ""
    if report_path.exists():
        try:
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                report = loaded
        except (OSError, json.JSONDecodeError) as exc:
            report_error = str(exc)
    else:
        report_error = f"Report was not written: {report_path}"

    ok = proc.returncode == 0 and bool(report.get("ok"))
    error = ""
    if not ok:
        error = str(report.get("error") or report_error or "Unreal live validation failed.")
    return {
        "ok": ok,
        "command": command,
        "report_path": str(report_path),
        "exit_code": proc.returncode,
        "report": report,
        "stdout_tail": _tail_text(proc.stdout),
        "stderr_tail": _tail_text(proc.stderr),
        "error": error,
    }


def _unreal_live_report_summary(report: dict) -> str:
    return (
        "Unreal commandlet passed: "
        f"{_as_int(report.get('applied_snapshots'))} snapshot(s), "
        f"{_as_int(report.get('applied_entities'))} applied entity/entities, "
        f"{_as_int(report.get('input_packets_built'))} input packet(s), "
        f"{_as_int(report.get('feedback_ready'))} feedback message(s), "
        f"{_as_int(report.get('protocol_errors'))} protocol error(s)."
    )


def _resolve_engine_executable(engine_type: str, executable_path: str) -> Path | None:
    executable = Path(executable_path).resolve() if str(executable_path or "").strip() else None
    if executable is not None and executable.exists() and executable.is_file():
        return executable
    detected = _detect_engine_tool(engine_type)
    executable_text = str(detected.get("executable_path") or "")
    executable = Path(executable_text).resolve() if executable_text else None
    if executable is not None and executable.exists() and executable.is_file():
        return executable
    return None


def _unreal_project_file(engine_root: Path) -> Path | None:
    return next(engine_root.glob("*.uproject"), None)


def _unreal_commandlet_executable(unreal_editor: Path) -> Path:
    name = unreal_editor.name.lower()
    if "unrealeditor-cmd" in name:
        return unreal_editor
    if sys.platform == "win32":
        candidate = unreal_editor.with_name("UnrealEditor-Cmd.exe")
        if candidate.exists():
            return candidate
    return unreal_editor


def _unreal_engine_root_from_editor(unreal_editor: Path) -> Path | None:
    for parent in unreal_editor.resolve().parents:
        if parent.name == "Engine":
            return parent
    return None


def _unreal_run_uat_path(unreal_editor: Path) -> Path | None:
    engine_root = _unreal_engine_root_from_editor(unreal_editor)
    if engine_root is None:
        return None
    candidates = [
        engine_root / "Build" / "BatchFiles" / "RunUAT.bat",
        engine_root / "Build" / "BatchFiles" / "RunUAT.sh",
        engine_root / "Build" / "BatchFiles" / "RunUAT.command",
    ]
    return next((path for path in candidates if path.exists()), None)


def _unreal_build_platform() -> str:
    if sys.platform == "win32":
        return "Win64"
    if sys.platform == "darwin":
        return "Mac"
    return "Linux"


def _unreal_binary_platform_dir() -> str:
    return _unreal_build_platform()


def _find_free_tcp_port(host: str = "127.0.0.1", avoid: set[int] | None = None) -> int:
    blocked = avoid or set()
    for _ in range(32):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            port = int(sock.getsockname()[1])
        if port not in blocked:
            return port
    raise RuntimeError("Unable to allocate a free local TCP port.")


def _tail_text(value: Any, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return str(value)[-limit:]


def _three_engine_demo_status(
    project_dir: str | Path,
    manifest: Any,
    engine_paths: dict[str, str],
    runtime_control: RuntimeControlClient | None = None,
    runtime_process: subprocess.Popen | None = None,
) -> dict:
    project_root = Path(project_dir).resolve()
    cgs_path = _project_cgs_path(project_root, manifest)
    repo_root = Path(__file__).resolve().parents[3]
    smoke_tool = repo_root / "tools" / "three_engine_runtime_smoke.py"
    runtime_bin = _find_runtime_binary(repo_root)
    engines = [
        _demo_engine_status("godot", engine_paths.get("godot", "")),
        _demo_engine_status("unity", engine_paths.get("unity", "")),
        _demo_engine_status("unreal", engine_paths.get("unreal", "")),
    ]
    ready_count = sum(1 for item in engines if item.get("ready"))
    installed_count = sum(1 for item in engines if item.get("adapter_installed"))

    return {
        "ok": True,
        "project_dir": str(project_root),
        "cgs_path": str(cgs_path),
        "cgs_exists": cgs_path.exists(),
        "runtime_bin": str(runtime_bin) if runtime_bin else "",
        "runtime_ready": runtime_bin is not None,
        "runtime_status": _demo_runtime_status(runtime_control, runtime_process)
        if runtime_control is not None else None,
        "smoke_tool": str(smoke_tool),
        "smoke_tool_ready": smoke_tool.exists(),
        "engine_tools": _detect_engine_tools(),
        "engines": engines,
        "ready_count": ready_count,
        "adapter_installed_count": installed_count,
        "all_engine_projects_ready": ready_count == 3,
        "all_adapters_installed": installed_count == 3,
        "editor_free_proof_ready": runtime_bin is not None and smoke_tool.exists() and cgs_path.exists(),
        "steps": _three_engine_demo_steps(engines),
    }


def _demo_engine_status(engine_type: str, engine_project_path: str) -> dict:
    label = _engine_label(engine_type)
    result = {
        "engine": engine_type,
        "label": label,
        "path": engine_project_path,
        "ready": False,
        "adapter_installed": False,
        "adapter_path": "",
        "reason": "",
        "next_step": "",
    }
    if not engine_project_path:
        result["reason"] = f"Choose the {label} project folder."
        result["next_step"] = f"Click Browse and select the {label} project folder."
        return result

    engine_root = Path(engine_project_path).resolve()
    result["path"] = str(engine_root)
    if not engine_root.exists() or not engine_root.is_dir():
        result["reason"] = f"{label} project folder was not found."
        result["next_step"] = "Choose the correct project folder."
        return result

    marker_ok, marker_reason = _engine_project_marker_ok(engine_root, engine_type)
    if not marker_ok:
        result["reason"] = marker_reason
        result["next_step"] = "Choose the root folder of the engine project."
        return result

    adapter_path = _engine_adapter_destination(engine_root, engine_type)
    result["adapter_path"] = str(adapter_path)
    result["ready"] = True
    result["adapter_installed"] = _engine_adapter_installed(adapter_path, engine_type)
    if result["adapter_installed"]:
        result["reason"] = f"{label} project and adapter look ready."
        result["next_step"] = "Open this project in the engine and connect it to the runtime."
    else:
        result["reason"] = f"{label} project is valid, but the XACE adapter is not installed there yet."
        result["next_step"] = "Use the Adapter tab to copy the adapter into this engine project."
    return result


def _engine_project_marker_ok(engine_root: Path, engine_type: str) -> tuple[bool, str]:
    if engine_type == "godot":
        marker = engine_root / "project.godot"
        return marker.exists(), f"Godot project.godot was not found at {marker}."
    if engine_type == "unity":
        assets = engine_root / "Assets"
        settings = engine_root / "ProjectSettings"
        ok = assets.exists() and settings.exists()
        return ok, f"Unity Assets and ProjectSettings folders were not found under {engine_root}."
    if engine_type == "unreal":
        ok = any(engine_root.glob("*.uproject"))
        return ok, f"An Unreal .uproject file was not found under {engine_root}."
    return False, f"Unknown engine type: {engine_type}"


def _engine_adapter_installed(adapter_path: Path, engine_type: str) -> bool:
    if engine_type == "godot":
        return (adapter_path / "xace_adapter.gd").exists() and (adapter_path / "plugin.cfg").exists()
    if engine_type == "unity":
        return (adapter_path / "XaceTransport.cs").exists() and (adapter_path / "XACE.Adapter.Unity.asmdef").exists()
    if engine_type == "unreal":
        return (adapter_path / "XACE.uplugin").exists() and (adapter_path / "Source" / "XACEAdapter" / "XACEAdapter.Build.cs").exists()
    return False


def _three_engine_demo_steps(engines: list[dict]) -> list[str]:
    steps = [
        "Run the editor-free proof from Builder to verify one runtime can feed three clients.",
        "Open the Godot, Unity, and Unreal projects after their adapters are installed.",
        "In each engine, set host to 127.0.0.1 and port to 7777.",
        "Start one XACE runtime for three engine clients, then press Play in each engine.",
        "Confirm all three engine windows show the same CGS hash, tick, and snapshot hash.",
    ]
    missing_paths = [item["label"] for item in engines if not item.get("ready")]
    missing_adapters = [item["label"] for item in engines if item.get("ready") and not item.get("adapter_installed")]
    if missing_paths:
        steps.insert(0, f"Choose valid project folders for: {', '.join(missing_paths)}.")
    if missing_adapters:
        steps.insert(1, f"Copy adapters into: {', '.join(missing_adapters)}.")
    return steps


def _start_demo_engine_projects(
    engine_paths: dict[str, str],
    executable_paths: dict[str, str],
) -> list[dict]:
    results: list[dict] = []
    for engine in ("godot", "unity", "unreal"):
        project_path = str(engine_paths.get(engine) or "").strip()
        label = _engine_label(engine)
        if not project_path:
            results.append({
                "ok": False,
                "skipped": True,
                "engine": engine,
                "label": label,
                "reason": f"{label} project folder is not selected.",
            })
            continue

        status = _demo_engine_status(engine, project_path)
        if not status.get("ready"):
            results.append({
                "ok": False,
                "skipped": True,
                "engine": engine,
                "label": label,
                "engine_project_path": project_path,
                "reason": status.get("reason") or f"{label} project folder is not ready.",
            })
            continue

        launch = _launch_engine_project(engine, project_path, executable_paths.get(engine, ""))
        results.append({
            **launch,
            "skipped": False,
            "reason": "Launched." if launch.get("ok") else launch.get("error", "Launch failed."),
        })
    return results


def _demo_runtime_status(
    runtime_control: RuntimeControlClient,
    process: subprocess.Popen | None = None,
) -> dict:
    managed_running = process is not None and process.poll() is None
    result: dict[str, Any] = {
        "ok": True,
        "running": False,
        "managed": managed_running,
        "pid": process.pid if process is not None else None,
        "returncode": process.poll() if process is not None else None,
        "control_endpoint": runtime_control.endpoint,
        "engine_port": 7777,
        "engine_clients": 3,
        "reason": "",
    }
    try:
        ack = runtime_control.send_control("snapshot", session_id="builder-three-engine-demo")
    except (OSError, RuntimeControlError) as exc:
        result["reason"] = (
            "Runtime process is starting; control socket is not ready yet."
            if managed_running else f"No runtime answered at {runtime_control.endpoint}: {exc}"
        )
        return result

    status = ack.get("status", {}) if isinstance(ack, dict) else {}
    if not isinstance(status, dict):
        status = {}
    adapter_type = str(status.get("adapter_type") or "headless")
    connected_engines = _connected_demo_engines(adapter_type)
    bridge_connections = status.get("engine_connections")
    connected_engines = _merge_connected_demo_engines(connected_engines, bridge_connections)
    snapshot = ack.get("snapshot") if isinstance(ack, dict) else None
    snapshot_hash = _snapshot_state_hash(snapshot) if isinstance(snapshot, dict) else ""
    snapshot_tick = snapshot.get("tick") if isinstance(snapshot, dict) else status.get("tick")
    result.update({
        "running": True,
        "tick": status.get("tick"),
        "snapshot_tick": snapshot_tick,
        "alive_count": status.get("alive_count"),
        "engine_connected": status.get("engine_connected"),
        "adapter_type": adapter_type,
        "connected_engines": connected_engines,
        "engine_connections": _demo_engine_connections(
            connected_engines,
            snapshot_tick,
            snapshot_hash,
            bridge_connections,
        ),
        "engine_snapshots_sent": _as_int(status.get("engine_snapshots_sent")),
        "engine_input_packets_received": _as_int(status.get("engine_input_packets_received")),
        "engine_feedback_payloads_received": _as_int(status.get("engine_feedback_payloads_received")),
        "engine_feedback_messages_received": _as_int(status.get("engine_feedback_messages_received")),
        "engine_malformed_messages": _as_int(status.get("engine_malformed_messages")),
        "engine_dropped_inputs": _as_int(status.get("engine_dropped_inputs")),
        "paused": status.get("paused"),
        "step_budget": status.get("step_budget"),
        "snapshot_hash": snapshot_hash,
        "state_hash": status.get("state_hash") or status.get("last_hash") or snapshot_hash,
        "reason": ack.get("reason", "Runtime is running."),
    })
    return result


def _start_demo_runtime(
    project_dir: Path,
    manifest: Any,
    runtime_control: RuntimeControlClient,
    process: subprocess.Popen | None = None,
    *,
    engine_port: int = 7777,
) -> tuple[dict, subprocess.Popen | None]:
    current = _demo_runtime_status(runtime_control, process)
    if current.get("running"):
        current.update({"ok": True, "already_running": True})
        return current, process
    if process is not None and process.poll() is None:
        current.update({"ok": True, "starting": True})
        return current, process

    repo_root = Path(__file__).resolve().parents[3]
    runtime_bin = _find_runtime_binary(repo_root)
    cgs_path = _project_cgs_path(project_dir, manifest)
    if runtime_bin is None:
        return {"ok": False, "error": "xace_runtime.exe was not found. Build the runtime first."}, process
    if not cgs_path.exists():
        return {"ok": False, "error": f"CGS file not found: {cgs_path}"}, process

    control_port = int(runtime_control.endpoint.rsplit(":", 1)[-1])
    command = _demo_runtime_launch_command(runtime_bin, cgs_path, engine_port, control_port)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    started = subprocess.Popen(
        command,
        cwd=str(repo_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    time.sleep(0.35)
    status = _demo_runtime_status(runtime_control, started)
    status.update({
        "ok": True,
        "started": True,
        "runtime_bin": str(runtime_bin),
        "cgs_path": str(cgs_path),
        "command": command,
    })
    return status, started


def _demo_runtime_launch_command(
    runtime_bin: Path,
    cgs_path: Path,
    engine_port: int,
    control_port: int,
) -> list[str]:
    return [
        str(runtime_bin),
        "--cgs",
        str(cgs_path),
        "--port",
        str(engine_port),
        "--engine-clients",
        "3",
        "--control-port",
        str(control_port),
        "--no-wait",
        "--live-engine-accept",
        "--quiet",
    ]


def _connected_demo_engines(adapter_type: str) -> list[str]:
    value = adapter_type.strip().lower()
    if value.startswith("multi(") and value.endswith(")"):
        value = value[len("multi("):-1]
        names = [item.strip() for item in value.split(",")]
    else:
        names = [value]
    allowed = {"godot", "unity", "unreal"}
    connected: list[str] = []
    for name in names:
        if name in allowed and name not in connected:
            connected.append(name)
    return connected


def _merge_connected_demo_engines(connected_engines: list[str], bridge_connections: Any) -> list[str]:
    out = list(connected_engines)
    for engine in _bridge_stats_by_engine(bridge_connections):
        if engine not in out:
            out.append(engine)
    return [engine for engine in ("godot", "unity", "unreal") if engine in out]


def _demo_engine_connections(
    connected_engines: list[str],
    tick: Any,
    snapshot_hash: str,
    bridge_connections: Any = None,
) -> list[dict]:
    connected = set(connected_engines)
    bridge_stats = _bridge_stats_by_engine(bridge_connections)
    return [
        ({
            "engine": engine,
            "label": _engine_label(engine),
            "connected": engine in connected or bool(bridge_stats.get(engine, {}).get("connected")),
            "tick": tick if engine in connected else None,
            "snapshot_hash": snapshot_hash if engine in connected else "",
        } | _bridge_engine_stats(bridge_stats.get(engine, {})))
        for engine in ("godot", "unity", "unreal")
    ]


def _bridge_stats_by_engine(bridge_connections: Any) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    if not isinstance(bridge_connections, list):
        return stats
    numeric_fields = [
        "snapshots_sent",
        "input_packets_received",
        "feedback_payloads_received",
        "feedback_messages_received",
        "malformed_messages",
        "dropped_inputs",
        "queued_inputs",
        "queued_feedback",
    ]
    for raw in bridge_connections:
        if not isinstance(raw, dict):
            continue
        for engine in _connected_demo_engines(str(raw.get("adapter_type") or "")):
            current = stats.setdefault(engine, {"connected": False})
            current["connected"] = bool(current.get("connected")) or bool(raw.get("connected"))
            for field in numeric_fields:
                current[field] = _as_int(current.get(field)) + _as_int(raw.get(field))
    return stats


def _bridge_engine_stats(stats: dict) -> dict:
    return {
        "snapshots_sent": _as_int(stats.get("snapshots_sent")),
        "input_packets_received": _as_int(stats.get("input_packets_received")),
        "feedback_payloads_received": _as_int(stats.get("feedback_payloads_received")),
        "feedback_messages_received": _as_int(stats.get("feedback_messages_received")),
        "malformed_messages": _as_int(stats.get("malformed_messages")),
        "dropped_inputs": _as_int(stats.get("dropped_inputs")),
        "queued_inputs": _as_int(stats.get("queued_inputs")),
        "queued_feedback": _as_int(stats.get("queued_feedback")),
    }


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _demo_live_validation_status(demo_status: dict, automation: dict[str, dict] | None = None) -> dict:
    automation = automation or {}
    runtime = demo_status.get("runtime_status") if isinstance(demo_status, dict) else {}
    if not isinstance(runtime, dict):
        runtime = {}
    runtime_running = bool(runtime.get("running"))
    runtime_reported = runtime_running and bool(runtime.get("control_endpoint"))
    connections = runtime.get("engine_connections")
    connection_by_engine = {
        str(item.get("engine")): item
        for item in connections
        if isinstance(connections, list) and isinstance(item, dict)
    } if isinstance(connections, list) else {}
    unreal_sdk = _detect_unreal_netfxsdk()

    rows: list[dict] = []
    engine_statuses = demo_status.get("engines", []) if isinstance(demo_status, dict) else []
    for engine_status in engine_statuses:
        if not isinstance(engine_status, dict):
            continue
        engine = str(engine_status.get("engine") or "").strip().lower()
        if engine not in {"godot", "unity", "unreal"}:
            continue
        connection = connection_by_engine.get(engine, {})
        steps = _live_validation_steps_for_engine(
            engine,
            engine_status,
            connection,
            runtime_running,
            runtime_reported,
            unreal_sdk,
            automation.get(engine, {}),
        )
        ready = all(bool(step.get("ok")) for step in steps)
        rows.append({
            "engine": engine,
            "label": _engine_label(engine),
            "ready": ready,
            "connected": bool(connection.get("connected")),
            "next_step": _live_validation_next_step(engine, steps),
            "steps": steps,
        })

    passed = sum(1 for row in rows if row.get("ready"))
    total = len(rows) or 3
    all_ready = passed == total
    return {
        "ok": all_ready,
        "runtime": runtime,
        "unreal_prerequisite": unreal_sdk,
        "automation": automation,
        "passed_count": passed,
        "engine_count": total,
        "engines": rows,
        "summary": f"{passed}/{total} engines have live adapter proof.",
        "next_step": "All live checks passed."
        if all_ready else (
            "Start Runtime, launch the engine projects, press Play, then check live validation again."
            if not runtime_running else "Open any missing engine project, press Play, and wait a few ticks."
        ),
    }


def _live_validation_steps_for_engine(
    engine: str,
    engine_status: dict,
    connection: dict,
    runtime_running: bool,
    runtime_reported: bool,
    unreal_sdk: dict,
    automation: dict | None = None,
) -> list[dict]:
    automation = automation if isinstance(automation, dict) else {}
    report = automation.get("report") if isinstance(automation.get("report"), dict) else {}
    automated_unreal_ok = engine == "unreal" and bool(automation.get("ok"))
    connected = bool(connection.get("connected"))
    snapshots_sent = _as_int(connection.get("snapshots_sent"))
    input_packets = _as_int(connection.get("input_packets_received"))
    feedback_messages = _as_int(connection.get("feedback_messages_received"))
    malformed = _as_int(connection.get("malformed_messages"))
    project_ready = bool(engine_status.get("ready"))
    adapter_ready = bool(engine_status.get("adapter_installed"))

    steps = [
        _live_step(
            "project",
            "Engine project folder",
            project_ready,
            engine_status.get("reason") or f"{_engine_label(engine)} project folder is valid.",
        ),
        _live_step(
            "adapter",
            "Adapter installed",
            adapter_ready,
            "XACE adapter files are installed in the engine project."
            if adapter_ready else engine_status.get("next_step") or "Copy the adapter into this engine project.",
        ),
    ]
    if engine == "unreal":
        steps.append(_live_step(
            "prerequisite",
            ".NET Framework SDK",
            bool(unreal_sdk.get("ok")),
            unreal_sdk.get("reason", ""),
        ))
        if automation:
            steps.append(_live_step(
                "automation",
                "Automatic Unreal commandlet",
                bool(automation.get("ok")),
                automation.get("summary")
                or automation.get("reason")
                or automation.get("next_step")
                or "Builder can run the Unreal commandlet from the dashboard.",
            ))
    steps.extend([
        _live_step(
            "runtime",
            "Runtime status reaches Builder",
            runtime_reported or automated_unreal_ok,
            "Builder can read the runtime control status."
            if runtime_reported else (
                "Builder started a temporary runtime for the Unreal commandlet."
                if automated_unreal_ok else "Start Runtime from Builder first."
            ),
        ),
        _live_step(
            "connect",
            "Adapter connected",
            connected or (engine == "unreal" and bool(report.get("connected"))),
            f"{_engine_label(engine)} is connected to the shared runtime."
            if connected else (
                "Unreal commandlet connected to the runtime."
                if engine == "unreal" and bool(report.get("connected"))
                else f"Launch {_engine_label(engine)}, open the project, and press Play."
            ),
        ),
        _live_step(
            "snapshot",
            "Snapshot received",
            connected and snapshots_sent > 0
            or (engine == "unreal" and _as_int(report.get("applied_snapshots")) > 0),
            f"Runtime sent {snapshots_sent} snapshot frame(s) to this adapter."
            if snapshots_sent > 0 else (
                f"Unreal commandlet applied {_as_int(report.get('applied_snapshots'))} snapshot(s)."
                if engine == "unreal" and _as_int(report.get("applied_snapshots")) > 0
                else "Wait a few ticks after the adapter connects."
            ),
        ),
        _live_step(
            "input",
            "Input sent back",
            connected and input_packets > 0
            or (engine == "unreal" and _as_int(report.get("input_packets_built")) > 0),
            f"Runtime received {input_packets} input packet(s) from this adapter."
            if input_packets > 0 else (
                f"Unreal commandlet built {_as_int(report.get('input_packets_built'))} input packet(s)."
                if engine == "unreal" and _as_int(report.get("input_packets_built")) > 0
                else "Click the engine window and press a movement/action key."
            ),
        ),
        _live_step(
            "feedback",
            "Feedback sent back",
            connected and feedback_messages > 0 and malformed == 0
            or (
                engine == "unreal"
                and _as_int(report.get("feedback_ready")) > 0
                and _as_int(report.get("protocol_errors")) == 0
            ),
            f"Runtime accepted {feedback_messages} feedback message(s) from this adapter."
            if feedback_messages > 0 else (
                f"Unreal commandlet queued {_as_int(report.get('feedback_ready'))} feedback message(s)."
                if engine == "unreal" and _as_int(report.get("feedback_ready")) > 0
                else "Wait a few ticks; the adapter reports after applying runtime state."
            ),
        ),
        _live_step(
            "delta",
            "Entity/transform applied",
            connected and snapshots_sent > 0 and feedback_messages > 0 and malformed == 0
            or (
                engine == "unreal"
                and _as_int(report.get("applied_entities")) > 0
                and _as_int(report.get("protocol_errors")) == 0
            ),
            "Adapter feedback is emitted only after runtime state is applied to engine entities."
            if feedback_messages > 0 else (
                f"Unreal commandlet applied {_as_int(report.get('applied_entities'))} entity/entities."
                if engine == "unreal" and _as_int(report.get("applied_entities")) > 0
                else "No adapter apply feedback has reached the runtime yet."
            ),
        ),
    ])
    return steps


def _live_step(step_id: str, label: str, ok: bool, detail: Any) -> dict:
    return {
        "id": step_id,
        "label": label,
        "ok": bool(ok),
        "detail": str(detail or ""),
    }


def _live_validation_next_step(engine: str, steps: list[dict]) -> str:
    for step in steps:
        if step.get("ok"):
            continue
        step_id = step.get("id")
        if step_id == "project":
            return f"Choose the {_engine_label(engine)} project folder."
        if step_id == "adapter":
            return f"Copy the XACE adapter into the {_engine_label(engine)} project."
        if step_id == "prerequisite":
            return _detect_unreal_netfxsdk().get("next_step", "Install the Unreal prerequisite.")
        if step_id == "automation":
            return "Run Check Live Validation again; Builder will prepare Unreal and run the commandlet."
        if step_id == "runtime":
            return "Click Start Runtime in Builder."
        if step_id == "connect":
            return f"Launch {_engine_label(engine)} and press Play."
        if step_id == "input":
            return f"Click the {_engine_label(engine)} game window and press a movement/action key."
        return "Wait a few ticks, then check live validation again."
    return "Live validation passed."


def _detect_unreal_netfxsdk() -> dict:
    label = ".NET Framework SDK 4.6+"
    if sys.platform != "win32":
        return {
            "ok": True,
            "label": label,
            "detected": True,
            "skipped": True,
            "reason": "This Unreal prerequisite check is only needed on Windows.",
            "next_step": "",
        }

    roots = []
    for env_key in ("ProgramFiles(x86)", "ProgramFiles"):
        value = os.environ.get(env_key)
        if value:
            roots.append(Path(value))
    candidates: list[Path] = []
    for root in roots:
        for sdk_root in (
            root / "Microsoft SDKs" / "NETFXSDK",
            root / "Windows Kits" / "NETFXSDK",
        ):
            if sdk_root.exists():
                candidates.extend(sorted(path for path in sdk_root.iterdir() if path.is_dir()))

    found: tuple[tuple[int, int, int], Path] | None = None
    for candidate in candidates:
        version = _parse_netfxsdk_version(candidate.name)
        marker = candidate / "Include" / "um" / "mscoree.h"
        if version >= (4, 6, 0) and marker.exists():
            if found is None or version > found[0]:
                found = (version, candidate)

    if found is not None:
        version, path = found
        version_text = f"{version[0]}.{version[1]}" if version[2] == 0 else ".".join(str(part) for part in version)
        return {
            "ok": True,
            "label": label,
            "detected": True,
            "version": version_text,
            "path": str(path),
            "reason": f"Unreal prerequisite found: .NET Framework SDK {version_text}.",
            "next_step": "",
        }

    return {
        "ok": False,
        "label": label,
        "detected": False,
        "version": "",
        "path": "",
        "checked_paths": [str(path) for path in candidates[:12]],
        "reason": "Unreal live validation needs the .NET Framework SDK 4.6 or newer before the editor/plugin build can run.",
        "next_step": "Open Visual Studio Installer > Modify > Individual components, install .NET Framework SDK 4.6 or newer, then reopen Builder.",
    }


def _parse_netfxsdk_version(value: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for segment in value.lower().removeprefix("v").split("."):
        digits = "".join(ch for ch in segment if ch.isdigit())
        if digits:
            parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


def _snapshot_state_hash(snapshot: dict) -> str:
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _stop_demo_runtime(
    runtime_control: RuntimeControlClient,
    process: subprocess.Popen | None = None,
) -> dict:
    status = _demo_runtime_status(runtime_control, process)
    if not status.get("running") and not (process is not None and process.poll() is None):
        status.update({"ok": True, "stopped": True, "reason": "Runtime was already stopped."})
        return status

    shutdown_error = ""
    try:
        runtime_control.send_control("shutdown", session_id="builder-three-engine-demo")
    except (OSError, RuntimeControlError) as exc:
        shutdown_error = str(exc)

    if process is not None and process.poll() is None:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    stopped = process is None or process.poll() is not None
    return {
        "ok": stopped,
        "running": False,
        "managed": process is not None,
        "pid": process.pid if process is not None else None,
        "returncode": process.poll() if process is not None else None,
        "control_endpoint": runtime_control.endpoint,
        "engine_port": 7777,
        "engine_clients": 3,
        "stopped": stopped,
        "reason": "Runtime stopped." if stopped else "Runtime stop was requested.",
        "error": "" if stopped else shutdown_error,
    }


def _run_three_engine_smoke(project_dir: Path, manifest: Any | None = None) -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    smoke_tool = repo_root / "tools" / "three_engine_runtime_smoke.py"
    runtime_bin = _find_runtime_binary(repo_root)
    cgs_path = _project_cgs_path(project_dir, manifest) if manifest is not None else project_dir / "game.cgs.json"
    if not smoke_tool.exists():
        return {"ok": False, "error": f"Smoke tool not found: {smoke_tool}"}
    if runtime_bin is None:
        return {"ok": False, "error": "xace_runtime.exe was not found. Build the runtime first."}
    if not cgs_path.exists():
        return {"ok": False, "error": f"CGS file not found: {cgs_path}"}

    command = [
        sys.executable,
        str(smoke_tool),
        "--runtime-bin",
        str(runtime_bin),
        "--cgs",
        str(cgs_path),
    ]
    completed = subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    parsed = {}
    for line in reversed(completed.stdout.splitlines()):
        try:
            parsed = json.loads(line)
            break
        except Exception:
            continue
    return {
        "ok": completed.returncode == 0 and bool(parsed.get("ok", False)),
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "result": parsed,
        "error": "" if completed.returncode == 0 else (completed.stderr.strip() or completed.stdout.strip()),
    }


def _run_multiplayer_product_smoke() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    package_dir = repo_root / "packages" / "network-core"
    if not (repo_root / "Cargo.toml").exists() or not package_dir.exists():
        return {
            "ok": False,
            "kind": "cargo_test",
            "error": "Network core cargo test target was not found.",
            "steps": _multiplayer_smoke_steps(False),
        }

    commands = [
        [
            "cargo",
            "test",
            "-p",
            "xace-network-core",
            "--target-dir",
            "target-codex-network-smoke",
            "networked_runtime_smoke_is_deterministic_across_arrival_orders",
        ],
        [
            "cargo",
            "test",
            "-p",
            "xace-network-core",
            "--target-dir",
            "target-codex-network-smoke",
            "x10_039",
        ],
        [
            "cargo",
            "test",
            "-p",
            "xace-network-core",
            "--target-dir",
            "target-codex-network-smoke",
            "x10_040",
        ],
        [
            "cargo",
            "test",
            "-p",
            "xace-network-core",
            "--target-dir",
            "target-codex-network-smoke",
            "x10_041",
        ],
    ]
    results = []
    try:
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            results.append({
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            })
    except FileNotFoundError:
        return {
            "ok": False,
            "kind": "cargo_test",
            "commands": commands,
            "error": "cargo was not found on PATH.",
            "steps": _multiplayer_smoke_steps(False),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "kind": "cargo_test",
            "commands": commands,
            "error": "Network primitives smoke timed out after 120 seconds.",
            "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "steps": _multiplayer_smoke_steps(False),
        }

    ok = all(result["returncode"] == 0 for result in results)
    stdout = "\n".join(str(result.get("stdout") or "") for result in results)[-4000:]
    stderr = "\n".join(str(result.get("stderr") or "") for result in results)[-4000:]
    error = ""
    if not ok:
        failed = next((result for result in results if result["returncode"] != 0), results[-1] if results else {})
        error = str(failed.get("stderr") or failed.get("stdout") or "Network primitives smoke failed.").strip()
    return {
        "ok": ok,
        "kind": "cargo_test",
        "command": commands[0],
        "commands": commands,
        "results": results,
        "returncode": 0 if ok else 1,
        "stdout": stdout,
        "stderr": stderr,
        "steps": _multiplayer_smoke_steps(ok),
        "error": error,
    }


def _build_multiplayer_diagnostics_panel() -> dict:
    """
    Build the deterministic Builder diagnostics payload for the selected
    host/client lockstep launch topology.

    Runtime-facing capture lives in xace-network-core diagnostics; this Python
    payload mirrors that schema so the Builder panel and server contract can be
    verified without opening an engine editor.
    """
    return {
        "schema": "xace.multiplayer_diagnostics_snapshot.v1",
        "topology_id": "host_client_authoritative_lockstep_v1",
        "session": {
            "mode": "Host",
            "phase": "Live",
            "tick": 42,
            "paused": False,
            "peer_total": 2,
            "live_peers": 2,
            "ready_peers": [1, 2],
            "required_input_peers": [1, 2],
            "compatibility_required": True,
            "compatibility_ok": True,
        },
        "peers": [
            {
                "peer_id": 1,
                "player_id": 101,
                "display_name": "Host Player",
                "state": "Live",
                "ready": True,
                "latency_ms": 16,
                "jitter_ms": 2,
                "packet_loss_ppm": 0,
                "last_seen_tick": 42,
                "last_input_tick": 41,
                "last_sequence_id": 41,
                "buffered_input_packets": 0,
                "missing_input_ranges": [],
                "authoritative_entities": [501],
            },
            {
                "peer_id": 2,
                "player_id": 102,
                "display_name": "Client Player",
                "state": "Live",
                "ready": True,
                "latency_ms": 96,
                "jitter_ms": 12,
                "packet_loss_ppm": 25000,
                "last_seen_tick": 42,
                "last_input_tick": 39,
                "last_sequence_id": 39,
                "buffered_input_packets": 1,
                "missing_input_ranges": [{"from_tick": 40, "to_tick": 41}],
                "authoritative_entities": [502],
            },
        ],
        "ticks": {
            "session_tick": 42,
            "simulation_tick": 42,
            "input_tick": 42,
            "last_released_tick": 41,
            "missing_peers": [2],
            "can_release": False,
        },
        "input_buffers": {
            "total_packet_count": 1,
            "accepted_count": 82,
            "duplicate_count": 1,
            "rejected_count": 1,
            "per_peer": [
                {
                    "peer_id": 1,
                    "buffered_packets": 0,
                    "missing_input_ranges": [],
                    "has_input_for_current_tick": True,
                },
                {
                    "peer_id": 2,
                    "buffered_packets": 1,
                    "missing_input_ranges": [{"from_tick": 40, "to_tick": 41}],
                    "has_input_for_current_tick": False,
                },
            ],
        },
        "latency": {
            "recommended_delay_ticks": 4,
            "worst_peer": 2,
            "max_rtt_ms": 96,
            "max_jitter_ms": 12,
            "max_packet_loss_ppm": 25000,
        },
        "rollback": {
            "rollback_count": 1,
            "pending": False,
            "latest_restore_tick": 39,
            "latest_target_tick": 41,
            "latest_completed_tick": 42,
            "latest_reason": "desync_recovery",
        },
        "resync": [
            {
                "peer_id": 2,
                "state": "AwaitingAck",
                "mode": "DeltaFromSnapshot",
                "snapshot_tick": 39,
                "target_tick": 42,
                "attempts": 1,
                "expected_hash": "authoritative-hash",
                "completed_tick": None,
                "failure_reason": None,
            }
        ],
        "hash_comparisons": [
            {
                "tick": 42,
                "expected_hash": "authoritative-hash",
                "majority_hash": "authoritative-hash",
                "matching_peers": [1],
                "divergent_peers": [{"peer_id": 2, "hash": "divergent-hash"}],
                "missing_peers": [],
            }
        ],
        "authority": [
            {
                "entity_id": 501,
                "owner_peer": 1,
                "fallback_peer": None,
                "shared_peers": [],
                "scope": "Exclusive",
                "version": 10,
                "transfer_locked": False,
            },
            {
                "entity_id": 502,
                "owner_peer": 2,
                "fallback_peer": 1,
                "shared_peers": [],
                "scope": "Exclusive",
                "version": 10,
                "transfer_locked": False,
            },
        ],
        "chaos_report": {
            "scenario": "deterministic_diagnostics_fixture",
            "packet_loss_ppm": 25000,
            "jitter_ms": 12,
            "missing_input_ranges": [{"peer_id": 2, "from_tick": 40, "to_tick": 41}],
            "divergent_hash_peer": 2,
            "resync_status": "AwaitingAck",
            "boundary": "Panel diagnostic fixture only; 4-16 client chaos/soak certification remains X10-043.",
        },
    }


def _multiplayer_smoke_steps(ok: bool) -> list[dict]:
    suffix = "Verified by network-core primitives smoke." if ok else "Run the smoke again after fixing the reported test error."
    return [
        {
            "id": "session_lifecycle",
            "label": "Lobby/session lifecycle",
            "ok": ok,
            "detail": f"Create, join, ready state, leave, reconnect, late join, player identity, and teardown are covered by the X10-039 lifecycle test. {suffix}",
        },
        {
            "id": "session_compatibility",
            "label": "Session compatibility gate",
            "ok": ok,
            "detail": f"Schema, SGC plan, adapter version, assets, packages, provider-free metadata, and template mismatches block session start in the X10-040 mismatch matrix. {suffix}",
        },
        {
            "id": "malicious_input_limits",
            "label": "Malicious input limits",
            "ok": ok,
            "detail": f"Rate limits, packet validation, replay/sequence checks, authority checks, and cheat-guard policy block bad packets before synchroniser mutation in the X10-041 matrix. {suffix}",
        },
        {
            "id": "host_client",
            "label": "Host/client session",
            "ok": ok,
            "detail": f"Host reaches live through lobby readiness with two identified peers; client waits on the server peer. {suffix}",
        },
        {
            "id": "lockstep",
            "label": "Lockstep input",
            "ok": ok,
            "detail": f"Ticks release only after every required peer input arrives. {suffix}",
        },
        {
            "id": "prediction",
            "label": "Prediction and reconciliation",
            "ok": ok,
            "detail": f"Client prediction remains within reconciliation tolerance. {suffix}",
        },
        {
            "id": "desync",
            "label": "Desync detection",
            "ok": ok,
            "detail": f"Intentional divergent peer hash is detected at the comparison tick. {suffix}",
        },
        {
            "id": "determinism",
            "label": "Deterministic final hash",
            "ok": ok,
            "detail": f"Normal and flipped input arrival orders produce the same smoke digest. {suffix}",
        },
    ]


def _launch_certification_status() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    tool = repo_root / "tools" / "certify_launch.py"
    package_json = repo_root / "package.json"
    script_ready = False
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            script_ready = "xace:certify" in dict(data.get("scripts") or {})
        except Exception:
            script_ready = False
    command = [sys.executable, str(tool), "--quick"]
    return {
        "ok": tool.exists() and script_ready,
        "tool": str(tool),
        "tool_ready": tool.exists(),
        "npm_script_ready": script_ready,
        "command": command,
        "label": "Quick launch certification",
        "detail": (
            "Ready to run editor-free runtime, Builder, bridge, multiplayer, and save replay checks."
            if tool.exists() and script_ready
            else "Certification command is not ready yet."
        ),
    }


def _run_launch_certification_quick() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    status = _launch_certification_status()
    if not status.get("tool_ready"):
        return {
            "ok": False,
            "error": f"Certification tool not found: {status.get('tool', '')}",
            "status": status,
            "steps": [],
        }

    command = [sys.executable, str(repo_root / "tools" / "certify_launch.py"), "--quick"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": command,
            "status": status,
            "error": "Quick certification timed out after 180 seconds.",
            "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "steps": _certification_steps_from_output(exc.stdout if isinstance(exc.stdout, str) else ""),
        }

    return {
        "ok": completed.returncode == 0,
        "command": command,
        "status": status,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "steps": _certification_steps_from_output(completed.stdout),
        "error": "" if completed.returncode == 0 else (completed.stderr.strip() or completed.stdout.strip()),
    }


def _certification_steps_from_output(output: str) -> list[dict]:
    steps: list[dict] = []
    for line in output.splitlines():
        if line.startswith("[certify] PASS "):
            label = line.removeprefix("[certify] PASS ").split(" (", 1)[0].strip()
            steps.append({
                "label": label,
                "ok": True,
                "detail": line,
            })
        elif line.startswith("[certify] FAIL "):
            label = line.removeprefix("[certify] FAIL ").split(" (", 1)[0].strip()
            steps.append({
                "label": label,
                "ok": False,
                "detail": line,
            })
    return steps


def _detect_engine_tools() -> list[dict]:
    return [
        _detect_engine_tool("godot"),
        _detect_engine_tool("unity"),
        _detect_engine_tool("unreal"),
    ]


def _detect_engine_tool(engine_type: str) -> dict:
    label = _engine_label(engine_type)
    candidates = _engine_executable_candidates(engine_type)
    found = next((path for path in candidates if path.exists() and path.is_file()), None)
    return {
        "engine": engine_type,
        "label": label,
        "detected": found is not None,
        "executable_path": str(found) if found else "",
        "candidates": [str(path) for path in candidates[:12]],
        "reason": f"{label} executable found." if found else f"{label} executable was not found automatically.",
    }


def _engine_executable_candidates(engine_type: str) -> list[Path]:
    names = {
        "godot": ["godot", "godot4", "Godot", "Godot_v4.3-stable_win64.exe", "Godot_v4.2-stable_win64.exe"],
        "unity": ["Unity", "Unity.exe"],
        "unreal": ["UnrealEditor", "UnrealEditor.exe"],
    }.get(engine_type, [])
    candidates: list[Path] = []

    env_key = {
        "godot": "XACE_GODOT_EXE",
        "unity": "XACE_UNITY_EXE",
        "unreal": "XACE_UNREAL_EXE",
    }.get(engine_type, "")
    if env_key and os.environ.get(env_key):
        candidates.append(Path(os.environ[env_key]))

    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    if sys.platform == "win32":
        program_files = [Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
        if os.environ.get("ProgramFiles(x86)"):
            program_files.append(Path(os.environ["ProgramFiles(x86)"]))
        if engine_type == "godot":
            for root in program_files:
                candidates.extend([
                    root / "Godot" / "Godot.exe",
                    root / "Godot" / "Godot_v4.3-stable_win64.exe",
                    root / "Godot" / "Godot_v4.2-stable_win64.exe",
                ])
        elif engine_type == "unity":
            for root in program_files:
                candidates.extend(sorted((root / "Unity" / "Hub" / "Editor").glob("*/Editor/Unity.exe")))
                candidates.append(root / "Unity" / "Editor" / "Unity.exe")
        elif engine_type == "unreal":
            for root in program_files:
                candidates.extend(sorted((root / "Epic Games").glob("UE_*/Engine/Binaries/Win64/UnrealEditor.exe")))
    elif sys.platform == "darwin":
        if engine_type == "godot":
            candidates.append(Path("/Applications/Godot.app/Contents/MacOS/Godot"))
        elif engine_type == "unity":
            candidates.extend(sorted(Path("/Applications/Unity/Hub/Editor").glob("*/Unity.app/Contents/MacOS/Unity")))
        elif engine_type == "unreal":
            candidates.extend(sorted(Path("/Users/Shared/Epic Games").glob("UE_*/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor")))
    else:
        if engine_type == "godot":
            candidates.extend([Path("/usr/bin/godot"), Path("/usr/local/bin/godot")])
        elif engine_type == "unity":
            candidates.extend(sorted(Path.home().glob("Unity/Hub/Editor/*/Editor/Unity")))
        elif engine_type == "unreal":
            candidates.extend(sorted(Path.home().glob("UnrealEngine/Engine/Binaries/Linux/UnrealEditor")))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate)
        if text not in seen:
            unique.append(candidate)
            seen.add(text)
    return unique


def _launch_engine_project(engine_type: str, engine_project_path: str, executable_path: str) -> dict:
    if engine_type not in {"godot", "unity", "unreal"}:
        return {"ok": False, "error": f"Unknown engine: {engine_type}"}
    if engine_type == "unreal":
        prerequisite = _detect_unreal_netfxsdk()
        if not prerequisite.get("ok"):
            return {
                "ok": False,
                "engine": engine_type,
                "label": _engine_label(engine_type),
                "error": prerequisite.get("reason", "Unreal prerequisite is missing."),
                "next_step": prerequisite.get("next_step", ""),
                "prerequisite": prerequisite,
            }

    engine_root = Path(engine_project_path).resolve()
    marker_ok, marker_reason = _engine_project_marker_ok(engine_root, engine_type)
    if not engine_root.exists() or not engine_root.is_dir():
        return {"ok": False, "engine": engine_type, "error": f"Engine project folder not found: {engine_root}"}
    if not marker_ok:
        return {"ok": False, "engine": engine_type, "error": marker_reason}

    executable = Path(executable_path).resolve() if executable_path else None
    if executable is None or not executable.exists():
        detected = _detect_engine_tool(engine_type)
        executable_text = str(detected.get("executable_path") or "")
        executable = Path(executable_text).resolve() if executable_text else None
    if executable is None or not executable.exists() or not executable.is_file():
        return {
            "ok": False,
            "engine": engine_type,
            "error": f"{_engine_label(engine_type)} executable was not found. Install the engine or paste the executable path.",
        }

    command = _engine_launch_command(engine_type, executable, engine_root)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        command,
        cwd=str(engine_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    return {
        "ok": True,
        "engine": engine_type,
        "label": _engine_label(engine_type),
        "engine_project_path": str(engine_root),
        "executable_path": str(executable),
        "command": [str(item) for item in command],
    }


def _engine_launch_command(engine_type: str, executable: Path, engine_root: Path) -> list[str]:
    if engine_type == "godot":
        return [str(executable), "--path", str(engine_root)]
    if engine_type == "unity":
        return [str(executable), "-projectPath", str(engine_root)]
    if engine_type == "unreal":
        project_file = next(engine_root.glob("*.uproject"), None)
        if project_file is None:
            raise FileNotFoundError(f"No .uproject file found in {engine_root}")
        return [str(executable), str(project_file)]
    return [str(executable)]


def _project_cgs_path(project_root: Path, manifest: Any) -> Path:
    raw = str(getattr(manifest, "cgs_path", "") or "game.cgs.json")
    cgs_path = Path(raw)
    if not cgs_path.is_absolute():
        cgs_path = project_root / cgs_path
    return cgs_path.resolve()


def _find_runtime_binary(repo_root: Path) -> Path | None:
    candidates = [
        repo_root / "target-codex-three-engine" / "debug" / "xace_runtime.exe",
        repo_root / "target-codex-xace-godot-dev" / "debug" / "xace_runtime.exe",
        repo_root / "target-codex-runtime-feedback" / "debug" / "xace_runtime.exe",
        repo_root / "target" / "debug" / "xace_runtime.exe",
    ]
    if sys.platform != "win32":
        candidates.extend([
            repo_root / "target-codex-three-engine" / "debug" / "xace_runtime",
            repo_root / "target" / "debug" / "xace_runtime",
        ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _engine_label(engine_type: str) -> str:
    if engine_type == "godot":
        return "Godot"
    if engine_type == "unity":
        return "Unity"
    if engine_type == "unreal":
        return "Unreal"
    return engine_type.title()


def _engine_adapter_destination(engine_root: Path, engine_type: str) -> Path:
    key = engine_type.strip().lower()
    if key == "godot":
        return engine_root / "addons" / "xace"
    if key == "unity":
        return engine_root / "Assets" / "XACE"
    if key == "unreal":
        return engine_root / "Plugins" / "XACE"
    return engine_root / ".xace" / "adapter" / key


def _engine_adapter_destination_label(engine_type: str) -> str:
    key = engine_type.strip().lower()
    if key == "godot":
        return "addons/xace"
    if key == "unity":
        return "Assets/XACE"
    if key == "unreal":
        return "Plugins/XACE"
    return f".xace/adapter/{key}"


def _engine_adapter_steps(engine_type: str) -> list[str]:
    key = engine_type.strip().lower()
    if key == "godot":
        return [
            "Choose the folder that contains project.godot.",
            "XACE copies the Godot adapter into addons/xace.",
            "In Godot, enable Project > Project Settings > Plugins > XACE Adapter.",
            "Use Setup Godot Scene to create scenes/xace_runtime_scene.tscn, or instance XaceAdapter in your own scene.",
        ]
    if key == "unity":
        return [
            "Choose the Unity project folder.",
            "XACE copies the Unity adapter package into Assets/XACE.",
            "Return to Unity and let it recompile the scripts.",
            "Use Tools > XACE > Create Runtime Object to add the scene components.",
        ]
    if key == "unreal":
        return [
            "Choose the Unreal project folder.",
            "XACE copies the Unreal adapter plugin into Plugins/XACE.",
            "Reopen or rebuild the Unreal project so Unreal discovers the plugin.",
            "Add XACE components to an Actor: Transport, Input Collector, and Delta Applicator.",
        ]
    return ["No engine adapter steps are needed for this project type."]


def _engine_adapter_target_path(destination: Path, engine_type: str, relative_path: str) -> Path:
    key = engine_type.strip().lower()
    path = Path(relative_path)
    if key == "unreal":
        if relative_path.endswith(".h"):
            return destination / "Source" / "XACEAdapter" / "Public" / path.name
        if relative_path.endswith(".cpp"):
            return destination / "Source" / "XACEAdapter" / "Private" / path.name
        return destination / path
    return destination / path


def _should_copy_engine_adapter_file(
    engine_type: str,
    relative_path: str,
    target_path: Path,
    overwrite: bool,
) -> bool:
    if overwrite:
        return True
    if not target_path.exists():
        return True
    return False


def _write_godot_addon_scene(source_path: Path, target_path: Path) -> None:
    text = source_path.read_text(encoding="utf-8")
    text = text.replace('path="res://xace_godot_main.gd"', 'path="res://addons/xace/xace_godot_main.gd"')
    target_path.write_text(text, encoding="utf-8")


def _write_godot_plugin_files(destination: Path, overwrite: bool) -> bool:
    plugin_cfg = destination / "plugin.cfg"
    plugin_script = destination / "xace_editor_plugin.gd"
    if not overwrite and (plugin_cfg.exists() or plugin_script.exists()):
        return False
    plugin_cfg.write_text(
        "\n".join([
            "[plugin]",
            "",
            'name="XACE Adapter"',
            'description="Connects a Godot project to the XACE runtime."',
            'author="XACE"',
            'version="0.1.0"',
            'script="xace_editor_plugin.gd"',
            "",
        ]),
        encoding="utf-8",
    )
    plugin_script.write_text(
        "\n".join([
            "@tool",
            "extends EditorPlugin",
            "",
            "",
            "func _enter_tree() -> void:",
            "\tpass",
            "",
            "",
            "func _exit_tree() -> void:",
            "\tpass",
            "",
        ]),
        encoding="utf-8",
    )
    return True


def _write_unreal_plugin_files(destination: Path, overwrite: bool) -> dict:
    generated = [
        ("XACE.uplugin", _unreal_uplugin_text()),
        ("Source/XACEAdapter/XACEAdapter.Build.cs", _unreal_build_cs_text()),
        ("Source/XACEAdapter/Public/XACEAdapterModule.h", _unreal_module_h_text()),
        ("Source/XACEAdapter/Private/XACEAdapterModule.cpp", _unreal_module_cpp_text()),
    ]
    copied: list[str] = []
    skipped: list[str] = []
    for relative_path, text in generated:
        target = destination / relative_path
        if target.exists() and not overwrite:
            skipped.append(relative_path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        copied.append(relative_path)
    return {"copied": copied, "skipped": skipped}


def _unreal_uplugin_text() -> str:
    return json.dumps({
        "FileVersion": 3,
        "Version": 1,
        "VersionName": "0.1.0",
        "FriendlyName": "XACE Adapter",
        "Description": "Connects Unreal projects to the XACE runtime.",
        "Category": "Gameplay",
        "CreatedBy": "XACE",
        "CanContainContent": False,
        "IsBetaVersion": True,
        "Modules": [
            {
                "Name": "XACEAdapter",
                "Type": "Runtime",
                "LoadingPhase": "Default",
            },
        ],
    }, indent=2) + "\n"


def _unreal_build_cs_text() -> str:
    return "\n".join([
        "using UnrealBuildTool;",
        "",
        "public class XACEAdapter : ModuleRules",
        "{",
        "    public XACEAdapter(ReadOnlyTargetRules Target) : base(Target)",
        "    {",
        "        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;",
        "",
        "        PublicDependencyModuleNames.AddRange(new string[]",
        "        {",
        "            \"Core\",",
        "            \"CoreUObject\",",
        "            \"Engine\",",
        "            \"InputCore\",",
        "            \"Json\",",
        "            \"Sockets\",",
        "            \"Networking\",",
        "            \"UMG\"",
        "        });",
        "    }",
        "}",
        "",
    ])


def _unreal_module_h_text() -> str:
    return "\n".join([
        "#pragma once",
        "",
        "#include \"Modules/ModuleManager.h\"",
        "",
        "class FXACEAdapterModule : public IModuleInterface",
        "{",
        "public:",
        "    virtual void StartupModule() override;",
        "    virtual void ShutdownModule() override;",
        "};",
        "",
    ])


def _unreal_module_cpp_text() -> str:
    return "\n".join([
        "#include \"XACEAdapterModule.h\"",
        "",
        "#include \"Modules/ModuleManager.h\"",
        "",
        "IMPLEMENT_MODULE(FXACEAdapterModule, XACEAdapter)",
        "",
        "void FXACEAdapterModule::StartupModule()",
        "{",
        "}",
        "",
        "void FXACEAdapterModule::ShutdownModule()",
        "{",
        "}",
        "",
    ])


def _godot_runtime_scene_text() -> str:
    return "\n".join([
        "[gd_scene load_steps=2 format=3]",
        "",
        '[ext_resource type="Script" path="res://addons/xace/xace_godot_main.gd" id="1"]',
        "",
        '[node name="XaceRuntimeScene" type="Node3D"]',
        'script = ExtResource("1")',
        "",
    ])


def _set_godot_main_scene(project_file: Path, scene_resource: str) -> bool:
    text = project_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    main_scene_line = f'run/main_scene="{scene_resource}"'
    for index, line in enumerate(lines):
        if line.strip().startswith("run/main_scene="):
            if line.strip() == main_scene_line:
                return False
            lines[index] = main_scene_line
            project_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True

    for index, line in enumerate(lines):
        if line.strip() == "[application]":
            insert_at = index + 1
            while insert_at < len(lines) and not lines[insert_at].strip().startswith("["):
                insert_at += 1
            lines.insert(insert_at, main_scene_line)
            project_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True

    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(["[application]", "", main_scene_line])
    project_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _is_within(root: Path, child: Path) -> bool:
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_source_checkout_project(project_dir: str | Path) -> str:
    root = Path(project_dir).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    looks_like_source_checkout = (
        (root / "Cargo.toml").exists()
        and (root / "packages" / "builder-workspace").exists()
        and (root / "packages" / "runtime-core").exists()
    )
    if root == repo_root or looks_like_source_checkout:
        return f"Choose or create a game project folder, not the XACE source checkout: {root}"
    return ""


def _empty_cgs() -> dict:
    return {
        "metadata": {
            "name": "New Project", "cgs_hash": "0" * 64,
            "version": "0.1.0", "schema_version": "0.1.0",
        },
        "global_systems": [], "modes": [],
    }


# ── Entrypoint ────────────────────────────────────────────────────────────────

def _is_loopback_ws(ws: WebSocket) -> bool:
    client = ws.client
    if client is None:
        return False
    return client.host in {"127.0.0.1", "::1", "localhost"}


def _is_loopback_http(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    return client.host in {"127.0.0.1", "::1", "localhost"}


def _launcher_state_path() -> Path:
    configured = os.environ.get(LAUNCHER_STATE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".xace" / "launcher_state.json").resolve()


def _remember_launcher_project(project_dir: str | Path) -> None:
    try:
        root = Path(project_dir).resolve()
        state_path = _launcher_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({
                "last_project": str(root),
                "updated_at_epoch": int(time.time()),
            }, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        log.debug("Could not update launcher state for project %s", project_dir, exc_info=True)


def _default_shell() -> str:
    if sys.platform == "win32":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "/bin/bash")


def _pick_folder_dialog(title: str, initial_path: str) -> str:
    initial = initial_path if Path(initial_path).exists() else str(Path.home())
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _folder_picker_subprocess_script(),
            title,
            initial,
        ],
        cwd=str(Path.home()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=600.0,
        check=False,
    )
    output = (completed.stdout or "").strip()
    if not output:
        error = (completed.stderr or "").strip()
        raise RuntimeError(error or "Folder picker did not return a result.")
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Folder picker returned unreadable output: {output[:160]}") from exc
    if not data.get("ok"):
        raise RuntimeError(str(data.get("error") or "Folder picker is unavailable."))
    selected = str(data.get("path") or "")
    return str(Path(selected).resolve()) if selected else ""


def _folder_picker_subprocess_script() -> str:
    return r'''
import json
import sys
from pathlib import Path

title = sys.argv[1] if len(sys.argv) > 1 else "Choose folder"
initial = sys.argv[2] if len(sys.argv) > 2 else str(Path.home())

try:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    selected = filedialog.askdirectory(
        title=title,
        initialdir=initial if Path(initial).exists() else str(Path.home()),
        mustexist=False,
    )
    try:
        root.update_idletasks()
    finally:
        root.destroy()
    path = str(Path(selected).resolve()) if selected else ""
    print(json.dumps({"ok": True, "path": path}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
    raise SystemExit(2)
'''


def _generated_adapter_files(engine_type: str) -> dict[str, str]:
    key = engine_type.strip().lower()
    if key == 'godot':
        return {
            'plugin.cfg': '\n'.join([
                '[plugin]',
                '',
                'name="XACE Adapter"',
                'description="Connects a Godot project to the XACE runtime."',
                'author="XACE"',
                'version="0.1.0"',
                'script="xace_editor_plugin.gd"',
                '',
            ]),
            'xace_editor_plugin.gd': '\n'.join([
                '@tool',
                'extends EditorPlugin',
                '',
                '',
                'func _enter_tree() -> void:',
                '\tpass',
                '',
                '',
                'func _exit_tree() -> void:',
                '\tpass',
                '',
            ]),
        }
    if key == 'unreal':
        return {
            'XACE.uplugin': _unreal_uplugin_text(),
            'Source/XACEAdapter/XACEAdapter.Build.cs': _unreal_build_cs_text(),
            'Source/XACEAdapter/Public/XACEAdapterModule.h': _unreal_module_h_text(),
            'Source/XACEAdapter/Private/XACEAdapterModule.cpp': _unreal_module_cpp_text(),
        }
    return {}


def _copy_named_adapter_to_engine_project(
    project_dir: str | Path,
    manifest: Any,
    engine_type: str,
    engine_project_path: str,
    *,
    overwrite: bool,
    save_primary_config: bool = False,
) -> dict:
    key = engine_type.strip().lower()
    if key == 'headless':
        return {
            'ok': True,
            'status': 'not_applicable',
            'code': 'ADAPTER_NOT_APPLICABLE',
            'target': key,
            'skipped': True,
            'unsupported': False,
            'reason': 'Headless projects do not need an engine adapter.',
            'action': 'Choose Godot, Unity, or Unreal as the project engine before copying an adapter.',
        }
    if key not in EXPORT_TARGETS:
        return {
            'ok': False,
            'target': key,
            'error': f'Unknown adapter target: {engine_type}',
            'targets': sorted(EXPORT_TARGETS),
        }

    engine_root = Path(engine_project_path).resolve()
    if not engine_root.exists() or not engine_root.is_dir():
        return {'ok': False, 'target': key, 'error': f'Engine project folder not found: {engine_root}'}
    marker_ok, marker_reason = _engine_project_marker_ok(engine_root, key)
    if not marker_ok:
        return {'ok': False, 'target': key, 'error': marker_reason}

    status = _adapter_status(project_dir, key)
    if not status.get('healthy'):
        _install_project_adapter(project_dir, key)
        status = _adapter_status(project_dir, key)
    if not status.get('healthy'):
        return {
            'ok': False,
            'target': key,
            'error': 'Prepared adapter is missing files. Use Repair Adapter first.',
            'adapter_status': status,
        }

    adapter_root = Path(str(status['path'])).resolve()
    destination = _engine_adapter_destination(engine_root, key)
    if not _is_within(engine_root, destination):
        return {
            'ok': False,
            'target': key,
            'error': f'Refusing to install adapter outside engine project: {destination}',
        }

    try:
        install_result = install_or_update_adapter(
            source_root=adapter_root,
            engine_project_root=engine_root,
            engine_type=key,
            destination=destination,
            overwrite=overwrite,
            generated_files=_generated_adapter_files(key),
            metadata={'builder_endpoint': '/api/project/adapter/install-engine'},
        )
    except AdapterInstallationError as exc:
        return {'ok': False, 'target': key, 'error': str(exc)}

    demo_projects = dict(manifest.adapter_config.get('demo_engine_projects', {}) or {})
    demo_projects[key] = str(engine_root)
    manifest.adapter_config['demo_engine_projects'] = demo_projects
    demo_install_paths = dict(manifest.adapter_config.get('demo_engine_adapter_install_paths', {}) or {})
    demo_install_paths[key] = str(install_result['destination_path'])
    manifest.adapter_config['demo_engine_adapter_install_paths'] = demo_install_paths
    if save_primary_config:
        manifest.adapter_config['engine_project_path'] = str(engine_root)
        manifest.adapter_config['engine_adapter_install_path'] = str(install_result['destination_path'])
    save_manifest(project_dir, manifest)

    install_result['steps'] = _engine_adapter_steps(key)
    return install_result


def _rollback_adapter_in_engine_project(
    project_dir: str | Path,
    manifest: Any,
    engine_project_path: str,
) -> dict:
    key = str(manifest.engine_type).strip().lower()
    root = _resolve_engine_project_root(manifest, engine_project_path)
    if not root['ok']:
        return {'ok': False, 'target': key, 'error': root['error']}
    engine_root = Path(root['path'])
    marker_ok, marker_reason = _engine_project_marker_ok(engine_root, key)
    if not marker_ok:
        return {'ok': False, 'target': key, 'error': marker_reason}
    destination = _engine_adapter_destination(engine_root, key)
    try:
        result = rollback_latest_adapter_transaction(
            engine_project_root=engine_root,
            engine_type=key,
            destination=destination,
        )
    except AdapterInstallationError as exc:
        return {'ok': False, 'target': key, 'error': str(exc)}
    result['steps'] = _engine_adapter_steps(key)
    return result


def _uninstall_adapter_from_engine_project(
    project_dir: str | Path,
    manifest: Any,
    engine_project_path: str,
) -> dict:
    key = str(manifest.engine_type).strip().lower()
    root = _resolve_engine_project_root(manifest, engine_project_path)
    if not root['ok']:
        return {'ok': False, 'target': key, 'error': root['error']}
    engine_root = Path(root['path'])
    marker_ok, marker_reason = _engine_project_marker_ok(engine_root, key)
    if not marker_ok:
        return {'ok': False, 'target': key, 'error': marker_reason}
    destination = _engine_adapter_destination(engine_root, key)
    try:
        result = uninstall_adapter(
            engine_project_root=engine_root,
            engine_type=key,
            destination=destination,
        )
    except AdapterInstallationError as exc:
        return {'ok': False, 'target': key, 'error': str(exc)}
    if result.get('ok'):
        if manifest.adapter_config.get('engine_project_path') == str(engine_root):
            manifest.adapter_config.pop('engine_adapter_install_path', None)
        install_paths = dict(manifest.adapter_config.get('demo_engine_adapter_install_paths', {}) or {})
        if install_paths.get(key) == str(destination):
            install_paths.pop(key, None)
            manifest.adapter_config['demo_engine_adapter_install_paths'] = install_paths
        save_manifest(project_dir, manifest)
    result['steps'] = _engine_adapter_steps(key)
    return result


def _resolve_engine_project_root(manifest: Any, engine_project_path: str) -> dict:
    configured = str(engine_project_path or '').strip()
    if not configured:
        configured = str((manifest.adapter_config or {}).get('engine_project_path') or '').strip()
    if not configured:
        return {'ok': False, 'error': 'Engine project path is required.'}
    engine_root = Path(configured).resolve()
    if not engine_root.exists() or not engine_root.is_dir():
        return {'ok': False, 'error': f'Engine project folder not found: {engine_root}'}
    return {'ok': True, 'path': str(engine_root)}


def main() -> None:
    parser = argparse.ArgumentParser(description="XACE Builder Server")
    parser.add_argument(
        "--project", default="./project",
        help="Path to the XACE project directory (containing game.cgs.json)",
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="Port to listen on (default: 8765)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--static-dir", default="../builder-workspace/dist",
        help="Path to built TypeScript output",
    )
    parser.add_argument(
        "--dev", action="store_true",
        help="Enable CORS for Vite dev server on localhost:5173",
    )
    parser.add_argument(
        "--log-level", default="info",
        choices=["debug", "info", "warning", "error"],
    )
    # ── Phase 14.5: real inference + SGC ─────────────────────────────────────
    parser.add_argument(
        "--api-key", default="",
        help=(
            "Hosted provider API key for real LLM calls. "
            "Saved to local machine settings outside XACE project files."
        ),
    )
    parser.add_argument(
        "--sgc-bin", default="",
        help=(
            "Path to compiled System Graph Compiler binary. "
            "If provided, SGC is run after each structural mutation to "
            "recompile the ExecutionPlan. If omitted, structural prompt applies are blocked."
        ),
    )
    parser.add_argument(
        "--model-provider", default="auto",
        choices=["auto", "ollama", "anthropic", "openai", "google", "moonshot"],
        help=(
            "LLM provider: 'auto' (default local Ollama auto-select), "
            "'ollama', 'anthropic', 'openai', 'google', or 'moonshot'."
        ),
    )
    parser.add_argument(
        "--model", default="",
        help=(
            "Model name. Use 'auto' for local Ollama auto-resolution, or a provider's exact model id. "
            "Run 'ollama list' to see available models. "
            "For hosted providers: use the provider's exact model id."
        ),
    )
    parser.add_argument(
        "--ollama-url", default="http://localhost:11434",
        help="Ollama server URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--runtime-host", default="127.0.0.1",
        help="Host for xace_runtime control socket (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--runtime-control-port", type=int, default=7778,
        help="Port for xace_runtime control socket (default: 7778)",
    )
    parser.add_argument(
        "--runtime-control-timeout", type=float, default=2.0,
        help="Seconds to wait for runtime control responses (default: 2.0)",
    )
    args = parser.parse_args()

    logging.getLogger().setLevel(args.log_level.upper())

    # ── Provider launch overrides ─────────────────────────────────────────────
    if args.api_key and args.model_provider == "auto":
        args.model_provider = "anthropic"
        log.info("--api-key without --model-provider defaults to Anthropic for compatibility")
    if args.api_key:
        log.info("Hosted API key provided; it will be saved to local machine settings")
    elif args.model_provider in {"anthropic", "openai", "google", "moonshot"}:
        log.info("Hosted provider selected; Builder will use the saved local key if present")
    else:
        log.info("Using local provider; no hosted API key required")

    # ── Resolve paths ─────────────────────────────────────────────────────────

    project = os.path.abspath(args.project)
    static  = os.path.abspath(args.static_dir)
    sgc_bin = os.path.abspath(args.sgc_bin) if args.sgc_bin else ""

    log.info("=" * 58)
    log.info("XACE Builder Server  (Phase 14.5)")
    log.info("  Project:    %s", project)
    log.info("  Static dir: %s", static)
    log.info("  Mode:       %s", "development" if args.dev else "production")
    log.info("  Listening:  http://%s:%d", args.host, args.port)
    log.info("  Provider:   %s", args.model_provider)
    log.info("  Runtime ctl:%s:%d", args.runtime_host, args.runtime_control_port)
    if args.model_provider in ("auto", "ollama"):
        log.info("  Ollama URL: %s", args.ollama_url)
        log.info("  Model:      %s", args.model or "auto")
    else:
        log.info("  Model:      %s", args.model or "saved/default")
        log.info("  Key source: %s", "launch argument" if args.api_key else "local settings")
    log.info("  SGC:        %s", sgc_bin if sgc_bin else "not configured; structural prompt applies block")
    if args.dev:
        log.info("  Dev UI:     http://localhost:5173")
    log.info("=" * 58)

    app = create_app(
        project_path    = project,
        static_dir      = static,
        dev_mode        = args.dev,
        sgc_bin         = sgc_bin,
        model_provider  = args.model_provider,
        model_name      = args.model,
        ollama_url      = args.ollama_url,
        api_key         = args.api_key,
        runtime_host    = args.runtime_host,
        runtime_control_port = args.runtime_control_port,
        runtime_control_timeout = args.runtime_control_timeout,
    )

    uvicorn.run(
        app,
        host               = args.host,
        port               = args.port,
        log_level          = args.log_level,
        ws_ping_interval   = 20,
        ws_ping_timeout    = 30,
        access_log         = args.dev,
    )


if __name__ == "__main__":
    main()

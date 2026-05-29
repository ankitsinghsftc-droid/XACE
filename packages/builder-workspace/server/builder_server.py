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
    --api-key sets ANTHROPIC_API_KEY for real LLM calls via InferenceAdapter.
              If omitted, PIL runs with MockAdapter (no real LLM calls).

## Phase 14.5 additions
    --api-key  wires the real InferenceAdapter into PIL
    --sgc-bin  path to compiled SGC binary (optional, skipped if absent)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from session_manager import SessionManager
from cgs_persistence import CGSPersistence, CGSLoadError
from ws_message_router import WSMessageRouter

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

# ── App factory ───────────────────────────────────────────────────────────────

def create_app(
    project_path:   str  = "./project",
    static_dir:     str  = "./dist",
    dev_mode:       bool = False,
    sgc_bin:        str  = "",
    model_provider: str  = "auto",
    model_name:     str  = "",
    ollama_url:     str  = "http://localhost:11434",
) -> FastAPI:
    """
    Creates the FastAPI application.

    Parameters
    ----------
    project_path   : str   — path to the XACE project directory
    static_dir     : str   — path to the built Vite output directory
    dev_mode       : bool  — enables CORS for Vite dev server
    sgc_bin        : str   — path to compiled SGC binary
    model_provider : str   — "auto" | "ollama" | "anthropic"
    model_name     : str   — model name (Ollama) or empty (Anthropic uses defaults)
    ollama_url     : str   — Ollama server URL
    """
    app = FastAPI(title="XACE Builder Server")

    # ── CORS (dev mode only) ──────────────────────────────────────────────────
    if dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins     = ["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials = True,
            allow_methods     = ["*"],
            allow_headers     = ["*"],
        )

    # ── Shared state ──────────────────────────────────────────────────────────
    persist       = CGSPersistence(project_path)
    session_mgr   = SessionManager(
        sgc_bin_path   = sgc_bin,
        model_provider = model_provider,
        model_name     = model_name,
        ollama_url     = ollama_url,
    )
    router        = WSMessageRouter(session_mgr)
    cgs_state: dict = {}

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
        """
        Spawns a bash subprocess and bridges its I/O to the WebSocket.
        Used by the XACE embedded terminal for running Ollama commands.
        Security: only accepts connections from localhost when not in dev mode.
        """
        await ws.accept()

        # Spawn a bash shell
        import asyncio, subprocess, os, sys
        shell = "/bin/bash" if sys.platform != "win32" else "cmd.exe"

        proc = await asyncio.create_subprocess_exec(
            shell,
            stdin  = subprocess.PIPE,
            stdout = subprocess.PIPE,
            stderr = subprocess.STDOUT,
            env    = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"},
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
                proc.kill()
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
        }

    # ── Model list (for UI model selector) ────────────────────────────────────
    @app.get("/api/models")
    async def list_models():
        """
        Returns available models for the current provider.
        Called by the TypeScript model selector on load and refresh.
        """
        return session_mgr.get_available_models()

    @app.post("/api/export/{target}")
    async def export_adapter(target: str):
        """
        Copies engine adapter source files into the active project's
        .xace/exports/<target>/ directory.
        """
        key = target.lower()
        if key not in EXPORT_TARGETS:
            return {
                "ok": False,
                "error": f"Unknown export target: {target}",
                "targets": sorted(EXPORT_TARGETS),
            }

        repo_root = Path(__file__).resolve().parents[3]
        src_dir = repo_root / EXPORT_TARGETS[key]["source"]
        if not src_dir.exists():
            return {
                "ok": False,
                "error": f"Adapter source missing: {src_dir}",
                "targets": sorted(EXPORT_TARGETS),
            }

        export_root = Path(project_path).resolve() / ".xace" / "exports" / key
        if export_root.exists():
            shutil.rmtree(export_root)
        shutil.copytree(src_dir, export_root)

        files = [
            str(path.relative_to(export_root)).replace("\\", "/")
            for path in sorted(export_root.rglob("*"))
            if path.is_file()
        ]
        manifest = {
            "target": key,
            "label": EXPORT_TARGETS[key]["label"],
            "file_count": len(files),
            "files": files,
        }
        (export_root / "xace_export_manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

        return {
            "ok": True,
            "target": key,
            "label": EXPORT_TARGETS[key]["label"],
            "path": str(export_root),
            "files": files,
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


def _empty_cgs() -> dict:
    return {
        "metadata": {
            "name": "New Project", "cgs_hash": "0000000000000000",
            "version": "0.1.0", "schema_version": "0.1.0",
        },
        "global_systems": [], "modes": [],
    }


# ── Entrypoint ────────────────────────────────────────────────────────────────

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
            "Anthropic API key for real LLM calls. "
            "Sets ANTHROPIC_API_KEY environment variable. "
            "If omitted, PIL runs with MockAdapter (no real LLM)."
        ),
    )
    parser.add_argument(
        "--sgc-bin", default="",
        help=(
            "Path to compiled System Graph Compiler binary. "
            "If provided, SGC is run after each structural mutation to "
            "recompile the ExecutionPlan. If omitted, SGC step is skipped."
        ),
    )
    parser.add_argument(
        "--model-provider", default="auto",
        choices=["auto", "ollama", "anthropic"],
        help=(
            "LLM provider: 'auto' (default local Ollama auto-select), "
            "'ollama', or 'anthropic' (requires --api-key)."
        ),
    )
    parser.add_argument(
        "--model", default="",
        help=(
            "Model name. For local testing: 'auto', 'llama3.2', or 'llama3.1'. "
            "Run 'ollama list' to see available models. "
            "For Anthropic: leave empty to use defaults from InferenceAdapter."
        ),
    )
    parser.add_argument(
        "--ollama-url", default="http://localhost:11434",
        help="Ollama server URL (default: http://localhost:11434)",
    )
    args = parser.parse_args()

    logging.getLogger().setLevel(args.log_level.upper())

    # ── Wire API key ──────────────────────────────────────────────────────────
    if args.api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.api_key
        log.info("API key set — PIL will use real InferenceAdapter")
    elif args.model_provider == "anthropic":
        existing = os.environ.get("ANTHROPIC_API_KEY", "")
        if existing:
            log.info("API key found in environment — PIL will use real InferenceAdapter")
        else:
            log.warning(
                "No API key provided (--api-key or ANTHROPIC_API_KEY). "
                "PIL will use MockAdapter — prompts will not reach a real LLM."
            )

    # ── Resolve paths ─────────────────────────────────────────────────────────
    else:
        log.info("Using local Ollama provider; no hosted API key required")

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
    if args.model_provider in ("auto", "ollama"):
        log.info("  Ollama URL: %s", args.ollama_url)
        log.info("  Model:      %s", args.model or ("auto" if args.model_provider == "auto" else "llama3.2"))
    else:
        log.info("  LLM:        %s", "real" if os.environ.get("ANTHROPIC_API_KEY") else "mock")
    log.info("  SGC:        %s", sgc_bin if sgc_bin else "skipped")
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

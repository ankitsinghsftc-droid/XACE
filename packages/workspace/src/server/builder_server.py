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
    ↓ Browser sends pil_apply → CGS updated → cgs_update broadcast

## Running

    python builder_server.py --project /path/to/project [--port 8765] [--dev]

    --dev flag enables CORS for the Vite dev server (localhost:5173).

## Multiple Sessions

    Each browser tab creates a session_id. Up to MAX_SESSIONS=8 can be
    active simultaneously. Oldest idle session is evicted at capacity.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from packages.workspace.src.server.session_manager import SessionManager
from packages.workspace.src.server.cgs_persistence import CGSPersistence, CGSLoadError
from packages.workspace.src.server.ws_message_router import WSMessageRouter

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt = "%H:%M:%S",
)
log = logging.getLogger("xace.server")

# ── App factory ───────────────────────────────────────────────────────────────

def create_app(
    project_path: str  = "./project",
    static_dir:   str  = "./dist",
    dev_mode:     bool = False,
) -> FastAPI:
    """
    Creates the FastAPI application.

    Parameters
    ----------
    project_path : str   — path to the XACE project directory (contains game.cgs.json)
    static_dir   : str   — path to the built Vite output directory
    dev_mode     : bool  — enables CORS for Vite dev server
    """
    app = FastAPI(
        title       = "XACE Builder Server",
        description = "Bridges the XACE TypeScript UI and Python PIL backend.",
        version     = "0.1.0",
        docs_url    = "/api/docs" if dev_mode else None,
    )

    # CORS — only in dev mode (Vite runs on a different port)
    if dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins     = ["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials = True,
            allow_methods     = ["*"],
            allow_headers     = ["*"],
        )

    # ── Shared state ──────────────────────────────────────────────────────────
    session_manager = SessionManager()
    router          = WSMessageRouter(session_manager)
    persist         = CGSPersistence(project_path)

    # Each session has its own in-memory CGS copy.
    # session_cgs[session_id] = current CGS dict (mutated on pil_apply)
    session_cgs: dict[str, dict] = {}

    # ── WebSocket endpoint ────────────────────────────────────────────────────

    @app.websocket("/ws/{session_id}")
    async def ws_endpoint(ws: WebSocket, session_id: str) -> None:
        await ws.accept()
        log.info("WS connected: session=%s", session_id[:12])

        # Create a typed send function for this connection
        async def send(message: dict) -> None:
            try:
                await ws.send_text(json.dumps(message, default=str))
            except Exception as exc:
                log.debug("WS send failed (probably disconnected): %s", exc)

        # Initialise session
        session = await session_manager.get_or_create(
            session_id   = session_id,
            send_fn      = send,
            project_path = project_path,
        )

        # Initialise per-session CGS state
        if session_id not in session_cgs:
            try:
                cgs = persist.load()
            except CGSLoadError as exc:
                log.warning("CGS not found, using empty: %s", exc)
                cgs = _empty_cgs()
            session_cgs[session_id] = cgs

        # Send session_init immediately
        cgs      = session_cgs[session_id]
        cgs_hash = cgs.get("metadata", {}).get("cgs_hash", "")
        snapshots = persist.list_snapshots(limit=50)

        await send({
            "type":       "session_init",
            "session_id": session_id,
            "cgs":        cgs,
            "hash":       cgs_hash,
            "snapshots":  [s.to_dict() for s in snapshots],
            "version":    cgs.get("metadata", {}).get("schema_version", "0.0.0"),
        })

        # ── Message loop ──────────────────────────────────────────────────────
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError as exc:
                    await send({
                        "type": "server_error",
                        "code": "INVALID_JSON",
                        "message": f"Malformed JSON: {exc}",
                    })
                    continue

                await router.route(
                    session_id = session_id,
                    message    = message,
                    send_fn    = send,
                    persist    = persist,
                    cgs_state  = session_cgs.setdefault(session_id, _empty_cgs()),
                )

        except WebSocketDisconnect:
            log.info("WS disconnected: session=%s", session_id[:12])
            session_manager.mark_disconnected(session_id)
            # Persist current CGS on disconnect
            try:
                if session_id in session_cgs:
                    persist.save(session_cgs[session_id])
            except Exception as exc:
                log.warning("CGS auto-save on disconnect failed: %s", exc)

        except Exception as exc:
            log.exception("WS handler error for session %s: %s", session_id[:12], exc)
            try:
                await send({
                    "type":    "server_error",
                    "code":    "FATAL",
                    "message": f"Server error: {str(exc)[:200]}",
                })
            except Exception:
                pass

    # ── REST endpoints ────────────────────────────────────────────────────────

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status":        "ok",
            "sessions":      session_manager.session_count,
            "project_path":  project_path,
        }

    # ── Static file serving (production) ─────────────────────────────────────

    static_path = Path(static_dir)
    if static_path.exists():
        # Serve Vite build output
        app.mount("/assets", StaticFiles(directory=str(static_path / "assets")), name="assets")

        @app.get("/")
        async def serve_index() -> FileResponse:
            return FileResponse(str(static_path / "index.html"))

        @app.get("/{path:path}")
        async def serve_spa(path: str) -> FileResponse:
            """Serve index.html for all non-asset routes (SPA routing)."""
            requested = static_path / path
            if requested.exists() and requested.is_file():
                return FileResponse(str(requested))
            return FileResponse(str(static_path / "index.html"))
    else:
        @app.get("/")
        async def serve_placeholder() -> HTMLResponse:
            return HTMLResponse(
                "<h2>XACE Builder</h2>"
                "<p>Run <code>npm run build</code> in packages/builder-workspace "
                "to build the UI, then restart the server.</p>"
                "<p>In development, run <code>npm run dev</code> and open "
                "<a href='http://localhost:5173'>localhost:5173</a> instead.</p>"
            )

    return app


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_cgs() -> dict[str, Any]:
    return {
        "metadata": {
            "name":           "New Project",
            "cgs_hash":       "0" * 64,
            "version":        "0.1.0",
            "schema_version": "0.1.0",
        },
        "global_systems": [],
        "modes": [],
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
    args = parser.parse_args()

    logging.getLogger().setLevel(args.log_level.upper())

    project = os.path.abspath(args.project)
    static  = os.path.abspath(args.static_dir)

    log.info("=" * 58)
    log.info("XACE Builder Server")
    log.info("  Project:    %s", project)
    log.info("  Static dir: %s", static)
    log.info("  Mode:       %s", "development" if args.dev else "production")
    log.info("  Listening:  http://%s:%d", args.host, args.port)
    if args.dev:
        log.info("  Dev UI:     http://localhost:5173")
    log.info("=" * 58)

    app = create_app(
        project_path = project,
        static_dir   = static,
        dev_mode     = args.dev,
    )

    uvicorn.run(
        app,
        host      = args.host,
        port      = args.port,
        log_level = args.log_level,
        ws_ping_interval   = 20,
        ws_ping_timeout    = 30,
        access_log = args.dev,  # only log HTTP access in dev mode
    )


if __name__ == "__main__":
    main()

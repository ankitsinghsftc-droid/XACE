"""
session_manager.py — Builder Session Manager (Phase 14.5)
==========================================================
Maintains one PILPipeline instance per connected WebSocket session.

## Phase 14.5 changes vs Phase 14
    - _create_pipeline() now builds the REAL InferenceAdapter when
      ANTHROPIC_API_KEY is set in the environment.
    - SessionManager accepts sgc_bin_path for SGC recompilation.
    - _build_real_adapter() constructs InferenceAdapter with all 7 deps.
      Falls back to _MockAdapter if packages/inference is not importable.
    - BuilderSession gains a gde_orchestrator field (GDEOrchestrator per session).

## Thread Safety
    All session state mutations happen in the asyncio thread.
    PIL calls happen in the executor (separate threads).
    The streaming adapter fires WebSocket callbacks from the PIL thread
    back to the event loop via run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

# ── Resolve package paths ─────────────────────────────────────────────────────
# Walks up from this file's location until it finds a directory that
# contains "prompt-intelligence" — the packages root. This handles:
#   packages/builder-server/session_manager.py   (correct)
#   packages/builder-workspace/server/...         (common mistake on Windows)

def _find_packages_root() -> str:
    candidate = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
    for _ in range(6):
        if os.path.isdir(os.path.join(candidate, "prompt-intelligence")):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    # Fallback: one level up from this file
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_PKGS    = _find_packages_root()
_PIL_SRC = os.path.join(_PKGS, "prompt-intelligence", "src")
_GDE_SRC = os.path.join(_PKGS, "gde")
_INF_SRC = os.path.join(_PKGS, "inference", "src")
_SF_SRC  = os.path.join(_PKGS, "schema-factory", "src")

log.info("Packages root resolved: %s", _PKGS)
log.debug("  PIL: %s (found=%s)", _PIL_SRC, os.path.isdir(_PIL_SRC))
log.debug("  GDE: %s (found=%s)", _GDE_SRC, os.path.isdir(_GDE_SRC))

sys.path.insert(0, _PIL_SRC)
for _sub in (
    "intent_intake", "context_assembler", "llm_orchestrator",
    "output_parser", "validation_loop", "critique_engine",
    "clarification_engine", "mutation_planner", "safety_scope_guard",
    "memory_model", "history_manager", "memory", "mode_controller",
):
    sys.path.insert(0, os.path.join(_PIL_SRC, _sub))
sys.path.insert(0, _INF_SRC)

# ── PIL import ────────────────────────────────────────────────────────────────

try:
    from pil_pipeline import PILPipeline  # type: ignore[import]
    log.info("PIL imported successfully")
except ImportError as e:
    log.warning("PIL not importable: %s", e)
    PILPipeline = None  # type: ignore[assignment,misc]

# ── GDE import ────────────────────────────────────────────────────────────────

_GDE_AVAILABLE = False
_GDEOrchestrator = None  # type: ignore[assignment]

try:
    sys.path.insert(0, _GDE_SRC)
    from src.gde_orchestrator import GDEOrchestrator, GDEResult  # type: ignore[import]
    _GDE_AVAILABLE = True
    _GDEOrchestrator = GDEOrchestrator
    log.info("GDE imported successfully")
except ImportError as e:
    log.warning("GDE not importable (will use naive apply): %s", e)

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_SESSIONS         = 8
IDLE_TIMEOUT_SECONDS = 3600
EXECUTOR_WORKERS     = 4

# ── Streaming Inference Adapter ───────────────────────────────────────────────

class StreamingInferenceAdapter:
    """
    Wraps any adapter with a .call() method and fires WebSocket
    callbacks before/after each LLM call for real-time pass streaming.
    """

    def __init__(
        self,
        real_adapter: Any,
        send_fn:      Callable[[dict], Awaitable[None]],
        loop:         asyncio.AbstractEventLoop,
    ) -> None:
        self._real  = real_adapter
        self._send  = send_fn
        self._loop  = loop

    def call(self, request: Any) -> Any:
        label = getattr(request, "call_label", "unknown")
        tier  = getattr(request, "complexity_tier", "TIER_M")

        self._fire({"type": "pil_pass_update", "update": {
            "pass": label, "status": "running", "tier": tier,
        }})

        try:
            response = self._real.call(request)
        except Exception as exc:
            self._fire({"type": "pil_pass_update", "update": {
                "pass": label, "status": "failed", "error": str(exc)[:200],
            }})
            raise

        self._fire({"type": "pil_pass_update", "update": {
            "pass":       label,
            "status":     "done",
            "tier":       tier,
            "tokens":     getattr(response, "output_tokens", 0),
            "cost_cents": getattr(response, "cost_cents", 0.0),
            "cached":     getattr(response, "cached", False),
        }})
        return response

    def _fire(self, message: dict) -> None:
        asyncio.run_coroutine_threadsafe(self._send(message), self._loop)


# ── Session ───────────────────────────────────────────────────────────────────

@dataclass
class BuilderSession:
    session_id:       str
    pipeline:         Any                # PILPipeline | None
    gde:              Any                # GDEOrchestrator | None  (Phase 14.5)
    created_at:       float              = field(default_factory=time.time)
    last_active:      float              = field(default_factory=time.time)
    current_mode:     str                = "COLLABORATIVE"
    project_path:     str                = ""
    pending_txn:      dict | None        = None
    pending_clar_id:  str | None         = None

    def touch(self) -> None:
        self.last_active = time.time()

    @property
    def is_idle(self) -> bool:
        return time.time() - self.last_active > IDLE_TIMEOUT_SECONDS


# ── Session Manager ───────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages builder sessions. One session per designer WebSocket connection.
    """

    def __init__(
        self,
        sgc_bin_path:   str = "",
        model_provider: str = "auto",
        model_name:     str = "",
        ollama_url:     str = "http://localhost:11434",
    ) -> None:
        self._sessions:       dict[str, BuilderSession] = {}
        self._sgc_bin:        str = sgc_bin_path
        self._model_provider: str = model_provider
        self._model_name:     str = model_name
        self._ollama_url:     str = ollama_url
        self._executor = ThreadPoolExecutor(
            max_workers        = EXECUTOR_WORKERS,
            thread_name_prefix = "pil-worker",
        )

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def get_or_create(
        self,
        session_id:   str,
        send_fn:      Callable[[dict], Awaitable[None]],
        project_path: str = "",
        mode:         str = "COLLABORATIVE",
    ) -> BuilderSession:
        if session_id in self._sessions:
            session = self._sessions[session_id]
            session.touch()
            log.info("Session resumed: %s", session_id[:12])
            return session

        if len(self._sessions) >= MAX_SESSIONS:
            self._evict_oldest()

        loop = asyncio.get_event_loop()
        pipeline = self._create_pipeline(
            send_fn        = send_fn,
            loop           = loop,
            session_id     = session_id,
            model_provider = self._model_provider,
            model_name     = self._model_name,
            ollama_url     = self._ollama_url,
        )
        gde = self._create_gde(mode, session_id)

        session = BuilderSession(
            session_id   = session_id,
            pipeline     = pipeline,
            gde          = gde,
            current_mode = mode,
            project_path = project_path,
        )
        self._sessions[session_id] = session
        log.info("Session created: %s (PIL=%s GDE=%s)",
                 session_id[:12],
                 "real" if pipeline is not None else "unavailable",
                 "real" if gde is not None else "unavailable")
        return session

    def destroy(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session and session.pipeline:
            try:
                session.pipeline.close_session()
            except Exception:
                pass

    def mark_disconnected(self, session_id: str) -> None:
        """Keep session alive for reconnection (evicted after IDLE_TIMEOUT)."""
        session = self._sessions.get(session_id)
        if session:
            session.touch()

    # ── PIL execution ─────────────────────────────────────────────────────────

    async def run_pil(
        self,
        session_id: str,
        prompt:     str,
        cgs:        dict,
        cgs_hash:   str,
        mode:       str = "COLLABORATIVE",
        send_fn:    Any = None,   # needed to stream pass updates when using SimplePipeline
    ) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            return _err("Session not found.")

        session.touch()
        session.current_mode = mode

        loop = asyncio.get_event_loop()

        # ── Path A: Real PIL available ────────────────────────────────────────
        if session.pipeline is not None:
            def _run() -> dict:
                result = session.pipeline.process(
                    prompt   = prompt,
                    cgs      = cgs,
                    cgs_hash = cgs_hash,
                    mode     = mode,
                )
                return _serialize_pil_result(result)

            try:
                result_dict = await loop.run_in_executor(self._executor, _run)
            except Exception as exc:
                log.exception("PIL execution error for session %s", session_id[:12])
                result_dict = _err(str(exc)[:300])

        # ── Path B: SimplePipeline (PIL not installed) ────────────────────────
        else:
            log.info(
                "PIL not available — using SimplePipeline (direct LLM) "
                "for session %s", session_id[:12]
            )
            # Build adapter fresh (same one the real pipeline would use)
            adapter = _build_adapter(
                provider   = self._model_provider,
                model_name = self._model_name,
                ollama_url = self._ollama_url,
            )
            streaming = StreamingInferenceAdapter(adapter, send_fn, loop) if send_fn else adapter
            simple    = SimplePipeline(streaming, session_id=session_id)

            def _run_simple() -> dict:
                return simple.process(prompt=prompt, cgs=cgs, cgs_hash=cgs_hash, mode=mode)

            try:
                result_dict = await loop.run_in_executor(self._executor, _run_simple)
            except Exception as exc:
                log.exception("SimplePipeline error for session %s", session_id[:12])
                result_dict = _err(str(exc)[:300])

        if result_dict.get("kind") == "mutation":
            session.pending_txn = result_dict.get("transaction")

        return result_dict

    async def submit_clarification_answer(
        self,
        session_id: str,
        clar_id:    str,
        answer:     str,
    ) -> dict:
        session = self._sessions.get(session_id)
        if session is None or session.pipeline is None:
            return {"accepted": False, "error": "Session not found.",
                    "next_question": None, "complete": False}

        session.touch()
        loop = asyncio.get_event_loop()

        def _run() -> dict:
            return session.pipeline.submit_clarification_answer(clar_id, answer)

        return await loop.run_in_executor(self._executor, _run)

    def clear_pending(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].pending_txn = None

    # ── GDE commit ────────────────────────────────────────────────────────────

    def apply_via_gde(
        self,
        session_id: str,
        txn_dict:   dict,
        current_cgs: dict,
    ) -> "GDEApplyResult":
        """
        Phase 14.5: Applies a MutationTransaction dict via the GDE.

        Converts PIL MutationTransaction → GDE DSLTransaction, runs
        through GDE validation pipeline (invariants, consistency checks),
        commits, returns the new CGS and metadata.

        Falls back to naive apply if GDE is unavailable.

        Returns GDEApplyResult with new_cgs, new_hash, snapshot, errors.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return GDEApplyResult(error="Session not found.")

        # ── Path A: GDE available ─────────────────────────────────────────────
        if session.gde is not None:
            return _apply_via_gde(session.gde, txn_dict, current_cgs, session_id)

        # ── Path B: GDE unavailable — naive apply (Phase 14 fallback) ────────
        log.warning(
            "GDE not available for session %s — using naive apply. "
            "Invariants and consistency checks skipped.",
            session_id[:12],
        )
        return _naive_apply(txn_dict, current_cgs)

    # ── SGC recompile ─────────────────────────────────────────────────────────

    def recompile_sgc(self, cgs: dict) -> str | None:
        """
        Phase 14.5: Calls the compiled SGC binary to produce an ExecutionPlan.

        Returns the ExecutionPlan JSON string, or None if SGC is unavailable
        or the mutation doesn't require recompilation.

        The SGC binary reads JSON from stdin and writes ExecutionPlan to stdout:
            cat systems.json | xace_sgc > execution_plan.json
        """
        if not self._sgc_bin:
            return None

        import subprocess, json as _json

        # Build the system definitions list that SGC expects
        systems = _extract_systems_for_sgc(cgs)
        if not systems:
            return None

        payload = _json.dumps({"systems": systems, "cgs_hash": cgs.get("metadata", {}).get("cgs_hash", "")})

        try:
            result = subprocess.run(
                [self._sgc_bin],
                input          = payload.encode(),
                capture_output = True,
                timeout        = 30,
            )
            if result.returncode != 0:
                log.error("SGC failed (exit %d): %s", result.returncode,
                          result.stderr.decode()[:200])
                return None

            plan = result.stdout.decode().strip()
            log.info("SGC recompile successful: %d bytes", len(plan))
            return plan

        except subprocess.TimeoutExpired:
            log.error("SGC timed out after 30s")
            return None
        except FileNotFoundError:
            log.error("SGC binary not found: %s", self._sgc_bin)
            return None
        except Exception as exc:
            log.error("SGC error: %s", exc)
            return None

    def get_available_models(self) -> dict:
        """Returns available models for the UI model selector dropdown."""
        if self._model_provider in ("auto", "ollama"):
            try:
                from ollama_adapter import OllamaAdapter, preferred_model_list  # type: ignore[import]
                adapter = OllamaAdapter(base_url=self._ollama_url)
                models  = adapter.list_models()
                healthy = adapter.is_healthy()
                current = self._model_name or ("auto" if self._model_provider == "auto" else "llama3.2")
                return {
                    "provider": self._model_provider,
                    "models":   preferred_model_list(models),
                    "current":  current,
                    "healthy":  healthy,
                    "url":      self._ollama_url,
                }
            except ImportError:
                return {"provider": self._model_provider, "models": ["auto", "llama3.2", "llama3.1"], "current": "auto",
                        "healthy": False, "url": self._ollama_url}
        return {
            "provider": "anthropic",
            "models":   ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
            "current":  "claude-sonnet-4-20250514",
            "healthy":  bool(os.environ.get("ANTHROPIC_API_KEY")),
            "url":      "https://api.anthropic.com",
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _create_pipeline(
        send_fn:        Callable[[dict], Awaitable[None]],
        loop:           asyncio.AbstractEventLoop,
        session_id:     str = "builder",
        model_provider: str = "auto",
        model_name:     str = "",
        ollama_url:     str = "http://localhost:11434",
    ) -> Any | None:
        if PILPipeline is None:
            return None
        real_adapter = _build_adapter(model_provider, model_name, ollama_url)
        streaming    = StreamingInferenceAdapter(real_adapter, send_fn, loop)
        return PILPipeline(streaming, session_id=session_id)

    @staticmethod
    def _create_gde(mode: str = "COLLABORATIVE", session_id: str = "") -> Any | None:
        if not _GDE_AVAILABLE or _GDEOrchestrator is None:
            return None
        try:
            return _GDEOrchestrator(mode=mode, session_id=session_id or "builder")
        except Exception as exc:
            log.warning("Failed to create GDEOrchestrator: %s", exc)
            return None

    def _evict_oldest(self) -> None:
        if not self._sessions:
            return
        oldest = min(self._sessions, key=lambda k: self._sessions[k].last_active)
        log.warning("Max sessions — evicting: %s", oldest[:12])
        self.destroy(oldest)

    @property
    def session_count(self) -> int:
        return len(self._sessions)


# ── GDE Apply Result ──────────────────────────────────────────────────────────

@dataclass
class GDEApplyResult:
    """
    Result of SessionManager.apply_via_gde().

    Attributes
    ----------
    new_cgs      : dict | None — the committed CGS (None on failure)
    new_hash     : str         — new cgs_hash
    snapshot     : dict        — commit metadata {version, cgs_hash, ...}
    error        : str         — non-empty if commit failed
    warnings     : list[str]   — non-fatal consistency warnings
    used_gde     : bool        — True if real GDE was used, False if naive fallback
    """
    new_cgs:   dict | None  = None
    new_hash:  str          = ""
    snapshot:  dict         = field(default_factory=dict)
    error:     str          = ""
    warnings:  list[str]    = field(default_factory=list)
    used_gde:  bool         = False

    @property
    def success(self) -> bool:
        return self.new_cgs is not None and not self.error


# ── Adapter factory (routes between Anthropic and Ollama) ─────────────────────

def _build_adapter(
    provider:   str = "auto",
    model_name: str = "",
    ollama_url: str = "http://localhost:11434",
) -> Any:
    """
    Selects and constructs the right inference adapter.

    auto/ollama -> create_ollama_adapter() (connects to local Ollama)
    anthropic   -> _build_real_adapter() (reads ANTHROPIC_API_KEY)
    """
    if provider in ("auto", "ollama"):
        try:
            from ollama_adapter import create_ollama_adapter  # type: ignore[import]
            model = model_name or ("auto" if provider == "auto" else "llama3.2")
            log.info("Using Ollama adapter: model=%s url=%s", model, ollama_url)
            return create_ollama_adapter(model=model, base_url=ollama_url)
        except ImportError:
            log.error(
                "ollama_adapter.py not found next to builder_server.py. "
                "Falling back to MockAdapter."
            )
            return _MockAdapter()
    else:
        return _build_real_adapter()


# ── Real Anthropic InferenceAdapter factory ───────────────────────────────────

def _build_real_adapter() -> Any:
    """
    Builds the real InferenceAdapter with all 7 dependencies.

    Tries to import from packages/inference/src. If any import fails,
    falls back to _MockAdapter.

    The real adapter reads ANTHROPIC_API_KEY from the environment
    (set by builder_server.py --api-key argument).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — using MockAdapter")
        return _MockAdapter()

    try:
        from inference_adapter import InferenceAdapter     # type: ignore[import]
        from provider_registry import ProviderRegistry     # type: ignore[import]
        from telemetry_pipeline import TelemetryPipeline   # type: ignore[import]
        from inference_budget import InferenceBudget       # type: ignore[import]
        from inference_retry_policy import InferenceRetryPolicy  # type: ignore[import]
        from prompt_cache import PromptCache               # type: ignore[import]
        from response_cache import ResponseCache           # type: ignore[import]
        from cache_key_builder import CacheKeyBuilder      # type: ignore[import]

        # Build each dependency with sensible defaults
        registry      = ProviderRegistry.from_env()          # reads ANTHROPIC_API_KEY
        telemetry     = TelemetryPipeline.create_default()
        budget        = InferenceBudget.create_default()
        retry         = InferenceRetryPolicy.create_default()
        prompt_cache  = PromptCache.create_default()
        resp_cache    = ResponseCache.create_in_memory()
        key_builder   = CacheKeyBuilder()

        adapter = InferenceAdapter(
            provider_registry  = registry,
            telemetry          = telemetry,
            budget             = budget,
            retry_policy       = retry,
            prompt_cache       = prompt_cache,
            response_cache     = resp_cache,
            cache_key_builder  = key_builder,
        )
        log.info("Real InferenceAdapter constructed (provider: anthropic)")
        return adapter

    except ImportError as exc:
        log.warning(
            "packages/inference not importable (%s) — falling back to MockAdapter. "
            "Copy packages/inference to the same parent directory as builder-server.",
            exc,
        )
        return _MockAdapter()
    except Exception as exc:
        log.error("Failed to build real InferenceAdapter: %s — using MockAdapter", exc)
        return _MockAdapter()


# ── GDE application ───────────────────────────────────────────────────────────

def _apply_via_gde(
    gde:        Any,        # GDEOrchestrator instance
    txn_dict:   dict,
    current_cgs: dict,
    session_id: str,
) -> GDEApplyResult:
    """
    Converts a serialised PIL MutationTransaction dict to a GDE DSLTransaction
    and runs it through the full GDE pipeline.

    Conversion: PIL MutationOp → GDE DSLOperation
        PIL op "SET"           → GDE OpType.SET
        PIL op "SCALE"         → GDE OpType.MULTIPLY
        PIL op "ADD_ACTOR"     → GDE OpType.ADD_ACTOR
        PIL op "REMOVE_ACTOR"  → GDE OpType.REMOVE_ACTOR
        PIL op "ADD_COMPONENT" → GDE OpType.ADD_COMPONENT
        PIL op "REMOVE_COMPONENT" → GDE OpType.REMOVE_COMPONENT
        PIL op "ADD_SYSTEM"    → GDE OpType.ADD_SYSTEM
        PIL op "REMOVE_SYSTEM" → GDE OpType.REMOVE_SYSTEM
        PIL op "ADD_RULE"      → GDE OpType.ADD_RULE
        PIL op "REMOVE_RULE"   → GDE OpType.REMOVE_RULE
    """
    import copy

    try:
        from src.gde_orchestrator import GDEResult               # type: ignore[import]
        from src.domain_dsl.transaction_model.transaction_builder import (  # type: ignore[import]
            TransactionBuilder, OpType,
        )
        from src.domain_dsl.mutation_metadata.mutation_metadata_model import (  # type: ignore[import]
            MutationMetadata,
        )
    except ImportError as exc:
        log.warning("GDE internals not importable: %s — naive fallback", exc)
        return _naive_apply(txn_dict, current_cgs)

    # ── 1. Ensure GDE has the current CGS loaded ──────────────────────────────
    try:
        if not gde.is_initialised or gde.current_hash != current_cgs.get("metadata", {}).get("cgs_hash", ""):
            gde.load_cgs(current_cgs, session_id=session_id)
    except Exception as exc:
        log.error("GDE load_cgs failed: %s", exc)
        return GDEApplyResult(error=f"GDE initialisation failed: {exc}")

    # ── 2. Build DSLTransaction from PIL ops ──────────────────────────────────
    PIL_TO_GDE_OP = {
        "SET":              "SET",
        "SCALE":            "MULTIPLY",
        "ADD_ACTOR":        "ADD_ACTOR",
        "REMOVE_ACTOR":     "REMOVE_ACTOR",
        "ADD_COMPONENT":    "ADD_COMPONENT",
        "REMOVE_COMPONENT": "REMOVE_COMPONENT",
        "ADD_SYSTEM":       "ADD_SYSTEM",
        "REMOVE_SYSTEM":    "REMOVE_SYSTEM",
        "ADD_RULE":         "ADD_RULE",
        "REMOVE_RULE":      "REMOVE_RULE",
    }

    ops       = txn_dict.get("operations", [])
    summary   = txn_dict.get("mutation_summary", "")[:100]
    cur_hash  = current_cgs.get("metadata", {}).get("cgs_hash", "")
    cur_ver   = current_cgs.get("metadata", {}).get("version", "0.1.0")

    try:
        metadata = MutationMetadata.for_manual_edit(
            parent_cgs_hash       = cur_hash,
            schema_version_target = cur_ver,
            description           = summary,
            session_id            = session_id,
        )
        builder = TransactionBuilder(metadata)

        for op in ops:
            pil_op   = op.get("op", "SET")
            gde_op   = PIL_TO_GDE_OP.get(pil_op, "SET")
            path     = op.get("path", "")
            value    = op.get("value")
            type_hint = op.get("type_hint", "float")

            if not path:
                continue

            # Map PIL op → TransactionBuilder method
            if gde_op == "SET":
                builder.set(path, value, type_hint=type_hint)
            elif gde_op == "MULTIPLY":
                builder.multiply(path, value)
            elif gde_op == "ADD_ACTOR":
                builder.add_actor(path, value)
            elif gde_op == "REMOVE_ACTOR":
                builder.remove_actor(path)
            elif gde_op == "ADD_COMPONENT":
                builder.add_component(path, value)
            elif gde_op == "REMOVE_COMPONENT":
                builder.remove_component(path)
            elif gde_op == "ADD_SYSTEM":
                builder.add_system(path, value)
            elif gde_op == "REMOVE_SYSTEM":
                builder.remove_system(path)
            elif gde_op == "ADD_RULE":
                builder.add_rule(path, value)
            elif gde_op == "REMOVE_RULE":
                builder.remove_rule(path)

        dsl_txn = builder.build()

    except Exception as exc:
        log.error("TransactionBuilder failed: %s", exc)
        # Fallback to naive so designer isn't blocked
        log.warning("Falling back to naive apply")
        return _naive_apply(txn_dict, current_cgs)

    # ── 3. Run through GDE (execute → validate → commit) ─────────────────────
    try:
        result: GDEResult = gde.process_transaction(dsl_txn)
    except Exception as exc:
        log.error("GDE process_transaction raised: %s", exc)
        return GDEApplyResult(error=f"GDE error: {exc}")

    if not result.success:
        if result.needs_clarification:
            # Edge case: GDE wants clarification even on a pre-classified txn
            return GDEApplyResult(
                error=f"GDE clarification needed: {result.error}",
                warnings=[result.error],
            )
        return GDEApplyResult(
            error    = result.error,
            warnings = (
                list(result.consistency_report.errors[:5])
                if result.consistency_report else []
            ),
        )

    # ── 4. Extract committed CGS from GDE ─────────────────────────────────────
    new_cgs  = gde.current_cgs   # deep copy already, per CGSManager contract
    new_hash = result.new_cgs_hash
    snapshot = result.snapshot or {}

    warnings: list[str] = []
    if result.consistency_report and result.consistency_report.warnings:
        warnings = list(result.consistency_report.warnings[:5])

    log.info("GDE committed: hash=%s warnings=%d", new_hash[:8], len(warnings))

    return GDEApplyResult(
        new_cgs  = new_cgs,
        new_hash = new_hash,
        snapshot = snapshot,
        warnings = warnings,
        used_gde = True,
    )


def _naive_apply(txn_dict: dict, current_cgs: dict) -> GDEApplyResult:
    """
    Fallback: applies PIL ops directly without GDE validation.
    Used when GDE is unavailable or TransactionBuilder fails.
    Exactly the same logic as the Phase 14 _apply_operations() helper.
    """
    import copy, hashlib, json, re

    new_cgs = copy.deepcopy(current_cgs)
    ops     = txn_dict.get("operations", [])

    for op in ops:
        op_type = op.get("op", "")
        path    = op.get("path", "")
        value   = op.get("value")
        if op_type in ("SET", "SCALE"):
            _naive_set(new_cgs, path, value, op_type)

    # Recompute hash
    stripped = copy.deepcopy(new_cgs)
    stripped.get("metadata", {}).pop("cgs_hash", None)
    canonical = json.dumps(stripped, sort_keys=True, ensure_ascii=False)
    new_hash  = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    new_cgs["metadata"]["cgs_hash"] = new_hash

    return GDEApplyResult(
        new_cgs  = new_cgs,
        new_hash = new_hash,
        snapshot = {},
        warnings = ["GDE unavailable — naive apply used, invariants not checked"],
        used_gde = False,
    )


def _naive_set(cgs: dict, path: str, value: Any, op_type: str) -> None:
    import re
    try:
        segments = re.split(r'\.|(?=\[)', path)
        obj = cgs
        for seg in segments[:-1]:
            if seg.startswith("[") and seg.endswith("]"):
                key = seg[1:-1]
                if isinstance(obj, list):
                    obj = next((x for x in obj if str(x.get("id", x.get("type_id", ""))) == key), obj)
                elif isinstance(obj, dict):
                    obj = obj.get(key, obj)
            elif isinstance(obj, dict):
                obj = obj.get(seg, {})
        last = segments[-1]
        if last.startswith("["):
            last = last[1:-1]
        if isinstance(obj, dict) and last in obj:
            if op_type == "SCALE":
                cur = obj[last]
                if isinstance(cur, (int, float)):
                    obj[last] = cur * value
            else:
                obj[last] = value
    except Exception as exc:
        log.warning("Naive set failed path=%r: %s", path, exc)


# ── SGC helpers ───────────────────────────────────────────────────────────────

def _extract_systems_for_sgc(cgs: dict) -> list[dict]:
    """Extracts all system definitions from the CGS for SGC input."""
    systems = list(cgs.get("global_systems", []))
    seen: set[str] = {s.get("id", "") for s in systems}
    for mode in cgs.get("modes", []):
        for sys in mode.get("systems", []):
            sid = sys.get("id", "")
            if sid and sid not in seen:
                systems.append(sys)
                seen.add(sid)
    return systems


# ── Mock adapter (fallback when InferenceAdapter unavailable) ─────────────────

@dataclass
class _SimplePromptPart:
    text:      str
    cacheable: bool = False
    label:     str  = ""


@dataclass
class _SimpleInferenceRequest:
    prompt_parts:          list[_SimplePromptPart]
    system_prompt:         str = ""
    logical_model:         str = "standard_mutation"
    complexity_tier:       str = "TIER_L"
    max_tokens:            int = 1200
    temperature:           float = 0.0
    session_id:            str = ""
    call_label:            str = "simple_fallback"
    request_id:            str = ""
    cgs_structural_hash:   str = ""
    intent_class:          str = "MutationRequest"
    bypass_response_cache: bool = False

    def full_prompt_text(self) -> str:
        return "\n".join(part.text for part in self.prompt_parts)

    def cacheable_text(self) -> str:
        return "\n".join(part.text for part in self.prompt_parts if part.cacheable)


XACE_ASSISTANT_POLICY = """
You are the XACE builder assistant. XACE edits a Canonical Game Specification
(CGS) through PIL/GDE mutation transactions and determinism checks.

Current implemented abilities in the builder:
- inspect and mutate CGS by returning a pending mutation transaction;
- ask for missing design details when a safe mutation cannot be inferred;
- link asset path fields into CGS when the user supplies or selects a path;
- export adapter source files for Unity, Unreal, and Godot;
- show a CGS-driven preview and run local deterministic smoke tests.

Current limits:
- do not claim Unity, Unreal, or Godot are live-connected;
- do not claim bidirectional engine/world editing is implemented;
- do not claim multiplayer, save systems, or real engine play mode are complete;
- do not edit files, execute commands, or mutate CGS directly from the LLM;
- do not bypass GDE, schema validation, determinism, invariants, or pil_apply.

When mutation is requested, return conservative JSON only. If the request would
break deterministic rules or needs a missing design choice, return no operations
and describe the blocker in mutation_summary.
""".strip()


class SimplePipeline:
    """
    Minimal no-direct-mutation fallback used when PILPipeline cannot import.

    It asks the configured adapter for a JSON MutationTransaction-shaped object
    and lets the existing pil_apply path perform the actual CGS update.
    """

    def __init__(self, adapter: Any, session_id: str = "builder") -> None:
        self._adapter    = adapter
        self._session_id = session_id
        self._turn_index = 0

    def process(self, prompt: str, cgs: dict, cgs_hash: str, mode: str = "COLLABORATIVE") -> dict:
        import json

        self._turn_index += 1
        request = _SimpleInferenceRequest(
            prompt_parts=[
                _SimplePromptPart(
                    label="xace_policy",
                    cacheable=True,
                    text=XACE_ASSISTANT_POLICY,
                ),
                _SimplePromptPart(
                    label="fallback_instructions",
                    text=(
                        "You are generating a safe XACE CGS mutation transaction. "
                        "Return only JSON with keys: operations, schema_delta_type, "
                        "confidence_score, risk_level, required_recompile, "
                        "affected_systems, mutation_summary. Do not include prose. "
                        "Use operations=[] when the safe action is to refuse, warn, "
                        "or ask for a missing choice."
                    ),
                ),
                _SimplePromptPart(label="active_mode", text=f"mode={mode}"),
                _SimplePromptPart(label="designer_prompt", text=prompt),
                _SimplePromptPart(
                    label="current_cgs",
                    text=json.dumps(cgs, ensure_ascii=False, sort_keys=True)[:20000],
                ),
            ],
            system_prompt=XACE_ASSISTANT_POLICY,
            session_id=self._session_id,
            cgs_structural_hash=cgs_hash,
        )

        response = self._adapter.call(request)
        raw_text = str(getattr(response, "text", "")).strip()

        try:
            txn = self._parse_transaction(raw_text)
        except Exception as exc:
            return _err(f"SimplePipeline could not parse adapter response: {exc}")

        return {
            "kind":                  "mutation",
            "turn_index":            self._turn_index,
            "intent_category":       "MutationRequest",
            "confidence":            float(txn.get("confidence_score", 0.0) or 0.0),
            "mode_profile_warnings": [
                "PIL unavailable; SimplePipeline fallback produced an unvalidated transaction."
            ],
            "auto_committed":        False,
            "diff_text":             "",
            "transaction":           txn,
        }

    def _parse_transaction(self, raw_text: str) -> dict:
        import json

        if not raw_text:
            raise ValueError("empty response")

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            start = raw_text.find("{")
            end   = raw_text.rfind("}")
            if start < 0 or end <= start:
                raise
            data = json.loads(raw_text[start:end + 1])

        operations = data.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError("'operations' must be a list")

        cleaned_ops = []
        for op in operations:
            if not isinstance(op, dict):
                continue
            cleaned_ops.append({
                "path":       str(op.get("path", "")),
                "op":         str(op.get("op", "SET")),
                "value":      op.get("value"),
                "type_hint":  str(op.get("type_hint", "")),
                "field_name": str(op.get("field_name", "")),
                "actor_id":   str(op.get("actor_id", "")),
                "type_id":    op.get("type_id", ""),
            })

        affected = data.get("affected_systems", [])
        if not isinstance(affected, list):
            affected = []

        return {
            "operations":         cleaned_ops,
            "schema_delta_type":  str(data.get("schema_delta_type", "value_mutation")),
            "confidence_score":   float(data.get("confidence_score", data.get("confidence", 0.0)) or 0.0),
            "risk_level":         str(data.get("risk_level", "low")),
            "required_recompile": bool(data.get("required_recompile", False)),
            "affected_systems":   [str(item) for item in affected],
            "mutation_summary":   str(data.get("mutation_summary", "SimplePipeline fallback mutation."))[:200],
        }


class _MockAdapter:
    """Returns valid-format responses for every PIL pass — no real LLM calls."""

    def call(self, request: Any) -> Any:
        import json as _json
        label = getattr(request, "call_label", "")

        if "pass1" in label:
            text = _json.dumps({
                "target_entities": [], "intended_mutation_type": "field_value_set",
                "component_targets": [], "risk_assessment": "low",
                "reasoning": "Mock reasoning.", "requires_recompile": False,
            })
        elif "pass2" in label:
            text = _json.dumps({
                "operations": [], "schema_delta_type": "value_mutation",
                "confidence": 0.8,
            })
        elif "pass3" in label:
            text = _json.dumps({
                "passed": True, "issues": [],
                "check_scores": {
                    "path_validity": True, "value_type_correctness": True,
                    "scope_compliance": True, "unintended_modifications": True,
                    "constraint_compliance": True,
                },
                "confidence": 0.9, "correction_hint": "",
            })
        elif "pass4" in label:
            text = _json.dumps({
                "passed": True, "violations": [], "hidden_dependencies": [],
                "required_recompile": False, "affected_systems": [],
                "determinism_risk": "low",
            })
        else:
            text = _json.dumps({
                "schema_delta_type": "value_mutation", "confidence_score": 0.85,
                "risk_level": "low", "required_recompile": False,
                "mutation_summary": "Mock mutation (no LLM — set --api-key to enable).",
            })

        return type("MockResp", (), {
            "text": text, "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "cost_cents": 0.0, "model_id": "mock", "provider": "mock",
            "latency_ms": 5.0, "call_label": label,
            "request_id": "mock", "session_id": "mock", "cached": True,
        })()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _err(reason: str) -> dict:
    return {
        "kind": "error", "reason": reason,
        "turn_index": 0, "intent_category": "", "confidence": 0.0,
        "mode_profile_warnings": [],
    }


def _serialize_pil_result(result: Any) -> dict:
    """Convert a PILResult Python object to a JSON-serialisable dict."""
    d: dict = {
        "kind":                  result.kind,
        "turn_index":            getattr(result, "turn_index", 0),
        "intent_category":       getattr(result, "intent_category", ""),
        "confidence":            getattr(result, "confidence", 0.0),
        "mode_profile_warnings": list(getattr(result, "mode_profile_warnings", [])),
    }

    if result.kind == "mutation":
        txn = result.transaction
        d["auto_committed"] = result.auto_committed
        d["diff_text"]      = result.diff_text
        d["transaction"]    = {
            "operations":         [
                {
                    "path":       op.path,
                    "op":         op.op,
                    "value":      op.value,
                    "type_hint":  op.type_hint,
                    "field_name": op.field_name,
                    "actor_id":   op.actor_id,
                    "type_id":    op.type_id,
                }
                for op in txn.operations
            ],
            "schema_delta_type":  txn.schema_delta_type,
            "confidence_score":   txn.confidence_score,
            "risk_level":         txn.risk_level,
            "required_recompile": txn.required_recompile,
            "affected_systems":   list(txn.affected_systems),
            "mutation_summary":   txn.mutation_summary,
        }

    elif result.kind == "clarification":
        d["clarification_session_id"] = result.clarification_session_id
        d["reason"]                    = result.reason
        d["questions"]                 = [
            {
                "question_id":   q.get("question_id", ""),
                "question_type": q.get("question_type", "CHOICE"),
                "prompt":        q.get("prompt", ""),
                "options":       q.get("options", []),
                "hint":          q.get("hint", ""),
                "parameter_key": q.get("parameter_key", ""),
            }
            for q in result.questions
        ]

    elif result.kind in ("blocked", "error"):
        d["reason"] = result.reason
        d["guard"]  = getattr(result, "guard", "")

    elif result.kind == "diagnostic":
        d["explanation"] = result.explanation
        d["suggestion"]  = None

    return d

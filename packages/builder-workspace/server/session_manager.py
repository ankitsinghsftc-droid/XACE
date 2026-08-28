"""
session_manager.py — Builder Session Manager (Phase 14.5)
==========================================================
Maintains one PILPipeline instance per connected WebSocket session.

## Phase 14.5 changes vs Phase 14
    - _create_pipeline() builds the configured real InferenceAdapter.
    - SessionManager accepts sgc_bin_path for SGC recompilation.
    - Missing PIL or provider dependencies block visibly instead of using
      test-double provider behavior.
    - BuilderSession gains a gde_orchestrator field (GDEOrchestrator per session).

## Thread Safety
    All session state mutations happen in the asyncio thread.
    PIL calls happen in the executor (separate threads).
    The streaming adapter fires WebSocket callbacks from the PIL thread
    back to the event loop via run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
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
sys.path.insert(0, _PKGS)
for _sub in (
    "intent_intake", "context_assembler", "llm_orchestrator",
    "output_parser", "validation_loop", "critique_engine",
    "clarification_engine", "mutation_planner", "safety_scope_guard",
    "memory_model", "history_manager", "memory", "mode_controller",
):
    sys.path.insert(0, os.path.join(_PIL_SRC, _sub))
sys.path.insert(0, _INF_SRC)

from provider_settings import ProviderSettingsStore  # noqa: E402
from prompt_classifier_gate import classify_prompt  # noqa: E402
from sgc_plan_validator import SgcPlanValidationError, validate_sgc_plan_for_runtime_load  # noqa: E402

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
    log.warning("GDE not importable; production CGS mutation apply is disabled: %s", e)

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_SESSIONS         = 8
IDLE_TIMEOUT_SECONDS = 3600
EXECUTOR_WORKERS     = 4
DETERMINISTIC_SIMPLE_EDIT_SCHEMA = "xace.deterministic_simple_edit.v1"
DETERMINISTIC_SIMPLE_EDIT_MODEL = "gde-simple-edit-v1"
_PLAYER_SPEED_PATH = "modes.mode_gameplay.actors.actor_player.components.5.defaults.max_linear_speed"
_PLAYER_SPEED_SIMPLE_EDIT = re.compile(
    r"^\s*(?:set|change|update)\s+(?:the\s+)?player\s+(?:movement\s+)?speed\s+to\s+"
    r"(?P<value>\d+(?:\.\d+)?)\s*\.?\s*$",
    re.IGNORECASE,
)
_MAX_DETERMINISTIC_PLAYER_SPEED = 1000.0

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
    pending_prompt_clarification: dict | None = None
    prompt_clarification_log: list[dict] = field(default_factory=list)
    pending_prompt_preview: dict | None = None
    pending_prompt_result: dict | None = None
    prompt_preview_approval_log: list[dict] = field(default_factory=list)
    runtime_connected: bool              = False
    runtime_adapter_type: str            = ""
    runtime_engine_version: str          = ""
    runtime_last_tick: dict | None       = None
    runtime_last_hash: str               = ""
    engine_edit_log: list[dict]          = field(default_factory=list)

    def touch(self) -> None:
        self.last_active = time.time()

    @property
    def is_idle(self) -> bool:
        return time.time() - self.last_active > IDLE_TIMEOUT_SECONDS

    def update_runtime_status(
        self,
        connected: bool,
        adapter_type: str = "",
        engine_version: str = "",
        last_tick: dict | None = None,
        last_hash: str = "",
    ) -> None:
        self.runtime_connected = connected
        if adapter_type:
            self.runtime_adapter_type = adapter_type
        if engine_version:
            self.runtime_engine_version = engine_version
        if last_tick is not None:
            self.runtime_last_tick = last_tick
        if last_hash:
            self.runtime_last_hash = last_hash
        self.touch()

    def record_engine_edit(self, edit: dict) -> None:
        self.engine_edit_log.append({
            "ts": time.time(),
            **edit,
        })
        if len(self.engine_edit_log) > 256:
            del self.engine_edit_log[:-256]
        self.touch()


@dataclass
class SGCCompileResult:
    status: str
    plan_json: str = ""
    validation: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"

    @property
    def failed(self) -> bool:
        return self.status == "failed"


# ── Session Manager ───────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages builder sessions. One session per designer WebSocket connection.
    """

    def __init__(
        self,
        sgc_bin_path:   str = "",
        sgc_args:       list[str] | None = None,
        model_provider: str = "auto",
        model_name:     str = "",
        ollama_url:     str = "http://localhost:11434",
        api_key:        str = "",
    ) -> None:
        self._sessions:       dict[str, BuilderSession] = {}
        self._sgc_bin:        str = sgc_bin_path
        self._sgc_args:       list[str] = list(sgc_args or [])
        self._provider_store = ProviderSettingsStore()
        selection = self._provider_store.apply_launch_overrides(
            provider=model_provider,
            model=model_name,
            api_key=api_key,
            ollama_url=ollama_url,
        )
        self._model_provider: str = selection.provider
        self._model_name:     str = selection.model
        self._ollama_url:     str = selection.base_url or ollama_url
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
            sgc_bin_path   = self._sgc_bin,
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
        send_fn:    Any = None,
    ) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            return _err("Session not found.")

        session.touch()
        session.current_mode = mode
        session.pending_prompt_clarification = None
        session.pending_clar_id = None
        session.pending_prompt_preview = None
        session.pending_prompt_result = None
        result_dict = _deterministic_simple_edit_result(prompt, cgs)
        if result_dict is not None:
            readiness = _deterministic_simple_edit_readiness()
        else:
            readiness = self.provider_readiness()
            if not readiness.get("ok"):
                return _blocked(
                    str(readiness.get("message") or "The selected prompt provider is not ready."),
                    {
                        "guard": "provider_readiness",
                        "code": str(readiness.get("code") or "PROVIDER_NOT_READY"),
                        "action": str(readiness.get("action") or "test_provider"),
                        "ux_state": readiness.get("ux_state") if isinstance(readiness.get("ux_state"), dict) else {},
                        "intent_category": "ProviderConfiguration",
                        "confidence": 1.0,
                    },
                )

            loop = asyncio.get_event_loop()

            # ── Path A: Real PIL available ────────────────────────────────────
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

            # ── Path B: PIL unavailable ───────────────────────────────────────
            else:
                log.error("PIL unavailable; blocking prompt execution for session %s", session_id[:12])
                result_dict = _blocked(
                    "Prompt processing is unavailable because PILPipeline could not be imported.",
                    {
                        "code": "PIL_UNAVAILABLE",
                        "action": (
                            "Repair the prompt-intelligence package before running prompts; "
                            "XACE will not use test or fallback prompt helpers in production."
                        ),
                        "unsupported": True,
                        "guard": "prompt_pipeline_runtime",
                        "intent_category": "PromptPipelineUnavailable",
                        "confidence": 1.0,
                    },
                )

        if result_dict.get("kind") == "mutation":
            txn = result_dict.get("transaction")
            _stamp_pending_transaction_authority(txn, cgs, cgs_hash)
            block_reason = _pending_transaction_block_reason(txn)
            if block_reason:
                session.pending_txn = None
                session.pending_prompt_preview = None
                session.pending_prompt_result = None
                return _blocked(block_reason, result_dict)
            session.pending_txn = txn
            preview = _build_prompt_diff_preview(
                session=session,
                prompt=prompt,
                cgs=cgs,
                submitted_hash=cgs_hash,
                mode=mode,
                result=result_dict,
                readiness=readiness,
            )
            session.pending_prompt_preview = preview
            result_dict["preview"] = preview
            result_dict["approval_required"] = True
            session.pending_prompt_result = copy.deepcopy(result_dict)
        else:
            session.pending_txn = None
            session.pending_prompt_preview = None
            session.pending_prompt_result = None

        return result_dict

    def validate_prompt_preview_approval(
        self,
        session_id: str,
        message:    dict,
    ) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "accepted": False,
                "code": "NO_SESSION",
                "message": "Session not found.",
                "approval": {},
            }

        preview = session.pending_prompt_preview
        if not isinstance(preview, dict):
            return {
                "accepted": False,
                "code": "PROMPT_DIFF_PREVIEW_REQUIRED",
                "message": "Review the structured prompt diff preview before applying this mutation.",
                "approval": {},
            }

        override = _prompt_test_mode_override(message, preview)
        if override is not None:
            session.prompt_preview_approval_log.append(override)
            _trim_prompt_preview_log(session)
            if override.get("approved") is True:
                return {"accepted": True, "code": "", "message": "", "approval": override}
            return {
                "accepted": False,
                "code": "PROMPT_TEST_MODE_APPROVAL_REASON_REQUIRED",
                "message": "Test-mode prompt apply overrides require an audited reason.",
                "approval": override,
            }

        approval = message.get("approval")
        if not isinstance(approval, dict):
            return {
                "accepted": False,
                "code": "PROMPT_PREVIEW_APPROVAL_REQUIRED",
                "message": "Apply requires the approval token from the structured prompt diff preview.",
                "approval": {
                    "schema": "xace.prompt_preview_approval.v1",
                    "preview_id": str(preview.get("preview_id") or ""),
                    "approved": False,
                    "approval_source": "missing",
                    "reason": "missing_approval",
                    "timestamp": time.time(),
                },
            }

        expected_id = str(preview.get("preview_id") or "")
        expected_token = str(preview.get("approval_token") or "")
        supplied_id = str(approval.get("preview_id") or "")
        supplied_token = str(approval.get("approval_token") or "")
        if supplied_id != expected_id or supplied_token != expected_token:
            return {
                "accepted": False,
                "code": "PROMPT_PREVIEW_APPROVAL_MISMATCH",
                "message": "Apply approval does not match the active structured prompt diff preview.",
                "approval": {
                    "schema": "xace.prompt_preview_approval.v1",
                    "preview_id": supplied_id or expected_id,
                    "approved": False,
                    "approval_source": str(approval.get("approval_source") or "ui"),
                    "approved_by": str(approval.get("approved_by") or ""),
                    "reason": "approval_mismatch",
                    "timestamp": time.time(),
                },
            }

        accepted = {
            "schema": "xace.prompt_preview_approval.v1",
            "preview_id": expected_id,
            "approval_token_hash": hashlib.sha256(expected_token.encode("utf-8")).hexdigest(),
            "transaction_fingerprint": str(preview.get("transaction_fingerprint") or ""),
            "approved": True,
            "approval_source": str(approval.get("approval_source") or "ui"),
            "approved_by": str(approval.get("approved_by") or "builder-user"),
            "timestamp": time.time(),
            "test_mode_override": False,
        }
        session.prompt_preview_approval_log.append(accepted)
        _trim_prompt_preview_log(session)
        return {"accepted": True, "code": "", "message": "", "approval": accepted}

    def start_prompt_clarification(
        self,
        session_id: str,
        prompt:     str,
        classifier: Any,
    ) -> dict:
        session = self._sessions.get(session_id)
        result = classifier.to_pil_result()
        if session is None:
            return result

        session.touch()
        session.pending_txn = None
        session.pending_prompt_preview = None
        session.pending_prompt_result = None
        clar_id = _new_prompt_clarification_id(session, prompt, classifier)
        questions = list(result.get("questions") or [])
        record = {
            "schema": "xace.prompt_clarification_session.v1",
            "clarification_session_id": clar_id,
            "prompt": prompt,
            "classifier": classifier.to_dict(),
            "questions": questions,
            "created_at": time.time(),
            "state": "pending",
            "resolution": None,
        }
        session.pending_prompt_clarification = record
        session.pending_clar_id = clar_id

        result["clarification_session_id"] = clar_id
        result["clarification_schema"] = record["schema"]
        result["requires_user_resolution"] = True
        result["resolution_required_before_mutation"] = True
        return result

    def submit_prompt_clarification_answer(
        self,
        session_id: str,
        clar_id:    str,
        answer:     str,
    ) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None

        active = session.pending_prompt_clarification
        if not active or active.get("clarification_session_id") != clar_id:
            return None

        session.touch()
        questions = list(active.get("questions") or [])
        question = questions[0] if questions else {}
        selected, error = _bounded_prompt_clarification_answer(str(answer), question)
        if error:
            return {
                "accepted": False,
                "error": error,
                "next_question": question or None,
                "complete": False,
            }

        resolution = {
            "schema": "xace.prompt_clarification_resolution.v1",
            "clarification_session_id": clar_id,
            "question_id": str(question.get("question_id") or ""),
            "question_type": str(question.get("question_type") or ""),
            "parameter_key": str(question.get("parameter_key") or ""),
            "answer": str(answer).strip(),
            "selected_options": selected,
            "original_prompt": str(active.get("prompt") or ""),
            "classifier": dict(active.get("classifier") or {}),
            "answered_at": time.time(),
            "mutation_generation_allowed": False,
            "requires_reprompt": True,
        }
        active["state"] = "resolved"
        active["resolution"] = resolution
        session.prompt_clarification_log.append(resolution)
        if len(session.prompt_clarification_log) > 256:
            del session.prompt_clarification_log[:-256]
        session.pending_prompt_clarification = None
        session.pending_clar_id = None
        session.pending_txn = None
        session.pending_prompt_preview = None
        session.pending_prompt_result = None

        return {
            "accepted": True,
            "error": "",
            "next_question": None,
            "complete": True,
            "clarification_result": resolution,
            "requires_reprompt": True,
            "resolved_prompt": _resolved_prompt_prefill(resolution),
        }

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
            session = self._sessions[session_id]
            session.pending_txn = None
            session.pending_prompt_clarification = None
            session.pending_clar_id = None
            session.pending_prompt_preview = None
            session.pending_prompt_result = None

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

        By default, fails clearly if GDE is unavailable. This avoids presenting
        direct CGS edits as if the full PIL/GDE validation path succeeded.

        Returns GDEApplyResult with new_cgs, new_hash, snapshot, errors.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return GDEApplyResult(error="Session not found.")

        conflict_reason = _transaction_conflict_reason(txn_dict, current_cgs)
        if conflict_reason:
            return GDEApplyResult(error=conflict_reason)

        # ── Path A: GDE available ─────────────────────────────────────────────
        if session.gde is not None:
            return _apply_via_gde(
                session.gde,
                txn_dict,
                current_cgs,
                session_id,
            )

        return GDEApplyResult(
            error=(
                "GDE is unavailable, so XACE did not apply this mutation. "
                "Restart Builder after the GDE package is available."
            )
        )

    # ── SGC recompile ─────────────────────────────────────────────────────────

    def compile_sgc_plan(self, cgs: dict) -> SGCCompileResult:
        """
        Phase 14.5: Calls the compiled SGC binary to produce an ExecutionPlan.

        Returns a typed status so callers can distinguish a legitimate skip
        from a compiler or plan-validation failure.

        The SGC binary reads JSON from stdin and writes ExecutionPlan to stdout:
            cat systems.json | xace_sgc > execution_plan.json
        """
        if not self._sgc_bin:
            return SGCCompileResult(status="skipped", error={
                "schema": "xace.sgc.builder_error.v1",
                "code": "SGC_UNCONFIGURED",
                "category": "unsupported_dependency",
                "message": "No SGC binary is configured for this Builder session.",
                "action": "Start Builder with --sgc-bin pointing to xace-system-graph-compiler before applying structural mutations.",
                "unsupported": True,
            })

        import subprocess, json as _json

        # Build the system definitions list that SGC expects
        systems = _extract_systems_for_sgc(cgs)
        if not systems:
            return SGCCompileResult(status="skipped", error={
                "schema": "xace.sgc.builder_error.v1",
                "code": "SGC_NO_SYSTEMS",
                "category": "unsupported_empty_graph",
                "message": "CGS has no SystemDefinition records to compile.",
                "action": "Add at least one SystemDefinition or apply a value-only mutation that does not require SGC.",
                "unsupported": True,
            })

        metadata = cgs.get("metadata", {}) if isinstance(cgs.get("metadata"), dict) else {}
        payload_obj = {
            "schema": "xace.sgc.cli.input.v1",
            "schema_version": str(metadata.get("schema_version") or metadata.get("version") or "0.1.0"),
            "plan_version": int(metadata.get("execution_plan_version") or 1),
            "cgs_hash": str(metadata.get("cgs_hash") or ""),
            "systems": systems,
        }
        payload = _json.dumps(payload_obj, sort_keys=True)

        try:
            result = subprocess.run(
                [self._sgc_bin, *self._sgc_args],
                input          = payload.encode(),
                capture_output = True,
                timeout        = 30,
            )
            stdout = result.stdout.decode(errors="replace").strip()
            stderr = result.stderr.decode(errors="replace").strip()
            if result.returncode != 0:
                error = _parse_sgc_error(stderr, result.returncode)
                log.error("SGC failed (exit %d): %s", result.returncode, error.get("message"))
                return SGCCompileResult(
                    status="failed",
                    error=error,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=result.returncode,
                )

            try:
                validation = validate_sgc_plan_for_runtime_load(cgs, stdout)
            except SgcPlanValidationError as exc:
                log.error("SGC plan validation failed: %s", exc)
                return SGCCompileResult(
                    status="failed",
                    error={
                        "schema": "xace.sgc.builder_error.v1",
                        "code": "SGC_PLAN_VALIDATION_FAILED",
                        "category": "plan_validation",
                        "message": str(exc),
                        "action": "Fix the CGS SystemDefinition metadata and re-run the mutation before loading this plan.",
                    },
                    validation=exc.report,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=result.returncode,
                )

            log.info("SGC recompile successful: %d bytes", len(stdout))
            return SGCCompileResult(
                status="ok",
                plan_json=stdout,
                validation=validation,
                stdout=stdout,
                stderr=stderr,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            log.error("SGC timed out after 30s")
            return SGCCompileResult(status="failed", error={
                "schema": "xace.sgc.builder_error.v1",
                "code": "SGC_TIMEOUT",
                "category": "timeout",
                "message": "SGC compile timed out after 30 seconds.",
                "action": "Reduce the system graph size or inspect the compiler for a hang before applying this mutation.",
            })
        except FileNotFoundError:
            log.error("SGC binary not found: %s", self._sgc_bin)
            return SGCCompileResult(status="failed", error={
                "schema": "xace.sgc.builder_error.v1",
                "code": "SGC_BINARY_NOT_FOUND",
                "category": "configuration",
                "message": f"SGC binary not found: {self._sgc_bin}",
                "action": "Build xace-system-graph-compiler or fix the Builder SGC path.",
            })
        except Exception as exc:
            log.error("SGC error: %s", exc)
            return SGCCompileResult(status="failed", error={
                "schema": "xace.sgc.builder_error.v1",
                "code": "SGC_EXECUTION_FAILED",
                "category": "runtime",
                "message": str(exc)[:500],
                "action": "Inspect Builder logs and retry after the SGC invocation path is fixed.",
            })

    def recompile_sgc(self, cgs: dict) -> str | None:
        """Legacy wrapper retained for older wiring tests."""
        result = self.compile_sgc_plan(cgs)
        return result.plan_json if result.ok else None

    def get_available_models(self) -> dict:
        """Returns available models for the UI model selector dropdown."""
        return self._provider_store.payload(refresh_models=True)

    def get_provider_settings(self) -> dict:
        """Returns full local provider settings metadata for the Builder UI."""
        return self._provider_store.payload(refresh_models=True)

    def configure_provider(
        self,
        *,
        provider: str,
        model_name: str = "",
        api_key: str | None = None,
        base_url: str = "",
        clear_key: bool = False,
    ) -> dict:
        """Persists and activates the selected provider/model."""
        payload = self._provider_store.configure(
            provider=provider,
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            clear_key=clear_key,
            make_active=True,
        )
        selection = self._provider_store.active_selection()
        self._model_provider = selection.provider
        self._model_name = selection.model
        self._ollama_url = selection.base_url or self._ollama_url
        return payload

    def test_provider_config(self, payload: dict[str, Any] | None = None) -> dict:
        """Runs a real provider health check: key, model, and test call."""
        return self._provider_store.test_provider(payload or {})

    def provider_readiness(self) -> dict:
        """Returns whether the active provider can run prompt inference now."""
        return self._provider_store.active_readiness(refresh_models=False)

    def build_active_adapter(self) -> Any:
        """Builds the currently configured real adapter."""
        return self._provider_store.build_adapter(
            provider=self._model_provider,
            model=self._model_name,
            ollama_url=self._ollama_url,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _create_pipeline(
        send_fn:        Callable[[dict], Awaitable[None]],
        loop:           asyncio.AbstractEventLoop,
        session_id:     str = "builder",
        model_provider: str = "auto",
        model_name:     str = "",
        ollama_url:     str = "http://localhost:11434",
        sgc_bin_path:   str = "",
    ) -> Any | None:
        if PILPipeline is None:
            return None
        real_adapter = _build_adapter(model_provider, model_name, ollama_url)
        streaming    = StreamingInferenceAdapter(real_adapter, send_fn, loop)
        return PILPipeline(
            streaming,
            session_id=session_id,
            enable_code_gen=True,
            sgc_bin_path=sgc_bin_path,
        )

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
    used_gde     : bool        — True if real GDE was used
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


# ── Adapter factory ───────────────────────────────────────────────────────────

def _build_adapter(
    provider:   str = "auto",
    model_name: str = "",
    ollama_url: str = "http://localhost:11434",
) -> Any:
    """
    Selects and constructs the configured real inference adapter.

    This reads local provider settings for hosted API keys. Missing keys or
    broken provider imports return an adapter that raises clearly on use.
    """
    try:
        from provider_settings import build_provider_adapter  # type: ignore[import]

        adapter = build_provider_adapter(
            provider=provider,
            model_name=model_name,
            ollama_url=ollama_url,
        )
        log.info("Inference adapter constructed: provider=%s model=%s", provider, model_name or "default")
        return adapter
    except Exception as exc:
        reason = str(exc)[:300]
        log.error("Inference adapter unavailable: %s", reason)
        return _UnavailableAdapter(reason)


# ── Real Anthropic InferenceAdapter factory ───────────────────────────────────

def _build_real_adapter() -> Any:
    """Backward-compatible Anthropic adapter entry point."""
    return _build_adapter(provider="anthropic")


def _transaction_conflict_reason(txn_dict: dict, current_cgs: dict) -> str:
    current_hash = str(current_cgs.get("metadata", {}).get("cgs_hash", "") or "")
    submitted_hashes = [
        txn_dict.get("parent_cgs_hash"),
        txn_dict.get("cgs_hash"),
        (txn_dict.get("version_ids") or {}).get("cgs_hash")
        if isinstance(txn_dict.get("version_ids"), dict)
        else "",
    ]
    for submitted in submitted_hashes:
        submitted_hash = str(submitted or "")
        if submitted_hash and submitted_hash != current_hash:
            return (
                "GDE conflict: transaction targets CGS hash "
                f"{submitted_hash} but current CGS hash is {current_hash}."
            )
    return ""


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
    try:
        from src.gde_orchestrator import GDEResult               # type: ignore[import]
        from src.domain_dsl.transaction_model.transaction_builder import (  # type: ignore[import]
            TransactionBuilder, OpType,
        )
        from src.domain_dsl.mutation_metadata.mutation_metadata_model import (  # type: ignore[import]
            MutationMetadata,
        )
    except ImportError as exc:
        return GDEApplyResult(error=f"GDE internals are not importable: {exc}")

    # ── 1. Ensure GDE has the current CGS loaded ──────────────────────────────
    try:
        if not gde.is_initialised or gde.current_hash != current_cgs.get("metadata", {}).get("cgs_hash", ""):
            gde.load_cgs(current_cgs, session_id=session_id)
    except Exception as exc:
        log.error("GDE load_cgs failed: %s", exc)
        return GDEApplyResult(error=f"GDE initialisation failed: {exc}")

    # ── 2. Build DSLTransaction from PIL ops ──────────────────────────────────
    typed_batch = txn_dict.get('typed_operation_batch')
    if isinstance(typed_batch, dict):
        summary = str(txn_dict.get('mutation_summary', ''))[:100]
        current_metadata = current_cgs.get('metadata', {})
        current_hash = current_metadata.get('cgs_hash', '')
        current_version = current_metadata.get('version', '0.1.0')
        try:
            metadata = MutationMetadata.create(
                source=_gde_mutation_source(txn_dict),
                parent_cgs_hash=current_hash,
                schema_version_target=current_version,
                description=summary or str(typed_batch.get('summary', ''))[:100],
                session_id=session_id,
                confidence=float(txn_dict.get('confidence_score', 1.0) or 1.0),
                risk_level=str(txn_dict.get('risk_level', 'medium') or 'medium'),
                transaction_id=str(txn_dict.get('transaction_id') or '') or None,
                extra={
                    'version_ids': txn_dict.get('version_ids', {}),
                    'mutation_path': 'typed_cgs_operations',
                    'typed_request_id': typed_batch.get('request_id', ''),
                    'typed_prompt_id': typed_batch.get('prompt_id', ''),
                },
            )
            result: GDEResult = gde.process_typed_operation_batch(
                typed_batch, metadata
            )
        except Exception as exc:
            log.error('GDE typed operation apply raised: %s', exc)
            return GDEApplyResult(error=f'GDE typed operation error: {exc}')

        if not result.success:
            return GDEApplyResult(
                error=result.error,
                warnings=(
                    list(result.consistency_report.errors[:5])
                    if result.consistency_report else []
                ),
            )

        snapshot = dict(result.snapshot or {})
        snapshot['typed_operation_batch_hash'] = result.typed_operation_batch_hash
        snapshot['typed_operation_ids'] = list(result.typed_operation_ids)
        snapshot['typed_operation_kinds'] = list(result.typed_operation_kinds)
        warnings = (
            list(result.consistency_report.warnings[:5])
            if result.consistency_report else []
        )
        return GDEApplyResult(
            new_cgs=gde.current_cgs,
            new_hash=result.new_cgs_hash,
            snapshot=snapshot,
            warnings=warnings,
            used_gde=True,
        )

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
        metadata = MutationMetadata.create(
            source                = _gde_mutation_source(txn_dict),
            parent_cgs_hash       = cur_hash,
            schema_version_target = cur_ver,
            description           = summary,
            session_id            = session_id,
            confidence            = float(txn_dict.get("confidence_score", 1.0) or 1.0),
            risk_level            = str(txn_dict.get("risk_level", "low") or "low"),
            transaction_id        = str(txn_dict.get("transaction_id") or "") or None,
            extra                 = {
                "version_ids": txn_dict.get("version_ids", {}),
                "mutation_path": txn_dict.get("mutation_path", ""),
            },
        )
        builder = TransactionBuilder(metadata)

        for op in ops:
            pil_op   = op.get("op", "SET")
            gde_op   = PIL_TO_GDE_OP.get(pil_op)
            path     = op.get("path", "")
            value    = op.get("value")
            type_hint = op.get("type_hint", "float")

            if not path:
                continue
            if gde_op is None:
                raise ValueError(f"Unsupported PIL operation: {pil_op}")

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
        return GDEApplyResult(error=f"GDE transaction build failed: {exc}")

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


def _parse_sgc_error(stderr: str, exit_code: int) -> dict[str, Any]:
    import json as _json

    try:
        error = _json.loads(stderr)
    except _json.JSONDecodeError:
        return {
            "schema": "xace.sgc.builder_error.v1",
            "code": "SGC_FAILED",
            "category": "compiler",
            "message": stderr[:1000] or f"SGC exited with code {exit_code}.",
            "exit_code": exit_code,
            "action": "Inspect the SGC stderr and fix the CGS SystemDefinition that failed compilation.",
        }
    if not isinstance(error, dict):
        return {
            "schema": "xace.sgc.builder_error.v1",
            "code": "SGC_FAILED",
            "category": "compiler",
            "message": f"SGC exited with code {exit_code} and emitted a non-object error payload.",
            "exit_code": exit_code,
            "action": "Inspect the SGC stderr and fix the compiler output contract.",
        }
    error.setdefault("schema", "xace.sgc.cli.error.v1")
    error.setdefault("code", "SGC_FAILED")
    error.setdefault("category", "compiler")
    error.setdefault("message", f"SGC exited with code {exit_code}.")
    error.setdefault("exit_code", exit_code)
    error.setdefault("action", _sgc_action_for(str(error.get("code") or "")))
    return error


def _sgc_action_for(code: str) -> str:
    return {
        "INVALID_PHASE": "Choose one of Initialization, Input, Simulation, PostSimulation, or Cleanup for the listed system.",
        "INVALID_PHASE_TYPE": "Set the system phase to a phase name string or valid phase ordinal.",
        "EMPTY_SYSTEM_ID": "Give every CGS SystemDefinition a stable non-empty id.",
        "INVALID_SYSTEM_DEFINITION": "Fix the listed SystemDefinition field and retry the mutation.",
        "CYCLE_DETECTED": "Break the system dependency cycle by removing a depends_on edge or moving one system to an earlier phase.",
        "CONFLICT_DETECTED": "Split or serialize the conflicting systems before loading this plan.",
        "JSON_PARSE_ERROR": "Report this as a Builder-to-SGC payload bug; the compiler did not receive valid JSON.",
    }.get(code, "Fix the CGS SystemDefinition issue reported by SGC and retry the mutation.")


# ── Unavailable adapter ───────────────────────────────────────────────────────

class _UnavailableAdapter:
    """Blocks inference when no real provider can run."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def call(self, request: Any) -> Any:
        raise RuntimeError(self._reason)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _deterministic_simple_edit_result(prompt: str, cgs: dict) -> dict | None:
    match = _PLAYER_SPEED_SIMPLE_EDIT.match(str(prompt or ""))
    if match is None:
        return None

    classifier = classify_prompt(str(prompt or ""))
    if classifier.category_id != "certified_supported" or not classifier.mutation_allowed:
        return None

    try:
        value = float(match.group("value"))
    except (TypeError, ValueError):
        return None
    if value < 0.0 or value > _MAX_DETERMINISTIC_PLAYER_SPEED:
        return None

    old_value = _read_cgs_preview_path(cgs, _PLAYER_SPEED_PATH)
    if isinstance(old_value, bool) or not isinstance(old_value, (int, float)):
        return None

    value_label = _format_simple_number(value)
    classifier_payload = classifier.to_dict()
    return {
        "kind": "mutation",
        "turn_index": 0,
        "intent_category": "MutationRequest",
        "confidence": 0.99,
        "mode_profile_warnings": [],
        "auto_committed": False,
        "diff_text": "",
        "tokens": 0,
        "cost_cents": 0.0,
        "cost_source": "deterministic_simple_edit_no_provider_call",
        "provider": "deterministic",
        "model": DETERMINISTIC_SIMPLE_EDIT_MODEL,
        "classifier": classifier_payload,
        "deterministic_simple_edit": {
            "schema": DETERMINISTIC_SIMPLE_EDIT_SCHEMA,
            "route": "gde_transaction",
            "matched_rule": "certified_player_speed",
            "provider_calls": 0,
            "llm_calls": 0,
            "pil_calls": 0,
            "target_path": _PLAYER_SPEED_PATH,
            "old_value": old_value,
            "new_value": value,
            "classifier_category_id": classifier.category_id,
            "classifier_matrix_hash": classifier.matrix_hash,
        },
        "transaction": {
            "operations": [
                {
                    "path": _PLAYER_SPEED_PATH,
                    "op": "SET",
                    "value": value,
                    "type_hint": "float",
                    "field_name": "max_linear_speed",
                    "actor_id": "actor_player",
                    "type_id": 5,
                },
            ],
            "schema_delta_type": "value_mutation",
            "confidence_score": 0.99,
            "risk_level": "low",
            "required_recompile": False,
            "affected_systems": ["MovementSystem"],
            "mutation_summary": f"Set player movement speed to {value_label}.",
            "planner": {
                "schema": DETERMINISTIC_SIMPLE_EDIT_SCHEMA,
                "route": "gde_transaction",
                "provider_calls": 0,
                "pil_calls": 0,
                "llm_calls": 0,
            },
        },
    }


def _deterministic_simple_edit_readiness() -> dict:
    code = "DETERMINISTIC_NO_LLM_SIMPLE_EDIT"
    return {
        "ok": True,
        "provider": "deterministic",
        "model": DETERMINISTIC_SIMPLE_EDIT_MODEL,
        "code": code,
        "message": "This certified simple edit was planned locally without a provider call.",
        "action": "review_prompt_diff",
        "ux_state": {
            "schema": "xace.provider_ux_state.v1",
            "state": "deterministic_no_llm",
            "code": code,
            "label": "No provider needed",
            "message": "This certified simple edit was planned locally without using a provider.",
            "action": "Review and approve the generated CGS diff.",
            "severity": "info",
            "provider": "deterministic",
            "model": DETERMINISTIC_SIMPLE_EDIT_MODEL,
        },
    }


def _format_simple_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _new_prompt_clarification_id(session: BuilderSession, prompt: str, classifier: Any) -> str:
    sequence = len(session.prompt_clarification_log) + 1
    seed = "|".join(
        (
            session.session_id,
            str(sequence),
            str(time.time_ns()),
            prompt,
            str(getattr(classifier, "matrix_hash", "")),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"prompt-clar-{int(time.time() * 1000):013d}-{digest}"


def _build_prompt_diff_preview(
    *,
    session: BuilderSession,
    prompt: str,
    cgs: dict,
    submitted_hash: str,
    mode: str,
    result: dict,
    readiness: dict,
) -> dict:
    txn = result.get("transaction") if isinstance(result.get("transaction"), dict) else {}
    operations = _transaction_preview_operations(txn)
    parent_hash = str(submitted_hash or cgs.get("metadata", {}).get("cgs_hash", "") or "")
    transaction_fingerprint = _hash_json({
        "parent_cgs_hash": parent_hash,
        "operation_format": txn.get("operation_format", "legacy_path_v1"),
        "typed_operation_batch": txn.get("typed_operation_batch"),
        "composite_prompt_plan": txn.get("composite_prompt_plan"),
        "operations": operations,
        "summary": txn.get("mutation_summary", ""),
        "schema_delta_type": txn.get("schema_delta_type", ""),
    })
    preview_id = f"prompt-preview-{int(time.time() * 1000):013d}-{transaction_fingerprint[:12]}"
    cgs_operations = [_preview_operation(cgs, op, index) for index, op in enumerate(operations)]
    required_recompile = (
        isinstance(txn.get("typed_operation_batch"), dict)
        or bool(txn.get("required_recompile"))
        or str(txn.get("schema_delta_type", "")).startswith("structural")
    )
    preview_core = {
        "schema": "xace.prompt_diff_preview.v1",
        "preview_id": preview_id,
        "prompt": prompt,
        "mode": mode,
        "parent_cgs_hash": parent_hash,
        "schema_version": str(cgs.get("metadata", {}).get("schema_version") or cgs.get("metadata", {}).get("version") or ""),
        "transaction_fingerprint": transaction_fingerprint,
        "mutation_summary": str(txn.get("mutation_summary") or ""),
        "risk_level": str(txn.get("risk_level") or "low"),
        "confidence": float(result.get("confidence") or txn.get("confidence_score") or 0.0),
        "approval_required": True,
        "generated_at": time.time(),
        "cgs_diff": {
            "schema": "xace.prompt_diff_preview.cgs.v1",
            "operation_count": len(cgs_operations),
            "operations": cgs_operations,
        },
        "system_diff": _preview_system_diff(txn, operations),
        "asset_diff": _preview_asset_diff(operations),
        "save_diff": _preview_composite_facet_diff(
            txn,
            "save_plan",
            "xace.prompt_diff_preview.save.v1",
        ),
        "network_diff": _preview_composite_facet_diff(
            txn,
            "network_plan",
            "xace.prompt_diff_preview.network.v1",
        ),
        "composite_prompt_plan": copy.deepcopy(
            txn.get("composite_prompt_plan")
            if isinstance(txn.get("composite_prompt_plan"), dict)
            else {}
        ),
        "sgc_diff": {
            "schema": "xace.prompt_diff_preview.sgc.v1",
            "required_recompile": required_recompile,
            "status": "required_before_persist" if required_recompile else "not_required",
            "compile_will_run_on_apply": required_recompile,
            "affected_systems": list(txn.get("affected_systems", [])),
            "plan_hash_before": "unresolved",
            "plan_hash_after": "computed_on_apply" if required_recompile else "unchanged",
        },
        "runtime_diff": {
            "schema": "xace.prompt_diff_preview.runtime.v1",
            "status": "not_run_pre_apply",
            "runtime_connected": bool(session.runtime_connected),
            "runtime_adapter_type": session.runtime_adapter_type,
            "runtime_world_hash_before": session.runtime_last_hash or "unresolved",
            "runtime_tick_before": (session.runtime_last_tick or {}).get("tick") if isinstance(session.runtime_last_tick, dict) else None,
            "will_require_runtime_reload": True,
            "runtime_validation": "deferred_until_apply_feedback",
        },
        "cost_diff": {
            "schema": "xace.prompt_diff_preview.cost.v1",
            "provider": str(readiness.get("provider") or ""),
            "model": str(readiness.get("model") or ""),
            "observed_cost_cents": float(result.get("cost_cents") or 0.0),
            "estimated_apply_cost_cents": 0.0,
            "token_count": int(result.get("tokens") or 0),
            "source": str(result.get("cost_source") or "pil_result_or_streaming_updates_when_available"),
        },
    }
    approval_token = _new_prompt_preview_token(session, preview_core)
    preview_core["approval_token"] = approval_token
    preview_core["approval_token_hash"] = hashlib.sha256(approval_token.encode("utf-8")).hexdigest()
    return preview_core


def _new_prompt_preview_token(session: BuilderSession, preview: dict) -> str:
    seed = {
        "session_id": session.session_id,
        "preview": preview,
        "nonce": time.time_ns(),
    }
    return "pat-" + _hash_json(seed)


def _transaction_preview_operations(txn: dict) -> list[Any]:
    typed_batch = txn.get('typed_operation_batch')
    if isinstance(typed_batch, dict):
        operations = typed_batch.get('operations')
        return list(operations) if isinstance(operations, list) else []
    operations = txn.get('operations')
    return list(operations) if isinstance(operations, list) else []


def _preview_operation(cgs: dict, op: Any, index: int) -> dict:
    if isinstance(op, dict) and isinstance(op.get('kind'), str):
        target_keys = (
            'mode_id', 'actor_id', 'component_type_id', 'component_name',
            'system_id', 'event_name', 'rule_id', 'asset_id',
        )
        return {
            'index': index,
            'operation_format': 'typed_cgs_v1',
            'operation_id': str(op.get('operation_id', '')),
            'kind': str(op.get('kind', '')),
            'target': {key: op[key] for key in target_keys if key in op},
            'explanation': str(op.get('explanation', '')),
            'typed_details': {
                key: copy.deepcopy(value)
                for key, value in op.items()
                if key not in {'operation_id', 'kind', 'explanation'}
            },
        }
    if not isinstance(op, dict):
        return {
            "index": index,
            "op": "invalid",
            "path": "",
            "old_value": None,
            "new_value": None,
            "preview_value": None,
            "type_hint": "",
            "field_name": "",
            "actor_id": "",
            "component_type_id": None,
        }
    path = str(op.get("path", ""))
    old_value = _read_cgs_preview_path(cgs, path)
    op_name = str(op.get("op", "SET"))
    new_value = op.get("value")
    preview_value = new_value
    if op_name == "SCALE" and isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
        preview_value = old_value * new_value
    return {
        "index": index,
        "op": op_name,
        "path": path,
        "old_value": old_value,
        "new_value": new_value,
        "preview_value": preview_value,
        "type_hint": str(op.get("type_hint", "")),
        "field_name": str(op.get("field_name", "")),
        "actor_id": str(op.get("actor_id", "")),
        "component_type_id": op.get("type_id"),
    }


def _preview_system_diff(txn: dict, operations: list[Any]) -> dict:
    added: list[str] = []
    removed: list[str] = []
    touched: list[str] = []
    for typed_operation in operations:
        if not isinstance(typed_operation, dict):
            continue
        if typed_operation.get('kind') not in {
            'add_system',
            'add_generated_system',
        }:
            continue
        system_id = str(typed_operation.get('system_id', ''))
        if system_id and system_id not in touched:
            touched.append(system_id)
            added.append(system_id)
    for op in operations:
        if not isinstance(op, dict):
            continue
        path = str(op.get("path", ""))
        op_name = str(op.get("op", ""))
        if "system" in path.lower() or op_name in {"ADD_SYSTEM", "REMOVE_SYSTEM"}:
            sid = _system_id_from_operation(op)
            if sid and sid not in touched:
                touched.append(sid)
            if op_name == "ADD_SYSTEM" and sid:
                added.append(sid)
            if op_name == "REMOVE_SYSTEM" and sid:
                removed.append(sid)
    return {
        "schema": "xace.prompt_diff_preview.system.v1",
        "affected_systems": list(txn.get("affected_systems", [])),
        "touched_systems": touched,
        "added_systems": added,
        "removed_systems": removed,
        "required_recompile": bool(txn.get("required_recompile")),
        "schema_delta_type": str(txn.get("schema_delta_type") or ""),
    }


def _system_id_from_operation(op: dict) -> str:
    value = op.get("value")
    if isinstance(value, dict):
        for key in ("id", "system_id", "name"):
            if value.get(key):
                return str(value[key])
    path = str(op.get("path", ""))
    parts = [part for part in path.replace("/", ".").split(".") if part]
    for index, part in enumerate(parts):
        if part in {"systems", "global_systems"} and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _preview_asset_diff(operations: list[Any]) -> dict:
    touched: list[dict] = []
    for index, typed_operation in enumerate(operations):
        if not isinstance(typed_operation, dict):
            continue
        if typed_operation.get('kind') != 'add_asset':
            continue
        touched.append({
            'index': index,
            'operation_format': 'typed_cgs_v1',
            'operation_id': str(typed_operation.get('operation_id', '')),
            'kind': 'add_asset',
            'asset_id': str(typed_operation.get('asset_id', '')),
            'asset_type': str(typed_operation.get('asset_type', '')),
            'status': str(typed_operation.get('status', '')),
        })
    asset_markers = ("asset", "mesh", "audio", "animation", "semantic_binding", "binding", "prefab", "vfx")
    for index, op in enumerate(operations):
        if not isinstance(op, dict):
            continue
        if isinstance(op.get('kind'), str):
            continue
        path = str(op.get("path", ""))
        value_text = json.dumps(op.get("value"), sort_keys=True, default=str)
        if any(marker in path.lower() or marker in value_text.lower() for marker in asset_markers):
            touched.append({
                "index": index,
                "op": str(op.get("op", "")),
                "path": path,
                "value": op.get("value"),
            })
    return {
        "schema": "xace.prompt_diff_preview.asset.v1",
        "operation_count": len(touched),
        "operations": touched,
        "status": "changed" if touched else "unchanged",
    }


def _preview_composite_facet_diff(
    txn: dict,
    plan_key: str,
    schema: str,
) -> dict:
    composite = txn.get("composite_prompt_plan")
    plan = composite.get(plan_key) if isinstance(composite, dict) else None
    if not isinstance(plan, dict):
        return {
            "schema": schema,
            "status": "unplanned",
            "operation_count": 0,
            "operation_ids": [],
            "component_type_ids": [],
            "policy": {},
        }
    operation_ids = list(plan.get("operation_ids") or [])
    return {
        "schema": schema,
        "status": str(plan.get("status") or ("planned" if operation_ids else "not_touched")),
        "operation_count": len(operation_ids),
        "operation_ids": operation_ids,
        "component_type_ids": list(plan.get("component_type_ids") or []),
        "policy": copy.deepcopy(plan.get("policy") if isinstance(plan.get("policy"), dict) else {}),
    }


def _read_cgs_preview_path(cgs: dict, path: str) -> Any:
    if not path:
        return None
    current: Any = cgs
    previous = ""
    for segment in path.replace("/", ".").split("."):
        if segment == "":
            continue
        if isinstance(current, list):
            current = _list_item_for_preview_path(current, previous, segment)
            if current is None:
                return None
        elif isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
        else:
            return None
        previous = segment
    return current


def _list_item_for_preview_path(items: list[Any], previous: str, segment: str) -> Any:
    if previous == "components":
        for item in items:
            if isinstance(item, dict) and str(item.get("type_id")) == segment:
                return item
    for item in items:
        if isinstance(item, dict) and str(item.get("id")) == segment:
            return item
    try:
        index = int(segment)
    except ValueError:
        return None
    return items[index] if 0 <= index < len(items) else None


def _prompt_test_mode_override(message: dict, preview: dict) -> dict | None:
    if not bool(message.get("test_mode_override")):
        return None
    reason = str(message.get("test_mode_reason") or "").strip()
    if not reason:
        return {
            "schema": "xace.prompt_preview_approval.v1",
            "preview_id": str(preview.get("preview_id") or ""),
            "approved": False,
            "approval_source": "test_mode_override",
            "reason": "missing_test_mode_reason",
            "timestamp": time.time(),
            "test_mode_override": True,
        }
    return {
        "schema": "xace.prompt_preview_approval.v1",
        "preview_id": str(preview.get("preview_id") or ""),
        "transaction_fingerprint": str(preview.get("transaction_fingerprint") or ""),
        "approved": True,
        "approval_source": "test_mode_override",
        "approved_by": str(message.get("approved_by") or "automated-test"),
        "reason": reason[:240],
        "timestamp": time.time(),
        "test_mode_override": True,
    }


def _trim_prompt_preview_log(session: BuilderSession) -> None:
    if len(session.prompt_preview_approval_log) > 256:
        del session.prompt_preview_approval_log[:-256]


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _bounded_prompt_clarification_answer(
    answer: str,
    question: dict,
) -> tuple[list[str], str]:
    cleaned = answer.strip()
    if not cleaned:
        return [], "Choose one of the clarification options before continuing."
    if len(cleaned) > 240:
        return [], "Clarification answers are bounded to 240 characters."

    options = [str(option) for option in question.get("options", [])]
    question_type = str(question.get("question_type") or "")
    if question_type == "SCOPE_SELECT":
        selected = [part.strip() for part in cleaned.split(",") if part.strip()]
        if not selected:
            return [], "Choose at least one scope option before continuing."
        unknown = [part for part in selected if part not in options]
        if unknown:
            return [], "Choose only the listed scope options before continuing."
        if len(set(selected)) != len(selected):
            return [], "Choose each listed scope option at most once."
        if len(selected) > len(options):
            return [], "Choose each listed scope option at most once."
        return selected, ""

    if options and cleaned not in options:
        return [], "Choose one of the listed clarification options before continuing."
    return [cleaned], ""


def _resolved_prompt_prefill(resolution: dict) -> str:
    prompt = str(resolution.get("original_prompt") or "").strip()
    answer = str(resolution.get("answer") or "").strip()
    if not prompt:
        return ""
    if not answer:
        return prompt
    return f"{prompt} [clarified scope: {answer}]"


def _err(reason: str) -> dict:
    return {
        "kind": "error", "reason": reason,
        "turn_index": 0, "intent_category": "", "confidence": 0.0,
        "mode_profile_warnings": [],
    }


def _blocked(reason: str, source: dict | None = None) -> dict:
    source = source or {}
    result = {
        "kind": "blocked",
        "reason": reason,
        "guard": str(source.get("guard") or "prompt_pipeline_contract"),
        "turn_index": int(source.get("turn_index", 0) or 0),
        "intent_category": str(source.get("intent_category", "MutationRequest")),
        "confidence": float(source.get("confidence", 0.0) or 0.0),
        "mode_profile_warnings": list(source.get("mode_profile_warnings", [])),
    }
    for key in ("code", "action", "unsupported", "ux_state"):
        if key in source:
            result[key] = source[key]
    return result


def _pending_transaction_block_reason(txn: Any) -> str:
    legacy_schema_adds = {'ADD_COMPONENT', 'ADD_SYSTEM', 'ADD_RULE'}
    if isinstance(txn, dict) and (
        txn.get('operation_format') == 'typed_cgs_v1'
        or 'typed_operation_batch' in txn
    ):
        typed_batch = txn.get('typed_operation_batch')
        if txn.get('operation_format') != 'typed_cgs_v1':
            return 'Typed CGS operations require operation_format typed_cgs_v1.'
        if not isinstance(typed_batch, dict):
            return 'Typed CGS mutation is missing typed_operation_batch.'
        legacy_operations = txn.get('operations', [])
        if legacy_operations not in (None, []):
            return 'Mixed typed and path-based mutation operations are not allowed.'
        try:
            from typed_operations import (
                parse_typed_operation_batch,
                validate_composite_prompt_plan,
            )

            # This transaction is the server-retained result of PIL's local
            # generated-system materializer.  Provider output is parsed with
            # the default (False) at Pass 2; the trusted handoff must permit
            # the locally signed runtime_executor so GDE can verify it again.
            parsed_batch = parse_typed_operation_batch(
                typed_batch,
                allow_materialized_generated_systems=True,
            )
            composite_plan = txn.get("composite_prompt_plan")
            if isinstance(composite_plan, dict):
                composite_validation = validate_composite_prompt_plan(
                    composite_plan,
                    parsed_batch,
                )
                if not composite_validation.valid:
                    return (
                        "Composite prompt plan is invalid: "
                        + "; ".join(composite_validation.errors[:3])
                    )
        except Exception as exc:
            return f'Typed CGS operation batch is invalid: {exc}'
        return ''

    if not isinstance(txn, dict):
        return "PIL did not return a CGS mutation transaction."

    operations = txn.get("operations")
    if not isinstance(operations, list):
        return "PIL returned a transaction with an invalid operations list."
    if not operations:
        summary = str(txn.get("mutation_summary", "")).strip()
        return summary or (
            "This prompt did not produce a safe CGS mutation. "
            "Make the requested edit more specific and try again."
        )

    supported_ops = {
        "SET",
        "SCALE",
        "ADD_ACTOR",
        "REMOVE_ACTOR",
        "ADD_COMPONENT",
        "REMOVE_COMPONENT",
        "ADD_SYSTEM",
        "REMOVE_SYSTEM",
        "ADD_RULE",
        "REMOVE_RULE",
    }
    structural_adds = {"ADD_ACTOR", "ADD_COMPONENT", "ADD_SYSTEM", "ADD_RULE"}
    for index, op in enumerate(operations):
        if not isinstance(op, dict):
            return f"Operation {index} is not a valid mutation object."
        op_name = str(op.get("op", "SET"))
        if op_name in legacy_schema_adds:
            return (
                f'Operation {index} uses legacy structural op {op_name!r}; '
                'new components, systems, and rules require typed CGS operations.'
            )
        if op_name not in supported_ops:
            return f"Operation {index} uses unsupported mutation op '{op_name}'."
        if not str(op.get("path", "")).strip():
            return f"Operation {index} is missing a CGS target path."
        if op_name in structural_adds and not isinstance(op.get("value"), dict):
            return f"Operation {index} must include a structural value object."

    return ""


def _stamp_pending_transaction_authority(txn: Any, cgs: dict, submitted_hash: str) -> None:
    if not isinstance(txn, dict):
        return
    meta = cgs.get("metadata", {}) if isinstance(cgs, dict) else {}
    current_hash = str(meta.get("cgs_hash", "") or "")
    parent_hash = str(submitted_hash or current_hash)
    schema_version = str(meta.get("schema_version") or meta.get("version") or "")
    txn.setdefault("source", "prompt")
    txn.setdefault("parent_cgs_hash", parent_hash)
    txn.setdefault("cgs_hash", parent_hash)
    version_ids = txn.setdefault("version_ids", {})
    if isinstance(version_ids, dict):
        version_ids.setdefault("cgs_hash", parent_hash)
        version_ids.setdefault("schema_version", schema_version)
        version_ids.setdefault("execution_plan_version", "unresolved")
        version_ids.setdefault("runtime_world_hash", "unresolved")
        version_ids.setdefault("runtime_tick", None)
        version_ids.setdefault("engine_adapter_sequence", None)


def _gde_mutation_source(txn_dict: dict) -> str:
    source = str(txn_dict.get("source", "") or "")
    if source in {"genesis", "prompt", "manual", "migration", "rollback", "import"}:
        return source
    return "manual"


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
        d["auto_committed"] = result.auto_committed
        d["diff_text"]      = result.diff_text

        typed_mutation = getattr(result, "typed_mutation", None)
        if typed_mutation is not None:
            normalized_batch = copy.deepcopy(
                getattr(typed_mutation, "normalized_batch", None)
            )
            composite_plan_obj = getattr(typed_mutation, "composite_plan", None)
            composite_plan = (
                composite_plan_obj.to_dict()
                if composite_plan_obj is not None
                else None
            )
            batch_operations = (
                normalized_batch.get("operations", [])
                if isinstance(normalized_batch, dict)
                else []
            )
            operation_kinds = {
                str(operation.get("kind", ""))
                for operation in batch_operations
                if isinstance(operation, dict)
            }
            structural = operation_kinds != {"set_defaults"}
            affected_systems = [
                str(operation.get("system_id"))
                for operation in batch_operations
                if (
                    isinstance(operation, dict)
                    and operation.get("kind") in {
                        "add_system",
                        "add_generated_system",
                    }
                    and operation.get("system_id")
                )
            ]
            d["transaction"] = {
                "operation_format": "typed_cgs_v1",
                "typed_operation_batch": normalized_batch,
                "operations": [],
                "schema_delta_type": (
                    "structural_add" if structural else "value_mutation"
                ),
                "confidence_score": float(
                    getattr(
                        result,
                        "confidence",
                        getattr(typed_mutation, "parser_confidence", 0.0),
                    )
                    or 0.0
                ),
                "risk_level": "medium" if structural else "low",
                "required_recompile": True,
                "affected_systems": affected_systems,
                "mutation_summary": (
                    str(normalized_batch.get("summary", ""))
                    if isinstance(normalized_batch, dict)
                    else ""
                ),
                "composite_prompt_plan": composite_plan,
            }
            return d

        txn = result.transaction
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

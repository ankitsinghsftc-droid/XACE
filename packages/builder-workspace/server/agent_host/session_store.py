"""Durable indexed Agent Mode session store.

AG-003 keeps provider-agent history outside the in-memory WebSocket session.
The store is intentionally not wired into Builder's default API/BYOK prompt
path yet.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from secret_redaction import redact_exception, redact_text, redact_value

from .contracts import (
    AGENT_CONTRACT_SCHEMA,
    AgentContractError,
    AgentEvent,
    AgentProposalEnvelope,
    AgentSessionHandle,
    JsonValue,
    normalize_json_value,
    utc_now_iso,
)


AGENT_SESSION_STORE_SCHEMA = "xace.agent_session_store.v1"
AGENT_SESSION_DB_FILENAME = "agent_sessions.sqlite3"
AGENT_SESSION_AUDIT_FILENAME = "agent_sessions.audit.jsonl"
SCHEMA_VERSION = 1


class AgentSessionStoreError(RuntimeError):
    """Raised when the durable agent session store cannot be used safely."""


@dataclass(frozen=True)
class AgentStoredSession:
    xace_session_id: str
    provider_id: str
    provider_session_id: str
    base_cgs_hash: str
    latest_cgs_hash: str
    mode: str = "agent"
    parent_xace_session_id: str = ""
    parent_provider_session_id: str = ""
    branch_name: str = ""
    title: str = ""
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = AGENT_SESSION_STORE_SCHEMA

    def __post_init__(self) -> None:
        _require_schema(self.schema)
        _require_identifier(self.xace_session_id, "xace_session_id")
        _require_identifier(self.provider_id, "provider_id")
        _require_nonempty(self.provider_session_id, "provider_session_id")
        _require_cgs_hash(self.base_cgs_hash, "base_cgs_hash")
        _require_cgs_hash(self.latest_cgs_hash, "latest_cgs_hash")
        if self.parent_xace_session_id:
            _require_identifier(self.parent_xace_session_id, "parent_xace_session_id")
        object.__setattr__(
            self,
            "metadata",
            _json_object(self.metadata, "session metadata"),
        )

    @classmethod
    def from_handle(
        cls,
        handle: AgentSessionHandle,
        *,
        mode: str = "agent",
        parent_xace_session_id: str = "",
        parent_provider_session_id: str = "",
        branch_name: str = "",
        title: str = "",
        summary: str = "",
        metadata: Mapping[str, Any] | None = None,
        updated_at: str = "",
    ) -> "AgentStoredSession":
        latest_hash = handle.latest_cgs_hash or handle.base_cgs_hash
        return cls(
            xace_session_id=handle.xace_session_id,
            provider_id=handle.provider_id,
            provider_session_id=handle.provider_session_id,
            base_cgs_hash=handle.base_cgs_hash,
            latest_cgs_hash=latest_hash,
            mode=mode,
            parent_xace_session_id=parent_xace_session_id,
            parent_provider_session_id=parent_provider_session_id,
            branch_name=branch_name,
            title=title,
            summary=summary,
            created_at=handle.created_at or utc_now_iso(),
            updated_at=updated_at or handle.created_at or utc_now_iso(),
            metadata={**dict(handle.metadata), **dict(metadata or {})},
        )

    def to_handle(self) -> AgentSessionHandle:
        return AgentSessionHandle(
            xace_session_id=self.xace_session_id,
            provider_id=self.provider_id,
            provider_session_id=self.provider_session_id,
            base_cgs_hash=self.base_cgs_hash,
            latest_cgs_hash=self.latest_cgs_hash,
            created_at=self.created_at,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "xace_session_id": self.xace_session_id,
            "provider_id": self.provider_id,
            "provider_session_id": self.provider_session_id,
            "base_cgs_hash": self.base_cgs_hash,
            "latest_cgs_hash": self.latest_cgs_hash,
            "mode": self.mode,
            "parent_xace_session_id": self.parent_xace_session_id,
            "parent_provider_session_id": self.parent_provider_session_id,
            "branch_name": self.branch_name,
            "title": self.title,
            "summary": self.summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentStoredSession":
        return cls(
            xace_session_id=str(value.get("xace_session_id", "")),
            provider_id=str(value.get("provider_id", "")),
            provider_session_id=str(value.get("provider_session_id", "")),
            base_cgs_hash=str(value.get("base_cgs_hash", "")),
            latest_cgs_hash=str(value.get("latest_cgs_hash", "")),
            mode=str(value.get("mode", "agent")),
            parent_xace_session_id=str(value.get("parent_xace_session_id", "")),
            parent_provider_session_id=str(value.get("parent_provider_session_id", "")),
            branch_name=str(value.get("branch_name", "")),
            title=str(value.get("title", "")),
            summary=str(value.get("summary", "")),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
            metadata=_json_object(value.get("metadata", {}), "session metadata"),
            schema=str(value.get("schema", AGENT_SESSION_STORE_SCHEMA)),
        )


@dataclass(frozen=True)
class AgentToolCallRecord:
    tool_call_id: str
    xace_session_id: str
    provider_id: str
    tool_name: str
    permission: str
    transport: str
    status: str
    event_id: str = ""
    cgs_hash: str = ""
    request: Mapping[str, Any] = field(default_factory=dict)
    response: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    completed_at: str = ""
    schema: str = AGENT_SESSION_STORE_SCHEMA

    def __post_init__(self) -> None:
        _require_schema(self.schema)
        _require_identifier(self.tool_call_id, "tool_call_id")
        _require_identifier(self.xace_session_id, "xace_session_id")
        _require_identifier(self.provider_id, "provider_id")
        _require_identifier(self.tool_name, "tool_name")
        _require_nonempty(self.permission, "permission")
        _require_nonempty(self.transport, "transport")
        _require_nonempty(self.status, "status")
        if self.event_id:
            _require_identifier(self.event_id, "event_id")
        if self.cgs_hash:
            _require_cgs_hash(self.cgs_hash, "cgs_hash")
        object.__setattr__(self, "request", _json_object(self.request, "request"))
        object.__setattr__(self, "response", _json_object(self.response, "response"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "tool_call_id": self.tool_call_id,
            "xace_session_id": self.xace_session_id,
            "provider_id": self.provider_id,
            "tool_name": self.tool_name,
            "permission": self.permission,
            "transport": self.transport,
            "status": self.status,
            "event_id": self.event_id,
            "cgs_hash": self.cgs_hash,
            "request": dict(self.request),
            "response": dict(self.response),
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass(frozen=True)
class AgentMutationLineageRecord:
    mutation_id: str
    proposal_id: str
    xace_session_id: str
    provider_id: str
    base_cgs_hash: str
    result_cgs_hash: str
    gde_transaction_id: str
    status: str
    summary: str
    sgc_plan_id: str = ""
    runtime_validation_id: str = ""
    created_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = AGENT_SESSION_STORE_SCHEMA

    def __post_init__(self) -> None:
        _require_schema(self.schema)
        _require_identifier(self.mutation_id, "mutation_id")
        _require_identifier(self.proposal_id, "proposal_id")
        _require_identifier(self.xace_session_id, "xace_session_id")
        _require_identifier(self.provider_id, "provider_id")
        _require_cgs_hash(self.base_cgs_hash, "base_cgs_hash")
        _require_cgs_hash(self.result_cgs_hash, "result_cgs_hash")
        _require_nonempty(self.gde_transaction_id, "gde_transaction_id")
        _require_nonempty(self.status, "status")
        _require_nonempty(self.summary, "summary")
        object.__setattr__(
            self,
            "metadata",
            _json_object(self.metadata, "mutation metadata"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "mutation_id": self.mutation_id,
            "proposal_id": self.proposal_id,
            "xace_session_id": self.xace_session_id,
            "provider_id": self.provider_id,
            "base_cgs_hash": self.base_cgs_hash,
            "result_cgs_hash": self.result_cgs_hash,
            "gde_transaction_id": self.gde_transaction_id,
            "sgc_plan_id": self.sgc_plan_id,
            "runtime_validation_id": self.runtime_validation_id,
            "status": self.status,
            "summary": self.summary,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


class AgentSessionStore:
    """SQLite-backed session history for Agent Mode."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        db_path: str | Path | None = None,
        audit_jsonl: bool = False,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.store_dir = self.project_root / ".xace" / "agent_sessions"
        self.db_path = Path(db_path).resolve() if db_path else self.store_dir / AGENT_SESSION_DB_FILENAME
        self.audit_path = (
            self.store_dir / AGENT_SESSION_AUDIT_FILENAME if audit_jsonl else None
        )
        self._initialize()

    def upsert_session(self, session: AgentStoredSession | AgentSessionHandle) -> None:
        stored = (
            session if isinstance(session, AgentStoredSession)
            else AgentStoredSession.from_handle(session)
        )
        now = stored.updated_at or utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    xace_session_id, provider_id, provider_session_id, mode,
                    base_cgs_hash, latest_cgs_hash, parent_xace_session_id,
                    parent_provider_session_id, branch_name, title, summary,
                    created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(xace_session_id) DO UPDATE SET
                    provider_id=excluded.provider_id,
                    provider_session_id=excluded.provider_session_id,
                    mode=excluded.mode,
                    latest_cgs_hash=excluded.latest_cgs_hash,
                    parent_xace_session_id=excluded.parent_xace_session_id,
                    parent_provider_session_id=excluded.parent_provider_session_id,
                    branch_name=excluded.branch_name,
                    title=excluded.title,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    stored.xace_session_id,
                    stored.provider_id,
                    stored.provider_session_id,
                    stored.mode,
                    stored.base_cgs_hash,
                    stored.latest_cgs_hash,
                    stored.parent_xace_session_id,
                    stored.parent_provider_session_id,
                    _redact_text(stored.branch_name),
                    _redact_text(stored.title),
                    _redact_text(stored.summary),
                    stored.created_at or now,
                    now,
                    _dumps(stored.metadata),
                ),
            )
        self._append_audit("session_upsert", stored.to_dict())

    def get_session(self, xace_session_id: str) -> AgentStoredSession | None:
        _require_identifier(xace_session_id, "xace_session_id")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE xace_session_id = ?",
                (xace_session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def find_session_by_provider(
        self,
        provider_id: str,
        provider_session_id: str,
    ) -> AgentStoredSession | None:
        _require_identifier(provider_id, "provider_id")
        _require_nonempty(provider_session_id, "provider_session_id")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM sessions
                WHERE provider_id = ? AND provider_session_id = ?
                """,
                (provider_id, provider_session_id),
            ).fetchone()
        return _session_from_row(row) if row else None

    def list_sessions(
        self,
        *,
        provider_id: str = "",
        parent_xace_session_id: str | None = None,
        limit: int = 50,
    ) -> tuple[AgentStoredSession, ...]:
        _require_limit(limit)
        where: list[str] = []
        args: list[Any] = []
        if provider_id:
            _require_identifier(provider_id, "provider_id")
            where.append("provider_id = ?")
            args.append(provider_id)
        if parent_xace_session_id is not None:
            if parent_xace_session_id:
                _require_identifier(parent_xace_session_id, "parent_xace_session_id")
            where.append("parent_xace_session_id = ?")
            args.append(parent_xace_session_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM sessions
                {clause}
                ORDER BY updated_at DESC, xace_session_id ASC
                LIMIT ?
                """,
                (*args, limit),
            ).fetchall()
        return tuple(_session_from_row(row) for row in rows)

    def record_event(self, event: AgentEvent) -> None:
        self._require_session(event.session_id)
        created_at = event.created_at or utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (
                    event_id, xace_session_id, provider_id, event_type,
                    sequence, message, created_at, data_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.session_id,
                    event.provider_id,
                    event.event_type.value,
                    event.sequence,
                    _redact_text(event.message),
                    created_at,
                    _dumps(event.data),
                ),
            )
            conn.execute(
                """
                UPDATE sessions
                SET updated_at = ?
                WHERE xace_session_id = ?
                """,
                (created_at, event.session_id),
            )
        self._append_audit("event_recorded", event.to_dict())

    def list_events(
        self,
        xace_session_id: str,
        *,
        event_type: str = "",
        limit: int = 100,
    ) -> tuple[AgentEvent, ...]:
        _require_identifier(xace_session_id, "xace_session_id")
        _require_limit(limit)
        args: list[Any] = [xace_session_id]
        type_clause = ""
        if event_type:
            type_clause = "AND event_type = ?"
            args.append(event_type)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM events
                WHERE xace_session_id = ?
                {type_clause}
                ORDER BY sequence ASC, created_at ASC, event_id ASC
                LIMIT ?
                """,
                (*args, limit),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def record_tool_call(self, record: AgentToolCallRecord) -> None:
        self._require_session(record.xace_session_id)
        created_at = record.created_at or utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tool_calls (
                    tool_call_id, xace_session_id, provider_id, tool_name,
                    permission, transport, status, event_id, cgs_hash,
                    request_json, response_json, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.tool_call_id,
                    record.xace_session_id,
                    record.provider_id,
                    record.tool_name,
                    record.permission,
                    record.transport,
                    record.status,
                    record.event_id,
                    record.cgs_hash,
                    _dumps(record.request),
                    _dumps(record.response),
                    created_at,
                    record.completed_at,
                ),
            )
        self._append_audit("tool_call_recorded", record.to_dict())

    def list_tool_calls(
        self,
        xace_session_id: str,
        *,
        tool_name: str = "",
        limit: int = 100,
    ) -> tuple[AgentToolCallRecord, ...]:
        _require_identifier(xace_session_id, "xace_session_id")
        _require_limit(limit)
        args: list[Any] = [xace_session_id]
        tool_clause = ""
        if tool_name:
            _require_identifier(tool_name, "tool_name")
            tool_clause = "AND tool_name = ?"
            args.append(tool_name)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM tool_calls
                WHERE xace_session_id = ?
                {tool_clause}
                ORDER BY created_at ASC, tool_call_id ASC
                LIMIT ?
                """,
                (*args, limit),
            ).fetchall()
        return tuple(_tool_call_from_row(row) for row in rows)

    def record_proposal(
        self,
        proposal: AgentProposalEnvelope,
        *,
        status: str = "pending",
        approval_id: str = "",
        mutation_transaction_id: str = "",
    ) -> None:
        self._require_session(proposal.session_id)
        _require_nonempty(status, "proposal status")
        now = utc_now_iso()
        payload = proposal.to_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    proposal_id, xace_session_id, provider_id, base_cgs_hash,
                    intent, proposal_kind, risk_level, status, summary,
                    requires_structural_regeneration, payload_json, created_at,
                    updated_at, mutation_transaction_id, approval_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    status=excluded.status,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at,
                    mutation_transaction_id=excluded.mutation_transaction_id,
                    approval_id=excluded.approval_id,
                    payload_json=excluded.payload_json
                """,
                (
                    proposal.proposal_id,
                    proposal.session_id,
                    proposal.provider_id,
                    proposal.base_cgs_hash,
                    _redact_text(proposal.intent),
                    proposal.proposal_kind.value,
                    proposal.risk_level.value,
                    status,
                    _redact_text(proposal.summary),
                    int(proposal.requires_structural_regeneration),
                    _dumps(payload),
                    now,
                    now,
                    mutation_transaction_id,
                    approval_id,
                ),
            )
        self._append_audit(
            "proposal_recorded",
            {
                "status": status,
                "approval_id": approval_id,
                "mutation_transaction_id": mutation_transaction_id,
                "proposal": payload,
            },
        )

    def update_proposal_status(
        self,
        proposal_id: str,
        *,
        status: str,
        approval_id: str = "",
        mutation_transaction_id: str = "",
    ) -> None:
        _require_identifier(proposal_id, "proposal_id")
        _require_nonempty(status, "proposal status")
        now = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE proposals
                SET status = ?,
                    approval_id = CASE WHEN ? = '' THEN approval_id ELSE ? END,
                    mutation_transaction_id = CASE WHEN ? = '' THEN mutation_transaction_id ELSE ? END,
                    updated_at = ?
                WHERE proposal_id = ?
                """,
                (
                    status,
                    approval_id,
                    approval_id,
                    mutation_transaction_id,
                    mutation_transaction_id,
                    now,
                    proposal_id,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentSessionStoreError(f"unknown proposal {proposal_id!r}")
        self._append_audit(
            "proposal_status_updated",
            {
                "proposal_id": proposal_id,
                "status": status,
                "approval_id": approval_id,
                "mutation_transaction_id": mutation_transaction_id,
            },
        )

    def get_proposal(self, proposal_id: str) -> dict[str, JsonValue] | None:
        _require_identifier(proposal_id, "proposal_id")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return _proposal_from_row(row) if row else None

    def list_proposals(
        self,
        xace_session_id: str,
        *,
        status: str = "",
        limit: int = 100,
    ) -> tuple[dict[str, JsonValue], ...]:
        _require_identifier(xace_session_id, "xace_session_id")
        _require_limit(limit)
        args: list[Any] = [xace_session_id]
        status_clause = ""
        if status:
            status_clause = "AND status = ?"
            args.append(status)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM proposals
                WHERE xace_session_id = ?
                {status_clause}
                ORDER BY created_at ASC, proposal_id ASC
                LIMIT ?
                """,
                (*args, limit),
            ).fetchall()
        return tuple(_proposal_from_row(row) for row in rows)

    def record_mutation_lineage(self, record: AgentMutationLineageRecord) -> None:
        self._require_session(record.xace_session_id)
        now = record.created_at or utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mutations (
                    mutation_id, proposal_id, xace_session_id, provider_id,
                    base_cgs_hash, result_cgs_hash, gde_transaction_id,
                    sgc_plan_id, runtime_validation_id, status, summary,
                    created_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.mutation_id,
                    record.proposal_id,
                    record.xace_session_id,
                    record.provider_id,
                    record.base_cgs_hash,
                    record.result_cgs_hash,
                    record.gde_transaction_id,
                    record.sgc_plan_id,
                    record.runtime_validation_id,
                    record.status,
                    _redact_text(record.summary),
                    now,
                    _dumps(record.metadata),
                ),
            )
        self._append_audit("mutation_lineage_recorded", record.to_dict())

    def list_mutations(
        self,
        xace_session_id: str,
        *,
        proposal_id: str = "",
        limit: int = 100,
    ) -> tuple[AgentMutationLineageRecord, ...]:
        _require_identifier(xace_session_id, "xace_session_id")
        _require_limit(limit)
        args: list[Any] = [xace_session_id]
        proposal_clause = ""
        if proposal_id:
            _require_identifier(proposal_id, "proposal_id")
            proposal_clause = "AND proposal_id = ?"
            args.append(proposal_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM mutations
                WHERE xace_session_id = ?
                {proposal_clause}
                ORDER BY created_at ASC, mutation_id ASC
                LIMIT ?
                """,
                (*args, limit),
            ).fetchall()
        return tuple(_mutation_from_row(row) for row in rows)

    def export_session(self, xace_session_id: str) -> dict[str, JsonValue]:
        session = self.get_session(xace_session_id)
        if session is None:
            raise AgentSessionStoreError(f"unknown session {xace_session_id!r}")
        return {
            "schema": AGENT_SESSION_STORE_SCHEMA,
            "session": session.to_dict(),
            "events": [event.to_dict() for event in self.list_events(xace_session_id)],
            "tool_calls": [
                call.to_dict() for call in self.list_tool_calls(xace_session_id)
            ],
            "proposals": list(self.list_proposals(xace_session_id)),
            "mutations": [
                mutation.to_dict()
                for mutation in self.list_mutations(xace_session_id)
            ],
        }

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.audit_path is not None:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as conn:
                _create_schema(conn)
                version = conn.execute(
                    "SELECT value FROM store_meta WHERE key = 'schema_version'"
                ).fetchone()
                if version is None:
                    conn.execute(
                        "INSERT INTO store_meta (key, value) VALUES (?, ?)",
                        ("schema_version", str(SCHEMA_VERSION)),
                    )
                elif str(version["value"]) != str(SCHEMA_VERSION):
                    raise AgentSessionStoreError(
                        "unsupported agent session store schema "
                        f"{version['value']!r}"
                    )
        except AgentSessionStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise AgentSessionStoreError(
                f"agent session store is unavailable or corrupt: {redact_exception(exc)}"
            ) from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
            conn.commit()
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except sqlite3.DatabaseError:
                    pass
            raise AgentSessionStoreError(
                f"agent session store is unavailable or corrupt: {redact_exception(exc)}"
            ) from exc
        finally:
            if conn is not None:
                conn.close()

    def _require_session(self, xace_session_id: str) -> None:
        if self.get_session(xace_session_id) is None:
            raise AgentSessionStoreError(f"unknown agent session {xace_session_id!r}")

    def _append_audit(self, kind: str, payload: Mapping[str, Any]) -> None:
        if self.audit_path is None:
            return
        audit_payload = {
            "schema": AGENT_SESSION_STORE_SCHEMA,
            "kind": kind,
            "created_at": utc_now_iso(),
            "payload": payload,
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(_dumps(audit_payload) + "\n")


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS store_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            xace_session_id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            provider_session_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            base_cgs_hash TEXT NOT NULL,
            latest_cgs_hash TEXT NOT NULL,
            parent_xace_session_id TEXT NOT NULL DEFAULT '',
            parent_provider_session_id TEXT NOT NULL DEFAULT '',
            branch_name TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_sessions_provider_thread
            ON sessions(provider_id, provider_session_id);
        CREATE INDEX IF NOT EXISTS idx_agent_sessions_parent
            ON sessions(parent_xace_session_id);
        CREATE INDEX IF NOT EXISTS idx_agent_sessions_provider
            ON sessions(provider_id);

        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            xace_session_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(xace_session_id) REFERENCES sessions(xace_session_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_events_session_sequence
            ON events(xace_session_id, sequence, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_events_type
            ON events(event_type);

        CREATE TABLE IF NOT EXISTS tool_calls (
            tool_call_id TEXT PRIMARY KEY,
            xace_session_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            permission TEXT NOT NULL,
            transport TEXT NOT NULL,
            status TEXT NOT NULL,
            event_id TEXT NOT NULL DEFAULT '',
            cgs_hash TEXT NOT NULL DEFAULT '',
            request_json TEXT NOT NULL DEFAULT '{}',
            response_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            completed_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(xace_session_id) REFERENCES sessions(xace_session_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_session
            ON tool_calls(xace_session_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_name
            ON tool_calls(tool_name);

        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY,
            xace_session_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            base_cgs_hash TEXT NOT NULL,
            intent TEXT NOT NULL,
            proposal_kind TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            requires_structural_regeneration INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            mutation_transaction_id TEXT NOT NULL DEFAULT '',
            approval_id TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(xace_session_id) REFERENCES sessions(xace_session_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_proposals_session_status
            ON proposals(xace_session_id, status, created_at);

        CREATE TABLE IF NOT EXISTS mutations (
            mutation_id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            xace_session_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            base_cgs_hash TEXT NOT NULL,
            result_cgs_hash TEXT NOT NULL,
            gde_transaction_id TEXT NOT NULL,
            sgc_plan_id TEXT NOT NULL DEFAULT '',
            runtime_validation_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(xace_session_id) REFERENCES sessions(xace_session_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_mutations_session
            ON mutations(xace_session_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_mutations_proposal
            ON mutations(proposal_id);
        """
    )


def _session_from_row(row: sqlite3.Row) -> AgentStoredSession:
    return AgentStoredSession(
        xace_session_id=str(row["xace_session_id"]),
        provider_id=str(row["provider_id"]),
        provider_session_id=str(row["provider_session_id"]),
        base_cgs_hash=str(row["base_cgs_hash"]),
        latest_cgs_hash=str(row["latest_cgs_hash"]),
        mode=str(row["mode"]),
        parent_xace_session_id=str(row["parent_xace_session_id"]),
        parent_provider_session_id=str(row["parent_provider_session_id"]),
        branch_name=str(row["branch_name"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        metadata=_loads(row["metadata_json"]),
    )


def _event_from_row(row: sqlite3.Row) -> AgentEvent:
    return AgentEvent.from_dict({
        "schema": AGENT_CONTRACT_SCHEMA,
        "event_id": row["event_id"],
        "event_type": row["event_type"],
        "session_id": row["xace_session_id"],
        "provider_id": row["provider_id"],
        "sequence": row["sequence"],
        "message": row["message"],
        "data": _loads(row["data_json"]),
        "created_at": row["created_at"],
    })


def _tool_call_from_row(row: sqlite3.Row) -> AgentToolCallRecord:
    return AgentToolCallRecord(
        tool_call_id=str(row["tool_call_id"]),
        xace_session_id=str(row["xace_session_id"]),
        provider_id=str(row["provider_id"]),
        tool_name=str(row["tool_name"]),
        permission=str(row["permission"]),
        transport=str(row["transport"]),
        status=str(row["status"]),
        event_id=str(row["event_id"]),
        cgs_hash=str(row["cgs_hash"]),
        request=_loads(row["request_json"]),
        response=_loads(row["response_json"]),
        created_at=str(row["created_at"]),
        completed_at=str(row["completed_at"]),
    )


def _proposal_from_row(row: sqlite3.Row) -> dict[str, JsonValue]:
    payload = _loads(row["payload_json"])
    return {
        "schema": AGENT_SESSION_STORE_SCHEMA,
        "proposal_id": row["proposal_id"],
        "xace_session_id": row["xace_session_id"],
        "provider_id": row["provider_id"],
        "base_cgs_hash": row["base_cgs_hash"],
        "intent": row["intent"],
        "proposal_kind": row["proposal_kind"],
        "risk_level": row["risk_level"],
        "status": row["status"],
        "summary": row["summary"],
        "requires_structural_regeneration": bool(
            row["requires_structural_regeneration"]
        ),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "mutation_transaction_id": row["mutation_transaction_id"],
        "approval_id": row["approval_id"],
        "payload": payload,
    }


def _mutation_from_row(row: sqlite3.Row) -> AgentMutationLineageRecord:
    return AgentMutationLineageRecord(
        mutation_id=str(row["mutation_id"]),
        proposal_id=str(row["proposal_id"]),
        xace_session_id=str(row["xace_session_id"]),
        provider_id=str(row["provider_id"]),
        base_cgs_hash=str(row["base_cgs_hash"]),
        result_cgs_hash=str(row["result_cgs_hash"]),
        gde_transaction_id=str(row["gde_transaction_id"]),
        sgc_plan_id=str(row["sgc_plan_id"]),
        runtime_validation_id=str(row["runtime_validation_id"]),
        status=str(row["status"]),
        summary=str(row["summary"]),
        created_at=str(row["created_at"]),
        metadata=_loads(row["metadata_json"]),
    )


def _dumps(value: Any) -> str:
    redacted = redact_value(normalize_json_value(value))
    return json.dumps(redacted, sort_keys=True, separators=(",", ":"))


def _redact_text(value: Any) -> str:
    return redact_text(value)

def _loads(value: Any) -> dict[str, JsonValue]:
    if not value:
        return {}
    data = json.loads(str(value))
    if not isinstance(data, dict):
        raise AgentSessionStoreError("stored JSON payload is not an object")
    return _json_object(data, "stored JSON payload")


def _json_object(value: Mapping[str, Any] | None, label: str) -> dict[str, JsonValue]:
    try:
        normalized = normalize_json_value(dict(value or {}), label)
    except AgentContractError as exc:
        raise AgentSessionStoreError(str(exc)) from exc
    if not isinstance(normalized, dict):
        raise AgentSessionStoreError(f"{label} must be an object")
    return normalized


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise AgentSessionStoreError(f"{label} must not be empty")
    try:
        from .contracts import _require_identifier as require_identifier  # noqa: WPS433

        require_identifier(value, label)
    except AgentContractError as exc:
        raise AgentSessionStoreError(str(exc)) from exc


def _require_nonempty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentSessionStoreError(f"{label} must not be empty")


def _require_cgs_hash(value: str, label: str) -> None:
    try:
        from .contracts import _require_cgs_hash as require_cgs_hash  # noqa: WPS433

        require_cgs_hash(value, label)
    except AgentContractError as exc:
        raise AgentSessionStoreError(str(exc)) from exc


def _require_schema(schema: str) -> None:
    if schema != AGENT_SESSION_STORE_SCHEMA:
        raise AgentSessionStoreError(
            f"schema must equal {AGENT_SESSION_STORE_SCHEMA!r}"
        )


def _require_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise AgentSessionStoreError("limit must be a positive integer")


def consume_events(
    store: AgentSessionStore,
    events: Iterable[AgentEvent],
) -> None:
    """Persist an event stream from an adapter in sequence."""

    for event in events:
        store.record_event(event)

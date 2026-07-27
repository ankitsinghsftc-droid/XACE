"""
route_evidence.py - benchmark evidence gate for automatic model routing.

Automatic provider/model routing is allowed only when the selected route has a
fresh benchmark proof record for the exact provider, logical model, concrete
model id, and tier. Manual provider settings and explicit logical model calls
are handled by their own readiness gates; this module is for ModelRouter's
automatic choice path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model_descriptor import ModelDescriptor


SCHEMA = "xace.provider_route_evidence.v1"

CODE_OK = "MODEL_ROUTE_EVIDENCE_OK"
CODE_MISSING = "MODEL_ROUTE_EVIDENCE_MISSING"
CODE_STALE = "MODEL_ROUTE_EVIDENCE_STALE"
CODE_INVALID = "MODEL_ROUTE_EVIDENCE_INVALID"


@dataclass(frozen=True)
class RouteEvidenceRecord:
    provider: str
    logical_name: str
    model_id: str
    tier: str
    benchmark_id: str
    benchmark_hash: str
    benchmarked_at_utc: datetime
    expires_at_utc: datetime
    status: str = "passed"
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def route_id(self) -> str:
        return route_id(self.provider, self.logical_name, self.model_id, self.tier)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RouteEvidenceRecord":
        provider = _required_str(data, "provider")
        logical_name = _required_str(data, "logical_name")
        model_id = _required_str(data, "model_id")
        tier = _required_str(data, "tier")
        benchmark_id = _required_str(data, "benchmark_id")
        benchmark_hash = _required_str(data, "benchmark_hash")
        benchmarked_at = _parse_utc(_required_str(data, "benchmarked_at_utc"))
        expires_at = _parse_utc(_required_str(data, "expires_at_utc"))
        status = str(data.get("status") or "passed")
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        return cls(
            provider=provider,
            logical_name=logical_name,
            model_id=model_id,
            tier=tier,
            benchmark_id=benchmark_id,
            benchmark_hash=benchmark_hash,
            benchmarked_at_utc=benchmarked_at,
            expires_at_utc=expires_at,
            status=status,
            metrics=dict(metrics),
        )

    def to_report(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "provider": self.provider,
            "logical_name": self.logical_name,
            "model_id": self.model_id,
            "tier": self.tier,
            "benchmark_id": self.benchmark_id,
            "benchmark_hash": self.benchmark_hash,
            "benchmarked_at_utc": _format_utc(self.benchmarked_at_utc),
            "expires_at_utc": _format_utc(self.expires_at_utc),
            "status": self.status,
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class RouteEvidenceResult:
    ok: bool
    code: str
    message: str
    action: str
    route_id: str
    record: RouteEvidenceRecord | None = None

    def to_report(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "action": self.action,
            "route_id": self.route_id,
        }
        if self.record:
            payload["record"] = self.record.to_report()
        return payload


class RouteEvidencePolicy:
    """Strict evidence lookup for automatic ModelRouter decisions."""

    def __init__(
        self,
        records: list[RouteEvidenceRecord] | None = None,
        *,
        now_utc: datetime | None = None,
    ) -> None:
        self._now_utc = now_utc or datetime.now(timezone.utc)
        self._records: dict[str, RouteEvidenceRecord] = {}
        for record in records or []:
            self._records[record.route_id] = record

    @classmethod
    def from_records(
        cls,
        rows: list[dict[str, Any]],
        *,
        now_utc: datetime | None = None,
    ) -> "RouteEvidencePolicy":
        return cls([RouteEvidenceRecord.from_dict(row) for row in rows], now_utc=now_utc)

    @classmethod
    def from_manifest(
        cls,
        data: dict[str, Any],
        *,
        now_utc: datetime | None = None,
    ) -> "RouteEvidencePolicy":
        if data.get("schema") != SCHEMA:
            raise ValueError(f"route evidence manifest must use schema {SCHEMA!r}")
        rows = data.get("records")
        if not isinstance(rows, list):
            raise ValueError("route evidence manifest must contain a records list")
        return cls.from_records(rows, now_utc=now_utc)

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        now_utc: datetime | None = None,
    ) -> "RouteEvidencePolicy":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_manifest(json.load(handle), now_utc=now_utc)

    def evaluate(
        self,
        descriptor: ModelDescriptor,
        *,
        tier: str | None = None,
        actual_model_id: str | None = None,
    ) -> RouteEvidenceResult:
        effective_tier = tier or descriptor.default_tier
        model_id = actual_model_id or descriptor.model_id
        rid = route_id(descriptor.provider, descriptor.logical_name, model_id, effective_tier)
        record = self._records.get(rid)
        if record is None:
            return RouteEvidenceResult(
                ok=False,
                code=CODE_MISSING,
                route_id=rid,
                action="Run and attach a fresh xace.provider_route_evidence.v1 benchmark record for this provider/model route.",
                message=(
                    f"{CODE_MISSING}: automatic routing for {rid} is blocked "
                    "because no benchmark proof was found."
                ),
            )

        invalid_reason = _record_invalid_reason(record, now_utc=self._now_utc)
        if invalid_reason:
            return RouteEvidenceResult(
                ok=False,
                code=CODE_INVALID,
                route_id=rid,
                record=record,
                action="Re-run the route benchmark and replace the invalid evidence record.",
                message=(
                    f"{CODE_INVALID}: automatic routing for {rid} is blocked "
                    f"because the benchmark proof is invalid: {invalid_reason}."
                ),
            )

        if record.expires_at_utc <= self._now_utc:
            return RouteEvidenceResult(
                ok=False,
                code=CODE_STALE,
                route_id=rid,
                record=record,
                action="Re-run the route benchmark before using this automatic route.",
                message=(
                    f"{CODE_STALE}: automatic routing for {rid} is blocked "
                    f"because benchmark proof expired at {_format_utc(record.expires_at_utc)}."
                ),
            )

        return RouteEvidenceResult(
            ok=True,
            code=CODE_OK,
            route_id=rid,
            record=record,
            action="",
            message=(
                f"{CODE_OK}: automatic routing for {rid} is backed by benchmark "
                f"{record.benchmark_id} until {_format_utc(record.expires_at_utc)}."
            ),
        )

    def report_records(self) -> list[dict[str, Any]]:
        return [record.to_report() for record in sorted(self._records.values(), key=lambda row: row.route_id)]


def route_id(provider: str, logical_name: str, model_id: str, tier: str) -> str:
    return f"{tier}:{provider}:{logical_name}:{model_id}"


def _record_invalid_reason(record: RouteEvidenceRecord, *, now_utc: datetime) -> str:
    if record.status != "passed":
        return f"status is {record.status!r}"
    if not record.benchmark_hash:
        return "benchmark_hash is empty"
    if not record.benchmark_id:
        return "benchmark_id is empty"
    if record.benchmarked_at_utc > now_utc:
        return "benchmarked_at_utc is in the future"
    if record.expires_at_utc <= record.benchmarked_at_utc:
        return "expires_at_utc must be after benchmarked_at_utc"
    return ""


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"route evidence record missing non-empty string field {key!r}")
    return value.strip()


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

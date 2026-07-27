"""Cloud save conflict resolution.

Conflicts are explicit: either local wins, cloud wins, or the caller must ask
the user. The resolver can also produce a deterministic profile merge for the
common cross-session profile case.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ConflictStrategy(str, Enum):
    LOCAL_WINS = "LOCAL_WINS"
    CLOUD_WINS = "CLOUD_WINS"
    ASK_USER = "ASK_USER"


class ConflictResolutionKind(str, Enum):
    USE_LOCAL = "USE_LOCAL"
    USE_CLOUD = "USE_CLOUD"
    ASK_USER = "ASK_USER"
    MERGED = "MERGED"
    NO_CONFLICT = "NO_CONFLICT"


class CloudConflictError(RuntimeError):
    """Raised when a conflict cannot be resolved automatically."""


@dataclass(frozen=True)
class SaveVersionInfo:
    revision: str
    content_hash: str
    modified_unix_ms: int
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ConflictDecision:
    kind: ConflictResolutionKind
    payload: Mapping[str, Any] | None
    reason: str


class CloudSyncConflictResolver:
    """Resolves divergent local/cloud save versions."""

    def __init__(self, strategy: ConflictStrategy | str = ConflictStrategy.ASK_USER) -> None:
        self.strategy = _normalise_strategy(strategy)

    def detect_conflict(self, local: SaveVersionInfo, cloud: SaveVersionInfo | None) -> bool:
        if cloud is None:
            return False
        if local.revision and cloud.revision and local.revision == cloud.revision:
            return False
        if local.content_hash and cloud.content_hash and local.content_hash == cloud.content_hash:
            return False
        return True

    def resolve(self, local: SaveVersionInfo, cloud: SaveVersionInfo | None) -> ConflictDecision:
        if cloud is None:
            return ConflictDecision(
                kind=ConflictResolutionKind.NO_CONFLICT,
                payload=local.payload,
                reason="cloud object is absent",
            )
        if not self.detect_conflict(local, cloud):
            return ConflictDecision(
                kind=ConflictResolutionKind.NO_CONFLICT,
                payload=local.payload or cloud.payload,
                reason="revisions or content hashes match",
            )
        if self.strategy == ConflictStrategy.LOCAL_WINS:
            return ConflictDecision(
                kind=ConflictResolutionKind.USE_LOCAL,
                payload=local.payload,
                reason="strategy LOCAL_WINS selected local payload",
            )
        if self.strategy == ConflictStrategy.CLOUD_WINS:
            return ConflictDecision(
                kind=ConflictResolutionKind.USE_CLOUD,
                payload=cloud.payload,
                reason="strategy CLOUD_WINS selected cloud payload",
            )
        return ConflictDecision(
            kind=ConflictResolutionKind.ASK_USER,
            payload=None,
            reason="strategy ASK_USER requires caller decision",
        )

    def merge_player_profile(
        self,
        local_payload: Mapping[str, Any],
        cloud_payload: Mapping[str, Any],
        *,
        settings_source: ConflictStrategy | str = ConflictStrategy.LOCAL_WINS,
    ) -> ConflictDecision:
        settings_strategy = _normalise_strategy(settings_source)
        if settings_strategy == ConflictStrategy.ASK_USER:
            raise CloudConflictError("profile settings merge cannot use ASK_USER")
        local_profile = dict(local_payload)
        cloud_profile = dict(cloud_payload)
        merged: dict[str, Any] = {}
        merged["profile_id"] = str(local_profile.get("profile_id") or cloud_profile.get("profile_id") or "")
        merged["display_name"] = str(local_profile.get("display_name") or cloud_profile.get("display_name") or "Player")
        merged["achievements"] = sorted(
            set(_string_list(local_profile.get("achievements", [])))
            | set(_string_list(cloud_profile.get("achievements", [])))
        )
        merged["total_play_time"] = max(
            _non_negative_int(local_profile.get("total_play_time", 0), "local total_play_time"),
            _non_negative_int(cloud_profile.get("total_play_time", 0), "cloud total_play_time"),
        )
        merged["statistics"] = _merge_numeric_maps(
            local_profile.get("statistics", {}),
            cloud_profile.get("statistics", {}),
        )
        merged["settings"] = _stable_map(
            local_profile.get("settings", {})
            if settings_strategy == ConflictStrategy.LOCAL_WINS
            else cloud_profile.get("settings", {}),
            "settings",
        )
        merged["last_played_slot_id"] = str(
            local_profile.get("last_played_slot_id") or cloud_profile.get("last_played_slot_id") or ""
        )
        return ConflictDecision(
            kind=ConflictResolutionKind.MERGED,
            payload=merged,
            reason="profile merge unioned achievements, kept max play time, and merged statistics",
        )


def _merge_numeric_maps(local: Any, cloud: Any) -> dict[str, Any]:
    left = _stable_map(local, "local statistics")
    right = _stable_map(cloud, "cloud statistics")
    merged: dict[str, Any] = {}
    for key in sorted(set(left.keys()) | set(right.keys())):
        a = left.get(key, 0)
        b = right.get(key, 0)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            merged[key] = max(a, b)
        else:
            merged[key] = a if key in left else b
    return merged


def _stable_map(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CloudConflictError(f"{field_name} must be a mapping")
    return {str(key): value[key] for key in sorted(value.keys(), key=lambda item: str(item)) if str(key)}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise CloudConflictError("achievements must be a list")
    return [str(item) for item in value if str(item)]


def _non_negative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise CloudConflictError(f"{field_name} must be a non-negative integer")
    return value


def _normalise_strategy(value: ConflictStrategy | str) -> ConflictStrategy:
    if isinstance(value, ConflictStrategy):
        return value
    text = str(value).strip().upper()
    try:
        return ConflictStrategy(text)
    except ValueError as exc:
        allowed = ", ".join(strategy.value for strategy in ConflictStrategy)
        raise CloudConflictError(f"strategy must be one of {allowed}") from exc

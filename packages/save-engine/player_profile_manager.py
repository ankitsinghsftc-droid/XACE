"""Cross-session player profile persistence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


PROFILE_FILE = "profile.json"


class PlayerProfileError(RuntimeError):
    """Raised when profile data is invalid or cannot be persisted."""


@dataclass(frozen=True)
class PlayerProfile:
    profile_id: str
    display_name: str = "Player"
    achievements: tuple[str, ...] = ()
    settings: Mapping[str, Any] = field(default_factory=dict)
    statistics: Mapping[str, Any] = field(default_factory=dict)
    total_play_time: int = 0
    last_played_slot_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "achievements": list(self.achievements),
            "settings": _stable_map(self.settings, "settings"),
            "statistics": _stable_map(self.statistics, "statistics"),
            "total_play_time": self.total_play_time,
            "last_played_slot_id": self.last_played_slot_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PlayerProfile":
        profile_id = _non_empty_text(data.get("profile_id", ""), "profile_id")
        achievements = tuple(sorted(set(_non_empty_text(item, "achievement") for item in data.get("achievements", []))))
        total_play_time = int(data.get("total_play_time", 0))
        if total_play_time < 0:
            raise PlayerProfileError("total_play_time must be non-negative")
        return cls(
            profile_id=profile_id,
            display_name=str(data.get("display_name") or "Player"),
            achievements=achievements,
            settings=_stable_map(data.get("settings", {}), "settings"),
            statistics=_stable_map(data.get("statistics", {}), "statistics"),
            total_play_time=total_play_time,
            last_played_slot_id=str(data.get("last_played_slot_id", "")).strip(),
        )


class PlayerProfileManager:
    """Loads and updates deterministic profile records."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def create_profile(
        self,
        profile_id: str,
        *,
        display_name: str = "Player",
        overwrite: bool = False,
    ) -> PlayerProfile:
        profile = PlayerProfile(
            profile_id=_normalise_profile_id(profile_id),
            display_name=str(display_name).strip() or "Player",
        )
        path = self._profile_path(profile.profile_id)
        if path.exists() and not overwrite:
            raise PlayerProfileError(f"profile already exists: {profile.profile_id}")
        self.save_profile(profile)
        return profile

    def load_profile(self, profile_id: str) -> PlayerProfile:
        profile = _normalise_profile_id(profile_id)
        path = self._profile_path(profile)
        if not path.exists():
            raise PlayerProfileError(f"profile not found: {profile}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise PlayerProfileError("profile root must be an object")
        return PlayerProfile.from_mapping(data)

    def save_profile(self, profile: PlayerProfile) -> None:
        data = profile.to_dict()
        _atomic_write(self._profile_path(profile.profile_id), _stable_json(data).encode("utf-8"))

    def list_profiles(self) -> list[PlayerProfile]:
        if not self.root.exists():
            return []
        profiles: list[PlayerProfile] = []
        for entry in self.root.iterdir():
            if entry.is_dir() and (entry / PROFILE_FILE).exists():
                profiles.append(self.load_profile(entry.name))
        return sorted(profiles, key=lambda profile: profile.profile_id)

    def set_display_name(self, profile_id: str, display_name: str) -> PlayerProfile:
        profile = self.load_profile(profile_id)
        updated = _replace_profile(profile, display_name=str(display_name).strip() or "Player")
        self.save_profile(updated)
        return updated

    def unlock_achievement(self, profile_id: str, achievement_id: str) -> PlayerProfile:
        profile = self.load_profile(profile_id)
        achievement = _non_empty_text(achievement_id, "achievement_id")
        updated = _replace_profile(
            profile,
            achievements=tuple(sorted(set(profile.achievements + (achievement,)))),
        )
        self.save_profile(updated)
        return updated

    def update_setting(self, profile_id: str, key: str, value: Any) -> PlayerProfile:
        profile = self.load_profile(profile_id)
        settings = dict(profile.settings)
        settings[_non_empty_text(key, "setting key")] = _json_safe(value, "setting value")
        updated = _replace_profile(profile, settings=_stable_map(settings, "settings"))
        self.save_profile(updated)
        return updated

    def increment_statistic(self, profile_id: str, key: str, amount: int | float = 1) -> PlayerProfile:
        profile = self.load_profile(profile_id)
        if not isinstance(amount, (int, float)):
            raise PlayerProfileError("statistic amount must be numeric")
        statistics = dict(profile.statistics)
        stat_key = _non_empty_text(key, "statistic key")
        current = statistics.get(stat_key, 0)
        if not isinstance(current, (int, float)):
            raise PlayerProfileError(f"statistic {stat_key!r} is not numeric")
        statistics[stat_key] = current + amount
        updated = _replace_profile(profile, statistics=_stable_map(statistics, "statistics"))
        self.save_profile(updated)
        return updated

    def add_play_time(self, profile_id: str, ticks: int, *, last_played_slot_id: str = "") -> PlayerProfile:
        if not isinstance(ticks, int) or ticks < 0:
            raise PlayerProfileError("ticks must be a non-negative integer")
        profile = self.load_profile(profile_id)
        updated = _replace_profile(
            profile,
            total_play_time=profile.total_play_time + ticks,
            last_played_slot_id=str(last_played_slot_id).strip() or profile.last_played_slot_id,
        )
        self.save_profile(updated)
        return updated

    def _profile_path(self, profile_id: str) -> Path:
        return self.root / profile_id / PROFILE_FILE


def _replace_profile(profile: PlayerProfile, **changes: Any) -> PlayerProfile:
    data = profile.to_dict()
    data.update(changes)
    return PlayerProfile.from_mapping(data)


def _stable_map(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PlayerProfileError(f"{field_name} must be a mapping")
    result: dict[str, Any] = {}
    for key in sorted(value.keys(), key=lambda item: str(item)):
        text_key = _non_empty_text(key, f"{field_name} key")
        result[text_key] = _json_safe(value[key], f"{field_name}.{text_key}")
    return result


def _json_safe(value: Any, field_name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise PlayerProfileError(f"{field_name} must be finite")
        return value
    if isinstance(value, list):
        return [_json_safe(item, field_name) for item in value]
    if isinstance(value, Mapping):
        return _stable_map(value, field_name)
    raise PlayerProfileError(f"{field_name} is not JSON-serializable")


def _stable_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _normalise_profile_id(profile_id: Any) -> str:
    text = _non_empty_text(profile_id, "profile_id")
    safe = "".join(char if char.isascii() and (char.isalnum() or char in {"_", "-"}) else "_" for char in text)
    if safe in {".", ".."}:
        raise PlayerProfileError("profile_id must not be a relative path marker")
    return safe


def _non_empty_text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise PlayerProfileError(f"{field_name} must not be empty")
    return text

"""Validated save deserialization with schema-version enforcement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from save_migration_engine import SaveMigrationEngine
from save_serializer import FORMAT_VERSION, SaveLayer, SaveSerializer


class SaveDeserializationError(ValueError):
    """Raised when save JSON is malformed or structurally invalid."""


class SaveMigrationRequired(SaveDeserializationError):
    """Raised when a save schema differs and no migration plan was supplied."""

    def __init__(self, save_schema: str, current_schema: str) -> None:
        super().__init__(
            f"save schema {save_schema} must be migrated to {current_schema} before load"
        )
        self.save_schema = save_schema
        self.current_schema = current_schema


@dataclass(frozen=True)
class LoadedSave:
    envelope: dict[str, Any]
    migrated: bool = False

    @property
    def payload(self) -> Mapping[str, Any]:
        return self.envelope["payload"]

    @property
    def schema_version(self) -> str:
        return str(self.envelope["schema_version"])

    @property
    def layer(self) -> SaveLayer:
        return SaveLayer(str(self.envelope["layer"]))


class SaveDeserializer:
    """Parses save JSON and enforces I14 schema-version compatibility."""

    def __init__(
        self,
        *,
        current_schema_version: str,
        serializer: SaveSerializer | None = None,
        migration_engine: SaveMigrationEngine | None = None,
    ) -> None:
        self.current_schema_version = _non_empty_text(
            current_schema_version, "current_schema_version"
        )
        self.serializer = serializer or SaveSerializer()
        self.migration_engine = migration_engine or SaveMigrationEngine()

    def loads(self, text: str, *, migration_plan: Any = None) -> LoadedSave:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SaveDeserializationError(f"invalid save JSON: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise SaveDeserializationError("save root must be a JSON object")
        return self.load_mapping(raw, migration_plan=migration_plan)

    def load_mapping(self, data: Mapping[str, Any], *, migration_plan: Any = None) -> LoadedSave:
        envelope = self._validate_envelope(data)
        save_schema = str(envelope["schema_version"])
        if save_schema != self.current_schema_version:
            if migration_plan is None:
                raise SaveMigrationRequired(save_schema, self.current_schema_version)
            result = self.migration_engine.migrate_envelope(
                envelope,
                target_schema_version=self.current_schema_version,
                migration_plan=migration_plan,
            )
            envelope = self._validate_envelope(result.envelope)
            return LoadedSave(envelope=self.serializer.canonicalise(envelope), migrated=True)
        return LoadedSave(envelope=self.serializer.canonicalise(envelope), migrated=False)

    def _validate_envelope(self, data: Mapping[str, Any]) -> dict[str, Any]:
        envelope = dict(data)
        if envelope.get("format_version") != FORMAT_VERSION:
            raise SaveDeserializationError(
                f"unsupported save format_version {envelope.get('format_version')!r}"
            )
        schema = _non_empty_text(envelope.get("schema_version", ""), "schema_version")
        try:
            layer = SaveLayer(str(envelope.get("layer", "")).strip().upper())
        except ValueError as exc:
            raise SaveDeserializationError("layer is not valid") from exc
        payload = envelope.get("payload")
        if not isinstance(payload, Mapping):
            raise SaveDeserializationError("payload must be a JSON object")
        history = envelope.get("migration_history", [])
        if not isinstance(history, list):
            raise SaveDeserializationError("migration_history must be a list")
        envelope["schema_version"] = schema
        envelope["layer"] = layer.value
        envelope["payload"] = dict(payload)
        envelope["migration_history"] = history
        envelope.setdefault("slot_id", "")
        envelope.setdefault("cgs_hash", "")
        envelope.setdefault("created_at", "")
        envelope.setdefault("saved_at", "")
        return envelope


def _non_empty_text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise SaveDeserializationError(f"{field_name} must not be empty")
    return text

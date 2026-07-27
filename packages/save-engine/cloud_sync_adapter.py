"""Platform-agnostic cloud save adapter contracts.

Real Steam/Epic/PSN/Xbox integrations plug into this module by implementing
``CloudSyncAdapter``. The built-in local-folder adapter gives deterministic
offline behavior for tests, development, and custom providers.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class CloudProvider(str, Enum):
    STEAM = "STEAM"
    EPIC = "EPIC"
    PSN = "PSN"
    XBOX = "XBOX"
    CUSTOM = "CUSTOM"
    NONE = "NONE"


class CloudSyncState(str, Enum):
    IDLE = "IDLE"
    UPLOADING = "UPLOADING"
    DOWNLOADING = "DOWNLOADING"
    CONFLICT = "CONFLICT"
    ERROR = "ERROR"
    SYNCED = "SYNCED"


class CloudSyncError(RuntimeError):
    """Raised when cloud sync cannot complete."""


@dataclass(frozen=True)
class CloudObjectMetadata:
    key: str
    provider: CloudProvider
    revision: str
    size_bytes: int
    content_hash: str
    modified_unix_ms: int


@dataclass(frozen=True)
class CloudSyncStatus:
    provider: CloudProvider
    state: CloudSyncState
    last_sync_tick: int = 0
    last_error: str = ""


class CloudSyncAdapter(Protocol):
    """Minimal provider interface used by the save orchestrator."""

    provider: CloudProvider

    def status(self) -> CloudSyncStatus:
        ...

    def list_objects(self) -> list[CloudObjectMetadata]:
        ...

    def upload(self, key: str, data: bytes, *, expected_revision: str = "") -> CloudObjectMetadata:
        ...

    def download(self, key: str) -> bytes:
        ...

    def metadata(self, key: str) -> CloudObjectMetadata | None:
        ...

    def delete(self, key: str, *, expected_revision: str = "") -> None:
        ...


class NullCloudSyncAdapter:
    """Provider for games with cloud sync disabled."""

    provider = CloudProvider.NONE

    def status(self) -> CloudSyncStatus:
        return CloudSyncStatus(provider=self.provider, state=CloudSyncState.IDLE)

    def list_objects(self) -> list[CloudObjectMetadata]:
        return []

    def upload(self, key: str, data: bytes, *, expected_revision: str = "") -> CloudObjectMetadata:
        raise CloudSyncError("cloud sync provider is NONE")

    def download(self, key: str) -> bytes:
        raise CloudSyncError("cloud sync provider is NONE")

    def metadata(self, key: str) -> CloudObjectMetadata | None:
        return None

    def delete(self, key: str, *, expected_revision: str = "") -> None:
        raise CloudSyncError("cloud sync provider is NONE")


class LocalFolderCloudSyncAdapter:
    """Filesystem-backed CUSTOM cloud adapter.

    It stores objects below ``root`` using sanitized keys and sidecar metadata.
    Revision values are content-addressed, which makes conflict checks stable
    and easy to reason about.
    """

    provider = CloudProvider.CUSTOM

    def __init__(self, root: str | Path, *, last_sync_tick: int = 0) -> None:
        self.root = Path(root)
        self.last_sync_tick = last_sync_tick
        self._state = CloudSyncState.IDLE
        self._last_error = ""

    def status(self) -> CloudSyncStatus:
        return CloudSyncStatus(
            provider=self.provider,
            state=self._state,
            last_sync_tick=self.last_sync_tick,
            last_error=self._last_error,
        )

    def list_objects(self) -> list[CloudObjectMetadata]:
        if not self.root.exists():
            return []
        items: list[CloudObjectMetadata] = []
        for path in self.root.glob("*.save"):
            items.append(self._metadata_for_path(path))
        return sorted(items, key=lambda item: item.key)

    def upload(self, key: str, data: bytes, *, expected_revision: str = "") -> CloudObjectMetadata:
        safe_key = _normalise_key(key)
        if not isinstance(data, (bytes, bytearray)):
            raise CloudSyncError("cloud upload data must be bytes")
        path = self._object_path(safe_key)
        existing = self.metadata(safe_key)
        if expected_revision and existing and existing.revision != expected_revision:
            self._state = CloudSyncState.CONFLICT
            raise CloudSyncError(
                f"revision conflict for {safe_key}: expected {expected_revision}, found {existing.revision}"
            )
        self._state = CloudSyncState.UPLOADING
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, bytes(data))
            metadata = self._metadata_for_path(path)
            self._state = CloudSyncState.SYNCED
            return metadata
        except Exception as exc:
            self._state = CloudSyncState.ERROR
            self._last_error = str(exc)
            raise

    def download(self, key: str) -> bytes:
        safe_key = _normalise_key(key)
        path = self._object_path(safe_key)
        if not path.exists():
            raise CloudSyncError(f"cloud object not found: {safe_key}")
        self._state = CloudSyncState.DOWNLOADING
        try:
            data = path.read_bytes()
            self._state = CloudSyncState.SYNCED
            return data
        except Exception as exc:
            self._state = CloudSyncState.ERROR
            self._last_error = str(exc)
            raise

    def metadata(self, key: str) -> CloudObjectMetadata | None:
        path = self._object_path(_normalise_key(key))
        if not path.exists():
            return None
        return self._metadata_for_path(path)

    def delete(self, key: str, *, expected_revision: str = "") -> None:
        safe_key = _normalise_key(key)
        path = self._object_path(safe_key)
        metadata = self.metadata(safe_key)
        if metadata is None:
            return
        if expected_revision and metadata.revision != expected_revision:
            self._state = CloudSyncState.CONFLICT
            raise CloudSyncError(
                f"revision conflict for {safe_key}: expected {expected_revision}, found {metadata.revision}"
            )
        path.unlink()

    def _object_path(self, key: str) -> Path:
        return self.root / f"{key}.save"

    def _metadata_for_path(self, path: Path) -> CloudObjectMetadata:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        stat = path.stat()
        key = path.stem
        return CloudObjectMetadata(
            key=key,
            provider=self.provider,
            revision=digest,
            size_bytes=len(data),
            content_hash=digest,
            modified_unix_ms=int(stat.st_mtime_ns // 1_000_000),
        )


def build_cloud_adapter(provider: CloudProvider | str, *, root: str | Path | None = None) -> CloudSyncAdapter:
    normalised = _normalise_provider(provider)
    if normalised == CloudProvider.NONE:
        return NullCloudSyncAdapter()
    if normalised == CloudProvider.CUSTOM:
        if root is None:
            raise CloudSyncError("CUSTOM cloud sync requires a root path")
        return LocalFolderCloudSyncAdapter(root)
    raise CloudSyncError(f"{normalised.value} cloud sync requires a platform SDK adapter")


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _normalise_provider(value: CloudProvider | str) -> CloudProvider:
    if isinstance(value, CloudProvider):
        return value
    text = str(value).strip().upper()
    try:
        return CloudProvider(text)
    except ValueError as exc:
        allowed = ", ".join(provider.value for provider in CloudProvider)
        raise CloudSyncError(f"provider must be one of {allowed}") from exc


def _normalise_key(key: str) -> str:
    text = str(key).strip()
    if not text:
        raise CloudSyncError("cloud object key must not be empty")
    safe = "".join(char if char.isascii() and (char.isalnum() or char in {"_", "-", "."}) else "_" for char in text)
    if safe in {".", ".."}:
        raise CloudSyncError("cloud object key must not be a relative path marker")
    return safe

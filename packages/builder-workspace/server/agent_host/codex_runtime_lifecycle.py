"""AG-024 lifecycle for a verified, user-owned Codex App Server runtime.

OpenAI documents a stable Python SDK with an internally pinned runtime, but it
does not document a public API for locating that executable for an existing
direct App Server client.  The standalone installer supports a caller-selected
install directory, but its public installer contract does not expose an exact
version pin.  AG-024 therefore implements the approved guided-install fallback:

* the user installs or updates Codex through the official provider channel;
* XACE verifies the executable, version, digest, native platform, and generated App Server
  schema before recording it;
* activation is an atomic metadata pointer and retains a last-known-good record;
* removal only deactivates XACE metadata and never deletes provider software;
* credentials remain entirely owned by Codex.

The state contains no tokens, account data, project data, or copied runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
import struct
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping


from .codex_compatibility import PROFILE, validate_schema, version_policy


CODEX_RUNTIME_LIFECYCLE_SCHEMA = "xace.codex_runtime_lifecycle.v1"
CODEX_RUNTIME_VERIFICATION_SCHEMA = "xace.codex_runtime_verification.v1"
CODEX_RUNTIME_GUIDE_SCHEMA = "xace.codex_runtime_guide.v1"
CODEX_RUNTIME_STATE_FILENAME = "runtime-state.json"
CODEX_RUNTIME_PENDING_FILENAME = "runtime-operation.pending.json"
CODEX_RUNTIME_LOCK_FILENAME = "runtime-operation.lock"
CODEX_RUNTIME_DIR_ENV = "XACE_CODEX_RUNTIME_DIR"
CODEX_GUIDED_RUNTIME_SOURCE = "xace_pinned_user_confirmed_external"
CODEX_OFFICIAL_CLI_DOCS = "https://developers.openai.com/codex/cli"
CODEX_OFFICIAL_ENV_DOCS = (
    "https://developers.openai.com/codex/config-file/environment-variables"
)
CODEX_WINDOWS_INSTALLER = "https://chatgpt.com/codex/install.ps1"
CODEX_POSIX_INSTALLER = "https://chatgpt.com/codex/install.sh"

_VERSION_RE = re.compile(r"(?P<version>\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?)")
_ALLOWED_OPERATIONS = {"install", "update", "repair"}
_HOST_EXTENSION_MARKERS = (
    "/.vscode/extensions/openai.chatgpt-",
    "/.cursor/extensions/openai.chatgpt-",
)


class CodexRuntimeLifecycleError(RuntimeError):
    """Raised when a runtime lifecycle operation cannot be trusted."""


@dataclass(frozen=True)
class CodexRuntimeVerification:
    executable_path: str
    source: str
    version: str
    sha256: str
    size_bytes: int
    platform: str
    architecture: str
    protocol_profile: str
    schema_fingerprint: str
    verified_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CODEX_RUNTIME_VERIFICATION_SCHEMA,
            "verified": True,
            "executable_path": self.executable_path,
            "source": self.source,
            "version": self.version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "platform": self.platform,
            "architecture": self.architecture,
            "protocol_profile": self.protocol_profile,
            "schema_fingerprint": self.schema_fingerprint,
            "compatibility_profile": PROFILE,
            "verified_at": self.verified_at,
            "credential_owner": "codex_provider",
            "xace_copied_runtime": False,
            "xace_read_credentials": False,
            "provenance_basis": "user_confirmed_official_install",
            "vendor_signature_verified": False,
        }


class CodexRuntimeLifecycle:
    """Verify and atomically select a provider-installed Codex executable."""

    def __init__(
        self,
        state_dir: str | Path | None = None,
        *,
        version_reader: Callable[[str], str | None] | None = None,
        schema_probe: Callable[[str], Mapping[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
        platform_name: str | None = None,
        architecture: str | None = None,
    ) -> None:
        self.state_dir = _state_dir(state_dir)
        self.state_path = self.state_dir / CODEX_RUNTIME_STATE_FILENAME
        self.pending_path = self.state_dir / CODEX_RUNTIME_PENDING_FILENAME
        self.lock_path = self.state_dir / CODEX_RUNTIME_LOCK_FILENAME
        self._version_reader = version_reader or _read_version
        self._schema_probe = schema_probe or _probe_stable_app_server
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._platform = _normalise_platform(platform_name or platform.system())
        self._architecture = _normalise_architecture(
            architecture or platform.machine()
        )

    def guided_plan(self, operation: str = "install") -> dict[str, Any]:
        """Return deterministic provider-owned setup/recovery guidance."""

        operation = str(operation or "").strip().lower()
        if operation not in {"install", "update", "repair", "rollback", "remove"}:
            raise CodexRuntimeLifecycleError(
                f"Unsupported Codex runtime operation: {operation or '<empty>'}"
            )
        if self._platform == "windows":
            installer_url = CODEX_WINDOWS_INSTALLER
            command = "irm https://chatgpt.com/codex/install.ps1 | iex"
        elif self._platform in {"linux", "macos"}:
            installer_url = CODEX_POSIX_INSTALLER
            command = "curl -fsSL https://chatgpt.com/codex/install.sh | sh"
        else:
            installer_url = None
            command = None

        if operation == "rollback":
            command = None
            detail = (
                "XACE can reselect the last-known-good executable only when that exact "
                "path, version, digest, platform, and App Server protocol still verify."
            )
        elif operation == "remove":
            command = None
            detail = (
                "XACE removes only its verified-runtime selection. Provider-installed "
                "software remains user-owned and is never deleted by XACE."
            )
        else:
            detail = (
                "Run the official provider installer outside the project, then ask XACE "
                f"to verify and activate the resulting executable for {operation}."
            )

        return {
            "schema": CODEX_RUNTIME_GUIDE_SCHEMA,
            "operation": operation,
            "mode": "guided_official_external_install",
            "platform": self._platform,
            "architecture": self._architecture,
            "supported": command is not None or operation in {"rollback", "remove"},
            "requires_user_action": operation in {"install", "update", "repair"},
            "official_installer_url": installer_url,
            "command": command,
            "official_docs": [CODEX_OFFICIAL_CLI_DOCS, CODEX_OFFICIAL_ENV_DOCS],
            "detail": detail,
            "activation_requires": [
                "stable_version",
                "sha256_digest",
                "platform_architecture_match",
                "generated_stable_app_server_schema",
                "user_confirmation_of_official_install",
            ],
            "automatic_download": False,
            "xace_modifies_external_runtime": False,
            "credential_owner": "codex_provider",
        }

    def verify_candidate(
        self,
        executable_path: str | Path,
        *,
        source: str = CODEX_GUIDED_RUNTIME_SOURCE,
        expected_version: str | None = None,
        expected_sha256: str | None = None,
    ) -> CodexRuntimeVerification:
        """Verify one executable without persisting or activating it."""

        path = Path(executable_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise CodexRuntimeLifecycleError(f"Codex executable was not found: {path}")
        normalised = path.as_posix().lower()
        if any(marker in normalised for marker in _HOST_EXTENSION_MARKERS):
            raise CodexRuntimeLifecycleError(
                "A private editor-extension runtime cannot be activated as XACE's "
                "verified production runtime"
            )
        clean_source = str(source or "").strip()
        if clean_source != CODEX_GUIDED_RUNTIME_SOURCE:
            raise CodexRuntimeLifecycleError(
                "Only the verified official external Codex source is activatable"
            )

        _verify_native_platform(path, self._platform, self._architecture)
        digest = _sha256_file(path)
        expected_digest = str(expected_sha256 or "").strip().lower()
        if expected_digest and digest != expected_digest:
            raise CodexRuntimeLifecycleError("Codex executable SHA-256 mismatch")
        if _is_revoked("", digest):
            raise CodexRuntimeLifecycleError("Codex runtime is revoked")
        version_output = self._version_reader(str(path))
        version = _parse_version(version_output or "")
        if not version:
            raise CodexRuntimeLifecycleError("Codex version could not be parsed")
        if "-" in version or "+" in version:
            raise CodexRuntimeLifecycleError(
                "Prerelease Codex runtimes cannot be activated for production"
            )
        if expected_version and version != str(expected_version).strip():
            raise CodexRuntimeLifecycleError(
                f"Codex version mismatch: expected {expected_version}, found {version}"
            )

        if _is_revoked(version, digest):
            raise CodexRuntimeLifecycleError("Codex runtime is revoked")
        try:
            version_policy(version)
            probe = self._schema_probe(str(path))
            fingerprint = _stable_schema_fingerprint(probe)
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise CodexRuntimeLifecycleError(f"Codex App Server schema compatibility failed: {exc}") from exc
        self._last_verified_schema = probe
        if _sha256_file(path) != digest:
            raise CodexRuntimeLifecycleError("Codex executable changed during verification")
        return CodexRuntimeVerification(
            executable_path=str(path),
            source=clean_source,
            version=version,
            sha256=digest,
            size_bytes=path.stat().st_size,
            platform=self._platform,
            architecture=self._architecture,
            protocol_profile="stable_app_server_jsonrpc",
            schema_fingerprint=fingerprint,
            verified_at=_iso_utc(self._clock()),
        )

    def verify_and_activate(
        self,
        executable_path: str | Path,
        *,
        operation: str = "install",
        source: str = CODEX_GUIDED_RUNTIME_SOURCE,
        expected_version: str | None = None,
        expected_sha256: str | None = None,
        confirm_official_install: bool = False,
        before_commit: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Verify a provider-owned runtime and atomically select it."""

        operation = str(operation or "").strip().lower()
        if confirm_official_install is not True:
            raise CodexRuntimeLifecycleError("Confirm the official installation before activation")
        if operation not in _ALLOWED_OPERATIONS:
            raise CodexRuntimeLifecycleError(
                "Activation operation must be install, update, or repair"
            )
        with self._operation_lock(operation, executable_path):
            state = self._read_state()
            target = state.get("active") if operation == "repair" else None
            if operation == "repair":
                if not isinstance(target, Mapping):
                    raise CodexRuntimeLifecycleError("Repair requires an existing pin; use install")
                if expected_sha256 and expected_sha256 != target["sha256"]:
                    raise CodexRuntimeLifecycleError("Codex executable SHA-256 mismatch")
                expected_sha256 = target["sha256"]
                expected_version = target["version"]
            operation_id = _operation_id(
                operation,
                str(Path(executable_path).expanduser().resolve()),
                int(state["generation"]) + 1,
            )
            self._write_pending(operation_id, operation, executable_path)
            try:
                verification = self.verify_candidate(
                    executable_path,
                    source=source,
                    expected_version=expected_version,
                    expected_sha256=expected_sha256,
                )
                if target and verification.schema_fingerprint != target["schema_fingerprint"]:
                    raise CodexRuntimeLifecycleError("Codex App Server schema mismatch")
                if before_commit is not None:
                    before_commit()
                state = self._activate(state, verification.to_dict(), operation, operation_id)
                self._write_state(state)
            finally:
                self.pending_path.unlink(missing_ok=True)
        return self.inspect()

    def rollback(self, *, before_commit: Callable[[], None] | None = None) -> dict[str, Any]:
        """Reselect the last-known-good record after exact re-verification."""

        with self._operation_lock("rollback", self.state_path):
            state = self._read_state()
            target = state.get("last_known_good")
            if not isinstance(target, Mapping):
                raise CodexRuntimeLifecycleError(
                    "No last-known-good Codex runtime is available"
                )
            operation_id = _operation_id(
                "rollback",
                str(target.get("executable_path") or ""),
                int(state["generation"]) + 1,
            )
            self._write_pending(
                operation_id,
                "rollback",
                str(target.get("executable_path") or ""),
            )
            try:
                verification = self.verify_candidate(
                    str(target.get("executable_path") or ""),
                    source=str(target.get("source") or ""),
                    expected_version=str(target.get("version") or ""),
                    expected_sha256=str(target.get("sha256") or ""),
                )
                if verification.schema_fingerprint != target["schema_fingerprint"]:
                    raise CodexRuntimeLifecycleError("Codex App Server schema mismatch")
                if before_commit is not None:
                    before_commit()
                current = state.get("active")
                state["active"] = verification.to_dict()
                state["last_known_good"] = verification.to_dict()
                state["generation"] = int(state["generation"]) + 1
                state["updated_at"] = _iso_utc(self._clock())
                _append_history(state, "rollback", operation_id, current, state["active"])
                self._write_state(state)
            finally:
                self.pending_path.unlink(missing_ok=True)
        return self.inspect()

    def deactivate(self) -> dict[str, Any]:
        """Remove XACE's selection without touching the external executable."""

        with self._operation_lock("remove", self.state_path):
            state = self._read_state()
            current = state.get("active")
            operation_id = _operation_id(
                "remove",
                str(current.get("executable_path") if isinstance(current, Mapping) else ""),
                int(state["generation"]) + 1,
            )
            state["active"] = None
            state["last_known_good"] = None
            state["generation"] = int(state["generation"]) + 1
            state["updated_at"] = _iso_utc(self._clock())
            _append_history(state, "remove", operation_id, current, None)
            self._write_state(state)
        return self.inspect()

    def recover_interrupted(self) -> dict[str, Any]:
        """Discard incomplete metadata while preserving the last atomic state."""

        with self._operation_lock("recover", self.state_path):
            pending_present = self.pending_path.exists()
            self.pending_path.unlink(missing_ok=True)
        result = self.inspect()
        result["recovery"] = {
            "recovered": pending_present,
            "discarded_pending_operation": pending_present,
            "discarded_stale_lock": False,
            "active_state_preserved": True,
        }
        return result

    def inspect(self) -> dict[str, Any]:
        """Return non-secret, machine-readable lifecycle state and health."""

        try:
            state = self._read_state()
            state_error = None
        except CodexRuntimeLifecycleError as exc:
            state = _empty_state()
            state_error = str(exc)
        active = state.get("active")
        active_health = _record_health(
            active,
            platform_name=self._platform,
            architecture=self._architecture,
        )
        return {
            "schema": CODEX_RUNTIME_LIFECYCLE_SCHEMA,
            "mode": "guided_official_external_install",
            "implementation_status": "complete",
            "state_path": str(self.state_path),
            "generation": int(state.get("generation") or 0),
            "active": dict(active) if isinstance(active, Mapping) else None,
            "last_known_good": (
                dict(state["last_known_good"])
                if isinstance(state.get("last_known_good"), Mapping)
                else None
            ),
            "active_health": active_health,
            "ready": bool(active_health.get("valid")),
            "pending_operation": self.pending_path.exists(),
            "state_error": state_error,
            "history_count": len(state.get("history") or []),
            "automatic_download": False,
            "xace_modifies_external_runtime": False,
            "credential_owner": "codex_provider",
        }

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return _empty_state()
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CodexRuntimeLifecycleError(
                f"Codex runtime state is unreadable: {type(exc).__name__}"
            ) from exc
        if not isinstance(value, dict) or value.get("schema") != CODEX_RUNTIME_LIFECYCLE_SCHEMA:
            raise CodexRuntimeLifecycleError("Unsupported Codex runtime state schema")
        if type(value.get("generation")) is not int or value["generation"] < 0:
            raise CodexRuntimeLifecycleError("Invalid Codex runtime state generation")
        if not isinstance(value.get("history"), list):
            raise CodexRuntimeLifecycleError("Invalid Codex runtime state history")
        for field in ("active", "last_known_good"):
            record = value.get(field)
            if record is not None and not _valid_record(record):
                raise CodexRuntimeLifecycleError("Invalid Codex runtime verification record")
        return value

    def _activate(
        self,
        state: dict[str, Any],
        verification: dict[str, Any],
        operation: str,
        operation_id: str,
    ) -> dict[str, Any]:
        previous = state.get("active")
        if isinstance(previous, Mapping) and _record_health(
            previous, platform_name=self._platform, architecture=self._architecture
        )["valid"]:
            state["last_known_good"] = dict(previous)
        elif not state.get("last_known_good"):
            state["last_known_good"] = dict(verification)
        state["active"] = dict(verification)
        state["generation"] = int(state["generation"]) + 1
        state["updated_at"] = _iso_utc(self._clock())
        _append_history(state, operation, operation_id, previous, verification)
        return state

    def _write_state(self, state: Mapping[str, Any]) -> None:
        active = state.get("active")
        documents = getattr(self, "_last_verified_schema", None)
        if active and documents is not None:
            fingerprint = _stable_schema_fingerprint(documents)
            if fingerprint == active["schema_fingerprint"]:
                _atomic_write_json(self.state_dir / "schemas" / f"{fingerprint}.json", documents)
        _atomic_write_json(self.state_path, state)

    def _write_pending(
        self,
        operation_id: str,
        operation: str,
        executable_path: str | Path,
    ) -> None:
        _atomic_write_json(
            self.pending_path,
            {
                "schema": CODEX_RUNTIME_LIFECYCLE_SCHEMA,
                "operation_id": operation_id,
                "operation": operation,
                "executable_path": str(Path(executable_path).expanduser().resolve()),
                "started_at": _iso_utc(self._clock()),
            },
        )

    @contextmanager
    def _operation_lock(
        self,
        operation: str,
        executable_path: str | Path,
    ) -> Iterator[None]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Keep the inode: recovery and writers must acquire the same OS lock.
        with self.lock_path.open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise CodexRuntimeLifecycleError("A Codex runtime lifecycle operation is already in progress") from exc
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def resolve_verified_codex_runtime(
    state_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Resolve the active record only while its immutable evidence still matches."""

    lifecycle = CodexRuntimeLifecycle(state_dir)
    try:
        state = lifecycle._read_state()
    except CodexRuntimeLifecycleError:
        return None
    active = state.get("active")
    health = _record_health(
        active,
        platform_name=lifecycle._platform,
        architecture=lifecycle._architecture,
    )
    if not health.get("valid") or not isinstance(active, Mapping):
        return None
    return dict(active)


def codex_runtime_selection_exists() -> bool:
    """An explicit selection or removal suppresses implicit PATH rediscovery."""
    return (_state_dir(None) / CODEX_RUNTIME_STATE_FILENAME).exists()


def codex_guided_install_plan(
    operation: str = "install",
    *,
    platform_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """Pure convenience wrapper used by settings and UI contracts."""

    return CodexRuntimeLifecycle(
        platform_name=platform_name,
        architecture=architecture,
    ).guided_plan(operation)


def _empty_state() -> dict[str, Any]:
    return {
        "schema": CODEX_RUNTIME_LIFECYCLE_SCHEMA,
        "generation": 0,
        "active": None,
        "last_known_good": None,
        "history": [],
        "updated_at": None,
    }


def _state_dir(value: str | Path | None) -> Path:
    configured = str(os.environ.get(CODEX_RUNTIME_DIR_ENV) or "").strip()
    root = Path(value).expanduser() if value is not None else (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".xace" / "codex-runtime"
    )
    resolved = root.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise CodexRuntimeLifecycleError("Codex runtime state directory is too broad")
    return resolved


def _is_revoked(version: str, digest: str) -> bool:
    from .codex_distribution import codex_distribution_policy

    policy = codex_distribution_policy()["revocation"]
    return version in policy["revoked_versions"] or digest in policy["revoked_sha256"]


def _valid_record(record: Any) -> bool:
    return (
        isinstance(record, Mapping)
        and record.get("schema") == CODEX_RUNTIME_VERIFICATION_SCHEMA
        and record.get("source") == CODEX_GUIDED_RUNTIME_SOURCE
        and record.get("provenance_basis") == "user_confirmed_official_install"
        and record.get("verified") is True
        and isinstance(record.get("executable_path"), str)
        and Path(record["executable_path"]).is_absolute()
        and bool(re.fullmatch(r"\d+\.\d+\.\d+", str(record.get("version", ""))))
        and all(re.fullmatch(r"[0-9a-f]{64}", str(record.get(key, "")))
                for key in ("sha256", "schema_fingerprint"))
        and record.get("protocol_profile") == "stable_app_server_jsonrpc"
    )


def _verify_native_platform(path: Path, expected_os: str, expected_arch: str) -> None:
    """Reject wrappers and wrong-machine binaries before executing them."""
    with path.open("rb") as stream:
        header = stream.read(64)
        actual_os, actual_arch = "", ""
        if header[:2] == b"MZ" and len(header) == 64:
            stream.seek(struct.unpack_from("<I", header, 60)[0])
            pe = stream.read(6)
            if pe[:4] == b"PE\0\0" and len(pe) == 6:
                actual_os = "windows"
                actual_arch = {0x8664: "x86_64", 0xAA64: "aarch64"}.get(
                    struct.unpack_from("<H", pe, 4)[0], "")
        elif header[:4] == b"\x7fELF" and len(header) >= 20 and header[4:6] == b"\x02\x01":
            actual_os = "linux"
            actual_arch = {62: "x86_64", 183: "aarch64"}.get(
                struct.unpack_from("<H", header, 18)[0], "")
        elif header[:4] == b"\xcf\xfa\xed\xfe" and len(header) >= 8:
            actual_os = "macos"
            actual_arch = {0x1000007: "x86_64", 0x100000C: "aarch64"}.get(
                struct.unpack_from("<I", header, 4)[0], "")
    if not actual_os or actual_os != expected_os or not actual_arch or actual_arch != expected_arch:
        raise CodexRuntimeLifecycleError("Unsupported native executable platform/architecture")


def _read_version(executable_path: str) -> str | None:
    completed = subprocess.run(
        [executable_path, "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3.0,
        check=False,
    )
    if completed.returncode != 0:
        raise CodexRuntimeLifecycleError("Codex version command failed")
    output = (completed.stdout or "").strip()
    return output.splitlines()[0].strip() if output else None


def _probe_stable_app_server(executable_path: str) -> Mapping[str, Any]:
    # The public schema generation command does not start a session or read auth.
    with tempfile.TemporaryDirectory(prefix="xace-codex-schema-") as tmp:
        completed = subprocess.run(
            [executable_path, "app-server", "generate-json-schema", "--out", tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, check=False, cwd=tmp,
        )
        if completed.returncode != 0:
            raise CodexRuntimeLifecycleError("Codex App Server schema generation failed")
        documents = {}
        total = 0
        for path in sorted(Path(tmp).rglob("*.json")):
            if path.is_symlink() or not path.resolve().is_relative_to(Path(tmp).resolve()):
                raise CodexRuntimeLifecycleError("Invalid generated schema path")
            total += path.stat().st_size
            if len(documents) >= 2048 or total > 32 * 1024 * 1024:
                raise CodexRuntimeLifecycleError("Generated App Server schema is too large")
            documents[path.relative_to(tmp).as_posix()] = json.loads(path.read_text(encoding="utf-8"))
        return documents


_REQUIRED_METHODS = frozenset({
    "initialize", "account/read", "model/list", "thread/start", "thread/resume",
    "thread/fork", "turn/start", "turn/interrupt",
})


def _stable_schema_fingerprint(probe: Mapping[str, Any]) -> str:
    try:
        return validate_schema(probe)["schema_fingerprint"]
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        raise CodexRuntimeLifecycleError(f"App Server schema incompatible: {exc}") from exc


def _record_health(
    record: Any,
    *,
    platform_name: str,
    architecture: str,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {"valid": False, "code": "not_active"}
    if not _valid_record(record):
        return {"valid": False, "code": "invalid_record_schema"}
    if record.get("compatibility_profile") != PROFILE:
        return {"valid": False, "code": "schema_reverification_required"}
    try:
        version_policy(str(record["version"]))
    except ValueError:
        return {"valid": False, "code": "unsupported_version"}
    if _is_revoked(str(record["version"]), str(record["sha256"])):
        return {"valid": False, "code": "runtime_revoked"}
    path = Path(str(record.get("executable_path") or "")).expanduser()
    if not path.exists() or not path.is_file():
        return {"valid": False, "code": "executable_missing"}
    if str(record.get("platform") or "") != platform_name:
        return {"valid": False, "code": "platform_mismatch"}
    if str(record.get("architecture") or "") != architecture:
        return {"valid": False, "code": "architecture_mismatch"}
    expected = str(record.get("sha256") or "").lower()
    try:
        if _sha256_file(path) != expected:
            return {"valid": False, "code": "digest_mismatch"}
    except OSError:
        return {"valid": False, "code": "executable_unreadable"}
    return {
        "valid": True,
        "code": "verified_active",
        "version": str(record.get("version") or ""),
        "sha256": expected,
        "source": str(record.get("source") or ""),
    }


def _append_history(
    state: dict[str, Any],
    operation: str,
    operation_id: str,
    before: Any,
    after: Any,
) -> None:
    history = list(state.get("history") or [])
    history.append(
        {
            "operation": operation,
            "operation_id": operation_id,
            "before_sha256": (
                str(before.get("sha256") or "") if isinstance(before, Mapping) else None
            ),
            "after_sha256": (
                str(after.get("sha256") or "") if isinstance(after, Mapping) else None
            ),
            "generation": int(state["generation"]),
        }
    )
    state["history"] = history[-32:]


def _operation_id(operation: str, path: str, generation: int) -> str:
    value = f"{operation}\n{Path(path).as_posix()}\n{generation}".encode("utf-8")
    return f"codex-{operation}-{hashlib.sha256(value).hexdigest()[:16]}"


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_version(value: str) -> str | None:
    match = _VERSION_RE.search(str(value or ""))
    return match.group("version") if match else None


def _normalise_platform(value: str) -> str:
    clean = str(value or "").strip().lower()
    return {
        "win32": "windows",
        "windows": "windows",
        "darwin": "macos",
        "macos": "macos",
        "linux": "linux",
    }.get(clean, clean or "unknown")


def _normalise_architecture(value: str) -> str:
    clean = str(value or "").strip().lower()
    return {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }.get(clean, clean or "unknown")


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "CODEX_GUIDED_RUNTIME_SOURCE",
    "CODEX_OFFICIAL_CLI_DOCS",
    "CODEX_OFFICIAL_ENV_DOCS",
    "CODEX_RUNTIME_DIR_ENV",
    "CODEX_RUNTIME_GUIDE_SCHEMA",
    "CODEX_RUNTIME_LIFECYCLE_SCHEMA",
    "CODEX_RUNTIME_LOCK_FILENAME",
    "CODEX_RUNTIME_PENDING_FILENAME",
    "CODEX_RUNTIME_STATE_FILENAME",
    "CODEX_RUNTIME_VERIFICATION_SCHEMA",
    "CodexRuntimeLifecycle",
    "CodexRuntimeLifecycleError",
    "CodexRuntimeVerification",
    "codex_guided_install_plan",
    "resolve_verified_codex_runtime",
]

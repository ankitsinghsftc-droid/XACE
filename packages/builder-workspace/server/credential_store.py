"""
credential_store.py - OS-backed API key storage for XACE Builder.

Provider settings may keep non-secret metadata in JSON, but API keys belong in
the user's platform credential vault. Linux requires libsecret's `secret-tool`.
If no Secret Service is available, an unsafe file fallback is allowed only when
XACE_DEV_UNSAFE_CREDENTIAL_FALLBACK=1 is set explicitly.
"""

from __future__ import annotations

import base64
import ctypes
import getpass
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from secret_redaction import redact_text


SERVICE_NAME = "XACE Builder Provider API Keys"
BACKEND_ENV = "XACE_CREDENTIAL_BACKEND"
UNSAFE_FALLBACK_ENV = "XACE_DEV_UNSAFE_CREDENTIAL_FALLBACK"
UNSAFE_STORE_PATH_ENV = "XACE_UNSAFE_CREDENTIAL_STORE_PATH"


class CredentialStoreError(RuntimeError):
    pass


class CredentialBackend(Protocol):
    name: str
    unsafe: bool

    def set_secret(self, account: str, secret: str) -> None:
        ...

    def get_secret(self, account: str) -> str:
        ...

    def delete_secret(self, account: str) -> None:
        ...


def credential_ref(provider: str) -> str:
    clean = "".join(ch for ch in str(provider or "").lower() if ch.isalnum() or ch in {"_", "-"})
    if not clean:
        raise CredentialStoreError("provider id is required for credential storage")
    return f"xace.provider.{clean}.api_key"


def create_credential_store() -> CredentialBackend:
    requested = os.environ.get(BACKEND_ENV, "auto").strip().lower()
    unsafe_allowed = _unsafe_fallback_enabled()
    if requested in {"unsafe", "unsafe-file", "dev-unsafe"}:
        if not unsafe_allowed:
            raise CredentialStoreError(
                f"{requested} credential backend requires {UNSAFE_FALLBACK_ENV}=1"
            )
        return UnsafeFileCredentialBackend()
    if requested == "windows":
        return WindowsCredentialManagerBackend()
    if requested in {"macos", "keychain"}:
        return MacOSKeychainBackend()
    if requested in {"linux", "secret-service", "libsecret"}:
        return LinuxSecretServiceBackend(allow_unsafe_fallback=unsafe_allowed)
    if requested != "auto":
        raise CredentialStoreError(f"unknown credential backend: {requested}")

    if sys.platform.startswith("win"):
        return WindowsCredentialManagerBackend()
    if sys.platform == "darwin":
        return MacOSKeychainBackend()
    if sys.platform.startswith("linux"):
        return LinuxSecretServiceBackend(allow_unsafe_fallback=unsafe_allowed)
    if unsafe_allowed:
        return UnsafeFileCredentialBackend()
    raise CredentialStoreError(
        f"unsupported credential platform {sys.platform!r}; set "
        f"{UNSAFE_FALLBACK_ENV}=1 only for local development"
    )


class WindowsCredentialManagerBackend:
    name = "windows-credential-manager"
    unsafe = False

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    def __init__(self) -> None:
        if not sys.platform.startswith("win"):
            raise CredentialStoreError("Windows Credential Manager is available only on Windows")
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)

    def set_secret(self, account: str, secret: str) -> None:
        blob = secret.encode("utf-16-le")
        blob_buffer = ctypes.create_string_buffer(blob)
        credential = self._CREDENTIAL()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = account
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_byte))
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = SERVICE_NAME
        if not self._advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialStoreError(f"CredWriteW failed: {_win_error()}")

    def get_secret(self, account: str) -> str:
        credential_ptr = ctypes.POINTER(self._CREDENTIAL)()
        ok = self._advapi32.CredReadW(
            ctypes.c_wchar_p(account),
            self.CRED_TYPE_GENERIC,
            0,
            ctypes.byref(credential_ptr),
        )
        if not ok:
            return ""
        try:
            credential = credential_ptr.contents
            size = int(credential.CredentialBlobSize)
            raw = ctypes.string_at(credential.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            self._advapi32.CredFree(credential_ptr)

    def delete_secret(self, account: str) -> None:
        self._advapi32.CredDeleteW(ctypes.c_wchar_p(account), self.CRED_TYPE_GENERIC, 0)


class MacOSKeychainBackend:
    name = "macos-keychain"
    unsafe = False

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise CredentialStoreError("macOS Keychain is available only on macOS")
        if shutil.which("security") is None:
            raise CredentialStoreError("macOS security command not found")

    def set_secret(self, account: str, secret: str) -> None:
        _run_secret_command([
            "security",
            "add-generic-password",
            "-U",
            "-s",
            SERVICE_NAME,
            "-a",
            account,
            "-w",
            secret,
        ])

    def get_secret(self, account: str) -> str:
        result = _run_secret_command([
            "security",
            "find-generic-password",
            "-s",
            SERVICE_NAME,
            "-a",
            account,
            "-w",
        ], missing_ok=True)
        return result.stdout.strip() if result.returncode == 0 else ""

    def delete_secret(self, account: str) -> None:
        _run_secret_command([
            "security",
            "delete-generic-password",
            "-s",
            SERVICE_NAME,
            "-a",
            account,
        ], missing_ok=True)


class LinuxSecretServiceBackend:
    name = "linux-secret-service"
    unsafe = False

    def __new__(cls, *, allow_unsafe_fallback: bool = False):
        if not sys.platform.startswith("linux"):
            raise CredentialStoreError("Linux Secret Service is available only on Linux")
        if shutil.which("secret-tool") is not None:
            return super().__new__(cls)
        if allow_unsafe_fallback:
            return UnsafeFileCredentialBackend()
        raise CredentialStoreError(
            "libsecret secret-tool not found. Install libsecret-tools or set "
            f"{UNSAFE_FALLBACK_ENV}=1 for an explicit dev-only unsafe fallback."
        )

    def __init__(self, *, allow_unsafe_fallback: bool = False) -> None:
        pass

    def set_secret(self, account: str, secret: str) -> None:
        _run_secret_command([
            "secret-tool",
            "store",
            "--label",
            SERVICE_NAME,
            "service",
            "xace",
            "account",
            account,
        ], input_text=secret)

    def get_secret(self, account: str) -> str:
        result = _run_secret_command([
            "secret-tool",
            "lookup",
            "service",
            "xace",
            "account",
            account,
        ], missing_ok=True)
        return result.stdout.rstrip("\r\n") if result.returncode == 0 else ""

    def delete_secret(self, account: str) -> None:
        _run_secret_command([
            "secret-tool",
            "clear",
            "service",
            "xace",
            "account",
            account,
        ], missing_ok=True)


class UnsafeFileCredentialBackend:
    name = "dev-unsafe-file"
    unsafe = True

    def __init__(self, path: Path | None = None) -> None:
        configured = os.environ.get(UNSAFE_STORE_PATH_ENV, "").strip()
        selected = path or (Path(configured).expanduser() if configured else Path.home() / ".xace" / "dev_unsafe_credentials.json")
        self.path = selected.resolve()

    def set_secret(self, account: str, secret: str) -> None:
        data = self._load()
        data[account] = _protect_secret(secret)
        self._save(data)

    def get_secret(self, account: str) -> str:
        token = self._load().get(account)
        if not isinstance(token, str) or not token:
            return ""
        return _unprotect_secret(token)

    def delete_secret(self, account: str) -> None:
        data = self._load()
        data.pop(account, None)
        self._save(data)

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


def _run_secret_command(
    args: list[str],
    *,
    input_text: str | None = None,
    missing_ok: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 and not missing_ok:
        detail = redact_text((result.stderr or result.stdout or "").strip())
        raise CredentialStoreError(f"{args[0]} failed with code {result.returncode}: {detail}")
    return result


def _unsafe_fallback_enabled() -> bool:
    return os.environ.get(UNSAFE_FALLBACK_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _win_error() -> str:
    return ctypes.FormatError(ctypes.get_last_error()).strip()


def _protect_secret(secret: str) -> str:
    data = secret.encode("utf-8")
    protected = _xor_with_local_key(data)
    return "xace-dev1." + base64.urlsafe_b64encode(protected).decode("ascii")


def _unprotect_secret(token: str) -> str:
    if not token.startswith("xace-dev1."):
        return ""
    data = base64.urlsafe_b64decode(token.split(".", 1)[1].encode("ascii"))
    return _xor_with_local_key(data).decode("utf-8")


def _xor_with_local_key(data: bytes) -> bytes:
    key_material = "|".join([
        "xace-provider-credential-dev-fallback-v1",
        getpass.getuser(),
        socket.gethostname(),
    ]).encode("utf-8", errors="ignore")
    key = hashlib.sha256(key_material).digest()
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))

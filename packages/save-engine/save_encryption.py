"""Optional save encryption.

AES-256-GCM is used when the optional ``cryptography`` package is installed.
No insecure fallback cipher is provided; callers can choose ``NONE`` for clear
storage or install cryptography for authenticated encryption.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from enum import Enum


MAGIC = b"XACE-SAVE-ENCRYPTED\0"
VERSION = 1
AES_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
PBKDF2_ITERATIONS = 390_000


class SaveCipher(str, Enum):
    NONE = "NONE"
    AES_256_GCM = "AES_256_GCM"


class SaveEncryptionError(RuntimeError):
    """Raised when encryption/decryption fails."""


@dataclass(frozen=True)
class EncryptionKey:
    cipher: SaveCipher
    key_bytes: bytes
    salt: bytes = b""
    iterations: int = PBKDF2_ITERATIONS

    @classmethod
    def from_raw(cls, key_bytes: bytes, *, cipher: SaveCipher | str = SaveCipher.AES_256_GCM) -> "EncryptionKey":
        normalised = _normalise_cipher(cipher)
        if normalised == SaveCipher.NONE:
            return cls(cipher=normalised, key_bytes=b"")
        if len(key_bytes) != AES_KEY_BYTES:
            raise SaveEncryptionError("AES_256_GCM raw key must be 32 bytes")
        return cls(cipher=normalised, key_bytes=bytes(key_bytes))

    @classmethod
    def from_passphrase(
        cls,
        passphrase: str,
        *,
        salt: bytes | None = None,
        iterations: int = PBKDF2_ITERATIONS,
    ) -> "EncryptionKey":
        text = str(passphrase)
        if not text:
            raise SaveEncryptionError("passphrase must not be empty")
        if iterations < 100_000:
            raise SaveEncryptionError("PBKDF2 iterations must be >= 100000")
        actual_salt = salt if salt is not None else secrets.token_bytes(16)
        key = hashlib.pbkdf2_hmac("sha256", text.encode("utf-8"), actual_salt, iterations, AES_KEY_BYTES)
        return cls(
            cipher=SaveCipher.AES_256_GCM,
            key_bytes=key,
            salt=actual_salt,
            iterations=iterations,
        )


@dataclass(frozen=True)
class EncryptionReport:
    cipher: SaveCipher
    plaintext_bytes: int
    encrypted_bytes: int


class SaveEncryption:
    """Authenticated encryption wrapper for save bytes."""

    def encrypt(self, data: bytes, key: EncryptionKey, *, nonce: bytes | None = None) -> tuple[bytes, EncryptionReport]:
        if not isinstance(data, (bytes, bytearray)):
            raise SaveEncryptionError("data must be bytes")
        if key.cipher == SaveCipher.NONE:
            envelope = _pack(SaveCipher.NONE, b"", key.salt, key.iterations, bytes(data))
            return envelope, EncryptionReport(key.cipher, len(data), len(envelope))
        if key.cipher != SaveCipher.AES_256_GCM:
            raise SaveEncryptionError(f"unsupported cipher: {key.cipher.value}")
        aesgcm = _aesgcm(key.key_bytes)
        actual_nonce = nonce if nonce is not None else secrets.token_bytes(AES_GCM_NONCE_BYTES)
        if len(actual_nonce) != AES_GCM_NONCE_BYTES:
            raise SaveEncryptionError("AES-GCM nonce must be 12 bytes")
        ciphertext = aesgcm.encrypt(actual_nonce, bytes(data), MAGIC)
        envelope = _pack(key.cipher, actual_nonce, key.salt, key.iterations, ciphertext)
        return envelope, EncryptionReport(key.cipher, len(data), len(envelope))

    def decrypt(self, data: bytes, key: EncryptionKey) -> bytes:
        cipher, nonce, salt, iterations, body = _unpack(data)
        if cipher != key.cipher:
            raise SaveEncryptionError(f"cipher mismatch: envelope={cipher.value} key={key.cipher.value}")
        if salt and key.salt and salt != key.salt:
            raise SaveEncryptionError("encryption salt mismatch")
        if iterations != key.iterations:
            raise SaveEncryptionError("PBKDF2 iteration mismatch")
        if cipher == SaveCipher.NONE:
            return body
        aesgcm = _aesgcm(key.key_bytes)
        try:
            return aesgcm.decrypt(nonce, body, MAGIC)
        except Exception as exc:
            raise SaveEncryptionError("save decryption failed") from exc


def encryption_available(cipher: SaveCipher | str = SaveCipher.AES_256_GCM) -> bool:
    normalised = _normalise_cipher(cipher)
    if normalised == SaveCipher.NONE:
        return True
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore[import-not-found]

        return AESGCM is not None
    except Exception:
        return False


def _pack(cipher: SaveCipher, nonce: bytes, salt: bytes, iterations: int, body: bytes) -> bytes:
    cipher_bytes = cipher.value.encode("ascii")
    if len(cipher_bytes) > 255 or len(nonce) > 255 or len(salt) > 255:
        raise SaveEncryptionError("encryption header field too large")
    return b"".join(
        [
            MAGIC,
            bytes([VERSION]),
            bytes([len(cipher_bytes)]),
            cipher_bytes,
            bytes([len(nonce)]),
            nonce,
            bytes([len(salt)]),
            salt,
            iterations.to_bytes(4, "little", signed=False),
            body,
        ]
    )


def _unpack(data: bytes) -> tuple[SaveCipher, bytes, bytes, int, bytes]:
    raw = bytes(data)
    if not raw.startswith(MAGIC):
        raise SaveEncryptionError("encrypted data missing XACE header")
    offset = len(MAGIC)
    if len(raw) < offset + 2:
        raise SaveEncryptionError("encrypted data header is truncated")
    version = raw[offset]
    offset += 1
    if version != VERSION:
        raise SaveEncryptionError(f"unsupported encryption version: {version}")
    cipher_len = raw[offset]
    offset += 1
    cipher = _normalise_cipher(raw[offset : offset + cipher_len].decode("ascii"))
    offset += cipher_len
    nonce_len = raw[offset]
    offset += 1
    nonce = raw[offset : offset + nonce_len]
    offset += nonce_len
    salt_len = raw[offset]
    offset += 1
    salt = raw[offset : offset + salt_len]
    offset += salt_len
    if len(raw) < offset + 4:
        raise SaveEncryptionError("encrypted data metadata is truncated")
    iterations = int.from_bytes(raw[offset : offset + 4], "little", signed=False)
    offset += 4
    return cipher, nonce, salt, iterations, raw[offset:]


def _normalise_cipher(value: SaveCipher | str) -> SaveCipher:
    if isinstance(value, SaveCipher):
        return value
    text = str(value).strip().upper()
    try:
        return SaveCipher(text)
    except ValueError as exc:
        allowed = ", ".join(cipher.value for cipher in SaveCipher)
        raise SaveEncryptionError(f"cipher must be one of {allowed}") from exc


def _aesgcm(key_bytes: bytes):
    if len(key_bytes) != AES_KEY_BYTES:
        raise SaveEncryptionError("AES_256_GCM key must be 32 bytes")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore[import-not-found]

        return AESGCM(key_bytes)
    except Exception as exc:
        raise SaveEncryptionError(
            "AES_256_GCM requires the optional 'cryptography' package"
        ) from exc


def generate_raw_key() -> EncryptionKey:
    return EncryptionKey.from_raw(os.urandom(AES_KEY_BYTES))

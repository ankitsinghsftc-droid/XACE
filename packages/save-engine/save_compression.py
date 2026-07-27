"""Compression helpers for save files.

The manifest calls for LZ4. When the optional ``lz4`` package is available we
use its frame format; otherwise the module falls back to deterministic zlib so
development and tests keep working without native dependencies.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from enum import Enum


MAGIC = b"XACE-SAVE-COMPRESSED\0"
VERSION = 1


class CompressionCodec(str, Enum):
    NONE = "NONE"
    LZ4 = "LZ4"
    ZLIB = "ZLIB"


class SaveCompressionError(RuntimeError):
    """Raised when compressed save bytes cannot be encoded or decoded."""


@dataclass(frozen=True)
class CompressionReport:
    codec: CompressionCodec
    original_bytes: int
    compressed_bytes: int

    @property
    def ratio(self) -> float:
        if self.original_bytes == 0:
            return 1.0
        return self.compressed_bytes / self.original_bytes


class SaveCompression:
    """Codec envelope for compressed save payloads."""

    def __init__(self, preferred_codec: CompressionCodec | str = CompressionCodec.LZ4) -> None:
        self.preferred_codec = _normalise_codec(preferred_codec)

    def compress(self, data: bytes) -> tuple[bytes, CompressionReport]:
        if not isinstance(data, (bytes, bytearray)):
            raise SaveCompressionError("data must be bytes")
        raw = bytes(data)
        codec = self._select_codec()
        if codec == CompressionCodec.NONE:
            body = raw
        elif codec == CompressionCodec.LZ4:
            body = _lz4_compress(raw)
        elif codec == CompressionCodec.ZLIB:
            body = zlib.compress(raw, level=9)
        else:
            raise SaveCompressionError(f"unsupported codec: {codec}")
        envelope = _pack(codec, len(raw), body)
        return envelope, CompressionReport(codec, len(raw), len(envelope))

    def decompress(self, data: bytes) -> bytes:
        codec, expected_len, body = _unpack(data)
        if codec == CompressionCodec.NONE:
            raw = body
        elif codec == CompressionCodec.LZ4:
            raw = _lz4_decompress(body)
        elif codec == CompressionCodec.ZLIB:
            raw = zlib.decompress(body)
        else:
            raise SaveCompressionError(f"unsupported codec: {codec}")
        if len(raw) != expected_len:
            raise SaveCompressionError(
                f"decompressed size mismatch: expected {expected_len}, got {len(raw)}"
            )
        return raw

    def _select_codec(self) -> CompressionCodec:
        if self.preferred_codec == CompressionCodec.LZ4 and not _has_lz4():
            return CompressionCodec.ZLIB
        return self.preferred_codec


def _pack(codec: CompressionCodec, original_len: int, body: bytes) -> bytes:
    codec_bytes = codec.value.encode("ascii")
    if len(codec_bytes) > 255:
        raise SaveCompressionError("codec name too long")
    return b"".join(
        [
            MAGIC,
            bytes([VERSION]),
            bytes([len(codec_bytes)]),
            codec_bytes,
            original_len.to_bytes(8, "little", signed=False),
            body,
        ]
    )


def _unpack(data: bytes) -> tuple[CompressionCodec, int, bytes]:
    if not isinstance(data, (bytes, bytearray)):
        raise SaveCompressionError("compressed data must be bytes")
    raw = bytes(data)
    if not raw.startswith(MAGIC):
        raise SaveCompressionError("compressed data missing XACE header")
    offset = len(MAGIC)
    if len(raw) < offset + 2:
        raise SaveCompressionError("compressed data header is truncated")
    version = raw[offset]
    offset += 1
    if version != VERSION:
        raise SaveCompressionError(f"unsupported compression version: {version}")
    codec_len = raw[offset]
    offset += 1
    codec_end = offset + codec_len
    size_end = codec_end + 8
    if len(raw) < size_end:
        raise SaveCompressionError("compressed data metadata is truncated")
    codec = _normalise_codec(raw[offset:codec_end].decode("ascii"))
    expected_len = int.from_bytes(raw[codec_end:size_end], "little", signed=False)
    return codec, expected_len, raw[size_end:]


def _normalise_codec(value: CompressionCodec | str) -> CompressionCodec:
    if isinstance(value, CompressionCodec):
        return value
    text = str(value).strip().upper()
    try:
        return CompressionCodec(text)
    except ValueError as exc:
        allowed = ", ".join(codec.value for codec in CompressionCodec)
        raise SaveCompressionError(f"codec must be one of {allowed}") from exc


def _has_lz4() -> bool:
    try:
        import lz4.frame  # type: ignore[import-not-found]

        return lz4.frame is not None
    except Exception:
        return False


def _lz4_compress(data: bytes) -> bytes:
    try:
        import lz4.frame  # type: ignore[import-not-found]

        return lz4.frame.compress(data, compression_level=0, block_linked=True)
    except Exception as exc:
        raise SaveCompressionError("LZ4 compression is unavailable") from exc


def _lz4_decompress(data: bytes) -> bytes:
    try:
        import lz4.frame  # type: ignore[import-not-found]

        return lz4.frame.decompress(data)
    except Exception as exc:
        raise SaveCompressionError("LZ4 decompression failed") from exc

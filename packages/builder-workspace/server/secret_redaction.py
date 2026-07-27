"""
Secret redaction helpers for logs, telemetry, errors, crash reports, and
serialized artifacts.

This module intentionally has no project-specific imports so it can be reused
from Builder server code, inference telemetry, smokes, and security tooling.
"""

from __future__ import annotations

import logging
import re
from dataclasses import is_dataclass, replace
from typing import Any


REDACTED_SECRET = "[REDACTED_SECRET]"

_SECRET_KEY_NAMES = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "x-api-key",
    "x_api_key",
    "secret",
    "password",
}

_TOKEN_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9][A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+\-/=]{12,}"),
    re.compile(r"(?i)((?:x-api-key|api-key)\s*[:=]\s*)[A-Za-z0-9._~+\-/=]{12,}"),
]


def redact_text(value: Any) -> str:
    """Returns a string with known credential shapes replaced."""
    text = "" if value is None else str(value)
    for pattern in _TOKEN_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda match: match.group(1) + REDACTED_SECRET, text)
        else:
            text = pattern.sub(REDACTED_SECRET, text)
    return text


def redact_value(value: Any) -> Any:
    """Recursively redacts strings and secret-bearing fields in JSON-like data."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key).strip().lower().replace("-", "_")
            if key_text in _SECRET_KEY_NAMES or key_text.replace("_", "") in _SECRET_KEY_NAMES:
                redacted[key] = REDACTED_SECRET if item else item
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        updates = {field: redact_value(getattr(value, field)) for field in value.__dataclass_fields__}
        return replace(value, **updates)
    return value


def redact_exception(exc: BaseException) -> str:
    return redact_text(str(exc).strip() or exc.__class__.__name__)


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts secrets from the final rendered message."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))

"""Fixed stdio-to-loopback proxy launched by Codex for XACE native MCP."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from typing import Any, BinaryIO


TOKEN_ENV = "XACE_MCP_SESSION_TOKEN"
MAX_LINE_BYTES = 8 * 1024 * 1024


def _read_object(stream: BinaryIO, *, allow_eof: bool = False) -> dict[str, Any] | None:
    line = stream.readline(MAX_LINE_BYTES + 1)
    if not line:
        if allow_eof:
            return None
        raise RuntimeError("XACE MCP broker closed the connection")
    if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
        raise RuntimeError("XACE MCP message exceeded its size limit")
    value = json.loads(line.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("XACE MCP message must be an object")
    return value


def _write_object(stream: BinaryIO, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_LINE_BYTES:
        raise RuntimeError("XACE MCP message exceeded its size limit")
    stream.write(payload + b"\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args(argv)
    if args.host != "127.0.0.1" or not (1 <= args.port <= 65535):
        print("XACE MCP proxy rejected a non-loopback endpoint.", file=sys.stderr)
        return 2
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        print("XACE MCP proxy is missing session authentication.", file=sys.stderr)
        return 2

    try:
        with socket.create_connection((args.host, args.port), timeout=5.0) as connection:
            connection.settimeout(60.0)
            reader = connection.makefile("rb")
            writer = connection.makefile("wb")
            try:
                _write_object(writer, {"token": token})
                auth = _read_object(reader)
                if not auth or auth.get("ok") is not True:
                    print("XACE MCP proxy authentication failed.", file=sys.stderr)
                    return 3
                while True:
                    message = _read_object(sys.stdin.buffer, allow_eof=True)
                    if message is None:
                        return 0
                    _write_object(writer, {"message": message})
                    envelope = _read_object(reader)
                    if envelope is None or "error" in envelope:
                        raise RuntimeError("XACE MCP broker rejected a message")
                    response = envelope.get("response")
                    if response is not None:
                        if not isinstance(response, dict):
                            raise RuntimeError("XACE MCP broker returned an invalid response")
                        _write_object(sys.stdout.buffer, response)
            finally:
                reader.close()
                writer.close()
    except Exception:
        print("XACE MCP proxy connection failed.", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())

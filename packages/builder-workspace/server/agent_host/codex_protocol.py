"""Bounded stdio protocol. No retries of possibly accepted provider operations."""
from __future__ import annotations

import contextlib
import json
import queue
import threading
import time
from collections import deque
from collections.abc import Mapping

MAX_FRAME_CHARS = 256 * 1024
MAX_QUEUED_FRAMES = 64
MAX_PENDING_NOTIFICATIONS = 64


class CodexAppServerProtocolError(RuntimeError):
    def __init__(self, message, *, code="protocol_error", retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class JsonRpcLineSession:
    def __init__(self, proc, *, timeout_seconds):
        self._proc = proc
        self._timeout_seconds = max(.25, float(timeout_seconds))
        self._next_id = 1
        self._messages = queue.Queue(maxsize=MAX_QUEUED_FRAMES)
        self.notifications = deque()
        self._io_lock = threading.RLock()
        self._closed = threading.Event()
        self._eof = threading.Event()
        self._failure = None
        self._reader = threading.Thread(target=self._read_stdout, name="codex-app-server-stdio-reader", daemon=True)
        self._reader.start()

    def _fail(self, code, *, retryable=False):
        self._failure = self._failure or CodexAppServerProtocolError(
            f"Codex App Server {code}; reconnect or repair/update the runtime. No operation was replayed.",
            code=code, retryable=retryable)
        # Stop output at the producer; do not silently drop ordered events.
        if self._proc.poll() is None:
            with contextlib.suppress(Exception):
                self._proc.terminate()
        return self._failure

    def request(self, method, params):
        with self._io_lock:
            request_id = self._next_id
            self._next_id += 1
            try:
                self._send({"method": method, "id": request_id, "params": None if method == "account/logout" and not params else dict(params)})
                return self._read_response(request_id)
            except CodexAppServerProtocolError as exc:
                if exc.code != "provider_error":
                    self.close()
                raise

    def optional_request(self, method, params):
        try:
            return self.request(method, params)
        except CodexAppServerProtocolError as exc:
            if exc.code != "provider_error":
                raise
            return {"unavailable": True, "method": method, "error": str(exc)}

    def notify(self, method, params):
        with self._io_lock:
            self._send({"method": method, "params": dict(params)})

    def respond(self, request_id, result):
        with self._io_lock:
            self._send({"id": request_id, "result": dict(result)})

    def read_notification(self, timeout_seconds=.25):
        deadline = time.monotonic() + max(.01, float(timeout_seconds))
        with self._io_lock:
            try:
                if self._failure:
                    raise self._failure
                if self.notifications:
                    return self.notifications.popleft()
                while time.monotonic() < deadline:
                    message = self._next_message(deadline)
                    if message is None:
                        continue
                    if "method" not in message:
                        raise self._fail("unexpected_response")
                    return message
                return None
            except CodexAppServerProtocolError:
                self.close()
                raise

    def close(self):
        # Kill/wait BEFORE closing stdout: the reader may hold its IO lock.
        self._closed.set()
        if self._proc.poll() is None:
            with contextlib.suppress(Exception):
                self._proc.terminate()
            try:
                self._proc.wait(timeout=1)
            except Exception:
                with contextlib.suppress(Exception):
                    self._proc.kill()
                    self._proc.wait(timeout=1)
        if threading.current_thread() is not self._reader:
            self._reader.join(timeout=1)
        for stream in (self._proc.stdin, self._proc.stdout):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()
        self.notifications.clear()

    def _send(self, message):
        if self._failure:
            raise self._failure
        if self._closed.is_set() or self._proc.poll() is not None:
            raise self._fail("process_exited", retryable=True)
        try:
            encoded = json.dumps(message, separators=(",", ":"), allow_nan=False) + "\n"
            if len(encoded) > MAX_FRAME_CHARS:
                raise self._fail("outbound_frame_too_large")
            finished = threading.Event()
            failed = []
            def write():
                try:
                    self._proc.stdin.write(encoded)
                    self._proc.stdin.flush()
                except Exception:
                    failed.append(True)
                finally:
                    finished.set()
            writer = threading.Thread(target=write, name="codex-app-server-stdio-writer", daemon=True)
            writer.start()
            if not finished.wait(self._timeout_seconds):
                error = self._fail("write_timeout", retryable=True)
                self.close()
                writer.join(timeout=1)
                raise error
            writer.join(timeout=1)
            if failed:
                raise self._fail("write_failed", retryable=True)
        except CodexAppServerProtocolError:
            raise
        except Exception:
            raise self._fail("write_failed", retryable=True) from None

    def _read_response(self, request_id):
        deadline = time.monotonic() + self._timeout_seconds
        while time.monotonic() < deadline:
            message = self._next_message(deadline)
            if message is None:
                continue
            if "method" in message:
                if len(self.notifications) >= MAX_PENDING_NOTIFICATIONS:
                    raise self._fail("notification_backpressure")
                self.notifications.append(message)
                continue
            if message.get("id") != request_id:
                raise self._fail("response_id_mismatch")
            if "error" in message:
                error = message["error"]
                # Provider strings may contain credentials/project content.
                raw = str(error.get("message", "")).lower()
                category = ("unauthorized" if any(x in raw for x in ("401", "unauthorized", "expired"))
                            else "rate limit" if any(x in raw for x in ("429", "quota", "rate limit"))
                            else "workspace forbidden" if any(x in raw for x in ("403", "forbidden", "entitlement"))
                            else "unsupported method" if error.get("code") == -32601
                            else "provider request failed")
                raise CodexAppServerProtocolError(category, code="provider_error")
            return message["result"]
        raise self._fail("request_timeout", retryable=True)

    def _next_message(self, deadline):
        if self._failure:
            raise self._failure
        try:
            line = self._messages.get(timeout=max(.001, min(.05, deadline-time.monotonic())))
        except queue.Empty:
            if self._eof.is_set() or self._proc.poll() is not None:
                raise self._fail("process_exited", retryable=True)
            return None
        try:
            message = json.loads(line, object_pairs_hook=_object,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(message, dict):
                raise ValueError()
            if "jsonrpc" in message and message["jsonrpc"] != "2.0":
                raise ValueError()
            if "id" in message and type(message["id"]) not in (int, str):
                raise ValueError()
            if "method" in message:
                if not isinstance(message["method"], str) or not message["method"] or not isinstance(message.get("params", {}), dict):
                    raise ValueError()
                if "result" in message or "error" in message:
                    raise ValueError()
            elif ("id" not in message or ("result" in message) == ("error" in message)
                  or not isinstance(message.get("result", message.get("error")), dict)):
                raise ValueError()
            return message
        except (ValueError, TypeError, RecursionError):
            raise self._fail("malformed_frame") from None

    def _read_stdout(self):
        try:
            while not self._closed.is_set():
                line = self._proc.stdout.readline(MAX_FRAME_CHARS + 1)
                if not line:
                    break
                if len(line) > MAX_FRAME_CHARS or not line.endswith("\n"):
                    self._fail("oversized_or_truncated_frame")
                    break
                try:
                    self._messages.put_nowait(line)
                except queue.Full:
                    self._fail("stream_backpressure")
                    break
        except Exception:
            if not self._closed.is_set():
                self._fail("read_failed", retryable=True)
        finally:
            self._eof.set()

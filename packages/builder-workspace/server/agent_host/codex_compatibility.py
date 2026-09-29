"""AG-027: versioned, conservative XACE-consumed protocol compatibility profile.

This checks the contract XACE uses, not arbitrary JSON Schema equivalence.
Unknown validation constructs on a consumed request fail closed.
"""
import hashlib
import json
import re
from datetime import date

PROFILE = "xace.codex_app_server_contract.v1"
MIN_VERSION = (0, 143, 0)
MAX_VERSION_EXCLUSIVE = (0, 155, 0)
# Maintainer-owned sunset dates; normal changes require 30 days notice.
DEPRECATED_VERSIONS = {}


def version_policy(version, *, today=None):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version or "")
    if not match:
        raise ValueError("Prerelease or unknown Codex version is not supported")
    parsed = tuple(map(int, match.groups()))
    if not MIN_VERSION <= parsed < MAX_VERSION_EXCLUSIVE:
        raise ValueError("Codex version outside supported schema-gated range; update or roll back")
    sunset = DEPRECATED_VERSIONS.get(version)
    if sunset and (today or date.today()) >= date.fromisoformat(sunset):
        raise ValueError("Codex version is deprecated; update or roll back to a supported version")
    return {"deprecation_sunset": sunset, "profile": PROFILE, "range": ">=0.143.0,<0.155.0", "prerelease": False,
            "certification": "schema_verified_not_real_account_certified"}


CONFIG = {"features": {"shell_tool": False, "unified_exec": False}, "web_search": "disabled",
          "mcp_servers": {"xace": {"command": "xace", "args": [], "required": True}}}
THREAD = {"approvalPolicy": "never", "sandbox": "read-only", "cwd": "/capsule", "config": CONFIG}
REQUESTS = {
    "initialize": {"clientInfo": {"name": "xace", "version": "1"}, "capabilities": {"experimentalApi": False}},
    "account/read": {"refreshToken": False},
    "account/login/start": {"type": "chatgpt"},
    "account/login/cancel": {"loginId": "login"},
    "account/logout": None,
    "account/rateLimits/read": {},
    "model/list": {},
    "thread/start": {**THREAD, "model": "model", "serviceName": "xace_builder", "allowProviderModelFallback": True},
    "thread/resume": {**THREAD, "threadId": "thread", "excludeTurns": True, "model": "model",
                      "initialTurnsPage": {"limit": 20, "sortDirection": "desc", "itemsView": "summary"}},
    "thread/fork": {"threadId": "thread", "excludeTurns": True, "ephemeral": False,
                    "lastTurnId": "turn", "beforeTurnId": "turn"},
    "thread/compact/start": {"threadId": "thread"},
    "turn/start": {"threadId": "thread", "clientUserMessageId": "message", "summary": "concise",
                   "personality": "pragmatic", "cwd": "/capsule", "model": "model", "effort": "high", "input": [{"type": "text", "text": "hello"}],
                   "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly", "access": {"type": "restricted", "includePlatformDefaults": False, "readableRoots": ["/capsule"]}}},
    "turn/interrupt": {"threadId": "thread", "turnId": "turn"},
    "mcpServerStatus/list": {"threadId": "thread", "detail": "toolsAndAuthOnly", "limit": 100},
}


def _resolve(node, doc, depth=0):
    if depth > 80 or not isinstance(node, dict):
        raise ValueError("Invalid or recursive App Server schema")
    if "$ref" in node:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            raise ValueError("External schema reference is not supported")
        target = doc
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return _resolve(target, doc, depth + 1)
    return node


def _accepts(value, node, doc, depth=0):
    if depth > 80:
        return False
    node = _resolve(node, doc)
    known = {"$schema", "$id", "$ref", "definitions", "$defs", "title", "description", "default", "examples",
             "deprecated", "type", "enum", "const", "anyOf", "oneOf", "allOf", "required", "properties",
             "additionalProperties", "items", "minItems", "maxItems", "minLength", "maxLength",
             "minimum", "maximum", "pattern", "format"}
    if set(node) - known:
        return False
    for key in ("anyOf", "oneOf", "allOf"):
        if key in node:
            results = [_accepts(value, branch, doc, depth+1) for branch in node[key]]
            if not (all(results) if key == "allOf" else sum(results) == 1 if key == "oneOf" else any(results)):
                return False
    kinds = {"null": value is None, "boolean": type(value) is bool, "string": isinstance(value, str),
             "integer": type(value) is int, "number": type(value) in (int, float),
             "array": isinstance(value, list), "object": isinstance(value, dict)}
    types = node.get("type")
    if types and not any(kinds.get(t, False) for t in ([types] if isinstance(types, str) else types)):
        return False
    if "enum" in node and value not in node["enum"] or "const" in node and value != node["const"]:
        return False
    if isinstance(value, dict):
        props = node.get("properties", {})
        if not set(node.get("required", [])).issubset(value):
            return False
        for key, item in value.items():
            if key in props:
                if not _accepts(item, props[key], doc, depth+1):
                    return False
            else:
                extra = node.get("additionalProperties", True)
                # Required XACE fields must be declared, except intentionally free maps.
                if props or extra is False:
                    return False
                if isinstance(extra, dict) and not _accepts(item, extra, doc, depth+1):
                    return False
    if isinstance(value, list):
        if not node.get("minItems", 0) <= len(value) <= node.get("maxItems", float("inf")):
            return False
        if not all(_accepts(item, node.get("items", {}), doc, depth+1) for item in value):
            return False
    if isinstance(value, str):
        if not node.get("minLength", 0) <= len(value) <= node.get("maxLength", float("inf")):
            return False
        if "pattern" in node and not re.search(node["pattern"], value):
            return False
        if "format" in node:  # Unknown string formats are not guessed.
            return False
    if type(value) in (int, float) and not node.get("minimum", -float("inf")) <= value <= node.get("maximum", float("inf")):
        return False
    return True


def validate_schema(documents):
    """Accept additive methods/optional fields; reject consumed request breakage."""
    doc = documents.get("ClientRequest.json")
    if not isinstance(doc, dict):
        raise ValueError("App Server schema lacks ClientRequest.json")
    branches = doc.get("oneOf", doc.get("anyOf", []))
    methods = {}
    for branch in branches:
        branch = _resolve(branch, doc)
        method = _resolve(branch.get("properties", {}).get("method", {}), doc)
        names = method.get("enum", [method.get("const")])
        for name in names:
            if isinstance(name, str):
                if name in methods:
                    raise ValueError("Duplicate App Server method schema")
                methods[name] = branch
    for method, params in REQUESTS.items():
        if method not in methods or not _accepts({"id": 1, "method": method, "params": params}, methods[method], doc):
            raise ValueError(f"App Server schema incompatible with {method}; update or roll back")
    # Independently check device-code login, not merely the browser variant.
    if not _accepts({"id": 1, "method": "account/login/start", "params": {"type": "chatgptDeviceCode"}}, methods["account/login/start"], doc):
        raise ValueError("App Server schema lacks device-code authentication")
    canonical = json.dumps(documents, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"profile": PROFILE, "schema_fingerprint": hashlib.sha256(canonical).hexdigest(),
            "required_methods": sorted(REQUESTS), "document_count": len(documents)}

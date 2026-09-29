"""Synthetic consumed-contract fixture, NOT a vendor schema or certified binary."""
from agent_host.codex_compatibility import REQUESTS


def _shape(value):
    if value is None:
        return {"type": "null"}
    if type(value) is bool:
        return {"type": "boolean"}
    if type(value) is int:
        return {"type": "integer"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {"type": "array", "items": _shape(value[0]) if value else {}}
    return {"type": "object", "properties": {k: _shape(v) for k,v in value.items()}, "required": list(value)}


def schema_fixture():
    return {"ClientRequest.json": {"oneOf": [
        {"type": "object", "properties": {"method": {"const": method}, "id": {"type": "integer"},
                                             "params": _shape(params)}, "required": ["id", "method", "params"]}
        for method, params in REQUESTS.items()
    ]}}

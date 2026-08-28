from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


STRUCTURED_OUTPUT_PROVIDER_MODES: dict[str, str] = {
    "anthropic": "anthropic_tool",
    "google": "gemini_response_schema",
    "openai": "openai_json_schema",
}


@dataclass(frozen=True)
class StructuredOutputContract:
    schema_id: str
    name: str
    schema: dict[str, Any]
    description: str = ""
    strict: bool = True

    @property
    def schema_hash(self) -> str:
        payload = json.dumps(self.schema, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StructuredOutputPlan:
    requested: bool
    supported: bool
    mode: str
    schema_id: str = ""
    schema_name: str = ""
    schema_hash: str = ""

    @classmethod
    def none(cls) -> "StructuredOutputPlan":
        return cls(requested=False, supported=False, mode="none")

    def telemetry_fields(self, *, quarantined: bool = False) -> dict[str, Any]:
        return {
            "structured_output_requested": self.requested,
            "structured_output_supported": self.supported,
            "structured_output_enforced": self.supported and self.mode != "none",
            "structured_output_mode": self.mode,
            "structured_output_schema_id": self.schema_id,
            "structured_output_schema_name": self.schema_name,
            "structured_output_schema_hash": self.schema_hash,
            "structured_output_quarantined": quarantined,
        }


_VALID_SCHEMA_DELTA_TYPES = (
    "value_mutation",
    "structural_add",
    "structural_remove",
    "rule_change",
)

_VALID_RISK_LEVELS = ("low", "medium", "high")


MUTATION_TRANSACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_delta_type",
        "confidence_score",
        "risk_level",
        "required_recompile",
        "mutation_summary",
    ],
    "properties": {
        "schema_delta_type": {
            "type": "string",
            "enum": list(_VALID_SCHEMA_DELTA_TYPES),
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "risk_level": {
            "type": "string",
            "enum": list(_VALID_RISK_LEVELS),
        },
        "required_recompile": {"type": "boolean"},
        "mutation_summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
        },
    },
}


def mutation_transaction_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        schema_id="xace.mutation_transaction.v1",
        name="xace_mutation_transaction_v1",
        schema=MUTATION_TRANSACTION_SCHEMA,
        description=(
            "Final XACE mutation transaction envelope. Operations are copied "
            "from the approved draft by PIL and must not be emitted here."
        ),
        strict=True,
    )


def structured_output_plan_for(
    provider: str,
    contract: StructuredOutputContract | None,
    *,
    descriptor_supports_structured_output: bool,
) -> StructuredOutputPlan:
    if contract is None:
        return StructuredOutputPlan.none()

    provider_key = provider.lower().strip()
    mode = STRUCTURED_OUTPUT_PROVIDER_MODES.get(provider_key)
    supported = bool(mode and descriptor_supports_structured_output)
    if not supported:
        mode = "repair_quarantine"

    return StructuredOutputPlan(
        requested=True,
        supported=supported,
        mode=mode,
        schema_id=contract.schema_id,
        schema_name=contract.name,
        schema_hash=contract.schema_hash,
    )


def openai_response_format(contract: StructuredOutputContract) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": contract.name,
            "strict": contract.strict,
            "schema": contract.schema,
        },
    }


def anthropic_tool_config(contract: StructuredOutputContract) -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": contract.name,
                "description": contract.description or contract.schema_id,
                "input_schema": contract.schema,
            }
        ],
        "tool_choice": {"type": "tool", "name": contract.name},
    }


def google_generation_config(contract: StructuredOutputContract) -> dict[str, Any]:
    return {
        "responseMimeType": "application/json",
        "responseSchema": contract.schema,
    }


def repair_quarantine_prompt(contract: StructuredOutputContract) -> str:
    schema_json = json.dumps(contract.schema, sort_keys=True, separators=(",", ":"))
    return (
        "=== XACE STRUCTURED OUTPUT REPAIR/QUARANTINE MODE ===\n"
        f"Schema ID: {contract.schema_id}\n"
        f"Schema Name: {contract.name}\n"
        "The selected provider cannot enforce a native structured-output "
        "contract for this call. Return only one JSON object matching this "
        "schema exactly; unsupported, malformed, fenced, or extra-key output "
        "is quarantined before mutation commit.\n"
        f"JSON Schema: {schema_json}\n"
        "=== END STRUCTURED OUTPUT CONTRACT ==="
    )


def validate_structured_output_text(
    text: str,
    contract: StructuredOutputContract,
) -> list[str]:
    raw = _strip_code_fences(text.strip())
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON for {contract.schema_id}: {exc}"]

    return _validate_value(parsed, contract.schema, path="$")


def _strip_code_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("```")
    ).strip()


def _validate_value(value: Any, schema: dict[str, Any], *, path: str) -> list[str]:
    if "oneOf" in schema:
        return [f"{path}: unsupported oneOf constraint in strict schema"]

    any_of = schema.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list) or not any_of:
            return [f"{path}: anyOf must contain at least one schema"]
        branch_errors = [
            _validate_value(value, branch, path=path)
            if isinstance(branch, dict)
            else [f"{path}: anyOf branch is not an object schema"]
            for branch in any_of
        ]
        if not any(not errors for errors in branch_errors):
            reasons = "; ".join(
                errors[0] if errors else "unknown branch failure"
                for errors in branch_errors
            )
            return [f"{path}: value does not match anyOf ({reasons})"]

    if "const" in schema and not _json_values_equal(value, schema["const"]):
        return [f"{path}: value does not match const"]

    expected_type = schema.get("type")
    errors: list[str] = []

    if expected_type == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object, got {type(value).__name__}"]
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
        if schema.get("additionalProperties") is False:
            allowed = set((schema.get("properties") or {}).keys())
            for key in sorted(set(value.keys()) - allowed):
                errors.append(f"{path}: additional key {key!r} is not allowed")
        properties = schema.get("properties") or {}
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                errors.extend(_validate_value(value[key], child_schema, path=f"{path}.{key}"))
        return errors

    if expected_type == "string":
        if not isinstance(value, str):
            return [f"{path}: expected string, got {type(value).__name__}"]
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path}: value {value!r} is outside enum")
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path}: string shorter than minLength")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: string longer than maxLength")
        if "pattern" in schema:
            try:
                matches = re.search(str(schema["pattern"]), value) is not None
            except re.error as exc:
                errors.append(f"{path}: invalid schema pattern: {exc}")
            else:
                if not matches:
                    errors.append(f"{path}: string does not match pattern")
        return errors

    if expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{path}: expected integer, got {type(value).__name__}"]
        if "minimum" in schema and value < int(schema["minimum"]):
            errors.append(f"{path}: value below minimum")
        if "maximum" in schema and value > int(schema["maximum"]):
            errors.append(f"{path}: value above maximum")
        return errors

    if expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{path}: expected number, got {type(value).__name__}"]
        if "minimum" in schema and float(value) < float(schema["minimum"]):
            errors.append(f"{path}: value below minimum")
        if "maximum" in schema and float(value) > float(schema["maximum"]):
            errors.append(f"{path}: value above maximum")
        return errors

    if expected_type == "boolean":
        if not isinstance(value, bool):
            return [f"{path}: expected boolean, got {type(value).__name__}"]
        return errors

    if expected_type == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array, got {type(value).__name__}"]
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path}: array shorter than minItems")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: array longer than maxItems")
        if schema.get("uniqueItems") is True:
            encoded_items = [
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(encoded_items) != len(set(encoded_items)):
                errors.append(f"{path}: array items are not unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                errors.extend(_validate_value(item, item_schema, path=f"{path}[{idx}]"))
        return errors

    return errors


def _json_values_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""

    return json.dumps(
        left, sort_keys=True, separators=(",", ":")
    ) == json.dumps(right, sort_keys=True, separators=(",", ":"))

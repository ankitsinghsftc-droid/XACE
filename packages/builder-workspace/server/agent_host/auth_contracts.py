"""Optional provider-neutral, operator-only authentication control contract."""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Protocol

AUTH_STATUS_SCHEMA = "xace.agent_auth_status.v1"


class AgentLoginFlow(str, Enum):
    BROWSER = "browser"
    DEVICE_CODE = "device_code"


@dataclass(frozen=True)
class AgentAuthSnapshot:
    provider_id: str
    state: str = "unknown"
    login_state: str = "idle"
    revision: int = 0
    account: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    recovery_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AUTH_STATUS_SCHEMA, **asdict(self),
            "credential_owner": "provider", "persistent": False,
            "entitlement": "provider_enforced_not_inferred_from_plan",
            "billing_source": "provider_account",
        }


class AgentAuthenticationControl(Protocol):
    """Optional adapter extension; never a model-callable tool."""

    def snapshot(self) -> dict[str, Any]: ...
    def refresh(self) -> dict[str, Any]: ...
    def start_login(self, flow: str) -> dict[str, Any]: ...
    def cancel_login(self) -> dict[str, Any]: ...
    def logout(self) -> dict[str, Any]: ...
    def poll(self) -> dict[str, Any]: ...
    def close(self) -> None: ...

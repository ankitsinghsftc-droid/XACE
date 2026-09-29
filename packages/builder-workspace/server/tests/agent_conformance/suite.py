"""Provider-neutral AgentAdapter conformance runner.

Providers supply deterministic scenarios; this module owns every assertion.
Adding a provider therefore requires a fixture, not a fork of the certification
logic. Unsupported optional capabilities are evidence, not certification
failures.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from agent_host.context_capsule import ContextRetrievalSource
from agent_host.contracts import (
    AgentAdapter,
    AgentCapabilities,
    AgentEvent,
    AgentEventType,
    AgentProviderStatus,
    AgentSessionHandle,
    AgentStartRequest,
    AgentTurnRequest,
    JsonValue,
    ToolTransport,
)
from agent_host.event_stream import AgentEventStreamManager
from agent_host.mcp_server import XaceMcpToolBridge, XaceMcpToolContext
from agent_host.proposal_ingress import AgentProposalIngressGate
from agent_host.registry import AgentAdapterRegistry
from agent_host.security_policy import AgentSecurityPolicyEnforcer
from agent_host.tool_surface import (
    READ_ONLY_XACE_TOOL_NAMES,
    XaceToolSurface,
    default_xace_tool_specs,
    proposal_xace_tool_spec,
)


AGENT_CONFORMANCE_REPORT_SCHEMA = "xace.agent_adapter_conformance.v1"
PASS = "pass"
FAIL = "fail"
UNSUPPORTED = "unsupported"
REQUIRED_METHODS = (
    "detect",
    "list_capabilities",
    "start_session",
    "resume_session",
    "run_turn",
    "cancel_turn",
)
TERMINAL_EVENTS = frozenset(
    {
        AgentEventType.TURN_COMPLETED,
        AgentEventType.TURN_CANCELLED,
        AgentEventType.ERROR,
    }
)
OPTIONAL_CAPABILITIES = (
    (
        "supports_thread_fork",
        "fork_session",
        "Provider does not implement thread branching; this is optional for certification.",
    ),
    (
        "supports_compaction",
        "compact_session",
        "Provider does not implement provider-native compaction; this is optional.",
    ),
    (
        "supports_model_discovery",
        "",
        "Provider does not expose provider-native model discovery; this is optional.",
    ),
    (
        "supports_account_state",
        "",
        "Provider does not expose provider-native account state; this is optional.",
    ),
    (
        "supports_progressive_retrieval",
        "",
        "Provider does not advertise progressive XACE retrieval; this is optional.",
    ),
)


def _empty_observation() -> Mapping[str, Any]:
    return {}


@dataclass
class AdapterScenario:
    adapter: AgentAdapter
    start_request: AgentStartRequest
    current_cgs: Mapping[str, Any]
    proposal_session: Any | None = None
    observe: Callable[[], Mapping[str, Any]] = _empty_observation

    def turn_request(self, prompt: str = "Run the conformance turn.") -> AgentTurnRequest:
        return AgentTurnRequest(
            handle=AgentSessionHandle(
                xace_session_id=self.start_request.xace_session_id,
                provider_id=self.adapter.provider_id,
                provider_session_id="unstarted",
                base_cgs_hash=self.start_request.base_cgs_hash,
            ),
            user_prompt=prompt,
            base_cgs_hash=self.start_request.base_cgs_hash,
            allowed_tools=self.start_request.allowed_tools,
            metadata=self.start_request.metadata,
        )


class AdapterConformanceFixture(Protocol):
    provider_id: str
    display_name: str
    production: bool

    def create_scenario(self, name: str, root: Path) -> AdapterScenario:
        """Create an isolated deterministic adapter scenario."""


@dataclass(frozen=True)
class ConformanceCheck:
    check_id: str
    status: str
    required: bool
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "required": self.required,
            "detail": self.detail,
            "evidence": _json_object(self.evidence),
        }


@dataclass(frozen=True)
class AdapterConformanceReport:
    provider_id: str
    display_name: str
    production: bool
    certified: bool
    checks: tuple[ConformanceCheck, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": AGENT_CONFORMANCE_REPORT_SCHEMA,
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "production": self.production,
            "certified": self.certified,
            "checks": [check.to_dict() for check in self.checks],
            "required_failures": [
                check.check_id
                for check in self.checks
                if check.required and check.status != PASS
            ],
            "unsupported_optional_capabilities": [
                {
                    "capability": check.check_id.removeprefix("optional."),
                    "reason": check.detail,
                }
                for check in self.checks
                if not check.required and check.status == UNSUPPORTED
            ],
        }


async def certify_fixtures(
    fixtures: Sequence[AdapterConformanceFixture],
    root: Path,
) -> tuple[AdapterConformanceReport, ...]:
    reports = []
    for fixture in fixtures:
        fixture_root = root / fixture.provider_id
        fixture_root.mkdir(parents=True, exist_ok=True)
        reports.append(await certify_fixture(fixture, fixture_root))
    return tuple(reports)


async def certify_fixture(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> AdapterConformanceReport:
    checks: list[ConformanceCheck] = []
    required_checks = (
        ("contract_surface", _check_contract_surface),
        ("detection", _check_detection),
        ("safe_capabilities", _check_capabilities),
        ("session_lifecycle", _check_session_lifecycle),
        ("event_ordering", _check_event_ordering),
        ("mcp_tool_permissions", _check_tool_permissions),
        ("proposal_ingress", _check_proposal_ingress),
        ("cancellation", _check_cancellation),
        ("failure_recovery", _check_failure_recovery),
    )
    for check_id, check_fn in required_checks:
        checks.append(await _run_required_check(check_id, check_fn, fixture, root))

    capability_snapshot = _capability_snapshot(checks)
    checks.extend(
        _optional_capability_checks(
            fixture=fixture,
            capabilities=capability_snapshot,
            lifecycle=_check_evidence(checks, "session_lifecycle"),
            detection=_check_evidence(checks, "detection"),
            tool_permissions=_check_evidence(checks, "mcp_tool_permissions"),
        )
    )
    certified = all(check.status == PASS for check in checks if check.required)
    return AdapterConformanceReport(
        provider_id=fixture.provider_id,
        display_name=fixture.display_name,
        production=fixture.production,
        certified=certified,
        checks=tuple(checks),
    )


async def _run_required_check(
    check_id: str,
    check_fn: Callable[[AdapterConformanceFixture, Path], Any],
    fixture: AdapterConformanceFixture,
    root: Path,
) -> ConformanceCheck:
    try:
        evidence = await check_fn(fixture, root / check_id)
        return ConformanceCheck(
            check_id=check_id,
            status=PASS,
            required=True,
            detail="Required conformance check passed.",
            evidence=_json_object(evidence),
        )
    except Exception as exc:
        return ConformanceCheck(
            check_id=check_id,
            status=FAIL,
            required=True,
            detail=f"{type(exc).__name__}: {exc}",
        )


async def _check_contract_surface(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("normal", root)
    adapter = scenario.adapter
    _require(adapter.provider_id == fixture.provider_id, "fixture/provider id mismatch")
    for method_name in REQUIRED_METHODS:
        _require(callable(getattr(adapter, method_name, None)), f"missing {method_name}()")
    return {"provider_id": adapter.provider_id, "methods": list(REQUIRED_METHODS)}


async def _check_detection(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("normal", root)
    try:
        status = await scenario.adapter.detect()
        _require(isinstance(status, AgentProviderStatus), "detect() returned an invalid status")
        _require(status.provider_id == fixture.provider_id, "detection provider id mismatch")
        _require(bool(status.display_name.strip()), "detection display name is empty")
        _require(status.installed, "deterministic certification adapter is not installed")
        _require(status.available, "deterministic certification adapter is unavailable")
        _require(status.capabilities.security_policy.builder_safe, "unsafe detected capabilities")
        return {
            "status": status.to_dict(),
            "capabilities": status.capabilities.to_dict(),
        }
    finally:
        _close_adapter(scenario.adapter)


async def _check_capabilities(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("normal", root)
    try:
        capabilities = await scenario.adapter.list_capabilities()
        _require(isinstance(capabilities, AgentCapabilities), "invalid capabilities object")
        _require(capabilities.supports_streaming_events, "streaming events are required")
        _require(capabilities.supports_thread_resume, "thread resume is required")
        _require(capabilities.supports_cancellation, "cancellation is required")
        _require(capabilities.supports_mcp_tools, "MCP/XACE tool transport is required")
        _require(
            ToolTransport.MCP in capabilities.supported_tool_transports,
            "MCP is missing from supported transports",
        )
        policy = _security_policy()
        policy.validate_capabilities(capabilities)
        names = [spec.name for spec in capabilities.xace_tools]
        _require(len(names) == len(set(names)), "capability tool names are duplicated")
        return {"capabilities": capabilities.to_dict(), "tool_names": sorted(names)}
    finally:
        _close_adapter(scenario.adapter)


async def _check_session_lifecycle(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("lifecycle", root)
    adapter = scenario.adapter
    evidence: dict[str, Any] = {}
    try:
        capabilities = await adapter.list_capabilities()
        handle = await adapter.start_session(scenario.start_request)
        _validate_handle(handle, fixture, scenario.start_request)
        resumed = await adapter.resume_session(handle)
        _validate_handle(resumed, fixture, scenario.start_request)
        _require(
            resumed.provider_session_id == handle.provider_session_id,
            "resume changed the provider session identity",
        )
        evidence.update(
            {
                "started": True,
                "resumed": True,
                "provider_session_id": resumed.provider_session_id,
            }
        )
        active_handle = resumed
        if capabilities.supports_thread_fork:
            fork_method = getattr(adapter, "fork_session", None)
            _require(callable(fork_method), "fork capability has no fork_session method")
            active_handle = await fork_method(
                resumed,
                xace_session_id=f"{resumed.xace_session_id}-fork",
                base_cgs_hash=resumed.base_cgs_hash,
                latest_cgs_hash=resumed.latest_cgs_hash,
                branch_name="conformance",
                ephemeral=True,
            )
            _require(
                active_handle.provider_session_id != resumed.provider_session_id,
                "fork did not create a distinct provider session",
            )
            evidence["forked"] = True
        if capabilities.supports_compaction:
            compact_method = getattr(adapter, "compact_session", None)
            _require(callable(compact_method), "compaction capability has no method")
            compaction = await compact_method(active_handle)
            _require(bool(getattr(compaction, "accepted", False)), "compaction was not accepted")
            evidence["compacted"] = True
        evidence.update(_json_object(scenario.observe()))
        return evidence
    finally:
        _close_adapter(adapter)


async def _check_event_ordering(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("normal", root)
    adapter = scenario.adapter
    try:
        handle = await adapter.start_session(scenario.start_request)
        events = await _collect_events(
            adapter,
            AgentTurnRequest(
                handle=handle,
                user_prompt="Run the deterministic conformance turn.",
                base_cgs_hash=scenario.start_request.base_cgs_hash,
                allowed_tools=scenario.start_request.allowed_tools,
                metadata=scenario.start_request.metadata,
            ),
        )
        _validate_event_stream(events, handle, scenario.start_request.allowed_tools)
        return {
            "event_types": [event.event_type.value for event in events],
            "event_count": len(events),
            **_json_object(scenario.observe()),
        }
    finally:
        _close_adapter(adapter)


async def _check_tool_permissions(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("normal", root)
    try:
        capabilities = await scenario.adapter.list_capabilities()
        allowed = tuple(spec.name for spec in capabilities.xace_tools if spec.read_only)
        surface = XaceToolSurface(
            ContextRetrievalSource(
                cgs=scenario.current_cgs,
                cgs_hash=scenario.start_request.base_cgs_hash,
            )
        )
        bridge = XaceMcpToolBridge(
            surface,
            XaceMcpToolContext(
                xace_session_id=scenario.start_request.xace_session_id,
                provider_id=fixture.provider_id,
                cgs_hash=scenario.start_request.base_cgs_hash,
                allowed_tools=allowed,
            ),
        )
        listing = bridge.handle_mcp_message({"id": 1, "method": "tools/list", "params": {}})
        _require(isinstance(listing, Mapping), "MCP tools/list did not return a response")
        listed = listing.get("result", {}).get("tools", [])
        listed_names = sorted(
            str(item.get("name")) for item in listed if isinstance(item, Mapping)
        )
        _require(listed_names == sorted(allowed), "MCP tool listing differs from capability catalog")
        denied = bridge.handle_mcp_message(
            {
                "id": 2,
                "method": "tools/call",
                "params": {"name": "xace.shell", "arguments": {"command": "whoami"}},
            }
        )
        _require(isinstance(denied, Mapping), "denied MCP call returned no response")
        denied_result = denied.get("result", {})
        _require(bool(denied_result.get("isError")), "raw shell tool was not denied")
        return {"listed_tools": listed_names, "denied_tool": "xace.shell"}
    finally:
        _close_adapter(scenario.adapter)


async def _check_proposal_ingress(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("proposal", root)
    adapter = scenario.adapter
    session = scenario.proposal_session or SimpleNamespace(
        pending_txn=None,
        pending_prompt_preview=None,
        pending_prompt_result=None,
    )
    before = _canonical_json(scenario.current_cgs)
    try:
        handle = await adapter.start_session(scenario.start_request)
        events = await _collect_events(
            adapter,
            AgentTurnRequest(
                handle=handle,
                user_prompt="Submit a typed preview-only proposal.",
                base_cgs_hash=scenario.start_request.base_cgs_hash,
                allowed_tools=scenario.start_request.allowed_tools,
                metadata=scenario.start_request.metadata,
            ),
        )
        proposal_events = [
            event for event in events if event.event_type is AgentEventType.PROPOSAL
        ]
        if proposal_events:
            proposal = proposal_events[0].data.get("proposal")
            _require(isinstance(proposal, Mapping), "proposal event is missing a proposal")
            ingress = AgentProposalIngressGate(
                clock=lambda: 1.0,
                token_factory=lambda: "apt-conformance",
            ).ingest(
                proposal,
                current_cgs=scenario.current_cgs,
                current_cgs_hash=scenario.start_request.base_cgs_hash,
                xace_session_id=scenario.start_request.xace_session_id,
                provider_id=fixture.provider_id,
                session=session,
            )
            _require(ingress.accepted and ingress.preview_created, "proposal preview was rejected")
        _require(getattr(session, "pending_txn", None) is not None, "no pending transaction")
        result = getattr(session, "pending_prompt_result", None)
        _require(isinstance(result, Mapping), "no pending proposal result")
        _require(result.get("approval_required") is True, "proposal bypassed approval")
        _require(result.get("auto_committed") is False, "proposal was auto-committed")
        _require(_canonical_json(scenario.current_cgs) == before, "proposal mutated the CGS")
        return {
            "preview_created": True,
            "project_mutated": False,
            "event_types": [event.event_type.value for event in events],
            **_json_object(scenario.observe()),
        }
    finally:
        _close_adapter(adapter)


async def _check_cancellation(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("cancel", root)
    adapter = scenario.adapter
    events: list[AgentEvent] = []
    first_event = asyncio.Event()
    release = asyncio.Event()
    task: asyncio.Task[Any] | None = None
    try:
        handle = await adapter.start_session(scenario.start_request)

        async def consume() -> None:
            async for event in adapter.run_turn(
                AgentTurnRequest(
                    handle=handle,
                    user_prompt="Begin cancellable conformance work.",
                    base_cgs_hash=scenario.start_request.base_cgs_hash,
                    allowed_tools=scenario.start_request.allowed_tools,
                    metadata=scenario.start_request.metadata,
                )
            ):
                events.append(event)
                if not first_event.is_set():
                    first_event.set()
                    await release.wait()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(first_event.wait(), timeout=2.0)
        await adapter.cancel_turn(handle)
        release.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.25)
        except (asyncio.TimeoutError, Exception):
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        observation = _json_object(scenario.observe())
        cancelled_event = any(
            event.event_type is AgentEventType.TURN_CANCELLED for event in events
        )
        _require(
            cancelled_event or bool(observation.get("cancel_observed")),
            "adapter exposed no cancellation evidence",
        )
        _require(not observation.get("project_mutated", False), "cancellation mutated project")
        return {
            "cancelled_event": cancelled_event,
            "events_before_stop": [event.event_type.value for event in events],
            **observation,
        }
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
        _close_adapter(adapter)


async def _check_failure_recovery(
    fixture: AdapterConformanceFixture,
    root: Path,
) -> Mapping[str, Any]:
    scenario = fixture.create_scenario("failure", root)
    messages: list[Mapping[str, Any]] = []

    async def send(message: Mapping[str, Any]) -> None:
        messages.append(copy.deepcopy(dict(message)))

    manager = AgentEventStreamManager(
        AgentAdapterRegistry([scenario.adapter]),
    )
    try:
        result = await manager.start_turn(
            session_id=scenario.start_request.xace_session_id,
            provider_id=fixture.provider_id,
            user_prompt="Reject unsafe conformance metadata.",
            cgs_hash=scenario.start_request.base_cgs_hash,
            send_fn=send,
            allowed_tools=scenario.start_request.allowed_tools,
            metadata={"api_key": "credential-fixture-must-not-reach-adapter"},
        )
        _require(not result.accepted, "unsafe failure scenario was accepted")
        _require(result.code == "AGENT_TURN_START_FAILED", "unexpected failure code")
        denial_observation = _json_object(scenario.observe())
        request_methods = list(denial_observation.get("request_methods", []))
        _require(
            "thread/start" not in request_methods,
            "provider session started after denial",
        )
        recovered = await manager.start_turn(
            session_id=scenario.start_request.xace_session_id,
            provider_id=fixture.provider_id,
            user_prompt="Run a safe turn after the rejected request.",
            cgs_hash=scenario.start_request.base_cgs_hash,
            send_fn=send,
            project_id=scenario.start_request.project_id,
            context_capsule_path=scenario.start_request.context_capsule_path,
            allowed_tools=scenario.start_request.allowed_tools,
            metadata=scenario.start_request.metadata,
            current_cgs=scenario.current_cgs,
        )
        _require(recovered.accepted, "adapter did not recover after a rejected request")
        await manager.wait_for_turn(scenario.start_request.xace_session_id)
        status = manager.status(
            session_id=scenario.start_request.xace_session_id,
            provider_id=fixture.provider_id,
        )
        _require(
            status.get("state") == "completed",
            "safe recovery turn did not complete",
        )
        observation = _json_object(scenario.observe())
        return {
            "code": result.code,
            "message_count": len(messages),
            "provider_session_started_after_denial": False,
            "recovered": True,
            "recovery_state": status.get("state"),
            **observation,
        }
    finally:
        _close_adapter(scenario.adapter)


def _optional_capability_checks(
    *,
    fixture: AdapterConformanceFixture,
    capabilities: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    detection: Mapping[str, Any],
    tool_permissions: Mapping[str, Any],
) -> list[ConformanceCheck]:
    checks = []
    for capability, method_name, unsupported_reason in OPTIONAL_CAPABILITIES:
        supported = capabilities.get(capability) is True
        if not supported:
            checks.append(
                ConformanceCheck(
                    check_id=f"optional.{capability}",
                    status=UNSUPPORTED,
                    required=False,
                    detail=unsupported_reason,
                    evidence={"reported": False},
                )
            )
            continue
        if method_name == "fork_session":
            proven = lifecycle.get("forked") is True
        elif method_name == "compact_session":
            proven = lifecycle.get("compacted") is True
        elif capability == "supports_model_discovery":
            status = detection.get("status", {})
            metadata = status.get("metadata", {}) if isinstance(status, Mapping) else {}
            proven = isinstance(metadata.get("models"), list) and bool(metadata["models"])
        elif capability == "supports_account_state":
            status = detection.get("status", {})
            metadata = status.get("metadata", {}) if isinstance(status, Mapping) else {}
            proven = isinstance(metadata.get("account"), Mapping)
        elif capability == "supports_progressive_retrieval":
            listed_tools = tool_permissions.get("listed_tools", [])
            proven = "xace.retrieve_context" in listed_tools
        else:
            proven = False
        checks.append(
            ConformanceCheck(
                check_id=f"optional.{capability}",
                status=PASS if proven else FAIL,
                required=False,
                detail=(
                    "Advertised optional capability is available."
                    if proven
                    else "Adapter advertised the optional capability but did not prove it."
                ),
                evidence={"reported": True, "provider_id": fixture.provider_id},
            )
        )
    return checks


async def _collect_events(
    adapter: AgentAdapter,
    request: AgentTurnRequest,
) -> list[AgentEvent]:
    async def consume() -> list[AgentEvent]:
        return [event async for event in adapter.run_turn(request)]

    return await asyncio.wait_for(consume(), timeout=3.0)


def _validate_event_stream(
    events: Sequence[AgentEvent],
    handle: AgentSessionHandle,
    allowed_tools: Sequence[str],
) -> None:
    _require(bool(events), "adapter emitted no events")
    sequences = [event.sequence for event in events]
    _require(sequences == sorted(sequences), "event sequence regressed")
    _require(len(sequences) == len(set(sequences)), "event sequence is duplicated")
    terminals = [index for index, event in enumerate(events) if event.event_type in TERMINAL_EVENTS]
    _require(len(terminals) == 1, "event stream must contain exactly one terminal event")
    _require(terminals[0] == len(events) - 1, "events were emitted after the terminal event")
    _require(
        events[0].event_type in {AgentEventType.SESSION_STARTED, AgentEventType.TURN_STARTED},
        "event stream did not begin with lifecycle state",
    )
    policy = _security_policy()
    for event in events:
        policy.validate_agent_event(
            event,
            session_id=handle.xace_session_id,
            provider_id=handle.provider_id,
            enabled_tools=allowed_tools or None,
        )


def _validate_handle(
    handle: AgentSessionHandle,
    fixture: AdapterConformanceFixture,
    request: AgentStartRequest,
) -> None:
    _require(isinstance(handle, AgentSessionHandle), "invalid session handle")
    _require(handle.provider_id == fixture.provider_id, "handle provider id mismatch")
    _require(handle.xace_session_id == request.xace_session_id, "handle XACE session mismatch")
    _require(handle.base_cgs_hash == request.base_cgs_hash, "handle CGS hash mismatch")
    _require(bool(handle.provider_session_id.strip()), "provider session id is empty")


def _security_policy() -> AgentSecurityPolicyEnforcer:
    return AgentSecurityPolicyEnforcer(
        tool_specs=default_xace_tool_specs() + (proposal_xace_tool_spec(),)
    )


def _capability_snapshot(checks: Sequence[ConformanceCheck]) -> Mapping[str, Any]:
    for check_id in ("safe_capabilities", "detection"):
        evidence = _check_evidence(checks, check_id)
        capabilities = evidence.get("capabilities")
        if isinstance(capabilities, Mapping):
            return capabilities
        status = evidence.get("status")
        if isinstance(status, Mapping) and isinstance(status.get("capabilities"), Mapping):
            return status["capabilities"]
    return {}


def _check_evidence(
    checks: Sequence[ConformanceCheck],
    check_id: str,
) -> Mapping[str, Any]:
    return next((check.evidence for check in checks if check.check_id == check_id), {})


def _close_adapter(adapter: AgentAdapter) -> None:
    close = getattr(adapter, "close", None)
    if callable(close):
        close()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_object(value: Mapping[str, Any] | None) -> dict[str, JsonValue]:
    normalized = json.loads(json.dumps(dict(value or {}), sort_keys=True, default=str))
    return normalized if isinstance(normalized, dict) else {}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)

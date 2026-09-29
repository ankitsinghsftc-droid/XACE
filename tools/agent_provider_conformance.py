#!/usr/bin/env python3
"""Certify selected XACE AgentAdapter implementations.

The default gate is deterministic and makes no external provider calls. An
optional live Codex smoke probes installed-runtime detection, App Server auth,
and capability discovery without starting a turn or mutating a project.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "builder-workspace" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.codex_adapter import CodexAppServerAdapter  # noqa: E402
from tests.agent_conformance.fixtures import (  # noqa: E402
    CodexConformanceFixture,
    MockConformanceFixture,
)
from tests.agent_conformance.suite import (  # noqa: E402
    AGENT_CONFORMANCE_REPORT_SCHEMA,
    certify_fixtures,
)


REPORT_SCHEMA = "xace.agent_provider_conformance_gate.v1"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "target-codex-agent-conformance"
    / "agent_provider_conformance.json"
)
FIXTURES = {
    "mock": MockConformanceFixture,
    "codex": CodexConformanceFixture,
}
DEFERRED_PROVIDERS = (
    {
        "provider_id": "local_agent",
        "roadmap_task": "AG-016",
        "required": False,
        "status": "deferred",
        "reason": "Local Agent is reserved for a concrete local/offline product dependency.",
    },
    {
        "provider_id": "claude_agent",
        "roadmap_tasks": ["AG-017", "AG-018"],
        "required": False,
        "status": "deferred",
        "reason": "Claude execution is reserved and is not a Codex release dependency.",
    },
)


async def build_report(
    *,
    provider_names: Sequence[str] = ("mock", "codex"),
    work_root: Path,
    live_codex: bool = False,
    require_live_codex: bool = False,
) -> dict[str, Any]:
    selected = tuple(dict.fromkeys(provider_names))
    fixtures = tuple(FIXTURES[name]() for name in selected)
    reports = await certify_fixtures(fixtures, work_root / "fixtures")
    provider_reports = [report.to_dict() for report in reports]
    certified = [report.provider_id for report in reports if report.certified]
    disabled = [
        report.provider_id
        for report in reports
        if report.production and not report.certified
    ]
    live = await _live_codex_smoke() if live_codex or require_live_codex else None
    deterministic_ok = all(report.certified for report in reports)
    live_ok = not require_live_codex or bool(live and live["status"] == "pass")
    return {
        "schema": REPORT_SCHEMA,
        "conformance_schema": AGENT_CONFORMANCE_REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": deterministic_ok and live_ok,
        "selected_fixtures": list(selected),
        "certified_adapters": certified,
        "disabled_production_adapters": disabled,
        "providers": provider_reports,
        "deferred_providers": list(DEFERRED_PROVIDERS),
        "live_codex_smoke": live,
        "live_codex_required": require_live_codex,
    }


async def _live_codex_smoke() -> dict[str, Any]:
    adapter = CodexAppServerAdapter()
    try:
        status = await adapter.detect()
        passed = status.installed and status.available
        return {
            "status": "pass" if passed else "unavailable",
            "provider_id": status.provider_id,
            "installed": status.installed,
            "available": status.available,
            "auth_state": status.auth_state.value,
            "version": status.version,
            "model_count": len(status.metadata.get("models", [])),
            "warnings": list(status.warnings),
        }
    except Exception as exc:
        return {
            "status": "error",
            "provider_id": "codex_app_server",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        adapter.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        action="append",
        choices=tuple(FIXTURES),
        dest="providers",
        help="Fixture to certify; repeat to select multiple (default: Mock + Codex).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Machine-readable JSON report path.",
    )
    parser.add_argument(
        "--live-codex",
        action="store_true",
        help="Optionally probe an installed Codex App Server without gating success.",
    )
    parser.add_argument(
        "--require-live-codex",
        action="store_true",
        help="Require the optional installed Codex smoke to pass.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete report instead of a concise summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    providers = tuple(args.providers or FIXTURES)
    output = args.output.resolve()
    work_root = output.parent / "work"
    report = asyncio.run(
        build_report(
            provider_names=providers,
            work_root=work_root,
            live_codex=args.live_codex,
            require_live_codex=args.require_live_codex,
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "AgentAdapter conformance:",
            "PASS" if report["ok"] else "FAIL",
            f"({len(report['certified_adapters'])}/{len(report['providers'])} certified)",
        )
        for provider in report["providers"]:
            status = "CERTIFIED" if provider["certified"] else "DISABLED"
            failures = provider["required_failures"]
            suffix = f"; failures={','.join(failures)}" if failures else ""
            print(f"- {provider['provider_id']}: {status}{suffix}")
        print(f"Report: {output}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

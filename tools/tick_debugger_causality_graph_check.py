#!/usr/bin/env python3
"""Retained X10-049 proof for debugger causality graphs.

The check validates source wiring and executes the actual TypeScript
CausalityGraphEngine against a combat-damage trace:

prompt -> mutation -> system -> event/RNG/feedback/network packet -> state change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUILDER_ROOT = ROOT / "packages" / "builder-workspace"
CAUSALITY_ENGINE = BUILDER_ROOT / "src" / "preview" / "causality_graph.ts"
TICK_DEBUGGER = BUILDER_ROOT / "src" / "preview" / "tick_debugger.ts"
MESSAGE_TYPES = BUILDER_ROOT / "src" / "api" / "message_types.ts"
BUILDER_UI_CONTRACT = BUILDER_ROOT / "tools" / "builder_ui_contract_test.mjs"

REPORT_SCHEMA = "xace.tick_debugger_causality_graph_check_report.v1"
EXPECTED_CAUSE_KINDS = [
    "prompt",
    "mutation",
    "system",
    "event",
    "rng_call",
    "feedback",
    "network_packet",
]
EXPECTED_TRACE_ID = "x10-049-combat-damage"
EXPECTED_STATE_CHANGE_NODE = "state.enemy.health"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def marker_check(path: Path, markers: list[str]) -> dict[str, Any]:
    text = read(path)
    missing = [marker for marker in markers if marker not in text]
    return {
        "name": f"markers:{path.relative_to(ROOT)}",
        "ok": not missing,
        "missing": missing,
        "sha256": sha256(path),
    }


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def tsc_command() -> list[str]:
    windows_tsc = BUILDER_ROOT / "node_modules" / ".bin" / "tsc.cmd"
    posix_tsc = BUILDER_ROOT / "node_modules" / ".bin" / "tsc"
    if windows_tsc.exists():
        return [str(windows_tsc)]
    if posix_tsc.exists():
        return [str(posix_tsc)]
    return ["npx.cmd" if os.name == "nt" else "npx", "tsc"]


def compile_engine(artifact_dir: Path) -> tuple[dict[str, Any], Path | None]:
    compiled_dir = artifact_dir / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    command = tsc_command() + [
        "src/preview/causality_graph.ts",
        "--target",
        "ES2020",
        "--module",
        "ES2020",
        "--moduleResolution",
        "Bundler",
        "--strict",
        "--skipLibCheck",
        "--outDir",
        str(compiled_dir),
    ]
    result = run(command, BUILDER_ROOT)
    candidates = [
        compiled_dir / "causality_graph.js",
        compiled_dir / "preview" / "causality_graph.js",
        compiled_dir / "src" / "preview" / "causality_graph.js",
    ]
    compiled_file = next((candidate for candidate in candidates if candidate.exists()), None)
    return (
        {
            "name": "compile:causality_graph.ts",
            "ok": result.returncode == 0 and compiled_file is not None,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "compiled_file": str(compiled_file.relative_to(ROOT)) if compiled_file else "",
        },
        compiled_file,
    )


def combat_damage_script() -> str:
    return r"""
import { pathToFileURL } from 'node:url';
import { writeFileSync } from 'node:fs';

const modulePath = process.argv[2];
const outputPath = process.argv[3];
const mod = await import(pathToFileURL(modulePath).href);

const expectedCauseKinds = ['prompt', 'mutation', 'system', 'event', 'rng_call', 'feedback', 'network_packet'];
const trace = {
  type: 'runtime_causality_trace',
  trace_id: 'x10-049-combat-damage',
  tick: 64,
  summary: 'Combat damage state change traced from prompt and live runtime causes.',
  state_change_node_id: 'state.enemy.health',
  nodes: [
    {
      id: 'prompt.pc049.damage-rule',
      kind: 'prompt',
      tick: 0,
      label: 'Prompt pc049',
      detail: 'Make sword attacks deal 25 deterministic damage.',
      fields: { prompt_id: 'pc049', prompt: 'make sword attacks deal 25 damage' },
    },
    {
      id: 'mutation.damage-rule',
      kind: 'mutation',
      tick: 1,
      label: 'Typed CGS mutation',
      detail: 'Registered CombatDamageSystem and Health damage operation.',
      fields: { transaction_id: 'txn-x10-049', operation: 'ADD_REGISTERED_SYSTEM' },
    },
    {
      id: 'packet.peer1.attack',
      kind: 'network_packet',
      tick: 63,
      label: 'Authoritative input packet',
      detail: 'peer 1 attack action targeted enemy 7.',
      fields: { peer_id: 1, sequence: 208, action: 'Attack', target_entity: 7 },
    },
    {
      id: 'feedback.hit-confirmed',
      kind: 'feedback',
      tick: 64,
      label: 'Engine feedback',
      detail: 'Hit volume confirmed sword overlap.',
      fields: { feedback_type: 'CollisionConfirmed', entity_id: 7 },
    },
    {
      id: 'system.CombatDamageSystem',
      kind: 'system',
      tick: 64,
      label: 'CombatDamageSystem',
      detail: 'Consumed attack input and feedback, rolled deterministic crit stream, emitted damage event.',
      fields: { system_id: 'CombatDamageSystem', phase: 'combat' },
    },
    {
      id: 'rng.crit-roll',
      kind: 'rng_call',
      tick: 64,
      label: 'Deterministic RNG call',
      detail: 'Crit stream roll returned no critical hit.',
      fields: { system_id: 'CombatDamageSystem', stream_id: 'combat.crit', seed: '0xC0FFEE', stream_position: 12, value: 17 },
    },
    {
      id: 'event.combat.damage',
      kind: 'event',
      tick: 64,
      label: 'combat.damage',
      detail: 'Damage event applied 25 Health damage to enemy 7.',
      fields: { event_type: 'combat.damage', entity_id: 7, amount: 25 },
    },
    {
      id: 'state.enemy.health',
      kind: 'state_change',
      tick: 64,
      label: 'Enemy Health',
      detail: 'Health changed 100 -> 75.',
      fields: { entity_id: 7, component: 'Health', before: 100, after: 75 },
    },
  ],
  edges: [
    { from: 'prompt.pc049.damage-rule', to: 'mutation.damage-rule', relation: 'authored' },
    { from: 'mutation.damage-rule', to: 'system.CombatDamageSystem', relation: 'registered_system' },
    { from: 'packet.peer1.attack', to: 'system.CombatDamageSystem', relation: 'consumed_input' },
    { from: 'feedback.hit-confirmed', to: 'system.CombatDamageSystem', relation: 'consumed_feedback' },
    { from: 'system.CombatDamageSystem', to: 'rng.crit-roll', relation: 'requested_rng' },
    { from: 'system.CombatDamageSystem', to: 'event.combat.damage', relation: 'emitted_event' },
    { from: 'rng.crit-roll', to: 'event.combat.damage', relation: 'affected_event' },
    { from: 'event.combat.damage', to: 'state.enemy.health', relation: 'caused_state_change' },
    { from: 'system.CombatDamageSystem', to: 'state.enemy.health', relation: 'wrote_component' },
  ],
};

const engine = new mod.CausalityGraphEngine();
const report = engine.ingestTrace(trace);
const nodeKinds = new Set(report.causeChain.map((node) => node.kind));
const edgeRelations = new Set(report.causeEdges.map((edge) => edge.relation));
const requiredKindsPresent = expectedCauseKinds.every((kind) => report.coverage[kind] === true && nodeKinds.has(kind));
const requiredRelationsPresent = [
  'authored',
  'registered_system',
  'consumed_input',
  'consumed_feedback',
  'requested_rng',
  'emitted_event',
  'affected_event',
  'caused_state_change',
  'wrote_component',
].every((relation) => edgeRelations.has(relation));
const orderedKinds = report.causeChain.map((node) => node.kind);
const state = report.stateChange;
const combatDamageEvent = report.causeChain.find((node) => node.id === 'event.combat.damage');
const output = {
  trace_id: report.traceId,
  complete: report.complete,
  summary: mod.summarizeCausalityReport(report),
  state_change_node_id: state?.id ?? null,
  state_change_component: state?.fields?.component ?? null,
  state_change_before: state?.fields?.before ?? null,
  state_change_after: state?.fields?.after ?? null,
  combat_damage_event_type: combatDamageEvent?.fields?.event_type ?? null,
  coverage: report.coverage,
  missingCauseKinds: report.missingCauseKinds,
  diagnostics: report.diagnostics,
  cause_node_count: report.causeChain.length,
  cause_edge_count: report.causeEdges.length,
  orderedKinds,
  requiredKindsPresent,
  requiredRelationsPresent,
  ok:
    report.complete === true &&
    report.traceId === 'x10-049-combat-damage' &&
    state?.id === 'state.enemy.health' &&
    state?.fields?.component === 'Health' &&
    state?.fields?.before === '100' &&
    state?.fields?.after === '75' &&
    combatDamageEvent?.fields?.event_type === 'combat.damage' &&
    requiredKindsPresent &&
    requiredRelationsPresent &&
    report.missingCauseKinds.length === 0 &&
    report.diagnostics.length === 0,
};
writeFileSync(outputPath, JSON.stringify(output, null, 2));
if (!output.ok) {
  console.error(JSON.stringify(output, null, 2));
  process.exit(1);
}
"""


def run_combat_damage_proof(compiled_file: Path, artifact_dir: Path) -> dict[str, Any]:
    script_path = artifact_dir / "combat_damage_causality_test.mjs"
    output_path = artifact_dir / "combat_damage_causality.json"
    (compiled_file.parent / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    script_path.write_text(combat_damage_script(), encoding="utf-8")
    result = run(["node", str(script_path), str(compiled_file), str(output_path)], ROOT)
    payload: dict[str, Any] = {}
    if output_path.exists():
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    return {
        "name": "combat_damage_end_to_end",
        "ok": result.returncode == 0 and bool(payload.get("ok")),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "payload": payload,
    }


def build_report(artifact_dir: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        marker_check(
            CAUSALITY_ENGINE,
            [
                "CAUSALITY_NODE_KIND_ORDER",
                "REQUIRED_STATE_CHANGE_CAUSE_KINDS",
                "CausalityGraphEngine",
                "normalizeRuntimeCausalityTrace",
                "reportStateChangeCause",
                "summarizeCausalityReport",
                "ancestorNodeIds",
                "topoSortReachable",
                "hasCycle",
                "prompt",
                "mutation",
                "system",
                "event",
                "rng_call",
                "feedback",
                "network_packet",
                "state_change",
            ],
        ),
        marker_check(
            TICK_DEBUGGER,
            [
                "Causality graph",
                "runtime_causality_trace",
                "CausalityGraphEngine",
                "renderCausalityGraph",
                "summarizeCausalityReport",
            ],
        ),
        marker_check(
            MESSAGE_TYPES,
            [
                "RuntimeCausalityTraceMessage",
                "RuntimeCausalityNodeKind",
                "RuntimeCausalityNode",
                "RuntimeCausalityEdge",
                "runtime_causality_trace",
                "isRuntimeCausalityTrace",
            ],
        ),
        marker_check(
            BUILDER_UI_CONTRACT,
            [
                "Causality graph",
                "runtime_causality_trace",
                "CausalityGraphEngine",
                "RuntimeCausalityTraceMessage",
            ],
        ),
    ]
    compile_check, compiled_file = compile_engine(artifact_dir)
    checks.append(compile_check)
    combat_check = (
        run_combat_damage_proof(compiled_file, artifact_dir)
        if compiled_file
        else {
            "name": "combat_damage_end_to_end",
            "ok": False,
            "stderr": "causality graph engine did not compile",
        }
    )
    checks.append(combat_check)
    payload = combat_check.get("payload", {})
    complete = (
        all(check.get("ok") for check in checks)
        and payload.get("trace_id") == EXPECTED_TRACE_ID
        and payload.get("state_change_node_id") == EXPECTED_STATE_CHANGE_NODE
        and payload.get("requiredKindsPresent") is True
        and payload.get("requiredRelationsPresent") is True
    )
    return {
        "schema": REPORT_SCHEMA,
        "task": "X10-049",
        "x10_049_complete": complete,
        "expected_cause_kinds": EXPECTED_CAUSE_KINDS,
        "expected_trace_id": EXPECTED_TRACE_ID,
        "expected_state_change_node": EXPECTED_STATE_CHANGE_NODE,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="target-codex-task49-causality/report.json")
    parser.add_argument("--artifact-dir", default="target-codex-task49-causality/artifacts")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output_path = ROOT / args.output
    artifact_dir = ROOT / args.artifact_dir
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    report = build_report(artifact_dir)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = "PASS" if report["x10_049_complete"] else "FAIL"
        print(f"{status}: wrote {output_path}")
    return 0 if report["x10_049_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

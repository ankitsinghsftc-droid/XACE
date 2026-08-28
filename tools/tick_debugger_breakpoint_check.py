#!/usr/bin/env python3
"""Retained X10-048 proof for debugger conditional breakpoints.

The check validates source wiring and executes the actual TypeScript
ConditionalBreakpointEngine against a synthetic debugger trace. Each accepted
breakpoint source must produce exactly one first hit at its expected tick.
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
CONDITIONAL_ENGINE = BUILDER_ROOT / "src" / "preview" / "conditional_breakpoints.ts"
TICK_DEBUGGER = BUILDER_ROOT / "src" / "preview" / "tick_debugger.ts"
MESSAGE_TYPES = BUILDER_ROOT / "src" / "api" / "message_types.ts"
BUILDER_UI_CONTRACT = BUILDER_ROOT / "tools" / "builder_ui_contract_test.mjs"

REPORT_SCHEMA = "xace.tick_debugger_breakpoint_check_report.v1"
EXPECTED_TICKS = {
    "entity_state": 7,
    "component_value": 11,
    "event_type": 13,
    "mutation_type": 17,
    "system_id": 19,
    "rng_call": 23,
    "hash_mismatch": 29,
    "network_desync": 31,
}


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
        "src/preview/conditional_breakpoints.ts",
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
        compiled_dir / "conditional_breakpoints.js",
        compiled_dir / "preview" / "conditional_breakpoints.js",
        compiled_dir / "src" / "preview" / "conditional_breakpoints.js",
    ]
    compiled_file = next((candidate for candidate in candidates if candidate.exists()), None)
    return (
        {
            "name": "compile:conditional_breakpoints.ts",
            "ok": result.returncode == 0 and compiled_file is not None,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "compiled_file": str(compiled_file.relative_to(ROOT)) if compiled_file else "",
        },
        compiled_file,
    )


def exact_tick_script() -> str:
    return r"""
import { pathToFileURL } from 'node:url';
import { writeFileSync } from 'node:fs';

const modulePath = process.argv[2];
const outputPath = process.argv[3];
const mod = await import(pathToFileURL(modulePath).href);

const expected = {
  entity_state: 7,
  component_value: 11,
  event_type: 13,
  mutation_type: 17,
  system_id: 19,
  rng_call: 23,
  hash_mismatch: 29,
  network_desync: 31,
};

const breakpoints = [
  { id: 'exact-entity-state', label: 'Entity state exact', kind: 'entity_state', enabled: true, operator: 'equals', field: 'state', value: 'destroyed', description: 'proof' },
  { id: 'exact-component-value', label: 'Component value exact', kind: 'component_value', enabled: true, operator: 'equals', field: 'component', value: 'Health', description: 'proof' },
  { id: 'exact-event-type', label: 'Event type exact', kind: 'event_type', enabled: true, operator: 'equals', field: 'event_type', value: 'combat.damage', description: 'proof' },
  { id: 'exact-mutation-type', label: 'Mutation type exact', kind: 'mutation_type', enabled: true, operator: 'equals', field: 'mutation_type', value: 'destroy', description: 'proof' },
  { id: 'exact-system-id', label: 'System ID exact', kind: 'system_id', enabled: true, operator: 'equals', field: 'system_id', value: 'CombatSystem', description: 'proof' },
  { id: 'exact-rng-call', label: 'RNG call exact', kind: 'rng_call', enabled: true, operator: 'equals', field: 'system_id', value: 'LootSystem', description: 'proof' },
  { id: 'exact-hash-mismatch', label: 'Hash mismatch exact', kind: 'hash_mismatch', enabled: true, operator: 'exists', field: 'actual_hash', description: 'proof' },
  { id: 'exact-network-desync', label: 'Network desync exact', kind: 'network_desync', enabled: true, operator: 'equals', field: 'peer_id', value: '2', description: 'proof' },
];

const engine = new mod.ConditionalBreakpointEngine(breakpoints);
const hits = [];
const evaluate = (candidates) => {
  hits.push(...engine.evaluateCandidates(candidates));
};

const baseSnapshot = {
  tick: 6,
  source: 'engine_tick',
  entities: [
    { id: 1, actor_id: 'enemy', components: { Health: '100' } },
    { id: 2, actor_id: 'player', components: { Health: '100' } },
  ],
  spawnedIds: [],
  destroyedIds: [],
  events: [],
};
const destroyedSnapshot = {
  tick: 7,
  source: 'engine_tick',
  entities: [
    { id: 2, actor_id: 'player', components: { Health: '100' } },
  ],
  spawnedIds: [],
  destroyedIds: [1],
  events: [],
};
evaluate(mod.snapshotBreakpointCandidates(destroyedSnapshot, baseSnapshot));

const componentBefore = {
  tick: 10,
  source: 'runtime_control_snapshot',
  entities: [{ id: 2, actor_id: 'player', components: { Health: '100', Mana: '5' } }],
  spawnedIds: [],
  destroyedIds: [],
  events: [],
};
const componentAfter = {
  tick: 11,
  source: 'runtime_control_snapshot',
  entities: [{ id: 2, actor_id: 'player', components: { Health: '37', Mana: '5' } }],
  spawnedIds: [],
  destroyedIds: [],
  events: [],
};
evaluate(mod.snapshotBreakpointCandidates(componentAfter, componentBefore));

evaluate(mod.eventBreakpointCandidates(13, [{ event_type: 'combat.damage', entity_id: 2, data: { amount: 63 } }]));
evaluate([mod.mutationBreakpointCandidate({ tick: 17, kind: 'destroy', entityId: 'enemy-1', component: '', detail: 'removed by gameplay rule' })]);
evaluate(mod.runtimeDebugTraceBreakpointCandidates({ type: 'runtime_debug_trace', tick: 19, systems: [{ system_id: 'CombatSystem', phase: 'update' }] }));
evaluate(mod.runtimeDebugTraceBreakpointCandidates({ type: 'runtime_debug_trace', tick: 23, rng_calls: [{ system_id: 'LootSystem', stream_id: 'loot', stream_position: 42, call_index: 0, value: 17 }] }));
evaluate([mod.hashMismatchBreakpointCandidate({ tick: 29, expectedHash: 'a'.repeat(64), actualHash: 'b'.repeat(64), source: 'engine_tick.world_hash' })]);
evaluate(mod.runtimeDebugTraceBreakpointCandidates({ type: 'runtime_debug_trace', tick: 31, network_desyncs: [{ peer_id: 2, expected_hash: 'c'.repeat(64), actual_hash: 'd'.repeat(64), reason: 'authoritative hash divergence' }] }));

const actual = {};
for (const hit of hits) {
  if (actual[hit.kind] === undefined) actual[hit.kind] = hit.tick;
}
const mismatches = Object.entries(expected)
  .filter(([kind, tick]) => actual[kind] !== tick)
  .map(([kind, tick]) => ({ kind, expected: tick, actual: actual[kind] ?? null }));
const duplicateKinds = Object.keys(expected).filter((kind) => hits.filter((hit) => hit.kind === kind).length !== 1);
const report = {
  expected,
  actual,
  hit_count: hits.length,
  hits: hits.map((hit) => ({ kind: hit.kind, tick: hit.tick, label: hit.label, detail: hit.detail, source: hit.source })),
  mismatches,
  duplicateKinds,
  ok: mismatches.length === 0 && duplicateKinds.length === 0,
};
writeFileSync(outputPath, JSON.stringify(report, null, 2));
if (!report.ok) {
  console.error(JSON.stringify(report, null, 2));
  process.exit(1);
}
"""


def run_exact_tick_proof(compiled_file: Path, artifact_dir: Path) -> dict[str, Any]:
    script_path = artifact_dir / "conditional_breakpoint_exact_tick_test.mjs"
    output_path = artifact_dir / "exact_tick_hits.json"
    (compiled_file.parent / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    script_path.write_text(exact_tick_script(), encoding="utf-8")
    result = run(["node", str(script_path), str(compiled_file), str(output_path)], ROOT)
    payload: dict[str, Any] = {}
    if output_path.exists():
      payload = json.loads(output_path.read_text(encoding="utf-8"))
    return {
        "name": "exact_tick_hits",
        "ok": result.returncode == 0 and bool(payload.get("ok")),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "payload": payload,
    }


def build_report(artifact_dir: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(
        marker_check(
            CONDITIONAL_ENGINE,
            [
                "BREAKPOINT_KIND_ORDER",
                "entity_state",
                "component_value",
                "event_type",
                "mutation_type",
                "system_id",
                "rng_call",
                "hash_mismatch",
                "network_desync",
                "ConditionalBreakpointEngine",
                "setBreakpointEnabled",
                "snapshotBreakpointCandidates",
                "eventBreakpointCandidates",
                "mutationBreakpointCandidate",
                "hashMismatchBreakpointCandidate",
                "runtimeDebugTraceBreakpointCandidates",
            ],
        )
    )
    checks.append(
        marker_check(
            TICK_DEBUGGER,
            [
                "Conditional breakpoints",
                "data-breakpoint-id",
                "runtime_debug_trace",
                "runtimeDebugTraceBreakpointCandidates",
                "snapshotBreakpointCandidates",
                "eventBreakpointCandidates",
                "mutationBreakpointCandidate",
                "hashMismatchBreakpointCandidate",
                "applyBreakpointHits",
                "makeRuntimeControl('pause'",
            ],
        )
    )
    checks.append(
        marker_check(
            MESSAGE_TYPES,
            [
                "RuntimeDebugTraceMessage",
                "RuntimeDebugSystemTrace",
                "RuntimeDebugRngCallTrace",
                "RuntimeDebugNetworkDesyncTrace",
                "isRuntimeDebugTrace",
                "runtime_debug_trace",
            ],
        )
    )
    checks.append(
        marker_check(
            BUILDER_UI_CONTRACT,
            [
                "Conditional breakpoints",
                "runtime_debug_trace",
                "data-breakpoint-id",
            ],
        )
    )
    compile_check, compiled_file = compile_engine(artifact_dir)
    checks.append(compile_check)
    exact_tick_check = (
        run_exact_tick_proof(compiled_file, artifact_dir)
        if compiled_file
        else {
            "name": "exact_tick_hits",
            "ok": False,
            "stderr": "conditional breakpoint engine did not compile",
        }
    )
    checks.append(exact_tick_check)

    actual_ticks = exact_tick_check.get("payload", {}).get("actual", {})
    complete = all(check.get("ok") for check in checks) and actual_ticks == EXPECTED_TICKS
    return {
        "schema": REPORT_SCHEMA,
        "task": "X10-048",
        "x10_048_complete": complete,
        "expected_ticks": EXPECTED_TICKS,
        "actual_ticks": actual_ticks,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="target-codex-task48-breakpoints/report.json")
    parser.add_argument("--artifact-dir", default="target-codex-task48-breakpoints/artifacts")
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
        status = "PASS" if report["x10_048_complete"] else "FAIL"
        print(f"{status}: wrote {output_path}")
    return 0 if report["x10_048_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

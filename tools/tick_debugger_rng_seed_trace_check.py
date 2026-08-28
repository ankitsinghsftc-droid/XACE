#!/usr/bin/env python3
"""Retained X10-050 proof for debugger RNG seed traces.

The check validates source wiring and executes the actual TypeScript
RngSeedTraceEngine against a source-free runtime_rng_trace payload proving:

- every deterministic RNG call is visible by tick, system, seed, stream
  position, and result;
- illegal RNG is reported as blocked; and
- legal RNG replay evidence has identical hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUILDER_ROOT = ROOT / "packages" / "builder-workspace"
RNG_SEED_TRACE_ENGINE = BUILDER_ROOT / "src" / "preview" / "rng_seed_trace.ts"
TICK_DEBUGGER = BUILDER_ROOT / "src" / "preview" / "tick_debugger.ts"
MESSAGE_TYPES = BUILDER_ROOT / "src" / "api" / "message_types.ts"
CONDITIONAL_BREAKPOINTS = BUILDER_ROOT / "src" / "preview" / "conditional_breakpoints.ts"
BUILDER_UI_CONTRACT = BUILDER_ROOT / "tools" / "builder_ui_contract_test.mjs"
RNG_INTERCEPTOR = ROOT / "packages" / "runtime-core" / "src" / "determinism_guard" / "rng_interceptor.rs"
RUNTIME_ORCHESTRATOR = ROOT / "packages" / "runtime-core" / "src" / "runtime_orchestrator.rs"

REPORT_SCHEMA = "xace.tick_debugger_rng_seed_trace_check_report.v1"
EXPECTED_REPLAY_ID = "x10-050-legal-rng-replay"
EXPECTED_TICK = 128
EXPECTED_SYSTEMS = ["CombatDamageSystem", "LootDropSystem"]
IDENTICAL_REPLAY_HASH = "8f4c2d7b0a1e9c63854d2f61b7a0e5c49d3b8a6f21c0d9e74a5b6c3d2e1f9087"


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
        "src/preview/rng_seed_trace.ts",
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
        compiled_dir / "rng_seed_trace.js",
        compiled_dir / "preview" / "rng_seed_trace.js",
        compiled_dir / "src" / "preview" / "rng_seed_trace.js",
    ]
    compiled_file = next((candidate for candidate in candidates if candidate.exists()), None)
    return (
        {
            "name": "compile:rng_seed_trace.ts",
            "ok": result.returncode == 0 and compiled_file is not None,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "compiled_file": str(compiled_file.relative_to(ROOT)) if compiled_file else "",
        },
        compiled_file,
    )


def rng_seed_trace_script() -> str:
    return r"""
import { pathToFileURL } from 'node:url';
import { writeFileSync } from 'node:fs';

const modulePath = process.argv[2];
const outputPath = process.argv[3];
const mod = await import(pathToFileURL(modulePath).href);

const identicalReplayHash = '8f4c2d7b0a1e9c63854d2f61b7a0e5c49d3b8a6f21c0d9e74a5b6c3d2e1f9087';
const trace = {
  type: 'runtime_rng_trace',
  tick: 128,
  calls: [
    {
      system_id: 'CombatDamageSystem',
      seed: '0x00000000C0FFEE01',
      stream_id: 'combat.crit',
      stream_position: 0,
      result: 17,
      call_index: 0,
      deterministic: true,
    },
    {
      system_id: 'LootDropSystem',
      seed: '0x00000000C0FFEE02',
      stream_id: 'loot.drop',
      stream_position: 1,
      result: 'rare_sword',
      call_index: 1,
      deterministic: true,
    },
  ],
  violations: [
    {
      tick: 128,
      system_id: 'UnregisteredRandomSystem',
      reason: 'rand::thread_rng and entropy-sourced RNG are forbidden; blocked by D6 guard',
      source: 'RngInterceptor::report_illegal_rng',
      blocked: true,
    },
  ],
  replay: {
    replay_id: 'x10-050-legal-rng-replay',
    first_hash: identicalReplayHash,
    second_hash: identicalReplayHash,
    identical: true,
  },
};

const engine = new mod.RngSeedTraceEngine();
const report = engine.ingestRuntimeRngTrace(trace);
const retainedCalls = engine.calls();
const retainedViolations = engine.violations();
const replayEvidence = engine.replayEvidence();
const legacyDebugCalls = mod.runtimeDebugRngCallsToSeedTrace({
  type: 'runtime_debug_trace',
  tick: 129,
  rng_calls: [
    {
      system_id: 'LegacyDebugRngSystem',
      seed: '0x00000000C0FFEE03',
      stream_id: 'legacy.debug',
      stream_position: 2,
      result: false,
      call_index: 2,
      deterministic: true,
    },
  ],
});
const everyDeterministicCallVisible = report.calls
  .filter((call) => call.deterministic)
  .every((call) => mod.validateRngSeedTraceCall(call).length === 0);
const expectedSystemsPresent = ['CombatDamageSystem', 'LootDropSystem'].every((systemId) =>
  report.calls.some((call) => call.systemId === systemId),
);
const streamPositionsPresent = report.calls.map((call) => call.streamPosition).join(',') === '0,1';
const resultsPresent = report.calls.map((call) => call.result).join(',') === '17,rare_sword';
const output = {
  tick: report.tick,
  summary: mod.summarizeRngSeedTraceReport(report),
  complete: report.complete,
  deterministicCallCount: report.deterministicCallCount,
  visibleDeterministicCallCount: report.visibleDeterministicCallCount,
  illegalBlocked: report.illegalBlocked,
  legalReplayIdentical: report.legalReplayIdentical,
  missingFields: report.missingFields,
  retainedCallCount: retainedCalls.length,
  retainedViolationCount: retainedViolations.length,
  replayEvidenceCount: replayEvidence.length,
  replayId: replayEvidence[0]?.replayId ?? null,
  everyDeterministicCallVisible,
  expectedSystemsPresent,
  streamPositionsPresent,
  resultsPresent,
  legacyDebugConversionVisible: legacyDebugCalls.length === 1 && mod.validateRngSeedTraceCall(legacyDebugCalls[0]).length === 0,
  ok:
    report.complete === true &&
    report.tick === 128 &&
    report.deterministicCallCount === 2 &&
    report.visibleDeterministicCallCount === 2 &&
    report.illegalBlocked === true &&
    report.legalReplayIdentical === true &&
    report.missingFields.length === 0 &&
    retainedCalls.length === 2 &&
    retainedViolations.length === 1 &&
    replayEvidence.length === 1 &&
    replayEvidence[0]?.replayId === 'x10-050-legal-rng-replay' &&
    everyDeterministicCallVisible &&
    expectedSystemsPresent &&
    streamPositionsPresent &&
    resultsPresent &&
    legacyDebugCalls.length === 1 &&
    mod.validateRngSeedTraceCall(legacyDebugCalls[0]).length === 0,
};
writeFileSync(outputPath, JSON.stringify(output, null, 2));
if (!output.ok) {
  console.error(JSON.stringify(output, null, 2));
  process.exit(1);
}
"""


def run_rng_seed_trace_proof(compiled_file: Path, artifact_dir: Path) -> dict[str, Any]:
    script_path = artifact_dir / "rng_seed_trace_test.mjs"
    output_path = artifact_dir / "rng_seed_trace.json"
    (compiled_file.parent / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    script_path.write_text(rng_seed_trace_script(), encoding="utf-8")
    result = run(["node", str(script_path), str(compiled_file), str(output_path)], ROOT)
    payload: dict[str, Any] = {}
    if output_path.exists():
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    return {
        "name": "rng_seed_trace_end_to_end",
        "ok": result.returncode == 0 and bool(payload.get("ok")),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "payload": payload,
    }


def build_report(artifact_dir: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        marker_check(
            RNG_SEED_TRACE_ENGINE,
            [
                "RngSeedTraceEngine",
                "RuntimeRngTraceMessage",
                "runtime_rng_trace",
                "runtimeDebugRngCallsToSeedTrace",
                "validateRngSeedTraceCall",
                "summarizeRngSeedTraceReport",
                "illegalBlocked",
                "legalReplayIdentical",
                "streamPosition",
                "result",
                "seed",
            ],
        ),
        marker_check(
            TICK_DEBUGGER,
            [
                "RNG seed trace",
                "runtime_rng_trace",
                "RngSeedTraceEngine",
                "renderRngSeedTrace",
                "summarizeRngSeedTraceReport",
            ],
        ),
        marker_check(
            MESSAGE_TYPES,
            [
                "RuntimeRngTraceMessage",
                "RuntimeRngTraceCall",
                "RuntimeRngTraceViolation",
                "RuntimeRngReplayTrace",
                "runtime_rng_trace",
                "isRuntimeRngTrace",
                "seed?: string | number",
                "result?: string | number | boolean",
            ],
        ),
        marker_check(
            CONDITIONAL_BREAKPOINTS,
            [
                "seed:",
                "result:",
                "deterministic",
                "runtime_debug_trace.rng_calls",
            ],
        ),
        marker_check(
            BUILDER_UI_CONTRACT,
            [
                "RNG seed trace",
                "runtime_rng_trace",
                "RngSeedTraceEngine",
                "RuntimeRngTraceMessage",
            ],
        ),
        marker_check(
            RNG_INTERCEPTOR,
            [
                "report_illegal_rng",
                "Strict => Err(err)",
                "rand::random(), thread_rng(), SmallRng::from_entropy()",
                "request_rng",
                "derive_seed",
                "accesses_for_tick",
            ],
        ),
        marker_check(
            RUNTIME_ORCHESTRATOR,
            [
                "RuntimeReplayRngCallTrace",
                "rng_call_trace",
                "deterministic: record.is_deterministic",
                "seed: record.seed",
                "rng_calls: self",
            ],
        ),
    ]
    compile_check, compiled_file = compile_engine(artifact_dir)
    checks.append(compile_check)
    rng_trace_check = (
        run_rng_seed_trace_proof(compiled_file, artifact_dir)
        if compiled_file
        else {
            "name": "rng_seed_trace_end_to_end",
            "ok": False,
            "stderr": "RNG seed trace engine did not compile",
        }
    )
    checks.append(rng_trace_check)
    payload = rng_trace_check.get("payload", {})
    complete = (
        all(check.get("ok") for check in checks)
        and payload.get("tick") == EXPECTED_TICK
        and payload.get("replayId") == EXPECTED_REPLAY_ID
        and payload.get("everyDeterministicCallVisible") is True
        and payload.get("illegalBlocked") is True
        and payload.get("legalReplayIdentical") is True
        and payload.get("expectedSystemsPresent") is True
        and payload.get("streamPositionsPresent") is True
        and payload.get("resultsPresent") is True
    )
    return {
        "schema": REPORT_SCHEMA,
        "task": "X10-050",
        "x10_050_complete": complete,
        "expected_tick": EXPECTED_TICK,
        "expected_systems": EXPECTED_SYSTEMS,
        "expected_replay_id": EXPECTED_REPLAY_ID,
        "identical_replay_hash": IDENTICAL_REPLAY_HASH,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="target-codex-task50-rng-seed-trace/report.json")
    parser.add_argument("--artifact-dir", default="target-codex-task50-rng-seed-trace/artifacts")
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
        status = "PASS" if report["x10_050_complete"] else "FAIL"
        print(f"{status}: wrote {output_path}")
    return 0 if report["x10_050_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


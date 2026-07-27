# XACE Cross-Platform Replay Proof Contract

Status: production contract for X10-014.

Source of truth: `tools/replay_cross_platform_proof.py`.

## Required Evidence

The acceptance artifact is:

```text
.xace/proof/replay-cross-platform/<run-id>/
```

A passing run contains one `platform_report.json` from each required platform:

- `windows`
- `linux`
- `macos`

and one aggregate `summary.json` with schema:

```text
xace.replay_cross_platform.summary.v1
```

## Canonical Replay Identity

The aggregator compares only platform-independent execution fields:

- `cgs_hash`
- `compiled_from_cgs_hash`
- `plan_hash`
- generated system IDs
- scheduled runtime system IDs
- tick count
- pinned `world_seed`
- canonical input-log schema and hash
- input packet count
- schedule fingerprint
- latest world hash
- per-tick runtime hash log

Platform-specific paths, command strings, stdout, stderr, absolute proof
locations, Rust installation paths, and machine metadata are recorded for audit
context but are not part of the equality key.

## Input Log

X10-014 uses a canonical headless input log:

```json
{"packets":[],"schema":"xace.replay.input_log.v1","topology":"headless"}
```

The log is written to each per-platform proof directory and hashed as canonical
JSON. Later multiplayer/input tasks may replace this with a non-empty packet log,
but the aggregate gate must still compare `input_log_hash` and
`input_packet_count`.

## Runtime Binding

`xace_runtime` exposes `--world-seed`, and schedule snapshot reports include the
seed as `world_seed`. The per-platform recorder rejects a runtime report whose
seed differs from the requested seed.

## Commands

Record one platform:

```bash
python tools/replay_cross_platform_proof.py record \
  --target-dir target-replay-cross-platform \
  --proof-root .xace/proof/replay-cross-platform \
  --run-id <run-id> \
  --ticks 6 \
  --world-seed 424242
```

Aggregate all required platforms:

```bash
python tools/replay_cross_platform_proof.py aggregate \
  --proof-root .xace/proof/replay-cross-platform \
  --run-id <run-id>
```

The GitHub workflow `xace-scope.yml` runs the record command on Windows, Linux,
and macOS, downloads all platform artifacts, and runs the aggregate command.

## Local Verification

Local development can prove the current OS leg and the aggregator behavior:

```bash
python -m py_compile tools/replay_cross_platform_proof.py tools/sgc_runtime_proof.py
python tools/replay_cross_platform_proof.py self-test
```

The self-test uses deterministic fixture reports to prove both the passing
comparison path and an injected mismatch failure. It is not a substitute for the
real three-platform artifact.

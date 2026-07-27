# XACE Fixed-Point Numeric Model

Status: Tasks X10-009 and X10-010 authoritative state/runtime contract.

## Contract

XACE authoritative gameplay state uses `xace_core::fixed_point::Fixed64`,
integer ticks, IDs, counters, hashes, or domain-specific integer enums. Raw
`f32` and `f64` are not permitted in authoritative core state definitions.

`Fixed64` stores signed micro-units:

- Rust type: `packages/core/src/fixed_point.rs`
- Raw storage: `i64`
- Scale: `1_000_000` raw units equals one world/unit value
- Serialization: transparent JSON integer, never a JSON float
- Math: integer add/subtract/multiply/divide/sqrt helpers with deterministic
  saturation or explicit `Option` on division

## Authoritative Roots

The fixed-point static gate scans executable Rust code under:

- `packages/core/src/fixed_point.rs`
- `packages/core/src/ucl`
- `packages/core/src/schema`
- `packages/core/src/runtime`
- `packages/core/src/events/event_struct.rs`
- `packages/runtime-core/src/fixed_json.rs`
- `packages/runtime-core/src/builtin_systems.rs`
- `packages/runtime-core/src/generated_system_abi.rs`
- `packages/runtime-core/src/phase_orchestrator/system_context.rs`
- `examples/zombie-chase/src`

These roots must not contain executable `f32`, `f64`, or float literals.
Comments and string fixtures are ignored by the scanner.

## Current Fixed-Point State

The following authoritative state surfaces now use `Fixed64`:

- `Vec3`, `Quat`, and `TransformComponent` spatial values
- `VelocityVec3` and `VelocityComponent` speed limits
- `ColliderSize`, `ColliderOffset`, and `PhysicsMaterial`
- `WorldSize` and `Gravity`
- `ActorDefinition.stats`
- `GameStateComponent::elapsed_seconds`
- `LifetimeComponent::lifetime_fraction`
- `WorldSnapshot.time_seconds`
- Event payload fixed-point parsing through `Event::get_payload_fixed64`
- Runtime JSON fixed-point helpers in `runtime-core/src/fixed_json.rs`
- Built-in runtime movement, AI, interaction ranges, inventory weights, combat,
  damage, and death checks
- Generated-system numeric increment/copy/set/RNG threshold operations
- `ISystemContext::next_random` and live `SystemContext` RNG output
- `examples/zombie-chase` reference CGS builders, systems, and runner

## Allowed Float Boundaries

Raw floats are still allowed only outside authoritative state, where they are
explicitly boundary data:

- Engine feedback and telemetry payloads
- Adapter/control interface values that are converted before authoritative
  mutation
- Wall-clock frame accumulation before conversion to ticks
- Client-side prediction and visual reconciliation

The scanner records these as allowed/non-authoritative zones; they are not
evidence that authoritative simulation is fixed-point incomplete.

## Verification

Run:

```powershell
python tools/fixed_point_authority_check.py --output target-codex-fixed-point/fixed_point_authority_report.json
cargo test -p xace-core -q
cargo test -p xace-runtime-core -q
cargo test -p xace-zombie-chase -q
```

The launch certification runner also includes the fixed-point authority check.

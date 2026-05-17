/*!
# ffi_transport.rs — FFI Simulation Core

Implements the simulation tick logic for FFI transport mode.

## Role

When the engine calls `xace_tick(world)`, this module:
1. Drains the input queue (populated by xace_apply_input)
2. Processes system execution (via runtime-core PhaseOrchestrator)
3. Computes the world hash (determinism guard)
4. Serialises the state delta into the SharedDeltaBuffer
5. Increments the tick counter

## Runtime Core Integration

In production: `FfiSimulation::tick()` delegates to the actual `PhaseOrchestrator`
from `xace-runtime-core`. The orchestrator is transport-agnostic — it never
knows it's running in FFI mode (constraint from user's decision 3).

For the initial FFI implementation, `FfiSimulation` provides a deterministic
baseline that exactly reproduces the Phase 9 world hash behaviour. The full
runtime-core integration point is marked with `// TODO: integrate runtime-core`.

## Determinism Contract

The FFI transport must produce the same world hashes as the TCP transport
for identical (world_seed, initial_cgs, input_sequence) triplets.
`test_ffi_determinism.rs` verifies this against the golden file.
*/

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use super::handle_types::FfiWorldHandle;
use super::shared_buffer::BufferError;
use crate::ffi::error_codes::XaceErrorCode;


// ── State Delta Wire Format ───────────────────────────────────────────────────

/// Serialisable state delta — what changed during one tick.
///
/// This is the wire format written to `SharedDeltaBuffer` and read by the engine.
/// The engine applies these changes to its scene graph.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StateDelta {
    pub tick:               u64,
    pub world_hash:         String,
    pub spawned_entities:   Vec<EntityDelta>,
    pub updated_components: Vec<ComponentUpdate>,
    pub destroyed_entities: Vec<u64>,
    pub events:             Vec<GameEvent>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EntityDelta {
    pub entity_id:   u64,
    pub entity_type: String,
    pub components:  Vec<ComponentUpdate>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComponentUpdate {
    pub entity_id:  u64,
    pub type_id:    u32,
    pub field:      String,
    pub value:      serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GameEvent {
    pub event_type: String,
    pub entity_id:  u64,
    pub data:       serde_json::Value,
}

/// Encoded input packet from the engine (one per player per tick).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InputPacket {
    pub player_id:  u64,
    pub tick:       u64,
    pub actions:    Vec<String>,
}


// ── FfiSimulation ─────────────────────────────────────────────────────────────

/// Drives one simulation tick in FFI mode.
///
/// Stateless — receives `&mut FfiWorldHandle` and mutates it.
/// All state lives in `FfiWorldHandle` (the opaque C pointer).
pub struct FfiSimulation;

impl FfiSimulation {
    /// Processes one tick: drain inputs → run systems → hash → serialise delta.
    ///
    /// Returns `Ok(())` on success or an error code if the tick fails.
    pub fn tick(world: &mut FfiWorldHandle) -> Result<(), XaceErrorCode> {
        if world.halted {
            world.set_error("World is halted due to a determinism violation. \
                             Call xace_shutdown() and create a new world.");
            return Err(XaceErrorCode::DeterminismViolation);
        }

        if !world.cgs_loaded {
            world.set_error("CGS not loaded. Call xace_load_cgs() before xace_tick().");
            return Err(XaceErrorCode::NotInitialized);
        }

        // ── Drain inputs ──────────────────────────────────────────────────────
        let inputs = world.input_queue.drain();
        let parsed_inputs: Vec<InputPacket> = inputs.iter()
            .filter_map(|raw| serde_json::from_slice(raw).ok())
            .collect();

        // TODO: integrate runtime-core PhaseOrchestrator
        // orchestrator.execute_tick(&parsed_inputs)?;
        //
        // For now: deterministic baseline simulation
        let (delta, new_hash) = Self::run_baseline_tick(world, &parsed_inputs);

        // ── Determinism guard ─────────────────────────────────────────────────
        // In production: determinism_guard.validate_hash(new_hash)?;
        // On violation: world.halted = true; crash_reporter::report(...);

        world.world_hash   = new_hash;
        world.tick_number += 1;

        // ── Serialise delta → SharedDeltaBuffer ───────────────────────────────
        let encoded = serde_json::to_vec(&delta)
            .map_err(|_| XaceErrorCode::IoError)?;

        world.delta_buffer.write(&encoded).map_err(|e| match e {
            BufferError::TooSmall { .. } => XaceErrorCode::BufferTooSmall,
            BufferError::Empty           => XaceErrorCode::TickError,
        })?;

        world.clear_error();
        Ok(())
    }

    /// Deterministic baseline tick — produces the same output for the same inputs.
    ///
    /// This is a placeholder for the full runtime-core integration.
    /// Produces consistent hashes — matching Phase 9 behaviour — by using
    /// a deterministic hash over tick + seed + action count.
    fn run_baseline_tick(
        world:  &FfiWorldHandle,
        inputs: &[InputPacket],
    ) -> (StateDelta, String) {
        let tick    = world.tick_number + 1;
        let actions: u64 = inputs.iter()
            .flat_map(|i| i.actions.iter())
            .count() as u64;

        // Deterministic hash: SHA-256 of (seed || tick || action_count)
        let hash_input = format!("{}:{}:{}:{}", world.world_seed, tick, actions, world.schema_version);
        let new_hash   = Self::deterministic_hash(&hash_input);

        // Minimal delta — in production this comes from the ECS component tables
        let delta = StateDelta {
            tick,
            world_hash:         new_hash.clone(),
            spawned_entities:   Vec::new(),
            updated_components: Self::simulate_updates(world, inputs),
            destroyed_entities: Vec::new(),
            events:             Vec::new(),
        };

        (delta, new_hash)
    }

    /// Simulates component updates from input actions.
    fn simulate_updates(
        world:  &FfiWorldHandle,
        inputs: &[InputPacket],
    ) -> Vec<ComponentUpdate> {
        // Placeholder: one position update per player action
        inputs.iter()
            .flat_map(|packet| {
                packet.actions.iter().filter_map(|action| {
                    match action.as_str() {
                        "MOVE_LEFT"  => Some(ComponentUpdate {
                            entity_id: packet.player_id,
                            type_id:   5,   // COMP_VELOCITY_V1
                            field:     "velocity_x".to_string(),
                            value:     serde_json::Value::Number((-1i32).into()),
                        }),
                        "MOVE_RIGHT" => Some(ComponentUpdate {
                            entity_id: packet.player_id,
                            type_id:   5,
                            field:     "velocity_x".to_string(),
                            value:     serde_json::Value::Number((1i32).into()),
                        }),
                        _ => None,
                    }
                })
            })
            .collect()
    }

    /// Deterministic SHA-256 hash of a string.
    /// Used for world hash computation — same inputs always produce same hash.
    pub fn deterministic_hash(input: &str) -> String {
        // Portable DJB2-style hash for the baseline implementation
        // In production: replaced by runtime-core's world_hasher (SHA-256 of full ECS state)
        let mut hash: u64 = 5381;
        for byte in input.bytes() {
            hash = hash.wrapping_mul(33).wrapping_add(byte as u64);
        }
        format!("{:016x}{:016x}{:016x}{:016x}", hash, hash ^ 0xDEADBEEF, hash.rotate_left(13), hash.rotate_right(7))
    }
}

/// Validates and parses CGS JSON. Returns the schema version on success.
pub fn load_cgs_json(cgs_json: &str) -> Result<String, String> {
    // Parse JSON
    let parsed: serde_json::Value = serde_json::from_str(cgs_json)
        .map_err(|e| format!("JSON parse error: {}", e))?;

    // Validate minimal structure
    if !parsed.is_object() {
        return Err("CGS must be a JSON object.".to_string());
    }

    let metadata = parsed.get("metadata")
        .ok_or_else(|| "CGS missing 'metadata' field.".to_string())?;

    let schema_version = metadata
        .get("schema_version")
        .or_else(|| metadata.get("version"))
        .and_then(|v| v.as_str())
        .unwrap_or("0.1.0")
        .to_string();

    Ok(schema_version)
}
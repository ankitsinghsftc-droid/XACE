//! # InputSystem
//!
//! Reads COMP_INPUT_V1 to identify player-controlled entities and generates
//! a deterministic velocity intent that simulates player movement.
//!
//! ## Phase 9 — Simulated Input
//! Real player input arrives from XaceInputCollector in Unity.
//! In Phase 9 (headless determinism test), input is simulated:
//! the player moves in a deterministic spiral based on the current tick.
//! This ensures 3 runs from the same seed produce identical hashes.
//!
//! ## Reads / Writes
//! Reads:  COMP_INPUT_V1 (6), COMP_TRANSFORM_V1 (1)
//! Writes: COMP_VELOCITY_V1 (5)
//!
//! ## Determinism
//! - Queries return entities sorted by EntityID ASC (D3, enforced by context)
//! - No wall-clock time access — uses current_tick() only (D7)
//! - Uses context.next_random() for any randomness (D6)
//! - Fixed spiral math: same tick → same velocity (D11)

use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;

use crate::cgs::component_ids;
use crate::cgs::{parse_input_controller_id, velocity_json};

/// Player speed in world units per tick at 60 Hz.
const PLAYER_SPEED: f32 = 5.0 / 60.0;

pub struct InputSystem;

impl ISystem for InputSystem {
    fn system_id(&self) -> &str {
        crate::cgs::SYSTEM_INPUT
    }

    fn declared_reads(&self) -> &[u32] {
        &[component_ids::INPUT, component_ids::TRANSFORM]
    }

    fn declared_writes(&self) -> &[u32] {
        &[component_ids::VELOCITY]
    }

    fn execute(&self, context: &mut dyn ISystemContext) -> Result<(), XaceError> {
        let tick = context.current_tick();

        // D3: query_entities returns EntityID ASC
        let input_entities = context.query_entities(&[component_ids::INPUT])?;

        for entity_id in input_entities {
            let input_json = match context.get_component(entity_id, component_ids::INPUT)? {
                Some(j) => j.to_owned(),
                None => continue,
            };

            // Only process HUMAN-controlled entities in Phase 9
            if !input_json.contains("\"HUMAN\"") {
                continue;
            }

            // Deterministic spiral input — same tick → same velocity (D7, D11)
            // Phase 9: no real Unity input yet. Player traces a slow outward spiral.
            let angle = tick as f32 * 0.05_f32;
            let radius = (tick as f32 * 0.01_f32).min(10.0_f32);
            let vx = angle.cos() * PLAYER_SPEED * radius.max(1.0_f32).min(10.0_f32) / 10.0_f32;
            let vz = angle.sin() * PLAYER_SPEED * radius.max(1.0_f32).min(10.0_f32) / 10.0_f32;

            let new_velocity = velocity_json(vx, 0.0, vz);

            // D4: submitted via Mutation Gate — applied after phase completion
            context.submit_mutation(entity_id, component_ids::VELOCITY, new_velocity)?;
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_id_matches_cgs() {
        assert_eq!(InputSystem.system_id(), crate::cgs::SYSTEM_INPUT);
    }

    #[test]
    fn declares_correct_reads_and_writes() {
        let s = InputSystem;
        assert!(s.declared_reads().contains(&component_ids::INPUT));
        assert!(s.declared_reads().contains(&component_ids::TRANSFORM));
        assert!(s.declared_writes().contains(&component_ids::VELOCITY));
        // Must NOT write INPUT or TRANSFORM (not declared)
        assert!(!s.declared_writes().contains(&component_ids::INPUT));
    }
}

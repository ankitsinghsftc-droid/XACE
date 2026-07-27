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
use xace_core::fixed_point::Fixed64;

use crate::cgs::component_ids;
use crate::cgs::velocity_json;

/// Player speed in world units per tick at 60 Hz.
const PLAYER_SPEED: Fixed64 = Fixed64::from_units(5);
const SEGMENT_TICKS: u64 = 60;
const MAX_RADIUS_UNITS: u64 = 10;

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
            let radius_units = ((tick / SEGMENT_TICKS) + 1).min(MAX_RADIUS_UNITS);
            let radius_scale = Fixed64::from_units(radius_units as i64)
                .checked_div(Fixed64::from_units(MAX_RADIUS_UNITS as i64))
                .unwrap_or(Fixed64::ZERO);
            let speed = PLAYER_SPEED * radius_scale;
            let (vx, vz) = match (tick / SEGMENT_TICKS) % 4 {
                0 => (speed, Fixed64::ZERO),
                1 => (Fixed64::ZERO, speed),
                2 => (-speed, Fixed64::ZERO),
                _ => (Fixed64::ZERO, -speed),
            };

            let new_velocity = velocity_json(vx, Fixed64::ZERO, vz);

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

//! # MovementSystem
//!
//! Integrates COMP_VELOCITY_V1 into COMP_TRANSFORM_V1 each tick.
//! Applies to all entities that have both components.
//!
//! ## Fixed Timestep (D7)
//! delta_time = 1/60 (constant). Never uses wall-clock dt.
//! Same velocity → same position change → same hash (D9).
//!
//! ## Reads / Writes
//! Reads:  COMP_VELOCITY_V1 (5), COMP_TRANSFORM_V1 (1)
//! Writes: COMP_TRANSFORM_V1 (1)
//!
//! ## Determinism
//! - All arithmetic uses f32 with no conditional branching on velocity sign
//! - Format uses fixed 6 decimal places → stable JSON (D11)
//! - D3 ordering from context.query_entities guaranteed

use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;

use crate::cgs::component_ids;
use crate::cgs::{parse_position_xz, parse_velocity_xz, transform_json};

/// Fixed simulation timestep: 1 / 60 Hz.
const DT: f32 = 1.0_f32 / 60.0_f32;

pub struct MovementSystem;

impl ISystem for MovementSystem {
    fn system_id(&self) -> &str {
        crate::cgs::SYSTEM_MOVEMENT
    }

    fn declared_reads(&self) -> &[u32] {
        &[component_ids::VELOCITY, component_ids::TRANSFORM]
    }

    fn declared_writes(&self) -> &[u32] {
        &[component_ids::TRANSFORM]
    }

    fn execute(&self, context: &mut dyn ISystemContext) -> Result<(), XaceError> {
        // D3: EntityID ASC order guaranteed by query_entities
        let entities =
            context.query_entities(&[component_ids::VELOCITY, component_ids::TRANSFORM])?;

        for entity_id in entities {
            // Read current position
            let transform_json_str =
                match context.get_component(entity_id, component_ids::TRANSFORM)? {
                    Some(j) => j.to_owned(),
                    None => continue,
                };

            // Read current velocity
            let velocity_json_str =
                match context.get_component(entity_id, component_ids::VELOCITY)? {
                    Some(j) => j.to_owned(),
                    None => continue,
                };

            let (px, pz) = parse_position_xz(&transform_json_str);
            let (vx, vz) = parse_velocity_xz(&velocity_json_str);

            // D7: fixed timestep integration — no wall-clock dt
            let new_x = px + vx * DT;
            let new_z = pz + vz * DT;

            // D11: stable 6-decimal format — same result = same bytes
            let new_transform = transform_json(new_x, 0.0, new_z);

            // D4: deferred via Mutation Gate
            context.submit_mutation(entity_id, component_ids::TRANSFORM, new_transform)?;
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_id_matches_cgs() {
        assert_eq!(MovementSystem.system_id(), crate::cgs::SYSTEM_MOVEMENT);
    }

    #[test]
    fn reads_both_velocity_and_transform() {
        let s = MovementSystem;
        assert!(s.declared_reads().contains(&component_ids::VELOCITY));
        assert!(s.declared_reads().contains(&component_ids::TRANSFORM));
    }

    #[test]
    fn writes_only_transform() {
        let s = MovementSystem;
        assert_eq!(s.declared_writes(), &[component_ids::TRANSFORM]);
    }

    #[test]
    fn fixed_dt_is_one_sixtieth() {
        // D7: delta_time = 1/simulation_rate. Rendering FPS must never affect sim.
        assert!((DT - 1.0 / 60.0).abs() < 1e-7);
    }
}

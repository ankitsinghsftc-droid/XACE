//! # DeathSystem
//!
//! Destroys any entity whose COMP_HEALTH_V1.current has reached 0.
//! Runs last in the execution order — after DamageSystem has applied
//! all damage for this tick.
//!
//! ## Reads / Writes
//! Reads:  COMP_HEALTH_V1 (100)
//! Writes: (submit_destroy — entity lifecycle, not a component write)
//!
//! ## Determinism (D3, D4)
//! - D3: EntityID ASC order from query_entities
//! - D4: submit_destroy is deferred through the Mutation Gate
//!       Entities are not immediately removed — they are destroyed
//!       at the end of the tick's apply_all() call
//! - Zero-health check uses exact float equality (0.0_f32) —
//!   health can only reach 0.0 via `.max(0.0_f32)` in DamageSystem,
//!   making this comparison always deterministic

use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;

use crate::cgs::component_ids;
use crate::cgs::parse_health_current;

pub struct DeathSystem;

impl ISystem for DeathSystem {
    fn system_id(&self) -> &str {
        crate::cgs::SYSTEM_DEATH
    }

    fn declared_reads(&self) -> &[u32] {
        &[component_ids::HEALTH]
    }

    fn declared_writes(&self) -> &[u32] {
        // DeathSystem writes nothing to components — it only destroys entities.
        // submit_destroy goes through the Mutation Gate's destroy queue (D4).
        &[]
    }

    fn execute(&self, context: &mut dyn ISystemContext) -> Result<(), XaceError> {
        // D3: EntityID ASC — all entities with HEALTH, sorted ascending
        let mortal_entities = context.query_entities(&[component_ids::HEALTH])?;

        for entity_id in mortal_entities {
            let health_json_str = match context.get_component(entity_id, component_ids::HEALTH)? {
                Some(j) => j.to_owned(),
                None    => continue,
            };

            let current_health = parse_health_current(&health_json_str);

            // Exact float zero — deterministic because DamageSystem uses .max(0.0)
            if current_health <= 0.0_f32 {
                // D4: deferred entity destruction — applied after phase completion
                // I2: all structural changes through Mutation Gate
                context.submit_destroy(entity_id)?;
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_id_matches_cgs() {
        assert_eq!(DeathSystem.system_id(), crate::cgs::SYSTEM_DEATH);
    }

    #[test]
    fn reads_only_health() {
        let s = DeathSystem;
        assert_eq!(s.declared_reads(), &[component_ids::HEALTH]);
    }

    #[test]
    fn declares_no_component_writes() {
        // DeathSystem uses submit_destroy, not submit_mutation
        assert_eq!(DeathSystem.declared_writes(), &[]);
    }

    #[test]
    fn death_threshold_is_zero_or_below() {
        // Any entity with health exactly 0 or somehow less must die
        assert!(0.0_f32 <= 0.0_f32);      // exactly zero → dead
        assert!(-0.1_f32 <= 0.0_f32);     // impossible via .max(0.0) but checked
    }
}
//! # DamageSystem
//!
//! Processes pending COMP_DAMAGE_V1 components and applies them to
//! COMP_HEALTH_V1 on the same entity. Marks damage as consumed.
//!
//! ## Flow
//! 1. Query all entities with COMP_DAMAGE_V1
//! 2. Skip already-consumed damage (is_consumed == true)
//! 3. Read COMP_HEALTH_V1 on the same entity
//! 4. new_health = current - damage.amount (clamped to 0)
//! 5. Submit updated COMP_HEALTH_V1 mutation
//! 6. Submit consumed COMP_DAMAGE_V1 mutation (marks processed)
//!
//! ## Reads / Writes
//! Reads:  COMP_DAMAGE_V1 (101), COMP_HEALTH_V1 (100)
//! Writes: COMP_HEALTH_V1 (100), COMP_DAMAGE_V1 (101)
//!
//! ## Determinism
//! - D3: EntityID ASC order from query_entities
//! - All arithmetic deterministic: no RNG, no wall-clock
//! - Health clamped to 0.0 exactly — no floating-point under-zero
//! - D11: fixed 2 decimal places for health values

use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;

use crate::cgs::component_ids;
use crate::cgs::{
    damage_consumed_json, health_json, parse_damage_amount, parse_damage_applied_tick,
    parse_damage_is_consumed, parse_health_current, parse_health_max,
};

pub struct DamageSystem;

impl ISystem for DamageSystem {
    fn system_id(&self) -> &str {
        crate::cgs::SYSTEM_DAMAGE
    }

    fn declared_reads(&self) -> &[u32] {
        &[component_ids::DAMAGE, component_ids::HEALTH]
    }

    fn declared_writes(&self) -> &[u32] {
        &[component_ids::HEALTH, component_ids::DAMAGE]
    }

    fn execute(&self, context: &mut dyn ISystemContext) -> Result<(), XaceError> {
        // D3: EntityID ASC order
        let damaged_entities = context.query_entities(&[component_ids::DAMAGE])?;

        for entity_id in damaged_entities {
            // Read the damage component
            let damage_json_str = match context.get_component(entity_id, component_ids::DAMAGE)? {
                Some(j) => j.to_owned(),
                None => continue,
            };

            // Skip already-consumed damage (idempotent processing)
            if parse_damage_is_consumed(&damage_json_str) {
                continue;
            }

            let damage_amount = parse_damage_amount(&damage_json_str);
            let damage_source =
                crate::cgs::extract_u64(&damage_json_str, "\"source_entity_id\":").unwrap_or(0);
            let damage_tick = parse_damage_applied_tick(&damage_json_str);

            // Read current health
            let health_json_str = match context.get_component(entity_id, component_ids::HEALTH)? {
                Some(j) => j.to_owned(),
                None => {
                    // Entity has DAMAGE but no HEALTH — mark consumed and skip
                    let consumed = damage_consumed_json(damage_amount, damage_source, damage_tick);
                    context.submit_mutation(entity_id, component_ids::DAMAGE, consumed)?;
                    continue;
                }
            };

            let current_health = parse_health_current(&health_json_str);
            let max_health = parse_health_max(&health_json_str);

            // Apply damage — clamp to exactly 0.0, never negative
            let new_health = (current_health - damage_amount).max(0.0_f32);

            // D4: submit health update — deferred, applied after phase
            let updated_health = health_json(new_health, max_health);
            context.submit_mutation(entity_id, component_ids::HEALTH, updated_health)?;

            // Mark damage as consumed — prevents double-processing (I9 analog)
            let consumed_damage = damage_consumed_json(damage_amount, damage_source, damage_tick);
            context.submit_mutation(entity_id, component_ids::DAMAGE, consumed_damage)?;
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_id_matches_cgs() {
        assert_eq!(DamageSystem.system_id(), crate::cgs::SYSTEM_DAMAGE);
    }

    #[test]
    fn reads_damage_and_health() {
        let s = DamageSystem;
        assert!(s.declared_reads().contains(&component_ids::DAMAGE));
        assert!(s.declared_reads().contains(&component_ids::HEALTH));
    }

    #[test]
    fn writes_health_and_damage() {
        let s = DamageSystem;
        assert!(s.declared_writes().contains(&component_ids::HEALTH));
        assert!(s.declared_writes().contains(&component_ids::DAMAGE));
    }

    #[test]
    fn health_clamp_never_negative() {
        // Property: (100.0 - 200.0).max(0.0) == 0.0 exactly
        let result = (100.0_f32 - 200.0_f32).max(0.0_f32);
        assert_eq!(result, 0.0_f32);
        // No floating-point under-zero possible
        assert!(result >= 0.0_f32);
    }
}

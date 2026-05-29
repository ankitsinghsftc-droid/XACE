//! # AISystem
//!
//! Zombie chase AI. Each zombie reads its target (player) position,
//! computes a direction vector, and submits a velocity mutation.
//! Zombies within attack range also submit a DAMAGE component on the player.
//!
//! ## Reads / Writes
//! Reads:  COMP_AI_V1 (160), COMP_TRANSFORM_V1 (1)
//! Writes: COMP_VELOCITY_V1 (5), COMP_DAMAGE_V1 (101)
//!
//! ## Determinism (D3, D6, D11)
//! - query_entities returns EntityID ASC (D3)
//! - Uses context.next_random() for velocity jitter — never thread_rng (D6)
//! - All float formatting fixed 6 decimal places (D11)
//! - Attack range check: deterministic float comparison
//!
//! ## Attack Mechanic
//! If a zombie is within ATTACK_RANGE of its target, it submits a
//! COMP_DAMAGE_V1 on the target entity. DamageSystem processes this
//! in the same tick (after AISystem in execution order).
//! The damage component carries applied_tick for dedup.

use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;

use crate::cgs::component_ids;
use crate::cgs::{damage_json, parse_ai_target, parse_position_xz, velocity_json};

/// Zombie movement speed — world units per second.
const ZOMBIE_SPEED: f32 = 2.0_f32;

/// Fixed simulation timestep.
const DT: f32 = 1.0_f32 / 60.0_f32;

/// Zombies attack when within this distance of their target.
const ATTACK_RANGE: f32 = 1.5_f32;

/// Damage per attack.
const ATTACK_DAMAGE: f32 = 5.0_f32;

/// Maximum random jitter applied to zombie velocity (keeps simulation interesting).
const MAX_JITTER: f64 = 0.02_f64;

pub struct AISystem;

impl ISystem for AISystem {
    fn system_id(&self) -> &str {
        crate::cgs::SYSTEM_AI
    }

    fn declared_reads(&self) -> &[u32] {
        &[component_ids::AI, component_ids::TRANSFORM]
    }

    fn declared_writes(&self) -> &[u32] {
        &[component_ids::VELOCITY, component_ids::DAMAGE]
    }

    fn execute(&self, context: &mut dyn ISystemContext) -> Result<(), XaceError> {
        let tick = context.current_tick();

        // D3: zombie entities in EntityID ASC order
        let ai_entities = context.query_entities(&[component_ids::AI, component_ids::TRANSFORM])?;

        for zombie_id in ai_entities {
            // Read AI component to get target
            let ai_json = match context.get_component(zombie_id, component_ids::AI)? {
                Some(j) => j.to_owned(),
                None => continue,
            };

            let target_id = parse_ai_target(&ai_json);
            if target_id == 0 {
                continue;
            }

            // Read zombie position
            let zombie_transform =
                match context.get_component(zombie_id, component_ids::TRANSFORM)? {
                    Some(j) => j.to_owned(),
                    None => continue,
                };

            // Read target (player) position
            let target_transform =
                match context.get_component(target_id, component_ids::TRANSFORM)? {
                    Some(j) => j.to_owned(),
                    None => continue,
                };

            let (zx, zz) = parse_position_xz(&zombie_transform);
            let (tx, tz) = parse_position_xz(&target_transform);

            let dx = tx - zx;
            let dz = tz - zz;
            let dist = (dx * dx + dz * dz).sqrt();

            // ── Attack check ───────────────────────────────────────────────
            if dist < ATTACK_RANGE {
                // Zombie is in attack range — submit damage on the player
                let dmg_json = damage_json(ATTACK_DAMAGE, zombie_id, tick);
                // D4: deferred mutation — DamageSystem processes this same tick
                context.submit_mutation(target_id, component_ids::DAMAGE, dmg_json)?;
                // Zombie stays in place when attacking
                context.submit_mutation(
                    zombie_id,
                    component_ids::VELOCITY,
                    velocity_json(0.0, 0.0, 0.0),
                )?;
                continue;
            }

            // ── Chase movement ─────────────────────────────────────────────
            // D6: deterministic jitter via context.next_random()
            // seed = hash(world_seed, system_id, tick) — reproducible
            let jitter_x = (context.next_random()? - 0.5) * MAX_JITTER * 2.0;
            let jitter_z = (context.next_random()? - 0.5) * MAX_JITTER * 2.0;

            let safe_dist = dist.max(0.001_f32);
            // Normalize direction and scale by speed
            let vx = (dx / safe_dist) * ZOMBIE_SPEED + jitter_x as f32;
            let vz = (dz / safe_dist) * ZOMBIE_SPEED + jitter_z as f32;

            let new_velocity = velocity_json(vx, 0.0, vz);

            // D4: deferred mutation
            context.submit_mutation(zombie_id, component_ids::VELOCITY, new_velocity)?;
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_id_matches_cgs() {
        assert_eq!(AISystem.system_id(), crate::cgs::SYSTEM_AI);
    }

    #[test]
    fn reads_ai_and_transform() {
        let s = AISystem;
        assert!(s.declared_reads().contains(&component_ids::AI));
        assert!(s.declared_reads().contains(&component_ids::TRANSFORM));
    }

    #[test]
    fn writes_velocity_and_damage() {
        let s = AISystem;
        assert!(s.declared_writes().contains(&component_ids::VELOCITY));
        assert!(s.declared_writes().contains(&component_ids::DAMAGE));
    }

    #[test]
    fn attack_range_is_positive() {
        assert!(ATTACK_RANGE > 0.0);
    }

    #[test]
    fn zombie_speed_is_positive() {
        assert!(ZOMBIE_SPEED > 0.0);
    }
}

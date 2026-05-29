//! Built-in runtime systems used by the standalone bridge runtime.
//!
//! These systems are intentionally generic and data-driven. They are not a
//! replacement for compiled game-specific systems, but they make CGS-authored
//! prototype worlds behave predictably in the live engine bridge.

use anyhow::Result;
use serde_json::{json, Value};

use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;

use crate::cgs_loader::type_ids;
use crate::phase_orchestrator::system_registry::SystemRegistry;

const DT: f32 = 1.0 / 60.0;

pub struct InputSystem;
pub struct MovementSystem;
pub struct AISystem;
pub struct DamageSystem;
pub struct DeathSystem;

impl ISystem for InputSystem {
    fn system_id(&self) -> &str {
        "InputSystem"
    }

    fn declared_reads(&self) -> &[u32] {
        &[type_ids::INPUT, type_ids::VELOCITY]
    }

    fn declared_writes(&self) -> &[u32] {
        &[type_ids::VELOCITY]
    }

    fn execute(&self, ctx: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
        for entity_id in ctx.query_entities(&[type_ids::INPUT, type_ids::VELOCITY])? {
            let Some(input) = ctx.get_component(entity_id, type_ids::INPUT)? else {
                continue;
            };
            let value = parse_json(input);
            let move_x = number_field(&value, &["move_x", "axis_x", "x"]).unwrap_or(0.0);
            let move_z = number_field(&value, &["move_z", "axis_z", "z", "move_y"]).unwrap_or(0.0);
            let speed = number_field(&value, &["speed", "max_speed"])
                .unwrap_or(5.0)
                .abs();
            if move_x == 0.0 && move_z == 0.0 {
                continue;
            }
            let (vx, vz) = normalize_xz(move_x, move_z, speed);
            ctx.submit_mutation(entity_id, type_ids::VELOCITY, velocity_json(vx, 0.0, vz))?;
        }
        Ok(())
    }
}

impl ISystem for MovementSystem {
    fn system_id(&self) -> &str {
        "MovementSystem"
    }

    fn declared_reads(&self) -> &[u32] {
        &[type_ids::TRANSFORM, type_ids::VELOCITY]
    }

    fn declared_writes(&self) -> &[u32] {
        &[type_ids::TRANSFORM]
    }

    fn execute(&self, ctx: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
        for entity_id in ctx.query_entities(&[type_ids::TRANSFORM, type_ids::VELOCITY])? {
            let Some(transform) = ctx.get_component(entity_id, type_ids::TRANSFORM)? else {
                continue;
            };
            let Some(velocity) = ctx.get_component(entity_id, type_ids::VELOCITY)? else {
                continue;
            };
            let (x, y, z) = parse_position_xyz(transform);
            let (vx, vy, vz) = parse_velocity_xyz(velocity);
            if vx == 0.0 && vy == 0.0 && vz == 0.0 {
                continue;
            }
            ctx.submit_mutation(
                entity_id,
                type_ids::TRANSFORM,
                transform_json(x + vx * DT, y + vy * DT, z + vz * DT),
            )?;
        }
        Ok(())
    }
}

impl ISystem for AISystem {
    fn system_id(&self) -> &str {
        "AISystem"
    }

    fn declared_reads(&self) -> &[u32] {
        &[type_ids::AI, type_ids::TRANSFORM, type_ids::IDENTITY]
    }

    fn declared_writes(&self) -> &[u32] {
        &[type_ids::VELOCITY, type_ids::DAMAGE]
    }

    fn execute(&self, ctx: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
        let Some(target_id) = find_player_entity(ctx)? else {
            return Ok(());
        };
        let Some(target_transform) = ctx.get_component(target_id, type_ids::TRANSFORM)? else {
            return Ok(());
        };
        let (tx, _ty, tz) = parse_position_xyz(target_transform);

        for entity_id in ctx.query_entities(&[type_ids::AI, type_ids::TRANSFORM])? {
            if entity_id == target_id {
                continue;
            }
            let Some(ai_json) = ctx.get_component(entity_id, type_ids::AI)? else {
                continue;
            };
            let Some(transform_json_str) = ctx.get_component(entity_id, type_ids::TRANSFORM)?
            else {
                continue;
            };
            let ai = parse_json(ai_json);
            let (x, _y, z) = parse_position_xyz(transform_json_str);
            let dx = tx - x;
            let dz = tz - z;
            let distance = (dx * dx + dz * dz).sqrt();
            let detection_radius =
                number_field(&ai, &["detection_radius", "radius"]).unwrap_or(20.0);
            let attack_range = number_field(&ai, &["attack_range"]).unwrap_or(1.5);
            let attack_damage = number_field(&ai, &["attack_damage", "damage"]).unwrap_or(10.0);
            let speed = number_field(&ai, &["move_speed", "speed"]).unwrap_or(3.0);

            if distance <= attack_range {
                ctx.submit_mutation(
                    target_id,
                    type_ids::DAMAGE,
                    json!({
                        "amount": attack_damage,
                        "source_entity_id": entity_id,
                        "target_entity_id": target_id,
                        "tick": ctx.current_tick()
                    })
                    .to_string(),
                )?;
                ctx.submit_mutation(entity_id, type_ids::VELOCITY, velocity_json(0.0, 0.0, 0.0))?;
            } else if distance <= detection_radius && distance > f32::EPSILON {
                let (vx, vz) = normalize_xz(dx, dz, speed);
                ctx.submit_mutation(entity_id, type_ids::VELOCITY, velocity_json(vx, 0.0, vz))?;
            }
        }
        Ok(())
    }
}

impl ISystem for DamageSystem {
    fn system_id(&self) -> &str {
        "DamageSystem"
    }

    fn declared_reads(&self) -> &[u32] {
        &[type_ids::DAMAGE, type_ids::HEALTH]
    }

    fn declared_writes(&self) -> &[u32] {
        &[type_ids::HEALTH, type_ids::DAMAGE]
    }

    fn execute(&self, ctx: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
        for entity_id in ctx.query_entities(&[type_ids::DAMAGE, type_ids::HEALTH])? {
            let Some(damage_json_str) = ctx.get_component(entity_id, type_ids::DAMAGE)? else {
                continue;
            };
            let Some(health_json_str) = ctx.get_component(entity_id, type_ids::HEALTH)? else {
                continue;
            };
            let damage = parse_json(damage_json_str);
            let health = parse_json(health_json_str);
            let amount = number_field(&damage, &["amount", "damage"])
                .unwrap_or(0.0)
                .max(0.0);
            if amount == 0.0 {
                continue;
            }
            let current = number_field(&health, &["current", "hp"]).unwrap_or(0.0);
            let max = number_field(&health, &["max", "max_hp"]).unwrap_or(current.max(0.0));
            let invincible = health
                .get("is_invincible")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let next = if invincible {
                current
            } else {
                (current - amount).max(0.0)
            };
            ctx.submit_mutation(
                entity_id,
                type_ids::HEALTH,
                json!({
                    "current": next,
                    "max": max,
                    "regen_rate": number_field(&health, &["regen_rate"]).unwrap_or(0.0),
                    "is_invincible": invincible
                })
                .to_string(),
            )?;
            ctx.submit_mutation(
                entity_id,
                type_ids::DAMAGE,
                json!({
                    "amount": 0.0,
                    "processed_tick": ctx.current_tick()
                })
                .to_string(),
            )?;
        }
        Ok(())
    }
}

impl ISystem for DeathSystem {
    fn system_id(&self) -> &str {
        "DeathSystem"
    }

    fn declared_reads(&self) -> &[u32] {
        &[type_ids::HEALTH]
    }

    fn declared_writes(&self) -> &[u32] {
        &[]
    }

    fn execute(&self, ctx: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
        for entity_id in ctx.query_entities(&[type_ids::HEALTH])? {
            let Some(health_json_str) = ctx.get_component(entity_id, type_ids::HEALTH)? else {
                continue;
            };
            let health = parse_json(health_json_str);
            if number_field(&health, &["current", "hp"]).unwrap_or(1.0) <= 0.0 {
                ctx.submit_destroy(entity_id)?;
            }
        }
        Ok(())
    }
}

pub fn build_default_registry() -> Result<SystemRegistry> {
    let mut registry = SystemRegistry::new();
    for system in builtin_systems() {
        let id = system.system_id().to_string();
        registry
            .register(system)
            .map_err(|err| anyhow::anyhow!("register {}: {}", id, err))?;
    }
    Ok(registry)
}

fn builtin_systems() -> Vec<Box<dyn ISystem>> {
    vec![
        Box::new(InputSystem),
        Box::new(MovementSystem),
        Box::new(AISystem),
        Box::new(DamageSystem),
        Box::new(DeathSystem),
    ]
}

fn find_player_entity(ctx: &mut dyn ISystemContext) -> std::result::Result<Option<u64>, XaceError> {
    for entity_id in ctx.query_entities(&[type_ids::IDENTITY, type_ids::TRANSFORM])? {
        let Some(identity_json) = ctx.get_component(entity_id, type_ids::IDENTITY)? else {
            continue;
        };
        let identity = parse_json(identity_json);
        let name = identity
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_ascii_lowercase();
        if name.contains("player") {
            return Ok(Some(entity_id));
        }
    }
    Ok(ctx
        .query_entities(&[type_ids::TRANSFORM])?
        .into_iter()
        .next())
}

fn parse_json(raw: &str) -> Value {
    serde_json::from_str(raw).unwrap_or_else(|_| json!({}))
}

fn parse_position_xyz(raw: &str) -> (f32, f32, f32) {
    let value = parse_json(raw);
    (
        number_field(&value, &["position_x", "x"]).unwrap_or(0.0),
        number_field(&value, &["position_y", "y"]).unwrap_or(0.0),
        number_field(&value, &["position_z", "z"]).unwrap_or(0.0),
    )
}

fn parse_velocity_xyz(raw: &str) -> (f32, f32, f32) {
    let value = parse_json(raw);
    (
        number_field(&value, &["linear_x", "vx", "x"]).unwrap_or(0.0),
        number_field(&value, &["linear_y", "vy", "y"]).unwrap_or(0.0),
        number_field(&value, &["linear_z", "vz", "z"]).unwrap_or(0.0),
    )
}

fn number_field(value: &Value, names: &[&str]) -> Option<f32> {
    names
        .iter()
        .find_map(|name| value.get(*name)?.as_f64())
        .filter(|number| number.is_finite())
        .map(|number| number as f32)
}

fn normalize_xz(x: f32, z: f32, speed: f32) -> (f32, f32) {
    let length = (x * x + z * z).sqrt();
    if length <= f32::EPSILON {
        return (0.0, 0.0);
    }
    let scale = speed / length;
    (x * scale, z * scale)
}

fn velocity_json(vx: f32, vy: f32, vz: f32) -> String {
    json!({
        "linear_x": vx,
        "linear_y": vy,
        "linear_z": vz
    })
    .to_string()
}

fn transform_json(x: f32, y: f32, z: f32) -> String {
    json!({
        "position_x": x,
        "position_y": y,
        "position_z": z
    })
    .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_xz_scales_to_speed() {
        let (x, z) = normalize_xz(3.0, 4.0, 10.0);
        assert!((x - 6.0).abs() < 0.001);
        assert!((z - 8.0).abs() < 0.001);
    }
}

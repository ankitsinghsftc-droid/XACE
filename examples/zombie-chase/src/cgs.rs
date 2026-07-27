//! # Zombie Chase — Canonical Game Schema (CGS)
//!
//! The minimal game definition for the Phase 9 vertical slice.
//! This is what a full CGS v1 would look like for the zombie chase game.
//! In production, the GDE generates this from designer prompts.
//! In Phase 9, we define it directly to prove the runtime works.
//!
//! ## Game Rules
//! - One player entity moves in a deterministic spiral
//! - N zombie entities chase the player (AISystem)
//! - Zombies deal damage when within attack range
//! - Entities with HEALTH <= 0 are destroyed (DeathSystem)
//!
//! ## Component Type IDs (from UCL + DCL)
//! UCL Core (frozen, IDs 1–10):
//!   TRANSFORM=1, IDENTITY=2, VELOCITY=5, INPUT=6
//! DCL combat (IDs 100–104):
//!   HEALTH=100, DAMAGE=101
//! DCL ai (IDs 160–163):
//!   AI=160

use std::collections::BTreeMap;
use xace_core::fixed_point::Fixed64;
use xace_runtime_core::fixed_json::{fixed_from_json, IntegerEncoding};

// ── Component Type IDs ────────────────────────────────────────────────────────

/// UCL Core component type IDs — frozen forever.
pub mod component_ids {
    pub const TRANSFORM: u32 = 1;
    pub const IDENTITY: u32 = 2;
    pub const VELOCITY: u32 = 5;
    pub const INPUT: u32 = 6;

    // DCL combat
    pub const HEALTH: u32 = 100;
    pub const DAMAGE: u32 = 101;

    // DCL ai
    pub const AI: u32 = 160;
}

// ── Actor IDs ─────────────────────────────────────────────────────────────────

pub const ACTOR_PLAYER: &str = "actor_player";
pub const ACTOR_ZOMBIE: &str = "actor_zombie";

// ── System IDs ────────────────────────────────────────────────────────────────
// Must match exactly what each ISystem::system_id() returns.
// Used for RNG seeding (D6) and ExecutionPlan ordering.

pub const SYSTEM_INPUT: &str = "InputSystem";
pub const SYSTEM_MOVEMENT: &str = "MovementSystem";
pub const SYSTEM_AI: &str = "AISystem";
pub const SYSTEM_DAMAGE: &str = "DamageSystem";
pub const SYSTEM_DEATH: &str = "DeathSystem";

// ── Execution Order ───────────────────────────────────────────────────────────
// D1: system order defined ONLY by ExecutionPlan, never by self-scheduling.
// All systems run in Simulation phase. Order within phase matters for D4.

pub fn execution_order() -> Vec<&'static str> {
    vec![
        SYSTEM_INPUT,    // 1. collect input → write VELOCITY intent
        SYSTEM_MOVEMENT, // 2. integrate VELOCITY → update TRANSFORM
        SYSTEM_AI,       // 3. zombie chase AI → write VELOCITY, may add DAMAGE
        SYSTEM_DAMAGE,   // 4. apply pending DAMAGE → update HEALTH
        SYSTEM_DEATH,    // 5. destroy entities with HEALTH <= 0
    ]
}

// ── Initial Component JSON Builders ───────────────────────────────────────────
// Stable field ordering (D11) — all maps use BTreeMap or sorted keys.

pub fn transform_json(x: Fixed64, y: Fixed64, z: Fixed64) -> String {
    format!(
        r#"{{"position":{{"x":{},"y":{},"z":{}}},"rotation":{{"x":{},"y":{},"z":{},"w":{}}},"scale":{{"x":{},"y":{},"z":{}}},"parent_entity_id":0}}"#,
        x.raw(),
        y.raw(),
        z.raw(),
        Fixed64::ZERO.raw(),
        Fixed64::ZERO.raw(),
        Fixed64::ZERO.raw(),
        Fixed64::ONE.raw(),
        Fixed64::ONE.raw(),
        Fixed64::ONE.raw(),
        Fixed64::ONE.raw()
    )
}

pub fn velocity_json(vx: Fixed64, vy: Fixed64, vz: Fixed64) -> String {
    format!(
        r#"{{"linear":{{"x":{},"y":{},"z":{}}},"angular":{{"x":{},"y":{},"z":{}}},"max_linear_speed":{},"max_angular_speed":{}}}"#,
        vx.raw(),
        vy.raw(),
        vz.raw(),
        Fixed64::ZERO.raw(),
        Fixed64::ZERO.raw(),
        Fixed64::ZERO.raw(),
        Fixed64::from_units(10).raw(),
        Fixed64::from_units(360).raw()
    )
}

pub fn identity_json(name: &str, entity_type: &str) -> String {
    format!(
        r#"{{"entity_name":"{}","entity_type":"{}","faction":"neutral","tags":[],"prefab_id":"","is_runtime_spawned":false}}"#,
        name, entity_type
    )
}

pub fn input_json(controller_id: u32, control_type: &str) -> String {
    format!(
        r#"{{"controller_id":{},"control_type":"{}","input_profile_id":"default","is_enabled":true}}"#,
        controller_id, control_type
    )
}

pub fn health_json(current: Fixed64, max: Fixed64) -> String {
    format!(
        r#"{{"current":{},"max":{},"regen_rate":{},"is_invincible":false,"death_behavior":"DESTROY","last_damage_tick":0}}"#,
        current.raw(),
        max.raw(),
        Fixed64::ZERO.raw()
    )
}

pub fn ai_json(target_entity_id: u64, detection_radius: Fixed64) -> String {
    format!(
        r#"{{"behavior_model":"CHASE","current_state":"ACTIVE","target_entity_id":{},"detection_radius":{},"aggression_level":{},"memory":{{}}}}"#,
        target_entity_id,
        detection_radius.raw(),
        Fixed64::ONE.raw()
    )
}

pub fn damage_json(amount: Fixed64, source_entity_id: u64, applied_tick: u64) -> String {
    format!(
        r#"{{"damage_type":"PHYSICAL","amount":{},"source_entity_id":{},"applied_tick":{},"is_consumed":false}}"#,
        amount.raw(),
        source_entity_id,
        applied_tick
    )
}

pub fn damage_consumed_json(amount: Fixed64, source_entity_id: u64, applied_tick: u64) -> String {
    format!(
        r#"{{"damage_type":"PHYSICAL","amount":{},"source_entity_id":{},"applied_tick":{},"is_consumed":true}}"#,
        amount.raw(),
        source_entity_id,
        applied_tick
    )
}

// ── Initial World Builder ─────────────────────────────────────────────────────

/// Builds initial component maps for the player entity.
pub fn player_initial_components(x: Fixed64, z: Fixed64) -> BTreeMap<u32, String> {
    let mut m = BTreeMap::new();
    m.insert(
        component_ids::TRANSFORM,
        transform_json(x, Fixed64::ZERO, z),
    );
    m.insert(component_ids::IDENTITY, identity_json("Player", "PLAYER"));
    m.insert(
        component_ids::VELOCITY,
        velocity_json(Fixed64::ZERO, Fixed64::ZERO, Fixed64::ZERO),
    );
    m.insert(component_ids::INPUT, input_json(0, "HUMAN"));
    m.insert(
        component_ids::HEALTH,
        health_json(Fixed64::from_units(100), Fixed64::from_units(100)),
    );
    m
}

/// Builds initial component maps for a zombie entity.
pub fn zombie_initial_components(
    x: Fixed64,
    z: Fixed64,
    target_player_id: u64,
) -> BTreeMap<u32, String> {
    let mut m = BTreeMap::new();
    m.insert(
        component_ids::TRANSFORM,
        transform_json(x, Fixed64::ZERO, z),
    );
    m.insert(component_ids::IDENTITY, identity_json("Zombie", "ENEMY"));
    m.insert(
        component_ids::VELOCITY,
        velocity_json(Fixed64::ZERO, Fixed64::ZERO, Fixed64::ZERO),
    );
    m.insert(
        component_ids::HEALTH,
        health_json(Fixed64::from_units(30), Fixed64::from_units(30)),
    );
    m.insert(
        component_ids::AI,
        ai_json(target_player_id, Fixed64::from_units(20)),
    );
    m
}

// ── Component JSON Parsers ─────────────────────────────────────────────────────
// Lightweight field extractors — no full struct deserialization for hot path.

/// Extracts (x, z) position from COMP_TRANSFORM_V1 JSON.
///
/// Searches within the "position":{...} sub-object only, so z is
/// never confused with rotation.z or scale.z.
pub fn parse_position_xz(json: &str) -> (Fixed64, Fixed64) {
    // Locate "position":{ and find its closing }
    let x = nested_fixed(json, "position", "x").unwrap_or(Fixed64::ZERO);
    let z = nested_fixed(json, "position", "z").unwrap_or(Fixed64::ZERO);
    // "sub" is e.g. {"x":1.0,"y":0.0,"z":2.0}
    // extract_f32 finds the FIRST occurrence of each key — correct here
    (x, z)
}

/// Extracts linear velocity (vx, vz) from COMP_VELOCITY_V1 JSON.
///
/// Searches within the "linear":{...} sub-object only, so z is
/// never confused with angular.z.
pub fn parse_velocity_xz(json: &str) -> (Fixed64, Fixed64) {
    // Locate "linear":{ and find its closing }
    let vx = nested_fixed(json, "linear", "x").unwrap_or(Fixed64::ZERO);
    let vz = nested_fixed(json, "linear", "z").unwrap_or(Fixed64::ZERO);
    // "sub" is e.g. {"x":vx,"y":vy,"z":vz}
    (vx, vz)
}

/// Extracts COMP_HEALTH_V1.current.
pub fn parse_health_current(json: &str) -> Fixed64 {
    top_fixed(json, "current").unwrap_or(Fixed64::ZERO)
}

/// Extracts COMP_HEALTH_V1.max.
pub fn parse_health_max(json: &str) -> Fixed64 {
    top_fixed(json, "max").unwrap_or(Fixed64::from_units(100))
}

/// Extracts COMP_AI_V1.target_entity_id.
pub fn parse_ai_target(json: &str) -> u64 {
    extract_u64(json, "\"target_entity_id\":").unwrap_or(0)
}

/// Extracts COMP_DAMAGE_V1.amount.
pub fn parse_damage_amount(json: &str) -> Fixed64 {
    top_fixed(json, "amount").unwrap_or(Fixed64::ZERO)
}

/// Extracts COMP_DAMAGE_V1.applied_tick.
pub fn parse_damage_applied_tick(json: &str) -> u64 {
    extract_u64(json, "\"applied_tick\":").unwrap_or(0)
}

/// Returns true if COMP_DAMAGE_V1.is_consumed == false.
pub fn parse_damage_is_consumed(json: &str) -> bool {
    json.contains("\"is_consumed\":true")
}

/// Returns COMP_INPUT_V1.controller_id.
pub fn parse_input_controller_id(json: &str) -> u32 {
    extract_u32(json, "\"controller_id\":").unwrap_or(0)
}

// ── Internal parse helpers ────────────────────────────────────────────────────

fn nested_fixed(json: &str, object_key: &str, field_key: &str) -> Option<Fixed64> {
    let value: serde_json::Value = serde_json::from_str(json).ok()?;
    fixed_from_json(
        value.get(object_key)?.get(field_key)?,
        IntegerEncoding::RawMicroUnits,
    )
}

fn top_fixed(json: &str, field_key: &str) -> Option<Fixed64> {
    let value: serde_json::Value = serde_json::from_str(json).ok()?;
    fixed_from_json(value.get(field_key)?, IntegerEncoding::RawMicroUnits)
}

pub fn extract_u64(json: &str, key: &str) -> Option<u64> {
    let pos = json.find(key)? + key.len();
    let rest = json[pos..].trim_start_matches(' ');
    let end = rest
        .find(|c: char| !c.is_ascii_digit())
        .unwrap_or(rest.len());
    rest[..end].parse().ok()
}

pub fn extract_u32(json: &str, key: &str) -> Option<u32> {
    extract_u64(json, key).map(|v| v as u32)
}

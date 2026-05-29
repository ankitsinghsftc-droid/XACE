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

pub fn transform_json(x: f32, y: f32, z: f32) -> String {
    format!(
        r#"{{"position":{{"x":{:.6},"y":{:.6},"z":{:.6}}},"rotation":{{"x":0.0,"y":0.0,"z":0.0,"w":1.0}},"scale":{{"x":1.0,"y":1.0,"z":1.0}},"parent_entity_id":0}}"#,
        x, y, z
    )
}

pub fn velocity_json(vx: f32, vy: f32, vz: f32) -> String {
    format!(
        r#"{{"linear":{{"x":{:.6},"y":{:.6},"z":{:.6}}},"angular":{{"x":0.0,"y":0.0,"z":0.0}},"max_linear_speed":10.0,"max_angular_speed":360.0}}"#,
        vx, vy, vz
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

pub fn health_json(current: f32, max: f32) -> String {
    format!(
        r#"{{"current":{:.2},"max":{:.2},"regen_rate":0.0,"is_invincible":false,"death_behavior":"DESTROY","last_damage_tick":0}}"#,
        current, max
    )
}

pub fn ai_json(target_entity_id: u64, detection_radius: f32) -> String {
    format!(
        r#"{{"behavior_model":"CHASE","current_state":"ACTIVE","target_entity_id":{},"detection_radius":{:.2},"aggression_level":1.0,"memory":{{}}}}"#,
        target_entity_id, detection_radius
    )
}

pub fn damage_json(amount: f32, source_entity_id: u64, applied_tick: u64) -> String {
    format!(
        r#"{{"damage_type":"PHYSICAL","amount":{:.2},"source_entity_id":{},"applied_tick":{},"is_consumed":false}}"#,
        amount, source_entity_id, applied_tick
    )
}

pub fn damage_consumed_json(amount: f32, source_entity_id: u64, applied_tick: u64) -> String {
    format!(
        r#"{{"damage_type":"PHYSICAL","amount":{:.2},"source_entity_id":{},"applied_tick":{},"is_consumed":true}}"#,
        amount, source_entity_id, applied_tick
    )
}

// ── Initial World Builder ─────────────────────────────────────────────────────

/// Builds initial component maps for the player entity.
pub fn player_initial_components(x: f32, z: f32) -> BTreeMap<u32, String> {
    let mut m = BTreeMap::new();
    m.insert(component_ids::TRANSFORM, transform_json(x, 0.0, z));
    m.insert(component_ids::IDENTITY, identity_json("Player", "PLAYER"));
    m.insert(component_ids::VELOCITY, velocity_json(0.0, 0.0, 0.0));
    m.insert(component_ids::INPUT, input_json(0, "HUMAN"));
    m.insert(component_ids::HEALTH, health_json(100.0, 100.0));
    m
}

/// Builds initial component maps for a zombie entity.
pub fn zombie_initial_components(x: f32, z: f32, target_player_id: u64) -> BTreeMap<u32, String> {
    let mut m = BTreeMap::new();
    m.insert(component_ids::TRANSFORM, transform_json(x, 0.0, z));
    m.insert(component_ids::IDENTITY, identity_json("Zombie", "ENEMY"));
    m.insert(component_ids::VELOCITY, velocity_json(0.0, 0.0, 0.0));
    m.insert(component_ids::HEALTH, health_json(30.0, 30.0));
    m.insert(component_ids::AI, ai_json(target_player_id, 20.0));
    m
}

// ── Component JSON Parsers ─────────────────────────────────────────────────────
// Lightweight field extractors — no full struct deserialization for hot path.

/// Extracts (x, z) position from COMP_TRANSFORM_V1 JSON.
///
/// Searches within the "position":{...} sub-object only, so z is
/// never confused with rotation.z or scale.z.
pub fn parse_position_xz(json: &str) -> (f32, f32) {
    // Locate "position":{ and find its closing }
    const KEY: &str = "\"position\":";
    let start = match json.find(KEY) {
        Some(i) => i + KEY.len(),
        None => return (0.0, 0.0),
    };
    let end = json[start..]
        .find('}')
        .map(|i| start + i + 1)
        .unwrap_or(json.len());
    let sub = &json[start..end];
    // "sub" is e.g. {"x":1.0,"y":0.0,"z":2.0}
    // extract_f32 finds the FIRST occurrence of each key — correct here
    let x = extract_f32(sub, "\"x\":").unwrap_or(0.0);
    let z = extract_f32(sub, "\"z\":").unwrap_or(0.0);
    (x, z)
}

/// Extracts linear velocity (vx, vz) from COMP_VELOCITY_V1 JSON.
///
/// Searches within the "linear":{...} sub-object only, so z is
/// never confused with angular.z.
pub fn parse_velocity_xz(json: &str) -> (f32, f32) {
    // Locate "linear":{ and find its closing }
    const KEY: &str = "\"linear\":";
    let start = match json.find(KEY) {
        Some(i) => i + KEY.len(),
        None => return (0.0, 0.0),
    };
    let end = json[start..]
        .find('}')
        .map(|i| start + i + 1)
        .unwrap_or(json.len());
    let sub = &json[start..end];
    // "sub" is e.g. {"x":vx,"y":vy,"z":vz}
    let vx = extract_f32(sub, "\"x\":").unwrap_or(0.0);
    let vz = extract_f32(sub, "\"z\":").unwrap_or(0.0);
    (vx, vz)
}

/// Extracts COMP_HEALTH_V1.current.
pub fn parse_health_current(json: &str) -> f32 {
    extract_f32(json, "\"current\":").unwrap_or(0.0)
}

/// Extracts COMP_HEALTH_V1.max.
pub fn parse_health_max(json: &str) -> f32 {
    extract_f32(json, "\"max\":").unwrap_or(100.0)
}

/// Extracts COMP_AI_V1.target_entity_id.
pub fn parse_ai_target(json: &str) -> u64 {
    extract_u64(json, "\"target_entity_id\":").unwrap_or(0)
}

/// Extracts COMP_DAMAGE_V1.amount.
pub fn parse_damage_amount(json: &str) -> f32 {
    extract_f32(json, "\"amount\":").unwrap_or(0.0)
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

/// Extracts the first f32 value immediately after `key` in `json`.
pub fn extract_f32(json: &str, key: &str) -> Option<f32> {
    let pos = json.find(key)? + key.len();
    let rest = json[pos..].trim_start_matches(' ');
    let end = rest
        .find(|c: char| !c.is_ascii_digit() && c != '.' && c != '-' && c != 'e')
        .unwrap_or(rest.len());
    rest[..end].parse().ok()
}

/// Extracts the LAST occurrence of `key` in `json` as f32.
/// Used for 'z' which appears multiple times in transform JSON.
pub fn extract_f32_after(json: &str, key: &str) -> Option<f32> {
    let pos = json.rfind(key)? + key.len();
    let rest = json[pos..].trim_start_matches(' ');
    let end = rest
        .find(|c: char| !c.is_ascii_digit() && c != '.' && c != '-' && c != 'e')
        .unwrap_or(rest.len());
    rest[..end].parse().ok()
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

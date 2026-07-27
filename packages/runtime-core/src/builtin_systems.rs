//! Built-in runtime systems used by the standalone bridge runtime.
//!
//! These systems are intentionally generic and data-driven. They are not a
//! replacement for compiled game-specific systems, but they make CGS-authored
//! prototype worlds behave predictably in the live engine bridge.

use anyhow::Result;
use serde_json::{json, Value};

use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::XaceError;
use xace_core::events::event_struct::Event;
use xace_core::events::semantic_event_registry as semantic_events;
use xace_core::fixed_point::Fixed64;
use xace_core::runtime::phase_enum::PhaseEnum;

use crate::cgs_loader::type_ids;
use crate::fixed_json::{
    fixed_field as json_fixed_field, fixed_from_units_u64, fixed_tick_delta_60hz, fixed_value,
    set_fixed_field as set_json_fixed_field, u64_field as json_u64_field, IntegerEncoding,
};
use crate::phase_orchestrator::system_registry::SystemRegistry;

pub struct InputSystem;
pub struct MovementSystem;
pub struct AISystem;
pub struct DamageSystem;
pub struct DeathSystem;
pub struct InteractionSystem;
pub struct InventorySystem;

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
            let Some(velocity) = ctx.get_component(entity_id, type_ids::VELOCITY)? else {
                continue;
            };
            let value = parse_json(input);
            let move_x = number_field(&value, &["move_x", "axis_x", "x"]).unwrap_or(Fixed64::ZERO);
            let move_z =
                number_field(&value, &["move_z", "axis_z", "z", "move_y"]).unwrap_or(Fixed64::ZERO);
            let velocity_value = parse_json(velocity);
            let speed = number_field(&value, &["speed", "max_speed"])
                .or_else(|| number_field(&velocity_value, &["max_linear_speed", "max_speed"]))
                .unwrap_or(Fixed64::from_units(5))
                .abs();
            let (vx, vz) = normalize_xz(move_x, move_z, speed);
            ctx.submit_mutation(
                entity_id,
                type_ids::VELOCITY,
                velocity_json_from_existing(velocity, vx, Fixed64::ZERO, vz),
            )?;
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
            if vx.is_zero() && vy.is_zero() && vz.is_zero() {
                continue;
            }
            let transform_value = parse_json(transform);
            let dt = fixed_tick_delta_60hz();
            let (next_x, next_z) = clamp_xz_to_bounds(&transform_value, x + vx * dt, z + vz * dt);
            ctx.submit_mutation(
                entity_id,
                type_ids::TRANSFORM,
                transform_json_from_existing(transform, next_x, y + vy * dt, next_z),
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
            let detection_radius = number_field(&ai, &["detection_radius", "radius"])
                .unwrap_or(Fixed64::from_units(20));
            let attack_range =
                number_field(&ai, &["attack_range"]).unwrap_or(Fixed64::from_millis(1500));
            let attack_damage =
                number_field(&ai, &["attack_damage", "damage"]).unwrap_or(Fixed64::from_units(10));
            let speed =
                number_field(&ai, &["move_speed", "speed"]).unwrap_or(Fixed64::from_units(3));

            if distance <= attack_range {
                ctx.submit_mutation(
                    target_id,
                    type_ids::DAMAGE,
                    json!({
                        "amount": fixed_value(attack_damage),
                        "source_entity_id": entity_id,
                        "target_entity_id": target_id,
                        "tick": ctx.current_tick()
                    })
                    .to_string(),
                )?;
                ctx.submit_mutation(
                    entity_id,
                    type_ids::VELOCITY,
                    velocity_json(Fixed64::ZERO, Fixed64::ZERO, Fixed64::ZERO),
                )?;
            } else if distance <= detection_radius && distance > Fixed64::ZERO {
                let (vx, vz) = normalize_xz(dx, dz, speed);
                ctx.submit_mutation(
                    entity_id,
                    type_ids::VELOCITY,
                    velocity_json(vx, Fixed64::ZERO, vz),
                )?;
            }
        }
        Ok(())
    }
}

impl ISystem for InteractionSystem {
    fn system_id(&self) -> &str {
        "InteractionSystem"
    }

    fn declared_reads(&self) -> &[u32] {
        &[
            type_ids::INPUT,
            type_ids::TRANSFORM,
            type_ids::INTERACTION,
            type_ids::IDENTITY,
        ]
    }

    fn declared_writes(&self) -> &[u32] {
        &[type_ids::INPUT, type_ids::INTERACTION]
    }

    fn execute(&self, ctx: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
        let interactables = collect_interactables(ctx)?;
        if interactables.is_empty() {
            clear_all_focus(ctx)?;
            return Ok(());
        }

        for actor_id in ctx.query_entities(&[type_ids::INPUT, type_ids::TRANSFORM])? {
            let Some(actor_input_raw) = ctx.get_component(actor_id, type_ids::INPUT)? else {
                continue;
            };
            let Some(actor_transform_raw) = ctx.get_component(actor_id, type_ids::TRANSFORM)?
            else {
                continue;
            };
            let actor_input = parse_json(actor_input_raw);
            let (actor_x, _actor_y, actor_z) = parse_position_xyz(actor_transform_raw);
            let previous_focus = u64_field(&actor_input, &["focused_entity_id"]).unwrap_or(0);
            let focus = nearest_valid_interactable(actor_id, actor_x, actor_z, &interactables);
            let input_state =
                input_with_focus_state(actor_input_raw, actor_id, previous_focus, focus.as_ref());
            ctx.submit_mutation(actor_id, type_ids::INPUT, input_state)?;

            if let Some(focus) = focus {
                emit_focus_transition(ctx, actor_id, previous_focus, focus.entity_id())?;
                if interaction_was_requested(&actor_input) {
                    accept_interaction(ctx, actor_id, &focus)?;
                }
            } else if previous_focus != 0 {
                emit_interaction_event(
                    ctx,
                    actor_id,
                    previous_focus,
                    semantic_events::INTERACTION_UNFOCUSED,
                    "Unfocused",
                    "",
                )?;
            }
        }
        Ok(())
    }
}

impl ISystem for InventorySystem {
    fn system_id(&self) -> &str {
        "InventorySystem"
    }

    fn declared_reads(&self) -> &[u32] {
        &[
            type_ids::INPUT,
            type_ids::INVENTORY,
            type_ids::ITEM,
            type_ids::INTERACTION,
            type_ids::TRANSFORM,
        ]
    }

    fn declared_writes(&self) -> &[u32] {
        &[
            type_ids::INVENTORY,
            type_ids::ITEM,
            type_ids::INTERACTION,
            type_ids::TRANSFORM,
        ]
    }

    fn execute(&self, ctx: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
        for actor_id in ctx.query_entities(&[type_ids::INPUT, type_ids::INVENTORY])? {
            let Some(input_raw) = ctx.get_component(actor_id, type_ids::INPUT)? else {
                continue;
            };
            let Some(inventory_raw) = ctx.get_component(actor_id, type_ids::INVENTORY)? else {
                continue;
            };
            let input = parse_json(input_raw);
            let mut inventory = parse_json(inventory_raw);
            ensure_inventory_shape(&mut inventory);

            let mut changed = false;
            if pickup_was_requested(&input) {
                changed |= handle_pickup_intent(ctx, actor_id, &input, &mut inventory)?;
            }
            if equip_was_requested(&input) {
                changed |= handle_equip_intent(ctx, actor_id, &input, &mut inventory)?;
            }
            if drop_was_requested(&input) {
                changed |= handle_drop_intent(ctx, actor_id, &input, &mut inventory)?;
            }

            if changed {
                normalize_inventory_summary(&mut inventory);
                ctx.submit_mutation(actor_id, type_ids::INVENTORY, inventory.to_string())?;
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
                .unwrap_or(Fixed64::ZERO)
                .max(Fixed64::ZERO);
            if amount.is_zero() {
                continue;
            }
            let current = number_field(&health, &["current", "hp"]).unwrap_or(Fixed64::ZERO);
            let max =
                number_field(&health, &["max", "max_hp"]).unwrap_or(current.max(Fixed64::ZERO));
            let invincible = health
                .get("is_invincible")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let next = if invincible {
                current
            } else {
                (current - amount).max(Fixed64::ZERO)
            };
            ctx.submit_mutation(
                entity_id,
                type_ids::HEALTH,
                json!({
                    "current": fixed_value(next),
                    "max": fixed_value(max),
                    "regen_rate": fixed_value(
                        number_field(&health, &["regen_rate"]).unwrap_or(Fixed64::ZERO)
                    ),
                    "is_invincible": invincible
                })
                .to_string(),
            )?;
            ctx.submit_mutation(
                entity_id,
                type_ids::DAMAGE,
                json!({
                    "amount": fixed_value(Fixed64::ZERO),
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
            if number_field(&health, &["current", "hp"]).unwrap_or(Fixed64::ONE) <= Fixed64::ZERO {
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
        Box::new(InteractionSystem),
        Box::new(InventorySystem),
        Box::new(AISystem),
        Box::new(DamageSystem),
        Box::new(DeathSystem),
    ]
}

#[derive(Debug, Clone, PartialEq)]
struct InteractableCandidate {
    entity_id: u64,
    x: Fixed64,
    z: Fixed64,
    range: Fixed64,
    interaction_type: String,
    prompt_text: String,
    interaction_count: u64,
    max_interactions: u64,
    raw_component: String,
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct FocusedInteractable<'a> {
    candidate: &'a InteractableCandidate,
    distance_sq: Fixed64,
}

impl<'a> FocusedInteractable<'a> {
    fn entity_id(&self) -> u64 {
        self.candidate.entity_id
    }
}

fn collect_interactables(
    ctx: &mut dyn ISystemContext,
) -> std::result::Result<Vec<InteractableCandidate>, XaceError> {
    let mut out = Vec::new();
    for entity_id in ctx.query_entities(&[type_ids::INTERACTION, type_ids::TRANSFORM])? {
        let Some(interaction_raw) = ctx.get_component(entity_id, type_ids::INTERACTION)? else {
            continue;
        };
        let Some(transform_raw) = ctx.get_component(entity_id, type_ids::TRANSFORM)? else {
            continue;
        };
        let interaction = parse_json(interaction_raw);
        if !bool_field(&interaction, &["is_interactable"]).unwrap_or(true) {
            continue;
        }
        let interaction_count = u64_field(&interaction, &["interaction_count"]).unwrap_or(0);
        let max_interactions = u64_field(&interaction, &["max_interactions"]).unwrap_or(0);
        if max_interactions > 0 && interaction_count >= max_interactions {
            continue;
        }
        let (x, _y, z) = parse_position_xyz(transform_raw);
        out.push(InteractableCandidate {
            entity_id,
            x,
            z,
            range: number_field(&interaction, &["range"])
                .unwrap_or(Fixed64::from_units(2))
                .max(Fixed64::ZERO),
            interaction_type: string_field(&interaction, &["interaction_type"])
                .unwrap_or("Custom")
                .to_string(),
            prompt_text: string_field(&interaction, &["prompt_text"])
                .unwrap_or("")
                .to_string(),
            interaction_count,
            max_interactions,
            raw_component: interaction_raw.to_string(),
        });
    }
    out.sort_by_key(|candidate| candidate.entity_id);
    Ok(out)
}

fn clear_all_focus(ctx: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
    for actor_id in ctx.query_entities(&[type_ids::INPUT])? {
        let Some(input_raw) = ctx.get_component(actor_id, type_ids::INPUT)? else {
            continue;
        };
        let input = parse_json(input_raw);
        if u64_field(&input, &["focused_entity_id"]).unwrap_or(0) > 0 {
            ctx.submit_mutation(
                actor_id,
                type_ids::INPUT,
                input_with_focus_state(input_raw, actor_id, 0, None),
            )?;
        }
    }
    Ok(())
}

fn nearest_valid_interactable<'a>(
    actor_id: u64,
    actor_x: Fixed64,
    actor_z: Fixed64,
    interactables: &'a [InteractableCandidate],
) -> Option<FocusedInteractable<'a>> {
    interactables
        .iter()
        .filter(|candidate| candidate.entity_id != actor_id)
        .filter_map(|candidate| {
            let dx = candidate.x - actor_x;
            let dz = candidate.z - actor_z;
            let distance_sq = dx * dx + dz * dz;
            (distance_sq <= candidate.range * candidate.range).then_some(FocusedInteractable {
                candidate,
                distance_sq,
            })
        })
        .min_by(|left, right| {
            left.distance_sq
                .cmp(&right.distance_sq)
                .then_with(|| left.entity_id().cmp(&right.entity_id()))
        })
}

fn input_with_focus_state(
    input_raw: &str,
    actor_id: u64,
    previous_focus: u64,
    focus: Option<&FocusedInteractable<'_>>,
) -> String {
    let mut input = parse_json(input_raw);
    if !input.is_object() {
        input = json!({});
    }
    let Some(object) = input.as_object_mut() else {
        return input.to_string();
    };
    if let Some(focus) = focus {
        object.insert("focused_entity_id".to_string(), json!(focus.entity_id()));
        object.insert(
            "focused_interaction_type".to_string(),
            json!(focus.candidate.interaction_type.clone()),
        );
        object.insert(
            "focused_prompt_text".to_string(),
            json!(focus.candidate.prompt_text.clone()),
        );
        object.insert(
            "focused_distance_sq".to_string(),
            fixed_value(focus.distance_sq),
        );
        object.insert("can_interact".to_string(), json!(true));
    } else {
        object.insert("focused_entity_id".to_string(), json!(0));
        object.insert("focused_interaction_type".to_string(), json!(""));
        object.insert("focused_prompt_text".to_string(), json!(""));
        object.insert(
            "focused_distance_sq".to_string(),
            fixed_value(Fixed64::ZERO),
        );
        object.insert("can_interact".to_string(), json!(false));
    }
    object.insert(
        "previous_focused_entity_id".to_string(),
        json!(previous_focus),
    );
    object.insert("interaction_actor_entity_id".to_string(), json!(actor_id));
    input.to_string()
}

fn emit_focus_transition(
    ctx: &mut dyn ISystemContext,
    actor_id: u64,
    previous_focus: u64,
    next_focus: u64,
) -> std::result::Result<(), XaceError> {
    if previous_focus == next_focus {
        return Ok(());
    }
    if previous_focus != 0 {
        emit_interaction_event(
            ctx,
            actor_id,
            previous_focus,
            semantic_events::INTERACTION_UNFOCUSED,
            "Unfocused",
            "",
        )?;
    }
    emit_interaction_event(
        ctx,
        actor_id,
        next_focus,
        semantic_events::INTERACTION_FOCUSED,
        "Focused",
        "",
    )
}

fn interaction_was_requested(input: &Value) -> bool {
    bool_field(
        input,
        &[
            "interact_started",
            "pickup_started",
            "use_started",
            "activate_started",
        ],
    )
    .unwrap_or(false)
}

fn accept_interaction(
    ctx: &mut dyn ISystemContext,
    actor_id: u64,
    focus: &FocusedInteractable<'_>,
) -> std::result::Result<(), XaceError> {
    let mut interaction = parse_json(&focus.candidate.raw_component);
    if !interaction.is_object() {
        interaction = json!({});
    }
    if let Some(object) = interaction.as_object_mut() {
        object.insert(
            "interaction_count".to_string(),
            json!(focus.candidate.interaction_count.saturating_add(1)),
        );
        object.insert("last_interactor_entity_id".to_string(), json!(actor_id));
        object.insert(
            "last_interaction_tick".to_string(),
            json!(ctx.current_tick()),
        );
    }
    ctx.submit_mutation(
        focus.entity_id(),
        type_ids::INTERACTION,
        interaction.to_string(),
    )?;
    emit_interaction_event(
        ctx,
        actor_id,
        focus.entity_id(),
        semantic_events::INTERACTION_INTERACTED,
        "Interacted",
        &focus.candidate.interaction_type,
    )?;
    emit_interaction_event(
        ctx,
        actor_id,
        focus.entity_id(),
        semantic_events::INTERACTION_ACCEPTED,
        "Accepted",
        &focus.candidate.interaction_type,
    )
}

fn emit_interaction_event(
    ctx: &mut dyn ISystemContext,
    actor_id: u64,
    target_id: u64,
    event_name: &str,
    state: &str,
    interaction_type: &str,
) -> std::result::Result<(), XaceError> {
    let event = Event::directed(
        actor_id,
        target_id,
        semantic_events::domain_event(event_name),
        ctx.current_tick(),
        PhaseEnum::Simulation,
    )
    .with_payload("actor_entity_id", actor_id.to_string())
    .with_payload("target_entity_id", target_id.to_string())
    .with_payload("interaction_state", state.to_string())
    .with_payload("interaction_type", interaction_type.to_string());
    ctx.emit_event(event)
}

fn pickup_was_requested(input: &Value) -> bool {
    bool_field(
        input,
        &["pickup_started", "take_started", "collect_started"],
    )
    .unwrap_or(false)
}

fn equip_was_requested(input: &Value) -> bool {
    bool_field(input, &["equip_started", "equip_requested"]).unwrap_or(false)
}

fn drop_was_requested(input: &Value) -> bool {
    bool_field(input, &["drop_started", "drop_requested"]).unwrap_or(false)
}

fn handle_pickup_intent(
    ctx: &mut dyn ISystemContext,
    actor_id: u64,
    input: &Value,
    inventory: &mut Value,
) -> std::result::Result<bool, XaceError> {
    let Some(item_entity_id) = u64_field(
        input,
        &[
            "pickup_target_entity_id",
            "interact_target_entity_id",
            "focused_entity_id",
        ],
    )
    .filter(|target_id| *target_id != 0 && *target_id != actor_id) else {
        emit_inventory_event(
            ctx,
            actor_id,
            0,
            semantic_events::INVENTORY_PICKUP_REJECTED,
            "PickupRejected",
            "missing_target",
        )?;
        return Ok(false);
    };

    emit_inventory_event(
        ctx,
        actor_id,
        item_entity_id,
        semantic_events::INVENTORY_PICKUP_REQUESTED,
        "PickupRequested",
        "",
    )?;

    let Some(item_raw) = ctx.get_component(item_entity_id, type_ids::ITEM)? else {
        emit_inventory_event(
            ctx,
            actor_id,
            item_entity_id,
            semantic_events::INVENTORY_PICKUP_REJECTED,
            "PickupRejected",
            "target_is_not_item",
        )?;
        return Ok(false);
    };
    let item = parse_json(item_raw);
    if !bool_field(&item, &["is_pickable", "can_pickup"]).unwrap_or(true) {
        emit_inventory_event(
            ctx,
            actor_id,
            item_entity_id,
            semantic_events::INVENTORY_PICKUP_REJECTED,
            "PickupRejected",
            "item_not_pickable",
        )?;
        return Ok(false);
    }
    if u64_field(&item, &["owner_entity_id", "owner_id"]).unwrap_or(0) != 0 {
        emit_inventory_event(
            ctx,
            actor_id,
            item_entity_id,
            semantic_events::INVENTORY_PICKUP_REJECTED,
            "PickupRejected",
            "item_already_owned",
        )?;
        return Ok(false);
    }

    let max_capacity = u64_field(inventory, &["max_capacity"]).unwrap_or(20);
    let current_count = inventory_slots(inventory).len() as u64;
    if max_capacity > 0 && current_count >= max_capacity {
        emit_inventory_event(
            ctx,
            actor_id,
            item_entity_id,
            semantic_events::INVENTORY_PICKUP_REJECTED,
            "PickupRejected",
            "inventory_full",
        )?;
        return Ok(false);
    }

    let quantity = u64_field(&item, &["quantity", "stack_quantity"])
        .unwrap_or(1)
        .max(1);
    let item_weight = number_field(&item, &["weight", "unit_weight"])
        .unwrap_or(Fixed64::ZERO)
        .max(Fixed64::ZERO);
    let weight_current = number_field(inventory, &["weight_current"]).unwrap_or(Fixed64::ZERO);
    let weight_max = number_field(inventory, &["weight_max"]).unwrap_or(Fixed64::ZERO);
    let added_weight = item_weight * fixed_from_units_u64(quantity);
    if weight_max > Fixed64::ZERO && weight_current + added_weight > weight_max {
        emit_inventory_event(
            ctx,
            actor_id,
            item_entity_id,
            semantic_events::INVENTORY_PICKUP_REJECTED,
            "PickupRejected",
            "too_heavy",
        )?;
        return Ok(false);
    }

    let item_id = string_field(&item, &["item_id", "id"])
        .map(str::to_string)
        .unwrap_or_else(|| format!("entity_{}", item_entity_id));
    let slot_id = format!("slot_{}", item_entity_id);
    let slot_type = string_field(&item, &["slot_type", "equip_slot"])
        .unwrap_or("")
        .to_string();
    let display_name = string_field(&item, &["display_name", "name"])
        .unwrap_or(item_id.as_str())
        .to_string();

    inventory_slots_mut(inventory).push(json!({
        "slot_id": slot_id,
        "item_id": item_id,
        "item_entity_id": item_entity_id,
        "display_name": display_name,
        "quantity": quantity,
        "slot_type": slot_type,
        "is_equipped": false,
        "weight": fixed_value(added_weight)
    }));

    set_number_field(inventory, "weight_current", weight_current + added_weight);

    let mut next_item = item;
    if let Some(object) = next_item.as_object_mut() {
        object.insert("owner_entity_id".to_string(), json!(actor_id));
        object.insert("inventory_slot_id".to_string(), json!(slot_id));
        object.insert("world_state".to_string(), json!("InInventory"));
        object.insert("is_pickable".to_string(), json!(false));
        object.insert("is_equipped".to_string(), json!(false));
        object.insert("last_inventory_tick".to_string(), json!(ctx.current_tick()));
    }
    ctx.submit_mutation(item_entity_id, type_ids::ITEM, next_item.to_string())?;

    if let Some(interaction_raw) = ctx.get_component(item_entity_id, type_ids::INTERACTION)? {
        let mut interaction = parse_json(interaction_raw);
        if let Some(object) = interaction.as_object_mut() {
            object.insert("is_interactable".to_string(), json!(false));
            object.insert("last_interactor_entity_id".to_string(), json!(actor_id));
            object.insert(
                "last_interaction_tick".to_string(),
                json!(ctx.current_tick()),
            );
        }
        ctx.submit_mutation(
            item_entity_id,
            type_ids::INTERACTION,
            interaction.to_string(),
        )?;
    }

    emit_inventory_event(
        ctx,
        actor_id,
        item_entity_id,
        semantic_events::INVENTORY_PICKUP_ACCEPTED,
        "PickupAccepted",
        "",
    )?;
    Ok(true)
}

fn handle_equip_intent(
    ctx: &mut dyn ISystemContext,
    actor_id: u64,
    input: &Value,
    inventory: &mut Value,
) -> std::result::Result<bool, XaceError> {
    let requested_slot = string_field(
        input,
        &["equip_slot_id", "equipment_slot_id", "inventory_slot_id"],
    )
    .map(str::to_string);
    let requested_item_entity = u64_field(input, &["equip_item_entity_id", "item_entity_id"]);
    let Some(selected_index) =
        select_inventory_slot(inventory, requested_slot.as_deref(), requested_item_entity)
    else {
        emit_inventory_event(
            ctx,
            actor_id,
            0,
            semantic_events::INVENTORY_EQUIP_REJECTED,
            "EquipRejected",
            "slot_not_found",
        )?;
        return Ok(false);
    };

    let mut equipped_item_entity_id = 0;
    let mut equipped_slot_id = String::new();
    for (index, slot) in inventory_slots_mut(inventory).iter_mut().enumerate() {
        let is_selected = index == selected_index;
        if let Some(object) = slot.as_object_mut() {
            object.insert("is_equipped".to_string(), json!(is_selected));
            if is_selected {
                equipped_item_entity_id = u64_field(slot, &["item_entity_id"]).unwrap_or_default();
                equipped_slot_id = string_field(slot, &["slot_id"]).unwrap_or("").to_string();
            }
        }
    }

    if let Some(object) = inventory.as_object_mut() {
        object.insert("equipped_slot_id".to_string(), json!(equipped_slot_id));
        object.insert(
            "equipped_item_entity_id".to_string(),
            json!(equipped_item_entity_id),
        );
    }

    if equipped_item_entity_id != 0 {
        if let Some(item_raw) = ctx.get_component(equipped_item_entity_id, type_ids::ITEM)? {
            let mut item = parse_json(item_raw);
            if let Some(object) = item.as_object_mut() {
                object.insert("is_equipped".to_string(), json!(true));
                object.insert("world_state".to_string(), json!("Equipped"));
                object.insert("last_inventory_tick".to_string(), json!(ctx.current_tick()));
            }
            ctx.submit_mutation(equipped_item_entity_id, type_ids::ITEM, item.to_string())?;
        }
    }

    emit_inventory_event(
        ctx,
        actor_id,
        equipped_item_entity_id,
        semantic_events::INVENTORY_EQUIPPED,
        "Equipped",
        "",
    )?;
    Ok(true)
}

fn handle_drop_intent(
    ctx: &mut dyn ISystemContext,
    actor_id: u64,
    input: &Value,
    inventory: &mut Value,
) -> std::result::Result<bool, XaceError> {
    let requested_slot = string_field(input, &["drop_slot_id", "inventory_slot_id"])
        .or_else(|| string_field(inventory, &["equipped_slot_id"]))
        .map(str::to_string);
    let requested_item_entity = u64_field(input, &["drop_item_entity_id", "item_entity_id"])
        .or_else(|| u64_field(inventory, &["equipped_item_entity_id"]));
    let Some(selected_index) =
        select_inventory_slot(inventory, requested_slot.as_deref(), requested_item_entity)
    else {
        emit_inventory_event(
            ctx,
            actor_id,
            0,
            semantic_events::INVENTORY_DROP_REJECTED,
            "DropRejected",
            "slot_not_found",
        )?;
        return Ok(false);
    };

    let dropped_slot = inventory_slots_mut(inventory).remove(selected_index);
    let item_entity_id = u64_field(&dropped_slot, &["item_entity_id"]).unwrap_or(0);
    let dropped_weight = number_field(&dropped_slot, &["weight"])
        .unwrap_or(Fixed64::ZERO)
        .max(Fixed64::ZERO);
    let weight_current = number_field(inventory, &["weight_current"]).unwrap_or(Fixed64::ZERO);
    set_number_field(
        inventory,
        "weight_current",
        (weight_current - dropped_weight).max(Fixed64::ZERO),
    );

    let dropped_slot_id = string_field(&dropped_slot, &["slot_id"]).unwrap_or("");
    let was_equipped = bool_field(&dropped_slot, &["is_equipped"]).unwrap_or(false)
        || string_field(inventory, &["equipped_slot_id"]).unwrap_or("") == dropped_slot_id;
    if was_equipped {
        if let Some(object) = inventory.as_object_mut() {
            object.insert("equipped_slot_id".to_string(), json!(""));
            object.insert("equipped_item_entity_id".to_string(), json!(0));
        }
    }

    if item_entity_id != 0 {
        if let Some(item_raw) = ctx.get_component(item_entity_id, type_ids::ITEM)? {
            let mut item = parse_json(item_raw);
            if let Some(object) = item.as_object_mut() {
                object.insert("owner_entity_id".to_string(), json!(0));
                object.insert("inventory_slot_id".to_string(), json!(""));
                object.insert("world_state".to_string(), json!("Dropped"));
                object.insert("is_pickable".to_string(), json!(true));
                object.insert("is_equipped".to_string(), json!(false));
                object.insert("last_inventory_tick".to_string(), json!(ctx.current_tick()));
            }
            ctx.submit_mutation(item_entity_id, type_ids::ITEM, item.to_string())?;
        }
        if let Some(interaction_raw) = ctx.get_component(item_entity_id, type_ids::INTERACTION)? {
            let mut interaction = parse_json(interaction_raw);
            if let Some(object) = interaction.as_object_mut() {
                object.insert("is_interactable".to_string(), json!(true));
                object.insert("last_interactor_entity_id".to_string(), json!(actor_id));
                object.insert(
                    "last_interaction_tick".to_string(),
                    json!(ctx.current_tick()),
                );
            }
            ctx.submit_mutation(
                item_entity_id,
                type_ids::INTERACTION,
                interaction.to_string(),
            )?;
        }
        if let Some(actor_transform) = ctx.get_component(actor_id, type_ids::TRANSFORM)? {
            if let Some(item_transform) = ctx.get_component(item_entity_id, type_ids::TRANSFORM)? {
                let (x, y, z) = parse_position_xyz(actor_transform);
                ctx.submit_mutation(
                    item_entity_id,
                    type_ids::TRANSFORM,
                    transform_json_from_existing(item_transform, x, y, z),
                )?;
            }
        }
    }

    emit_inventory_event(
        ctx,
        actor_id,
        item_entity_id,
        semantic_events::INVENTORY_DROPPED,
        "Dropped",
        "",
    )?;
    Ok(true)
}

fn ensure_inventory_shape(inventory: &mut Value) {
    if !inventory.is_object() {
        *inventory = json!({});
    }
    let Some(object) = inventory.as_object_mut() else {
        return;
    };
    if !object.get("slots").is_some_and(Value::is_array) {
        object.insert("slots".to_string(), json!([]));
    }
    object
        .entry("max_capacity".to_string())
        .or_insert(json!(20));
    object
        .entry("equipped_slot_id".to_string())
        .or_insert(json!(""));
    object
        .entry("equipped_item_entity_id".to_string())
        .or_insert(json!(0));
    object
        .entry("weight_current".to_string())
        .or_insert(fixed_value(Fixed64::ZERO));
    object
        .entry("weight_max".to_string())
        .or_insert(fixed_value(Fixed64::ZERO));
}

fn normalize_inventory_summary(inventory: &mut Value) {
    ensure_inventory_shape(inventory);
    let slots = inventory_slots(inventory);
    let current_count = slots.len() as u64;
    let item_ids = slots
        .iter()
        .filter_map(|slot| string_field(slot, &["item_id"]).map(str::to_string))
        .collect::<Vec<_>>();
    if let Some(object) = inventory.as_object_mut() {
        object.insert("current_count".to_string(), json!(current_count));
        object.insert("item_ids".to_string(), json!(item_ids));
    }
}

fn inventory_slots(inventory: &Value) -> Vec<Value> {
    inventory
        .get("slots")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn inventory_slots_mut(inventory: &mut Value) -> &mut Vec<Value> {
    ensure_inventory_shape(inventory);
    inventory
        .get_mut("slots")
        .and_then(Value::as_array_mut)
        .expect("ensure_inventory_shape must create slots array")
}

fn select_inventory_slot(
    inventory: &Value,
    slot_id: Option<&str>,
    item_entity_id: Option<u64>,
) -> Option<usize> {
    let slots = inventory.get("slots")?.as_array()?;
    if let Some(slot_id) = slot_id.filter(|value| !value.is_empty()) {
        if let Some(index) = slots
            .iter()
            .position(|slot| string_field(slot, &["slot_id"]) == Some(slot_id))
        {
            return Some(index);
        }
    }
    if let Some(item_entity_id) = item_entity_id.filter(|value| *value != 0) {
        if let Some(index) = slots
            .iter()
            .position(|slot| u64_field(slot, &["item_entity_id"]) == Some(item_entity_id))
        {
            return Some(index);
        }
    }
    (!slots.is_empty()).then_some(0)
}

fn emit_inventory_event(
    ctx: &mut dyn ISystemContext,
    actor_id: u64,
    item_entity_id: u64,
    event_name: &str,
    state: &str,
    reason: &str,
) -> std::result::Result<(), XaceError> {
    let event = Event::directed(
        actor_id,
        item_entity_id,
        semantic_events::domain_event(event_name),
        ctx.current_tick(),
        PhaseEnum::Simulation,
    )
    .with_payload("actor_entity_id", actor_id.to_string())
    .with_payload("item_entity_id", item_entity_id.to_string())
    .with_payload("inventory_state", state.to_string())
    .with_payload("reason", reason.to_string());
    ctx.emit_event(event)
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

fn parse_position_xyz(raw: &str) -> (Fixed64, Fixed64, Fixed64) {
    let value = parse_json(raw);
    (
        number_field(&value, &["position_x", "x"]).unwrap_or(Fixed64::ZERO),
        number_field(&value, &["position_y", "y"]).unwrap_or(Fixed64::ZERO),
        number_field(&value, &["position_z", "z"]).unwrap_or(Fixed64::ZERO),
    )
}

fn parse_velocity_xyz(raw: &str) -> (Fixed64, Fixed64, Fixed64) {
    let value = parse_json(raw);
    (
        number_field(&value, &["linear_x", "vx", "x"]).unwrap_or(Fixed64::ZERO),
        number_field(&value, &["linear_y", "vy", "y"]).unwrap_or(Fixed64::ZERO),
        number_field(&value, &["linear_z", "vz", "z"]).unwrap_or(Fixed64::ZERO),
    )
}

fn number_field(value: &Value, names: &[&str]) -> Option<Fixed64> {
    json_fixed_field(value, names, IntegerEncoding::RawMicroUnits)
}

fn u64_field(value: &Value, names: &[&str]) -> Option<u64> {
    json_u64_field(value, names)
}

fn bool_field(value: &Value, names: &[&str]) -> Option<bool> {
    names.iter().find_map(|name| value.get(*name)?.as_bool())
}

fn string_field<'a>(value: &'a Value, names: &[&str]) -> Option<&'a str> {
    names.iter().find_map(|name| value.get(*name)?.as_str())
}

fn normalize_xz(x: Fixed64, z: Fixed64, speed: Fixed64) -> (Fixed64, Fixed64) {
    let length = (x * x + z * z).sqrt();
    if length.is_zero() || speed <= Fixed64::ZERO {
        return (Fixed64::ZERO, Fixed64::ZERO);
    }
    let scale = speed.checked_div(length).unwrap_or(Fixed64::ZERO);
    (x * scale, z * scale)
}

fn velocity_json(vx: Fixed64, vy: Fixed64, vz: Fixed64) -> String {
    json!({
        "linear_x": fixed_value(vx),
        "linear_y": fixed_value(vy),
        "linear_z": fixed_value(vz)
    })
    .to_string()
}

fn velocity_json_from_existing(raw: &str, vx: Fixed64, vy: Fixed64, vz: Fixed64) -> String {
    let mut value = parse_json(raw);
    set_number_field(&mut value, "linear_x", vx);
    set_number_field(&mut value, "linear_y", vy);
    set_number_field(&mut value, "linear_z", vz);
    value.to_string()
}

fn transform_json_from_existing(raw: &str, x: Fixed64, y: Fixed64, z: Fixed64) -> String {
    let mut value = parse_json(raw);
    set_number_field(&mut value, "position_x", x);
    set_number_field(&mut value, "position_y", y);
    set_number_field(&mut value, "position_z", z);
    value.to_string()
}

fn set_number_field(value: &mut Value, field: &str, number: Fixed64) {
    set_json_fixed_field(value, field, number);
}

fn clamp_xz_to_bounds(transform: &Value, x: Fixed64, z: Fixed64) -> (Fixed64, Fixed64) {
    let min_x = number_field(
        transform,
        &["bounds_min_x", "world_min_x", "min_x", "clamp_min_x"],
    );
    let max_x = number_field(
        transform,
        &["bounds_max_x", "world_max_x", "max_x", "clamp_max_x"],
    );
    let min_z = number_field(
        transform,
        &["bounds_min_z", "world_min_z", "min_z", "clamp_min_z"],
    );
    let max_z = number_field(
        transform,
        &["bounds_max_z", "world_max_z", "max_z", "clamp_max_z"],
    );
    (
        clamp_optional(x, min_x, max_x),
        clamp_optional(z, min_z, max_z),
    )
}

fn clamp_optional(value: Fixed64, min: Option<Fixed64>, max: Option<Fixed64>) -> Fixed64 {
    let mut out = value;
    if let Some(min) = min {
        out = out.max(min);
    }
    if let Some(max) = max {
        out = out.min(max);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    use xace_core::entity_id::EntityID;
    use xace_core::entity_metadata::Tick;
    use xace_core::events::event_struct::Event;

    #[derive(Default)]
    struct MockContext {
        components: BTreeMap<(EntityID, u32), String>,
        mutations: Vec<(EntityID, u32, String)>,
        events: Vec<Event>,
    }

    impl MockContext {
        fn with_component(mut self, entity_id: EntityID, type_id: u32, value: Value) -> Self {
            self.components
                .insert((entity_id, type_id), value.to_string());
            self
        }
    }

    impl ISystemContext for MockContext {
        fn get_component(
            &self,
            entity_id: EntityID,
            component_type_id: u32,
        ) -> std::result::Result<Option<&str>, XaceError> {
            Ok(self
                .components
                .get(&(entity_id, component_type_id))
                .map(String::as_str))
        }

        fn query_entities(
            &self,
            component_type_ids: &[u32],
        ) -> std::result::Result<Vec<EntityID>, XaceError> {
            let mut ids = self
                .components
                .keys()
                .map(|(entity_id, _)| *entity_id)
                .collect::<Vec<_>>();
            ids.sort();
            ids.dedup();
            ids.retain(|entity_id| {
                component_type_ids
                    .iter()
                    .all(|type_id| self.components.contains_key(&(*entity_id, *type_id)))
            });
            Ok(ids)
        }

        fn submit_mutation(
            &mut self,
            entity_id: EntityID,
            component_type_id: u32,
            component_json: String,
        ) -> std::result::Result<(), XaceError> {
            self.mutations
                .push((entity_id, component_type_id, component_json));
            Ok(())
        }

        fn submit_spawn(
            &mut self,
            _actor_id: String,
            _initial_components: BTreeMap<u32, String>,
        ) -> std::result::Result<(), XaceError> {
            Ok(())
        }

        fn submit_destroy(&mut self, _entity_id: EntityID) -> std::result::Result<(), XaceError> {
            Ok(())
        }

        fn emit_event(&mut self, event: Event) -> std::result::Result<(), XaceError> {
            self.events.push(event);
            Ok(())
        }

        fn current_tick(&self) -> Tick {
            1
        }

        fn next_random(&mut self) -> std::result::Result<Fixed64, XaceError> {
            Ok(Fixed64::ZERO)
        }
    }

    fn fv_units(units: i64) -> Value {
        fixed_value(Fixed64::from_units(units))
    }

    fn fv_millis(millis: i64) -> Value {
        fixed_value(Fixed64::from_millis(millis))
    }

    #[test]
    fn normalize_xz_scales_to_speed() {
        let (x, z) = normalize_xz(
            Fixed64::from_units(3),
            Fixed64::from_units(4),
            Fixed64::from_units(10),
        );
        assert_eq!(x, Fixed64::from_units(6));
        assert_eq!(z, Fixed64::from_units(8));
    }

    #[test]
    fn input_system_stops_velocity_when_idle_input_arrives() {
        let mut ctx = MockContext::default()
            .with_component(
                1,
                type_ids::INPUT,
                json!({ "move_x": fv_units(0), "move_z": fv_units(0) }),
            )
            .with_component(
                1,
                type_ids::VELOCITY,
                json!({
                    "linear_x": fv_units(4),
                    "linear_y": fv_units(0),
                    "linear_z": fv_units(3),
                    "max_linear_speed": fv_units(6)
                }),
            );

        InputSystem.execute(&mut ctx).unwrap();

        assert_eq!(ctx.mutations.len(), 1);
        let value = parse_json(&ctx.mutations[0].2);
        assert_eq!(number_field(&value, &["linear_x"]), Some(Fixed64::ZERO));
        assert_eq!(number_field(&value, &["linear_z"]), Some(Fixed64::ZERO));
        assert_eq!(
            number_field(&value, &["max_linear_speed"]),
            Some(Fixed64::from_units(6))
        );
    }

    #[test]
    fn movement_system_clamps_to_transform_bounds_and_preserves_fields() {
        let mut ctx = MockContext::default()
            .with_component(
                1,
                type_ids::TRANSFORM,
                json!({
                    "position_x": fv_millis(11900),
                    "position_y": fv_units(0),
                    "position_z": fv_millis(-11900),
                    "rotation_y": fv_units(45),
                    "bounds_min_x": fv_units(-12),
                    "bounds_max_x": fv_units(12),
                    "bounds_min_z": fv_units(-12),
                    "bounds_max_z": fv_units(12)
                }),
            )
            .with_component(
                1,
                type_ids::VELOCITY,
                json!({ "linear_x": fv_units(60), "linear_y": fv_units(0), "linear_z": fv_units(-60) }),
            );

        MovementSystem.execute(&mut ctx).unwrap();

        assert_eq!(ctx.mutations.len(), 1);
        let value = parse_json(&ctx.mutations[0].2);
        assert_eq!(
            number_field(&value, &["position_x"]),
            Some(Fixed64::from_units(12))
        );
        assert_eq!(
            number_field(&value, &["position_z"]),
            Some(Fixed64::from_units(-12))
        );
        assert_eq!(
            number_field(&value, &["rotation_y"]),
            Some(Fixed64::from_units(45))
        );
        assert_eq!(
            number_field(&value, &["bounds_max_x"]),
            Some(Fixed64::from_units(12))
        );
    }

    #[test]
    fn interaction_system_focuses_nearest_interactable_in_range() {
        let mut ctx = MockContext::default()
            .with_component(
                1,
                type_ids::INPUT,
                json!({ "interact_started": false, "move_x": fv_units(0), "move_z": fv_units(0) }),
            )
            .with_component(
                1,
                type_ids::TRANSFORM,
                json!({ "position_x": fv_units(0), "position_y": fv_units(0), "position_z": fv_units(0) }),
            )
            .with_component(
                2,
                type_ids::TRANSFORM,
                json!({ "position_x": fv_units(1), "position_y": fv_units(0), "position_z": fv_units(0) }),
            )
            .with_component(
                2,
                type_ids::INTERACTION,
                json!({
                    "interaction_type": "Open",
                    "range": fv_units(2),
                    "is_interactable": true,
                    "prompt_text": "Open"
                }),
            )
            .with_component(
                3,
                type_ids::TRANSFORM,
                json!({ "position_x": fv_units(4), "position_y": fv_units(0), "position_z": fv_units(0) }),
            )
            .with_component(
                3,
                type_ids::INTERACTION,
                json!({
                    "interaction_type": "Talk",
                    "range": fv_units(2),
                    "is_interactable": true,
                    "prompt_text": "Talk"
                }),
            );

        InteractionSystem.execute(&mut ctx).unwrap();

        assert_eq!(ctx.mutations.len(), 1);
        assert_eq!(ctx.mutations[0].0, 1);
        assert_eq!(ctx.mutations[0].1, type_ids::INPUT);
        let input = parse_json(&ctx.mutations[0].2);
        assert_eq!(u64_field(&input, &["focused_entity_id"]), Some(2));
        assert_eq!(
            string_field(&input, &["focused_interaction_type"]),
            Some("Open")
        );
        assert_eq!(bool_field(&input, &["can_interact"]), Some(true));
        assert_eq!(ctx.events.len(), 1);
        assert_eq!(
            ctx.events[0].event_type.name(),
            "Domain(interaction.focused)"
        );
    }

    #[test]
    fn interaction_system_accepts_general_interaction_intent() {
        let mut ctx = MockContext::default()
            .with_component(
                1,
                type_ids::INPUT,
                json!({
                    "interact_started": true,
                    "focused_entity_id": 0,
                    "move_x": fv_units(0),
                    "move_z": fv_units(0)
                }),
            )
            .with_component(
                1,
                type_ids::TRANSFORM,
                json!({ "position_x": fv_units(0), "position_y": fv_units(0), "position_z": fv_units(0) }),
            )
            .with_component(
                2,
                type_ids::TRANSFORM,
                json!({ "position_x": fv_units(1), "position_y": fv_units(0), "position_z": fv_units(0) }),
            )
            .with_component(
                2,
                type_ids::INTERACTION,
                json!({
                    "interaction_type": "Activate",
                    "range": fv_units(2),
                    "is_interactable": true,
                    "prompt_text": "Activate",
                    "interaction_count": 0,
                    "max_interactions": 0
                }),
            );

        InteractionSystem.execute(&mut ctx).unwrap();

        assert_eq!(ctx.mutations.len(), 2);
        let target_update = ctx
            .mutations
            .iter()
            .find(|(entity_id, type_id, _)| *entity_id == 2 && *type_id == type_ids::INTERACTION)
            .expect("interaction target should be mutated");
        let interaction = parse_json(&target_update.2);
        assert_eq!(u64_field(&interaction, &["interaction_count"]), Some(1));
        assert_eq!(
            u64_field(&interaction, &["last_interactor_entity_id"]),
            Some(1)
        );
        assert!(ctx
            .events
            .iter()
            .any(|event| event.event_type.name() == "Domain(interaction.accepted)"));
        assert!(ctx
            .events
            .iter()
            .any(|event| event.event_type.name() == "Domain(interaction.interacted)"));
    }

    #[test]
    fn inventory_system_picks_up_general_item() {
        let mut ctx = MockContext::default()
            .with_component(
                1,
                type_ids::INPUT,
                json!({ "pickup_started": true, "focused_entity_id": 2 }),
            )
            .with_component(
                1,
                type_ids::INVENTORY,
                json!({
                    "slots": [],
                    "max_capacity": 4,
                    "current_count": 0,
                    "weight_current": fv_units(0),
                    "weight_max": fv_units(10)
                }),
            )
            .with_component(
                2,
                type_ids::ITEM,
                json!({
                    "item_id": "item_key",
                    "display_name": "Key",
                    "quantity": 1,
                    "weight": fv_millis(200),
                    "slot_type": "utility",
                    "is_pickable": true,
                    "owner_entity_id": 0,
                    "world_state": "World"
                }),
            )
            .with_component(
                2,
                type_ids::INTERACTION,
                json!({
                    "interaction_type": "PickUp",
                    "is_interactable": true,
                    "prompt_text": "Pick up"
                }),
            );

        InventorySystem.execute(&mut ctx).unwrap();

        let inventory_update = ctx
            .mutations
            .iter()
            .find(|(entity_id, type_id, _)| *entity_id == 1 && *type_id == type_ids::INVENTORY)
            .expect("inventory should be updated");
        let inventory = parse_json(&inventory_update.2);
        let slots = inventory.get("slots").and_then(Value::as_array).unwrap();
        assert_eq!(slots.len(), 1);
        assert_eq!(string_field(&slots[0], &["item_id"]), Some("item_key"));
        assert_eq!(u64_field(&inventory, &["current_count"]), Some(1));

        let item_update = ctx
            .mutations
            .iter()
            .find(|(entity_id, type_id, _)| *entity_id == 2 && *type_id == type_ids::ITEM)
            .expect("item should be marked owned");
        let item = parse_json(&item_update.2);
        assert_eq!(u64_field(&item, &["owner_entity_id"]), Some(1));
        assert_eq!(string_field(&item, &["world_state"]), Some("InInventory"));
        assert_eq!(bool_field(&item, &["is_pickable"]), Some(false));
        assert!(ctx
            .events
            .iter()
            .any(|event| event.event_type.name() == "Domain(inventory.pickup_accepted)"));
    }

    #[test]
    fn inventory_system_equips_requested_slot() {
        let mut ctx = MockContext::default()
            .with_component(
                1,
                type_ids::INPUT,
                json!({ "equip_started": true, "equip_slot_id": "slot_2" }),
            )
            .with_component(
                1,
                type_ids::INVENTORY,
                json!({
                    "slots": [{
                        "slot_id": "slot_2",
                        "item_id": "item_tool",
                        "item_entity_id": 2,
                        "quantity": 1,
                        "slot_type": "hand",
                        "is_equipped": false
                    }],
                    "max_capacity": 4,
                    "current_count": 1,
                    "equipped_slot_id": "",
                    "equipped_item_entity_id": 0
                }),
            )
            .with_component(
                2,
                type_ids::ITEM,
                json!({
                    "item_id": "item_tool",
                    "owner_entity_id": 1,
                    "world_state": "InInventory",
                    "is_equipped": false
                }),
            );

        InventorySystem.execute(&mut ctx).unwrap();

        let inventory_update = ctx
            .mutations
            .iter()
            .find(|(entity_id, type_id, _)| *entity_id == 1 && *type_id == type_ids::INVENTORY)
            .expect("inventory should be updated");
        let inventory = parse_json(&inventory_update.2);
        assert_eq!(
            string_field(&inventory, &["equipped_slot_id"]),
            Some("slot_2")
        );
        assert_eq!(u64_field(&inventory, &["equipped_item_entity_id"]), Some(2));
        let item_update = ctx
            .mutations
            .iter()
            .find(|(entity_id, type_id, _)| *entity_id == 2 && *type_id == type_ids::ITEM)
            .expect("item should be marked equipped");
        let item = parse_json(&item_update.2);
        assert_eq!(bool_field(&item, &["is_equipped"]), Some(true));
        assert_eq!(string_field(&item, &["world_state"]), Some("Equipped"));
    }

    #[test]
    fn inventory_system_drops_equipped_item_to_world() {
        let mut ctx = MockContext::default()
            .with_component(1, type_ids::INPUT, json!({ "drop_started": true }))
            .with_component(
                1,
                type_ids::INVENTORY,
                json!({
                    "slots": [{
                        "slot_id": "slot_2",
                        "item_id": "item_tool",
                        "item_entity_id": 2,
                        "quantity": 1,
                        "weight": fv_millis(1500),
                        "is_equipped": true
                    }],
                    "max_capacity": 4,
                    "current_count": 1,
                    "equipped_slot_id": "slot_2",
                    "equipped_item_entity_id": 2,
                    "weight_current": fv_millis(1500)
                }),
            )
            .with_component(
                1,
                type_ids::TRANSFORM,
                json!({ "position_x": fv_units(3), "position_y": fv_units(0), "position_z": fv_units(-4) }),
            )
            .with_component(
                2,
                type_ids::ITEM,
                json!({
                    "item_id": "item_tool",
                    "owner_entity_id": 1,
                    "world_state": "Equipped",
                    "is_equipped": true,
                    "is_pickable": false
                }),
            )
            .with_component(
                2,
                type_ids::INTERACTION,
                json!({ "interaction_type": "PickUp", "is_interactable": false }),
            )
            .with_component(
                2,
                type_ids::TRANSFORM,
                json!({ "position_x": fv_units(0), "position_y": fv_units(0), "position_z": fv_units(0) }),
            );

        InventorySystem.execute(&mut ctx).unwrap();

        let inventory_update = ctx
            .mutations
            .iter()
            .find(|(entity_id, type_id, _)| *entity_id == 1 && *type_id == type_ids::INVENTORY)
            .expect("inventory should be updated");
        let inventory = parse_json(&inventory_update.2);
        assert_eq!(
            inventory
                .get("slots")
                .and_then(Value::as_array)
                .map(Vec::len),
            Some(0)
        );
        assert_eq!(u64_field(&inventory, &["equipped_item_entity_id"]), Some(0));

        let item_update = ctx
            .mutations
            .iter()
            .find(|(entity_id, type_id, _)| *entity_id == 2 && *type_id == type_ids::ITEM)
            .expect("item should be dropped");
        let item = parse_json(&item_update.2);
        assert_eq!(u64_field(&item, &["owner_entity_id"]), Some(0));
        assert_eq!(string_field(&item, &["world_state"]), Some("Dropped"));
        assert_eq!(bool_field(&item, &["is_pickable"]), Some(true));

        let transform_update = ctx
            .mutations
            .iter()
            .find(|(entity_id, type_id, _)| *entity_id == 2 && *type_id == type_ids::TRANSFORM)
            .expect("item transform should move to actor");
        let transform = parse_json(&transform_update.2);
        assert_eq!(
            number_field(&transform, &["position_x"]),
            Some(Fixed64::from_units(3))
        );
        assert_eq!(
            number_field(&transform, &["position_z"]),
            Some(Fixed64::from_units(-4))
        );
        assert!(ctx
            .events
            .iter()
            .any(|event| event.event_type.name() == "Domain(inventory.dropped)"));
    }
}

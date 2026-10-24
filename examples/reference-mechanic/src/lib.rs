//! Removable reference gameplay package. No XACE core crate depends on this crate.
//! All mechanic-specific rules, names, configuration and state live here.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::{event_struct::Event, event_type::EventType};
use xace_core::fixed_point::Fixed64;
use xace_core::geometry::*;
use xace_core::runtime::phase_enum::PhaseEnum;

pub const SYSTEM_ID: &str = "reference.traversal.v1";
pub const STATE_ID: u32 = 10000;
pub const CONFIG_ID: u32 = 10001;
pub const SURFACE_CAPABILITY: &str = "reference.wall_runnable.v1";
const SCALE: i64 = 1_000_000;
const MAX_SPEED: i64 = 60 * MAX_DISPLACEMENT_RAW;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ThirdAttempt {
    Disabled,
    ReversalShockwave,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub schema_version: u32,
    pub surface_capability: String,
    pub run_speed: i64,
    pub jump_speed: i64,
    pub away_speed: i64,
    pub gravity_per_tick: i64,
    pub side_probe: i64,
    pub ground_probe: i64,
    pub third_attempt: ThirdAttempt,
    pub shockwave_radius: i64,
    pub shockwave_impulse: i64,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            schema_version: 1,
            surface_capability: SURFACE_CAPABILITY.into(),
            run_speed: 5 * SCALE,
            jump_speed: 8 * SCALE,
            away_speed: 6 * SCALE,
            gravity_per_tick: 163_500,
            side_probe: 100_000,
            ground_probe: 1_000,
            third_attempt: ThirdAttempt::Disabled,
            shockwave_radius: 5 * SCALE,
            shockwave_impulse: 3 * SCALE,
        }
    }
}
impl Config {
    pub fn validate(&self) -> Result<(), XaceError> {
        if self.schema_version != 1
            || !xace_core::world::valid_semantic_capability(&self.surface_capability)
            || [
                self.run_speed,
                self.jump_speed,
                self.away_speed,
                self.shockwave_impulse,
            ]
            .iter()
            .any(|v| !(1..=20 * SCALE).contains(v))
            || !(0..=SCALE).contains(&self.gravity_per_tick)
            || !(1..=SCALE).contains(&self.side_probe)
            || !(1..=10_000).contains(&self.ground_probe)
            || !(1..=16 * SCALE).contains(&self.shockwave_radius)
        {
            return Err(invalid("unsupported reference configuration"));
        }
        Ok(())
    }
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub schema_version: u32,
    pub chain: u8,
    pub third_used: bool,
    pub grounded: bool,
    pub jump_held: bool,
    pub wall_entity: u64,
    pub wall_axis: u8,
    pub wall_sign: i8,
    pub mode: String,
}
impl Default for State {
    fn default() -> Self {
        Self {
            schema_version: 1,
            chain: 0,
            third_used: false,
            grounded: false,
            jump_held: false,
            wall_entity: 0,
            wall_axis: 0,
            wall_sign: 0,
            mode: "airborne".into(),
        }
    }
}
fn invalid(message: &str) -> XaceError {
    XaceError::ValidationFailure {
        message: message.into(),
        context: ErrorContext::new("reference.traversal.v1", "execute"),
        rule_violated: "ReferencePackage".into(),
        failed_path: SYSTEM_ID.into(),
    }
}
fn payload(ctx: &dyn ISystemContext, id: u64, kind: u32) -> Result<Value, XaceError> {
    serde_json::from_str(
        ctx.get_component(id, kind)?
            .ok_or_else(|| invalid("missing package component"))?,
    )
    .map_err(|_| invalid("malformed package component"))
}
fn vector(value: &Value) -> Result<[i64; 3], XaceError> {
    let mut out = [0; 3];
    for (i, k) in ["x", "y", "z"].iter().enumerate() {
        out[i] = value
            .get(k)
            .and_then(Value::as_i64)
            .ok_or_else(|| invalid("expected fixed-point integer vector"))?;
    }
    Ok(out)
}
fn fixed(v: [i64; 3]) -> [Fixed64; 3] {
    v.map(Fixed64::from_raw)
}
fn store_vector(value: &mut Value, v: [i64; 3]) {
    *value = json!({"x":v[0],"y":v[1],"z":v[2]});
}
fn contacts(
    ctx: &mut dyn ISystemContext,
    b: Aabb,
    d: [i64; 3],
    id: u64,
) -> Result<Vec<GeometryContact>, XaceError> {
    match ctx.geometry_query_v1(&GeometryQueryV1::Sweep {
        bounds: b,
        displacement: fixed(d),
        filter: GeometryFilter {
            exclude: Some(id),
            ..GeometryFilter::default()
        },
    })? {
        GeometryResultV1::Contacts(h) => Ok(h),
        _ => Err(invalid("unexpected geometry result")),
    }
}
fn emit(ctx: &mut dyn ISystemContext, id: u64, name: &str, chain: u8) -> Result<(), XaceError> {
    ctx.emit_event(
        Event::broadcast(
            id,
            EventType::Domain(format!("reference.{name}.v1")),
            ctx.current_tick(),
            PhaseEnum::Simulation,
        )
        .with_payload("chain", chain.to_string()),
    )?;
    // Keep the custom gameplay event, and publish the existing presentation
    // contract for native playback. This does not register arbitrary new names.
    if matches!(name, "ground_jump" | "wall_jump") {
        ctx.emit_event(
            Event::broadcast(
                id,
                xace_core::events::semantic_event_registry::domain_event(
                    xace_core::events::semantic_event_registry::MOVEMENT_JUMP_STARTED,
                ),
                ctx.current_tick(),
                PhaseEnum::Simulation,
            )
            .with_payload("actor_entity_id", id.to_string())
            .with_payload("movement_state", "airborne"),
        )?;
    }
    Ok(())
}
struct Row {
    transform: Value,
    velocity: Value,
    linear: [i64; 3],
    state: State,
    origin: [Fixed64; 3],
    config: Config,
}
/// Constructed by this package's ordinary catalog registration, never core orchestration.
#[derive(Default)]
pub struct ReferenceSystem;
impl ISystem for ReferenceSystem {
    fn system_id(&self) -> &str {
        SYSTEM_ID
    }
    fn declared_reads(&self) -> &[u32] {
        &[1, 4, 5, 6, STATE_ID, CONFIG_ID]
    }
    fn declared_writes(&self) -> &[u32] {
        &[1, 5, STATE_ID]
    }
    fn execute(&self, ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
        let ids = ctx.query_entities(&[STATE_ID])?;
        let mut rows = BTreeMap::new();
        let mut shocks = Vec::new();
        for id in &ids {
            let cfg: Config = serde_json::from_value(payload(ctx, *id, CONFIG_ID)?)
                .map_err(|_| invalid("invalid reference configuration"))?;
            cfg.validate()?;
            let mut transform = payload(ctx, *id, 1)?;
            let velocity = payload(ctx, *id, 5)?;
            let input = payload(ctx, *id, 6)?;
            let collider = payload(ctx, *id, 4)?;
            let mut state: State = serde_json::from_value(payload(ctx, *id, STATE_ID)?)
                .map_err(|_| invalid("invalid reference state"))?;
            if state.schema_version != 1
                || state.chain > 2
                || (state.third_used && state.chain != 2)
            {
                return Err(invalid("unsupported reference state/version"));
            }
            let p = vector(&transform["position"])?;
            let offset = vector(&collider["offset"])?;
            let size = vector(&collider["size"])?;
            if size.iter().any(|v| *v <= 0 || *v % 2 != 0) {
                return Err(invalid("invalid actor box"));
            }
            let mut center = [0; 3];
            for i in 0..3 {
                center[i] = p[i]
                    .checked_add(offset[i])
                    .ok_or_else(|| invalid("actor position overflow"))?;
            }
            let bounds = Aabb {
                center: fixed(center),
                half_extents: fixed(size.map(|n| n / 2)),
            };
            let origin = bounds.center;
            let mut linear = vector(&velocity["linear"])?;
            if linear.iter().any(|v| !(-MAX_SPEED..=MAX_SPEED).contains(v)) {
                return Err(invalid("velocity exceeds fixture bounds"));
            }
            let axis = |name: &str| -> Result<i64, XaceError> {
                // Same Fixed64 JSON convention as ordinary runtime input systems:
                // integers are microunits, decimal numbers are unit values.
                let v = xace_runtime_core::fixed_json::fixed_field(
                    &input, &[name], xace_runtime_core::fixed_json::IntegerEncoding::RawMicroUnits,
                ).or_else(|| if input.get(name).is_none() { Some(Fixed64::ZERO) } else { None })
                .ok_or_else(|| invalid("invalid semantic input axis"))?.raw();
                if !(-SCALE..=SCALE).contains(&v) {
                    return Err(invalid("input axis outside quantization"));
                }
                Ok(v)
            };
            let mx = axis("move_x")?;
            let mz = axis("move_z")?;
            let held = input
                .get("jump_pressed")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let edge = held && !state.jump_held;
            state.jump_held = held;
            let ground = contacts(ctx, bounds, [0, -cfg.ground_probe, 0], *id)?;
            if ground.iter().any(|h| h.initial_overlap) {
                return Err(invalid("reference actor starts penetrating geometry"));
            }
            state.grounded = linear[1] <= 0
                && ground
                    .first()
                    .is_some_and(|h| h.normal == AxisNormal::PositiveY);
            if state.grounded {
                state.chain = 0;
                state.third_used = false;
                linear[1] = 0;
            }
            let mut walls = Vec::new();
            for direction in [
                AxisNormal::NegativeX,
                AxisNormal::PositiveX,
                AxisNormal::NegativeZ,
                AxisNormal::PositiveZ,
            ] {
                let mut d = [0; 3];
                d[direction.axis()] = cfg.side_probe * direction.sign();
                if let Some(h) = contacts(ctx, bounds, d, *id)?.first() {
                    if ctx
                        .world_capabilities_v1(h.entity_id)?
                        .iter()
                        .any(|c| c == &cfg.surface_capability)
                    {
                        walls.push(h.clone());
                    }
                }
            }
            walls.sort_by(|a, b| {
                ((a.time_numerator as u128) * (b.time_denominator as u128))
                    .cmp(&((b.time_numerator as u128) * (a.time_denominator as u128)))
                    .then(
                        (a.object_id.is_none(), &a.object_id, a.entity_id, a.normal).cmp(&(
                            b.object_id.is_none(),
                            &b.object_id,
                            b.entity_id,
                            b.normal,
                        )),
                    )
            });
            let wall = walls.first();
            state.wall_entity = wall.map_or(0, |h| h.entity_id);
            state.wall_axis = wall.map_or(0, |h| h.normal.axis() as u8);
            state.wall_sign = wall.map_or(0, |h| h.normal.sign() as i8);
            if state.grounded || mx != 0 || mz != 0 {
                linear[0] = mx * cfg.run_speed / SCALE;
                linear[2] = mz * cfg.run_speed / SCALE;
            }
            state.mode = if state.grounded {
                "grounded"
            } else {
                "airborne"
            }
            .into();
            if !state.grounded {
                linear[1] = (linear[1] - cfg.gravity_per_tick).max(-20 * SCALE);
            }
            if let Some(h) = wall {
                if !state.grounded && (mx != 0 || mz != 0) {
                    state.mode = "wall_running".into();
                    linear[h.normal.axis()] = 0;
                    linear[1] = linear[1].max(0);
                }
            }
            if edge {
                if state.grounded {
                    linear[1] = cfg.jump_speed;
                    state.grounded = false;
                    state.mode = "airborne".into();
                    emit(ctx, *id, "ground_jump", state.chain)?;
                } else if let Some(h) = wall {
                    if state.chain < 2 {
                        state.chain += 1;
                        linear[h.normal.axis()] = cfg.away_speed * h.normal.sign();
                        linear[1] = cfg.jump_speed;
                        state.mode = "airborne".into();
                        emit(ctx, *id, "wall_jump", state.chain)?;
                    } else if cfg.third_attempt == ThirdAttempt::ReversalShockwave
                        && !state.third_used
                    {
                        state.third_used = true;
                        linear[0] = -linear[0];
                        linear[2] = -linear[2];
                        linear[1] = cfg.jump_speed;
                        state.mode = "airborne".into();
                        shocks.push(*id);
                        emit(ctx, *id, "third_attempt", state.chain)?;
                    } else {
                        emit(ctx, *id, "jump_denied", state.chain)?;
                    }
                }
            }
            // Swept slide response belongs to the fixture, not the generic query engine.
            let mut b = bounds;
            let mut remaining = linear.map(|n| n / 60);
            for _ in 0..3 {
                if remaining == [0; 3] {
                    break;
                }
                let hits = contacts(ctx, b, remaining, *id)?;
                if let Some(h) = hits.first() {
                    if h.initial_overlap {
                        return Err(invalid("initial overlap requires an explicit spawn repair"));
                    }
                    for i in 0..3 {
                        b.center[i] = Fixed64::from_raw(b.center[i].raw() + h.travel[i].raw());
                        remaining[i] -= h.travel[i].raw();
                    }
                    let axis = h.normal.axis();
                    remaining[axis] = 0;
                    linear[axis] = 0;
                    if h.normal == AxisNormal::PositiveY {
                        state.grounded = true;
                        state.chain = 0;
                        state.third_used = false;
                        state.mode = "grounded".into();
                    }
                } else {
                    for i in 0..3 {
                        b.center[i] = Fixed64::from_raw(b.center[i].raw() + remaining[i]);
                    }
                    break;
                }
            }
            store_vector(
                &mut transform["position"],
                std::array::from_fn(|i| b.center[i].raw() - offset[i]),
            );
            rows.insert(
                *id,
                Row {
                    transform,
                    velocity,
                    linear,
                    state,
                    origin,
                    config: cfg,
                },
            );
        }
        // Accumulate effects before a single write per actor; simultaneous actors cannot overwrite each other.
        for source in shocks {
            let cfg = rows[&source].config.clone();
            let origin = rows[&source].origin;
            emit(ctx, source, "shockwave", rows[&source].state.chain)?;
            for target in &ids {
                if *target != source {
                    let result = ctx.geometry_query_v1(&GeometryQueryV1::Nearest {
                        origin,
                        max_distance: Fixed64::from_raw(cfg.shockwave_radius),
                        candidates: vec![*target],
                    })?;
                    if matches!(result, GeometryResultV1::Nearest(Some(_))) {
                        let row = rows.get_mut(target).unwrap();
                        let mut signs = [0; 3];
                        for i in [0, 2] {
                            signs[i] = (row.origin[i].raw() - origin[i].raw()).signum();
                        }
                        if signs == [0; 3] {
                            signs[0] = if *target > source { 1 } else { -1 };
                        }
                        for i in [0, 2] {
                            row.linear[i] = row.linear[i]
                                .checked_add(signs[i] * cfg.shockwave_impulse)
                                .ok_or_else(|| invalid("shockwave overflow"))?;
                        }
                        ctx.emit_event(Event::directed(
                            source,
                            *target,
                            EventType::Domain("reference.shockwave_hit.v1".into()),
                            ctx.current_tick(),
                            PhaseEnum::Simulation,
                        ))?;
                    }
                }
            }
        }
        for (id, mut row) in rows {
            if row
                .linear
                .iter()
                .any(|v| !(-MAX_SPEED..=MAX_SPEED).contains(v))
            {
                return Err(invalid("combined impulse exceeds bound"));
            }
            store_vector(&mut row.velocity["linear"], row.linear);
            ctx.submit_mutation(id, 1, row.transform.to_string())?;
            ctx.submit_mutation(id, 5, row.velocity.to_string())?;
            ctx.submit_mutation(
                id,
                STATE_ID,
                serde_json::to_string(&row.state).map_err(|_| invalid("state serialization"))?,
            )?;
        }
        Ok(())
    }
}

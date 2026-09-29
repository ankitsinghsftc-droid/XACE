//! Bounded integer-only geometry. No engine contacts, mutable world state, or persistent cache.
use serde::Deserialize;
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use xace_core::contracts::interfaces::ISystemContext;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::fixed_point::{Fixed64, FIXED64_SCALE};
use xace_core::geometry::*;
use xace_core::wire::session_contract::ContractId;
use xace_core::world::{WORLD_COORDINATE_LIMIT, WORLD_MAX_OBJECTS};

pub(crate) fn invalid(message: impl Into<String>) -> XaceError {
    XaceError::ValidationFailure {
        message: message.into(),
        context: ErrorContext::new("Geometry", "query_v1"),
        rule_violated: "XP-004".into(),
        failed_path: "geometry_query_v1".into(),
    }
}
fn raw(v: [Fixed64; 3]) -> [i64; 3] {
    v.map(Fixed64::raw)
}
fn point(p: [i64; 3]) -> Result<(), XaceError> {
    if p.iter()
        .any(|v| !(-WORLD_COORDINATE_LIMIT..=WORLD_COORDINATE_LIMIT).contains(v))
    {
        return Err(invalid("position outside portable world bounds"));
    }
    Ok(())
}
fn edges(b: Aabb) -> Result<([i64; 3], [i64; 3]), XaceError> {
    let c = raw(b.center);
    let h = raw(b.half_extents);
    point(c)?;
    if h.iter()
        .any(|v| !(1..=WORLD_COORDINATE_LIMIT / 2).contains(v))
    {
        return Err(invalid(
            "box extents must be positive and within portable bounds",
        ));
    }
    let lo = std::array::from_fn(|i| c[i] - h[i]);
    let hi = std::array::from_fn(|i| c[i] + h[i]);
    point(lo)?;
    point(hi)?;
    Ok((lo, hi))
}
#[derive(Debug, Clone, Copy)]
struct Ratio(i128, i128);
impl Ratio {
    fn cmp(self, other: Self) -> Ordering {
        (self.0 * other.1).cmp(&(other.0 * self.1))
    }
}
fn fraction(mut n: u64, mut d: u64) -> (u64, u64) {
    let (a, b) = (n, d);
    while d != 0 {
        let r = n % d;
        n = d;
        d = r;
    }
    (a / n, b / n)
}
#[derive(Debug, Clone)]
pub struct GeometryBody {
    pub object_id: Option<ContractId>,
    pub entity_id: u64,
    pub bounds: Aabb,
    pub is_trigger: bool,
    pub layer_mask: u32,
}
/// Derived immutable view, sorted by bound object ID then unbound EntityID.
/// Recreate after component changes/restore.
#[derive(Debug)]
pub struct GeometryScene {
    bodies: Vec<GeometryBody>,
}

/// Immutable semantic identity binding. Reinstall on a new package/world activation;
/// ordinary snapshot restores preserve EntityIDs and reuse this same binding.
#[derive(Debug)]
pub struct WorldGeometryBindings {
    objects: BTreeMap<u64, ContractId>,
    capabilities: BTreeMap<u64, Vec<String>>,
    semantic_objects: BTreeMap<u64, Vec<xace_core::world::v3::SemanticObject>>,
    profile_entities: Option<BTreeSet<u64>>,
}
impl WorldGeometryBindings {
    pub fn object_entity_ids(&self) -> BTreeMap<String, String> {
        if !self.semantic_objects.is_empty() {
            self.semantic_objects.iter().flat_map(|(entity, objects)| {
                objects.iter().map(move |object| (String::from(object.id.clone()), entity.to_string()))
            }).collect()
        } else {
            self.objects.iter().map(|(entity, object)| (String::from(object.clone()), entity.to_string())).collect()
        }
    }

    pub fn new(
        world: &xace_core::world::WorldContract,
        actors: &BTreeMap<ContractId, u64>,
    ) -> Result<Self, XaceError> {
        world.validate().map_err(invalid)?;
        let mut objects = BTreeMap::new();
        let mut capabilities = BTreeMap::new();
        for object in &world.objects {
            let id = *actors
                .get(&object.actor_id)
                .ok_or_else(|| invalid("missing world actor binding"))?;
            capabilities.insert(id, object.capabilities.clone());
            if id == 0 || objects.insert(id, object.id.clone()).is_some() {
                return Err(invalid(
                    "world actor bindings must reference distinct nonzero entities",
                ));
            }
        }
        Ok(Self {
            objects,
            capabilities,
            semantic_objects: BTreeMap::new(),
            profile_entities: None,
        })
    }
    pub fn from_v3(
        world: &xace_core::world::v3::WorldContractV3,
        instances: &BTreeMap<(ContractId, u32), u64>,
    ) -> Result<Self, XaceError> {
        world
            .admit(&xace_core::world::v3::supported_geometry_profiles())
            .map_err(invalid)?;
        let mut result = Self {
            objects: BTreeMap::new(),
            capabilities: BTreeMap::new(),
            semantic_objects: BTreeMap::new(),
            profile_entities: Some(BTreeSet::new()),
        };
        let mut reverse = BTreeMap::new();
        for o in &world.objects {
            let key = (o.actor_id.clone(), o.instance_index);
            let id = *instances
                .get(&key)
                .ok_or_else(|| invalid("missing semantic instance binding"))?;
            if id == 0 || reverse.get(&id).is_some_and(|previous| previous != &key) {
                return Err(invalid(
                    "distinct instances must bind distinct nonzero entities",
                ));
            }
            reverse.insert(id, key);
            result
                .semantic_objects
                .entry(id)
                .or_default()
                .push(o.clone());
            result
                .capabilities
                .entry(id)
                .or_default()
                .extend(o.capabilities.iter().map(|c| String::from(c.clone())));
            result.objects.entry(id).or_insert_with(|| o.id.clone());
            if o.geometry.is_some() {
                result.profile_entities.as_mut().unwrap().insert(id);
                result.objects.insert(id, o.id.clone());
            }
        }
        for caps in result.capabilities.values_mut() {
            caps.sort();
            caps.dedup();
        }
        Ok(result)
    }
    pub(crate) fn semantic_objects(&self, id: u64) -> Vec<xace_core::world::v3::SemanticObject> {
        self.semantic_objects.get(&id).cloned().unwrap_or_default()
    }
    pub(crate) fn capabilities(&self, id: u64) -> Vec<String> {
        self.capabilities.get(&id).cloned().unwrap_or_default()
    }
    fn object_id(&self, id: u64) -> Option<ContractId> {
        self.objects.get(&id).cloned()
    }
}
// Bound world objects order lexically first. Runtime-only objects use EntityID (D3).
fn identity_key(id: u64, object: &Option<ContractId>) -> (bool, Option<&ContractId>, u64) {
    (object.is_none(), object.as_ref(), id)
}

impl GeometryScene {
    pub fn new(mut bodies: Vec<GeometryBody>) -> Result<Self, XaceError> {
        if bodies.len() > WORLD_MAX_OBJECTS {
            return Err(invalid("too many geometry bodies"));
        }
        bodies.sort_by_key(|b| b.entity_id);
        let mut previous = 0;
        let mut object_ids = BTreeSet::new();
        for b in &bodies {
            if b.entity_id == 0 || b.entity_id == previous {
                return Err(invalid("invalid or duplicate geometry entity ID"));
            }
            if let Some(id) = &b.object_id {
                if !object_ids.insert(id.clone()) {
                    return Err(invalid("duplicate semantic geometry object ID"));
                }
            }
            edges(b.bounds)?;
            previous = b.entity_id;
        }
        bodies.sort_by(|a, b| {
            identity_key(a.entity_id, &a.object_id).cmp(&identity_key(b.entity_id, &b.object_id))
        });
        Ok(Self { bodies })
    }
    fn selected(&self, f: GeometryFilter) -> impl Iterator<Item = &GeometryBody> {
        self.bodies.iter().filter(move |b| {
            f.exclude != Some(b.entity_id)
                && f.layer_mask & b.layer_mask != 0
                && match f.selection {
                    GeometrySelection::All => true,
                    GeometrySelection::Solids => !b.is_trigger,
                    GeometrySelection::Triggers => b.is_trigger,
                }
        })
    }
    /// Positive-volume overlap only; touching faces/edges are not overlaps.
    pub fn overlap(&self, bounds: Aabb, filter: GeometryFilter) -> Result<Vec<u64>, XaceError> {
        let (lo, hi) = edges(bounds)?;
        Ok(self
            .selected(filter)
            .filter(|b| {
                let (bl, bh) = edges(b.bounds).expect("validated scene");
                (0..3).all(|i| lo[i] < bh[i] && hi[i] > bl[i])
            })
            .map(|b| b.entity_id)
            .collect())
    }
    pub fn sweep(
        &self,
        bounds: Aabb,
        displacement: [Fixed64; 3],
        filter: GeometryFilter,
    ) -> Result<Vec<GeometryContact>, XaceError> {
        let (lo, hi) = edges(bounds)?;
        let d = raw(displacement);
        // Euclidean bound, calculated only after per-axis validation to bound products.
        if d.iter()
            .any(|v| !(-MAX_DISPLACEMENT_RAW..=MAX_DISPLACEMENT_RAW).contains(v))
            || d.iter().map(|v| (*v as i128) * (*v as i128)).sum::<i128>()
                > (MAX_DISPLACEMENT_RAW as i128).pow(2)
        {
            return Err(invalid("sweep exceeds 16 metre displacement bound"));
        }
        point(std::array::from_fn(|i| lo[i] + d[i]))?;
        point(std::array::from_fn(|i| hi[i] + d[i]))?;
        let mut hits = Vec::new();
        for b in self.selected(filter) {
            let (bl, bh) = edges(b.bounds)?;
            let initial = (0..3).all(|i| lo[i] < bh[i] && hi[i] > bl[i]);
            let mut entry = Ratio(-4 * (WORLD_COORDINATE_LIMIT as i128), 1);
            let mut exit = Ratio(4 * (WORLD_COORDINATE_LIMIT as i128), 1);
            let mut normal = AxisNormal::NegativeX;
            if initial {
                let (_, n) = (0..3)
                    .flat_map(|i| {
                        [
                            (hi[i] - bl[i], AxisNormal::from_axis(i, false).unwrap()),
                            (bh[i] - lo[i], AxisNormal::from_axis(i, true).unwrap()),
                        ]
                    })
                    .min()
                    .unwrap();
                normal = n;
                entry = Ratio(0, 1);
            } else {
                let mut misses = false;
                for i in 0..3 {
                    if d[i] == 0 {
                        if hi[i] <= bl[i] || lo[i] >= bh[i] {
                            misses = true;
                            break;
                        }
                        continue;
                    }
                    let (near, far, n) = if d[i] > 0 {
                        (
                            bl[i] - hi[i],
                            bh[i] - lo[i],
                            AxisNormal::from_axis(i, false).unwrap(),
                        )
                    } else {
                        (
                            lo[i] - bh[i],
                            hi[i] - bl[i],
                            AxisNormal::from_axis(i, true).unwrap(),
                        )
                    };
                    let near = Ratio(near as i128, d[i].abs() as i128);
                    let far = Ratio(far as i128, d[i].abs() as i128);
                    if near.cmp(entry) == Ordering::Greater {
                        entry = near;
                        normal = n;
                    }
                    if far.cmp(exit) == Ordering::Less {
                        exit = far;
                    }
                }
                // Tangential contact, moving away from a face, and zero motion do not block.
                if misses
                    || entry.cmp(Ratio(0, 1)) == Ordering::Less
                    || entry.cmp(Ratio(1, 1)) == Ordering::Greater
                    || entry.cmp(exit) != Ordering::Less
                {
                    continue;
                }
            }
            let (n, den) = fraction(entry.0 as u64, entry.1 as u64);
            hits.push(GeometryContact {
                entity_id: b.entity_id,
                object_id: b.object_id.clone(),
                time_numerator: n,
                time_denominator: den,
                normal,
                initial_overlap: initial,
                travel: std::array::from_fn(|i| {
                    Fixed64::from_raw((d[i] as i128 * n as i128 / den as i128) as i64)
                }),
            });
        }
        hits.sort_by(|a, b| {
            ((a.time_numerator as u128) * (b.time_denominator as u128))
                .cmp(&((b.time_numerator as u128) * (a.time_denominator as u128)))
                .then(
                    identity_key(a.entity_id, &a.object_id)
                        .cmp(&identity_key(b.entity_id, &b.object_id)),
                )
        });
        Ok(hits)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Vector {
    x: Fixed64,
    y: Fixed64,
    z: Fixed64,
}
impl Vector {
    fn array(&self) -> [Fixed64; 3] {
        [self.x, self.y, self.z]
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Quaternion {
    x: Fixed64,
    y: Fixed64,
    z: Fixed64,
    w: Fixed64,
}
#[derive(Deserialize)]
struct Transform {
    position: Vector,
    rotation: Quaternion,
    scale: Vector,
    parent_entity_id: u64,
}
#[derive(Deserialize)]
struct Collider {
    shape: String,
    size: Vector,
    offset: Vector,
    is_trigger: bool,
    #[serde(default = "default_layer_mask")]
    layer_mask: u32,
}
fn default_layer_mask() -> u32 {
    xace_core::ucl::collider_component::LayerMask::DEFAULT.0
}
fn read_transform(ctx: &dyn ISystemContext, id: u64) -> Result<Transform, XaceError> {
    let text = ctx
        .get_component(id, 1)?
        .ok_or_else(|| invalid("geometry entity missing transform"))?;
    let t: Transform = serde_json::from_str(text)
        .map_err(|e| invalid(format!("invalid geometry transform: {e}")))?;
    point(raw(t.position.array()))?;
    Ok(t)
}
fn transform(ctx: &dyn ISystemContext, id: u64) -> Result<Transform, XaceError> {
    let t = read_transform(ctx, id)?;
    if raw(t.scale.array()) != [FIXED64_SCALE; 3]
        || t.parent_entity_id != 0
        || [
            t.rotation.x.raw(),
            t.rotation.y.raw(),
            t.rotation.z.raw(),
            t.rotation.w.raw(),
        ] != [0, 0, 0, FIXED64_SCALE]
    {
        return Err(invalid(
            "geometry v1 requires identity rotation/scale and no parent",
        ));
    }
    point(raw(t.position.array()))?;
    Ok(t)
}
/// Reads only through the scheduled context: colliders require declared types 1 and 4;
/// targeting requires type 1. No engine feedback or independently authored cache enters this path.
pub(crate) fn query(
    ctx: &dyn ISystemContext,
    q: &GeometryQueryV1,
    bindings: Option<&WorldGeometryBindings>,
) -> Result<GeometryResultV1, XaceError> {
    if let GeometryQueryV1::Nearest {
        origin,
        max_distance,
        candidates,
    } = q
    {
        point(raw(*origin))?;
        if !(0..=2 * WORLD_COORDINATE_LIMIT).contains(&max_distance.raw())
            || candidates.len() > WORLD_MAX_OBJECTS
        {
            return Err(invalid("target query bounds exceeded"));
        }
        // Require access even for an empty candidate list.
        ctx.query_entities(&[1])?;
        let mut ids = BTreeSet::new();
        let mut best: Option<GeometryTarget> = None;
        for id in candidates {
            if *id == 0 || !ids.insert(*id) {
                return Err(invalid("invalid or duplicate target ID"));
            }
            let t = read_transform(ctx, *id)?;
            if t.parent_entity_id != 0 {
                return Err(invalid("nearest requires resolved world-space position"));
            }
            let p = raw(t.position.array());
            let o = raw(*origin);
            let distance_squared = (0..3)
                .map(|i| (p[i] as i128 - o[i] as i128).pow(2) as u128)
                .sum();
            let object_id = bindings.and_then(|b| b.object_id(*id));
            if distance_squared <= (max_distance.raw() as u128).pow(2)
                && best.as_ref().map_or(true, |b| {
                    (distance_squared, identity_key(*id, &object_id))
                        < (b.distance_squared, identity_key(b.entity_id, &b.object_id))
                })
            {
                best = Some(GeometryTarget {
                    entity_id: *id,
                    object_id,
                    distance_squared,
                });
            }
        }
        return Ok(GeometryResultV1::Nearest(best));
    }
    ctx.query_entities(&[1])?;
    let ids = ctx.query_entities(&[4])?;
    if ids.len() > WORLD_MAX_OBJECTS {
        return Err(invalid("too many geometry bodies"));
    }
    let mut bodies = Vec::with_capacity(ids.len());
    let filter = match q {
        GeometryQueryV1::Sweep { filter, .. }
        | GeometryQueryV1::Overlap { filter, .. }
        | GeometryQueryV1::Probe { filter, .. } => *filter,
        _ => unreachable!(),
    };
    for id in ids {
        if bindings
            .and_then(|b| b.profile_entities.as_ref())
            .is_some_and(|members| !members.contains(&id))
            || filter.exclude == Some(id)
        {
            continue;
        }

        let text = ctx
            .get_component(id, 4)?
            .ok_or_else(|| invalid("missing collider"))?;
        let c: Collider =
            serde_json::from_str(text).map_err(|e| invalid(format!("invalid collider: {e}")))?;
        if filter.layer_mask & c.layer_mask == 0
            || match filter.selection {
                GeometrySelection::All => false,
                GeometrySelection::Solids => c.is_trigger,
                GeometrySelection::Triggers => !c.is_trigger,
            }
        {
            continue;
        }
        let t = transform(ctx, id)?;
        let size = raw(c.size.array());
        let offset = raw(c.offset.array());
        point(offset)?;
        if c.shape != "BOX"
            || size
                .iter()
                .any(|v| *v <= 0 || *v > WORLD_COORDINATE_LIMIT || v % 2 != 0)
        {
            return Err(invalid(
                "geometry v1 supports only bounded even-micro-unit BOX sizes",
            ));
        }
        let p = raw(t.position.array());
        bodies.push(GeometryBody {
            entity_id: id,
            object_id: bindings.and_then(|b| b.object_id(id)),
            is_trigger: c.is_trigger,
            layer_mask: c.layer_mask,
            bounds: Aabb {
                center: std::array::from_fn(|i| Fixed64::from_raw(p[i] + offset[i])),
                half_extents: std::array::from_fn(|i| Fixed64::from_raw(size[i] / 2)),
            },
        });
    }
    let scene = GeometryScene::new(bodies)?;
    match q {
        GeometryQueryV1::Sweep {
            bounds,
            displacement,
            filter,
        } => Ok(GeometryResultV1::Contacts(scene.sweep(
            *bounds,
            *displacement,
            *filter,
        )?)),
        GeometryQueryV1::Overlap { bounds, filter } => {
            Ok(GeometryResultV1::Overlaps(scene.overlap(*bounds, *filter)?))
        }
        GeometryQueryV1::Probe {
            bounds,
            direction,
            distance,
            filter,
        } => {
            if !(0..=MAX_DISPLACEMENT_RAW).contains(&distance.raw()) {
                return Err(invalid("invalid probe distance"));
            }
            let mut d = [Fixed64::ZERO; 3];
            d[direction.axis()] = Fixed64::from_raw(direction.sign() * distance.raw());
            Ok(GeometryResultV1::Contacts(
                scene.sweep(*bounds, d, *filter)?,
            ))
        }
        GeometryQueryV1::Nearest { .. } => unreachable!(),
    }
}

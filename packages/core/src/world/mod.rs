pub mod v3;
// XP-003 World Contract v2: immutable data and validation, no geometry execution.
use crate::assets::asset_type::AssetType;
use crate::fixed_point::{Fixed64, FIXED64_SCALE};
use crate::schema::world_definition::{Gravity, WorldSize};
use crate::wire::session_contract::{ContentHash, ContractId, WorldIdentity};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

pub const WORLD_CONTRACT_VERSION: u32 = 2;
pub const WORLD_MAX_OBJECTS: usize = 4096;
pub const WORLD_COORDINATE_LIMIT: i64 = 8192 * FIXED64_SCALE;
pub const WORLD_NUMERIC_PROFILE: &str = "fixed64_y_up_neg_z_v1";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorldVector {
    pub x: Fixed64,
    pub y: Fixed64,
    pub z: Fixed64,
}
impl WorldVector {
    fn values(&self) -> [i64; 3] {
        [self.x.raw(), self.y.raw(), self.z.raw()]
    }
    fn valid(&self, positive: bool) -> bool {
        self.values().into_iter().all(|v| {
            (-WORLD_COORDINATE_LIMIT..=WORLD_COORDINATE_LIMIT).contains(&v) && (!positive || v > 0)
        })
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorldObjectKind {
    StaticBox,
    KinematicBox,
    Trigger,
    Spawn,
    Anchor,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SemanticAssetRequirement {
    pub id: ContractId,
    pub asset_type: AssetType,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorldObject {
    pub id: ContractId,
    pub actor_id: ContractId,
    pub kind: WorldObjectKind,
    pub position: WorldVector,
    pub half_extents: Option<WorldVector>,
    pub capabilities: Vec<String>,
    pub target_id: Option<ContractId>,
    pub asset_requirement: Option<SemanticAssetRequirement>,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorldContract {
    /// Package-owned semantic declarations, sorted by ID; no gameplay names in core.
    pub capability_declarations: Vec<SemanticCapabilityDeclaration>,
    pub schema: String,
    pub contract_version: u32,
    pub numeric_profile: String,
    pub mode_id: ContractId,
    pub size: WorldSize,
    pub gravity: Gravity,
    pub day_length_ticks: u64,
    pub required_capabilities: Vec<String>,
    pub objects: Vec<WorldObject>,
}
fn sorted_unique<T: Ord>(values: &[T]) -> bool {
    values.windows(2).all(|w| w[0] < w[1])
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SemanticCapabilityDeclaration {
    pub id: ContractId,
    /// Sorted role names supplied by the owning package/catalog.
    pub allowed_kinds: Vec<String>,
}
/// Versioned namespaced semantic identifiers. Platform requirements are separate.
pub fn valid_semantic_capability(id: &str) -> bool {
    if ContractId::try_from(id.to_string()).is_err() {
        return false;
    }
    let parts: Vec<_> = id.split('.').collect();
    parts.len() >= 3
        && parts.iter().all(|p| !p.is_empty())
        && parts.last().is_some_and(|p| {
            p.strip_prefix('v').is_some_and(|v| {
                !v.is_empty() && !v.starts_with('0') && v.bytes().all(|c| c.is_ascii_digit())
            })
        })
        && ![
            "input.timed.v1",
            "world.aabb.v1",
            "world.semantic_bindings.v1",
            "world.semantic_bindings.v3",
        ]
        .contains(&id)
}
fn kind_name(kind: WorldObjectKind) -> &'static str {
    match kind {
        WorldObjectKind::StaticBox => "static_box",
        WorldObjectKind::KinematicBox => "kinematic_box",
        WorldObjectKind::Trigger => "trigger",
        WorldObjectKind::Spawn => "spawn",
        WorldObjectKind::Anchor => "anchor",
    }
}
impl WorldContract {
    /// Reject unrecognized fields, including in reused legacy nested structs.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, String> {
        let value: serde_json::Value = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        let world: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        world.validate()?;
        if serde_json::to_value(&world).map_err(|e| e.to_string())? != value {
            return Err("noncanonical or unknown world fields".into());
        }
        Ok(world)
    }
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != "xace.world_contract.v2"
            || self.contract_version != WORLD_CONTRACT_VERSION
            || self.numeric_profile != WORLD_NUMERIC_PROFILE
        {
            return Err("unsupported world contract/profile".into());
        }
        let size = WorldVector {
            x: self.size.width,
            y: self.size.height,
            z: self.size.depth,
        };
        let gravity = WorldVector {
            x: self.gravity.x,
            y: self.gravity.y,
            z: self.gravity.z,
        };
        if !size.valid(true)
            || !gravity.valid(false)
            || self.objects.is_empty()
            || self.objects.len() > WORLD_MAX_OBJECTS
        {
            return Err("world bounds/count exceed profile".into());
        }
        if self.required_capabilities != ["world.aabb.v1", "world.semantic_bindings.v1"] {
            return Err("unknown/unsorted world capabilities".into());
        }
        let declaration_ids: Vec<_> = self.capability_declarations.iter().map(|d| &d.id).collect();
        if self.capability_declarations.len() > 4096 || !sorted_unique(&declaration_ids) {
            return Err("invalid semantic declaration count/order".into());
        }
        let mut declarations = std::collections::BTreeMap::new();
        for declaration in &self.capability_declarations {
            let id = String::from(declaration.id.clone());
            if !valid_semantic_capability(&id)
                || declaration.allowed_kinds.is_empty()
                || !sorted_unique(&declaration.allowed_kinds)
                || declaration.allowed_kinds.iter().any(|k| {
                    !["static_box", "kinematic_box", "trigger", "spawn", "anchor"]
                        .contains(&k.as_str())
                })
            {
                return Err("invalid semantic capability declaration".into());
            }
            declarations.insert(id, &declaration.allowed_kinds);
        }
        let ids: Vec<_> = self.objects.iter().map(|o| &o.id).collect();
        if !sorted_unique(&ids) {
            return Err("duplicate/unsorted world object IDs".into());
        }
        let id_set: BTreeSet<_> = ids.into_iter().collect();
        let mut actors = BTreeSet::new();
        for object in &self.objects {
            if !actors.insert(&object.actor_id)
                || !object.position.valid(false)
                || !sorted_unique(&object.capabilities)
                || object
                    .target_id
                    .as_ref()
                    .is_some_and(|id| !id_set.contains(id))
            {
                return Err("invalid world actor/target/position/capabilities".into());
            }
            let boxed = matches!(
                object.kind,
                WorldObjectKind::StaticBox
                    | WorldObjectKind::KinematicBox
                    | WorldObjectKind::Trigger
            );
            if boxed != object.half_extents.is_some() {
                return Err("geometry does not match world role".into());
            }
            if let Some(half) = &object.half_extents {
                if !half.valid(true)
                    || half
                        .values()
                        .iter()
                        .any(|v| *v > WORLD_COORDINATE_LIMIT / 2)
                {
                    return Err("invalid half extents".into());
                }
                for (center, extent) in object.position.values().into_iter().zip(half.values()) {
                    if center - extent < -WORLD_COORDINATE_LIMIT
                        || center + extent > WORLD_COORDINATE_LIMIT
                    {
                        return Err("box bounds exceed profile".into());
                    }
                }
            }
            for capability in &object.capabilities {
                let allowed = declarations
                    .get(capability)
                    .ok_or("undeclared semantic capability")?;
                if !allowed.iter().any(|k| k == kind_name(object.kind)) {
                    return Err("semantic declaration excludes object role".into());
                }
            }
        }
        Ok(())
    }
    /// JSON object keys are sorted recursively through serde_json::Value maps.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        serde_json::to_vec(&serde_json::to_value(self).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())
    }
    pub fn content_hash(&self) -> Result<ContentHash, String> {
        format!("{:x}", Sha256::digest(self.canonical_bytes()?))
            .try_into()
            .map_err(str::to_string)
    }
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SchemaPackageProvenance {
    pub cgs_hash: ContentHash,
    pub schema_version: ContractId,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorldManifest {
    pub schema: String,
    pub world: WorldIdentity,
    pub schema_package: SchemaPackageProvenance,
}
impl WorldManifest {
    /// Expected CGS identity must come from the caller's trusted compiled package.
    pub fn verify(
        &self,
        content: &WorldContract,
        expected_cgs_hash: &ContentHash,
        expected_schema_version: &ContractId,
    ) -> Result<(), String> {
        if self.schema != "xace.world_manifest.v1"
            || self.world.contract_version != WORLD_CONTRACT_VERSION
            || self.world.mode_id != content.mode_id
            || self.world.artifact.content_hash != content.content_hash()?
            || &self.world.compiled_from_cgs_hash != expected_cgs_hash
            || &self.schema_package.cgs_hash != expected_cgs_hash
            || &self.schema_package.schema_version != expected_schema_version
        {
            return Err("world manifest content/source/package identity mismatch".into());
        }
        Ok(())
    }
}

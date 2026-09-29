//! Versioned project semantics, independent of collision vocabulary.
use super::{WorldManifest, WorldVector, WORLD_COORDINATE_LIMIT, WORLD_MAX_OBJECTS};
use crate::wire::session_contract::{ContentHash, ContractId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

pub const AABB_PROFILE: &str = "world.aabb.v1";
/// Shared profile identity/limits consumed by the compiler and runtime reader.
/// Adding a registry record alone never installs an executable backend.
pub fn supported_geometry_profiles() -> BTreeSet<String> {
    let registry: Value = serde_json::from_str(include_str!("profiles.json")).expect("shipped registry");
    let p = &registry["profiles"]["aabb_v1"];
    assert_eq!(p["id"], AABB_PROFILE);
    assert_eq!(p["coordinate_limit_raw"], WORLD_COORDINATE_LIMIT);
    assert_eq!(p["max_bodies"], WORLD_MAX_OBJECTS);
    BTreeSet::from([p["id"].as_str().unwrap().to_string()])
}

fn token(s: &str) -> bool {
    ContractId::try_from(s.to_owned()).is_ok()
}
fn versioned(s: &str) -> bool {
    token(s)
        && s.split('.').count() >= 3
        && s.split('.').all(|p| {
            !p.is_empty()
                && p.bytes()
                    .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        })
        && s.rsplit('.')
            .next()
            .and_then(|p| p.strip_prefix('v'))
            .is_some_and(|v| {
                !v.is_empty() && !v.starts_with('0') && v.bytes().all(|c| c.is_ascii_digit())
            })
}
fn ensure(ok: bool, error: &str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(error.into())
    }
}
fn sorted<T: Ord>(v: &[T]) -> bool {
    v.windows(2).all(|p| p[0] < p[1])
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase", deny_unknown_fields)]
pub enum DataSchema {
    Integer,
    Boolean,
    String,
    Object {
        fields: BTreeMap<String, DataSchema>,
    },
    Array {
        items: Box<DataSchema>,
    },
}
impl DataSchema {
    fn definition(&self, depth: usize) -> Result<(), String> {
        ensure(depth <= 16, "schema nesting limit")?;
        match self {
            Self::Object { fields } => {
                ensure(
                    fields.len() <= 256 && fields.keys().all(|k| token(k)),
                    "invalid schema fields",
                )?;
                for s in fields.values() {
                    s.definition(depth + 1)?;
                }
            }
            Self::Array { items } => items.definition(depth + 1)?,
            _ => (),
        }
        Ok(())
    }
    pub fn validate(&self, value: &Value) -> Result<(), String> {
        match self {
            Self::Integer => ensure(value.as_i64().is_some(), "expected signed integer"),
            Self::Boolean => ensure(value.is_boolean(), "expected boolean"),
            Self::String => ensure(
                value.as_str().is_some_and(|s| s.len() <= 16384),
                "expected bounded string",
            ),
            Self::Object { fields } => {
                let v = value.as_object().ok_or("expected object")?;
                ensure(v.len() == fields.len(), "unknown or missing properties")?;
                for (key, s) in fields {
                    s.validate(v.get(key).ok_or("missing property")?)?;
                }
                Ok(())
            }
            Self::Array { items } => {
                let v = value.as_array().ok_or("expected array")?;
                ensure(v.len() <= 4096, "array limit")?;
                for x in v {
                    items.validate(x)?;
                }
                Ok(())
            }
        }
    }
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SchemaDeclaration {
    pub id: ContractId,
    pub definition: DataSchema,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityDeclaration {
    pub id: ContractId,
    pub allowed_types: Vec<ContractId>,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeometryProfile {
    pub id: ContractId,
    pub required: bool,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SemanticTransform {
    pub position: WorldVector,
    pub rotation: BTreeMap<String, i64>,
    pub scale: WorldVector,
    pub parent_entity_id: u64,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssetRequirement {
    pub id: ContractId,
    pub asset_type: String,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeometryProjection {
    pub profile: ContractId,
    pub size: WorldVector,
    pub offset: WorldVector,
    pub is_trigger: bool,
    pub layer_mask: u32,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SemanticObject {
    pub id: ContractId,
    pub actor_id: ContractId,
    pub instance_index: u32,
    pub semantic_type: ContractId,
    pub properties: Value,
    pub capabilities: Vec<ContractId>,
    pub relationships: BTreeMap<String, Vec<ContractId>>,
    pub asset_bindings: BTreeMap<String, AssetRequirement>,
    pub transform: SemanticTransform,
    pub geometry: Option<GeometryProjection>,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorldContractV3 {
    pub schema: String,
    pub contract_version: u32,
    pub mode_id: ContractId,
    pub schemas: Vec<SchemaDeclaration>,
    pub capability_declarations: Vec<CapabilityDeclaration>,
    pub geometry_profiles: Vec<GeometryProfile>,
    pub objects: Vec<SemanticObject>,
}
impl WorldContractV3 {
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, String> {
        ensure(bytes.len() <= 16 * 1024 * 1024, "world artifact limit")?;
        let v: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        v.validate()?;
        ensure(
            serde_json::to_value(&v).map_err(|e| e.to_string())?
                == serde_json::from_slice::<Value>(bytes).map_err(|e| e.to_string())?,
            "unknown fields",
        )?;
        Ok(v)
    }
    pub fn validate(&self) -> Result<(), String> {
        ensure(
            self.schema == "xace.world_contract.v3" && self.contract_version == 3,
            "unsupported semantic world version",
        )?;
        let schemas: BTreeMap<_, _> = self
            .schemas
            .iter()
            .map(|s| (&s.id, &s.definition))
            .collect();
        ensure(
            self.schemas.len() <= 4096
                && sorted(&self.schemas.iter().map(|s| &s.id).collect::<Vec<_>>()),
            "duplicate/unsorted schemas",
        )?;
        for s in &self.schemas {
            ensure(versioned(&String::from(s.id.clone())), "invalid schema ID")?;
            s.definition.definition(0)?;
        }
        let caps: BTreeMap<_, _> = self
            .capability_declarations
            .iter()
            .map(|c| (&c.id, &c.allowed_types))
            .collect();
        ensure(
            self.capability_declarations.len() <= 4096
                && sorted(
                    &self
                        .capability_declarations
                        .iter()
                        .map(|s| &s.id)
                        .collect::<Vec<_>>(),
                ),
            "duplicate/unsorted capabilities",
        )?;
        for c in &self.capability_declarations {
            ensure(
                super::valid_semantic_capability(&String::from(c.id.clone()))
                    && versioned(&String::from(c.id.clone()))
                    && sorted(&c.allowed_types)
                    && c.allowed_types.iter().all(|s| schemas.contains_key(s)),
                "invalid capability declaration",
            )?;
        }
        ensure(
            self.geometry_profiles.len() <= 4096
                && sorted(
                    &self
                        .geometry_profiles
                        .iter()
                        .map(|s| &s.id)
                        .collect::<Vec<_>>(),
                ),
            "duplicate/unsorted profiles",
        )?;
        for p in &self.geometry_profiles {
            ensure(versioned(&String::from(p.id.clone())), "invalid profile ID")?;
        }
        ensure(
            self.objects.len() <= WORLD_MAX_OBJECTS
                && sorted(&self.objects.iter().map(|o| &o.id).collect::<Vec<_>>()),
            "duplicate/unsorted object IDs",
        )?;
        let ids: BTreeSet<_> = self.objects.iter().map(|o| &o.id).collect();
        let mut geometry_instances = BTreeSet::new();
        for o in &self.objects {
            ensure(o.instance_index < 4096, "instance limit")?;
            schemas
                .get(&o.semantic_type)
                .ok_or("unregistered semantic type")?
                .validate(&o.properties)?;
            ensure(
                sorted(&o.capabilities),
                "duplicate/unsorted object capabilities",
            )?;
            for c in &o.capabilities {
                let allowed = caps.get(c).ok_or("undeclared capability")?;
                ensure(
                    allowed.is_empty() || allowed.contains(&o.semantic_type),
                    "incompatible semantic type",
                )?;
            }
            for (role, targets) in &o.relationships {
                ensure(
                    versioned(role) && sorted(targets) && targets.iter().all(|t| ids.contains(t)),
                    "invalid relationship",
                )?;
            }
            for (role, asset) in &o.asset_bindings {
                let builtin = [
                    "MESH",
                    "TEXTURE",
                    "MATERIAL",
                    "ANIMATION_CONTROLLER",
                    "ANIMATION_CLIP",
                    "AUDIO_CLIP",
                    "AUDIO_MUSIC",
                    "SPRITE",
                    "PARTICLE",
                    "PREFAB",
                    "FONT",
                ]
                .contains(&asset.asset_type.as_str());
                ensure(
                    versioned(role)
                        && (builtin
                            || schemas
                                .keys()
                                .any(|s| String::from((*s).clone()) == asset.asset_type)),
                    "unregistered asset role/category",
                )?;
            }
            let t = &o.transform;
            ensure(
                t.rotation
                    .keys()
                    .map(String::as_str)
                    .eq(["w", "x", "y", "z"])
                    && t.rotation.values().any(|v| *v != 0)
                    && t.scale.values().iter().all(|v| *v != 0),
                "invalid transform",
            )?;
            if let Some(g) = &o.geometry {
                ensure(
                    self.geometry_profiles
                        .iter()
                        .any(|p| p.id == g.profile && p.required),
                    "geometry profile must be declared required",
                )?;
                ensure(
                    String::from(g.profile.clone()) == AABB_PROFILE,
                    "unsupported geometry projection",
                )?;
                ensure(
                    geometry_instances.insert((&o.actor_id, o.instance_index)),
                    "duplicate geometry binding",
                )?;
                ensure(
                    t.parent_entity_id == 0
                        && t.rotation
                            == BTreeMap::from([
                                ("w".into(), 1_000_000),
                                ("x".into(), 0),
                                ("y".into(), 0),
                                ("z".into(), 0),
                            ])
                        && t.scale.values() == [1_000_000; 3],
                    "AABB transform unsupported",
                )?;
                ensure(
                    t.position.valid(false)
                        && g.offset.valid(false)
                        && g.size
                            .values()
                            .iter()
                            .all(|v| *v > 0 && *v <= WORLD_COORDINATE_LIMIT && *v % 2 == 0),
                    "invalid AABB geometry",
                )?;
                for ((p, off), size) in t
                    .position
                    .values()
                    .into_iter()
                    .zip(g.offset.values())
                    .zip(g.size.values())
                {
                    ensure(
                        p + off - size / 2 >= -WORLD_COORDINATE_LIMIT
                            && p + off + size / 2 <= WORLD_COORDINATE_LIMIT,
                        "AABB bounds exceeded",
                    )?;
                }
            }
        }
        Ok(())
    }
    /// Host support is trusted registration, never a peer-supplied promise.
    pub fn admit(&self, supported_profiles: &BTreeSet<String>) -> Result<(), String> {
        self.validate()?;
        ensure(
            self.geometry_profiles
                .iter()
                .all(|p| !p.required || supported_profiles.contains(&String::from(p.id.clone()))),
            "unsupported required geometry profile",
        )
    }
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
    pub fn verify_manifest(
        &self,
        m: &WorldManifest,
        cgs: &ContentHash,
        version: &ContractId,
    ) -> Result<(), String> {
        ensure(
            m.schema == "xace.world_manifest.v1"
                && m.world.contract_version == 3
                && m.world.mode_id == self.mode_id
                && m.world.artifact.content_hash == self.content_hash()?
                && &m.world.compiled_from_cgs_hash == cgs
                && &m.schema_package.cgs_hash == cgs
                && &m.schema_package.schema_version == version,
            "world content/source/package mismatch",
        )
    }
}

/// Verify admission against the actual schema/profile-bearing world artifact.
pub fn compare_session_with_world_v3(
    authority: &crate::wire::session_contract::SessionContract,
    candidate: &crate::wire::session_contract::SessionOffer,
    world: &WorldContractV3,
    certified_adapters: &BTreeSet<crate::wire::session_contract::AdapterIdentity>,
    supported_profiles: &BTreeSet<String>,
) -> Result<(), crate::wire::session_contract::CompatibilityRejection> {
    use crate::wire::session_contract::{compare_session, CompatibilityRejection as R};
    world.admit(supported_profiles).map_err(|_| R::World)?;
    if world.content_hash().map_err(|_| R::World)? != authority.gameplay.world.artifact.content_hash
        || world.mode_id != authority.gameplay.world.mode_id
        || authority.gameplay.world.contract_version != 3
    {
        return Err(R::World);
    }
    let semantics: BTreeSet<_> = world
        .objects
        .iter()
        .flat_map(|o| o.capabilities.iter().cloned())
        .collect();
    let required: BTreeSet<_> = std::iter::once("input.timed.v1".to_string())
        .chain(std::iter::once("world.semantic_bindings.v3".to_string()))
        .chain(
            world
                .geometry_profiles
                .iter()
                .filter(|p| p.required)
                .map(|p| String::from(p.id.clone())),
        )
        .map(|s| ContractId::try_from(s).expect("validated profile"))
        .collect();
    if semantics != authority.semantic_capabilities || required != authority.required_capabilities {
        return Err(R::RequiredCapabilities);
    }
    compare_session(authority, candidate, certified_adapters)
}

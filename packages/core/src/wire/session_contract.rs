//! XP-001 shared, opt-in compatibility contract. No transport or authority writes.
//! See docs/adr/XP-001-supported-session-contract.md before using for admission.
use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::wire_message::XACE_PROTOCOL_VERSION;
use crate::runtime::execution_plan::ExecutionPlan;
use crate::schema::canonical_game_schema::CgsVersion;

pub const SESSION_CONTRACT_SCHEMA: &str = "xace.session_contract.v1";
pub const SESSION_PROFILE_ID: &str = "host_client_lockstep_4p_60hz_windows_v1";
pub const SESSION_PROFILE_V3_ID: &str = "host_client_lockstep_4p_60hz_windows_world_v3";
pub const SESSION_TOPOLOGY_ID: &str = "host_client_lockstep_v1";
pub const SESSION_MAX_PLAYERS: u8 = 4;
pub const SESSION_TICK_RATE: u32 = 60;
pub const INPUT_LEAD_TICKS: u32 = 3;
pub const MAX_INPUT_LEAD_TICKS: u32 = 12;
pub const INPUT_STALL_TIMEOUT_MS: u32 = 5000;

/// Canonical lowercase SHA-256 text. Existing CGS/SGC hashes are copied, not rehashed.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct ContentHash(String);
impl TryFrom<String> for ContentHash {
    type Error = &'static str;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        if value.len() != 64
            || !value
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err("expected 64 lowercase hexadecimal SHA-256 characters");
        }
        Ok(Self(value))
    }
}
impl From<ContentHash> for String {
    fn from(value: ContentHash) -> Self {
        value.0
    }
}

/// Stable semantic identifier/version, never an engine path or a display label.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct ContractId(String);
impl TryFrom<String> for ContractId {
    type Error = &'static str;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        if value.is_empty()
            || value.len() > 128
            || !value
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        {
            return Err("expected bounded semantic identifier, not a native path");
        }
        Ok(Self(value))
    }
}
impl From<ContractId> for String {
    fn from(value: ContractId) -> Self {
        value.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CgsIdentity {
    pub schema_version: CgsVersion,
    pub cgs_hash: ContentHash,
}

/// Projection of the existing persisted ExecutionPlan identity fields.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SgcIdentity {
    pub schema_version: String,
    pub plan_version: u32,
    pub plan_hash: ContentHash,
    pub compiled_from_cgs_hash: ContentHash,
    pub adapter_protocol_version: u32,
}
impl TryFrom<&ExecutionPlan> for SgcIdentity {
    type Error = String;
    fn try_from(plan: &ExecutionPlan) -> Result<Self, Self::Error> {
        plan.validate()?;
        Ok(Self {
            schema_version: plan.schema_version.clone(),
            plan_version: plan.plan_version,
            plan_hash: plan.plan_hash.clone().try_into()?,
            compiled_from_cgs_hash: plan.compiled_from_cgs_hash.clone().try_into()?,
            adapter_protocol_version: plan.adapter_protocol_version,
        })
    }
}

/// Future artifacts use the same content-addressed pattern; not an artifact loader.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactIdentity {
    pub id: ContractId,
    pub version: ContractId,
    pub content_hash: ContentHash,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorldIdentity {
    pub artifact: ArtifactIdentity,
    pub contract_version: u32,
    pub compiled_from_cgs_hash: ContentHash,
    pub mode_id: ContractId,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InputIdentity {
    pub artifact: ArtifactIdentity,
    pub packet_schema_version: u16,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeIdentity {
    /// Semantic execution ABI/system-set identity, not a platform executable digest.
    pub artifact: ArtifactIdentity,
    pub wire_protocol_version: u32,
    pub engine_protocol_version: u32,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GameplayIdentity {
    pub cgs: CgsIdentity,
    pub sgc: SgcIdentity,
    pub world: WorldIdentity,
    /// Common gameplay package projection; native presentation variants are separate.
    pub playable_package: ArtifactIdentity,
    pub input: InputIdentity,
    pub runtime: RuntimeIdentity,
}

/// The complete ruleset identity is this fence plus GameplayIdentity, not a new hash.
/// A restarted authority gets a new incarnation; epoch zero is the initial ruleset.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionEpoch {
    pub session_id: Uuid,
    pub authority_incarnation: Uuid,
    pub ruleset_epoch: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionContract {
    pub schema: String,
    pub profile_id: String,
    pub epoch: SessionEpoch,
    pub gameplay: GameplayIdentity,
    /// Platform/protocol requirements only. Unknown required values fail closed.
    pub required_capabilities: BTreeSet<ContractId>,
    /// Package semantic requirements are data, not host protocol capabilities.
    #[serde(default, skip_serializing_if = "BTreeSet::is_empty")]
    pub semantic_capabilities: BTreeSet<ContractId>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HostEngine {
    Godot,
    Unity,
    Unreal,
}
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AdapterIdentity {
    pub engine: HostEngine,
    pub adapter_version: ContractId,
    pub client_version: ContractId,
    pub platform: ContractId,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClientCompatibility {
    pub adapter: AdapterIdentity,
    pub engine_protocol_version: u32,
    pub capabilities: BTreeSet<ContractId>,
    pub presentation_manifest_hash: ContentHash,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionOffer {
    pub contract: SessionContract,
    pub client: ClientCompatibility,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ActivationIdentity {
    pub mutation_id: Uuid,
    pub activation_id: Uuid,
}
/// Identity-only provenance envelope. No payload execution, causal graph or logging.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionProvenance {
    pub schema: String,
    pub contract: SessionContract,
    pub adapter: AdapterIdentity,
    pub tick: u64,
    pub activation: Option<ActivationIdentity>,
}
impl SessionProvenance {
    pub fn validate(&self) -> Result<(), CompatibilityRejection> {
        self.contract.validate()?;
        if self.schema != "xace.session_provenance.v1"
            || self
                .activation
                .as_ref()
                .is_some_and(|v| v.mutation_id.is_nil() || v.activation_id.is_nil())
        {
            return Err(CompatibilityRejection::InvalidProvenance);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CompatibilityRejection {
    MalformedContract,
    UnsupportedProfile,
    InvalidIdentity,
    IdentityLink,
    UnknownRequiredCapability,
    MissingRequiredCapability,
    RequiredCapabilities,
    Cgs,
    SgcPlan,
    World,
    PlayablePackage,
    InputContract,
    Runtime,
    Protocol,
    Session,
    AuthorityIncarnation,
    RulesetEpoch,
    UncertifiedAdapter,
    Platform,
    InvalidProvenance,
}

/// Supported platform/protocol vocabulary only; package semantics never enter this list.
pub const KNOWN_CAPABILITIES: &[&str] = &[
    "session.projection.v1",
    "input.timed.v1",
    "world.aabb.v1",
    "world.semantic_bindings.v1",
];
pub const REQUIRED_PROFILE_CAPABILITIES: &[&str] = &[
    "input.timed.v1",
    "world.aabb.v1",
    "world.semantic_bindings.v1",
];

impl SessionContract {
    pub fn validate(&self) -> Result<(), CompatibilityRejection> {
        use CompatibilityRejection::*;
        if self.schema != SESSION_CONTRACT_SCHEMA
            || ![SESSION_PROFILE_ID, SESSION_PROFILE_V3_ID].contains(&self.profile_id.as_str())
        {
            return Err(UnsupportedProfile);
        }
        let g = &self.gameplay;
        if self.epoch.session_id.is_nil()
            || self.epoch.authority_incarnation.is_nil()
            || g.sgc.plan_version == 0
        {
            return Err(InvalidIdentity);
        }
        if g.sgc.schema_version != g.cgs.schema_version.to_string()
            || g.sgc.compiled_from_cgs_hash != g.cgs.cgs_hash
            || g.world.compiled_from_cgs_hash != g.cgs.cgs_hash
        {
            return Err(IdentityLink);
        }
        if (self.profile_id == SESSION_PROFILE_ID && ![1, 2].contains(&g.world.contract_version))
            || (self.profile_id == SESSION_PROFILE_V3_ID && g.world.contract_version != 3)
        {
            return Err(World);
        }
        if g.input.packet_schema_version != 1 {
            return Err(InputContract);
        }
        if g.runtime.wire_protocol_version != XACE_PROTOCOL_VERSION
            || g.runtime.engine_protocol_version != 1
            || g.sgc.adapter_protocol_version != g.runtime.engine_protocol_version
        {
            return Err(Protocol);
        }
        if self.required_capabilities.iter().any(|c| {
            !KNOWN_CAPABILITIES.contains(&c.0.as_str())
                && !(self.profile_id == SESSION_PROFILE_V3_ID
                    && c.0 == "world.semantic_bindings.v3")
        }) {
            return Err(UnknownRequiredCapability);
        }
        if self.semantic_capabilities.len() > 4096
            || self
                .semantic_capabilities
                .iter()
                .any(|c| !crate::world::valid_semantic_capability(&c.0))
            || (g.world.contract_version == 1 && !self.semantic_capabilities.is_empty())
        {
            return Err(UnknownRequiredCapability);
        }
        let required: &[&str] = if g.world.contract_version == 3 {
            &["input.timed.v1", "world.semantic_bindings.v3"]
        } else {
            REQUIRED_PROFILE_CAPABILITIES
        };
        if required
            .iter()
            .any(|c| !self.required_capabilities.iter().any(|r| r.0 == *c))
        {
            return Err(MissingRequiredCapability);
        }
        Ok(())
    }
}

/// Pure admission predicate only. The caller supplies a TRUSTED certification allowlist;
/// never accept a list supplied by the joining peer. Equality does not verify artifact
/// bytes, ownership, signatures, or actual host conformance. Those remain loader gates.
/// First failure order is normative: validate authority, candidate, then compare below.
pub fn compare_session(
    authority: &SessionContract,
    candidate: &SessionOffer,
    certified_adapters: &BTreeSet<AdapterIdentity>,
) -> Result<(), CompatibilityRejection> {
    use CompatibilityRejection::*;
    authority.validate()?;
    candidate.contract.validate()?;
    let peer = &candidate.contract;
    if authority.epoch.session_id != peer.epoch.session_id {
        return Err(Session);
    }
    if authority.epoch.authority_incarnation != peer.epoch.authority_incarnation {
        return Err(AuthorityIncarnation);
    }
    if authority.epoch.ruleset_epoch != peer.epoch.ruleset_epoch {
        return Err(RulesetEpoch);
    }
    let a = &authority.gameplay;
    let b = &peer.gameplay;
    if a.cgs != b.cgs {
        return Err(Cgs);
    }
    if a.sgc != b.sgc {
        return Err(SgcPlan);
    }
    if a.world != b.world {
        return Err(World);
    }
    if a.playable_package != b.playable_package {
        return Err(PlayablePackage);
    }
    if a.input != b.input {
        return Err(InputContract);
    }
    if a.runtime != b.runtime {
        return Err(Runtime);
    }
    if authority.required_capabilities != peer.required_capabilities
        || authority.semantic_capabilities != peer.semantic_capabilities
    {
        return Err(RequiredCapabilities);
    }
    if candidate.client.adapter.platform.0 != "windows_x64" {
        return Err(Platform);
    }
    if candidate.client.engine_protocol_version != a.runtime.engine_protocol_version {
        return Err(Protocol);
    }
    if !certified_adapters.contains(&candidate.client.adapter) {
        return Err(UncertifiedAdapter);
    }
    if !authority
        .required_capabilities
        .is_subset(&candidate.client.capabilities)
    {
        return Err(MissingRequiredCapability);
    }
    Ok(())
}

/// Admission with a validated world artifact. The legacy metadata-only predicate cannot
/// establish which semantic requirements were actually declared by package content.
/// Package/source/signature verification remains the caller's load-time responsibility.
pub fn compare_session_with_world(
    authority: &SessionContract,
    candidate: &SessionOffer,
    world: &crate::world::WorldContract,
    certified_adapters: &BTreeSet<AdapterIdentity>,
) -> Result<(), CompatibilityRejection> {
    let hash = world
        .content_hash()
        .map_err(|_| CompatibilityRejection::World)?;
    if hash != authority.gameplay.world.artifact.content_hash
        || world.mode_id != authority.gameplay.world.mode_id
        || world.contract_version != authority.gameplay.world.contract_version
    {
        return Err(CompatibilityRejection::World);
    }
    let semantics: BTreeSet<ContractId> = world
        .objects
        .iter()
        .flat_map(|o| o.capabilities.iter())
        .map(|s| ContractId::try_from(s.clone()).expect("validated world capability"))
        .collect();
    if semantics != authority.semantic_capabilities {
        return Err(CompatibilityRejection::RequiredCapabilities);
    }
    compare_session(authority, candidate, certified_adapters)
}

/// Strict missing/unknown-field/type rejection for readers using the shared JSON vectors.
pub fn compare_session_json(
    authority: &SessionContract,
    candidate: &str,
    certified_adapters: &BTreeSet<AdapterIdentity>,
) -> Result<(), CompatibilityRejection> {
    let offer: SessionOffer =
        serde_json::from_str(candidate).map_err(|_| CompatibilityRejection::MalformedContract)?;
    compare_session(authority, &offer, certified_adapters)
}

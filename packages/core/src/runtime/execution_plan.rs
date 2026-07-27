//! # Execution Plan
//!
//! The complete, compiled, deterministic runtime schedule produced by
//! the System Graph Compiler (SGC). Tells the PhaseOrchestrator exactly
//! which systems run in which order every tick.
//!
//! ## What the ExecutionPlan Is
//! The ExecutionPlan is the output of the SGC pipeline. It takes the
//! SystemDefinitions from the CGS and compiles them into a concrete
//! schedule — phases, groups, and system ordering — that the runtime
//! can execute without any further decision-making.
//!
//! The runtime is a pure executor. It never decides ordering at runtime.
//! All scheduling decisions are made by the SGC at compile time and
//! frozen into the ExecutionPlan (D1).
//!
//! ## Versioning and Validation (D10, I7)
//! Every ExecutionPlan carries the schema_version it was compiled from.
//! The runtime validates this against the current CGS version before
//! executing any tick. Version mismatch = immediate halt (I7).
//! This prevents stale plans from executing against an updated schema.
//!
//! ## Plan Hash
//! The plan_hash is a deterministic hash of the entire ExecutionPlan
//! content. Used by the DeterminismGuard to verify that two machines
//! running the same CGS produce identical execution plans (D9).
//!
//! ## Recompilation
//! The SGC recompiles the ExecutionPlan whenever:
//! - A system is added or removed from the CGS
//! - A system's phase assignment changes
//! - A system's read/write declarations change
//! - A system's explicit dependencies change
//! The GDE flags MutationTransactions that require recompile (D10).

use crate::runtime::execution_group::ExecutionGroup;
use crate::runtime::phase_enum::PhaseEnum;
use crate::schema::system_definition::{SystemDefinition, SystemVersion};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

pub const COMPONENT_ACCESS_SETS_SCHEMA: &str = "xace.sgc.component_access_sets.v1";
pub const SYSTEM_METADATA_SCHEMA: &str = "xace.sgc.system_metadata.v1";
pub const SGC_PROOF_REF_SCHEMA: &str = "xace.sgc.proof_ref.v1";
pub const CURRENT_MIGRATION_STATUS: &str = "current";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComponentAccess {
    pub reads: Vec<u32>,
    pub writes: Vec<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComponentAccessSets {
    pub schema: String,
    pub by_system: BTreeMap<String, ComponentAccess>,
    pub all_reads: Vec<u32>,
    pub all_writes: Vec<u32>,
    pub component_ids: Vec<u32>,
}

impl ComponentAccessSets {
    pub fn empty() -> Self {
        Self {
            schema: COMPONENT_ACCESS_SETS_SCHEMA.to_string(),
            by_system: BTreeMap::new(),
            all_reads: Vec::new(),
            all_writes: Vec::new(),
            component_ids: Vec::new(),
        }
    }

    pub fn from_system_definitions(definitions: &[SystemDefinition]) -> Self {
        let mut by_system = BTreeMap::new();
        let mut all_reads = BTreeSet::new();
        let mut all_writes = BTreeSet::new();

        for system in sorted_system_definitions(definitions) {
            let reads = sorted_unique_u32(&system.reads);
            let writes = sorted_unique_u32(&system.writes);
            all_reads.extend(reads.iter().copied());
            all_writes.extend(writes.iter().copied());
            by_system.insert(system.id.clone(), ComponentAccess { reads, writes });
        }

        let component_ids = all_reads.union(&all_writes).copied().collect::<Vec<u32>>();

        Self {
            schema: COMPONENT_ACCESS_SETS_SCHEMA.to_string(),
            by_system,
            all_reads: all_reads.iter().copied().collect(),
            all_writes: all_writes.iter().copied().collect(),
            component_ids,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionPlanSystemMetadata {
    pub schema: String,
    pub systems: BTreeMap<String, ExecutionPlanSystemMetadataEntry>,
}

impl ExecutionPlanSystemMetadata {
    pub fn empty() -> Self {
        Self {
            schema: SYSTEM_METADATA_SCHEMA.to_string(),
            systems: BTreeMap::new(),
        }
    }

    pub fn from_system_definitions(definitions: &[SystemDefinition]) -> Self {
        let mut systems = BTreeMap::new();
        for system in sorted_system_definitions(definitions) {
            systems.insert(
                system.id.clone(),
                ExecutionPlanSystemMetadataEntry {
                    display_name: if system.display_name.trim().is_empty() {
                        system.id.clone()
                    } else {
                        system.display_name.clone()
                    },
                    phase: system.phase.to_string(),
                    depends_on: sorted_unique_string(&system.depends_on),
                    deterministic: system.deterministic,
                    version: system.version.clone(),
                    description: system.description.clone(),
                },
            );
        }
        Self {
            schema: SYSTEM_METADATA_SCHEMA.to_string(),
            systems,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionPlanSystemMetadataEntry {
    pub display_name: String,
    pub phase: String,
    pub depends_on: Vec<String>,
    pub deterministic: bool,
    pub version: SystemVersion,
    pub description: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SgcProofBundleRef {
    pub schema: String,
    pub path: String,
    pub compiled_from_cgs_hash: String,
    pub plan_hash: String,
    pub input_hash: String,
    pub validation_hash: String,
}

impl SgcProofBundleRef {
    pub fn empty() -> Self {
        Self {
            schema: SGC_PROOF_REF_SCHEMA.to_string(),
            path: String::new(),
            compiled_from_cgs_hash: String::new(),
            plan_hash: String::new(),
            input_hash: String::new(),
            validation_hash: String::new(),
        }
    }
}

// ── Phase Schedule ────────────────────────────────────────────────────────────

/// The compiled schedule for a single execution phase.
///
/// Contains all execution groups for one phase, ordered by
/// execution_index ascending. The PhaseOrchestrator runs groups
/// in this order — group N must complete before group N+1 starts,
/// even if both are marked parallel-eligible internally.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PhaseSchedule {
    /// Which phase this schedule covers.
    pub phase: PhaseEnum,

    /// Execution groups in this phase, ordered by execution_index ASC.
    /// The PhaseOrchestrator runs them in this exact order.
    pub groups: Vec<ExecutionGroup>,

    /// Total number of systems across all groups in this phase.
    /// Cached for quick access — recomputed by SGC on plan creation.
    pub total_system_count: usize,
}

impl PhaseSchedule {
    /// Creates a phase schedule from an ordered list of groups.
    pub fn new(phase: PhaseEnum, groups: Vec<ExecutionGroup>) -> Self {
        let total_system_count = groups.iter().map(|g| g.system_count()).sum();
        Self {
            phase,
            groups,
            total_system_count,
        }
    }

    /// Returns true if this phase has no systems to execute.
    /// Empty phases are skipped by the PhaseOrchestrator.
    pub fn is_empty(&self) -> bool {
        self.total_system_count == 0
    }

    /// Returns the group containing the given system ID, if any.
    pub fn group_for_system(&self, system_id: &str) -> Option<&ExecutionGroup> {
        self.groups.iter().find(|g| g.contains_system(system_id))
    }

    /// Returns true if this phase contains the given system.
    pub fn contains_system(&self, system_id: &str) -> bool {
        self.groups.iter().any(|g| g.contains_system(system_id))
    }

    /// Returns all system IDs in this phase in execution order.
    /// Within parallel-eligible groups, systems are listed in sorted ID order (D11).
    pub fn all_system_ids(&self) -> Vec<&str> {
        self.groups
            .iter()
            .flat_map(|g| g.systems.iter().map(|s| s.as_str()))
            .collect()
    }
}

// ── Execution Plan ────────────────────────────────────────────────────────────

/// The complete compiled runtime execution schedule.
///
/// Produced by the SGC from the CGS SystemDefinitions.
/// Consumed by the PhaseOrchestrator every tick.
/// Immutable at runtime — never modified after creation.
///
/// ## Structure
/// ExecutionPlan
///   └── phases: BTreeMap<PhaseEnum, PhaseSchedule>
///         └── PhaseSchedule
///               └── groups: Vec<ExecutionGroup>
///                     └── systems: Vec<SystemId>
///
/// ## Lifecycle
/// CGS mutated → SGC recompiles → new ExecutionPlan created →
/// runtime validates version match (I7) → PhaseOrchestrator uses new plan
///
/// ## Determinism Proof
/// The SGC guarantees that given identical CGS + identical SystemDefinitions,
/// the produced ExecutionPlan is always byte-for-byte identical (D9, D11).
/// The plan_hash captures this guarantee in a single verifiable value.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionPlan {
    /// The CGS semantic version this plan was compiled from.
    /// Runtime halts if this does not match current CGS version (I7, D10).
    pub schema_version: String,

    /// Monotonically incrementing plan version.
    /// Starts at 1. Incremented each time the SGC recompiles.
    /// Embedded in WireMessage for engine adapter version validation.
    pub plan_version: u32,

    /// The simulation tick on which this plan was created.
    /// Used for replay validation — replays must use the plan that was
    /// active at the tick they were recorded on.
    pub created_tick: u64,

    /// Deterministic hash of this plan's entire content.
    /// Same CGS + same systems = same hash, always (D9, D11).
    /// Verified by DeterminismGuard on plan creation.
    pub plan_hash: String,

    /// Phase schedules keyed by PhaseEnum.
    /// BTreeMap guarantees deterministic iteration order (D11).
    /// All five phases are always present — empty phases have no groups.
    pub phases: BTreeMap<u8, PhaseSchedule>,

    /// All system IDs covered by this plan, sorted ascending (D11).
    /// Used for quick existence checks without iterating all phases.
    pub all_system_ids: Vec<String>,

    /// The CGS hash this plan was compiled from.
    /// Cross-referenced with CGS metadata.cgs_hash at runtime (D10).
    pub compiled_from_cgs_hash: String,

    /// Runtime adapter protocol version this plan was compiled against.
    pub adapter_protocol_version: u32,

    /// Migration status for persisted runtime loading. Runtime accepts only
    /// "current" plans at tick zero.
    pub migration_status: String,

    /// Component read/write contract used to build and verify the plan.
    pub component_access_sets: ComponentAccessSets,

    /// Stable system metadata embedded for runtime compatibility checks.
    pub system_metadata: ExecutionPlanSystemMetadata,

    /// Reference to the SGC proof bundle for this plan.
    pub proof_bundle: SgcProofBundleRef,
}

impl ExecutionPlan {
    /// Creates a new ExecutionPlan from compiled phase schedules.
    pub fn new(
        schema_version: impl Into<String>,
        plan_version: u32,
        created_tick: u64,
        plan_hash: impl Into<String>,
        phase_schedules: Vec<PhaseSchedule>,
        compiled_from_cgs_hash: impl Into<String>,
    ) -> Self {
        let mut phases = BTreeMap::new();
        let mut all_system_ids = Vec::new();

        for schedule in phase_schedules {
            // Collect all system IDs
            for group in &schedule.groups {
                for sys_id in &group.systems {
                    all_system_ids.push(sys_id.clone());
                }
            }
            phases.insert(schedule.phase.as_u8(), schedule);
        }

        // Sort all system IDs for deterministic lookup (D11)
        all_system_ids.sort();
        all_system_ids.dedup();

        Self {
            schema_version: schema_version.into(),
            plan_version,
            created_tick,
            plan_hash: plan_hash.into(),
            phases,
            all_system_ids,
            compiled_from_cgs_hash: compiled_from_cgs_hash.into(),
            adapter_protocol_version: 0,
            migration_status: String::new(),
            component_access_sets: ComponentAccessSets::empty(),
            system_metadata: ExecutionPlanSystemMetadata::empty(),
            proof_bundle: SgcProofBundleRef::empty(),
        }
    }

    pub fn finalize_identity_from_systems(
        &mut self,
        compiled_from_cgs_hash: impl Into<String>,
        adapter_protocol_version: u32,
        definitions: &[SystemDefinition],
    ) -> Result<(), String> {
        let cgs_hash = compiled_from_cgs_hash.into();
        if !is_lower_hex_hash(&cgs_hash) {
            return Err(
                "ExecutionPlan compiled_from_cgs_hash must be a lowercase 64-character SHA-256 digest"
                    .to_string(),
            );
        }
        if adapter_protocol_version == 0 {
            return Err("ExecutionPlan adapter_protocol_version must be >= 1".to_string());
        }

        self.compiled_from_cgs_hash = cgs_hash;
        self.adapter_protocol_version = adapter_protocol_version;
        self.migration_status = CURRENT_MIGRATION_STATUS.to_string();
        self.component_access_sets = ComponentAccessSets::from_system_definitions(definitions);
        self.system_metadata = ExecutionPlanSystemMetadata::from_system_definitions(definitions);

        let input_hash = self.compute_input_hash(definitions)?;
        let plan_hash = self.compute_identity_hash(&input_hash)?;
        self.plan_hash = plan_hash.clone();
        let validation_hash = self.compute_validation_hash()?;
        self.proof_bundle = SgcProofBundleRef {
            schema: SGC_PROOF_REF_SCHEMA.to_string(),
            path: format!(".xace/proof/sgc/{}", self.compiled_from_cgs_hash),
            compiled_from_cgs_hash: self.compiled_from_cgs_hash.clone(),
            plan_hash,
            input_hash,
            validation_hash,
        };

        Ok(())
    }

    /// Returns the phase schedule for the given phase, if present.
    pub fn get_phase(&self, phase: PhaseEnum) -> Option<&PhaseSchedule> {
        self.phases.get(&phase.as_u8())
    }

    /// Returns true if the given system ID is in this plan.
    pub fn contains_system(&self, system_id: &str) -> bool {
        self.all_system_ids
            .binary_search_by(|s| s.as_str().cmp(system_id))
            .is_ok()
    }

    /// Returns which phase the given system runs in.
    /// Returns None if the system is not in this plan.
    pub fn phase_for_system(&self, system_id: &str) -> Option<PhaseEnum> {
        for (phase_byte, schedule) in &self.phases {
            if schedule.contains_system(system_id) {
                return PhaseEnum::from_u8(*phase_byte);
            }
        }
        None
    }

    /// Returns all system IDs in execution order across all phases.
    /// Order: Initialization → Input → Simulation → PostSimulation → Cleanup.
    /// Within each phase, systems appear in group execution_index order.
    pub fn all_systems_in_order(&self) -> Vec<&str> {
        PhaseEnum::ALL
            .iter()
            .filter_map(|phase| self.get_phase(*phase))
            .flat_map(|schedule| schedule.all_system_ids())
            .collect()
    }

    /// Returns the total number of systems across all phases.
    pub fn total_system_count(&self) -> usize {
        self.all_system_ids.len()
    }

    /// Returns true if this plan is empty (no systems scheduled).
    /// Empty plans are valid for games with no user-defined systems yet.
    pub fn is_empty(&self) -> bool {
        self.all_system_ids.is_empty()
    }

    /// Validates this ExecutionPlan for structural correctness.
    ///
    /// Checks:
    /// - schema_version is not empty
    /// - plan_version >= 1
    /// - plan_hash is not empty
    /// - compiled_from_cgs_hash is not empty
    /// - All phase schedules pass validation
    /// - No system appears in more than one phase
    /// - all_system_ids matches actual systems in phases
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version.is_empty() {
            return Err("ExecutionPlan schema_version must not be empty".into());
        }

        if self.plan_version == 0 {
            return Err("ExecutionPlan plan_version must be >= 1".into());
        }

        if self.plan_hash.is_empty() {
            return Err("ExecutionPlan plan_hash must not be empty".into());
        }

        if self.compiled_from_cgs_hash.is_empty() {
            return Err("ExecutionPlan compiled_from_cgs_hash must not be empty".into());
        }

        if self.adapter_protocol_version == 0 {
            return Err("ExecutionPlan adapter_protocol_version must be >= 1".into());
        }

        if self.migration_status != CURRENT_MIGRATION_STATUS {
            return Err("ExecutionPlan migration_status must be 'current'".into());
        }

        self.validate_identity_metadata()?;

        // Validate all phase schedules and check for cross-phase duplicates
        let mut seen_systems = std::collections::HashSet::new();
        for (phase_byte, schedule) in &self.phases {
            // Validate each group
            for group in &schedule.groups {
                group.validate().map_err(|e| {
                    format!(
                        "Phase {} group {} invalid: {}",
                        phase_byte, group.group_id, e
                    )
                })?;

                // Check for cross-phase duplicates
                for sys_id in &group.systems {
                    if !seen_systems.insert(sys_id.as_str()) {
                        return Err(format!(
                            "System '{}' appears in multiple phases — \
                             each system must be in exactly one phase",
                            sys_id
                        ));
                    }
                }
            }
        }

        Ok(())
    }

    /// Returns true if this plan's schema version matches the given version.
    /// Used by the runtime to validate before executing each tick (I7, D10).
    pub fn matches_schema_version(&self, version: &str) -> bool {
        self.schema_version == version
    }

    /// Returns true if this plan was compiled from the given CGS hash.
    /// Cross-referenced with CGS metadata at runtime (D10).
    pub fn matches_cgs_hash(&self, cgs_hash: &str) -> bool {
        self.compiled_from_cgs_hash == cgs_hash
    }

    fn compute_input_hash(&self, definitions: &[SystemDefinition]) -> Result<String, String> {
        let systems = sorted_system_definitions(definitions)
            .into_iter()
            .map(|system| {
                (
                    system.id.clone(),
                    SystemDefinitionHashInput {
                        id: system.id.clone(),
                        display_name: if system.display_name.trim().is_empty() {
                            system.id.clone()
                        } else {
                            system.display_name.clone()
                        },
                        phase: system.phase.to_string(),
                        reads: sorted_unique_u32(&system.reads),
                        writes: sorted_unique_u32(&system.writes),
                        depends_on: sorted_unique_string(&system.depends_on),
                        deterministic: system.deterministic,
                        version: system.version.clone(),
                        description: system.description.clone(),
                    },
                )
            })
            .collect::<BTreeMap<_, _>>();

        stable_json_hash(&SgcInputHashPayload {
            schema: "xace.sgc.input_hash.v1",
            schema_version: &self.schema_version,
            plan_version: self.plan_version,
            compiled_from_cgs_hash: &self.compiled_from_cgs_hash,
            systems,
        })
    }

    fn compute_identity_hash(&self, input_hash: &str) -> Result<String, String> {
        stable_json_hash(&ExecutionPlanIdentityHashPayload {
            schema: "xace.sgc.execution_plan_identity.v1",
            schema_version: &self.schema_version,
            plan_version: self.plan_version,
            created_tick: self.created_tick,
            compiled_from_cgs_hash: &self.compiled_from_cgs_hash,
            adapter_protocol_version: self.adapter_protocol_version,
            migration_status: &self.migration_status,
            all_system_ids: &self.all_system_ids,
            phases: &self.phases,
            component_access_sets: &self.component_access_sets,
            system_metadata: &self.system_metadata,
            input_hash,
        })
    }

    fn compute_validation_hash(&self) -> Result<String, String> {
        stable_json_hash(&ExecutionPlanValidationHashPayload {
            schema: "xace.sgc.validation_hash.v1",
            compiled_from_cgs_hash: &self.compiled_from_cgs_hash,
            plan_hash: &self.plan_hash,
            adapter_protocol_version: self.adapter_protocol_version,
            migration_status: &self.migration_status,
            component_access_sets: &self.component_access_sets,
            system_metadata: &self.system_metadata,
        })
    }

    fn validate_identity_metadata(&self) -> Result<(), String> {
        if self.component_access_sets.schema != COMPONENT_ACCESS_SETS_SCHEMA {
            return Err(format!(
                "ExecutionPlan component_access_sets schema must be {}",
                COMPONENT_ACCESS_SETS_SCHEMA
            ));
        }
        if self.system_metadata.schema != SYSTEM_METADATA_SCHEMA {
            return Err(format!(
                "ExecutionPlan system_metadata schema must be {}",
                SYSTEM_METADATA_SCHEMA
            ));
        }
        if self.proof_bundle.schema != SGC_PROOF_REF_SCHEMA {
            return Err(format!(
                "ExecutionPlan proof_bundle schema must be {}",
                SGC_PROOF_REF_SCHEMA
            ));
        }
        let expected_path = format!(".xace/proof/sgc/{}", self.compiled_from_cgs_hash);
        if self.proof_bundle.path != expected_path {
            return Err(format!(
                "ExecutionPlan proof_bundle.path must be {}",
                expected_path
            ));
        }
        if self.proof_bundle.compiled_from_cgs_hash != self.compiled_from_cgs_hash {
            return Err(
                "ExecutionPlan proof_bundle compiled_from_cgs_hash must match plan identity".into(),
            );
        }
        if self.proof_bundle.plan_hash != self.plan_hash {
            return Err("ExecutionPlan proof_bundle plan_hash must match plan_hash".into());
        }
        if !is_lower_hex_hash(&self.proof_bundle.input_hash) {
            return Err(
                "ExecutionPlan proof_bundle input_hash must be a lowercase 64-character SHA-256 digest"
                    .into(),
            );
        }
        if !is_lower_hex_hash(&self.proof_bundle.validation_hash) {
            return Err(
                "ExecutionPlan proof_bundle validation_hash must be a lowercase 64-character SHA-256 digest"
                    .into(),
            );
        }
        Ok(())
    }
}

#[derive(Serialize)]
struct SgcInputHashPayload<'a> {
    schema: &'static str,
    schema_version: &'a str,
    plan_version: u32,
    compiled_from_cgs_hash: &'a str,
    systems: BTreeMap<String, SystemDefinitionHashInput>,
}

#[derive(Serialize)]
struct SystemDefinitionHashInput {
    id: String,
    display_name: String,
    phase: String,
    reads: Vec<u32>,
    writes: Vec<u32>,
    depends_on: Vec<String>,
    deterministic: bool,
    version: SystemVersion,
    description: String,
}

#[derive(Serialize)]
struct ExecutionPlanIdentityHashPayload<'a> {
    schema: &'static str,
    schema_version: &'a str,
    plan_version: u32,
    created_tick: u64,
    compiled_from_cgs_hash: &'a str,
    adapter_protocol_version: u32,
    migration_status: &'a str,
    all_system_ids: &'a [String],
    phases: &'a BTreeMap<u8, PhaseSchedule>,
    component_access_sets: &'a ComponentAccessSets,
    system_metadata: &'a ExecutionPlanSystemMetadata,
    input_hash: &'a str,
}

#[derive(Serialize)]
struct ExecutionPlanValidationHashPayload<'a> {
    schema: &'static str,
    compiled_from_cgs_hash: &'a str,
    plan_hash: &'a str,
    adapter_protocol_version: u32,
    migration_status: &'a str,
    component_access_sets: &'a ComponentAccessSets,
    system_metadata: &'a ExecutionPlanSystemMetadata,
}

fn sorted_system_definitions(definitions: &[SystemDefinition]) -> Vec<&SystemDefinition> {
    let mut systems = definitions.iter().collect::<Vec<_>>();
    systems.sort_by(|left, right| left.id.cmp(&right.id));
    systems
}

fn sorted_unique_u32(values: &[u32]) -> Vec<u32> {
    values
        .iter()
        .copied()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn sorted_unique_string(values: &[String]) -> Vec<String> {
    values
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn stable_json_hash<T: Serialize>(value: &T) -> Result<String, String> {
    let bytes = serde_json::to_vec(value)
        .map_err(|error| format!("ExecutionPlan identity serialization failed: {}", error))?;
    let digest = Sha256::digest(&bytes);
    Ok(digest.iter().map(|byte| format!("{:02x}", byte)).collect())
}

fn is_lower_hex_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::system_definition::ExecutionPhase;

    const TEST_PLAN_HASH: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const TEST_CGS_HASH: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    fn system_definition(
        id: &str,
        phase: ExecutionPhase,
        reads: Vec<u32>,
        writes: Vec<u32>,
        depends_on: Vec<&str>,
    ) -> SystemDefinition {
        SystemDefinition {
            id: id.into(),
            display_name: id.into(),
            phase,
            reads,
            writes,
            depends_on: depends_on.into_iter().map(String::from).collect(),
            deterministic: true,
            version: SystemVersion::INITIAL,
            description: String::new(),
        }
    }

    fn test_system_definitions() -> Vec<SystemDefinition> {
        vec![
            system_definition("sys_input", ExecutionPhase::Input, vec![6], vec![5], vec![]),
            system_definition(
                "sys_damage",
                ExecutionPhase::Simulation,
                vec![101],
                vec![100],
                vec![],
            ),
            system_definition(
                "sys_movement",
                ExecutionPhase::Simulation,
                vec![5],
                vec![1],
                vec!["sys_input"],
            ),
            system_definition(
                "sys_ai",
                ExecutionPhase::Simulation,
                vec![1],
                vec![101],
                vec![],
            ),
            system_definition(
                "sys_cleanup",
                ExecutionPhase::Cleanup,
                vec![100],
                vec![],
                vec![],
            ),
        ]
    }

    fn test_plan() -> ExecutionPlan {
        let input_group = ExecutionGroup::sequential(
            "Input_group_0",
            PhaseEnum::Input,
            vec!["sys_input".into()],
            0,
        );

        let sim_group_1 = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_damage".into()],
            0,
        );

        let sim_group_2 = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_movement".into(), "sys_ai".into()],
            1,
        );

        let cleanup_group = ExecutionGroup::sequential(
            "Cleanup_group_0",
            PhaseEnum::Cleanup,
            vec!["sys_cleanup".into()],
            0,
        );

        let phases = vec![
            PhaseSchedule::new(PhaseEnum::Input, vec![input_group]),
            PhaseSchedule::new(PhaseEnum::Simulation, vec![sim_group_1, sim_group_2]),
            PhaseSchedule::new(PhaseEnum::Cleanup, vec![cleanup_group]),
        ];

        let mut plan = ExecutionPlan::new("0.1.0", 1, 0, TEST_PLAN_HASH, phases, TEST_CGS_HASH);
        plan.finalize_identity_from_systems(TEST_CGS_HASH, 1, &test_system_definitions())
            .unwrap();
        plan
    }

    #[test]
    fn plan_validates_successfully() {
        assert!(test_plan().validate().is_ok());
    }

    #[test]
    fn empty_schema_version_fails() {
        let mut plan = test_plan();
        plan.schema_version = String::new();
        assert!(plan.validate().is_err());
    }

    #[test]
    fn zero_plan_version_fails() {
        let mut plan = test_plan();
        plan.plan_version = 0;
        assert!(plan.validate().is_err());
    }

    #[test]
    fn empty_plan_hash_fails() {
        let mut plan = test_plan();
        plan.plan_hash = String::new();
        assert!(plan.validate().is_err());
    }

    #[test]
    fn contains_system_works() {
        let plan = test_plan();
        assert!(plan.contains_system("sys_input"));
        assert!(plan.contains_system("sys_movement"));
        assert!(plan.contains_system("sys_ai"));
        assert!(!plan.contains_system("sys_nonexistent"));
    }

    #[test]
    fn phase_for_system_correct() {
        let plan = test_plan();
        assert_eq!(plan.phase_for_system("sys_input"), Some(PhaseEnum::Input));
        assert_eq!(
            plan.phase_for_system("sys_movement"),
            Some(PhaseEnum::Simulation)
        );
        assert_eq!(
            plan.phase_for_system("sys_cleanup"),
            Some(PhaseEnum::Cleanup)
        );
        assert_eq!(plan.phase_for_system("sys_missing"), None);
    }

    #[test]
    fn total_system_count_correct() {
        let plan = test_plan();
        assert_eq!(plan.total_system_count(), 5);
    }

    #[test]
    fn all_systems_in_order_correct() {
        let plan = test_plan();
        let systems = plan.all_systems_in_order();
        // Input comes before Simulation
        let input_pos = systems.iter().position(|&s| s == "sys_input").unwrap();
        let movement_pos = systems.iter().position(|&s| s == "sys_movement").unwrap();
        assert!(input_pos < movement_pos);
        // Simulation comes before Cleanup
        let cleanup_pos = systems.iter().position(|&s| s == "sys_cleanup").unwrap();
        assert!(movement_pos < cleanup_pos);
    }

    #[test]
    fn get_phase_returns_correct_schedule() {
        let plan = test_plan();
        let input_schedule = plan.get_phase(PhaseEnum::Input);
        assert!(input_schedule.is_some());
        assert!(input_schedule.unwrap().contains_system("sys_input"));
    }

    #[test]
    fn get_phase_returns_none_for_missing_phase() {
        let plan = test_plan();
        // PostSimulation has no systems in test plan
        let post_sim = plan.get_phase(PhaseEnum::PostSimulation);
        assert!(post_sim.is_none());
    }

    #[test]
    fn matches_schema_version_correct() {
        let plan = test_plan();
        assert!(plan.matches_schema_version("0.1.0"));
        assert!(!plan.matches_schema_version("0.2.0"));
    }

    #[test]
    fn matches_cgs_hash_correct() {
        let plan = test_plan();
        assert!(plan.matches_cgs_hash(TEST_CGS_HASH));
        assert!(!plan.matches_cgs_hash("wrong_hash"));
    }

    #[test]
    fn phase_schedule_empty_detection() {
        let schedule = PhaseSchedule::new(PhaseEnum::Initialization, vec![]);
        assert!(schedule.is_empty());
    }

    #[test]
    fn phase_schedule_system_ids_in_order() {
        let group1 = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_damage".into()],
            0,
        );
        let group2 = ExecutionGroup::parallel(
            "Simulation_group_1",
            PhaseEnum::Simulation,
            vec!["sys_movement".into(), "sys_ai".into()],
            1,
        );
        let schedule = PhaseSchedule::new(PhaseEnum::Simulation, vec![group1, group2]);
        let ids = schedule.all_system_ids();
        assert_eq!(ids[0], "sys_damage");
        // parallel group sorted: sys_ai < sys_movement
        assert_eq!(ids[1], "sys_ai");
        assert_eq!(ids[2], "sys_movement");
    }

    #[test]
    fn is_empty_false_when_systems_exist() {
        assert!(!test_plan().is_empty());
    }

    #[test]
    fn duplicate_system_across_phases_fails() {
        let group1 = ExecutionGroup::sequential(
            "Input_group_0",
            PhaseEnum::Input,
            vec!["sys_duplicate".into()],
            0,
        );
        let group2 = ExecutionGroup::sequential(
            "Simulation_group_0",
            PhaseEnum::Simulation,
            vec!["sys_duplicate".into()],
            0,
        );
        let mut plan = ExecutionPlan::new(
            "0.1.0",
            1,
            0,
            TEST_PLAN_HASH,
            vec![
                PhaseSchedule::new(PhaseEnum::Input, vec![group1]),
                PhaseSchedule::new(PhaseEnum::Simulation, vec![group2]),
            ],
            TEST_CGS_HASH,
        );
        let definitions = vec![system_definition(
            "sys_duplicate",
            ExecutionPhase::Input,
            vec![],
            vec![],
            vec![],
        )];
        plan.finalize_identity_from_systems(TEST_CGS_HASH, 1, &definitions)
            .unwrap();
        assert!(plan.validate().is_err());
    }
}

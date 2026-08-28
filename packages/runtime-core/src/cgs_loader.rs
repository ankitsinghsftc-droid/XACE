//! CGS loader for the standalone runtime.
//!
//! The loader is deliberately conservative: it validates the minimal CGS shape
//! required by the runtime, registers every component table referenced by
//! actors or system access sets, spawns initial entities deterministically, and
//! loads the persisted SGC `ExecutionPlan` as the authoritative schedule when
//! present or required by runtime policy.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use xace_core::assets::SemanticBindingTable;

use crate::component_tables::component_table_store::ComponentTableStore;
use crate::engine_protocol::PROTOCOL_VERSION as ENGINE_ADAPTER_PROTOCOL_VERSION;
use crate::entity_store::entity_store::EntityStore;

pub type RuntimePhasePlan = Vec<(String, Vec<String>, bool)>;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeSchedulePlan {
    pub source: RuntimePhasePlanSource,
    pub schema_version: String,
    pub plan_version: u32,
    pub plan_hash: String,
    pub compiled_from_cgs_hash: String,
    pub plan_path: Option<PathBuf>,
    pub groups: Vec<RuntimeScheduleGroup>,
    pub system_access: BTreeMap<String, RuntimeComponentAccess>,
    pub system_dependencies: BTreeMap<String, Vec<String>>,
}

impl RuntimeSchedulePlan {
    pub fn identity(&self) -> RuntimeScheduleIdentity {
        RuntimeScheduleIdentity {
            schema: "xace.runtime.schedule_identity.v1".to_string(),
            source: self.source,
            schema_version: self.schema_version.clone(),
            plan_version: self.plan_version,
            plan_hash: self.plan_hash.clone(),
            cgs_hash: self.compiled_from_cgs_hash.clone(),
            compiled_from_cgs_hash: self.compiled_from_cgs_hash.clone(),
            scheduled_system_ids: scheduled_system_ids_from_groups(&self.groups),
            groups: self.groups.clone(),
            system_access: self.system_access.clone(),
            system_dependencies: self.system_dependencies.clone(),
        }
    }

    pub fn phase_plan(&self) -> RuntimePhasePlan {
        self.groups
            .iter()
            .map(|group| (group.phase.clone(), group.systems.clone(), group.parallel))
            .collect()
    }

    pub fn phase_plan_for_runtime(&self) -> Vec<(&str, Vec<String>, bool)> {
        self.groups
            .iter()
            .map(|group| (group.phase.as_str(), group.systems.clone(), group.parallel))
            .collect()
    }

    pub fn snapshot_for_tick(&self, tick: u64) -> RuntimeScheduleSnapshot {
        self.identity().snapshot_for_tick(tick)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeScheduleIdentity {
    pub schema: String,
    pub source: RuntimePhasePlanSource,
    pub schema_version: String,
    pub plan_version: u32,
    pub plan_hash: String,
    pub cgs_hash: String,
    pub compiled_from_cgs_hash: String,
    pub scheduled_system_ids: Vec<String>,
    pub groups: Vec<RuntimeScheduleGroup>,
    pub system_access: BTreeMap<String, RuntimeComponentAccess>,
    pub system_dependencies: BTreeMap<String, Vec<String>>,
}

impl RuntimeScheduleIdentity {
    pub fn snapshot_for_tick(&self, tick: u64) -> RuntimeScheduleSnapshot {
        RuntimeScheduleSnapshot {
            schema: "xace.runtime.schedule_snapshot.v1".to_string(),
            tick,
            source: self.source,
            schema_version: self.schema_version.clone(),
            plan_version: self.plan_version,
            plan_hash: self.plan_hash.clone(),
            cgs_hash: self.cgs_hash.clone(),
            compiled_from_cgs_hash: self.compiled_from_cgs_hash.clone(),
            scheduled_system_ids: self.scheduled_system_ids.clone(),
            groups: self.groups.clone(),
            system_access: self.system_access.clone(),
            system_dependencies: self.system_dependencies.clone(),
        }
    }

    pub fn phase_plan_for_runtime(&self) -> Vec<(&str, Vec<String>, bool)> {
        self.groups
            .iter()
            .map(|group| (group.phase.as_str(), group.systems.clone(), group.parallel))
            .collect()
    }

    pub fn validate_snapshot(
        &self,
        snapshot: &RuntimeScheduleSnapshot,
    ) -> std::result::Result<(), String> {
        if snapshot.schema != "xace.runtime.schedule_snapshot.v1" {
            return Err(format!(
                "schema drift: expected 'xace.runtime.schedule_snapshot.v1', got '{}'",
                snapshot.schema
            ));
        }
        compare_schedule_identity("source", &self.source, &snapshot.source)?;
        compare_schedule_identity(
            "schema_version",
            &self.schema_version,
            &snapshot.schema_version,
        )?;
        compare_schedule_identity("plan_version", &self.plan_version, &snapshot.plan_version)?;
        compare_schedule_identity("plan_hash", &self.plan_hash, &snapshot.plan_hash)?;
        compare_schedule_identity("cgs_hash", &self.cgs_hash, &snapshot.cgs_hash)?;
        compare_schedule_identity(
            "compiled_from_cgs_hash",
            &self.compiled_from_cgs_hash,
            &snapshot.compiled_from_cgs_hash,
        )?;
        compare_schedule_identity(
            "scheduled_system_ids",
            &self.scheduled_system_ids,
            &snapshot.scheduled_system_ids,
        )?;
        compare_schedule_identity("groups", &self.groups, &snapshot.groups)?;
        compare_schedule_identity(
            "system_access",
            &self.system_access,
            &snapshot.system_access,
        )?;
        compare_schedule_identity(
            "system_dependencies",
            &self.system_dependencies,
            &snapshot.system_dependencies,
        )?;
        Ok(())
    }
}

fn compare_schedule_identity<T: PartialEq + std::fmt::Debug>(
    field: &str,
    expected: &T,
    actual: &T,
) -> std::result::Result<(), String> {
    if expected == actual {
        Ok(())
    } else {
        Err(format!(
            "{} drift: expected {:?}, got {:?}",
            field, expected, actual
        ))
    }
}

fn scheduled_system_ids_from_groups(groups: &[RuntimeScheduleGroup]) -> Vec<String> {
    groups
        .iter()
        .flat_map(|group| group.systems.iter().cloned())
        .collect()
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeScheduleGroup {
    pub group_id: String,
    pub phase: String,
    pub parallel: bool,
    pub systems: Vec<String>,
    pub serialization_constraints: Vec<String>,
    pub execution_index: u32,
    pub component_access: BTreeMap<String, RuntimeComponentAccess>,
    pub depends_on: BTreeMap<String, Vec<String>>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeComponentAccess {
    pub reads: Vec<u32>,
    pub writes: Vec<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeScheduleSnapshot {
    pub schema: String,
    pub tick: u64,
    pub source: RuntimePhasePlanSource,
    pub schema_version: String,
    pub plan_version: u32,
    pub plan_hash: String,
    pub cgs_hash: String,
    pub compiled_from_cgs_hash: String,
    pub scheduled_system_ids: Vec<String>,
    pub groups: Vec<RuntimeScheduleGroup>,
    pub system_access: BTreeMap<String, RuntimeComponentAccess>,
    pub system_dependencies: BTreeMap<String, Vec<String>>,
}

impl RuntimeScheduleSnapshot {
    pub fn phase_plan_for_runtime(&self) -> Vec<(&str, Vec<String>, bool)> {
        self.groups
            .iter()
            .map(|group| (group.phase.as_str(), group.systems.clone(), group.parallel))
            .collect()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SgcPlanPolicy {
    /// Compatibility mode: load a persisted plan when present, but never
    /// silently derive a runtime schedule when it is missing.
    PreferPersisted,
    /// Production mode: a compatible persisted SGC plan is mandatory.
    RequirePersisted,
    /// Explicit development/test mode for CGS-derived schedules.
    DeriveFromCgs,
}

impl Default for SgcPlanPolicy {
    fn default() -> Self {
        Self::RequirePersisted
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimePhasePlanSource {
    PersistedSgc,
    CgsDerived,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CgsRoot {
    #[serde(default)]
    pub metadata: serde_json::Value,
    #[serde(default)]
    pub semantic_bindings: SemanticBindingTable,
    #[serde(default)]
    pub component_schemas: Vec<CgsComponentSchema>,
    #[serde(default)]
    pub global_systems: Vec<CgsSystem>,
    #[serde(default)]
    pub modes: Vec<CgsMode>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CgsComponentSchema {
    #[serde(default)]
    pub type_id: u32,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub defaults: serde_json::Value,
    #[serde(default)]
    pub source: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CgsMode {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub schema_version: String,
    #[serde(default)]
    pub is_default: bool,
    #[serde(default)]
    pub actors: Vec<CgsActor>,
    #[serde(default)]
    pub systems: Vec<CgsSystem>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CgsActor {
    #[serde(default)]
    pub id: String,
    #[serde(default = "one")]
    pub spawn_count: u32,
    #[serde(default)]
    pub components: Vec<CgsComponent>,
}

fn one() -> u32 {
    1
}

#[derive(Debug, Clone, Deserialize)]
pub struct CgsComponent {
    #[serde(default)]
    pub type_id: u32,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub defaults: serde_json::Value,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CgsSystem {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub phase: String,
    #[serde(default)]
    pub reads: Vec<u32>,
    #[serde(default)]
    pub writes: Vec<u32>,
    #[serde(default)]
    pub depends_on: Vec<String>,
    #[serde(default = "default_true")]
    pub deterministic: bool,
    #[serde(default)]
    pub parallel: bool,
    #[serde(default)]
    pub runtime_executor: serde_json::Value,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone)]
pub struct ComponentRegistration {
    pub type_id: u32,
    pub name: String,
    pub source: ComponentRegistrationSource,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ComponentRegistrationSource {
    ActorComponent,
    CgsSchema,
    GeneratedSchema,
    PluginSchema,
    SystemRead,
    SystemWrite,
    Builtin,
}

#[derive(Debug, Clone)]
pub struct SpawnedActor {
    pub actor_id: String,
    pub entity_ids: Vec<u64>,
}

#[derive(Debug, Clone)]
pub struct SpawnSummary {
    pub source_path: PathBuf,
    pub mode_id: String,
    pub actor_count: u32,
    pub entity_count: u32,
    pub schema_version: String,
    pub cgs_hash: String,
    pub execution_plan_version: u32,
    pub execution_plan_hash: String,
    pub execution_plan_path: Option<PathBuf>,
    pub phase_plan_source: RuntimePhasePlanSource,
    pub registered_components: Vec<ComponentRegistration>,
    pub runtime_systems: Vec<CgsSystem>,
    pub phase_plan: RuntimePhasePlan,
    pub schedule_plan: RuntimeSchedulePlan,
    pub spawned_actors: Vec<SpawnedActor>,
    pub semantic_bindings: SemanticBindingTable,
}

impl SpawnSummary {
    pub fn phase_plan_for_runtime(&self) -> Vec<(&str, Vec<String>, bool)> {
        self.phase_plan
            .iter()
            .map(|(phase, systems, parallel)| (phase.as_str(), systems.clone(), *parallel))
            .collect()
    }
}

pub fn load_cgs(cgs_path: &Path) -> Result<CgsRoot> {
    let bytes = fs::read(cgs_path)
        .map_err(|err| anyhow::anyhow!("cannot read '{}': {}", cgs_path.display(), err))?;
    let raw_cgs: Value = serde_json::from_slice(&bytes).map_err(|err| {
        anyhow::anyhow!("cannot parse CGS JSON '{}': {}", cgs_path.display(), err)
    })?;
    validate_cgs_raw_top_level(&raw_cgs)?;
    let cgs: CgsRoot = serde_json::from_value(raw_cgs.clone()).map_err(|err| {
        anyhow::anyhow!(
            "cannot parse typed CGS JSON '{}': {}",
            cgs_path.display(),
            err
        )
    })?;
    validate_cgs_for_runtime(&cgs, &raw_cgs)?;
    Ok(cgs)
}

pub fn load_and_spawn(
    cgs_path: &Path,
    entity_store: &mut EntityStore,
    table_store: &mut ComponentTableStore,
) -> Result<SpawnSummary> {
    load_and_spawn_with_plan_policy(
        cgs_path,
        entity_store,
        table_store,
        SgcPlanPolicy::RequirePersisted,
        None,
    )
}

pub fn load_and_spawn_with_plan_policy(
    cgs_path: &Path,
    entity_store: &mut EntityStore,
    table_store: &mut ComponentTableStore,
    plan_policy: SgcPlanPolicy,
    explicit_plan_path: Option<&Path>,
) -> Result<SpawnSummary> {
    let bytes = fs::read(cgs_path)
        .map_err(|err| anyhow::anyhow!("cannot read '{}': {}", cgs_path.display(), err))?;
    let raw_cgs: Value = serde_json::from_slice(&bytes)
        .map_err(|err| anyhow::anyhow!("cannot parse CGS JSON: {}", err))?;
    validate_cgs_raw_top_level(&raw_cgs)?;
    let cgs: CgsRoot = serde_json::from_value(raw_cgs.clone())
        .map_err(|err| anyhow::anyhow!("cannot parse typed CGS JSON: {}", err))?;
    validate_cgs_for_runtime(&cgs, &raw_cgs)?;
    let mode =
        pick_default_mode(&cgs.modes).ok_or_else(|| anyhow::anyhow!("CGS has no modes defined"))?;

    validate_mode(mode)?;
    let semantic_bindings = SemanticBindingTable::new(cgs.semantic_bindings.bindings.clone());
    semantic_bindings
        .validate()
        .map_err(|err| anyhow::anyhow!("invalid semantic_bindings: {}", err))?;
    let registrations = register_all_component_tables(table_store, &cgs)?;
    let runtime_systems = cgs
        .global_systems
        .iter()
        .chain(mode.systems.iter())
        .cloned()
        .collect::<Vec<_>>();

    let mut actor_count = 0u32;
    let mut entity_count = 0u32;
    let mut spawned_actors = Vec::new();

    for actor in &mode.actors {
        actor_count = actor_count.saturating_add(1);
        let count = actor.spawn_count.max(1);
        let mut entity_ids = Vec::with_capacity(count as usize);

        for instance in 0..count {
            let entity_id = entity_store
                .create_entity(0)
                .map_err(|err| anyhow::anyhow!("create_entity actor='{}': {}", actor.id, err))?;
            for component in &actor.components {
                let json = component.defaults.to_string();
                table_store
                    .add_component(entity_id, component.type_id, json, 0)
                    .map_err(|err| {
                        anyhow::anyhow!(
                            "add_component entity={} type_id={}: {}",
                            entity_id,
                            component.type_id,
                            err
                        )
                    })?;
            }
            entity_ids.push(entity_id);
            entity_count = entity_count.saturating_add(1);
            log::debug!(
                "Spawned entity {} (actor='{}' {}/{})",
                entity_id,
                actor.id,
                instance + 1,
                count
            );
        }

        spawned_actors.push(SpawnedActor {
            actor_id: actor.id.clone(),
            entity_ids,
        });
    }

    let schema_version = extract_str(&mode.schema_version)
        .or_else(|| extract_metadata_str(&cgs.metadata, "schema_version"))
        .or_else(|| extract_metadata_str(&cgs.metadata, "version"))
        .unwrap_or("0.1.0")
        .to_string();
    let cgs_hash = extract_metadata_str(&cgs.metadata, "cgs_hash")
        .map(str::to_string)
        .unwrap_or_else(|| canonical_content_hash(&bytes));
    let loaded_plan = load_runtime_phase_plan(
        cgs_path,
        mode,
        &cgs.global_systems,
        &schema_version,
        &cgs_hash,
        &cgs.metadata,
        plan_policy,
        explicit_plan_path,
    )?;
    let phase_plan = loaded_plan.schedule_plan.phase_plan();

    log::info!(
        "Loaded '{}': mode='{}' actors={} entities={} systems={} plan_source={:?}",
        cgs_path.file_name().unwrap_or_default().to_string_lossy(),
        mode.id,
        actor_count,
        entity_count,
        phase_plan
            .iter()
            .map(|(_, systems, _)| systems.len())
            .sum::<usize>(),
        loaded_plan.schedule_plan.source
    );

    Ok(SpawnSummary {
        source_path: cgs_path.to_path_buf(),
        mode_id: mode.id.clone(),
        actor_count,
        entity_count,
        schema_version,
        cgs_hash,
        execution_plan_version: loaded_plan.schedule_plan.plan_version,
        execution_plan_hash: loaded_plan.schedule_plan.plan_hash.clone(),
        execution_plan_path: loaded_plan.schedule_plan.plan_path.clone(),
        phase_plan_source: loaded_plan.schedule_plan.source,
        registered_components: registrations,
        runtime_systems,
        phase_plan,
        schedule_plan: loaded_plan.schedule_plan,
        spawned_actors,
        semantic_bindings,
    })
}

pub fn register_all_component_tables(
    table_store: &mut ComponentTableStore,
    cgs: &CgsRoot,
) -> Result<Vec<ComponentRegistration>> {
    let registrations = collect_component_registrations(cgs)?;
    register_component_tables(table_store, &registrations)?;
    Ok(registrations)
}

const CGS_SCHEMA_VALIDATION_PREFIX: &str = "CGS schema validation failed before runtime load";

fn validate_cgs_raw_top_level(raw_cgs: &Value) -> Result<()> {
    if !raw_cgs.is_object() {
        anyhow::bail!(
            "{}: top-level JSON value must be an object",
            CGS_SCHEMA_VALIDATION_PREFIX
        );
    }
    Ok(())
}

fn validate_cgs_for_runtime(cgs: &CgsRoot, raw_cgs: &Value) -> Result<()> {
    let mut issues = Vec::new();
    let Some(root) = raw_cgs.as_object() else {
        issues.push("top-level JSON value must be an object".to_string());
        return Err(cgs_schema_error(issues));
    };

    for field in ["metadata", "global_systems", "modes"] {
        if !root.contains_key(field) {
            issues.push(format!("missing top-level field '{}'", field));
        }
    }
    require_raw_array(root, "global_systems", "global_systems", &mut issues);
    require_raw_array(root, "modes", "modes", &mut issues);
    if root.contains_key("component_schemas") {
        require_raw_array(root, "component_schemas", "component_schemas", &mut issues);
    }

    let metadata_schema_version =
        validate_cgs_metadata(root.get("metadata"), root, &mut issues).unwrap_or_default();
    let mut declared_components = builtin_component_names()
        .into_iter()
        .map(|(type_id, name)| (type_id, name.to_string()))
        .collect::<BTreeMap<_, _>>();

    validate_cgs_component_schemas(
        &cgs.component_schemas,
        raw_cgs.get("component_schemas").and_then(Value::as_array),
        &mut declared_components,
        &mut issues,
    );
    validate_cgs_modes(
        cgs,
        raw_cgs,
        &metadata_schema_version,
        &mut declared_components,
        &mut issues,
    );
    validate_cgs_systems(cgs, raw_cgs, &declared_components, &mut issues);

    if issues.is_empty() {
        Ok(())
    } else {
        Err(cgs_schema_error(issues))
    }
}

fn cgs_schema_error(issues: Vec<String>) -> anyhow::Error {
    anyhow::anyhow!("{}: {}", CGS_SCHEMA_VALIDATION_PREFIX, issues.join("; "))
}

fn validate_cgs_metadata(
    metadata: Option<&Value>,
    root: &serde_json::Map<String, Value>,
    issues: &mut Vec<String>,
) -> Option<String> {
    let Some(metadata) = metadata else {
        issues.push("metadata is required".to_string());
        return None;
    };
    let Some(metadata) = metadata.as_object() else {
        issues.push("metadata must be an object".to_string());
        return None;
    };

    required_nonempty_string(metadata.get("name"), "metadata.name", issues);
    required_semver_string(metadata.get("version"), "metadata.version", issues);
    let schema_version = required_semver_string(
        metadata.get("schema_version"),
        "metadata.schema_version",
        issues,
    );

    match required_nonempty_string(metadata.get("cgs_hash"), "metadata.cgs_hash", issues) {
        Some(cgs_hash) if cgs_hash == "0".repeat(64) => {
            issues.push("metadata.cgs_hash must not be an unresolved zero digest".to_string());
        }
        Some(cgs_hash) if !is_lower_hex_hash(&cgs_hash) => {
            issues.push(
                "metadata.cgs_hash must be a lowercase 64-character SHA-256 digest".to_string(),
            );
        }
        _ => {}
    }

    if let Some(value) = metadata.get("execution_plan_version") {
        validate_positive_u32(value, "metadata.execution_plan_version", issues);
    }

    validate_optional_cgs_format(root, issues);
    validate_optional_cgs_metadata_extensions(root, metadata, issues);
    schema_version
}

fn validate_optional_cgs_format(root: &serde_json::Map<String, Value>, issues: &mut Vec<String>) {
    if let Some(value) = root.get("format") {
        if value.as_str() != Some("xace.cgs.export") {
            issues.push("format must be 'xace.cgs.export' when present".to_string());
        }
    }
    if let Some(value) = root.get("format_version") {
        required_semver_string(Some(value), "format_version", issues);
    }
}

fn validate_optional_cgs_metadata_extensions(
    root: &serde_json::Map<String, Value>,
    metadata: &serde_json::Map<String, Value>,
    issues: &mut Vec<String>,
) {
    if let Some(value) = root.get("semantic_bindings") {
        if !value.is_object() {
            issues.push("semantic_bindings must be an object when present".to_string());
        }
    }
    if let Some(value) = root.get("assets") {
        validate_asset_metadata(value, "assets", issues);
    }
    if let Some(value) = metadata.get("assets") {
        validate_asset_metadata(value, "metadata.assets", issues);
    }
    if let Some(value) = metadata.get("networking") {
        validate_networking_metadata(value, "metadata.networking", issues);
    }
    for key in ["save", "saves", "save_metadata"] {
        if let Some(value) = metadata.get(key) {
            validate_save_metadata(value, &format!("metadata.{}", key), issues);
        }
    }
}

fn validate_asset_metadata(value: &Value, path: &str, issues: &mut Vec<String>) {
    match value {
        Value::Array(items) => {
            for (index, item) in items.iter().enumerate() {
                validate_asset_entry(item, &format!("{}[{}]", path, index), issues);
            }
        }
        Value::Object(map) => {
            if let Some(items) = map.get("items") {
                match items {
                    Value::Array(items) => {
                        for (index, item) in items.iter().enumerate() {
                            validate_asset_entry(
                                item,
                                &format!("{}.items[{}]", path, index),
                                issues,
                            );
                        }
                    }
                    _ => issues.push(format!("{}.items must be an array when present", path)),
                }
            }
        }
        _ => issues.push(format!("{} must be an object or array when present", path)),
    }
}

fn validate_asset_entry(value: &Value, path: &str, issues: &mut Vec<String>) {
    let Some(entry) = value.as_object() else {
        issues.push(format!("{} must be an object", path));
        return;
    };
    for field in ["id", "asset_type", "status", "path", "source_path"] {
        if let Some(value) = entry.get(field) {
            if !value.as_str().is_some_and(|text| !text.trim().is_empty()) {
                issues.push(format!("{}.{} must be a non-empty string", path, field));
            }
        }
    }
}

fn validate_networking_metadata(value: &Value, path: &str, issues: &mut Vec<String>) {
    let Some(metadata) = value.as_object() else {
        issues.push(format!("{} must be an object when present", path));
        return;
    };
    for field in ["mode", "authority", "status"] {
        if let Some(value) = metadata.get(field) {
            if !value.as_str().is_some_and(|text| !text.trim().is_empty()) {
                issues.push(format!("{}.{} must be a non-empty string", path, field));
            }
        }
    }
    if let Some(value) = metadata.get("max_players") {
        validate_positive_u32(value, &format!("{}.max_players", path), issues);
    }
}

fn validate_save_metadata(value: &Value, path: &str, issues: &mut Vec<String>) {
    match value {
        Value::Object(map) => {
            if let Some(version) = map.get("version") {
                required_semver_string(Some(version), &format!("{}.version", path), issues);
            }
            for field in ["strategy", "mode", "backend", "status"] {
                if let Some(value) = map.get(field) {
                    if !value.as_str().is_some_and(|text| !text.trim().is_empty()) {
                        issues.push(format!("{}.{} must be a non-empty string", path, field));
                    }
                }
            }
        }
        Value::Array(items) => {
            for (index, item) in items.iter().enumerate() {
                validate_save_metadata(item, &format!("{}[{}]", path, index), issues);
            }
        }
        _ => issues.push(format!("{} must be an object or array when present", path)),
    }
}

fn validate_cgs_component_schemas(
    schemas: &[CgsComponentSchema],
    raw_schemas: Option<&Vec<Value>>,
    declared_components: &mut BTreeMap<u32, String>,
    issues: &mut Vec<String>,
) {
    let mut schema_type_ids = BTreeSet::new();
    for (schema_index, schema) in schemas.iter().enumerate() {
        let schema_path = format!("component_schemas[{}]", schema_index);
        if schema.type_id == 0 {
            issues.push(format!(
                "{}.type_id must be a positive component type ID",
                schema_path
            ));
            continue;
        }
        if !schema_type_ids.insert(schema.type_id) {
            issues.push(format!(
                "component_schemas declares duplicate component type_id {}",
                schema.type_id
            ));
        }
        if schema.name.trim().is_empty() {
            issues.push(format!("{}.name must be a non-empty string", schema_path));
        } else if let Some(previous_name) = declared_components.get(&schema.type_id) {
            if previous_name != schema.name.trim() {
                issues.push(format!(
                    "{} component type_id {} name '{}' conflicts with '{}'",
                    schema_path,
                    schema.type_id,
                    schema.name.trim(),
                    previous_name
                ));
            }
        } else {
            declared_components.insert(schema.type_id, schema.name.trim().to_string());
        }
        if !schema.defaults.is_object() {
            issues.push(format!("{}.defaults must be an object", schema_path));
        }

        let raw_schema = raw_schemas
            .and_then(|schemas| schemas.get(schema_index))
            .and_then(Value::as_object);
        for field in ["type_id", "name", "defaults"] {
            if raw_schema.and_then(|schema| schema.get(field)).is_none() {
                issues.push(format!("{}.{} is required", schema_path, field));
            }
        }
        if let Some(source) = raw_schema.and_then(|schema| schema.get("source")) {
            if !source.as_str().is_some_and(|text| !text.trim().is_empty()) {
                issues.push(format!(
                    "{}.source must be a non-empty string when present",
                    schema_path
                ));
            }
        }
    }
}

fn validate_cgs_modes(
    cgs: &CgsRoot,
    raw_cgs: &Value,
    metadata_schema_version: &str,
    declared_components: &mut BTreeMap<u32, String>,
    issues: &mut Vec<String>,
) {
    if cgs.modes.is_empty() {
        issues.push("modes must contain at least one mode".to_string());
    }

    let default_count = cgs.modes.iter().filter(|mode| mode.is_default).count();
    if default_count != 1 {
        issues.push(format!(
            "exactly one mode must have is_default=true; found {}",
            default_count
        ));
    }

    let raw_modes = raw_cgs.get("modes").and_then(Value::as_array);
    let mut mode_ids = BTreeSet::new();
    let mut actor_ids = BTreeMap::new();

    for (mode_index, mode) in cgs.modes.iter().enumerate() {
        let mode_path = format!("modes[{}]", mode_index);
        let mode_id = mode.id.trim();
        if mode_id.is_empty() {
            issues.push(format!("{}.id must be a non-empty string", mode_path));
        } else if !mode_ids.insert(mode_id.to_string()) {
            issues.push(format!("duplicate mode id '{}'", mode_id));
        }

        if mode.schema_version.trim().is_empty() {
            issues.push(format!("{}.schema_version is required", mode_path));
        } else if !is_semver(mode.schema_version.trim()) {
            issues.push(format!(
                "{}.schema_version must be a MAJOR.MINOR.PATCH string",
                mode_path
            ));
        } else if !metadata_schema_version.is_empty()
            && mode.schema_version.trim() != metadata_schema_version
        {
            issues.push(format!(
                "{}.schema_version '{}' does not match metadata.schema_version '{}'",
                mode_path,
                mode.schema_version.trim(),
                metadata_schema_version
            ));
        }

        let raw_mode = raw_modes
            .and_then(|modes| modes.get(mode_index))
            .and_then(Value::as_object);
        validate_required_bool(raw_mode, "is_default", &mode_path, issues);
        let raw_actors = raw_array_field(raw_mode, "actors", &mode_path, issues);
        raw_array_field(raw_mode, "systems", &mode_path, issues);
        let raw_rules = raw_array_field(raw_mode, "rules", &mode_path, issues);
        validate_cgs_rules(raw_rules, &mode_path, issues);

        validate_cgs_actors(
            &mode.actors,
            raw_actors,
            &mode_path,
            &mut actor_ids,
            declared_components,
            issues,
        );
    }
}

fn validate_cgs_actors(
    actors: &[CgsActor],
    raw_actors: Option<&Vec<Value>>,
    mode_path: &str,
    actor_ids: &mut BTreeMap<String, String>,
    declared_components: &mut BTreeMap<u32, String>,
    issues: &mut Vec<String>,
) {
    let mut mode_actor_ids = BTreeSet::new();
    for (actor_index, actor) in actors.iter().enumerate() {
        let actor_path = format!("{}.actors[{}]", mode_path, actor_index);
        let actor_id = actor.id.trim();
        if actor_id.is_empty() {
            issues.push(format!("{}.id must be a non-empty string", actor_path));
        } else {
            if !mode_actor_ids.insert(actor_id.to_string()) {
                issues.push(format!(
                    "duplicate actor id '{}' in {}",
                    actor_id, mode_path
                ));
            }
            if let Some(previous_path) = actor_ids.insert(actor_id.to_string(), actor_path.clone())
            {
                issues.push(format!(
                    "duplicate actor id '{}' at {} and {}",
                    actor_id, previous_path, actor_path
                ));
            }
        }

        if actor.spawn_count == 0 {
            issues.push(format!(
                "{}.spawn_count must be an integer >= 1",
                actor_path
            ));
        }

        let raw_actor = raw_actors
            .and_then(|actors| actors.get(actor_index))
            .and_then(Value::as_object);
        let raw_components = raw_array_field(raw_actor, "components", &actor_path, issues);
        validate_cgs_components(
            &actor.components,
            raw_components,
            &actor_path,
            declared_components,
            issues,
        );
    }
}

fn validate_cgs_components(
    components: &[CgsComponent],
    raw_components: Option<&Vec<Value>>,
    actor_path: &str,
    declared_components: &mut BTreeMap<u32, String>,
    issues: &mut Vec<String>,
) {
    let mut component_ids = BTreeSet::new();
    for (component_index, component) in components.iter().enumerate() {
        let component_path = format!("{}.components[{}]", actor_path, component_index);
        if component.type_id == 0 {
            issues.push(format!(
                "{}.type_id must be a positive component type ID",
                component_path
            ));
            continue;
        }
        if !component_ids.insert(component.type_id) {
            issues.push(format!(
                "{} declares duplicate component type_id {}",
                actor_path, component.type_id
            ));
        }
        if component.name.trim().is_empty() {
            issues.push(format!(
                "{}.name must be a non-empty string",
                component_path
            ));
        } else if let Some(previous_name) = declared_components.get(&component.type_id) {
            if previous_name != component.name.trim() {
                issues.push(format!(
                    "{} component type_id {} name '{}' conflicts with '{}'",
                    component_path,
                    component.type_id,
                    component.name.trim(),
                    previous_name
                ));
            }
        } else {
            declared_components.insert(component.type_id, component.name.trim().to_string());
        }
        if !component.defaults.is_object() {
            issues.push(format!("{}.defaults must be an object", component_path));
        }

        let raw_component = raw_components
            .and_then(|components| components.get(component_index))
            .and_then(Value::as_object);
        for field in ["type_id", "name", "defaults"] {
            if raw_component
                .and_then(|component| component.get(field))
                .is_none()
            {
                issues.push(format!("{}.{} is required", component_path, field));
            }
        }
    }
}

fn validate_cgs_rules(raw_rules: Option<&Vec<Value>>, mode_path: &str, issues: &mut Vec<String>) {
    let Some(raw_rules) = raw_rules else {
        return;
    };
    let mut rule_ids = BTreeSet::new();
    for (rule_index, rule) in raw_rules.iter().enumerate() {
        let rule_path = format!("{}.rules[{}]", mode_path, rule_index);
        let Some(rule) = rule.as_object() else {
            issues.push(format!("{} must be an object", rule_path));
            continue;
        };
        let rule_id =
            required_nonempty_string(rule.get("id"), &format!("{}.id", rule_path), issues)
                .unwrap_or_default();
        if !rule_id.is_empty() && !rule_ids.insert(rule_id.clone()) {
            issues.push(format!("duplicate rule id '{}' in {}", rule_id, mode_path));
        }
        for field in ["condition", "effect"] {
            if !rule
                .get(field)
                .and_then(Value::as_str)
                .is_some_and(|text| !text.trim().is_empty())
            {
                issues.push(format!(
                    "{}.{} must be a non-empty string",
                    rule_path, field
                ));
            }
        }
        if !rule
            .get("priority")
            .is_some_and(|value| value.as_i64().is_some())
        {
            issues.push(format!("{}.priority must be an integer", rule_path));
        }
        if !rule.get("is_active").is_some_and(Value::is_boolean) {
            issues.push(format!("{}.is_active must be boolean", rule_path));
        }
    }
}

struct CgsSystemValidationRef<'a> {
    system: &'a CgsSystem,
    path: String,
    raw: Option<&'a serde_json::Map<String, Value>>,
}

fn validate_cgs_systems(
    cgs: &CgsRoot,
    raw_cgs: &Value,
    declared_components: &BTreeMap<u32, String>,
    issues: &mut Vec<String>,
) {
    let system_refs = cgs_system_refs(cgs, raw_cgs);
    let mut system_ids = BTreeMap::new();
    let mut all_system_ids = BTreeSet::new();
    let mut system_phases = BTreeMap::new();
    let mut dependencies = BTreeMap::new();

    for system_ref in &system_refs {
        let system_id = system_ref.system.id.trim();
        if system_id.is_empty() {
            issues.push(format!("{}.id must be a non-empty string", system_ref.path));
            continue;
        }
        if let Some(previous_path) =
            system_ids.insert(system_id.to_string(), system_ref.path.clone())
        {
            issues.push(format!(
                "system id '{}' is declared more than once at {} and {}",
                system_id, previous_path, system_ref.path
            ));
        }
        all_system_ids.insert(system_id.to_string());
        if let Ok(phase) = canonical_phase(system_ref.system.phase.trim()) {
            if let Some(order) = cgs_runtime_phase_index(phase) {
                system_phases.insert(system_id.to_string(), order);
            }
        }
        dependencies.insert(system_id.to_string(), system_ref.system.depends_on.clone());
    }

    for system_ref in &system_refs {
        validate_cgs_system(
            system_ref,
            declared_components,
            &all_system_ids,
            &system_phases,
            issues,
        );
    }
    validate_cgs_dependency_cycles(&dependencies, issues);
}

fn cgs_system_refs<'a>(cgs: &'a CgsRoot, raw_cgs: &'a Value) -> Vec<CgsSystemValidationRef<'a>> {
    let raw_global_systems = raw_cgs.get("global_systems").and_then(Value::as_array);
    let mut refs = Vec::new();
    for (system_index, system) in cgs.global_systems.iter().enumerate() {
        refs.push(CgsSystemValidationRef {
            system,
            path: format!("global_systems[{}]", system_index),
            raw: raw_global_systems
                .and_then(|systems| systems.get(system_index))
                .and_then(Value::as_object),
        });
    }

    let raw_modes = raw_cgs.get("modes").and_then(Value::as_array);
    for (mode_index, mode) in cgs.modes.iter().enumerate() {
        let raw_mode_systems = raw_modes
            .and_then(|modes| modes.get(mode_index))
            .and_then(Value::as_object)
            .and_then(|mode| mode.get("systems"))
            .and_then(Value::as_array);
        for (system_index, system) in mode.systems.iter().enumerate() {
            refs.push(CgsSystemValidationRef {
                system,
                path: format!("modes[{}].systems[{}]", mode_index, system_index),
                raw: raw_mode_systems
                    .and_then(|systems| systems.get(system_index))
                    .and_then(Value::as_object),
            });
        }
    }
    refs
}

fn validate_cgs_system(
    system_ref: &CgsSystemValidationRef<'_>,
    declared_components: &BTreeMap<u32, String>,
    all_system_ids: &BTreeSet<String>,
    system_phases: &BTreeMap<String, u8>,
    issues: &mut Vec<String>,
) {
    let system = system_ref.system;
    let system_id = system.id.trim();
    let display_system_id = if system_id.is_empty() {
        "<empty>"
    } else {
        system_id
    };

    if system.phase.trim().is_empty() {
        issues.push(format!("{}.phase is required", system_ref.path));
    } else if let Err(err) = canonical_phase(system.phase.trim()) {
        issues.push(format!("{}.{}", system_ref.path, err));
    }

    for field in ["reads", "writes", "depends_on"] {
        raw_array_field(system_ref.raw, field, &system_ref.path, issues);
    }
    validate_required_bool(system_ref.raw, "deterministic", &system_ref.path, issues);
    if let Some(value) = system_ref.raw.and_then(|system| system.get("parallel")) {
        if !value.is_boolean() {
            issues.push(format!(
                "{}.parallel must be boolean when present",
                system_ref.path
            ));
        }
    }
    if let Some(value) = system_ref
        .raw
        .and_then(|system| system.get("runtime_executor"))
    {
        if !value.is_object() {
            issues.push(format!(
                "{}.runtime_executor must be an object when present",
                system_ref.path
            ));
        }
    }

    validate_cgs_component_access(
        display_system_id,
        &system_ref.path,
        "reads",
        &system.reads,
        declared_components,
        issues,
    );
    validate_cgs_component_access(
        display_system_id,
        &system_ref.path,
        "writes",
        &system.writes,
        declared_components,
        issues,
    );
    validate_cgs_dependencies(
        display_system_id,
        &system_ref.path,
        &system.depends_on,
        all_system_ids,
        system_phases,
        issues,
    );
}

fn validate_cgs_component_access(
    system_id: &str,
    system_path: &str,
    field: &str,
    values: &[u32],
    declared_components: &BTreeMap<u32, String>,
    issues: &mut Vec<String>,
) {
    let mut seen = BTreeSet::new();
    for value in values {
        if *value == 0 {
            issues.push(format!(
                "{}.{} for system '{}' contains invalid component type_id 0",
                system_path, field, system_id
            ));
            continue;
        }
        if !seen.insert(*value) {
            issues.push(format!(
                "{}.{} for system '{}' contains duplicate component type_id {}",
                system_path, field, system_id, value
            ));
        }
        if !declared_components.contains_key(value) {
            issues.push(format!(
                "{}.{} for system '{}' references undeclared component type_id {}",
                system_path, field, system_id, value
            ));
        }
    }
}

fn validate_cgs_dependencies(
    system_id: &str,
    system_path: &str,
    depends_on: &[String],
    all_system_ids: &BTreeSet<String>,
    system_phases: &BTreeMap<String, u8>,
    issues: &mut Vec<String>,
) {
    let mut seen = BTreeSet::new();
    for dependency in depends_on {
        let dependency_id = dependency.trim();
        if dependency_id.is_empty() {
            issues.push(format!(
                "{}.depends_on contains an empty system id",
                system_path
            ));
            continue;
        }
        if !seen.insert(dependency_id.to_string()) {
            issues.push(format!(
                "{}.depends_on for system '{}' contains duplicate dependency '{}'",
                system_path, system_id, dependency_id
            ));
        }
        if dependency_id == system_id {
            issues.push(format!(
                "{}.depends_on for system '{}' references itself",
                system_path, system_id
            ));
            continue;
        }
        if !all_system_ids.contains(dependency_id) {
            issues.push(format!(
                "{}.depends_on for system '{}' references unknown system '{}'",
                system_path, system_id, dependency_id
            ));
            continue;
        }
        if let (Some(system_phase), Some(dependency_phase)) = (
            system_phases.get(system_id),
            system_phases.get(dependency_id),
        ) {
            if dependency_phase > system_phase {
                issues.push(format!(
                    "{}.depends_on for system '{}' points to later-phase system '{}'",
                    system_path, system_id, dependency_id
                ));
            }
        }
    }
}

fn validate_cgs_dependency_cycles(
    dependencies: &BTreeMap<String, Vec<String>>,
    issues: &mut Vec<String>,
) {
    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    let mut stack = Vec::new();
    let mut reported = BTreeSet::new();
    for system_id in dependencies.keys() {
        visit_cgs_dependency(
            system_id,
            dependencies,
            &mut visiting,
            &mut visited,
            &mut stack,
            &mut reported,
            issues,
        );
    }
}

fn visit_cgs_dependency(
    system_id: &str,
    dependencies: &BTreeMap<String, Vec<String>>,
    visiting: &mut BTreeSet<String>,
    visited: &mut BTreeSet<String>,
    stack: &mut Vec<String>,
    reported: &mut BTreeSet<String>,
    issues: &mut Vec<String>,
) {
    if visited.contains(system_id) {
        return;
    }
    if visiting.contains(system_id) {
        if let Some(start) = stack.iter().position(|id| id == system_id) {
            let mut cycle = stack[start..].to_vec();
            cycle.push(system_id.to_string());
            let display = cycle.join(" -> ");
            if reported.insert(display.clone()) {
                issues.push(format!("system dependency cycle detected: {}", display));
            }
        }
        return;
    }

    visiting.insert(system_id.to_string());
    stack.push(system_id.to_string());
    if let Some(deps) = dependencies.get(system_id) {
        for dependency in deps {
            let dependency_id = dependency.trim();
            if dependencies.contains_key(dependency_id) {
                visit_cgs_dependency(
                    dependency_id,
                    dependencies,
                    visiting,
                    visited,
                    stack,
                    reported,
                    issues,
                );
            }
        }
    }
    stack.pop();
    visiting.remove(system_id);
    visited.insert(system_id.to_string());
}

fn require_raw_array<'a>(
    object: &'a serde_json::Map<String, Value>,
    field: &str,
    path: &str,
    issues: &mut Vec<String>,
) -> Option<&'a Vec<Value>> {
    match object.get(field) {
        Some(Value::Array(items)) => Some(items),
        Some(_) => {
            issues.push(format!("{} must be an array", path));
            None
        }
        None => {
            issues.push(format!("{} is required", path));
            None
        }
    }
}

fn raw_array_field<'a>(
    object: Option<&'a serde_json::Map<String, Value>>,
    field: &str,
    parent_path: &str,
    issues: &mut Vec<String>,
) -> Option<&'a Vec<Value>> {
    let Some(object) = object else {
        return None;
    };
    match object.get(field) {
        Some(Value::Array(items)) => Some(items),
        Some(_) => {
            issues.push(format!("{}.{} must be an array", parent_path, field));
            None
        }
        None => {
            issues.push(format!("{}.{} is required", parent_path, field));
            None
        }
    }
}

fn validate_required_bool(
    object: Option<&serde_json::Map<String, Value>>,
    field: &str,
    parent_path: &str,
    issues: &mut Vec<String>,
) {
    let Some(object) = object else {
        return;
    };
    match object.get(field) {
        Some(Value::Bool(_)) => {}
        Some(_) => issues.push(format!("{}.{} must be boolean", parent_path, field)),
        None => issues.push(format!("{}.{} is required", parent_path, field)),
    }
}

fn required_nonempty_string(
    value: Option<&Value>,
    path: &str,
    issues: &mut Vec<String>,
) -> Option<String> {
    match value.and_then(Value::as_str) {
        Some(text) if !text.trim().is_empty() => Some(text.trim().to_string()),
        Some(_) => {
            issues.push(format!("{} must be a non-empty string", path));
            None
        }
        None => {
            issues.push(format!("{} is required", path));
            None
        }
    }
}

fn required_semver_string(
    value: Option<&Value>,
    path: &str,
    issues: &mut Vec<String>,
) -> Option<String> {
    let value = required_nonempty_string(value, path, issues)?;
    if !is_semver(&value) {
        issues.push(format!("{} must be a MAJOR.MINOR.PATCH string", path));
        None
    } else {
        Some(value)
    }
}

fn validate_positive_u32(value: &Value, path: &str, issues: &mut Vec<String>) {
    match value.as_u64() {
        Some(value) if (1..=u32::MAX as u64).contains(&value) => {}
        _ => issues.push(format!("{} must be an integer >= 1", path)),
    }
}

fn is_semver(value: &str) -> bool {
    let parts = value.split('.').collect::<Vec<_>>();
    parts.len() == 3
        && parts
            .iter()
            .all(|part| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit()))
}

fn cgs_runtime_phase_index(phase: &str) -> Option<u8> {
    match phase {
        "Initialization" => Some(0),
        "Input" => Some(1),
        "Simulation" => Some(2),
        "PostSimulation" => Some(3),
        "Cleanup" => Some(4),
        _ => None,
    }
}

fn validate_mode(mode: &CgsMode) -> Result<()> {
    if mode.id.trim().is_empty() {
        return Err(anyhow::anyhow!("default CGS mode id cannot be empty"));
    }
    let mut actor_ids = BTreeSet::new();
    for actor in &mode.actors {
        if actor.id.trim().is_empty() {
            return Err(anyhow::anyhow!("actor id cannot be empty"));
        }
        if !actor_ids.insert(actor.id.clone()) {
            return Err(anyhow::anyhow!("duplicate actor id '{}'", actor.id));
        }
        let mut component_ids = BTreeSet::new();
        for component in &actor.components {
            if component.type_id == 0 {
                return Err(anyhow::anyhow!("actor '{}' has type_id 0", actor.id));
            }
            if !component_ids.insert(component.type_id) {
                return Err(anyhow::anyhow!(
                    "actor '{}' declares duplicate component type_id {}",
                    actor.id,
                    component.type_id
                ));
            }
        }
    }
    Ok(())
}

fn collect_component_registrations(cgs: &CgsRoot) -> Result<Vec<ComponentRegistration>> {
    let mut registrations = BTreeMap::new();
    for (type_id, name) in builtin_component_names() {
        insert_component_registration(
            &mut registrations,
            type_id,
            name.to_string(),
            ComponentRegistrationSource::Builtin,
        )?;
    }

    for schema in &cgs.component_schemas {
        insert_component_registration(
            &mut registrations,
            schema.type_id,
            component_schema_name(schema),
            schema_component_registration_source(schema.source.trim()),
        )?;
    }

    for mode in &cgs.modes {
        for actor in &mode.actors {
            for component in &actor.components {
                insert_component_registration(
                    &mut registrations,
                    component.type_id,
                    component_name(component),
                    ComponentRegistrationSource::ActorComponent,
                )?;
            }
        }
    }

    for system in cgs
        .global_systems
        .iter()
        .chain(cgs.modes.iter().flat_map(|mode| mode.systems.iter()))
    {
        for type_id in &system.reads {
            insert_component_registration(
                &mut registrations,
                *type_id,
                default_component_name(*type_id),
                ComponentRegistrationSource::SystemRead,
            )?;
        }
        for type_id in &system.writes {
            insert_component_registration(
                &mut registrations,
                *type_id,
                default_component_name(*type_id),
                ComponentRegistrationSource::SystemWrite,
            )?;
        }
    }

    Ok(registrations.into_values().collect())
}

fn register_component_tables(
    table_store: &mut ComponentTableStore,
    registrations: &[ComponentRegistration],
) -> Result<()> {
    for registration in registrations {
        if table_store.has_table(registration.type_id) {
            anyhow::bail!(
                "component table type_id {} was registered before authoritative CGS registration",
                registration.type_id
            );
        }
        table_store
            .register_table(registration.type_id, registration.name.as_str())
            .map_err(|err| {
                anyhow::anyhow!(
                    "register_table {} '{}': {}",
                    registration.type_id,
                    registration.name,
                    err
                )
            })?;
    }
    Ok(())
}

fn insert_component_registration(
    registrations: &mut BTreeMap<u32, ComponentRegistration>,
    type_id: u32,
    name: String,
    source: ComponentRegistrationSource,
) -> Result<()> {
    if type_id == 0 {
        anyhow::bail!("component registration type_id 0 is invalid");
    }
    let name = if name.trim().is_empty() {
        default_component_name(type_id)
    } else {
        name.trim().to_string()
    };
    let is_system_access = matches!(
        source,
        ComponentRegistrationSource::SystemRead | ComponentRegistrationSource::SystemWrite
    );
    if let Some(registration) = registrations.get_mut(&type_id) {
        if !is_system_access && registration.name != name {
            anyhow::bail!(
                "component registration type_id {} name '{}' conflicts with '{}'",
                type_id,
                name,
                registration.name
            );
        }
        if component_registration_source_rank(source)
            > component_registration_source_rank(registration.source)
        {
            registration.source = source;
        }
        return Ok(());
    }
    registrations.insert(
        type_id,
        ComponentRegistration {
            type_id,
            name,
            source,
        },
    );
    Ok(())
}

fn component_registration_source_rank(source: ComponentRegistrationSource) -> u8 {
    match source {
        ComponentRegistrationSource::SystemRead | ComponentRegistrationSource::SystemWrite => 0,
        ComponentRegistrationSource::ActorComponent => 1,
        ComponentRegistrationSource::CgsSchema => 2,
        ComponentRegistrationSource::GeneratedSchema
        | ComponentRegistrationSource::PluginSchema => 3,
        ComponentRegistrationSource::Builtin => 4,
    }
}

#[cfg(test)]
fn build_phase_plan(mode: &CgsMode, global_systems: &[CgsSystem]) -> Result<RuntimePhasePlan> {
    let compatibility = evaluate_cgs_derived_compatibility(mode, global_systems);
    if !compatibility.unsupported_systems.is_empty() {
        anyhow::bail!(
            "{}",
            format_runtime_compatibility_error(&compatibility, None)
        );
    }
    Ok(compatibility.phase_plan)
}

#[derive(Debug, Clone)]
struct DerivedRuntimeCompatibility {
    phase_plan: RuntimePhasePlan,
    declared_system_ids: Vec<String>,
    scheduled_system_ids: Vec<String>,
    unsupported_systems: Vec<RuntimeCompatibilityIssue>,
}

#[derive(Debug, Clone)]
struct RuntimeCompatibilityIssue {
    system_id: String,
    reason: String,
}

fn evaluate_cgs_derived_compatibility(
    mode: &CgsMode,
    global_systems: &[CgsSystem],
) -> DerivedRuntimeCompatibility {
    let systems = global_systems
        .iter()
        .chain(mode.systems.iter())
        .collect::<Vec<_>>();
    let mut declared_system_ids = Vec::new();
    let mut scheduled_system_ids = Vec::new();
    let mut unsupported_systems = Vec::new();
    let mut known_ids = BTreeSet::new();
    let mut duplicate_ids = BTreeSet::new();

    for system in &systems {
        let system_id = system.id.trim();
        if system_id.is_empty() {
            unsupported_systems.push(RuntimeCompatibilityIssue {
                system_id: "<empty>".to_string(),
                reason: "CGS system id is empty".to_string(),
            });
            continue;
        }
        declared_system_ids.push(system_id.to_string());
        if !known_ids.insert(system_id.to_string()) {
            duplicate_ids.insert(system_id.to_string());
        }
    }

    let mut phase_map: BTreeMap<String, Vec<&CgsSystem>> = BTreeMap::new();
    for system in systems {
        let system_id = system.id.trim();
        if system_id.is_empty() {
            continue;
        }
        let mut reasons = Vec::new();
        if duplicate_ids.contains(system_id) {
            reasons.push("CGS system id is declared more than once".to_string());
        }
        if !system.deterministic {
            reasons.push("CGS system is marked deterministic=false".to_string());
        }
        if let Some(issue) = runtime_system_support_issue(system) {
            reasons.push(issue);
        }
        let phase = match canonical_phase(&system.phase) {
            Ok(phase) => phase.to_string(),
            Err(err) => {
                reasons.push(err.to_string());
                "Simulation".to_string()
            }
        };
        for dependency in &system.depends_on {
            let dependency_id = dependency.trim();
            if dependency_id.is_empty() {
                reasons.push("CGS system depends_on contains an empty system id".to_string());
            } else if dependency_id == system_id {
                reasons.push("CGS system depends on itself".to_string());
            } else if !known_ids.contains(dependency_id) {
                reasons.push(format!(
                    "CGS system depends on unknown system '{}'",
                    dependency_id
                ));
            }
        }
        if !reasons.is_empty() {
            unsupported_systems.push(RuntimeCompatibilityIssue {
                system_id: system_id.to_string(),
                reason: reasons.join("; "),
            });
            continue;
        }
        phase_map.entry(phase).or_default().push(system);
    }

    let mut plan = Vec::new();
    for phase in [
        "Initialization",
        "Input",
        "Simulation",
        "PostSimulation",
        "Cleanup",
    ] {
        let Some(mut systems) = phase_map.remove(phase) else {
            continue;
        };
        systems.sort_by(|left, right| {
            left.depends_on
                .len()
                .cmp(&right.depends_on.len())
                .then_with(|| left.id.cmp(&right.id))
        });
        let system_ids = systems
            .into_iter()
            .map(|system| system.id.trim().to_string())
            .collect::<Vec<_>>();
        if !system_ids.is_empty() {
            scheduled_system_ids.extend(system_ids.iter().cloned());
            plan.push((phase.to_string(), system_ids, false));
        }
    }

    for (phase, systems) in phase_map {
        for system in systems {
            unsupported_systems.push(RuntimeCompatibilityIssue {
                system_id: system.id.trim().to_string(),
                reason: format!(
                    "phase '{}' is not supported by the runtime phase order",
                    phase
                ),
            });
        }
    }

    DerivedRuntimeCompatibility {
        phase_plan: plan,
        declared_system_ids,
        scheduled_system_ids,
        unsupported_systems,
    }
}

fn format_runtime_compatibility_error(
    compatibility: &DerivedRuntimeCompatibility,
    proof_path: Option<&Path>,
) -> String {
    let unsupported = compatibility
        .unsupported_systems
        .iter()
        .map(|issue| format!("{} ({})", issue.system_id, issue.reason))
        .collect::<Vec<_>>()
        .join(", ");
    match proof_path {
        Some(path) => format!(
            "CGS-derived runtime compatibility failed before tick zero: unsupported system(s): {}; proof artifact: {}",
            unsupported,
            path.display()
        ),
        None => format!(
            "CGS-derived runtime compatibility failed before tick zero: unsupported system(s): {}",
            unsupported
        ),
    }
}

fn write_runtime_compatibility_proof(
    cgs_path: &Path,
    cgs_hash: &str,
    compatibility: &DerivedRuntimeCompatibility,
) -> Result<PathBuf> {
    let proof_path = runtime_compatibility_proof_path(cgs_path, cgs_hash);
    let proof_dir = proof_path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("runtime compatibility proof path has no parent"))?;
    fs::create_dir_all(proof_dir).map_err(|err| {
        anyhow::anyhow!(
            "cannot create runtime compatibility proof directory '{}': {}",
            proof_dir.display(),
            err
        )
    })?;
    let unsupported_systems = compatibility
        .unsupported_systems
        .iter()
        .map(|issue| {
            json!({
                "system_id": issue.system_id,
                "reason": issue.reason,
            })
        })
        .collect::<Vec<_>>();
    let legacy_dropped_system_ids = compatibility
        .unsupported_systems
        .iter()
        .map(|issue| issue.system_id.clone())
        .collect::<Vec<_>>();
    let report = json!({
        "schema": "xace.runtime.plan_compatibility.v1",
        "ok": compatibility.unsupported_systems.is_empty(),
        "source": "cgs-derived",
        "cgs_hash": cgs_hash,
        "declared_system_ids": compatibility.declared_system_ids.clone(),
        "scheduled_system_ids": compatibility.scheduled_system_ids.clone(),
        "unsupported_systems": unsupported_systems,
        "legacy_dropped_system_ids": legacy_dropped_system_ids,
        "default_system_injected": false,
        "runtime_rule": "CGS-derived plans must fail before tick zero when any declared system cannot be executed; no system may be silently filtered or replaced.",
    });
    let bytes = serde_json::to_vec_pretty(&report)?;
    fs::write(&proof_path, bytes).map_err(|err| {
        anyhow::anyhow!(
            "cannot write runtime compatibility proof '{}': {}",
            proof_path.display(),
            err
        )
    })?;
    Ok(proof_path)
}

fn runtime_compatibility_proof_path(cgs_path: &Path, cgs_hash: &str) -> PathBuf {
    cgs_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(".xace")
        .join("proof")
        .join("runtime-compatibility")
        .join(format!("{}.json", cgs_hash))
}

fn write_sgc_plan_migration_proof(
    cgs_path: &Path,
    plan_path: &Path,
    schema_version: &str,
    cgs_hash: &str,
    cgs_metadata: &serde_json::Value,
    plan: &PersistedExecutionPlan,
    error_message: &str,
) -> Result<PathBuf> {
    let proof_path = sgc_plan_migration_proof_path(cgs_path, cgs_hash);
    let proof_dir = proof_path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("SGC migration proof path has no parent"))?;
    fs::create_dir_all(proof_dir).map_err(|err| {
        anyhow::anyhow!(
            "cannot create SGC migration proof directory '{}': {}",
            proof_dir.display(),
            err
        )
    })?;
    let report = json!({
        "schema": "xace.sgc.plan_migration.v1",
        "ok": false,
        "source": "persisted_sgc_plan",
        "decision": "reject_and_regenerate",
        "migration_performed": false,
        "fallback_to_cgs_derived": false,
        "silent_downgrade_performed": false,
        "runtime_tick_started": false,
        "cgs_hash": cgs_hash,
        "plan_path": plan_path.display().to_string(),
        "reason_code": classify_sgc_plan_migration_reason(error_message),
        "reason": error_message,
        "runtime_expectation": {
            "schema_version": schema_version,
            "cgs_hash": cgs_hash,
            "execution_plan_version": metadata_u32_for_proof(cgs_metadata, "execution_plan_version"),
            "adapter_protocol_version": ENGINE_ADAPTER_PROTOCOL_VERSION,
            "migration_status": "current",
        },
        "plan_identity": {
            "schema_version": &plan.schema_version,
            "plan_version": plan.plan_version,
            "adapter_protocol_version": plan.adapter_protocol_version,
            "migration_status": &plan.migration_status,
            "created_tick": plan.created_tick,
            "plan_hash": &plan.plan_hash,
            "compiled_from_cgs_hash": &plan.compiled_from_cgs_hash,
        },
        "action": "Regenerate the persisted SGC plan for the current CGS schema, template/runtime plan version, and adapter protocol. Runtime never mutates, downgrades, or silently falls back from a stale persisted SGC plan.",
    });
    let bytes = serde_json::to_vec_pretty(&report)?;
    fs::write(&proof_path, bytes).map_err(|err| {
        anyhow::anyhow!(
            "cannot write SGC migration proof '{}': {}",
            proof_path.display(),
            err
        )
    })?;
    Ok(proof_path)
}

fn sgc_plan_migration_proof_path(cgs_path: &Path, cgs_hash: &str) -> PathBuf {
    cgs_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(".xace")
        .join("proof")
        .join("sgc-migration")
        .join(format!("{}.json", proof_file_stem(cgs_hash)))
}

fn proof_file_stem(cgs_hash: &str) -> String {
    if is_lower_hex_hash(cgs_hash) {
        cgs_hash.to_string()
    } else {
        "unresolved-cgs-hash".to_string()
    }
}

fn metadata_u32_for_proof(metadata: &serde_json::Value, key: &str) -> Option<u32> {
    metadata.get(key).and_then(|value| {
        value
            .as_u64()
            .and_then(|number| u32::try_from(number).ok())
            .or_else(|| value.as_str().and_then(|text| text.parse::<u32>().ok()))
    })
}

fn classify_sgc_plan_migration_reason(error_message: &str) -> &'static str {
    if error_message.contains("schema_version") {
        "schema_version_mismatch"
    } else if error_message.contains("adapter_protocol_version") {
        "adapter_protocol_version_mismatch"
    } else if error_message.contains("migration_status") {
        "migration_status_not_current"
    } else if error_message.contains("plan_version") {
        "plan_version_mismatch"
    } else if error_message.contains("compiled_from_cgs_hash") {
        "cgs_hash_mismatch"
    } else if error_message.contains("created_tick") {
        "created_tick_not_zero"
    } else {
        "runtime_compatibility_failed"
    }
}

#[derive(Debug, Clone)]
struct LoadedRuntimePhasePlan {
    schedule_plan: RuntimeSchedulePlan,
}

#[derive(Debug, Deserialize)]
struct PersistedExecutionPlan {
    schema_version: String,
    plan_version: u32,
    created_tick: u64,
    plan_hash: String,
    compiled_from_cgs_hash: String,
    all_system_ids: Vec<String>,
    phases: BTreeMap<String, PersistedPhaseSchedule>,
    #[serde(default)]
    adapter_protocol_version: Option<u32>,
    #[serde(default)]
    migration_status: Option<String>,
    #[serde(default)]
    component_access_sets: Option<serde_json::Value>,
    #[serde(default)]
    system_metadata: Option<serde_json::Value>,
    #[serde(default)]
    proof_bundle: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct PersistedPhaseSchedule {
    phase: String,
    groups: Vec<PersistedExecutionGroup>,
    total_system_count: usize,
}

#[derive(Debug, Deserialize)]
struct PersistedExecutionGroup {
    group_id: String,
    phase: String,
    parallel: bool,
    systems: Vec<String>,
    serialization_constraints: Vec<String>,
    execution_index: u32,
}

fn load_runtime_phase_plan(
    cgs_path: &Path,
    mode: &CgsMode,
    global_systems: &[CgsSystem],
    schema_version: &str,
    cgs_hash: &str,
    cgs_metadata: &serde_json::Value,
    policy: SgcPlanPolicy,
    explicit_plan_path: Option<&Path>,
) -> Result<LoadedRuntimePhasePlan> {
    if policy == SgcPlanPolicy::DeriveFromCgs {
        return derived_phase_plan(cgs_path, schema_version, cgs_hash, mode, global_systems);
    }

    let plan_path = explicit_plan_path
        .map(Path::to_path_buf)
        .unwrap_or_else(|| default_execution_plan_path(cgs_path, cgs_hash));

    if !plan_path.exists() {
        if policy == SgcPlanPolicy::RequirePersisted {
            anyhow::bail!(
                "SGC execution plan required but missing: {}",
                plan_path.display()
            );
        }
        anyhow::bail!(
            "SGC execution plan preferred but missing: {}; CGS-derived schedules require explicit SgcPlanPolicy::DeriveFromCgs",
            plan_path.display()
        );
    }

    load_persisted_runtime_phase_plan(
        cgs_path,
        &plan_path,
        schema_version,
        cgs_hash,
        cgs_metadata,
        mode,
        global_systems,
    )
}

fn derived_phase_plan(
    cgs_path: &Path,
    schema_version: &str,
    cgs_hash: &str,
    mode: &CgsMode,
    global_systems: &[CgsSystem],
) -> Result<LoadedRuntimePhasePlan> {
    let compatibility = evaluate_cgs_derived_compatibility(mode, global_systems);
    let proof_path = write_runtime_compatibility_proof(cgs_path, cgs_hash, &compatibility)?;
    if !compatibility.unsupported_systems.is_empty() {
        anyhow::bail!(
            "{}",
            format_runtime_compatibility_error(&compatibility, Some(&proof_path))
        );
    }
    let cgs_systems = collect_cgs_system_definitions(mode, global_systems)?;
    let schedule_plan = derived_runtime_schedule_plan(
        schema_version,
        cgs_hash,
        &compatibility.phase_plan,
        &cgs_systems,
    )?;
    Ok(LoadedRuntimePhasePlan { schedule_plan })
}

fn load_persisted_runtime_phase_plan(
    cgs_path: &Path,
    plan_path: &Path,
    schema_version: &str,
    cgs_hash: &str,
    cgs_metadata: &serde_json::Value,
    mode: &CgsMode,
    global_systems: &[CgsSystem],
) -> Result<LoadedRuntimePhasePlan> {
    let bytes = fs::read(plan_path).map_err(|err| {
        anyhow::anyhow!(
            "cannot read persisted SGC execution plan '{}': {}",
            plan_path.display(),
            err
        )
    })?;
    let plan: PersistedExecutionPlan = serde_json::from_slice(&bytes).map_err(|err| {
        anyhow::anyhow!(
            "cannot parse persisted SGC execution plan '{}': {}",
            plan_path.display(),
            err
        )
    })?;
    let mut schedule_plan = match validate_and_convert_persisted_plan(
        &plan,
        schema_version,
        cgs_hash,
        cgs_metadata,
        mode,
        global_systems,
    ) {
        Ok(schedule_plan) => schedule_plan,
        Err(err) => {
            let error_message = err.to_string();
            match write_sgc_plan_migration_proof(
                cgs_path,
                plan_path,
                schema_version,
                cgs_hash,
                cgs_metadata,
                &plan,
                &error_message,
            ) {
                Ok(proof_path) => anyhow::bail!(
                    "{}; SGC migration proof artifact: {}",
                    error_message,
                    proof_path.display()
                ),
                Err(proof_err) => anyhow::bail!(
                    "{}; additionally failed to write SGC migration proof: {}",
                    error_message,
                    proof_err
                ),
            }
        }
    };
    schedule_plan.plan_path = Some(plan_path.to_path_buf());
    Ok(LoadedRuntimePhasePlan { schedule_plan })
}

fn validate_and_convert_persisted_plan(
    plan: &PersistedExecutionPlan,
    schema_version: &str,
    cgs_hash: &str,
    cgs_metadata: &serde_json::Value,
    mode: &CgsMode,
    global_systems: &[CgsSystem],
) -> Result<RuntimeSchedulePlan> {
    if schema_version.trim().is_empty() {
        anyhow::bail!("SGC runtime compatibility check failed: CGS schema_version is empty");
    }
    if !is_lower_hex_hash(cgs_hash) {
        anyhow::bail!(
            "SGC runtime compatibility check failed: CGS hash '{}' is not a lowercase 64-character SHA-256 digest",
            cgs_hash
        );
    }
    if plan.schema_version != schema_version {
        anyhow::bail!(
            "SGC execution plan schema_version '{}' does not match CGS schema_version '{}'",
            plan.schema_version,
            schema_version
        );
    }
    if plan.plan_version == 0 {
        anyhow::bail!("SGC execution plan plan_version must be >= 1");
    }
    validate_cgs_expected_plan_version(plan, cgs_metadata)?;
    validate_adapter_protocol_version(plan)?;
    validate_migration_status(plan)?;
    if !is_lower_hex_hash(&plan.plan_hash) {
        anyhow::bail!(
            "SGC execution plan plan_hash must be a lowercase 64-character SHA-256 digest"
        );
    }
    validate_created_tick(plan)?;
    if plan.compiled_from_cgs_hash != cgs_hash {
        anyhow::bail!(
            "SGC execution plan compiled_from_cgs_hash '{}' does not match CGS hash '{}'",
            plan.compiled_from_cgs_hash,
            cgs_hash
        );
    }
    validate_sorted_unique_ids("all_system_ids", &plan.all_system_ids)?;
    let cgs_systems = collect_cgs_system_definitions(mode, global_systems)?;
    validate_plan_system_ids_against_cgs(plan, &cgs_systems)?;
    validate_component_access_sets(plan, &cgs_systems)?;
    validate_system_metadata(plan, &cgs_systems)?;
    validate_persistence_metadata(plan, cgs_hash)?;

    let mut groups = Vec::new();
    let mut scheduled_ids = Vec::new();
    let mut seen_group_ids = BTreeSet::new();

    for phase_key in ["0", "1", "2", "3", "4"] {
        let Some(schedule) = plan.phases.get(phase_key) else {
            continue;
        };
        let expected_phase = phase_name_for_key(phase_key).unwrap();
        if schedule.phase != expected_phase {
            anyhow::bail!(
                "SGC execution plan phase key {} declares phase '{}', expected '{}'",
                phase_key,
                schedule.phase,
                expected_phase
            );
        }
        let mut phase_system_count = 0_usize;
        let mut previous_execution_index: Option<u32> = None;
        for group in &schedule.groups {
            if group.group_id.trim().is_empty() {
                anyhow::bail!("SGC execution plan group_id must not be empty");
            }
            if !seen_group_ids.insert(group.group_id.clone()) {
                anyhow::bail!(
                    "SGC execution plan group_id '{}' appears more than once",
                    group.group_id
                );
            }
            if group.phase != schedule.phase {
                anyhow::bail!(
                    "SGC execution plan group '{}' phase '{}' does not match schedule phase '{}'",
                    group.group_id,
                    group.phase,
                    schedule.phase
                );
            }
            if let Some(previous) = previous_execution_index {
                if group.execution_index <= previous {
                    anyhow::bail!(
                        "SGC execution plan groups in phase '{}' must be sorted by strict execution_index",
                        schedule.phase
                    );
                }
            }
            previous_execution_index = Some(group.execution_index);
            validate_group_system_ids(&group.group_id, &group.systems)?;
            validate_group_constraints(group)?;
            validate_group_compatibility(group, &cgs_systems)?;
            validate_parallel_group_hazards(group, &cgs_systems)?;

            phase_system_count += group.systems.len();
            scheduled_ids.extend(group.systems.iter().cloned());
            groups.push(runtime_schedule_group_from_persisted(group, &cgs_systems)?);
        }
        if phase_system_count != schedule.total_system_count {
            anyhow::bail!(
                "SGC execution plan phase '{}' total_system_count {} does not match grouped system count {}",
                schedule.phase,
                schedule.total_system_count,
                phase_system_count
            );
        }
    }

    let unexpected_phase_keys = plan
        .phases
        .keys()
        .filter(|key| phase_name_for_key(key.as_str()).is_none())
        .cloned()
        .collect::<Vec<_>>();
    if !unexpected_phase_keys.is_empty() {
        anyhow::bail!(
            "SGC execution plan contains invalid phase key(s): {:?}",
            unexpected_phase_keys
        );
    }

    let mut scheduled_sorted = scheduled_ids.clone();
    scheduled_sorted.sort();
    if scheduled_sorted.iter().collect::<BTreeSet<_>>().len() != scheduled_sorted.len() {
        anyhow::bail!("SGC execution plan schedules at least one system more than once");
    }
    if scheduled_sorted != plan.all_system_ids {
        anyhow::bail!(
            "SGC execution plan scheduled systems do not match all_system_ids: scheduled={:?} declared={:?}",
            scheduled_sorted,
            plan.all_system_ids
        );
    }
    validate_dependency_order(&groups, &cgs_systems)?;

    Ok(RuntimeSchedulePlan {
        source: RuntimePhasePlanSource::PersistedSgc,
        schema_version: plan.schema_version.clone(),
        plan_version: plan.plan_version,
        plan_hash: plan.plan_hash.clone(),
        compiled_from_cgs_hash: plan.compiled_from_cgs_hash.clone(),
        plan_path: None,
        groups,
        system_access: runtime_component_access_map(&cgs_systems),
        system_dependencies: runtime_dependency_map(&cgs_systems),
    })
}

fn derived_runtime_schedule_plan(
    schema_version: &str,
    cgs_hash: &str,
    phase_plan: &RuntimePhasePlan,
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> Result<RuntimeSchedulePlan> {
    let mut groups = Vec::new();
    let mut phase_group_counts: BTreeMap<String, u32> = BTreeMap::new();
    for (phase, systems, parallel) in phase_plan {
        let execution_index = *phase_group_counts.get(phase).unwrap_or(&0);
        phase_group_counts.insert(phase.clone(), execution_index.saturating_add(1));
        let group = PersistedExecutionGroup {
            group_id: format!("{}_derived_group_{}", phase, execution_index),
            phase: phase.clone(),
            parallel: *parallel,
            systems: systems.clone(),
            serialization_constraints: Vec::new(),
            execution_index,
        };
        validate_parallel_group_hazards(&group, cgs_systems)?;
        groups.push(runtime_schedule_group_from_persisted(&group, cgs_systems)?);
    }
    validate_dependency_order(&groups, cgs_systems)?;
    let system_access = runtime_component_access_map(cgs_systems);
    let system_dependencies = runtime_dependency_map(cgs_systems);
    let plan_hash = derived_schedule_plan_hash(
        schema_version,
        cgs_hash,
        1,
        &groups,
        &system_access,
        &system_dependencies,
    )?;
    Ok(RuntimeSchedulePlan {
        source: RuntimePhasePlanSource::CgsDerived,
        schema_version: schema_version.to_string(),
        plan_version: 1,
        plan_hash,
        compiled_from_cgs_hash: cgs_hash.to_string(),
        plan_path: None,
        groups,
        system_access,
        system_dependencies,
    })
}

fn derived_schedule_plan_hash(
    schema_version: &str,
    cgs_hash: &str,
    plan_version: u32,
    groups: &[RuntimeScheduleGroup],
    system_access: &BTreeMap<String, RuntimeComponentAccess>,
    system_dependencies: &BTreeMap<String, Vec<String>>,
) -> Result<String> {
    let identity = json!({
        "schema": "xace.runtime.derived_schedule_plan_hash.v1",
        "source": RuntimePhasePlanSource::CgsDerived,
        "schema_version": schema_version,
        "plan_version": plan_version,
        "cgs_hash": cgs_hash,
        "compiled_from_cgs_hash": cgs_hash,
        "scheduled_system_ids": scheduled_system_ids_from_groups(groups),
        "groups": groups,
        "system_access": system_access,
        "system_dependencies": system_dependencies,
    });
    let bytes = serde_json::to_vec(&identity)?;
    Ok(canonical_content_hash(&bytes))
}

fn runtime_schedule_group_from_persisted(
    group: &PersistedExecutionGroup,
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> Result<RuntimeScheduleGroup> {
    let mut component_access = BTreeMap::new();
    let mut depends_on = BTreeMap::new();
    for system_id in &group.systems {
        let system = cgs_systems.get(system_id).ok_or_else(|| {
            anyhow::anyhow!(
                "SGC runtime compatibility check failed: group '{}' references unknown system '{}'",
                group.group_id,
                system_id
            )
        })?;
        component_access.insert(system_id.clone(), runtime_component_access(system));
        depends_on.insert(system_id.clone(), sorted_unique_strings(&system.depends_on));
    }
    Ok(RuntimeScheduleGroup {
        group_id: group.group_id.clone(),
        phase: group.phase.clone(),
        parallel: group.parallel,
        systems: group.systems.clone(),
        serialization_constraints: group.serialization_constraints.clone(),
        execution_index: group.execution_index,
        component_access,
        depends_on,
    })
}

fn runtime_component_access_map(
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> BTreeMap<String, RuntimeComponentAccess> {
    cgs_systems
        .iter()
        .map(|(system_id, system)| (system_id.clone(), runtime_component_access(system)))
        .collect()
}

fn runtime_component_access(system: &CgsSystem) -> RuntimeComponentAccess {
    RuntimeComponentAccess {
        reads: sorted_unique_u32(&system.reads),
        writes: sorted_unique_u32(&system.writes),
    }
}

fn runtime_dependency_map(
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> BTreeMap<String, Vec<String>> {
    cgs_systems
        .iter()
        .map(|(system_id, system)| (system_id.clone(), sorted_unique_strings(&system.depends_on)))
        .collect()
}

fn validate_dependency_order(
    groups: &[RuntimeScheduleGroup],
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> Result<()> {
    let mut positions: BTreeMap<String, (usize, u32, usize, bool, String)> = BTreeMap::new();
    for (group_order, group) in groups.iter().enumerate() {
        for (system_order, system_id) in group.systems.iter().enumerate() {
            positions.insert(
                system_id.clone(),
                (
                    group_order,
                    group.execution_index,
                    system_order,
                    group.parallel,
                    group.group_id.clone(),
                ),
            );
        }
    }
    for (system_id, system) in cgs_systems {
        let Some(system_position) = positions.get(system_id) else {
            continue;
        };
        for dependency in &system.depends_on {
            let Some(dependency_position) = positions.get(dependency) else {
                anyhow::bail!(
                    "SGC runtime compatibility check failed: system '{}' depends on unscheduled system '{}'",
                    system_id,
                    dependency
                );
            };
            if dependency_position.0 == system_position.0 && system_position.3 {
                anyhow::bail!(
                    "SGC runtime compatibility check failed: parallel group '{}' schedules dependent systems '{}' and '{}' together",
                    system_position.4,
                    dependency,
                    system_id
                );
            }
            if dependency_position.0 > system_position.0
                || (dependency_position.0 == system_position.0
                    && dependency_position.2 >= system_position.2)
            {
                anyhow::bail!(
                    "SGC runtime compatibility check failed: system '{}' depends on '{}' but the persisted schedule runs the dependency later",
                    system_id,
                    dependency
                );
            }
        }
    }
    Ok(())
}

fn validate_parallel_group_hazards(
    group: &PersistedExecutionGroup,
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> Result<()> {
    if !group.parallel {
        return Ok(());
    }
    for left_index in 0..group.systems.len() {
        let left_id = &group.systems[left_index];
        let left = cgs_systems.get(left_id).ok_or_else(|| {
            anyhow::anyhow!(
                "SGC runtime compatibility check failed: parallel group '{}' references unknown system '{}'",
                group.group_id,
                left_id
            )
        })?;
        let left_reads = sorted_unique_u32(&left.reads);
        let left_writes = sorted_unique_u32(&left.writes);
        for right_id in group.systems.iter().skip(left_index + 1) {
            let right = cgs_systems.get(right_id).ok_or_else(|| {
                anyhow::anyhow!(
                    "SGC runtime compatibility check failed: parallel group '{}' references unknown system '{}'",
                    group.group_id,
                    right_id
                )
            })?;
            let right_reads = sorted_unique_u32(&right.reads);
            let right_writes = sorted_unique_u32(&right.writes);
            let shared_writes = intersection_u32(&left_writes, &right_writes);
            if !shared_writes.is_empty() {
                anyhow::bail!(
                    "SGC runtime compatibility check failed: parallel group '{}' has write/write component hazard between '{}' and '{}': {:?}",
                    group.group_id,
                    left_id,
                    right_id,
                    shared_writes
                );
            }
            let left_writes_right_reads = intersection_u32(&left_writes, &right_reads);
            let right_writes_left_reads = intersection_u32(&right_writes, &left_reads);
            if !left_writes_right_reads.is_empty() || !right_writes_left_reads.is_empty() {
                anyhow::bail!(
                    "SGC runtime compatibility check failed: parallel group '{}' has read/write component hazard between '{}' and '{}': left_writes_right_reads={:?} right_writes_left_reads={:?}",
                    group.group_id,
                    left_id,
                    right_id,
                    left_writes_right_reads,
                    right_writes_left_reads
                );
            }
        }
    }
    Ok(())
}

fn intersection_u32(left: &[u32], right: &[u32]) -> Vec<u32> {
    let right = right.iter().copied().collect::<BTreeSet<_>>();
    left.iter()
        .copied()
        .filter(|value| right.contains(value))
        .collect()
}

fn validate_persistence_metadata(plan: &PersistedExecutionPlan, cgs_hash: &str) -> Result<()> {
    if !plan
        .component_access_sets
        .as_ref()
        .is_some_and(serde_json::Value::is_object)
    {
        anyhow::bail!("SGC execution plan component_access_sets metadata is required");
    }
    if !plan
        .system_metadata
        .as_ref()
        .is_some_and(serde_json::Value::is_object)
    {
        anyhow::bail!("SGC execution plan system_metadata metadata is required");
    }
    let proof = plan
        .proof_bundle
        .as_ref()
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| anyhow::anyhow!("SGC execution plan proof_bundle metadata is required"))?;
    let expected_path = format!(".xace/proof/sgc/{}", cgs_hash);
    if proof.get("path").and_then(serde_json::Value::as_str) != Some(expected_path.as_str()) {
        anyhow::bail!(
            "SGC execution plan proof_bundle.path must be '{}'",
            expected_path
        );
    }
    if proof
        .get("compiled_from_cgs_hash")
        .and_then(serde_json::Value::as_str)
        != Some(cgs_hash)
    {
        anyhow::bail!("SGC execution plan proof_bundle compiled_from_cgs_hash must match CGS hash");
    }
    if proof.get("schema").and_then(serde_json::Value::as_str) != Some("xace.sgc.proof_ref.v1") {
        anyhow::bail!("SGC execution plan proof_bundle schema must be xace.sgc.proof_ref.v1");
    }
    if proof.get("plan_hash").and_then(serde_json::Value::as_str) != Some(plan.plan_hash.as_str()) {
        anyhow::bail!("SGC execution plan proof_bundle.plan_hash must match plan_hash");
    }
    for field in ["input_hash", "validation_hash"] {
        let value = proof
            .get(field)
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default();
        if !is_lower_hex_hash(value) {
            anyhow::bail!(
                "SGC execution plan proof_bundle.{} must be a lowercase 64-character SHA-256 digest",
                field
            );
        }
    }
    Ok(())
}

fn validate_cgs_expected_plan_version(
    plan: &PersistedExecutionPlan,
    cgs_metadata: &serde_json::Value,
) -> Result<()> {
    let Some(expected) = optional_metadata_u32(cgs_metadata, "execution_plan_version")? else {
        return Ok(());
    };
    if expected != plan.plan_version {
        anyhow::bail!(
            "SGC runtime compatibility check failed: ExecutionPlan plan_version {} does not match CGS metadata.execution_plan_version {}",
            plan.plan_version,
            expected
        );
    }
    Ok(())
}

fn validate_adapter_protocol_version(plan: &PersistedExecutionPlan) -> Result<()> {
    let Some(adapter_protocol_version) = plan.adapter_protocol_version else {
        anyhow::bail!(
            "SGC runtime compatibility check failed: ExecutionPlan adapter_protocol_version is required"
        );
    };
    if adapter_protocol_version != ENGINE_ADAPTER_PROTOCOL_VERSION {
        anyhow::bail!(
            "SGC runtime compatibility check failed: ExecutionPlan adapter_protocol_version {} does not match runtime adapter protocol version {}",
            adapter_protocol_version,
            ENGINE_ADAPTER_PROTOCOL_VERSION
        );
    }
    Ok(())
}

fn validate_migration_status(plan: &PersistedExecutionPlan) -> Result<()> {
    match plan.migration_status.as_deref() {
        Some("current") => Ok(()),
        Some(status) => anyhow::bail!(
            "SGC runtime compatibility check failed: ExecutionPlan migration_status '{}' is not loadable; regenerate or migrate the SGC plan so migration_status is 'current'",
            status
        ),
        None => anyhow::bail!(
            "SGC runtime compatibility check failed: ExecutionPlan migration_status is required and must be 'current'"
        ),
    }
}

fn validate_created_tick(plan: &PersistedExecutionPlan) -> Result<()> {
    if plan.created_tick != 0 {
        anyhow::bail!(
            "SGC runtime compatibility check failed: ExecutionPlan created_tick {} is not loadable at runtime startup; regenerate the plan at tick 0 or use runtime reload support",
            plan.created_tick
        );
    }
    Ok(())
}

fn collect_cgs_system_definitions(
    mode: &CgsMode,
    global_systems: &[CgsSystem],
) -> Result<BTreeMap<String, CgsSystem>> {
    let mut systems = BTreeMap::new();
    for system in global_systems.iter().chain(mode.systems.iter()) {
        let system_id = system.id.trim();
        if system_id.is_empty() {
            anyhow::bail!("SGC runtime compatibility check failed: CGS system id cannot be empty");
        }
        if systems
            .insert(system_id.to_string(), system.clone())
            .is_some()
        {
            anyhow::bail!(
                "SGC runtime compatibility check failed: CGS system id '{}' is declared more than once",
                system_id
            );
        }
        validate_sorted_unique_component_ids(
            &format!("CGS system '{}'.reads", system_id),
            sorted_unique_u32(&system.reads).as_slice(),
        )?;
        validate_sorted_unique_component_ids(
            &format!("CGS system '{}'.writes", system_id),
            sorted_unique_u32(&system.writes).as_slice(),
        )?;
    }
    for system in systems.values() {
        for dependency in &system.depends_on {
            if dependency.trim().is_empty() {
                anyhow::bail!(
                    "SGC runtime compatibility check failed: CGS system '{}' has an empty dependency id",
                    system.id
                );
            }
            if dependency == &system.id {
                anyhow::bail!(
                    "SGC runtime compatibility check failed: CGS system '{}' depends on itself",
                    system.id
                );
            }
            if !systems.contains_key(dependency) {
                anyhow::bail!(
                    "SGC runtime compatibility check failed: CGS system '{}' depends on unknown system '{}'",
                    system.id,
                    dependency
                );
            }
        }
    }
    Ok(systems)
}

fn validate_plan_system_ids_against_cgs(
    plan: &PersistedExecutionPlan,
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> Result<()> {
    let cgs_ids = cgs_systems.keys().cloned().collect::<Vec<_>>();
    if plan.all_system_ids != cgs_ids {
        anyhow::bail!(
            "SGC runtime compatibility check failed: ExecutionPlan all_system_ids {:?} do not match CGS system IDs {:?}",
            plan.all_system_ids,
            cgs_ids
        );
    }
    for system in cgs_systems.values() {
        if !system.deterministic {
            anyhow::bail!(
                "SGC runtime compatibility check failed: CGS system '{}' is marked deterministic=false and cannot be scheduled by a strict runtime SGC plan",
                system.id
            );
        }
        canonical_phase(&system.phase).map_err(|err| {
            anyhow::anyhow!(
                "SGC runtime compatibility check failed: CGS system '{}' {}",
                system.id,
                err
            )
        })?;
    }
    Ok(())
}

fn validate_component_access_sets(
    plan: &PersistedExecutionPlan,
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> Result<()> {
    let access = plan
        .component_access_sets
        .as_ref()
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| {
            anyhow::anyhow!("SGC execution plan component_access_sets metadata is required")
        })?;
    if access.get("schema").and_then(serde_json::Value::as_str)
        != Some("xace.sgc.component_access_sets.v1")
    {
        anyhow::bail!(
            "SGC execution plan component_access_sets schema must be xace.sgc.component_access_sets.v1"
        );
    }
    let by_system = access
        .get("by_system")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| {
            anyhow::anyhow!("SGC execution plan component_access_sets.by_system must be an object")
        })?;
    validate_json_object_keys(
        "component_access_sets.by_system",
        by_system.keys().map(String::as_str),
        cgs_systems.keys().map(String::as_str),
    )?;

    let mut all_reads = BTreeSet::new();
    let mut all_writes = BTreeSet::new();
    for (system_id, cgs_system) in cgs_systems {
        let access_entry = by_system
            .get(system_id)
            .and_then(serde_json::Value::as_object)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "SGC execution plan component_access_sets.by_system is missing system '{}'",
                    system_id
                )
            })?;
        let reads = component_id_array(
            access_entry.get("reads"),
            &format!("component_access_sets.by_system.{}.reads", system_id),
        )?;
        let writes = component_id_array(
            access_entry.get("writes"),
            &format!("component_access_sets.by_system.{}.writes", system_id),
        )?;
        let expected_reads = sorted_unique_u32(&cgs_system.reads);
        let expected_writes = sorted_unique_u32(&cgs_system.writes);
        if reads != expected_reads {
            anyhow::bail!(
                "SGC runtime compatibility check failed: component read IDs for system '{}' do not match CGS (plan={:?}, cgs={:?})",
                system_id,
                reads,
                expected_reads
            );
        }
        if writes != expected_writes {
            anyhow::bail!(
                "SGC runtime compatibility check failed: component write IDs for system '{}' do not match CGS (plan={:?}, cgs={:?})",
                system_id,
                writes,
                expected_writes
            );
        }
        all_reads.extend(reads);
        all_writes.extend(writes);
    }

    let expected_all_reads = all_reads.iter().copied().collect::<Vec<_>>();
    let expected_all_writes = all_writes.iter().copied().collect::<Vec<_>>();
    let expected_component_ids = all_reads.union(&all_writes).copied().collect::<Vec<_>>();
    validate_component_summary(access, "all_reads", expected_all_reads.as_slice())?;
    validate_component_summary(access, "all_writes", expected_all_writes.as_slice())?;
    validate_component_summary(access, "component_ids", expected_component_ids.as_slice())?;
    Ok(())
}

fn validate_system_metadata(
    plan: &PersistedExecutionPlan,
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> Result<()> {
    let metadata = plan
        .system_metadata
        .as_ref()
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| {
            anyhow::anyhow!("SGC execution plan system_metadata metadata is required")
        })?;
    if metadata.get("schema").and_then(serde_json::Value::as_str)
        != Some("xace.sgc.system_metadata.v1")
    {
        anyhow::bail!(
            "SGC execution plan system_metadata schema must be xace.sgc.system_metadata.v1"
        );
    }
    let systems = metadata
        .get("systems")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| {
            anyhow::anyhow!("SGC execution plan system_metadata.systems must be an object")
        })?;
    validate_json_object_keys(
        "system_metadata.systems",
        systems.keys().map(String::as_str),
        cgs_systems.keys().map(String::as_str),
    )?;

    for (system_id, cgs_system) in cgs_systems {
        let entry = systems
            .get(system_id)
            .and_then(serde_json::Value::as_object)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "SGC execution plan system_metadata.systems is missing system '{}'",
                    system_id
                )
            })?;
        let display_name = entry
            .get("display_name")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default();
        if display_name.trim().is_empty() {
            anyhow::bail!(
                "SGC execution plan system_metadata for '{}' must include display_name",
                system_id
            );
        }
        let metadata_phase = entry
            .get("phase")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default();
        let cgs_phase = canonical_phase(&cgs_system.phase)?;
        if metadata_phase != cgs_phase {
            anyhow::bail!(
                "SGC runtime compatibility check failed: system_metadata phase for '{}' is '{}', but CGS phase is '{}'",
                system_id,
                metadata_phase,
                cgs_phase
            );
        }
        let deterministic = entry
            .get("deterministic")
            .and_then(serde_json::Value::as_bool)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "SGC execution plan system_metadata for '{}' must include deterministic boolean",
                    system_id
                )
            })?;
        if deterministic != cgs_system.deterministic {
            anyhow::bail!(
                "SGC runtime compatibility check failed: system_metadata deterministic flag for '{}' is {}, but CGS deterministic is {}",
                system_id,
                deterministic,
                cgs_system.deterministic
            );
        }
        if !deterministic {
            anyhow::bail!(
                "SGC runtime compatibility check failed: system '{}' is non-deterministic and cannot run in strict runtime mode",
                system_id
            );
        }
        let depends_on = string_array(
            entry.get("depends_on"),
            &format!("system_metadata.systems.{}.depends_on", system_id),
        )?;
        let expected_depends_on = sorted_unique_strings(&cgs_system.depends_on);
        if depends_on != expected_depends_on {
            anyhow::bail!(
                "SGC runtime compatibility check failed: system_metadata depends_on for '{}' does not match CGS (plan={:?}, cgs={:?})",
                system_id,
                depends_on,
                expected_depends_on
            );
        }
        validate_system_metadata_version(entry, system_id)?;
        if !entry
            .get("description")
            .is_some_and(serde_json::Value::is_string)
        {
            anyhow::bail!(
                "SGC execution plan system_metadata for '{}' must include description string",
                system_id
            );
        }
    }
    Ok(())
}

fn validate_group_compatibility(
    group: &PersistedExecutionGroup,
    cgs_systems: &BTreeMap<String, CgsSystem>,
) -> Result<()> {
    for system_id in &group.systems {
        let Some(system) = cgs_systems.get(system_id) else {
            anyhow::bail!(
                "SGC runtime compatibility check failed: ExecutionPlan group '{}' schedules unknown CGS system '{}'",
                group.group_id,
                system_id
            );
        };
        let cgs_phase = canonical_phase(&system.phase)?;
        if group.phase != cgs_phase {
            anyhow::bail!(
                "SGC runtime compatibility check failed: ExecutionPlan schedules system '{}' in phase '{}', but CGS declares phase '{}'",
                system_id,
                group.phase,
                cgs_phase
            );
        }
        if !system.deterministic {
            anyhow::bail!(
                "SGC runtime compatibility check failed: ExecutionPlan schedules non-deterministic system '{}'",
                system_id
            );
        }
    }
    Ok(())
}

fn validate_system_metadata_version(
    entry: &serde_json::Map<String, serde_json::Value>,
    system_id: &str,
) -> Result<()> {
    let version = entry
        .get("version")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| {
            anyhow::anyhow!(
                "SGC execution plan system_metadata for '{}' must include version object",
                system_id
            )
        })?;
    let major = json_u32(
        version.get("major"),
        &format!("system_metadata.{}.version.major", system_id),
    )?;
    let _minor = json_u32(
        version.get("minor"),
        &format!("system_metadata.{}.version.minor", system_id),
    )?;
    if major == 0 {
        anyhow::bail!(
            "SGC execution plan system_metadata for '{}' version.major must be >= 1",
            system_id
        );
    }
    Ok(())
}

fn validate_component_summary(
    access: &serde_json::Map<String, serde_json::Value>,
    field: &str,
    expected: &[u32],
) -> Result<()> {
    let actual = component_id_array(
        access.get(field),
        &format!("component_access_sets.{}", field),
    )?;
    if actual != expected {
        anyhow::bail!(
            "SGC runtime compatibility check failed: component_access_sets.{} {:?} does not match expected {:?}",
            field,
            actual,
            expected
        );
    }
    Ok(())
}

fn optional_metadata_u32(metadata: &serde_json::Value, key: &str) -> Result<Option<u32>> {
    let Some(value) = metadata.get(key) else {
        return Ok(None);
    };
    if value.is_null() {
        return Ok(None);
    }
    if let Some(parsed) = value.as_u64() {
        if parsed <= u32::MAX as u64 {
            return Ok(Some(parsed as u32));
        }
    }
    if let Some(text) = value.as_str() {
        if text.trim().is_empty() {
            return Ok(None);
        }
        if let Ok(parsed) = text.parse::<u32>() {
            return Ok(Some(parsed));
        }
    }
    anyhow::bail!(
        "SGC runtime compatibility check failed: CGS metadata.{} must be an integer when present",
        key
    );
}

fn json_u32(value: Option<&serde_json::Value>, label: &str) -> Result<u32> {
    let value = value.ok_or_else(|| anyhow::anyhow!("SGC execution plan {} is required", label))?;
    let Some(parsed) = value.as_u64() else {
        anyhow::bail!("SGC execution plan {} must be an integer >= 0", label);
    };
    if parsed > u32::MAX as u64 {
        anyhow::bail!("SGC execution plan {} is too large", label);
    }
    Ok(parsed as u32)
}

fn component_id_array(value: Option<&serde_json::Value>, label: &str) -> Result<Vec<u32>> {
    let value = value.ok_or_else(|| anyhow::anyhow!("SGC execution plan {} is required", label))?;
    let Some(items) = value.as_array() else {
        anyhow::bail!(
            "SGC execution plan {} must be an array of component IDs",
            label
        );
    };
    let mut ids = Vec::with_capacity(items.len());
    for item in items {
        let Some(raw) = item.as_u64() else {
            anyhow::bail!(
                "SGC execution plan {} contains a non-integer component ID",
                label
            );
        };
        if raw > u32::MAX as u64 {
            anyhow::bail!(
                "SGC execution plan {} contains component ID {} outside u32 range",
                label,
                raw
            );
        }
        ids.push(raw as u32);
    }
    validate_sorted_unique_component_ids(label, &ids)?;
    Ok(ids)
}

fn string_array(value: Option<&serde_json::Value>, label: &str) -> Result<Vec<String>> {
    let value = value.ok_or_else(|| anyhow::anyhow!("SGC execution plan {} is required", label))?;
    let Some(items) = value.as_array() else {
        anyhow::bail!("SGC execution plan {} must be an array of strings", label);
    };
    let mut values = Vec::with_capacity(items.len());
    for item in items {
        let Some(text) = item.as_str() else {
            anyhow::bail!("SGC execution plan {} contains a non-string value", label);
        };
        if text.trim().is_empty() {
            anyhow::bail!("SGC execution plan {} contains an empty string", label);
        }
        values.push(text.to_string());
    }
    validate_sorted_unique_ids(label, &values)?;
    Ok(values)
}

fn validate_json_object_keys<'a>(
    label: &str,
    actual: impl Iterator<Item = &'a str>,
    expected: impl Iterator<Item = &'a str>,
) -> Result<()> {
    let actual_keys = actual.map(str::to_string).collect::<Vec<_>>();
    let expected_keys = expected.map(str::to_string).collect::<Vec<_>>();
    if actual_keys != expected_keys {
        anyhow::bail!(
            "SGC runtime compatibility check failed: {} keys {:?} do not match expected system IDs {:?}",
            label,
            actual_keys,
            expected_keys
        );
    }
    Ok(())
}

fn validate_sorted_unique_component_ids(label: &str, values: &[u32]) -> Result<()> {
    let mut seen = BTreeSet::new();
    let mut previous: Option<u32> = None;
    for value in values {
        if !seen.insert(*value) {
            anyhow::bail!(
                "SGC execution plan {} contains duplicate component ID {}",
                label,
                value
            );
        }
        if previous.is_some_and(|prev| prev > *value) {
            anyhow::bail!("SGC execution plan {} must be sorted", label);
        }
        previous = Some(*value);
    }
    Ok(())
}

fn sorted_unique_u32(values: &[u32]) -> Vec<u32> {
    values
        .iter()
        .copied()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn sorted_unique_strings(values: &[String]) -> Vec<String> {
    values
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn canonical_phase(phase: &str) -> Result<&str> {
    if phase.trim().is_empty() {
        return Ok("Simulation");
    }
    match phase {
        "Initialization" | "Input" | "Simulation" | "PostSimulation" | "Cleanup" => Ok(phase),
        other => anyhow::bail!(
            "phase '{}' is not one of Initialization, Input, Simulation, PostSimulation, Cleanup",
            other
        ),
    }
}

fn validate_sorted_unique_ids(label: &str, values: &[String]) -> Result<()> {
    let mut seen = BTreeSet::new();
    let mut previous: Option<&str> = None;
    for value in values {
        if value.trim().is_empty() {
            anyhow::bail!("SGC execution plan {} contains an empty system id", label);
        }
        if !seen.insert(value.as_str()) {
            anyhow::bail!(
                "SGC execution plan {} contains duplicate system id '{}'",
                label,
                value
            );
        }
        if previous.is_some_and(|prev| prev > value.as_str()) {
            anyhow::bail!("SGC execution plan {} must be sorted", label);
        }
        previous = Some(value);
    }
    Ok(())
}

fn validate_group_system_ids(group_id: &str, systems: &[String]) -> Result<()> {
    if systems.is_empty() {
        anyhow::bail!(
            "SGC execution plan group '{}' must contain at least one system",
            group_id
        );
    }
    let mut seen = BTreeSet::new();
    for system_id in systems {
        if system_id.trim().is_empty() {
            anyhow::bail!(
                "SGC execution plan group '{}' contains an empty system id",
                group_id
            );
        }
        if !seen.insert(system_id.as_str()) {
            anyhow::bail!(
                "SGC execution plan group '{}' contains duplicate system id '{}'",
                group_id,
                system_id
            );
        }
    }
    Ok(())
}

fn validate_group_constraints(group: &PersistedExecutionGroup) -> Result<()> {
    validate_sorted_unique_ids(
        &format!("group '{}' serialization_constraints", group.group_id),
        &group.serialization_constraints,
    )?;
    for constraint in &group.serialization_constraints {
        if !group.systems.contains(constraint) {
            anyhow::bail!(
                "SGC execution plan group '{}' serialization constraint '{}' is not in the group systems",
                group.group_id,
                constraint
            );
        }
    }
    Ok(())
}

fn phase_name_for_key(key: &str) -> Option<&'static str> {
    match key {
        "0" => Some("Initialization"),
        "1" => Some("Input"),
        "2" => Some("Simulation"),
        "3" => Some("PostSimulation"),
        "4" => Some("Cleanup"),
        _ => None,
    }
}

fn is_lower_hex_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .as_bytes()
            .iter()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn default_execution_plan_path(cgs_path: &Path, cgs_hash: &str) -> PathBuf {
    cgs_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(".xace")
        .join("execution_plans")
        .join(format!("{}.plan.json", cgs_hash))
}

fn pick_default_mode(modes: &[CgsMode]) -> Option<&CgsMode> {
    modes
        .iter()
        .find(|mode| mode.is_default)
        .or_else(|| modes.first())
}

fn component_name(component: &CgsComponent) -> String {
    if component.name.is_empty() {
        default_component_name(component.type_id)
    } else {
        component.name.clone()
    }
}

fn component_schema_name(schema: &CgsComponentSchema) -> String {
    if schema.name.is_empty() {
        default_component_name(schema.type_id)
    } else {
        schema.name.clone()
    }
}

fn schema_component_registration_source(source: &str) -> ComponentRegistrationSource {
    match source.trim().to_ascii_lowercase().as_str() {
        "generated" | "generator" | "llm_generated" | "llm-generated" => {
            ComponentRegistrationSource::GeneratedSchema
        }
        "plugin" | "extension" => ComponentRegistrationSource::PluginSchema,
        _ => ComponentRegistrationSource::CgsSchema,
    }
}

fn default_component_name(type_id: u32) -> String {
    builtin_component_names()
        .into_iter()
        .find(|(builtin_type_id, _)| *builtin_type_id == type_id)
        .map(|(_, name)| name.to_string())
        .unwrap_or_else(|| format!("COMP_{}", type_id))
}

fn builtin_component_names() -> Vec<(u32, &'static str)> {
    vec![
        (type_ids::TRANSFORM, "COMP_TRANSFORM_V1"),
        (type_ids::IDENTITY, "COMP_IDENTITY_V1"),
        (type_ids::VELOCITY, "COMP_VELOCITY_V1"),
        (type_ids::INPUT, "COMP_INPUT_V1"),
        (type_ids::AUTHORITY, "COMP_AUTHORITY_V1"),
        (type_ids::HEALTH, "COMP_HEALTH_V1"),
        (type_ids::DAMAGE, "COMP_DAMAGE_V1"),
        (type_ids::MOVEMENT_INTENT, "COMP_MOVEMENT_INTENT_V1"),
        (type_ids::KINEMATIC_CHARACTER, "COMP_KINEMATIC_CHARACTER_V1"),
        (type_ids::AI, "COMP_AI_V1"),
        (type_ids::INVENTORY, "COMP_INVENTORY_V1"),
        (type_ids::ITEM, "COMP_ITEM_V1"),
        (type_ids::PERSISTENCE, "COMP_PERSISTENCE_V1"),
        (type_ids::INTERACTION, "COMP_INTERACTION_V1"),
        (type_ids::REPLICATION, "COMP_REPLICATION_V1"),
        (type_ids::CHECKPOINT, "COMP_CHECKPOINT_V1"),
    ]
}

fn is_builtin_runtime_system(system_id: &str) -> bool {
    matches!(
        system_id,
        "InputSystem"
            | "MovementIntentSystem"
            | "PlatformerMotionSystem"
            | "MovementSystem"
            | "InteractionSystem"
            | "InventorySystem"
            | "AISystem"
            | "DamageSystem"
            | "DeathSystem"
    )
}

pub use crate::generated_system_abi::{
    GeneratedSystemAbiSpec as GeneratedRuntimeExecutorSpec,
    GeneratedSystemAbiSpec as RuntimeExecutorSpec, EXTERNAL_COPY_NUMERIC_FIELD_EXECUTOR_KIND,
    EXTERNAL_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND,
    GENERATED_EMIT_RNG_THRESHOLD_EVENT_EXECUTOR_KIND,
    GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND, PLUGIN_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND,
    PLUGIN_SET_JSON_FIELD_EXECUTOR_KIND, RUNTIME_EXECUTOR_ABI_SCHEMA,
};

pub fn runtime_executor_spec(system: &CgsSystem) -> Result<Option<RuntimeExecutorSpec>> {
    crate::generated_system_abi::spec_from_runtime_executor(
        &system.id,
        &system.phase,
        &system.reads,
        &system.writes,
        &system.runtime_executor,
    )
}

pub fn generated_runtime_executor_spec(
    system: &CgsSystem,
) -> Result<Option<GeneratedRuntimeExecutorSpec>> {
    runtime_executor_spec(system)
}

pub fn runtime_system_support_issue(system: &CgsSystem) -> Option<String> {
    if is_builtin_runtime_system(system.id.trim()) {
        return None;
    }
    match runtime_executor_spec(system) {
        Ok(Some(_)) => None,
        Ok(None) => Some(
            "no registered runtime executor exists for this CGS system; add runtime_executor or provide generated/plugin/external registry support"
                .to_string(),
        ),
        Err(err) => Some(err.to_string()),
    }
}

fn extract_metadata_str<'a>(value: &'a serde_json::Value, key: &str) -> Option<&'a str> {
    value.get(key)?.as_str()
}

fn extract_str(value: &str) -> Option<&str> {
    (!value.trim().is_empty()).then_some(value)
}

fn canonical_content_hash(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    format!("{:x}", digest)
}

pub mod type_ids {
    pub const TRANSFORM: u32 = 1;
    pub const IDENTITY: u32 = 2;
    pub const VELOCITY: u32 = 5;
    pub const INPUT: u32 = 6;
    pub const AUTHORITY: u32 = 10;
    pub const HEALTH: u32 = 100;
    pub const DAMAGE: u32 = 101;
    pub const MOVEMENT_INTENT: u32 = 120;
    pub const KINEMATIC_CHARACTER: u32 = 125;
    pub const AI: u32 = 160;
    pub const INVENTORY: u32 = 201;
    pub const ITEM: u32 = 205;
    pub const PERSISTENCE: u32 = 232;
    pub const INTERACTION: u32 = 260;
    pub const REPLICATION: u32 = 320;
    pub const CHECKPOINT: u32 = 361;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::component_tables::component_table_store::ComponentTableStore;
    use crate::entity_store::entity_store::EntityStore;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn phase_plan_keeps_supported_builtin_systems_in_phase_order() {
        let mode = CgsMode {
            id: "mode".to_string(),
            schema_version: "1".to_string(),
            is_default: true,
            actors: Vec::new(),
            systems: vec![CgsSystem {
                id: "MovementSystem".to_string(),
                phase: "Simulation".to_string(),
                reads: vec![1],
                writes: vec![1],
                depends_on: Vec::new(),
                deterministic: true,
                parallel: false,
                runtime_executor: serde_json::Value::Null,
            }],
        };
        let globals = vec![CgsSystem {
            id: "InputSystem".to_string(),
            phase: "Input".to_string(),
            reads: vec![6],
            writes: vec![5],
            depends_on: Vec::new(),
            deterministic: true,
            parallel: false,
            runtime_executor: serde_json::Value::Null,
        }];
        let plan = build_phase_plan(&mode, &globals).unwrap();
        assert_eq!(plan[0].0, "Input");
        assert_eq!(plan[1].0, "Simulation");
    }

    #[test]
    fn cgs_derived_plan_rejects_unknown_system_and_writes_compatibility_proof() {
        let hash = "6".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_single_runtime_system(
            &hash,
            "GeneratedCraftingSystem",
            true,
        ));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::DeriveFromCgs,
            None,
        )
        .expect_err("unknown generated system must not be filtered out");

        assert!(err.to_string().contains("GeneratedCraftingSystem"));
        let proof = read_runtime_compatibility_proof(&root, &hash);
        assert_eq!(proof["ok"], false);
        assert_eq!(
            proof["unsupported_systems"][0]["system_id"],
            "GeneratedCraftingSystem"
        );
        assert_eq!(
            proof["legacy_dropped_system_ids"][0],
            "GeneratedCraftingSystem"
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn cgs_derived_plan_rejects_non_deterministic_system_and_writes_compatibility_proof() {
        let hash = "7".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_single_runtime_system(
            &hash,
            "MovementSystem",
            false,
        ));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::DeriveFromCgs,
            None,
        )
        .expect_err("non-deterministic system must not be filtered out");

        assert!(err.to_string().contains("deterministic=false"));
        let proof = read_runtime_compatibility_proof(&root, &hash);
        assert_eq!(proof["ok"], false);
        assert_eq!(
            proof["unsupported_systems"][0]["system_id"],
            "MovementSystem"
        );
        assert!(proof["unsupported_systems"][0]["reason"]
            .as_str()
            .unwrap()
            .contains("deterministic=false"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn cgs_derived_plan_writes_success_compatibility_proof_without_default_injection() {
        let hash = "8".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_single_runtime_system(
            &hash,
            "MovementSystem",
            true,
        ));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let summary = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::DeriveFromCgs,
            None,
        )
        .unwrap();

        assert_eq!(
            summary.phase_plan,
            vec![(
                "Simulation".to_string(),
                vec!["MovementSystem".to_string()],
                false
            )]
        );
        let proof = read_runtime_compatibility_proof(&root, &hash);
        assert_eq!(proof["ok"], true);
        assert_eq!(proof["default_system_injected"], false);
        assert_eq!(
            proof["legacy_dropped_system_ids"].as_array().unwrap().len(),
            0
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn cgs_derived_plan_accepts_supported_generated_runtime_executor() {
        let hash = "9".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_generated_counter_system(&hash));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let summary = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::DeriveFromCgs,
            None,
        )
        .unwrap();

        assert_eq!(
            summary.phase_plan,
            vec![(
                "Simulation".to_string(),
                vec!["GeneratedCounterSystem".to_string()],
                false
            )]
        );
        let spec = generated_runtime_executor_spec(&summary.runtime_systems[0])
            .unwrap()
            .unwrap();
        assert_eq!(spec.kind, GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND);
        assert_eq!(spec.inputs.query_components, vec![300]);
        assert_eq!(spec.rng.allowed, false);
        let proof = read_runtime_compatibility_proof(&root, &hash);
        assert_eq!(proof["ok"], true);
        assert_eq!(
            proof["scheduled_system_ids"][0].as_str(),
            Some("GeneratedCounterSystem")
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn cgs_derived_plan_accepts_supported_generated_rng_event_abi() {
        let hash = "a".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_generated_rng_event_system(&hash));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let summary = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::DeriveFromCgs,
            None,
        )
        .unwrap();

        assert_eq!(
            summary.phase_plan,
            vec![(
                "Simulation".to_string(),
                vec!["GeneratedLootRollSystem".to_string()],
                false
            )]
        );
        let spec = generated_runtime_executor_spec(&summary.runtime_systems[0])
            .unwrap()
            .unwrap();
        assert_eq!(spec.kind, GENERATED_EMIT_RNG_THRESHOLD_EVENT_EXECUTOR_KIND);
        assert_eq!(spec.inputs.query_components, vec![301]);
        assert_eq!(spec.rng.allowed, true);
        assert_eq!(spec.rng.max_calls_per_entity, 1);
        assert_eq!(spec.events.emits[0].event_type, "generated.loot_roll");
        let proof = read_runtime_compatibility_proof(&root, &hash);
        assert_eq!(proof["ok"], true);
        assert_eq!(
            proof["scheduled_system_ids"][0].as_str(),
            Some("GeneratedLootRollSystem")
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn require_persisted_sgc_plan_fails_when_plan_is_missing() {
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&"a".repeat(64)));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("required SGC plan must fail when missing");

        assert!(err
            .to_string()
            .contains("SGC execution plan required but missing"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn prefer_persisted_sgc_plan_does_not_silently_derive_when_plan_is_missing() {
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&"a".repeat(64)));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::PreferPersisted,
            None,
        )
        .expect_err("preferred SGC plan must not silently derive when missing");

        assert!(err
            .to_string()
            .contains("SGC execution plan preferred but missing"));
        assert!(err.to_string().contains("DeriveFromCgs"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_is_authoritative_and_not_builtin_filtered() {
        let hash = "b".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(&root, &hash, persisted_plan(&hash, true));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let summary = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .unwrap();

        assert_eq!(
            summary.phase_plan_source,
            RuntimePhasePlanSource::PersistedSgc
        );
        assert_eq!(summary.execution_plan_version, 1);
        assert_eq!(summary.execution_plan_hash, "c".repeat(64));
        assert_eq!(
            summary.phase_plan,
            vec![
                ("Input".to_string(), vec!["InputSystem".to_string()], false),
                (
                    "Simulation".to_string(),
                    vec!["CustomGeneratedSystem".to_string()],
                    false
                ),
                (
                    "Simulation".to_string(),
                    vec!["MovementSystem".to_string()],
                    false
                ),
            ]
        );
        assert_eq!(summary.schedule_plan.groups.len(), 3);
        assert_eq!(summary.schedule_plan.groups[0].group_id, "Input_group_0");
        assert_eq!(
            summary.schedule_plan.groups[1].component_access["CustomGeneratedSystem"].writes,
            vec![100]
        );
        assert_eq!(
            summary.schedule_plan.system_dependencies["MovementSystem"],
            vec!["InputSystem".to_string()]
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_parallel_component_hazard() {
        let hash = "9".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(
            &root,
            &hash,
            mutate_persisted_plan(&hash, true, |plan| {
                plan["phases"]["2"]["groups"] = serde_json::json!([
                    {
                        "group_id": "Simulation_group_0",
                        "phase": "Simulation",
                        "parallel": true,
                        "systems": ["CustomGeneratedSystem", "MovementSystem"],
                        "serialization_constraints": [],
                        "execution_index": 0
                    }
                ]);
                plan["phases"]["2"]["total_system_count"] = serde_json::json!(2);
            }),
        );
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("runtime must reject persisted parallel component hazards");

        assert!(err.to_string().contains("component hazard"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_incompatible_cgs_hash() {
        let hash = "d".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(&root, &hash, persisted_plan(&"e".repeat(64), false));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("mismatched plan hash must fail");

        assert!(err.to_string().contains("compiled_from_cgs_hash"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_adapter_protocol_mismatch() {
        let hash = "e".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(
            &root,
            &hash,
            mutate_persisted_plan(&hash, true, |plan| {
                plan["adapter_protocol_version"] = serde_json::json!(99);
            }),
        );
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("adapter protocol mismatch must fail before tick zero");

        assert!(err.to_string().contains("adapter_protocol_version"));
        assert!(err.to_string().contains("SGC migration proof artifact"));
        let proof = assert_sgc_migration_proof(&root, &hash, "adapter_protocol_version_mismatch");
        assert_eq!(proof["plan_identity"]["adapter_protocol_version"], 99);
        assert_eq!(
            proof["runtime_expectation"]["adapter_protocol_version"],
            ENGINE_ADAPTER_PROTOCOL_VERSION
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_non_current_migration_status() {
        let hash = "f".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(
            &root,
            &hash,
            mutate_persisted_plan(&hash, true, |plan| {
                plan["migration_status"] = serde_json::json!("pending");
            }),
        );
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("stale migration status must fail before tick zero");

        assert!(err.to_string().contains("migration_status"));
        assert!(err.to_string().contains("SGC migration proof artifact"));
        let proof = assert_sgc_migration_proof(&root, &hash, "migration_status_not_current");
        assert_eq!(proof["plan_identity"]["migration_status"], "pending");
        assert_eq!(proof["runtime_expectation"]["migration_status"], "current");
        assert!(proof["action"]
            .as_str()
            .unwrap()
            .contains("Regenerate the persisted SGC plan"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_plan_version_mismatch() {
        let hash = "1".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(
            &root,
            &hash,
            mutate_persisted_plan(&hash, true, |plan| {
                plan["plan_version"] = serde_json::json!(2);
            }),
        );
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("CGS execution_plan_version mismatch must fail before tick zero");

        assert!(err.to_string().contains("execution_plan_version"));
        assert!(err.to_string().contains("SGC migration proof artifact"));
        let proof = assert_sgc_migration_proof(&root, &hash, "plan_version_mismatch");
        assert_eq!(proof["plan_identity"]["plan_version"], 2);
        assert_eq!(proof["runtime_expectation"]["execution_plan_version"], 1);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_schema_version_mismatch_with_migration_proof() {
        let hash = "6".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(
            &root,
            &hash,
            mutate_persisted_plan(&hash, true, |plan| {
                plan["schema_version"] = serde_json::json!("0.0.9");
            }),
        );
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("schema-version stale plan must fail before tick zero");

        assert!(err.to_string().contains("schema_version"));
        assert!(err.to_string().contains("SGC migration proof artifact"));
        let proof = assert_sgc_migration_proof(&root, &hash, "schema_version_mismatch");
        assert_eq!(proof["plan_identity"]["schema_version"], "0.0.9");
        assert_eq!(proof["runtime_expectation"]["schema_version"], "0.1.0");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_component_access_mismatch() {
        let hash = "2".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(
            &root,
            &hash,
            mutate_persisted_plan(&hash, true, |plan| {
                plan["component_access_sets"]["by_system"]["MovementSystem"]["reads"] =
                    serde_json::json!([1]);
            }),
        );
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("component access mismatch must fail before tick zero");

        assert!(err.to_string().contains("component read IDs"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_system_metadata_mismatch() {
        let hash = "3".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(
            &root,
            &hash,
            mutate_persisted_plan(&hash, true, |plan| {
                plan["system_metadata"]["systems"]["MovementSystem"]["deterministic"] =
                    serde_json::json!(false);
            }),
        );
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("determinism metadata mismatch must fail before tick zero");

        assert!(err.to_string().contains("deterministic flag"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_nonzero_created_tick() {
        let hash = "4".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(
            &root,
            &hash,
            mutate_persisted_plan(&hash, true, |plan| {
                plan["created_tick"] = serde_json::json!(12);
            }),
        );
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("non-zero plan tick must fail before runtime tick zero");

        assert!(err.to_string().contains("created_tick"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn persisted_sgc_plan_rejects_system_id_mismatch() {
        let hash = "5".repeat(64);
        let (root, cgs_path) = write_temp_project_cgs(cgs_with_systems(&hash));
        write_plan(&root, &hash, persisted_plan(&hash, false));
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &cgs_path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("system ID mismatch must fail before tick zero");

        assert!(err.to_string().contains("all_system_ids"));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn load_and_spawn_accepts_valid_semantic_playback_bindings() {
        let path = write_temp_cgs(valid_cgs_with_bindings());
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let summary = load_and_spawn_with_plan_policy(
            &path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::DeriveFromCgs,
            None,
        )
        .unwrap();

        assert_eq!(summary.semantic_bindings.bindings.len(), 3);
        assert_eq!(
            summary.semantic_bindings.bindings[0].binding_id,
            "bind_anim"
        );
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn load_and_spawn_rejects_invalid_semantic_asset_type() {
        let path = write_temp_cgs(invalid_cgs_with_mesh_audio_binding());
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn(&path, &mut entity_store, &mut table_store)
            .expect_err("wrong playback asset type must fail CGS load");

        assert!(err.to_string().contains("invalid semantic_bindings"));
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn load_and_spawn_rejects_invalid_cgs_schema_before_state_mutation() {
        let path = write_temp_cgs(invalid_cgs_schema_corpus());
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();

        let err = load_and_spawn_with_plan_policy(
            &path,
            &mut entity_store,
            &mut table_store,
            SgcPlanPolicy::RequirePersisted,
            None,
        )
        .expect_err("invalid CGS schema must fail before SGC/runtime loading");

        let message = err.to_string();
        assert!(message.contains(CGS_SCHEMA_VALIDATION_PREFIX));
        assert!(message.contains("metadata.name must be a non-empty string"));
        assert!(message.contains("metadata.version must be a MAJOR.MINOR.PATCH string"));
        assert!(
            message.contains("metadata.cgs_hash must be a lowercase 64-character SHA-256 digest")
        );
        assert!(message.contains("exactly one mode must have is_default=true; found 0"));
        assert!(message.contains(
            "modes[0].schema_version '0.2.0' does not match metadata.schema_version '0.1.0'"
        ));
        assert!(message.contains("modes[0].actors[0].spawn_count must be an integer >= 1"));
        assert!(message.contains("modes[0].actors[0].components[0].defaults must be an object"));
        assert!(message.contains("modes[0].rules[0].priority must be an integer"));
        assert!(message.contains("global_systems[0].writes for system 'BadSystem' references undeclared component type_id 999"));
        assert!(message.contains("global_systems[0].depends_on for system 'BadSystem' references unknown system 'MissingSystem'"));
        assert!(!message.contains("SGC execution plan required but missing"));
        assert_eq!(entity_store.total_count(), 0);
        assert_eq!(table_store.table_count(), 0);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn register_all_component_tables_registers_authoritative_cgs_components() {
        let path = write_temp_cgs(cgs_with_authoritative_component_schemas());
        let cgs = load_cgs(&path).unwrap();
        let mut table_store = ComponentTableStore::new();

        let registrations = register_all_component_tables(&mut table_store, &cgs).unwrap();
        let type_ids = table_store.all_type_ids();

        for expected in [
            type_ids::TRANSFORM,
            type_ids::IDENTITY,
            type_ids::VELOCITY,
            type_ids::INPUT,
            type_ids::HEALTH,
            type_ids::DAMAGE,
            type_ids::AI,
            type_ids::INVENTORY,
            type_ids::ITEM,
            type_ids::INTERACTION,
            300,
            302,
            700,
            701,
        ] {
            assert!(type_ids.contains(&expected), "missing table {expected}");
        }
        assert_eq!(table_store.table_count(), registrations.len());
        assert_eq!(
            registration_source(&registrations, type_ids::TRANSFORM),
            Some(ComponentRegistrationSource::Builtin)
        );
        assert_eq!(
            registration_source(&registrations, 300),
            Some(ComponentRegistrationSource::GeneratedSchema)
        );
        assert_eq!(
            registration_source(&registrations, 700),
            Some(ComponentRegistrationSource::PluginSchema)
        );
        assert_eq!(
            registration_source(&registrations, 302),
            Some(ComponentRegistrationSource::ActorComponent)
        );
        assert_eq!(
            registration_source(&registrations, 701),
            Some(ComponentRegistrationSource::ActorComponent)
        );
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn register_all_component_tables_rejects_pre_registered_table() {
        let path = write_temp_cgs(cgs_with_authoritative_component_schemas());
        let cgs = load_cgs(&path).unwrap();
        let mut table_store = ComponentTableStore::new();
        table_store
            .register_table(type_ids::TRANSFORM, "COMP_TRANSFORM_V1")
            .unwrap();

        let err = register_all_component_tables(&mut table_store, &cgs)
            .expect_err("pre-registered tables must not be silently accepted");

        assert!(err
            .to_string()
            .contains("registered before authoritative CGS registration"));
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn load_cgs_rejects_duplicate_component_schema_type_ids() {
        let path = write_temp_cgs(invalid_cgs_with_duplicate_component_schemas());

        let err = load_cgs(&path).expect_err("duplicate component schema type_ids must fail");

        let message = err.to_string();
        assert!(message.contains(CGS_SCHEMA_VALIDATION_PREFIX));
        assert!(message.contains("component_schemas declares duplicate component type_id 700"));
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn load_cgs_rejects_system_access_to_undeclared_schema_component() {
        let path = write_temp_cgs(invalid_cgs_with_undeclared_schema_component_access());

        let err = load_cgs(&path).expect_err("unknown component access must fail");

        let message = err.to_string();
        assert!(message.contains(CGS_SCHEMA_VALIDATION_PREFIX));
        assert!(message.contains(
            "global_systems[0].writes for system 'PluginMirrorSystem' references undeclared component type_id 999"
        ));
        let _ = std::fs::remove_file(path);
    }

    fn registration_source(
        registrations: &[ComponentRegistration],
        type_id: u32,
    ) -> Option<ComponentRegistrationSource> {
        registrations
            .iter()
            .find(|registration| registration.type_id == type_id)
            .map(|registration| registration.source)
    }

    fn write_temp_cgs(contents: String) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "xace-cgs-loader-semantic-bindings-{}-{}.json",
            std::process::id(),
            unique
        ));
        std::fs::write(&path, contents).unwrap();
        path
    }

    fn write_temp_project_cgs(contents: String) -> (PathBuf, PathBuf) {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "xace-cgs-loader-sgc-plan-{}-{}",
            std::process::id(),
            unique
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("game.cgs.json");
        std::fs::write(&path, contents).unwrap();
        (root, path)
    }

    fn write_plan(root: &Path, cgs_hash: &str, contents: String) {
        let dir = root.join(".xace").join("execution_plans");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join(format!("{}.plan.json", cgs_hash)), contents).unwrap();
    }

    fn valid_cgs_with_bindings() -> String {
        cgs_with_bindings(
            r#"
            {
              "bindings": [
                {
                  "binding_id": "bind_anim",
                  "event_name": "interaction.accepted",
                  "playback_kind": "Animation",
                  "asset": {"id": "asset_interact_anim_clip_v1", "asset_type": "AnimationClip", "status": "Linked"},
                  "semantic_action": "play",
                  "entity_selector": "SourceEntity",
                  "parameters": {"layer": "upper_body"},
                  "priority": 0
                },
                {
                  "binding_id": "bind_audio",
                  "event_name": "interaction.accepted",
                  "playback_kind": "Audio",
                  "asset": {"id": "asset_interact_sfx_v1", "asset_type": "AudioClip", "status": "Linked"},
                  "semantic_action": "play",
                  "entity_selector": "SourceEntity",
                  "priority": 1
                },
                {
                  "binding_id": "bind_vfx",
                  "event_name": "interaction.accepted",
                  "playback_kind": "Vfx",
                  "asset": {"id": "asset_interact_particle_v1", "asset_type": "Particle", "status": "Linked"},
                  "semantic_action": "spawn",
                  "entity_selector": "TargetEntity",
                  "priority": 2
                }
              ]
            }
            "#,
        )
    }

    fn invalid_cgs_with_mesh_audio_binding() -> String {
        cgs_with_bindings(
            r#"
            {
              "bindings": [
                {
                  "binding_id": "bind_bad_audio",
                  "event_name": "interaction.accepted",
                  "playback_kind": "Audio",
                  "asset": {"id": "asset_bad_mesh_v1", "asset_type": "Mesh", "status": "Linked"},
                  "entity_selector": "SourceEntity"
                }
              ]
            }
            "#,
        )
    }

    fn invalid_cgs_schema_corpus() -> String {
        r#"
        {
          "metadata": {
            "name": "",
            "version": "0.1",
            "schema_version": "0.1.0",
            "cgs_hash": "short"
          },
          "global_systems": [
            {
              "id": "BadSystem",
              "phase": "Simulation",
              "reads": [1],
              "writes": [999],
              "depends_on": ["MissingSystem"],
              "deterministic": true
            }
          ],
          "modes": [
            {
              "id": "default",
              "schema_version": "0.2.0",
              "is_default": false,
              "actors": [
                {
                  "id": "actor_bad",
                  "spawn_count": 0,
                  "components": [
                    {"type_id": 300, "name": "COMP_BAD_V1", "defaults": []}
                  ]
                }
              ],
              "systems": [],
              "rules": [
                {
                  "id": "rule_bad",
                  "condition": "",
                  "effect": "",
                  "priority": "first",
                  "is_active": "yes"
                }
              ]
            }
          ]
        }
        "#
        .to_string()
    }

    fn cgs_with_authoritative_component_schemas() -> String {
        format!(
            r#"{{
              "metadata": {{"name": "Component Schema Test", "version": "0.1.0", "schema_version": "0.1.0", "cgs_hash": "{}"}},
              "component_schemas": [
                {{"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {{"count": 0}}, "source": "generated"}},
                {{"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {{"humidity": 0}}, "source": "plugin"}}
              ],
              "global_systems": [
                {{"id": "GeneratedCounterSystem", "phase": "Simulation", "reads": [300], "writes": [300], "depends_on": [], "deterministic": true}},
                {{"id": "PluginWeatherSystem", "phase": "PostSimulation", "reads": [700], "writes": [700], "depends_on": ["GeneratedCounterSystem"], "deterministic": true}}
              ],
              "modes": [
                {{
                  "id": "default",
                  "schema_version": "0.1.0",
                  "is_default": true,
                  "actors": [
                    {{
                      "id": "player",
                      "spawn_count": 1,
                      "components": [
                        {{"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {{"position_x": 0, "position_y": 0, "position_z": 0}}}},
                        {{"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {{"name": "player"}}}},
                        {{"type_id": 302, "name": "COMP_ACTOR_ONLY_V1", "defaults": {{"enabled": true}}}}
                      ]
                    }}
                  ],
                  "systems": [],
                  "rules": []
                }},
                {{
                  "id": "challenge",
                  "schema_version": "0.1.0",
                  "is_default": false,
                  "actors": [
                    {{
                      "id": "challenge_marker",
                      "spawn_count": 1,
                      "components": [
                        {{"type_id": 701, "name": "PLUGIN_CHALLENGE_STATE_V1", "defaults": {{"level": 1}}}}
                      ]
                    }}
                  ],
                  "systems": [],
                  "rules": []
                }}
              ]
            }}"#,
            "b".repeat(64)
        )
    }

    fn invalid_cgs_with_duplicate_component_schemas() -> String {
        format!(
            r#"{{
              "metadata": {{"name": "Duplicate Component Schema Test", "version": "0.1.0", "schema_version": "0.1.0", "cgs_hash": "{}"}},
              "component_schemas": [
                {{"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {{"humidity": 0}}, "source": "plugin"}},
                {{"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {{"humidity": 1}}, "source": "plugin"}}
              ],
              "global_systems": [],
              "modes": [
                {{
                  "id": "default",
                  "schema_version": "0.1.0",
                  "is_default": true,
                  "actors": [],
                  "systems": [],
                  "rules": []
                }}
              ]
            }}"#,
            "c".repeat(64)
        )
    }

    fn invalid_cgs_with_undeclared_schema_component_access() -> String {
        format!(
            r#"{{
              "metadata": {{"name": "Unknown Schema Component Test", "version": "0.1.0", "schema_version": "0.1.0", "cgs_hash": "{}"}},
              "component_schemas": [
                {{"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {{"humidity": 0}}, "source": "plugin"}}
              ],
              "global_systems": [
                {{"id": "PluginMirrorSystem", "phase": "Simulation", "reads": [700], "writes": [999], "depends_on": [], "deterministic": true}}
              ],
              "modes": [
                {{
                  "id": "default",
                  "schema_version": "0.1.0",
                  "is_default": true,
                  "actors": [],
                  "systems": [],
                  "rules": []
                }}
              ]
            }}"#,
            "d".repeat(64)
        )
    }

    fn cgs_with_bindings(bindings_json: &str) -> String {
        format!(
            r#"{{
              "metadata": {{"name": "Semantic Binding Test", "version": "0.1.0", "schema_version": "0.1.0", "cgs_hash": "{}"}},
              "semantic_bindings": {},
              "global_systems": [],
              "modes": [
                {{
                  "id": "default",
                  "schema_version": "0.1.0",
                  "is_default": true,
                  "actors": [
                    {{
                      "id": "player",
                      "spawn_count": 1,
                      "components": [
                        {{"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {{"position_x": 0, "position_y": 0, "position_z": 0}}}},
                        {{"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {{"name": "player"}}}}
                      ]
                    }}
                  ],
                  "systems": [],
                  "rules": []
                }}
              ]
            }}"#,
            "a".repeat(64),
            bindings_json
        )
    }

    fn cgs_with_systems(cgs_hash: &str) -> String {
        format!(
            r#"{{
              "metadata": {{"name": "SGC Plan Test", "schema_version": "0.1.0", "version": "0.1.0", "execution_plan_version": 1, "cgs_hash": "{}"}},
              "global_systems": [
                {{"id": "InputSystem", "phase": "Input", "reads": [6], "writes": [5], "depends_on": [], "deterministic": true}},
                {{"id": "MovementSystem", "phase": "Simulation", "reads": [1, 5], "writes": [1], "depends_on": ["InputSystem"], "deterministic": true}},
                {{"id": "CustomGeneratedSystem", "phase": "Simulation", "reads": [1], "writes": [100], "depends_on": [], "deterministic": true}}
              ],
              "modes": [
                {{
                  "id": "default",
                  "schema_version": "0.1.0",
                  "is_default": true,
                  "actors": [
                    {{
                      "id": "player",
                      "spawn_count": 1,
                      "components": [
                        {{"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {{"position_x": 0, "position_y": 0, "position_z": 0}}}},
                        {{"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {{"name": "player"}}}}
                      ]
                    }}
                  ],
                  "systems": [],
                  "rules": []
                }}
              ]
            }}"#,
            cgs_hash
        )
    }

    fn cgs_with_single_runtime_system(
        cgs_hash: &str,
        system_id: &str,
        deterministic: bool,
    ) -> String {
        format!(
            r#"{{
              "metadata": {{"name": "Runtime System Test", "schema_version": "0.1.0", "version": "0.1.0", "cgs_hash": "{}"}},
              "global_systems": [
                {{"id": "{}", "phase": "Simulation", "reads": [1, 5], "writes": [1], "depends_on": [], "deterministic": {}}}
              ],
              "modes": [
                {{
                  "id": "default",
                  "schema_version": "0.1.0",
                  "is_default": true,
                  "actors": [
                    {{
                      "id": "player",
                      "spawn_count": 1,
                      "components": [
                        {{"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {{"position_x": 0, "position_y": 0, "position_z": 0}}}},
                        {{"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {{"name": "player"}}}},
                        {{"type_id": 5, "name": "COMP_VELOCITY_V1", "defaults": {{"vx": 1, "vy": 0, "vz": 0}}}}
                      ]
                    }}
                  ],
                  "systems": [],
                  "rules": []
                }}
              ]
            }}"#,
            cgs_hash, system_id, deterministic
        )
    }

    fn cgs_with_generated_counter_system(cgs_hash: &str) -> String {
        format!(
            r#"{{
              "metadata": {{"name": "Generated Counter Test", "schema_version": "0.1.0", "version": "0.1.0", "cgs_hash": "{}"}},
              "global_systems": [
                {{
                  "id": "GeneratedCounterSystem",
                  "phase": "Simulation",
                  "reads": [300],
                  "writes": [300],
                  "depends_on": [],
                  "deterministic": true,
                  "runtime_executor": {{
                    "kind": "generated.increment_numeric_field",
                    "component_type_id": 300,
                    "field": "count",
                    "amount": 1
                  }}
                }}
              ],
              "modes": [
                {{
                  "id": "default",
                  "schema_version": "0.1.0",
                  "is_default": true,
                  "actors": [
                    {{
                      "id": "counter",
                      "spawn_count": 1,
                      "components": [
                        {{"type_id": 300, "name": "COMP_COUNTER_V1", "defaults": {{"count": 0}}}}
                      ]
                    }}
                  ],
                  "systems": [],
                  "rules": []
                }}
              ]
            }}"#,
            cgs_hash
        )
    }

    fn cgs_with_generated_rng_event_system(cgs_hash: &str) -> String {
        format!(
            r#"{{
              "metadata": {{"name": "Generated RNG Event Test", "schema_version": "0.1.0", "version": "0.1.0", "cgs_hash": "{}"}},
              "global_systems": [
                {{
                  "id": "GeneratedLootRollSystem",
                  "phase": "Simulation",
                  "reads": [301],
                  "writes": [],
                  "depends_on": [],
                  "deterministic": true,
                  "runtime_executor": {{
                    "kind": "generated.emit_event_on_rng_threshold",
                    "component_type_id": 301,
                    "chance": 1.0,
                    "event_type": "generated.loot_roll",
                    "payload": {{"source": "generated"}},
                    "abi": {{
                      "schema": "xace.generated_system_abi.v1",
                      "version": 1,
                      "inputs": {{
                        "query_components": [301],
                        "component_reads": [301],
                        "current_tick": true
                      }},
                      "events": {{
                        "emits": [
                          {{
                            "event_type": "generated.loot_roll",
                            "broadcast": true,
                            "payload": {{"source": "generated"}}
                          }}
                        ]
                      }},
                      "rng": {{"allowed": true, "max_calls_per_entity": 1}},
                      "errors": {{"policy": "halt_and_rollback"}},
                      "rollback": {{
                        "mutation_hook": "mutation_gate_deferred",
                        "event_hook": "event_bus_phase_buffered",
                        "rng_hook": "rng_windowed"
                      }}
                    }}
                  }}
                }}
              ],
              "modes": [
                {{
                  "id": "default",
                  "schema_version": "0.1.0",
                  "is_default": true,
                  "actors": [
                    {{
                      "id": "loot_source",
                      "spawn_count": 1,
                      "components": [
                        {{"type_id": 301, "name": "COMP_LOOT_ROLL_V1", "defaults": {{"enabled": true}}}}
                      ]
                    }}
                  ],
                  "systems": [],
                  "rules": []
                }}
              ]
            }}"#,
            cgs_hash
        )
    }

    fn read_runtime_compatibility_proof(root: &Path, cgs_hash: &str) -> serde_json::Value {
        let proof_path = root
            .join(".xace")
            .join("proof")
            .join("runtime-compatibility")
            .join(format!("{}.json", cgs_hash));
        let text = std::fs::read_to_string(proof_path).unwrap();
        serde_json::from_str(&text).unwrap()
    }

    fn read_sgc_migration_proof(root: &Path, cgs_hash: &str) -> serde_json::Value {
        let proof_path = root
            .join(".xace")
            .join("proof")
            .join("sgc-migration")
            .join(format!("{}.json", cgs_hash));
        let text = std::fs::read_to_string(proof_path).unwrap();
        serde_json::from_str(&text).unwrap()
    }

    fn assert_sgc_migration_proof(
        root: &Path,
        cgs_hash: &str,
        reason_code: &str,
    ) -> serde_json::Value {
        let proof = read_sgc_migration_proof(root, cgs_hash);
        assert_eq!(proof["schema"], "xace.sgc.plan_migration.v1");
        assert_eq!(proof["ok"], false);
        assert_eq!(proof["decision"], "reject_and_regenerate");
        assert_eq!(proof["migration_performed"], false);
        assert_eq!(proof["fallback_to_cgs_derived"], false);
        assert_eq!(proof["silent_downgrade_performed"], false);
        assert_eq!(proof["runtime_tick_started"], false);
        assert_eq!(proof["cgs_hash"], cgs_hash);
        assert_eq!(proof["reason_code"], reason_code);
        proof
    }

    fn persisted_plan(cgs_hash: &str, include_custom: bool) -> String {
        let simulation_groups = if include_custom {
            r#"
            [
              {
                "group_id": "Simulation_group_0",
                "phase": "Simulation",
                "parallel": false,
                "systems": ["CustomGeneratedSystem"],
                "serialization_constraints": [],
                "execution_index": 0
              },
              {
                "group_id": "Simulation_group_1",
                "phase": "Simulation",
                "parallel": false,
                "systems": ["MovementSystem"],
                "serialization_constraints": [],
                "execution_index": 1
              }
            ]
            "#
        } else {
            r#"
            [
              {
                "group_id": "Simulation_group_0",
                "phase": "Simulation",
                "parallel": false,
                "systems": ["MovementSystem"],
                "serialization_constraints": [],
                "execution_index": 0
              }
            ]
            "#
        };
        let all_system_ids = if include_custom {
            r#"["CustomGeneratedSystem", "InputSystem", "MovementSystem"]"#
        } else {
            r#"["InputSystem", "MovementSystem"]"#
        };
        let custom_access = if include_custom {
            r#""CustomGeneratedSystem": {"reads": [1], "writes": [100]},"#
        } else {
            ""
        };
        let custom_metadata = if include_custom {
            r#""CustomGeneratedSystem": {"display_name": "Custom Generated System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {"major": 1, "minor": 0}, "description": ""},"#
        } else {
            ""
        };
        format!(
            r#"{{
              "schema_version": "0.1.0",
              "plan_version": 1,
              "adapter_protocol_version": 1,
              "migration_status": "current",
              "created_tick": 0,
              "plan_hash": "{}",
              "compiled_from_cgs_hash": "{}",
              "all_system_ids": {},
              "phases": {{
                "1": {{
                  "phase": "Input",
                  "groups": [
                    {{
                      "group_id": "Input_group_0",
                      "phase": "Input",
                      "parallel": false,
                      "systems": ["InputSystem"],
                      "serialization_constraints": [],
                      "execution_index": 0
                    }}
                  ],
                  "total_system_count": 1
                }},
                "2": {{
                  "phase": "Simulation",
                  "groups": {},
                  "total_system_count": {}
                }}
              }},
              "component_access_sets": {{
                "schema": "xace.sgc.component_access_sets.v1",
                "by_system": {{
                  {}"InputSystem": {{"reads": [6], "writes": [5]}},
                  "MovementSystem": {{"reads": [1, 5], "writes": [1]}}
                }},
                "all_reads": [1, 5, 6],
                "all_writes": [1, 5, 100],
                "component_ids": [1, 5, 6, 100]
              }},
              "system_metadata": {{
                "schema": "xace.sgc.system_metadata.v1",
                "systems": {{
                  {}"InputSystem": {{"display_name": "Input System", "phase": "Input", "depends_on": [], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": ""}},
                  "MovementSystem": {{"display_name": "Movement System", "phase": "Simulation", "depends_on": ["InputSystem"], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": ""}}
                }}
              }},
              "proof_bundle": {{
                "schema": "xace.sgc.proof_ref.v1",
                "path": ".xace/proof/sgc/{}",
                "compiled_from_cgs_hash": "{}",
                "plan_hash": "{}",
                "input_hash": "{}",
                "validation_hash": "{}"
              }}
            }}"#,
            "c".repeat(64),
            cgs_hash,
            all_system_ids,
            simulation_groups,
            if include_custom { 2 } else { 1 },
            custom_access,
            custom_metadata,
            cgs_hash,
            cgs_hash,
            "c".repeat(64),
            "1".repeat(64),
            "2".repeat(64)
        )
    }

    fn mutate_persisted_plan(
        cgs_hash: &str,
        include_custom: bool,
        mutate: impl FnOnce(&mut serde_json::Value),
    ) -> String {
        let mut plan: serde_json::Value =
            serde_json::from_str(&persisted_plan(cgs_hash, include_custom)).unwrap();
        mutate(&mut plan);
        serde_json::to_string_pretty(&plan).unwrap()
    }
}

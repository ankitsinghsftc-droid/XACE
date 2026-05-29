//! CGS loader for the standalone runtime.
//!
//! The loader is deliberately conservative: it validates the minimal CGS shape
//! required by the runtime, registers every component table referenced by
//! actors or system write sets, spawns initial entities deterministically, and
//! emits a phase plan that the runtime can execute without hard-coded ordering.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::Result;
use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::component_tables::component_table_store::ComponentTableStore;
use crate::entity_store::entity_store::EntityStore;

pub type RuntimePhasePlan = Vec<(String, Vec<String>, bool)>;

#[derive(Debug, Clone, Deserialize)]
pub struct CgsRoot {
    #[serde(default)]
    pub metadata: serde_json::Value,
    #[serde(default)]
    pub global_systems: Vec<CgsSystem>,
    #[serde(default)]
    pub modes: Vec<CgsMode>,
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
    pub registered_components: Vec<ComponentRegistration>,
    pub phase_plan: RuntimePhasePlan,
    pub spawned_actors: Vec<SpawnedActor>,
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
    serde_json::from_slice(&bytes)
        .map_err(|err| anyhow::anyhow!("cannot parse CGS JSON '{}': {}", cgs_path.display(), err))
}

pub fn load_and_spawn(
    cgs_path: &Path,
    entity_store: &mut EntityStore,
    table_store: &mut ComponentTableStore,
) -> Result<SpawnSummary> {
    let bytes = fs::read(cgs_path)
        .map_err(|err| anyhow::anyhow!("cannot read '{}': {}", cgs_path.display(), err))?;
    let cgs: CgsRoot = serde_json::from_slice(&bytes)
        .map_err(|err| anyhow::anyhow!("cannot parse CGS JSON: {}", err))?;
    let mode =
        pick_default_mode(&cgs.modes).ok_or_else(|| anyhow::anyhow!("CGS has no modes defined"))?;

    validate_mode(mode)?;
    let registrations = collect_component_registrations(mode, &cgs.global_systems);
    register_component_tables(table_store, &registrations)?;

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
        .unwrap_or_else(|| short_hash(&bytes));
    let phase_plan = build_phase_plan(mode, &cgs.global_systems);

    log::info!(
        "Loaded '{}': mode='{}' actors={} entities={} systems={}",
        cgs_path.file_name().unwrap_or_default().to_string_lossy(),
        mode.id,
        actor_count,
        entity_count,
        phase_plan
            .iter()
            .map(|(_, systems, _)| systems.len())
            .sum::<usize>()
    );

    Ok(SpawnSummary {
        source_path: cgs_path.to_path_buf(),
        mode_id: mode.id.clone(),
        actor_count,
        entity_count,
        schema_version,
        cgs_hash,
        registered_components: registrations,
        phase_plan,
        spawned_actors,
    })
}

pub fn register_all_component_tables(_tables: &mut ComponentTableStore) -> Result<()> {
    Ok(())
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

fn collect_component_registrations(
    mode: &CgsMode,
    global_systems: &[CgsSystem],
) -> Vec<ComponentRegistration> {
    let mut registrations: BTreeMap<u32, ComponentRegistration> = builtin_component_names()
        .into_iter()
        .map(|(type_id, name)| {
            (
                type_id,
                ComponentRegistration {
                    type_id,
                    name: name.to_string(),
                    source: ComponentRegistrationSource::Builtin,
                },
            )
        })
        .collect();

    for actor in &mode.actors {
        for component in &actor.components {
            registrations
                .entry(component.type_id)
                .and_modify(|registration| {
                    if !component.name.is_empty() {
                        registration.name = component.name.clone();
                        registration.source = ComponentRegistrationSource::ActorComponent;
                    }
                })
                .or_insert_with(|| ComponentRegistration {
                    type_id: component.type_id,
                    name: component_name(component),
                    source: ComponentRegistrationSource::ActorComponent,
                });
        }
    }

    for system in global_systems.iter().chain(mode.systems.iter()) {
        for type_id in &system.reads {
            registrations
                .entry(*type_id)
                .or_insert_with(|| ComponentRegistration {
                    type_id: *type_id,
                    name: default_component_name(*type_id),
                    source: ComponentRegistrationSource::SystemRead,
                });
        }
        for type_id in &system.writes {
            registrations
                .entry(*type_id)
                .or_insert_with(|| ComponentRegistration {
                    type_id: *type_id,
                    name: default_component_name(*type_id),
                    source: ComponentRegistrationSource::SystemWrite,
                });
        }
    }

    registrations.into_values().collect()
}

fn register_component_tables(
    table_store: &mut ComponentTableStore,
    registrations: &[ComponentRegistration],
) -> Result<()> {
    for registration in registrations {
        if table_store.has_table(registration.type_id) {
            continue;
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

fn build_phase_plan(mode: &CgsMode, global_systems: &[CgsSystem]) -> RuntimePhasePlan {
    let mut phase_map: BTreeMap<String, Vec<&CgsSystem>> = BTreeMap::new();
    for system in global_systems.iter().chain(mode.systems.iter()) {
        if system.id.trim().is_empty() || !system.deterministic {
            continue;
        }
        let phase = if system.phase.trim().is_empty() {
            "Simulation"
        } else {
            system.phase.as_str()
        };
        phase_map.entry(phase.to_string()).or_default().push(system);
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
            .filter(|system| is_builtin_runtime_system(&system.id))
            .map(|system| system.id.clone())
            .collect::<Vec<_>>();
        if !system_ids.is_empty() {
            plan.push((phase.to_string(), system_ids, false));
        }
    }

    if plan.is_empty() {
        plan.push((
            "Simulation".to_string(),
            vec!["MovementSystem".to_string()],
            false,
        ));
    }
    plan
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
        (type_ids::HEALTH, "COMP_HEALTH_V1"),
        (type_ids::DAMAGE, "COMP_DAMAGE_V1"),
        (type_ids::AI, "COMP_AI_V1"),
    ]
}

fn is_builtin_runtime_system(system_id: &str) -> bool {
    matches!(
        system_id,
        "InputSystem" | "MovementSystem" | "AISystem" | "DamageSystem" | "DeathSystem"
    )
}

fn extract_metadata_str<'a>(value: &'a serde_json::Value, key: &str) -> Option<&'a str> {
    value.get(key)?.as_str()
}

fn extract_str(value: &str) -> Option<&str> {
    (!value.trim().is_empty()).then_some(value)
}

fn short_hash(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    format!("{:x}", digest)[..16].to_string()
}

pub mod type_ids {
    pub const TRANSFORM: u32 = 1;
    pub const IDENTITY: u32 = 2;
    pub const VELOCITY: u32 = 5;
    pub const INPUT: u32 = 6;
    pub const HEALTH: u32 = 100;
    pub const DAMAGE: u32 = 101;
    pub const AI: u32 = 160;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn phase_plan_filters_to_builtin_systems_in_phase_order() {
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
        }];
        let plan = build_phase_plan(&mode, &globals);
        assert_eq!(plan[0].0, "Input");
        assert_eq!(plan[1].0, "Simulation");
    }
}

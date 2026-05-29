//! Runtime orchestrator for the standalone bridge runtime.

use std::path::Path;

use anyhow::Result;
use serde_json::json;
use xace_core::errors::xace_error::XaceError;
use xace_core::runtime::state_delta::StateDelta;

use crate::component_tables::component_table_store::ComponentTableStore;
use crate::engine_bridge::{EngineBridge, EngineBridgeConfig, EngineBridgeStats};
use crate::entity_store::entity_store::EntityStore;
use crate::event_bus::event_bus::EventBus;
use crate::mutation_gate::mutation_gate::MutationGate;
use crate::phase_orchestrator::phase_orchestrator::{PhaseOrchestrator, TickResult};
use crate::phase_orchestrator::system_registry::SystemRegistry;
use crate::query_engine::QueryEngine;
use crate::state_printer::{print_state, PrinterOpts};
use crate::{builtin_systems, cgs_loader, tcp_server};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeConfig {
    pub world_seed: u64,
    pub execution_plan_version: u32,
    pub bridge: EngineBridgeConfig,
    pub apply_engine_input_components: bool,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            world_seed: 42,
            execution_plan_version: 1,
            bridge: EngineBridgeConfig::default(),
            apply_engine_input_components: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeStatus {
    pub tick: u64,
    pub alive_count: usize,
    pub engine_connected: bool,
    pub pending_engine_inputs: usize,
    pub registered_systems: usize,
    pub phase_count: usize,
}

pub struct RuntimeOrchestrator {
    config: RuntimeConfig,
    phase_orch: PhaseOrchestrator,
    registry: SystemRegistry,
    entity_store: EntityStore,
    table_store: ComponentTableStore,
    mutation_gate: MutationGate,
    query_engine: QueryEngine,
    event_bus: EventBus,
    spawn_summary: cgs_loader::SpawnSummary,
    phase_plan: cgs_loader::RuntimePhasePlan,
    bridge: Option<EngineBridge>,
    engine_inputs: Vec<xace_network_core::input::InputPacket>,
    last_tick_result: Option<RuntimeTickSummary>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeTickSummary {
    pub tick: u64,
    pub mutations_applied: usize,
    pub events_dispatched: usize,
    pub engine_inputs_applied: usize,
    pub state_changes: usize,
}

impl RuntimeOrchestrator {
    pub fn initialise(cgs_path: &Path) -> Result<Self> {
        Self::initialise_with_config(cgs_path, RuntimeConfig::default())
    }

    pub fn initialise_with_config(cgs_path: &Path, config: RuntimeConfig) -> Result<Self> {
        let mut entity_store = EntityStore::new();
        let mut table_store = ComponentTableStore::new();
        let mutation_gate = MutationGate::new();
        let query_engine = QueryEngine::new();
        let event_bus = EventBus::new();

        cgs_loader::register_all_component_tables(&mut table_store)?;
        let spawn_summary =
            cgs_loader::load_and_spawn(cgs_path, &mut entity_store, &mut table_store)?;
        let phase_plan = spawn_summary.phase_plan.clone();
        let registry = builtin_systems::build_default_registry()?;
        validate_phase_plan(&phase_plan, &registry)?;

        let phase_orch = PhaseOrchestrator::new(
            config.world_seed,
            spawn_summary.schema_version.clone(),
            config.execution_plan_version,
        );

        Ok(Self {
            config,
            phase_orch,
            registry,
            entity_store,
            table_store,
            mutation_gate,
            query_engine,
            event_bus,
            spawn_summary,
            phase_plan,
            bridge: None,
            engine_inputs: Vec::new(),
            last_tick_result: None,
        })
    }

    pub fn connect_engine(&mut self, port: u16) -> Result<()> {
        let conn = tcp_server::wait_for_connection(port)?;
        let bridge = EngineBridge::handshake_with_config(
            conn.writer()?,
            conn.buf_reader()?,
            self.session_id(),
            self.spawn_summary.cgs_hash.clone(),
            self.spawn_summary.schema_version.clone(),
            &self.entity_store,
            &self.table_store,
            self.config.bridge.clone(),
        )?;
        self.bridge = Some(bridge);
        Ok(())
    }

    pub fn try_connect_engine(&mut self, port: u16, timeout_secs: u64) -> Result<bool> {
        let Some(conn) = tcp_server::try_connect(port, timeout_secs)? else {
            return Ok(false);
        };
        let bridge = EngineBridge::handshake_with_config(
            conn.writer()?,
            conn.buf_reader()?,
            self.session_id(),
            self.spawn_summary.cgs_hash.clone(),
            self.spawn_summary.schema_version.clone(),
            &self.entity_store,
            &self.table_store,
            self.config.bridge.clone(),
        )?;
        self.bridge = Some(bridge);
        Ok(true)
    }

    pub fn tick(&mut self) -> Result<TickResult, XaceError> {
        let applied_inputs = if self.config.apply_engine_input_components {
            self.apply_pending_engine_inputs()?
        } else {
            0
        };
        let phase_plan = self
            .phase_plan
            .iter()
            .map(|(phase, systems, parallel)| (phase.as_str(), systems.clone(), *parallel))
            .collect::<Vec<_>>();

        let result = self.phase_orch.tick(
            &phase_plan,
            &self.registry,
            &mut self.entity_store,
            &mut self.table_store,
            &mut self.mutation_gate,
            &mut self.query_engine,
            &mut self.event_bus,
        )?;

        self.send_tick_to_engine(&result);
        self.last_tick_result = Some(RuntimeTickSummary {
            tick: result.tick,
            mutations_applied: result.mutations_applied,
            events_dispatched: result.events_dispatched,
            engine_inputs_applied: applied_inputs,
            state_changes: result.state_delta.change_count(),
        });
        Ok(result)
    }

    pub fn print_state(&self, tick: u64, delta: &StateDelta, opts: &PrinterOpts) {
        print_state(tick, delta, &self.entity_store, &self.table_store, opts);
    }

    pub fn disconnect_engine(&mut self, reason: &str) {
        if let Some(bridge) = &mut self.bridge {
            bridge.disconnect(reason);
        }
        self.bridge = None;
    }

    pub fn engine_connected(&self) -> bool {
        self.bridge
            .as_ref()
            .map(EngineBridge::is_connected)
            .unwrap_or(false)
    }

    pub fn engine_bridge_stats(&self) -> Option<EngineBridgeStats> {
        self.bridge.as_ref().map(EngineBridge::stats)
    }

    pub fn alive_count(&self) -> usize {
        self.entity_store.get_all_alive().len()
    }

    pub fn drain_engine_inputs(&mut self) -> Vec<xace_network_core::input::InputPacket> {
        std::mem::take(&mut self.engine_inputs)
    }

    pub fn pending_engine_input_count(&self) -> usize {
        self.engine_inputs.len()
    }

    pub fn spawn_summary(&self) -> &cgs_loader::SpawnSummary {
        &self.spawn_summary
    }

    pub fn phase_plan(&self) -> &cgs_loader::RuntimePhasePlan {
        &self.phase_plan
    }

    pub fn status(&self) -> RuntimeStatus {
        RuntimeStatus {
            tick: self.phase_orch.current_tick(),
            alive_count: self.alive_count(),
            engine_connected: self.engine_connected(),
            pending_engine_inputs: self.pending_engine_input_count(),
            registered_systems: self.registry.system_count(),
            phase_count: self.phase_plan.len(),
        }
    }

    pub fn last_tick_result(&self) -> Option<&RuntimeTickSummary> {
        self.last_tick_result.as_ref()
    }

    fn send_tick_to_engine(&mut self, result: &TickResult) {
        let Some(bridge) = &mut self.bridge else {
            return;
        };
        let spawned = result
            .state_delta
            .spawned_entities
            .iter()
            .map(|entity| entity.entity_id)
            .collect();
        let destroyed = result
            .state_delta
            .destroyed_entities
            .iter()
            .map(|entity| entity.entity_id)
            .collect();
        let still_connected = bridge.send_tick(
            result.tick,
            &self.entity_store,
            &self.table_store,
            spawned,
            destroyed,
        );
        if !still_connected {
            log::warn!("Engine disconnected; continuing headless");
            self.bridge = None;
        } else {
            self.engine_inputs.extend(bridge.take_input_packets());
        }
    }

    fn apply_pending_engine_inputs(&mut self) -> Result<usize, XaceError> {
        let inputs = std::mem::take(&mut self.engine_inputs);
        let mut applied = 0;
        for packet in inputs {
            let Some(player_id) = packet.player_id else {
                continue;
            };
            if player_id == 0 || !self.entity_store.is_alive(player_id) {
                continue;
            }
            let mut move_x = 0.0_f32;
            let mut move_z = 0.0_f32;
            for action in &packet.actions {
                match action.action.as_str() {
                    "move_x" | "axis_x" => move_x = action.value,
                    "move_z" | "axis_z" | "move_y" => move_z = action.value,
                    "move_forward" => move_z += action.value,
                    "move_back" => move_z -= action.value,
                    "move_right" => move_x += action.value,
                    "move_left" => move_x -= action.value,
                    _ => {}
                }
            }
            let input_json = json!({
                "move_x": move_x.clamp(-1.0, 1.0),
                "move_z": move_z.clamp(-1.0, 1.0),
                "sequence_id": packet.sequence_id,
                "peer_id": packet.peer_id,
                "source_tick": packet.tick,
            })
            .to_string();
            if self
                .table_store
                .has_component(player_id, cgs_loader::type_ids::INPUT)
            {
                self.table_store.update_component(
                    player_id,
                    cgs_loader::type_ids::INPUT,
                    input_json,
                    self.phase_orch.current_tick(),
                )?;
            } else {
                self.table_store.add_component(
                    player_id,
                    cgs_loader::type_ids::INPUT,
                    input_json,
                    self.phase_orch.current_tick(),
                )?;
            }
            applied += 1;
        }
        Ok(applied)
    }

    fn session_id(&self) -> String {
        format!("session-{}", std::process::id())
    }
}

fn validate_phase_plan(
    plan: &cgs_loader::RuntimePhasePlan,
    registry: &SystemRegistry,
) -> Result<()> {
    for (_, systems, _) in plan {
        let system_refs = systems.iter().map(String::as_str).collect::<Vec<_>>();
        registry
            .validate_execution_plan_systems(&system_refs)
            .map_err(|err| anyhow::anyhow!("invalid phase plan: {}", err))?;
    }
    Ok(())
}

// xace-runtime-core — Deterministic ECS simulation engine
// Tick-driven, not frame-driven. Build phases 2-6.

pub mod entity_store;
pub mod component_tables;
pub mod query_engine;
pub mod mutation_gate;
pub mod phase_orchestrator;
pub mod time_controller;
pub mod snapshot_engine;
pub mod event_bus;
pub mod determinism_guard;

// xace-runtime-core — Deterministic ECS simulation engine
// Tick-driven, not frame-driven. Build phases 2-6.

pub mod component_tables;
pub mod dcl;
pub mod determinism_guard;
pub mod entity_store;
pub mod event_bus;
pub mod mutation_gate;
pub mod phase_orchestrator;
pub mod query_engine;
pub mod snapshot_engine;
pub mod time_controller;

// ── M1: Runtime binary support ───────────────────────────────────────────────
// These modules support the standalone xace_runtime binary at src/bin/.
// They wire the existing phases 2-6 modules into a runnable simulation.

pub mod builtin_systems;
pub mod cgs_loader;
pub mod runtime_orchestrator;
pub mod state_printer;

// ── M2: TCP engine bridge ────────────────────────────────────────────────────
pub mod engine_bridge;
pub mod engine_protocol;
pub mod tcp_server;

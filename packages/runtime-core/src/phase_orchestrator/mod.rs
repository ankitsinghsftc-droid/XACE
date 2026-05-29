//! # Phase Orchestrator Module

pub mod parallel_executor;
pub mod phase_orchestrator;
pub mod system_context;
pub mod system_registry;

#[cfg(test)]
mod tests;

pub use phase_orchestrator::PhaseOrchestrator;
pub use system_registry::SystemRegistry;

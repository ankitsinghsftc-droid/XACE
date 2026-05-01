//! # Phase Orchestrator Module

pub mod system_registry;
pub mod system_context;
pub mod parallel_executor;
pub mod phase_orchestrator;

#[cfg(test)]
mod tests;

pub use phase_orchestrator::PhaseOrchestrator;
pub use system_registry::SystemRegistry;
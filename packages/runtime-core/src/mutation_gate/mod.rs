//! # Mutation Gate Module
//! The enforced gateway for all world state mutations.

pub mod mutation_gate;
pub mod mutation_queue;
pub mod mutation_validator;

#[cfg(test)]
mod tests;

pub use mutation_gate::{MutationApplyFailureDiagnostic, MutationGate, MutationRollbackStatus};
pub use mutation_queue::MutationQueues;
pub use mutation_validator::MutationValidator;

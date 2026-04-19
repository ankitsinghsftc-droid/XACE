//! # Mutation Module
//! DSL operations, transactions, and schema deltas —
//! the complete mutation pipeline types for XACE.

pub mod usmc_categories;
pub mod dsl_operation;
pub mod mutation_transaction;
pub mod schema_delta;

pub use usmc_categories::UsmcCategory;
pub use dsl_operation::{DslOperation, DslValue, OperationType, TypeHint};
pub use mutation_transaction::MutationTransaction;
pub use schema_delta::SchemaDelta;
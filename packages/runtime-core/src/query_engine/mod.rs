//! # Query Engine Module
//! Deterministic cached entity query system.

pub mod query_engine;
pub mod query_cache;

#[cfg(test)]
mod tests;

pub use query_engine::{QueryEngine, QueryResult, QueryCacheStats};
pub use query_cache::QueryCache;
//! # Query Engine Module
//! Deterministic cached entity query system.

pub mod query_cache;
pub mod query_engine;
pub mod sorted_merge_iterator;
pub mod vectorized_query;

#[cfg(test)]
mod tests;

pub use query_cache::QueryCache;
pub use query_engine::{QueryCacheStats, QueryEngine, QueryResult};
// VectorizedQuery is an internal implementation detail — not exported publicly.
// It is used inside query_engine.rs directly. Remove this pub use once the
// struct is fully implemented and made pub in vectorized_query.rs.
pub use sorted_merge_iterator::SortedMergeIterator;

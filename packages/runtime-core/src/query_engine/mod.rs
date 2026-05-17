//! # Query Engine Module
//! Deterministic cached entity query system.

pub mod query_engine;
pub mod query_cache;
pub mod vectorized_query;
pub mod sorted_merge_iterator;

#[cfg(test)]
mod tests;

pub use query_engine::{QueryEngine, QueryResult, QueryCacheStats};
pub use query_cache::QueryCache;
pub use vectorized_query::VectorizedQuery;
pub use sorted_merge_iterator::SortedMergeIterator;
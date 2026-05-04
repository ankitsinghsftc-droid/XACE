//! # Snapshot Engine Module
//! Deterministic world state capture and restore.

pub mod snapshot_engine;
pub mod snapshot_serializer;
pub mod snapshot_store;

#[cfg(test)]
mod tests;

pub use snapshot_engine::SnapshotEngine;
pub use snapshot_serializer::SnapshotSerializer;
pub use snapshot_store::{SnapshotStore, RetentionPolicy};
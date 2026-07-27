//! Deterministic save/load foundation for XACE.
//!
//! The save engine stores three layers per slot:
//! - session: the authoritative WorldSnapshot for the active run
//! - progress: player/profile/story data that survives session rollback
//! - world: persistent world changes such as opened doors or defeated NPCs

pub mod autosave_trigger_system;
pub mod checkpoint_system;
pub mod save_engine;
pub mod save_serializer;
pub mod save_slot;

pub use autosave_trigger_system::{
    AutosaveDecision, AutosaveTriggerSystem, AutosaveTriggerSystemConfig, DirtyPersistenceRecord,
    SaveLayerRequest,
};
pub use checkpoint_system::{
    CheckpointRecord, CheckpointRestorePlan, CheckpointSystem, CheckpointSystemConfig,
    CheckpointType,
};
pub use save_engine::{compute_asset_tree_hash, FileSaveEngine, SaveRecoveryReport};
pub use save_serializer::SaveSerializer;
pub use save_slot::{SaveLayer, SaveSlotMetadata};

use thiserror::Error;

#[derive(Debug, Error)]
pub enum SaveEngineError {
    #[error("save slot '{0}' was not found")]
    SlotNotFound(String),

    #[error("save schema mismatch: save={save_schema} current={current_schema}")]
    SchemaMismatch {
        save_schema: String,
        current_schema: String,
    },

    #[error("save data is invalid: {0}")]
    InvalidData(String),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

pub type SaveResult<T> = Result<T, SaveEngineError>;

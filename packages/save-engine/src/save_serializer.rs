use xace_core::runtime::world_snapshot::WorldSnapshot;

use crate::{SaveEngineError, SaveResult};

#[derive(Debug, Clone, Default)]
pub struct SaveSerializer;

impl SaveSerializer {
    pub fn new() -> Self {
        Self
    }

    pub fn serialize_snapshot(&self, snapshot: &WorldSnapshot) -> SaveResult<String> {
        snapshot.validate().map_err(SaveEngineError::InvalidData)?;
        Ok(serde_json::to_string(snapshot)?)
    }

    pub fn deserialize_snapshot(&self, json: &str) -> SaveResult<WorldSnapshot> {
        let snapshot: WorldSnapshot = serde_json::from_str(json)?;
        snapshot.validate().map_err(SaveEngineError::InvalidData)?;
        Ok(snapshot)
    }

    pub fn validate_schema(&self, save_schema: &str, current_schema: &str) -> SaveResult<()> {
        if save_schema == current_schema {
            Ok(())
        } else {
            Err(SaveEngineError::SchemaMismatch {
                save_schema: save_schema.to_string(),
                current_schema: current_schema.to_string(),
            })
        }
    }
}

use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use xace_core::runtime::world_snapshot::WorldSnapshot;

use crate::{SaveEngineError, SaveLayer, SaveResult, SaveSerializer, SaveSlotMetadata};

#[derive(Debug, Clone)]
pub struct FileSaveEngine {
    root: PathBuf,
    current_schema_version: String,
    serializer: SaveSerializer,
}

impl FileSaveEngine {
    pub fn new(root: impl Into<PathBuf>, current_schema_version: impl Into<String>) -> Self {
        Self {
            root: root.into(),
            current_schema_version: current_schema_version.into(),
            serializer: SaveSerializer::new(),
        }
    }

    pub fn save_session(
        &self,
        slot_id: &str,
        display_name: &str,
        snapshot: &WorldSnapshot,
    ) -> SaveResult<()> {
        self.serializer
            .validate_schema(&snapshot.schema_version, &self.current_schema_version)?;
        self.ensure_slot_dir(slot_id)?;
        let json = self.serializer.serialize_snapshot(snapshot)?;
        self.atomic_write(
            &self.layer_path(slot_id, SaveLayer::Session),
            json.as_bytes(),
        )?;

        let metadata = SaveSlotMetadata {
            slot_id: slot_id.to_string(),
            display_name: display_name.to_string(),
            schema_version: snapshot.schema_version.clone(),
            cgs_hash: snapshot.cgs_hash.clone(),
            tick: snapshot.tick,
            last_saved_unix_ms: unix_ms(),
        };
        self.write_metadata(&metadata)
    }

    pub fn load_session(&self, slot_id: &str) -> SaveResult<WorldSnapshot> {
        let path = self.layer_path(slot_id, SaveLayer::Session);
        if !path.exists() {
            return Err(SaveEngineError::SlotNotFound(slot_id.to_string()));
        }
        let json = fs::read_to_string(path)?;
        let snapshot = self.serializer.deserialize_snapshot(&json)?;
        self.serializer
            .validate_schema(&snapshot.schema_version, &self.current_schema_version)?;
        Ok(snapshot)
    }

    pub fn save_progress(&self, slot_id: &str, progress_json: &str) -> SaveResult<()> {
        self.write_json_layer(slot_id, SaveLayer::Progress, progress_json)
    }

    pub fn load_progress(&self, slot_id: &str) -> SaveResult<String> {
        self.read_json_layer(slot_id, SaveLayer::Progress)
    }

    pub fn save_world_state(&self, slot_id: &str, world_json: &str) -> SaveResult<()> {
        self.write_json_layer(slot_id, SaveLayer::World, world_json)
    }

    pub fn load_world_state(&self, slot_id: &str) -> SaveResult<String> {
        self.read_json_layer(slot_id, SaveLayer::World)
    }

    pub fn list_slots(&self) -> SaveResult<Vec<SaveSlotMetadata>> {
        if !self.root.exists() {
            return Ok(Vec::new());
        }
        let mut slots = Vec::new();
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            if !entry.file_type()?.is_dir() {
                continue;
            }
            let metadata_path = entry.path().join("metadata.json");
            if metadata_path.exists() {
                let json = fs::read_to_string(metadata_path)?;
                slots.push(serde_json::from_str(&json)?);
            }
        }
        slots.sort_by(|a: &SaveSlotMetadata, b: &SaveSlotMetadata| a.slot_id.cmp(&b.slot_id));
        Ok(slots)
    }

    pub fn delete_slot(&self, slot_id: &str) -> SaveResult<()> {
        let path = self.slot_dir(slot_id);
        if !path.exists() {
            return Err(SaveEngineError::SlotNotFound(slot_id.to_string()));
        }
        fs::remove_dir_all(path)?;
        Ok(())
    }

    fn write_json_layer(&self, slot_id: &str, layer: SaveLayer, json: &str) -> SaveResult<()> {
        serde_json::from_str::<serde_json::Value>(json)?;
        self.ensure_slot_dir(slot_id)?;
        self.atomic_write(&self.layer_path(slot_id, layer), json.as_bytes())
    }

    fn read_json_layer(&self, slot_id: &str, layer: SaveLayer) -> SaveResult<String> {
        let path = self.layer_path(slot_id, layer);
        if !path.exists() {
            return Err(SaveEngineError::SlotNotFound(slot_id.to_string()));
        }
        Ok(fs::read_to_string(path)?)
    }

    fn write_metadata(&self, metadata: &SaveSlotMetadata) -> SaveResult<()> {
        let json = serde_json::to_string(metadata)?;
        self.atomic_write(
            &self.slot_dir(&metadata.slot_id).join("metadata.json"),
            json.as_bytes(),
        )
    }

    fn ensure_slot_dir(&self, slot_id: &str) -> SaveResult<()> {
        fs::create_dir_all(self.slot_dir(slot_id))?;
        Ok(())
    }

    fn slot_dir(&self, slot_id: &str) -> PathBuf {
        self.root.join(sanitize_slot_id(slot_id))
    }

    fn layer_path(&self, slot_id: &str, layer: SaveLayer) -> PathBuf {
        self.slot_dir(slot_id).join(layer.file_name())
    }

    fn atomic_write(&self, path: &Path, bytes: &[u8]) -> SaveResult<()> {
        let tmp = path.with_extension("tmp");
        fs::write(&tmp, bytes)?;
        fs::rename(tmp, path)?;
        Ok(())
    }
}

fn sanitize_slot_id(slot_id: &str) -> String {
    slot_id
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '_' || c == '-' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0)
}

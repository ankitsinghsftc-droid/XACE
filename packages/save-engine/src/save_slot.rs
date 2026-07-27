use serde::{Deserialize, Serialize};

use xace_core::entity_metadata::Tick;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SaveLayer {
    Session,
    Progress,
    World,
}

impl SaveLayer {
    pub fn file_name(self) -> &'static str {
        match self {
            Self::Session => "session.json",
            Self::Progress => "progress.json",
            Self::World => "world.json",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SaveSlotMetadata {
    pub slot_id: String,
    pub display_name: String,
    pub schema_version: String,
    pub cgs_hash: String,
    #[serde(default = "default_asset_hash")]
    pub asset_hash: String,
    pub tick: Tick,
    pub last_saved_unix_ms: u128,
}

pub fn default_asset_hash() -> String {
    "no-assets".to_string()
}

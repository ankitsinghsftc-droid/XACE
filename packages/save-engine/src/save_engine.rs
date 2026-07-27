use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};
use xace_core::runtime::world_snapshot::WorldSnapshot;

use crate::{
    save_slot::default_asset_hash, SaveEngineError, SaveLayer, SaveResult, SaveSerializer,
    SaveSlotMetadata,
};

#[derive(Debug, Clone)]
pub struct FileSaveEngine {
    root: PathBuf,
    current_schema_version: String,
    serializer: SaveSerializer,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SaveRecoveryReport {
    pub temp_files_removed: usize,
    pub files_restored: usize,
    pub slots_checked: usize,
    pub errors: Vec<String>,
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
        self.save_session_with_asset_hash(slot_id, display_name, snapshot, &default_asset_hash())
    }

    pub fn save_project_session(
        &self,
        slot_id: &str,
        display_name: &str,
        snapshot: &WorldSnapshot,
        asset_root: impl AsRef<Path>,
    ) -> SaveResult<()> {
        let asset_hash = compute_asset_tree_hash(asset_root)?;
        self.save_session_with_asset_hash(slot_id, display_name, snapshot, &asset_hash)
    }

    pub fn save_session_with_asset_hash(
        &self,
        slot_id: &str,
        display_name: &str,
        snapshot: &WorldSnapshot,
        asset_hash: &str,
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
            asset_hash: asset_hash.to_string(),
            tick: snapshot.tick,
            last_saved_unix_ms: unix_ms(),
        };
        self.write_metadata(&metadata)
    }

    pub fn load_session(&self, slot_id: &str) -> SaveResult<WorldSnapshot> {
        self.recover()?;
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

    pub fn load_metadata(&self, slot_id: &str) -> SaveResult<SaveSlotMetadata> {
        self.recover()?;
        let metadata_path = self.slot_dir(slot_id).join("metadata.json");
        if !metadata_path.exists() {
            return Err(SaveEngineError::SlotNotFound(slot_id.to_string()));
        }
        let json = fs::read_to_string(metadata_path)?;
        Ok(serde_json::from_str(&json)?)
    }

    pub fn save_progress(&self, slot_id: &str, progress_json: &str) -> SaveResult<()> {
        self.write_json_layer(slot_id, SaveLayer::Progress, progress_json)
    }

    pub fn load_progress(&self, slot_id: &str) -> SaveResult<String> {
        self.recover()?;
        self.read_json_layer(slot_id, SaveLayer::Progress)
    }

    pub fn save_world_state(&self, slot_id: &str, world_json: &str) -> SaveResult<()> {
        self.write_json_layer(slot_id, SaveLayer::World, world_json)
    }

    pub fn load_world_state(&self, slot_id: &str) -> SaveResult<String> {
        self.recover()?;
        self.read_json_layer(slot_id, SaveLayer::World)
    }

    pub fn list_slots(&self) -> SaveResult<Vec<SaveSlotMetadata>> {
        self.recover()?;
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

    pub fn recover(&self) -> SaveResult<SaveRecoveryReport> {
        let mut report = SaveRecoveryReport::default();
        if !self.root.exists() {
            return Ok(report);
        }
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            if !entry.file_type()?.is_dir() {
                continue;
            }
            report.slots_checked += 1;
            self.recover_slot(&entry.path(), &mut report)?;
        }
        Ok(report)
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

    fn recover_slot(&self, slot_dir: &Path, report: &mut SaveRecoveryReport) -> SaveResult<()> {
        report.temp_files_removed += cleanup_save_temp_files(slot_dir)?;
        let metadata_path = slot_dir.join("metadata.json");
        self.restore_file_if_invalid(&metadata_path, SaveFileKind::Metadata, report)?;
        for layer in [SaveLayer::Session, SaveLayer::Progress, SaveLayer::World] {
            let path = slot_dir.join(layer.file_name());
            self.restore_file_if_invalid(&path, SaveFileKind::Layer(layer), report)?;
        }
        self.recover_slot_consistency(slot_dir, report)?;
        Ok(())
    }

    fn restore_file_if_invalid(
        &self,
        path: &Path,
        kind: SaveFileKind,
        report: &mut SaveRecoveryReport,
    ) -> SaveResult<()> {
        if path.exists() && self.save_file_is_valid(path, kind) {
            return Ok(());
        }
        let backup = backup_path(path);
        if backup.exists() && self.save_file_is_valid(&backup, kind) {
            copy_file_atomically(&backup, path)?;
            report.files_restored += 1;
            return Ok(());
        }
        if !path.exists() {
            return Ok(());
        }
        report
            .errors
            .push(format!("no valid backup for {}", path.display()));
        Ok(())
    }

    fn recover_slot_consistency(
        &self,
        slot_dir: &Path,
        report: &mut SaveRecoveryReport,
    ) -> SaveResult<()> {
        let metadata_path = slot_dir.join("metadata.json");
        let session_path = slot_dir.join(SaveLayer::Session.file_name());
        if !metadata_path.exists() || !session_path.exists() {
            return Ok(());
        }
        let Ok(metadata) = self.read_metadata_file(&metadata_path) else {
            return Ok(());
        };
        let Ok(session) = self.read_session_file(&session_path) else {
            return Ok(());
        };
        if metadata.tick == session.tick
            && metadata.schema_version == session.schema_version
            && metadata.cgs_hash == session.cgs_hash
        {
            return Ok(());
        }

        let session_backup = backup_path(&session_path);
        if let Ok(backup_session) = self.read_session_file(&session_backup) {
            if metadata.tick == backup_session.tick
                && metadata.schema_version == backup_session.schema_version
                && metadata.cgs_hash == backup_session.cgs_hash
            {
                copy_file_atomically(&session_backup, &session_path)?;
                report.files_restored += 1;
                return Ok(());
            }
        }

        let metadata_backup = backup_path(&metadata_path);
        if let Ok(backup_metadata) = self.read_metadata_file(&metadata_backup) {
            if backup_metadata.tick == session.tick
                && backup_metadata.schema_version == session.schema_version
                && backup_metadata.cgs_hash == session.cgs_hash
            {
                copy_file_atomically(&metadata_backup, &metadata_path)?;
                report.files_restored += 1;
                return Ok(());
            }
        }

        report.errors.push(format!(
            "metadata/session mismatch in {} cannot be repaired",
            slot_dir.display()
        ));
        Ok(())
    }

    fn save_file_is_valid(&self, path: &Path, kind: SaveFileKind) -> bool {
        match kind {
            SaveFileKind::Metadata => self.read_metadata_file(path).is_ok(),
            SaveFileKind::Layer(SaveLayer::Session) => self.read_session_file(path).is_ok(),
            SaveFileKind::Layer(SaveLayer::Progress) | SaveFileKind::Layer(SaveLayer::World) => {
                fs::read_to_string(path)
                    .ok()
                    .and_then(|json| serde_json::from_str::<serde_json::Value>(&json).ok())
                    .is_some()
            }
        }
    }

    fn read_metadata_file(&self, path: &Path) -> SaveResult<SaveSlotMetadata> {
        let json = fs::read_to_string(path)?;
        let metadata: SaveSlotMetadata = serde_json::from_str(&json)?;
        self.serializer
            .validate_schema(&metadata.schema_version, &self.current_schema_version)?;
        Ok(metadata)
    }

    fn read_session_file(&self, path: &Path) -> SaveResult<WorldSnapshot> {
        let json = fs::read_to_string(path)?;
        let snapshot = self.serializer.deserialize_snapshot(&json)?;
        self.serializer
            .validate_schema(&snapshot.schema_version, &self.current_schema_version)?;
        Ok(snapshot)
    }

    fn atomic_write(&self, path: &Path, bytes: &[u8]) -> SaveResult<()> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        if path.exists() {
            copy_file_atomically(path, &backup_path(path))?;
        }
        let tmp = temp_path(path);
        let mut file = fs::File::create(&tmp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        replace_file_atomically(&tmp, path)?;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy)]
enum SaveFileKind {
    Metadata,
    Layer(SaveLayer),
}

fn temp_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("save");
    path.with_file_name(format!(".xace_tmp_{}_{}", std::process::id(), name))
}

fn backup_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("save");
    path.with_file_name(format!(".xace_bak_{}", name))
}

fn copy_file_atomically(source: &Path, target: &Path) -> SaveResult<()> {
    let bytes = fs::read(source)?;
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)?;
    }
    let tmp = temp_path(target);
    let mut file = fs::File::create(&tmp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    replace_file_atomically(&tmp, target)?;
    Ok(())
}

fn replace_file_atomically(source: &Path, target: &Path) -> SaveResult<()> {
    match fs::rename(source, target) {
        Ok(()) => Ok(()),
        Err(_) if target.exists() => {
            fs::remove_file(target)?;
            fs::rename(source, target)?;
            Ok(())
        }
        Err(err) => Err(SaveEngineError::Io(err)),
    }
}

fn cleanup_save_temp_files(slot_dir: &Path) -> SaveResult<usize> {
    let mut removed = 0;
    for entry in fs::read_dir(slot_dir)? {
        let entry = entry?;
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
            continue;
        };
        if name.starts_with(".xace_tmp_") || name.ends_with(".tmp") {
            fs::remove_file(path)?;
            removed += 1;
        }
    }
    Ok(removed)
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

pub fn compute_asset_tree_hash(root: impl AsRef<Path>) -> SaveResult<String> {
    let root = root.as_ref();
    if !root.exists() {
        return Ok(default_asset_hash());
    }
    if !root.is_dir() {
        return Err(SaveEngineError::InvalidData(format!(
            "asset root is not a directory: {}",
            root.display()
        )));
    }

    let mut files = Vec::new();
    collect_files(root, root, &mut files)?;
    files.sort_by(|a, b| a.0.cmp(&b.0));

    let mut hasher = Sha256::new();
    feed_str(&mut hasher, "xace-asset-tree-v1");
    feed_u64(&mut hasher, files.len() as u64);
    for (relative_path, absolute_path) in files {
        feed_str(&mut hasher, &relative_path);
        let bytes = fs::metadata(&absolute_path)?.len();
        feed_u64(&mut hasher, bytes);
        feed_str(&mut hasher, &hash_file(&absolute_path)?);
    }
    Ok(hex_encode(&hasher.finalize()))
}

fn collect_files(root: &Path, current: &Path, out: &mut Vec<(String, PathBuf)>) -> SaveResult<()> {
    for entry in fs::read_dir(current)? {
        let entry = entry?;
        let path = entry.path();
        let file_type = entry.file_type()?;
        if file_type.is_dir() {
            collect_files(root, &path, out)?;
        } else if file_type.is_file() {
            let relative = path
                .strip_prefix(root)
                .map_err(|err| SaveEngineError::InvalidData(err.to_string()))?
                .to_string_lossy()
                .replace('\\', "/")
                .to_lowercase();
            out.push((relative, path));
        }
    }
    Ok(())
}

fn hash_file(path: &Path) -> SaveResult<String> {
    let mut file = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hex_encode(&hasher.finalize()))
}

fn feed_u64(hasher: &mut Sha256, value: u64) {
    hasher.update(value.to_be_bytes());
}

fn feed_str(hasher: &mut Sha256, value: &str) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value.as_bytes());
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

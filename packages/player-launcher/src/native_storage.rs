//! Stable native save namespace and conservative compatibility admission.
//! Payloads remain runtime snapshots; this layer never migrates gameplay state.
use crate::distribution::digest;
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::{Path, PathBuf};

#[derive(Clone, Deserialize, Serialize, PartialEq, Debug)]
#[serde(deny_unknown_fields)]
pub struct SaveIdentity {
    pub game_id: String,
    pub save_schema: String,
    pub gameplay_hash: String,
    pub executor_sha256: String,
    pub compatibility: crate::native_release::Compatibility,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    schema: String,
    identity: SaveIdentity,
    payload_sha256: String,
    snapshot: Value,
}
/// No install path, release version or cache name participates in the namespace.
/// The host supplies the actual per-user LocalAppData directory, never a project.
pub fn namespace(local_app_data: &Path, game_id: &str) -> Result<PathBuf> {
    ensure!(local_app_data.is_absolute(), "Absolute per-user data directory required");
    ensure!(!game_id.is_empty() && game_id.len() <= 128 && game_id.bytes().all(|b|
        b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_'), "Invalid stable game identity");
    Ok(local_app_data.join("XACE/NativeGames").join(format!("game-{game_id}")).join("saves"))
}
/// Snapshot validation and restoration still belong to the runtime SaveEngine.
/// This envelope only binds its serialized snapshot to the admitted executor.
#[cfg(test)]
fn encode(identity: &SaveIdentity, snapshot: Value) -> Result<Vec<u8>> {
    ensure!(snapshot.is_object(), "Runtime snapshot object required");
    let payload = serde_json::to_vec(&snapshot)?;
    ensure!(payload.len() <= 64 * 1024 * 1024, "Snapshot size limit");
    Ok(serde_json::to_vec(&Envelope { schema: "xace.native_save.v1".into(),
        identity: identity.clone(), payload_sha256: digest(&payload), snapshot })?)
}
/// Read-only, exact compatibility. No migration is silently inferred from a
/// version number, and refusal leaves the original bytes untouched.
pub fn admit(bytes: &[u8], expected: &SaveIdentity) -> Result<Value> {
    ensure!(bytes.len() <= 65 * 1024 * 1024, "Save size limit");
    let envelope: Envelope = serde_json::from_slice(bytes).context("Invalid save envelope")?;
    ensure!(envelope.schema == "xace.native_save.v1" && envelope.identity == *expected,
        "Save requires a different gameplay/executor profile; original retained, explicit migration required");
    ensure!(envelope.snapshot.is_object()
        && digest(&serde_json::to_vec(&envelope.snapshot)?) == envelope.payload_sha256,
        "Save payload integrity mismatch");
    Ok(envelope.snapshot)
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn identity() -> SaveIdentity {
        serde_json::from_value(json!({"game_id":"game-a","save_schema":"game.save.v1",
            "gameplay_hash":"a".repeat(64),"executor_sha256":"b".repeat(64),
            "compatibility":{"runtime_abi":"xace.runtime_executor.v1","numeric_profile":"fixed64_y_up_neg_z_v1",
            "simulation_profile":"fixed64_60hz.v1","world_versions":[3],"geometry_profiles":["world.aabb.v1"],
            "snapshot_schema":"xace.world_snapshot.v1","replay_schema":"xace.epoch_replay.v1",
            "input_schema":"xace.input_packet.v1","event_schema":"xace.domain_event.v1","platform":"windows_x64"}})).unwrap()
    }
    #[test]
    fn exact_roundtrip_and_non_destructive_refusal() {
        let identity = identity(); let snapshot = json!({"tick":42,"rng_state":{"world_seed":17}});
        let bytes = encode(&identity, snapshot.clone()).unwrap(); let original = bytes.clone();
        assert_eq!(admit(&bytes, &identity).unwrap(), snapshot);
        for field in ["game_id", "save_schema", "gameplay_hash", "executor_sha256"] {
            let mut changed = serde_json::to_value(&identity).unwrap(); changed[field] = "different".into();
            assert!(admit(&bytes, &serde_json::from_value(changed).unwrap()).is_err());
        }
        let mut changed = identity.clone(); changed.compatibility.snapshot_schema = "other.v1".into();
        assert!(admit(&bytes, &changed).is_err()); assert_eq!(bytes, original);
        let mut corrupt: Value = serde_json::from_slice(&bytes).unwrap(); corrupt["snapshot"]["tick"] = 43.into();
        assert!(admit(&serde_json::to_vec(&corrupt).unwrap(), &identity).is_err());
    }
    #[test]
    fn namespace_separates_games_and_refuses_paths() {
        let root = std::env::current_dir().unwrap();
        assert_ne!(namespace(&root, "one").unwrap(), namespace(&root, "two").unwrap());
        assert!(namespace(&root, "../escape").is_err());
        assert!(namespace(Path::new("relative"), "one").is_err());
        assert!(namespace(&root, "CON").is_err());
    }
}

/// Called only after release admission and matching runtime ticket readiness.
/// Old activation receipts are retained; failed replacement preserves active.json.
pub(crate) fn activate(root: &Path, source: &Path, identity: &str) -> Result<()> {
    use std::io::Write;
    let _lock = crate::distribution::InstallLock::acquire(root)?;
    let active = root.join("active.json");
    if active.exists() {
        crate::distribution::plain(&active)?;
        let old = std::fs::read(&active)?;
        let backup = root.join(format!("previous-{}.json", uuid::Uuid::new_v4()));
        let mut file = std::fs::OpenOptions::new().write(true).create_new(true).open(backup)?;
        file.write_all(&old)?; file.sync_all()?;
    }
    let next = root.join(format!("candidate-{}.json", uuid::Uuid::new_v4()));
    let bytes = serde_json::to_vec(&serde_json::json!({"schema":"xace.native_activation.v1",
        "release_sha256":identity,"source":source.canonicalize()?}))?;
    let mut file = std::fs::OpenOptions::new().write(true).create_new(true).open(&next)?;
    file.write_all(&bytes)?; file.sync_all()?; drop(file);
    crate::distribution::replace(&next, &active)
}

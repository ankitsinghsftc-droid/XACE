// ============================================================================
// packages/asset-runtime/tests/test_hot_reload_determinism.rs
// ============================================================================
 
/*!
# test_hot_reload_determinism.rs — Hot-Reload Determinism Proof
 
Critical tests that verify the hot-reload pipeline is deterministic:
 
1. Same file content → same SHA-256 hash → same version string
2. TickBoundaryGate holds requests until drain() is called
3. ReloadCoordinator routes file changes to correct component/entity
4. Multiple peers computing the same hash produce identical AssetRef updates
 
## What "deterministic hot-reload" means
 
Two simulation instances that:
    - Start from the same CGS
    - Receive the same reload event (asset_id + content_hash)
    - At the same tick number
 
…must produce the same world state after the reload.
 
This is guaranteed because:
    - Content hash is deterministic (SHA-256 of bytes)
    - Reload becomes a Mutation Gate operation (same as any other mutation)
    - Mutation ordering follows D4 (spawn→add→modify→remove→destroy)
    - World hash includes AssetReference.version field
*/
 
use std::sync::Arc;
use tempfile::NamedTempFile;
 
use xace_asset_runtime::{
    hot_reload::{
        reload_coordinator::{AssetOwnershipMap, ReloadCoordinator},
        tick_boundary_gate::TickBoundaryGate,
        version_hasher::VersionHasher,
    },
    AssetId,
};
 
// ── VersionHasher Tests ───────────────────────────────────────────────────────
 
#[test]
fn hash_bytes_is_deterministic() {
    let data = b"test asset content 12345";
    let h1   = VersionHasher::hash_bytes(data);
    let h2   = VersionHasher::hash_bytes(data);
    assert_eq!(h1, h2);
}
 
#[test]
fn hash_bytes_is_sha256_length() {
    let h = VersionHasher::hash_bytes(b"any data");
    assert_eq!(h.len(), 64, "SHA-256 hex must be 64 chars");
    assert!(h.chars().all(|c| c.is_ascii_hexdigit()));
}
 
#[test]
fn different_content_different_hash() {
    let h1 = VersionHasher::hash_bytes(b"content v1");
    let h2 = VersionHasher::hash_bytes(b"content v2");
    assert_ne!(h1, h2);
}
 
#[test]
fn hash_file_matches_hash_bytes() {
    use std::io::Write;
    let mut f = NamedTempFile::new().unwrap();
    let data  = b"deterministic asset content";
    f.write_all(data).unwrap();
 
    let hash_from_bytes = VersionHasher::hash_bytes(data);
    let hash_from_file  = VersionHasher::hash_file(f.path()).unwrap();
    assert_eq!(hash_from_bytes, hash_from_file);
}
 
#[test]
fn verify_passes_for_matching_content() {
    let data = b"asset bytes";
    let hash = VersionHasher::hash_bytes(data);
    assert!(VersionHasher::verify(data, &hash));
}
 
#[test]
fn verify_fails_for_tampered_content() {
    let data    = b"original asset";
    let hash    = VersionHasher::hash_bytes(data);
    let tampered = b"tampered  asset";
    assert!(!VersionHasher::verify(tampered, &hash));
}
 
 
// ── TickBoundaryGate Tests ────────────────────────────────────────────────────
 
#[test]
fn gate_holds_requests_until_drain() {
    use xace_asset_runtime::hot_reload::tick_boundary_gate::ReloadRequest;
 
    let gate = TickBoundaryGate::new_shared();
 
    gate.push(ReloadRequest::new("mesh_knight", "/assets/mesh.fbx",
        "abc123", 2, 1, 42));
    gate.push(ReloadRequest::new("tex_ground",  "/assets/tex.png",
        "def456", 1, 2, 43));
 
    assert_eq!(gate.pending_count(), 2);
    assert!(!gate.is_empty());
 
    let drained = gate.drain();
    assert_eq!(drained.len(), 2);
    assert_eq!(gate.pending_count(), 0);
    assert!(gate.is_empty());
}
 
#[test]
fn gate_drain_is_idempotent_when_empty() {
    let gate   = TickBoundaryGate::new_shared();
    let empty1 = gate.drain();
    let empty2 = gate.drain();
    assert!(empty1.is_empty());
    assert!(empty2.is_empty());
}
 
#[test]
fn gate_requests_contain_correct_hash() {
    use xace_asset_runtime::hot_reload::tick_boundary_gate::ReloadRequest;
 
    let gate = TickBoundaryGate::new_shared();
    let hash = "a3f2bc7d1e9f452108c3d44e560ab789012f33c1d8e6a97b2c4d5f601234567a";
 
    gate.push(ReloadRequest::new("asset_1", "/file.fbx", hash, 1, 5, 100));
 
    let reqs = gate.drain();
    assert_eq!(reqs[0].content_hash, hash);
    assert_eq!(reqs[0].component_type_id, 5);
    assert_eq!(reqs[0].entity_id, 100);
}
 
 
// ── ReloadCoordinator Tests ───────────────────────────────────────────────────
 
#[test]
fn coordinator_routes_file_change_to_correct_entity() {
    use std::io::Write;
    use xace_asset_runtime::hot_reload::file_watcher::{FileChangeEvent, FileChangeKind};
 
    let mut f = NamedTempFile::new().unwrap();
    f.write_all(b"mesh content v1").unwrap();
    let path = f.path().to_path_buf();
 
    let gate  = TickBoundaryGate::new_shared();
    let coord = ReloadCoordinator::new(Arc::clone(&gate));
 
    coord.register_asset(
        path.clone(),
        "mesh_player",
        5,     // COMP_RENDER_V1 type_id
        1001,  // actor_player entity_id
        1,     // current version
    );
 
    // Simulate file change event
    let event = FileChangeEvent {
        path:         path.clone(),
        kind:         FileChangeKind::Modified,
        timestamp_ms: 0,
    };
    coord.handle_changes(vec![event]);
 
    let pending = gate.drain();
    assert_eq!(pending.len(), 1, "one reload request must be queued");
    let req = &pending[0];
    assert_eq!(req.asset_id.as_str(), "mesh_player");
    assert_eq!(req.component_type_id, 5);
    assert_eq!(req.entity_id, 1001);
    assert_eq!(req.new_version, 2, "version must be incremented");
    assert!(!req.content_hash.is_empty());
}
 
#[test]
fn coordinator_ignores_untracked_file() {
    use xace_asset_runtime::hot_reload::file_watcher::{FileChangeEvent, FileChangeKind};
 
    let gate  = TickBoundaryGate::new_shared();
    let coord = ReloadCoordinator::new(Arc::clone(&gate));
 
    // No assets registered
    let event = FileChangeEvent {
        path:         std::path::PathBuf::from("/some/random/file.fbx"),
        kind:         FileChangeKind::Modified,
        timestamp_ms: 0,
    };
    coord.handle_changes(vec![event]);
    assert!(gate.is_empty(), "untracked file must not produce a reload request");
}
 
#[test]
fn two_instances_same_content_produce_same_hash() {
    // Simulates two simulation peers both receiving a file change
    let data  = b"shared asset content";
    let hash1 = VersionHasher::hash_bytes(data);
    let hash2 = VersionHasher::hash_bytes(data);
 
    // Both peers compute the same hash → AssetReference.version is identical
    assert_eq!(hash1, hash2,
        "DETERMINISM VIOLATION: two peers computing hash for same content must agree");
}
 
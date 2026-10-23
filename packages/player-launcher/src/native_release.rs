//! Native release admission. Trust comes from the host's pinned receipt digest.
//! Verification is read-only and never executes a package or invokes a compiler.
use crate::distribution::{digest, safe_path, FileRecord, plain};
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeSet, fs, path::{Path, PathBuf}};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Compatibility {
    pub runtime_abi: String,
    pub numeric_profile: String,
    pub simulation_profile: String,
    pub world_versions: Vec<u64>,
    pub geometry_profiles: Vec<String>,
    pub snapshot_schema: String,
    pub replay_schema: String,
    pub input_schema: String,
    pub event_schema: String,
    pub platform: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Release {
    pub schema: String,
    pub game_id: String,
    pub engine: String,
    pub executor_receipt_sha256: String,
    pub package_manifest_sha256: String,
    pub compatibility: Compatibility,
    pub required_capabilities: Vec<String>,
    pub resources: Vec<FileRecord>,
    pub save_schema: String,
}
pub struct AdmittedRelease {
    pub receipt: Release,
    pub package: PathBuf,
    pub identity: String,
}
fn hash(value: &str) -> Result<()> {
    ensure!(value.len() == 64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)), "Invalid SHA256 identity"); Ok(())
}
fn file(root: &Path, relative: &str, limit: u64) -> Result<Vec<u8>> {
    let rel = safe_path(relative)?;
    plain(root)?;
    let mut path = root.to_path_buf();
    for part in rel.components() { path.push(part); plain(&path)?; }
    let metadata = fs::metadata(&path)?;
    ensure!(metadata.is_file() && metadata.len() <= limit, "Invalid or oversized release file");
    let bytes = fs::read(path)?;
    ensure!(bytes.len() as u64 <= limit, "Release file grew during verification");
    Ok(bytes)
}
fn pinned(root: &Path, relative: &str, expected: &str, limit: u64) -> Result<Vec<u8>> {
    hash(expected)?;
    let bytes = file(root, relative, limit)?;
    ensure!(digest(&bytes) == expected, "Release file identity changed: {relative}"); Ok(bytes)
}
fn records(root: &Path, records: &[FileRecord]) -> Result<()> {
    ensure!(records.len() <= 4096, "Too many release files");
    let mut paths = BTreeSet::new();
    let mut total = 0u64;
    for record in records {
        ensure!(paths.insert(record.path.to_lowercase()), "Aliased release file");
        total = total.checked_add(record.size).context("Release size overflow")?;
        ensure!(record.size <= 128*1024*1024 && total <= 512*1024*1024, "Release size limit");
        let bytes = pinned(root, &record.path, &record.sha256, record.size)?;
        ensure!(bytes.len() as u64 == record.size, "Release file size changed");
    }
    Ok(())
}
impl Compatibility {
    fn validate(&self) -> Result<()> {
        ensure!(self.runtime_abi == "xace.runtime_executor.v1"
            && self.numeric_profile == "fixed64_y_up_neg_z_v1"
            && self.simulation_profile == "fixed64_60hz.v1"
            && self.platform == "windows_x64", "Unsupported executor profile");
        ensure!(!self.world_versions.is_empty() && self.world_versions.iter().all(|v| [2,3].contains(v))
            && self.world_versions.windows(2).all(|w| w[0] < w[1]), "Unsupported World versions");
        for schema in [&self.snapshot_schema, &self.replay_schema, &self.input_schema, &self.event_schema] {
            ensure!(schema.ends_with(".v1"), "Unversioned state compatibility");
        }
        ensure!(!self.geometry_profiles.is_empty() && self.geometry_profiles.windows(2).all(|w| w[0] < w[1]), "Unsorted geometry profiles");
        Ok(())
    }
}
/// Receipt and executor are independently pinned by the approved common release.
/// Call again immediately before each launch; an admitted path is not a file lock.
pub fn admit(root: &Path, expected: &str) -> Result<AdmittedRelease> {
    let bytes = pinned(root, "native-release.json", expected, 4*1024*1024)?;
    let receipt: Release = serde_json::from_slice(&bytes)?;
    ensure!(receipt.schema == "xace.native_release.v1", "Unsupported native release");
    ensure!(["Unity", "Unreal", "Godot"].contains(&receipt.engine.as_str()), "Unsupported engine");
    ensure!(!receipt.game_id.is_empty() && receipt.game_id.len() <= 128
        && receipt.game_id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'), "Invalid stable game identity");
    ensure!(receipt.save_schema.ends_with(".v1"), "Versioned save schema required");
    receipt.compatibility.validate()?;
    let executor: Value = serde_json::from_slice(&pinned(root, "executor-receipt.json", &receipt.executor_receipt_sha256, 4*1024*1024)?)?;
    ensure!(executor["schema"] == "xace.native_executor_build.v1", "Unsupported creator receipt");
    let compatibility: Compatibility = serde_json::from_value(executor["compatibility"].clone())?;
    ensure!(compatibility == receipt.compatibility, "Executor compatibility differs from approved release");
    ensure!(executor["state_policy"] == "all_gameplay_state_in_snapshot_no_hidden_mutable_state"
        && executor["shipping"]["player_compilation"] == false, "Unsupported shipping state policy");
    let executable = executor["executable_sha256"].as_str().context("Missing executor identity")?;
    hash(executable)?;
    let builds = executor["build"]["independent_outputs"].as_array().context("Missing creator builds")?;
    ensure!(builds.len() == 2 && builds[0]["build_id"].as_str().is_some_and(|s| !s.is_empty())
        && builds[1]["build_id"].as_str().is_some_and(|s| !s.is_empty())
        && builds[0]["build_id"] != builds[1]["build_id"]
        && builds.iter().all(|b| b["executable_sha256"] == executable), "Unreproduced creator executable");
    let capabilities = executor["capabilities"].as_array().context("Missing executor capabilities")?;
    ensure!(receipt.required_capabilities.windows(2).all(|w| w[0] < w[1])
        && receipt.required_capabilities.iter().all(|c| !c.is_empty() && capabilities.contains(&Value::String(c.clone()))), "Missing required executor capability");
    let package = root.join("package");
    let manifest: Value = serde_json::from_slice(&pinned(&package, "playable.manifest.json", &receipt.package_manifest_sha256, 4*1024*1024)?)?;
    ensure!(manifest["schema"] == "xace.playable_package.v1", "Unsupported package");
    let files: Vec<FileRecord> = serde_json::from_value(manifest["files"].clone())?;
    records(&package, &files)?;
    for required in ["game.cgs.json", "compiled_schema.json", "execution_plan.json", "world.json", "world.manifest.json", "runtime/xace_runtime.exe"] {
        ensure!(files.iter().any(|f| f.path == required), "Missing core package file");
    }
    let gameplay = &manifest["gameplay"];
    ensure!(gameplay["runtime_sha256"] == executable, "Package requires a different executable");
    pinned(&package, "runtime/xace_runtime.exe", executable, 128*1024*1024)?;
    for (key, expected) in [("runtime_abi", &compatibility.runtime_abi), ("simulation_profile", &compatibility.simulation_profile),
        ("input_schema", &compatibility.input_schema), ("event_schema", &compatibility.event_schema), ("platform", &compatibility.platform)] {
        ensure!(gameplay[key].as_str() == Some(expected.as_str()), "Package compatibility mismatch: {key}");
    }
    let world = gameplay["world"]["contract_version"].as_u64().context("Missing World version")?;
    ensure!(compatibility.world_versions.contains(&world), "Unsupported package World version");
    let geometry = gameplay["required_geometry_profiles"].as_array().context("Missing required geometry")?;
    ensure!(geometry.iter().all(|p| p.as_str().is_some_and(|s| compatibility.geometry_profiles.iter().any(|v| v == s))), "Unsupported geometry backend");
    let systems = executor["systems"].as_array().context("Missing executor system census")?;
    let required = gameplay["executors"].as_array().context("Missing package system census")?;
    ensure!(required.iter().all(|s| systems.contains(s)), "Unsupported gameplay system contract");
    let shipping = executor["shipping"]["required_files"].as_object().context("Missing shipping closure")?;
    ensure!(shipping.get("runtime/xace_runtime.exe").and_then(Value::as_str) == Some(executable), "Missing shipping executable");
    for (path, sha) in shipping { pinned(&package, path, sha.as_str().context("Invalid shipping identity")?, 128*1024*1024)?; }
    records(root, &receipt.resources)?;
    Ok(AdmittedRelease { receipt, package, identity: expected.into() })
}

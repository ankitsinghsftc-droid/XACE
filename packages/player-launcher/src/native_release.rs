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
    manifest: Value,
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
        && receipt.game_id.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_'), "Invalid stable game identity");
    ensure!(receipt.save_schema.ends_with(".v1"), "Versioned save schema required");
    receipt.compatibility.validate()?;
    let executor: Value = serde_json::from_slice(&pinned(root, "executor-receipt.json", &receipt.executor_receipt_sha256, 4*1024*1024)?)?;
    ensure!(executor["schema"] == "xace.native_executor_build.v1", "Unsupported creator receipt");
    validate_creator(&executor)?;
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
    Ok(AdmittedRelease { receipt, package, identity: expected.into(), manifest })
}

impl AdmittedRelease {
    pub fn save_identity(&self) -> Result<crate::native_storage::SaveIdentity> {
        Ok(crate::native_storage::SaveIdentity {
            game_id: self.receipt.game_id.clone(), save_schema: self.receipt.save_schema.clone(),
            gameplay_hash: self.manifest["gameplay_hash"].as_str().context("Missing gameplay hash")?.into(),
            executor_sha256: self.manifest["gameplay"]["runtime_sha256"].as_str().context("Missing runtime hash")?.into(),
            compatibility: self.receipt.compatibility.clone(),
        })
    }

    /// Runtime-created ticket is readiness only for this exact admitted package.
    pub fn verify_ticket(&self, ticket: &Value, controller: u64) -> Result<()> {
        ensure!(ticket["schema"] == "xace.session_ticket.v1"
            && ticket["peer_id"] == 1 && ticket["controller_id"] == controller,
            "Authority ticket belongs to another controller");
        let offer = &ticket["offer"];
        let encoded: Value = serde_json::from_str(ticket["offer_json"].as_str().context("Missing serialized offer")?)?;
        ensure!(encoded == *offer, "Authority offer encodings disagree");
        let contract = &offer["contract"];
        ensure!(contract["schema"] == "xace.session_contract.v1"
            && contract["epoch"]["ruleset_epoch"] == 0, "Unexpected authority epoch");
        for key in ["session_id", "authority_incarnation"] {
            uuid::Uuid::parse_str(contract["epoch"][key].as_str().context("Missing authority identity")?)?;
        }
        let gameplay = &contract["gameplay"];
        let pinned = &self.manifest["gameplay"];
        ensure!(gameplay["cgs"]["cgs_hash"] == pinned["cgs_hash"]
            && gameplay["sgc"]["plan_hash"] == pinned["plan_hash"]
            && gameplay["world"] == pinned["world"]
            && gameplay["playable_package"]["content_hash"] == self.manifest["gameplay_hash"]
            && gameplay["playable_package"]["id"] == self.manifest["package_id"]
            && gameplay["playable_package"]["version"] == self.manifest["version"],
            "Authority ticket differs from admitted gameplay");
        ensure!(offer["client"]["adapter"]["engine"].as_str() == Some(self.receipt.engine.to_lowercase().as_str()),
            "Authority adapter claim differs from release; engine offer integration required");
        ensure!(offer["client"]["presentation_manifest_hash"] == self.manifest["presentation_variants"]["player"]["content_hash"], "Authority presentation differs from release");
        hash(ticket["credential"].as_str().context("Missing admission credential")?)?;
        Ok(())
    }
}

fn keys(value: &Value, expected: &[&str]) -> Result<()> {
    let object = value.as_object().context("Contract object required")?;
    ensure!(object.len() == expected.len() && expected.iter().all(|k| object.contains_key(*k)), "Unexpected creator contract fields"); Ok(())
}
fn ordered_strings(value: &Value) -> Result<()> {
    let values = value.as_array().context("String list required")?;
    ensure!(!values.is_empty() && values.iter().all(|v| v.as_str().is_some_and(|s| !s.is_empty() && s.len() <= 256))
        && values.windows(2).all(|w| w[0].as_str() < w[1].as_str()), "Sorted unique string declarations required"); Ok(())
}
fn creator_path(path: &str) -> Result<()> {
    safe_path(path)?;
    for part in path.split('/') {
        let base = part.split('.').next().unwrap().to_ascii_uppercase();
        ensure!(!["CON", "PRN", "AUX", "NUL"].contains(&base.as_str())
            && !(1..=9).any(|n| base == format!("COM{n}") || base == format!("LPT{n}"))
            && !part.chars().any(|c| c < ' ' || "<>\"|?*".contains(c)), "Nonportable creator path");
    }
    Ok(())
}
fn validate_creator(executor: &Value) -> Result<()> {
    keys(executor, &["schema","executor_id","source_files","toolchain","build","executable_sha256","systems","capabilities","compatibility","state_policy","shipping"])?;
    ensure!(executor["executor_id"].as_str().is_some_and(|s| s.ends_with(".v1")), "Versioned executor identity required");
    let sources = executor["source_files"].as_object().context("Build source inventory required")?;
    ensure!(!sources.is_empty() && sources.len() <= 10000 && sources.contains_key("Cargo.lock"), "Locked source inventory required");
    let mut names = BTreeSet::new();
    for (name, sha) in sources { creator_path(name)?; hash(sha.as_str().context("Source hash required")?)?;
        ensure!(names.insert(name.to_lowercase()), "Aliased creator sources"); }
    let toolchain = &executor["toolchain"];
    keys(toolchain, &["rustc_verbose","rustc_sha256","linker_sha256","target"])?;
    ensure!(toolchain["target"] == "x86_64-pc-windows-msvc" && toolchain["rustc_verbose"].as_str().is_some_and(|s| !s.is_empty()), "Unsupported creator toolchain");
    for key in ["rustc_sha256","linker_sha256"] { hash(toolchain[key].as_str().context("Toolchain hash required")?)?; }
    let build = &executor["build"];
    keys(build, &["command","environment","source_digest","independent_outputs"])?;
    let command = build["command"].as_array().context("Build command required")?;
    ensure!(command.iter().all(Value::is_string) && command.contains(&Value::String("--locked".into()))
        && command.contains(&Value::String("--offline".into())), "Locked offline creator build required");
    ensure!(build["environment"].as_object().is_some_and(|m| m.values().all(Value::is_string)), "Explicit build environment required");
    // Python creator canonical JSON uses ensure_ascii, including UTF-16 escapes.
    let json = serde_json::to_string(&executor["source_files"])?;
    let mut canonical = String::new();
    for c in json.chars() {
        if c as u32 >= 127 { let mut units = [0u16;2]; for unit in c.encode_utf16(&mut units) { canonical.push_str(&format!("\\u{unit:04x}")); } }
        else { canonical.push(c); }
    }
    ensure!(build["source_digest"] == digest(canonical.as_bytes()), "Creator source inventory changed");
    ordered_strings(&executor["capabilities"])?;
    let shipping = &executor["shipping"];
    keys(shipping, &["player_compilation","required_files","notices"])?;
    ordered_strings(&shipping["notices"])?;
    let required = shipping["required_files"].as_object().context("Required shipping files missing")?;
    names.clear();
    for (path, sha) in required { creator_path(path)?; hash(sha.as_str().context("Shipping hash required")?)?;
        ensure!(names.insert(path.to_lowercase()), "Aliased shipping files"); }
    let systems = executor["systems"].as_array().context("System census required")?;
    ensure!(!systems.is_empty(), "Empty executor census");
    let mut previous = "";
    for system in systems {
        let id = system["id"].as_str().context("System identity required")?;
        ensure!(id > previous && system["deterministic"] == true, "Sorted deterministic systems required"); previous = id;
        ensure!(system["phase"].as_str().is_some_and(|s| ["Initialization","Input","Simulation","PostSimulation","Cleanup"].contains(&s)), "Unsupported system phase");
        for access in ["reads","writes"] { let values = system[access].as_array().context("Component access required")?;
            ensure!(values.iter().all(|v| v.as_u64().is_some_and(|n| n > 0)) && values.windows(2).all(|w| w[0].as_u64() < w[1].as_u64()), "Sorted positive component access required"); }
        let deps = system["depends_on"].as_array().context("System dependencies required")?;
        ensure!(deps.iter().all(|d| d.as_str().is_some_and(|s| !s.is_empty() && s != id))
            && deps.windows(2).all(|w| w[0].as_str() < w[1].as_str()), "Sorted non-self dependencies required");
    }
    Ok(())
}

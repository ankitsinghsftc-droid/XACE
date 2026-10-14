use crate::{
    cgs_loader::{self, SpawnSummary},
    component_tables::component_table_store::ComponentTableStore,
};
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::Write,
    path::Path,
    sync::{Arc, Mutex},
};
use uuid::Uuid;
use xace_core::{
    wire::session_contract::{compare_session, AdapterIdentity, SessionContract, SessionOffer},
    world::v3::WorldContractV3,
};
use xace_network_core::session::{
    NetworkMode, SessionCompatibilityProfile, SessionManager, SessionPlayerIdentity,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionTicket {
    pub schema: String,
    pub offer: SessionOffer,
    pub offer_json: String,
    pub credential: String,
    pub peer_id: u64,
    pub controller_id: u64,
}
// Opt-in wall-clock diagnostics only; never consumed by simulation or admission.
#[derive(Debug, Default)]
struct SessionLogProbe(Mutex<Option<(std::time::Instant, String)>>);
impl SessionLogProbe {
    fn start() -> Option<Arc<Self>> {
        if std::env::var_os("XACE_SESSION_LOG_DIAGNOSTICS").is_none() { return None; }
        let probe = Arc::new(Self::default());
        let weak = Arc::downgrade(&probe);
        std::thread::spawn(move || loop {
            std::thread::sleep(std::time::Duration::from_millis(250));
            let Some(probe) = weak.upgrade() else { break; };
            let state = probe.0.lock().ok().and_then(|state| state.clone());
            if let Some((started, operation)) = state {
                if started.elapsed() >= std::time::Duration::from_secs(1) {
                    log::warn!("session_journal_stall elapsed_ms={} {}", started.elapsed().as_millis(), operation);
                }
            }
        });
        Some(probe)
    }
    fn set(&self, operation: Option<String>) {
        if let Ok(mut state) = self.0.lock() {
            *state = operation.map(|name| (std::time::Instant::now(), name));
        }
    }
}
#[derive(Debug)]
struct SessionLogFile {
    file: File,
    pending: Option<Vec<u8>>,
}
#[derive(Debug, Clone)]
pub struct SessionLog {
    file: Arc<Mutex<SessionLogFile>>,
    probe: Option<Arc<SessionLogProbe>>,
}
impl SessionLog {
    fn open(path: &Path) -> Result<Self> {
        Ok(Self {
            file: Arc::new(Mutex::new(SessionLogFile { file: OpenOptions::new().create_new(true).append(true).open(path)?, pending: None })),
            probe: SessionLogProbe::start(),
        })
    }
    // The caller's staging operation must not release input to gameplay. Every
    // staged record is synced before this scope can return success, even when
    // the operation itself returns an error. No records are silently dropped.
    pub(crate) fn with_ingress_batch<T>(&self, operation: impl FnOnce() -> Result<T>) -> Result<T> {
        {
            let mut state = self.file.lock().map_err(|_| anyhow::anyhow!("session log poisoned"))?;
            anyhow::ensure!(state.pending.is_none(), "nested session journal batch");
            state.pending = Some(Vec::new());
        }
        let result = operation();
        let flush = (|| -> Result<()> {
            let mut state = self.file.lock().map_err(|_| anyhow::anyhow!("session log poisoned"))?;
            let bytes = state.pending.take().expect("active journal batch");
            if !bytes.is_empty() {
                if let Some(probe) = &self.probe { probe.set(Some("stage=ingress_batch_write".into())); }
                write_durable_batch(&mut state.file, &bytes, |file| {
                    if let Some(probe) = &self.probe { probe.set(Some("stage=ingress_batch_sync_data".into())); }
                    file.sync_data()
                })?;
            }
            Ok(())
        })();
        if let Some(probe) = &self.probe { probe.set(None); }
        flush?;
        result
    }
    pub fn append(&self, value: &Value) -> Result<()> {
        self.append_batch(std::slice::from_ref(value))
    }
    pub fn append_batch(&self, values: &[Value]) -> Result<()> {
        if values.is_empty() { return Ok(()); }
        let mut bytes = Vec::new();
        for value in values {
            serde_json::to_writer(&mut bytes, value)?;
            bytes.push(b'\n');
        }
        let value = &values[0];
        let mark = |stage: &str| {
            if let Some(probe) = &self.probe {
                probe.set(Some(format!("stage={} kind={} tick={} peer={}", stage,
                    value["kind"], value["packet"]["tick"], value["peer_id"])));
            }
        };
        mark("lock");
        let result = (|| -> Result<()> {
            let mut file = self.file.lock().map_err(|_| anyhow::anyhow!("session log poisoned"))?;
            if let Some(pending) = file.pending.as_mut() {
                anyhow::ensure!(pending.len().saturating_add(bytes.len()) <= 8 * 1024 * 1024,
                    "session journal ingress batch exceeds 8 MiB");
                pending.extend_from_slice(&bytes);
                return Ok(());
            }
            mark("write");
            write_durable_batch(&mut file.file, &bytes, |file| {
                mark("sync_data");
                file.sync_data()
            })?;
            Ok(())
        })();
        if let Some(probe) = &self.probe { probe.set(None); }
        result
    }
}
// Success means every complete record in the batch has reached the durability
// barrier. Callers must not release staged input until this returns successfully.
fn write_durable_batch<W: Write>(writer: &mut W, bytes: &[u8],
    sync: impl FnOnce(&mut W) -> std::io::Result<()>) -> std::io::Result<()> {
    writer.write_all(bytes)?;
    sync(writer)
}
#[derive(Debug, Clone)]
pub struct SessionAdmission {
    pub generation: u64,
    pub reconnect_credential: String,
    pub peer_id: u64,
    pub player_id: u64,
    pub contract: SessionContract,
    pub log: SessionLog,
}
#[derive(Debug, Clone)]
struct SessionGrant {
    credential: String,
    controller_id: u64,
    admitted: bool,
    generation: u64,
    player_id: Option<u64>,
}

pub struct LiveSessionController {
    contract: SessionContract,
    grants: BTreeMap<u64, SessionGrant>,
    certified: BTreeSet<AdapterIdentity>,
    members: SessionManager,
    log: SessionLog,
}
fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn file_hash(path: &Path) -> Result<String> {
    Ok(digest(&fs::read(path)?))
}
fn ascii_json_digest(value: &Value) -> Result<String> {
    let mut canonical = String::new();
    for ch in serde_json::to_string(value)?.chars() {
        if ch.is_ascii() && ch != '\u{7f}' {
            canonical.push(ch);
        } else {
            for unit in ch.encode_utf16(&mut [0; 2]) {
                canonical.push_str(&format!("\\u{:04x}", unit));
            }
        }
    }
    Ok(digest(canonical.as_bytes()))
}
fn field<'a>(value: &'a Value, keys: &[&str]) -> Result<&'a Value> {
    keys.iter().try_fold(value, |v, k| {
        v.get(*k)
            .ok_or_else(|| anyhow::anyhow!("missing {}", keys.join(".")))
    })
}
fn string(value: &Value) -> Result<&str> {
    value.as_str().context("expected string identity")
}
fn cgs_version(raw: &str) -> Result<Value> {
    let parts: Vec<u32> = raw
        .split('.')
        .map(str::parse)
        .collect::<std::result::Result<_, _>>()?;
    if parts.len() != 3 {
        bail!("invalid CGS version");
    }
    Ok(json!({"major":parts[0],"minor":parts[1],"patch":parts[2]}))
}
fn adapter(engine: &str) -> AdapterIdentity {
    serde_json::from_value(json!({"engine":engine,"adapter_version":"0.1.0",
        "client_version":"xace.player.v1","platform":"windows_x64"}))
    .unwrap()
}
impl LiveSessionController {
    pub(crate) fn current_contract(&self) -> &SessionContract { &self.contract }
    pub(crate) fn next_ruleset_contract(&self, summary:&SpawnSummary, directory:&Path, parent_manifest:&Path)->Result<SessionContract> {
        let package: Value = serde_json::from_slice(&fs::read(directory.join("playable.manifest.json"))?)?;
        let parent: Value = serde_json::from_slice(&fs::read(parent_manifest)?)?;
        for key in ["schema", "package_id", "version", "presentation_variants"] {
            if field(&package, &[key])? != field(&parent, &[key])? {
                bail!("activation changes unsupported package field: {}", key);
            }
        }
        if package["schema"] != "xace.playable_package.v1"
            || package["gameplay"]["cgs_hash"] != summary.cgs_hash
            || package["gameplay"]["plan_hash"] != summary.execution_plan_hash
            || package["gameplay"]["schema_version"] != summary.schema_version
            || package["gameplay"]["compiled_schema_hash"] != file_hash(&directory.join("compiled_schema.json"))? {
            bail!("activation package does not identify compiled candidate");
        }
        let mut before = parent["gameplay"].clone();
        let mut after = package["gameplay"].clone();
        for key in ["cgs_hash", "plan_hash", "schema_version", "compiled_schema_hash", "world"] {
            before.as_object_mut().context("parent gameplay missing")?.remove(key);
            after.as_object_mut().context("candidate gameplay missing")?.remove(key);
        }
        if before != after { bail!("activation changes unsupported gameplay profile"); }
        let entries = |manifest: &Value| -> Result<BTreeMap<String, Value>> {
            let mut result = BTreeMap::new();
            for entry in manifest["files"].as_array().context("package files missing")? {
                let path = string(field(entry, &["path"])?)?.to_owned();
                if result.insert(path, entry.clone()).is_some() { bail!("duplicate package file"); }
            }
            Ok(result)
        };
        let previous = entries(&parent)?;
        let current = entries(&package)?;
        if previous.keys().ne(current.keys()) { bail!("activation changes package file set"); }
        for (path, entry) in &current {
            if ["game.cgs.json", "execution_plan.json", "world.json", "world.manifest.json", "compiled_schema.json"].contains(&path.as_str()) {
                let bytes = fs::read(directory.join(path))?;
                if entry["sha256"] != digest(&bytes) || entry["size"].as_u64() != Some(bytes.len() as u64) {
                    bail!("activation package file mismatch: {}", path);
                }
            } else if previous.get(path) != Some(entry) { bail!("activation changes runtime or presentation"); }
        }
        let mut unhashed = package.clone();
        unhashed.as_object_mut().context("package object missing")?.remove("package_content_hash");
        if package["gameplay_hash"] != ascii_json_digest(&package["gameplay"])?
            || package["package_content_hash"] != ascii_json_digest(&unhashed)? {
            bail!("activation package identity mismatch");
        }
        let mut value=serde_json::to_value(&self.contract)?;
        value["epoch"]["ruleset_epoch"]=json!(self.contract.epoch.ruleset_epoch.checked_add(1).context("epoch exhausted")?);
        value["gameplay"]["cgs"]=json!({"schema_version":cgs_version(&summary.schema_version)?,"cgs_hash":summary.cgs_hash});
        let plan:Value=serde_json::from_slice(&fs::read(directory.join("execution_plan.json"))?)?;
        value["gameplay"]["sgc"]=json!({"schema_version":summary.schema_version,"plan_version":summary.execution_plan_version,"plan_hash":summary.execution_plan_hash,"compiled_from_cgs_hash":summary.cgs_hash,"adapter_protocol_version":plan["adapter_protocol_version"]});
        let manifest:Value=serde_json::from_slice(&fs::read(directory.join("world.manifest.json"))?)?;
        if package["gameplay"]["world"] != manifest["world"] { bail!("activation package world mismatch"); }
        value["gameplay"]["world"]=manifest["world"].clone();
        value["gameplay"]["input"]["artifact"]["content_hash"]=plan["proof_bundle"]["input_hash"].clone();
        value["gameplay"]["playable_package"]["content_hash"]=package["gameplay_hash"].clone();
        let contract:SessionContract=serde_json::from_value(value)?;
        contract.validate().map_err(|e|anyhow::anyhow!("invalid activation contract: {:?}",e))?;
        Ok(contract)
    }
    pub(crate) fn install_ruleset_contract(&mut self,contract:SessionContract)->Result<()> {
        self.members.require_compatibility_profile(Self::profile(&contract,1))?;
        self.log.append(&json!({"schema":"xace.session_record.v1","kind":"ruleset_committed","epoch":contract.epoch,"gameplay":contract.gameplay}))?;
        self.contract=contract;Ok(())
    }
    pub(crate) fn candidate_identity(&self) -> Value {
        json!({"epoch":self.contract.epoch,"gameplay":self.contract.gameplay})
    }
    #[allow(clippy::too_many_arguments)]
    pub fn create(
        manifest_path: &Path,
        cgs_path: &Path,
        plan_path: &Path,
        world_path: &Path,
        summary: &SpawnSummary,
        ticket_path: &Path,
        log_path: &Path,
        controller_ids: &[u64],
    ) -> Result<Self> {
        if controller_ids.is_empty() || controller_ids.len() > 4
            || controller_ids.iter().any(|id| *id == 0)
            || controller_ids.iter().copied().collect::<BTreeSet<_>>().len() != controller_ids.len()
        {
            bail!("session requires one to four distinct nonzero controller IDs");
        }
        let manifest: Value = serde_json::from_slice(&fs::read(manifest_path)?)?;
        if field(&manifest, &["schema"])? != "xace.playable_package.v1" {
            bail!("invalid package schema");
        }
        let root = manifest_path.parent().context("manifest parent missing")?;
        // Presentation descriptors explicitly declare cosmetic fallbacks. Their
        // own bytes must verify before they can authorize a missing resource;
        // existing-but-tampered files and all gameplay artifacts still fail.
        let mut optional_resources = BTreeSet::new();
        for entry in field(&manifest, &["files"])?.as_array().context("files missing")? {
            let relative = string(field(entry, &["path"])?)?;
            if relative.starts_with("presentation/") && relative.ends_with("/presentation.json")
                && Path::new(relative).components().all(|c|matches!(c,std::path::Component::Normal(_))) {
                let bytes = fs::read(root.join(relative))?;
                if format!("{:x}",Sha256::digest(&bytes)) != string(field(entry,&["sha256"])?)? {
                    bail!("presentation descriptor hash mismatch");
                }
                let descriptor: Value = serde_json::from_slice(&bytes)?;
                if let Some(assets) = descriptor.get("assets").and_then(Value::as_array) {
                    for asset in assets {
                        if asset.get("required").and_then(Value::as_bool)==Some(false) {
                            if let Some(path)=asset.get("path").and_then(Value::as_str) {
                                if path.starts_with("presentation/resources/") {optional_resources.insert(path.to_string());}
                            }
                        }
                    }
                }
            }
        }
        for entry in field(&manifest, &["files"])?
            .as_array()
            .context("files missing")?
        {
            let relative = string(field(entry, &["path"])?)?;
            let path = Path::new(relative);
            if path.is_absolute()
                || path
                    .components()
                    .any(|c| !matches!(c, std::path::Component::Normal(_)))
            {
                bail!("unsafe package path");
            }
            if !root.join(path).try_exists()? && optional_resources.contains(relative) {continue;}
            if file_hash(&root.join(path))? != string(field(entry, &["sha256"])?)? {
                bail!("package hash mismatch: {}", relative);
            }
        }
        for (actual, name) in [
            (cgs_path, "game.cgs.json"),
            (plan_path, "execution_plan.json"),
            (world_path, "world.json"),
        ] {
            if file_hash(actual)? != file_hash(&root.join(name))? {
                bail!("loaded artifact differs from {}", name);
            }
        }
        let gameplay = field(&manifest, &["gameplay"])?;
        if string(field(gameplay, &["cgs_hash"])?)? != summary.cgs_hash
            || string(field(gameplay, &["plan_hash"])?)? != summary.execution_plan_hash
            || string(field(gameplay, &["schema_version"])?)? != summary.schema_version
        {
            bail!("loaded CGS/plan identity mismatch");
        }
        let plan: Value = serde_json::from_slice(&fs::read(plan_path)?)?;
        if string(field(&plan, &["compiled_from_cgs_hash"])?)? != summary.cgs_hash
            || string(field(&plan, &["plan_hash"])?)? != summary.execution_plan_hash
        {
            bail!("persisted plan identity mismatch");
        }
        let world =
            WorldContractV3::from_bytes(&fs::read(world_path)?).map_err(anyhow::Error::msg)?;
        let world_hash: String = world.content_hash().map_err(anyhow::Error::msg)?.into();
        if world_hash != file_hash(world_path)?
            || field(gameplay, &["world", "artifact", "content_hash"])? != &json!(world_hash)
        {
            bail!("world identity mismatch");
        }
        if file_hash(&std::env::current_exe()?)? != string(field(gameplay, &["runtime_sha256"])?)? {
            bail!("runtime executable mismatch");
        }
        let runtime_semantic_hash = digest(&serde_json::to_vec(&json!({
            "abi":field(gameplay,&["runtime_abi"])?,"executors":field(gameplay,&["executors"])?
        }))?);
        let session_id = Uuid::new_v4();
        let incarnation = Uuid::new_v4();
        let semantics: BTreeSet<String> = world
            .objects
            .iter()
            .flat_map(|o| o.capabilities.iter().map(|c| String::from(c.clone())))
            .collect();
        let contract: SessionContract = serde_json::from_value(json!({
            "schema":"xace.session_contract.v1","profile_id":"host_client_lockstep_4p_60hz_windows_world_v3",
            "epoch":{"session_id":session_id,"authority_incarnation":incarnation,"ruleset_epoch":0},
            "gameplay":{
                "cgs":{"schema_version":cgs_version(&summary.schema_version)?,"cgs_hash":summary.cgs_hash},
                "sgc":{"schema_version":summary.schema_version,"plan_version":field(&plan,&["plan_version"])?,
                    "plan_hash":summary.execution_plan_hash,"compiled_from_cgs_hash":summary.cgs_hash,
                    "adapter_protocol_version":field(&plan,&["adapter_protocol_version"])?},
                "world":field(gameplay,&["world"])?,
                "playable_package":{"id":field(&manifest,&["package_id"])?, "version":field(&manifest,&["version"])?,
                    "content_hash":field(&manifest,&["gameplay_hash"])?},
                "input":{"artifact":{"id":"xace.input_profile","version":"1.0.0",
                    "content_hash":field(&plan,&["proof_bundle","input_hash"])?},"packet_schema_version":1},
                "runtime":{"artifact":{"id":"xace.runtime_semantics","version":field(gameplay,&["runtime_abi"])?,
                    "content_hash":runtime_semantic_hash},"wire_protocol_version":1,"engine_protocol_version":1}
            },
            "required_capabilities":["input.timed.v1","world.semantic_bindings.v3","session.projection.v1"],
            "semantic_capabilities":semantics
        }))?;
        contract
            .validate()
            .map_err(|e| anyhow::anyhow!("authority contract: {:?}", e))?;
        let offer: SessionOffer = serde_json::from_value(json!({"contract":contract,
            "client":{"adapter":adapter("godot"),"engine_protocol_version":1,
            "capabilities":["input.timed.v1","world.semantic_bindings.v3","session.projection.v1"],
            "presentation_manifest_hash":field(&manifest,&["presentation_variants","player","content_hash"])?}}))?;
        let offer_json = serde_json::to_string(&offer)?;
        if ticket_path.exists() || log_path.exists() {
            bail!("session ticket/log already exists");
        }
        let ticket_paths: Vec<_> = (0..controller_ids.len())
            .map(|index| {
                if index == 0 { Ok(ticket_path.to_path_buf()) } else {
                    let stem = ticket_path.file_stem().and_then(|v| v.to_str())
                        .context("ticket filename must be UTF-8")?;
                    let suffix = ticket_path.extension().and_then(|v| v.to_str()).unwrap_or("json");
                    Ok(ticket_path.with_file_name(format!("{}.peer{}.{}", stem, index + 1, suffix)))
                }
            })
            .collect::<Result<_>>()?;
        if ticket_paths.iter().any(|path| path.exists()) {
            bail!("session ticket already exists");
        }
        if let Some(parent) = ticket_path.parent() { fs::create_dir_all(parent)?; }
        if let Some(parent) = log_path.parent() { fs::create_dir_all(parent)?; }
        let log = SessionLog::open(log_path)?;
        log.append(&json!({"schema":"xace.session_record.v1","kind":"start",
            "session_id":session_id,"authority_incarnation":incarnation,"ruleset_epoch":0,
            "gameplay":contract.gameplay}))?;
        let mut members = SessionManager::new(NetworkMode::Host);
        members.require_compatibility_profile(Self::profile(&contract, 1))?;
        let mut grants = BTreeMap::new();
        for (index, controller_id) in controller_ids.iter().enumerate() {
            let peer_id = index as u64 + 1;
            let credential = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
            let ticket = SessionTicket {
                schema: "xace.session_ticket.v1".into(),
                offer: offer.clone(),
                offer_json: offer_json.clone(),
                credential: credential.clone(),
                peer_id,
                controller_id: *controller_id,
            };
            let staging = ticket_paths[index].with_extension(format!("{}.tmp", Uuid::new_v4()));
            let mut out = OpenOptions::new().write(true).create_new(true).open(&staging)?;
            serde_json::to_writer(&mut out, &ticket)?;
            out.sync_all()?;
            drop(out);
            fs::rename(&staging, &ticket_paths[index])?;
            grants.insert(peer_id, SessionGrant { credential, controller_id: *controller_id, admitted: false, generation: 0, player_id: None });
        }
        Ok(Self {
            contract,
            grants,
            certified: ["godot", "unity", "unreal"]
                .into_iter()
                .map(adapter)
                .collect(),
            members,
            log,
        })
    }
    fn profile(contract: &SessionContract, peer_id: u64) -> SessionCompatibilityProfile {
        let g = &contract.gameplay;
        SessionCompatibilityProfile::new(
            peer_id,
            g.cgs.schema_version.to_string(),
            String::from(g.sgc.plan_hash.clone()),
            "xace.engine_protocol.v1",
            String::from(g.playable_package.content_hash.clone()),
            String::from(g.runtime.artifact.content_hash.clone()),
            String::from(g.input.artifact.content_hash.clone()),
            contract.profile_id.clone(),
        )
    }
    pub fn disconnect(&mut self, peer_id: u64, reason: &str) -> Result<()> {
        if !self.grants.get(&peer_id).is_some_and(|grant| grant.admitted) {
            bail!("unknown admitted peer");
        }
        let mut next = self.members.clone();
        next.disconnect_peer(peer_id)?;
        next.remove_peer(peer_id)?;
        self.log.append(
            &json!({"schema":"xace.session_record.v1","kind":"membership",
            "action":"disconnected","peer_id":peer_id,"reason":reason,
            "session_id":self.contract.epoch.session_id,
            "authority_incarnation":self.contract.epoch.authority_incarnation,
            "ruleset_epoch":self.contract.epoch.ruleset_epoch}),
        )?;
        self.members = next;
        self.grants.get_mut(&peer_id).expect("known peer").admitted = false;
        Ok(())
    }

    pub(crate) fn journal(&self) -> SessionLog { self.log.clone() }

    pub fn mark_ready(&mut self, peer_id: u64) -> Result<()> {
        self.members.mark_peer_ready(peer_id)?;
        Ok(())
    }

    pub(crate) fn input_validation_record(
        &self,
        packet: &xace_network_core::input::InputPacket,
        decision: &str,
        reason: &str,
    ) -> Value {
        json!({
            "schema":"xace.session_record.v1","kind":"input_validation",
            "session_id":self.contract.epoch.session_id,
            "authority_incarnation":self.contract.epoch.authority_incarnation,
            "ruleset_epoch":self.contract.epoch.ruleset_epoch,
            "peer_id":packet.peer_id,"player_id":packet.player_id,
            "decision":decision,"reason":reason,"packet":packet
        })
    }
    pub(crate) fn record_input_validations(&self, records: &[Value]) -> Result<()> {
        self.log.append_batch(records)
    }
    pub fn record_input_validation(&self, packet: &xace_network_core::input::InputPacket,
        decision: &str, reason: &str) -> Result<()> {
        self.log.append(&self.input_validation_record(packet, decision, reason))
    }

    pub fn record_rejection(&self, reason: &str) -> Result<()> {
        self.log.append(
            &json!({"schema":"xace.session_record.v1","kind":"admission_rejected",
            "session_id":self.contract.epoch.session_id,
            "authority_incarnation":self.contract.epoch.authority_incarnation,
            "ruleset_epoch":self.contract.epoch.ruleset_epoch,"reason":reason}),
        )
    }

    pub fn admit(
        &mut self,
        offer: &SessionOffer,
        credential: &str,
        peer_id: u64,
        tables: &ComponentTableStore,
    ) -> Result<SessionAdmission> {
        let grant = self.grants.get(&peer_id).context("unknown grant peer")?;
        if grant.admitted || credential != grant.credential {
            bail!("invalid or spent grant");
        }
        let controller_id = grant.controller_id;
        compare_session(&self.contract, offer, &self.certified)
            .map_err(|e| anyhow::anyhow!("compatibility rejected: {:?}", e))?;
        let players: Vec<u64> = tables
            .entities_with_all_components(&[cgs_loader::type_ids::INPUT])
            .into_iter()
            .filter(|id| {
                tables
                    .get_component(*id, cgs_loader::type_ids::INPUT)
                    .and_then(|raw| serde_json::from_str::<Value>(raw).ok())
                    .is_some_and(|v| {
                        v["controller_id"].as_u64() == Some(controller_id)
                            && v["control_type"] == "HUMAN"
                    })
            })
            .collect();
        if players.len() != 1 {
            bail!("controller must map to exactly one human player");
        }
        let player_id = players[0];
        if grant.player_id.is_some_and(|previous| previous != player_id) {
            bail!("reconnect player identity changed");
        }
        let generation = grant.generation.checked_add(1).context("generation exhausted")?;
        let reconnect_credential = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
        let identity = SessionPlayerIdentity::new(peer_id, player_id, "Local player").with_adapter(
            format!("{:?}", offer.client.adapter.engine),
            String::from(offer.client.adapter.adapter_version.clone()),
        );
        let mut next = self.members.clone();
        let report =
            next.join_peer_with_compatibility(identity, Self::profile(&self.contract, peer_id))?;
        if !report.compatible {
            bail!("session manager compatibility rejected");
        }
        // Readiness is granted only after projection acknowledgement at a tick boundary.
        self.log.append(
            &json!({"schema":"xace.session_record.v1","kind":"membership",
            "action":"admitted","peer_id":peer_id,"player_id":player_id,
            "session_id":self.contract.epoch.session_id,
            "authority_incarnation":self.contract.epoch.authority_incarnation,
            "ruleset_epoch":self.contract.epoch.ruleset_epoch,
            "adapter":offer.client.adapter,
            "presentation_manifest_hash":offer.client.presentation_manifest_hash}),
        )?;
        self.members = next;
        let grant = self.grants.get_mut(&peer_id).expect("validated grant");
        grant.admitted = true;
        grant.generation = generation;
        grant.player_id = Some(player_id);
        grant.credential = reconnect_credential.clone();
        Ok(SessionAdmission {
            generation, reconnect_credential,
            peer_id,
            player_id,
            contract: self.contract.clone(),
            log: self.log.clone(),
        })
    }
}

#[cfg(test)]
mod durable_batch_tests {
    use super::*;
    #[test]
    fn ingress_scope_flushes_ordered_records_even_when_staging_fails() {
        let path = std::env::temp_dir().join(format!("xace-journal-test-{}.jsonl", Uuid::new_v4()));
        let log = SessionLog::open(&path).unwrap();
        let result: Result<()> = log.with_ingress_batch(|| {
            log.append(&json!({"peer": 3}))?;
            log.append(&json!({"peer": 2}))?;
            assert!(fs::read(&path)?.is_empty());
            bail!("staging rejected")
        });
        assert!(result.unwrap_err().to_string().contains("staging rejected"));
        assert_eq!(fs::read_to_string(&path).unwrap(), "{\"peer\":3}\n{\"peer\":2}\n");
        log.append(&json!({"peer": 1})).unwrap();
        assert!(fs::read_to_string(&path).unwrap().ends_with("{\"peer\":1}\n"));
        drop(log);
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn ingress_scope_rejects_nested_batches_and_oversized_records() {
        let path = std::env::temp_dir().join(format!("xace-journal-test-{}.jsonl", Uuid::new_v4()));
        let log = SessionLog::open(&path).unwrap();
        log.with_ingress_batch(|| {
            assert!(log.with_ingress_batch(|| Ok(())).is_err());
            log.append(&json!({"kept": true}))?;
            assert!(log.append(&json!({"large": "x".repeat(8 * 1024 * 1024)})).is_err());
            Ok(())
        }).unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), "{\"kept\":true}\n");
        drop(log);
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn ordered_records_reach_one_barrier_before_success() {
        let bytes = b"{\"peer\":3}\n{\"peer\":2}\n{\"peer\":1}\n";
        let mut output = Vec::new();
        let mut barriers = 0;
        write_durable_batch(&mut output, bytes, |written| {
            assert_eq!(written.as_slice(), bytes);
            barriers += 1;
            Ok(())
        }).unwrap();
        assert_eq!(barriers, 1);
        assert_eq!(output, bytes);
    }
    #[test]
    fn failed_durability_barrier_never_reports_success() {
        let mut output = Vec::new();
        let result = write_durable_batch(&mut output, b"record\n", |_| {
            Err(std::io::Error::other("injected sync failure"))
        });
        assert!(result.is_err());
        assert_eq!(output, b"record\n");
    }
    #[test]
    fn failed_write_never_calls_durability_barrier() {
        struct Reject;
        impl Write for Reject {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("injected write failure"))
            }
            fn flush(&mut self) -> std::io::Result<()> { Ok(()) }
        }
        assert!(write_durable_batch(&mut Reject, b"record\n", |_| {
            panic!("must not acknowledge a failed write")
        }).is_err());
    }
}

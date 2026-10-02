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
#[derive(Debug, Clone)]
pub struct SessionLog(Arc<Mutex<File>>);
impl SessionLog {
    fn open(path: &Path) -> Result<Self> {
        Ok(Self(Arc::new(Mutex::new(
            OpenOptions::new()
                .create_new(true)
                .append(true)
                .open(path)?,
        ))))
    }
    pub fn append(&self, value: &Value) -> Result<()> {
        let mut file = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session log poisoned"))?;
        serde_json::to_writer(&mut *file, value)?;
        file.write_all(b"\n")?;
        file.sync_data()?;
        Ok(())
    }
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

    pub fn mark_ready(&mut self, peer_id: u64) -> Result<()> {
        self.members.mark_peer_ready(peer_id)?;
        Ok(())
    }

    pub fn record_input_validation(
        &self,
        packet: &xace_network_core::input::InputPacket,
        decision: &str,
        reason: &str,
    ) -> Result<()> {
        self.log.append(&json!({
            "schema":"xace.session_record.v1","kind":"input_validation",
            "session_id":self.contract.epoch.session_id,
            "authority_incarnation":self.contract.epoch.authority_incarnation,
            "ruleset_epoch":self.contract.epoch.ruleset_epoch,
            "peer_id":packet.peer_id,"player_id":packet.player_id,
            "decision":decision,"reason":reason,"packet":packet
        }))
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

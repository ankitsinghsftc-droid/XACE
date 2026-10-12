//! Durable activation decisions. Gameplay and semantic capability names are opaque.
use super::*;
use super::ruleset_candidate::CandidateParent;
use serde::{Deserialize, Serialize};
use std::{fs::{File, OpenOptions}, io::Write};
use super::ruleset_candidate::{CandidateStore,CandidateProposal,CandidatePolicy,migrate_isolated};

/// The local control socket can name only content identities. All filesystem
/// locations come from the trusted host's ruleset_root, never from this payload.
#[derive(Debug,Clone,Serialize,Deserialize)]
#[serde(tag="operation",rename_all="snake_case",deny_unknown_fields)]
pub enum RulesetControl {
    Inspect,
    ExportReplay,
    Current,
    Preview { artifact_digest:String },
    Stage { artifact_digest:String, approved_proposal_digest:String },
    Prepare { candidate_digest:String, proof_digest:String, activation_tick:u64 },
}
fn require_digest(value:&str)->Result<()> {
    anyhow::ensure!(value.len()==64 && value.bytes().all(|c|c.is_ascii_digit() || (b'a'..=b'f').contains(&c)),"expected lowercase SHA-256 identity");Ok(())
}
fn bounded_directory(root:&Path,name:&str)->Result<PathBuf> {
    let path=root.join(name);
    if !path.exists() {std::fs::create_dir(&path)?;}
    let path=path.canonicalize()?;
    anyhow::ensure!(path.starts_with(root),"ruleset directory escaped host storage");Ok(path)
}
impl RuntimeOrchestrator {
    pub fn control_ruleset(&mut self,request:&RulesetControl)->Result<Value> {
        if matches!(request,RulesetControl::ExportReplay) {
            let root=self.config.ruleset_root.as_ref().ok_or_else(||anyhow::anyhow!("host replay storage is not configured"))?.canonicalize()?;
            let directory=bounded_directory(&root,"replays")?;
            let bytes=serde_json::to_vec(&self.sealed_epoch_recording()?)?;
            anyhow::ensure!(bytes.len()<=512*1024*1024,"replay exceeds export size limit");
            let id=format!("{:x}",Sha256::digest(&bytes));let path=directory.join(format!("{}.json",id));
            if path.exists(){anyhow::ensure!(path.canonicalize()?.starts_with(&directory) && std::fs::read(&path)?==bytes,"replay export integrity mismatch");}
            else {anyhow::ensure!(std::fs::read_dir(&directory)?.count()<64,"replay export storage is full");let mut file=OpenOptions::new().create_new(true).write(true).open(path)?;file.write_all(&bytes)?;file.sync_all()?;}
            return Ok(json!({"schema":"xace.replay_export.v1","recording_id":id,"through_tick":self.phase_orch.current_tick().saturating_sub(1)}));
        }
        if matches!(request,RulesetControl::Inspect) {
            return Ok(json!({"schema":"xace.ruleset_inspection.v1","tick":self.phase_orch.current_tick(),
                "contract":self.live_session_controller.as_ref().map(|s|s.current_contract()),
                "phase":if self.activation_failure.is_some(){"ended"}else if self.pending_activation.is_some(){"preparing"}else{"live"},
                "activation_tick":self.pending_activation.as_ref().map(|p|p.journal.request.activation_tick),
                "activation_id":self.pending_activation.as_ref().map(|p|&p.id),"failure":self.activation_failure}));
        }
        let policy=CandidatePolicy{configuration_components:self.config.candidate_configuration_components.clone()};
        anyhow::ensure!(!policy.configuration_components.is_empty(),"host has no registered ruleset migration policy");
        let root=self.config.ruleset_root.as_ref().ok_or_else(||anyhow::anyhow!("host ruleset storage is not configured"))?.canonicalize()?;
        let store=bounded_directory(&root,"candidates")?;
        let make_proposal=|digest:&str|->Result<CandidateProposal> {
            require_digest(digest)?;
            let directory=root.join("incoming").join(digest).canonicalize()?;
            anyhow::ensure!(directory.starts_with(&root),"candidate escaped host storage");
            for name in ["game.cgs.json","execution_plan.json","world.json","world.manifest.json","compiled_schema.json","playable.manifest.json"] {
                anyhow::ensure!(directory.join(name).canonicalize()?.starts_with(&directory),"artifact escaped candidate directory");
            }
            let artifacts=ruleset_candidate::CandidateArtifacts::read(&directory)?;
            anyhow::ensure!(artifacts.digest()?==digest,"installed artifact digest mismatch");
            Ok(CandidateProposal{schema:"xace.ruleset_candidate.v1".into(),parent:self.candidate_parent()?,artifacts,replace_config_defaults:policy.configuration_components.clone()})
        };
        match request {
            RulesetControl::Inspect | RulesetControl::ExportReplay => unreachable!("read-only inspection handled above"),
            RulesetControl::Current => Ok(serde_json::to_value(self.live_session_controller.as_ref().ok_or_else(||anyhow::anyhow!("no live session"))?.current_contract())?),
            RulesetControl::Preview{artifact_digest}=> {
                let proposal=make_proposal(artifact_digest)?;
                Ok(json!({"proposal_digest":proposal.digest()?,"parent":proposal.parent,"configuration_components":proposal.replace_config_defaults}))
            },
            RulesetControl::Stage{artifact_digest,approved_proposal_digest}=> {
                require_digest(approved_proposal_digest)?;
                let proposal=make_proposal(artifact_digest)?;
                anyhow::ensure!(proposal.digest()?==*approved_proposal_digest,"approval does not match current proposal");
                let target=store.join(approved_proposal_digest);
                if target.exists() {anyhow::ensure!(target.canonicalize()?.starts_with(&store),"candidate escaped storage");}
                let approval=ruleset_candidate::CandidateApproval::approve_reviewed(&proposal)?;
                let proof=CandidateStore::new(store).stage(self,&proposal,&approval,&policy,2,|runtime|Ok(json!({"final_tick":runtime.candidate_parent()?.tick})))?;
                Ok(json!({"candidate_digest":proposal.digest()?,"proof_digest":proof.digest()?,"proof":proof}))
            },
            RulesetControl::Prepare{candidate_digest,proof_digest,activation_tick}=> {
                require_digest(candidate_digest)?;require_digest(proof_digest)?;
                anyhow::ensure!(store.join(candidate_digest).canonicalize()?.starts_with(&store),"candidate escaped storage");
                let journals=bounded_directory(&root,"activations")?;
                let id=self.prepare_ruleset_activation(&CandidateStore::new(store),candidate_digest,proof_digest,*activation_tick,&journals.join(format!("{}.jsonl",candidate_digest)),&policy)?;
                Ok(json!({"activation_id":id,"activation_tick":activation_tick}))
            },
        }
    }
}

pub(super) struct PendingActivation {
    id:String,
    directory:PathBuf,
    proposal:CandidateProposal,
    proof_digest:String,
    journal:ActivationJournal,
    contract:Option<xace_core::wire::session_contract::SessionContract>,
    journal_path:PathBuf,
}
#[cfg(feature = "activation-fault-injection")]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActivationFault { DuringMigration, BeforeDecision, AfterDecision, BeforeBroadcast }
impl RuntimeOrchestrator {
    #[cfg(feature = "activation-fault-injection")]
    pub fn inject_activation_fault(&mut self, fault:ActivationFault) { self.activation_fault=Some(fault); }
    #[cfg(feature = "activation-fault-injection")]
    fn activation_fault_at(&mut self, point:ActivationFault)->Result<()> {
        if self.activation_fault==Some(point) {
            self.activation_fault=None;
            anyhow::bail!("injected activation failure: {:?}",point);
        }
        Ok(())
    }
    pub fn prepare_ruleset_activation(&mut self,store:&CandidateStore,candidate_digest:&str,proof_digest:&str,
        tick:u64,journal_path:&Path,policy:&CandidatePolicy)->Result<String> {
        anyhow::ensure!(self.activation_failure.is_none(),"session ended after activation failure");
        if let Some((candidate,proof,at,id))=&self.completed_activation {
            if candidate==candidate_digest && proof==proof_digest && *at==tick { return Ok(id.clone()); }
        }
        if let Some(pending)=&self.pending_activation {
            anyhow::ensure!(pending.proposal.digest()?==candidate_digest && pending.proof_digest==proof_digest && pending.journal.request.activation_tick==tick,"another activation is pending");
            return Ok(pending.id.clone());
        }
        anyhow::ensure!(self.activation_failure.is_none(),"session ended after activation failure");
        let (proposal,proof,directory)=store.verified_candidate(candidate_digest,proof_digest)?;
        anyhow::ensure!(self.candidate_parent()?==proposal.parent,"stale prepared candidate parent");
        anyhow::ensure!(proposal.replace_config_defaults.is_subset(&policy.configuration_components),"migration not registered by host");
        anyhow::ensure!(proof.host_executable_digest==format!("{:x}",Sha256::digest(std::fs::read(std::env::current_exe()?)?)),"candidate was proved by a different executable");
        let (scratch,_,_)=migrate_isolated(self,&proposal,&directory)?;
        let contract=self.live_session_controller.as_ref().map(|s|s.next_ruleset_contract(&scratch.spawn_summary,&directory,self.config.session_manifest_path.as_deref().ok_or_else(||anyhow::anyhow!("missing parent package"))?)).transpose()?;
        let peers=self.bridges.iter().filter_map(|b|b.activation_peer()).collect::<BTreeMap<_,_>>();
        anyhow::ensure!(!self.config.live_session || !peers.is_empty(),"live activation needs ready clients");
        let request=ActivationRequest{schema:"xace.ruleset_activation.v1".into(),candidate_digest:candidate_digest.into(),proof_digest:proof_digest.into(),parent:proposal.parent.clone(),activation_tick:tick,peers};
        let id=request.digest()?;let mut journal=ActivationJournal::create(journal_path,request)?;
        if let Some(contract)=&contract {
            for bridge in &mut self.bridges {
                if bridge.activation_peer().is_some() {
                    if let Err(error)=bridge.prepare_ruleset(&id,tick,contract) {
                        journal.abort(format!("prepare delivery: {}",error))?;
                        for bridge in &mut self.bridges {bridge.abort_ruleset(&id);}
                        return Err(error);
                    }
                }
            }
        }
        self.pending_activation=Some(PendingActivation{id:id.clone(),directory,proposal,proof_digest:proof_digest.into(),journal,contract,journal_path:journal_path.to_owned()});
        Ok(id)
    }
    pub(super) fn process_ruleset_activation(&mut self)->Result<()> {
        let Some(mut pending)=self.pending_activation.take() else {return Ok(());};
        let tick=self.phase_orch.current_tick();
        for bridge in &self.bridges {
            if bridge.ruleset_ready(&pending.id) {
                if let Some((peer,generation))=bridge.activation_peer() {
                    if let Err(error)=pending.journal.mark_ready(peer,generation) {
                        self.activation_failure=Some(format!("activation readiness journal failure: {}",error));
                        let _=self.disconnect_engine("ruleset_journal_failed_session_ended");
                        return Err(error);
                    }
                }
            }
        }
        if tick<pending.journal.request.activation_tick {self.pending_activation=Some(pending);return Ok(());}
        let peers=self.bridges.iter().filter_map(|b|b.activation_peer()).collect::<BTreeMap<_,_>>();
        let result=(||->Result<()> {
            anyhow::ensure!(peers==pending.journal.request.peers && pending.journal.all_ready(),"activation readiness or membership changed");
            anyhow::ensure!(same_ruleset(&self.candidate_parent()?,&pending.proposal.parent),"activation parent changed");
            let artifacts=ruleset_candidate::CandidateArtifacts::read(&pending.directory)?;
            anyhow::ensure!(artifacts.digest()?==pending.proposal.artifacts.digest()?,"candidate artifacts changed before activation");
            // Exactly the XP-018 snapshot migration, now based on state at N.
            // All fallible migration work finishes in isolation before decision.
            let (candidate,_,new_hash)=migrate_isolated(self,&pending.proposal,&pending.directory)?;
            #[cfg(feature = "activation-fault-injection")]
            self.activation_fault_at(ActivationFault::DuringMigration)?;
            let checkpoint=self.world_snapshot().map_err(|e|anyhow::anyhow!("{}",e))?;
            #[cfg(feature = "activation-fault-injection")]
            self.activation_fault_at(ActivationFault::BeforeDecision)?;
            pending.journal.decide(&self.candidate_parent()?,checkpoint)?;
            #[cfg(feature = "activation-fault-injection")]
            self.activation_fault_at(ActivationFault::AfterDecision)?;
            self.install_prepared_runtime(candidate);
            if pending.contract.is_some() { self.config.session_manifest_path=Some(pending.directory.join("playable.manifest.json")); }
            self.activation_sync_peers=pending.journal.request.peers.keys().copied().collect();
            let epoch=pending.contract.as_ref().map(|c|c.epoch.ruleset_epoch).unwrap_or(1);
            pending.journal.published(tick,epoch,new_hash)?;
            self.record_replay_activation(&pending.id,&pending.proposal,&pending.journal_path)?;
            #[cfg(feature = "activation-fault-injection")]
            self.activation_fault_at(ActivationFault::BeforeBroadcast)?;
            if let Some(contract)=pending.contract.clone() {
                self.live_session_controller.as_mut().ok_or_else(||anyhow::anyhow!("missing live controller"))?.install_ruleset_contract(contract.clone())?;
                for bridge in &mut self.bridges { if bridge.activation_peer().is_some() {bridge.commit_ruleset(&pending.id,&contract)?;} }
            }
            self.completed_activation=Some((pending.proposal.digest()?,pending.proof_digest.clone(),tick,pending.id.clone()));
            Ok(())
        })();
        if let Err(error)=result {
            if pending.journal.is_decided() || pending.journal.terminal {
                let reason=format!("durable ruleset decision could not complete: {}",error);
                let _=pending.journal.end(reason.clone());self.activation_failure=Some(reason);
                let _=self.disconnect_engine("ruleset_activation_failed_session_ended");return Err(error);
            }
            pending.journal.abort(error.to_string())?;
            for bridge in &mut self.bridges {bridge.abort_ruleset(&pending.id);}
        }
        Ok(())
    }
    fn install_prepared_runtime(&mut self,candidate:RuntimeOrchestrator) {
        // Old snapshots cannot be replayed under the new plan. Immutable journals
        // retain epoch history; XP-020 supplies explicit cross-epoch replay.
        self.rollback_snapshots=candidate.rollback_snapshots;
        self.table_store=candidate.table_store;
        self.registry=candidate.registry;
        self.pending_input_mutations=candidate.pending_input_mutations;
        self.phase_plan=candidate.phase_plan;self.schedule_plan=candidate.schedule_plan;
        self.schedule_identity=candidate.schedule_identity;self.spawn_summary=candidate.spawn_summary;
        self.query_engine=candidate.query_engine;
        self.config.sgc_plan_path=candidate.config.sgc_plan_path;
        self.config.world_path=candidate.config.world_path;
        self.config.world_manifest_path=candidate.config.world_manifest_path;
        self.config.execution_plan_version=candidate.config.execution_plan_version;
        self.phase_orch.update_schema_version(self.spawn_summary.schema_version.clone(),self.config.execution_plan_version);
        let systems=self.phase_plan.iter().flat_map(|(_,systems,_)|systems.iter().map(String::as_str)).collect::<Vec<_>>();
        self.determinism_guard.reconfigure_for_hot_swap(self.spawn_summary.schema_version.clone(),self.config.execution_plan_version,&systems);
        self.config.input_sync.required_peers.clear();
        self.engine_inputs.clear();self.input_synchroniser=build_runtime_input_synchroniser(&self.config.input_sync);
        self.last_playback_commands.clear();self.replay_golden_log=None;
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ActivationRequest {
    pub schema: String,
    pub candidate_digest: String,
    pub proof_digest: String,
    pub parent: CandidateParent,
    pub activation_tick: u64,
    /// Exact transport incarnations; a reconnect cannot inherit readiness.
    pub peers: BTreeMap<u64, u64>,
}
impl ActivationRequest {
    pub fn digest(&self) -> Result<String> {
        Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(self)?)))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all="snake_case", deny_unknown_fields)]
pub enum ActivationRecord {
    Prepared { request: ActivationRequest },
    Ready { peer_id:u64, generation:u64 },
    Decided { tick:u64, checkpoint: WorldSnapshot },
    Published { tick:u64, ruleset_epoch:u64, world_hash:String },
    Aborted { reason:String },
    Ended { reason:String },
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JournalRow {
    schema:String,
    sequence:u64,
    previous_hash:String,
    record:ActivationRecord,
    hash:String,
}
impl JournalRow {
    fn digest(&self)->Result<String> {
        Ok(format!("{:x}",Sha256::digest(serde_json::to_vec(&(&self.schema,self.sequence,&self.previous_hash,&self.record))?)))
    }
}
#[derive(Debug,Clone,Copy,PartialEq,Eq)]
pub enum RecoveryDisposition {
    /// No decision was durable; a fresh prepare is required before any activation.
    ParentUnchanged,
    /// A decision may have been observed. Never silently reopen the parent epoch.
    EndSession,
}
pub struct ActivationJournal {
    file:File,
    request:ActivationRequest,
    ready:BTreeSet<u64>,
    sequence:u64,
    tail:String,
    decided:bool,
    published:bool,
    decision_hash:Option<String>,
    publication:Option<(u64,String)>,
    terminal:bool,
}
impl ActivationJournal {
    pub fn create(path:&Path,request:ActivationRequest)->Result<Self> {
        anyhow::ensure!(request.schema=="xace.ruleset_activation.v1", "unsupported activation schema");
        anyhow::ensure!(request.activation_tick>request.parent.tick,"activation tick must be future");
        for digest in [&request.candidate_digest,&request.proof_digest] {
            anyhow::ensure!(digest.len()==64 && digest.bytes().all(|c| c.is_ascii_hexdigit()),"invalid activation digest");
        }
        anyhow::ensure!(request.peers.iter().all(|(p,g)|*p>0 && *g>0),"invalid peer generation");
        let file=OpenOptions::new().create_new(true).write(true).open(path)?;
        let mut journal=Self{file,request:request.clone(),ready:BTreeSet::new(),sequence:0,tail:String::new(),decided:false,published:false,decision_hash:None,publication:None,terminal:false};
        journal.append(ActivationRecord::Prepared{request})?;
        Ok(journal)
    }
    pub fn request(&self)->&ActivationRequest { &self.request }
    pub fn all_ready(&self)->bool { self.ready.len()==self.request.peers.len() }
    pub fn is_decided(&self)->bool { self.decided }
    pub fn is_published(&self)->bool { self.published }
    pub fn mark_ready(&mut self,peer_id:u64,generation:u64)->Result<()> {
        anyhow::ensure!(!self.terminal && !self.decided,"readiness window closed");
        anyhow::ensure!(self.request.peers.get(&peer_id)==Some(&generation),"stale readiness generation");
        if self.ready.contains(&peer_id) { return Ok(()); }
        self.append(ActivationRecord::Ready{peer_id,generation})?;
        self.ready.insert(peer_id); Ok(())
    }
    pub fn decide(&mut self,parent:&CandidateParent,checkpoint:WorldSnapshot)->Result<()> {
        anyhow::ensure!(!self.terminal,"activation is terminal");
        anyhow::ensure!(self.all_ready(),"activation peers are not ready");
        anyhow::ensure!(same_ruleset(parent,&self.request.parent),"activation parent epoch changed");
        anyhow::ensure!(parent.tick==self.request.activation_tick && checkpoint.tick==parent.tick,"activation tick mismatch");
        anyhow::ensure!(checkpoint.world_hash==parent.snapshot_hash && WorldHasher::compute(&checkpoint)==checkpoint.world_hash,"activation checkpoint mismatch");
        crate::snapshot_engine::validate_restorable_snapshot(&checkpoint).map_err(|e|anyhow::anyhow!("invalid activation checkpoint: {}",e))?;
        if self.decided {
            anyhow::ensure!(self.decision_hash.as_ref()==Some(&checkpoint.world_hash),"conflicting duplicate decision");
            return Ok(());
        }
        let decision_hash=checkpoint.world_hash.clone();
        self.append(ActivationRecord::Decided{tick:parent.tick,checkpoint})?;
        self.decision_hash=Some(decision_hash);self.decided=true;Ok(())
    }
    pub fn published(&mut self,tick:u64,ruleset_epoch:u64,world_hash:String)->Result<()> {
        anyhow::ensure!(self.decided && !self.terminal && tick==self.request.activation_tick,"no matching activation decision");
        if self.published {
            anyhow::ensure!(self.publication.as_ref()==Some(&(ruleset_epoch,world_hash)),"conflicting duplicate publication");
            return Ok(());
        }
        self.append(ActivationRecord::Published{tick,ruleset_epoch,world_hash:world_hash.clone()})?;
        self.publication=Some((ruleset_epoch,world_hash));self.published=true;Ok(())
    }
    pub fn abort(&mut self,reason:String)->Result<()> {
        anyhow::ensure!(!self.decided && !self.terminal,"cannot abort a durable activation decision");
        self.append(ActivationRecord::Aborted{reason})?;self.terminal=true;Ok(())
    }
    pub fn end(&mut self,reason:String)->Result<()> {
        anyhow::ensure!(!self.terminal,"activation already terminal");
        self.append(ActivationRecord::Ended{reason})?;self.terminal=true;Ok(())
    }
    fn append(&mut self,record:ActivationRecord)->Result<()> {
        let mut row=JournalRow{schema:"xace.activation_journal.v1".into(),sequence:self.sequence,previous_hash:self.tail.clone(),record,hash:String::new()};
        row.hash=row.digest()?;
        let mut bytes=serde_json::to_vec(&row)?;bytes.push(b'\n');
        // Memory acknowledges a decision only after the complete record is durable.
        if let Err(error)=self.file.write_all(&bytes).and_then(|_|self.file.sync_all()) {
            self.terminal=true; return Err(error.into());
        }
        self.sequence+=1;self.tail=row.hash;Ok(())
    }
    pub fn inspect_recovery(path:&Path)->Result<RecoveryDisposition> {
        let bytes=std::fs::read(path)?;
        anyhow::ensure!(bytes.last()==Some(&b'\n'),"torn activation journal; session must remain closed");
        let mut tail=String::new();let mut prepared:Option<ActivationRequest>=None;
        let mut ready=BTreeSet::new();let mut decided=false;let mut published=false;let mut terminal=false;
        for (sequence,line) in bytes.split(|b|*b==b'\n').filter(|l|!l.is_empty()).enumerate() {
            let row:JournalRow=serde_json::from_slice(line)?;
            anyhow::ensure!(row.schema=="xace.activation_journal.v1" && row.sequence==sequence as u64 && row.previous_hash==tail && row.digest()?==row.hash && !terminal,"corrupt activation journal");
            match &row.record {
                ActivationRecord::Prepared{request}=> {anyhow::ensure!(sequence==0,"duplicate prepare");prepared=Some(request.clone());},
                ActivationRecord::Ready{peer_id,generation}=> {anyhow::ensure!(!decided && prepared.as_ref().is_some_and(|r|r.peers.get(peer_id)==Some(generation)) && ready.insert(*peer_id),"invalid readiness record");},
                ActivationRecord::Decided{tick,checkpoint}=> {
                    let request=prepared.as_ref().ok_or_else(||anyhow::anyhow!("missing prepare"))?;
                    anyhow::ensure!(!decided && ready.len()==request.peers.len() && *tick==request.activation_tick && checkpoint.tick==*tick && WorldHasher::compute(checkpoint)==checkpoint.world_hash,"invalid decision record");decided=true;
                },
                ActivationRecord::Published{tick,..}=> {anyhow::ensure!(decided && !published && prepared.as_ref().is_some_and(|r|r.activation_tick==*tick),"invalid publication");published=true;},
                ActivationRecord::Aborted{..}=> {anyhow::ensure!(prepared.is_some() && !decided,"abort after decision");terminal=true;},
                ActivationRecord::Ended{..}=> {anyhow::ensure!(prepared.is_some(),"end without prepare");terminal=true;},
            }
            tail=row.hash;
        }
        anyhow::ensure!(prepared.is_some(),"empty activation journal");
        Ok(if decided {RecoveryDisposition::EndSession}else{RecoveryDisposition::ParentUnchanged})
    }
}
pub fn same_ruleset(a:&CandidateParent,b:&CandidateParent)->bool {
    a.schema==b.schema && a.session==b.session && a.cgs_hash==b.cgs_hash && a.plan_hash==b.plan_hash && a.world_digest==b.world_digest
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn control_rejects_paths_and_non_digest_identifiers() {
        assert!(serde_json::from_value::<RulesetControl>(json!({"operation":"preview","artifact_digest":"a".repeat(64),"directory":"C:/private"})).is_err());
        for invalid in ["../escape", "ABCDEF", "", &"G".repeat(64)] {assert!(require_digest(invalid).is_err());}
        assert!(require_digest(&"a".repeat(64)).is_ok());
    }
    fn fixture()->(PathBuf,ActivationRequest,CandidateParent,WorldSnapshot) {
        let path=std::env::temp_dir().join(format!("xace-activation-{}.jsonl",uuid::Uuid::new_v4()));
        let snapshot=SnapshotEngine::standard("0.1.0",1,42).take_snapshot(5,&EntityStore::new(),&ComponentTableStore::new()).unwrap();
        let parent=CandidateParent{schema:"xace.candidate_parent.v1".into(),session:json!({"ruleset_epoch":0}),cgs_hash:snapshot.cgs_hash.clone(),plan_hash:"a".repeat(64),world_digest:"b".repeat(64),tick:5,snapshot_hash:snapshot.world_hash.clone()};
        let mut captured=parent.clone();captured.tick=2;
        let request=ActivationRequest{schema:"xace.ruleset_activation.v1".into(),candidate_digest:"c".repeat(64),proof_digest:"d".repeat(64),parent:captured,activation_tick:5,peers:BTreeMap::from([(1,2)])};
        (path,request,parent,snapshot)
    }
    #[test]
    fn durable_decision_is_idempotent_and_cannot_be_aborted() {
        let (path,request,parent,snapshot)=fixture();let mut j=ActivationJournal::create(&path,request).unwrap();
        assert!(j.decide(&parent,snapshot.clone()).is_err());
        assert!(j.mark_ready(1,1).is_err());j.mark_ready(1,2).unwrap();j.mark_ready(1,2).unwrap();
        j.decide(&parent,snapshot.clone()).unwrap();let bytes=std::fs::read(&path).unwrap();
        j.decide(&parent,snapshot).unwrap();assert_eq!(bytes,std::fs::read(&path).unwrap());
        assert!(j.abort("late".into()).is_err());
        assert_eq!(ActivationJournal::inspect_recovery(&path).unwrap(),RecoveryDisposition::EndSession);
        j.published(5,1,"e".repeat(64)).unwrap();assert!(j.mark_ready(1,2).is_err());
        let bytes=std::fs::read(&path).unwrap();j.published(5,1,"e".repeat(64)).unwrap();
        assert_eq!(bytes,std::fs::read(&path).unwrap());
        assert!(j.published(5,2,"e".repeat(64)).is_err());
        assert_eq!(ActivationJournal::inspect_recovery(&path).unwrap(),RecoveryDisposition::EndSession);
    }
    #[test]
    fn precommit_abort_preserves_parent_and_stale_epoch_never_decides() {
        let (path,request,mut parent,snapshot)=fixture();let mut j=ActivationJournal::create(&path,request).unwrap();j.mark_ready(1,2).unwrap();
        parent.session=json!({"ruleset_epoch":1});assert!(j.decide(&parent,snapshot).is_err());
        j.abort("stale parent".into()).unwrap();
        assert_eq!(ActivationJournal::inspect_recovery(&path).unwrap(),RecoveryDisposition::ParentUnchanged);
    }
    #[test]
    fn recovery_refuses_torn_or_rewritten_history() {
        let (path,request,_,_)=fixture();let j=ActivationJournal::create(&path,request).unwrap();drop(j);
        let bytes=std::fs::read(&path).unwrap();std::fs::write(&path,&bytes[..bytes.len()-1]).unwrap();assert!(ActivationJournal::inspect_recovery(&path).is_err());
        let mut row:Value=serde_json::from_slice(&bytes).unwrap();row["record"]["prepared"]["request"]["activation_tick"]=json!(6);
        std::fs::write(&path,format!("{}\n",row)).unwrap();assert!(ActivationJournal::inspect_recovery(&path).is_err());
    }
}

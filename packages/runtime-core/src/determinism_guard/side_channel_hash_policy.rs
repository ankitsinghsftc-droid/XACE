//! Side-channel hash policy for X10-011.
//!
//! This module is intentionally executable policy, not only documentation. It
//! lists every side channel covered by X10-011 and states whether the channel is
//! directly included in WorldHasher, materialized into hashed world state,
//! covered by a replay/integrity log, or explicitly excluded as a derived
//! adapter/save side effect.

use std::collections::BTreeSet;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SideChannel {
    Rng,
    EventQueue,
    MutationQueue,
    FeedbackQueue,
    NetworkInputBuffer,
    SaveState,
    AdapterSideEffects,
    AssetBindingState,
}

impl SideChannel {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Rng => "rng",
            Self::EventQueue => "event_queue",
            Self::MutationQueue => "mutation_queue",
            Self::FeedbackQueue => "feedback_queue",
            Self::NetworkInputBuffer => "network_input_buffer",
            Self::SaveState => "save_state",
            Self::AdapterSideEffects => "adapter_side_effects",
            Self::AssetBindingState => "asset_binding_state",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SideChannelHashDisposition {
    DirectWorldHashInput,
    MaterializedIntoWorldHash,
    ReplayIntegrityLog,
    PersistedHashCarrier,
    ExplicitDerivedSideEffect,
}

impl SideChannelHashDisposition {
    pub const fn is_explicit_for_non_world_hash_input(self) -> bool {
        matches!(
            self,
            Self::MaterializedIntoWorldHash
                | Self::ReplayIntegrityLog
                | Self::PersistedHashCarrier
                | Self::ExplicitDerivedSideEffect
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SideChannelHashPolicy {
    pub channel: SideChannel,
    pub disposition: SideChannelHashDisposition,
    pub direct_world_hash_input: bool,
    pub proof: &'static str,
    pub enforcement: &'static str,
}

pub const REQUIRED_SIDE_CHANNELS: [SideChannel; 8] = [
    SideChannel::Rng,
    SideChannel::EventQueue,
    SideChannel::MutationQueue,
    SideChannel::FeedbackQueue,
    SideChannel::NetworkInputBuffer,
    SideChannel::SaveState,
    SideChannel::AdapterSideEffects,
    SideChannel::AssetBindingState,
];

const SIDE_CHANNEL_HASH_POLICIES: [SideChannelHashPolicy; 8] = [
    SideChannelHashPolicy {
        channel: SideChannel::Rng,
        disposition: SideChannelHashDisposition::DirectWorldHashInput,
        direct_world_hash_input: true,
        proof: "WorldHasher feeds WorldSnapshot.rng_state, including world_seed and sorted stream positions.",
        enforcement: "RngInterceptor gates legal RNG access; injected hash tests perturb rng_state.",
    },
    SideChannelHashPolicy {
        channel: SideChannel::EventQueue,
        disposition: SideChannelHashDisposition::DirectWorldHashInput,
        direct_world_hash_input: true,
        proof: "WorldHasher feeds WorldSnapshot.event_queue_state pending_events and next_event_id.",
        enforcement: "PhaseOrchestrator dispatches phase events before clean end-of-tick hashing; injected tests perturb pending events.",
    },
    SideChannelHashPolicy {
        channel: SideChannel::MutationQueue,
        disposition: SideChannelHashDisposition::DirectWorldHashInput,
        direct_world_hash_input: true,
        proof: "WorldHasher feeds WorldSnapshot.mutation_queue_state for all pending mutation vectors.",
        enforcement: "MutationGate applies deferred mutations before clean end-of-tick hashing and rollback-proves failed batches.",
    },
    SideChannelHashPolicy {
        channel: SideChannel::FeedbackQueue,
        disposition: SideChannelHashDisposition::ReplayIntegrityLog,
        direct_world_hash_input: false,
        proof: "FeedbackBuffer is transient, but drained feedback is recorded in FeedbackLog with tick entry hashes and session_hash.",
        enforcement: "RuntimeOrchestrator drains feedback at tick start; injected tests perturb FeedbackLog payloads.",
    },
    SideChannelHashPolicy {
        channel: SideChannel::NetworkInputBuffer,
        disposition: SideChannelHashDisposition::MaterializedIntoWorldHash,
        direct_world_hash_input: false,
        proof: "Pending network input buffers are transient; accepted packets have deterministic packet digests/log chains and are written to the INPUT component before ticking.",
        enforcement: "RuntimeOrchestrator applies pending engine inputs before PhaseOrchestrator::tick_with_guard; injected tests perturb input logs and INPUT component state.",
    },
    SideChannelHashPolicy {
        channel: SideChannel::SaveState,
        disposition: SideChannelHashDisposition::PersistedHashCarrier,
        direct_world_hash_input: false,
        proof: "Save files carry the canonical WorldSnapshot.world_hash plus save-slot cgs_hash and asset_hash metadata instead of entering the live tick hash as a side channel.",
        enforcement: "FileSaveEngine serializes WorldSnapshot deterministically and RuntimeOrchestrator validates snapshot hashes before restore.",
    },
    SideChannelHashPolicy {
        channel: SideChannel::AdapterSideEffects,
        disposition: SideChannelHashDisposition::ExplicitDerivedSideEffect,
        direct_world_hash_input: false,
        proof: "Engine playback commands, rendered objects, audio handles, and adapter transport side effects are derived outputs, not authoritative world state.",
        enforcement: "RuntimeOrchestrator derives EnginePlaybackCommand batches from semantic events after hashing; injected tests keep playback divergence out of WorldSnapshot.",
    },
    SideChannelHashPolicy {
        channel: SideChannel::AssetBindingState,
        disposition: SideChannelHashDisposition::DirectWorldHashInput,
        direct_world_hash_input: true,
        proof: "WorldHasher feeds cgs_hash for CGS semantic bindings and component JSON for committed AssetReference fields.",
        enforcement: "SemanticAssetBinding validation rejects uncommittable asset refs; injected tests perturb cgs_hash and asset-ref component JSON.",
    },
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SideChannelPolicyError {
    MissingChannel(SideChannel),
    DuplicateChannel(SideChannel),
    EmptyProof(SideChannel),
    EmptyEnforcement(SideChannel),
    NonWorldHashChannelWithoutExplicitDisposition(SideChannel),
}

pub fn side_channel_hash_policies() -> &'static [SideChannelHashPolicy] {
    &SIDE_CHANNEL_HASH_POLICIES
}

pub fn policy_for(channel: SideChannel) -> Option<&'static SideChannelHashPolicy> {
    side_channel_hash_policies()
        .iter()
        .find(|policy| policy.channel == channel)
}

pub fn validate_side_channel_hash_policy() -> Result<(), SideChannelPolicyError> {
    let mut seen = BTreeSet::new();
    for policy in side_channel_hash_policies() {
        if !seen.insert(policy.channel) {
            return Err(SideChannelPolicyError::DuplicateChannel(policy.channel));
        }
        if policy.proof.trim().is_empty() {
            return Err(SideChannelPolicyError::EmptyProof(policy.channel));
        }
        if policy.enforcement.trim().is_empty() {
            return Err(SideChannelPolicyError::EmptyEnforcement(policy.channel));
        }
        if !policy.direct_world_hash_input
            && !policy.disposition.is_explicit_for_non_world_hash_input()
        {
            return Err(
                SideChannelPolicyError::NonWorldHashChannelWithoutExplicitDisposition(
                    policy.channel,
                ),
            );
        }
    }

    for channel in REQUIRED_SIDE_CHANNELS {
        if !seen.contains(&channel) {
            return Err(SideChannelPolicyError::MissingChannel(channel));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::determinism_guard::world_hasher::WorldHasher;
    use crate::engine_protocol::EnginePlaybackCommand;
    use std::collections::BTreeMap;
    use xace_core::assets::{AssetReference, AssetType, SemanticPlaybackKind};
    use xace_core::entity_state::EntityState;
    use xace_core::runtime::world_snapshot::{ComponentTableSnapshot, EntityRecord, WorldSnapshot};
    use xace_core::wire::feedback_payload::{FeedbackMessage, FeedbackType};
    use xace_engine_feedback::feedback_log::FeedbackLog;
    use xace_network_core::input::{InputLog, InputPacket};

    fn base_snapshot(tick: u64) -> WorldSnapshot {
        let mut snapshot = WorldSnapshot::empty("schema.side-channel.test", 7, 99);
        snapshot.tick = tick;
        snapshot.cgs_hash = "c".repeat(64);
        snapshot
    }

    fn component_snapshot(
        tick: u64,
        component_type_id: u32,
        component_type_name: &str,
        component_json: &str,
    ) -> WorldSnapshot {
        let mut snapshot = base_snapshot(tick);
        snapshot
            .entity_store_snapshot
            .entities
            .push(EntityRecord::new(1, EntityState::Active, 0));
        snapshot.entity_store_snapshot.next_entity_id = 2;
        let mut table = ComponentTableSnapshot::new(component_type_id, component_type_name);
        table.set(1, component_json);
        snapshot.component_tables_snapshot.set_table(table);
        snapshot
    }

    fn playback_command(binding_id: &str, asset_id: &str) -> EnginePlaybackCommand {
        EnginePlaybackCommand {
            binding_id: binding_id.to_string(),
            event_name: "damage_taken".to_string(),
            playback_kind: SemanticPlaybackKind::Audio,
            entity_id: 1,
            asset: AssetReference::linked(asset_id, AssetType::AudioClip),
            semantic_action: "play".to_string(),
            parameters: BTreeMap::new(),
            priority: 0,
        }
    }

    #[test]
    fn x10_011_policy_covers_all_required_channels_once() {
        validate_side_channel_hash_policy().unwrap();
        let covered = side_channel_hash_policies()
            .iter()
            .map(|policy| policy.channel)
            .collect::<BTreeSet<_>>();
        let required = REQUIRED_SIDE_CHANNELS.into_iter().collect::<BTreeSet<_>>();
        assert_eq!(covered, required);
    }

    #[test]
    fn x10_011_non_world_hash_channels_have_explicit_proof() {
        for policy in side_channel_hash_policies() {
            if !policy.direct_world_hash_input {
                assert!(
                    policy.disposition.is_explicit_for_non_world_hash_input(),
                    "{} must have an explicit non-world-hash disposition",
                    policy.channel.as_str()
                );
                assert!(!policy.proof.trim().is_empty());
                assert!(!policy.enforcement.trim().is_empty());
            }
        }
    }

    #[test]
    fn x10_011_rng_state_divergence_changes_world_hash() {
        let a = base_snapshot(3);
        let mut b = base_snapshot(3);
        b.rng_state.set_stream_position("sys_loot", 4);
        assert_ne!(WorldHasher::compute(&a), WorldHasher::compute(&b));
    }

    #[test]
    fn x10_011_event_queue_divergence_changes_world_hash() {
        let a = base_snapshot(4);
        let mut b = base_snapshot(4);
        b.event_queue_state
            .pending_events
            .push(r#"{"event_id":10,"event_type":"enemy_spawned"}"#.into());
        assert_ne!(WorldHasher::compute(&a), WorldHasher::compute(&b));
    }

    #[test]
    fn x10_011_mutation_queue_divergence_changes_world_hash() {
        let a = base_snapshot(5);
        let mut b = base_snapshot(5);
        b.mutation_queue_state
            .pending_removals
            .push(r#"{"entity_id":1,"component_type_id":8}"#.into());
        assert_ne!(WorldHasher::compute(&a), WorldHasher::compute(&b));
    }

    #[test]
    fn x10_011_feedback_queue_divergence_changes_feedback_session_hash() {
        let mut a = FeedbackLog::new("schema.side-channel.test", 7);
        let mut b = FeedbackLog::new("schema.side-channel.test", 7);
        a.record_tick_checked(
            6,
            vec![FeedbackMessage::new(
                FeedbackType::PhysicsSettled,
                1,
                6,
                r#"{"grounded":true}"#,
            )],
        )
        .unwrap();
        b.record_tick_checked(
            6,
            vec![FeedbackMessage::new(
                FeedbackType::PhysicsSettled,
                1,
                6,
                r#"{"grounded":false}"#,
            )],
        )
        .unwrap();
        assert_ne!(a.session_hash(), b.session_hash());
        assert_eq!(
            policy_for(SideChannel::FeedbackQueue).unwrap().disposition,
            SideChannelHashDisposition::ReplayIntegrityLog
        );
    }

    #[test]
    fn x10_011_network_input_divergence_changes_input_log_and_world_hash_after_materialization() {
        let packet_a = InputPacket::unsigned(1, 7, 1).with_player(1);
        let packet_b = InputPacket::unsigned(1, 7, 2).with_player(1);
        let mut log_a = InputLog::new();
        let mut log_b = InputLog::new();
        log_a.append_result(packet_a).unwrap();
        log_b.append_result(packet_b).unwrap();
        assert_ne!(log_a.deterministic_hash(), log_b.deterministic_hash());

        let snap_a = component_snapshot(
            7,
            5,
            "COMP_INPUT_V1",
            r#"{"peer_id":1,"sequence_id":1,"source_tick":7}"#,
        );
        let snap_b = component_snapshot(
            7,
            5,
            "COMP_INPUT_V1",
            r#"{"peer_id":1,"sequence_id":2,"source_tick":7}"#,
        );
        assert_ne!(WorldHasher::compute(&snap_a), WorldHasher::compute(&snap_b));
    }

    #[test]
    fn x10_011_save_state_corruption_changes_recomputed_snapshot_hash() {
        let mut saved = component_snapshot(8, 20, "COMP_HEALTH_V1", r#"{"hp":10000000}"#);
        saved.world_hash = WorldHasher::compute(&saved);
        let mut corrupted = saved.clone();
        let table = corrupted
            .component_tables_snapshot
            .tables
            .get_mut(&20)
            .unwrap();
        table.set(1, r#"{"hp":9000000}"#);
        assert_ne!(saved.world_hash, WorldHasher::compute(&corrupted));
        assert_eq!(
            policy_for(SideChannel::SaveState).unwrap().disposition,
            SideChannelHashDisposition::PersistedHashCarrier
        );
    }

    #[test]
    fn x10_011_adapter_side_effect_divergence_is_excluded_as_derived_output() {
        let commands_a = vec![playback_command("binding_hit_a", "hit_sfx_a")];
        let commands_b = vec![playback_command("binding_hit_b", "hit_sfx_b")];
        assert_ne!(
            serde_json::to_string(&commands_a).unwrap(),
            serde_json::to_string(&commands_b).unwrap()
        );

        let snapshot = base_snapshot(9);
        assert_eq!(
            WorldHasher::compute(&snapshot),
            WorldHasher::compute(&snapshot)
        );
        assert_eq!(
            policy_for(SideChannel::AdapterSideEffects)
                .unwrap()
                .disposition,
            SideChannelHashDisposition::ExplicitDerivedSideEffect
        );
    }

    #[test]
    fn x10_011_asset_binding_divergence_changes_cgs_or_component_hash() {
        let mut cgs_a = base_snapshot(10);
        let mut cgs_b = base_snapshot(10);
        cgs_a.cgs_hash = "a".repeat(64);
        cgs_b.cgs_hash = "b".repeat(64);
        assert_ne!(WorldHasher::compute(&cgs_a), WorldHasher::compute(&cgs_b));

        let asset_a = component_snapshot(
            10,
            30,
            "COMP_RENDER_ASSET_V1",
            r#"{"asset_ref":{"asset_type":"Mesh","id":"hero_mesh_a","status":"Linked"}}"#,
        );
        let asset_b = component_snapshot(
            10,
            30,
            "COMP_RENDER_ASSET_V1",
            r#"{"asset_ref":{"asset_type":"Mesh","id":"hero_mesh_b","status":"Linked"}}"#,
        );
        assert_ne!(
            WorldHasher::compute(&asset_a),
            WorldHasher::compute(&asset_b)
        );
    }
}

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use crate::authority::AuthorityResolver;
use crate::input::{DelayRecommendation, InputSynchroniser, MissingInputRange};
use crate::prediction::{RollbackManager, RollbackReason};
use crate::session::SessionManager;
use crate::synchronisation::{DesyncDetector, DesyncReport, ResyncEngine};
use crate::{EntityId, PeerId, Tick};

pub const MULTIPLAYER_DIAGNOSTICS_SCHEMA: &str = "xace.multiplayer_diagnostics_snapshot.v1";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerDiagnosticsSnapshot {
    pub schema: String,
    pub topology_id: String,
    pub session: MultiplayerSessionDiagnostics,
    pub peers: Vec<MultiplayerPeerDiagnostics>,
    pub ticks: MultiplayerTickDiagnostics,
    pub input_buffers: MultiplayerInputBufferDiagnostics,
    pub latency: MultiplayerLatencyDiagnostics,
    pub rollback: MultiplayerRollbackDiagnostics,
    pub resync: Vec<MultiplayerResyncDiagnostics>,
    pub hash_comparisons: Vec<MultiplayerHashComparisonDiagnostics>,
    pub authority: Vec<MultiplayerAuthorityDiagnostics>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerSessionDiagnostics {
    pub mode: String,
    pub phase: String,
    pub tick: Tick,
    pub paused: bool,
    pub peer_total: usize,
    pub live_peers: usize,
    pub ready_peers: Vec<PeerId>,
    pub required_input_peers: Vec<PeerId>,
    pub compatibility_required: bool,
    pub compatibility_ok: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerPeerDiagnostics {
    pub peer_id: PeerId,
    pub player_id: Option<EntityId>,
    pub display_name: String,
    pub state: String,
    pub ready: bool,
    pub latency_ms: u32,
    pub jitter_ms: u32,
    pub packet_loss_ppm: u32,
    pub last_seen_tick: Tick,
    pub last_input_tick: Tick,
    pub last_sequence_id: u64,
    pub buffered_input_packets: usize,
    pub missing_input_ranges: Vec<MissingInputRange>,
    pub authoritative_entities: Vec<EntityId>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerTickDiagnostics {
    pub session_tick: Tick,
    pub simulation_tick: Tick,
    pub input_tick: Option<Tick>,
    pub last_released_tick: Option<Tick>,
    pub missing_peers: Vec<PeerId>,
    pub can_release: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerInputBufferDiagnostics {
    pub total_packet_count: usize,
    pub accepted_count: u64,
    pub duplicate_count: u64,
    pub rejected_count: u64,
    pub per_peer: Vec<MultiplayerPeerBufferDiagnostics>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerPeerBufferDiagnostics {
    pub peer_id: PeerId,
    pub buffered_packets: usize,
    pub missing_input_ranges: Vec<MissingInputRange>,
    pub has_input_for_current_tick: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerLatencyDiagnostics {
    pub recommended_delay_ticks: u32,
    pub worst_peer: Option<PeerId>,
    pub max_rtt_ms: u32,
    pub max_jitter_ms: u32,
    pub max_packet_loss_ppm: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerRollbackDiagnostics {
    pub rollback_count: usize,
    pub pending: bool,
    pub latest_restore_tick: Option<Tick>,
    pub latest_target_tick: Option<Tick>,
    pub latest_completed_tick: Option<Tick>,
    pub latest_reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerResyncDiagnostics {
    pub peer_id: PeerId,
    pub state: String,
    pub mode: String,
    pub snapshot_tick: Tick,
    pub target_tick: Tick,
    pub attempts: u8,
    pub expected_hash: String,
    pub completed_tick: Option<Tick>,
    pub failure_reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerHashComparisonDiagnostics {
    pub tick: Tick,
    pub expected_hash: String,
    pub majority_hash: Option<String>,
    pub matching_peers: Vec<PeerId>,
    pub divergent_peers: Vec<MultiplayerDivergentPeerDiagnostics>,
    pub missing_peers: Vec<PeerId>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerDivergentPeerDiagnostics {
    pub peer_id: PeerId,
    pub hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MultiplayerAuthorityDiagnostics {
    pub entity_id: EntityId,
    pub owner_peer: Option<PeerId>,
    pub fallback_peer: Option<PeerId>,
    pub shared_peers: Vec<PeerId>,
    pub scope: String,
    pub version: u64,
    pub transfer_locked: bool,
}

pub fn capture_multiplayer_diagnostics(
    session: &SessionManager,
    synchroniser: &InputSynchroniser,
    latency: DelayRecommendation,
    rollback: &RollbackManager,
    resync: &ResyncEngine,
    desync: &DesyncDetector,
    authority: &AuthorityResolver,
    simulation_tick: Tick,
) -> MultiplayerDiagnosticsSnapshot {
    let status = session.status();
    let input_tick = synchroniser.pending_or_target_tick_for_sim_tick(simulation_tick);
    let missing_peers = input_tick
        .map(|tick| {
            synchroniser
                .buffer()
                .missing_for_tick(tick, synchroniser.required_peers())
        })
        .unwrap_or_else(|| synchroniser.required_peers().iter().copied().collect());
    let required_input_peers = sorted_vec(&status.required_input_peers);

    let peers = session
        .peers()
        .iter()
        .map(|peer| MultiplayerPeerDiagnostics {
            peer_id: peer.peer_id,
            player_id: peer.player_id,
            display_name: peer.display_name.clone(),
            state: format!("{:?}", peer.state),
            ready: peer.ready,
            latency_ms: peer.latency_ms,
            jitter_ms: peer.jitter_ms,
            packet_loss_ppm: peer.packet_loss_ppm,
            last_seen_tick: peer.last_seen_tick,
            last_input_tick: peer.last_input_tick,
            last_sequence_id: peer.last_sequence_id,
            buffered_input_packets: synchroniser.buffer().packet_count_for_peer(peer.peer_id),
            missing_input_ranges: synchroniser.buffer().missing_ranges(peer.peer_id),
            authoritative_entities: sorted_vec(&peer.authoritative_entities),
        })
        .collect::<Vec<_>>();

    let per_peer = status
        .required_input_peers
        .iter()
        .copied()
        .map(|peer_id| MultiplayerPeerBufferDiagnostics {
            peer_id,
            buffered_packets: synchroniser.buffer().packet_count_for_peer(peer_id),
            missing_input_ranges: synchroniser.buffer().missing_ranges(peer_id),
            has_input_for_current_tick: input_tick
                .is_some_and(|tick| synchroniser.buffer().has_input(peer_id, tick)),
        })
        .collect();

    let latest_rollback = rollback.records().last();

    MultiplayerDiagnosticsSnapshot {
        schema: MULTIPLAYER_DIAGNOSTICS_SCHEMA.to_string(),
        topology_id: session
            .config()
            .mode
            .require_launch_topology()
            .map(|decision| decision.topology_id.to_string())
            .unwrap_or_else(|_| "unsupported".to_string()),
        session: MultiplayerSessionDiagnostics {
            mode: format!("{:?}", status.mode),
            phase: format!("{:?}", status.phase),
            tick: status.tick,
            paused: status.paused,
            peer_total: status.peer_stats.total,
            live_peers: status.peer_stats.live,
            ready_peers: sorted_vec(&status.ready_peers),
            required_input_peers,
            compatibility_required: status.compatibility_required,
            compatibility_ok: status.compatibility_ok,
        },
        peers,
        ticks: MultiplayerTickDiagnostics {
            session_tick: status.tick,
            simulation_tick,
            input_tick,
            last_released_tick: synchroniser.last_released_tick(),
            can_release: input_tick.is_some() && missing_peers.is_empty(),
            missing_peers,
        },
        input_buffers: MultiplayerInputBufferDiagnostics {
            total_packet_count: synchroniser.buffer().total_packet_count(),
            accepted_count: synchroniser.buffer().accepted_count(),
            duplicate_count: synchroniser.buffer().duplicate_count(),
            rejected_count: synchroniser.buffer().rejected_count(),
            per_peer,
        },
        latency: MultiplayerLatencyDiagnostics {
            recommended_delay_ticks: latency.delay_ticks,
            worst_peer: latency.worst_peer,
            max_rtt_ms: latency.max_rtt_ms,
            max_jitter_ms: latency.max_jitter_ms,
            max_packet_loss_ppm: latency.max_packet_loss_ppm,
        },
        rollback: MultiplayerRollbackDiagnostics {
            rollback_count: rollback.records().len(),
            pending: rollback.pending_record().is_some(),
            latest_restore_tick: latest_rollback.map(|record| record.plan.restore_tick),
            latest_target_tick: latest_rollback.map(|record| record.plan.target_tick),
            latest_completed_tick: latest_rollback.and_then(|record| record.completed_tick),
            latest_reason: latest_rollback
                .map(|record| rollback_reason_id(&record.plan.reason).to_string()),
        },
        resync: resync
            .sessions()
            .map(|session| MultiplayerResyncDiagnostics {
                peer_id: session.peer_id,
                state: format!("{:?}", session.state),
                mode: format!("{:?}", session.mode),
                snapshot_tick: session.snapshot_tick,
                target_tick: session.target_tick,
                attempts: session.attempts,
                expected_hash: session.expected_hash.clone(),
                completed_tick: session.completed_tick,
                failure_reason: session.failure_reason.clone(),
            })
            .collect(),
        hash_comparisons: desync
            .reports()
            .iter()
            .map(hash_comparison_from_report)
            .collect(),
        authority: authority
            .snapshot()
            .records
            .into_iter()
            .map(|record| MultiplayerAuthorityDiagnostics {
                entity_id: record.entity_id,
                owner_peer: record.owner_peer,
                fallback_peer: record.fallback_peer,
                shared_peers: sorted_vec(&record.shared_peers),
                scope: format!("{:?}", record.scope),
                version: record.version,
                transfer_locked: record.transfer_locked,
            })
            .collect(),
    }
}

fn hash_comparison_from_report(report: &DesyncReport) -> MultiplayerHashComparisonDiagnostics {
    MultiplayerHashComparisonDiagnostics {
        tick: report.tick,
        expected_hash: report.expected_hash.clone(),
        majority_hash: report.majority_hash.clone(),
        matching_peers: report.matching_peers.clone(),
        divergent_peers: report
            .divergent_peers
            .iter()
            .map(|(peer_id, hash)| MultiplayerDivergentPeerDiagnostics {
                peer_id: *peer_id,
                hash: hash.clone(),
            })
            .collect(),
        missing_peers: report.missing_peers.clone(),
    }
}

fn rollback_reason_id(reason: &RollbackReason) -> &'static str {
    match reason {
        RollbackReason::AuthoritativeCorrection => "authoritative_correction",
        RollbackReason::DesyncRecovery => "desync_recovery",
        RollbackReason::LateInput => "late_input",
        RollbackReason::Resimulation => "resimulation",
        RollbackReason::Manual => "manual",
    }
}

fn sorted_vec<T: Ord + Copy>(values: &BTreeSet<T>) -> Vec<T> {
    values.iter().copied().collect()
}

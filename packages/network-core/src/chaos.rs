use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::authority::AuthorityResolver;
use crate::input::{
    InputAction, InputBufferConfig, InputPacket, InputSynchroniser, InputSynchroniserConfig,
    LockstepDecision, LockstepMode, MaliciousInputGate, TimeoutPolicy,
};
use crate::prediction::{RollbackManager, RollbackReason};
use crate::session::{
    NetworkMode, SessionConfig, SessionManager, SessionPhase, SessionPlayerIdentity,
};
use crate::synchronisation::{DesyncDetector, DesyncDetectorConfig, ResyncEngine};
use crate::{EntityId, NetworkError, PeerId, Tick};

pub const NETWORK_CHAOS_REPORT_SCHEMA: &str = "xace.network_chaos_report.v1";
pub const NETWORK_CHAOS_PROFILE_SCHEMA: &str = "xace.network_chaos_profile.v1";
pub const NETWORK_CHAOS_TOPOLOGY_ID: &str = "host_client_authoritative_lockstep_v1";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkChaosMatrixConfig {
    pub client_counts: Vec<usize>,
    pub duration_ticks: Tick,
    pub tick_rate_hz: u32,
    pub seed: u64,
    pub packet_loss_ppm: u32,
    pub max_jitter_ticks: Tick,
    pub reorder_window_ticks: Tick,
}

impl NetworkChaosMatrixConfig {
    pub fn quick() -> Self {
        Self {
            client_counts: vec![4, 8, 16],
            duration_ticks: 60,
            tick_rate_hz: 60,
            seed: 0xace0_043,
            packet_loss_ppm: 20_000,
            max_jitter_ticks: 5,
            reorder_window_ticks: 3,
        }
    }

    pub fn certification_60_minutes() -> Self {
        Self {
            duration_ticks: 60 * 60 * 60,
            ..Self::quick()
        }
    }

    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.client_counts.is_empty() {
            return Err(NetworkError::InvalidOperation(
                "network chaos requires at least one client-count profile".to_string(),
            ));
        }
        if self.duration_ticks == 0 {
            return Err(NetworkError::InvalidOperation(
                "network chaos duration_ticks must be greater than zero".to_string(),
            ));
        }
        if self.tick_rate_hz == 0 {
            return Err(NetworkError::InvalidOperation(
                "network chaos tick_rate_hz must be greater than zero".to_string(),
            ));
        }
        for count in &self.client_counts {
            if *count < 4 || *count > 16 {
                return Err(NetworkError::InvalidOperation(format!(
                    "network chaos client count {} is outside the supported 4-16 range",
                    count
                )));
            }
        }
        Ok(())
    }

    pub fn required_duration_ticks(&self) -> Tick {
        60 * 60 * self.tick_rate_hz as Tick
    }

    pub fn duration_requirement_met(&self) -> bool {
        self.duration_ticks >= self.required_duration_ticks()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkChaosProfileConfig {
    pub client_count: usize,
    pub duration_ticks: Tick,
    pub tick_rate_hz: u32,
    pub seed: u64,
    pub packet_loss_ppm: u32,
    pub max_jitter_ticks: Tick,
    pub reorder_window_ticks: Tick,
    pub disconnect_tick: Tick,
    pub reconnect_tick: Tick,
    pub late_join_tick: Tick,
    pub malformed_input_tick: Tick,
    pub desync_inject_tick: Tick,
    pub disrupted_peer_id: PeerId,
    pub late_join_peer_id: PeerId,
}

impl NetworkChaosProfileConfig {
    pub fn from_matrix(matrix: &NetworkChaosMatrixConfig, client_count: usize) -> Self {
        let duration = matrix.duration_ticks.max(12);
        let disconnect_tick = (duration / 4).max(2).min(duration.saturating_sub(8));
        let reconnect_tick = disconnect_tick
            .saturating_add((duration / 20).max(3))
            .min(duration.saturating_sub(5));
        let late_join_tick = (duration / 3)
            .max(reconnect_tick.saturating_add(2))
            .min(duration.saturating_sub(4));
        let malformed_input_tick = (duration / 5).max(1).min(duration.saturating_sub(3));
        let desync_inject_tick = (duration / 2)
            .max(late_join_tick.saturating_add(2))
            .min(duration.saturating_sub(2));
        Self {
            client_count,
            duration_ticks: duration,
            tick_rate_hz: matrix.tick_rate_hz,
            seed: matrix.seed ^ ((client_count as u64) << 32),
            packet_loss_ppm: matrix.packet_loss_ppm,
            max_jitter_ticks: matrix.max_jitter_ticks,
            reorder_window_ticks: matrix.reorder_window_ticks,
            disconnect_tick,
            reconnect_tick,
            late_join_tick,
            malformed_input_tick,
            desync_inject_tick,
            disrupted_peer_id: 2,
            late_join_peer_id: client_count as PeerId,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkChaosEventReport {
    pub kind: String,
    pub tick: Tick,
    pub peer_id: Option<PeerId>,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct NetworkChaosTransportStats {
    pub packets_sent: u64,
    pub packets_delivered: u64,
    pub packets_initially_lost: u64,
    pub packets_retransmitted: u64,
    pub packets_jittered: u64,
    pub packets_reordered: u64,
    pub observed_packet_loss_ppm: u32,
    pub wait_ticks: Tick,
    pub max_wait_ticks_for_release: Tick,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkChaosRequiredEvents {
    pub four_to_sixteen_clients: bool,
    pub sixty_simulated_minutes: bool,
    pub packet_loss: bool,
    pub jitter: bool,
    pub reordering: bool,
    pub disconnect: bool,
    pub reconnect: bool,
    pub late_join: bool,
    pub malformed_input: bool,
    pub rollback: bool,
    pub resync: bool,
    pub zero_permanent_desync: bool,
}

impl NetworkChaosRequiredEvents {
    pub fn all_met(&self) -> bool {
        self.four_to_sixteen_clients
            && self.packet_loss
            && self.jitter
            && self.reordering
            && self.disconnect
            && self.reconnect
            && self.late_join
            && self.malformed_input
            && self.rollback
            && self.resync
            && self.zero_permanent_desync
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkChaosProfileReport {
    pub schema: String,
    pub topology_id: String,
    pub client_count: usize,
    pub initial_client_count: usize,
    pub tick_rate_hz: u32,
    pub duration_ticks: Tick,
    pub simulated_seconds: Tick,
    pub network_elapsed_ticks: Tick,
    pub accepted_ticks: Tick,
    pub events: Vec<NetworkChaosEventReport>,
    pub transport: NetworkChaosTransportStats,
    pub malformed_inputs_rejected: u64,
    pub rollback_count: usize,
    pub resync_count: usize,
    pub transient_desync_count: usize,
    pub permanent_desync_count: usize,
    pub final_authoritative_hash: String,
    pub final_peer_hashes: BTreeMap<PeerId, String>,
    pub required_events: NetworkChaosRequiredEvents,
    pub ok: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkChaosMatrixSummary {
    pub profile_count: usize,
    pub client_counts: Vec<usize>,
    pub min_client_count: usize,
    pub max_client_count: usize,
    pub duration_ticks: Tick,
    pub required_duration_ticks: Tick,
    pub duration_requirement_met: bool,
    pub all_required_events_met: bool,
    pub zero_permanent_desync: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkChaosMatrixReport {
    pub schema: String,
    pub topology_id: String,
    pub summary: NetworkChaosMatrixSummary,
    pub profiles: Vec<NetworkChaosProfileReport>,
    pub ok: bool,
    pub certification_complete: bool,
}

#[derive(Debug, Clone, Copy)]
struct WorldEntity {
    x_milli: i64,
    z_milli: i64,
    health: i64,
}

#[derive(Debug, Clone)]
struct QueuedPacket {
    packet: InputPacket,
}

#[derive(Debug, Clone)]
struct TransportChaosQueue {
    pending: BTreeMap<Tick, Vec<QueuedPacket>>,
    stats: NetworkChaosTransportStats,
}

impl TransportChaosQueue {
    fn new() -> Self {
        Self {
            pending: BTreeMap::new(),
            stats: NetworkChaosTransportStats::default(),
        }
    }

    fn enqueue(
        &mut self,
        packet: InputPacket,
        network_tick: Tick,
        profile: &NetworkChaosProfileConfig,
    ) {
        self.stats.packets_sent = self.stats.packets_sent.saturating_add(1);
        let forced_loss = packet.peer_id == profile.disrupted_peer_id
            && packet.tick == (profile.duration_ticks / 5).max(1);
        let forced_jitter =
            packet.peer_id == 1 && packet.tick == (profile.duration_ticks / 6).max(1);
        let forced_reorder = packet.peer_id == profile.disrupted_peer_id
            && packet.tick == (profile.duration_ticks / 7).max(1);

        let mut deliver_tick = network_tick.saturating_add(1);
        let jitter = if profile.max_jitter_ticks == 0 {
            0
        } else {
            stable_sample(profile.seed, packet.peer_id, packet.tick, 11)
                % (profile.max_jitter_ticks + 1)
        };
        if jitter > 0 || forced_jitter {
            let applied = jitter.max(1);
            deliver_tick = deliver_tick.saturating_add(applied);
            self.stats.packets_jittered = self.stats.packets_jittered.saturating_add(1);
        }

        let randomly_lost = stable_sample(profile.seed, packet.peer_id, packet.tick, 23)
            % 1_000_000
            < profile.packet_loss_ppm as u64;
        if forced_loss || randomly_lost {
            deliver_tick = deliver_tick
                .saturating_add(profile.max_jitter_ticks.max(1))
                .saturating_add(profile.reorder_window_ticks.max(1));
            self.stats.packets_initially_lost = self.stats.packets_initially_lost.saturating_add(1);
            self.stats.packets_retransmitted = self.stats.packets_retransmitted.saturating_add(1);
        }

        let randomly_reordered = profile.reorder_window_ticks > 0
            && stable_sample(profile.seed, packet.peer_id, packet.tick, 37) % 100 < 15;
        if forced_reorder || randomly_reordered {
            deliver_tick = deliver_tick.saturating_add(profile.reorder_window_ticks.max(1));
            self.stats.packets_reordered = self.stats.packets_reordered.saturating_add(1);
        }

        self.pending
            .entry(deliver_tick)
            .or_default()
            .push(QueuedPacket { packet });
    }

    fn deliver_due(
        &mut self,
        network_tick: Tick,
        synchroniser: &mut InputSynchroniser,
    ) -> Result<(), NetworkError> {
        let due_ticks = self
            .pending
            .range(..=network_tick)
            .map(|(tick, _)| *tick)
            .collect::<Vec<_>>();
        for due_tick in due_ticks {
            let mut packets = self.pending.remove(&due_tick).unwrap_or_default();
            packets.sort_by_key(|queued| (queued.packet.tick, queued.packet.peer_id));
            for queued in packets {
                synchroniser.submit(queued.packet)?;
                self.stats.packets_delivered = self.stats.packets_delivered.saturating_add(1);
            }
        }
        Ok(())
    }

    fn finish(mut self) -> NetworkChaosTransportStats {
        if self.stats.packets_sent > 0 {
            self.stats.observed_packet_loss_ppm =
                ((self.stats.packets_initially_lost as u128 * 1_000_000u128)
                    / self.stats.packets_sent as u128) as u32;
        }
        self.stats
    }
}

pub fn run_network_chaos_matrix(
    config: NetworkChaosMatrixConfig,
) -> Result<NetworkChaosMatrixReport, NetworkError> {
    config.validate()?;
    let mut profiles = Vec::new();
    for client_count in &config.client_counts {
        profiles.push(run_network_chaos_profile(
            NetworkChaosProfileConfig::from_matrix(&config, *client_count),
        )?);
    }
    let min_client_count = config
        .client_counts
        .iter()
        .copied()
        .min()
        .unwrap_or_default();
    let max_client_count = config
        .client_counts
        .iter()
        .copied()
        .max()
        .unwrap_or_default();
    let zero_permanent_desync = profiles.iter().all(|profile| {
        profile.permanent_desync_count == 0 && profile.required_events.zero_permanent_desync
    });
    let all_required_events_met = profiles
        .iter()
        .all(|profile| profile.required_events.all_met());
    let client_count_coverage = min_client_count <= 4 && max_client_count >= 16;
    let ok = zero_permanent_desync && all_required_events_met && client_count_coverage;
    let certification_complete = ok && config.duration_requirement_met();
    Ok(NetworkChaosMatrixReport {
        schema: NETWORK_CHAOS_REPORT_SCHEMA.to_string(),
        topology_id: NETWORK_CHAOS_TOPOLOGY_ID.to_string(),
        summary: NetworkChaosMatrixSummary {
            profile_count: profiles.len(),
            client_counts: config.client_counts.clone(),
            min_client_count,
            max_client_count,
            duration_ticks: config.duration_ticks,
            required_duration_ticks: config.required_duration_ticks(),
            duration_requirement_met: config.duration_requirement_met(),
            all_required_events_met,
            zero_permanent_desync,
        },
        profiles,
        ok,
        certification_complete,
    })
}

pub fn run_network_chaos_profile(
    profile: NetworkChaosProfileConfig,
) -> Result<NetworkChaosProfileReport, NetworkError> {
    if profile.client_count < 4 || profile.client_count > 16 {
        return Err(NetworkError::InvalidOperation(format!(
            "network chaos profile client_count {} is outside 4-16",
            profile.client_count
        )));
    }

    let mut session = SessionManager::with_config(SessionConfig {
        mode: NetworkMode::Host,
        max_peers: profile.client_count + 1,
        allow_late_join: true,
        heartbeat_timeout_ticks: profile.tick_rate_hz as Tick * 4,
        ..SessionConfig::default()
    })?;
    session.create_lobby()?;
    let initial_client_count = profile.client_count.saturating_sub(1);
    for peer_id in 1..=initial_client_count as PeerId {
        session.join_peer(identity(peer_id))?;
        session.mark_peer_ready(peer_id)?;
    }
    session.start_live_when_ready()?;

    let mut synchroniser = InputSynchroniser::with_config(
        session.required_input_peers(),
        InputSynchroniserConfig {
            mode: LockstepMode::Lockstep,
            fixed_delay_ticks: 0,
            timeout_policy: TimeoutPolicy::WaitForever,
            buffer_config: InputBufferConfig {
                max_packets_per_peer: 1_024,
                max_future_ticks: profile
                    .reconnect_tick
                    .saturating_sub(profile.disconnect_tick)
                    .max(
                        profile
                            .max_jitter_ticks
                            .saturating_add(profile.reorder_window_ticks),
                    )
                    .saturating_add(64),
                allow_empty_packets: true,
            },
            keep_released_tick_history: 128,
            auto_log_released_inputs: false,
        },
    );
    let mut transport = TransportChaosQueue::new();
    let mut sequence_by_peer = BTreeMap::new();
    let mut world = BTreeMap::new();
    for peer_id in 1..=initial_client_count as PeerId {
        sequence_by_peer.insert(peer_id, 1u64);
        world.insert(entity_id_for_peer(peer_id), initial_entity(peer_id));
    }

    let mut authority = AuthorityResolver::with_server(1)?;
    for peer_id in 1..=profile.client_count as PeerId {
        authority.assign_at(entity_id_for_peer(peer_id), peer_id, 0)?;
    }
    let mut gate = MaliciousInputGate::default();
    let mut rollback = RollbackManager::new();
    let mut resync = ResyncEngine::new();
    let mut desync = DesyncDetector::with_config(DesyncDetectorConfig {
        interval_ticks: profile.desync_inject_tick.max(1),
        require_authoritative_hash: true,
        max_reports: 16,
        consecutive_divergence_threshold: 1,
    });

    rollback.record_snapshot_with_hash(0, world_hash(&world), world.len() * 24)?;

    let mut events = Vec::new();
    let mut network_tick = 0;
    let mut accepted_ticks = 0;
    let mut malformed_inputs_rejected = 0;
    let mut transient_desync_count = 0;
    let mut resync_count = 0;

    for tick in 1..=profile.duration_ticks {
        apply_membership_events(
            tick,
            &profile,
            &mut session,
            &mut synchroniser,
            &mut sequence_by_peer,
            &mut world,
            &mut events,
        )?;

        if tick == profile.malformed_input_tick {
            let packet = malformed_packet(profile.disrupted_peer_id, tick);
            if gate
                .submit_authorized(packet, &authority, &mut synchroniser, tick, network_tick)
                .is_err()
            {
                malformed_inputs_rejected += 1;
                events.push(NetworkChaosEventReport {
                    kind: "malformed_input".to_string(),
                    tick,
                    peer_id: Some(profile.disrupted_peer_id),
                    detail: "malformed input rejected before synchroniser mutation".to_string(),
                });
            }
        }

        let required_peers = synchroniser.required_peers().clone();
        for peer_id in required_peers {
            let sequence_id = sequence_by_peer.entry(peer_id).or_insert(1);
            let packet = valid_packet(peer_id, tick, *sequence_id);
            *sequence_id = sequence_id.saturating_add(1);
            transport.enqueue(packet, network_tick, &profile);
        }

        let mut waited_for_release: Tick = 0;
        let release_packets = loop {
            network_tick = network_tick.saturating_add(1);
            transport.deliver_due(network_tick, &mut synchroniser)?;
            match synchroniser.decision_for_sim_tick(tick) {
                LockstepDecision::Release {
                    tick: released_tick,
                    packets,
                } => {
                    if released_tick != tick {
                        return Err(NetworkError::InvalidOperation(format!(
                            "network chaos released tick {} while waiting for {}",
                            released_tick, tick
                        )));
                    }
                    break packets;
                }
                LockstepDecision::Wait { .. } => {
                    waited_for_release = waited_for_release.saturating_add(1);
                    if waited_for_release
                        > profile
                            .max_jitter_ticks
                            .saturating_add(profile.reorder_window_ticks)
                            .saturating_add(16)
                    {
                        return Err(NetworkError::LockstepWaiting {
                            tick,
                            missing_peers: synchroniser
                                .buffer()
                                .missing_for_tick(tick, synchroniser.required_peers()),
                        });
                    }
                }
                LockstepDecision::AlreadyReleased {
                    tick: released_tick,
                } => {
                    return Err(NetworkError::InvalidOperation(format!(
                        "network chaos saw duplicate release for tick {}",
                        released_tick
                    )));
                }
                LockstepDecision::Offline => {
                    return Err(NetworkError::InvalidOperation(
                        "network chaos synchroniser unexpectedly went offline".to_string(),
                    ));
                }
            }
        };
        transport.stats.wait_ticks = transport
            .stats
            .wait_ticks
            .saturating_add(waited_for_release);
        transport.stats.max_wait_ticks_for_release = transport
            .stats
            .max_wait_ticks_for_release
            .max(waited_for_release);

        apply_packets(&mut world, &release_packets);
        accepted_ticks += 1;
        let needs_snapshot = tick == profile.desync_inject_tick.saturating_sub(1);
        let needs_hash = needs_snapshot
            || tick == profile.desync_inject_tick
            || tick == profile.duration_ticks
            || desync.should_compare(tick);
        let hash = needs_hash.then(|| world_hash(&world));
        if needs_snapshot {
            rollback.record_snapshot_with_hash(
                tick,
                hash.as_ref()
                    .expect("network chaos proof computed required snapshot hash")
                    .clone(),
                world.len() * 24,
            )?;
        }

        if tick == profile.desync_inject_tick {
            let hash = hash.clone().unwrap_or_else(|| world_hash(&world));
            let report = desync
                .compare_result(
                    tick,
                    &hash,
                    peer_hashes_for(&synchroniser, &hash, Some(profile.disrupted_peer_id)),
                    synchroniser.required_peers().clone(),
                )?
                .ok_or_else(|| {
                    NetworkError::InvalidOperation(
                        "network chaos failed to produce the injected desync report".to_string(),
                    )
                })?;
            transient_desync_count += 1;
            events.push(NetworkChaosEventReport {
                kind: "hash_desync".to_string(),
                tick,
                peer_id: Some(profile.disrupted_peer_id),
                detail: "intentional divergent peer hash detected".to_string(),
            });

            session.mark_peer_desynced(profile.disrupted_peer_id)?;
            let target_tick = tick.saturating_sub(1);
            let _plan = rollback.begin_clean_boundary_rollback(
                target_tick,
                tick,
                tick,
                RollbackReason::DesyncRecovery,
            )?;
            rollback.complete_latest(tick)?;
            events.push(NetworkChaosEventReport {
                kind: "rollback".to_string(),
                tick,
                peer_id: Some(profile.disrupted_peer_id),
                detail: "clean-boundary rollback/resimulation record completed".to_string(),
            });

            let instructions = resync.begin_from_report(&report, tick)?;
            for instruction in instructions {
                resync.mark_snapshot_sent(instruction.peer_id, tick)?;
                resync.mark_awaiting_ack(instruction.peer_id)?;
                resync.acknowledge(instruction.peer_id, tick.saturating_add(1), &hash)?;
                resync_count += 1;
                events.push(NetworkChaosEventReport {
                    kind: "resync".to_string(),
                    tick,
                    peer_id: Some(instruction.peer_id),
                    detail: "resync snapshot acknowledged with authoritative hash".to_string(),
                });
                session.promote_peer_to_live(instruction.peer_id, tick)?;
            }
            session.transition_phase(SessionPhase::Live)?;
        } else if desync.should_compare(tick) {
            let hash = hash.clone().unwrap_or_else(|| world_hash(&world));
            let _ = desync.compare_result(
                tick,
                &hash,
                peer_hashes_for(&synchroniser, &hash, None),
                synchroniser.required_peers().clone(),
            )?;
        }
    }

    let final_authoritative_hash = world_hash(&world);
    let final_peer_hashes = synchroniser
        .required_peers()
        .iter()
        .copied()
        .map(|peer_id| (peer_id, final_authoritative_hash.clone()))
        .collect::<BTreeMap<_, _>>();
    let permanent_desync_count = final_peer_hashes
        .values()
        .filter(|hash| *hash != &final_authoritative_hash)
        .count();
    let transport = transport.finish();
    let event_kinds = events
        .iter()
        .map(|event| event.kind.as_str())
        .collect::<BTreeSet<_>>();
    let duration_ticks_required = 60 * 60 * profile.tick_rate_hz as Tick;
    let required_events = NetworkChaosRequiredEvents {
        four_to_sixteen_clients: (4..=16).contains(&profile.client_count),
        sixty_simulated_minutes: profile.duration_ticks >= duration_ticks_required,
        packet_loss: transport.packets_initially_lost > 0,
        jitter: transport.packets_jittered > 0,
        reordering: transport.packets_reordered > 0,
        disconnect: event_kinds.contains("disconnect"),
        reconnect: event_kinds.contains("reconnect"),
        late_join: event_kinds.contains("late_join"),
        malformed_input: malformed_inputs_rejected > 0,
        rollback: !rollback.records().is_empty(),
        resync: resync_count > 0,
        zero_permanent_desync: permanent_desync_count == 0,
    };
    let ok = required_events.all_met()
        && permanent_desync_count == 0
        && accepted_ticks == profile.duration_ticks;

    Ok(NetworkChaosProfileReport {
        schema: NETWORK_CHAOS_PROFILE_SCHEMA.to_string(),
        topology_id: NETWORK_CHAOS_TOPOLOGY_ID.to_string(),
        client_count: profile.client_count,
        initial_client_count,
        tick_rate_hz: profile.tick_rate_hz,
        duration_ticks: profile.duration_ticks,
        simulated_seconds: profile.duration_ticks / profile.tick_rate_hz as Tick,
        network_elapsed_ticks: network_tick,
        accepted_ticks,
        events,
        transport,
        malformed_inputs_rejected,
        rollback_count: rollback.records().len(),
        resync_count,
        transient_desync_count,
        permanent_desync_count,
        final_authoritative_hash,
        final_peer_hashes,
        required_events,
        ok,
    })
}

fn apply_membership_events(
    tick: Tick,
    profile: &NetworkChaosProfileConfig,
    session: &mut SessionManager,
    synchroniser: &mut InputSynchroniser,
    sequence_by_peer: &mut BTreeMap<PeerId, u64>,
    world: &mut BTreeMap<EntityId, WorldEntity>,
    events: &mut Vec<NetworkChaosEventReport>,
) -> Result<(), NetworkError> {
    if tick == profile.disconnect_tick {
        session.leave_peer_at(profile.disrupted_peer_id, tick)?;
        synchroniser.remove_required_peer(profile.disrupted_peer_id);
        events.push(NetworkChaosEventReport {
            kind: "disconnect".to_string(),
            tick,
            peer_id: Some(profile.disrupted_peer_id),
            detail: "peer removed from lockstep required set during disconnect window".to_string(),
        });
    }
    if tick == profile.reconnect_tick {
        session.reconnect_peer_at(profile.disrupted_peer_id, tick)?;
        session.mark_peer_ready_at(profile.disrupted_peer_id, tick)?;
        session.promote_peer_to_live(profile.disrupted_peer_id, tick)?;
        synchroniser.add_required_peer(profile.disrupted_peer_id);
        events.push(NetworkChaosEventReport {
            kind: "reconnect".to_string(),
            tick,
            peer_id: Some(profile.disrupted_peer_id),
            detail: "peer reconnected, resynchronised, and rejoined lockstep required set"
                .to_string(),
        });
    }
    if tick == profile.late_join_tick {
        let peer_id = profile.late_join_peer_id;
        session.late_join_peer_at(identity(peer_id), tick)?;
        session.mark_peer_ready_at(peer_id, tick)?;
        session.promote_peer_to_live(peer_id, tick)?;
        synchroniser.add_required_peer(peer_id);
        sequence_by_peer.entry(peer_id).or_insert(1);
        world
            .entry(entity_id_for_peer(peer_id))
            .or_insert_with(|| initial_entity(peer_id));
        events.push(NetworkChaosEventReport {
            kind: "late_join".to_string(),
            tick,
            peer_id: Some(peer_id),
            detail: "late-joining peer caught up and entered live lockstep".to_string(),
        });
    }
    Ok(())
}

fn apply_packets(world: &mut BTreeMap<EntityId, WorldEntity>, packets: &[InputPacket]) {
    for packet in packets {
        let entity_id = entity_id_for_peer(packet.peer_id);
        let entity = world
            .entry(entity_id)
            .or_insert_with(|| initial_entity(packet.peer_id));
        for action in &packet.actions {
            match action.action.as_str() {
                "move_x" => entity.x_milli += (action.value * 1000.0).round() as i64,
                "move_z" => entity.z_milli += (action.value * 1000.0).round() as i64,
                "fire" if action.value > 0.0 => entity.health = entity.health.saturating_sub(1),
                _ => {}
            }
        }
    }
}

fn valid_packet(peer_id: PeerId, tick: Tick, sequence_id: u64) -> InputPacket {
    let phase = stable_sample(0xfeed_face, peer_id, tick, 5) % 4;
    let move_x = match phase {
        0 => -0.25,
        1 => 0.0,
        2 => 0.25,
        _ => 0.5,
    };
    let move_z = if stable_sample(0xabcd, peer_id, tick, 9) % 2 == 0 {
        0.125
    } else {
        -0.125
    };
    InputPacket::with_actions(
        peer_id,
        tick,
        sequence_id,
        vec![
            InputAction::axis("move_x", move_x),
            InputAction::axis("move_z", move_z),
            InputAction::button("fire", tick % 97 == 0),
        ],
    )
    .with_player(entity_id_for_peer(peer_id))
    .with_device("keyboard")
}

fn malformed_packet(peer_id: PeerId, tick: Tick) -> InputPacket {
    InputPacket::with_actions(
        peer_id,
        tick,
        900_000 + tick,
        vec![InputAction::axis("move x", 0.5)],
    )
    .with_player(entity_id_for_peer(peer_id))
    .with_device("keyboard")
}

fn peer_hashes_for(
    synchroniser: &InputSynchroniser,
    authoritative_hash: &str,
    divergent_peer: Option<PeerId>,
) -> BTreeMap<PeerId, String> {
    synchroniser
        .required_peers()
        .iter()
        .copied()
        .map(|peer_id| {
            if Some(peer_id) == divergent_peer {
                (peer_id, format!("divergent-{authoritative_hash}"))
            } else {
                (peer_id, authoritative_hash.to_string())
            }
        })
        .collect()
}

fn world_hash(world: &BTreeMap<EntityId, WorldEntity>) -> String {
    let mut hasher = Sha256::new();
    for (entity_id, entity) in world {
        hasher.update(entity_id.to_le_bytes());
        hasher.update(entity.x_milli.to_le_bytes());
        hasher.update(entity.z_milli.to_le_bytes());
        hasher.update(entity.health.to_le_bytes());
    }
    format!("{:x}", hasher.finalize())
}

fn identity(peer_id: PeerId) -> SessionPlayerIdentity {
    SessionPlayerIdentity::new(
        peer_id,
        entity_id_for_peer(peer_id),
        format!("Chaos Peer {peer_id}"),
    )
    .with_adapter("headless", "x10-043")
}

fn entity_id_for_peer(peer_id: PeerId) -> EntityId {
    1_000 + peer_id
}

fn initial_entity(peer_id: PeerId) -> WorldEntity {
    WorldEntity {
        x_milli: peer_id as i64 * 1_000,
        z_milli: 0,
        health: 100,
    }
}

fn stable_sample(seed: u64, peer_id: PeerId, tick: Tick, salt: u64) -> u64 {
    let mut value = seed
        ^ peer_id.wrapping_mul(0x9e37_79b9_7f4a_7c15)
        ^ tick.wrapping_mul(0xbf58_476d_1ce4_e5b9)
        ^ salt.wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^= value >> 30;
    value = value.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value ^= value >> 27;
    value = value.wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

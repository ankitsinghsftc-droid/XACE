use std::collections::BTreeSet;

use xace_network_core::replication::{
    EntityRelevance, InterestZone, InterestZoneManager, InterestZoneShape, PeerRelevanceContext,
    RelevanceFilter, RelevanceFilterConfig, RelevanceReason, ReplicationConfig, ReplicationManager,
    ReplicationPriority, ReplicationReason,
};

fn set(values: impl IntoIterator<Item = u64>) -> BTreeSet<u64> {
    values.into_iter().collect()
}

#[test]
fn interest_zones_index_entities_and_peers_bidirectionally() {
    let mut zone = InterestZone::new("graveyard")
        .with_shape(InterestZoneShape::Circle {
            x: 0.0,
            z: 0.0,
            radius: 10.0,
        })
        .with_priority(5);
    zone.add_entity(100).unwrap();
    zone.add_entity(101).unwrap();
    zone.add_peer(1).unwrap();

    let mut zones = InterestZoneManager::new();
    let diff = zones.upsert_zone_result(zone).unwrap();
    assert_eq!(diff.added_entities, set([100, 101]));
    assert_eq!(diff.added_peers, set([1]));
    assert!(zones.zone("graveyard").unwrap().contains_position(3.0, 4.0));
    assert_eq!(zones.relevant_entities_for_peer(1), set([100, 101]));
    assert_eq!(zones.relevant_peers_for_entity(100), set([1]));

    zones.remove_entity_from_zone("graveyard", 100).unwrap();
    assert_eq!(zones.relevant_entities_for_peer(1), set([101]));
    assert!(zones.zone_ids_for_entity(100).is_empty());
}

#[test]
fn interest_zone_upsert_reports_membership_changes() {
    let mut zones = InterestZoneManager::new();
    let mut first = InterestZone::new("street");
    first.add_entity(10).unwrap();
    first.add_peer(1).unwrap();
    zones.upsert_zone_result(first).unwrap();

    let mut second = InterestZone::new("street");
    second.add_entity(11).unwrap();
    second.add_peer(1).unwrap();
    second.add_peer(2).unwrap();

    let diff = zones.upsert_zone_result(second).unwrap();
    assert_eq!(diff.added_entities, set([11]));
    assert_eq!(diff.removed_entities, set([10]));
    assert_eq!(diff.added_peers, set([2]));
    assert!(diff.removed_peers.is_empty());
}

#[test]
fn relevance_filter_ranks_explicit_controlled_and_always_relevant_entities() {
    let mut filter = RelevanceFilter::new(RelevanceFilterConfig {
        max_entities_per_peer: 3,
        ..RelevanceFilterConfig::default()
    });
    filter.set_always_relevant(30, true);
    filter.add_explicit_interest(7, 20).unwrap();

    let context = PeerRelevanceContext {
        peer_id: 7,
        x: 0.0,
        z: 0.0,
        team_id: Some(2),
        controlled_entity: Some(10),
    };
    let entities = [
        EntityRelevance {
            entity_id: 10,
            x: 100.0,
            z: 0.0,
            radius: 1.0,
            team_id: 1,
        },
        EntityRelevance {
            entity_id: 20,
            x: 80.0,
            z: 0.0,
            radius: 1.0,
            team_id: 1,
        },
        EntityRelevance {
            entity_id: 30,
            x: 500.0,
            z: 0.0,
            radius: 1.0,
            team_id: 3,
        },
        EntityRelevance {
            entity_id: 40,
            x: 4.0,
            z: 0.0,
            radius: 10.0,
            team_id: 2,
        },
    ];

    let decisions = filter.rank_entities(&context, &entities).unwrap();
    assert_eq!(decisions.len(), 3);
    assert_eq!(decisions[0].entity_id, 30);
    assert_eq!(decisions[0].reason, RelevanceReason::AlwaysRelevant);
    assert!(decisions.iter().any(|decision| decision.entity_id == 10));
    assert!(decisions.iter().any(|decision| decision.entity_id == 20));
}

#[test]
fn replication_manager_schedules_visibility_dirty_refresh_and_ack() {
    let mut replication = ReplicationManager::with_config(ReplicationConfig {
        min_delta_interval_ticks: 2,
        full_snapshot_interval_ticks: 10,
        max_entities_per_peer_per_tick: 8,
        forget_invisible_after_ticks: 5,
    });

    let update = replication.update_interest_at(1, set([10, 20]), 5).unwrap();
    assert_eq!(update.entered, set([10, 20]));

    let initial = replication.work_items_for_peer(1, 5).unwrap();
    assert_eq!(initial.len(), 2);
    assert!(initial
        .iter()
        .all(|item| item.reason == ReplicationReason::BecameVisible));

    replication.mark_sent_result(1, 10, 5).unwrap();
    replication.mark_sent_result(1, 20, 5).unwrap();
    replication.acknowledge(1, 10, 5, 6).unwrap();
    replication
        .mark_entity_changed_with_priority(10, 6, ReplicationPriority::High)
        .unwrap();
    assert!(replication.work_items_for_peer(1, 6).unwrap().is_empty());

    let dirty = replication.work_items_for_peer(1, 7).unwrap();
    assert_eq!(dirty[0].entity_id, 10);
    assert_eq!(dirty[0].reason, ReplicationReason::Dirty);
    assert_eq!(dirty[0].priority, ReplicationPriority::High);

    replication.mark_sent_result(1, 10, 7).unwrap();
    let refresh = replication.work_items_for_peer(1, 17).unwrap();
    assert!(refresh
        .iter()
        .any(|item| item.entity_id == 10 && item.reason == ReplicationReason::FullRefresh));
}

#[test]
fn replication_manager_prunes_invisible_peer_entity_state() {
    let mut replication = ReplicationManager::with_config(ReplicationConfig {
        forget_invisible_after_ticks: 3,
        ..ReplicationConfig::default()
    });

    replication.update_interest_at(1, set([99]), 1).unwrap();
    replication.mark_sent_result(1, 99, 2).unwrap();
    replication
        .update_interest_at(1, BTreeSet::new(), 4)
        .unwrap();

    assert_eq!(replication.last_sent_tick(1, 99), Some(2));
    assert_eq!(replication.prune_invisible(6), 0);
    assert_eq!(replication.prune_invisible(7), 1);
    assert_eq!(replication.last_sent_tick(1, 99), None);
}

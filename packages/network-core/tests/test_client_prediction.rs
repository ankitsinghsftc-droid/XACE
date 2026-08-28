use xace_network_core::prediction::{
    ClientPredictor, PredictionBuffer, PredictionConfig, PredictionInput, ReconciliationConfig,
    ReconciliationEngine, ReconciliationMode, RollbackConfig, RollbackManager, RollbackReason,
    Vec3,
};

#[test]
fn client_predictor_uses_fixed_tick_dt() {
    let predictor = ClientPredictor::new(60);
    let predicted = predictor.predict_linear(42, 10, (0.0, 0.0, 0.0), (60.0, 0.0, 0.0));
    assert_eq!(predicted.entity_id, 42);
    assert!((predicted.x - 1.0).abs() < 0.0001);
}

#[test]
fn client_predictor_clamps_horizon_and_velocity() {
    let predictor = ClientPredictor::with_config(PredictionConfig {
        tick_rate_hz: 10,
        max_velocity_units_per_second: 5.0,
        max_acceleration_units_per_second_sq: 10.0,
        max_prediction_ticks: 3,
    })
    .unwrap();

    let state = predictor
        .predict(PredictionInput {
            entity_id: 7,
            base_tick: 10,
            target_tick: 13,
            position: Vec3::ZERO,
            velocity: Vec3::new(100.0, 0.0, 0.0),
            acceleration: Vec3::new(100.0, 0.0, 0.0),
        })
        .unwrap();
    assert!(state.velocity.magnitude() <= 5.0001);
    assert_eq!(state.prediction_ticks, 3);

    let too_far = predictor.predict(PredictionInput {
        entity_id: 7,
        base_tick: 10,
        target_tick: 14,
        position: Vec3::ZERO,
        velocity: Vec3::ZERO,
        acceleration: Vec3::ZERO,
    });
    assert!(too_far.is_err());
}

#[test]
fn reconciliation_snaps_when_error_exceeds_threshold() {
    let engine = ReconciliationEngine::new(0.5);
    let plan = engine.plan(
        1,
        20,
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        ReconciliationMode::Interpolate,
    );
    assert_eq!(plan.mode, ReconciliationMode::Snap);
    assert!(plan.needs_correction);
}

#[test]
fn reconciliation_interpolates_small_errors_over_blend_ticks() {
    let engine = ReconciliationEngine::with_config(ReconciliationConfig {
        snap_threshold: 10.0,
        correction_epsilon: 0.001,
        max_interpolation_ticks: 4,
        smooth_correction_ticks: 8,
    })
    .unwrap();
    let plan = engine.plan(
        1,
        20,
        (0.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
        ReconciliationMode::Interpolate,
    );
    assert_eq!(plan.mode, ReconciliationMode::Interpolate);
    assert_eq!(plan.blend_ticks, 4);
    assert_eq!(plan.corrected_position_at_step(2).x, 2.0);
}

#[test]
fn prediction_buffer_keeps_bounded_window() {
    let mut buffer = PredictionBuffer::new(2);
    buffer.insert(1, "a");
    buffer.insert(2, "b");
    buffer.insert(3, "c");
    assert_eq!(buffer.ticks(), vec![2, 3]);
    assert_eq!(buffer.get(3), Some(&"c"));
}

#[test]
fn prediction_buffer_supports_floor_ceil_and_drain_after() {
    let mut buffer = PredictionBuffer::new(8);
    for tick in 10..=14 {
        buffer.insert(tick, tick * 10);
    }

    assert_eq!(buffer.floor(12).map(|(tick, _)| tick), Some(12));
    assert_eq!(buffer.ceil(11).map(|(tick, _)| tick), Some(11));
    assert_eq!(buffer.range(11, 13).len(), 3);
    let drained = buffer.drain_after(12);
    assert_eq!(
        drained
            .into_iter()
            .map(|(tick, _)| tick)
            .collect::<Vec<_>>(),
        vec![13, 14]
    );
    assert_eq!(buffer.ticks(), vec![10, 11, 12]);
}

#[test]
fn rollback_manager_plans_from_nearest_snapshot() {
    let mut manager = RollbackManager::new();
    manager.record_snapshot(10);
    manager.record_snapshot(20);
    let plan = manager.plan(24, 27).unwrap();
    assert_eq!(plan.restore_tick, 20);
    assert_eq!(plan.replay_ticks, vec![21, 22, 23, 24, 25, 26, 27]);
}

#[test]
fn rollback_manager_clean_boundary_plan_replays_restore_tick_from_pre_tick_snapshot() {
    let mut manager = RollbackManager::new();
    manager.record_snapshot(0);
    manager.record_snapshot(2);

    let plan = manager
        .begin_clean_boundary_rollback(0, 3, 3, RollbackReason::AuthoritativeCorrection)
        .unwrap();

    assert_eq!(plan.restore_tick, 0);
    assert_eq!(plan.replay_ticks, vec![0, 1, 2]);
    assert_eq!(plan.live_tick, 3);
    manager.complete_latest(3).unwrap();
    assert_eq!(manager.records()[0].completed_tick, Some(3));
}

#[test]
fn rollback_manager_ignores_unstable_snapshots_and_tracks_records() {
    let mut manager = RollbackManager::with_config(RollbackConfig {
        max_replay_ticks: 20,
        snapshot_retention_ticks: 100,
        max_snapshots: 8,
    });
    manager
        .record_snapshot_with_hash(10, "hash10", 128)
        .unwrap();
    manager
        .record_snapshot_with_hash(20, "hash20", 256)
        .unwrap();
    manager.mark_snapshot_unstable(20).unwrap();

    let plan = manager
        .begin_rollback(24, 25, 30, RollbackReason::AuthoritativeCorrection)
        .unwrap();
    assert_eq!(plan.restore_tick, 10);
    assert_eq!(plan.snapshot_hash.as_deref(), Some("hash10"));
    assert!(manager.pending_record().is_some());

    manager.complete_latest(31).unwrap();
    assert_eq!(manager.records()[0].completed_tick, Some(31));
}

#[test]
fn rollback_manager_rejects_overlong_replay() {
    let mut manager = RollbackManager::with_config(RollbackConfig {
        max_replay_ticks: 5,
        snapshot_retention_ticks: 100,
        max_snapshots: 8,
    });
    manager.record_snapshot(10);
    assert!(manager.plan(12, 20).is_err());
}

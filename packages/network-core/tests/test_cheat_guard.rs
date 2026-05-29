use std::collections::{BTreeMap, BTreeSet};

use xace_network_core::authority::{
    ActionLimit, AuthorityResolver, CheatGuard, CheatGuardConfig, CheatViolationKind,
    TransformSample,
};
use xace_network_core::input::{InputAction, InputPacket};

#[test]
fn cheat_guard_rejects_non_monotonic_sequences() {
    let mut guard = CheatGuard::new(CheatGuardConfig::default());
    guard
        .validate_input(&InputPacket::unsigned(1, 0, 10))
        .unwrap();
    assert!(guard
        .validate_input(&InputPacket::unsigned(1, 1, 10))
        .is_err());
}

#[test]
fn cheat_guard_rejects_out_of_range_action_values() {
    let mut guard = CheatGuard::new(CheatGuardConfig::default());
    let packet = InputPacket::with_actions(1, 0, 1, vec![InputAction::axis("move_x", 4.0)]);
    assert!(guard.validate_input(&packet).is_err());
}

#[test]
fn cheat_guard_rejects_impossible_transform_delta() {
    let mut guard = CheatGuard::new(CheatGuardConfig::default());
    guard
        .validate_transform_delta(
            9,
            TransformSample {
                tick: 1,
                x: 0.0,
                y: 0.0,
                z: 0.0,
            },
        )
        .unwrap();
    assert!(guard
        .validate_transform_delta(
            9,
            TransformSample {
                tick: 2,
                x: 100.0,
                y: 0.0,
                z: 0.0,
            }
        )
        .is_err());
}

#[test]
fn cheat_guard_enforces_signature_device_player_and_future_tick_policy() {
    let mut allowed_devices = BTreeSet::new();
    allowed_devices.insert("keyboard".to_string());
    let mut guard = CheatGuard::new(CheatGuardConfig {
        require_signature: true,
        signature_secret: Some(b"secret".to_vec()),
        require_player_id: true,
        allowed_devices,
        max_future_ticks: 2,
        ..CheatGuardConfig::default()
    });

    let unsigned = InputPacket::with_actions(1, 10, 1, vec![InputAction::button("jump", true)])
        .with_device("keyboard")
        .with_player(99);
    assert!(guard.validate_input_at(&unsigned, Some(10)).is_err());

    let signed = unsigned.clone().signed(b"secret");
    guard.validate_input_at(&signed, Some(10)).unwrap();

    let future = InputPacket::with_actions(1, 20, 2, vec![InputAction::button("jump", true)])
        .with_device("keyboard")
        .with_player(99)
        .signed(b"secret");
    assert!(guard.validate_input_at(&future, Some(10)).is_err());
    assert!(guard
        .violation_log()
        .any(|violation| violation.kind == CheatViolationKind::FutureTick));
}

#[test]
fn cheat_guard_enforces_per_action_repeat_limits() {
    let mut limits = BTreeMap::new();
    limits.insert(
        "fire".to_string(),
        ActionLimit {
            max_abs_value: 1.0,
            max_abs_secondary_value: 1.0,
            max_per_tick: 1,
        },
    );
    let mut guard = CheatGuard::new(CheatGuardConfig {
        per_action_limits: limits,
        ..CheatGuardConfig::default()
    });

    guard
        .validate_input(&InputPacket::with_actions(
            1,
            5,
            1,
            vec![InputAction::button("fire", true)],
        ))
        .unwrap();
    assert!(guard
        .validate_input(&InputPacket::with_actions(
            1,
            5,
            2,
            vec![InputAction::button("fire", true)],
        ))
        .is_err());
}

#[test]
fn cheat_guard_checks_target_entity_authority() {
    let mut resolver = AuthorityResolver::with_server(1).unwrap();
    resolver.assign_at(50, 2, 0).unwrap();

    let mut action = InputAction::button("use", true);
    action.target_entity = Some(50);
    let packet = InputPacket::with_actions(3, 1, 1, vec![action]);

    let mut guard = CheatGuard::new(CheatGuardConfig::default());
    assert!(guard
        .validate_authorized_input(&packet, &resolver, Some(1))
        .is_err());
    assert_eq!(
        guard.violation_log().next().unwrap().kind,
        CheatViolationKind::AuthorityDenied
    );
}

#[test]
fn cheat_guard_records_transform_reports_and_prunes_action_counts() {
    let mut guard = CheatGuard::new(CheatGuardConfig {
        max_transform_units_per_tick: 10.0,
        ..CheatGuardConfig::default()
    });
    guard
        .validate_transform_delta_result(
            7,
            TransformSample {
                tick: 1,
                x: 0.0,
                y: 0.0,
                z: 0.0,
            },
        )
        .unwrap();
    let report = guard
        .validate_transform_delta_result(
            7,
            TransformSample {
                tick: 2,
                x: 3.0,
                y: 4.0,
                z: 0.0,
            },
        )
        .unwrap()
        .unwrap();
    assert_eq!(report.distance, 5.0);

    guard
        .validate_input(&InputPacket::with_actions(
            1,
            1,
            1,
            vec![InputAction::button("jump", true)],
        ))
        .unwrap();
    assert_eq!(guard.prune_before_tick(2), 1);
}

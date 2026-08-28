use xace_network_core::chaos::{run_network_chaos_matrix, NetworkChaosMatrixConfig};

#[test]
fn x10_043_network_chaos_quick_profiles_cover_required_events_without_permanent_desync() {
    let report = run_network_chaos_matrix(NetworkChaosMatrixConfig::quick()).unwrap();

    assert!(report.ok);
    assert!(!report.certification_complete);
    assert_eq!(report.summary.client_counts, vec![4, 8, 16]);
    assert!(report.summary.all_required_events_met);
    assert!(report.summary.zero_permanent_desync);
    for profile in &report.profiles {
        assert_eq!(profile.permanent_desync_count, 0);
        assert!(profile.required_events.packet_loss);
        assert!(profile.required_events.jitter);
        assert!(profile.required_events.reordering);
        assert!(profile.required_events.disconnect);
        assert!(profile.required_events.reconnect);
        assert!(profile.required_events.late_join);
        assert!(profile.required_events.malformed_input);
        assert!(profile.required_events.rollback);
        assert!(profile.required_events.resync);
        assert_eq!(profile.accepted_ticks, profile.duration_ticks);
    }
}
